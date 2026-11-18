# Tests — Agent Instructions

> Scope: `tests/`. Inherits all repo-wide rules from the root
> [AGENTS.md](../AGENTS.md); this file adds testing-specific conventions.

## Harness
- Framework: `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`), so
  `async def test_*` functions run without markers.
- The package is installed editable into `.venv`; import it as `tgmate`,
  never by manipulating `sys.path`.
- Run: `coverage run -m pytest` (with coverage) or `pytest -q` (fast). Subset:
  `pytest tests/test_smoke.py -q`.

## Writing tests
- Add or update a test for every behavior change.
- Assert the stated behavior, not merely that code runs; avoid weak
  assertions like `assert result` when a specific value is expected.
- Cover negative cases alongside positive ones.
- Test tools directly. Front-end tests check the adapter (argument parsing,
  replies, error presentation); they call the real tool when it is fast and
  local, and a faked one when it is slow or needs external binaries or the
  network.
- Check generated files by reading them back (e.g. `tests/images.py`
  decodes QR codes), not just by their size or header.
- Compare CLI usage errors and help through `tests.terminal.plain`: in CI
  (`GITHUB_ACTIONS`) Typer styles them with ANSI codes that split words like
  `--force`. Reproduce locally with `GITHUB_ACTIONS=true pytest`.
- Tests must be order-independent and parallel-safe: use `tmp_path` and
  `monkeypatch`; never hit the real Telegram API, YouTube or network.
- Name tests for the behavior under test; keep them small and focused.
