"""Tests for system_lifespan plugged into a plain, natively-built FastAPI app."""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from python_components import ComponentStartError, System, SystemState

from fastapi_component import system_lifespan
from fastapi_component.tests.helpers import (
    AsyncComponent,
    FailingShutdownComponent,
    FailingStartComponent,
    Recorder,
    SyncComponent,
)


def make_system(recorder: Recorder) -> System:
    """A three-component chain mixing sync and async lifecycles."""
    return System(
        {
            "database": AsyncComponent("database", recorder),
            "cache": SyncComponent("cache", recorder).using(["database"]),
            "consumer": AsyncComponent("consumer", recorder).using(["cache"]),
        }
    )


def test_starts_and_stops_components_around_the_app_lifetime():
    recorder = Recorder()
    system = make_system(recorder)
    app = FastAPI(lifespan=system_lifespan(system))

    with TestClient(app):
        assert system.state is SystemState.STARTED
        assert recorder.of("start") == ["database", "cache", "consumer"]
        assert recorder.of("shutdown") == []
        assert app.state.system is system

    assert system.state is SystemState.STOPPED
    assert recorder.of("shutdown") == ["consumer", "cache", "database"]


def test_async_components_start_inside_the_running_event_loop():
    recorder = Recorder()
    database = AsyncComponent("database", recorder)
    system = System({"database": database})
    app = FastAPI(lifespan=system_lifespan(system))

    with TestClient(app):
        assert database.started_in_loop


def test_routes_can_resolve_components_while_running():
    recorder = Recorder()
    system = make_system(recorder)
    app = FastAPI(lifespan=system_lifespan(system))

    @app.get("/component-class")
    def component_class(request: Request):
        cache = request.app.state.system.get_component("cache")
        return {"cls": type(cache).__name__}

    with TestClient(app) as client:
        assert client.get("/component-class").json() == {"cls": "SyncComponent"}


def test_wrap_lifespan_runs_inside_the_system_lifecycle():
    recorder = Recorder()
    system = System({"database": AsyncComponent("database", recorder)})

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        recorder.record("app", "start")
        yield
        recorder.record("app", "shutdown")

    app = FastAPI(lifespan=system_lifespan(system, wrap=app_lifespan))
    with TestClient(app):
        pass

    assert recorder.events == [
        ("database", "start"),
        ("app", "start"),
        ("app", "shutdown"),
        ("database", "shutdown"),
    ]


def test_wrap_lifespan_state_reaches_requests():
    system = System({"database": AsyncComponent("database", Recorder())})

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        yield {"greeting": "hello"}

    app = FastAPI(lifespan=system_lifespan(system, wrap=app_lifespan))

    @app.get("/greeting")
    def greeting(request: Request):
        return {"greeting": request.state.greeting}

    with TestClient(app) as client:
        assert client.get("/greeting").json() == {"greeting": "hello"}


def test_wrap_startup_failure_still_shuts_the_system_down():
    recorder = Recorder()
    system = System({"database": AsyncComponent("database", recorder)})

    @asynccontextmanager
    async def broken_lifespan(app: FastAPI):
        raise RuntimeError("app startup failed")
        yield

    app = FastAPI(lifespan=system_lifespan(system, wrap=broken_lifespan))
    with pytest.raises(RuntimeError, match="app startup failed"):
        with TestClient(app):
            pass

    assert system.state is SystemState.STOPPED
    assert recorder.of("shutdown") == ["database"]


def test_component_start_failure_rolls_back_and_aborts_startup():
    recorder = Recorder()
    system = System(
        {
            "database": AsyncComponent("database", recorder),
            "broken": FailingStartComponent("broken", recorder).using(["database"]),
        }
    )
    app = FastAPI(lifespan=system_lifespan(system))

    with pytest.raises(ComponentStartError) as excinfo:
        with TestClient(app):
            pass

    assert excinfo.value.component_name == "broken"
    # Only the component that had started is rolled back.
    assert recorder.of("shutdown") == ["database"]
    assert system.state is SystemState.STOPPED


def test_shutdown_failure_propagates_as_exception_group():
    recorder = Recorder()
    system = System(
        {
            "database": AsyncComponent("database", recorder),
            "broken": FailingShutdownComponent("broken", recorder).using(["database"]),
        }
    )
    app = FastAPI(lifespan=system_lifespan(system))

    with pytest.raises(ExceptionGroup):
        with TestClient(app):
            pass

    # The failure did not prevent the remaining component from stopping.
    assert recorder.of("shutdown") == ["database"]
    assert system.state is SystemState.STOPPED


def test_custom_state_key():
    system = System({"database": AsyncComponent("database", Recorder())})
    app = FastAPI(lifespan=system_lifespan(system, state_key="components"))

    with TestClient(app):
        assert app.state.components is system


def test_rejects_an_already_started_system():
    recorder = Recorder()
    system = System({"cache": SyncComponent("cache", recorder)})
    system.start()

    app = FastAPI(lifespan=system_lifespan(system))
    with pytest.raises(RuntimeError, match="already started"):
        with TestClient(app):
            pass
