"""The JWTAuth component: issues, rotates, and revokes token pairs.

Refresh tokens are opaque 256-bit secrets stored sha256-hashed; rows sharing
a ``session_id`` form one login's rotation chain. The claim-then-classify
sequence in :meth:`JWTAuth.refresh` implements rotation with reuse
detection: replaying an already-rotated token revokes the entire session.

There is deliberately no cross-statement transaction around claim + insert —
the atomic claim is the security-critical step; a crash between the two only
forces a re-login. Under a concurrent double-refresh exactly one caller wins
the claim and the loser lands in the reuse branch, the standard trade-off of
rotating refresh tokens.
"""

import hashlib
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from python_components import Component

from fastapi_component.auth.errors import (
    InvalidCredentialsError,
    RefreshTokenError,
    RefreshTokenExpiredError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
)
from fastapi_component.auth.passwords import hash_password, verify_password
from fastapi_component.auth.protocols import AuthUser, RefreshTokenStore, UserStore
from fastapi_component.auth.tokens import create_access_token, decode_access_token

_MIN_SECRET_LENGTH = 32  # RFC 7518 §3.2 minimum for HS256 keys
_DEFAULT_ACCESS_TTL_MINUTES = 15
_DEFAULT_REFRESH_TTL_DAYS = 30

# Verified against when login hits an unknown/IdP-only account, so both
# failure paths cost one Argon2 verification (no timing oracle on email
# existence). Not black-box testable; kept honest by inspection.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def hash_refresh_secret(secret_value: str) -> str:
    """sha256 hex digest of an opaque refresh secret.

    Deliberately not Argon2: a 256-bit random secret cannot be guessed, and
    stores must look tokens up by value on a unique index.
    """
    return hashlib.sha256(secret_value.encode()).hexdigest()


_REFRESH_COOKIE = "refresh_token"


class LoginRequest(BaseModel):
    """JSON body of ``POST {prefix}/login``."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """JSON body returned by login and refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


@dataclass
class TokenPair:
    """What a successful login/refresh yields.

    ``refresh_secret`` is the raw secret for the cookie; only its hash is
    ever stored.
    """

    access_token: str
    refresh_secret: str
    expires_in: int


