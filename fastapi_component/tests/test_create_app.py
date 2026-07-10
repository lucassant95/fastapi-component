"""Tests for the create_app convenience factory."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from python_components import System

from fastapi_component import create_app
from fastapi_component.tests.helpers import AsyncComponent, Recorder, SyncComponent


def make_system(recorder: Recorder | None = None) -> System:
    return System({"cache": SyncComponent("cache", recorder or Recorder())})


def make_ping_router() -> APIRouter:
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"pong": True}

    return router


def test_fastapi_kwargs_pass_through():
    app = create_app(
        make_system(), title="My API", version="9.9.9", docs_url="/documentation"
    )

    assert app.title == "My API"
    assert app.version == "9.9.9"
    assert app.docs_url == "/documentation"


def test_routers_are_registered():
    app = create_app(make_system(), routers=[make_ping_router()])

    with TestClient(app) as client:
        assert client.get("/ping").json() == {"pong": True}


def test_native_app_level_dependencies_still_apply():
    calls = []

    def guard():
        calls.append("guard")

    app = create_app(
        make_system(), routers=[make_ping_router()], dependencies=[Depends(guard)]
    )

    with TestClient(app) as client:
        client.get("/ping")

    assert calls == ["guard"]


def test_native_exception_handlers_still_apply():
    class TeapotError(Exception):
        pass

    def handle_teapot(request: Request, exc: TeapotError) -> JSONResponse:
        return JSONResponse(status_code=418, content={"detail": "teapot"})

    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise TeapotError()

    app = create_app(
        make_system(),
        routers=[router],
        exception_handlers={TeapotError: handle_teapot},
    )

    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 418
    assert response.json() == {"detail": "teapot"}


def test_configure_hook_runs_once_at_build_time():
    seen = []

    app = create_app(make_system(), configure=seen.append)

    assert seen == [app]


def test_user_lifespan_is_composed_inside_the_system():
    recorder = Recorder()
    system = System({"database": AsyncComponent("database", recorder)})

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        recorder.record("app", "start")
        yield
        recorder.record("app", "shutdown")

    app = create_app(system, lifespan=app_lifespan)
    with TestClient(app):
        pass

    assert recorder.events == [
        ("database", "start"),
        ("app", "start"),
        ("app", "shutdown"),
        ("database", "shutdown"),
    ]


def test_custom_state_key():
    system = make_system()
    app = create_app(system, state_key="valley")

    with TestClient(app):
        assert app.state.valley is system
