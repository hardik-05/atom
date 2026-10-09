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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

REGION = os.environ["AWS_REGION"]
INSTANCE_ID = os.environ["ATOM_INSTANCE_ID"]
SSM_PREFIX = os.environ.get("ATOM_SSM_PREFIX", "/atom/telegram")
CONSOLE_URL = os.environ.get("ATOM_CONSOLE_URL", "")
# Hard ceiling on one start-to-stop session, in minutes. Set in Terraform
# (max_runtime_minutes); 0 disables it.
MAX_RUNTIME_MINUTES = int(os.environ.get("ATOM_MAX_RUNTIME_MINUTES", "60"))

# After a start: how long to wait for the site, and how often to look. A cold boot
# plus pre-flight is ~90s; four minutes leaves room without hanging around.
SITE_WAIT_SECONDS = int(os.environ.get("ATOM_SITE_WAIT_SECONDS", "240"))
SITE_POLL_SECONDS = 10

TELEGRAM_API = "https://api.telegram.org"

_ssm = boto3.client("ssm", region_name=REGION)
_ec2 = boto3.client("ec2", region_name=REGION)
_lambda = boto3.client("lambda", region_name=REGION)

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


# Three buttons under the message box; tapping one sends its label as text.
KEYBOARD = {
    "keyboard": [[{"text": "Status"}, {"text": "Start"}, {"text": "Stop"}]],
    "resize_keyboard": True,
    "is_persistent": True,
}


def _send(chat_id: int, text: str) -> None:
    token = _secret("bot_token")
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,  # plain text: instance names and IPs contain Markdown characters
            "reply_markup": json.dumps(KEYBOARD),
        }
    ).encode()
    req = urllib.request.Request(f"{TELEGRAM_API}/bot{token}/sendMessage", data=payload)
    try:
        urllib.request.urlopen(req, timeout=8).read()
    except urllib.error.URLError as exc:
        # A failed reply must not fail the action that already happened.
        log.warning("telegram sendMessage failed: %s", exc)


def _instance() -> dict[str, Any]:
    return _ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"][0]["Instances"][0]


def _instance_state() -> str:
    return str(_instance()["State"]["Name"])


def _public_ip(inst: dict[str, Any]) -> str:
    """The address, even while stopped: an Elastic IP stays attached but the instance
    itself then reports none."""
    if inst.get("PublicIpAddress"):
        return str(inst["PublicIpAddress"])
    try:
        found = _ec2.describe_addresses(Filters=[{"Name": "instance-id", "Values": [INSTANCE_ID]}])
        return str(found["Addresses"][0]["PublicIp"]) if found["Addresses"] else "none"
    except (ClientError, IndexError, KeyError):
        return "unknown"


