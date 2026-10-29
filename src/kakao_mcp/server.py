#!/usr/bin/env python
"""MCP Server for KakaoTalk PC automation via Win32 API."""
import os
import re
from typing import Dict, Optional

from mcp.server.fastmcp import FastMCP

from kakao_mcp import controller
from kakao_mcp import parser
from kakao_mcp import config
from kakao_mcp import openchat
from kakao_mcp import board
from kakao_mcp import history
from kakao_mcp.auth.scopes import MANAGE, READ, SEND, guard
from kakao_mcp.controller import ui_exclusive

app = FastMCP(
    "kakao-mcp-server",
    instructions="MCP Server for KakaoTalk PC automation via Win32 API",
)


@app.tool()
@guard(READ)
def kakao_health_check() -> Dict:
    """Check if KakaoTalk PC is currently running.
    Returns status, window handle, and process ID."""
    try:
        status = controller.is_kakaotalk_running()
        if status["running"]:
            return {
                "message": "KakaoTalk is running",
                "running": True,
                "hwnd": status["hwnd"],
                "pid": status["pid"],
            }
        return {"message": "KakaoTalk is not running", "running": False}
    except Exception as e:
        return {"error": f"Health check failed: {e}"}


@app.tool()
@guard(READ)
def kakao_list_open_rooms() -> Dict:
    """List all currently open KakaoTalk chat room windows.
    Returns a list of open chat rooms with their window titles."""
    try:
        status = controller.is_kakaotalk_running()
        if not status["running"]:
            return {"error": "KakaoTalk is not running"}
        rooms = controller.list_chat_windows()
        return {
            "message": f"Found {len(rooms)} open chat room(s)",
            "rooms": [{"title": r["title"], "hwnd": r["hwnd"]} for r in rooms],
        }
    except Exception as e:
        return {"error": f"Failed to list rooms: {e}"}


@app.tool()
@guard(SEND)
@ui_exclusive
def kakao_open_room(room_name: str) -> Dict:
    """Open or bring to front a KakaoTalk chat room by name.
    If the chat window is already open, brings it to foreground.
    If not, searches for the room in KakaoTalk's search bar.

    Args:
        room_name: The name of the chat room or person to open.
    """
    try:
        hwnd = controller.find_chat_window(room_name)
        if hwnd:
            controller.bring_window_to_front(hwnd)
            return {"message": f"Chat room '{room_name}' brought to foreground", "hwnd": hwnd}
        result = controller.search_and_open_room(room_name)
        if result["success"]:
            return {"message": result["message"], "hwnd": result.get("hwnd")}
        return {"error": result["error"]}
    except Exception as e:
        return {"error": f"Failed to open room '{room_name}': {e}"}


@app.tool()
@guard(SEND)
@ui_exclusive
def kakao_send_message(room_name: str, message: str) -> Dict:
    """Send a text message to a KakaoTalk chat room.
    The chat room window must already be open.

    Args:
        room_name: Exact title of the chat room window.
        message: The text message to send.
    """
    try:
        if not message.strip():
            return {"error": "Message cannot be empty"}
        result = controller.send_message_to_room(room_name, message)
        if result["success"]:
            return {"message": result["message"]}
        return {"error": result["error"]}
    except Exception as e:
        return {"error": f"Failed to send message: {e}"}


@app.tool()
@guard(SEND)
@ui_exclusive
def kakao_send_bulk(room_names: list[str], message: str, interval_sec: float = 0.5) -> Dict:
    """Send the same message to multiple KakaoTalk chat rooms at once.
    Opens each room if not already open and sends the message sequentially.
    Maintains a safe interval between rooms to ensure reliability.

    Args:
        room_names: List of chat room names or person names to send to.
        message: The text message to send to all rooms.
        interval_sec: Seconds to wait between rooms (default 0.5, minimum 0.3).
    """
    try:
        if not room_names:
            return {"error": "room_names cannot be empty"}
        if not message.strip():
            return {"error": "Message cannot be empty"}
        result = controller.send_bulk_messages(room_names, message, interval_sec)
        if result["success"]:
            return {"message": result["message"], "results": result["results"]}
        return {"error": result.get("message", "Failed to send bulk messages"), "results": result.get("results", [])}
    except Exception as e:
        return {"error": f"Failed to send bulk messages: {e}"}


