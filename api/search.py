import base64
import binascii
import json
import os
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Iterable

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


def _get_api_key() -> str:
    key = os.environ.get("PPLX_API_KEY")
    if not key:
        raise RuntimeError("PPLX_API_KEY environment variable is not set")
    return key


def _parse_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length == 0:
        return {}
    body = handler.rfile.read(length)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc


def _decode_file_content(content: Any, filename: str, encoding: str) -> Any:
    if encoding and encoding.lower() == "base64":
        try:
            return base64.b64decode(content)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid base64 content for file '{filename}'") from exc

    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(content, str):
        return content
    raise ValueError(f"Unsupported content type for file '{filename}'")


def _parse_files(raw_files: Any) -> Dict[str, Any]:
    if not raw_files:
        return {}

    files: Dict[str, Any] = {}
    if isinstance(raw_files, dict):
        for filename, payload in raw_files.items():
            if isinstance(payload, dict) and "content" in payload:
                encoding = payload.get("encoding") or ("base64" if payload.get("base64") else "")
                files[filename] = _decode_file_content(payload["content"], filename, encoding)
            else:
                files[filename] = _decode_file_content(payload, filename, "")
        return files

    if isinstance(raw_files, list):
        for item in raw_files:
            if not isinstance(item, dict) or "filename" not in item or "content" not in item:
                raise ValueError("Each item in 'files' must include 'filename' and 'content'")
            encoding = item.get("encoding") or ("base64" if item.get("base64") else "")
            files[item["filename"]] = _decode_file_content(item["content"], item["filename"], encoding)
        return files

    raise ValueError("Field 'files' must be a dict or a list of file objects")


class handler(BaseHTTPRequestHandler):  # noqa: N801 (Vercel expects lowercase)
    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self, chunks: Iterable[Dict[str, Any]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()

        try:
            for chunk in chunks:
                message = f"data: {json.dumps({'data': chunk})}\n\n".encode("utf-8")
                self.wfile.write(message)
                self.wfile.flush()
        except BrokenPipeError:
            return

        try:
            self.wfile.write(b"event: end\ndata: {}\n\n")
            self.wfile.flush()
        except BrokenPipeError:
            return

    def _cors_headers(self) -> Dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        }

    def _authenticate(self) -> bool:
        try:
            expected = _get_api_key()
        except RuntimeError as exc:
            self._send(500, {"error": str(exc)})
            return False

        provided = self.headers.get("x-api-key") or ""
        auth_header = self.headers.get("authorization") or ""
        if not provided and auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()

        if not provided or provided != expected:
            self._send(401, {"error": "Invalid or missing API key"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802  (Vercel expects this signature)
        self._send(
            200,
            {"status": "ok", "message": "Use POST with JSON to run a Perplexity query."},
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticate():
            return

        try:
            data = _parse_body(self)
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return

        try:
            files = _parse_files(data.get("files"))
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return

        query = data.get("query")
        if not query or not isinstance(query, str):
            self._send(400, {"error": "Field 'query' (string) is required"})
            return

        sources = data.get("sources", ["web"])
        if isinstance(sources, str):
            sources = [sources]

        stream_raw = data.get("stream", False)
        stream = stream_raw if isinstance(stream_raw, bool) else str(stream_raw).lower() == "true"

        incognito_raw = data.get("incognito", False)
        incognito = (
            incognito_raw
            if isinstance(incognito_raw, bool)
            else str(incognito_raw).lower() == "true"
        )

        try:
            cookies = _load_cookies()
            client = perplexity.Client(cookies)

            search_kwargs = dict(
                query=query,
                mode=data.get("mode", "auto"),
                model=data.get("model"),
                sources=sources,
                files=files,
                stream=stream,
                language=data.get("language", "en-US"),
                follow_up=data.get("follow_up"),
                incognito=incognito,
            )

            if stream:
                chunks = client.search(**search_kwargs)
                self._send_stream(chunks)
                return

            response = client.search(**search_kwargs)
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
