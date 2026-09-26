"""Connection, transaction and query helpers.

The only module that knows what a database connection is. Repositories take a
``Connection`` and never open one; the run owns the transaction and the
repositories join it (MODULE-MAP: SQL lives only in `persistence/`).

Two rules shape everything here:

**The DSN comes from the environment, never from the repository and never from a
table.** It is read once, through ``load_settings``, and the password is never
logged, never repr'd and never carried in an exception message.

**One transaction per run phase.** A phase either completes and commits or fails
and rolls back whole. A partially applied phase would leave the database saying
something the broker does not — which reconciliation would then have to
distinguish from a real fill, and cannot.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from atom.domain.errors import AtomError, ConfigError

T = TypeVar("T")

SCHEMA = "atom"

DSN_ENV = "ATOM_DATABASE_URL"
"""Environment variable holding the connection string.

A URL, so the password is inside it and must be percent-encoded: a password
containing `@` breaks the URL unless it is written `%40`. That is a real trap
and the reason ``load_settings`` checks the DSN parses before the first query
rather than at the first query.
"""


@dataclass(frozen=True, slots=True)
class DbSettings:
    """Everything needed to connect, and nothing that identifies a person."""

    dsn: str
    min_size: int
    max_size: int
    connect_timeout_sec: int
    statement_timeout_ms: int

    def __repr__(self) -> str:
        """Never print the DSN — it contains the password.

        A default dataclass repr puts the credential into every log line that
        formats a settings object, and into every traceback frame that holds one.
        """
        return (
            f"DbSettings(dsn=<redacted>, min_size={self.min_size}, "
            f"max_size={self.max_size}, connect_timeout_sec={self.connect_timeout_sec}, "
            f"statement_timeout_ms={self.statement_timeout_ms})"
        )


def load_settings(env: dict[str, str] | None = None) -> DbSettings:
    """Read the connection settings from the environment.

    Raises rather than defaulting. A missing DSN is a deployment error and
    ATOM has no fallback database to quietly connect to instead (D-037).
    """
    source = os.environ if env is None else env
    dsn = source.get(DSN_ENV)
    if not dsn:
        raise ConfigError(
            f"{DSN_ENV} is not set. ATOM has no default database; "
            f"the connection string must be supplied by the environment."
        )
    if not dsn.startswith(("postgres://", "postgresql://")):
        raise ConfigError(
            f"{DSN_ENV} must be a postgres:// or postgresql:// URL. "
            f"A bare host or a key=value connection string is not accepted, "
            f"because the password in a URL has to be percent-encoded and a "
            f"non-URL form hides that requirement until a password contains '@'."
        )
    return DbSettings(
        dsn=dsn,
        min_size=_int_from(source, "ATOM_DB_POOL_MIN", 1),
        max_size=_int_from(source, "ATOM_DB_POOL_MAX", 4),
        connect_timeout_sec=_int_from(source, "ATOM_DB_CONNECT_TIMEOUT_SEC", 10),
        # A run is a handful of small statements; anything that takes 30 seconds
        # is a bug or a lock, and both are better surfaced than waited on.
        statement_timeout_ms=_int_from(source, "ATOM_DB_STATEMENT_TIMEOUT_MS", 30_000),
    )


def _int_from(source: Any, name: str, fallback: int) -> int:
    raw = source.get(name)
    if raw is None:
        return fallback
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


class QueryShapeError(AtomError):
    """A query returned a different shape of result than the caller required.

    Carries the SQL but never the parameters: parameters carry account
    identifiers and prices, and this exception travels into logs.
    """

    def __init__(self, message: str, *, sql: str) -> None:
        super().__init__(f"{message} — {_first_line(sql)}")
        self.sql = sql


def make_pool(settings: DbSettings) -> ConnectionPool:
    """Build a connection pool.

    ``open=False`` so nothing connects at import time: a module that opens a
    socket when imported makes every test and every CLI ``--help`` depend on a
    reachable database.

    Every connection is configured the same way at checkout, so a query cannot
    depend on which connection it happened to get:

    * ``search_path`` is ``atom`` — but every statement in this codebase still
      writes ``atom.<table>`` in full. The search path is a convenience for a
      human at a psql prompt, never something a query relies on.
    * ``statement_timeout`` bounds a stuck query.
    * ``TimeZone`` is UTC. Every ``timestamptz`` in the schema is stored in UTC
      (D-073c) and IST conversion happens in the presentation layer.
    """

    def configure(conn: Connection[Any]) -> None:
        # Autocommit ON for the duration of the configuration, and only for that.
        #
        # psycopg3 connections are non-autocommit by default, so these SETs would
        # otherwise open a transaction that the pool rolls back when the
        # connection is returned — quietly discarding every setting below. The
        # search path and the timeout would then apply to the first checkout of
        # each connection and to nothing after it, which is the kind of bug that
        # only shows up under load.
        conn.autocommit = True
        conn.execute(f"SET search_path TO {SCHEMA}")
        conn.execute(f"SET statement_timeout TO {settings.statement_timeout_ms}")
        conn.execute("SET TimeZone TO 'UTC'")
        # Back to explicit transactions for real work. Safe here because
        # autocommit mode leaves no transaction open to conflict with the change.
        conn.autocommit = False

    return ConnectionPool(
        conninfo=settings.dsn,
        min_size=settings.min_size,
        max_size=settings.max_size,
        timeout=settings.connect_timeout_sec,
        configure=configure,
        kwargs={"row_factory": dict_row},
        open=False,
    )


@contextmanager
def transaction(pool: ConnectionPool) -> Iterator[Connection[Any]]:
    """One unit of work: commits on success, rolls back on any exception.

    Repositories take the yielded connection. They do not commit, and they do not
    know whether they are the only writer in the transaction — which is what lets
    a run phase compose several of them and still be atomic.
    """
    with pool.connection() as conn, conn.transaction():
        yield conn


def fetch_all(
    conn: Connection[Any], sql: str, params: Sequence[Any] | dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_one(
    conn: Connection[Any], sql: str, params: Sequence[Any] | dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """The first row, or None. Does NOT assert the query returned only one."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_exactly_one(
    conn: Connection[Any], sql: str, params: Sequence[Any] | dict[str, Any] | None = None
) -> dict[str, Any]:
    """The one row this query must return.

    Raises if there are none or more than one. Use it wherever the caller's next
    line would have assumed a single row anyway — an assumption that fails
    loudly here beats one that fails three frames later as a ``KeyError`` on a
    dictionary that turned out to be the wrong row.
    """
    rows = fetch_all(conn, sql, params)
    if len(rows) != 1:
        raise QueryShapeError(
            f"expected exactly one row, got {len(rows)}",
            sql=sql,
        )
    return rows[0]


