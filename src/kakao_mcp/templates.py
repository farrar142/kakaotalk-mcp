"""Reference images (templates) that tell KakaoTalk windows apart without OCR.

Each template is a small grayscale PNG in ``templates/``, cut at 100% display scale
from a fixed position of a window (``POSITIONS``). Matching compares the "ink"
(dark pixels) of the template with the same spot of a window shot, allowing a
few pixels of shift: ``score`` is the share of the template's ink that differs,
0.0 for the same picture, around 1.0 for blank or different text.

Callers normally use ``window_matches(hwnd, name)``, which takes the shot and the
display scale itself. New templates: ``python scripts/capture_template.py``.
"""
import functools
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageChops

from . import config, ocr, screen

DIR = Path(__file__).parent / "templates"

# name -> (x, y) of the template's top-left corner in its window, at 100% scale
POSITIONS: Dict[str, Tuple[int, int]] = {
    "link_warning": (24, 27),  # "주의" heading of the link confirmation (262x182)
    "openchat_make": (339, 154),  # "+ 만들기" on the open chat home (420x640) scrolled to the top
    "form_topics": (20, 203),  # "채팅방 주제" on the create form scrolled 3 notches from the top
    "form_join_settings": (20, 184),  # "참여 설정" on the create form scrolled to the bottom
}

# Menu row labels: name -> (x, y offset from the row's center), at 100% scale
ROW_LABELS: Dict[str, Tuple[int, int]] = {
    "menu_leave": (38, -8),  # "채팅방 나가기" (not "신고하고 나가기")
}


def _ink(img: Image.Image) -> Image.Image:
    return img.convert("L").point(lambda v: 255 if v < config.TEMPLATE_INK_LUMA else 0)


@functools.lru_cache(maxsize=None)
def _load(name: str) -> Image.Image:
    return _ink(Image.open(DIR / f"{name}.png"))


def score(shot: Image.Image, name: str, scale: float = 1.0,
          at: Optional[Tuple[float, float]] = None) -> float:
    """Best (lowest) ink mismatch of template ``name`` around its spot in ``shot``
    (``POSITIONS[name]``, or ``at``: top-left at 100% scale).

    At other display scales the spot is cut at its scaled size and shrunk back to
    100% before comparing, which keeps strokes as thick as in the template.
    """
    tpl = _load(name)
    ink = tpl.histogram()[255]
    if not ink:
        raise ValueError(f"template {name!r} has no ink")
    w, h = round(tpl.width * scale), round(tpl.height * scale)
    x0, y0 = (round(v * scale) for v in (at or POSITIONS[name]))
    shift = round(config.TEMPLATE_MAX_SHIFT * scale)
    best = 1.0
    for dy in range(-shift, shift + 1):
        for dx in range(-shift, shift + 1):
            box = (x0 + dx, y0 + dy, x0 + dx + w, y0 + dy + h)
            if box[0] < 0 or box[1] < 0 or box[2] > shot.width or box[3] > shot.height:
                continue
            region = shot.crop(box).convert("L")
            if (w, h) != tpl.size:
                region = region.resize(tpl.size, Image.LANCZOS)
            diff = ImageChops.difference(tpl, _ink(region)).histogram()[255]
            best = min(best, diff / ink)
    return best


def matches(shot: Image.Image, name: str, scale: float = 1.0) -> bool:
    """``shot`` (taken at ``scale``) shows template ``name`` at its spot."""
    return score(shot, name, scale) <= config.TEMPLATE_MAX_MISMATCH


def row_matches(shot: Image.Image, name: str, from_bottom: float, scale: float = 1.0) -> bool:
    """The menu row centered ``from_bottom`` px (100% scale) above the bottom of ``shot``
    shows the label template ``name`` (``ROW_LABELS``)."""
    x, dy = ROW_LABELS[name]
    at = (x, shot.height / scale - from_bottom + dy)
    return score(shot, name, scale, at=at) <= config.TEMPLATE_MAX_MISMATCH


def window_matches(hwnd: int, name: str) -> bool:
    """Window ``hwnd`` shows template ``name``: shot with PrintWindow (works behind
    other windows), compared at the window's display scale."""
    return matches(ocr.grab_window(hwnd), name, screen.dpi_scale(hwnd))


def cut(shot: Image.Image, name: str, box: Tuple[int, int, int, int]) -> Path:
    """Save ``box`` (left, top, right, bottom; a 100% scale shot) of ``shot`` as template ``name``."""
    DIR.mkdir(exist_ok=True)
    path = DIR / f"{name}.png"
    shot.crop(box).convert("L").save(path)
    return path
