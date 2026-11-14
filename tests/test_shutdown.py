import asyncio
import signal
from types import SimpleNamespace

from gab_faq.discord_bot.app import serve
from gab_faq.operations import Metrics


def test_sigterm_marks_draining_and_closes_the_app(monkeypatch):
    async def run():
        callbacks = {}
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            loop, "add_signal_handler", lambda sig, callback: callbacks.__setitem__(sig, callback)
        )
        monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: callbacks.pop(sig, None))

        class Application:
            def __init__(self):
                self.settings = SimpleNamespace(
                    runtime=SimpleNamespace(health_host="127.0.0.1", health_port=0)
                )
                self.metrics = Metrics()
                self.draining = False
                self.closed_while_draining = False
                self.stopped = asyncio.Event()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                await self.close()

            def readiness(self):
                return {"accepting": not self.draining}

            async def start(self, token):
                loop.call_soon(callbacks[signal.SIGTERM])
                await self.stopped.wait()

            async def close(self):
                self.closed_while_draining = self.draining
                self.stopped.set()

        app = Application()
        await asyncio.wait_for(serve(app, "synthetic-token"), 5)
        assert app.closed_while_draining and app.stopped.is_set()
        assert callbacks == {}

    asyncio.run(run())
