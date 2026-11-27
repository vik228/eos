"""Streamable HTTP remote MCP server for EOS KB with isolated /mcp/personal and /mcp/work endpoints."""

from __future__ import annotations

import json
import os
import secrets
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .mcp_oauth import GoogleExchangeFn, GoogleOAuthBroker, GoogleOAuthConfig, OAuthError
from .mcp_tools import TOOL_DEFINITIONS, McpToolError, dispatch_tool

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


@dataclass(frozen=True)
class McpServerConfig:
    base_url: str
    kb_roots: dict[str, Path]
    google_client_id: str
    google_client_secret: str
    allowed_emails: dict[str, frozenset[str]]
    oauth_db_path: Path
    host: str = "127.0.0.1"
    port: int = 8765


def _parse_email_list(raw: str | None) -> frozenset[str]:
    if not raw or not raw.strip():
        return frozenset()
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def load_config_from_env(environ: dict[str, str] | None = None) -> McpServerConfig:
    env = dict(os.environ if environ is None else environ)
    home = Path(env.get("HOME", str(Path.home())))
    base_url = env.get("EOS_MCP_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("EOS_MCP_BASE_URL must be set in the environment (e.g. https://kb.example.com).")
    personal_kb = Path(env.get("EOS_PERSONAL_KNOWLEDGE_ROOT", str(home / "personal/knowledge"))).expanduser()
    work_kb = Path(env.get("EOS_WORK_KNOWLEDGE_ROOT", str(home / "work/knowledge"))).expanduser()
    oauth_db = Path(
        env.get("EOS_MCP_OAUTH_DB", str(home / ".local/share/eos/kb/mcp-oauth.sqlite3"))
    ).expanduser()
    client_id = env.get("EOS_MCP_GOOGLE_CLIENT_ID", "").strip()
    client_secret = env.get("EOS_MCP_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "EOS_MCP_GOOGLE_CLIENT_ID and EOS_MCP_GOOGLE_CLIENT_SECRET must be set in the environment."
        )
    allowed_emails = {
        "personal": _parse_email_list(env.get("EOS_MCP_PERSONAL_EMAILS")),
        "work": _parse_email_list(env.get("EOS_MCP_WORK_EMAILS")),
    }
    if not allowed_emails["personal"] and not allowed_emails["work"]:
        raise RuntimeError(
            "At least one of EOS_MCP_PERSONAL_EMAILS or EOS_MCP_WORK_EMAILS must be set in the environment."
        )
    return McpServerConfig(
        base_url=base_url,
        kb_roots={"personal": personal_kb, "work": work_kb},
        google_client_id=client_id,
        google_client_secret=client_secret,
        allowed_emails=allowed_emails,
        oauth_db_path=oauth_db,
        host=env.get("EOS_MCP_HOST", "127.0.0.1"),
        port=int(env.get("EOS_MCP_PORT", "8765")),
    )


def _jsonrpc_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def create_app(
    config: McpServerConfig,
    *,
    google_exchange: GoogleExchangeFn | None = None,
) -> Starlette:
    broker = GoogleOAuthBroker(
        GoogleOAuthConfig(
            base_url=config.base_url,
            client_id=config.google_client_id,
            client_secret=config.google_client_secret,
            allowed_emails=config.allowed_emails,
            db_path=config.oauth_db_path,
        ),
        google_exchange=google_exchange,
    )

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "profiles": sorted(config.kb_roots)})

    async def well_known_protected_resource(request: Request) -> JSONResponse:
        profile = request.path_params.get("profile")
        if profile is not None and profile not in config.kb_roots:
            return JSONResponse({"error": "unknown_profile"}, status_code=404)
        return JSONResponse(broker.protected_resource_metadata(profile))

    async def well_known_auth_server(request: Request) -> JSONResponse:
        profile = request.path_params.get("profile")
        if profile is not None and profile not in config.kb_roots:
            return JSONResponse({"error": "unknown_profile"}, status_code=404)
        return JSONResponse(broker.authorization_server_metadata(profile))

    async def oauth_register(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid_request", "error_description": "Invalid JSON body."}, status_code=400)
        try:
            result = broker.store.register_client(
                client_name=str(body.get("client_name") or "MCP Client"),
                redirect_uris=list(body.get("redirect_uris") or []),
            )
        except OAuthError as exc:
            return JSONResponse({"error": exc.code, "error_description": exc.description}, status_code=exc.status_code)
        return JSONResponse(result, status_code=201)

    async def oauth_authorize(request: Request) -> Response:
        profile = request.path_params.get("profile")
        qp = request.query_params
        try:
            google_url = broker.start_authorize(
                profile=profile,
                client_id=qp.get("client_id"),
                redirect_uri=qp.get("redirect_uri"),
                response_type=qp.get("response_type"),
                code_challenge=qp.get("code_challenge"),
                code_challenge_method=qp.get("code_challenge_method"),
                client_state=qp.get("state"),
                resource=qp.get("resource"),
                scope=qp.get("scope"),
            )
        except OAuthError as exc:
            return JSONResponse({"error": exc.code, "error_description": exc.description}, status_code=exc.status_code)
        return RedirectResponse(url=google_url, status_code=302)

    async def oauth_google_callback(request: Request) -> Response:
        qp = request.query_params
        try:
            redirect_url = await broker.complete_google_callback(
                code=qp.get("code"),
                state=qp.get("state"),
                error=qp.get("error"),
            )
        except OAuthError as exc:
            return HTMLResponse(
                f"<h1>Authorization Failed</h1><p>{exc.description}</p>",
                status_code=exc.status_code,
            )
        return RedirectResponse(url=redirect_url, status_code=302)

    async def oauth_token(request: Request) -> JSONResponse:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                raw = await request.json()
                form = {str(k): str(v) for k, v in raw.items()}
            except json.JSONDecodeError:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
        else:
            raw_body = (await request.body()).decode("utf-8", errors="replace")
            form = dict(urllib.parse.parse_qsl(raw_body, keep_blank_values=True))
        try:
            payload = broker.exchange_token(form)
        except OAuthError as exc:
            return JSONResponse({"error": exc.code, "error_description": exc.description}, status_code=exc.status_code)
        return JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    def _authenticate(request: Request, profile: str) -> Response | None:
        base = config.base_url.rstrip("/")
        www_auth = (
            f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp/{profile}", '
            f'scope="mcp:{profile}"'
        )
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "unauthorized", "error_description": "Missing Bearer token."},
                status_code=401,
                headers={"WWW-Authenticate": www_auth},
            )
        token = auth_header.removeprefix("Bearer ").strip()
        info = broker.store.verify_access_token(token)
        if info is None:
            return JSONResponse(
                {"error": "invalid_token", "error_description": "Access token is invalid or expired."},
                status_code=401,
                headers={"WWW-Authenticate": www_auth},
            )
        if info.profile != profile:
            return JSONResponse(
                {
                    "error": "insufficient_scope",
                    "error_description": f"Token is scoped to '{info.profile}' and cannot access '{profile}'.",
                },
                status_code=403,
            )
        return None

    async def mcp_endpoint(request: Request) -> Response:
        profile = request.path_params["profile"]
        if profile not in config.kb_roots:
            return JSONResponse({"error": "unknown_profile"}, status_code=404)

        auth_error = _authenticate(request, profile)
        if auth_error is not None:
            return auth_error

        if request.method == "DELETE":
            return Response(status_code=204)
        if request.method == "GET":
            return Response(status_code=405, headers={"Allow": "POST, DELETE"})

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(_jsonrpc_error(None, -32700, "Parse error"), status_code=400)

        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            return JSONResponse(_jsonrpc_error(None, -32600, "Invalid Request"), status_code=400)

        method = payload.get("method")
        msg_id = payload.get("id")
        params = payload.get("params") or {}

        # Notifications (no id) return 202 Accepted per MCP Streamable HTTP spec.
        if msg_id is None:
            return Response(status_code=202)

        if method == "initialize":
            requested_version = params.get("protocolVersion")
            negotiated = (
                requested_version
                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                else SUPPORTED_PROTOCOL_VERSIONS[0]
            )
            session_id = secrets.token_urlsafe(24)
            return JSONResponse(
                _jsonrpc_result(
                    msg_id,
                    {
                        "protocolVersion": negotiated,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": f"eos-kb-{profile}", "version": "0.1.0"},
                    },
                ),
                headers={"Mcp-Session-Id": session_id},
            )

        if method == "ping":
            return JSONResponse(_jsonrpc_result(msg_id, {}))

        if method == "tools/list":
            return JSONResponse(_jsonrpc_result(msg_id, {"tools": TOOL_DEFINITIONS}))

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            kb_root = config.kb_roots[profile]
            try:
                result = await anyio.to_thread.run_sync(
                    dispatch_tool, kb_root, profile, str(tool_name or ""), arguments
                )
                return JSONResponse(
                    _jsonrpc_result(
                        msg_id,
                        {
                            "content": [{"type": "text", "text": result["text"]}],
                            "isError": False,
                        },
                    )
                )
            except McpToolError as exc:
                return JSONResponse(
                    _jsonrpc_result(
                        msg_id,
                        {
                            "content": [{"type": "text", "text": f"Error: {exc}"}],
                            "isError": True,
                        },
                    )
                )

        return JSONResponse(_jsonrpc_error(msg_id, -32601, f"Method not found: {method}"))

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", well_known_protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource/mcp/{profile}", well_known_protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", well_known_auth_server, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server/mcp/{profile}", well_known_auth_server, methods=["GET"]),
        Route("/oauth/register", oauth_register, methods=["POST"]),
        Route("/oauth/authorize", oauth_authorize, methods=["GET"]),
        Route("/oauth/authorize/{profile}", oauth_authorize, methods=["GET"]),
        Route("/oauth/google/callback", oauth_google_callback, methods=["GET"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Route("/mcp/{profile}", mcp_endpoint, methods=["POST", "GET", "DELETE"]),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Mcp-Session-Id", "Mcp-Protocol-Version"],
        expose_headers=["Mcp-Session-Id"],
    )
    return app


def main() -> None:
    config = load_config_from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
