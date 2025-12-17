import json
import os
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

import perplexity


def _load_cookies() -> Dict[str, str]:
    raw = os.environ.get("PPLX_COOKIES")
    if not raw:
        raise RuntimeError("PPLX_COOKIES environment variable is not set")
    try:
        cookies = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PPLX_COOKIES must be valid JSON") from exc
    if not isinstance(cookies, dict):
        raise RuntimeError("PPLX_COOKIES must deserialize to a dict of cookies")
    return cookies


def _parse_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length == 0:
        return {}
    body = handler.rfile.read(length)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc


class handler(BaseHTTPRequestHandler):  # noqa: N801 (Vercel expects lowercase)
    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802  (Vercel expects this signature)
        self._send(
            200,
            {"status": "ok", "message": "Use POST with JSON to run a Perplexity query."},
        )

    def do_POST(self) -> None:  # noqa: N802
        try:
            data = _parse_body(self)
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return

        query = data.get("query")
        if not query or not isinstance(query, str):
            self._send(400, {"error": "Field 'query' (string) is required"})
            return

        try:
            cookies = _load_cookies()
            client = perplexity.Client(cookies)

            response = client.search(
                query=query,
                mode=data.get("mode", "auto"),
                model=data.get("model"),
                sources=data.get("sources", ["web"]),
                files=data.get("files", {}),
                stream=False,
                language=data.get("language", "en-US"),
                follow_up=data.get("follow_up"),
                incognito=bool(data.get("incognito", False)),
            )
        except AssertionError as exc:
            self._send(400, {"error": str(exc)})
            return
        except Exception as exc:  # pragma: no cover - defensive guard for runtime issues
            self._send(500, {"error": "Search failed", "detail": str(exc)})
            return

        self._send(200, {"data": response})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Silence default HTTP request logging to keep Vercel logs clean.
        return
