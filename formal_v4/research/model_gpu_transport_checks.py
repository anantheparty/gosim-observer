"""Local stub gates for bounded chat transport and exact state overwrites.

This does not connect to the competition or start a deployed service.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import http.client
import json
import random
import threading
import unittest
from unittest.mock import patch

from .model_gpu_transport import ModelGPUTransport, chat_packets, compact, MAX_CHAT_BYTES, MODEL
from .model_gpu_adapter import (AdapterServer, AdapterError, ChunkStore, SessionBackend,
                               parse_chat, strict_json, FixedBackend, MAX_PARTS)


class StubBackend:
    def __init__(self):
        self.calls = []
        self.next_session = 0

    def __call__(self, op, payload):
        self.calls.append((op, payload))
        if op == "health":
            return {"gpu_available": True, "gpu_backend_ready": True}
        if op == "initialize":
            self.next_session += 1
            return {"session": "stub-" + str(self.next_session)}
        if op == "choose":
            return {"action": {"action": "wait", "duration_seconds": 60}, "stats": {"planning_seconds": .001}}
        if op == "close":
            return {"closed": True}
        raise AssertionError(op)


def envelope(packet):
    return parse_chat(strict_json(packet))


class StoreChecks(unittest.TestCase):
    def setUp(self):
        self.backend = StubBackend()
        self.store = ChunkStore(self.backend)

    def test_large_catalog_chunks_and_final_dispatch(self):
        rng = random.Random(503)
        rows = [[i, rng.random(), rng.random(), rng.random()] for i in range(10000)]
        payload = {"initialize": {"targets": {"rows": rows}}}
        packets = chat_packets("initialize", payload)
        self.assertGreater(len(packets), 1)
        for i, packet in enumerate(packets):
            self.assertLess(len(packet), MAX_CHAT_BYTES)
            result = self.store.accept(envelope(packet))
            if i + 1 < len(packets):
                self.assertEqual(result["status"], "chunk_accepted")
                self.assertFalse(self.backend.calls)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.backend.calls, [("initialize", payload)])
        self.assertGreaterEqual(self.store.storage, 0)

    def test_last_chunk_retry_does_not_recompute(self):
        packet = chat_packets("health", {})[0]
        first = self.store.accept(envelope(packet))
        self.assertEqual(self.store.accept(envelope(packet)), first)
        self.assertEqual(len(self.backend.calls), 1)

    def test_changed_nonce_data_rejected(self):
        packet = chat_packets("health", {})[0]
        self.store.accept(envelope(packet))
        bad = envelope(packet)
        bad["data"] = "A" + bad["data"][1:]
        with self.assertRaises(AdapterError):
            self.store.accept(bad)

    def test_corrupt_sha_and_base64_never_dispatch(self):
        packet = chat_packets("health", {})[0]
        bad = envelope(packet)
        bad["sha256"] = "0" * 64
        with self.assertRaises(AdapterError):
            self.store.accept(bad)
        bad = envelope(packet)
        bad["data"] = "A"
        with self.assertRaises(AdapterError):
            self.store.accept(bad)
        self.assertFalse(self.backend.calls)
        self.assertEqual(self.store.storage, 0)

    def test_decoded_bomb_bounded(self):
        packet = chat_packets("health", {})[0]
        bad = envelope(packet)
        bad["data"] = base64.b64encode(gzip.compress(b"x" * 5000)).decode()
        with patch("formal_v4.research.model_gpu_adapter.MAX_UNCOMPRESSED_BYTES", 1024):
            with self.assertRaises(AdapterError) as error:
                self.store.accept(bad)
        self.assertEqual(error.exception.status, 413)
        self.assertFalse(self.backend.calls)

    def test_ttl_frees_payload_and_receipt_storage(self):
        clock = [0.]
        store = ChunkStore(self.backend, clock=lambda: clock[0])
        store.accept(envelope(chat_packets("health", {})[0]))
        self.assertGreater(store.storage, 0)
        clock[0] = 121
        with store.lock:
            store._expire(clock[0])
        self.assertEqual(store.storage, 0)
        self.assertFalse(store.cache)

    def test_storage_upload_and_concurrency_limits(self):
        packet = envelope(chat_packets("health", {})[0])
        with patch("formal_v4.research.model_gpu_adapter.MAX_TOTAL_STORAGE", 1):
            with self.assertRaises(AdapterError) as error:
                self.store.accept(packet)
        self.assertEqual(error.exception.status, 429)
        for _ in range(4):
            self.assertTrue(self.store.slots.acquire(False))
        with self.assertRaises(AdapterError) as error:
            self.store.accept(packet)
        self.assertEqual(error.exception.status, 429)
        for _ in range(4):
            self.store.slots.release()

    def test_bad_fields_and_duplicate_json(self):
        body = strict_json(chat_packets("health", {})[0])
        body["model"] = "LLM-pretence"
        with self.assertRaises(AdapterError):
            parse_chat(body)
        with self.assertRaises(ValueError):
            strict_json('{"x":1,"x":2}')
        with self.assertRaises(ValueError):
            strict_json('{"x":NaN}')
        bad = envelope(chat_packets("health", {})[0])
        bad["total"] = MAX_PARTS + 1
        body = strict_json(chat_packets("health", {})[0])
        body["messages"][0]["content"] = compact(bad).decode()
        with self.assertRaises(AdapterError):
            parse_chat(body)

    def test_backend_cannot_be_arbitrary_url(self):
        for url in ("https://example.com", "http://10.0.0.1:19924", "http://127.0.0.1:19924/other"):
            with self.assertRaises(ValueError):
                FixedBackend(url, "test" * 16)
        FixedBackend("http://127.0.0.1:19926", "test" * 16)


class NetworkChecks(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""})
        self.environment.start()
        self.stub = StubBackend()
        self.token = "local-stub-credential-" * 3
        self.server = AdapterServer(("127.0.0.1", 0), self.token, self.stub)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.initial = {"targets": {"rows": [[1], [2], [3]]}}
        self.client = ModelGPUTransport(self.initial, {
            "base_url": "http://127.0.0.1:" + str(self.server.server_port) + "/v1",
            "credential": self.token})

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.environment.stop()

    def choose(self, scores, factors):
        return self.client.choose({"decision_sequence": self.client.sequence + 1}, scores, factors, {}, [])

    def test_normal_action_and_two_state_overwrites(self):
        self.assertEqual(self.client.check()["remote_check"], "ok")
        action = self.choose([.8, 0., .1], [.9, 0., .2])["action"]
        self.assertEqual(action, {"action": "wait", "duration_seconds": 60})
        self.assertEqual(self.stub.calls[-1][1]["best_scores"], [.8, 0., .1])
        self.choose([.3, .5, 0.], [.4, .8, 0.])
        self.assertEqual(self.stub.calls[-1][1]["best_scores"], [.3, .5, 0.])
        self.assertEqual(self.stub.calls[-1][1]["best_factors"], [.4, .8, 0.])
        self.assertEqual(self.client.calls, 2)
        self.assertEqual(self.client.failures, 0)

    def test_lost_ack_resets_full_state_including_values_changed_back(self):
        self.choose([.8, 0., .1], [.9, 0., .2])
        original = self.client.request

        def lost_ack(op, payload=None, timeout=4):
            result = original(op, payload, timeout)
            if op == "choose":
                raise TimeoutError("synthetic lost answer")
            return result

        with patch.object(self.client, "request", lost_ack):
            with self.assertRaises(TimeoutError):
                self.choose([1., 0., .1], [1., 0., .2])
        # Returns to previous ACK state: an ordinary diff would omit index 0.
        self.choose([.8, 0., .1], [.9, 0., .2])
        self.assertEqual(self.stub.calls[-1][1]["best_scores"], [.8, 0., .1])
        self.assertEqual(self.client.failures, 0)

    def test_two_failures_disable_remote_and_do_not_commit_cache(self):
        self.choose([.8, 0., .1], [.9, 0., .2])
        with patch.object(self.client, "request", side_effect=TimeoutError("synthetic")):
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    self.choose([1., 0., .1], [1., 0., .2])
        self.assertFalse(self.client.enabled)
        self.assertIsNone(self.client.previous_scores)

    def test_auth_cors_wrong_route_and_large_body(self):
        cases = [(401, "/v1/chat/completions", {}, chat_packets("health", {})[0]),
                 (403, "/v1/chat/completions", {"Origin": "https://attacker.example"}, chat_packets("health", {})[0]),
                 (404, "/anything", {}, chat_packets("health", {})[0]),
                 (413, "/v1/chat/completions", {}, b"x" * MAX_CHAT_BYTES)]
        for expected, path, extras, data in cases:
            conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
            headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json", **extras}
            if expected == 401:
                headers["Authorization"] = "Bearer not-authorized"
            conn.request("POST", path, data, headers)
            response = conn.getresponse()
            self.assertEqual(response.status, expected)
            self.assertNotIn(self.token.encode(), response.read())
            conn.close()
        self.assertFalse(self.stub.calls)

    def test_exact_cors_preflight(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        conn.request("OPTIONS", "/v1/chat/completions", headers={"Origin": "https://create.gosim.org"})
        response = conn.getresponse()
        self.assertEqual(response.status, 204)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "https://create.gosim.org")
        response.read()
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
