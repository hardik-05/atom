"""ATOM control plane — Telegram webhook to EC2 start/stop.

Small on purpose. It does four things: verify the caller, start or stop the
tagged instance, read run status from the database, and reply to Telegram.

It holds **no trading logic**, no broker credentials, and no ability to place an
order. Its IAM role cannot reach ``/atom/brokers/*`` or ``/atom/sessions/*``.

That is what bounds the damage of a leaked bot token or a compromised phone to
"someone can turn a computer on and off" — which is why no command here trades
(``docs/02-infrastructure/LAMBDA-AND-TELEGRAM.md`` section 2).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

REGION = os.environ["AWS_REGION"]
INSTANCE_ID = os.environ["ATOM_INSTANCE_ID"]
SSM_PREFIX = os.environ.get("ATOM_SSM_PREFIX", "/atom/telegram")
CONSOLE_URL = os.environ.get("ATOM_CONSOLE_URL", "")

TELEGRAM_API = "https://api.telegram.org"

_ssm = boto3.client("ssm", region_name=REGION)
_ec2 = boto3.client("ec2", region_name=REGION)

_cache: dict[str, str] = {}


def _secret(name: str) -> str:
    """Read a SecureString from SSM, cached for the container's lifetime."""
    if name not in _cache:
        resp = _ssm.get_parameter(Name=f"{SSM_PREFIX}/{name}", WithDecryption=True)
        _cache[name] = resp["Parameter"]["Value"]
    return _cache[name]


def _allowed_user_ids() -> set[int]:
    """Numeric Telegram user IDs, never usernames.

    Usernames can be changed and reused; numeric IDs cannot.
    """
    raw = _secret("allowed_user_ids")
    return {int(part) for part in raw.replace(" ", "").split(",") if part}


def _send(chat_id: int, text: str) -> None:
    token = _secret("bot_token")
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    ).encode()
    req = urllib.request.Request(f"{TELEGRAM_API}/bot{token}/sendMessage", data=payload)
    try:
        urllib.request.urlopen(req, timeout=8).read()
    except urllib.error.URLError as exc:
        # A failed reply must not fail the action that already happened.
        log.warning("telegram sendMessage failed: %s", exc)


def _instance_state() -> str:
    resp = _ec2.describe_instances(InstanceIds=[INSTANCE_ID])
    return resp["Reservations"][0]["Instances"][0]["State"]["Name"]


def _start() -> str:
    state = _instance_state()
    if state == "running":
        return f"Already running.\n{CONSOLE_URL}" if CONSOLE_URL else "Already running."
    if state in ("pending", "stopping"):
        return f"Instance is `{state}` — try again in a moment."
    _ec2.start_instances(InstanceIds=[INSTANCE_ID])
    return (
        "Starting the engine (~90s).\n\n"
        "The console appears once pre-flight passes — if the egress IP check "
        "fails it will deliberately *not* serve."
    )


def _stop(force: bool) -> str:
    state = _instance_state()
    if state == "stopped":
        return "Already stopped."
    if not force:
        # The Lambda cannot see run state without the database, so this is a
        # reminder rather than a hard guard. /status shows the authoritative view.
        _ec2.stop_instances(InstanceIds=[INSTANCE_ID])
        return "Stopping. (Check `/status` first if a run may still be executing.)"
    _ec2.stop_instances(InstanceIds=[INSTANCE_ID], Force=True)
    return "Force-stopping."


def _status() -> str:
    state = _instance_state()
    lines = [f"*Engine:* `{state}`"]
    if state == "running" and CONSOLE_URL:
        lines.append(CONSOLE_URL)
    lines.append("")
    lines.append("_Run status and P&L live in the console; this bot cannot trade._")
    return "\n".join(lines)


HELP = """*ATOM control*

`/start` — bring the engine up
`/stop` — shut it down (`/stop force` to override)
`/status` — instance state and console URL
`/help` — this

Trading actions are only available in the console, where the full context is
visible. That is deliberate.
"""


def _dispatch(text: str) -> str:
    command, _, rest = text.strip().partition(" ")
    command = command.split("@", 1)[0].lower()  # strip @botname in groups

    if command == "/start":
        return _start()
    if command == "/stop":
        return _stop(force=rest.strip().lower() == "force")
    if command == "/status":
        return _status()
    if command == "/help":
        return HELP
    return f"Unknown command `{command}`. Try `/help`."


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Lambda Function URL entry point.

    Replies fast and does the slow part after, because Telegram retries a webhook
    that does not answer within ~60s — which would double-start the instance.
    ``StartInstances`` is idempotent, but not relying on that is better.
    """
    # The Function URL cannot use AWS_IAM auth (Telegram cannot sign requests), so
    # the secret token IS the authentication and is therefore mandatory.
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-telegram-bot-api-secret-token") != _secret("webhook_secret"):
        log.warning("rejected webhook with bad or missing secret token")
        return {"statusCode": 403, "body": "forbidden"}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "bad json"}

    message = body.get("message") or body.get("edited_message") or {}
    user_id = (message.get("from") or {}).get("id")
    chat_id = (message.get("chat") or {}).get("id")
    text = message.get("text") or ""

    if user_id is None or chat_id is None:
        return {"statusCode": 200, "body": "ignored"}

    if user_id not in _allowed_user_ids():
        # Silence, not an error. A bot that answers confirms the token is live;
        # one that says nothing is indistinguishable from a dead token.
        # Log the id and the command only — never the message body.
        log.warning("unauthorised sender %s issued %r", user_id, text.split(" ", 1)[0])
        return {"statusCode": 200, "body": "ignored"}

    try:
        reply = _dispatch(text)
    except Exception:
        log.exception("command failed")
        reply = "Command failed. Check CloudWatch logs for `atom-control`."

    _send(chat_id, reply)
    return {"statusCode": 200, "body": "ok"}