@app.tool()
@guard(SEND)
@ui_exclusive
def kakao_send_image(room_name: str, image_paths: list[str]) -> Dict:
    """Send image file(s) to a KakaoTalk chat room.
    Copies the image to clipboard using file-drop format and pastes into the chat.
    KakaoTalk shows a confirmation dialog which is automatically accepted.
    The chat room window must already be open.
    NOTE: This briefly brings the chat window to the foreground.

    Args:
        room_name: Exact title of the chat room window.
        image_paths: List of absolute file paths to images (JPG, PNG, GIF, BMP, WebP).
    """
    try:
        if not image_paths:
            return {"error": "image_paths cannot be empty"}

        for path in image_paths:
            if not os.path.isfile(os.path.abspath(path)):
                return {"error": f"Image file not found: {path}"}

        if len(image_paths) == 1:
            result = controller.send_image_to_room(room_name, image_paths[0])
            if result["success"]:
                return {"message": result["message"]}
            return {"error": result["error"]}
        else:
            result = controller.send_images_to_room(room_name, image_paths)
            if result["success"]:
                return {"message": result["message"], "results": result["results"]}
            return {"error": result.get("message", "Failed to send images"), "results": result.get("results", [])}
    except Exception as e:
        return {"error": f"Failed to send image: {e}"}


@app.tool()
@guard(READ)
@ui_exclusive
def kakao_read_messages(room_name: str, max_messages: int = 50) -> Dict:
    """Read recent messages from a KakaoTalk chat room.
    Uses clipboard-based reading (Ctrl+A, Ctrl+C on the chat list).
    Each message has date (YYYY-MM-DD) and time24 (HH:MM); everything read is
    also saved to the chat history DB (see kakao_history_search).
    NOTE: This briefly brings the chat window to the foreground.

    Args:
        room_name: Exact title of the chat room window.
        max_messages: Maximum number of recent messages to return (default 50).
    """
    try:
        result = controller.read_chat_messages(room_name)
        if not result["success"]:
            return {"error": result["error"]}
        parsed = parser.parse_chat_text(result["raw_text"])
        messages = parsed["messages"]
        try:
            stored = history.store.save(room_name, messages)
        except Exception as e:
            stored = {"error": str(e)}
        if len(messages) > max_messages:
            messages = messages[-max_messages:]
        return {
            "message": f"Read {len(messages)} messages from '{room_name}'",
            # KakaoTalk 26.x copies no header line, so fall back to the window title
            "room_name": parsed["room_name"] or room_name,
            "member_count": parsed["member_count"],
            "messages": messages,
            "history": stored,
            **({"link_warnings": result["link_warnings"]} if result.get("link_warnings") else {}),
        }
    except Exception as e:
        return {"error": f"Failed to read messages: {e}"}


@app.tool()
@guard(READ)
@ui_exclusive
def kakao_extract_links(room_name: str) -> Dict:
    """Extract all URLs/links from messages in a KakaoTalk chat room.
    Reads the chat first, then extracts URLs from all messages.

    Args:
        room_name: Exact title of the chat room window.
    """
    try:
        result = controller.read_chat_messages(room_name)
        if not result["success"]:
            return {"error": result["error"]}
        parsed = parser.parse_chat_text(result["raw_text"])
        urls = parser.extract_urls_from_messages(parsed["messages"])
        return {
            "message": f"Found {len(urls)} URL(s) in '{room_name}'",
            "links": urls,
        }
    except Exception as e:
        return {"error": f"Failed to extract links: {e}"}


