"""Tests for the Depends-compatible helpers."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from python_components import System

from fastapi_component import component, create_app, get_system
from fastapi_component.tests.helpers import Recorder, SyncComponent


def make_system() -> System:
    return System({"cache": SyncComponent("cache", Recorder())})


def test_get_system_dependency_resolves_the_running_system():
    system = make_system()
    app = create_app(system)

    @app.get("/check")
    def check(resolved: System = Depends(get_system)):
        return {"same": resolved is system}

    with TestClient(app) as client:
        assert client.get("/check").json() == {"same": True}


def test_component_dependency_resolves_by_name():
    app = create_app(make_system())

    @app.get("/cache-name")
    def cache_name(cache=Depends(component("cache"))):
        return {"name": cache.name}

    with TestClient(app) as client:
        assert client.get("/cache-name").json() == {"name": "cache"}


def test_component_dependency_honors_custom_state_key():
    app = create_app(make_system(), state_key="valley")

    @app.get("/cache-name")
    def cache_name(cache=Depends(component("cache", state_key="valley"))):
        return {"name": cache.name}

    with TestClient(app) as client:
        assert client.get("/cache-name").json() == {"name": "cache"}


def test_missing_component_name_raises_a_clear_error():
    app = create_app(make_system())

    @app.get("/nope")
    def nope(thing=Depends(component("nope"))):
        return {}

    with TestClient(app) as client:
        with pytest.raises(KeyError, match="not found in system map"):
            client.get("/nope")


def test_missing_system_raises_a_helpful_error():
    app = FastAPI()  # built without system_lifespan/create_app

    @app.get("/check")
    def check(resolved: System = Depends(get_system)):
        return {}

    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="No System found"):
            client.get("/check")
