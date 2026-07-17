import json
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from ebooklib import epub
import pytest

from contextweaver.adapters import (
    MockTranslationAdapter,
    OpenAITranslationAdapter,
    TranslationAdapter,
)
from contextweaver.knowledge import propose_knowledge
from contextweaver.models import ContextPacket, Segment, TranslationRecord
from contextweaver.pipeline import (
    build_context,
    active_translations,
    import_document,
    import_translation_draft,
    init_project,
    segment_document,
    translate_project,
    validate_project,
)
from contextweaver.reference import import_reference, simplify_reference, simplify_reference_outputs
from contextweaver.storage import read_jsonl


def _project(tmp_path: Path, source: Path) -> Path:
    root = tmp_path / "project"
    init_project(root, "Phase Two", "en", "zh-CN")
    import_document(root, source)
    return root


def test_structured_markdown_preserves_blocks_and_inline_markup(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "# Title\n\n- One **bold** item\n- Two items\n\n> A *quoted* line.[^1]\n\n[^1]: Note.\n",
        encoding="utf-8",
    )
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
    report = json.loads((root / "state" / "import_report.json").read_text())
    assert report["spine_documents"] == 1


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
    translate_project(
        root, MockTranslationAdapter(), segment_ids={segments[0].id}, reason="terminology-fix"
    )
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
    adapter = OpenAITranslationAdapter(
        client=SimpleNamespace(responses=responses), max_retries=2, sleep=sleeps.append
    )
    segment = Segment(
        "seg", "doc", "sec", 0, "Source", raw="**Source**", format_signature=["strong"]
    )
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
    glossary.write_text(
        "term,preferred_translation,allowed_variants,note,source_segment_id,confidence,evidence_segment_ids,status\nContextWeaver,上下文编织器,,,1,,approved\n",
        encoding="utf-8",
    )
    issues = validate_project(root)
    assert "terminology_mismatch" in {item.kind for item in issues}