@app.tool()
@guard(SEND)
@ui_exclusive
def kakao_send_mention(room_name: str, mention_name: str, message: str) -> Dict:
    """Send a message with @mention to a KakaoTalk chat room.
    Types '@' to activate the mention popup, selects the target user,
    then sends the message. The chat room window must already be open.
    NOTE: This briefly brings the chat window to the foreground.

    Args:
        room_name: Exact title of the chat room window.
        mention_name: Display name of the person to mention (e.g. '홍길동').
        message: The text message to send after the mention.
    """
    try:
        if not mention_name.strip():
            return {"error": "Mention name cannot be empty"}
        if not message.strip():
            return {"error": "Message cannot be empty"}
        result = controller.send_mention_message(room_name, mention_name, message)
        if result["success"]:
            return {"message": result["message"]}
        return {"error": result["error"]}
    except Exception as e:
        return {"error": f"Failed to send mention message: {e}"}


@app.tool()
@guard(READ)
def kakao_download_images(
    room_name: str,
    output_dir: Optional[str] = None,
    max_images: int = 10,
) -> Dict:
    """Download recent images from KakaoTalk's local cache.
    Images are sorted by modification time (newest first).
    Note: Cache is global, not per-room — images are the most recently cached ones.

    Args:
        room_name: Chat room name (for context/logging).
        output_dir: Directory to save images. Defaults to Documents/KakaoMCP_Images.
        max_images: Maximum number of images to download (default 10).
    """
    try:
        if output_dir is None:
            output_dir = config.DEFAULT_IMAGE_OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)
        result = controller.download_recent_images(room_name, output_dir, max_images)
        return result
    except Exception as e:
        return {"error": f"Failed to download images: {e}"}


@app.tool()
@guard(SEND)
@ui_exclusive
def kakao_start_monitor(
    room_name: str,
    keywords: list[str],
    poll_interval_sec: float = 5.0,
) -> Dict:
    """Start monitoring a KakaoTalk chat room for keyword matches.
    Runs in background, checking for new messages at the specified interval.
    Use kakao_get_monitor_events() to retrieve detected keyword matches.
    NOTE: The chat room window must be open. Polling brings it to foreground briefly.

    Args:
        room_name: Exact title of the chat room window to monitor.
        keywords: List of keywords to watch for (case-insensitive).
        poll_interval_sec: Seconds between each poll (minimum 3, default 5).
    """
    try:
        if not keywords:
            return {"error": "Keywords list cannot be empty"}
        result = controller._chat_monitor.start(room_name, keywords, poll_interval_sec)
        if result["success"]:
            return {"message": result["message"]}
        return {"error": result["error"]}
    except Exception as e:
        return {"error": f"Failed to start monitor: {e}"}


@app.tool()
@guard(SEND)
def kakao_stop_monitor() -> Dict:
    """Stop the running chat room monitor."""
    try:
        result = controller._chat_monitor.stop()
        if result["success"]:
            return {"message": result["message"]}
        return {"error": result["error"]}
    except Exception as e:
        return {"error": f"Failed to stop monitor: {e}"}


@app.tool()
@guard(READ)
def kakao_get_monitor_events() -> Dict:
    """Get pending keyword match events from the chat monitor.
    Returns events detected since last call. Each event includes:
    - keyword: the matched keyword
    - trigger_message: the message that matched (sender, time, text)
    - recent_context: last 10 messages for context understanding
    - room_name: the monitored chat room

    Call this periodically while monitor is running to check for matches.
    """
    try:
        is_running = controller._chat_monitor.is_running
        events = controller._chat_monitor.get_events()
        return {
            "monitoring": is_running,
            "event_count": len(events),
            "events": events,
        }
    except Exception as e:
        return {"error": f"Failed to get monitor events: {e}"}


