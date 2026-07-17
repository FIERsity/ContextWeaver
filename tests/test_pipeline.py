from pathlib import Path

import pytest

from contextweaver.adapters import MockTranslationAdapter, TranslationAdapter
from contextweaver.models import ContextPacket
from contextweaver.pipeline import (
    build_context,
    export_project,
    import_document,
    init_project,
    project_status,
    segment_document,
    translate_project,
    validate_project,
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "book.md"
    path.write_text("# One\n\nFirst paragraph.\n\nSecond paragraph.\n\n# Two\n\nLast paragraph.\n", encoding="utf-8")
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


def test_resume_validate_and_export(project: Path) -> None:
    segment_document(project, unit_size=2)
    assert translate_project(project, MockTranslationAdapter()) == (3, 0)
    assert translate_project(project, MockTranslationAdapter()) == (0, 3)
    assert validate_project(project) == []
    translated, bilingual = export_project(project)
    assert "[MOCK] First paragraph." in translated.read_text(encoding="utf-8")
    assert "> First paragraph." in bilingual.read_text(encoding="utf-8")
    assert project_status(project).translation_count == 3


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


def test_adapter_cardinality_is_enforced(project: Path) -> None:
    segment_document(project)
    with pytest.raises(RuntimeError, match="outputs"):
        translate_project(project, BrokenAdapter())

