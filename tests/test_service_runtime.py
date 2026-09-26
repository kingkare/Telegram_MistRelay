import tests  # noqa: F401
import asyncio
import unittest

from service_runtime import run_event_loop


class ServiceRuntimeTests(unittest.TestCase):
    def test_startup_failure_stops_loop_and_propagates_after_shutdown(self):
        loop = asyncio.new_event_loop()
        shutdown_called = False

        async def startup():
            raise RuntimeError("startup failed")

        async def shutdown():
            nonlocal shutdown_called
            shutdown_called = True

        try:
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                run_event_loop(loop, startup, shutdown)
            self.assertTrue(shutdown_called)
        finally:
            loop.close()

    def test_successful_startup_can_use_existing_loop(self):
        loop = asyncio.new_event_loop()
        calls = []

        async def startup():
            calls.append("startup")
            loop.call_soon(loop.stop)

        async def shutdown():
            calls.append("shutdown")

        try:
            run_event_loop(loop, startup, shutdown)
            self.assertEqual(calls, ["startup", "shutdown"])
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
