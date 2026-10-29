"""Open chat (오픈채팅) automation for KakaoTalk PC.

Flows were mapped against KakaoTalk PC 26.9 (Windows, 100% display scale):

- Main window (chat tab) header has an open-chat icon that opens the
  "오픈채팅" window. That window has a real Win32 ``Edit`` search box; the
  home list, the search header and the result list are owner-drawn
  ``EVA_Window_Dblclk`` children, read with OCR.
- Double-clicking a search result opens a preview window whose bottom button
  is "오픈채팅 참여하기" (or "채팅방 들어가기" when already joined). Joining
  shows a "프로필 설정" dialog (KakaoTalk profile vs. random nickname). Picking
  the random profile enables the nickname ``Edit`` below the list, so the
  open-chat profile can be given any name (1-20 chars). Community rooms first
  show a modal "커뮤니티 시작하기" consent dialog over the preview (messages
  are public and searchable, kept 90 days; "동의" / "취소").
- A chat room window's ≡ menu is an ``EVA_Menu`` popup with "채팅방 URL 복사",
  "채팅방 나가기", ...; leaving asks for confirmation ("나가기" / "취소").
- "+ 만들기" opens "오픈채팅 만들기" with a name ``Edit``, a description
  ``RICHEDIT50W``, topic chips and participation options.

All coordinates below are window-relative pixels. Every click first brings the
target window to the foreground and aborts if that fails, so a stray click
never lands in another application.
"""
import ctypes
import re
import time
from typing import Callable, Dict, List, Optional, Set

import win32api
import win32clipboard
import win32gui
import win32process

from . import config, controller, ocr

_user32 = ctypes.windll.user32

EM_SETSEL = 0x00B1
WM_CLEAR = 0x0303
WM_CHAR = 0x0102
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
GA_ROOT = 2
GW_OWNER = 4
WM_CLOSE = 0x0010
WM_GETTEXT = 0x000D

CREATED_DIALOG_TITLE = "오픈채팅방을 만들었습니다."
COMMUNITY_DIALOG_TITLE = "커뮤니티 시작하기"
NO_RESULTS_TEXT = "검색 결과가 없습니다"

SEPARATOR_RGB = (237, 237, 237)


class UIError(Exception):
    """A KakaoTalk UI step failed (window missing, unexpected dialog, ...)."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _main_hwnd() -> int:
    hwnd = win32gui.FindWindow(config.KAKAO_MAIN_WINDOW_CLASS, config.KAKAO_MAIN_WINDOW_TITLE)
    if not hwnd:
        raise UIError("KakaoTalk main window not found (is KakaoTalk running and logged in?)")
    return hwnd


def _kakao_windows() -> Set[int]:
    """Visible top-level windows that belong to the KakaoTalk process."""
    _, pid = win32process.GetWindowThreadProcessId(_main_hwnd())
    found: Set[int] = set()

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            if win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
                found.add(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def _size(hwnd: int):
    r = win32gui.GetWindowRect(hwnd)
    return r[2] - r[0], r[3] - r[1]


def _children(hwnd: int, direct: bool = True) -> List[int]:
    out: List[int] = []

    def _cb(child, _):
        if not direct or win32gui.GetParent(child) == hwnd:
            out.append(child)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _cb, None)
    except Exception:
        pass
    return out


def _wait_for(pred: Callable[[], Optional[int]], timeout: float = 5.0, interval: float = 0.15) -> Optional[int]:
    end = time.time() + timeout
    while time.time() < end:
        found = pred()
        if found:
            return found
        time.sleep(interval)
    return None


def _wait_new_window(before: Set[int], pred: Callable[[int], bool] = lambda h: True,
                     timeout: float = 5.0) -> Optional[int]:
    def _check():
        for h in _kakao_windows() - before:
            if pred(h):
                return h
        return None
    return _wait_for(_check, timeout)


def _focus(hwnd: int):
    """Bring the top-level window containing ``hwnd`` to the foreground."""
    hwnd = win32gui.GetAncestor(hwnd, GA_ROOT) or hwnd
    controller.bring_window_to_front(hwnd)
    time.sleep(config.WINDOW_ACTIVATE_WAIT_SEC)
    if _user32.GetForegroundWindow() != hwnd:
        controller.bring_window_to_front(hwnd)
        time.sleep(0.3)
        if _user32.GetForegroundWindow() != hwnd:
            raise UIError(f"Could not bring window {hwnd:#x} to the foreground")


def _click(hwnd: int, x: float, y: float, double: bool = False, focus: bool = True):
    """Click at window-relative (x, y) after making ``hwnd`` the foreground window."""
    if focus:
        _focus(hwnd)
    left, top, _, _ = win32gui.GetWindowRect(hwnd)
    _user32.SetCursorPos(int(left + x), int(top + y))
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    if double:
        time.sleep(0.05)
        _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.4)


def _wheel(hwnd: int, x: float, y: float, notches: int):
    """Scroll with the mouse wheel over a window-relative point (positive = down)."""
    _focus(hwnd)
    left, top, _, _ = win32gui.GetWindowRect(hwnd)
    _user32.SetCursorPos(int(left + x), int(top + y))
    for _ in range(abs(notches)):
        _user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -120 if notches > 0 else 120, 0)
        time.sleep(0.05)
    time.sleep(0.5)


def _press(vk: int):
    _user32.keybd_event(vk, 0, 0, 0)
    _user32.keybd_event(vk, 0, config.KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)


def _set_text(edit_hwnd: int, text: str):
    """Replace an Edit/RichEdit's text by typing WM_CHAR (works with Korean, no IME needed)."""
    win32api.SendMessage(edit_hwnd, EM_SETSEL, 0, -1)
    win32api.SendMessage(edit_hwnd, WM_CLEAR, 0, 0)
    for ch in text:
        win32api.SendMessage(edit_hwnd, WM_CHAR, ord("\r") if ch == "\n" else ord(ch), 0)
        time.sleep(config.SEARCH_CHAR_INTERVAL_SEC)


