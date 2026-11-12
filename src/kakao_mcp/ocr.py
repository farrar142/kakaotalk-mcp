"""Screen capture + Windows built-in OCR (Windows.Media.Ocr) helpers.

KakaoTalk draws most of its UI itself (no UIA/Win32 children for list items),
so text in open-chat lists, menus and dialogs is read via OCR.
Requires the Korean OCR language (installed with the Korean language pack).
"""
import asyncio
import ctypes
import difflib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import win32gui
from PIL import Image, ImageGrab

ctypes.windll.user32.SetProcessDPIAware()

# OCR runs on its own thread so it works both inside and outside an event loop
_executor = ThreadPoolExecutor(max_workers=1)
_engine = None


PW_RENDERFULLCONTENT = 2
GA_ROOT = 2


def _print_window(root: int) -> Optional[Image.Image]:
    """Render a top-level window into a bitmap (PrintWindow): works while it is covered."""
    import win32ui
    l, t, r, b = win32gui.GetWindowRect(root)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None
    wdc = win32gui.GetWindowDC(root)
    src = win32ui.CreateDCFromHandle(wdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    try:
        bmp.CreateCompatibleBitmap(src, w, h)
        mem.SelectObject(bmp)
        if not ctypes.windll.user32.PrintWindow(root, mem.GetSafeHdc(), PW_RENDERFULLCONTENT):
            return None
        return Image.frombuffer("RGB", (w, h), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(root, wdc)


def grab_window(hwnd: int) -> Image.Image:
    """Capture a window's pixels without bringing it to the front.

    Renders its top-level window with PrintWindow and crops to ``hwnd``. A minimized
    window or a failed/blank render falls back to the on-screen pixels (ImageGrab),
    which need the window visible and unobscured.
    """
    rect = win32gui.GetWindowRect(hwnd)
    root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    if not ctypes.windll.user32.IsIconic(root):
        try:
            img = _print_window(root)
        except Exception:
            img = None
        if img is not None and img.convert("L").getextrema()[0] != img.convert("L").getextrema()[1]:
            rl, rt = win32gui.GetWindowRect(root)[:2]
            return img.crop((rect[0] - rl, rect[1] - rt, rect[2] - rl, rect[3] - rt))
    return ImageGrab.grab(bbox=rect, all_screens=True)


def _get_engine():
    global _engine
    if _engine is None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        _engine = OcrEngine.try_create_from_language(Language("ko"))
        if _engine is None:
            raise RuntimeError("Korean OCR language is not installed")
    return _engine


async def _recognize_async(img: Image.Image):
    from winrt.windows.graphics.imaging import (
        BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap,
    )
    from winrt.windows.storage.streams import DataWriter

    r, g, b, a = img.convert("RGBA").split()
    writer = DataWriter()
    writer.write_bytes(Image.merge("RGBA", (b, g, r, a)).tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8,
        img.width, img.height, BitmapAlphaMode.PREMULTIPLIED,
    )
    result = await _get_engine().recognize_async(bitmap)
    lines = []
    for line in result.lines:
        words = list(line.words)
        rects = [w.bounding_rect for w in words]
        x0 = min(r.x for r in rects)
        y0 = min(r.y for r in rects)
        x1 = max(r.x + r.width for r in rects)
        y1 = max(r.y + r.height for r in rects)
        lines.append({"text": line.text, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return lines


def recognize(img: Image.Image, scale: float = 2.0) -> List[Dict]:
    """OCR an image. Returns lines with text and bbox in *original* image pixels.

    Upscaling (default 2x) noticeably improves accuracy on KakaoTalk's small fonts.
    """
    src = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    lines = _executor.submit(asyncio.run, _recognize_async(src)).result(timeout=30)
    for ln in lines:
        for k in ("x", "y", "w", "h"):
            ln[k] = ln[k] / scale
        ln["cx"] = ln["x"] + ln["w"] / 2
        ln["cy"] = ln["y"] + ln["h"] / 2
    lines.sort(key=lambda ln: (round(ln["y"]), ln["x"]))
    return lines


def normalize(text: str) -> str:
    """Normalize text for fuzzy matching (drop spaces/punct, fold common OCR confusions)."""
    t = re.sub(r"[\s\W_]+", "", text.lower())
    for a, b in (("재", "채"), ("으", "오"), ("틔", "퇴")):
        t = t.replace(a, b)
    return t


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    short, long_ = sorted((na, nb), key=len)
    # Containment only counts when lengths are comparable, so a stray "다."
    # doesn't match "위 내용을 모두 확인하였습니다".
    if short in long_ and len(short) >= 0.6 * len(long_):
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def find_line(lines: List[Dict], target: str, threshold: float = 0.6,
              exclude: Optional[List[str]] = None) -> Optional[Dict]:
    """Return the OCR line best matching ``target`` (or None below threshold)."""
    best, best_score = None, threshold
    for ln in lines:
        if exclude and any(normalize(e) in normalize(ln["text"]) for e in exclude):
            continue
        score = similarity(ln["text"], target)
        if score > best_score or (score == best_score == 1.0 and best is None):
            best, best_score = ln, score
    return best


def line_darkness(img: Image.Image, line: Dict) -> int:
    """Minimum luminance inside a line's bbox (lower = darker text, e.g. titles)."""
    box = (int(line["x"]), int(line["y"]), int(line["x"] + line["w"]) + 1, int(line["y"] + line["h"]) + 1)
    lo, _ = img.crop(box).convert("L").getextrema()
    return lo