def _info() -> str:
    inst = _instance()
    state = inst["State"]["Name"]
    name = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), "-")
    lines = [
        "ℹ️ EC2 Runtime Metadata",
        "",
        f"🏷️ Name: {name}",
        f"🆔 ID: {INSTANCE_ID}",
        f"📈 State: {state}",
        f"⚙️ Type: {inst.get('InstanceType', '-')}",
        f"🌐 Public IP: {_public_ip(inst)}",
        f"🔒 Private IP: {inst.get('PrivateIpAddress', '-')}",
    ]
    if state == "running":
        up = int((datetime.now(UTC) - inst["LaunchTime"]).total_seconds() // 60)
        limit = f", stops automatically at {MAX_RUNTIME_MINUTES} min" if MAX_RUNTIME_MINUTES else ""
        lines.append(f"⏱️ Uptime: {up} min{limit}")
        if CONSOLE_URL:
            lines.append(f"🔗 {CONSOLE_URL}")
    return "\n".join(lines)


def _site_up() -> bool:
    """True when the console answers its health check over HTTPS."""
    try:
        with urllib.request.urlopen(f"{CONSOLE_URL}/api/health", timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False  # not listening yet, or TLS not ready: both mean "not up"


def _announce_when_up(chat_id: int) -> dict[str, Any]:
    """Poll the console after a start, then tell the chat whether it is serving.

    Runs as a separate asynchronous invocation, so the Telegram webhook that asked
    for the start has long since been answered.
    """
    deadline = time.monotonic() + SITE_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _site_up():
            _send(chat_id, f"✅ The site is up!\n🔗 {CONSOLE_URL}")
            return {"site_up": True}
        time.sleep(SITE_POLL_SECONDS)
    _send(
        chat_id,
        f"⚠️ The engine is running but the site is not answering after {SITE_WAIT_SECONDS // 60} "
        "min. Pre-flight (the egress IP check) may have failed, which deliberately stops "
        "the console serving. Check the atom-engine logs in CloudWatch.",
    )
    return {"site_up": False}


def _start(chat_id: int, who: str) -> str:
    _send(chat_id, f"🔄 {who} initiated an EC2 start...")
    state = _instance_state()
    if state == "running":
        return f"✅ Instance {INSTANCE_ID} is already running!" + (
            f"\n🔗 {CONSOLE_URL}" if CONSOLE_URL else ""
        )
    if state in ("pending", "stopping"):
        return f"⏳ Instance is {state}. Try again in a moment."
    _ec2.start_instances(InstanceIds=[INSTANCE_ID])
    if CONSOLE_URL:
        # Fire and forget: this invocation answers Telegram now; the next one waits.
        _lambda.invoke(
            FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
            InvocationType="Event",
            Payload=json.dumps({"action": "announce_when_up", "chat_id": chat_id}).encode(),
        )
    return (
        "🚀 Start command successfully executed. Booting takes about 90 seconds; "
        "I will message you when the site is up."
    )


def _stop(chat_id: int, who: str, force: bool) -> str:
    _send(chat_id, f"🔄 {who} initiated a shutdown command...")
    state = _instance_state()
    if state == "stopped":
        return f"✅ Instance {INSTANCE_ID} is already stopped."
    # The Lambda cannot see run state without the database, so this is not a guard
    # against stopping mid-run; the console shows that.
    _ec2.stop_instances(InstanceIds=[INSTANCE_ID], Force=force)
    return f"🛑 {'Force-stop' if force else 'Stop'} signal successfully sent to {INSTANCE_ID}."


def _uptime_minutes() -> int | None:
    """Minutes since the instance last started (LaunchTime resets on every start)."""
    inst = _ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"][0]["Instances"][0]
    if inst["State"]["Name"] != "running":
        return None
    return int((datetime.now(UTC) - inst["LaunchTime"]).total_seconds() // 60)


HELP = """🤖 ATOM control

/info or /status - instance details, state and uptime
/start - bring the engine up and tell me when the site is serving
/stop - shut it down (/stop force to override)
/help - this

The Status, Start and Stop buttons do the same.

This bot cannot trade. Trading actions are only available in the console, where
the full context is visible. That is deliberate."""


def _dispatch(text: str, chat_id: int, who: str) -> str:
    command, _, rest = text.strip().partition(" ")
    command = command.split("@", 1)[0].lower()  # strip @botname in groups
    if command in ("status", "start", "stop", "info"):  # the buttons send bare words
        command = "/" + command

    if command == "/start":
        return _start(chat_id, who)
    if command == "/stop":
        return _stop(chat_id, who, force=rest.strip().lower() == "force")
    if command in ("/status", "/info"):
        return _info()
    if command == "/help":
        return HELP
    return f"❓ Unknown command {command}. Try /help."


def _enforce_max_runtime() -> dict[str, Any]:
    """Scheduled check: stop the instance once it has run MAX_RUNTIME_MINUTES.

    Independent of the on-instance idle timer, which only fires after an hour of
    NO console use: a session left open, or a forgotten start, still ends.
    """
    up = _uptime_minutes()
    if not MAX_RUNTIME_MINUTES or up is None or up < MAX_RUNTIME_MINUTES:
        return {"stopped": False, "uptime_minutes": up}
    _ec2.stop_instances(InstanceIds=[INSTANCE_ID])
    log.info("stopping: up %s min, limit %s", up, MAX_RUNTIME_MINUTES)
    for user_id in _allowed_user_ids():
        _send(user_id, f"⏱️ Engine stopped automatically after {MAX_RUNTIME_MINUTES} min.")
    return {"stopped": True, "uptime_minutes": up}


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Lambda Function URL entry point.

    Replies fast and does the slow part after, because Telegram retries a webhook
    that does not answer within ~60s — which would double-start the instance.
    ``StartInstances`` is idempotent, but not relying on that is better.
    """
    if event.get("source") == "aws.events" or event.get("action") == "enforce_max_runtime":
        return _enforce_max_runtime()
    # Like the schedule above, only our own invoke() sets a top-level "action"; a
    # request through the Function URL cannot, its fields all sit under headers/body.
    if event.get("action") == "announce_when_up":
        return _announce_when_up(int(event["chat_id"]))

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
        reply = _dispatch(text, chat_id, (message.get("from") or {}).get("first_name") or "Someone")
    except Exception:
        log.exception("command failed")
        reply = "❌ Command failed. Check the CloudWatch logs for atom-control."

    _send(chat_id, reply)
    return {"statusCode": 200, "body": "ok"}