def _paste_text(edit_hwnd: int, text: str):
    """Replace a RichEdit's text by click-focus + Ctrl+A + clipboard paste.

    KakaoTalk's description box ignores WM_CHAR for its own model (text shows,
    but the counter stays 0 and nothing is saved); real paste input is needed.
    """
    r = win32gui.GetWindowRect(edit_hwnd)
    root = win32gui.GetAncestor(edit_hwnd, GA_ROOT)
    left, top, _, _ = win32gui.GetWindowRect(root)
    _click(root, (r[0] + r[2]) / 2 - left, (r[1] + r[3]) / 2 - top)
    controller._send_ctrl_key_combo(config.VK_A)
    time.sleep(config.KEY_COMBO_WAIT_SEC)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    time.sleep(config.CLIPBOARD_PASTE_WAIT_SEC)
    controller._send_ctrl_key_combo(0x56)  # Ctrl+V
    time.sleep(0.3)


def _get_text(hwnd: int) -> str:
    """Read an Edit control's text from another process (WM_GETTEXT)."""
    buf = ctypes.create_unicode_buffer(1024)
    _user32.SendMessageW(hwnd, WM_GETTEXT, len(buf), buf)
    return buf.value


def _read_clipboard() -> str:
    for _ in range(config.CLIPBOARD_MAX_RETRIES):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
                return ""
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(config.CLIPBOARD_RETRY_INTERVAL_SEC)
    return ""


def _clear_clipboard():
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass


def _ocr_window(hwnd: int, focus: bool = True) -> List[Dict]:
    if focus:
        _focus(hwnd)
    return ocr.recognize(ocr.grab_window(hwnd))


def _ocr_text(hwnd: int) -> str:
    try:
        return " / ".join(ln["text"] for ln in _ocr_window(hwnd))
    except Exception as e:  # diagnostics only
        return f"<ocr failed: {e}>"


# ---------------------------------------------------------------------------
# Open chat window
# ---------------------------------------------------------------------------

def _is_openchat_window(hwnd: int) -> bool:
    """Untitled EVA window with a direct ``Edit`` search box (the 오픈채팅 window)."""
    if win32gui.GetClassName(hwnd) != config.KAKAO_CHAT_WINDOW_CLASS or win32gui.GetWindowText(hwnd):
        return False
    w, h = _size(hwnd)
    if h < 400:
        return False
    return any(
        win32gui.GetClassName(c) == "Edit" and win32gui.IsWindowVisible(c) and _size(c)[0] > 100
        for c in _children(hwnd)
    )


