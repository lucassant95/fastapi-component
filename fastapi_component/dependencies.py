"""FastAPI dependency helpers for accessing the running System."""

from collections.abc import Callable

from fastapi import Request
from python_components import Component, System


def _resolve_system(request: Request, state_key: str) -> System:
    system = getattr(request.app.state, state_key, None)
    if system is None:
        raise RuntimeError(
            f"No System found at app.state.{state_key}; build the application "
            "with create_app() or FastAPI(lifespan=system_lifespan(system))"
        )
    return system


def get_system(request: Request) -> System:
    """Resolve the running System, for use as ``Depends(get_system)``.

    Raises:
        RuntimeError: If no System is exposed at ``app.state.system``.
    """
    return _resolve_system(request, "system")


def component(
    name: str, *, state_key: str = "system"
) -> Callable[[Request], Component]:
    """Build a dependency that resolves a component by name.

    Example:
        >>> @app.get("/auctions")
        ... def list_auctions(db=Depends(component("async_database"))):
        ...     ...

    Args:
        name: The component's name in the system map.
        state_key: Attribute name under ``app.state`` where the system is
            exposed.

    Raises (at request time):
        RuntimeError: If no System is exposed at ``app.state.<state_key>``.
        KeyError: If the component name is not in the system map.
    """

    def _provider(request: Request) -> Component:
        return _resolve_system(request, state_key).get_component(name)

    return _provider
