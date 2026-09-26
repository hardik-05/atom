"""Which public address traffic actually leaves from.

The pre-flight egress gate (RUN-LIFECYCLE.md 3.1). It asks a neutral service —
not a broker — what source address it sees *through the account's proxy*, and
the answer is compared with the Elastic IP registered for that investor.

It is a separate check from the token probe on purpose. On Dhan the IP
whitelist gates order placement only, so a token probes green from the wrong
address and the first order is the first thing to fail — with no IP-specific
error code to say why (D-173, Q-305).
"""

from __future__ import annotations

import ipaddress

import httpx

CHECK_URL = "https://checkip.amazonaws.com"


class EgressCheckError(RuntimeError):
    """The address could not be determined at all. Treated as a mismatch."""


def observed_egress_ip(proxy_url: str | None, *, timeout: float = 10.0) -> str:
    try:
        with httpx.Client(proxy=proxy_url, timeout=timeout, verify=True) as client:
            response = client.get(CHECK_URL)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EgressCheckError(f"could not determine egress address: {exc}") from exc
    text = response.text.strip()
    try:
        return str(ipaddress.ip_address(text))
    except ValueError as exc:
        raise EgressCheckError(
            f"egress check returned something that is not an IP: {text[:40]!r}"
        ) from exc
