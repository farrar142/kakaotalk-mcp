"""grab_window: PrintWindow first (works while covered), on-screen pixels as the fallback."""
from unittest.mock import patch

from PIL import Image

from kakao_mcp import ocr

RECTS = {1: (100, 200, 500, 800), 2: (150, 300, 450, 700)}  # 1 = top-level room, 2 = its child


def _rendered():
    img = Image.new("RGB", (400, 600), "white")
    img.putpixel((60, 110), (0, 0, 0))  # inside the child's area
    return img


def _patches(iconic=False, rendered=None):
    return [
        patch.object(ocr.win32gui, "GetWindowRect", side_effect=lambda h: RECTS[h]),
        patch.object(ocr.ctypes.windll.user32, "GetAncestor", return_value=1),
        patch.object(ocr.ctypes.windll.user32, "IsIconic", return_value=iconic),
        patch.object(ocr, "_print_window", return_value=rendered),
        patch.object(ocr.ImageGrab, "grab", return_value=Image.new("RGB", (1, 1))),
    ]


def _run(hwnd, **kw):
    ps = _patches(**kw)
    mocks = [p.start() for p in ps]
    try:
        return ocr.grab_window(hwnd), mocks[-1]
    finally:
        for p in ps:
            p.stop()


def test_child_is_cropped_from_the_rendered_top_level_window():
    img, screen = _run(2, rendered=_rendered())
    assert img.size == (300, 400)
    assert img.getpixel((10, 10)) == (0, 0, 0)  # (60,110) in the room = (10,10) in the child
    screen.assert_not_called()


def test_minimized_window_falls_back_to_screen_pixels():
    _, screen = _run(1, iconic=True, rendered=_rendered())
    screen.assert_called_once_with(bbox=RECTS[1], all_screens=True)


def test_blank_render_falls_back_to_screen_pixels():
    _, screen = _run(1, rendered=Image.new("RGB", (400, 600), "black"))
    screen.assert_called_once()


def test_failed_render_falls_back_to_screen_pixels():
    _, screen = _run(1, rendered=None)
    screen.assert_called_once()
