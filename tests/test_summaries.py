import json
from pathlib import Path
from types import SimpleNamespace

from contextweaver.models import AmbiguityRecord, SectionSummary
from contextweaver.pipeline import build_context, import_document, init_project, segment_document
from contextweaver.storage import read_jsonl
from contextweaver.summaries import summarize_project
from contextweaver.summary_adapters import HeuristicSummaryAdapter, OpenAISummaryAdapter, _truncate


def _project(tmp_path: Path) -> tuple[Path, list[object], list[object]]:
    source = tmp_path / "book.md"
    source.write_text(
        "# One\n\nPower shapes technology.[?]\n\n# Two\n\nWorkers seek prosperity.\n",
        encoding="utf-8",
    )
    root = tmp_path / "project"
    init_project(root, "Summaries", "en", "zh-CN")
    import_document(root, source)
    sections, _, units = segment_document(root, unit_size=1)
    return root, sections, units


def test_summaries_are_resumable_versioned_and_injected(tmp_path: Path) -> None:
    root, sections, units = _project(tmp_path)
    adapter = HeuristicSummaryAdapter()
    assert summarize_project(root, adapter) == (2, 1, 0)
    assert summarize_project(root, adapter) == (0, 0, 2)
    packet = build_context(root, units[0])
    assert packet.section_summary == "Power shapes technology.[?]"
    assert (root / "notes" / "section_summaries.md").exists()
    assert summarize_project(root, adapter, {sections[0].id}, refresh=True) == (1, 0, 0)
    records = read_jsonl(root / "state" / "section_summaries.jsonl", SectionSummary)
    chain = [item for item in records if item.section_id == sections[0].id]
    assert [item.revision for item in chain] == [1, 2]
    assert chain[1].supersedes == chain[0].id
    ambiguities = read_jsonl(root / "state" / "ambiguities.jsonl", AmbiguityRecord)
    assert len(ambiguities) == 1
    assert ambiguities[0].status == "open"


def test_openai_summary_adapter_returns_structured_context() -> None:
    result = {
        "summary": "本章讨论权力与技术。",
        "key_points": ["权力塑造技术"],
        "evidence_segment_ids": ["seg"],
        "confidence": 0.9,
        "ambiguities": [
            {
                "category": "term",
                "description": "power 的语境义需区分。",
                "evidence_segment_ids": ["seg"],
                "confidence": 0.8,
            }
        ],
    }
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                output_text=json.dumps(result, ensure_ascii=False)
            )
        )
    )
    decision = OpenAISummaryAdapter(client=client, model="test").summarize({"evidence": []})
    assert decision.summary == "本章讨论权力与技术。"
    assert decision.ambiguities[0].category == "term"


def test_openai_summary_retries_transient_failure() -> None:
    result = {
        "summary": "摘要",
        "key_points": [],
        "evidence_segment_ids": [],
        "confidence": 0.8,
        "ambiguities": [],
    }

    class RetryError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "0.25"})

    class Responses:
        calls = 0

        def create(self, **kwargs: object) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 1:
                raise RetryError("busy")
            return SimpleNamespace(output_text=json.dumps(result, ensure_ascii=False))

    responses = Responses()
    sleeps: list[float] = []
    adapter = OpenAISummaryAdapter(
        client=SimpleNamespace(responses=responses), model="test", sleep=sleeps.append
    )
    assert adapter.summarize({"evidence": []}).summary == "摘要"
    assert responses.calls == 2
    assert sleeps == [0.25]


def test_extract_summary_never_cuts_an_english_word() -> None:
    text = "A complete sentence. " + "word " * 300
    result = _truncate(text, 120)
    assert result.startswith("A complete sentence.")
    assert result.endswith("word")
    assert not result.endswith("wor")
