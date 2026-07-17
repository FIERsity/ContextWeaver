import json
from pathlib import Path
from types import SimpleNamespace

from contextweaver.cli import run
from contextweaver.pipeline import build_context, import_document, init_project, segment_document
from contextweaver.strategy import (
    HeuristicBookAnalysisAdapter,
    OpenAIBookAnalysisAdapter,
    analyze_project,
)


def _project(tmp_path: Path) -> Path:
    source = tmp_path / "book.md"
    source.write_text(
        "# Power and Progress\n\nPolitical power shapes technology.\n\n"
        "Computational power raises productivity.\n\nWorkers seek shared prosperity.\n",
        encoding="utf-8",
    )
    root = tmp_path / "project"
    init_project(root, "Power", "en", "zh-CN")
    import_document(root, source)
    segment_document(root, unit_size=1)
    return root


def test_analysis_creates_editable_strategy_and_injects_context(tmp_path: Path) -> None:
    root = _project(tmp_path)
    brief = analyze_project(root, HeuristicBookAnalysisAdapter())
    assert brief["human_review_required"] is False
    assert any(item["source_term"] == "power" for item in brief["concept_rules"])
    assert (root / "notes" / "translation_brief.md").exists()
    units = json.loads((root / "state" / "units.jsonl").read_text().splitlines()[0])
    from contextweaver.models import TranslationUnit

    packet = build_context(root, TranslationUnit(**units))
    assert packet.translation_strategy["target_style"].startswith("idiomatic Mainland")


def test_analysis_scans_rare_high_impact_concepts_outside_samples(tmp_path: Path) -> None:
    root = _project(tmp_path)
    source = root / "source" / "document.md"
    source.write_text(source.read_text() + "\n# Later\n\nMost people are disempowered.\n", encoding="utf-8")
    segment_document(root, unit_size=1)
    brief = analyze_project(root, HeuristicBookAnalysisAdapter())
    rule = next(item for item in brief["concept_rules"] if item["source_term"] == "disempowered")
    assert rule["preferred_rendering"] == "权力受到削弱"


def test_analysis_is_resumable_and_does_not_overwrite_edits(tmp_path: Path) -> None:
    root = _project(tmp_path)
    first = analyze_project(root, HeuristicBookAnalysisAdapter())
    path = root / "state" / "translation_brief.json"
    edited = {**first, "target_style": "Custom reviewed style"}
    path.write_text(json.dumps(edited), encoding="utf-8")
    assert analyze_project(root, HeuristicBookAnalysisAdapter())["target_style"] == "Custom reviewed style"


def test_openai_analysis_adapter_uses_structured_output() -> None:
    result = {
        "genre": "social science", "domains": ["political economy"],
        "source_style": "analytical", "target_style": "natural zh-CN", "audience": "general",
        "principles": ["faithful"], "concept_rules": [], "confidence": 0.9,
    }
    responses = SimpleNamespace(create=lambda **kwargs: SimpleNamespace(output_text=json.dumps(result)))
    adapter = OpenAIBookAnalysisAdapter(client=SimpleNamespace(responses=responses), model="test-model")
    assert adapter.analyze({"samples": []}) == result


def test_auto_cli_runs_agent_first_path_without_human_gate(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "state" / "units.jsonl").unlink()
    assert run(["auto", str(root)]) == 0
    assert (root / "state" / "translation_brief.json").exists()
    assert (root / "state" / "section_summaries.jsonl").exists()
    assert (root / "state" / "reviews.jsonl").exists()
    assert (root / "state" / "scope_reviews.jsonl").exists()
    assert (root / "output" / "translated.md").exists()
    assert (root / "output" / "translated.epub").exists()
    report = json.loads((root / "state" / "v1_audit.json").read_text(encoding="utf-8"))
    assert report["ready"] is True
