"""Explicit, resumable JATS figure-asset retrieval for supported open PLOS articles."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import urlopen
from xml.etree import ElementTree

from .models import SourceDocument
from .pipeline import STATE
from .storage import read_json, write_json


def fetch_jats_assets(root: Path) -> dict[str, object]:
    source = SourceDocument(**read_json(root / STATE / "source_document.json"))
    if source.source_format != "jats" or not source.original_path:
        raise RuntimeError("academic-assets currently requires an imported JATS source")
    xml = ElementTree.parse(root / source.original_path).getroot()
    doi = _doi(xml)
    if not doi.startswith("10.1371/journal.pone."):
        raise RuntimeError("asset retrieval currently supports PLOS ONE JATS articles only")
    graphics = _graphics(xml)
    destination = root / "source" / "assets"
    destination.mkdir(parents=True, exist_ok=True)
    assets = []
    for reference, remote_id in graphics:
        path = destination / f"{reference}.png"
        url = f"https://journals.plos.org/plosone/article/figure/image?size=large&id={remote_id}"
        if not path.exists():
            try:
                with urlopen(url, timeout=30) as response:
                    payload = response.read()
            except OSError as error:
                raise RuntimeError(f"Unable to fetch figure asset {reference}: {error}") from error
            if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"Unexpected non-PNG response for figure asset {reference}")
            path.write_bytes(payload)
        assets.append(
            {
                "reference": reference,
                "url": url,
                "path": str(path.relative_to(root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
                "status": "available",
            }
        )
    result: dict[str, object] = {"schema_version": 1, "source_format": "jats", "provider": "plos-one", "doi": doi, "assets": assets}
    write_json(root / STATE / "academic_assets.json", result)
    return result


def _doi(root: ElementTree.Element) -> str:
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "article-id" and node.attrib.get("pub-id-type") == "doi":
            return "".join(node.itertext()).strip()
    return ""


def _graphics(root: ElementTree.Element) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for figure in root.iter():
        if figure.tag.rsplit("}", 1)[-1] != "fig":
            continue
        for node in figure.iter():
            if node.tag.rsplit("}", 1)[-1] != "graphic":
                continue
            value = next(
                (item for key, item in node.attrib.items() if key.rsplit("}", 1)[-1] == "href"),
                "",
            )
            remote_id = value.removeprefix("info:doi/")
            reference = remote_id.rsplit("/", 1)[-1].split("journal.")[-1]
            if reference and (reference, remote_id) not in values:
                values.append((reference, remote_id))
    return values