# ---------------------------------------------------------------------------
# Chat history (SQLite)
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.tool()
@guard(SEND)
def kakao_history_record(room_names: list[str], interval_sec: float = 300) -> Dict:
    """Record chat rooms' messages into the history DB, now and then periodically.
    Each capture copies the messages the room window has loaded, so keep the
    interval short enough that no messages scroll out between captures. A room
    whose window is closed is opened by search first. Recording continues after
    server restarts until kakao_history_stop.
    NOTE: Every capture briefly brings the room window to the foreground.

    Args:
        room_names: Exact titles of the chat rooms to record.
        interval_sec: Seconds between captures of each room (minimum 60, default 300).
    """
    try:
        if not room_names:
            return {"error": "room_names cannot be empty"}
        results = history.recorder.add(room_names, interval_sec)
        return {
            "message": f"Recording {len(room_names)} room(s) every "
                       f"{max(history.MIN_INTERVAL_SEC, interval_sec):g}s",
            "first_capture": [
                {k: v for k, v in r.items() if k != "success"} if r.get("success")
                else {"room_name": room, "error": r["error"]}
                for room, r in zip(room_names, results)
            ],
        }
    except Exception as e:
        return {"error": f"Failed to start recording: {e}"}


@app.tool()
@guard(SEND)
def kakao_history_stop(room_names: Optional[list[str]] = None) -> Dict:
    """Stop recording rooms (all rooms when room_names is omitted). Stored messages are kept.

    Args:
        room_names: Rooms to stop recording; omit to stop all.
    """
    try:
        removed = history.recorder.remove(room_names)
        return {"message": f"Stopped recording {removed} room(s)"}
    except Exception as e:
        return {"error": f"Failed to stop recording: {e}"}


@app.tool()
@guard(READ)
def kakao_history_status() -> Dict:
    """Show recorded rooms (interval, last capture, errors) and stored message counts per room.
    link_events lists windows the server closed because a link was opened by accident."""
    try:
        return {
            "recorder_running": history.recorder.is_running,
            "link_events": list(controller.LINK_EVENTS),
            "recorded_rooms": history.store.recorded(),
            "stored": history.store.room_stats(),
            "db_path": str(history.store.path),
        }
    except Exception as e:
        return {"error": f"Failed to read history status: {e}"}


@app.tool()
@guard(READ)
def kakao_history_search(
    room_name: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    keyword: Optional[str] = None,
    sender: Optional[str] = None,
    limit: int = 50,
) -> Dict:
    """Search stored chat history. Returns the latest `limit` matching messages, oldest first.
    With no filters this is "the most recent N messages". Only messages captured
    by kakao_history_record, kakao_read_messages or the monitor are stored.

    Args:
        room_name: Exact room title; omit to search all rooms.
        date: A single day (YYYY-MM-DD).
        date_from: First day of a range (YYYY-MM-DD, inclusive).
        date_to: Last day of a range (YYYY-MM-DD, inclusive).
        keyword: Text the message contains.
        sender: Text the sender name contains.
        limit: Maximum messages (1-1000, default 50).
    """
    for name, value in (("date", date), ("date_from", date_from), ("date_to", date_to)):
        if value and not DATE_RE.match(value):
            return {"error": f"{name} must be YYYY-MM-DD"}
    if not 1 <= limit <= 1000:
        return {"error": "limit must be 1-1000"}
    try:
        rows = history.store.search(room_name, date, date_from, date_to, keyword, sender, limit)
        return {"message": f"Found {len(rows)} message(s)", "count": len(rows), "messages": rows}
    except Exception as e:
        return {"error": f"Failed to search history: {e}"}


# ---------------------------------------------------------------------------
# Room board (톡게시판)
# ---------------------------------------------------------------------------

@app.tool()
@guard(READ)
@ui_exclusive
def kakao_read_board(room_name: str, tab: str = "공지", max_posts: int = 10, include_body: bool = True) -> Dict:
    """Read posts (공지 notices, 일정, 투표, 퀴즈) from a chat room's 톡게시판, newest first.
    Each post has title, posted (YYYY-MM-DD HH:MM; approximate for "N시간 전"),
    posted_raw, author, comments (count) and, with include_body, the full body
    text. List titles and dates are read with OCR; bodies are copied exactly.
    The room window must be open; a board window opened for this is closed
    again afterwards. Comments themselves are not read.

    Args:
        room_name: Exact title of the chat room window.
        tab: '공지' (default), '일정', '투표' or '퀴즈'.
        max_posts: Maximum posts to return (1-50, default 10).
        include_body: Open each post to copy its body (about 3-4 s per post).
    """
    if not 1 <= max_posts <= 50:
        return {"error": "max_posts must be 1-50"}
    return _openchat_call(board.read_board, room_name, tab=tab, max_posts=max_posts, include_body=include_body)


