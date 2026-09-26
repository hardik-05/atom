"""The canonical error taxonomy.

Every adapter maps its broker's failures onto exactly one of these. The engine's
retry, alert and abort behaviour keys off the class and nothing else, so adding a
broker never changes the orchestration logic.
"""

from __future__ import annotations


class AtomError(Exception):
    """Base for everything ATOM raises deliberately."""


class BrokerError(AtomError):
    """Base for a failure that came from, or concerns, a broker."""

    #: Whether the engine may retry the same call unchanged.
    retryable: bool = False
    #: Whether this halts the whole run rather than one account.
    halts_everything: bool = False

    def __init__(self, message: str, *, broker: str | None = None, raw: object = None) -> None:
        super().__init__(message)
        self.broker = broker
        self.raw = raw


class AuthError(BrokerError):
    """Token expired, invalid or revoked. Halt this account; regenerate."""


class IpBlockedError(BrokerError):
    """Egress IP not whitelisted.

    Never retried: the address is wrong, not flaky. On Dhan a changed IP cannot
    be re-registered for 7 days, so this is an infrastructure incident (D-173).
    """

    halts_everything = True


class RateLimitError(BrokerError):
    """Throttled. Retried with exponential backoff *and jitter*."""

    retryable = True


class InsufficientFundsError(BrokerError):
    """Not enough cash or margin.

    Deliberately *not* fatal: ATOM records the broker's verbatim reason and
    continues to the next order (D-052). Funds cannot be known reliably ahead of
    the exchange.
    """


class InsufficientHoldingsError(BrokerError):
    """Not enough sellable stock. ATOM's books are wrong — halt and reconcile."""


class AuthorisationRequiredError(BrokerError):
    """Depository authorisation needed before a sell can be placed.

    Upstox EDIS (one-time) and Zerodha's CDSL flow (per trading session).
    Carries the URL the operator must visit, where the broker supplies one.
    """

    def __init__(
        self,
        message: str,
        *,
        broker: str | None = None,
        raw: object = None,
        authorisation_url: str | None = None,
    ) -> None:
        super().__init__(message, broker=broker, raw=raw)
        self.authorisation_url = authorisation_url


class ValidationError(BrokerError):
    """The payload was wrong. A bug — fail loudly, never retry."""


class DuplicateRefError(BrokerError):
    """The ``client_ref`` was already used.

    This is **success, already placed** — not a failure. Groww's ``GA007``.
    Treating it as an error would report a false failure on a good order and,
    worse, invite a re-place.
    """


class TransientError(BrokerError):
    """Network, 5xx, OMS unreachable. Bounded retry, then halt the account."""

    retryable = True


class UnknownError(BrokerError):
    """Unmapped. Halt the account and preserve the raw payload.

    Halting rather than retrying is deliberate: guessing is worse than stopping.
    """


# --------------------------------------------------------------- non-broker


class PreflightError(AtomError):
    """A pre-flight gate failed. Nothing has been sent to any broker."""

    def __init__(self, message: str, *, gate: str, account_id: int | None = None) -> None:
        super().__init__(message)
        self.gate = gate
        self.account_id = account_id


class ReconciliationError(AtomError):
    """ATOM's books disagree with the broker in a way that blocks the run."""


class ConfigError(AtomError):
    """A required configuration value is unset or invalid.

    There are no defaults (D-037): an unset value blocks the run rather than
    quietly falling back to a number nobody chose.
    """


class HarvestError(AtomError):
    """A harvest was attempted that the rules forbid."""
