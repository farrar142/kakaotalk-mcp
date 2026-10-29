"""Mock-based unit tests for kakao_mcp.controller."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from kakao_mcp import controller, config


# ---------------------------------------------------------------------------
# is_kakaotalk_running
# ---------------------------------------------------------------------------

@patch("kakao_mcp.controller.win32process")
@patch("kakao_mcp.controller.win32gui")
def test_is_running_true(mock_gui, mock_proc):
    mock_gui.FindWindow.return_value = 12345
    mock_proc.GetWindowThreadProcessId.return_value = (0, 9876)
    result = controller.is_kakaotalk_running()
    assert result["running"] is True
    assert result["hwnd"] == 12345
    assert result["pid"] == 9876
    mock_gui.FindWindow.assert_called_once_with(
        config.KAKAO_MAIN_WINDOW_CLASS, config.KAKAO_MAIN_WINDOW_TITLE
    )


@patch("kakao_mcp.controller.win32gui")
def test_is_running_false(mock_gui):
    mock_gui.FindWindow.return_value = 0
    result = controller.is_kakaotalk_running()
    assert result["running"] is False
    assert result["hwnd"] is None


# ---------------------------------------------------------------------------
# find_chat_window
# ---------------------------------------------------------------------------

@patch("kakao_mcp.controller.win32gui")
def test_find_chat_window_found(mock_gui):
    # Simulate EnumWindows calling the callback with a matching window
    def enum_side_effect(callback, _):
        # Simulate a matching window
        mock_gui.IsWindowVisible.return_value = True
        mock_gui.GetClassName.return_value = config.KAKAO_CHAT_WINDOW_CLASS
        mock_gui.GetWindowText.return_value = "TestRoom"
        callback(99999, None)

    mock_gui.EnumWindows.side_effect = enum_side_effect
    result = controller.find_chat_window("TestRoom")
    assert result == 99999


@patch("kakao_mcp.controller.win32gui")
def test_find_chat_window_not_found(mock_gui):
    def enum_side_effect(callback, _):
        mock_gui.IsWindowVisible.return_value = True
        mock_gui.GetClassName.return_value = config.KAKAO_CHAT_WINDOW_CLASS
        mock_gui.GetWindowText.return_value = "OtherRoom"
        callback(99999, None)

    mock_gui.EnumWindows.side_effect = enum_side_effect
    result = controller.find_chat_window("TestRoom")
    assert result is None


# ---------------------------------------------------------------------------
# list_chat_windows
# ---------------------------------------------------------------------------

@patch("kakao_mcp.controller.win32gui")
def test_list_chat_windows(mock_gui):
    mock_gui.FindWindow.return_value = 10000  # main window

    call_count = [0]
    rooms_data = [
        (10000, config.KAKAO_MAIN_WINDOW_TITLE),  # main window — should be excluded
        (20001, "Room A"),
        (20002, "Room B"),
    ]

    def enum_side_effect(callback, _):
        for hwnd, title in rooms_data:
            mock_gui.IsWindowVisible.return_value = True
            mock_gui.GetClassName.return_value = config.KAKAO_CHAT_WINDOW_CLASS
            mock_gui.GetWindowText.return_value = title
            callback(hwnd, None)

    mock_gui.EnumWindows.side_effect = enum_side_effect
    result = controller.list_chat_windows()
    titles = [r["title"] for r in result]
    assert "Room A" in titles
    assert "Room B" in titles
    assert config.KAKAO_MAIN_WINDOW_TITLE not in titles


# ---------------------------------------------------------------------------
# send_message_to_room
# ---------------------------------------------------------------------------

PLACEHOLDER = "메시지 입력"


def _send_patches(edit_texts, foreground=11111, activate_error=None):
    """Patch every input/clipboard side effect of send_message_to_room."""
    return [
        patch("kakao_mcp.controller.find_chat_window", return_value=11111),
        patch("kakao_mcp.controller.find_child_window_recursive", return_value=22222),
        patch("kakao_mcp.controller.activate_window", return_value=activate_error),
        patch("kakao_mcp.controller._edit_text", side_effect=edit_texts),
        patch("kakao_mcp.controller._send_ctrl_key_combo"),
        patch("kakao_mcp.controller._user32", **{"GetForegroundWindow.return_value": foreground}),
        patch("kakao_mcp.controller.win32clipboard"),
        patch("kakao_mcp.controller.win32gui", **{"GetWindowRect.return_value": (0, 0, 100, 100)}),
        patch("kakao_mcp.controller.time.sleep"),
    ]


def _run_send(patches):
    import contextlib
    with contextlib.ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        result = controller.send_message_to_room("TestRoom", "Hello")
        return result, mocks


def test_send_message_success():
    # placeholder -> pasted -> back to placeholder after Enter
    result, mocks = _run_send(_send_patches([PLACEHOLDER, "Hello", PLACEHOLDER]))
    assert result["success"] is True
    assert "sent" in result["message"].lower()
    mocks[4].assert_called_once_with(0x56)  # Ctrl+V


def test_send_message_refuses_without_foreground():
    result, mocks = _run_send(_send_patches([PLACEHOLDER], activate_error="no fg"))
    assert result == {"success": False, "error": "no fg"}
    mocks[4].assert_not_called()  # no keystrokes when the window isn't focused


def test_send_message_paste_not_landed():
    result, mocks = _run_send(_send_patches([PLACEHOLDER, PLACEHOLDER]))
    assert result["success"] is False and "Paste did not reach" in result["error"]
    mocks[5].keybd_event.assert_not_called()  # Enter is never pressed


def test_send_message_not_cleared_after_enter():
    result, _ = _run_send(_send_patches([PLACEHOLDER, "Hello"] + ["Hello"] * 10))
    assert result["success"] is False and "not sent" in result["error"]


@patch("kakao_mcp.controller.find_chat_window")
def test_send_message_room_not_found(mock_find):
    mock_find.return_value = None
    result = controller.send_message_to_room("NoRoom", "Hello")
    assert result["success"] is False
    assert "not found" in result["error"]


@patch("kakao_mcp.controller.find_child_window_recursive")
@patch("kakao_mcp.controller.find_chat_window")
def test_send_message_no_edit_control(mock_find, mock_child):
    mock_find.return_value = 11111
    mock_child.return_value = None
    result = controller.send_message_to_room("TestRoom", "Hello")
    assert result["success"] is False
    assert "edit control" in result["error"].lower()


# ---------------------------------------------------------------------------
# read_chat_messages
# ---------------------------------------------------------------------------

@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.find_child_window_recursive")
@patch("kakao_mcp.controller.find_chat_window")
def test_read_messages_success(mock_find, mock_child, mock_gui, mock_user32, mock_ctrl, mock_clip,
                               mock_activate, mock_empty, mock_sleep, mock_focus, mock_guard, _sweep):
    mock_guard.return_value.check.return_value = []
    mock_user32.GetForegroundWindow.return_value = 11111
    mock_find.return_value = 11111
    mock_child.return_value = 33333
    mock_gui.GetWindowRect.return_value = (0, 0, 100, 100)
    mock_clip.return_value = "[Room] [대화상대 2명]\n[A] [오전 10:00] Hello"
    result = controller.read_chat_messages("Room")
    assert result["success"] is True
    assert "Hello" in result["raw_text"]
    assert mock_empty.call_count == 2  # cleared before the copy and before its confirming copy
    mock_focus.assert_called_once_with(11111, 33333)
    mock_user32.mouse_event.assert_not_called()  # the message list is never clicked (links)
    assert "link_warnings" not in result


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text", return_value="")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_empty_clipboard_is_error(*mocks):
    mocks[-2].return_value.check.return_value = []
    result = controller.read_chat_messages("Room")
    assert result["success"] is False and "Nothing was copied" in result["error"]


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=False)
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_unfocusable_list_is_error_without_typing(mock_find, mock_child, mock_activate,
                                                               mock_ctrl, mock_focus, mock_guard, _sweep):
    result = controller.read_chat_messages("Room")
    assert result["success"] is False and "focus the message list" in result["error"]
    mock_ctrl.assert_not_called()


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_retries_after_closing_a_link_window(mock_find, mock_child, mock_ctrl, mock_clip,
                                                           mock_activate, mock_empty, mock_sleep,
                                                           mock_focus, mock_guard, _sweep):
    mock_guard.return_value.check.side_effect = [["closed browser window 'x'"], []]
    mock_clip.side_effect = ["https://example.com", "https://example.com",
                             "[A] [오전 10:00] Hello", "[A] [오전 10:00] Hello"]
    with patch.object(controller, "_user32") as u32:
        u32.GetForegroundWindow.return_value = 11111
        result = controller.read_chat_messages("Room")
    assert result["success"] is True and "Hello" in result["raw_text"]
    assert result["link_warnings"] == ["closed browser window 'x'"]
    assert mock_focus.call_count == 2


class TestLinkGuard:
    KAKAO, BROWSER = 100, 200

    def _guard(self, before, after, fg, strict=False, webview=()):
        exes = {self.KAKAO: "kakaotalk.exe", self.BROWSER: "chrome.exe"}
        with patch.object(controller, "_top_windows", side_effect=[before, after]), \
                patch.object(controller, "_user32") as u32, \
                patch.object(controller, "win32gui") as gui, \
                patch.object(controller, "win32process") as proc, \
                patch.object(controller, "_exe_name", side_effect=lambda pid: exes[pid]), \
                patch.object(controller, "_has_webview", side_effect=lambda h: h in webview), \
                patch.object(controller, "_send_ctrl_key_combo") as ctrl, \
                patch.object(controller, "bring_window_to_front") as front, \
                patch.object(controller.time, "sleep"):
            gui.FindWindow.return_value = 1
            gui.GetWindowText.return_value = "title"
            gui.IsWindowVisible.return_value = False  # closed windows are gone at once
            gui.GetWindow.return_value = 0  # no window is the main window's ad banner
            proc.GetWindowThreadProcessId.return_value = (0, self.KAKAO)
            u32.GetForegroundWindow.return_value = fg
            guard = controller.LinkGuard("test", strict=strict)
            events = guard.check()
            return events, gui.PostMessage, ctrl, front

    def test_nothing_new(self):
        win = {1: (self.KAKAO, "카카오톡"), 5: (self.BROWSER, "Docs")}
        events, post, ctrl, front = self._guard(win, win, fg=1)
        assert events == [] and not post.called and not front.called

    def test_new_foreground_browser_window_is_closed(self):
        before = {1: (self.KAKAO, "카카오톡")}
        events, post, _, front = self._guard(before, {**before, 9: (self.BROWSER, "YouTube")}, fg=9)
        assert len(events) == 1 and "browser window" in events[0]
        post.assert_called_once_with(9, controller.win32con.WM_CLOSE, 0, 0)
        front.assert_called_once()

    def test_background_browser_window_is_closed_too(self):
        before = {1: (self.KAKAO, "카카오톡")}
        events, post, _, _ = self._guard(before, {**before, 9: (self.BROWSER, "YouTube")}, fg=1)
        assert len(events) == 1
        post.assert_called_once_with(9, controller.win32con.WM_CLOSE, 0, 0)

    def test_unread_counter_title_change_is_ignored(self):
        before = {1: (self.KAKAO, "카카오톡"), 5: (self.BROWSER, "(1) YouTube")}
        events, post, ctrl, _ = self._guard(before, {1: before[1], 5: (self.BROWSER, "(2) YouTube")}, fg=1)
        assert events == [] and not ctrl.called

    def test_new_tab_in_existing_browser_is_closed_with_ctrl_w(self):
        before = {1: (self.KAKAO, "카카오톡"), 5: (self.BROWSER, "Docs")}
        events, post, ctrl, _ = self._guard(before, {1: before[1], 5: (self.BROWSER, "pickle.com")}, fg=5)
        assert "browser tab" in events[0]
        ctrl.assert_called_once_with(0x57)
        assert not post.called

    def test_new_kakao_webview_is_closed(self):
        before = {1: (self.KAKAO, "카카오톡")}
        events, post, _, _ = self._guard(before, {**before, 7: (self.KAKAO, "")}, fg=7, webview={7})
        assert "KakaoTalk window" in events[0]
        post.assert_called_once_with(7, controller.win32con.WM_CLOSE, 0, 0)

    def test_new_kakao_dialog_only_counts_when_strict(self):
        before = {1: (self.KAKAO, "카카오톡")}
        after = {**before, 7: (self.KAKAO, "방 이름")}
        assert self._guard(before, after, fg=7)[0] == []
        events, post, _, _ = self._guard(before, after, fg=7, strict=True)
        assert len(events) == 1


@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.activate_window", return_value="no fg")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_refuses_without_foreground(mock_find, mock_child, mock_activate, mock_ctrl):
    result = controller.read_chat_messages("Room")
    assert result == {"success": False, "error": "no fg", "raw_text": ""}
    mock_ctrl.assert_not_called()


@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._log")
@patch("kakao_mcp.controller.bring_window_to_front")
@patch("kakao_mcp.controller._user32")
def test_activate_window_reports_failure(mock_user32, mock_front, mock_log, mock_sleep):
    mock_user32.GetForegroundWindow.return_value = 999
    assert "foreground" in controller.activate_window(11111, "Room")
    mock_user32.GetForegroundWindow.return_value = 11111
    assert controller.activate_window(11111, "Room") is None


@patch("kakao_mcp.controller.find_chat_window")
def test_read_messages_room_not_found(mock_find):
    mock_find.return_value = None
    result = controller.read_chat_messages("NoRoom")
    assert result["success"] is False


# ---------------------------------------------------------------------------
# get_kakao_user_hash_dir
# ---------------------------------------------------------------------------

@patch("os.listdir")
@patch("os.path.isdir")
def test_get_user_hash_dir_found(mock_isdir, mock_listdir):
    mock_isdir.return_value = True
    mock_listdir.return_value = ["a" * 40, "not_a_hash"]

    # Make only the 40-char entry look like a directory
    def isdir_side(path):
        return True

    mock_isdir.side_effect = isdir_side
    result = controller.get_kakao_user_hash_dir()
    assert result is not None
    assert "a" * 40 in result


@patch("os.path.isdir")
def test_get_user_hash_dir_no_users_dir(mock_isdir):
    mock_isdir.return_value = False
    result = controller.get_kakao_user_hash_dir()
    assert result is None


# ---------------------------------------------------------------------------
# _copy_image_to_clipboard
# ---------------------------------------------------------------------------

@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller.subprocess")
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value="C:\\test\\image.jpg")
def test_copy_image_to_clipboard_success(mock_abs, mock_isfile, mock_subprocess,
                                          mock_clipboard):
    # Fake BMP data: 14-byte file header + 40-byte info header + pixel data
    fake_bmp = b"BM" + b"\x00" * 12 + b"\x00" * 40 + b"\xff" * 100
    mock_result = mock_subprocess.run.return_value
    mock_result.returncode = 0
    mock_result.stdout = fake_bmp
    controller._copy_image_to_clipboard("C:\\test\\image.jpg")
    mock_subprocess.run.assert_called_once()
    call_args = mock_subprocess.run.call_args[0][0]
    assert call_args[0] == "powershell"
    mock_clipboard.OpenClipboard.assert_called_once()
    mock_clipboard.EmptyClipboard.assert_called_once()
    mock_clipboard.SetClipboardData.assert_called_once()


@patch("os.path.isfile", return_value=False)
@patch("os.path.abspath", return_value="C:\\nonexistent.jpg")
def test_copy_image_to_clipboard_not_found(mock_abs, mock_isfile):
    with pytest.raises(FileNotFoundError):
        controller._copy_image_to_clipboard("C:\\nonexistent.jpg")


# ---------------------------------------------------------------------------
# send_image_to_room
# ---------------------------------------------------------------------------

@patch("kakao_mcp.controller._copy_image_to_clipboard")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.bring_window_to_front")
@patch("kakao_mcp.controller.find_child_window_recursive")
@patch("kakao_mcp.controller.find_chat_window")
@patch("os.path.splitext", return_value=("C:\\test\\image", ".jpg"))
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value="C:\\test\\image.jpg")
def test_send_image_success(mock_abs, mock_isfile, mock_split, mock_find,
                            mock_find_child, mock_bring, mock_ctrl,
                            mock_user32, mock_win32gui, mock_copy):
    mock_find.return_value = 11111
    mock_find_child.return_value = 22222
    mock_win32gui.GetWindowRect.return_value = (100, 100, 200, 120)
    # Simulate dialog appearing (foreground changes to a different window)
    mock_user32.GetForegroundWindow.side_effect = [11111, 33333]
    result = controller.send_image_to_room("TestRoom", "C:\\test\\image.jpg")
    assert result["success"] is True
    assert "sent" in result["message"].lower()
    mock_copy.assert_called_once()
    mock_bring.assert_called_once()


@patch("os.path.isfile", return_value=False)
@patch("os.path.abspath", return_value="C:\\nonexistent.jpg")
def test_send_image_file_not_found(mock_abs, mock_isfile):
    result = controller.send_image_to_room("TestRoom", "C:\\nonexistent.jpg")
    assert result["success"] is False
    assert "not found" in result["error"]


@patch("os.path.splitext", return_value=("C:\\test\\doc", ".pdf"))
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value="C:\\test\\doc.pdf")
def test_send_image_unsupported_format(mock_abs, mock_isfile, mock_split):
    result = controller.send_image_to_room("TestRoom", "C:\\test\\doc.pdf")
    assert result["success"] is False
    assert "unsupported" in result["error"].lower()


@patch("os.path.splitext", return_value=("C:\\test\\image", ".jpg"))
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value="C:\\test\\image.jpg")
@patch("kakao_mcp.controller.find_chat_window", return_value=None)
def test_send_image_room_not_found(mock_find, mock_abs, mock_isfile, mock_split):
    result = controller.send_image_to_room("NoRoom", "C:\\test\\image.jpg")
    assert result["success"] is False
    assert "not found" in result["error"]


@patch("kakao_mcp.controller.close_link_dialogs", return_value=["declined a leftover link confirmation"])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text", return_value="[A] [오전 10:00] Hello")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_reports_declined_leftover_link_dialog(*mocks):
    mocks[-2].return_value.check.return_value = []
    with patch.object(controller, "_user32") as u32:
        u32.GetForegroundWindow.return_value = 11111
        result = controller.read_chat_messages("Room")
    assert result["success"] is True
    assert result["link_warnings"] == ["declined a leftover link confirmation"]


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text", return_value="[A] [오전 10:00] Other room")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_discards_copy_when_room_lost_foreground(*mocks):
    mocks[-2].return_value.check.return_value = []
    with patch.object(controller, "_user32") as u32:
        u32.GetForegroundWindow.return_value = 22222  # another window took the keys
        result = controller.read_chat_messages("Room")
    assert result["success"] is False and result["raw_text"] == ""


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text", return_value="")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_empty_room_is_not_an_error(*mocks):
    mocks[-2].return_value.check.return_value = []
    with patch.object(controller, "_user32") as u32:
        u32.GetForegroundWindow.return_value = 11111  # focused and in front, nothing to copy
        result = controller.read_chat_messages("나와의 채팅")
    assert result == {"success": True, "raw_text": "", "empty": True}


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_partial_copy_is_not_accepted(mock_find, mock_child, mock_ctrl, mock_clip, *rest):
    rest[-2].return_value.check.return_value = []
    date_only = "2026년 10월 29일 목요일\r\n"
    full = date_only + "[나] [오후 4:49] 안녕하세요\r\n"
    # Ctrl+C before Ctrl+A finished selecting copies only the date line
    mock_clip.side_effect = [date_only, full, full, full]
    with patch.object(controller, "_user32") as u32:
        u32.GetForegroundWindow.return_value = 11111
        result = controller.read_chat_messages("나와의 채팅")
    assert result["raw_text"] == full


@patch("kakao_mcp.controller.close_link_dialogs", return_value=[])
@patch("kakao_mcp.controller.LinkGuard")
@patch("kakao_mcp.controller.focus_child", return_value=True)
@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller._empty_clipboard")
@patch("kakao_mcp.controller.activate_window", return_value=None)
@patch("kakao_mcp.controller._read_clipboard_text")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller.find_child_window_recursive", return_value=33333)
@patch("kakao_mcp.controller.find_chat_window", return_value=11111)
def test_read_messages_stuck_partial_selection_is_reselected(mock_find, mock_child, mock_ctrl, mock_clip, *rest):
    rest[-2].return_value.check.return_value = []
    first = "[나] [오후 4:49] 첫 메시지\r\n"
    both = first + "[나] [오후 4:54] 둘째\n- 여러 줄\r\n"
    # An early Ctrl+C leaves only the first bubble selected; copying again without
    # a new Ctrl+A would just repeat it
    mock_clip.side_effect = [first, both, both]
    with patch.object(controller, "_user32") as u32:
        u32.GetForegroundWindow.return_value = 11111
        result = controller.read_chat_messages("나와의 채팅")
    assert result["raw_text"] == both
    ctrl_a = [c for c in mock_ctrl.call_args_list if c.args == (config.VK_A,)]
    assert len(ctrl_a) == 3


def test_link_guard_skips_window_closed_during_check():
    with patch.object(controller, "_top_windows", side_effect=[{}, {5: (100, "")}]), \
            patch.object(controller, "_user32"), \
            patch.object(controller, "win32process") as proc, \
            patch.object(controller, "win32gui") as gui, \
            patch.object(controller, "_has_webview", return_value=False):
        gui.FindWindow.return_value = 1
        proc.GetWindowThreadProcessId.return_value = (0, 100)
        gui.GetWindowRect.side_effect = Exception("invalid window handle")
        gui.IsWindow.return_value = False
        guard = controller.LinkGuard("test", strict=False)
        assert guard.check() == []
