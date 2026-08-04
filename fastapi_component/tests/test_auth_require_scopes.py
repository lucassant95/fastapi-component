"""Tests for the require_scopes dependency factory."""

from fastapi import Depends
from fastapi.testclient import TestClient
from python_components import System

from fastapi_component import create_app
from fastapi_component.auth.component import JWTAuth
from fastapi_component.auth.dependencies import AuthenticatedUser, require_scopes
from fastapi_component.auth.passwords import hash_password
from fastapi_component.tests.helpers_auth import (
    FakeTokenStore,
    FakeUser,
    FakeUserStore,
    StubConfig,
)

SECRET = "unit-test-secret-0123456789abcdef-0123456789abcdef"
PASSWORD = "correct horse battery staple"
PASSWORD_HASH = hash_password(PASSWORD)
SCOPES_BY_ROLE = {
    "customer": ["analytics:read"],
    "admin": ["analytics:read", "catalog:write"],
}


def make_app():
    system = System(
        {
            "config": StubConfig(JWT_SECRET_KEY=SECRET),
            "user_store": FakeUserStore(
                [
                    FakeUser("user-1", "ada@example.com", PASSWORD_HASH),
                    FakeUser("user-2", "root@example.com", PASSWORD_HASH, role="admin"),
                ]
            ),
            "token_store": FakeTokenStore(),
            "auth": JWTAuth(scopes_by_role=SCOPES_BY_ROLE).using(
                ["user_store", "token_store", "config"]
            ),
        }
    )
    app = create_app(system)

    @app.get("/writes", dependencies=[Depends(require_scopes("catalog:write"))])
    def writes():
        return {"ok": True}

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(require_scopes())):
        return {"sub": user.user_id, "role": user.role, "scopes": sorted(user.scopes)}

    return app


def token_for(client, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_missing_credentials_is_401_with_bearer_challenge():
    with TestClient(make_app()) as client:
        response = client.get("/writes")

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_garbage_token_is_401():
    with TestClient(make_app()) as client:
        response = client.get("/writes", headers=auth_header("not-a-jwt"))

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_valid_token_without_required_scope_is_403():
    with TestClient(make_app()) as client:
        token = token_for(client, "ada@example.com")

        response = client.get("/writes", headers=auth_header(token))

        assert response.status_code == 403
        assert "catalog:write" in response.json()["detail"]
        assert "WWW-Authenticate" not in response.headers


def test_valid_token_with_required_scope_passes():
    with TestClient(make_app()) as client:
        token = token_for(client, "root@example.com")

        assert client.get("/writes", headers=auth_header(token)).status_code == 200


def test_route_level_capture_returns_identity():
    with TestClient(make_app()) as client:
        token = token_for(client, "ada@example.com")

        body = client.get("/me", headers=auth_header(token)).json()

        assert body == {
            "sub": "user-1",
            "role": "customer",
            "scopes": ["analytics:read"],
        }


def test_factory_returns_identical_callable_for_identical_scopes():
    assert require_scopes("catalog:write") is require_scopes("catalog:write")
    assert require_scopes() is require_scopes()
    assert require_scopes("a") is not require_scopes("b")


def test_dependency_overrides_work_via_factory_identity():
    """The consumer-facing contract: a fresh require_scopes(...) call in a test
    suite must be usable as the dependency_overrides key for a router that
    called require_scopes(...) at import time."""
    app = make_app()
    app.dependency_overrides[require_scopes("catalog:write")] = lambda: (
        AuthenticatedUser(user_id="fake", role="admin", scopes=frozenset())
    )

    with TestClient(app) as client:
        assert client.get("/writes").status_code == 200


def test_missing_credentials_is_401_even_before_the_lifespan_runs():
    """Anonymous requests must not require the running system: the 401 for a
    missing token fires before the auth component is resolved. Consumer test
    suites that build the real app but never run the lifespan (no `with`
    TestClient block) must see 401, not a RuntimeError-driven 500."""
    client = TestClient(make_app())  # no `with` — app.state.system never set

    response = client.get("/writes")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