class JWTAuth(Component):
    """Auth plugin component; see the module docstring.

    Injected dependencies (via ``.using({...})``): ``user_store`` and
    ``token_store`` implementing the protocols in ``protocols.py``, and
    ``config`` exposing ``JWT_SECRET_KEY`` (required, ≥32 chars) plus
    optional ``JWT_ACCESS_TOKEN_TTL_MINUTES`` / ``JWT_REFRESH_TOKEN_TTL_DAYS``.
    """

    user_store: UserStore
    token_store: RefreshTokenStore
    config: Any

    def __init__(
        self,
        *,
        scopes_by_role: Mapping[str, Sequence[str]],
        prefix: str = "/auth",
        cookie_secure: bool = True,
        cookie_samesite: str = "lax",
    ):
        super().__init__()
        self.scopes_by_role = {role: list(s) for role, s in scopes_by_role.items()}
        self.prefix = prefix
        self.cookie_secure = cookie_secure
        self.cookie_samesite = cookie_samesite

    def start(self) -> None:
        secret_key = getattr(self.config, "JWT_SECRET_KEY", None)
        if not secret_key:
            raise RuntimeError(
                "JWTAuth requires JWT_SECRET_KEY on its config component"
            )
        if len(secret_key) < _MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"JWT_SECRET_KEY must be at least {_MIN_SECRET_LENGTH} characters "
                f"(got {len(secret_key)})"
            )
        self._secret = secret_key
        self._access_ttl_minutes = int(
            getattr(
                self.config, "JWT_ACCESS_TOKEN_TTL_MINUTES", _DEFAULT_ACCESS_TTL_MINUTES
            )
        )
        self._refresh_ttl_days = int(
            getattr(
                self.config, "JWT_REFRESH_TOKEN_TTL_DAYS", _DEFAULT_REFRESH_TTL_DAYS
            )
        )

    def shutdown(self) -> None:
        pass

    def decode(self, access_token: str) -> dict[str, Any]:
        """Validate an access token and return its claims.

        Raises:
            InvalidAccessTokenError: If the token is invalid or expired.
        """
        return decode_access_token(access_token, secret=self._secret)

    async def issue_tokens(
        self, user: AuthUser, *, session_id: str | None = None
    ) -> TokenPair:
        """Mint an access/refresh pair for an already-authenticated user.

        Public so that future identity-provider logins (e.g. Google) can
        reuse the exact issuance path password login uses. Omitting
        ``session_id`` starts a new session; passing one continues an
        existing rotation chain.
        """
        session = session_id if session_id is not None else str(uuid4())
        refresh_secret = secrets.token_urlsafe(32)
        await self.token_store.insert(
            user_id=str(user.user_id),
            session_id=session,
            token_hash=hash_refresh_secret(refresh_secret),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=self._refresh_ttl_days),
        )
        access_token = create_access_token(
            subject=str(user.user_id),
            role=user.role,
            scopes=self.scopes_by_role.get(user.role, []),
            secret=self._secret,
            ttl_minutes=self._access_ttl_minutes,
        )
        return TokenPair(
            access_token=access_token,
            refresh_secret=refresh_secret,
            expires_in=self._access_ttl_minutes * 60,
        )

    async def login(self, email: str, password: str) -> TokenPair:
        """Authenticate by email/password and start a new session.

        Raises:
            InvalidCredentialsError: For unknown email, wrong password,
                inactive account, or an account without a password — one
                error type so responses cannot enumerate accounts.
        """
        user = await self.user_store.get_by_email(email)
        if user is None or user.password_hash is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError("invalid credentials")
        if not verify_password(password, user.password_hash) or not user.is_active:
            raise InvalidCredentialsError("invalid credentials")
        return await self.issue_tokens(user)

    async def refresh(self, refresh_secret: str) -> TokenPair:
        """Rotate a refresh token, detecting reuse.

        Raises:
            RefreshTokenInvalidError: Unknown token, or its user can no
                longer authenticate.
            RefreshTokenReusedError: The token was already rotated — the
                whole session is revoked as compromised before raising.
            RefreshTokenExpiredError: The token exists but has expired (an
                expired credential is not evidence of theft; no cascade).
        """
        token_hash = hash_refresh_secret(refresh_secret)
        claimed = await self.token_store.claim(token_hash)
        if claimed is None:
            found = await self.token_store.find_by_hash(token_hash)
            if found is None:
                raise RefreshTokenInvalidError("unknown refresh token")
            if found.revoked_at is not None:
                await self.token_store.revoke_session(found.session_id, "compromised")
                raise RefreshTokenReusedError("refresh token replayed after rotation")
            raise RefreshTokenExpiredError("refresh token expired")

        user = await self.user_store.get_by_id(claimed.user_id)
        if user is None or not user.is_active:
            await self.token_store.revoke_session(claimed.session_id, "logout")
            raise RefreshTokenInvalidError("user can no longer authenticate")
        return await self.issue_tokens(user, session_id=claimed.session_id)

    async def logout(self, refresh_secret: str | None) -> None:
        """Best-effort revocation of the presented token; never raises."""
        if not refresh_secret:
            return
        await self.token_store.revoke_by_hash(
            hash_refresh_secret(refresh_secret), "logout"
        )

    # ------------------------------------------------------------ routes

    def routes(self) -> APIRouter:
        """RouteProvider hook: the login/refresh/logout router.

        Runs at build time, before ``start()`` — handler bodies only touch
        settings resolved in ``start()`` at request time.
        """
        router = APIRouter(prefix=self.prefix, tags=["auth"])

        @router.post("/login", response_model=TokenResponse)
        async def login(body: LoginRequest, response: Response) -> TokenResponse:
            """Authenticate with email/password; sets the refresh cookie."""
            try:
                pair = await self.login(body.email, body.password)
            except InvalidCredentialsError:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            self._set_refresh_cookie(response, pair.refresh_secret)
            return TokenResponse(
                access_token=pair.access_token, expires_in=pair.expires_in
            )

        @router.post("/refresh", response_model=TokenResponse)
        async def refresh(request: Request, response: Response) -> TokenResponse:
            """Rotate the refresh cookie and return a fresh access token."""
            refresh_secret = request.cookies.get(_REFRESH_COOKIE)
            if not refresh_secret:
                raise HTTPException(
                    status_code=401,
                    detail="Missing refresh token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                pair = await self.refresh(refresh_secret)
            except RefreshTokenError:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid refresh token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            self._set_refresh_cookie(response, pair.refresh_secret)
            return TokenResponse(
                access_token=pair.access_token, expires_in=pair.expires_in
            )

        @router.post("/logout", status_code=204)
        async def logout(request: Request, response: Response) -> None:
            """Best-effort revoke; always clears the cookie, always 204."""
            await self.logout(request.cookies.get(_REFRESH_COOKIE))
            self._clear_refresh_cookie(response)

        return router

    def _set_refresh_cookie(self, response: Response, refresh_secret: str) -> None:
        response.set_cookie(
            _REFRESH_COOKIE,
            refresh_secret,
            max_age=self._refresh_ttl_days * 86400,
            httponly=True,
            secure=self.cookie_secure,
            samesite=self.cookie_samesite,
            path=self.prefix,
        )

    def _clear_refresh_cookie(self, response: Response) -> None:
        response.delete_cookie(
            _REFRESH_COOKIE,
            path=self.prefix,
            httponly=True,
            secure=self.cookie_secure,
            samesite=self.cookie_samesite,
        )
