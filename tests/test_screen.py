"""screen.menu_select: posted Down until the highlight reaches the row, then Enter."""
from unittest.mock import patch

from PIL import Image, ImageDraw

from kakao_mcp import screen

# 1:1 room menu (225x298): row centers measured on KakaoTalk PC 26.9
ROWS = [20, 57, 83, 109, 135, 172, 209, 246]
HEIGHT = 298


class FakeMenu:
    """Draws the highlight on the row the posted Downs reached (none past the end)."""

    def __init__(self, rows=ROWS, ignore_keys=0):
        self.rows, self.downs, self.keys, self.ignore = rows, 0, [], ignore_keys

    def post(self, hwnd, vk):
        self.keys.append(vk)
        if vk == screen.VK_DOWN:
            if self.ignore:
                self.ignore -= 1
            else:
                self.downs += 1

    def shot(self, hwnd):
        img = Image.new("L", (225, HEIGHT), 255)
        if 1 <= self.downs <= len(self.rows):
            c = self.rows[self.downs - 1]
            ImageDraw.Draw(img).rectangle((0, c - 13, 224, c + 12), fill=235)
        return img


def _select(fake, from_bottom):
    with patch.object(screen, "_post_key", side_effect=fake.post), \
            patch.object(screen.ocr, "grab_window", side_effect=fake.shot), \
            patch.object(screen, "dpi_scale", return_value=1.0), \
            patch.object(screen.win32gui, "GetWindowRect", return_value=(0, 0, 225, HEIGHT)), \
            patch.object(screen.win32gui, "PostMessage") as close, \
            patch.object(screen.time, "sleep"):
        return screen.menu_select(7, from_bottom), close


def test_enter_on_the_row_at_that_distance():
    fake = FakeMenu()
    ok, close = _select(fake, 189)  # 톡게시판
    assert ok and fake.downs == 4
    assert fake.keys == [screen.VK_DOWN] * 4 + [screen.VK_RETURN]
    assert not close.called


def test_never_enter_when_no_row_is_there():
    fake = FakeMenu()
    ok, close = _select(fake, 100)  # between rows
    assert not ok and screen.VK_RETURN not in fake.keys
    close.assert_called_once()


def test_up_is_never_sent():
    """Up on a fresh menu jumps to the last entry, "채팅방 나가기"."""
    fake = FakeMenu()
    _select(fake, 52)
    assert 0x26 not in fake.keys


def test_ignored_key_stops_without_enter():
    fake = FakeMenu(ignore_keys=99)
    ok, close = _select(fake, 189)
    assert not ok and screen.VK_RETURN not in fake.keys
    close.assert_called_once()


def _row(size, entry, scale=1.0):
    w, h = size
    with patch.object(screen.win32gui, "GetWindowRect", return_value=(100, 50, 100 + w, 50 + h)), \
            patch.object(screen, "dpi_scale", return_value=scale):
        return screen.room_menu_row(7, entry)


def test_room_menu_layout_by_size():
    assert _row((225, 298), "톡게시판") == 189
    assert _row((225, 324), "톡게시판") == 189
    assert _row((179, 335), "톡게시판") == 252  # open chat (owner): 189 there is "오픈채팅 관리"
    assert _row((179, 335), "채팅방 URL 복사") == 315


def test_room_menu_layout_scaled():
    assert _row((338, 486), "톡게시판", scale=1.5) == 189


def test_unknown_menu_or_entry_gives_none():
    assert _row((200, 400), "톡게시판") is None
    assert _row((225, 298), "채팅방 URL 복사") is None


def test_room_menu_select_closes_unknown_menu():
    with patch.object(screen, "room_menu_row", return_value=None), \
            patch.object(screen, "menu_select") as select, \
            patch.object(screen.win32gui, "PostMessage") as close:
        assert screen.room_menu_select(7, "톡게시판") is False
    select.assert_not_called()
    close.assert_called_once()
