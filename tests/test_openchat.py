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
            openchat._answer_community(1, accept)
        return click.call_args.args

    def test_decline_clicks_cancel(self):
        assert self._answer(False) == (1, 218, 325)

    def test_accept_clicks_agree(self):
        assert self._answer(True) == (1, 82, 325)
