"""Canonical models — the complete vocabulary between the adapter layer and
everything above it.

All frozen dataclasses. Nothing here performs I/O, reads configuration, or knows
which broker it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from atom.domain.enums import (
    BasisKind,
    CashEventType,
    ChargeSource,
    GttStatus,
    OrderStatus,
    Product,
    Provenance,
    SellAuthScope,
    Side,
    StaticIpScope,
    TokenProbe,
    Validity,
)
from atom.domain.money import ZERO

# --------------------------------------------------------------------------- refs


@dataclass(frozen=True, slots=True)
class AccountRef:
    """What an adapter needs to act for one account. No secrets — only a path."""

    trading_account_id: int
    broker_code: str
    broker_client_id: str
    proxy_url: str | None
    egress_ip: str | None
    secret_ref: str | None
    """SSM parameter path. Never the token itself (D-079)."""

    extra: dict[str, str] = field(default_factory=dict)
    """Broker-specific non-secret identifiers, e.g. Zerodha's api_key."""


# -------------------------------------------------------------------- instruments


@dataclass(frozen=True, slots=True)
class CanonicalInstrument:
    """One row of a broker's instrument master, normalised.

    ``isin`` is the join key. A row without one is never matched on symbol alone
    (the single exception is Zerodha's curated seed, D-187) — symbols collide
    across exchanges and are renamed by corporate actions.
    """

    symbol: str
    exchange: str
    name: str
    broker_token: str
    broker_symbol: str
    isin: str | None = None
    lot_size: int = 1
    tick_size: Decimal | None = None
    """Informational only. Pricing uses ATOM's own tick size (D-209)."""

    tradable: bool = True
    instrument_type: str | None = None
    broker_flags: dict[str, object] = field(default_factory=dict)


# ----------------------------------------------------------------------- holdings


@dataclass(frozen=True, slots=True)
class CanonicalHolding:
    """One instrument's position at a broker.

    Two quantities, two jobs (D-182):

    * ``total_quantity`` answers *do our books agree with the broker's* and feeds
      the attribution identity.
    * ``free_quantity`` answers *can this sell actually execute* and caps the sell
      pass. ``None`` means the broker does not publish it, in which case the
      caller falls back to the total **and logs that it is doing so**.
    """

    instrument_id: int
    total_quantity: int
    average_price: Decimal
    free_quantity: int | None = None
    last_price: Decimal | None = None
    pledged_quantity: int = 0
    unsettled_quantity: int = 0
    broker_flags: dict[str, object] = field(default_factory=dict)

    @property
    def sellable(self) -> int:
        """The cap for the sell pass. Falls back to the total when unpublished."""
        return self.total_quantity if self.free_quantity is None else self.free_quantity

    @property
    def free_quantity_is_assumed(self) -> bool:
        """True when the sellable figure is a fallback, not the broker's own.

        The caller must log this: it is the case where a foreseeable rejection
        becomes possible again.
        """
        return self.free_quantity is None


# ------------------------------------------------------------------------- orders


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """What ATOM wants to do. Always a limit order (D-174), always delivery (D-207)."""

    trading_account_id: int
    universe_id: int
    instrument_id: int
    side: Side
    quantity: int
    limit_price: Decimal
    client_ref: str
    """ATOM-generated, 8-20 alphanumeric with at most two hyphens (D-175).

    The lower bound comes from Groww, the upper from Zerodha; together they fix
    the format that satisfies all five brokers.
    """

    product: Product = Product.DELIVERY
    validity: Validity = Validity.DAY
    algo_id: str | None = None
    """Reserved and unset. No Algo ID is required (D-181)."""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.limit_price <= ZERO:
            raise ValueError(f"limit_price must be positive, got {self.limit_price}")


@dataclass(frozen=True, slots=True)
class OrderState:
    """What the broker says about an order."""

    broker_order_id: str
    status: OrderStatus
    raw_status: str
    """Preserved verbatim for forensics, and because status maps are incomplete."""

    filled_quantity: int = 0
    pending_quantity: int = 0
    average_price: Decimal | None = None
    client_ref: str | None = None
    reject_reason: str | None = None
    """The broker's own words, never paraphrased (D-042)."""


@dataclass(frozen=True, slots=True)
class CanonicalFill:
    """One execution. The lot grain (D-166) — never aggregated before persisting."""

    broker_order_id: str
    broker_trade_id: str
    quantity: int
    fill_price: Decimal
    filled_at: datetime

    def __post_init__(self) -> None:
        if self.filled_at.tzinfo is None:
            raise ValueError("filled_at must be timezone-aware")


# ---------------------------------------------------------------------------- GTT


