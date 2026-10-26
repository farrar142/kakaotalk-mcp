"""Owner login + consent page (/login), the step between /authorize and the code.

One form: owner password + TOTP, the scopes to grant, approve/deny.
Protections: CSRF double-submit cookie, failure throttling (per IP and global),
TOTP replay prevention, no-store/CSP/frame-deny headers.
"""
import html
import secrets
import time
from typing import List, Optional
from urllib.parse import urlsplit

import pyotp
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import construct_redirect_uri

from .config import AuthConfig, verify_password
from .provider import is_loopback
from .scopes import MANAGE, OFFLINE, READ, SCOPE_LABELS, SEND, TOOL_SCOPES
from .store import AuthStore

CSRF_COOKIE = "kmcp_csrf"
FAIL_WINDOW = 15 * 60
MAX_FAILS_PER_IP = 5
MAX_FAILS_GLOBAL = 20

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https: http://localhost:* http://127.0.0.1:*; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KakaoTalk MCP 접근 승인</title>
<style>
body{{font-family:system-ui,-apple-system,"Malgun Gothic",sans-serif;background:#f5f5f5;margin:0;padding:24px 16px;color:#191919}}
main{{max-width:420px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
h1{{font-size:20px;margin:0 0 16px}} .client{{background:#fafafa;border-radius:8px;padding:12px;margin-bottom:16px;line-height:1.6}}
.warn{{background:#fff4e5;color:#8a4b00;border-radius:8px;padding:10px 12px;margin-bottom:16px;font-size:14px}}
.err{{background:#fdecea;color:#a1000f;border-radius:8px;padding:10px 12px;margin-bottom:16px}}
label{{display:block;margin:10px 0 4px;font-weight:600}} input[type=password],input[type=text]{{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:16px}}
fieldset{{border:1px solid #e5e5e5;border-radius:8px;margin:16px 0;padding:8px 12px}} fieldset label{{font-weight:400;display:flex;gap:8px;align-items:flex-start}}
.buttons{{display:flex;gap:8px;margin-top:16px}} button{{flex:1;padding:12px;border:0;border-radius:8px;font-size:16px;cursor:pointer}}
.approve{{background:#fee500;color:#191919;font-weight:700}} .deny{{background:#eee}}
</style></head><body><main>
<h1>KakaoTalk MCP 접근 승인</h1>
{error}
<div class="client"><b>{client_name}</b>이(가) 카카오톡 제어 권한을 요청합니다.<br>
돌아갈 주소: <b>{redirect_host}</b></div>
{warning}
<form method="post" action="/login">
<input type="hidden" name="req" value="{req}"><input type="hidden" name="csrf" value="{csrf}">
<label for="pw">소유자 비밀번호</label><input id="pw" type="password" name="password" autocomplete="current-password" autofocus>
<label for="otp">인증 앱 6자리 코드</label><input id="otp" type="text" name="totp" inputmode="numeric" autocomplete="one-time-code" maxlength="6">
<fieldset><legend>허용할 권한</legend>{scopes}</fieldset>
<div class="buttons"><button class="deny" name="action" value="deny">거부</button>
<button class="approve" name="action" value="approve">승인</button></div>
</form></main></body></html>"""


def _page(status: int, body: str) -> HTMLResponse:
    return HTMLResponse(body, status_code=status, headers=SECURITY_HEADERS)


def _message(status: int, text: str) -> HTMLResponse:
    return _page(status, f"<!doctype html><meta charset=utf-8><title>KakaoTalk MCP</title>"
                         f"<p style='font-family:sans-serif;padding:24px'>{html.escape(text)}</p>")


class LoginEndpoint:
    def __init__(self, cfg: AuthConfig, store: AuthStore):
        self.cfg = cfg
        self.store = store

    # -- rendering ----------------------------------------------------------

    async def _render(self, request: Request, pending: dict, req: str, error: str = "",
                      status: int = 200) -> Response:
        client = self.store.get_client(pending["client_id"]) or {}
        redirect = pending["redirect_uri"]
        loopback = is_loopback(redirect)
        warning = ("<div class='warn'>이 요청은 이 컴퓨터의 로컬 앱(예: Claude Code)으로 돌아갑니다. "
                   "직접 시작한 연결이 아니라면 거부하세요.</div>") if loopback else ""
        boxes = []
        for scope in TOOL_SCOPES:
            fixed = scope == READ
            boxes.append(
                f"<label><input type='checkbox' name='scope' value='{scope}' checked"
                f"{' disabled' if fixed else ''}>{html.escape(SCOPE_LABELS[scope])}"
                f"{' (필수)' if fixed else ''}</label>")
        csrf = secrets.token_urlsafe(24)
        body = PAGE.format(
            error=f"<div class='err'>{html.escape(error)}</div>" if error else "",
            client_name=html.escape(client.get("client_name") or "이름 없는 앱"),
            redirect_host=html.escape(urlsplit(redirect).netloc),
            warning=warning,
            req=html.escape(req),
            csrf=csrf,
            scopes="".join(boxes),
        )
        resp = _page(status, body)
        resp.set_cookie(CSRF_COOKIE, csrf, max_age=600, path="/login", httponly=True,
                        secure=self.cfg.secure_cookies, samesite="strict")
        return resp

    # -- handlers -----------------------------------------------------------

    async def get(self, request: Request) -> Response:
        req = request.query_params.get("req", "")
        pending = self.store.get_pending(req)
        if not pending:
            return _message(400, "만료되었거나 잘못된 요청입니다. 앱에서 연결을 다시 시작하세요.")
        return await self._render(request, pending, req)

    async def post(self, request: Request) -> Response:
        form = await request.form()
        req = str(form.get("req", ""))
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not secrets.compare_digest(cookie, str(form.get("csrf", ""))):
            return _message(400, "보안 토큰이 맞지 않습니다. 페이지를 새로 고친 뒤 다시 시도하세요.")
        pending = self.store.get_pending(req)
        if not pending:
            return _message(400, "만료되었거나 잘못된 요청입니다. 앱에서 연결을 다시 시작하세요.")

        if form.get("action") != "approve":
            self.store.delete_pending(req)
            return self._redirect(pending, error="access_denied")

        ip = request.client.host if request.client else "unknown"
        since = time.time() - FAIL_WINDOW
        if (self.store.login_failures_since(f"ip:{ip}", since) >= MAX_FAILS_PER_IP
                or self.store.login_failures_since("global", since) >= MAX_FAILS_GLOBAL):
            return await self._render(request, pending, req, "로그인 시도가 너무 많습니다. 15분 뒤 다시 시도하세요.", 429)

        password = str(form.get("password", ""))
        totp_code = str(form.get("totp", "")).strip().replace(" ", "")
        if not (verify_password(password, self.cfg.owner_password_scrypt) and self._check_totp(totp_code)):
            self.store.record_login_failure(f"ip:{ip}")
            self.store.record_login_failure("global")
            return await self._render(request, pending, req, "비밀번호 또는 인증 코드가 올바르지 않습니다.", 401)

        granted: List[str] = [READ] + [s for s in (SEND, MANAGE) if s in form.getlist("scope")]
        granted.append(OFFLINE)  # always issue a refresh token
        code = self.store.create_code(
            pending["client_id"], granted, pending["code_challenge"], pending["redirect_uri"],
            pending["redirect_explicit"], pending.get("resource"),
        )
        self.store.delete_pending(req)
        return self._redirect(pending, code=code)

    # -- helpers ------------------------------------------------------------

    def _check_totp(self, code: str) -> bool:
        """Verify a TOTP code (±1 step) and refuse reuse of the same or an older step."""
        if not (code.isdigit() and len(code) == 6):
            return False
        totp = pyotp.TOTP(self.cfg.owner_totp_secret)
        now = time.time()
        last = int(self.store.get_meta("totp_last_step") or 0)
        for offset in (-1, 0, 1):
            step = int(now // totp.interval) + offset
            if step > last and secrets.compare_digest(totp.at(step * totp.interval), code):
                self.store.set_meta("totp_last_step", str(step))
                return True
        return False

    @staticmethod
    def _redirect(pending: dict, code: Optional[str] = None, error: Optional[str] = None) -> Response:
        url = construct_redirect_uri(pending["redirect_uri"], code=code, error=error, state=pending.get("state"))
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
