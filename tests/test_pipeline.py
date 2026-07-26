from pathlib import Path
import json
import threading
from zipfile import ZipFile

import pytest
from ebooklib import epub

from contextweaver.adapters import BibliographyPassthroughAdapter, MockTranslationAdapter, TranslationAdapter
from contextweaver.audit import _epub_resource_integrity
from contextweaver.academic import export_academic_pdf
from contextweaver.exporters import _reader_typography, render_markdown
from contextweaver.models import ContextPacket, Section, SectionTitleRecord, Segment, TranslationRecord
from contextweaver.pipeline import (
    build_context,
    export_project,
    export_agent_batch,
    export_selected,
    import_document,
    import_section_title_draft,
    import_translation_draft,
    init_project,
    plan_agent_campaign,
    project_status,
    segment_document,
    translate_project,
    translate_section_titles,
    validate_project,
)
from contextweaver.storage import read_jsonl


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "book.md"
    path.write_text(
        "# One\n\nFirst paragraph.\n\nSecond paragraph.\n\n# Two\n\nLast paragraph.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def project(tmp_path: Path, source: Path) -> Path:
    root = tmp_path / "translation"
    init_project(root, "Test Book", "en", "zh-CN")
    import_document(root, source)
    return root


def test_segmentation_is_stable(project: Path) -> None:
    first = segment_document(project, unit_size=2)
    second = segment_document(project, unit_size=2)
    assert [item.id for item in first[1]] == [item.id for item in second[1]]
    assert len(first[0]) == 2
    assert len(first[1]) == 3
    assert len(first[2]) == 2


def test_context_contains_neighbors(project: Path) -> None:
    _, _, units = segment_document(project, unit_size=1)
    packet = build_context(project, units[1])
    assert packet.previous_text == "First paragraph."
    assert packet.next_text == "Last paragraph."


def test_bibliography_passthrough_preserves_source_entry(project: Path) -> None:
    _, segments, units = segment_document(project, unit_size=1)
    packet = build_context(project, units[0])
    assert BibliographyPassthroughAdapter().translate(packet) == [segments[0].raw]


def test_resume_validate_and_export(project: Path) -> None:
    segment_document(project, unit_size=2)
    assert translate_project(project, MockTranslationAdapter()) == (3, 0)
    assert translate_project(project, MockTranslationAdapter()) == (0, 3)
    assert validate_project(project) == []
    translated, bilingual = export_project(project)
    assert "[MOCK] First paragraph." in translated.read_text(encoding="utf-8")
    assert 'translator: "ContextWeaver Mock Adapter' in translated.read_text(encoding="utf-8")
    assert "> First paragraph." in bilingual.read_text(encoding="utf-8")
    assert project_status(project).translation_count == 3
    metadata = json.loads((project / "state" / "export_metadata.json").read_text())
    assert metadata["translator"].startswith("ContextWeaver Mock Adapter")
    assert "authoritative" in metadata["fidelity_note"]


def test_bounded_translation_units_resume_without_duplicates(project: Path) -> None:
    segment_document(project, unit_size=1)
    assert translate_project(project, MockTranslationAdapter(), max_units=1) == (1, 0)
    assert project_status(project).translation_count == 1
    assert translate_project(project, MockTranslationAdapter(), max_units=1) == (1, 1)
    assert project_status(project).translation_count == 2
    assert translate_project(project, MockTranslationAdapter()) == (1, 2)
    assert project_status(project).translation_count == 3


def test_bounded_translation_rejects_invalid_limit(project: Path) -> None:
    segment_document(project)
    with pytest.raises(ValueError, match="max_units"):
        translate_project(project, MockTranslationAdapter(), max_units=0)


def test_parallel_translation_writes_complete_units_without_duplicates(project: Path) -> None:
    segment_document(project, unit_size=1)

    class ParallelAdapter(TranslationAdapter):
        name = "parallel-test"
        model = "test"

        def __init__(self) -> None:
            self.barrier = threading.Barrier(2)

        def translate(self, packet: ContextPacket) -> list[str]:
            self.barrier.wait(timeout=1)
            return [f"parallel:{item.text}" for item in packet.source_segments]

    assert translate_project(project, ParallelAdapter(), max_units=2, workers=2) == (2, 0)
    records = read_jsonl(project / "state" / "translations.jsonl", TranslationRecord)
    assert len(records) == 2
    assert len({item.segment_id for item in records}) == 2


def test_parallel_translation_rejects_invalid_worker_count(project: Path) -> None:
    segment_document(project)
    with pytest.raises(ValueError, match="workers"):
        translate_project(project, MockTranslationAdapter(), workers=0)


def test_agent_batch_exports_pending_context_and_resumes_safely(
    project: Path, tmp_path: Path
) -> None:
    sections, segments, _ = segment_document(project, unit_size=1)
    assert translate_project(project, MockTranslationAdapter(), max_units=1) == (1, 0)
    output = tmp_path / "agent-work.jsonl"
    assert export_agent_batch(project, output, {sections[0].id}, max_units=1) == (1, 1)
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["schema_version"] == 1
    assert row["section"] == {"id": sections[0].id, "title": "One"}
    assert [item["id"] for item in row["context_packet"]["source_segments"]] == [segments[1].id]
    assert row["context_packet"]["previous_text"] == "First paragraph."
    assert row["response_contract"]["fields"] == ["segment_id", "translated_text"]
    with pytest.raises(FileExistsError, match="--force"):
        export_agent_batch(project, output)
    assert export_agent_batch(project, output, {sections[1].id}, force=True) == (1, 1)


def test_agent_batch_rejects_invalid_scope_and_limit(project: Path, tmp_path: Path) -> None:
    segment_document(project)
    with pytest.raises(ValueError, match="max_units"):
        export_agent_batch(project, tmp_path / "batch.jsonl", max_units=0)
    with pytest.raises(ValueError, match="Unknown section"):
        export_agent_batch(project, tmp_path / "batch.jsonl", {"sec_missing"})


def test_agent_batch_adapts_to_source_budget_and_section_boundary(
    project: Path, tmp_path: Path
) -> None:
    sections, segments, _ = segment_document(project, unit_size=1)
    output = tmp_path / "adaptive.jsonl"
    assert export_agent_batch(project, output, target_source_chars=25) == (1, 1)
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["section"]["id"] == sections[0].id
    assert row["context_packet"]["source_segments"][0]["id"] == segments[0].id
    strategy = json.loads((project / "state" / "batch_strategy.json").read_text())
    assert strategy["mode"] == "adaptive"
    assert strategy["target_source_chars"] == 25
    assert strategy["last_package"]["segment_count"] == 1


def test_agent_batch_explicit_limit_overrides_adaptive_section_stop(
    project: Path, tmp_path: Path
) -> None:
    segment_document(project, unit_size=1)
    assert export_agent_batch(project, tmp_path / "explicit.jsonl", max_units=3) == (3, 3)
    assert not (project / "state" / "batch_strategy.json").exists()


def test_agent_batch_production_defaults_are_chapter_sized(project: Path, tmp_path: Path) -> None:
    segment_document(project, unit_size=1)
    export_agent_batch(project, tmp_path / "default.jsonl")
    strategy = json.loads((project / "state" / "batch_strategy.json").read_text())
    assert strategy["target_source_chars"] == 400_000
    assert strategy["nominal_serialized_input_chars"] == 800_000
    assert strategy["usable_context_tokens"] == 340_000
    assert strategy["last_package"]["estimated_workload_tokens"] <= 340_000
    assert strategy["max_units"] == 500
    assert strategy["stop_at_section_boundary"] is True
    assert strategy["model_context"]["context_window_tokens"] == 400_000
    assert strategy["model_context"]["budget_source"] == "derived"


def test_agent_campaign_plans_all_pending_and_refreshes_progress(
    project: Path,
) -> None:
    segment_document(project, unit_size=1)
    campaign = plan_agent_campaign(project, checkpoint_source_chars=100, checkpoint_max_units=2)
    assert campaign["scope"] == "all-pending"
    assert campaign["target_segments"] == 3
    assert campaign["checkpoint_count"] == 2
    assert campaign["checkpoints"][0]["section_id"] != campaign["checkpoints"][1]["section_id"]
    translate_project(project, MockTranslationAdapter(), max_units=1)
    updated = plan_agent_campaign(project)
    assert updated["campaign_id"] == campaign["campaign_id"]
    assert updated["completed_segments"] == 1
    assert updated["checkpoints"][0]["status"] == "in_progress"


def test_agent_campaign_supports_explicit_bounded_scope(project: Path) -> None:
    segment_document(project, unit_size=1)
    campaign = plan_agent_campaign(project, max_segments=2)
    assert campaign["scope"] == "bounded-pending"
    assert campaign["target_segments"] == 2


def test_optional_epub_exports_are_readable(project: Path) -> None:
    segment_document(project, unit_size=2)
    translate_project(project, MockTranslationAdapter())
    paths = export_selected(project, {"epub"}, {"translated", "bilingual"})
    assert [path.name for path in paths] == ["translated.epub", "bilingual.epub"]
    for path in paths:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        assert book.get_metadata("DC", "title")
        assert len(book.spine) == 4
        assert book.get_metadata("DC", "creator")[0][0].startswith("ContextWeaver Mock Adapter")


def test_academic_pdf_reflows_tables_and_requires_complete_translation(project: Path) -> None:
    segment_document(project, unit_size=1)
    with pytest.raises(RuntimeError, match="complete translation"):
        export_academic_pdf(project)
    translate_project(project, MockTranslationAdapter())
    output = export_academic_pdf(project)
    assert output.name == "translated.pdf"
    assert output.read_bytes().startswith(b"%PDF")


def test_epub_export_copies_images_and_rewrites_internal_chapter_links(tmp_path: Path) -> None:
    source = tmp_path / "source.epub"
    book = epub.EpubBook()
    book.set_identifier("resources")
    book.set_title("Resource book")
    image = epub.EpubItem(
        uid="diagram",
        file_name="images/diagram.png",
        media_type="image/png",
        content=b"\x89PNG\r\n\x1a\nresource-test",
    )
    one = epub.EpubHtml(title="One", file_name="one.xhtml")
    one.content = '<h1>One</h1><p>See <a href="two.xhtml">chapter two</a>.</p><img src="images/diagram.png" alt="Diagram"/>'
    two = epub.EpubHtml(title="Two", file_name="two.xhtml")
    two.content = "<h1>Two</h1><p>Second chapter text.</p>"
    for item in (image, one, two, epub.EpubNcx(), epub.EpubNav()):
        book.add_item(item)
    book.spine = [one, two]
    epub.write_epub(str(source), book)

    root = tmp_path / "project"
    init_project(root, "Resources", "en", "zh-CN")
    import_document(root, source)
    segment_document(root)
    translate_project(root, MockTranslationAdapter())
    output = export_selected(root, {"epub"}, {"translated"})[0]

    integrity = _epub_resource_integrity(output)
    assert integrity["image_references"] == 1
    assert integrity["image_resources"] >= 1
    assert integrity["broken_local_references"] == 0
    with ZipFile(output) as archive:
        content = archive.read("EPUB/section-0000.xhtml").decode("utf-8")
    assert "images/0000-diagram.png" in content
    assert "section-0001.xhtml" in content


def test_reader_export_uses_chinese_outer_quotes_and_css_heading_heuristic() -> None:
    assert _reader_typography("她说：‘你好。’") == "她说：“你好。”"
    assert _reader_typography("她说：“所谓‘进步’，并不简单。”") == "她说：“所谓‘进步’，并不简单。”"
    assert _reader_typography("所谓「好」的技术") == "所谓“好”的技术"
    assert _reader_typography("她说：「所谓『进步』，并不简单。」") == "她说：“所谓‘进步’，并不简单。”"
    assert _reader_typography("O”Reilly and Economists” Hour") == "O'Reilly and Economists' Hour"
    assert _reader_typography("O’Reilly and Economists’ Hour") == "O'Reilly and Economists' Hour"
    assert _reader_typography("她说：“中文”之后仍是中文。") == "她说：“中文”之后仍是中文。"
    section = Section("section", "document", "Chapter", 1, 0)
    segment = Segment(
        "segment", "document", "section", 0, "Radio Days", raw="Radio Days"
    )
    output = render_markdown([section], [segment], {segment.id: "广播时代"}, "translated")
    assert "## 广播时代" in output
    explicit = Segment(
        "explicit", "document", "section", 1, "Illegible", kind="subheading", raw="Illegible"
    )
    output = render_markdown([section], [explicit], {explicit.id: "不可识读"}, "translated")
    assert "## 不可识读" in output


def test_validation_reports_missing_translation(project: Path) -> None:
    segment_document(project)
    issues = validate_project(project)
    assert len(issues) == 3
    assert {issue.kind for issue in issues} == {"missing_translation"}


class BrokenAdapter(TranslationAdapter):
    name = "broken"
    model = "broken"

    def translate(self, packet: ContextPacket) -> list[str]:
        return []


class CapturingAdapter(TranslationAdapter):
    name = "capture"
    model = "test"

    def __init__(self) -> None:
        self.segment_ids: list[str] = []

    def translate(self, packet: ContextPacket) -> list[str]:
        self.segment_ids.extend(item.id for item in packet.source_segments)
        return [f"translated:{item.text}" for item in packet.source_segments]


def test_adapter_cardinality_is_enforced(project: Path) -> None:
    segment_document(project)
    with pytest.raises(RuntimeError, match="outputs"):
        translate_project(project, BrokenAdapter())


def test_image_only_segments_bypass_model_and_preserve_markdown(tmp_path: Path) -> None:
    source = tmp_path / "images.md"
    source.write_text(
        "# One\n\n![Cover](images/cover.jpg)\n\nCopyright notice.\n", encoding="utf-8"
    )
    root = tmp_path / "translation"
    init_project(root, "Images", "en", "zh-CN")
    import_document(root, source)
    _, segments, _ = segment_document(root, unit_size=3)
    adapter = CapturingAdapter()
    assert translate_project(root, adapter) == (2, 0)
    assert adapter.segment_ids == [segments[1].id]
    records = read_jsonl(root / "state" / "translations.jsonl", TranslationRecord)
    image_record = next(item for item in records if item.segment_id == segments[0].id)
    assert image_record.translated_text == "![Cover](images/cover.jpg)"
    assert image_record.adapter == "structural-passthrough"
    assert image_record.model == "deterministic-v1"
    assert validate_project(root) == []
    export_project(root)
    metadata = json.loads((root / "state" / "export_metadata.json").read_text(encoding="utf-8"))
    assert "structural-passthrough" not in metadata["translator"]


def test_agent_draft_import_and_scoped_export(project: Path, tmp_path: Path) -> None:
    sections, segments, _ = segment_document(project, unit_size=1)
    draft = tmp_path / "draft.jsonl"
    draft.write_text(
        "\n".join(
            json.dumps({"segment_id": item.id, "translated_text": f"译文 {item.text}"})
            for item in segments[:2]
        )
        + "\n",
        encoding="utf-8",
    )
    assert import_translation_draft(project, draft, "codex-agent", "GPT-5.6", "pilot") == 2
    issues = validate_project(project, {sections[0].id})
    assert issues == []
    paths = export_selected(
        project,
        {"epub"},
        {"translated"},
        "Codex Agent using GPT-5.6",
        "Human translator (reference only)",
        {sections[0].id},
    )
    assert paths[0].parent.name == sections[0].id


def test_section_title_draft_is_append_only_and_used_by_exports(
    project: Path, tmp_path: Path
) -> None:
    sections, _, _ = segment_document(project, unit_size=1)
    translate_project(project, MockTranslationAdapter())
    draft = tmp_path / "titles.jsonl"
    draft.write_text(
        "\n".join(
            json.dumps({"section_id": item.id, "translated_title": f"章节 {index}"})
            for index, item in enumerate(sections, 1)
        )
        + "\n",
        encoding="utf-8",
    )
    assert import_section_title_draft(project, draft, "codex-agent", "GPT-5", "initial") == 2
    translated, bilingual = export_project(project)
    assert "# 章节 1" in translated.read_text(encoding="utf-8")
    assert "# One / 章节 1" in bilingual.read_text(encoding="utf-8")
    metadata = json.loads((project / "state" / "export_metadata.json").read_text(encoding="utf-8"))
    assert metadata["title"] == "章节 1"

    revision = tmp_path / "title-revision.jsonl"
    revision.write_text(
        json.dumps({"section_id": sections[0].id, "translated_title": "第一章"}) + "\n",
        encoding="utf-8",
    )
    assert import_section_title_draft(project, revision, "codex-agent", "GPT-5", "style-fix") == 1
    records = read_jsonl(project / "state" / "section_titles.jsonl", SectionTitleRecord)
    assert records[-1].revision == 2
    assert records[-1].supersedes == records[0].id


def test_online_section_title_translation_resumes_and_refreshes(project: Path) -> None:
    segment_document(project)
    assert translate_section_titles(project, MockTranslationAdapter()) == (2, 0)
    assert translate_section_titles(project, MockTranslationAdapter()) == (0, 2)
    assert translate_section_titles(
        project, CapturingAdapter(), reason="style-refresh", refresh=True
    ) == (2, 0)
    records = read_jsonl(project / "state" / "section_titles.jsonl", SectionTitleRecord)
    assert [item.revision for item in records] == [1, 1, 2, 2]
    assert records[2].supersedes == records[0].id
