"""Authenticated HTTPS accelerator client with bounded failures and local fallback."""
from __future__ import annotations

import json
import gzip
import http.client
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class RemotePlanner:
    def __init__(self, initial, config):
        self.initial = initial
        self.config = config
        self.base = config["url"].rstrip("/")
        self.token = config["token"]
        self.session = None
        self.failures = 0
        self.calls = 0
        self.seconds = 0.
        self.enabled = True
        self.connection = None

    def request(self, path, payload=None, timeout=4):
        data = None if payload is None else json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        target = urlsplit(self.base)
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        if data and len(data) > 16384:
            data = gzip.compress(data, compresslevel=1)
            headers["Content-Encoding"] = "gzip"
        if self.connection is None:
            connection_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
            self.connection = connection_type(target.hostname, port=target.port, timeout=timeout)
        self.connection.timeout = timeout
        if self.connection.sock is not None:
            self.connection.sock.settimeout(timeout)
        try:
            self.connection.request("GET" if data is None else "POST", target.path.rstrip("/") + path,
                                    body=data, headers=headers)
            response = self.connection.getresponse()
            body = response.read(4 * 1024 * 1024)
            if response.status != 200:
                raise RuntimeError("remote HTTP status " + str(response.status))
            return json.loads(body)
        except Exception:
            self.connection.close()
            self.connection = None
            raise

    def check(self):
        start = time.perf_counter()
        try:
            health = self.request("/health")
            return {"remote_check": "ok", "gpu_available": health.get("gpu_available"),
                    "gpu_backend_ready": health.get("gpu_backend_ready"),
                    "seconds": round(time.perf_counter() - start, 3)}
        except Exception as exc:
            self.enabled = False
            return {"remote_check": "failed", "exception": type(exc).__name__,
                    "seconds": round(time.perf_counter() - start, 3)}

    def choose(self, snapshot, scores, factors, env, requests):
        if not self.enabled:
            raise RuntimeError("remote disabled")
        start = time.perf_counter()
        try:
            if self.session is None:
                self.session = self.request("/initialize", {"initialize": self.initial}, timeout=8)["session"]
            result = self.request("/choose", {"session": self.session, "snapshot": snapshot,
                                   "best_scores": scores.tolist(), "best_factors": factors.tolist(),
                                   "env": {k: v.tolist() if hasattr(v, "tolist") else v for k, v in env.items()},
                                   "requests": requests}, timeout=float(self.config.get("timeout_seconds", 3)))
            self.calls += 1
            self.failures = 0
            self.seconds += time.perf_counter() - start
            return result
        except Exception:
            self.failures += 1
            if self.failures >= 2:
                self.enabled = False
            raise
