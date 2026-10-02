"""Traditional CUDA planner through the platform's supported chat API.

Only the normal injected model proxy is used. Messages carry application data;
the service truthfully identifies itself as traditional-cuda-planner.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import http.client
import json
import os
import time
import uuid
from urllib.parse import urlsplit

MODEL = "traditional-cuda-planner"
SCHEMA = "traditional-planner-chunks-v1"
CHUNK_BYTES = 42 * 1024
MAX_CHAT_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 192 * 1024
MAX_UNCOMPRESSED_BYTES = 12 * 1024 * 1024
MAX_PARTS = 256
OPERATIONS = frozenset(("health", "initialize", "choose", "close"))


class TransportError(RuntimeError):
    """A bounded public error code, never a provider body or credential."""


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def chat_packets(operation, payload, *, nonce=None, upload_id=None):
    if operation not in OPERATIONS:
        raise ValueError("unsupported operation")
    nonce = nonce or str(uuid.uuid4())
    upload_id = upload_id or str(uuid.uuid4())
    raw = compact({"op": operation, "payload": payload, "nonce": nonce})
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("planner payload too large")
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=3, mtime=0)).decode("ascii")
    total = (len(encoded) + CHUNK_BYTES - 1) // CHUNK_BYTES
    if not 1 <= total <= MAX_PARTS:
        raise ValueError("too many planner chunks")
    digest = hashlib.sha256(raw).hexdigest()
    packets = []
    for index in range(total):
        envelope = {"schema": SCHEMA, "upload_id": upload_id, "nonce": nonce,
                    "op": operation, "index": index, "total": total,
                    "sha256": digest, "encoding": "gzip+base64",
                    "data": encoded[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]}
        body = {"model": MODEL, "messages": [{"role": "user", "content": compact(envelope).decode()}],
                "max_tokens": 4096, "stream": False, "n": 1, "temperature": 0}
        wire = compact(body)
        if len(wire) >= MAX_CHAT_BYTES:
            raise ValueError("planner chat exceeds proxy limit")
        packets.append(wire)
    return packets


class ModelGPUTransport:
    """Same check/choose/close interface and fallback counters as RemotePlanner."""

    def __init__(self, initial, config=None):
        config = config or {}
        self.initial = initial
        self.config = dict(config)
        # Production always obtains scoped credentials through the official runner.
        self.base = os.environ.get("OPENAI_BASE_URL") or config.get("base_url", "")
        self.token = os.environ.get("OPENAI_API_KEY") or config.get("credential", "")
        target = urlsplit(self.base)
        local_test = target.hostname in ("localhost", "127.0.0.1", "::1")
        injected = self.base == os.environ.get("OPENAI_BASE_URL")
        if (target.scheme not in ("https", "http") or not target.hostname or
                target.username or target.password or target.query or target.fragment or
                (target.scheme == "http" and not (injected or local_test))):
            raise ValueError("invalid official model proxy URL")
        if not isinstance(self.token, str) or not self.token or any(c in self.token for c in "\r\n"):
            raise ValueError("model proxy credential missing")
        self.target = target
        self.path = target.path.rstrip("/") + "/chat/completions"
        self.connection = None
        self.session = None
        self.failures = 0
        self.calls = 0
        self.seconds = 0.
        self.rpc_calls = 0
        self.rpc_seconds = 0.
        self.enabled = True
        self.previous_scores = None
        self.previous_factors = None
        self.sequence = 0
        self.last_initialization_seconds = 0.
        self.last_decision_seconds = 0.
        self.last_failure_kind = None

    def _post(self, wire, timeout):
        if timeout <= 0:
            raise TimeoutError("planner transaction deadline")
        if self.connection is None:
            kind = http.client.HTTPSConnection if self.target.scheme == "https" else http.client.HTTPConnection
            self.connection = kind(self.target.hostname, self.target.port, timeout=timeout)
        self.connection.timeout = timeout
        if self.connection.sock is not None:
            self.connection.sock.settimeout(timeout)
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
                   "Idempotency-Key": str(uuid.uuid4())}
        started = time.perf_counter()
        try:
            self.connection.request("POST", self.path, body=wire, headers=headers)
            response = self.connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if response.status != 200:
                raise TransportError("planner_http_" + str(response.status))
            if len(body) > MAX_RESPONSE_BYTES:
                raise TransportError("planner_response_too_large")
            value = json.loads(body)
            content = value["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TransportError("planner_invalid_response")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise TransportError("planner_invalid_result")
            self.rpc_calls += 1
            self.rpc_seconds += time.perf_counter() - started
            return result
        except Exception:
            self._disconnect()
            raise

    def request(self, operation, payload=None, timeout=4):
        packets = chat_packets(operation, {} if payload is None else payload)
        deadline = time.perf_counter() + timeout
        for index, wire in enumerate(packets):
            result = self._post(wire, deadline - time.perf_counter())
            if index + 1 < len(packets):
                if result.get("status") != "chunk_accepted" or result.get("index") != index:
                    raise TransportError("planner_invalid_chunk_ack")
            elif result.get("status") != "complete" or not isinstance(result.get("result"), dict):
                raise TransportError("planner_invalid_complete_response")
        return result["result"]

    def check(self):
        start = time.perf_counter()
        try:
            health = self.request("health", timeout=float(self.config.get("health_timeout_seconds", 6)))
            return {"remote_check": "ok", "transport": "official-compatible-api",
                    "model": MODEL, "gpu_available": health.get("gpu_available"),
                    "gpu_backend_ready": health.get("gpu_backend_ready"),
                    "seconds": round(time.perf_counter() - start, 3)}
        except Exception as exc:
            self.enabled = False
            return {"remote_check": "failed", "transport": "official-compatible-api",
                    "exception": type(exc).__name__, "seconds": round(time.perf_counter() - start, 3)}

    def choose(self, snapshot, scores, factors, env, requests):
        if not self.enabled:
            raise TransportError("planner_disabled")
        start = time.perf_counter()
        self.last_initialization_seconds = 0.
        self.last_decision_seconds = 0.
        self.last_failure_kind = None
        stage = "decision"
        try:
            if self.session is None:
                stage = "initialize"
                initialize_start = time.perf_counter()
                try:
                    self.session = self.request("initialize", {"initialize": self.initial},
                                                timeout=float(self.config.get("initialize_timeout_seconds", 25)))["session"]
                finally:
                    # Failed setup still consumes the real clock and is measured.
                    self.last_initialization_seconds = time.perf_counter() - initialize_start
                count = len(self.initial["targets"]["rows"])
                self.previous_scores = [0.] * count
                self.previous_factors = [0.] * count
            stage = "decision"
            current_scores = scores.tolist() if hasattr(scores, "tolist") else list(scores)
            current_factors = factors.tolist() if hasattr(factors, "tolist") else list(factors)
            if len(current_scores) != len(current_factors):
                raise ValueError("planner state length mismatch")
            reset = self.previous_scores is None or len(self.previous_scores) != len(current_scores)
            changed = (list(range(len(current_scores))) if reset else
                       [i for i, (s, f, old_s, old_f) in enumerate(zip(current_scores, current_factors,
                            self.previous_scores, self.previous_factors)) if s != old_s or f != old_f])
            self.sequence += 1
            payload = {"session": self.session, "snapshot": snapshot,
                       "sequence": self.sequence,
                       "state_delta": {"size": len(current_scores), "reset": reset, "indices": changed,
                                       "scores": [current_scores[i] for i in changed],
                                       "factors": [current_factors[i] for i in changed]},
                       "env": {k: v.tolist() if hasattr(v, "tolist") else v for k, v in env.items()},
                       "requests": requests}
            result = self.request("choose", payload, timeout=float(self.config.get("timeout_seconds", 4)))
            # The participant still validates the actual competition action.
            if "action" not in result or (result["action"] is not None and not isinstance(result["action"], dict)):
                raise TransportError("planner_invalid_action")
            self.calls += 1
            self.failures = 0
            self.previous_scores, self.previous_factors = current_scores, current_factors
            self.seconds += time.perf_counter() - start
            return result
        except Exception:
            self.last_failure_kind = stage
            # An answer might have been lost after server-side state changed. A full
            # overwrite next time also restores entries that changed back to old values.
            self.previous_scores = self.previous_factors = None
            self.failures += 1
            if self.failures >= 2:
                self.enabled = False
            raise
        finally:
            self.last_decision_seconds = max(0., time.perf_counter() - start - self.last_initialization_seconds)

    def _disconnect(self):
        if self.connection:
            self.connection.close()
        self.connection = None

    def close(self):
        try:
            if self.session:
                self.request("close", {"session": self.session}, timeout=2)
        except Exception:
            pass
        finally:
            self.session = None
            self.previous_scores = self.previous_factors = None
            self._disconnect()
