"""`kakaotalk-mcp auth ...` / `kakaotalk-mcp token ...` management commands."""
import argparse
import getpass
import sys
import time
from pathlib import Path

import pyotp

from .config import CONFIG_PATH, AuthConfig, hash_password, load_config, save_config
from .scopes import TOOL_SCOPES
from .store import AuthStore


def _read_password(args) -> str:
    if args.password_stdin:
        pw = sys.stdin.readline().rstrip("\r\n")
    else:
        pw = getpass.getpass("Owner password: ")
        if getpass.getpass("Repeat: ") != pw:
            sys.exit("Passwords do not match")
    if len(pw) < 12:
        sys.exit("Use at least 12 characters")
    return pw


def _require_config(path: Path) -> AuthConfig:
    cfg = load_config(path)
    if cfg is None:
        sys.exit(f"{path} not found; run `kakaotalk-mcp auth init` first")
    return cfg


def cmd_auth_init(args):
    path = Path(args.config)
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists (use --force to overwrite)")
    secret = pyotp.random_base32()
    cfg = AuthConfig(
        public_url=args.public_url,
        owner_password_scrypt=hash_password(_read_password(args)),
        owner_totp_secret=secret,
        trusted_proxies=args.trusted_proxy or [],
        extra_hosts=args.extra_host or [],
    )
    save_config(cfg, path)
    uri = pyotp.TOTP(secret).provisioning_uri(name="owner", issuer_name="KakaoTalk MCP")
    print(f"Wrote {path}")
    print("Add this to your authenticator app (secret or otpauth URI):")
    print(f"  secret: {secret}")
    print(f"  uri:    {uri}")


def cmd_auth_set(args):
    path = Path(args.config)
    cfg = _require_config(path)
    if args.what == "password":
        cfg.owner_password_scrypt = hash_password(_read_password(args))
        print("Password updated")
    elif args.what == "totp":
        cfg.owner_totp_secret = pyotp.random_base32()
        uri = pyotp.TOTP(cfg.owner_totp_secret).provisioning_uri(name="owner", issuer_name="KakaoTalk MCP")
        print(f"New TOTP secret: {cfg.owner_totp_secret}\n  uri: {uri}")
    elif args.what == "public-url":
        cfg.public_url = args.value.rstrip("/")
        print(f"public_url = {cfg.public_url}")
    save_config(cfg, path)
    print("Restart the server to apply.")


def _parse_scopes(text: str):
    scopes = [s.strip() for s in text.split(",") if s.strip()]
    bad = [s for s in scopes if s not in TOOL_SCOPES]
    if bad:
        sys.exit(f"Unknown scope(s): {bad}; choose from {TOOL_SCOPES}")
    if "kakao.read" not in scopes:
        scopes.insert(0, "kakao.read")
    return scopes


def cmd_token(args):
    cfg = _require_config(Path(args.config))
    store = AuthStore(cfg.db_path)
    if args.action == "create":
        token = store.create_pat(args.name, _parse_scopes(args.scopes))
        print(token)
        print("Shown once. Use it as: Authorization: Bearer <token>", file=sys.stderr)
    elif args.action == "list":
        for row in store.list_pats():
            created = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["created_at"]))
            print(f"{row['name']}\t{row['scopes']}\t{created}")
    elif args.action == "revoke":
        if args.all:
            store.revoke_everything()
            print("Revoked every token and forgot all OAuth clients")
        elif args.name:
            print("Revoked" if store.revoke_pat(args.name) else f"No active token named '{args.name}'")
        else:
            sys.exit("Give a token name or --all")


def main(argv):
    ap = argparse.ArgumentParser(prog="kakaotalk-mcp")
    ap.add_argument("--config", default=str(CONFIG_PATH), help=f"auth.toml path (default {CONFIG_PATH})")
    sub = ap.add_subparsers(dest="group", required=True)

    auth = sub.add_parser("auth", help="owner login settings")
    auth_sub = auth.add_subparsers(dest="cmd", required=True)
    init = auth_sub.add_parser("init", help="create auth.toml (password + TOTP)")
    init.add_argument("--public-url", required=True, help="e.g. https://kakao-mcp.example.com")
    init.add_argument("--trusted-proxy", action="append", help="reverse proxy IP (repeatable)")
    init.add_argument("--extra-host", action="append", help="extra allowed Host header, e.g. 192.168.1.20:*")
    init.add_argument("--password-stdin", action="store_true")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_auth_init)
    for what in ("password", "totp", "public-url"):
        p = auth_sub.add_parser(f"set-{what}")
        if what == "public-url":
            p.add_argument("value")
        p.add_argument("--password-stdin", action="store_true")
        p.set_defaults(func=cmd_auth_set, what=what)

    token = sub.add_parser("token", help="personal access tokens")
    tok_sub = token.add_subparsers(dest="action", required=True)
    create = tok_sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--scopes", default="kakao.read", help="comma separated: " + ",".join(TOOL_SCOPES))
    tok_sub.add_parser("list")
    revoke = tok_sub.add_parser("revoke")
    revoke.add_argument("name", nargs="?")
    revoke.add_argument("--all", action="store_true", help="revoke every token and OAuth client")
    token.set_defaults(func=cmd_token)

    args = ap.parse_args(argv)
    args.func(args)
