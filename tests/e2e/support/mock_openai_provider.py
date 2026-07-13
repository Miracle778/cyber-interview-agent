from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json({"status": "ok"})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            tools = request.get("tools") or []
            if tools:
                evaluation = {
                    "score": "partial",
                    "missing_key_points": ["隔离性", "持久性"],
                    "evidence": "回答包含原子性",
                }
                delta = {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-evaluation",
                            "type": "function",
                            "function": {
                                "name": tools[0]["function"]["name"],
                                "arguments": json.dumps(evaluation, ensure_ascii=False),
                            },
                        }
                    ]
                }
                chunks = ((delta, "tool_calls"),)
            else:
                chunks = tuple(
                    ({"content": text}, None)
                    for text in (
                        "# 单题复习报告\n\n",
                        "- 评分：partial\n- 下一步：补充隔离性和持久性\n",
                    )
                )
            for delta, finish_reason in chunks:
                chunk = {
                    "id": "chatcmpl-stream",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.get("model", "e2e-model"),
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    ],
                }
                self.wfile.write(
                    f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode(
                        "utf-8"
                    )
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        evaluation = {
            "score": "partial",
            "missing_key_points": ["隔离性", "持久性"],
            "evidence": "回答包含原子性",
        }
        tools = request.get("tools") or []
        if request.get("response_format"):
            message = {
                "role": "assistant",
                "content": json.dumps(evaluation, ensure_ascii=False),
            }
            finish_reason = "stop"
        elif tools:
            function_name = tools[0]["function"]["name"]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-evaluation",
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "arguments": json.dumps(evaluation, ensure_ascii=False),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "ok"}
            finish_reason = "stop"
        self._json(
            {
                "id": "chatcmpl-e2e",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.get("model", "e2e-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 9017), Handler).serve_forever()
