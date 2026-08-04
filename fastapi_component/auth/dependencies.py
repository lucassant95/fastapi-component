"""Route guard: the require_scopes dependency factory.

Verification is stateless — signature and expiry only, no store access. The
plugin revokes *refresh* tokens; a revoked or deactivated user is shut out
at the next refresh, bounded by the access token's TTL.
"""

import functools
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fastapi_component.auth.tokens import InvalidAccessTokenError
from fastapi_component.dependencies import component

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identity extracted from a validated access token."""

    user_id: str
    role: str
    scopes: frozenset[str]


@functools.lru_cache(maxsize=None)
def require_scopes(*required_scopes: str, auth_component: str = "auth"):
    """Build a dependency enforcing a Bearer token with the given scopes.

    The result is cached per argument tuple so repeated calls return the
    *same* callable — FastAPI's ``dependency_overrides`` keys on callable
    identity, and without the cache a second ``require_scopes("x")`` in a
    test suite could never override the one baked into a router.

    Usage: ``dependencies=[Depends(require_scopes("catalog:write"))]`` at
    router level, or ``user: AuthenticatedUser = Depends(require_scopes())``
    to capture the identity in a handler. No scopes means any authenticated
    user passes.

    Responses: 401 with a ``WWW-Authenticate: Bearer`` challenge when the
    token is missing or invalid (re-authenticating can help); 403 without
    the challenge when scopes are insufficient (it cannot).
    """

    async def _guard(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
        auth=Depends(component(auth_component)),
    ) -> AuthenticatedUser:
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            claims = auth.decode(credentials.credentials)
        except InvalidAccessTokenError:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_scopes = frozenset(claims.get("scope", []))
        missing = set(required_scopes) - token_scopes
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing required scope(s): {', '.join(sorted(missing))}",
            )
        return AuthenticatedUser(
            user_id=claims["sub"],
            role=claims.get("role", ""),
            scopes=token_scopes,
        )

    return _guard
