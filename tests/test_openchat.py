"""Tests for open chat helpers that don't need a running KakaoTalk."""
from unittest.mock import patch

from PIL import Image

from kakao_mcp import ocr, openchat


def _list_image(width=418, height=409, separators=(105, 218), content_end=None):
    img = Image.new("RGB", (width, height), (255, 255, 255))
    for y in separators:
        for x in range(20, width - 20):
            img.putpixel((x, y), openchat.SEPARATOR_RGB)
    end = content_end if content_end is not None else height
    # some "text" in every row so rows aren't blank
    for y in list(range(10, end - 10, 30)) + [end - 1]:
        for x in range(30, 120):
            img.putpixel((x, y), (20, 20, 20))
    return img


class TestSplitItems:
    def test_rows_between_separators(self):
        spans = openchat._split_items(_list_image())
        assert spans == [(0, 105), (105, 218), (218, 409)]

    def test_blank_tail_makes_last_row_complete(self):
        img = _list_image(separators=(), content_end=110)
        spans = openchat._split_items(img)
        assert len(spans) == 1
        assert spans[0][1] < img.size[1]

    def test_tiny_spans_dropped(self):
        spans = openchat._split_items(_list_image(separators=(100, 120)))
        assert (100, 120) not in spans


class TestFuzzyMatching:
    def test_normalize_folds_ocr_confusions(self):
        assert ocr.normalize("재팅방 나가기") == ocr.normalize("채팅방 나가기")

    def test_similarity_substring(self):
        assert ocr.similarity("샌드코프 테스트", "샌드코프테스트") == 1.0

    def test_short_fragment_is_not_a_match(self):
        lines = [{"text": "다."}, {"text": "위 내용을 모두 확인하였습니다."}]
        assert ocr.find_line(lines, "위 내용을 모두 확인하였습니다")["text"].startswith("위")
        assert ocr.similarity("다.", "위 내용을 모두 확인하였습니다") < 0.6

    def test_find_line_excludes(self):
        lines = [{"text": "채팅방 나가기"}, {"text": "신고하고 나가기"}]
        assert ocr.find_line(lines, "나가기", exclude=["신고"])["text"] == "채팅방 나가기"

    def test_find_line_threshold(self):
        assert ocr.find_line([{"text": "전혀 다른 글"}], "채팅방 URL 복사", threshold=0.75) is None


class TestParseItem:
    def _parse(self, lines, darkness):
        img = _list_image()
        with patch.object(ocr, "recognize", return_value=lines), \
                patch.object(ocr, "line_darkness", side_effect=darkness):
            return openchat._parse_item(img, 105, 218)

    def _line(self, text, y):
        return {"text": text, "x": 20, "y": y, "w": 100, "h": 14, "cx": 70, "cy": y + 7}

    def test_title_desc_meta(self):
        item = self._parse(
            [self._line("0 파이썬 처음처럼", 10), self._line("#파이썬 #입장코드", 40), self._line("531경", 70)],
            [20, 140, 140],
        )
        assert item["title"] == "파이썬 처음처럼"
        assert item["description"] == "#파이썬 #입장코드"
        assert item["members"] == 531
        assert item["complete"] is True

    def test_two_line_title_and_activity(self):
        item = self._parse(
            [self._line("<코딩 테스트 합격자 되기>(파이썬/", 5), self._line("JS)", 25),
             self._line("#코딩 #알고리즘", 50), self._line("798옇 30분 전", 75)],
            [20, 20, 140, 140],
        )
        assert item["title"] == "<코딩 테스트 합격자 되기>(파이썬/ JS)"
        assert item["members"] == 798


