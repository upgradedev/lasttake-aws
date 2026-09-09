"""Offline HTTP adapter for CI journeys. The real handler and real Strands run.

Run with python -m lasttake.app.local_server --state-dir /tmp/lasttake-ui.
No credentials, AWS adapter construction or model inference is used here.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from . import handler as H
from ..adapters.local.infrastructure import LocalArtifactStore, LocalEventBus, LocalRunStore
from ..agents.orchestrator import build_orchestrator


def configure(root):
    bus = LocalEventBus(root / "events")
    artifacts = LocalArtifactStore(root / "artifacts")
    runs = LocalRunStore(root / "runs")
    bus.replay = lambda correlation=None: [r for r in LocalEventBus.replay(bus)
                                           if correlation is None or r["correlation_id"] == correlation]
    H.from_environment = lambda: (bus, artifacts, runs)
    H.run_store_kind = lambda: "local-files"
    H.build_agent = lambda run, plan=None: build_orchestrator(run, session_dir=root / "sessions", plan=plan)
    original_json = H._json

    def local_json(status, payload, request_id):
        response = original_json(status, payload, request_id)
        data = json.loads(response["body"])
        data["served_by"]["note"] = "Offline HTTP test server. Real Strands sessions and local durable adapters; no AWS or model calls."
        response["body"] = json.dumps(data)
        return response

    H._json = local_json


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 128_000:
            self.send_error(413)
            return
        event = {"requestContext": {"http": {"path": self.path, "method": self.command}},
                 "body": self.rfile.read(length).decode("utf-8") if length else "{}"}
        response = H.handler(event, SimpleNamespace(aws_request_id=str(uuid4())))
        self.send_response(response["statusCode"])
        for key, value in response["headers"].items():
            self.send_header(key, value)
        content = response["body"].encode("utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    configure(args.state_dir)
    HTTPServer(("127.0.0.1", args.port), RequestHandler).serve_forever()


if __name__ == "__main__":
    main()
