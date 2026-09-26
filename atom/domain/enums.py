"""Canonical enumerations.

Every value here is ATOM's own vocabulary. Broker-specific codes are mapped onto
these at the adapter boundary and never appear above it (D-185).
"""

from __future__ import annotations

from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderKind(StrEnum):
    """Order types ATOM is permitted to place.

    ``MARKET`` is deliberately absent: market orders have not been permitted via
    Indian broker APIs since 1 April 2026, and ATOM places limit orders only
    (D-174). Its absence from this enum is the enforcement.
    """

    LIMIT = "LIMIT"
    GTT = "GTT"


class Product(StrEnum):
    """Only delivery. No margin, MTF, intraday or leverage anywhere (D-207)."""

    DELIVERY = "DELIVERY"


class Validity(StrEnum):
    DAY = "DAY"


class OrderStatus(StrEnum):
    """Canonical order lifecycle.

    ``IN_FLIGHT`` is the mandatory default for any broker status ATOM does not
    recognise (D-180). Mapping an unknown status to a terminal state would make
    ATOM re-place an order that is about to fill.
    """

    INTENT = "INTENT"
    PLACED = "PLACED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    IN_FLIGHT = "IN_FLIGHT"

    @property
    def is_terminal(self) -> bool:
        return self in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


class GttStatus(StrEnum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_live(self) -> bool:
        return self is GttStatus.ACTIVE


class BasisKind(StrEnum):
    """Which cost basis a figure was computed against (D-190).

    No monetary return is ever presented without one of these.
    """

    SYNTHETIC = "SYNTHETIC"
    ACTUAL = "ACTUAL"
    TAXABLE = "TAXABLE"


class ExecutionMode(StrEnum):
    DRY = "DRY"
    LIVE = "LIVE"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunType(StrEnum):
    EXECUTE = "EXECUTE"
    UNIVERSE_JOB = "UNIVERSE_JOB"
    HARVEST = "HARVEST"
    AVERAGE = "AVERAGE"


class RunPhase(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    REFERENCE = "REFERENCE"
    RECONCILE = "RECONCILE"
    SELL = "SELL"
    BUY = "BUY"
    HARVEST = "HARVEST"
    SETTLE = "SETTLE"


class ChargeType(StrEnum):
    BROKERAGE = "BROKERAGE"
    STT = "STT"
    EXCHANGE = "EXCHANGE"
    SEBI = "SEBI"
    STAMP = "STAMP"
    GST = "GST"
    DP = "DP"


class ChargeSource(StrEnum):
    """Both coexist for one order — that contrast is the feature (D-024)."""

    COMPUTED = "COMPUTED"
    BROKER = "BROKER"


class CashEventType(StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    SETTLEMENT = "SETTLEMENT"
    CHARGE = "CHARGE"
    UNKNOWN = "UNKNOWN"


class Provenance(StrEnum):
    """Whether ATOM created a lot, or found it (D-062, D-137)."""

    ATOM = "ATOM"
    EXTERNAL = "EXTERNAL"


class CapitalBucket(StrEnum):
    DEPLOYED = "DEPLOYED"
    SETTLEMENT = "SETTLEMENT"
    IDLE = "IDLE"


class Decision(StrEnum):
    BOUGHT = "BOUGHT"
    SOLD = "SOLD"
    SKIPPED = "SKIPPED"
    NOT_CONSIDERED = "NOT_CONSIDERED"


class SellAuthScope(StrEnum):
    NONE = "NONE"
    ONE_TIME = "ONE_TIME"
    PER_SESSION = "PER_SESSION"


class StaticIpScope(StrEnum):
    ORDERS_ONLY = "ORDERS_ONLY"
    ALL_CALLS = "ALL_CALLS"


class TokenProbe(StrEnum):
    PROFILE = "PROFILE"
    HOLDINGS = "HOLDINGS"
