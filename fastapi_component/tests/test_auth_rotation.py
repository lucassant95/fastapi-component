"""Tests for JWTAuth: login, refresh rotation, reuse detection, logout."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fastapi_component.auth.component import JWTAuth, hash_refresh_secret
from fastapi_component.auth.errors import (
    InvalidCredentialsError,
    RefreshTokenError,
    RefreshTokenExpiredError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
)
from fastapi_component.auth.passwords import hash_password
from fastapi_component.tests.helpers_auth import FakeTokenStore, FakeUser, FakeUserStore

SECRET = "unit-test-secret-0123456789abcdef-0123456789abcdef"
PASSWORD = "correct horse battery staple"
PASSWORD_HASH = hash_password(PASSWORD)


def make_user(**overrides) -> FakeUser:
    defaults = dict(
        user_id="user-1", email="ada@example.com", password_hash=PASSWORD_HASH
    )
    defaults.update(overrides)
    return FakeUser(**defaults)


def make_auth(users=None, config=None) -> JWTAuth:
    auth = JWTAuth()
    auth.user_store = FakeUserStore(users if users is not None else [make_user()])
    auth.token_store = FakeTokenStore()
    auth.config = (
        config
        if config is not None
        else SimpleNamespace(
            JWT_SECRET_KEY=SECRET,
            JWT_ACCESS_TOKEN_TTL_MINUTES=15,
            JWT_REFRESH_TOKEN_TTL_DAYS=30,
        )
    )
    auth.start()
    return auth


# ---------------------------------------------------------------- login


def test_login_embeds_the_users_own_scopes():
    auth = make_auth(users=[make_user(scopes=("analytics:read", "catalog:write"))])

    pair = asyncio.run(auth.login("ada@example.com", PASSWORD))

    claims = auth.decode(pair.access_token)
    assert claims["sub"] == "user-1"
    assert claims["scope"] == ["analytics:read", "catalog:write"]
    assert "role" not in claims
    assert pair.expires_in == 15 * 60


def test_login_persists_one_live_hashed_refresh_token():
    auth = make_auth()

    pair = asyncio.run(auth.login("ada@example.com", PASSWORD))

    live = auth.token_store.live_rows()
    assert len(live) == 1
    assert live[0].token_hash == hash_refresh_secret(pair.refresh_secret)
    assert live[0].user_id == "user-1"
    expected_expiry = datetime.now(timezone.utc) + timedelta(days=30)
    assert abs((live[0].expires_at - expected_expiry).total_seconds()) < 10


@pytest.mark.parametrize(
    "email,password,users",
    [
        ("ada@example.com", "wrong-password", None),
        ("nobody@example.com", PASSWORD, None),
        (
            "ada@example.com",
            PASSWORD,
            [FakeUser("user-1", "ada@example.com", PASSWORD_HASH, is_active=False)],
        ),
        ("ada@example.com", PASSWORD, [FakeUser("user-1", "ada@example.com", None)]),
    ],
    ids=["wrong-password", "unknown-email", "inactive", "idp-only"],
)
def test_login_failures_all_raise_the_same_error(email, password, users):
    auth = make_auth(users=users)

    with pytest.raises(InvalidCredentialsError):
        asyncio.run(auth.login(email, password))


# ---------------------------------------------------------------- refresh


def test_refresh_rotates_within_the_same_session():
    auth = make_auth()
    first = asyncio.run(auth.login("ada@example.com", PASSWORD))

    second = asyncio.run(auth.refresh(first.refresh_secret))

    assert auth.decode(second.access_token)["sub"] == "user-1"
    live = auth.token_store.live_rows()
    assert len(live) == 1
    assert live[0].token_hash == hash_refresh_secret(second.refresh_secret)
    old_row = auth.token_store.rows[hash_refresh_secret(first.refresh_secret)]
    assert old_row.revoked_reason == "rotated"
    assert old_row.session_id == live[0].session_id


def test_refresh_with_unknown_token_raises_invalid():
    auth = make_auth()

    with pytest.raises(RefreshTokenInvalidError):
        asyncio.run(auth.refresh("never-issued-secret"))


def test_reusing_a_rotated_token_revokes_the_whole_session():
    auth = make_auth()
    first = asyncio.run(auth.login("ada@example.com", PASSWORD))
    asyncio.run(auth.refresh(first.refresh_secret))

    with pytest.raises(RefreshTokenReusedError):
        asyncio.run(auth.refresh(first.refresh_secret))

    assert auth.token_store.live_rows() == []
    reasons = {row.revoked_reason for row in auth.token_store.rows.values()}
    assert "compromised" in reasons


def test_expired_token_raises_expired_without_compromising_anything():
    auth = make_auth()
    asyncio.run(
        auth.token_store.insert(
            user_id="user-1",
            session_id="session-old",
            token_hash=hash_refresh_secret("stale-secret"),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )

    with pytest.raises(RefreshTokenExpiredError):
        asyncio.run(auth.refresh("stale-secret"))

    reasons = {row.revoked_reason for row in auth.token_store.rows.values()}
    assert "compromised" not in reasons


def test_refresh_for_deactivated_user_fails_and_revokes_the_session():
    user = make_user()
    auth = make_auth(users=[user])
    pair = asyncio.run(auth.login("ada@example.com", PASSWORD))
    user.is_active = False

    with pytest.raises(RefreshTokenError):
        asyncio.run(auth.refresh(pair.refresh_secret))

    assert auth.token_store.live_rows() == []


# ---------------------------------------------------------------- logout


def test_logout_revokes_the_presented_token():
    auth = make_auth()
    pair = asyncio.run(auth.login("ada@example.com", PASSWORD))

    asyncio.run(auth.logout(pair.refresh_secret))

    row = auth.token_store.rows[hash_refresh_secret(pair.refresh_secret)]
    assert row.revoked_reason == "logout"


def test_logout_with_unknown_secret_is_silent():
    auth = make_auth()

    asyncio.run(auth.logout("never-issued"))
    asyncio.run(auth.logout(None))


# ---------------------------------------------------------------- settings


def test_start_without_secret_fails():
    auth = JWTAuth()
    auth.user_store = FakeUserStore([])
    auth.token_store = FakeTokenStore()
    auth.config = SimpleNamespace()

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        auth.start()


def test_start_with_short_secret_fails():
    auth = JWTAuth()
    auth.user_store = FakeUserStore([])
    auth.token_store = FakeTokenStore()
    auth.config = SimpleNamespace(JWT_SECRET_KEY="too-short")

    with pytest.raises(RuntimeError, match="32"):
        auth.start()


def test_ttls_fall_back_to_defaults_when_config_lacks_them():
    auth = make_auth(config=SimpleNamespace(JWT_SECRET_KEY=SECRET))

    pair = asyncio.run(auth.login("ada@example.com", PASSWORD))

    assert pair.expires_in == 15 * 60
