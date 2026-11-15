import asyncio
import contextlib
import inspect
import os

import pytest

from app.routers import consultations


class FakeSocket:
    def __init__(self, fail_after=None):
        self.sent = []
        self.fail_after = fail_after

    async def send_json(self, data):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError("client went away")
        self.sent.append(data)


def test_keep_alive_sends_pings_until_cancelled():
    ws = FakeSocket()

    async def scenario():
        task = asyncio.create_task(consultations._ws_keep_alive(ws, 0.05))
        await asyncio.sleep(0.4)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(ws.sent) >= 3
    assert all(m == {"type": "ping"} for m in ws.sent)


def test_keep_alive_ends_quietly_when_the_client_is_gone():
    ws = FakeSocket(fail_after=1)

    async def scenario():
        await asyncio.wait_for(consultations._ws_keep_alive(ws, 0.05), timeout=2)

    asyncio.run(scenario())
    assert len(ws.sent) == 1


def test_endpoint_starts_and_stops_the_keep_alive():
    source = inspect.getsource(consultations.websocket_transcribe)
    assert "_ws_keep_alive(websocket, settings.WS_PING_INTERVAL_SECONDS)" in source
    assert "ping_task.cancel()" in source


def test_browser_answers_ping_with_pong():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "pages", "consultation.html")
    if not os.path.exists(path):
        pytest.skip("front end not in this checkout")
    html = open(path, encoding="utf-8").read()
    assert 'data.type === "ping"' in html and '"pong"' in html