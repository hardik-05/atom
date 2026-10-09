"""Which instruments of a category are tradable: the top N by average volume.

Built when market data is synced, never during a run (D-112/D-113 amended). Volume is the
only thing that qualifies an instrument; a run then decides on price and NAV alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal


def pick(
    volumes: Mapping[int, tuple[Decimal, int]],
    symbols: Mapping[int, str],
    *,
    size: int,
    window: int,
    threshold: Decimal,
) -> list[tuple[int, int, Decimal, int]]:
    """``[(instrument_id, rank, average volume, days)]``, best first.

    An instrument qualifies with a full ``window`` of volume days and an average at or above
    ``threshold`` units. Ties break on symbol, so the same data gives the same list.
    """
    eligible = [
        (iid, avg, days)
        for iid, (avg, days) in volumes.items()
        if iid in symbols and days >= window and avg >= threshold
    ]
    eligible.sort(key=lambda r: (-r[1], symbols[r[0]]))
    return [(iid, rank, avg, days) for rank, (iid, avg, days) in enumerate(eligible[:size], 1)]
