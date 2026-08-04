"""JWT authentication plugin for fastapi-component.

Provides a ``JWTAuth`` component that issues and rotates JWT/refresh-token
pairs against application-supplied stores, plus a ``require_scopes``
dependency factory to guard routes. Requires the ``auth`` extra:
``pip install 'fastapi-component[auth]'``.
"""

try:
    import jwt  # noqa: F401
    import pwdlib  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised via sys.modules patching
    raise ImportError(
        "fastapi_component.auth requires the optional 'auth' extra; "
        "install it with: pip install 'fastapi-component[auth]'"
    ) from exc

from fastapi_component.auth.component import (
    JWTAuth,
    LoginRequest,
    TokenPair,
    TokenResponse,
    hash_refresh_secret,
)
from fastapi_component.auth.dependencies import AuthenticatedUser, require_scopes
from fastapi_component.auth.errors import (
    InvalidCredentialsError,
    RefreshTokenError,
    RefreshTokenExpiredError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
)
from fastapi_component.auth.passwords import hash_password, verify_password
from fastapi_component.auth.protocols import (
    AuthUser,
    RefreshTokenRecord,
    RefreshTokenStore,
    UserStore,
)
from fastapi_component.auth.tokens import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
)

__all__ = [
    "AuthUser",
    "AuthenticatedUser",
    "InvalidAccessTokenError",
    "InvalidCredentialsError",
    "JWTAuth",
    "LoginRequest",
    "RefreshTokenError",
    "RefreshTokenExpiredError",
    "RefreshTokenInvalidError",
    "RefreshTokenRecord",
    "RefreshTokenReusedError",
    "RefreshTokenStore",
    "TokenPair",
    "TokenResponse",
    "UserStore",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "hash_refresh_secret",
    "require_scopes",
    "verify_password",
]
