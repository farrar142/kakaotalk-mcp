"""Cut a template image for ``kakao_mcp.templates`` from a window or a saved shot.

    uv run python scripts/capture_template.py NAME LEFT TOP RIGHT BOTTOM --hwnd 0x1234
    uv run python scripts/capture_template.py NAME LEFT TOP RIGHT BOTTOM --image shot.png

The box is window-relative, at 100% display scale. Leave 2 px of background around
the mark. Then add ``"NAME": (LEFT, TOP)`` to ``templates.POSITIONS`` and check the
score against the window it should match (~0) and ones it should not (~1).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from kakao_mcp import ocr, templates  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("box", nargs=4, type=int, metavar="LEFT TOP RIGHT BOTTOM")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--hwnd", type=lambda v: int(v, 0))
    src.add_argument("--image")
    args = ap.parse_args()
    shot = ocr.grab_window(args.hwnd) if args.hwnd else Image.open(args.image)
    path = templates.cut(shot, args.name, tuple(args.box))
    print(f"saved {path}")
    print(f'POSITIONS entry: "{args.name}": ({args.box[0]}, {args.box[1]}),')


if __name__ == "__main__":
    main()
