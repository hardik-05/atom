"""Console authentication primitives."""

from __future__ import annotations

import base64

import pytest

from atom.web import security


def test_totp_matches_the_rfc_6238_vector() -> None:
    """RFC 6238 appendix B: SHA-1, secret "12345678901234567890", T=59 → 94287082.
    Six digits is the last six of that."""
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert security.totp_at(secret, 59 // 30) == "287082"
    assert security.verify_totp(secret, "287082", now=59)


def test_totp_tolerates_one_step_of_drift_and_no_more() -> None:
    secret = security.new_totp_secret()
    now = 1_800_000_000
    previous = security.totp_at(secret, now // 30 - 1)
    two_back = security.totp_at(secret, now // 30 - 2)
    assert security.verify_totp(secret, previous, now=now)
    assert not security.verify_totp(secret, two_back, now=now) or two_back == previous


def test_totp_rejects_garbage() -> None:
    secret = security.new_totp_secret()
    for code in ("", "12345", "abcdef", "1234567"):
        assert not security.verify_totp(secret, code)


def test_password_round_trip_and_minimum_length() -> None:
    stored = security.hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    assert security.verify_password("correct horse battery", stored)
    assert not security.verify_password("correct horse batterY", stored)
    with pytest.raises(ValueError):
        security.hash_password("short")


def test_session_rejects_tampering_and_expiry() -> None:
    token = security.sign_session("operator", "k" * 40, now=1000)
    assert security.read_session(token, "k" * 40, now=1001) == "operator"
    assert security.read_session(token, "other-key" * 5, now=1001) is None
    _payload, sig = token.rsplit(".", 1)
    forged = (
        base64.urlsafe_b64encode(b'{"u":"admin","iat":1000,"exp":99999999}').decode().rstrip("=")
    )
    assert security.read_session(f"{forged}.{sig}", "k" * 40, now=1001) is None
    assert security.read_session(token, "k" * 40, now=1000 + security.SESSION_SECONDS + 1) is None


def test_lockout_after_five_failures() -> None:
    throttle = security.LoginThrottle()
    for _ in range(5):
        assert throttle.locked_for("1.2.3.4", now=100) == 0
        throttle.fail("1.2.3.4", now=100)
    assert throttle.locked_for("1.2.3.4", now=101) > 0
    assert throttle.locked_for("5.6.7.8", now=101) == 0
    assert throttle.locked_for("1.2.3.4", now=100 + security.LOCKOUT_SECONDS + 1) == 0
