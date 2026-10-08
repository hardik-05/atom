"""ATOM database keep-alive — one query a day so Supabase never pauses the project.

The free tier pauses a project after about a week without activity. A paused
project is not a slow database, it is no database: the pooler answers "tenant/user
not found", the engine fails its startup pool check, and the console serves 502.
The EC2 instance is stopped most of the time, so it cannot be the thing that
keeps the database awake — this function is, on an EventBridge schedule.

It logs in as ``atom_keepalive``, a role with LOGIN and nothing else: no
membership in ``atom_engine``, no grants on the ``atom`` schema. Its DSN lives at
its own SSM path, so this function never holds the engine's credential.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any
from urllib.parse import unquote, urlparse

import boto3
import pg8000.native

log = logging.getLogger()
log.setLevel(logging.INFO)

REGION = os.environ["AWS_REGION"]
DSN_PARAMETER = os.environ["ATOM_KEEPALIVE_DSN_PARAMETER"]

_ssm = boto3.client("ssm", region_name=REGION)


def _connect() -> pg8000.native.Connection:
    dsn = urlparse(
        _ssm.get_parameter(Name=DSN_PARAMETER, WithDecryption=True)["Parameter"]["Value"]
    )
    # sslmode=require semantics, the same as the engine's DSN: encrypted, but the
    # pooler's certificate chains to Supabase's own CA, not a public one.
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        user=unquote(dsn.username or ""),
        password=unquote(dsn.password or ""),
        host=dsn.hostname or "",
        port=dsn.port or 5432,
        database=(dsn.path or "/postgres").lstrip("/") or "postgres",
        ssl_context=tls,
        timeout=20,
    )


def handler(_event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Raise on failure: a failed invocation is what the error metric counts."""
    conn = _connect()
    try:
        [[server_time]] = conn.run("SELECT now()")
    finally:
        conn.close()
    log.info("keep-alive ok at %s", server_time)
    return {"ok": True, "server_time": str(server_time)}