# ---------------------------------------------------------------------------
# Open chat (오픈채팅)
# ---------------------------------------------------------------------------

def _openchat_call(fn, *args, **kwargs) -> Dict:
    try:
        if not controller.is_kakaotalk_running()["running"]:
            return {"error": "KakaoTalk is not running"}
        result = fn(*args, **kwargs)
        if result.get("success"):
            result.pop("success")
            return result
        return {"error": result.get("error", "Unknown error")}
    except openchat.UIError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{fn.__name__} failed: {e}"}


@app.tool()
@guard(READ)
@ui_exclusive
def kakao_openchat_search(query: str, max_results: int = 10) -> Dict:
    """Search KakaoTalk open chat rooms (group chats) by name/description/tag.
    Results are read from the screen with OCR, so titles may contain small
    recognition errors. Use the returned title or index with kakao_openchat_join.
    NOTE: Opens the 오픈채팅 window and brings it to the foreground.

    Args:
        query: Search text (room name, description or #tag).
        max_results: Maximum results to return (default 10; scrolls the list).
    """
    return _openchat_call(openchat.search_openchat, query, max_results=max_results)


@app.tool()
@guard(MANAGE)
@ui_exclusive
def kakao_openchat_join(
    query: str,
    title: Optional[str] = None,
    index: int = 0,
    profile: str = "kakao",
    passcode: Optional[str] = None,
    nickname: Optional[str] = None,
    accept_community: bool = False,
    accept_safebot: bool = False,
) -> Dict:
    """Join an open chat room found by search (or open it if already joined).
    Returns the joined room's window title, usable with kakao_send_message,
    kakao_read_messages, kakao_leave_room, etc.

    Args:
        query: Search text used to find the room.
        title: Title of the room to join (fuzzy match). Preferred over index.
        index: 0-based index in the search results when title is not given.
        profile: 'kakao' to join with the KakaoTalk profile, 'random' for a random nickname.
        passcode: Participation code (참여 코드) if the room requires one.
        nickname: Join with an open-chat profile under this name (1-20 chars)
            instead of the KakaoTalk profile; overrides profile. Not possible in
            rooms that only allow KakaoTalk profiles (기본프로필만 참여 허용).
        accept_community: Community rooms ask for consent first (커뮤니티 시작하기:
            messages become public and searchable, kept 90 days). Only set True
            when the user agreed; otherwise the consent is declined and the
            join stops with an error saying so.
        accept_safebot: Rooms with SafeBot ask to agree to 세이프봇 적용 동의
            (messages may be hidden under Kakao's policy). Only set True when
            the user agreed; otherwise it is declined like accept_community.
    """
    return _openchat_call(
        openchat.join_openchat, query, title=title, index=index, profile=profile, passcode=passcode,
        nickname=nickname, accept_community=accept_community, accept_safebot=accept_safebot,
    )


@app.tool()
@guard(MANAGE)
@ui_exclusive
def kakao_openchat_create(
    name: str,
    description: str = "",
    topic: str = "자유수다",
    searchable: bool = True,
    kakao_profile_only: bool = False,
) -> Dict:
    """Create a new group open chat room. The new room's window opens afterwards.

    Args:
        name: Room name (1-30 chars).
        description: Room description (up to 200 chars; #tags help discovery).
        topic: One of 자유수다, 팬덤, 게임, 엔터테인먼트, 스포츠, 일상, 운동/건강,
            여행, 취미, 친목/모임, 패션/뷰티, 직업, 자기계발, 재테크.
        searchable: Allow the room to be found by search (default True).
        kakao_profile_only: Only allow members using their KakaoTalk profile
            (cannot be changed after creation).
    """
    return _openchat_call(
        openchat.create_openchat, name, description=description, topic=topic,
        searchable=searchable, kakao_profile_only=kakao_profile_only,
    )


