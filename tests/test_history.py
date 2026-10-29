"""Tests for the chat history store and the CRLF clipboard format."""
from kakao_mcp import history
from kakao_mcp.parser import parse_chat_text

# KakaoTalk 26.x: records end with CRLF, line breaks inside a message are LF
CRLF_SAMPLE = (
    "2026년 10월 28일 수요일\r\n"
    "[봇] [오후 11:59] 어서오세요 \n공지 확인 부탁드려요\r\n"
    "2026년 10월 29일 목요일\r\n"
    "파라님이 들어왔습니다.\r\n"
    "[널널K] [오전 12:05] 반가워요\r\n"
    "[널널K] [오전 12:05] ㅋㅋ\r\n"
    "[널널K] [오전 12:05] ㅋㅋ\r\n"
    "[파라] [오후 12:30] 점심!\r\n"
)


def _store(tmp_path):
    return history.HistoryStore(tmp_path / "h.db")


class TestCrlfParsing:
    def test_dates_and_24h_times(self):
        msgs = parse_chat_text(CRLF_SAMPLE)["messages"]
        assert [(m["date"], m["time24"]) for m in msgs] == [
            ("2026-10-28", "23:59"), ("2026-10-29", "00:05"), ("2026-10-29", "00:05"),
            ("2026-10-29", "00:05"), ("2026-10-29", "12:30")]

    def test_multiline_text_kept(self):
        assert parse_chat_text(CRLF_SAMPLE)["messages"][0]["text"] == "어서오세요\n공지 확인 부탁드려요"

    def test_system_lines_are_not_message_text(self):
        parsed = parse_chat_text(CRLF_SAMPLE)
        assert parsed["system"] == [{"date": "2026-10-29", "text": "파라님이 들어왔습니다."}]
        assert all("들어왔습니다" not in m["text"] for m in parsed["messages"])

    def test_messages_before_first_separator_are_undated(self):
        msgs = parse_chat_text("[a] [오전 9:00] hi\r\n")["messages"]
        assert msgs[0]["date"] is None


class TestHistoryStore:
    def test_save_is_idempotent_and_keeps_repeats(self, tmp_path):
        store = _store(tmp_path)
        msgs = parse_chat_text(CRLF_SAMPLE)["messages"]
        assert store.save("room", msgs) == {"new": 5, "known": 0, "undated": 0}
        assert store.save("room", msgs) == {"new": 0, "known": 5, "undated": 0}
        assert [r["text"] for r in store.search("room")].count("ㅋㅋ") == 2

    def test_undated_not_stored(self, tmp_path):
        store = _store(tmp_path)
        assert store.save("room", parse_chat_text("[a] [오전 9:00] hi\r\n")["messages"])["undated"] == 1
        assert store.search() == []

    def test_latest_n_oldest_first(self, tmp_path):
        store = _store(tmp_path)
        store.save("room", parse_chat_text(CRLF_SAMPLE)["messages"])
        rows = store.search("room", limit=2)
        assert [r["text"] for r in rows] == ["ㅋㅋ", "점심!"]

    def test_filters(self, tmp_path):
        store = _store(tmp_path)
        store.save("room", parse_chat_text(CRLF_SAMPLE)["messages"])
        store.save("other", parse_chat_text(CRLF_SAMPLE.replace("점심!", "저녁!").replace("반가워요", "안녕"))["messages"])
        assert len(store.search("room", date="2026-10-28")) == 1
        assert len(store.search("room", date_from="2026-10-29", date_to="2026-10-29")) == 4
        assert [r["room"] for r in store.search(keyword="점심")] == ["room"]
        assert len(store.search("room", sender="널널")) == 3
        assert store.search(keyword="%") == []  # LIKE wildcards are literal

    def test_recorded_rooms(self, tmp_path):
        store = _store(tmp_path)
        store.set_recorded("a", 60)
        store.set_recorded("a", 120)
        store.mark_sync("a", 3, None)
        [row] = store.recorded()
        assert (row["room"], row["interval_sec"], row["last_new"]) == ("a", 120, 3)
        assert store.unset_recorded() == 1
        assert store.recorded() == []


class TestWrongRoomCopy:
    def _msgs(self, n, sender="a"):
        lines = ["2026년 10월 29일 목요일"] + [f"[{sender}] [오후 3:{i:02d}] 메시지 {i}" for i in range(n)]
        return parse_chat_text("\r\n".join(lines) + "\r\n")["messages"]

    def test_copy_of_another_room_is_rejected(self, tmp_path):
        store = _store(tmp_path)
        store.save("dev", self._msgs(20))
        store.save("insider", self._msgs(3, sender="other"))
        result = store.save("insider", self._msgs(20))
        assert result["new"] == 0 and "'dev'" in result["rejected"]
        assert len(store.search("insider")) == 3

    def test_new_room_sharing_one_crosspost_is_saved(self, tmp_path):
        store = _store(tmp_path)
        store.save("dev", self._msgs(20))
        msgs = self._msgs(1) + self._msgs(10, sender="b")
        assert store.save("vibe", msgs)["new"] == 11

    def test_recopy_of_same_room_is_fine(self, tmp_path):
        store = _store(tmp_path)
        store.save("dev", self._msgs(20))
        assert "rejected" in store.save("other", self._msgs(20))  # a copy of "dev" under another name
        assert store.save("dev", self._msgs(20))["known"] == 20
