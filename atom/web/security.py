"""Console authentication: one operator, a password and a TOTP code (D-040).

Standard library only — scrypt, HMAC and base32 are all in ``hashlib``,
``hmac`` and ``base64`` — so the login path adds no dependency that could be
compromised upstream.

The session is a signed cookie, not a server-side table: the console has one
user, the instance is stopped most of the day, and a session store would be
one more thing to lose on an instance replacement. The signing key lives in
SSM, so rotating it logs everyone out — which is the behaviour wanted after a
suspected compromise.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets as pysecrets
import struct
import threading
import time
from dataclasses import dataclass

SESSION_COOKIE = "atom_session"
SESSION_SECONDS = 12 * 3600
"""Twelve hours: covers a trading day, and forces a fresh login each morning."""

TOTP_STEP = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1
"""Accept the previous and next step too — phones drift, and a 30-second window
with no tolerance fails often enough that operators start to resent 2FA."""

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1


# ------------------------------------------------------------------ password


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("the console password must be at least 12 characters")
    salt = pysecrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=64 * 1024 * 1024
    )
    b64 = base64.b64encode
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = base64.b64decode(hash_b64)
    actual = hashlib.scrypt(
        password.encode(),
        salt=base64.b64decode(salt_b64),
        n=int(n),
        r=int(r),
        p=int(p),
        maxmem=64 * 1024 * 1024,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------------- TOTP


def new_totp_secret() -> str:
    return base64.b32encode(pysecrets.token_bytes(20)).decode().rstrip("=")


def totp_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**TOTP_DIGITS
    return f"{code:0{TOTP_DIGITS}d}"


def verify_totp(secret: str, code: str, *, now: float | None = None) -> bool:
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    counter = int((time.time() if now is None else now) // TOTP_STEP)
    return any(
        hmac.compare_digest(totp_at(secret, counter + delta), code)
        for delta in range(-TOTP_WINDOW, TOTP_WINDOW + 1)
    )


def otpauth_uri(secret: str, *, account: str, issuer: str = "ATOM") -> str:
    return f"otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}&digits={TOTP_DIGITS}"


# ------------------------------------------------------------------- session


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(username: str, key: str, *, now: float | None = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = _b64(
        json.dumps({"u": username, "iat": issued, "exp": issued + SESSION_SECONDS}).encode()
    )
    signature = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def read_session(token: str | None, key: str, *, now: float | None = None) -> str | None:
    """The username, or ``None`` for anything missing, tampered with or expired."""
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    expected = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("exp", 0)) < (time.time() if now is None else now):
        return None
    user = data.get("u")
    return str(user) if user else None


# ------------------------------------------------------------------- lockout


@dataclass
class _Failures:
    count: int
    first_at: float


class LoginThrottle:
    """Five wrong attempts from one address lock it out for fifteen minutes.

    In memory, per process: it exists to make an online guess of a 12-character
    password AND a TOTP code slower than useless, not to survive a restart.
    """

    def __init__(self) -> None:
        self._failures: dict[str, _Failures] = {}
        self._lock = threading.Lock()

    def locked_for(self, client: str, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        with self._lock:
            entry = self._failures.get(client)
            if entry is None:
                return 0
            if current - entry.first_at > LOCKOUT_SECONDS:
                self._failures.pop(client, None)
                return 0
            if entry.count >= MAX_FAILURES:
                return int(LOCKOUT_SECONDS - (current - entry.first_at))
            return 0

    def fail(self, client: str, *, now: float | None = None) -> None:
        current = time.time() if now is None else now
        with self._lock:
            entry = self._failures.get(client)
            if entry is None or current - entry.first_at > LOCKOUT_SECONDS:
                self._failures[client] = _Failures(1, current)
            else:
                entry.count += 1

    def succeed(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
