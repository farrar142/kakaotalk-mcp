"""Tests for 톡게시판 list parsing helpers (no KakaoTalk needed)."""
from datetime import datetime
from unittest.mock import patch

from PIL import Image

from kakao_mcp import board, config, ocr

NOW = datetime(2026, 10, 29, 14, 0)


class TestParseWhen:
    def test_relative(self):
        assert board._parse_when("17시간 전", NOW) == "2026-10-28 21:00"
        assert board._parse_when("5분 전", NOW) == "2026-10-29 13:55"
        assert board._parse_when("방금", NOW) == "2026-10-29 14:00"

    def test_absolute_with_ocr_dropped_colon(self):
        assert board._parse_when("10월 27일 오후 951", NOW) == "2026-10-27 21:51"
        assert board._parse_when("10월 24일 오후 1.09", NOW) == "2026-10-24 13:09"
        assert board._parse_when("2023년 7월 27일 오후 2:56", NOW) == "2023-07-27 14:56"

    def test_future_month_is_last_year(self):
        assert board._parse_when("12월 30일 오전 9:00", NOW) == "2025-12-30 09:00"

    def test_unparseable(self):
        assert board._parse_when("알 수 없음", NOW) is None


class TestParseMeta:
    def test_author_and_comments(self):
        meta = board._parse_meta("2023년 7월 27일 오후 2:56 • Kai • 덧글 195")
        assert meta["author"] == "Kai"
        assert meta["comments"] == 195
        assert meta["posted_raw"] == "2023년 7월 27일 오후 2:56"

    def test_no_comments(self):
        meta = board._parse_meta("17시간 전 • 방구석/Ai자동화")
        assert (meta["author"], meta["comments"]) == ("방구석/Ai자동화", None)


def _line(text, y, h=12):
    return {"text": text, "x": 20, "y": y, "w": 200, "h": h, "cx": 120, "cy": y + h / 2}


class TestVisibleItems:
    def _items(self, lines, gray):
        img = Image.new("RGB", (370, 590), (255, 255, 255))
        with patch.object(board, "_focus"), \
                patch.object(ocr, "grab_window", return_value=img), \
                patch.object(ocr, "recognize", return_value=lines), \
                patch.object(ocr, "line_darkness",
                             side_effect=lambda _img, ln: 118 if ln["text"] in gray else 0):
            return board._visible_items(1)

    def test_groups_titles_with_meta(self):
        lines = [_line("[무료 배포] 컷 없이 30초", 20), _line("5종 · 채점표", 35),
                 _line("17시간 전 • 방구석", 54), _line("새 영상", 100), _line("23시간 전 • 방구석", 130)]
        items = self._items(lines, {"17시간 전 • 방구석", "23시간 전 • 방구석"})
        assert [i["title"] for i in items] == ["[무료 배포] 컷 없이 30초 5종 · 채점표", "새 영상"]
        assert items[0]["cy"] == 26 + config.BOARD_LIST_TOP

    def test_title_cut_at_top_is_skipped(self):
        lines = [_line("잘린 제목 두번째 줄", 2), _line("10월 25일 오후 6:33 • a", 20),
                 _line("다음 글", 60), _line("10월 24일 오후 6:39 • a", 80)]
        items = self._items(lines, {"10월 25일 오후 6:33 • a", "10월 24일 오후 6:39 • a"})
        assert [i["title"] for i in items] == ["다음 글"]

    def test_gray_text_without_date_is_not_an_item(self):
        lines = [_line("게시물 저장주기 안내", 20), _line("게시판에 등록된 게시물은 최대 90일", 40)]
        assert self._items(lines, {"게시물 저장주기 안내", "게시판에 등록된 게시물은 최대 90일"}) == []

    def test_same_allows_ocr_noise(self):
        a = {"title": "로그인도 안 했는데, 서버가 공격자의 코드를 실 험할 수", "meta": "10월 24일 오후 1.09 • 방구석"}
        b = {"title": "로그인도 안 했는데, 서버가 공격자의 코드를 실 행할 수", "meta": "10월 24일 오후 1.09 • 방구석"}
        assert board._same(a, b)
        assert not board._same(a, {"title": "다른 글", "meta": "10월 23일 오후 6:15 • 방구석"})