@dataclass(frozen=True, slots=True)
class GttIntent:
    """A resting sell. ATOM only ever places sell GTTs."""

    instrument_id: int
    quantity: int
    trigger_price: Decimal
    limit_price: Decimal
    client_ref: str
    side: Side = Side.SELL
    last_price: Decimal | None = None
    """Required at placement by Zerodha, ignored elsewhere."""

    def __post_init__(self) -> None:
        if self.side is not Side.SELL:
            raise ValueError("ATOM only places sell GTTs")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")


@dataclass(frozen=True, slots=True)
class GttState:
    """A GTT as the broker reports it.

    ``is_ours`` is computed by the engine, never taken from the broker. Where the
    broker carries a ``client_ref`` (Dhan, Groww) it is matched; where it does not
    (Zerodha, Upstox) only ATOM's own stored id can decide (D-176). An unknown GTT
    is never cancelled — it may be the investor's own (D-064).
    """

    broker_gtt_id: str
    status: GttStatus
    raw_status: str
    client_ref: str | None = None
    instrument_id: int | None = None
    trigger_price: Decimal | None = None
    quantity: int | None = None
    is_ours: bool = False
    broker_flags: dict[str, object] = field(default_factory=dict)


# ------------------------------------------------------------------------ charges


@dataclass(frozen=True, slots=True)
class CanonicalCharges:
    """A charge breakdown from one source.

    ``source`` is what makes the estimated-vs-reported contrast possible (D-024):
    both a ``COMPUTED`` and a ``BROKER`` set coexist for the same order.
    """

    source: ChargeSource
    brokerage: Decimal = ZERO
    stt: Decimal = ZERO
    exchange: Decimal = ZERO
    sebi: Decimal = ZERO
    stamp: Decimal = ZERO
    gst: Decimal = ZERO
    dp: Decimal = ZERO
    provisional: bool = False
    """True while the rate table is unverified (Q-313). Surfaced in the UI."""

    @property
    def total(self) -> Decimal:
        return (
            self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst + self.dp
        )


# --------------------------------------------------------------------------- cash


@dataclass(frozen=True, slots=True)
class CanonicalCashEvent:
    """One line of a broker ledger.

    ``UNKNOWN`` is a first-class outcome: an unrecognised narration is stored as
    ``UNKNOWN`` and surfaced for classification, never guessed into a bucket that
    would silently corrupt the cost-of-capital model.
    """

    event_date: date
    amount: Decimal
    """Signed: positive is a credit, negative a debit."""

    event_type: CashEventType
    narration: str
    running_balance: Decimal | None = None
    """Dhan's ``runbal`` — the reconciliation anchor. No other broker supplies it."""

    broker_ref: str | None = None


# -------------------------------------------------------------------------- quote


@dataclass(frozen=True, slots=True)
class CanonicalQuote:
    instrument_id: int
    last_price: Decimal
    as_of: datetime
    close_price: Decimal | None = None
    volume: int | None = None

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")


# -------------------------------------------------------------------------- funds


@dataclass(frozen=True, slots=True)
class CanonicalFunds:
    """Cash at a broker, as the broker reports it.

    ``available_cash`` is what the broker says can be spent on a delivery buy now.
    It is informational: funds cannot be known reliably ahead of the exchange, so
    a buy the broker rejects for funds is recorded, not prevented (D-052).
    ``components`` keeps the broker's own named figures for display, so nothing
    is summed into a number the broker never published.
    """

    available_cash: Decimal
    used_margin: Decimal
    as_of: datetime
    components: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")


# ------------------------------------------------------------------------- candle


@dataclass(frozen=True, slots=True)
class CanonicalCandle:
    """One daily bar. The deviation metric is computed from ``close``."""

    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None

    def __post_init__(self) -> None:
        if self.close <= 0:
            raise ValueError(f"close must be positive, got {self.close}")
        if self.high < self.low:
            raise ValueError(f"high {self.high} below low {self.low} on {self.trade_date}")


# ------------------------------------------------------------------------ profile


@dataclass(frozen=True, slots=True)
class BrokerProfile:
    """Who a token belongs to.

    Checked against the account the token was generated FOR: a code pasted into
    the wrong account's screen would otherwise bind one investor's broker session
    to another investor's ledger.
    """

    broker_client_id: str
    display_name: str
    is_active: bool
    flags: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------- lot


