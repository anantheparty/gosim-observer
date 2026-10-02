"""Bounded OpenAI-compatible facade for one fixed owned planner backend.

No language model is called. No arbitrary URL, shell or filesystem operation is
accepted. Bind to loopback behind an owned TLS reverse proxy when deployed.
"""
from __future__ import annotations

import argparse
from array import array
import base64
import gzip
import hashlib
import hmac
import http.client
import io
import json
import math
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .model_gpu_transport import (MODEL, SCHEMA, CHUNK_BYTES, MAX_CHAT_BYTES,
        MAX_RESPONSE_BYTES, MAX_UNCOMPRESSED_BYTES, MAX_PARTS, OPERATIONS, compact)
except ImportError:
    from model_gpu_transport import (MODEL, SCHEMA, CHUNK_BYTES, MAX_CHAT_BYTES,
        MAX_RESPONSE_BYTES, MAX_UNCOMPRESSED_BYTES, MAX_PARTS, OPERATIONS, compact)

ALLOWED_ORIGIN = "https://create.gosim.org"
TTL_SECONDS = 120
MAX_UPLOADS = 16
MAX_CACHED = 4096
MAX_TOTAL_STORAGE = 32 * 1024 * 1024
MAX_SESSION_STORAGE = 32 * 1024 * 1024
MAX_SESSIONS = 16
MAX_TARGETS = 100000
SESSION_TTL_SECONDS = 7200
MAX_INFLIGHT = 4
MAX_BACKEND_RESPONSE = 160 * 1024


class AdapterError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def is_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("non-finite JSON constant")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


def parse_chat(value):
    if not isinstance(value, dict) or value.get("model") != MODEL:
        raise AdapterError(400, "unsupported_model")
    allowed = {"model", "messages", "max_tokens", "max_completion_tokens", "stream", "n", "temperature"}
    if set(value) - allowed or value.get("stream", False) is not False or value.get("n", 1) != 1:
        raise AdapterError(400, "unsupported_chat_option")
    if "max_tokens" in value and "max_completion_tokens" in value:
        raise AdapterError(400, "ambiguous_token_limit")
    tokens = value.get("max_completion_tokens", value.get("max_tokens", 1024))
    if type(tokens) is not int or not 1 <= tokens <= 4096:
        raise AdapterError(400, "invalid_token_limit")
    messages = value.get("messages")
    if (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict) or
            set(messages[0]) != {"role", "content"} or messages[0]["role"] != "user" or
            not isinstance(messages[0]["content"], str)):
        raise AdapterError(400, "planner_text_message_required")
    try:
        envelope = strict_json(messages[0]["content"])
    except (ValueError, TypeError):
        raise AdapterError(400, "invalid_planner_json") from None
    keys = {"schema", "upload_id", "nonce", "op", "index", "total", "sha256", "encoding", "data"}
    if not isinstance(envelope, dict) or set(envelope) != keys:
        raise AdapterError(400, "invalid_chunk_envelope")
    if (envelope["schema"] != SCHEMA or envelope["encoding"] != "gzip+base64" or
            not is_uuid(envelope["upload_id"]) or not is_uuid(envelope["nonce"]) or
            envelope["op"] not in OPERATIONS or type(envelope["total"]) is not int or
            type(envelope["index"]) is not int or not 1 <= envelope["total"] <= MAX_PARTS or
            not 0 <= envelope["index"] < envelope["total"] or
            not isinstance(envelope["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", envelope["sha256"]) or
            not isinstance(envelope["data"], str) or not 0 < len(envelope["data"]) <= CHUNK_BYTES or
            not re.fullmatch(r"[A-Za-z0-9+/=]+", envelope["data"])):
        raise AdapterError(400, "invalid_chunk_metadata")
    return envelope


class FixedBackend:
    """Server-side immutable destination; request JSON cannot change it."""

    def __init__(self, base, token, *, timeout=4):
        target = urlsplit(base)
        if (target.scheme != "http" or target.hostname not in ("localhost", "127.0.0.1", "::1", "172.31.144.1") or
                target.username or target.password or target.query or target.fragment or
                target.path not in ("", "/")):
            raise ValueError("backend must be the fixed local planner endpoint")
        self.target, self.token, self.timeout = target, token, timeout
        self.local = threading.local()

    def __call__(self, operation, payload):
        if operation not in OPERATIONS:
            raise AdapterError(400, "unsupported_operation")
        connection = getattr(self.local, "connection", None)
        if connection is None:
            connection = http.client.HTTPConnection(self.target.hostname, self.target.port, timeout=self.timeout)
            self.local.connection = connection
        try:
            body = None if operation == "health" else compact(payload)
            connection.request("GET" if body is None else "POST", "/" + operation, body=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token})
            response = connection.getresponse()
            raw = response.read(MAX_BACKEND_RESPONSE + 1)
            if response.status != 200:
                raise AdapterError(502, "planner_backend_http_" + str(response.status))
            if len(raw) > MAX_BACKEND_RESPONSE:
                raise AdapterError(502, "planner_backend_response_too_large")
            value = strict_json(raw)
            if not isinstance(value, dict):
                raise AdapterError(502, "planner_backend_invalid_response")
            return value
        except AdapterError:
            connection.close()
            self.local.connection = None
            raise
        except Exception:
            connection.close()
            self.local.connection = None
            raise AdapterError(502, "planner_backend_unavailable") from None


