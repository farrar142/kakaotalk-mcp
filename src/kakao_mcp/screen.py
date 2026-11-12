"""Display scale and keyboard menu selection, without screenshots of the screen or focus.

Fixed positions in ``config`` are measured at 100% display scale (96 DPI). ``px``
turns them into pixels for a given window. The process is DPI aware (``ocr`` calls
``SetProcessDPIAware`` on import), so window rectangles are in physical pixels.
"""
import ctypes
import time
from typing import Optional, Tuple

import win32con
import win32gui
from PIL import ImageChops

from . import config, ocr

_user32 = ctypes.windll.user32
VK_DOWN = 0x28
VK_RETURN = 0x0D


def dpi_scale(hwnd: int) -> float:
    """1.0 at 100% display scale, 1.5 at 150% and so on."""
    try:
        return (_user32.GetDpiForWindow(hwnd) or 96) / 96
    except Exception:
        return 1.0


def px(hwnd: int, value: float) -> float:
    """A length measured at 100% scale, in this window's pixels."""
    return value * dpi_scale(hwnd)


def _post_key(hwnd: int, vk: int):
    lparam = ctypes.c_ssize_t
    _user32.PostMessageW(hwnd, win32con.WM_KEYDOWN, vk, lparam(1))
    _user32.PostMessageW(hwnd, win32con.WM_KEYUP, vk, lparam(0xC0000001))


def highlighted_band(base, img) -> Optional[Tuple[int, int]]:
    """(top, bottom) of the rows that differ between two shots of a menu: the highlight."""
    diff = ImageChops.difference(base.convert("L"), img.convert("L")).point(
        lambda v: 255 if v > config.MENU_HIGHLIGHT_MIN_DIFF else 0)
    box = diff.getbbox()
    return (box[1], box[3]) if box else None


def room_menu_row(menu: int, entry: str) -> Optional[float]:
    """Distance (100% scale) of ``entry`` above the bottom of a chat room ≡ menu, or
    None when the menu's size matches no known layout or the layout lacks the entry."""
    left, top, right, bottom = win32gui.GetWindowRect(menu)
    scale = dpi_scale(menu)
    w, h = (right - left) / scale, (bottom - top) / scale
    tol = config.ROOM_MENU_SIZE_TOLERANCE
    for (lw, lh), rows in config.ROOM_MENU_LAYOUTS.items():
        if abs(w - lw) <= tol and abs(h - lh) <= tol:
            return rows.get(entry)
    return None


def room_menu_select(menu: int, entry: str) -> bool:
    """``menu_select`` the named entry of a chat room ≡ menu; False (menu closed) when the
    menu is of an unknown layout or the entry is not on it."""
    row = room_menu_row(menu, entry)
    if row is None:
        win32gui.PostMessage(menu, win32con.WM_CLOSE, 0, 0)
        return False
    return menu_select(menu, row)


def menu_select(menu: int, from_bottom: float) -> bool:
    """Pick the ``EVA_Menu`` entry whose center is ``from_bottom`` px (100% scale) above
    the menu's bottom edge, with posted keys: no click, no focus.

    Down moves the highlight one entry at a time from the top (a fresh menu has none);
    Enter is sent only once the highlight is seen on the target row, so a wrong count
    never runs a wrong entry. Up is never used: on a fresh menu it jumps to the last
    entry, which in a chat room is "채팅방 나가기". Returns False (menu closed) when
    the highlight runs past the end without reaching the row.
    """
    _, top, _, bottom = win32gui.GetWindowRect(menu)
    target = (bottom - top) - px(menu, from_bottom)
    tol = px(menu, config.MENU_ROW_TOLERANCE)
    base = ocr.grab_window(menu)
    band = None
    for _ in range(config.MENU_MAX_ENTRIES):
        _post_key(menu, VK_DOWN)
        prev, end = band, time.time() + config.MENU_KEY_WAIT_SEC
        while time.time() < end:
            time.sleep(0.05)
            band = highlighted_band(base, ocr.grab_window(menu))
            if band != prev:
                break
        if band is None or band == prev:  # ran past the last entry, or the key was ignored
            break
        center = (band[0] + band[1]) / 2
        if abs(center - target) <= tol:
            _post_key(menu, VK_RETURN)
            return True
        if center > target + tol:
            break  # already below the target row
    win32gui.PostMessage(menu, win32con.WM_CLOSE, 0, 0)
    return False
