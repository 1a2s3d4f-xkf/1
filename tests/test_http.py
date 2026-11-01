import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from local_ai.agent import run_agent
from local_ai.client import OllamaClient
from local_ai.config import Config, LabError
from test_lab import Fixture, call, response


class HttpTests(Fixture):
    def setUp(self):
        super().setUp()
        self.requests = []
        self.route = lambda path, body: (200, {"version": "test-only"})
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = json.loads(data) if data else None
                outer.requests.append((self.path, body))
                status, payload = outer.route(self.path, body)
                encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Location", "http://127.0.0.1:1/not-followed")
                self.end_headers()
                self.wfile.write(encoded)

            do_GET = do_POST = handle_request

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.config = Config(base_url=f"http://127.0.0.1:{self.server.server_port}")
        self.client = OllamaClient(self.config)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_real_http_unicode_tool_roundtrip(self):
        def route(path, body):
            if path == "/api/show":
                return 200, {"capabilities": ["completion", "tools"], "details": {"format": "gguf"}}
            if path == "/api/version":
                return 200, {"version": "test-only"}
            self.assertEqual(path, "/api/chat")
            self.assertFalse(body["stream"])
            self.assertFalse(body["think"])
            self.assertEqual(body["options"]["num_ctx"], 8192)
            self.assertEqual(body["messages"][1]["content"], "请计算")
            if body["messages"][-1]["role"] != "tool":
                return 200, response([call(expression="123*456")], content="")
            self.assertEqual(body["messages"][-1]["tool_name"], "calculate")
            self.assertEqual(json.loads(body["messages"][-1]["content"])["value"], 56088)
            return 200, response(content="结果为 56088。")
        self.route = route
        self.assertEqual(self.client.preflight()["ollama_version"], "test-only")
        result = run_agent(self.client, self.runner, "请计算", self.config)
        self.assertEqual(result.text, "结果为 56088。")
        self.assertEqual(len(self.requests), 4)

    def test_remote_alias_rejected_before_chat(self):
        for field in ("remote_host", "remote_model"):
            self.route = lambda path, body: (200, {"capabilities": ["tools"], field: "cloud"})
            with self.assertRaisesRegex(LabError, "远程"):
                self.client.preflight()
        self.assertNotIn("/api/chat", [p for p, _ in self.requests])

    def test_model_without_tools_is_rejected(self):
        self.route = lambda path, body: (200, {"capabilities": ["completion"]})
        with self.assertRaisesRegex(LabError, "tools"):
            self.client.preflight()

    def test_http_errors_and_redirects_are_not_retried(self):
        for status in (302, 404, 500):
            before = len(self.requests)
            self.route = lambda path, body: (status, {"error": "test error"})
            with self.assertRaises(LabError):
                self.client.request("/api/version")
            self.assertEqual(len(self.requests), before + 1)

    def test_invalid_json_and_response_size(self):
        self.route = lambda path, body: (200, b"not JSON")
        with self.assertRaises(LabError):
            self.client.request("/api/version")
        self.route = lambda path, body: (200, b" " * 101)
        with patch("local_ai.client.MAX_RESPONSE_BYTES", 100), self.assertRaises(LabError):
            self.client.request("/api/version")

    def test_timeout_has_actionable_error(self):
        with patch("http.client.HTTPConnection.request", side_effect=TimeoutError), self.assertRaisesRegex(LabError, "超时"):
            self.client.request("/api/version")


if __name__ == "__main__":
    unittest.main()
