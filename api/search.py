import json
import os
from typing import Any, Dict, List, Optional, Union

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from mangum import Mangum
from pydantic import BaseModel, ConfigDict, Field

import perplexity_async
from perplexity.config import MODEL_MAPPINGS, SEARCH_MODES, SEARCH_SOURCES
from perplexity.exceptions import ValidationError
from perplexity.utils import sanitize_query, validate_file_data, validate_search_params


def _load_json_env(name: str) -> Dict[str, str]:
    raw = os.getenv(name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must be a JSON object of cookies")
    return {str(k): str(v) for k, v in parsed.items()}


ENV_COOKIES_ERROR: Optional[str] = None
DEFAULT_COOKIES: Dict[str, str] = {}
EMAILNATOR_COOKIES: Dict[str, str] = {}

try:
    DEFAULT_COOKIES = _load_json_env("PPLX_COOKIES")
except RuntimeError as exc:  # pragma: no cover - validated at runtime
    ENV_COOKIES_ERROR = str(exc)

try:
    EMAILNATOR_COOKIES = _load_json_env("EMAILNATOR_COOKIES")
except RuntimeError:
    EMAILNATOR_COOKIES = {}

API_KEY = os.getenv("PPLX_API_KEY")


class SearchRequest(BaseModel):
    query: str
    mode: str = "auto"
    model: Optional[str] = None
    sources: List[str] = Field(default_factory=lambda: ["web"])
    files: Optional[Dict[str, str]] = None
    language: str = "en-US"
    follow_up: Optional[Dict[str, Any]] = None
    incognito: bool = False
    stream: bool = False
    cookies: Optional[Dict[str, str]] = None

    model_config = ConfigDict(extra="forbid")


class AccountCreateRequest(BaseModel):
    emailnator_cookies: Optional[Dict[str, str]] = None

    model_config = ConfigDict(extra="forbid")


app = FastAPI(
    title="Perplexity FastAPI backend",
    version="1.0.0",
    description="FastAPI wrapper exposing Perplexity search, streaming, file upload, and account creation.",
)


def require_api_key(
    x_api_key: Optional[str] = Header(default=None, convert_underscores=False),
    authorization: Optional[str] = Header(default=None),
) -> None:
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PPLX_API_KEY is not configured on the server.",
        )

    bearer_token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1]

    supplied = x_api_key or bearer_token
    if supplied != API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")


def _resolve_cookies(override: Optional[Dict[str, str]]) -> Dict[str, str]:
    if override:
        return override
    if ENV_COOKIES_ERROR:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ENV_COOKIES_ERROR,
        )
    return DEFAULT_COOKIES


def _parse_optional_json(raw: Optional[str], field_name: str) -> Optional[Any]:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field '{field_name}' must be valid JSON: {exc}",
        ) from exc


async def _run_search(
    request: SearchRequest, files: Dict[str, Any], cookies: Dict[str, str]
) -> Union[Dict[str, Any], StreamingResponse]:
    own_account = bool(cookies)

    try:
        validate_search_params(request.mode, request.model, request.sources, own_account=own_account)
        if files:
            validate_file_data(files)
        clean_query = sanitize_query(request.query)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    client = await perplexity_async.Client(cookies)

    if request.stream:
        search_stream = await client.search(
            query=clean_query,
            mode=request.mode,
            model=request.model,
            sources=request.sources,
            files=files,
            stream=True,
            language=request.language,
            follow_up=request.follow_up,
            incognito=request.incognito,
        )

        async def stream_response():
            async for chunk in search_stream:
                yield json.dumps(chunk).encode("utf-8") + b"\n"

        return StreamingResponse(stream_response(), media_type="application/x-ndjson")

    response = await client.search(
        query=clean_query,
        mode=request.mode,
        model=request.model,
        sources=request.sources,
        files=files,
        stream=False,
        language=request.language,
        follow_up=request.follow_up,
        incognito=request.incognito,
    )

    return {"data": response}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
def list_models() -> Dict[str, Dict[str, str]]:
    return {"modes": SEARCH_MODES, "sources": SEARCH_SOURCES, "models": MODEL_MAPPINGS}


@app.post("/v1/search", dependencies=[Depends(require_api_key)])
async def search(request: SearchRequest):
    cookies = _resolve_cookies(request.cookies)
    files = request.files or {}
    try:
        result = await _run_search(request, files, cookies)
    except AssertionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {exc}",
        ) from exc

    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post("/v1/search/upload", dependencies=[Depends(require_api_key)])
async def search_with_upload(
    query: str = Form(...),
    mode: str = Form("auto"),
    model: Optional[str] = Form(default=None),
    sources: Optional[str] = Form(default=None),
    language: str = Form("en-US"),
    incognito: bool = Form(False),
    stream: bool = Form(False),
    follow_up: Optional[str] = Form(default=None),
    cookies: Optional[str] = Form(default=None),
    files: Optional[List[UploadFile]] = File(default=None),
):
    request = SearchRequest(
        query=query,
        mode=mode,
        model=model,
        sources=_parse_optional_json(sources, "sources") or ["web"],
        language=language,
        incognito=incognito,
        stream=stream,
        follow_up=_parse_optional_json(follow_up, "follow_up"),
        cookies=_parse_optional_json(cookies, "cookies"),
    )

    upload_map: Dict[str, bytes] = {}
    for upload in files or []:
        upload_map[upload.filename] = await upload.read()

    resolved_cookies = _resolve_cookies(request.cookies)

    try:
        result = await _run_search(request, upload_map, resolved_cookies)
    except AssertionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {exc}",
        ) from exc

    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post("/v1/account", dependencies=[Depends(require_api_key)])
async def create_account(request: AccountCreateRequest):
    cookies = request.emailnator_cookies or EMAILNATOR_COOKIES
    if not cookies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Emailnator cookies are required (provide in body or EMAILNATOR_COOKIES env).",
        )

    client = await perplexity_async.Client({})
    try:
        await client.create_account(cookies)
        session_cookies = client.session.cookies.get_dict()
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Account creation failed: {exc}",
        ) from exc

    return {"data": {"cookies": session_cookies, "copilot": client.copilot, "file_upload": client.file_upload}}


@app.get("/v1/usage", dependencies=[Depends(require_api_key)])
def usage() -> Dict[str, Any]:
    # Shows whether cookies are loaded so callers can debug auth quickly.
    return {
        "has_cookies": bool(DEFAULT_COOKIES),
        "has_emailnator_cookies": bool(EMAILNATOR_COOKIES),
        "auth_mode": "api_key",
    }


handler = Mangum(app)
