"""Keep the HTTP server running; used by the logon autostart.

Run with pythonw.exe so no console window (and no console-host/terminal
hand-off at logon) is involved:

    pythonw -m kakao_mcp.supervisor --transport streamable-http --host 0.0.0.0 --port 8765

Arguments are passed to ``python -m kakao_mcp``. The server's output goes to
%LOCALAPPDATA%\\kakaotalk-mcp\\server.log; one supervisor per user session.
"""
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

from kakao_mcp.auth.config import DATA_DIR

MUTEX_NAME = "Local\\kakaotalk-mcp-server"
ERROR_ALREADY_EXISTS = 183
CREATE_NO_WINDOW = 0x08000000
MAX_LOG_BYTES = 5 * 1024 * 1024


def _log_line(log: Path, text: str):
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"=== {time.strftime('%Y-%m-%dT%H:%M:%S')} {text}\n")


def main():
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return  # another supervisor already runs in this session
    _ = mutex  # held for the life of the process

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = DATA_DIR / "server.log"
    python = Path(sys.executable).with_name("python.exe")
    args = sys.argv[1:] or ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8765"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

    _log_line(log, f"supervisor pid {os.getpid()} started: {' '.join(args)}")
    while True:
        if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
            log.replace(log.with_name(log.name + ".1"))
        _log_line(log, "starting server")
        with open(log, "ab") as out:
            code = subprocess.call([str(python), "-m", "kakao_mcp", *args], stdout=out,
                                   stderr=subprocess.STDOUT, env=env, creationflags=CREATE_NO_WINDOW)
        # Exit code 1 = refused to start (e.g. no auth.toml); retry slowly instead of spinning
        delay = 60 if code == 1 else 5
        _log_line(log, f"server exited with {code}, restarting in {delay}s")
        time.sleep(delay)


if __name__ == "__main__":
    main()
