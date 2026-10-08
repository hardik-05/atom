"""Register the investor's Elastic IP with Upstox — the order-traffic whitelist.

    python scripts/upstox_static_ip.py url                    # print the login URL
    python scripts/upstox_static_ip.py apply --code <code>    # token → GET → PUT if needed
    python scripts/upstox_static_ip.py check --code <code>    # token → GET only

Upstox's rules (static-ip-apis announcement, 2026-04-10):
  * the static IP is per Upstox USER, across every app that user owns
  * it can change only ONCE PER CALENDAR WEEK
  * a successful update INVALIDATES every existing access token

Hence the order here: read the current registration first, and update only when
it differs — an update that changes nothing still spends the week's change.
The token lives in this process only and is dead after a successful update
anyway, so it is never stored or printed; neither are the key or the secret,
which are read from the local credentials CSV.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

API = "https://api.upstox.com"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REDIRECT = "https://app.metaalgocapital.com/brokers/upstox/callback"


def credentials(path: Path) -> tuple[str, str]:
    key = secret = None
    for row in csv.reader(path.open(newline="", encoding="utf-8-sig")):
        if len(row) < 2:
            continue
        label = row[0].strip().lower()
        if label.startswith("upstox") and "key" in label:
            key = row[1].strip()
        elif label.startswith("upstox") and "secret" in label:
            secret = row[1].strip()
    if not key or not secret:
        sys.exit(f"no 'Upstox Key' / 'Upstox Secret' rows in {path.name}")
    return key, secret


def code_from(value: str) -> str:
    """Accept either the bare code or the whole redirect URL pasted from the address bar."""
    if value.startswith("http"):
        query = parse_qs(urlparse(value).query)
        if "code" not in query:
            sys.exit("that URL carries no ?code= — the Upstox sign-in did not complete")
        return query["code"][0]
    return value.strip()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["url", "check", "apply"])
    p.add_argument("--code", help="the authorisation code, or the full redirect URL")
    p.add_argument("--primary", default="13.127.7.83")
    p.add_argument("--secondary", default=None,
                   help="optional; if omitted, an existing secondary registration is kept")
    p.add_argument("--redirect-uri", default=DEFAULT_REDIRECT)
    p.add_argument("--csv", default=str(ROOT / "metacap_hdk_accessKeys.csv"))
    a = p.parse_args()
    ipaddress.IPv4Address(a.primary)  # refuse a malformed IP before anything is sent

    key, secret = credentials(Path(a.csv))
    if a.action == "url":
        query = urlencode({"response_type": "code", "client_id": key, "redirect_uri": a.redirect_uri})
        print(f"{API}/v2/login/authorization/dialog?{query}")
        return
    if not a.code:
        sys.exit("--code is required")

    with httpx.Client(timeout=30, verify=True) as http:
        r = http.post(
            f"{API}/v2/login/authorization/token",
            headers={"Accept": "application/json", "Api-Version": "2.0"},
            data={
                "code": code_from(a.code),
                "client_id": key,
                "client_secret": secret,
                "redirect_uri": a.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        body = r.json()
        if r.status_code != 200 or "access_token" not in body:
            errors = body.get("errors") or body
            sys.exit(f"token exchange failed ({r.status_code}): {errors}")
        token = body["access_token"]
        print(f"token: OK for Upstox user {body.get('user_id')} ({body.get('user_name')}), "
              f"poa={body.get('poa')}, active={body.get('is_active')}")

        auth = {"Accept": "application/json", "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"}
        current = http.get(f"{API}/v2/user/ip", headers=auth)
        data = current.json().get("data") or {}
        print(f"GET /v2/user/ip -> {current.status_code}: primary={data.get('primary_ip')} "
              f"(updated {data.get('primary_ip_updated_at')}), secondary={data.get('secondary_ip')} "
              f"(updated {data.get('secondary_ip_updated_at')})")
        if current.status_code != 200:
            sys.exit(f"could not read the registration: {current.text[:300]}")

        if a.action == "check":
            return
        secondary = a.secondary if a.secondary is not None else data.get("secondary_ip")
        if data.get("primary_ip") == a.primary and (a.secondary is None or data.get("secondary_ip") == a.secondary):
            print(f"already registered: primary is {a.primary} — NOT updating, the week's change is kept")
            return

        payload: dict[str, str] = {"primary_ip": a.primary}
        if secondary:
            payload["secondary_ip"] = secondary
        updated = http.put(f"{API}/v2/user/ip", headers=auth, json=payload)
        result = updated.json()
        print(f"PUT /v2/user/ip {payload} -> {updated.status_code}: {result.get('status')}")
        if updated.status_code != 200:
            sys.exit(f"update refused: {result.get('errors') or result}")
        d = result.get("data") or {}
        print(f"now: primary={d.get('primary_ip')}, secondary={d.get('secondary_ip')}, "
              f"tokens invalidated={d.get('access_tokens_invalidated')}")
        print("next: a fresh OAuth login is required — every earlier token is dead")


if __name__ == "__main__":
    main()
