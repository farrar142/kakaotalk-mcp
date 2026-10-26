"""SQLite storage for OAuth clients, codes and tokens.

Only SHA-256 hashes of codes and tokens are stored; the raw values exist only
in the response that hands them out.
"""
import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

ACCESS_PREFIX = "kmcp_at_"
REFRESH_PREFIX = "kmcp_rt_"
PAT_PREFIX = "kmcp_pat_"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    info TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL
);
CREATE TABLE IF NOT EXISTS pending_authorizations (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    params TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_codes (
    hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    redirect_explicit INTEGER NOT NULL,
    resource TEXT,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    family_id TEXT
);
CREATE TABLE IF NOT EXISTS access_tokens (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,            -- 'oauth' | 'pat'
    client_id TEXT NOT NULL,
    name TEXT,                     -- PAT name
    scopes TEXT NOT NULL,
    family_id TEXT,
    expires_at REAL,               -- NULL for PATs
    created_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    family_id TEXT NOT NULL,
    status TEXT NOT NULL,          -- 'active' | 'rotated' | 'revoked'
    expires_at REAL NOT NULL,
    family_expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refresh_family ON refresh_tokens(family_id);
CREATE INDEX IF NOT EXISTS idx_access_family ON access_tokens(family_id);
CREATE TABLE IF NOT EXISTS login_failures (
    key TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


class AuthStore:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    def _one(self, sql: str, args: tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def purge_expired(self):
        now = time.time()
        self._exec("DELETE FROM pending_authorizations WHERE expires_at < ?", (now,))
        self._exec("DELETE FROM auth_codes WHERE expires_at < ?", (now - 86400,))
        self._exec("DELETE FROM access_tokens WHERE kind = 'oauth' AND expires_at < ?", (now - 86400,))
        self._exec("DELETE FROM refresh_tokens WHERE family_expires_at < ?", (now,))
        self._exec("DELETE FROM login_failures WHERE at < ?", (now - 86400,))

    # -- clients ------------------------------------------------------------

    def save_client(self, client_id: str, info: Dict):
        self._exec("INSERT OR REPLACE INTO clients (client_id, info, created_at) VALUES (?, ?, ?)",
                   (client_id, json.dumps(info), time.time()))

    def get_client(self, client_id: str) -> Optional[Dict]:
        row = self._one("SELECT info FROM clients WHERE client_id = ?", (client_id,))
        return json.loads(row["info"]) if row else None

    def delete_all_clients(self):
        self._exec("DELETE FROM clients")

    # -- pending authorization requests (between /authorize and /login) -----

    def create_pending(self, client_id: str, params: Dict, ttl: int = 600) -> str:
        pid = secrets.token_urlsafe(24)
        self._exec("INSERT INTO pending_authorizations (id, client_id, params, expires_at) VALUES (?, ?, ?, ?)",
                   (pid, client_id, json.dumps(params), time.time() + ttl))
        return pid

    def get_pending(self, pid: str) -> Optional[Dict]:
        row = self._one("SELECT client_id, params FROM pending_authorizations WHERE id = ? AND expires_at > ?",
                        (pid, time.time()))
        if not row:
            return None
        params = json.loads(row["params"])
        params["client_id"] = row["client_id"]
        return params

    def delete_pending(self, pid: str):
        self._exec("DELETE FROM pending_authorizations WHERE id = ?", (pid,))

    # -- authorization codes ------------------------------------------------

    def create_code(self, client_id: str, scopes: List[str], code_challenge: str, redirect_uri: str,
                    redirect_explicit: bool, resource: Optional[str], ttl: int = 300) -> str:
        code = new_token()
        self._exec(
            "INSERT INTO auth_codes (hash, client_id, scopes, code_challenge, redirect_uri, redirect_explicit,"
            " resource, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (token_hash(code), client_id, " ".join(scopes), code_challenge, redirect_uri,
             int(redirect_explicit), resource, time.time() + ttl))
        return code

    def get_code(self, code: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM auth_codes WHERE hash = ?", (token_hash(code),))

    def consume_code(self, code: str, family_id: str) -> bool:
        """Mark a code used (atomically). False if it was already used."""
        cur = self._exec("UPDATE auth_codes SET used = 1, family_id = ? WHERE hash = ? AND used = 0",
                         (family_id, token_hash(code)))
        return cur.rowcount == 1

    # -- OAuth tokens -------------------------------------------------------

    def issue_tokens(self, client_id: str, scopes: List[str], access_ttl: int, refresh_ttl: int,
                     family_id: Optional[str] = None, family_expires_at: Optional[float] = None,
                     max_age: int = 0) -> Tuple[str, str, str]:
        """Issue an access + refresh token pair; returns (access, refresh, family_id)."""
        now = time.time()
        family_id = family_id or uuid.uuid4().hex
        family_expires_at = family_expires_at or now + max_age
        access = new_token(ACCESS_PREFIX)
        refresh = new_token(REFRESH_PREFIX)
        scope_str = " ".join(scopes)
        self._exec(
            "INSERT INTO access_tokens (hash, kind, client_id, scopes, family_id, expires_at, created_at)"
            " VALUES (?, 'oauth', ?, ?, ?, ?, ?)",
            (token_hash(access), client_id, scope_str, family_id, now + access_ttl, now))
        self._exec(
            "INSERT INTO refresh_tokens (hash, client_id, scopes, family_id, status, expires_at,"
            " family_expires_at, created_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (token_hash(refresh), client_id, scope_str, family_id,
             min(now + refresh_ttl, family_expires_at), family_expires_at, now))
        self._exec("UPDATE clients SET last_used_at = ? WHERE client_id = ?", (now, client_id))
        return access, refresh, family_id

    def get_access(self, token: str) -> Optional[sqlite3.Row]:
        return self._one(
            "SELECT * FROM access_tokens WHERE hash = ? AND revoked = 0 AND (expires_at IS NULL OR expires_at > ?)",
            (token_hash(token), time.time()))

    def get_refresh(self, token: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM refresh_tokens WHERE hash = ?", (token_hash(token),))

    def rotate_refresh(self, token: str) -> bool:
        """Mark an active refresh token as rotated (atomically). False if it wasn't active."""
        cur = self._exec("UPDATE refresh_tokens SET status = 'rotated' WHERE hash = ? AND status = 'active'",
                         (token_hash(token),))
        return cur.rowcount == 1

    def revoke_family(self, family_id: str):
        self._exec("UPDATE refresh_tokens SET status = 'revoked' WHERE family_id = ?", (family_id,))
        self._exec("UPDATE access_tokens SET revoked = 1 WHERE family_id = ?", (family_id,))

    def revoke_access(self, token: str):
        self._exec("UPDATE access_tokens SET revoked = 1 WHERE hash = ?", (token_hash(token),))

    # -- personal access tokens --------------------------------------------

    def create_pat(self, name: str, scopes: List[str]) -> str:
        if self._one("SELECT 1 FROM access_tokens WHERE kind = 'pat' AND name = ? AND revoked = 0", (name,)):
            raise ValueError(f"A token named '{name}' already exists")
        token = new_token(PAT_PREFIX)
        self._exec(
            "INSERT INTO access_tokens (hash, kind, client_id, name, scopes, created_at)"
            " VALUES (?, 'pat', ?, ?, ?, ?)",
            (token_hash(token), f"pat:{name}", name, " ".join(scopes), time.time()))
        return token

    def list_pats(self) -> List[sqlite3.Row]:
        with self._lock:
            return self._db.execute(
                "SELECT name, scopes, created_at FROM access_tokens WHERE kind = 'pat' AND revoked = 0"
                " ORDER BY created_at").fetchall()

    def revoke_pat(self, name: str) -> bool:
        cur = self._exec("UPDATE access_tokens SET revoked = 1 WHERE kind = 'pat' AND name = ? AND revoked = 0",
                         (name,))
        return cur.rowcount > 0

    def revoke_everything(self):
        """Emergency stop: revoke all tokens and forget all clients."""
        self._exec("UPDATE access_tokens SET revoked = 1")
        self._exec("UPDATE refresh_tokens SET status = 'revoked'")
        self._exec("DELETE FROM auth_codes")
        self._exec("DELETE FROM pending_authorizations")
        self.delete_all_clients()

    # -- login throttling / misc --------------------------------------------

    def record_login_failure(self, key: str):
        self._exec("INSERT INTO login_failures (key, at) VALUES (?, ?)", (key, time.time()))

    def login_failures_since(self, key: str, since: float) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM login_failures WHERE key = ? AND at > ?", (key, since))
        return row["n"]

    def get_meta(self, key: str) -> Optional[str]:
        row = self._one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        self._exec("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
