# Changelog

## 0.3.0 (2026-08-04)

- `fastapi_component.auth` — JWT authentication plugin behind the new optional
  `auth` extra (`pip install 'fastapi-component[auth]'`; PyJWT + pwdlib/Argon2):
  - `JWTAuth` component: HS256 access tokens (`sub`/`scope` claims),
    rotating sha256-hashed refresh tokens with reuse detection (a replayed
    rotated token revokes its whole session as compromised), and a
    `RouteProvider`-discovered `POST {prefix}/login|refresh|logout` router
    with an httpOnly refresh cookie. `issue_tokens()` is public so external
    identity providers can reuse the same issuance path.
  - `UserStore` / `RefreshTokenStore` protocols the application implements
    for persistence; `AuthUser` protocol for the user shape. Scopes are
    per-user data on `AuthUser` — the plugin has no role concept; scope
    assignment policy is entirely application-side.
  - `require_scopes(*scopes)` dependency factory (401 + `WWW-Authenticate`
    vs 403 semantics), cached per argument tuple so consumer test suites can
    key `dependency_overrides` on a fresh call.
  - `hash_password` / `verify_password` (Argon2) for application-side user
    creation.

## 0.2.0 (2026-07-23)

- `RouteProvider` — runtime-checkable protocol for components that contribute
  an `APIRouter` via `def routes(self) -> APIRouter`.
- `include_component_routes(app, system)` — includes the routers of every
  provider in the system, depth-first in system-map insertion order, each
  instance at most once.
- `create_app` gains `component_routes: bool = True` and includes component
  routes automatically, after explicit `routers=` and before `configure`.

## 0.1.0 (2026-07-09)

Initial release.

- `system_lifespan(system, *, wrap=None, state_key="system")` — a standard
  FastAPI lifespan that starts a python-components `System` with `astart()`
  inside the server's event loop, exposes it at `app.state.<state_key>`, and
  stops it with `ashutdown()` in reverse dependency order. Supports composing
  a user lifespan (`wrap=`) that runs inside the system's lifecycle.
- `create_app(system, *, routers=(), configure=None, lifespan=None,
  state_key="system", **fastapi_kwargs)` — convenience factory; all native
  FastAPI constructor arguments pass through.
- `get_system` / `component(name)` — `Depends`-compatible helpers to resolve
  the system or a named component in request handlers.
- Failure semantics: fail-fast startup with automatic rollback
  (`ComponentStartError`), aggregated shutdown errors (`ExceptionGroup`),
  double-start guard.
