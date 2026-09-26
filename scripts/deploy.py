"""Build, ship and install one ATOM release on the engine host.

    python scripts/deploy.py                 # deploy HEAD
    python scripts/deploy.py --skip-build    # reuse web/dist as it is

Runs from the operator's machine with the ``atom`` AWS profile. What it does,
in order, and why each step is where it is:

1. refuses a dirty tree — a release is a COMMIT, so the version on the instance
   names exactly the code that is running
2. builds the console (``web/dist``)
3. packages the tracked files plus ``web/dist``; ``data/raw`` stays behind
   (38 MB of vendor snapshots the engine never reads at run time)
4. uploads to the artifacts bucket
5. starts the instance if the idle timer has stopped it, and waits for SSM
6. runs ``deploy/install.sh`` on the instance and streams its result

Nothing here holds a secret: the instance reads its own from SSM.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_PREFIXES = ("data/raw/", "infra/", ".github/")


def sh(cmd: list[str], cwd: Path = ROOT) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def package(version: str) -> bytes:
    files = [f for f in sh(["git", "ls-files"]).splitlines() if not f.startswith(EXCLUDE_PREFIXES)]
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").exists():
        sys.exit("web/dist is missing — build the console first (or drop --skip-build)")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in files:
            tar.add(ROOT / name, arcname=name, recursive=False)
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(ROOT).as_posix())
        info = tarfile.TarInfo("RELEASE")
        payload = f"{version}\n".encode()
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def wait_for_ssm(ssm, instance_id: str, timeout: int = 300) -> None:  # type: ignore[no-untyped-def]
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
        )["InstanceInformationList"]
        if info and info[0]["PingStatus"] == "Online":
            return
        time.sleep(5)
    sys.exit("the instance never came online in SSM")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="atom")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--instance-id", default="i-046d2247ea21f668f")
    parser.add_argument("--bucket", default="atom-artifacts-905221883695-prod")
    parser.add_argument("--host", default="app.metaalgocapital.com")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if sh(["git", "status", "--porcelain", "--untracked-files=no"]) and not args.allow_dirty:
        sys.exit(
            "working tree has uncommitted changes — commit first, so the release names real code"
        )
    version = f"{time.strftime('%Y%m%d-%H%M%S')}-{sh(['git', 'rev-parse', '--short', 'HEAD'])}"

    if not args.skip_build:
        print("building console…")
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "web", check=True)
        subprocess.run([npm, "run", "build"], cwd=ROOT / "web", check=True)

    blob = package(version)
    print(f"release {version}: {len(blob) / 1e6:.1f} MB")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3, ec2, ssm = session.client("s3"), session.client("ec2"), session.client("ssm")
    s3.put_object(
        Bucket=args.bucket,
        Key=f"releases/{version}.tar.gz",
        Body=blob,
        ServerSideEncryption="AES256",
    )
    print("uploaded")

    state = ec2.describe_instances(InstanceIds=[args.instance_id])["Reservations"][0]["Instances"][
        0
    ]["State"]["Name"]
    if state != "running":
        print(f"instance is {state}; starting it")
        if state == "stopping":
            ec2.get_waiter("instance_stopped").wait(InstanceIds=[args.instance_id])
        ec2.start_instances(InstanceIds=[args.instance_id])
        ec2.get_waiter("instance_running").wait(InstanceIds=[args.instance_id])
    wait_for_ssm(ssm, args.instance_id)

    commands = [
        "set -euo pipefail",
        f"aws s3 cp --only-show-errors s3://{args.bucket}/releases/{version}.tar.gz /tmp/atom-release.tgz --region {args.region}",
        "rm -rf /tmp/atom-install && mkdir -p /tmp/atom-install",
        "tar -xzf /tmp/atom-release.tgz -C /tmp/atom-install deploy/install.sh",
        f"bash /tmp/atom-install/deploy/install.sh {version} {args.bucket} {args.host}",
    ]
    command_id = ssm.send_command(
        InstanceIds=[args.instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands, "executionTimeout": ["1200"]},
        TimeoutSeconds=1200,
    )["Command"]["CommandId"]
    print(f"installing (ssm command {command_id})…")

    while True:
        time.sleep(8)
        try:
            inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=args.instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
            print(inv["StandardOutputContent"][-4000:])
            if inv["StandardErrorContent"].strip():
                print("--- stderr ---\n" + inv["StandardErrorContent"][-3000:])
            print(f"==> {inv['Status']}: release {version}")
            sys.exit(0 if inv["Status"] == "Success" else 1)


if __name__ == "__main__":
    main()
