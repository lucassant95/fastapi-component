"""FastAPI lifespan integration for python-components Systems."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from python_components import ComponentStartError, System, SystemState
from starlette.types import Lifespan

logger = logging.getLogger(__name__)


def system_lifespan(
    system: System,
    *,
    wrap: Lifespan[FastAPI] | None = None,
    state_key: str = "system",
) -> Lifespan[FastAPI]:
    """Build a FastAPI lifespan that owns the lifecycle of a component System.

    On startup the system is exposed as ``app.state.<state_key>`` and started
    with ``System.astart()``, so components declared with ``async def start``
    run inside the server's event loop. On shutdown the system is stopped in
    reverse dependency order with ``System.ashutdown()``.

    Args:
        system: The System whose lifecycle the application should own. It must
            not be started already; the lifespan starts and stops it.
        wrap: An optional application lifespan composed inside the system's:
            it enters after every component has started and exits before any
            component shuts down. Anything it yields becomes lifespan state.
        state_key: Attribute name under ``app.state`` where the system is
            exposed.

    Returns:
        A lifespan context manager suitable for ``FastAPI(lifespan=...)``.

    A system in the STOPPED state is restarted, so each component's ``start()``
    runs again; components must tolerate that if the app lifecycle can cycle.

    Exception precedence follows python-components' ``System.__aexit__``: if the
    app body (or ``wrap`` teardown) raises, that exception stays primary and a
    shutdown ``ExceptionGroup`` is logged and attached via ``add_note`` rather
    than masking it. When the body exits cleanly, a shutdown ``ExceptionGroup``
    still propagates.

    Raises (when the application starts up or shuts down):
        RuntimeError: If the system is already started when the lifespan begins.
        ComponentStartError: If a component fails to start. Components that had
            already started are rolled back before the error propagates, and
            the server aborts startup.
        ExceptionGroup: If one or more components fail to shut down (and the app
            body exited cleanly). The remaining components are still shut down
            first.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if system.state is SystemState.STARTED:
            raise RuntimeError(
                "System is already started; system_lifespan() must own the system "
                "lifecycle. Do not call start()/astart() before the app runs."
            )
        setattr(app.state, state_key, system)
        try:
            await system.astart()
        except ComponentStartError as exc:
            logger.error(
                "Aborting application startup: component '%s' failed to start",
                exc.component_name,
            )
            raise
        logger.info(
            "Component system started (%d component(s))", len(system.system_map)
        )
        try:
            if wrap is None:
                yield
            else:
                async with wrap(app) as state:
                    yield state
        except BaseException as exc:
            # The body (or wrap teardown) raised. That exception is primary;
            # mirror python-components' System.__aexit__ convention: still shut
            # the system down, but if shutdown itself fails, log and attach the
            # failure as a note rather than masking the original exception.
            try:
                await system.ashutdown()
            except ExceptionGroup as shutdown_exc:
                logger.exception("Component system shutdown finished with failures")
                exc.add_note(f"additionally, system shutdown failed: {shutdown_exc!r}")
            raise
        else:
            # Clean exit from the body: a shutdown ExceptionGroup is the only
            # error in flight, so it must propagate.
            try:
                await system.ashutdown()
            except ExceptionGroup:
                logger.exception("Component system shutdown finished with failures")
                raise
            logger.info("Component system shut down cleanly")

    return lifespan
