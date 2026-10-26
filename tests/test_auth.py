"""Tests for the OAuth authorization server (provider, store, login, HTTP flow)."""
import asyncio
import base64
import hashlib
import re
import secrets
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from pydantic import AnyUrl
from starlette.testclient import TestClient

from mcp.server.auth.provider import AuthorizationParams, RegistrationError, TokenError
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull

from kakao_mcp.auth import enable_auth
from kakao_mcp.auth.config import AuthConfig, hash_password, load_config, save_config, verify_password
from kakao_mcp.auth.login import LoginEndpoint
from kakao_mcp.auth.provider import KakaoClient, KakaoOAuthProvider, redirect_matches
from kakao_mcp.auth.scopes import MANAGE, READ, SEND, guard
from kakao_mcp.auth.store import AuthStore

PASSWORD = "correct horse battery"
CLAUDE_CB = "https://claude.ai/api/mcp/auth_callback"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def cfg(tmp_path):
    return AuthConfig(
        public_url="http://localhost",
        owner_password_scrypt=hash_password(PASSWORD),
        owner_totp_secret=pyotp.random_base32(),
        db_path=str(tmp_path / "auth.db"),
    )


@pytest.fixture
def provider(cfg):
    return KakaoOAuthProvider(cfg, AuthStore(cfg.db_path))


def _client(redirects=(CLAUDE_CB,)):
    return OAuthClientInformationFull(
        client_id=secrets.token_hex(8), redirect_uris=[AnyUrl(u) for u in redirects],
        token_endpoint_auth_method="none", grant_types=["authorization_code", "refresh_token"],
        response_types=["code"], client_name="Claude",
    )


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _issue_code(provider, client, scopes):
    _, challenge = _pkce()
    return provider.store.create_code(client.client_id, scopes, challenge, CLAUDE_CB, True, None)


# ---------------------------------------------------------------------------
# Config / password
# ---------------------------------------------------------------------------

