"""FastAPI integration for python-components.

Run a python-components System inside a FastAPI application lifespan:
components with ``async def start()`` are awaited in the server's event loop,
and everything shuts down in reverse dependency order when the server stops.
Components can contribute routers by implementing ``RouteProvider``.
"""

from fastapi_component.app import create_app
from fastapi_component.dependencies import component, get_system
from fastapi_component.lifespan import system_lifespan
from fastapi_component.routing import RouteProvider, include_component_routes

__version__ = "0.1.0"

__all__ = [
    "RouteProvider",
    "component",
    "create_app",
    "get_system",
    "include_component_routes",
    "system_lifespan",
]
