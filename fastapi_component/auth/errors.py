"""Domain errors raised by the auth plugin.

The router maps ``InvalidCredentialsError`` and every ``RefreshTokenError``
subtype to a generic 401 so responses never reveal *why* authentication
failed (no account enumeration, no token-state oracle). The subtypes exist
for logging and tests, not for response bodies.
"""


class InvalidCredentialsError(Exception):
    """Login failed: unknown email, wrong password, inactive or IdP-only account."""


class RefreshTokenError(Exception):
    """Base class for refresh failures; callers catch this one type."""


class RefreshTokenInvalidError(RefreshTokenError):
    """The presented token is unknown, or its user can no longer authenticate."""


class RefreshTokenExpiredError(RefreshTokenError):
    """The presented token exists but its lifetime has elapsed."""


class RefreshTokenReusedError(RefreshTokenError):
    """An already-rotated token was replayed; the session has been revoked."""
