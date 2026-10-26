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
                               mock_activate, mock_empty, mock_sleep):
    mock_find.return_value = 11111
    mock_child.return_value = 33333
    mock_gui.GetWindowRect.return_value = (0, 0, 100, 100)
    mock_clip.return_value = "[Room] [대화상대 2명]\n[A] [오전 10:00] Hello"
    result = controller.read_chat_messages("Room")
    assert result["success"] is True
    assert "Hello" in result["raw_text"]
    mock_empty.assert_called_once()  # stale clipboard cleared before copying


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
    mocks[2].GetWindowRect.return_value = (0, 0, 100, 100)
    result = controller.read_chat_messages("Room")
    assert result["success"] is False and "Nothing was copied" in result["error"]


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
