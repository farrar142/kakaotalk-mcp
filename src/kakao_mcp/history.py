"""Chat history kept in SQLite, and a background recorder that fills it.

Messages come from the same clipboard copy as ``kakao_read_messages`` (only what
the room window has loaded). KakaoTalk gives no message ids, so a message is
identified by (room, date, time, sender, text, occ), where ``occ`` numbers
identical messages sent by the same person in the same minute. Messages above
the first date separator of a copy have no known date and are not stored.
"""
import sqlite3
import threading
import time
from typing import Dict, Iterable, List, Optional

from . import controller, parser
from .auth.config import DATA_DIR

DB_PATH = DATA_DIR / "history.db"
MIN_INTERVAL_SEC = 60.0
TICK_SEC = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    room TEXT NOT NULL,
    date TEXT NOT NULL,          -- YYYY-MM-DD
    time TEXT NOT NULL,          -- HH:MM (24h)
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    occ INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    UNIQUE (room, date, time, sender, text, occ)
);
CREATE INDEX IF NOT EXISTS messages_room_when ON messages (room, date, time);
CREATE TABLE IF NOT EXISTS recorded_rooms (
    room TEXT PRIMARY KEY,
    interval_sec REAL NOT NULL,
    added_at TEXT NOT NULL,
    last_sync TEXT,
    last_new INTEGER,
    last_error TEXT
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class HistoryStore:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            if str(self.path) != ":memory:":
                self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
        return self._conn

    def save(self, room: str, messages: Iterable[Dict]) -> Dict:
        """Insert parsed messages; returns counts of new / already stored / undated.

        A copy whose newest messages are all stored under one other room and none
        under this one came from the wrong window: it is rejected (``rejected``).
        """
        rows, undated, occ = [], 0, {}
        for m in messages:
            if not m.get("date") or not m.get("time24"):
                undated += 1
                continue
            key = (m["date"], m["time24"], m["sender"], m["text"])
            occ[key] = occ.get(key, 0) + 1
            rows.append((room, *key, occ[key], _now()))
        with self._lock:
            db = self._db()
            other = self._stored_elsewhere(db, room, [r[1:5] for r in rows])
            if other:
                return {"new": 0, "known": 0, "undated": undated,
                        "rejected": f"the copied messages are those of '{other}', not '{room}'"}
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO messages (room, date, time, sender, text, occ, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            db.commit()
            new = db.total_changes - before
        return {"new": new, "known": len(rows) - new, "undated": undated}

    @staticmethod
    def _stored_elsewhere(db, room: str, keys: List[tuple]) -> Optional[str]:
        sample = keys[-30:]
        if len(sample) < 5:
            return None
        counts: Dict[str, int] = {}
        for key in sample:
            for (r,) in db.execute("SELECT DISTINCT room FROM messages "
                                   "WHERE date = ? AND time = ? AND sender = ? AND text = ?", key):
                counts[r] = counts.get(r, 0) + 1
        if counts.pop(room, 0) or not counts:
            return None
        other, n = max(counts.items(), key=lambda kv: kv[1])
        # Rooms do share a cross-posted message now and then, not half a copy
        return other if n >= len(sample) // 2 else None

    def search(self, room: Optional[str] = None, date: Optional[str] = None,
               date_from: Optional[str] = None, date_to: Optional[str] = None,
               keyword: Optional[str] = None, sender: Optional[str] = None,
               limit: int = 50) -> List[Dict]:
        """The latest ``limit`` messages matching the filters, oldest first."""
        where, args = [], []
        if room:
            where.append("room = ?")
            args.append(room)
        if date:
            date_from = date_to = date
        if date_from:
            where.append("date >= ?")
            args.append(date_from)
        if date_to:
            where.append("date <= ?")
            args.append(date_to)
        if keyword:
            where.append("text LIKE ? ESCAPE '\\'")
            args.append(_like(keyword))
        if sender:
            where.append("sender LIKE ? ESCAPE '\\'")
            args.append(_like(sender))
        sql = ("SELECT room, date, time, sender, text FROM messages"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY date DESC, time DESC, id DESC LIMIT ?")
        with self._lock:
            rows = self._db().execute(sql, (*args, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def room_stats(self) -> List[Dict]:
        with self._lock:
            rows = self._db().execute(
                "SELECT room, COUNT(*) AS messages, MIN(date || ' ' || time) AS first, "
                "MAX(date || ' ' || time) AS last FROM messages GROUP BY room ORDER BY room").fetchall()
        return [dict(r) for r in rows]

    # recorded rooms -------------------------------------------------------

    def set_recorded(self, room: str, interval_sec: float):
        with self._lock:
            db = self._db()
            db.execute(
                "INSERT INTO recorded_rooms (room, interval_sec, added_at) VALUES (?, ?, ?) "
                "ON CONFLICT (room) DO UPDATE SET interval_sec = excluded.interval_sec",
                (room, interval_sec, _now()))
            db.commit()

    def unset_recorded(self, room: Optional[str] = None) -> int:
        with self._lock:
            db = self._db()
            cur = (db.execute("DELETE FROM recorded_rooms WHERE room = ?", (room,)) if room
                   else db.execute("DELETE FROM recorded_rooms"))
            db.commit()
            return cur.rowcount

    def recorded(self) -> List[Dict]:
        with self._lock:
            rows = self._db().execute("SELECT * FROM recorded_rooms ORDER BY room").fetchall()
        return [dict(r) for r in rows]

    def mark_sync(self, room: str, new: Optional[int], error: Optional[str]):
        with self._lock:
            db = self._db()
            db.execute("UPDATE recorded_rooms SET last_sync = ?, last_new = ?, last_error = ? WHERE room = ?",
                       (_now(), new, error, room))
            db.commit()


store = HistoryStore()


def capture(room: str) -> Dict:
    """Copy a room's loaded messages and store them (opening the room if needed)."""
    with controller.UI_LOCK:
        if controller.find_chat_window(room) is None:
            opened = controller.search_and_open_room(room)
            if not opened.get("success") or controller.find_chat_window(room) is None:
                return {"success": False, "error": f"Chat room '{room}' is not open and could not be opened"}
        result = controller.read_chat_messages(room)
        if not result["success"] and "foreground" in result["error"]:
            time.sleep(1.0)  # focus is often refused only momentarily
            result = controller.read_chat_messages(room)
    warnings = {"link_warnings": result["link_warnings"]} if result.get("link_warnings") else {}
    if not result["success"]:
        return {"success": False, "error": result["error"], **warnings}
    saved = store.save(room, parser.parse_chat_text(result["raw_text"])["messages"])
    if saved.get("rejected"):
        return {"success": False, "error": f"Not saved: {saved['rejected']}", **warnings}
    return {"success": True, "room_name": room, **saved, **warnings}


class HistoryRecorder:
    """Background thread capturing every recorded room at its interval.

    The room list lives in the DB, so recording resumes when the server restarts.
    Once started the thread stays alive and idles while no room is recorded.
    """

    def __init__(self, history: HistoryStore = store):
        self._store = history
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._due: Dict[str, float] = {}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_running(self):
        if not self.is_running and self._store.recorded():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="history-recorder", daemon=True)
            self._thread.start()

    def add(self, rooms: List[str], interval_sec: float) -> List[Dict]:
        interval = max(MIN_INTERVAL_SEC, interval_sec)
        results = []
        for room in rooms:
            self._store.set_recorded(room, interval)
            r = capture(room)
            self._store.mark_sync(room, r.get("new"), r.get("error"))
            self._due[room] = time.time() + interval
            results.append(r)
        self.ensure_running()
        return results

    def remove(self, rooms: Optional[List[str]] = None) -> int:
        return sum(self._store.unset_recorded(r) for r in rooms) if rooms else self._store.unset_recorded()

    def _loop(self):
        controller._log("History recorder started")
        while not self._stop.wait(TICK_SEC):
            for r in self._store.recorded():
                due = self._due.setdefault(r["room"], time.time())
                if time.time() < due or self._stop.is_set():
                    continue
                self._due[r["room"]] = time.time() + r["interval_sec"]
                try:
                    res = capture(r["room"])
                except Exception as e:
                    res = {"error": f"{type(e).__name__}: {e}"}
                self._store.mark_sync(r["room"], res.get("new"), res.get("error")
                                      or "; ".join(res.get("link_warnings", [])) or None)
                if res.get("error"):
                    controller._log(f"History: {r['room']}: {res['error']}")
        controller._log("History recorder stopped")


recorder = HistoryRecorder()
