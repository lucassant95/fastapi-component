"""Storage protocols the auth plugin consumes.

Applications implement these structurally (no inheritance required) and hand
the implementing component(s) to ``JWTAuth`` via dependency injection. All
identifiers cross this boundary as strings; consumers that store UUIDs
convert at their own edge.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class AuthUser(Protocol):
    """The minimal user shape the plugin needs.

    ``password_hash`` is ``None`` for accounts that only authenticate through
    an external identity provider and therefore cannot use password login.
    """

    user_id: UUID | str
    email: str
    password_hash: str | None
    role: str
    is_active: bool


@dataclass
class RefreshTokenRecord:
    """Snapshot of a stored refresh token, as returned by a store."""

    user_id: str
    session_id: str
    expires_at: datetime
    revoked_at: datetime | None


@runtime_checkable
class UserStore(Protocol):
    """Read access to user accounts."""

    async def get_by_email(self, email: str) -> AuthUser | None:
        """Return the user with this email (case-insensitive), or ``None``."""
        ...

    async def get_by_id(self, user_id: str) -> AuthUser | None:
        """Return the user with this id, or ``None``."""
        ...


@runtime_checkable
class RefreshTokenStore(Protocol):
    """Persistence for hashed refresh tokens, keyed by sha256 hex digest.

    Rows belonging to one login form a rotation chain sharing a
    ``session_id``; at most one row per chain is live (unrevoked, unexpired)
    at any time.
    """

    async def insert(
        self, *, user_id: str, session_id: str, token_hash: str, expires_at: datetime
    ) -> None:
        """Persist a new live token row."""
        ...

    async def claim(self, token_hash: str) -> RefreshTokenRecord | None:
        """Atomically revoke a *live* token with reason ``"rotated"``.

        Returns the claimed record, or ``None`` if no live (unrevoked,
        unexpired) row matches. This is the linchpin of rotation: under
        concurrent presentation of the same token, exactly one caller may
        receive a record.
        """
        ...

    async def find_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        """Return the row for this hash regardless of state, or ``None``."""
        ...

    async def revoke_session(self, session_id: str, reason: str) -> None:
        """Revoke every still-live row in the session."""
        ...

    async def revoke_by_hash(self, token_hash: str, reason: str) -> None:
        """Revoke the row for this hash if it is still live; never raise."""
        ...