class TestCommunityDialog:
    # OCR of the "커뮤니티 시작하기" dialog (302x365): body text, then the buttons
    LINES = [
        {"text": "커뮤니티 시작하기", "x": 30, "y": 24, "cx": 86, "cy": 31},
        {"text": "커뮤니티 메시지는 90일간 보관되며, 보관기간", "x": 30, "y": 175, "cx": 154, "cy": 182},
        {"text": "동의", "x": 70, "y": 318, "cx": 82, "cy": 325},
        {"text": "취소", "x": 206, "y": 318, "cx": 218, "cy": 325},
    ]

    def _answer(self, accept):
        with patch.object(openchat, "_ocr_window", return_value=self.LINES), \
                patch.object(openchat, "_size", return_value=(302, 365)), \
                patch.object(openchat, "_click") as click, \
                patch.object(openchat, "_wait_for", return_value=True):
            openchat._answer_dialog(1, "동의" if accept else "취소")
        return click.call_args.args

    def test_decline_clicks_cancel(self):
        assert self._answer(False) == (1, 218, 325)

    def test_accept_clicks_agree(self):
        assert self._answer(True) == (1, 82, 325)


class TestSafebotDialog:
    LINES = [
        {"text": "세이프봇 적용 동의", "x": 30, "y": 24, "cx": 86, "cy": 31},
        {"text": "동의하고 참여", "x": 60, "y": 318, "cx": 92, "cy": 325},
        {"text": "취소", "x": 206, "y": 318, "cx": 218, "cy": 325},
    ]

    def _click(self, label):
        with patch.object(openchat, "_ocr_window", return_value=self.LINES), \
                patch.object(openchat, "_size", return_value=(302, 365)), \
                patch.object(openchat, "_click") as click, \
                patch.object(openchat, "_wait_for", return_value=True):
            openchat._answer_dialog(1, label)
        return click.call_args.args

    def test_accept_clicks_agree_and_join(self):
        assert self._click("동의하고 참여") == (1, 92, 325)

    def test_decline_clicks_cancel(self):
        assert self._click("취소") == (1, 218, 325)

    def test_dismiss_falls_back_to_wm_close(self):
        with patch.object(openchat, "_answer_dialog", side_effect=openchat.UIError("no button")), \
                patch.object(openchat, "_is_open", return_value=True), \
                patch.object(openchat, "_wait_for", return_value=True), \
                patch.object(openchat.win32gui, "PostMessage") as post:
            openchat._dismiss(7)
        post.assert_called_once_with(7, openchat.WM_CLOSE, 0, 0)


class TestRateLimit:
    # OCR of the real dialog, garbled as it came back on 2026-10-29
    GARBLED = ("이용자보호조지로 인하 빠른 시간 내에 다수의 으픈재팅방이 참여할 수 없 / 도루 제한되었습니다. "
               "/ 잠시 후 다시 시도하 주세요. / 닫기 / 자세히 보기")

    def test_garbled_dialog_is_recognised(self):
        assert openchat.is_rate_limit_text(self.GARBLED)

    def test_other_dialogs_are_not(self):
        assert not openchat.is_rate_limit_text("세이프봇 적용 동의 / 동의하고 참여 / 취소")
        assert not openchat.is_rate_limit_text("참여 코드를 입력해 주세요 / 확인")
        assert not openchat.is_rate_limit_text("기본프로필만 참여 허용 / 확인")

    def test_closed_with_close_button(self):
        with patch.object(openchat, "_answer_dialog") as answer, \
                patch.object(openchat, "_is_open", return_value=False):
            err = openchat._close_rate_limit(5, self.GARBLED)
        answer.assert_called_once_with(5, "닫기")
        assert err.dialog_closed and err.dialog_text == self.GARBLED
        assert isinstance(err, openchat.UIError)

    def test_server_reports_error_code(self):
        from kakao_mcp import server

        def join(*a, **k):
            raise openchat.RateLimited(self.GARBLED, dialog_closed=True)

        with patch.object(server.controller, "is_kakaotalk_running", return_value={"running": True}), \
                patch.object(openchat, "_kakao_windows", return_value=set()), \
                patch.object(openchat, "check_rate_limit"):
            result = server._openchat_call(join)
        assert result["error_code"] == "rate_limited"
        assert result["dialog_closed"] is True and result["dialog_text"] == self.GARBLED

    def test_dialog_after_a_search_is_reported(self):
        from kakao_mcp import server

        def search(*a, **k):
            return {"success": True, "results": []}

        with patch.object(server.controller, "is_kakaotalk_running", return_value={"running": True}), \
                patch.object(openchat, "_kakao_windows", return_value=set()), \
                patch.object(openchat, "check_rate_limit",
                             side_effect=openchat.RateLimited(self.GARBLED, dialog_closed=True)):
            result = server._openchat_call(search)
        assert result["error_code"] == "rate_limited"


