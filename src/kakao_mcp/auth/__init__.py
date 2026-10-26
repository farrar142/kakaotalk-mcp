"""OAuth 2.1 for remote (connector) access. See docs/remote-auth.md."""
from pathlib import Path
from urllib.parse import urlsplit

from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from .config import AuthConfig, load_config
from .login import LoginEndpoint
from .provider import KakaoOAuthProvider
from .scopes import READ, VALID_SCOPES, guard, setup_audit_log
from .store import AuthStore

__all__ = ["AuthConfig", "load_config", "enable_auth", "guard"]


def enable_auth(app, cfg: AuthConfig) -> KakaoOAuthProvider:
    """Turn on OAuth for a FastMCP app built without auth.

    FastMCP normally takes ``auth``/``auth_server_provider`` in its constructor;
    the tools in server.py are registered on a module-level app, so auth is
    decided at startup and wired the same way the constructor does it.
    """
    store = AuthStore(cfg.db_path)
    store.purge_expired()
    provider = KakaoOAuthProvider(cfg, store)
    setup_audit_log(str(Path(cfg.db_path).with_name("audit.log")))

    app.settings.auth = AuthSettings(
        issuer_url=cfg.public_url,
        resource_server_url=cfg.resource_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=VALID_SCOPES, default_scopes=VALID_SCOPES,
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[READ],
        validate_token_resource=True,
    )
    app._auth_server_provider = provider
    app._token_verifier = ProviderTokenVerifier(provider)

    public_host = urlsplit(cfg.public_url).netloc
    app.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, *cfg.extra_hosts],
        allowed_origins=[cfg.public_url, "https://claude.ai", "https://claude.com"],
    )

    login = LoginEndpoint(cfg, store)

    @app.custom_route("/login", methods=["GET", "POST"])
    async def login_route(request: Request):
        return await (login.post(request) if request.method == "POST" else login.get(request))

    @app.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request):
        return PlainTextResponse("ok")

    return provider
