# Design: component-declared routes (`RouteProvider` + `include_component_routes`)

Date: 2026-07-23
Status: implemented

## Problem

Routing was entirely manual: users hand-wrote `APIRouter`s and passed them to
`create_app(system, routers=[...])`, with no link between a component and the
endpoints it serves. Components that conceptually own routes (a users service,
a health-check component) could not ship them alongside their lifecycle.

## Decisions

1. **API shape** — a `@runtime_checkable` Protocol `RouteProvider` in
   `fastapi_component.routing` with one method, `def routes(self) -> APIRouter`.
   `python-components` stays untouched (framework-agnostic; must not import
   FastAPI).
2. **Integration** — a public helper `include_component_routes(app, system)`;
   `create_app` calls it automatically (opt-out `component_routes=False`),
   native-first users call it explicitly after building their app.
3. **Nesting** — discovery recurses depth-first into nested `System`s, in
   `system_map` insertion order, a node's own router before its children's.
   The root system itself may be a provider. A seen-set keyed by `id()`
   includes each instance at most once and terminates on cyclic composition.

## Semantics

- **Ordering / precedence:** in `create_app`, explicit `routers=` are included
  first (Starlette is first-match-wins, so explicit routers shadow component
  routes on collision); component routes next; `configure` runs last and
  observes the fully-routed app.
- **Build-time constraint:** the app is built before the system starts, so
  `routes()` runs on un-started components. Handlers resolve live components
  at request time via `Depends(component("name"))` / `Depends(get_system)`.
- **Discovery predicate** is `callable(getattr(component, "routes", None))`,
  not `isinstance(x, RouteProvider)`: runtime-checkable protocols only check
  attribute presence, and Python 3.11 (`hasattr`) vs 3.12+ (`getattr_static`)
  diverge on exotic attributes. The protocol remains the public typed contract.

## Error handling (all build-time, deterministic)

| Case | Behavior |
|---|---|
| `routes` attribute exists but is not callable | Skipped silently |
| `routes` is an `APIRouter` instance | `TypeError` with guidance (checked before the callable branch — `APIRouter` is itself callable as an ASGI app) |
| `routes()` returns a non-`APIRouter` | `TypeError` naming the component path and actual type |
| `routes()` raises | Propagates with `add_note` naming the component path (e.g. `outer.exploding`) |
| Empty system / no providers | No-op |