class SessionBackend:
    """Exact overwrite deltas reconstructed before the unchanged GPU interface."""

    def __init__(self, backend, *, clock=time.monotonic):
        self.backend, self.clock = backend, clock
        self.sessions = {}
        self.lock = threading.Lock()
        self.storage = 0
        self.initializing = 0

    def _expire(self):
        now = self.clock()
        for key, record in list(self.sessions.items()):
            if now - record["last"] > SESSION_TTL_SECONDS:
                self.storage -= record["bytes"]
                del self.sessions[key]

    def __call__(self, operation, payload):
        if operation == "health":
            return self.backend(operation, payload)
        if operation == "initialize":
            try:
                rows = payload["initialize"]["targets"]["rows"]
                count = len(rows)
            except (KeyError, TypeError):
                raise AdapterError(400, "planner_initialization_targets") from None
            if not isinstance(rows, list) or not 1 <= count <= MAX_TARGETS:
                raise AdapterError(413, "planner_target_capacity")
            size = count * 16
            with self.lock:
                self._expire()
                if len(self.sessions) + self.initializing >= MAX_SESSIONS or self.storage + size > MAX_SESSION_STORAGE:
                    raise AdapterError(429, "planner_session_capacity")
                self.initializing += 1
                self.storage += size
            try:
                result = self.backend(operation, payload)
                key = result.get("session")
                if not isinstance(key, str) or not key or len(key) > 128:
                    raise AdapterError(502, "planner_invalid_session")
                record = {"scores": array("d", [0.]) * count, "factors": array("d", [0.]) * count,
                          "bytes": size, "last": self.clock(), "sequence": 0, "lock": threading.Lock()}
                with self.lock:
                    if key in self.sessions:
                        raise AdapterError(502, "planner_duplicate_session")
                    self.sessions[key] = record
                return result
            except Exception:
                with self.lock:
                    self.storage -= size
                raise
            finally:
                with self.lock:
                    self.initializing -= 1
        with self.lock:
            self._expire()
            record = self.sessions.get(payload.get("session"))
        if record is None:
            raise AdapterError(404, "planner_unknown_session")
        with record["lock"]:
            if operation == "close":
                result = self.backend(operation, payload)
                with self.lock:
                    if self.sessions.pop(payload["session"], None) is not None:
                        self.storage -= record["bytes"]
                return result
            sequence, delta = payload.get("sequence"), payload.get("state_delta")
            if type(sequence) is not int or sequence <= record["sequence"]:
                raise AdapterError(409, "planner_state_sequence")
            fields = {"size", "reset", "indices", "scores", "factors"}
            if not isinstance(delta, dict) or set(delta) != fields:
                raise AdapterError(400, "planner_invalid_state_delta")
            indices, scores, factors = delta["indices"], delta["scores"], delta["factors"]
            count = len(record["scores"])
            if (type(delta["size"]) is not int or delta["size"] != count or type(delta["reset"]) is not bool or
                    not all(isinstance(x, list) for x in (indices, scores, factors)) or
                    not len(indices) == len(scores) == len(factors) or len(indices) > count):
                raise AdapterError(400, "planner_state_size")
            if (any(type(i) is not int or not 0 <= i < count for i in indices) or len(set(indices)) != len(indices) or
                    any(type(s) not in (int, float) or not math.isfinite(s) or s < 0 for s in scores) or
                    any(type(f) not in (int, float) or not math.isfinite(f) or not 0 <= f <= 1 for f in factors) or
                    (delta["reset"] and set(indices) != set(range(count)))):
                raise AdapterError(400, "planner_invalid_state_values")
            for index, score, factor in zip(indices, scores, factors):
                record["scores"][index], record["factors"][index] = score, factor
            record["sequence"] = sequence
            record["last"] = self.clock()
            expanded = {"session": payload["session"], "snapshot": payload["snapshot"],
                        "best_scores": list(record["scores"]), "best_factors": list(record["factors"]),
                        "env": payload["env"], "requests": payload["requests"]}
            return self.backend(operation, expanded)


