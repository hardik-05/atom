"""``client_ref`` generation — one identifier ATOM sends to every broker.

The format is fixed by the intersection of five brokers' constraints (D-175):

* **Groww** requires 8-20 alphanumeric characters with at most two hyphens, and
  rejects a duplicate with ``GA007`` — which is what makes a retry exact.
* **Zerodha** caps its ``tag`` at 20 alphanumeric characters.
* Dhan allows 30 (``correlationId``), Upstox and Shoonya are unconstrained.

So Groww's floor and Zerodha's ceiling together define the canonical format, and
it is enforced here rather than in any one adapter.
"""

from __future__ import annotations

import re
from datetime import date

MIN_LEN = 8
MAX_LEN = 20
MAX_HYPHENS = 2

_ALLOWED = re.compile(r"^[A-Za-z0-9-]+$")

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


class ClientRefError(ValueError):
    """The reference would be rejected by at least one broker."""


def _base36(value: int, width: int) -> str:
    if value < 0:
        raise ClientRefError("cannot encode a negative value")
    out = ""
    while value:
        value, rem = divmod(value, 36)
        out = _BASE36[rem] + out
    return out.rjust(width, "0")[-width:]


def make_client_ref(*, trade_date: date, run_id: int, sequence: int) -> str:
    """A deterministic reference for one order within one run.

    ``atm{YYMMDD}{run}{seq}`` in base36 — deterministic so that a retry after a
    timeout produces the *same* reference, which is what makes Groww's duplicate
    rejection a recovery mechanism rather than a nuisance.

    >>> make_client_ref(trade_date=date(2026, 9, 26), run_id=8871, sequence=3)
    'atm26092606uf03'
    """
    stamp = f"{trade_date.year % 100:02d}{trade_date.month:02d}{trade_date.day:02d}"
    ref = f"atm{stamp}{_base36(run_id, 4)}{_base36(sequence, 2)}"
    validate_client_ref(ref)
    return ref


def validate_client_ref(ref: str) -> None:
    """Raise unless ``ref`` satisfies every broker's constraints."""
    if not MIN_LEN <= len(ref) <= MAX_LEN:
        raise ClientRefError(
            f"client_ref must be {MIN_LEN}-{MAX_LEN} chars, got {len(ref)}: {ref!r}"
        )
    if not _ALLOWED.match(ref):
        raise ClientRefError(f"client_ref must be alphanumeric with hyphens, got {ref!r}")
    if ref.count("-") > MAX_HYPHENS:
        raise ClientRefError(f"client_ref may carry at most {MAX_HYPHENS} hyphens, got {ref!r}")


def truncate_for(ref: str, max_len: int) -> str:
    """Fit a reference to a broker's own limit.

    Truncation keeps the **tail**, because the sequence number is the part that
    distinguishes two orders in the same run.
    """
    validate_client_ref(ref)
    return ref if len(ref) <= max_len else ref[-max_len:]