def _find_openchat_window() -> Optional[int]:
    for h in _kakao_windows():
        if _is_openchat_window(h):
            return h
    return None


def open_openchat_window() -> int:
    """Open (or focus) the 오픈채팅 window and return its hwnd."""
    hwnd = _find_openchat_window()
    if hwnd:
        _focus(hwnd)
        return hwnd

    main = _main_hwnd()
    before = _kakao_windows()
    _click(main, *config.MAIN_CHAT_TAB_POS)  # chat tab — the open-chat icon lives in its header
    w, _ = _size(main)
    _click(main, w - config.MAIN_OPENCHAT_ICON_OFFSET[0], config.MAIN_OPENCHAT_ICON_OFFSET[1])
    hwnd = _wait_new_window(before, _is_openchat_window, timeout=5)
    if not hwnd:
        raise UIError("Open chat window did not appear")
    time.sleep(0.5)
    return hwnd


def _search_edit(oc_hwnd: int) -> int:
    for c in _children(oc_hwnd):
        if win32gui.GetClassName(c) == "Edit" and win32gui.IsWindowVisible(c):
            return c
    raise UIError("Open chat search box not found")


def _result_list(oc_hwnd: int) -> Optional[int]:
    """The visible result list in search view (it starts well below the search box)."""
    edit_bottom = win32gui.GetWindowRect(_search_edit(oc_hwnd))[3]
    best = None
    for c in _children(oc_hwnd):
        if win32gui.GetClassName(c) != config.KAKAO_CHAT_WINDOW_CLASS or not win32gui.IsWindowVisible(c):
            continue
        r = win32gui.GetWindowRect(c)
        if r[1] - edit_bottom > 60 and r[3] - r[1] > 150:
            best = c
    return best


def _go_home(oc_hwnd: int):
    """Return the open chat window to its home view (back arrow in search view)."""
    if _result_list(oc_hwnd):
        _click(oc_hwnd, *config.OPENCHAT_BACK_POS)
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _split_items(img) -> List[tuple]:
    """Split a result-list screenshot into item row spans using the 1px separators."""
    w, h = img.size
    rgb = img.convert("RGB")
    xs = range(25, max(26, w - 40), 5)
    seps = [y for y in range(h)
            if rgb.getpixel((25, y)) == SEPARATOR_RGB
            and all(rgb.getpixel((x, y)) == SEPARATOR_RGB for x in xs)]
    # If the list ends before the viewport does, trim the blank tail so the last
    # row counts as complete (its bottom is above the viewport edge).
    end = h
    while end > 0 and all(rgb.getpixel((x, end - 1)) == (255, 255, 255) for x in xs):
        end -= 1
    if h - end > 10:
        end = min(h - 1, end + 5)
    else:
        end = h
    bounds = [0] + [y for y in seps if y < end] + [end]
    return [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a > 40]


def _parse_item(img, top: int, bottom: int) -> Optional[Dict]:
    """OCR one result row: title (dark text), description, member count/activity."""
    w, _ = img.size
    crop = img.crop((0, top, w - config.OPENCHAT_THUMB_WIDTH, bottom))
    lines = ocr.recognize(crop, scale=config.OPENCHAT_OCR_SCALE)
    if not lines:
        return None
    title_lines, rest = [], []
    for ln in lines:
        dark = ocr.line_darkness(crop, ln) < config.OPENCHAT_TITLE_MAX_LUMA
        if dark and not rest and not ln["text"].lstrip().startswith("#"):
            title_lines.append(ln)
        else:
            rest.append(ln)
    if not title_lines:
        title_lines, rest = lines[:1], lines[1:]
    meta = rest[-1]["text"] if len(rest) >= 2 else ""
    desc = " ".join(ln["text"] for ln in (rest[:-1] if meta else rest))
    title = " ".join(ln["text"] for ln in title_lines).strip()
    # Room icons (lock, badges) in front of the title OCR as a stray glyph
    title = re.sub(r"^(?:[0十+*·•]|[^\w\s<\[(〈])\s+", "", title)
    members = re.search(r"(\d[\d,]*)\s*\S?\s*(?:\||방금|\d+\s*(?:분|시간|일)|$)", meta)
    return {
        "title": title,
        "description": desc.strip(),
        "meta": meta.strip(),
        "members": int(members.group(1).replace(",", "")) if members else None,
        "y_center": (top + bottom) / 2,
        "complete": bottom < img.size[1],
        "top": top,
    }


