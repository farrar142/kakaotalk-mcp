"""Template matching (templates.py): fixed spot, a few px of shift, display scale."""
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from kakao_mcp import config, screen, templates

NAME = "link_warning"
DIALOG = (262, 182)


def _dialog(offset=(0, 0), scale=1.0, text=None):
    """A white 262x182 dialog with the template (or ``text``) at its spot."""
    shot = Image.new("L", DIALOG, 255)
    x, y = templates.POSITIONS[NAME]
    if text is None:
        shot.paste(Image.open(templates.DIR / f"{NAME}.png"), (x + offset[0], y + offset[1]))
    else:
        ImageDraw.Draw(shot).text((x + 2, y + 1), text, font=ImageFont.truetype("malgun.ttf", 15), fill=0)
    if scale != 1.0:
        shot = shot.resize((round(DIALOG[0] * scale), round(DIALOG[1] * scale)), Image.LANCZOS)
    return shot


def test_same_picture_scores_zero():
    assert templates.score(_dialog(), NAME) == 0.0


def test_blank_or_other_text_does_not_match():
    assert templates.score(Image.new("L", DIALOG, 255), NAME) == 1.0
    assert not templates.matches(_dialog(text="김지애"), NAME)


def test_small_shift_is_allowed():
    assert templates.matches(_dialog(offset=(2, -2)), NAME)
    assert not templates.matches(_dialog(offset=(config.TEMPLATE_MAX_SHIFT + 6, 0)), NAME)


def test_other_display_scales():
    for scale in (1.25, 1.5, 2.0):
        assert templates.matches(_dialog(scale=scale), NAME, scale), scale


def test_window_matches_uses_the_window_shot_and_scale():
    with patch.object(templates.ocr, "grab_window", return_value=_dialog(scale=1.5)) as grab, \
            patch.object(screen, "dpi_scale", return_value=1.5):
        assert templates.window_matches(5, NAME)
    grab.assert_called_once_with(5)