class TestConfig:
    def test_password_roundtrip(self):
        stored = hash_password(PASSWORD)
        assert verify_password(PASSWORD, stored)
        assert not verify_password("wrong", stored)
        assert not verify_password(PASSWORD, "garbage")

    def test_save_and_load(self, cfg, tmp_path):
        path = tmp_path / "auth.toml"
        cfg.trusted_proxies = ["192.168.0.10"]
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.public_url == cfg.public_url
        assert loaded.trusted_proxies == ["192.168.0.10"]
        assert loaded.resource_url == "http://localhost/mcp"

    def test_incomplete_config_fails_closed(self, tmp_path):
        path = tmp_path / "auth.toml"
        path.write_text('public_url = "https://x.example"\n', encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(path)

    def test_missing_config_is_none(self, tmp_path):
        assert load_config(tmp_path / "nope.toml") is None


# ---------------------------------------------------------------------------
# Redirect URIs / registration
# ---------------------------------------------------------------------------

class TestRedirects:
    def test_loopback_any_port(self):
        assert redirect_matches("http://localhost/callback", "http://localhost:51234/callback")
        assert redirect_matches("http://127.0.0.1:1/callback", "http://127.0.0.1:9/callback")

    def test_loopback_host_and_path_must_match(self):
        assert not redirect_matches("http://localhost/callback", "http://127.0.0.1:5/callback")
        assert not redirect_matches("http://localhost/callback", "http://localhost:5/other")

    def test_non_loopback_exact_only(self):
        assert not redirect_matches(CLAUDE_CB, CLAUDE_CB + "x")
        assert not redirect_matches("https://localhost/callback", "https://localhost:5/callback")

    def test_kakao_client_validates_loopback_port(self):
        client = KakaoClient.model_validate(_client(["http://localhost/callback"]).model_dump())
        assert client.validate_redirect_uri(AnyUrl("http://localhost:4321/callback"))
        with pytest.raises(InvalidRedirectUriError):
            client.validate_redirect_uri(AnyUrl("https://evil.example/cb"))

    def test_register_rejects_foreign_redirect(self, provider):
        with pytest.raises(RegistrationError):
            run(provider.register_client(_client(["https://evil.example/callback"])))

    def test_register_claude_gets_all_scopes(self, provider):
        client = _client([CLAUDE_CB, "http://127.0.0.1/callback"])
        client.scope = READ
        run(provider.register_client(client))
        stored = run(provider.get_client(client.client_id))
        assert isinstance(stored, KakaoClient)
        assert set(stored.scope.split()) == {READ, SEND, MANAGE, "offline_access"}


# ---------------------------------------------------------------------------
# Codes and tokens
# ---------------------------------------------------------------------------

class TestTokens:
    def _registered(self, provider):
        client = _client()
        run(provider.register_client(client))
        return client

    def test_authorize_goes_to_login(self, provider):
        client = self._registered(provider)
        _, challenge = _pkce()
        url = run(provider.authorize(client, AuthorizationParams(
            state="s", scopes=[READ], code_challenge=challenge, redirect_uri=AnyUrl(CLAUDE_CB),
            redirect_uri_provided_explicitly=True, resource="http://localhost/mcp")))
        req = parse_qs(urlsplit(url).query)["req"][0]
        assert url.startswith("http://localhost/login?")
        assert provider.store.get_pending(req)["state"] == "s"

    def test_authorize_rejects_other_resource(self, provider):
        client = self._registered(provider)
        with pytest.raises(Exception):
            run(provider.authorize(client, AuthorizationParams(
                state=None, scopes=None, code_challenge="x", redirect_uri=AnyUrl(CLAUDE_CB),
                redirect_uri_provided_explicitly=True, resource="https://other.example/mcp")))

    def test_code_exchange_and_replay(self, provider):
        client = self._registered(provider)
        code = _issue_code(provider, client, [READ, SEND])
        loaded = run(provider.load_authorization_code(client, code))
        tokens = run(provider.exchange_authorization_code(client, loaded))
        assert tokens.scope == f"{READ} {SEND}"
        access = run(provider.load_access_token(tokens.access_token))
        assert access.scopes == [READ, SEND] and access.resource == "http://localhost/mcp"

        # Replaying the code fails and revokes what it issued
        assert run(provider.load_authorization_code(client, code)) is None
        assert run(provider.load_access_token(tokens.access_token)) is None
        with pytest.raises(TokenError):
            run(provider.exchange_authorization_code(client, loaded))

    def test_code_bound_to_client(self, provider):
        client, other = self._registered(provider), self._registered(provider)
        code = _issue_code(provider, client, [READ])
        assert run(provider.load_authorization_code(other, code)) is None

    def test_refresh_rotation_and_reuse_detection(self, provider):
        client = self._registered(provider)
        code = _issue_code(provider, client, [READ])
        first = run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))

        rt = run(provider.load_refresh_token(client, first.refresh_token))
        second = run(provider.exchange_refresh_token(client, rt, rt.scopes))
        assert second.refresh_token != first.refresh_token
        assert run(provider.load_access_token(second.access_token))

        # Old refresh token reused -> whole family revoked
        assert run(provider.load_refresh_token(client, first.refresh_token)) is None
        assert run(provider.load_access_token(second.access_token)) is None
        assert run(provider.load_refresh_token(client, second.refresh_token)) is None

    def test_access_token_expiry(self, provider, cfg):
        cfg.access_token_ttl = -1
        client = self._registered(provider)
        code = _issue_code(provider, client, [READ])
        tokens = run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))
        assert run(provider.load_access_token(tokens.access_token)) is None

    def test_revoke_via_refresh_revokes_family(self, provider):
        client = self._registered(provider)
        code = _issue_code(provider, client, [READ])
        tokens = run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))
        run(provider.revoke_token(run(provider.load_refresh_token(client, tokens.refresh_token))))
        assert run(provider.load_access_token(tokens.access_token)) is None

    def test_pat(self, provider):
        pat = provider.store.create_pat("main-pc", [READ, SEND])
        token = run(provider.load_access_token(pat))
        assert token.client_id == "pat:main-pc" and token.expires_at is None
        with pytest.raises(ValueError):
            provider.store.create_pat("main-pc", [READ])
        assert provider.store.revoke_pat("main-pc")
        assert run(provider.load_access_token(pat)) is None

    def test_revoke_everything(self, provider):
        client = self._registered(provider)
        pat = provider.store.create_pat("x", [READ])
        provider.store.revoke_everything()
        assert run(provider.load_access_token(pat)) is None
        assert run(provider.get_client(client.client_id)) is None


# ---------------------------------------------------------------------------
# TOTP / guard
# ---------------------------------------------------------------------------

class TestTotpAndGuard:
    def test_totp_replay_rejected(self, cfg):
        login = LoginEndpoint(cfg, AuthStore(cfg.db_path))
        code = pyotp.TOTP(cfg.owner_totp_secret).now()
        assert login._check_totp(code)
        assert not login._check_totp(code)
        assert not login._check_totp("12345")

    def test_guard_denies_missing_scope(self):
        @guard(MANAGE)
        def tool(room_name):
            return {"ok": room_name}

        class Tok:
            client_id, scopes = "c", [READ]

        with patch("kakao_mcp.auth.scopes.get_access_token", return_value=Tok()):
            assert tool(room_name="r") == {"error": "insufficient_scope: kakao.manage"}
        Tok.scopes = [READ, MANAGE]
        with patch("kakao_mcp.auth.scopes.get_access_token", return_value=Tok()):
            assert tool(room_name="r") == {"ok": "r"}
        assert tool(room_name="r") == {"ok": "r"}  # no auth (stdio) -> allowed


