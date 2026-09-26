"""Process-level settings, read once from the environment.

Non-secret only. Anything secret is an SSM path resolved through
``atom.infra.secrets``; the environment carries at most the name of the backend
to read it from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from atom.domain.errors import ConfigError


@dataclass(frozen=True, slots=True)
class Settings:
    env: str
    """``prod`` or ``dev``. ``prod`` refuses the in-memory secret store."""

    region: str
    public_base_url: str
    """Where the console is served, e.g. ``https://app.metaalgocapital.com``.

    Also the stem of every broker redirect URI, which must match the one
    registered with the broker character for character.
    """

    secret_backend: str
    """``ssm`` or ``memory``."""

    static_dir: Path | None
    """The built SPA. ``None`` serves the API only (tests, local dev with Vite)."""

    activity_marker: Path | None
    """Touched on every authenticated request; read by the idle-shutdown timer."""

    cookie_secure: bool

    data_proxy_url: str | None = None
    """Proxy for token-free vendor downloads (instrument masters, AMFI). On the
    instance this is the first investor's squid port, so even public downloads
    leave from a known address."""

    @property
    def upstox_redirect_uri(self) -> str:
        return f"{self.public_base_url}/brokers/upstox/callback"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        atom_env = source.get("ATOM_ENV", "dev")
        if atom_env not in {"dev", "prod"}:
            raise ConfigError(f"ATOM_ENV must be dev or prod, got {atom_env!r}")
        backend = source.get("ATOM_SECRET_BACKEND", "ssm")
        if backend not in {"ssm", "memory"}:
            raise ConfigError(f"ATOM_SECRET_BACKEND must be ssm or memory, got {backend!r}")
        if atom_env == "prod" and backend != "ssm":
            raise ConfigError("ATOM_ENV=prod requires ATOM_SECRET_BACKEND=ssm")
        base_url = source.get("ATOM_PUBLIC_BASE_URL")
        if not base_url:
            raise ConfigError(
                "ATOM_PUBLIC_BASE_URL is not set. It is the stem of every broker redirect "
                "URI, which must match the registered one exactly, so it has no default."
            )
        if atom_env == "prod" and not base_url.startswith("https://"):
            raise ConfigError("ATOM_PUBLIC_BASE_URL must be https in prod")
        static = source.get("ATOM_STATIC_DIR")
        marker = source.get("ATOM_ACTIVITY_MARKER")
        return cls(
            env=atom_env,
            region=source.get("ATOM_REGION", "ap-south-1"),
            public_base_url=base_url.rstrip("/"),
            secret_backend=backend,
            static_dir=Path(static) if static else None,
            activity_marker=Path(marker) if marker else None,
            cookie_secure=base_url.startswith("https://"),
            data_proxy_url=source.get("ATOM_DATA_PROXY_URL") or None,
        )
