"""Run the database changes listed in db/changes.csv (see db/README.md).

    python scripts/db_changes.py install|uninstall|redeploy [--dry-run]

The DSN comes from ATOM_ADMIN_DATABASE_URL and is never printed.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGES = ROOT / "db" / "changes.csv"


def load(path: Path = CHANGES) -> tuple[list[Path], list[Path]]:
    installs: list[Path] = []
    uninstalls: list[Path] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.reader(fh), start=1):
            if not row or not "".join(row).strip():
                continue
            if len(row) != 2 or row[0].strip() not in ("install", "uninstall"):
                raise ValueError(f"{path.name} line {n}: expected 'install,<file>' or 'uninstall,<file>'")
            kind, name = row[0].strip(), row[1].strip()
            target = ROOT / name
            if not target.is_file():
                raise ValueError(f"{path.name} line {n}: {name} does not exist")
            if kind == "install":
                if uninstalls:
                    raise ValueError(f"{path.name} line {n}: install rows must precede uninstall rows")
                installs.append(target)
            else:
                uninstalls.append(target)
    return installs, uninstalls


def run(files: list[Path], dsn: str | None, dry_run: bool) -> None:
    if dry_run or not files:
        for f in files:
            print("would run", f.relative_to(ROOT))
        return
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:  # type: ignore[arg-type]
        for f in files:
            try:
                with conn.transaction():
                    conn.execute(f.read_text(encoding="utf-8").encode())
            except psycopg.Error as exc:
                sys.exit(f"{f.relative_to(ROOT)} failed: {exc}")
            print("ran", f.relative_to(ROOT))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["install", "uninstall", "redeploy"])
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    installs, uninstalls = load()
    dsn = os.environ.get("ATOM_ADMIN_DATABASE_URL")
    if not dsn and not a.dry_run:
        sys.exit("set ATOM_ADMIN_DATABASE_URL (a role with DDL rights, not atom_api)")
    if a.action in ("uninstall", "redeploy"):
        run(uninstalls, dsn, a.dry_run)
    if a.action in ("install", "redeploy"):
        run(installs, dsn, a.dry_run)


if __name__ == "__main__":
    main()
