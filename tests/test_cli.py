from pathlib import Path

from contextweaver.cli import run


def test_cli_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Chapter One\n\nHello world.\n", encoding="utf-8")
    project = tmp_path / "demo"
    assert run(["init", str(project), "--name", "Demo"]) == 0
    assert run(["import", str(project), str(source)]) == 0
    assert run(["segment", str(project)]) == 0
    assert run(["translate", str(project)]) == 0
    assert run(["validate", str(project)]) == 0
    assert run(["export", str(project)]) == 0
    assert (project / "output" / "translated.md").exists()

