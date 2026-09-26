"""Point the console's hostname at the Elastic IP, through Cloudflare's API.

    python scripts/cloudflare_dns.py                      # app.metaalgocapital.com -> 13.127.7.83
    python scripts/cloudflare_dns.py --check              # show, change nothing

The API token is read from SSM ``/ops/cloudflare/dns_token`` inside this process
and never printed. It lives OUTSIDE ``/atom/*`` on purpose: the engine's
instance role can read ``/atom/*``, and an engine that could rewrite DNS could
send the operator's browser — and their console password — anywhere.

The record is DNS-only (``proxied: false``). With Cloudflare's proxy on, the
browser would terminate TLS at Cloudflare and Caddy's certificate would never
reach it; the threat model assumes TLS end to end.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

import boto3
import httpx

API = "https://api.cloudflare.com/client/v4"
TOKEN_PATH = "/ops/cloudflare/dns_token"


def token(profile: str, region: str) -> str:
    ssm = boto3.Session(profile_name=profile, region_name=region).client("ssm")
    try:
        return str(ssm.get_parameter(Name=TOKEN_PATH, WithDecryption=True)["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        sys.exit(f"{TOKEN_PATH} is not set — run: python -m atom.cli cloudflare-token")


def cf(client: httpx.Client, method: str, path: str, **kw: object) -> dict:  # type: ignore[type-arg]
    r = client.request(method, f"{API}{path}", **kw)  # type: ignore[arg-type]
    body = r.json()
    if not body.get("success"):
        errors = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in body.get("errors", []))
        sys.exit(f"Cloudflare {method} {path} failed: {errors or r.status_code}")
    return body  # type: ignore[no-any-return]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--zone", default="metaalgocapital.com")
    p.add_argument("--name", default="app.metaalgocapital.com")
    p.add_argument("--ip", default="13.127.7.83")
    p.add_argument("--check", action="store_true")
    p.add_argument("--profile", default="atom")
    p.add_argument("--region", default="ap-south-1")
    a = p.parse_args()

    headers = {"Authorization": f"Bearer {token(a.profile, a.region)}"}
    with httpx.Client(headers=headers, timeout=30) as client:
        verify = cf(client, "GET", "/user/tokens/verify")["result"]
        print(f"token: {verify.get('status')}")
        zones = cf(client, "GET", "/zones", params={"name": a.zone})["result"]
        if not zones:
            sys.exit(f"token cannot see zone {a.zone} — give it Zone:Read on that zone")
        zone_id = zones[0]["id"]
        records = cf(client, "GET", f"/zones/{zone_id}/dns_records", params={"name": a.name})["result"]
        for r in records:
            print(f"existing: {r['type']} {r['name']} -> {r['content']} proxied={r['proxied']}")
        if a.check:
            return

        conflicting = [r for r in records if r["type"] in ("CNAME", "AAAA")]
        if conflicting:
            sys.exit(f"{a.name} already has {[r['type'] for r in conflicting]} records — "
                     "remove them by hand; this script will not delete records it did not create")

        desired = {
            "type": "A",
            "name": a.name,
            "content": a.ip,
            "proxied": False,
            "ttl": 300,
            "comment": "ATOM console — Elastic IP of the engine instance. DNS-only: TLS ends at Caddy.",
        }
        a_records = [r for r in records if r["type"] == "A"]
        if a_records:
            rec = a_records[0]
            if rec["content"] == a.ip and not rec["proxied"]:
                print("already correct — nothing changed")
            else:
                cf(client, "PUT", f"/zones/{zone_id}/dns_records/{rec['id']}", json=desired)
                print(f"updated: A {a.name} -> {a.ip} (DNS only)")
        else:
            cf(client, "POST", f"/zones/{zone_id}/dns_records", json=desired)
            print(f"created: A {a.name} -> {a.ip} (DNS only)")

    for _ in range(24):
        try:
            got = socket.gethostbyname(a.name)
            if got == a.ip:
                print(f"resolves: {a.name} -> {got}")
                return
            print(f"resolves to {got}, waiting…")
        except socket.gaierror:
            print("not resolving yet, waiting…")
        time.sleep(5)
    print("record is set; local resolvers have not caught up yet (TTL 300s)")


if __name__ == "__main__":
    main()
