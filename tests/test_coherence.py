import json
from pathlib import Path
from types import SimpleNamespace

from contextweaver.coherence import review_book, review_sections
from contextweaver.coherence_adapters import (
    CoherenceReviewAdapter,
    OpenAICoherenceReviewAdapter,
    ScopeReviewDecision,
)
from contextweaver.models import ScopeReview, TranslationRecord
from contextweaver.pipeline import (
    active_translations,
    import_document,
    import_section_title_draft,
    import_translation_draft,
    init_project,
    segment_document,
)
from contextweaver.storage import read_jsonl
from contextweaver.summaries import summarize_project
from contextweaver.summary_adapters import HeuristicSummaryAdapter


class FixPowerAdapter(CoherenceReviewAdapter):
    name = "test-coherence"
    model = "test"

    def review_scope(self, payload: dict[str, object]) -> ScopeReviewDecision:
        evidence = payload["evidence"]
        assert isinstance(evidence, list)
        for item in evidence:
            if "失去了力量" in item["translation"]:
                return ScopeReviewDecision(
                    "revised",
                    ["concept_consistency"],
                    "Use political-economic power.",
                    0.95,
                    {item["segment_id"]: item["translation"].replace("失去了力量", "权力遭到削弱")},
                )
        return ScopeReviewDecision("pass", [], "Consistent.", 0.9)


def _project(tmp_path: Path) -> tuple[Path, list[str]]:
    source = tmp_path / "book.md"
    source.write_text(
        "# One\n\nMost people are disempowered.\n\nProgress is contested.\n\n"
        "# Two\n\nTechnology can expand human capabilities.\n",
        encoding="utf-8",
    )
    root = tmp_path / "project"
    init_project(root, "Coherence", "en", "zh-CN")
    import_document(root, source)
    sections, segments, _ = segment_document(root, unit_size=1)
    translations = ["大多数人失去了力量。", "进步存在争议。", "技术可以扩展人的能力。"]
    draft = tmp_path / "draft.jsonl"
    draft.write_text(
        "\n".join(
            json.dumps({"segment_id": segment.id, "translated_text": text}, ensure_ascii=False)
            for segment, text in zip(segments, translations, strict=True)
        )
        + "\n",
        encoding="utf-8",
    )
    import_translation_draft(root, draft, "test", "test", "initial")
    return root, [item.id for item in sections]


def test_section_and_book_reviews_are_digest_resumable(tmp_path: Path) -> None:
    root, section_ids = _project(tmp_path)
    adapter = FixPowerAdapter()
    assert review_sections(root, adapter, {section_ids[0]}) == (1, 1, 0)
    assert review_sections(root, adapter, {section_ids[0]}) == (0, 0, 1)
    summarize_project(root, HeuristicSummaryAdapter(), {section_ids[0]})
    assert review_sections(root, adapter, {section_ids[0]}) == (1, 0, 0)
    assert review_book(root, adapter) == (1, 0, 0)
    assert review_book(root, adapter) == (0, 0, 1)
    active = active_translations(
        read_jsonl(root / "state" / "translations.jsonl", TranslationRecord)
    )
    assert any("权力遭到削弱" in item.translated_text for item in active.values())
    reviews = read_jsonl(root / "state" / "scope_reviews.jsonl", ScopeReview)
    assert [item.scope_type for item in reviews] == ["section", "section", "book"]
    assert reviews[0].input_digest != reviews[0].output_digest
    assert reviews[1].input_digest == reviews[1].output_digest


def test_book_review_requires_complete_translation(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    translations = root / "state" / "translations.jsonl"
    translations.write_text("\n".join(translations.read_text().splitlines()[:-1]) + "\n")
    import pytest

    with pytest.raises(RuntimeError, match="missing"):
        review_book(root, FixPowerAdapter())


def test_section_title_revision_invalidates_scope_fingerprint(tmp_path: Path) -> None:
    root, section_ids = _project(tmp_path)
    adapter = FixPowerAdapter()
    assert review_sections(root, adapter, {section_ids[0]})[0] == 1
    assert review_sections(root, adapter, {section_ids[0]}) == (0, 0, 1)
    draft = tmp_path / "titles.jsonl"
    draft.write_text(
        json.dumps({"section_id": section_ids[0], "translated_title": "第一章"}) + "\n",
        encoding="utf-8",
    )
    import_section_title_draft(root, draft, "codex-agent", "GPT-5", "title-translation")
    assert review_sections(root, adapter, {section_ids[0]}) == (1, 0, 0)


def test_openai_coherence_adapter_returns_structured_revisions() -> None:
    result = {
        "verdict": "revise",
        "categories": ["concept_consistency"],
        "rationale": "Align the core concept.",
        "confidence": 0.9,
        "revisions": [{"segment_id": "seg", "revised_translation": "权力受到削弱。"}],
    }
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                output_text=json.dumps(result, ensure_ascii=False)
            )
        )
    )
    adapter = OpenAICoherenceReviewAdapter(client=client, model="test")
    decision = adapter.review_scope({"scope_type": "book", "evidence": []})
    assert decision.revisions == {"seg": "权力受到削弱。"}
