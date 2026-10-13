"""Verify the real HTTP provider adapter and Track 1 privacy at the request boundary."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from pipelines.rag_agents.agents import MetadataAgent
from project_name.infrastructure.llm import OpenAICompatibleLLM


def test_openai_http_request_excludes_legacy_body() -> None:
    captured: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            captured.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
            response = json.dumps(
                {"choices": [{"message": {"content": "The sender is Alice."}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        llm = OpenAICompatibleLLM(f"http://127.0.0.1:{server.server_port}/v1", "test-model", "")
        metadata = json.dumps(
            {
                "email_id": "1",
                "sender": "alice@company.example",
                "date": "2026-01-01",
                "body": "SECRET_BODY",
            }
        )
        answer = MetadataAgent(llm).ask(metadata, "Who sent this?")
        assert "Alice" in answer.text
        assert "alice@company.example" in captured[0]
        assert "SECRET_BODY" not in captured[0]
        assert json.loads(captured[0])["model"] == "test-model"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
