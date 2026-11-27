"""Unit and integration tests for EOS remote MCP server and Google OAuth 2.1 broker."""

from __future__ import annotations

import base64
import hashlib
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from eos_kb.indexer import index_bundle
from eos_kb.mcp_server import McpServerConfig, create_app


def _pkce_pair(verifier: str = "test-pkce-verifier-string-1234567890-abcdef") -> tuple[str, str]:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _seed_kb(root: Path, *, project: str, title: str, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "00-index.md").write_text(
        f"---\ntitle: KB Index\ntype: Index\n---\n# Index\n- {project}\n",
        encoding="utf-8",
    )
    (root / "_pending-kb-updates.md").write_text(
        "---\ntitle: Pending KB Updates\ntype: Knowledge Proposal\n---\n\n# Pending KB Updates\n\n",
        encoding="utf-8",
    )
    proj_dir = root / "projects" / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "00-index.md").write_text(
        f"---\ntitle: {project} Index\ntype: Index\n---\n# {project}\n",
        encoding="utf-8",
    )
    (proj_dir / "_pending-kb-updates.md").write_text(
        f"---\ntitle: {project} Pending Updates\ntype: Knowledge Proposal\n---\n\n# Pending Updates\n\n",
        encoding="utf-8",
    )
    (proj_dir / "architecture.md").write_text(
        f"---\ntitle: {title}\ntype: Note\nresource: kb:test/{project}/architecture.md\nstatus: stable\nfreshness: historical\n---\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )
    res = index_bundle(root)
    assert not res.errors, f"index_bundle errors: {res.errors}"


@pytest.fixture(autouse=True)
def _isolate_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "eos-kb-state"))


def _make_client(
    tmp_path: Path,
    *,
    google_email: str = "personal@example.com",
    email_verified: bool = True,
) -> tuple[TestClient, Path, Path]:
    personal_kb = tmp_path / "personal-kb"
    work_kb = tmp_path / "work-kb"
    _seed_kb(personal_kb, project="eos", title="EOS Architecture", body="EOS uses SQLite FTS5 and Cloudflare tunnels.")
    _seed_kb(work_kb, project="nova", title="Nova Agent Runtime", body="Nova runs isolated enterprise workflows.")

    async def fake_google_exchange(code: str, redirect_uri: str) -> dict[str, Any]:
        assert code == "fake-google-code"
        assert redirect_uri == "https://kb.example.com/oauth/google/callback"
        return {"email": google_email, "email_verified": email_verified}

    cfg = McpServerConfig(
        base_url="https://kb.example.com",
        kb_roots={"personal": personal_kb, "work": work_kb},
        google_client_id="fake-client-id",
        google_client_secret="fake-client-secret",
        allowed_emails={
            "personal": frozenset({"personal@example.com"}),
            "work": frozenset({"work@example.com"}),
        },
        oauth_db_path=tmp_path / "mcp-oauth.sqlite3",
    )
    app = create_app(cfg, google_exchange=fake_google_exchange)
    return TestClient(app), personal_kb, work_kb


def _authorize_and_get_tokens(
    client: TestClient,
    *,
    profile: str,
    verifier: str = "verifier-1234567890-abcdefghijklmnopqrstuvwxyz",
) -> tuple[str, dict[str, Any]]:
    _, challenge = _pkce_pair(verifier)
    reg = client.post(
        "/oauth/register",
        json={"client_name": "Claude", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]},
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]

    auth_resp = client.get(
        f"/oauth/authorize/{profile}",
        params={
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "claude-state-xyz",
        },
        follow_redirects=False,
    )
    assert auth_resp.status_code == 302
    google_qs = urllib.parse.parse_qs(urllib.parse.urlparse(auth_resp.headers["location"]).query)
    google_state = google_qs["state"][0]

    cb_resp = client.get(
        "/oauth/google/callback",
        params={"code": "fake-google-code", "state": google_state},
        follow_redirects=False,
    )
    assert cb_resp.status_code == 302
    cb_qs = urllib.parse.parse_qs(urllib.parse.urlparse(cb_resp.headers["location"]).query)
    assert cb_qs["state"][0] == "claude-state-xyz"
    mcp_code = cb_qs["code"][0]

    tok_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code": mcp_code,
            "code_verifier": verifier,
        },
    )
    assert tok_resp.status_code == 200
    return client_id, tok_resp.json()


