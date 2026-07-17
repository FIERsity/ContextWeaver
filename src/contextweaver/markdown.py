"""Structured Markdown block parsing that retains source markup."""

from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin


@dataclass(frozen=True)
class MarkdownBlock:
    kind: str
    raw: str
    text: str
    level: int = 0
    title: str = ""
    source_locator: str = ""
    format_signature: tuple[str, ...] = ()


def parse_markdown(source: str) -> list[MarkdownBlock]:
    """Parse top-level source ranges while retaining their exact Markdown."""
    lines = source.splitlines()
    tokens = MarkdownIt("commonmark", {"html": True}).use(footnote_plugin).parse(source)
    ranges: list[tuple[int, int, str, object]] = []
    consumed_until = -1
    for token in tokens:
        if token.level != 0 or token.map is None:
            continue
        start, end = token.map
        if start < consumed_until:
            continue
        if token.type in {
            "heading_open",
            "paragraph_open",
            "bullet_list_open",
            "ordered_list_open",
            "blockquote_open",
            "fence",
            "code_block",
            "table_open",
            "footnote_block_open",
            "html_block",
            "hr",
        }:
            ranges.append((start, end, token.type, token))
            consumed_until = end
    covered = {line for start, end, _, _ in ranges for line in range(start, end)}
    for line_number, line in enumerate(lines):
        if line_number not in covered and re.match(r"^\[\^[^]]+\]:", line):
            ranges.append((line_number, line_number + 1, "footnote_block_open", None))
    ranges.sort(key=lambda item: item[0])
    blocks: list[MarkdownBlock] = []
    for start, end, token_type, token in ranges:
        raw = "\n".join(lines[start:end]).strip("\n")
        if not raw.strip():
            continue
        kind = _kind(token_type, raw)
        text = _plain(raw, kind)
        level = int(getattr(token, "tag", "h0")[1:]) if token_type == "heading_open" else 0
        blocks.append(
            MarkdownBlock(
                kind,
                raw,
                text,
                level,
                text if kind == "heading" else "",
                f"lines:{start + 1}-{end}",
                tuple(format_signature(raw)),
            )
        )
    return blocks


def format_signature(raw: str) -> list[str]:
    signature: list[str] = []
    # Link destinations may legitimately contain underscores (for example,
    # ``[Chapter 1](009_Chapter_002.xhtml)``).  They are not emphasis markup.
    prose_for_emphasis = re.sub(r"!?\[[^]]*\]\([^)]+\)", "", raw)
    checks = {
        "emphasis": r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)",
        "strong": r"\*\*[^*\n]+\*\*|__[^_\n]+__",
        "link": r"\[[^]]+\]\([^)]+\)",
        "image": r"!\[[^]]*\]\([^)]+\)",
        "code": r"`[^`\n]+`",
        "footnote_ref": r"\[\^[^]]+\]",
    }
    for name, pattern in checks.items():
        haystack = prose_for_emphasis if name == "emphasis" else raw
        signature.extend([name] * len(re.findall(pattern, haystack)))
    if raw.lstrip().startswith(("- ", "* ", "+ ")):
        signature.append("unordered_list")
    if re.match(r"^\s*\d+[.)]\s", raw):
        signature.append("ordered_list")
    if raw.lstrip().startswith(">"):
        signature.append("blockquote")
    return sorted(signature)


def plain_text(raw: str) -> str:
    """Return visible Markdown text for content-level checks.

    List markers and inline delimiters are formatting syntax, not source
    quantities. Callers that compare content should therefore use this form.
    """
    return _plain(raw, "heading" if re.match(r"^#{1,6}\\s+", raw) else "paragraph")


def _kind(token_type: str, raw: str) -> str:
    return {
        "heading_open": "heading",
        "bullet_list_open": "list",
        "ordered_list_open": "list",
        "blockquote_open": "blockquote",
        "fence": "code",
        "code_block": "code",
        "table_open": "table",
        "footnote_block_open": "footnote",
        "html_block": "html",
        "hr": "thematic_break",
    }.get(token_type, "footnote" if raw.lstrip().startswith("[^") else "paragraph")


def _plain(raw: str, kind: str) -> str:
    value = raw
    if kind == "heading":
        value = re.sub(r"^#{1,6}\s+", "", value)
    value = re.sub(r"^\s*(?:>|[-+*]|\d+[.)])\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_~`]", "", value)
    return " ".join(value.split())
