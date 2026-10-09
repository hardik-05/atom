"""Connect the Telegram bot to the control Lambda.

    python scripts/telegram_setup.py            # register the webhook and the command menu
    python scripts/telegram_setup.py --check    # show what Telegram has, change nothing

Prerequisite: the bot token, your numeric Telegram user id and a webhook secret are in SSM
under /atom/telegram/ (see docs/02-infrastructure/LAMBDA-AND-TELEGRAM.md). The token is read
here and never printed.
"""

from __future__ import annotations

import argparse
import json
import sys

import boto3
import httpx


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="atom")
    p.add_argument("--region", default="ap-south-1")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()

    session = boto3.Session(profile_name=a.profile, region_name=a.region)
    ssm = session.client("ssm")

    def secret(name: str) -> str:
        return str(ssm.get_parameter(Name=f"/atom/telegram/{name}", WithDecryption=True)["Parameter"]["Value"])

    token, webhook_secret = secret("bot_token"), secret("webhook_secret")
    if "set-me" in (token, webhook_secret) or secret("allowed_user_ids") == "set-me":
        sys.exit("bot_token, webhook_secret and allowed_user_ids must all be set first")
    url = session.client("lambda").get_function_url_config(FunctionName="atom-control")["FunctionUrl"]
    api = f"https://api.telegram.org/bot{token}"
    with httpx.Client(timeout=20) as c:
        info = c.get(f"{api}/getWebhookInfo").json()["result"]
        print("webhook now:", info.get("url") or "(none)", "| pending:", info.get("pending_update_count"))
        if a.check:
            return
        r = c.post(f"{api}/setWebhook", data={"url": url, "secret_token": webhook_secret,
                                              "allowed_updates": json.dumps(["message"])}).json()
        print("setWebhook:", r.get("description"))
        cmds = [
            ("info", "Instance details and state"),
            ("status", "Instance details and state"),
            ("start", "Bring the engine up"),
            ("stop", "Shut it down"),
        ]
        r = c.post(f"{api}/setMyCommands",
                   data={"commands": json.dumps([{"command": k, "description": d} for k, d in cmds])}).json()
        print("setMyCommands:", r.get("ok"))


if __name__ == "__main__":
    main()
