# tgmate

Everyday tools with CLI & Telegram integration.

## Usage

```bash
uv sync
uv run tgmate qr example.com -o qr.png   # QR code for https://example.com
uv run tgmate --help                      # all commands
```

Commands are listed in [src/tgmate/cli/README.md](src/tgmate/cli/README.md);
planned tools and product decisions are in
[docs/architecture.md](docs/architecture.md).

### Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
   Optionally turn off *Allow Groups* there (the bot leaves groups anyway).
2. Find your numeric Telegram user id (e.g. with
   [@userinfobot](https://t.me/userinfobot)).
3. Configure and start it:

   ```bash
   cp .env.example .env   # set TELEGRAM_BOT_TOKEN and OWNER_USER_ID
   uv run python -m tgmate.telegram
   ```

4. Send `/start` to the bot from your account, so it can DM you approval
   requests. Other people write to the bot, and you approve them from the DM
   or from `/users`.

The database (`data/tgmate.db` by default) is created and migrated on start.
How the bot behaves: [src/tgmate/telegram/README.md](src/tgmate/telegram/README.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/tgmate/tools/` | The tools, independent of any front end |
| `src/tgmate/cli/` | Command-line front end |
| `src/tgmate/telegram/` | Telegram bot front end |
| `src/tgmate/storage/` | The bot's SQLite database and migrations |
| `tests/` | pytest suite |
| `docs/` | Architecture and product decisions |
| `.github/` | CI workflow and Dependabot config |
| `.claude/` | Agent settings and skills (`.agents/skills`, `.cursor/skills` link here) |
| `AGENTS.md` (+ nested) | Agent instructions; each `CLAUDE.md` imports its sibling `AGENTS.md` |
| `.env.example` | Environment variable template |

## Development

The project uses [`uv`](https://docs.astral.sh/uv/) and Python 3.14.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
cp .env.example .env
```

Run any command in the environment with `uv run <cmd>` or after
`source .venv/bin/activate`.

```bash
uv run pytest -q
uv run coverage run -m pytest && uv run coverage report
uv run ruff check .
uv run bandit -c pyproject.toml -r src --severity-level medium
uv run pre-commit run semgrep --hook-stage manual --all-files
uv run pre-commit install
```

After changing dependencies: `uv lock && uv sync`.

| Tool | Purpose | Config |
| --- | --- | --- |
| `ruff` | Linting and import sorting | `[tool.ruff]` in `pyproject.toml` |
| `pytest`, `pytest-asyncio` | Tests | `[tool.pytest.ini_options]` |
| `coverage` | Test coverage | `[tool.coverage.*]` |
| `bandit` | Security scanning | `[tool.bandit]` |
| `semgrep` | Pattern-based scanning (own environment, via pre-commit) | `.semgrep.yml`; version in `.pre-commit-config.yaml` |
| `pre-commit` | Git hooks | `.pre-commit-config.yaml` |

CI (`.github/workflows/ci.yml`) runs lint, tests and security scans on pull
requests and pushes to `main`. Dependabot (`.github/dependabot.yml`) opens
weekly update PRs for dependencies and GitHub Actions.

## Contributing

Branches and commits follow Conventional Commits types (`feat`, `fix`,
`chore`, `docs`, …): branch `<type>/<slug>`, commit `<type>(<scope>): <summary>`.
See [AGENTS.md](AGENTS.md) for the full conventions.

## License

[MIT](LICENSE)
