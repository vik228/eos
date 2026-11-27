"""OAuth 2.1 broker for EOS remote MCP delegating identity to Google OAuth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

PENDING_AUTH_TTL_SECONDS = 600
AUTH_CODE_TTL_SECONDS = 300
ACCESS_TOKEN_TTL_SECONDS = 86400
REFRESH_TOKEN_TTL_SECONDS = 86400 * 90


class OAuthError(RuntimeError):
    def __init__(self, code: str, description: str, status_code: int = 400) -> None:
        self.code = code
        self.description = description
        self.status_code = status_code
        super().__init__(f"{code}: {description}")


@dataclass(frozen=True)
class TokenInfo:
    profile: str
    email: str
    client_id: str
    resource: str
    expires_at: float


@dataclass(frozen=True)
class GoogleOAuthConfig:
    base_url: str
    client_id: str
    client_secret: str
    allowed_emails: dict[str, frozenset[str]]
    db_path: Path
    google_auth_url: str = GOOGLE_AUTH_URL
    google_token_url: str = GOOGLE_TOKEN_URL
    google_userinfo_url: str = GOOGLE_USERINFO_URL

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.base_url.rstrip('/')}/oauth/google/callback"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _valid_redirect_uri(uri: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(uri)
    except ValueError:
        return False
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    return False


def infer_profile_from_resource(resource: str | None, scope: str | None = None) -> str | None:
    if resource:
        parsed = urllib.parse.urlparse(resource)
        path = parsed.path.rstrip("/")
        if path.endswith("/mcp/work"):
            return "work"
        if path.endswith("/mcp/personal"):
            return "personal"
    if scope:
        tokens = set(scope.split())
        if "mcp:work" in tokens or "work" in tokens:
            return "work"
        if "mcp:personal" in tokens or "personal" in tokens:
            return "personal"
    return None


GoogleExchangeFn = Callable[[str, str], Awaitable[dict[str, Any]]]


class OAuthStore:
    """SQLite-backed OAuth 2.1 broker state (stores hashed tokens only)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    redirect_uris TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_auth (
                    google_state TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    code_challenge TEXT NOT NULL,
                    client_state TEXT,
                    profile TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code_hash TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    code_challenge TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    email TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token_hash TEXT PRIMARY KEY,
                    token_type TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    email TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                """
            )
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def register_client(self, client_name: str, redirect_uris: list[str]) -> dict[str, Any]:
        if not redirect_uris or not all(isinstance(u, str) and _valid_redirect_uri(u) for u in redirect_uris):
            raise OAuthError("invalid_redirect_uri", "All redirect_uris must be valid https or localhost URLs.")
        client_id = "eos_" + secrets.token_urlsafe(24)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO clients (client_id, client_name, redirect_uris, created_at) VALUES (?, ?, ?, ?)",
                (client_id, client_name or "MCP Client", json.dumps(redirect_uris), now),
            )
        return {
            "client_id": client_id,
            "client_name": client_name or "MCP Client",
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        }

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        if row is None:
            return None
        return {
            "client_id": row["client_id"],
            "client_name": row["client_name"],
            "redirect_uris": json.loads(row["redirect_uris"]),
        }

    def create_pending_auth(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        client_state: str | None,
        profile: str,
        resource: str,
    ) -> str:
        google_state = secrets.token_urlsafe(32)
        expires_at = time.time() + PENDING_AUTH_TTL_SECONDS
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_auth WHERE expires_at < ?", (time.time(),))
            conn.execute(
                """
                INSERT INTO pending_auth
                    (google_state, client_id, redirect_uri, code_challenge, client_state, profile, resource, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (google_state, client_id, redirect_uri, code_challenge, client_state, profile, resource, expires_at),
            )
        return google_state

    def pop_pending_auth(self, google_state: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_auth WHERE google_state = ?", (google_state,)
            ).fetchone()
            if row is not None:
                conn.execute("DELETE FROM pending_auth WHERE google_state = ?", (google_state,))
        if row is None or row["expires_at"] < now:
            return None
        return dict(row)

    def create_auth_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        profile: str,
        email: str,
        resource: str,
    ) -> str:
        raw_code = secrets.token_urlsafe(32)
        expires_at = time.time() + AUTH_CODE_TTL_SECONDS
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_codes WHERE expires_at < ?", (time.time(),))
            conn.execute(
                """
                INSERT INTO auth_codes
                    (code_hash, client_id, redirect_uri, code_challenge, profile, email, resource, expires_at, used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (_sha256_hex(raw_code), client_id, redirect_uri, code_challenge, profile, email, resource, expires_at),
            )
        return raw_code

    def consume_auth_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        now = time.time()
        code_hash = _sha256_hex(code)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM auth_codes WHERE code_hash = ?", (code_hash,)).fetchone()
            if row is None or row["used"] or row["expires_at"] < now:
                raise OAuthError("invalid_grant", "Authorization code is invalid or expired.")
            if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
                raise OAuthError("invalid_grant", "Authorization code does not match client or redirect_uri.")
            expected = _pkce_s256(code_verifier)
            if not hmac.compare_digest(expected, row["code_challenge"]):
                raise OAuthError("invalid_grant", "PKCE code_verifier verification failed.")
            conn.execute("UPDATE auth_codes SET used = 1 WHERE code_hash = ?", (code_hash,))
            return dict(row)

    def issue_token_pair(
        self,
        *,
        client_id: str,
        profile: str,
        email: str,
        resource: str,
    ) -> dict[str, Any]:
        now = time.time()
        access_token = "eos_at_" + secrets.token_urlsafe(32)
        refresh_token = "eos_rt_" + secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tokens
                    (token_hash, token_type, client_id, profile, email, resource, expires_at, revoked)
                VALUES (?, 'access', ?, ?, ?, ?, ?, 0)
                """,
                (_sha256_hex(access_token), client_id, profile, email, resource, now + ACCESS_TOKEN_TTL_SECONDS),
            )
            conn.execute(
                """
                INSERT INTO tokens
                    (token_hash, token_type, client_id, profile, email, resource, expires_at, revoked)
                VALUES (?, 'refresh', ?, ?, ?, ?, ?, 0)
                """,
                (_sha256_hex(refresh_token), client_id, profile, email, resource, now + REFRESH_TOKEN_TTL_SECONDS),
            )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL_SECONDS,
            "refresh_token": refresh_token,
            "scope": f"mcp:{profile}",
        }

    def rotate_refresh_token(self, *, refresh_token: str, client_id: str) -> dict[str, Any]:
        now = time.time()
        token_hash = _sha256_hex(refresh_token)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tokens WHERE token_hash = ? AND token_type = 'refresh'",
                (token_hash,),
            ).fetchone()
            if row is None or row["revoked"] or row["expires_at"] < now:
                raise OAuthError("invalid_grant", "Refresh token is invalid or expired.")
            if row["client_id"] != client_id:
                raise OAuthError("invalid_grant", "Refresh token client mismatch.")
            conn.execute("UPDATE tokens SET revoked = 1 WHERE token_hash = ?", (token_hash,))
            profile = row["profile"]
            email = row["email"]
            resource = row["resource"]
        return self.issue_token_pair(
            client_id=client_id, profile=profile, email=email, resource=resource
        )

    def verify_access_token(self, raw_token: str) -> TokenInfo | None:
        now = time.time()
        token_hash = _sha256_hex(raw_token)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tokens WHERE token_hash = ? AND token_type = 'access'",
                (token_hash,),
            ).fetchone()
        if row is None or row["revoked"] or row["expires_at"] < now:
            return None
        return TokenInfo(
            profile=row["profile"],
            email=row["email"],
            client_id=row["client_id"],
            resource=row["resource"],
            expires_at=row["expires_at"],
        )


