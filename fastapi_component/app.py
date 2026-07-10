"""Application factory built on top of system_lifespan."""

from collections.abc import Callable, Sequence

from fastapi import APIRouter, FastAPI
from python_components import System
from starlette.types import Lifespan

from fastapi_component.lifespan import system_lifespan


def create_app(
    system: System,
    *,
    routers: Sequence[APIRouter] = (),
    configure: Callable[[FastAPI], None] | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
    state_key: str = "system",
    **fastapi_kwargs,
) -> FastAPI:
    """Create a FastAPI application whose lifespan owns the given System.

    A thin convenience over ``system_lifespan()``: every native FastAPI
    constructor argument (``title``, ``version``, ``dependencies``,
    ``exception_handlers``, ``docs_url``, ...) passes through untouched, so
    nothing FastAPI offers is hidden behind this factory.

    Args:
        system: The System the application lifespan should own.
        routers: Routers to include on the application.
        configure: Build-time hook called once with the application, for
            middleware, instrumentation or any other native customization.
        lifespan: An application lifespan composed inside the system's
            (see ``system_lifespan``'s ``wrap``).
        state_key: Attribute name under ``app.state`` where the system is
            exposed.
        **fastapi_kwargs: Forwarded verbatim to ``FastAPI()``.

    Returns:
        The configured FastAPI application (not yet started).
    """
    app = FastAPI(
        lifespan=system_lifespan(system, wrap=lifespan, state_key=state_key),
        **fastapi_kwargs,
    )
    for router in routers:
        app.include_router(router)
    if configure is not None:
        configure(app)
    return app
