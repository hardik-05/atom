#!/usr/bin/env python3
"""
Verify that each account's traffic leaves from that investor's static IPv4.

This is the health check for the single hardest assumption in ATOM's
infrastructure (D-005/D-007): one EC2 instance, several Elastic IPs, and every
broker call for an investor egressing from *their* whitelisted address.

Vendor-independent by design (D-143). Two brokers happen to expose an egress-IP
endpoint — Upstox /v2/user/ip and Dhan /ip/getIP — but relying on those would
leave three brokers unverified and couple the check to broker availability and a
valid token. This script needs neither.

    for each configured account:
        call an IP-echo service THROUGH that account's proxy
        assert the echoed address == the investor's expected Elastic IP

Run it:
  * at engine startup, before any order is placed (fail closed)
  * after any change to proxies, ENIs or Elastic IPs
  * from CI against a staging instance

Exit code 0 = every account verified. Non-zero = at least one mismatch, and no
trading should proceed.

Config (JSON):
[
  {"account": "personA-upstox", "proxy": "http://127.0.0.1:3128", "expected_ip": "13.234.x.x"},
  {"account": "personB-dhan",   "proxy": "http://127.0.0.1:3129", "expected_ip": "13.235.y.y"}
]

Usage:
    python3 scripts/verify_egress_ip.py accounts.json [--timeout 10]
"""
import json
import sys
import urllib.request

# Independent echo services. Several, because agreement between two providers
# rules out one of them being wrong or stale; checkip.amazonaws.com is first as
# it is AWS-operated and returns a bare address.
ECHO_SERVICES = [
    ("checkip.amazonaws.com", "https://checkip.amazonaws.com"),
    ("ipify",                 "https://api.ipify.org"),
    ("icanhazip",             "https://icanhazip.com"),
]


def fetch_via_proxy(url, proxy, timeout):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy, "http": proxy})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "atom-egress-check/1"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore").strip()


def observed_ip(proxy, timeout):
    """Return (ip, service) from the first echo service that answers."""
    errors = []
    for name, url in ECHO_SERVICES:
        try:
            ip = fetch_via_proxy(url, proxy, timeout)
            if ip:
                return ip, name, errors
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return None, None, errors


def main(config_path, timeout):
    accounts = json.load(open(config_path, encoding="utf-8"))
    width = max((len(a["account"]) for a in accounts), default=10)
    failures = []

    print(f"Verifying egress for {len(accounts)} account(s)\n")
    for acc in accounts:
        name = acc["account"]
        expected = acc["expected_ip"].strip()
        ip, service, errors = observed_ip(acc["proxy"], timeout)

        if ip is None:
            print(f"  {name:<{width}}  ERROR   no echo service reachable through the proxy")
            for e in errors:
                print(f"  {'':<{width}}          {e}")
            failures.append((name, "unreachable", expected, None))
            continue

        if ip == expected:
            print(f"  {name:<{width}}  ✅ OK    {ip}   (via {service})")
        else:
            print(f"  {name:<{width}}  ❌ WRONG expected {expected}, got {ip}   (via {service})")
            failures.append((name, "mismatch", expected, ip))

    # A duplicate address across accounts means the per-account split is not working
    # at all, even if each address individually matched what was configured.
    seen = {}
    for acc in accounts:
        ip, _, _ = observed_ip(acc["proxy"], timeout)
        if ip:
            seen.setdefault(ip, []).append(acc["account"])
    shared = {ip: names for ip, names in seen.items() if len(names) > 1}
    if shared:
        print("\n  ⚠️  SHARED ADDRESSES — per-account egress is NOT isolated:")
        for ip, names in shared.items():
            print(f"       {ip}  ←  {', '.join(names)}")
            failures.append((", ".join(names), "shared", ip, ip))

    print()
    if failures:
        print(f"FAILED — {len(failures)} problem(s). Do not trade until resolved.")
        return 1
    print("All accounts verified. Egress isolation confirmed.")
    return 0


def parse_args(argv):
    timeout, positional, i = 10, [], 0
    while i < len(argv):
        if argv[i] == "--timeout":
            if i + 1 >= len(argv):
                sys.exit("--timeout needs a value")
            timeout = int(argv[i + 1])
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    if len(positional) != 1:
        sys.exit(__doc__)
    return positional[0], timeout


if __name__ == "__main__":
    config_path, timeout = parse_args(sys.argv[1:])
    sys.exit(main(config_path, timeout))