# ---------------------------------------------------------------------------
# End-to-end over HTTP
# ---------------------------------------------------------------------------

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


@pytest.fixture
def http(cfg):
    mcp = FastMCP("test")

    @mcp.tool()
    @guard(READ)
    def ping() -> dict:
        return {"pong": True}

    enable_auth(mcp, cfg)
    with TestClient(mcp.streamable_http_app(), base_url="http://localhost") as client:
        yield client


def _login_flow(http, cfg, approve_scopes=(SEND,), password=PASSWORD):
    reg = http.post("/register", json={
        "client_name": "Claude", "redirect_uris": [CLAUDE_CB], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]
    verifier, challenge = _pkce()
    r = http.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CB, "state": "st",
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": "kakao.read offline_access",
        "resource": "http://localhost/mcp"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    page = http.get(r.headers["location"])
    assert page.status_code == 200 and "KakaoTalk MCP" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    req = re.search(r'name="req" value="([^"]+)"', page.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    resp = http.post("/login", data={
        "req": req, "csrf": csrf, "password": password, "totp": pyotp.TOTP(cfg.owner_totp_secret).now(),
        "scope": list(approve_scopes), "action": "approve"}, follow_redirects=False)
    return client_id, verifier, resp


class TestHttpFlow:
    def test_discovery_and_401(self, http):
        r = http.post("/mcp", json=INIT, headers=MCP_HEADERS)
        assert r.status_code == 401
        assert 'resource_metadata="http://localhost/.well-known/oauth-protected-resource/mcp"' in \
            r.headers["www-authenticate"]
        prm = http.get("/.well-known/oauth-protected-resource/mcp").json()
        assert prm["resource"] == "http://localhost/mcp"
        assert prm["authorization_servers"] == ["http://localhost/"]
        asm = http.get("/.well-known/oauth-authorization-server").json()
        assert asm["code_challenge_methods_supported"] == ["S256"]
        assert "offline_access" in asm["scopes_supported"] and asm["registration_endpoint"]

    def test_full_flow(self, http, cfg):
        client_id, verifier, resp = _login_flow(http, cfg)
        assert resp.status_code == 302
        loc = urlsplit(resp.headers["location"])
        q = parse_qs(loc.query)
        assert f"{loc.scheme}://{loc.netloc}{loc.path}" == CLAUDE_CB and q["state"] == ["st"]

        tok = http.post("/token", data={
            "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": CLAUDE_CB,
            "client_id": client_id, "code_verifier": verifier, "resource": "http://localhost/mcp"})
        assert tok.status_code == 200, tok.text
        body = tok.json()
        assert set(body["scope"].split()) == {READ, SEND, "offline_access"}

        auth = {**MCP_HEADERS, "Authorization": f"Bearer {body['access_token']}"}
        r = http.post("/mcp", json=INIT, headers=auth)
        assert r.status_code == 200, r.text

        ref = http.post("/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"],
                                        "client_id": client_id})
        assert ref.status_code == 200 and ref.json()["refresh_token"] != body["refresh_token"]
        again = http.post("/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"],
                                          "client_id": client_id})
        assert again.status_code == 400 and again.json()["error"] == "invalid_grant"

    def test_wrong_password_and_lockout(self, http, cfg):
        for _ in range(5):
            _, _, resp = _login_flow(http, cfg, password="nope")
            assert resp.status_code == 401
        _, _, resp = _login_flow(http, cfg)
        assert resp.status_code == 429

    def test_csrf_required(self, http, cfg):
        reg = http.post("/register", json={"redirect_uris": [CLAUDE_CB], "token_endpoint_auth_method": "none",
                                           "grant_types": ["authorization_code", "refresh_token"],
                                           "response_types": ["code"]})
        _, challenge = _pkce()
        r = http.get("/authorize", params={
            "response_type": "code", "client_id": reg.json()["client_id"], "redirect_uri": CLAUDE_CB,
            "code_challenge": challenge, "code_challenge_method": "S256"}, follow_redirects=False)
        req = parse_qs(urlsplit(r.headers["location"]).query)["req"][0]
        http.cookies.clear()
        resp = http.post("/login", data={"req": req, "csrf": "forged", "password": PASSWORD,
                                         "totp": "000000", "action": "approve"})
        assert resp.status_code == 400

    def test_register_rejects_foreign_redirect(self, http):
        r = http.post("/register", json={"redirect_uris": ["https://evil.example/cb"],
                                         "token_endpoint_auth_method": "none",
                                         "grant_types": ["authorization_code", "refresh_token"],
                                         "response_types": ["code"]})
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"

    def test_pat_works_on_mcp(self, http, cfg):
        pat = AuthStore(cfg.db_path).create_pat("cli", [READ])
        r = http.post("/mcp", json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {pat}"})
        assert r.status_code == 200

    def test_healthz_open(self, http):
        assert http.get("/healthz").text == "ok"
