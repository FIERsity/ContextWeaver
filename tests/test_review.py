import json
from pathlib import Path
from types import SimpleNamespace

from contextweaver.adapters import HeuristicReviewAdapter, OpenAIReviewAdapter
from contextweaver.models import ContextPacket, Segment, TranslationRecord, TranslationReview
from contextweaver.pipeline import (
    active_translations,
    import_document,
    import_translation_draft,
    init_project,
    segment_document,
)
from contextweaver.review import review_project
from contextweaver.storage import read_jsonl


def _translated_project(tmp_path: Path) -> tuple[Path, Segment]:
    source = tmp_path / "book.md"
    source.write_text("# Progress\n\nMost people are disempowered and benefit little.\n", encoding="utf-8")
    root = tmp_path / "project"
    init_project(root, "Review", "en", "zh-CN")
    import_document(root, source)
    _, segments, _ = segment_document(root, unit_size=1)
    draft = tmp_path / "draft.jsonl"
    draft.write_text(json.dumps({
        "segment_id": segments[0].id,
        "translated_text": "大多数人失去了力量，获益很少。",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    import_translation_draft(root, draft, "test-agent", "test-model", "initial")
    return root, segments[0]


def test_review_appends_critique_and_linked_revision_once(tmp_path: Path) -> None:
    root, segment = _translated_project(tmp_path)
    assert review_project(root, HeuristicReviewAdapter()) == (1, 1, 0)
    translations = read_jsonl(root / "state" / "translations.jsonl", TranslationRecord)
    active = active_translations(translations)[segment.id]
    assert "权力遭到削弱" in active.translated_text
    assert active.supersedes == translations[0].id
    assert active.prompt_version == "review-v1-agent-critic-reviser"
    reviews = read_jsonl(root / "state" / "reviews.jsonl", TranslationReview)
    assert reviews[0].categories == ["concept_role"]
    assert reviews[0].input_translation_id == translations[0].id
    assert reviews[0].output_translation_id == active.id
    assert review_project(root, HeuristicReviewAdapter()) == (0, 0, 1)


def test_openai_reviewer_returns_structured_revision() -> None:
    response = {"reviews": [{
        "verdict": "revise", "categories": ["natural_zh"],
        "rationale": "Use native Chinese order.", "confidence": 0.9,
        "revised_translation": "自然的中文。",
    }]}
    client = SimpleNamespace(responses=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(output_text=json.dumps(response, ensure_ascii=False))
    ))
    adapter = OpenAIReviewAdapter(client=client, model="test")
    segment = Segment("seg", "doc", "sec", 0, "Natural Chinese.")
    packet = ContextPacket("unit", [segment], None, None, None, [], [])
    record = TranslationRecord(
        "tr", "unit", "seg", "中文自然。", "test", "test", "v", "now", "hash"
    )
    decisions = adapter.review(packet, [record])
    assert decisions[0].verdict == "revised"
    assert decisions[0].revised_translation == "自然的中文。"