class TestEmptyRoomMenu:
    """A room whose join never completed opens its ≡ menu as a zero-size EVA_Menu."""

    def _open(self, menu_size):
        with patch.object(openchat.controller, "find_chat_window", return_value=1), \
                patch.object(openchat, "_kakao_windows", return_value=set()), \
                patch.object(openchat, "_click"), \
                patch.object(openchat, "_wait_new_window", return_value=2), \
                patch.object(openchat, "_size", side_effect=[(380, 640), menu_size]), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat.time, "sleep"), \
                patch.object(openchat.win32gui, "PostMessage") as post:
            try:
                return openchat._open_room_menu("room"), post
            except openchat.EmptyRoomMenu as e:
                return e, post

    def test_empty_menu_is_closed_and_reported(self):
        err, post = self._open((0, 0))
        assert isinstance(err, openchat.EmptyRoomMenu)
        post.assert_called_once_with(2, openchat.WM_CLOSE, 0, 0)

    def test_normal_menu_is_returned(self):
        menu, post = self._open((179, 335))
        assert menu == 2
        post.assert_not_called()

    def test_leave_closes_the_leftover_window(self):
        with patch.object(openchat.controller, "find_chat_window", return_value=1), \
                patch.object(openchat, "_open_room_menu", side_effect=openchat.EmptyRoomMenu("empty")), \
                patch.object(openchat, "_is_open", return_value=False), \
                patch.object(openchat.win32gui, "PostMessage") as post:
            result = openchat.leave_room("room")
        post.assert_called_once_with(1, openchat.WM_CLOSE, 0, 0)
        assert result["success"] and result["was_member"] is False and result["window_closed"]


class TestGetRoomLink:
    """The URL entry is picked by the menu's layout; a menu without it (not an open chat) is closed."""

    def _link(self, selected, clip=""):
        with patch.object(openchat, "_clear_clipboard"), \
                patch.object(openchat, "_open_room_menu", return_value=7) as menu, \
                patch.object(openchat, "_size", return_value=(225, 298)), \
                patch.object(openchat, "room_menu_select", return_value=selected) as select, \
                patch.object(openchat, "_read_clipboard", return_value=clip), \
                patch.object(openchat.time, "sleep"):
            return openchat.get_room_link("room"), select, menu

    def test_url_copied_in_the_background(self):
        result, select, menu = self._link(True, "https://open.kakao.com/o/x")
        assert result["url"] == "https://open.kakao.com/o/x"
        select.assert_called_once_with(7, "채팅방 URL 복사")
        menu.assert_called_once_with("room", background=True)

    def test_menu_without_the_entry(self):
        result, _, _ = self._link(False)
        assert not result["success"] and "225x298" in result["error"]


class TestLeaveMenu:
    def test_nothing_pressed_when_the_leave_row_is_not_recognised(self):
        with patch.object(openchat.controller, "find_chat_window", return_value=1), \
                patch.object(openchat, "_open_room_menu", return_value=7) as menu, \
                patch.object(openchat, "_kakao_windows", return_value=set()), \
                patch.object(openchat, "_size", return_value=(179, 335)), \
                patch.object(openchat, "room_menu_select", return_value=False) as select, \
                patch.object(openchat, "_click") as click:
            try:
                openchat.leave_room("room")
                raise AssertionError("expected UIError")
            except openchat.UIError as e:
                assert "nothing pressed" in str(e)
        select.assert_called_once_with(7, "채팅방 나가기")
        menu.assert_called_once_with("room", background=True)
        click.assert_not_called()


