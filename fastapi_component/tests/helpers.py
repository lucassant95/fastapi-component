"""Shared test components: recorders that log lifecycle events in order."""

import asyncio

from python_components import Component


class Recorder:
    """Collects (component_name, event) tuples in occurrence order."""

    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def record(self, name: str, event: str) -> None:
        self.events.append((name, event))

    def of(self, event: str) -> list[str]:
        """Names that recorded the given event, in order."""
        return [name for name, e in self.events if e == event]


class SyncComponent(Component):
    """Component with synchronous lifecycle methods."""

    def __init__(self, name: str, recorder: Recorder):
        super().__init__()
        self.name = name
        self.recorder = recorder

    def start(self):
        self.recorder.record(self.name, "start")

    def shutdown(self):
        self.recorder.record(self.name, "shutdown")


class AsyncComponent(Component):
    """Component with async lifecycle methods; records whether a loop was live."""

    def __init__(self, name: str, recorder: Recorder):
        super().__init__()
        self.name = name
        self.recorder = recorder
        self.started_in_loop = False

    async def start(self):
        self.started_in_loop = asyncio.get_running_loop() is not None
        self.recorder.record(self.name, "start")

    async def shutdown(self):
        self.recorder.record(self.name, "shutdown")


class FailingStartComponent(Component):
    """Component whose start always raises."""

    def __init__(self, name: str, recorder: Recorder):
        super().__init__()
        self.name = name
        self.recorder = recorder

    async def start(self):
        self.recorder.record(self.name, "start-attempt")
        raise RuntimeError(f"{self.name} cannot start")

    async def shutdown(self):
        self.recorder.record(self.name, "shutdown")


class FailingShutdownComponent(Component):
    """Component whose shutdown always raises."""

    def __init__(self, name: str, recorder: Recorder):
        super().__init__()
        self.name = name
        self.recorder = recorder

    async def start(self):
        self.recorder.record(self.name, "start")

    async def shutdown(self):
        self.recorder.record(self.name, "shutdown-attempt")
        raise RuntimeError(f"{self.name} cannot shut down")
