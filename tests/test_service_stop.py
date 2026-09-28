"""Service stop drains Gateway work through the client close path."""

import asyncio
import signal

import pytest

from yoyackbot.discord import _serve_until_stop


def test_sigterm_closes_gateway_before_service_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        handlers = {}
        monkeypatch.setattr(
            loop, "add_signal_handler", lambda key, callback: handlers.update({key: callback})
        )
        monkeypatch.setattr(
            loop, "remove_signal_handler", lambda key: handlers.pop(key, None)
        )

        class Client:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.closed = asyncio.Event()
                self.close_calls = 0

            async def start(self, _token: str) -> None:
                self.started.set()
                await self.closed.wait()

            async def close(self) -> None:
                self.close_calls += 1
                self.closed.set()

        client = Client()
        serving = asyncio.create_task(
            _serve_until_stop(client, "synthetic")  # type: ignore[arg-type]
        )
        await asyncio.wait_for(client.started.wait(), 2)
        handlers[signal.SIGTERM]()
        await asyncio.wait_for(serving, 2)
        assert client.closed.is_set() and client.close_calls == 1
        assert handlers == {}

    asyncio.run(scenario())
