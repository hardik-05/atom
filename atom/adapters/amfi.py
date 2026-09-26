"""AMFI's daily NAV file — the reference the NAV-premium gate compares against.

Not a broker, but a vendor all the same, so it lives in the adapter layer and
only its parsed output crosses the boundary. The file is public and needs no
credentials.

Format: semicolon-separated, with section headings and blank lines between
AMCs. The column set has changed at least once (Plan and Option were added), so
the parser reads NAV and date from the END of the row and the ISINs from the
two columns after the scheme code — which have stayed put.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from atom.infra.clock import IST

NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


@dataclass(frozen=True, slots=True)
class NavRecord:
    isin: str
    nav: Decimal
    nav_date: date
    scheme_name: str


def parse(text: str) -> dict[str, NavRecord]:
    """ISIN → NAV. A scheme with two ISINs (payout and reinvestment) maps both."""
    out: dict[str, NavRecord] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        try:
            nav = Decimal(parts[-2])
            nav_date = datetime.strptime(parts[-1], "%d-%b-%Y").replace(tzinfo=IST).date()
        except (InvalidOperation, ValueError):
            continue  # "N.A." NAVs and malformed rows carry no price
        if nav <= 0:
            continue
        for isin in (parts[1], parts[2]):
            if len(isin) == 12 and isin.startswith("INF"):
                out[isin] = NavRecord(isin=isin, nav=nav, nav_date=nav_date, scheme_name=parts[3])
    return out


def fetch(*, proxy_url: str | None = None, timeout: float = 60.0) -> dict[str, NavRecord]:
    with httpx.Client(
        proxy=proxy_url, timeout=timeout, verify=True, follow_redirects=True
    ) as client:
        response = client.get(NAV_URL)
        response.raise_for_status()
    return parse(response.text)
