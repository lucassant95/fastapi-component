"""In-memory fake stores for auth plugin tests.

``FakeTokenStore`` mirrors the SQL semantics the protocols demand — most
importantly that ``claim`` only succeeds on a live row and revokes it in the
same step.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from python_components import Component

from fastapi_component.auth.protocols import RefreshTokenRecord


class StubConfig(Component):
    """Component exposing arbitrary settings as plain attributes."""

    def __init__(self, **settings):
        super().__init__()
        for name, value in settings.items():
            setattr(self, name, value)

    def start(self):
        pass

    def shutdown(self):
        pass


@dataclass
class FakeUser:
    """Plain-attribute user satisfying the AuthUser protocol."""

    user_id: str
    email: str
    password_hash: str | None
    scopes: tuple[str, ...] = ("analytics:read",)
    is_active: bool = True


class FakeUserStore(Component):
    """Dict-backed UserStore; email lookup is case-insensitive like citext.

    A Component so it can sit in a System map for router tests; the no-op
    lifecycle does not get in the way of direct use in unit tests.
    """

    def __init__(self, users: list[FakeUser]):
        super().__init__()
        self.users = list(users)

    def start(self):
        pass

    def shutdown(self):
        pass

    async def get_by_email(self, email: str) -> FakeUser | None:
        for user in self.users:
            if user.email.lower() == email.lower():
                return user
        return None

    async def get_by_id(self, user_id: str) -> FakeUser | None:
        for user in self.users:
            if user.user_id == user_id:
                return user
        return None


@dataclass
class _Row:
    user_id: str
    session_id: str
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None


class FakeTokenStore(Component):
    """Dict-backed RefreshTokenStore keyed by token hash."""

    def __init__(self):
        super().__init__()
        self.rows: dict[str, _Row] = {}

    def start(self):
        pass

    def shutdown(self):
        pass

    async def insert(
        self, *, user_id: str, session_id: str, token_hash: str, expires_at: datetime
    ) -> None:
        self.rows[token_hash] = _Row(
            user_id=user_id,
            session_id=session_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

    async def claim(self, token_hash: str) -> RefreshTokenRecord | None:
        row = self.rows.get(token_hash)
        now = datetime.now(timezone.utc)
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            return None
        row.revoked_at = now
        row.revoked_reason = "rotated"
        return self._record(row)

    async def find_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        row = self.rows.get(token_hash)
        return self._record(row) if row else None

    async def revoke_session(self, session_id: str, reason: str) -> None:
        now = datetime.now(timezone.utc)
        for row in self.rows.values():
            if row.session_id == session_id and row.revoked_at is None:
                row.revoked_at = now
                row.revoked_reason = reason

    async def revoke_by_hash(self, token_hash: str, reason: str) -> None:
        row = self.rows.get(token_hash)
        if row and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            row.revoked_reason = reason

    def live_rows(self) -> list[_Row]:
        """Rows that are unrevoked and unexpired, for assertions."""
        now = datetime.now(timezone.utc)
        return [
            row
            for row in self.rows.values()
            if row.revoked_at is None and row.expires_at > now
        ]

    @staticmethod
    def _record(row: _Row) -> RefreshTokenRecord:
        return RefreshTokenRecord(
            user_id=row.user_id,
            session_id=row.session_id,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )
