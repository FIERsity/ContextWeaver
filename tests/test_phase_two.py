import json
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from ebooklib import epub

from contextweaver.adapters import MockTranslationAdapter, OpenAITranslationAdapter, TranslationAdapter
from contextweaver.knowledge import propose_knowledge
from contextweaver.models import ContextPacket, Segment, TranslationRecord
from contextweaver.pipeline import (
    active_translations,
    import_document,
    init_project,
    segment_document,
    translate_project,
    validate_project,
)
from contextweaver.storage import read_jsonl


def _project(tmp_path: Path, source: Path) -> Path:
    root = tmp_path / "project"
    init_project(root, "Phase Two", "en", "zh-CN")
    import_document(root, source)
    return root


def test_structured_markdown_preserves_blocks_and_inline_markup(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Title\n\n- One **bold** item\n- Two items\n\n> A *quoted* line.[^1]\n\n[^1]: Note.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    assert [item.kind for item in segments] == ["list", "blockquote", "footnote"]
    assert "**bold**" in segments[0].raw
    assert "footnote_ref" in segments[1].format_signature


def test_docx_import(tmp_path: Path) -> None:
    source = tmp_path / "book.docx"
    document = Document()
    document.add_heading("DOCX Chapter", 1)
    paragraph = document.add_paragraph()
    paragraph.add_run("Important").bold = True
    paragraph.add_run(" text")
    document.save(source)
    root = _project(tmp_path, source)
    doc = json.loads((root / "state" / "source_document.json").read_text())
    assert doc["source_format"] == "docx"
    _, segments, _ = segment_document(root)
    assert segments[0].raw == "**Important** text"


def test_epub_import(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    book = epub.EpubBook()
    book.set_identifier("test")
    book.set_title("EPUB Book")
    chapter = epub.EpubHtml(title="One", file_name="one.xhtml")
    chapter.content = "<h1>One</h1><p>Hello EPUB.</p>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]
    epub.write_epub(str(source), book)
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    assert segments[0].text == "Hello EPUB."


def test_knowledge_proposals_have_evidence_and_preserve_edits(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nMara met Iven.\n\nMara warned Iven.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    segment_document(root)
    glossary, entities = propose_knowledge(root)
    assert {item.term for item in glossary} == {"Iven", "Mara"}
    assert all(len(item.evidence_segment_ids) == 2 for item in entities)
    path = root / "state" / "glossary.csv"
    path.write_text(path.read_text().replace("Mara,,", "Mara,玛拉,"), encoding="utf-8")
    glossary, _ = propose_knowledge(root)
    assert next(item for item in glossary if item.term == "Mara").preferred_translation == "玛拉"


def test_selective_retranslation_creates_revision_chain(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nAlpha.\n\nBeta.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    translate_project(root, MockTranslationAdapter())
    translate_project(root, MockTranslationAdapter(), segment_ids={segments[0].id}, reason="terminology-fix")
    records = read_jsonl(root / "state" / "translations.jsonl", TranslationRecord)
    chain = [item for item in records if item.segment_id == segments[0].id]
    assert [item.revision for item in chain] == [1, 2]
    assert chain[1].supersedes == chain[0].id
    assert active_translations(records)[segments[0].id].reason == "terminology-fix"
    assert validate_project(root) == []


class RetryError(Exception):
    status_code = 429
    response = SimpleNamespace(headers={"retry-after": "0.25"})


class FakeResponses:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        if self.calls == 1:
            raise RetryError("rate limited")
        return SimpleNamespace(output_text=json.dumps({"translations": ["译文"]}))


def test_openai_adapter_retries_rate_limits_without_network() -> None:
    responses = FakeResponses()
    sleeps: list[float] = []
    adapter = OpenAITranslationAdapter(client=SimpleNamespace(responses=responses), max_retries=2, sleep=sleeps.append)
    segment = Segment("seg", "doc", "sec", 0, "Source", raw="**Source**", format_signature=["strong"])
    packet = ContextPacket("unit", [segment], None, None, None, [], [])
    assert adapter.translate(packet) == ["译文"]
    assert responses.calls == 2
    assert sleeps == [0.25]


class FailSecondUnit(TranslationAdapter):
    name = "intermittent"
    model = "test"

    def __init__(self) -> None:
        self.calls = 0

    def translate(self, packet: ContextPacket) -> list[str]:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("temporary outage")
        return [f"done:{item.text}" for item in packet.source_segments]


def test_pipeline_resumes_after_adapter_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nAlpha.\n\nBeta.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    segment_document(root, unit_size=1)
    import pytest

    with pytest.raises(RuntimeError, match="outage"):
        translate_project(root, FailSecondUnit())
    assert translate_project(root, MockTranslationAdapter()) == (1, 1)
    assert validate_project(root) == []


def test_format_and_terminology_validation(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nUse **ContextWeaver** now.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    segment_document(root)
    translate_project(root, MockTranslationAdapter())
    glossary = root / "state" / "glossary.csv"
    glossary.write_text("term,preferred_translation,allowed_variants,note,source_segment_id,confidence,evidence_segment_ids,status\nContextWeaver,上下文编织器,,,1,,approved\n", encoding="utf-8")
    issues = validate_project(root)
    assert "terminology_mismatch" in {item.kind for item in issues}
