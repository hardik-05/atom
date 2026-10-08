"""Assemble the keep-alive Lambda's package directory; called by Terraform.

Terraform's ``external`` data source runs this at plan time and reads ONE JSON
object from stdout, so pip's output goes to stderr. The dependencies are
reinstalled only when requirements.txt changes (a stamp file records its hash):
a plan then neither needs the network nor produces a different zip.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "terraform" / ".build" / "keepalive"
STAMP = OUT / ".requirements.sha256"


def main() -> None:
    requirements = HERE / "requirements.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not STAMP.exists() or STAMP.read_text() != digest:
        shutil.rmtree(OUT, ignore_errors=True)
        OUT.mkdir(parents=True)
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--quiet",
                "--requirement", str(requirements),
                "--target", str(OUT),
                "--platform", "manylinux2014_x86_64",
                "--python-version", "3.12",
                "--only-binary=:all:",
                "--no-compile",
            ],
            check=True,
            stdout=sys.stderr,
        )
        # Installer metadata is the only thing pip writes that varies between
        # otherwise identical installs; without it the zip hash is stable.
        for record in OUT.glob("*.dist-info/RECORD"):
            record.unlink()
        STAMP.write_text(digest)
    shutil.copy2(HERE / "handler.py", OUT / "handler.py")
    print(json.dumps({"dir": OUT.as_posix()}))


if __name__ == "__main__":
    main()
