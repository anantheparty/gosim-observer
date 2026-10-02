#!/usr/bin/env python3
"""Scoped stateless-search service for the team's external accelerator.

The bearer credential is supplied separately at deployment. Only public
initialization and already received feedback/state are accepted; no shell, file
retrieval, evaluator access or manual action endpoints exist.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np

SESSIONS = {}
LOCK = threading.Lock()
TOKEN = ""
GPU_AVAILABLE = False
GPU_NAME = "unavailable"
MAX_BODY = 12 * 1024 * 1024
ROOT = Path(__file__).resolve().parent


def capability():
    global GPU_AVAILABLE, GPU_NAME
    try:
        from numba import cuda
        GPU_AVAILABLE = cuda.is_available()
        if GPU_AVAILABLE:
            name = cuda.get_current_device().name
            GPU_NAME = name.decode() if isinstance(name, bytes) else str(name)
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, code, value):
        data = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, "Bearer " + TOKEN)

    def do_GET(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path != "/health":
            return self.reply(404, {"error": "unknown endpoint"})
        backend_file = ROOT / "research" / "gpu_spatial_candidates.py"
        return self.reply(200, {"ok": True, "gpu_available": GPU_AVAILABLE,
                                "gpu_name": GPU_NAME, "gpu_backend_ready": backend_file.exists(),
                                "protocol": "observer-search-rpc-v1"})

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if size <= 0 or size > MAX_BODY:
                return self.reply(413, {"error": "invalid size"})
            body = self.rfile.read(size)
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            if len(body) > MAX_BODY:
                return self.reply(413, {"error": "invalid size"})
            payload = json.loads(body)
            with LOCK:
                if self.path == "/initialize":
                    now = time.monotonic()
                    for key, value in list(SESSIONS.items()):
                        if now - value["last"] > 7200:
                            del SESSIONS[key]
                    if len(SESSIONS) >= 16:
                        return self.reply(429, {"error": "session capacity"})
                    if GPU_AVAILABLE:
                        from research.gpu_spatial_candidates import GPUSpatialPlanner
                        planner = GPUSpatialPlanner(payload["initialize"])
                    else:
                        from research.spatial_candidates import SpatialPlanner
                        planner = SpatialPlanner(payload["initialize"])
                    key = uuid.uuid4().hex
                    SESSIONS[key] = {"planner": planner, "last": now}
                    return self.reply(200, {"session": key, "backend": type(planner).__name__})
                if self.path == "/choose":
                    session = SESSIONS.get(payload.get("session"))
                    if session is None:
                        return self.reply(404, {"error": "unknown session"})
                    session["last"] = time.monotonic()
                    planner = session["planner"]
                    start = time.perf_counter()
                    action = planner.choose(payload["snapshot"], payload["best_scores"], payload["best_factors"],
                                            payload.get("env", {}), payload.get("requests", []))
                    return self.reply(200, {"action": action, "prediction": planner.last_prediction,
                                            "stats": planner.stats, "seconds": time.perf_counter() - start})
                return self.reply(404, {"error": "unknown endpoint"})
        except Exception as exc:
            # No payloads or credentials appear in logs or error replies.
            return self.reply(500, {"error": type(exc).__name__})


def main():
    global TOKEN
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19923)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    TOKEN = Path(args.token_file).read_text().strip()
    if len(TOKEN) < 32:
        raise SystemExit("credential too short")
    capability()
    print(json.dumps({"listening": args.port, "gpu_available": GPU_AVAILABLE,
                      "gpu_name": GPU_NAME}), flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
