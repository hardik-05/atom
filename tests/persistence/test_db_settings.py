"""Settings and error helpers — no database required.

The connection itself is exercised in `test_db_integration.py`, which skips
unless ATOM_DATABASE_URL points at a reachable database.
"""

from __future__ import annotations

import pytest

from atom.domain.errors import ConfigError
from atom.persistence.db import DSN_ENV, DbSettings, QueryShapeError, load_settings


def test_missing_dsn_raises_rather_than_defaulting() -> None:
    """D-037: there is no fallback database to quietly connect to."""
    with pytest.raises(ConfigError, match="no default database"):
        load_settings({})


def test_non_url_dsn_is_rejected() -> None:
    """A key=value DSN hides the percent-encoding requirement until it bites.

    The password this project was handed contains '@'. In a URL that must be
    written '%40'; in a key=value string it must not be escaped at all. Accepting
    both forms means the same password is correct in one and silently wrong in
    the other, and the failure arrives as an authentication error that looks like
    a revoked credential.
    """
    with pytest.raises(ConfigError, match="percent-encoded"):
        load_settings({DSN_ENV: "host=db.example.com user=atom password=s3cret"})


def test_url_dsn_is_accepted() -> None:
    settings = load_settings({DSN_ENV: "postgresql://atom:pw%40word@db.example.com:5432/postgres"})
    assert settings.dsn.startswith("postgresql://")
    assert settings.min_size == 1
    assert settings.max_size == 4


def test_pool_sizes_come_from_the_environment() -> None:
    settings = load_settings(
        {
            DSN_ENV: "postgresql://x@y/z",
            "ATOM_DB_POOL_MIN": "2",
            "ATOM_DB_POOL_MAX": "8",
            "ATOM_DB_STATEMENT_TIMEOUT_MS": "5000",
        }
    )
    assert (settings.min_size, settings.max_size) == (2, 8)
    assert settings.statement_timeout_ms == 5000


def test_a_non_numeric_pool_size_is_an_error_not_a_fallback() -> None:
    with pytest.raises(ConfigError, match="must be an integer"):
        load_settings({DSN_ENV: "postgresql://x@y/z", "ATOM_DB_POOL_MAX": "lots"})


def test_settings_never_print_the_dsn() -> None:
    """The password is inside the DSN, and a settings object reaches logs.

    A default dataclass repr would put the credential into every log line that
    formats one, and into every traceback frame that holds one.
    """
    settings = load_settings({DSN_ENV: "postgresql://atom:hunter2@db.example.com/postgres"})
    rendered = repr(settings)
    assert "hunter2" not in rendered
    assert "db.example.com" not in rendered
    assert "<redacted>" in rendered
    # And inside a container, which is how it usually reaches a log line.
    assert "hunter2" not in repr({"db": settings})
    assert "hunter2" not in f"{settings}"


def test_settings_are_frozen() -> None:
    settings = load_settings({DSN_ENV: "postgresql://x@y/z"})
    with pytest.raises((AttributeError, TypeError)):
        settings.dsn = "postgresql://elsewhere"  # type: ignore[misc]


def test_query_shape_error_carries_sql_but_not_parameters() -> None:
    """The message reaches logs; parameters carry account IDs and prices."""
    exc = QueryShapeError(
        "statement affected 0 rows, expected 1",
        sql="-- a comment first\nUPDATE atom.position_lot SET quantity_open = %s WHERE lot_id = %s",
    )
    message = str(exc)
    assert "UPDATE atom.position_lot" in message
    assert "a comment first" not in message  # the first REAL line, not the first line
    assert "expected 1" in message


def test_db_settings_repr_is_stable_enough_to_read() -> None:
    settings = DbSettings(
        dsn="postgresql://x@y/z",
        min_size=1,
        max_size=4,
        connect_timeout_sec=10,
        statement_timeout_ms=30_000,
    )
    assert repr(settings) == (
        "DbSettings(dsn=<redacted>, min_size=1, max_size=4, "
        "connect_timeout_sec=10, statement_timeout_ms=30000)"
    )
