"""A tiny fake "ShotTrack" production-tracking API for demos and tests.

It behaves like a real tracker API: bearer-token auth, paginated results,
filtering, and (optionally) the occasional 429/503 so the client's retry
logic has something to do.

    python -m api_report.mock_server --port 8765
"""
from __future__ import annotations

import argparse
import csv
import json
import threading
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DATA = Path(__file__).resolve().parent.parent / "sample_data"
DEMO_TOKEN = "demo-token"


def _read_csv(name: str) -> list[dict]:
    with open(DATA / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@dataclass
class ServerState:
    token: str = DEMO_TOKEN
    flaky_every: int = 0  # 0 = never fail; N = every Nth request returns 503/429
    request_count: int = 0


def make_handler(state: ServerState, shots: list[dict], vendors: list[dict]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ShotTrackMock/1.0"

        def log_message(self, *args):  # keep test output quiet
            pass

        def _send(self, status: int, body: dict, headers: dict | None = None):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            state.request_count += 1
            if self.headers.get("Authorization") != f"Bearer {state.token}":
                return self._send(401, {"error": "invalid or missing bearer token"})
            if state.flaky_every and state.request_count % state.flaky_every == 0:
                if (state.request_count // state.flaky_every) % 2:
                    return self._send(429, {"error": "rate limited"}, {"Retry-After": "0"})
                return self._send(503, {"error": "temporarily unavailable"})

            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/v1/health":
                return self._send(200, {"ok": True})
            if url.path == "/api/v1/shots":
                rows = shots
                for key in ("status", "vendor_id", "episode", "sequence"):
                    if key in q:
                        rows = [r for r in rows if r[key] == q[key]]
                return self._paginate(rows, q)
            if url.path == "/api/v1/vendors":
                return self._paginate(vendors, q)
            return self._send(404, {"error": f"no route for {url.path}"})

        def _paginate(self, rows: list[dict], q: dict):
            try:
                page = max(1, int(q.get("page", 1)))
                per_page = min(100, max(1, int(q.get("per_page", 10))))
            except ValueError:
                return self._send(400, {"error": "page and per_page must be integers"})
            start = (page - 1) * per_page
            items = rows[start:start + per_page]
            next_page = page + 1 if start + per_page < len(rows) else None
            return self._send(200, {"data": items, "page": page, "per_page": per_page,
                                    "total": len(rows), "next_page": next_page})

    return Handler


class MockServer:
    """Run the mock API in a background thread (used by tests and `--mock`)."""

    def __init__(self, port: int = 0, state: ServerState | None = None):
        self.state = state or ServerState()
        handler = make_handler(self.state, _read_csv("shots.csv"), _read_csv("vendors.csv"))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> MockServer:
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the mock ShotTrack API.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--flaky-every", type=int, default=0, help="fail every Nth request with 429/503")
    args = p.parse_args(argv)
    server = MockServer(args.port, ServerState(flaky_every=args.flaky_every))
    print(f"Mock ShotTrack API on {server.url}  (token: {DEMO_TOKEN})")
    print(json.dumps(asdict(server.state)))
    server.httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
