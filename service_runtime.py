import asyncio
from collections.abc import Awaitable, Callable


_SERVICE_READY = False


def set_service_ready(ready: bool) -> None:
    global _SERVICE_READY
    _SERVICE_READY = bool(ready)


def is_service_ready() -> bool:
    return _SERVICE_READY


def run_event_loop(
    loop: asyncio.AbstractEventLoop,
    startup: Callable[[], Awaitable[None]],
    shutdown: Callable[[], Awaitable[None]],
) -> None:
    """Keep the existing client-bound loop alive and propagate startup failures."""
    startup_task = loop.create_task(startup())

    def stop_on_failure(task: asyncio.Task) -> None:
        if task.cancelled() or task.exception() is not None:
            loop.stop()

    startup_task.add_done_callback(stop_on_failure)
    try:
        loop.run_forever()
        if startup_task.done():
            startup_task.result()
    finally:
        loop.run_until_complete(shutdown())
        loop.stop()
