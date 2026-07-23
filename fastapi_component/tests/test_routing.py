"""Tests for RouteProvider discovery and include_component_routes."""

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from python_components import System

from fastapi_component import (
    RouteProvider,
    component,
    include_component_routes,
    system_lifespan,
)
from fastapi_component.tests.helpers import (
    ProviderComponent,
    Recorder,
    SyncComponent,
    registered_paths,
)


class RoutedSystem(System):
    """A System that also provides its own router at /system."""

    def routes(self) -> APIRouter:
        router = APIRouter()

        @router.get("/system")
        def info():
            return {"component": "system"}

        return router


class DataRoutesComponent(SyncComponent):
    """Component with a non-callable ``routes`` data attribute."""

    def __init__(self, name: str, recorder: Recorder):
        super().__init__(name, recorder)
        self.routes = ["not", "a", "method"]


class RouterAttributeComponent(SyncComponent):
    """Component that misuses the protocol: ``routes`` is an APIRouter."""

    def __init__(self, name: str, recorder: Recorder):
        super().__init__(name, recorder)
        self.routes = APIRouter()


class BadReturnComponent(SyncComponent):
    """Component whose routes() returns something that is not an APIRouter."""

    def routes(self):
        return {"not": "a router"}


class ExplodingRoutesComponent(SyncComponent):
    """Component whose routes() raises."""

    def routes(self):
        raise ValueError("boom")


class DependentProviderComponent(SyncComponent):
    """Provider whose handler resolves another component at request time."""

    def routes(self) -> APIRouter:
        router = APIRouter()

        @router.get("/whoami")
        def whoami(cache=Depends(component("cache"))):
            return {"cache": cache.name}

        return router


def test_route_provider_is_runtime_checkable():
    provider = ProviderComponent("users", Recorder())
    plain = SyncComponent("cache", Recorder())

    assert isinstance(provider, RouteProvider)
    assert not isinstance(plain, RouteProvider)


def test_includes_routes_from_providers():
    recorder = Recorder()
    system = System(
        {
            "users": ProviderComponent("users", recorder),
            "cache": SyncComponent("cache", recorder),
        }
    )
    app = FastAPI()

    include_component_routes(app, system)

    client = TestClient(app)
    assert client.get("/users").json() == {"component": "users"}


def test_discovery_follows_insertion_order_depth_first():
    recorder = Recorder()
    sub = System(
        {
            "b1": ProviderComponent("b1", recorder),
            "b2": ProviderComponent("b2", recorder),
        }
    )
    system = System(
        {
            "a": ProviderComponent("a", recorder),
            "sub": sub,
            "c": ProviderComponent("c", recorder),
        }
    )
    app = FastAPI()

    include_component_routes(app, system)

    assert registered_paths(app)[-4:] == ["/a", "/b1", "/b2", "/c"]


def test_nested_system_provider_included_before_its_children():
    nested = RoutedSystem({"child": ProviderComponent("child", Recorder())})
    system = System({"nested": nested})
    app = FastAPI()

    include_component_routes(app, system)

    assert registered_paths(app)[-2:] == ["/system", "/child"]


def test_root_system_can_be_a_provider():
    system = RoutedSystem({"child": ProviderComponent("child", Recorder())})
    app = FastAPI()

    include_component_routes(app, system)

    assert registered_paths(app)[-2:] == ["/system", "/child"]


def test_same_instance_under_two_names_included_once():
    provider = ProviderComponent("users", Recorder())
    system = System({"users": provider, "alias": provider})
    app = FastAPI()

    include_component_routes(app, system)

    assert registered_paths(app).count("/users") == 1


def test_non_callable_routes_attribute_is_skipped():
    system = System({"data": DataRoutesComponent("data", Recorder())})
    app = FastAPI()
    routes_before = len(app.routes)

    include_component_routes(app, system)

    assert len(app.routes) == routes_before


def test_router_valued_routes_attribute_raises_helpful_error():
    system = System({"users": RouterAttributeComponent("users", Recorder())})
    app = FastAPI()

    with pytest.raises(TypeError, match=r"users.*method"):
        include_component_routes(app, system)


def test_routes_returning_non_router_raises_type_error():
    system = System({"bad": BadReturnComponent("bad", Recorder())})
    app = FastAPI()

    with pytest.raises(TypeError, match=r"bad.*dict"):
        include_component_routes(app, system)


def test_routes_exception_propagates_with_nested_component_path_note():
    inner = System({"exploding": ExplodingRoutesComponent("exploding", Recorder())})
    system = System({"outer": inner})
    app = FastAPI()

    with pytest.raises(ValueError, match="boom") as excinfo:
        include_component_routes(app, system)

    assert "outer.exploding" in excinfo.value.__notes__[0]


def test_empty_system_is_a_noop():
    app = FastAPI()
    routes_before = len(app.routes)

    include_component_routes(app, System({}))

    assert len(app.routes) == routes_before


def test_native_first_end_to_end_with_component_dependency():
    recorder = Recorder()
    system = System(
        {
            "cache": SyncComponent("cache", recorder),
            "api": DependentProviderComponent("api", recorder),
        }
    )
    app = FastAPI(lifespan=system_lifespan(system))
    include_component_routes(app, system)

    with TestClient(app) as client:
        assert client.get("/whoami").json() == {"cache": "cache"}

    assert recorder.of("start") == ["cache", "api"]