class GoogleOAuthBroker:
    """Handles MCP OAuth 2.1 metadata, DCR, PKCE, and Google identity verification."""

    def __init__(
        self,
        config: GoogleOAuthConfig,
        *,
        google_exchange: GoogleExchangeFn | None = None,
    ) -> None:
        self.config = config
        self.store = OAuthStore(config.db_path)
        self._google_exchange = google_exchange or self._default_google_exchange

    async def _default_google_exchange(self, code: str, redirect_uri: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                self.config.google_token_url,
                data={
                    "code": code,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise OAuthError("server_error", f"Google token exchange failed ({token_resp.status_code}).", 502)
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise OAuthError("server_error", "Google token response missing access_token.", 502)
            userinfo_resp = await client.get(
                self.config.google_userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                raise OAuthError("server_error", f"Google userinfo fetch failed ({userinfo_resp.status_code}).", 502)
            return userinfo_resp.json()

    def protected_resource_metadata(self, profile: str | None = None) -> dict[str, Any]:
        base = self.config.base_url.rstrip("/")
        if profile in ("personal", "work"):
            return {
                "resource": f"{base}/mcp/{profile}",
                "authorization_servers": [f"{base}/mcp/{profile}"],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [f"mcp:{profile}"],
            }
        return {
            "resource": base,
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["mcp:personal", "mcp:work"],
        }

    def authorization_server_metadata(self, profile: str | None = None) -> dict[str, Any]:
        base = self.config.base_url.rstrip("/")
        issuer = f"{base}/mcp/{profile}" if profile in ("personal", "work") else base
        auth_endpoint = f"{base}/oauth/authorize/{profile}" if profile in ("personal", "work") else f"{base}/oauth/authorize"
        return {
            "issuer": issuer,
            "authorization_endpoint": auth_endpoint,
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [f"mcp:{profile}"] if profile in ("personal", "work") else ["mcp:personal", "mcp:work"],
        }

    def start_authorize(
        self,
        *,
        profile: str | None,
        client_id: str | None,
        redirect_uri: str | None,
        response_type: str | None,
        code_challenge: str | None,
        code_challenge_method: str | None,
        client_state: str | None,
        resource: str | None,
        scope: str | None,
    ) -> str:
        if response_type != "code":
            raise OAuthError("unsupported_response_type", "Only response_type=code is supported.")
        if not client_id:
            raise OAuthError("invalid_request", "client_id is required.")
        client = self.store.get_client(client_id)
        if client is None:
            raise OAuthError("invalid_client", "Unknown client_id.")
        if not redirect_uri or redirect_uri not in client["redirect_uris"]:
            raise OAuthError("invalid_request", "redirect_uri does not match registered client.")
        if not code_challenge or (code_challenge_method or "S256") != "S256":
            raise OAuthError("invalid_request", "PKCE S256 code_challenge is required.")

        resolved_profile = profile or infer_profile_from_resource(resource, scope)
        if resolved_profile not in self.config.allowed_emails:
            raise OAuthError("invalid_request", "Could not determine valid KB profile (personal or work).")

        resolved_resource = resource or f"{self.config.base_url.rstrip('/')}/mcp/{resolved_profile}"
        google_state = self.store.create_pending_auth(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            client_state=client_state,
            profile=resolved_profile,
            resource=resolved_resource,
        )
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": google_state,
            "prompt": "select_account",
        }
        return f"{self.config.google_auth_url}?{urllib.parse.urlencode(params)}"

    async def complete_google_callback(self, *, code: str | None, state: str | None, error: str | None) -> str:
        if error:
            raise OAuthError("access_denied", f"Google OAuth returned error: {error}", 403)
        if not code or not state:
            raise OAuthError("invalid_request", "Missing code or state from Google callback.")
        pending = self.store.pop_pending_auth(state)
        if pending is None:
            raise OAuthError("invalid_request", "Authorization session expired or invalid.")

        userinfo = await self._google_exchange(code, self.config.google_redirect_uri)
        email = str(userinfo.get("email") or "").strip().lower()
        verified = bool(userinfo.get("email_verified"))
        profile = pending["profile"]
        allowed = self.config.allowed_emails.get(profile, frozenset())
        if not email or not verified or email not in allowed:
            raise OAuthError(
                "access_denied",
                f"Google account '{email or 'unknown'}' is not authorized for the '{profile}' KB endpoint.",
                403,
            )

        mcp_code = self.store.create_auth_code(
            client_id=pending["client_id"],
            redirect_uri=pending["redirect_uri"],
            code_challenge=pending["code_challenge"],
            profile=profile,
            email=email,
            resource=pending["resource"],
        )
        redirect_params: dict[str, str] = {"code": mcp_code}
        if pending["client_state"]:
            redirect_params["state"] = pending["client_state"]
        sep = "&" if "?" in pending["redirect_uri"] else "?"
        return f"{pending['redirect_uri']}{sep}{urllib.parse.urlencode(redirect_params)}"

    def exchange_token(self, form: dict[str, str]) -> dict[str, Any]:
        grant_type = form.get("grant_type")
        client_id = form.get("client_id", "")
        if not client_id:
            raise OAuthError("invalid_client", "client_id is required.")
        if grant_type == "authorization_code":
            code = form.get("code", "")
            redirect_uri = form.get("redirect_uri", "")
            code_verifier = form.get("code_verifier", "")
            if not code or not redirect_uri or not code_verifier:
                raise OAuthError("invalid_request", "code, redirect_uri, and code_verifier are required.")
            record = self.store.consume_auth_code(
                code=code,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
            return self.store.issue_token_pair(
                client_id=client_id,
                profile=record["profile"],
                email=record["email"],
                resource=record["resource"],
            )
        if grant_type == "refresh_token":
            refresh_token = form.get("refresh_token", "")
            if not refresh_token:
                raise OAuthError("invalid_request", "refresh_token is required.")
            return self.store.rotate_refresh_token(refresh_token=refresh_token, client_id=client_id)
        raise OAuthError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")
