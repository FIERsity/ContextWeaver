from pathlib import Path
import json

from contextweaver.cli import run


def test_cli_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Chapter One\n\nHello world.\n", encoding="utf-8")
    project = tmp_path / "demo"
    assert run(["init", str(project), "--name", "Demo"]) == 0
    assert run(["import", str(project), str(source)]) == 0
    assert run(["segment", str(project)]) == 0
    batch = tmp_path / "agent-batch.jsonl"
    assert run(["agent-batch", str(project), str(batch), "--max-units", "1"]) == 0
    assert batch.exists()
    assert run(["translate", str(project)]) == 0
    assert run(["validate", str(project)]) == 0
    assert run(["export", str(project)]) == 0
    assert (project / "output" / "translated.md").exists()
    assert run(["export", str(project), "--format", "epub", "--content", "translated"]) == 0
    assert (project / "output" / "translated.epub").exists()


def test_cli_imports_and_adjudicates_sourced_terminology(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Chapter One\n\nThe OECD report.\n", encoding="utf-8")
    project = tmp_path / "demo"
    assert run(["init", str(project), "--name", "Demo"]) == 0
    assert run(["import", str(project), str(source)]) == 0
    assert run(["segment", str(project)]) == 0
    segment = json.loads((project / "state" / "segments.jsonl").read_text().splitlines()[0])
    candidates = tmp_path / "terms.jsonl"
    candidates.write_text(json.dumps({
        "term": "OECD", "candidate_translation": "经济合作与发展组织", "authority": "official",
        "source_title": "OECD", "source_url": "https://www.oecd.org/", "source_excerpt": "OECD",
        "evidence_segment_ids": [segment["id"]], "confidence": 0.98,
    }) + "\n", encoding="utf-8")
    assert run(["terminology-import", str(project), str(candidates)]) == 0
    assert run(["terminology-adjudicate", str(project), "--approve-authoritative"]) == 0
    assert "经济合作与发展组织" in (project / "state" / "glossary.csv").read_text(encoding="utf-8")
