"""Tests for Argon2 password hashing helpers."""

from fastapi_component.auth.passwords import hash_password, verify_password


def test_hash_and_verify_round_trip():
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed)


def test_wrong_password_fails_verification():
    hashed = hash_password("correct horse battery staple")

    assert not verify_password("Tr0ub4dor&3", hashed)


def test_same_password_hashes_differently_each_time():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second


def test_hash_is_argon2():
    assert hash_password("anything").startswith("$argon2")
