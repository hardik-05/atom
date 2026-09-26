"""The fully resolved configuration a run decides against.

Built once, at run start, from raw stored values and frozen into
``run.config_snapshot`` (D-061). Nothing re-reads live config mid-run.

No defaults, anywhere (D-037). A required key with no stored value blocks the
run, and every missing key is reported at once — an operator fixing config one
error per attempt would learn to stop reading the errors.

An explicit NULL is different from absent (D-039). On a per-category key it
means "do not buy this category"; sells continue (D-068). On an account or
global key it has no agreed meaning, so it is refused as though absent rather
than guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from atom.domain.errors import ConfigError

CATEGORY_KEYS = (
    "profit_target_pct",
    "depth_levels",
    "trade_amount_inr",
    "lookback_days",
    "average_method",
    "category_enabled",
    "nav_check_enabled",
    "nav_premium_tolerance_pct",
    "volume_threshold_units",
    "volume_window_days",
)
ACCOUNT_KEYS = (
    "category_priority",
    "daily_spend_cap_inr",
    "max_orders_per_run",
    "dry_run",
    "budget_buffer_pct",
    "buy_limit_premium_pct",
)
GLOBAL_KEYS = ("kill_switch", "market_open_gate_time")

StoredValue = tuple[bool, str | None]
"""``(is_set, value_text)``. ``(True, None)`` is an explicit NULL."""


@dataclass(frozen=True, slots=True)
class CategoryConfig:
    category: str
    buying_enabled: bool
    """False when switched off — by ``category_enabled = false`` or an explicit
    NULL on any buy-side key. Sells for the category still run."""

    disabled_reason: str | None
    profit_target_pct: Decimal
    depth_levels: int
    trade_amount_inr: Decimal
    lookback_days: int
    average_method: str
    nav_check_enabled: bool
    nav_premium_tolerance_pct: Decimal | None
    volume_threshold_units: Decimal
    volume_window_days: int


@dataclass(frozen=True, slots=True)
class RunConfig:
    categories: dict[str, CategoryConfig]
    category_priority: tuple[str, ...]
    daily_spend_cap_inr: Decimal
    max_orders_per_run: int
    dry_run: bool
    budget_buffer_pct: Decimal
    buy_limit_premium_pct: Decimal
    kill_switch: bool
    market_open_gate_time: str

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe, for ``run.config_snapshot``. Decimals as strings, so a
        re-read reproduces the exact value rather than a float approximation."""

        def clean(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [clean(v) for v in value]
            return value

        return clean(asdict(self))  # type: ignore[no-any-return]


# ------------------------------------------------------------------ parsing


def _dec(key: str, raw: str) -> Decimal:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{key} must be a number, got {raw!r}") from exc


def _int(key: str, raw: str) -> int:
    value = _dec(key, raw)
    if value != value.to_integral_value():
        raise ValueError(f"{key} must be a whole number, got {raw!r}")
    return int(value)


def _bool(key: str, raw: str) -> bool:
    text = raw.strip().lower()
    if text in {"true", "t", "yes", "1"}:
        return True
    if text in {"false", "f", "no", "0"}:
        return False
    raise ValueError(f"{key} must be true or false, got {raw!r}")


def resolve(
    *,
    universe_categories: Sequence[str],
    account_values: Mapping[tuple[str, str | None], StoredValue],
    global_values: Mapping[str, StoredValue],
) -> RunConfig:
    """Assemble and validate. Raises ``ConfigError`` naming EVERY problem."""
    missing: list[str] = []
    invalid: list[str] = []

    def account(key: str) -> str | None:
        is_set, value = account_values.get((key, None), (False, None))
        if not is_set or value is None:
            missing.append(key)
            return None
        return value

    def glob(key: str) -> str | None:
        is_set, value = global_values.get(key, (False, None))
        if not is_set or value is None:
            missing.append(f"{key} (global)")
            return None
        return value

    def parse(key: str, raw: str | None, fn: Any) -> Any:
        if raw is None:
            return None
        try:
            return fn(key, raw)
        except ValueError as exc:
            invalid.append(str(exc))
            return None

    categories: dict[str, CategoryConfig] = {}
    for cat in universe_categories:
        raw: dict[str, str | None] = {}
        switched_off: list[str] = []
        for key in CATEGORY_KEYS:
            is_set, value = account_values.get((key, cat), (False, None))
            if not is_set:
                missing.append(f"{key} [{cat}]")
            elif value is None:
                switched_off.append(key)
            raw[key] = value
        # A NULL on the NAV tolerance is only meaningful when the check is off.
        nav_on = parse("nav_check_enabled", raw["nav_check_enabled"], _bool)
        if nav_on is False and "nav_premium_tolerance_pct" in switched_off:
            switched_off.remove("nav_premium_tolerance_pct")
        enabled_flag = parse("category_enabled", raw["category_enabled"], _bool)
        reason = None
        if switched_off:
            reason = f"explicitly switched off: {', '.join(switched_off)} set to NULL"
        elif enabled_flag is False:
            reason = "category_enabled is false"
        buying = reason is None
        target = parse("profit_target_pct", raw["profit_target_pct"], _dec)
        depth = parse("depth_levels", raw["depth_levels"], _int)
        amount = parse("trade_amount_inr", raw["trade_amount_inr"], _dec)
        lookback = parse("lookback_days", raw["lookback_days"], _int)
        method = raw["average_method"]
        tolerance = parse("nav_premium_tolerance_pct", raw["nav_premium_tolerance_pct"], _dec)
        volume = parse("volume_threshold_units", raw["volume_threshold_units"], _dec)
        window = parse("volume_window_days", raw["volume_window_days"], _int)

        # CONFIGURATION-MODEL.md section 5 — rejected, not discovered at run time.
        if target is not None and not (0 < target <= 100):
            invalid.append(f"profit_target_pct [{cat}] must be > 0 and <= 100, got {target}")
        if depth is not None and not (1 <= depth <= 20):
            invalid.append(f"depth_levels [{cat}] must be 1-20, got {depth}")
        if amount is not None and amount <= 0:
            invalid.append(f"trade_amount_inr [{cat}] must be positive, got {amount}")
        if lookback is not None and lookback < 2:
            invalid.append(f"lookback_days [{cat}] must be at least 2, got {lookback}")
        if method is not None and method not in {"MEAN", "MEDIAN"}:
            invalid.append(f"average_method [{cat}] must be MEAN or MEDIAN, got {method!r}")
        if tolerance is not None and tolerance < 0:
            invalid.append(f"nav_premium_tolerance_pct [{cat}] must be >= 0, got {tolerance}")
        if volume is not None and volume < 0:
            invalid.append(f"volume_threshold_units [{cat}] must be >= 0, got {volume}")
        if window is not None and window < 1:
            invalid.append(f"volume_window_days [{cat}] must be at least 1, got {window}")

        if buying and None in (target, depth, amount, lookback, method, nav_on, volume, window):
            continue  # already reported as missing or invalid
        categories[cat] = CategoryConfig(
            category=cat,
            buying_enabled=buying,
            disabled_reason=reason,
            profit_target_pct=target if target is not None else Decimal(0),
            depth_levels=depth or 0,
            trade_amount_inr=amount if amount is not None else Decimal(0),
            lookback_days=lookback or 0,
            average_method=method or "MEAN",
            nav_check_enabled=bool(nav_on),
            nav_premium_tolerance_pct=tolerance,
            volume_threshold_units=volume if volume is not None else Decimal(0),
            volume_window_days=window or 0,
        )

    priority_raw = account("category_priority")
    cap = parse("daily_spend_cap_inr", account("daily_spend_cap_inr"), _dec)
    max_orders = parse("max_orders_per_run", account("max_orders_per_run"), _int)
    dry_run = parse("dry_run", account("dry_run"), _bool)
    buffer = parse("budget_buffer_pct", account("budget_buffer_pct"), _dec)
    premium = parse("buy_limit_premium_pct", account("buy_limit_premium_pct"), _dec)
    kill = parse("kill_switch", glob("kill_switch"), _bool)
    gate_time = glob("market_open_gate_time")

    priority: tuple[str, ...] = ()
    if priority_raw is not None:
        priority = tuple(p.strip() for p in priority_raw.split(",") if p.strip())
        if sorted(priority) != sorted(universe_categories) or len(set(priority)) != len(priority):
            invalid.append(
                f"category_priority must be a permutation of {list(universe_categories)}, "
                f"got {list(priority)}"
            )
    if cap is not None and cap <= 0:
        invalid.append(f"daily_spend_cap_inr must be positive, got {cap}")
    if max_orders is not None and max_orders < 1:
        invalid.append(f"max_orders_per_run must be at least 1, got {max_orders}")
    if buffer is not None and not (0 < buffer <= 100):
        invalid.append(f"budget_buffer_pct must be > 0 and <= 100, got {buffer}")
    if premium is not None and not (0 <= premium <= 5):
        invalid.append(f"buy_limit_premium_pct must be 0-5, got {premium}")
    if cap is not None:
        for c in categories.values():
            if c.buying_enabled and c.trade_amount_inr > cap:
                invalid.append(
                    f"trade_amount_inr [{c.category}] {c.trade_amount_inr} exceeds "
                    f"daily_spend_cap_inr {cap}"
                )
    if gate_time is not None:
        try:
            hh, mm = gate_time.split(":")
            if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                raise ValueError
        except ValueError:
            invalid.append(f"market_open_gate_time must be HH:MM, got {gate_time!r}")

    if missing or invalid:
        lines = []
        if missing:
            lines.append("not configured: " + "; ".join(missing))
        if invalid:
            lines.append("invalid: " + "; ".join(invalid))
        raise ConfigError(" | ".join(lines))

    assert cap is not None and max_orders is not None and dry_run is not None
    assert buffer is not None and premium is not None and kill is not None and gate_time
    return RunConfig(
        categories=categories,
        category_priority=priority,
        daily_spend_cap_inr=cap,
        max_orders_per_run=max_orders,
        dry_run=dry_run,
        budget_buffer_pct=buffer,
        buy_limit_premium_pct=premium,
        kill_switch=kill,
        market_open_gate_time=gate_time,
    )