def _visible_results(oc_hwnd: int, at_top: bool = False) -> List[Dict]:
    """Parse the rows currently visible in the result list.

    A row is ``complete`` when both its separators are visible; when the list
    is scrolled to the top (``at_top``) the first row has no separator above.
    """
    lst = _result_list(oc_hwnd)
    if not lst:
        return []
    _focus(oc_hwnd)
    img = ocr.grab_window(lst)
    items = []
    for top, bottom in _split_items(img):
        item = _parse_item(img, top, bottom)
        if item and item["title"] and ocr.similarity(item["title"], NO_RESULTS_TEXT) < 0.8:
            item["complete"] = item["complete"] and (item["top"] > 0 or at_top)
            item["list_hwnd"] = lst
            items.append(item)
    return items


def _run_search(query: str) -> int:
    oc = open_openchat_window()
    edit = _search_edit(oc)
    _set_text(edit, query)
    r = win32gui.GetWindowRect(edit)
    o = win32gui.GetWindowRect(oc)
    _click(oc, (r[0] + r[2]) / 2 - o[0], (r[1] + r[3]) / 2 - o[1])  # focus the box
    _press(VK_RETURN)
    if not _wait_for(lambda: _result_list(oc), timeout=5):
        raise UIError(f"No search results view for '{query}'")
    time.sleep(config.OPENCHAT_RESULTS_WAIT_SEC)
    return oc


def search_openchat(query: str, max_results: int = 10, max_pages: int = 3) -> Dict:
    """Search open chat rooms (group chats) and return parsed results."""
    oc = _run_search(query)
    results: List[Dict] = []
    seen: Set[str] = set()
    for page in range(max_pages):
        new = 0
        for item in _visible_results(oc, at_top=page == 0):
            key = ocr.normalize(item["title"])
            if key in seen or not item["complete"]:
                continue
            seen.add(key)
            new += 1
            results.append({k: item[k] for k in ("title", "description", "members", "meta")})
        if len(results) >= max_results or new == 0 or page == max_pages - 1:
            break
        lst = _result_list(oc)
        w, h = _size(lst)
        _wheel(lst, w / 2, h / 2, config.OPENCHAT_SCROLL_NOTCHES)
    results = results[:max_results]
    for i, r in enumerate(results):
        r["index"] = i
    return {"success": True, "query": query, "count": len(results), "results": results}


def _locate_result(oc: int, title: Optional[str], index: int, max_pages: int = 5) -> Dict:
    """Scroll through results until the wanted item is fully visible; return it."""
    seen: List[str] = []
    for page in range(max_pages):
        for item in _visible_results(oc, at_top=page == 0):
            if not item["complete"]:
                continue
            key = ocr.normalize(item["title"])
            if key not in seen:
                seen.append(key)
            pos = seen.index(key)
            matched = (ocr.similarity(item["title"], title) >= 0.75) if title else pos == index
            if matched and item["complete"]:
                return item
        lst = _result_list(oc)
        w, h = _size(lst)
        _wheel(lst, w / 2, h / 2, config.OPENCHAT_SCROLL_NOTCHES)
    raise UIError(f"Result not found: {title!r}" if title else f"Result index {index} not found")


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------

def _is_preview_window(hwnd: int) -> bool:
    if win32gui.GetClassName(hwnd) != config.KAKAO_CHAT_WINDOW_CLASS or win32gui.GetWindowText(hwnd):
        return False
    w, h = _size(hwnd)
    return 250 < w < 400 and h > 500 and not _is_openchat_window(hwnd)


