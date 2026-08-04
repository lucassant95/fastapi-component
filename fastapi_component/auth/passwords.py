"""Argon2 password hashing helpers.

Argon2 is used for passwords only. Refresh-token secrets are deliberately
hashed with plain sha256 instead (see ``component.py``): they are high-entropy
random values that must support O(1) lookup by hash, which a salted slow hash
cannot provide and does not need.
"""

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2 (salted; unique per call)."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored Argon2 hash."""
    return _hasher.verify(password, password_hash)