@app.tool()
@guard(MANAGE)
@ui_exclusive
def kakao_leave_room(room_name: str, confirm: bool = False) -> Dict:
    """Leave a chat room (open chat or regular). This cannot be undone:
    the conversation history is deleted. The room window must be open.

    Args:
        room_name: Exact title of the chat room window.
        confirm: Must be true to actually leave (safety guard).
    """
    if not confirm:
        return {"error": f"Refusing to leave '{room_name}' without confirm=true"}
    return _openchat_call(openchat.leave_room, room_name)


@app.tool()
@guard(READ)
@ui_exclusive
def kakao_get_room_link(room_name: str) -> Dict:
    """Get the share URL of an open chat room (via the room menu's 'URL 복사').
    The room window must be open.

    Args:
        room_name: Exact title of the chat room window.
    """
    return _openchat_call(openchat.get_room_link, room_name)


def main():
    """Run the server.

    Default is stdio. To control KakaoTalk in a VM from another machine, run with
    ``--transport streamable-http --host 0.0.0.0 --port 8765`` inside the VM's
    logged-in desktop session (not via SSH/service — UI automation needs the
    interactive desktop) and connect to ``http://<vm-ip>:8765/mcp``.
    """
    import argparse
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("auth", "token"):
        from kakao_mcp.auth.cli import main as cli_main
        cli_main(sys.argv[1:])
        return

    from kakao_mcp.auth import enable_auth, load_config
    from kakao_mcp.auth.config import CONFIG_PATH

    ap = argparse.ArgumentParser(
        prog="kakaotalk-mcp",
        epilog="Management: kakaotalk-mcp auth init|set-password|set-totp|set-public-url, "
               "kakaotalk-mcp token create|list|revoke",
    )
    ap.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    ap.add_argument("--host", default=os.environ.get("KAKAO_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("KAKAO_MCP_PORT", "8765")))
    ap.add_argument("--auth-config", default=str(CONFIG_PATH),
                    help="auth.toml; when it exists, HTTP transports require OAuth/PAT tokens")
    ap.add_argument("--insecure-no-auth", action="store_true",
                    help="allow serving a non-localhost address without auth (anyone who can reach it "
                         "controls KakaoTalk)")
    args = ap.parse_args()

    app.settings.host = args.host
    app.settings.port = args.port
    history.recorder.ensure_running()  # resume recording rooms registered earlier
    auth_cfg = load_config(args.auth_config) if args.transport != "stdio" else None

    if auth_cfg is None:
        if args.transport != "stdio" and args.host not in ("127.0.0.1", "localhost", "::1"):
            # Fail closed: a reverse proxy may forward the internet to this port.
            if not args.insecure_no_auth:
                sys.exit(f"Refusing to serve {args.host}:{args.port} without auth: {args.auth_config} not found. "
                         "Run `kakaotalk-mcp auth init`, or pass --insecure-no-auth for a trusted LAN only.")
            # The default DNS-rebinding guard only accepts localhost Host headers,
            # which rejects remote clients. Restrict access with the firewall instead.
            app.settings.transport_security = None
            print(f"WARNING: serving without authentication on {args.host}:{args.port}", file=sys.stderr)
        app.run(transport=args.transport)
        return

    if args.transport != "streamable-http":
        sys.exit("OAuth is only supported with --transport streamable-http")
    enable_auth(app, auth_cfg)

    import uvicorn

    # Run uvicorn directly so client IPs from the reverse proxy are trusted
    # (login throttling and logs use them).
    uvicorn.run(
        app.streamable_http_app(),
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=",".join(auth_cfg.trusted_proxies) or "127.0.0.1",
        log_level="info",
    )


if __name__ == "__main__":
    main()