@dataclass(frozen=True, slots=True)
class OpenLot:
    """An open position lot, as the strategy layer sees it.

    Two cost bases (D-190). ``synthetic_cost_basis`` is ``None`` for every lot
    ATOM bought normally, and set only on a harvest proxy, where it carries the
    capital committed to the security that was harvested (D-188).
    """

    lot_id: int
    instrument_id: int
    universe_id: int
    quantity_open: int
    unit_cost: Decimal
    acquired_on: date
    synthetic_cost_basis: Decimal | None = None
    provenance: Provenance = Provenance.ATOM

    def __post_init__(self) -> None:
        if self.quantity_open <= 0:
            raise ValueError(f"an open lot needs positive quantity, got {self.quantity_open}")

    @property
    def is_harvest_proxy(self) -> bool:
        """True when this lot carries forward another security's committed capital.

        Such a lot can never itself be harvested (D-193), and it forms its own
        sell tranche (D-195).
        """
        return self.synthetic_cost_basis is not None

    @property
    def strategy_cost(self) -> Decimal:
        """The basis the sell trigger and deviation use."""
        return self.unit_cost if self.synthetic_cost_basis is None else self.synthetic_cost_basis


# ------------------------------------------------------------------------- tranche


@dataclass(frozen=True, slots=True)
class SellTranche:
    """A slice of a position sold against one basis (D-195).

    A position whose lots mix synthetic and actual cost bases cannot be sold
    against one blended average: the proxy units would exit below the capital
    they are recovering and the shortfall would be booked as a gain. At most two
    tranches per (account, universe, instrument) — synthetic lots blend with each
    other, and only the boundary between the two bases splits.
    """

    instrument_id: int
    basis_kind: BasisKind
    quantity: int
    basis_price: Decimal
    target_price: Decimal
    lot_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.basis_kind is BasisKind.TAXABLE:
            raise ValueError("a sell tranche is SYNTHETIC or ACTUAL, never TAXABLE")
        if self.quantity <= 0:
            raise ValueError(f"tranche quantity must be positive, got {self.quantity}")


# ---------------------------------------------------------------------- session


@dataclass(frozen=True, slots=True)
class TokenProbeResult:
    ok: bool
    probe_used: TokenProbe
    detail: str = ""
    token_validity: str | None = None
    flags: dict[str, object] = field(default_factory=dict)
    """e.g. Dhan's ``ddpi`` / ``dataPlan``, Zerodha's ``demat_consent``."""


@dataclass(frozen=True, slots=True)
class Token:
    secret_ref: str
    """Where the token was stored. The value itself never lives in a model."""

    obtained_at: datetime
    broker_client_id: str | None = None
    flags: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuthorisationRequest:
    """A depository authorisation the operator must complete."""

    url: str
    request_id: str | None = None
    scope: SellAuthScope = SellAuthScope.PER_SESSION


# ------------------------------------------------------------------- capabilities


@dataclass(frozen=True, slots=True)
class BrokerCapabilities:
    """What one broker can do.

    Every field is a research finding made machine-readable, so the engine adapts
    to a broker without ever branching on its name.
    """

    broker_code: str

    # GTT
    supports_gtt: bool
    gtt_carries_client_ref: bool
    gtt_max_validity_days: int | None = None

    # orders
    client_ref_field: str | None = None
    client_ref_max_len: int = 20
    client_ref_is_idempotent: bool = False
    lookup_by_client_ref: bool = False

    # data
    provides_trade_charges: bool = False
    provides_charge_preview: bool = False
    provides_ledger: bool = False
    provides_free_quantity: bool = False

    # infrastructure
    requires_static_ip: bool = True
    static_ip_scope: StaticIpScope = StaticIpScope.ALL_CALLS
    static_ip_lock_days: int = 0
    token_probe_endpoint: TokenProbe = TokenProbe.HOLDINGS
    token_revocable: bool = False
    sell_authorisation_scope: SellAuthScope = SellAuthScope.NONE

    # limits
    orders_per_second: int = 10
    quote_batch_size: int | None = None

    @property
    def requires_sell_authorisation(self) -> bool:
        """Whether a separate demat authorisation is needed before a sell.

        Derived rather than stored, so the flag and the scope cannot disagree.
        Upstox needs one per instruction (eDIS, ``ONE_TIME``) and Zerodha one per
        session (``PER_SESSION``); the other three need none.
        """
        return self.sell_authorisation_scope is not SellAuthScope.NONE

    @property
    def egress_needs_separate_check(self) -> bool:
        """True when a token probe cannot prove the egress IP is right.

        Dhan whitelists *writes* only, so a token probes green from the wrong
        address and the first order still fails — with no IP-specific error code
        (D-173, Q-305). This is why egress verification is its own pre-flight gate.
        """
        return self.requires_static_ip and self.static_ip_scope is StaticIpScope.ORDERS_ONLY
