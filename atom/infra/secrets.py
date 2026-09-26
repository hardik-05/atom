"""Secrets: where they live, and the only code that reads or writes them.

Every secret is an SSM ``SecureString`` encrypted with the project's own KMS key
(SECRETS-MANAGEMENT.md). The database stores the *path*, never the value
(D-079), and nothing in this module logs, repr's or returns a value except
through ``get``.

Paths are defined here and nowhere else, because a typo in a path is a secret
written somewhere nothing will ever read it from — or, worse, somewhere a
broader IAM grant does.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from atom.domain.errors import ConfigError

PLACEHOLDER = "set-me"
"""What Terraform writes so a parameter exists before the operator sets it."""

# ----------------------------------------------------------------- paths


def broker_secret_path(broker_code: str, trading_account_id: int, name: str) -> str:
    """Long-lived broker credentials: ``api_key``, ``api_secret``, ``totp``, ``pin``.

    Written by the OPERATOR from their own machine. The engine's IAM role can read
    ``/atom/*`` but write only ``/atom/sessions/*``, so a compromised engine can
    neither overwrite a broker key nor plant its own.
    """
    if name not in {"api_key", "api_secret", "totp", "pin"}:
        raise ValueError(f"unknown broker secret {name!r}")
    return f"/atom/brokers/{broker_code.lower()}/{trading_account_id}/{name}"


def session_path(trading_account_id: int, trade_date: date) -> str:
    """Today's broker token for one account. Created each morning, deleted after."""
    return f"/atom/sessions/{trading_account_id}/{trade_date.isoformat()}"


CONSOLE_USERNAME = "/atom/console/username"
CONSOLE_PASSWORD_HASH = "/atom/console/password_hash"
CONSOLE_TOTP = "/atom/console/totp"
CONSOLE_SESSION_KEY = "/atom/console/session_key"
DATABASE_DSN = "/atom/db/dsn"


class SecretNotFoundError(ConfigError):
    """A secret the engine needs has not been set.

    A ``ConfigError`` because that is what it is: nothing is broken, the operator
    has a step to do. The message names the path so the fix is one command.
    """

    def __init__(self, path: str) -> None:
        super().__init__(
            f"secret {path} is not set. Set it with: "
            f"aws ssm put-parameter --name {path} --type SecureString "
            f"--key-id alias/atom --overwrite --value <value>"
        )
        self.path = path


# ----------------------------------------------------------------- stores


class SecretStore(Protocol):
    def get(self, path: str) -> str:
        """The value, or ``SecretNotFoundError``."""
        ...

    def put(self, path: str, value: str) -> None: ...

    def delete(self, path: str) -> None:
        """Idempotent: deleting a secret that is already gone is not an error."""
        ...

    def exists(self, path: str) -> bool: ...


class MemorySecretStore:
    """For tests and local development. Refused when ``ATOM_ENV=prod``."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values: dict[str, str] = dict(initial or {})

    def get(self, path: str) -> str:
        value = self._values.get(path)
        if value is None or value == PLACEHOLDER:
            raise SecretNotFoundError(path)
        return value

    def put(self, path: str, value: str) -> None:
        if not value:
            raise ValueError(f"refusing to store an empty secret at {path}")
        self._values[path] = value

    def delete(self, path: str) -> None:
        self._values.pop(path, None)

    def exists(self, path: str) -> bool:
        return self._values.get(path) not in (None, PLACEHOLDER)

    def __repr__(self) -> str:
        return f"MemorySecretStore(<{len(self._values)} secrets>)"


class SsmSecretStore:
    """SSM Parameter Store, SecureString, encrypted with ``alias/atom``."""

    def __init__(self, *, region: str, kms_key_id: str = "alias/atom", client: Any = None) -> None:
        if client is None:
            import boto3  # deferred: nothing imports the AWS SDK until it is needed

            client = boto3.client("ssm", region_name=region)
        self._ssm = client
        self._kms_key_id = kms_key_id

    def get(self, path: str) -> str:
        try:
            response = self._ssm.get_parameter(Name=path, WithDecryption=True)
        except self._ssm.exceptions.ParameterNotFound:
            raise SecretNotFoundError(path) from None
        value: str = response["Parameter"]["Value"]
        if value == PLACEHOLDER:
            # The placeholder Terraform writes so the parameter exists. Treating it
            # as a real value would e.g. try to log in with the password "set-me".
            raise SecretNotFoundError(path)
        return value

    def put(self, path: str, value: str) -> None:
        if not value:
            raise ValueError(f"refusing to store an empty secret at {path}")
        self._ssm.put_parameter(
            Name=path, Value=value, Type="SecureString", KeyId=self._kms_key_id, Overwrite=True
        )

    def delete(self, path: str) -> None:
        try:
            self._ssm.delete_parameter(Name=path)
        except self._ssm.exceptions.ParameterNotFound:
            return

    def exists(self, path: str) -> bool:
        try:
            self.get(path)
        except SecretNotFoundError:
            return False
        return True

    def __repr__(self) -> str:
        return f"SsmSecretStore(kms_key_id={self._kms_key_id!r})"