def _find_titled_window(title: str, exclude: Set[int]) -> Optional[int]:
    for h in _kakao_windows() - exclude:
        t = win32gui.GetWindowText(h)
        if t and t != config.KAKAO_MAIN_WINDOW_TITLE and ocr.similarity(t, title) >= 0.75:
            return h
    return None


def join_openchat(query: str, title: Optional[str] = None, index: int = 0,
                  profile: str = "kakao", passcode: Optional[str] = None,
                  nickname: Optional[str] = None, accept_community: bool = False) -> Dict:
    """Search, open the preview of a result, and join it.

    Args:
        query: Search text.
        title: Room title to pick (fuzzy). If omitted, ``index`` is used.
        index: 0-based result index when ``title`` is not given.
        profile: "kakao" (KakaoTalk profile) or "random" (random nickname).
        passcode: Participation code for code-protected rooms.
        nickname: Join with an open-chat profile of this name (1-20 chars)
            instead of the KakaoTalk profile; implies ``profile="random"``.
        accept_community: Agree to the "커뮤니티 시작하기" terms of community
            rooms (messages become public). If False, the dialog is declined
            and nothing is joined.
    """
    if profile not in ("kakao", "random"):
        return {"success": False, "error": "profile must be 'kakao' or 'random'"}
    if nickname is not None:
        nickname = nickname.strip()
        if not nickname or len(nickname) > 20:
            return {"success": False, "error": "nickname must be 1-20 characters"}
        profile = "random"

    oc = _run_search(query)
    item = _locate_result(oc, title, index)
    room_title = item["title"]
    lst = item["list_hwnd"]

    before = _kakao_windows()
    _focus(oc)
    _click(lst, config.OPENCHAT_ITEM_CLICK_X, item["y_center"], double=True, focus=False)
    preview = _wait_new_window(before, _is_preview_window, timeout=5)
    if not preview:
        room = _find_titled_window(room_title, set())
        if room:  # already a member: KakaoTalk may open the room directly
            return _joined(room, already=True)
        raise UIError(f"Preview window did not open for '{room_title}'")
    time.sleep(0.6)

    pw, ph = _size(preview)
    btn_y = ph - config.OPENCHAT_PREVIEW_BUTTON_FROM_BOTTOM

    before = _kakao_windows()
    _click(preview, pw / 2, btn_y)

    handled: Set[int] = set()
    passcode_sent = False
    end = time.time() + 10
    while time.time() < end:
        time.sleep(0.3)
        preview_open = win32gui.IsWindow(preview) and win32gui.IsWindowVisible(preview)
        new = [h for h in _kakao_windows() - before - handled if h != preview]
        for dialog in new:
            dtitle = win32gui.GetWindowText(dialog)
            if dtitle == "프로필 설정":
                time.sleep(0.4)
                _confirm_profile(dialog, profile, nickname)
                handled.add(dialog)
            elif dtitle == COMMUNITY_DIALOG_TITLE:
                time.sleep(0.4)
                _answer_community(dialog, accept_community)
                handled.add(dialog)
                if not accept_community:
                    _close_preview(preview)
                    return {"success": False, "community": True,
                            "error": f"'{room_title}' is a community room: joining requires agreeing to "
                                     f"'{COMMUNITY_DIALOG_TITLE}' (messages are public and searchable, "
                                     "kept 90 days). Declined; pass accept_community=True to agree."}
            elif dtitle and ocr.similarity(dtitle, room_title) < 0.75 and _owner(dialog) == preview:
                text = _ocr_text(dialog)
                _close_preview(preview)
                raise UIError(f"Unexpected dialog '{dtitle}' while joining: {text}")
            elif dtitle:
                continue  # a titled window: possibly the room, checked below
            else:
                time.sleep(0.4)
                text = _ocr_text(dialog)
                if "코드" in text and passcode and not passcode_sent:
                    edits = [c for c in _children(dialog, direct=False)
                             if win32gui.GetClassName(c) == "Edit"]
                    if not edits:
                        raise UIError(f"Passcode dialog without an input box: {text}")
                    _set_text(edits[0], passcode)
                    _focus(dialog)
                    _press(VK_RETURN)
                    passcode_sent = True
                    handled.add(dialog)
                else:
                    raise UIError(f"Unexpected dialog while joining: {text}")
        room = _find_titled_window(room_title, {preview})
        if room and not preview_open and _user32.GetForegroundWindow() == room:
            # Members go straight in; joining always passes through 프로필 설정
            return _joined(room, already=not handled)
    if win32gui.IsWindow(preview) and win32gui.IsWindowVisible(preview):
        modals = [h for h in _kakao_windows() if _owner(h) == preview]
        detail = " | ".join(_ocr_text(h) for h in modals + [preview])
        _close_preview(preview)
        raise UIError(f"Join did not complete; preview still open: {detail}")
    raise UIError(f"Room window for '{room_title}' did not open")