class TestLeaveDialogLayout:
    """Open chat leave confirmations are answered at fixed spots with posted clicks."""

    def _layout(self, size):
        with patch.object(openchat, "_size", return_value=size), \
                patch.object(openchat, "dpi_scale", return_value=1.0):
            return openchat._leave_dialog_layout(5)

    def test_known_sizes(self):
        assert self._layout((260, 210)) == {"leave": (65, 25)}
        assert "ack" in self._layout((260, 312))
        assert self._layout((260, 216)) is None  # group room: "조용히 나가기" too, OCR path
        assert self._layout((260, 178)) is None  # 1:1 room

    def _confirm(self, spots, ticks=True, room_closes=True):
        shots = iter([Image.new("L", (260, 312), 255)] + [Image.new("L", (260, 312), 0 if ticks else 255)] * 9)
        with patch.object(openchat, "_size", return_value=(260, 312)), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat.ocr, "grab_window", side_effect=lambda h: next(shots)), \
                patch.object(openchat, "_post_click") as click, \
                patch.object(openchat, "_wait_for", return_value=True if room_closes else None), \
                patch.object(openchat, "_is_open", return_value=True), \
                patch.object(openchat.win32gui, "PostMessage") as post:
            try:
                return openchat._confirm_leave_by_layout(1, "room", 5, spots), click, post
            except openchat.UIError as e:
                return e, click, post

    def test_member_presses_leave_only(self):
        result, click, _ = self._confirm({"leave": (65, 25)})
        assert result["success"] and result["room_closed"] is False
        click.assert_called_once_with(5, 65, 312 - 25)

    def test_owner_ticks_the_checkbox_first(self):
        result, click, _ = self._confirm({"leave": (65, 25), "ack": (35, 86)})
        assert result["room_closed"] is True
        assert [c.args for c in click.call_args_list] == [(5, 35, 312 - 86), (5, 65, 312 - 25)]

    def test_untickable_checkbox_leaves_nothing(self):
        err, click, post = self._confirm({"leave": (65, 25), "ack": (35, 86)}, ticks=False)
        assert isinstance(err, openchat.UIError)
        assert all(c.args[1:] == (35, 312 - 86) for c in click.call_args_list)  # never "나가기"
        post.assert_called_once_with(5, openchat.WM_CLOSE, 0, 0)


