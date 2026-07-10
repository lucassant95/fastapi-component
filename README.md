# fastapi-component

FastAPI integration for [python-components](https://github.com/lucassant95/python-components):
run a component `System` inside the application lifespan.

Declaring that a component needs async initialization is just defining
`async def start()` — the `System` awaits it inside the server's event loop
when the application starts, and shuts everything down in reverse dependency
order when the server stops. This library wires that lifecycle into FastAPI
without hiding any native FastAPI feature.

```bash
pip install fastapi-component
```

Requires Python >= 3.11, `fastapi >= 0.115` and `python-components >= 0.4, < 0.5`.

## Usage

### 1. Native-first: plug the lifespan into your own app

If you build your `FastAPI` app yourself (custom middleware, sub-apps,
anything), use `system_lifespan` — it is a standard lifespan callable:

```python
from fastapi import FastAPI
from python_components import System
from fastapi_component import system_lifespan

system = System({
    "config": Config(),
    "database": Database().using(["config"]),      # async def start() → awaited in the loop
    "consumer": QueueConsumer().using(["config"]),  # async def start() / async def shutdown()
})

app = FastAPI(title="My API", lifespan=system_lifespan(system))
```

On startup the system is exposed as `app.state.system` (configurable via
`state_key=`) and started with `astart()`; on shutdown it is stopped with
`ashutdown()`.

Have startup/teardown logic of your own? Compose it with `wrap=` — it runs
strictly *inside* the system's lifecycle (components are up before it enters,
still up when it exits), and whatever it yields becomes regular
[lifespan state](https://www.starlette.io/lifespan/#lifespan-state):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def app_lifespan(app):
    ml_model = await load_model()
    yield {"ml_model": ml_model}
    await ml_model.close()

app = FastAPI(lifespan=system_lifespan(system, wrap=app_lifespan))
```

### 2. Batteries: `create_app`

A thin factory when you don't need to construct `FastAPI` yourself. Every
native constructor argument passes through untouched — the one exception being
the legacy `on_startup`/`on_shutdown` event kwargs: because `create_app` always
installs a lifespan (which makes FastAPI ignore them), passing either raises
`TypeError` instead of silently dropping the handlers. Move that logic into
`lifespan=` (composed inside the system's lifecycle):

```python
from fastapi_component import create_app

app = create_app(
    system,
    routers=[users_router, orders_router],
    configure=lambda app: app.add_middleware(CORSMiddleware, allow_origins=["*"]),
    lifespan=app_lifespan,          # composed inside the system's lifecycle
    title="My API",                 # ← any FastAPI(...) kwarg:
    dependencies=[Depends(auth)],   #   app-level dependencies,
    exception_handlers=handlers,    #   exception handlers, docs_url, ...
)
```

`configure` is a build-time hook called once with the app — middleware,
instrumentation (e.g. Prometheus), extra endpoints, anything.

### 3. Idiomatic DI in handlers

```python
from fastapi import Depends
from fastapi_component import component, get_system

@app.get("/status")
def status(system=Depends(get_system)):
    return {"state": system.state.value}

@app.get("/users")
async def list_users(db=Depends(component("database"))):
    return await db.fetch_all("SELECT * FROM users")
```

Handlers can also reach the system directly via `request.app.state.system`.

## Failure semantics

- **Startup failure (fail-fast):** if a component's `start()` raises, the
  components already started are rolled back (shut down in reverse order,
  automatic in python-components 0.4), `ComponentStartError` propagates and
  the server aborts startup. Nothing is left half-running.
- **Runtime failure:** this is a lifecycle manager, not a supervisor — there
  is no in-process restart of individual components. Clients that recover by
  design (e.g. lazy connection pools) self-heal on the next use; for anything
  irrecoverable, expose component health on an endpoint (the system is at
  `app.state.system`) and let your orchestrator's liveness probe restart the
  process.
- **Shutdown failure:** a component failing to shut down does not prevent the
  others from shutting down; the failures are aggregated in an
  `ExceptionGroup`, logged and re-raised so a non-clean exit is visible. If the
  app body (or `wrap` teardown) already raised, that exception stays primary and
  the shutdown `ExceptionGroup` is logged and attached to it via `add_note`
  rather than masking it (mirroring python-components' `System.__aexit__`).
- **Double start:** the lifespan refuses (with `RuntimeError`) a system that
  is already started — it must own the system's lifecycle. A system left in the
  STOPPED state is restarted, so each component's `start()` runs again;
  components must tolerate that if the app lifecycle can cycle.

## Development

```bash
uv sync
uv run pytest
uv run ruff format --check . && uv run ruff check .
```

## License

MIT