def test_discovery_and_dcr_validation(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    assert client.get("/health").json()["status"] == "ok"

    prm = client.get("/.well-known/oauth-protected-resource/mcp/personal")
    assert prm.status_code == 200
    assert prm.json()["resource"] == "https://kb.example.com/mcp/personal"

    asm = client.get("/.well-known/oauth-authorization-server/mcp/work")
    assert asm.status_code == 200
    assert asm.json()["authorization_endpoint"] == "https://kb.example.com/oauth/authorize/work"
    assert asm.json()["code_challenge_methods_supported"] == ["S256"]

    bad_reg = client.post(
        "/oauth/register",
        json={"client_name": "Evil", "redirect_uris": ["http://evil.example.com/cb"]},
    )
    assert bad_reg.status_code == 400


def test_unauthenticated_returns_401_with_resource_metadata(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.post("/mcp/personal", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 401
    assert "resource_metadata=\"https://kb.example.com/.well-known/oauth-protected-resource/mcp/personal\"" in resp.headers["www-authenticate"]


def test_unauthorized_google_email_rejected(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path, google_email="intruder@gmail.com")
    _, challenge = _pkce_pair()
    client_id = client.post(
        "/oauth/register",
        json={"client_name": "Claude", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]},
    ).json()["client_id"]
    auth_resp = client.get(
        "/oauth/authorize/personal",
        params={
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    google_state = urllib.parse.parse_qs(urllib.parse.urlparse(auth_resp.headers["location"]).query)["state"][0]
    cb = client.get("/oauth/google/callback", params={"code": "fake-google-code", "state": google_state})
    assert cb.status_code == 403
    assert "not authorized" in cb.text


def test_profile_isolation_and_refresh_rotation(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path, google_email="personal@example.com")
    client_id, tokens = _authorize_and_get_tokens(client, profile="personal")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Personal token works on /mcp/personal
    ok = client.post("/mcp/personal", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert ok.status_code == 200

    # Personal token is strictly rejected on /mcp/work
    cross = client.post("/mcp/work", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert cross.status_code == 403
    assert cross.json()["error"] == "insufficient_scope"

    # Refresh rotates tokens and revokes old refresh token
    refreshed = client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != tokens["access_token"]

    reused = client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]},
    )
    assert reused.status_code == 400


def test_mcp_tools_governance_and_capture(tmp_path: Path) -> None:
    client, personal_kb, _ = _make_client(tmp_path, google_email="personal@example.com")
    _, tokens = _authorize_and_get_tokens(client, profile="personal")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Initialize + notification + tools/list
    init = client.post(
        "/mcp/personal",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
    )
    assert init.status_code == 200
    assert init.headers.get("mcp-session-id")
    assert init.json()["result"]["serverInfo"]["name"] == "eos-kb-personal"

    notif = client.post("/mcp/personal", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notif.status_code == 202

    tools = client.post("/mcp/personal", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"kb_context", "kb_search", "kb_read", "kb_list_projects", "kb_log", "kb_propose", "kb_due_reviews"} <= names

    # kb_context & kb_search hit indexed personal KB
    ctx = client.post(
        "/mcp/personal",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kb_context", "arguments": {"query": "Cloudflare tunnels"}}},
    ).json()["result"]
    assert not ctx["isError"]
    assert "EOS Architecture" in ctx["content"][0]["text"]

    # kb_read blocks path traversal
    traversal = client.post(
        "/mcp/personal",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "kb_read", "arguments": {"path": "../work-kb/00-index.md"}}},
    ).json()["result"]
    assert traversal["isError"]

    # kb_log writes valid Log frontmatter under logs/ and never overwrites
    log1 = client.post(
        "/mcp/personal",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "kb_log",
                "arguments": {
                    "kind": "decision",
                    "title": "Use Cloudflare Tunnel",
                    "body": "Chose Cloudflare Tunnel over Tailscale Funnel.",
                    "project": "eos",
                    "revisit_after": "2026-11-20",
                },
            },
        },
    ).json()["result"]
    assert not log1["isError"]
    log2 = client.post(
        "/mcp/personal",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "kb_log",
                "arguments": {
                    "kind": "decision",
                    "title": "Use Cloudflare Tunnel",
                    "body": "Second note with same title.",
                },
            },
        },
    ).json()["result"]
    assert not log2["isError"]
    assert "-2.md" in log2["content"][0]["text"]

    # kb_due_reviews surfaces the due decision
    due = client.post(
        "/mcp/personal",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "kb_due_reviews", "arguments": {"as_of": "2026-11-27"}}},
    ).json()["result"]
    assert not due["isError"]
    assert "Use Cloudflare Tunnel" in due["content"][0]["text"]

    # kb_propose queues to projects/eos/_pending-kb-updates.md, deduplicates, and leaves stable doc untouched
    stable_before = (personal_kb / "projects/eos/architecture.md").read_text(encoding="utf-8")
    prop1 = client.post(
        "/mcp/personal",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "kb_propose",
                "arguments": {
                    "target_path": "projects/eos/architecture.md",
                    "summary": "Document remote MCP server",
                    "proposed_change": "Add section for /mcp/personal and /mcp/work endpoints.",
                },
            },
        },
    ).json()["result"]
    assert not prop1["isError"]
    assert "projects/eos/_pending-kb-updates.md" in prop1["content"][0]["text"]

    prop2 = client.post(
        "/mcp/personal",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "kb_propose",
                "arguments": {
                    "target_path": "projects/eos/architecture.md",
                    "summary": "Document remote MCP server",
                    "proposed_change": "Add section for /mcp/personal and /mcp/work endpoints.",
                },
            },
        },
    ).json()["result"]
    assert "deduplicated" in prop2["content"][0]["text"]
    assert (personal_kb / "projects/eos/architecture.md").read_text(encoding="utf-8") == stable_before
