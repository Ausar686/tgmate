# storage

SQLAlchemy 2 async persistence on SQLite (aiosqlite). Schema in
[models.py](models.py), query helpers in [repo.py](repo.py), engine and
migrations in [db.py](db.py).

## Tables
| Table | Key | Holds |
| --- | --- | --- |
| `users` | Telegram user id | `full_name`, `username` (refreshed on every message), access `status` |

## Invariants
- User `status`: `pending` (waiting for the owner), `approved`, `rejected`
  (owner said no), `revoked` (owner withdrew approval). Only `approved` users
  can use the tools; the owner is never stored and always allowed. See
  [telegram](../telegram/README.md) for the transitions.
- Datetimes are stored as naive UTC and returned as aware UTC
  (`UTCDateTime`); binding a naive datetime raises.

## Migrations
- The bot applies them at startup (`db.upgrade`), so deploying is enough.
- After changing models, generate one from the repo root and review it:
  `uv run alembic revision --autogenerate -m "<what changed>"`. It reads
  `DATABASE_URL` (default `data/tgmate.db`); point it at a database that is
  at the current head.
- `tests/storage/test_migrations.py` fails when models and migrations differ.