def _owner(hwnd: int) -> int:
    return win32gui.GetWindow(hwnd, GW_OWNER)


def _close_preview(preview: int):
    """Close the preview window, dismissing any modal it owns first.

    A modal leaves the preview disabled, so WM_CLOSE to it alone is ignored.
    """
    for h in _kakao_windows():
        if _owner(h) == preview:
            win32gui.PostMessage(h, WM_CLOSE, 0, 0)
    _wait_for(lambda: None if any(_owner(h) == preview for h in _kakao_windows()) else True, 3)
    if win32gui.IsWindow(preview):
        win32gui.PostMessage(preview, WM_CLOSE, 0, 0)


def _answer_community(dialog: int, accept: bool):
    """Click "동의" or "취소" on the "커뮤니티 시작하기" consent dialog."""
    lines = _ocr_window(dialog)
    _, h = _size(dialog)
    btn = ocr.find_line([ln for ln in lines if ln["y"] > h - 70], "동의" if accept else "취소", threshold=0.75)
    if not btn:
        win32gui.PostMessage(dialog, WM_CLOSE, 0, 0)
        raise UIError(f"Buttons not found on '{COMMUNITY_DIALOG_TITLE}': "
                      f"{' / '.join(ln['text'] for ln in lines)}")
    _click(dialog, btn["cx"], btn["cy"])
    if not _wait_for(lambda: None if win32gui.IsWindow(dialog) and win32gui.IsWindowVisible(dialog) else True, 3):
        raise UIError(f"'{COMMUNITY_DIALOG_TITLE}' did not close after clicking "
                      f"{'동의' if accept else '취소'}")


def _joined(room: int, already: bool) -> Dict:
    actual = win32gui.GetWindowText(room)
    return {
        "success": True,
        "already_joined": already,
        "room_name": actual,
        "message": f"{'Opened' if already else 'Joined'} open chat '{actual}'",
    }


def _confirm_profile(dialog: int, profile: str, nickname: Optional[str] = None):
    w, h = _size(dialog)
    if profile == "random":
        _click(dialog, *config.PROFILE_RANDOM_RADIO_POS)
    if nickname:
        # The nickname box is disabled until the random profile is selected
        edit = next((c for c in _children(dialog, direct=False) if win32gui.GetClassName(c) == "Edit"), None)
        if not edit:
            raise UIError("Nickname field not found in the 프로필 설정 dialog")
        _set_text(edit, nickname)
        time.sleep(0.2)
        if _get_text(edit) != nickname:
            _click(dialog, w - config.FORM_CANCEL_FROM_RIGHT, h - config.DIALOG_BUTTON_FROM_BOTTOM)
            raise UIError(f"Nickname was not accepted (field shows {_get_text(edit)!r})")
    _click(dialog, w / 2 - config.PROFILE_CONFIRM_FROM_CENTER, h - config.DIALOG_BUTTON_FROM_BOTTOM)


# ---------------------------------------------------------------------------
# Room menu: leave / link
# ---------------------------------------------------------------------------

def _open_room_menu(room_name: str) -> int:
    room = controller.find_chat_window(room_name)
    if room is None:
        raise UIError(f"Chat window '{room_name}' not found (open it first)")
    w, _ = _size(room)
    before = _kakao_windows()
    _click(room, w - config.ROOM_MENU_ICON_OFFSET[0], config.ROOM_MENU_ICON_OFFSET[1])
    menu = _wait_new_window(before, lambda h: win32gui.GetClassName(h) == "EVA_Menu", timeout=3)
    if not menu:
        raise UIError("Chat room menu did not open")
    time.sleep(0.3)
    return menu


