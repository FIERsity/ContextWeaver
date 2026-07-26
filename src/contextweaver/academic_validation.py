"""Deterministic publication-structure checks for imported academic articles."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import ReviewIssue, Segment, SourceDocument
from .pipeline import STATE, stable_id
from .storage import read_json


def academic_issues(root: Path, source: SourceDocument, segments: list[Segment]) -> list[ReviewIssue]:
    """Validate figures, tables, and fetched figure assets for a JATS article."""
    if source.source_format != "jats":
        return []
    report_path = root / STATE / "import_report.json"
    if not report_path.exists():
        return [_issue("academic_missing_import_report", "JATS import report is missing", None, "error")]
    report = read_json(report_path)
    image_segments = [item for item in segments if re.fullmatch(r"!\[[^]]*\]\(assets/[^)]+\)", item.raw)]
    expected_figures = int(report.get("figures", 0))
    expected_tables = int(report.get("tables", 0))
    issues: list[ReviewIssue] = []
    if len(image_segments) != expected_figures:
        issues.append(
            _issue(
                "academic_figure_count_mismatch",
                f"JATS report lists {expected_figures} figures but normalized source has {len(image_segments)} image blocks",
                None,
                "error",
            )
        )
    tables = [item for item in segments if item.kind == "table"]
    if len(tables) != expected_tables:
        issues.append(
            _issue(
                "academic_table_count_mismatch",
                f"JATS report lists {expected_tables} tables but normalized source has {len(tables)} table blocks",
                None,
                "error",
            )
        )
    asset_path = root / STATE / "academic_assets.json"
    asset_rows = read_json(asset_path).get("assets", []) if asset_path.exists() else []
    assets = {str(item.get("path", "")): item for item in asset_rows if isinstance(item, dict)}
    for segment in image_segments:
        relative = re.fullmatch(r"!\[[^]]*\]\((assets/[^)]+)\)", segment.raw).group(1)  # type: ignore[union-attr]
        path = root / "source" / relative
        record = assets.get(f"source/{relative}")
        if not path.exists() or record is None:
            issues.append(_issue("academic_missing_figure_asset", f"Missing fetched figure asset {relative}", segment.id, "error"))
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record.get("sha256"):
            issues.append(_issue("academic_figure_asset_changed", f"Figure asset hash differs from manifest for {relative}", segment.id, "error"))
    return issues


def _issue(kind: str, message: str, segment_id: str | None, severity: str) -> ReviewIssue:
    return ReviewIssue(
        stable_id("issue", kind, segment_id or "project", message), kind, message, segment_id, severity  # type: ignore[arg-type]
    )
