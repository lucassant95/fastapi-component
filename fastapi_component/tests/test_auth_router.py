"""Tests for the /auth router contributed by JWTAuth via RouteProvider."""

from fastapi.testclient import TestClient
from python_components import System

from fastapi_component import create_app
from fastapi_component.auth.component import JWTAuth
from fastapi_component.auth.passwords import hash_password
from fastapi_component.tests.helpers import registered_paths
from fastapi_component.tests.helpers_auth import (
    FakeTokenStore,
    FakeUser,
    FakeUserStore,
    StubConfig,
)

SECRET = "unit-test-secret-0123456789abcdef-0123456789abcdef"
PASSWORD = "correct horse battery staple"
PASSWORD_HASH = hash_password(PASSWORD)
SCOPES_BY_ROLE = {"customer": ["analytics:read"]}


def make_app(users=None):
    users = (
        users
        if users is not None
        else [FakeUser("user-1", "ada@example.com", PASSWORD_HASH)]
    )
    system = System(
        {
            "config": StubConfig(JWT_SECRET_KEY=SECRET),
            "user_store": FakeUserStore(users),
            "token_store": FakeTokenStore(),
            "auth": JWTAuth(scopes_by_role=SCOPES_BY_ROLE).using(
                ["user_store", "token_store", "config"]
            ),
        }
    )
    return create_app(system)


def make_client(app) -> TestClient:
    # https base_url so the cookie jar accepts and re-sends Secure cookies.
    return TestClient(app, base_url="https://testserver")


def login(client) -> dict:
    response = client.post(
        "/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_auth_routes_are_discovered_via_route_provider():
    app = make_app()

    paths = registered_paths(app)
    assert "/auth/login" in paths
    assert "/auth/refresh" in paths
    assert "/auth/logout" in paths


def test_login_returns_token_json_and_sets_refresh_cookie():
    with make_client(make_app()) as client:
        response = client.post(
            "/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60
        assert body["access_token"]
        cookie_header = response.headers["set-cookie"]
        assert "refresh_token=" in cookie_header
        assert "HttpOnly" in cookie_header
        assert "Secure" in cookie_header
        assert "SameSite=lax" in cookie_header
        assert "Path=/auth" in cookie_header
        assert "Max-Age=2592000" in cookie_header


def test_login_failure_is_a_generic_401_without_cookie():
    with make_client(make_app()) as client:
        response = client.post(
            "/auth/login", json={"email": "ada@example.com", "password": "wrong"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"
        assert "set-cookie" not in response.headers


def test_refresh_rotates_the_cookie_and_returns_a_new_token():
    with make_client(make_app()) as client:
        login(client)
        first_cookie = client.cookies.get("refresh_token")

        response = client.post("/auth/refresh")

        assert response.status_code == 200
        assert response.json()["access_token"]
        assert client.cookies.get("refresh_token") != first_cookie


def test_refresh_without_cookie_is_401():
    with make_client(make_app()) as client:
        response = client.post("/auth/refresh")

        assert response.status_code == 401


def test_replaying_a_rotated_cookie_is_401():
    with make_client(make_app()) as client:
        login(client)
        stale = client.cookies.get("refresh_token")
        client.post("/auth/refresh").raise_for_status()

        client.cookies.set("refresh_token", stale, path="/auth")
        response = client.post("/auth/refresh")

        assert response.status_code == 401


def test_logout_is_204_and_clears_the_cookie():
    with make_client(make_app()) as client:
        login(client)

        response = client.post("/auth/logout")

        assert response.status_code == 204
        cookie_header = response.headers["set-cookie"]
        assert 'refresh_token=""' in cookie_header or "refresh_token=;" in cookie_header
        assert client.post("/auth/refresh").status_code == 401


def test_logout_without_cookie_is_still_204():
    with make_client(make_app()) as client:
        assert client.post("/auth/logout").status_code == 204