def execute(
    conn: Connection[Any], sql: str, params: Sequence[Any] | dict[str, Any] | None = None
) -> int:
    """Run a statement and return the number of rows it touched."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def execute_expecting(
    conn: Connection[Any],
    sql: str,
    params: Sequence[Any] | dict[str, Any] | None,
    rows: int,
) -> None:
    """Run a statement that must touch exactly ``rows`` rows.

    An UPDATE that matches nothing is the quietest bug in this system: it
    succeeds, commits, and leaves the database describing a world that has moved
    on. Anywhere the count is known in advance, state it.
    """
    touched = execute(conn, sql, params)
    if touched != rows:
        raise QueryShapeError(
            f"statement affected {touched} rows, expected {rows}",
            sql=sql,
        )


def _first_line(sql: str) -> str:
    for line in sql.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return stripped[:120]
    return "<empty statement>"


def is_unique_violation(exc: BaseException) -> bool:
    """Whether an exception is a duplicate-key error.

    Used by the order path: a duplicate ``idempotency_key`` means the order was
    already written before the send (D-094), which is not a failure to report but
    a state to resolve by looking at what the broker has.
    """
    return isinstance(exc, psycopg.errors.UniqueViolation)


def is_check_violation(exc: BaseException) -> bool:
    """Whether an exception is a CHECK constraint failure.

    Every CHECK in the schema encodes a decision, so this is always a bug in the
    layer above rather than bad input to be retried — see
    ``atom/persistence/migrations/`` for what each one refuses and why.
    """
    return isinstance(exc, psycopg.errors.CheckViolation)


def constraint_name(exc: BaseException) -> str | None:
    """The constraint a database error names, if it names one."""
    diag = getattr(exc, "diag", None)
    return None if diag is None else diag.constraint_name
