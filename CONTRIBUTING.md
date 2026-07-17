# Contributing

ContextWeaver welcomes focused fixes and small, test-backed features. Open an issue before large schema, segmentation, or workflow changes so compatibility can be discussed.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
uv run --with pyyaml python ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/contextweaver-translate
```

Keep runtime dependencies minimal. A new persisted field must have a clear purpose, documented semantics, and a migration plan if it changes existing data. Adapter packages should remain optional. Include an end-to-end test when changing workflow behavior, and update the README or architecture notes when changing user-visible commands or invariants.

When changing CLI steps, persisted files, or review policy, update the bundled Codex Skill in the same change and run its validator. Keep `SKILL.md` concise; put detailed field guidance in `references/`.
