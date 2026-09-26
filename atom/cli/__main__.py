"""Operator commands, run from the operator's OWN machine with their AWS profile.

    python -m atom.cli console-setup
    python -m atom.cli broker-secret --account-id 1 --broker UPSTOX
    python -m atom.cli db-login --role atom_api
    python -m atom.cli migrate --dsn-from-ssm

Secrets are typed at a hidden prompt and go straight to SSM. None is echoed,
logged or written to disk — and none is ever pasted into a chat window, which
is how two of this project's credentials were exposed.

These run from the laptop, not the instance, on purpose: the engine's IAM role
can write only ``/atom/sessions/*``, so it could not set a console password or
a broker key even if something on the instance tried.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import secrets as pysecrets
import sys

from atom.infra import secrets as paths
from atom.infra.secrets import SsmSecretStore
from atom.web import security


def _store(args: argparse.Namespace) -> SsmSecretStore:
    import boto3

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    return SsmSecretStore(region=args.region, client=session.client("ssm"))


def _prompt(label: str, *, confirm: bool = False, min_len: int = 1) -> str:
    while True:
        value = getpass.getpass(f"{label}: ")
        if len(value) < min_len:
            print(f"  must be at least {min_len} characters")
            continue
        if confirm and getpass.getpass(f"{label} (again): ") != value:
            print("  did not match")
            continue
        return value


def console_setup(args: argparse.Namespace) -> None:
    store = _store(args)
    username = input("Console username: ").strip()
    if len(username) < 3:
        sys.exit("username too short")
    password = _prompt("Console password (12+ characters)", confirm=True, min_len=12)
    totp = security.new_totp_secret()
    store.put(paths.CONSOLE_USERNAME, username)
    store.put(paths.CONSOLE_PASSWORD_HASH, security.hash_password(password))
    store.put(paths.CONSOLE_TOTP, totp)
    store.put(paths.CONSOLE_SESSION_KEY, pysecrets.token_urlsafe(48))
    print("\nStored in SSM. Add this to your authenticator app — as a setup key:\n")
    print(f"  account : ATOM ({username})")
    print(f"  key     : {' '.join(totp[i : i + 4] for i in range(0, len(totp), 4))}")
    print("  type    : time-based, 6 digits")
    print(f"\n  or as a URI: {security.otpauth_uri(totp, account=username)}")
    print("\nThis is the only time the key is shown. Clear the terminal when done.")


def broker_secret(args: argparse.Namespace) -> None:
    store = _store(args)
    for name, label in (("api_key", "API key"), ("api_secret", "API secret")):
        value = _prompt(f"{args.broker} {label} for account {args.account_id}").strip()
        store.put(paths.broker_secret_path(args.broker, args.account_id, name), value)
    print(f"stored under /atom/brokers/{args.broker.lower()}/{args.account_id}/")


def _scram_verifier(password: str, *, iterations: int = 4096) -> str:
    """A SCRAM-SHA-256 verifier, which Postgres accepts in place of a password.

    Sending the VERIFIER to the database — never the password — means the SQL
    that creates the login can be run through any channel, including one that
    keeps a transcript, without exposing the credential it sets.
    """
    salt = pysecrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = base64.b64encode
    return (
        f"SCRAM-SHA-256${iterations}:{b64(salt).decode()}$"
        f"{b64(stored_key).decode()}:{b64(server_key).decode()}"
    )


def db_login(args: argparse.Namespace) -> None:
    """Generate a login password, store the DSN in SSM, print the SQL to run.

    The printed SQL carries only the SCRAM verifier. The password itself exists
    in this process and in the SSM parameter, and nowhere else.
    """
    store = _store(args)
    password = pysecrets.token_urlsafe(32)
    from urllib.parse import quote

    user = f"{args.role}.{args.project_ref}" if args.pooler else args.role
    dsn = (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{args.host}:{args.port}/"
        f"postgres?sslmode=require"
    )
    store.put(paths.DATABASE_DSN, dsn)
    verifier = _scram_verifier(password)
    print("DSN stored at", paths.DATABASE_DSN)
    print("\nRun this SQL once (it contains a verifier, not the password):\n")
    print(
        "DO $$ BEGIN\n"
        f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{args.role}') THEN\n"
        f"    CREATE ROLE {args.role} LOGIN IN ROLE atom_engine;\n  END IF;\nEND $$;"
    )
    print(f"ALTER ROLE {args.role} WITH LOGIN PASSWORD '{verifier}';")
    print(f"ALTER ROLE {args.role} SET search_path = atom;")


def migrate(args: argparse.Namespace) -> None:
    from atom.persistence.migrate import apply_all

    dsn = _store(args).get(paths.DATABASE_DSN) if args.dsn_from_ssm else _prompt("DSN")
    for name in apply_all(dsn):
        print("applied", name)


CLOUDFLARE_TOKEN = "/ops/cloudflare/dns_token"
"""Outside /atom/* on purpose: the engine's role reads /atom/*, and an engine that
could rewrite DNS could send the operator's browser, and password, anywhere."""


def cloudflare_token(args: argparse.Namespace) -> None:
    store = _store(args)
    value = _prompt("Cloudflare API token (Zone:DNS:Edit on metaalgocapital.com)", min_len=20)
    store.put(CLOUDFLARE_TOKEN, value.strip())
    print(f"stored at {CLOUDFLARE_TOKEN} — the engine cannot read this path")


def main() -> None:
    parser = argparse.ArgumentParser(prog="atom")
    parser.add_argument("--profile", default="atom")
    parser.add_argument("--region", default="ap-south-1")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("console-setup", help="set the console username, password and TOTP")

    b = sub.add_parser("broker-secret", help="store a broker app's API key and secret")
    b.add_argument("--account-id", type=int, required=True)
    b.add_argument(
        "--broker", required=True, choices=["UPSTOX", "DHAN", "ZERODHA", "GROWW", "SHOONYA"]
    )

    d = sub.add_parser("db-login", help="create the engine's database login")
    d.add_argument("--role", default="atom_api")
    d.add_argument("--host", required=True)
    d.add_argument("--port", type=int, default=5432)
    d.add_argument("--project-ref", default="njcnttyafolmuqwgixfq")
    d.add_argument(
        "--pooler",
        action="store_true",
        help="connecting through Supavisor, which wants user.project_ref",
    )

    m = sub.add_parser("migrate", help="apply migrations to the configured database")
    m.add_argument("--dsn-from-ssm", action="store_true")

    sub.add_parser("cloudflare-token", help="store a scoped Cloudflare DNS token")

    args = parser.parse_args()
    {
        "console-setup": console_setup,
        "broker-secret": broker_secret,
        "db-login": db_login,
        "migrate": migrate,
        "cloudflare-token": cloudflare_token,
    }[args.command](args)


if __name__ == "__main__":
    main()
