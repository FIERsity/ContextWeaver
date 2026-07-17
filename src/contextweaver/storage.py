"""File-first project storage with atomic rewrites for generated records."""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable, TypeVar

from .models import Record

T = TypeVar("T", bound=Record)


def write_json(path: Path, value: Record | dict[str, Any]) -> None:
    data = value.to_dict() if isinstance(value, Record) else value
    _atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, records: Iterable[Record]) -> None:
    content = "".join(json.dumps(record.to_dict(), ensure_ascii=False) + "\n" for record in records)
    _atomic_text(path, content)


def append_jsonl(path: Path, record: Record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path, cls: type[T]) -> list[T]:
    if not path.exists():
        return []
    valid = {item.name for item in fields(cls)}
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        unknown = set(raw) - valid
        if unknown:
            raise ValueError(f"{path}:{line_number}: unknown fields: {sorted(unknown)}")
        result.append(cls(**raw))
    return result


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
