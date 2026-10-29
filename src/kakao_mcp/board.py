"""Room board (톡게시판) reading: 공지 / 일정 / 투표 / 퀴즈 posts.

Mapped against KakaoTalk PC 26.9 (100% display scale):

- A chat room's ≡ menu has "톡게시판", which opens a separate window titled like
  the room. It holds ``MoimFeedView`` (post list) or ``MoimContentWnd`` (a post's
  상세보기) children; tabs 공지 · 일정 · 투표 · 퀴즈 sit under the header.
- A list item is a near-black title (1-2 lines, truncated) over a gray meta line
  "<date> · <author> [· 댓글 N]", with an optional thumbnail on the right.
  Double-clicking the title opens 상세보기; its ← returns to the list, which is
  then scrolled back to the top.
- In 상세보기, Ctrl+A / Ctrl+C (no click needed, so links are never hit) copies
  the post body. Comments are not part of the copy.
"""
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import win32gui

from . import config, controller, ocr
from .openchat import (
    VK_ESCAPE, WM_CLOSE, UIError, _clear_clipboard, _click, _focus, _kakao_windows,
    _open_room_menu, _press, _read_clipboard, _size, _wait_for, _wait_new_window, _wheel,
)

TABS = ("공지", "일정", "투표", "퀴즈")
META_SPLIT = re.compile(r"\s*[•·]\s*")
META_DATE = re.compile(r"방금|\d+\s*(?:분|시간|일)\s*전|어제|\d{1,2}월\s*\d{1,2}일")
COMMENTS = re.compile(r"[댓덧]글\s*(\d[\d,]*)")
ABS_DATE = re.compile(
    r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(?:(오전|오후)\s*(\d{1,2})\s*[:.]?\s*(\d{2}))?")
VK_HOME = 0x24
YESTERDAY = re.compile(r"어제\s*(?:(오전|오후)\s*(\d{1,2})\s*[:.]?\s*(\d{2}))?")


def _find_board(room_name: str) -> Optional[int]:
    for h in _kakao_windows():
        if win32gui.GetWindowText(h) == room_name and controller.is_board_window(h):
            return h
    return None


def _open_board(room_name: str) -> int:
    """Open the room's 톡게시판 from its ≡ menu."""
    menu = _open_room_menu(room_name)
    lines = ocr.recognize(ocr.grab_window(menu))
    item = ocr.find_line(lines, "톡게시판", threshold=0.6)
    if not item:
        # OCR rarely gets this label right ("특기시단", "홀계시판"); it is the
        # entry right below "채팅방 서랍".
        drawer = ocr.find_line(lines, "채팅방 서랍", threshold=0.6)
        below = [ln for ln in lines if drawer and ln["cy"] > drawer["cy"] + 5]
        item = min(below, key=lambda ln: ln["cy"]) if below else None
    if not item:
        _press(VK_ESCAPE)
        raise UIError(f"'톡게시판' not found in the room menu: {[ln['text'] for ln in lines]}")
    before = _kakao_windows()
    _click(menu, item["cx"], item["cy"], focus=False)
    board = _wait_new_window(before, controller.is_board_window, timeout=5)
    if not board:
        raise UIError(f"톡게시판 window did not open for '{room_name}'")
    time.sleep(0.8)
    return board


def _in_detail(board: int) -> bool:
    w, _ = _size(board)
    _focus(board)
    head = ocr.recognize(ocr.grab_window(board).crop((0, 25, w, 70)))
    return ocr.find_line(head, "상세보기", threshold=0.6) is not None


def _show_list(board: int, tab: str):
    if _in_detail(board):
        _click(board, *config.BOARD_BACK_POS)
        time.sleep(config.BOARD_NAV_WAIT_SEC)
    _click(board, config.BOARD_TAB_X[tab], config.BOARD_TAB_Y)
    time.sleep(config.BOARD_NAV_WAIT_SEC)
    _press(VK_HOME)  # the tab keeps its scroll position
    time.sleep(0.5)


def _visible_items(board: int) -> List[Dict]:
    """Group the list viewport's OCR lines into items (title lines + meta line).

    Items whose title starts above the viewport are skipped; lines of banners or
    empty-state text have no meta line and are dropped.
    """
    _focus(board)
    img = ocr.grab_window(board)
    w, h = img.size
    top = config.BOARD_LIST_TOP
    crop = img.crop((0, top, w - config.BOARD_THUMB_WIDTH, h))
    items, titles, prev_bottom, cut = [], [], None, False
    for ln in ocr.recognize(crop, scale=config.OPENCHAT_OCR_SCALE):
        if ocr.line_darkness(crop, ln) >= config.BOARD_META_MIN_LUMA:
            if titles and not cut and META_DATE.search(ln["text"]) and len(META_SPLIT.split(ln["text"])) >= 2:
                items.append({
                    "title": " ".join(t["text"] for t in titles).strip(),
                    "meta": ln["text"].strip(),
                    "cx": titles[0]["cx"], "cy": titles[0]["cy"] + top,
                })
            titles, cut = [], False
        elif not titles and ln["y"] <= 4:
            cut = True  # the title starts above the viewport
        elif not cut:
            if titles and ln["y"] - prev_bottom > config.BOARD_TITLE_GAP:
                titles = []  # a big gap: the earlier lines were not this item's title
            titles.append(ln)
        prev_bottom = ln["y"] + ln["h"]
    return items


def _scroll(board: int, pages: int):
    """Scroll the list by ``pages`` steps (negative = up)."""
    w, h = _size(board)
    if pages:
        _wheel(board, w / 2, (config.BOARD_LIST_TOP + h) / 2, pages * config.BOARD_SCROLL_NOTCHES)


def _same(a: Dict, b: Dict) -> bool:
    """The same list item, allowing for OCR differences between screenshots."""
    return ocr.similarity(a["meta"], b["meta"]) >= 0.85 and ocr.similarity(a["title"], b["title"]) >= 0.7


def _parse_when(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """Best-effort "YYYY-MM-DD HH:MM" for list dates (relative ones are approximate)."""
    now = now or datetime.now()
    m = re.search(r"(\d+)\s*(분|시간|일)\s*전", text)
    if m:
        unit = {"분": "minutes", "시간": "hours", "일": "days"}[m.group(2)]
        return (now - timedelta(**{unit: int(m.group(1))})).strftime("%Y-%m-%d %H:%M")
    if "방금" in text:
        return now.strftime("%Y-%m-%d %H:%M")

    def _hm(ampm, hh, mm):
        if not hh:
            return 0, 0
        return int(hh) % 12 + (12 if ampm == "오후" else 0), int(mm)

    m = YESTERDAY.search(text)
    if m:
        hh, mm = _hm(*m.groups())
        return (now - timedelta(days=1)).replace(hour=hh, minute=mm).strftime("%Y-%m-%d %H:%M")
    m = ABS_DATE.search(text)
    if m:
        year, month, day, ampm, hh, mm = m.groups()
        hh, mm = _hm(ampm, hh, mm)
        try:
            when = datetime(int(year or now.year), int(month), int(day), hh, mm)
        except ValueError:
            return None
        if not year and when > now:  # "12월 30일" seen in January
            when = when.replace(year=when.year - 1)
        return when.strftime("%Y-%m-%d %H:%M")
    return None


def _parse_meta(meta: str) -> Dict:
    parts = META_SPLIT.split(meta)
    comments = COMMENTS.search(meta)
    return {
        "posted": _parse_when(parts[0]),
        "posted_raw": parts[0],
        "author": parts[1] if len(parts) > 1 and not COMMENTS.match(parts[1]) else None,
        "comments": int(comments.group(1).replace(",", "")) if comments else None,
    }


def _read_body(board: int, item: Dict, from_page: int) -> str:
    """Open ``item`` from the list (now scrolled to ``from_page``), copy its body, go back.

    Going back leaves the list scrolled to the top (page 0).
    """
    _scroll(board, item["page"] - from_page)
    target = next((it for it in _visible_items(board) if _same(it, item)), None)
    if not target:  # not where expected: count pages again from the top
        _focus(board)
        _press(VK_HOME)
        time.sleep(0.5)
        _scroll(board, item["page"])
        target = next((it for it in _visible_items(board) if _same(it, item)), None)
    if not target:
        raise UIError(f"Board post not found again: {item['title']!r}")
    _click(board, target["cx"], target["cy"], double=True)
    if not _wait_for(lambda: _in_detail(board), timeout=4, interval=0.3):
        raise UIError(f"Board post did not open: {item['title']!r}")
    _clear_clipboard()
    _focus(board)
    controller._send_ctrl_key_combo(config.VK_A)
    time.sleep(config.KEY_COMBO_WAIT_SEC)
    controller._send_ctrl_key_combo(config.VK_C)
    body = ""
    for _ in range(10):
        time.sleep(0.2)
        body = _read_clipboard()
        if body:
            break
    _click(board, *config.BOARD_BACK_POS)
    time.sleep(config.BOARD_NAV_WAIT_SEC)
    return body.replace("\r\n", "\n").strip()


def read_board(room_name: str, tab: str = "공지", max_posts: int = 10,
               include_body: bool = True, max_pages: int = 6) -> Dict:
    """Read posts from a room's 톡게시판 tab, newest first.

    Args:
        room_name: Exact title of the chat room window (it must be open).
        tab: "공지", "일정", "투표" or "퀴즈".
        max_posts: Maximum posts to return.
        include_body: Open each post and copy its full text (slower: ~3s a post).
    """
    if tab not in TABS:
        return {"success": False, "error": f"tab must be one of {list(TABS)}"}
    board = _find_board(room_name)
    opened = board is None
    if opened:
        if controller.find_chat_window(room_name) is None:
            return {"success": False, "error": f"Chat window '{room_name}' not found (open it first)"}
        board = _open_board(room_name)
    try:
        _show_list(board, tab)
        found: List[Dict] = []
        for page in range(max_pages):
            new = 0
            for it in _visible_items(board):
                if not any(_same(it, f) for f in found):
                    found.append({**it, "page": page})
                    new += 1
            if len(found) >= max_posts or new == 0:
                break
            _scroll(board, 1)
        found = found[:max_posts]

        posts, at_page = [], page
        for i, it in enumerate(found):
            post = {"index": i, "title": it["title"], **_parse_meta(it["meta"])}
            if include_body:
                body = _read_body(board, it, at_page)
                at_page = 0
                post["body"] = body
                if body:
                    post["title"] = body.split("\n", 1)[0].strip()
            posts.append(post)
        return {"success": True, "room_name": room_name, "tab": tab, "count": len(posts), "posts": posts}
    finally:
        if opened and win32gui.IsWindow(board):
            win32gui.PostMessage(board, WM_CLOSE, 0, 0)
