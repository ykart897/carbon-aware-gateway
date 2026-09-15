"""HTTP validation checks without a server or application database."""

import json
import unittest
from unittest.mock import patch

from main import app


async def get(path, query=""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 123),
        },
        receive,
        send,
    )
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages)
    return status, json.loads(body)


class ApiValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_is_not_interpreted_as_region(self):
        with patch("main.ENTSOE_API_KEY", ""):
            status, body = await get("/entsoe/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["active"])

    async def test_invalid_regions(self):
        for path in ("/forecast/XX", "/forecast/prophet/XX", "/entsoe/XX"):
            with self.subTest(path=path):
                self.assertEqual((await get(path))[0], 422)

    async def test_forecast_step_bounds(self):
        for path in ("/forecast", "/forecast/IE", "/forecast/prophet/IE"):
            for steps in ("0", "25", "-1", "abc"):
                with self.subTest(path=path, steps=steps):
                    self.assertEqual((await get(path, "steps=" + steps))[0], 422)

    async def test_valid_step_boundaries(self):
        with patch("main.get_forecast", return_value={"model": "test"}) as forecast:
            for steps in (1, 24):
                self.assertEqual((await get("/forecast/DE", f"steps={steps}"))[0], 200)
                forecast.assert_called_with("DE", steps)

    async def test_lifespan_initializes_database(self):
        with patch("main.init") as initialize:
            async with app.router.lifespan_context(app):
                initialize.assert_called_once_with()
