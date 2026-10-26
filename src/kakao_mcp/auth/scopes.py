"""OAuth scopes and the per-tool guard (scope check + audit log)."""
import functools
import logging
import time
from logging.handlers import RotatingFileHandler

from mcp.server.auth.middleware.auth_context import get_access_token

READ = "kakao.read"
SEND = "kakao.send"
MANAGE = "kakao.manage"
OFFLINE = "offline_access"

TOOL_SCOPES = [READ, SEND, MANAGE]
VALID_SCOPES = TOOL_SCOPES + [OFFLINE]

SCOPE_LABELS = {
    READ: "읽기 — 실행 상태, 채팅방 목록, 메시지 읽기, 오픈채팅 검색, 링크",
    SEND: "보내기 — 메시지/이미지/멘션 전송, 채팅방 열기, 모니터링",
    MANAGE: "방 관리 — 오픈채팅 참여, 만들기, 나가기",
}

_audit = logging.getLogger("kakao_mcp.audit")
_audit.propagate = False


def setup_audit_log(path: str):
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit.addHandler(handler)
    _audit.setLevel(logging.INFO)


def guard(scope: str):
    """Require ``scope`` on the caller's token (when auth is on) and audit the call.

    Without auth (stdio / LAN mode) there is no token and the call is allowed.
    Only the tool name and room-ish arguments are logged, never message bodies.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            token = get_access_token()
            client = token.client_id if token else "-"
            target = kwargs.get("room_name") or kwargs.get("query") or kwargs.get("name") or ""
            if token is not None and scope not in token.scopes:
                _audit.info(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} DENY {client} {fn.__name__} {target}")
                return {"error": f"insufficient_scope: {scope}"}
            _audit.info(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} CALL {client} {fn.__name__} {target}")
            return fn(*args, **kwargs)
        return wrapper
    return deco