def _click_menu_item(menu: int, label: str, exclude: Optional[List[str]] = None):
    lines = ocr.recognize(ocr.grab_window(menu))
    line = ocr.find_line(lines, label, threshold=0.6, exclude=exclude)
    if not line:
        _press(VK_ESCAPE)
        raise UIError(f"Menu item '{label}' not found in: {[ln['text'] for ln in lines]}")
    _click(menu, line["cx"], line["cy"], focus=False)


def get_room_link(room_name: str) -> Dict:
    """Copy an open chat room's URL via its menu and return it."""
    _clear_clipboard()
    menu = _open_room_menu(room_name)
    _click_menu_item(menu, "채팅방 URL 복사")
    url = ""
    for _ in range(10):
        url = _read_clipboard().strip()
        if url:
            break
        time.sleep(0.2)
    if not url:
        return {"success": False, "error": "URL was not copied (is this an open chat room?)"}
    return {"success": True, "room_name": room_name, "url": url}


def leave_room(room_name: str) -> Dict:
    """Leave a chat room (open chat or regular) via its menu, confirming the dialog."""
    room = controller.find_chat_window(room_name)
    menu = _open_room_menu(room_name)
    before = _kakao_windows()
    _click_menu_item(menu, "채팅방 나가기", exclude=["신고"])
    dialog = _wait_new_window(before, lambda h: win32gui.GetClassName(h) != "EVA_Menu", timeout=4)
    if not dialog:
        raise UIError("Leave confirmation dialog did not appear")
    time.sleep(0.3)
    lines = _ocr_window(dialog)
    w, h = _size(dialog)
    btn = ocr.find_line([ln for ln in lines if ln["y"] > h - 60], "나가기")
    if not btn:
        _press(VK_ESCAPE)
        raise UIError(f"Unexpected leave dialog: {' / '.join(ln['text'] for ln in lines)}")
    # When the owner leaves, the room is closed and "나가기" stays disabled until
    # the "위 내용을 모두 확인하였습니다." checkbox is ticked.
    ack = ocr.find_line(lines, "위 내용을 모두 확인하였습니다", threshold=0.7)
    if ack:
        _click(dialog, ack["x"] - config.LEAVE_ACK_CHECK_OFFSET, ack["cy"])
    _click(dialog, btn["cx"], btn["cy"])
    gone = _wait_for(lambda: True if not (room and win32gui.IsWindow(room)
                                          and win32gui.IsWindowVisible(room)) else None, timeout=5)
    if not gone:
        if win32gui.IsWindow(dialog) and win32gui.IsWindowVisible(dialog):
            win32gui.PostMessage(dialog, WM_CLOSE, 0, 0)
        return {"success": False, "error": f"Room window '{room_name}' is still open after leaving"}
    msg = f"Left chat room '{room_name}'" + (" (owner left: the room was closed)" if ack else "")
    return {"success": True, "room_closed": bool(ack), "message": msg}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

TOPICS = ["자유수다", "팬덤", "게임", "엔터테인먼트", "스포츠", "일상", "운동/건강",
          "여행", "취미", "친목/모임", "패션/뷰티", "직업", "자기계발", "재테크"]


def _form_body(form: int) -> int:
    for c in _children(form):
        if win32gui.GetClassName(c) == "EVA_ChildWindow" and win32gui.IsWindowVisible(c):
            return c
    raise UIError("Create form body not found")


def _find_on_form(form: int, label: str, max_scrolls: int = 4,
                  exclude: Optional[List[str]] = None) -> Dict:
    """OCR the form, scrolling down until ``label`` is visible; return the line."""
    body = _form_body(form)
    bw, bh = _size(body)
    for _ in range(max_scrolls + 1):
        lines = _ocr_window(form)
        top = win32gui.GetWindowRect(body)[1] - win32gui.GetWindowRect(form)[1]
        visible = [ln for ln in lines if top <= ln["cy"] <= top + bh]
        line = ocr.find_line(visible, label, threshold=0.75, exclude=exclude)
        if line:
            return line
        _wheel(body, bw / 2, bh / 2, 3)
    raise UIError(f"'{label}' not found on the create form")


