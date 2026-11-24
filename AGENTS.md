# tgmate — Agent Instructions

Everyday tools (media download, document and image conversion, QR codes)
exposed through several front ends: a CLI and a Telegram bot.

## Project overview
- Package: [src/tgmate/](src/tgmate). **See [src/tgmate/AGENTS.md](src/tgmate/AGENTS.md).**
- Runtime: Python 3.14 (`requires-python` in [pyproject.toml](pyproject.toml)).
- Product decisions (tools, front ends, Telegram access and limits, licensing):
  **see [docs/architecture.md](docs/architecture.md)** — read it before
  changing behavior and update it when a decision changes.

## Environment & setup
- Dependency manager: `uv`; lock file `uv.lock`. The project is a src-layout
  package installed into the local `.venv` in editable mode.
- First-time setup:
  1. Install `uv` (once per machine): `curl -LsSf https://astral.sh/uv/install.sh | sh`
  2. Create `.venv` with runtime + dev deps: `uv sync` (the `dev` group is a
     default group).
  3. Run commands with the venv activated (`source .venv/bin/activate`) or
     prefix each with `uv run`.
- After **any** dependency change: `uv lock`, then `uv sync`; verify with
  `uv lock --check`.
- Secrets and runtime settings come from `.env` (template:
  [.env.example](.env.example)). Never read or commit a real `.env`.

## Build / test / lint commands
> Run from the repo root inside `.venv` (or prefix with `uv run`). Tests + lint
> must pass before a task is done.
- Tests with coverage: `coverage run -m pytest` then `coverage report`
- Quick tests: `pytest -q`
- Lint (including import order): `ruff check .`; autofix with `ruff check --fix .`
- Security: `bandit -c pyproject.toml -r src --severity-level medium` and
  `pre-commit run semgrep --hook-stage manual --all-files` (semgrep is not a
  project dependency: pre-commit installs it in its own environment, so its
  pinned dependencies stay out of `uv.lock`)
- Git hooks: `pre-commit install` once; `pre-commit run --all-files` on demand.

## Code style & conventions
- Python 3.14 idioms: builtin generics (`list`, `dict`, `tuple`), PEP 604
  unions (`X | None`), `import typing as t` instead of `from typing import ...`.
- Keep logic modular and unit-testable: small pure functions and explicit
  boundaries around I/O (Telegram, YouTube, external converters, filesystem).
- **DRY — one source of truth per fact.** A contract (tool API, config
  semantics, file layout) lives in exactly one place — a code constant or the
  owning module's `README.md` — and everything else links to it.
- Give every function an explicit `return` where a value is expected.
- Line length, naming and import order are owned by `ruff` (config in
  `pyproject.toml`) — make it pass instead of hand-styling.
- Don't over-engineer: no speculative config, fallbacks or validation for
  states that can't occur. Validate only at real boundaries (user input, I/O).

### Comments & docstrings
Write code that needs as little prose as possible; add prose only where the
code can't speak.
1. **Self-explanatory code (default).** Clear names, type hints and small
   functions are the primary documentation.
2. **A one-line `#` comment** — only for the non-obvious: a rationale,
   trade-off, invariant, API quirk or deliberate deviation. Explain *why*,
   never restate *what*.
3. **A short docstring** — one-line module docstring stating the file's role;
   one-line contract on public or non-trivial functions/classes.

Never write: comments that paraphrase code, docstrings that echo the name,
param prose that repeats annotations, commented-out code, change-log
narration, or dated TODOs. Match the comment density of neighboring code.

## Architecture map
- [src/tgmate/](src/tgmate) — the application package.
  - [tools/](src/tgmate/tools) — the tools themselves, front-end agnostic
    (`README.md`).
  - [cli/](src/tgmate/cli) — the `tgmate` command (Typer); run with
    `uv run tgmate --help` (`README.md`).
  - [telegram/](src/tgmate/telegram) — the Telegram bot (aiogram): owner
    approval of users, tool buttons and commands; run with
    `uv run python -m tgmate.telegram` (`README.md`).
  - [storage/](src/tgmate/storage) — SQLite schema, query helpers and Alembic
    migrations for the bot (`README.md`).
  - [config.py](src/tgmate/config.py) — the bot's `Settings` from env/`.env`;
    the single source of env variable names and defaults (template:
    [.env.example](.env.example)).
- [tests/](tests) — pytest suite. **See [tests/AGENTS.md](tests/AGENTS.md).**
- [.docker/](.docker) + [docker-compose.yaml](docker-compose.yaml) — the bot's
  image (uv two-stage build on Debian slim, no pip, non-root, `/data`
  volume) and its compose service, built locally, plus the optional local
  Bot API server (`bot-api.Dockerfile`, compose profile `bot-api`). CI builds the image,
  migrates a database inside it and fails on fixable high/critical CVEs
  (Trivy). Running it: [docs/deployment.md](docs/deployment.md).
  `.dockerignore` is an allowlist, so new top-level files the build needs
  must be added there.
- [.github/](.github) — CI (lint, tests, security scans, Docker image) and
  Dependabot (weekly `uv`, pre-commit hook, base image and GitHub Actions
  updates).
- [.claude/](.claude) — agent tooling: settings and skills. `.agents/skills`
  and `.cursor/skills` are symlinks to `.claude/skills` so Codex and Cursor
  share the same skills.
- Read a module's `README.md` (when present) before editing that module.

## Testing instructions
- Add or update tests for every behavior change; assert the stated behavior,
  not just "it runs".
- Fake only external boundaries (Telegram API, YouTube, network); exercise
  real conversions on small fixture files.
- All tests must be green before a task is done.

## Security & safety
- No `eval`/`exec`, no `subprocess(..., shell=True)`, no unsafe YAML or
  untrusted deserialization (enforced by `.semgrep.yml`).
- Every uploaded file and URL is untrusted: check size and type before
  processing, and bound the work (timeouts, page/pixel/duration limits).
- Tools that parse untrusted files in-process (PDFium, Pillow, …) run each
  operation in a sandboxed worker process
  ([tools/sandbox.py](src/tgmate/tools/sandbox.py)); a new such tool
  registers its operations in [tools/worker.py](src/tgmate/tools/worker.py).
- External binaries (e.g. converters, downloaders) run with an argument list,
  a timeout and a per-job temporary directory that is always cleaned up; user
  input never becomes an option (pass `--` before positional paths/URLs).
- Never hardcode, log or commit secrets; load them from the environment.
- New dependencies must be justified, license-compatible with AGPL-3.0-or-later, pinned with
  `==` and locked in `uv.lock`.

## Git conventions
- No issue tracker: branches and commits use Conventional Commits types —
  `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `perf`, `build`.
- Branch: `<type>/<short-kebab-slug>` (e.g. `feat/qr-code`,
  `fix/pdf-page-order`). Never commit directly to `main`.
- Commit: `<type>(<optional scope>): <imperative summary>` (e.g.
  `feat(tools): add QR code generation`). One logical change per commit.
- PR title follows the commit format; write the body with the
  `/pr-description` skill (concise bulleted changelog).
- Commit messages and PR bodies are plain changelogs — no co-authorship,
  "generated by" or tool-attribution trailers.
- Keep changes minimal and scoped; avoid drive-by refactors.

## Gotchas
- Don't paste pinned versions into docs — reference `pyproject.toml` /
  `uv.lock`.