class ChunkStore:
    def __init__(self, backend, *, clock=time.monotonic):
        self.backend, self.clock = backend, clock
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(MAX_INFLIGHT)
        self.uploads, self.cache = {}, {}
        self.storage = 0

    def _expire(self, now):
        for key, upload in list(self.uploads.items()):
            if now - upload["last"] > TTL_SECONDS:
                self.storage -= upload["bytes"]
                del self.uploads[key]
        for key, entry in list(self.cache.items()):
            if entry["result"] is not None and now - entry["last"] > TTL_SECONDS:
                self.storage -= entry["bytes"]
                del self.cache[key]

    def accept(self, envelope):
        if not self.slots.acquire(blocking=False):
            raise AdapterError(429, "planner_concurrency_limit")
        try:
            return self._accept(envelope)
        finally:
            self.slots.release()

    def _accept(self, e):
        key, nonce = e["upload_id"], e["nonce"]
        metadata = (e["op"], e["sha256"], e["total"], key)
        part_hash = hashlib.sha256(e["data"].encode("ascii")).hexdigest()
        now = self.clock()
        with self.lock:
            self._expire(now)
            cached = self.cache.get(nonce)
            if cached:
                if cached["metadata"] != metadata or cached["parts"].get(e["index"]) != part_hash:
                    raise AdapterError(409, "planner_nonce_conflict")
                if cached["result"] is None:
                    raise AdapterError(409, "planner_request_in_progress")
                return cached["result"]
            upload = self.uploads.get(key)
            if upload is None:
                if len(self.uploads) >= MAX_UPLOADS:
                    raise AdapterError(429, "planner_upload_capacity")
                if e["index"] != 0:
                    raise AdapterError(409, "planner_chunk_order")
                upload = {"metadata": metadata, "nonce": nonce, "parts": {}, "bytes": 0, "last": now}
                self.uploads[key] = upload
            if upload["metadata"] != metadata or upload["nonce"] != nonce:
                raise AdapterError(409, "planner_upload_conflict")
            earlier = upload["parts"].get(e["index"])
            if earlier is not None and earlier != e["data"]:
                raise AdapterError(409, "planner_chunk_conflict")
            if earlier is None:
                if e["index"] != len(upload["parts"]):
                    raise AdapterError(409, "planner_chunk_order")
                if self.storage + len(e["data"]) > MAX_TOTAL_STORAGE:
                    raise AdapterError(429, "planner_storage_capacity")
                upload["parts"][e["index"]] = e["data"]
                upload["bytes"] += len(e["data"])
                self.storage += len(e["data"])
            upload["last"] = now
            if len(upload["parts"]) < e["total"]:
                return {"status": "chunk_accepted", "index": e["index"], "nonce": nonce}
            if len(self.cache) >= MAX_CACHED:
                raise AdapterError(429, "planner_receipt_capacity")
            encoded = "".join(upload["parts"][i] for i in range(e["total"]))
            hashes = {i: hashlib.sha256(v.encode("ascii")).hexdigest() for i, v in upload["parts"].items()}
            self.storage -= upload["bytes"]
            del self.uploads[key]
            cache_bytes = 512 + len(hashes) * 128
            if self.storage + cache_bytes > MAX_TOTAL_STORAGE:
                raise AdapterError(429, "planner_storage_capacity")
            self.storage += cache_bytes
            self.cache[nonce] = {"metadata": metadata, "parts": hashes, "result": None,
                                 "bytes": cache_bytes, "last": now}
        try:
            compressed = base64.b64decode(encoded, validate=True)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                raw = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
            if len(raw) > MAX_UNCOMPRESSED_BYTES:
                raise AdapterError(413, "planner_decoded_size")
            if hashlib.sha256(raw).hexdigest() != e["sha256"]:
                raise AdapterError(400, "planner_digest_mismatch")
            payload = strict_json(raw)
            if (not isinstance(payload, dict) or set(payload) != {"op", "payload", "nonce"} or
                    payload["op"] != e["op"] or payload["nonce"] != nonce or
                    not isinstance(payload["payload"], dict)):
                raise AdapterError(400, "planner_payload_mismatch")
            keys = set(payload["payload"])
            required = {"health": set(), "initialize": {"initialize"}, "close": {"session"},
                        "choose": {"session", "snapshot", "sequence", "state_delta", "env", "requests"}}
            if keys != required[e["op"]]:
                raise AdapterError(400, "planner_operation_fields")
            result = self.backend(e["op"], payload["payload"])
            value = {"status": "complete", "nonce": nonce, "result": result}
            result_bytes = len(compact(value))
            if result_bytes > MAX_BACKEND_RESPONSE:
                raise AdapterError(502, "planner_result_too_large")
            with self.lock:
                if self.storage + result_bytes > MAX_TOTAL_STORAGE:
                    raise AdapterError(429, "planner_storage_capacity")
                self.storage += result_bytes
                self.cache[nonce]["bytes"] += result_bytes
                self.cache[nonce]["result"] = value
                self.cache[nonce]["last"] = self.clock()
            return value
        except AdapterError:
            with self.lock:
                entry = self.cache.pop(nonce, None)
                if entry:
                    self.storage -= entry["bytes"]
            raise
        except Exception:
            with self.lock:
                entry = self.cache.pop(nonce, None)
                if entry:
                    self.storage -= entry["bytes"]
            raise AdapterError(400, "planner_invalid_compressed_payload") from None


