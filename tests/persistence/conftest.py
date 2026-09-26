"""Database fixtures.

Every test in this package needs a real Postgres. It gets one from
``ATOM_TEST_DATABASE_URL`` and skips when that is unset, so the unit suite still
runs on a machine with no database at all.

The fixture applies every migration to a throwaway schema and rolls back after
each test, so the tests exercise the same DDL that was deployed rather than a
simplified stand-in. A constraint that exists only in production is a constraint
nothing has tested.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

MIGRATIONS = Path(__file__).resolve().parents[2] / "atom" / "persistence" / "migrations"
DSN_ENV = "ATOM_TEST_DATABASE_URL"


def _dsn() -> str:
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        pytest.skip(f"{DSN_ENV} is not set")
    return dsn


@pytest.fixture(scope="session")
def migrated_dsn() -> str:
    """Apply every migration once per session, from scratch.

    Drops and recreates the `atom` schema, so this must never point at anything
    holding real data. The DSN is a separate variable from the engine's own
    ``ATOM_DATABASE_URL`` for precisely that reason.
    """
    from atom.persistence.migrate import apply_all

    dsn = _dsn()
    try:
        apply_all(dsn, drop_schema_first=True, directory=MIGRATIONS)
    except RuntimeError as exc:
        pytest.fail(str(exc))
    return dsn


@pytest.fixture
def conn(migrated_dsn: str) -> Iterator[psycopg.Connection]:  # type: ignore[type-arg]
    """A connection whose work is rolled back when the test ends.

    Tests therefore see the seeded reference data from 0016 and never see each
    other's writes, without any per-test cleanup to forget.
    """
    from psycopg.rows import dict_row

    with psycopg.connect(migrated_dsn, row_factory=dict_row) as connection:
        connection.execute("SET search_path TO atom")
        try:
            yield connection
        finally:
            connection.rollback()
