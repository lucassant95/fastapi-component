"""Route discovery: include APIRouters provided by components in a System."""

from typing import Protocol, runtime_checkable

from fastapi import APIRouter, FastAPI
from python_components import Component, System


@runtime_checkable
class RouteProvider(Protocol):
    """A component that contributes an APIRouter to the application.

    Implement it by defining ``def routes(self) -> APIRouter`` on a component;
    ``include_component_routes()`` (called automatically by ``create_app``)
    includes the returned router on the application. Discovery additionally
    requires ``routes`` to be callable — a data attribute of the same name is
    ignored.

    ``routes()`` runs at build time, before the system starts, so it must not
    depend on state produced by ``start()``. Handlers run after startup and
    should resolve live components with ``Depends(component("name"))`` or
    ``Depends(get_system)``. Providers that want a URL prefix bake it into the
    router themselves via ``APIRouter(prefix=...)``.
    """

    def routes(self) -> APIRouter: ...


def include_component_routes(app: FastAPI, system: System) -> None:
    """Include the routers of every RouteProvider component in the system.

    The system is traversed depth-first in ``system_map`` insertion order,
    recursing into nested Systems; a node's own router is included before its
    children's. The root system itself may be a provider. Each component
    instance is included at most once, even if it is reachable under several
    names.

    Args:
        app: The application to include routers on.
        system: The System whose components are scanned for providers.

    Raises:
        TypeError: If a component's ``routes`` is an APIRouter instead of a
            method, or if ``routes()`` returns anything but an APIRouter.
        Exception: Whatever a component's ``routes()`` raises, with a note
            naming the component added via ``add_note``.
    """
    _include(app, system, "<system>", seen=set())


def _include(app: FastAPI, component: Component, path: str, seen: set[int]) -> None:
    if id(component) in seen:
        return
    seen.add(id(component))
    # Discovery deliberately uses callable(getattr(...)) rather than
    # isinstance(component, RouteProvider): runtime_checkable protocols only
    # check attribute presence, and 3.11 (hasattr) vs 3.12+ (getattr_static)
    # disagree on exotic attributes. This behaves identically on 3.11-3.14.
    provider = getattr(component, "routes", None)
    if isinstance(provider, APIRouter):
        raise TypeError(
            f"component '{path}' has an APIRouter attribute named 'routes'; "
            "RouteProvider requires a method: def routes(self) -> APIRouter"
        )
    if callable(provider):
        try:
            router = provider()
        except Exception as exc:
            exc.add_note(f"raised by routes() of component '{path}'")
            raise
        if not isinstance(router, APIRouter):
            raise TypeError(
                f"routes() of component '{path}' must return an APIRouter, "
                f"got {type(router).__name__}"
            )
        app.include_router(router)
    if isinstance(component, System):
        for name, child in component.system_map.items():
            child_path = name if path == "<system>" else f"{path}.{name}"
            _include(app, child, child_path, seen)
