# tgmate package — Agent Instructions

> Scope: `src/tgmate/`. Inherits all repo-wide rules from the root
> [AGENTS.md](../../AGENTS.md); this file adds package-specific conventions.

## Layout
- `tools/` — one module per tool. Each tool is a class whose operations are
  `@staticmethod`s / `@classmethod`s (instance state only when a tool truly
  needs it). Tools take and return plain values and paths; they never import a
  front end.
- `cli/`, `telegram/` (and any future front end) — thin adapters: parse input,
  call the tool's method, present the result. No conversion logic here; a fix
  to a tool's behavior belongs in `tools/` so every front end gets it.
- Each subpackage owns a `README.md` describing its contract once it has
  code; read it before editing and update it when the contract changes.

## Conventions
- Settings are read from the environment once, at the edge, and passed in —
  no module-level reads of `os.environ` deep in the code.
- Tools are synchronous; async front ends offload them (e.g.
  `asyncio.to_thread`) instead of blocking the event loop.
- New runtime dependencies go in `[project].dependencies` pinned with `==`.
