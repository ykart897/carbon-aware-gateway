"""Start the real HTTP application against an isolated database, then shut it down."""

import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with TemporaryDirectory() as directory:
        os.environ.update(
            DATABASE_PATH=str(Path(directory) / "smoke.db"),
            OPENWHISK_REAL="false",
            ENTSOE_API_KEY="",
            USE_LIVE_API="false",
            ELECTRICITY_MAPS_API_KEY="",
        )
        import uvicorn
        from main import app

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            address = f"http://127.0.0.1:{listener.getsockname()[1]}"
            server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while (
                    not server.started
                    and thread.is_alive()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                assert server.started, "HTTP server did not start"

                def request(path, body=None):
                    req = urllib.request.Request(
                        address + path,
                        data=json.dumps(body).encode() if body else None,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=20) as response:
                        return response.read()

                assert json.loads(request("/health"))["status"] == "ok"
                assert not json.loads(request("/entsoe/status"))["active"]
                result = json.loads(request("/route", {"action": "smoke", "data": {}}))
                assert result["backend"] == "simulation"
                assert (
                    result["decision"]["selected_region"]
                    == result["invocation"]["region"]
                )
                assert json.loads(request("/stats"))["totals"]["total_requests"] == 1
                assert b"/static/dashboard.js" in request("/dashboard")
                assert b"textContent" in request("/static/dashboard.js")
                print(
                    "Real HTTP smoke passed: startup, routing, persistence, dashboard and static assets"
                )
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                assert not thread.is_alive(), "HTTP server did not stop"


if __name__ == "__main__":
    main()