def _close_created_dialog(exclude: Set[int], timeout: float = 8) -> str:
    """Close the modal "오픈채팅방을 만들었습니다." shown after creating; return its URL.

    The modal blocks the new room window (input and focus) until it is closed.
    """
    dialog = _wait_for(lambda: next((h for h in _kakao_windows() - exclude
                                     if win32gui.GetWindowText(h) == CREATED_DIALOG_TITLE), None), timeout)
    if not dialog:
        return ""
    edit = next((c for c in _children(dialog, direct=False) if win32gui.GetClassName(c) == "Edit"), None)
    url = _get_text(edit).strip() if edit else ""
    win32gui.PostMessage(dialog, WM_CLOSE, 0, 0)
    _wait_for(lambda: None if win32gui.IsWindow(dialog) and win32gui.IsWindowVisible(dialog) else True, 3)
    return url


def create_openchat(name: str, description: str = "", topic: str = "자유수다",
                    searchable: bool = True, kakao_profile_only: bool = False) -> Dict:
    """Create a group open chat room and return the new room's window title."""
    if not name.strip() or len(name) > 30:
        return {"success": False, "error": "name must be 1-30 characters"}
    if len(description) > 200:
        return {"success": False, "error": "description must be at most 200 characters"}
    if topic not in TOPICS:
        return {"success": False, "error": f"topic must be one of {TOPICS}"}

    oc = open_openchat_window()
    _go_home(oc)
    _wheel(oc, 200, 300, -10)  # home view scrolled to top so '+ 만들기' is visible
    lines = _ocr_window(oc)
    make = ocr.find_line(lines, "만들기", threshold=0.75)
    if not make:
        raise UIError("'+ 만들기' button not found in the open chat window")
    before = _kakao_windows()
    _click(oc, make["cx"], make["cy"])
    form = _wait_new_window(before, lambda h: win32gui.GetWindowText(h) == "오픈채팅 만들기", timeout=5)
    if not form:
        raise UIError("'오픈채팅 만들기' window did not open")
    time.sleep(0.5)

    try:
        fields = _children(form, direct=False)
        name_edit = next((c for c in fields if win32gui.GetClassName(c) == "Edit"), None)
        desc_edit = next((c for c in fields if win32gui.GetClassName(c) == config.KAKAO_EDIT_CLASS), None)
        if not name_edit:
            raise UIError("Name field not found on the create form")
        _set_text(name_edit, name)
        if description:
            if not desc_edit:
                raise UIError("Description field not found on the create form")
            _paste_text(desc_edit, description)

        chip = _find_on_form(form, topic)
        _click(form, chip["cx"], chip["cy"])

        if kakao_profile_only:
            opt = _find_on_form(form, "기본프로필만 참여 허용")
            _click(form, config.FORM_OPTION_CHECK_X, opt["cy"])
        if not searchable:
            opt = _find_on_form(form, "검색 허용")
            _click(form, config.FORM_OPTION_CHECK_X, opt["cy"])

        w, h = _size(form)
        exclude = _kakao_windows()
        _click(form, w / 2 + config.FORM_CONFIRM_FROM_CENTER, h - config.DIALOG_BUTTON_FROM_BOTTOM)
    except Exception:
        # Leave nothing half-filled behind
        if win32gui.IsWindow(form):
            w, h = _size(form)
            try:
                _click(form, w - config.FORM_CANCEL_FROM_RIGHT, h - config.DIALOG_BUTTON_FROM_BOTTOM)
            except Exception:
                pass
        raise

    url = _close_created_dialog(exclude)
    room = _wait_for(lambda: _find_titled_window(name, exclude - {form}), timeout=8)
    if not room:
        still = win32gui.IsWindow(form) and win32gui.IsWindowVisible(form)
        detail = _ocr_text(form) if still else "form closed"
        return {"success": False, "error": f"Room window did not open after creating ({detail})"}
    return {"success": True, "room_name": win32gui.GetWindowText(room), "url": url,
            "message": f"Created open chat '{win32gui.GetWindowText(room)}'"}