class TestCreateForm:
    """'+ 만들기', topic chips, options and '확인' with posted clicks at fixed spots."""

    def test_topic_spots_cover_every_topic(self):
        assert set(openchat.config.FORM_TOPIC_POS) == set(openchat.TOPICS)

    def test_confirm_is_not_clicked_again_once_something_appeared(self):
        windows = iter([set(), {9}])
        with patch.object(openchat, "_size", return_value=(422, 642)), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat, "_post_click") as click, \
                patch.object(openchat, "_is_open", return_value=True), \
                patch.object(openchat, "_kakao_windows", side_effect=lambda: next(windows, {9})), \
                patch.object(openchat.time, "sleep"):
            openchat._press_confirm(5, exclude=set())
        click.assert_called_once_with(5, 211 + 69, 642 - 41)

    def test_confirm_gives_up_without_a_response(self):
        with patch.object(openchat, "_size", return_value=(422, 642)), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat, "_post_click") as click, \
                patch.object(openchat, "_wait_for", return_value=None):
            try:
                openchat._press_confirm(5, exclude=set())
                raise AssertionError("expected UIError")
            except openchat.UIError:
                pass
        assert click.call_count == openchat.config.BACKGROUND_CLICK_ATTEMPTS

    def _press(self, view_ok, toggles=True):
        with patch.object(openchat, "_scroll_form") as scroll, \
                patch.object(openchat.templates, "window_matches", return_value=view_ok), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat, "_toggle_at", return_value=toggles) as toggle, \
                patch.object(openchat, "_find_on_form", return_value={"cx": 100, "cy": 200}) as find, \
                patch.object(openchat, "_click") as click:
            try:
                openchat._press_on_form(5, "form_topics", 3, (160, 373), "재테크")
                err = None
            except openchat.UIError as e:
                err = e
        return scroll, toggle, find, click, err

    def test_chip_at_its_spot_when_the_view_matches(self):
        scroll, toggle, find, click, err = self._press(True)
        scroll.assert_called_once_with(5, 3)
        toggle.assert_called_once_with(5, 160, 373)
        assert not find.called and not click.called and err is None

    def test_ocr_when_the_view_does_not_match(self):
        _, toggle, find, click, _ = self._press(False)
        assert not toggle.called
        click.assert_called_once_with(5, 100, 200)

    def test_chip_that_never_toggles_is_an_error(self):
        *_, err = self._press(True, toggles=False)
        assert isinstance(err, openchat.UIError)

    def test_make_button_by_template(self):
        with patch.object(openchat, "_post_wheel"), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat.templates, "window_matches", return_value=True), \
                patch.object(openchat, "_kakao_windows", return_value=set()), \
                patch.object(openchat, "_post_click") as click, \
                patch.object(openchat, "_wait_new_window", return_value=42), \
                patch.object(openchat, "_ocr_window") as ocr_:
            assert openchat._open_create_form(3) == 42
        click.assert_called_once_with(3, 365, 161)
        assert not ocr_.called


class TestKakaoProfileOnly:
    """A "기본프로필만 참여 허용" room shows 프로필 설정 without the random choice (300x251);
    confirming it with a nickname joins with the real KakaoTalk profile."""

    def _confirm(self, size, profile, nickname=None):
        with patch.object(openchat, "_size", return_value=size), \
                patch.object(openchat, "dpi_scale", return_value=1.0), \
                patch.object(openchat, "px", side_effect=lambda h, v: v), \
                patch.object(openchat, "_click") as click, \
                patch.object(openchat, "_children", return_value=[11]), \
                patch.object(openchat.win32gui, "GetClassName", return_value="Edit"), \
                patch.object(openchat, "_set_text"), \
                patch.object(openchat, "_get_text", side_effect=lambda h: nickname), \
                patch.object(openchat, "_is_open", return_value=False), \
                patch.object(openchat.win32gui, "PostMessage") as post, \
                patch.object(openchat.time, "sleep"):
            try:
                openchat._confirm_profile(5, profile, nickname)
                return None, click, post
            except openchat.UIError as e:
                return e, click, post

    def test_nickname_join_is_cancelled(self):
        err, click, post = self._confirm((300, 251), "random", "mcp측정")
        assert isinstance(err, openchat.KakaoProfileOnly) and err.error_code == "kakao_profile_only"
        click.assert_not_called()
        post.assert_called_once_with(5, openchat.WM_CLOSE, 0, 0)

    def test_kakao_profile_join_is_confirmed(self):
        err, click, post = self._confirm((300, 251), "kakao")
        assert err is None and click.call_count == 1 and not post.called

    def test_nickname_join_with_the_choice_goes_on(self):
        err, click, _ = self._confirm((300, 307), "random", "mcp측정")
        assert err is None and click.call_count == 2  # random radio, then 확인

    def test_server_reports_the_code(self):
        from kakao_mcp import server

        def join(*a, **k):
            raise openchat.KakaoProfileOnly("only the KakaoTalk profile")

        with patch.object(server.controller, "is_kakaotalk_running", return_value={"running": True}), \
                patch.object(openchat, "_kakao_windows", return_value=set()), \
                patch.object(openchat, "check_rate_limit"):
            result = server._openchat_call(join)
        assert result["error_code"] == "kakao_profile_only"
