"""OAuth 2.1 authorization server provider for the MCP SDK.

The SDK serves the standard endpoints (metadata, /register, /authorize,
/token, /revoke) and checks PKCE, code expiry and redirect consistency; this
provider stores state and adds the policy:

- DCR is open (Claude registers on every new connection) but redirect URIs
  must be Claude's callbacks or a loopback ``/callback`` (any port).
- /authorize hands off to the owner login page (login.py) instead of issuing
  a code directly.
- Codes are single-use; replaying a used code revokes what it issued.
- Refresh tokens rotate; replaying a rotated one revokes the whole family.
"""
import logging
import time
import uuid
from typing import List, Optional
from urllib.parse import urlsplit

from pydantic import AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken

from .config import AuthConfig
from .scopes import VALID_SCOPES
from .store import PAT_PREFIX, AuthStore

log = logging.getLogger(__name__)

CLAUDE_CALLBACKS = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
]
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")
LOOPBACK_PATH = "/callback"
OWNER = "owner"


def is_loopback(uri: str) -> bool:
    parts = urlsplit(uri)
    host = (parts.hostname or "").lower()
    return parts.scheme == "http" and (host in LOOPBACK_HOSTS or host == "::1")


def redirect_matches(registered: str, actual: str) -> bool:
    """Exact match, or the same loopback host/path with any port (RFC 8252 §7.3)."""
    if registered == actual:
        return True
    if is_loopback(registered) and is_loopback(actual):
        r, a = urlsplit(registered), urlsplit(actual)
        return (r.hostname, r.path, r.query) == (a.hostname, a.path, a.query)
    return False


class KakaoClient(OAuthClientInformationFull):
    """Client whose loopback redirect URIs match regardless of port."""

    def validate_redirect_uri(self, redirect_uri: Optional[AnyUrl]) -> AnyUrl:
        if redirect_uri is not None and self.redirect_uris:
            if any(redirect_matches(str(r), str(redirect_uri)) for r in self.redirect_uris):
                return redirect_uri
            raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
        return super().validate_redirect_uri(redirect_uri)


class KakaoRefreshToken(RefreshToken):
    family_id: str
    family_expires_at: float


class KakaoAccessToken(AccessToken):
    family_id: Optional[str] = None
    kind: str = "oauth"


class KakaoOAuthProvider:
    def __init__(self, cfg: AuthConfig, store: AuthStore):
        self.cfg = cfg
        self.store = store

    # -- clients ------------------------------------------------------------

    def redirect_allowed(self, uri: str) -> bool:
        if uri in CLAUDE_CALLBACKS or uri in self.cfg.extra_redirect_uris:
            return True
        return is_loopback(uri) and urlsplit(uri).path == LOOPBACK_PATH

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        info = self.store.get_client(client_id)
        return KakaoClient.model_validate(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        bad = [u for u in uris if not self.redirect_allowed(u)]
        if not uris or bad:
            raise RegistrationError("invalid_redirect_uri", f"Redirect URI not allowed: {', '.join(bad) or '(none)'}")
        # Single-owner server: what a client may get is decided on the consent page,
        # so every client is registered for all scopes.
        client_info.scope = " ".join(VALID_SCOPES)
        self.store.save_client(client_info.client_id, client_info.model_dump(mode="json", exclude_none=True))
        log.info("registered client %s (%s) redirect=%s", client_info.client_id, client_info.client_name, uris)

    # -- authorization ------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") != self.cfg.resource_url:
            raise AuthorizeError("invalid_request", f"Unknown resource '{params.resource}'")
        pending_id = self.store.create_pending(client.client_id, {
            "state": params.state,
            "scopes": params.scopes or [],
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_explicit": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        })
        return f"{self.cfg.public_url}/login?req={pending_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> Optional[AuthorizationCode]:
        row = self.store.get_code(authorization_code)
        if not row or row["client_id"] != client.client_id:
            return None
        if row["used"]:
            # RFC 6749 §4.1.2: a replayed code should revoke tokens issued from it
            log.warning("authorization code replay for client %s; revoking family", client.client_id)
            if row["family_id"]:
                self.store.revoke_family(row["family_id"])
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=row["scopes"].split(),
            expires_at=row["expires_at"],
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=AnyUrl(row["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(row["redirect_explicit"]),
            resource=row["resource"],
            subject=OWNER,
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        family_id = uuid.uuid4().hex
        if not self.store.consume_code(authorization_code.code, family_id):
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes, family_id=family_id)

    # -- refresh ------------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> Optional[KakaoRefreshToken]:
        row = self.store.get_refresh(refresh_token)
        if not row or row["client_id"] != client.client_id:
            return None
        if row["status"] == "rotated":
            log.warning("refresh token reuse for client %s; revoking family %s", client.client_id, row["family_id"])
            self.store.revoke_family(row["family_id"])
            return None
        if row["status"] != "active" or row["family_expires_at"] < time.time():
            return None
        return KakaoRefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=row["scopes"].split(),
            expires_at=int(row["expires_at"]),
            resource=self.cfg.resource_url,
            subject=OWNER,
            family_id=row["family_id"],
            family_expires_at=row["family_expires_at"],
        )

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: KakaoRefreshToken,
                                     scopes: List[str]) -> OAuthToken:
        if not self.store.rotate_refresh(refresh_token.token):
            raise TokenError("invalid_grant", "refresh token is no longer valid")
        return self._issue(client.client_id, scopes, family_id=refresh_token.family_id,
                           family_expires_at=refresh_token.family_expires_at)

    def _issue(self, client_id: str, scopes: List[str], family_id: str,
               family_expires_at: Optional[float] = None) -> OAuthToken:
        access, refresh, _ = self.store.issue_tokens(
            client_id, scopes, self.cfg.access_token_ttl, self.cfg.refresh_token_ttl,
            family_id=family_id, family_expires_at=family_expires_at, max_age=self.cfg.refresh_token_max_age,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self.cfg.access_token_ttl,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    # -- access tokens ------------------------------------------------------

    async def load_access_token(self, token: str) -> Optional[KakaoAccessToken]:
        row = self.store.get_access(token)
        if not row:
            return None
        return KakaoAccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=row["scopes"].split(),
            expires_at=int(row["expires_at"]) if row["expires_at"] else None,
            resource=self.cfg.resource_url,  # every token here is issued for this server's /mcp
            subject=OWNER,
            family_id=row["family_id"],
            kind=row["kind"],
        )

    async def revoke_token(self, token) -> None:
        family_id = getattr(token, "family_id", None)
        if family_id:
            self.store.revoke_family(family_id)
        elif isinstance(token, AccessToken) and token.token.startswith(PAT_PREFIX):
            pass  # PATs are revoked by name with the CLI, not through /revoke
        else:
            self.store.revoke_access(token.token)
