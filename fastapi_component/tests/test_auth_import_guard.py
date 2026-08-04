"""Tests for the optional-extra import guard of fastapi_component.auth."""

import importlib
import sys

import pytest


def test_auth_import_without_extras_names_the_extra(monkeypatch):
    """Importing the auth package without pyjwt installed must point at the extra."""
    monkeypatch.setitem(sys.modules, "jwt", None)
    for cached in [m for m in sys.modules if m.startswith("fastapi_component.auth")]:
        monkeypatch.delitem(sys.modules, cached)

    with pytest.raises(ImportError, match=r"fastapi-component\[auth\]"):
        importlib.import_module("fastapi_component.auth")
