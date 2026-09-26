"""Apply the numbered SQL migrations, in order, through psycopg.

Through the driver rather than by shelling out to ``psql``: the test suite and
the CLI then need nothing installed but the Python package, and there is no
argument-order trap — Windows ``psql`` stops reading options at the first
positional argument, so ``psql <dsn> -f file`` silently runs nothing at all.

Each file runs in its own transaction. A migration that fails part-way leaves
the database exactly as the previous file left it.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("0*.sql"))


def apply_all(
    dsn: str, *, drop_schema_first: bool = False, directory: Path = MIGRATIONS_DIR
) -> list[str]:
    """Returns the names applied. ``drop_schema_first`` is for throwaway databases
    only — it destroys every table in ``atom``."""
    applied = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        if drop_schema_first:
            conn.execute("DROP SCHEMA IF EXISTS atom CASCADE")
        for path in migration_files(directory):
            sql = path.read_text(encoding="utf-8")
            try:
                with conn.transaction():
                    conn.execute(sql.encode())
            except psycopg.Error as exc:
                raise RuntimeError(f"migration {path.name} failed: {exc}") from exc
            applied.append(path.name)
    return applied
