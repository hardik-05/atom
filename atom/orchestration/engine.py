"""The engine context: the pool, the secret store, settings, and adapters.

Adapters are built per unit of work, because the ``InstrumentResolver`` each
one is given is bound to that unit's database connection. An adapter that
outlived its transaction would resolve against a connection already returned
to the pool.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from atom.adapters.base import BrokerAdapter
from atom.domain.errors import ConfigError
from atom.infra.secrets import SecretStore
from atom.infra.settings import Settings
from atom.persistence.repositories import instruments

AdapterFactory = Callable[[str, "Connection[Any]", "Engine"], BrokerAdapter]


def default_adapter_factory(
    broker_code: str, conn: Connection[Any], engine: Engine
) -> BrokerAdapter:
    resolver = instruments.DbInstrumentResolver(conn, instruments.broker_id_for(conn, broker_code))
    if broker_code == "UPSTOX":
        from atom.adapters.upstox import UpstoxAdapter

        return UpstoxAdapter(
            secrets=engine.secrets,
            resolver=resolver,
            redirect_uri=engine.settings.upstox_redirect_uri,
            default_proxy_url=engine.settings.data_proxy_url,
        )
    raise ConfigError(
        f"the {broker_code} adapter is not built yet — Upstox is the first broker wired end to end"
    )


@dataclass
class Engine:
    pool: ConnectionPool
    secrets: SecretStore
    settings: Settings
    adapter_factory: AdapterFactory = field(default=default_adapter_factory)

    def adapter(self, broker_code: str, conn: Connection[Any]) -> BrokerAdapter:
        return self.adapter_factory(broker_code, conn, self)


def close_adapter(adapter: object) -> None:
    close = getattr(adapter, "close", None)
    if callable(close):
        close()