def completion(result):
    value = {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion",
             "created": int(time.time()), "model": MODEL,
             "choices": [{"index": 0, "message": {"role": "assistant", "content": compact(result).decode()},
                          "finish_reason": "stop"}]}
    raw = compact(value)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AdapterError(502, "planner_completion_too_large")
    return raw


class AdapterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(6)

    def reply(self, status, raw):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if self.headers.get("Origin") == ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(raw)

    def error(self, status, code):
        self.close_connection = True
        self.reply(status, compact({"error": {"type": "traditional_planner_error", "code": code, "message": code}}))

    def do_OPTIONS(self):
        if self.headers.get("Origin") != ALLOWED_ORIGIN or self.path != "/v1/chat/completions":
            return self.error(403, "planner_origin_denied")
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type, idempotency-key")
        self.send_header("Content-Length", "0")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        self.error(405, "planner_method_not_allowed")

    do_PUT = do_DELETE = do_PATCH = do_GET

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode("utf-8"),
                                   ("Bearer " + self.server.planner_token).encode("utf-8")):
            return self.error(401, "planner_unauthorized")
        origin = self.headers.get("Origin")
        if origin is not None and origin != ALLOWED_ORIGIN:
            return self.error(403, "planner_origin_denied")
        if self.path != "/v1/chat/completions":
            return self.error(404, "planner_endpoint_not_found")
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            return self.error(400, "planner_unsupported_encoding")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < MAX_CHAT_BYTES:
                raise AdapterError(413, "planner_chat_size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise AdapterError(400, "planner_incomplete_body")
            envelope = parse_chat(strict_json(raw))
            result = self.server.planner_store.accept(envelope)
            self.reply(200, completion(result))
        except AdapterError as exc:
            self.error(exc.status, exc.code)
        except Exception:
            self.error(400, "planner_invalid_request")


class AdapterServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token, backend):
        if not isinstance(token, str) or len(token) < 32 or any(c.isspace() for c in token):
            raise ValueError("planner service credential too short")
        self.planner_token = token
        self.planner_store = ChunkStore(SessionBackend(backend))
        super().__init__(address, AdapterHandler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=19928)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--backend", default="http://127.0.0.1:19924")
    parser.add_argument("--backend-timeout", type=float, default=4)
    args = parser.parse_args()
    token = Path(args.token_file).read_text().strip()
    backend = FixedBackend(args.backend, token, timeout=args.backend_timeout)
    server = AdapterServer((args.host, args.port), token, backend)
    print(json.dumps({"model": MODEL, "listening": args.port, "backend": "fixed-owned-planner"}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