def test_numeric_anchor_validation_is_blocking(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nOutput rose 25% in 2024.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    translate_project(root, MockTranslationAdapter())
    records = root / "state" / "translations.jsonl"
    records.write_text(records.read_text().replace("25%", "20%"), encoding="utf-8")
    issues = validate_project(root)
    assert "numeric_anchor_mismatch" in {item.kind for item in issues}


def test_balanced_numeric_mode_warns_for_target_only_number(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nNo quantity was stated.\n", encoding="utf-8")
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    draft = tmp_path / "draft.jsonl"
    draft.write_text(
        json.dumps(
            {"segment_id": segments[0].id, "translated_text": "原文未说明数量，但这里写了5。"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    import_translation_draft(root, draft, "codex-agent", "test", "numeric-mode")
    balanced = validate_project(root)
    strict = validate_project(root, numeric_mode="strict")
    assert [item.severity for item in balanced if item.kind == "numeric_anchor_mismatch"] == [
        "warning"
    ]
    assert [item.severity for item in strict if item.kind == "numeric_anchor_mismatch"] == [
        "error"
    ]


def test_numeric_anchors_work_next_to_cjk() -> None:
    from contextweaver.validation import (
        _balanced_numeric_anchors,
        _numbers,
        _numeric_anchors,
    )

    assert _numbers("In 1791, close to 90 percent") == ["1791", "90"]
    assert _numbers("1791年，接近90%") == ["1791", "90"]
    assert _balanced_numeric_anchors(["5"]) == _balanced_numeric_anchors(["ordinal:5"])
    assert _numeric_anchors("seven hundred and fifty people") == ["quantity:750"]
    assert _numeric_anchors("more than three hundred million people") == [
        "quantity:300000000"
    ]
    assert _numeric_anchors("fifty-five million messages") == ["quantity:55000000"]
    assert _numeric_anchors("the first century") == _numeric_anchors("最初一个世纪")
    assert _numeric_anchors("First edition: May 2023") == ["2023", "month:5"]
    assert _numeric_anchors("第一版：2023年5月") == ["2023", "month:5"]
    assert _numeric_anchors("第一版：2023年五月") == ["2023", "month:5"]
    assert _numeric_anchors("Published Jan. 2024") == ["2024", "month:1"]
    assert _numeric_anchors("出版于2024年1月") == ["2024", "month:1"]
    assert _numeric_anchors("It may improve 2023 outcomes") == ["2023"]


def test_calendar_month_naturalization_is_not_an_invented_number(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Copyright\n\nFirst edition: May 2023\n", encoding="utf-8")
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    draft = tmp_path / "draft.jsonl"
    draft.write_text(
        json.dumps(
            {"segment_id": segments[0].id, "translated_text": "第一版：2023年5月"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    import_translation_draft(root, draft, "codex-agent", "GPT-5", "date-naturalization")
    issues = validate_project(root)
    assert "numeric_anchor_mismatch" not in {item.kind for item in issues}


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("in the 1980s", "在20世纪80年代"),
        ("in the 1700s", "在18世纪"),
        ("throughout the 1950s and 1960s", "整个20世纪50年代和60年代"),
        ("during the twentieth century", "在20世纪期间"),
        ("in the third century bce", "公元前3世纪"),
        ("in eighteenth-century Britain", "在18世纪的英国"),
        ("from the sixteenth and seventeenth centuries", "从16世纪和17世纪"),
        ("chapters 5 through 9", "第五章至第九章"),
        ("Chapter 7", "第七章"),
        ("January 5, 1914", "1914年1月5日"),
        ("by May 23", "到5月23日"),
        ("the worker died in June", "工人于6月死亡"),
        ("In October of that year", "同年10月"),
        ("World War II", "第二次世界大战"),
        ("around 1.5 million cars", "约150万辆汽车"),
        ("more than one million options", "一百万多个选项"),
        ("five thousand bonuses", "五千笔奖金"),
        ("for more than a millennium", "延续超过一千年"),
        ("for more than a thousand years", "延续超过一千年"),
        ("two hundred thousand residents", "二十万名居民"),
        ("thirteen thousand sheep", "一万三千只羊"),
        ("fifteen hundred people", "一千五百人"),
        ("about a million people", "约一百万人"),
        ("17–18 million people", "1700万至1800万人"),
        ("over five hundred years", "五百多年"),
        ("ten thousand workers", "一万名工人"),
        ("the 5th Regiment", "第5团"),
    ],
)
def test_semantic_numeric_renderings_share_source_anchors(source: str, target: str) -> None:
    from contextweaver.validation import _numeric_anchors

    assert _numeric_anchors(source) == _numeric_anchors(target)


def test_roman_regnal_numbers_are_not_acronyms() -> None:
    from contextweaver.validation import _acronyms

    assert _acronyms("Henry VIII met Richard II") == []


def test_approved_acronym_translation_preserves_semantic_anchor(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "# One\n\nA US industrial firm.\n\nIts purposes let us proceed unchanged.\n",
        encoding="utf-8",
    )
    root = _project(tmp_path, source)
    _, segments, _ = segment_document(root)
    glossary = root / "state" / "glossary.csv"
    glossary.write_text(
        "term,preferred_translation,allowed_variants,note,source_segment_id,confidence,evidence_segment_ids,status\n"
        f"US,美国,,Geopolitical abbreviation,{segments[0].id},0.99,{segments[0].id},approved\n",
        encoding="utf-8",
    )
    draft = tmp_path / "draft.jsonl"
    draft.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False)
            for item in (
                {"segment_id": segments[0].id, "translated_text": "一家美国工业企业。"},
                {"segment_id": segments[1].id, "translated_text": "其宗旨并未改变。"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    import_translation_draft(root, draft, "codex-agent", "GPT-5", "acronym-localization")
    issues = validate_project(root)
    assert "acronym_missing" not in {item.kind for item in issues}
    assert "terminology_mismatch" not in {item.kind for item in issues}


def test_link_destination_underscores_are_not_emphasis() -> None:
    from contextweaver.markdown import format_signature

    assert format_signature("See [Chapter 1](009_Chapter_002.xhtml).") == ["link"]


def test_human_reference_alignment_and_mainland_draft(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "# 1 Control over Technology\n\nDigital technology changes work.\n\nA second paragraph.\n",
        encoding="utf-8",
    )
    root = _project(tmp_path, source)
    _, _, units = segment_document(root, unit_size=1)
    reference = tmp_path / "reference.md"
    reference.write_text(
        "# １ 對科技的掌控\n\n數位科技改變工作。\n\n第二段使用軟體與網路。\n", encoding="utf-8"
    )
    assert import_reference(root, reference, "zh-TW", "Human Translator (reference)") == (1, 2, 1)
    packet = build_context(root, units[0])
    assert packet.reference_texts
    count, output = simplify_reference(root)
    assert count == 2
    simplified = output.read_text(encoding="utf-8")
    assert "数字科技" in simplified
    assert "软件与网络" in simplified
    assert "Human Translator (reference)" in simplified
    assert "not a new translation" in simplified
    packet = build_context(root, units[1])
    assert any("软件与网络" in item for item in packet.reference_texts)
    _, paths = simplify_reference_outputs(root, {"epub"})
    assert paths[0].name == "reference-zh-CN.epub"
    assert epub.read_epub(str(paths[0]), options={"ignore_ncx": True}).spine
