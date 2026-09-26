"""The ASGI entry point: ``uvicorn atom.web.main:app``.

Everything is assembled from the environment and SSM at import time — the
settings, the secret store, the database pool, the engine and the job runner —
and a missing piece fails the process at start, loudly, rather than on the
first request.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from atom.infra.secrets import DATABASE_DSN, MemorySecretStore, SecretStore, SsmSecretStore
from atom.infra.settings import Settings
from atom.orchestration.engine import Engine
from atom.orchestration.jobs import JobRunner
from atom.persistence.db import DSN_ENV, load_settings, make_pool
from atom.web.app import create_app


def _secret_store(settings: Settings) -> SecretStore:
    if settings.secret_backend == "ssm":
        return SsmSecretStore(region=settings.region)
    # Development only — Settings refuses this combination in prod. Values come
    # from a local JSON file that is gitignored like every other credential file.
    initial: dict[str, str] = {}
    dev_file = os.environ.get("ATOM_DEV_SECRETS_FILE")
    if dev_file:
        initial = json.loads(Path(dev_file).read_text(encoding="utf-8"))
    return MemorySecretStore(initial)


def build() -> FastAPI:
    settings = Settings.from_env()
    secrets = _secret_store(settings)
    dsn = os.environ.get(DSN_ENV) or secrets.get(DATABASE_DSN)
    pool = make_pool(load_settings({**os.environ, DSN_ENV: dsn}))
    jobs = JobRunner()
    engine = Engine(pool=pool, secrets=secrets, settings=settings)
    app = create_app(engine, jobs)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pool.open(wait=True, timeout=30)
        try:
            yield
        finally:
            jobs.shutdown()
            pool.close()

    app.router.lifespan_context = lifespan
    return app


app = build() if os.environ.get("ATOM_SKIP_APP_BUILD") != "1" else FastAPI()
