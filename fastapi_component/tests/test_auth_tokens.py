"""Tests for JWT access-token creation and validation."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from fastapi_component.auth.tokens import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
)

SECRET = "unit-test-secret-0123456789abcdef-0123456789abcdef"


def make_token(**overrides):
    defaults = dict(
        subject="user-123",
        scopes=["analytics:read"],
        secret=SECRET,
        ttl_minutes=15,
    )
    defaults.update(overrides)
    return create_access_token(**defaults)


def test_decode_round_trips_subject_and_scopes():
    claims = decode_access_token(make_token(), secret=SECRET)

    assert claims["sub"] == "user-123"
    assert claims["scope"] == ["analytics:read"]
    assert "role" not in claims


def test_token_carries_expiry_and_issued_at():
    before = datetime.now(timezone.utc)
    claims = decode_access_token(make_token(ttl_minutes=15), secret=SECRET)

    issued_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
    expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    assert before - timedelta(seconds=5) <= issued_at <= before + timedelta(seconds=5)
    assert expires_at - issued_at == timedelta(minutes=15)


def test_expired_token_is_rejected():
    expired = make_token(
        now=datetime.now(timezone.utc) - timedelta(minutes=30), ttl_minutes=15
    )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(expired, secret=SECRET)


def test_wrong_secret_is_rejected():
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(make_token(), secret="a-different-secret-0123456789abcdef")


def test_garbage_token_is_rejected():
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token("not-a-jwt", secret=SECRET)


def test_unsigned_algorithm_is_rejected():
    forged = jwt.encode(
        {"sub": "user-123", "scope": ["users:manage"]},
        key=None,
        algorithm="none",
    )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged, secret=SECRET)
