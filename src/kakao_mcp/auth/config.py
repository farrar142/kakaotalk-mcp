"""Auth configuration (auth.toml) and owner password hashing."""
import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

DATA_DIR = Path(
    os.environ.get("KAKAO_MCP_DATA_DIR")
    or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "kakaotalk-mcp"
)
CONFIG_PATH = Path(os.environ.get("KAKAO_MCP_AUTH_CONFIG") or DATA_DIR / "auth.toml")

REQUIRED_KEYS = ("public_url", "owner_password_scrypt", "owner_totp_secret")


@dataclass
class AuthConfig:
    public_url: str  # e.g. https://kakao-mcp.example.com (issuer; MCP is at /mcp)
    owner_password_scrypt: str
    owner_totp_secret: str
    trusted_proxies: List[str] = field(default_factory=list)  # NPM host IP(s)
    extra_hosts: List[str] = field(default_factory=list)  # other Host values, e.g. "192.168.1.20:*"
    extra_redirect_uris: List[str] = field(default_factory=list)
    access_token_ttl: int = 3600
    refresh_token_ttl: int = 30 * 86400
    refresh_token_max_age: int = 90 * 86400
    db_path: str = ""

    def __post_init__(self):
        self.public_url = self.public_url.rstrip("/")

    @property
    def resource_url(self) -> str:
        return self.public_url + "/mcp"

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


def load_config(path: Path = CONFIG_PATH) -> Optional[AuthConfig]:
    """Load auth.toml. Returns None if it doesn't exist; raises if it's incomplete
    (fail closed: a half-written config must not silently disable auth)."""
    path = Path(path)
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if not data.get(k)]
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)} (run `kakaotalk-mcp auth init`)")
    known = AuthConfig.__dataclass_fields__
    cfg = AuthConfig(**{k: v for k, v in data.items() if k in known})
    if not cfg.db_path:
        cfg.db_path = str(path.parent / "auth.db")
    return cfg


def save_config(cfg: AuthConfig, path: Path = CONFIG_PATH):
    """Write auth.toml (flat keys; JSON string/list syntax is valid TOML here)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in asdict(cfg).items():
        if key == "db_path" and value == str(path.parent / "auth.db"):
            continue
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Owner password (scrypt)
# ---------------------------------------------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(_unb64(digest)))
        return hmac.compare_digest(actual, _unb64(digest))
    except (ValueError, TypeError):
        return False
