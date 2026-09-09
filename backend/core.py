"""Shared database, authentication and validation for the independent Studio ledger."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

PASSWORD_ITERATIONS = 600_000
SESSION_HOURS = 12
ACTIONS = [
    {"id": 0, "hname": "收入", "handle": 0, "exempt": False, "disable": False},
    {"id": 1, "hname": "支出", "handle": 1, "exempt": False, "disable": False},
    {"id": 2, "hname": "转账", "handle": 2, "exempt": False, "disable": False},
]




class LoginLimiter:
    """Small bounded per-process throttle for password verification attempts."""
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = OrderedDict()

    def check(self, request, username):
        source = request.client.host if request.client else "unknown"
        now = time.monotonic()
        keys = [("source", source), ("account", source, username)]
        with self.lock:
            windows = [[instant for instant in self.attempts.get(key, []) if now - instant < 60] for key in keys]
            if len(windows[0]) >= 30 or len(windows[1]) >= 10:
                raise HTTPException(429, "登录尝试过于频繁，请一分钟后重试", headers={"Retry-After": "60"})
            for key, values in zip(keys, windows):
                self.attempts[key] = values + [now]
                self.attempts.move_to_end(key)
            while len(self.attempts) > 2048:
                self.attempts.popitem(last=False)


class SameOriginMiddleware:
    """Block browser cross-origin writes, including same-site multipart CSRF.

    CLI clients without browser Origin/Fetch-Metadata remain usable. Browser
    requests with an Origin must match this service or its configured public URL.
    """
    def __init__(self, app, public_origin=""):
        self.app = app
        self.public_origin = public_origin.rstrip("/").lower()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and scope.get("path", "").startswith("/api/"):
            headers = {key.lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
            origin = headers.get(b"origin")
            expected = self.public_origin or (scope.get("scheme", "http") + "://" + headers.get(b"host", "")).lower()
            rejected = headers.get(b"sec-fetch-site") == "cross-site"
            if origin is not None:
                try:
                    parsed = urlsplit(origin)
                    actual = (parsed.scheme + "://" + parsed.netloc).lower()
                    rejected = rejected or parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.path not in {"", "/"} or bool(parsed.query or parsed.fragment) or actual != expected
                except ValueError:
                    rejected = True
            elif headers.get(b"sec-fetch-site") == "same-site":
                rejected = True
            if rejected:
                response = JSONResponse(status_code=403, content={"code": 403, "msg": "请从工作室账本页面发起此操作", "data": None})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@contextmanager
def get_db(request_or_app):
    app = getattr(request_or_app, "app", request_or_app)
    directory = Path(app.state.data_dir)
    connection = sqlite3.connect(directory / "studio.sqlite3", timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db(app):
    app.state.data_dir.mkdir(parents=True, exist_ok=True)
    with get_db(app) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','member')),
                enabled INTEGER NOT NULL DEFAULT 1,
                password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                initial_cents INTEGER NOT NULL DEFAULT 0, account_type INTEGER NOT NULL DEFAULT 0,
                card TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                parent INTEGER REFERENCES categories(id), action_ids TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT, cents INTEGER NOT NULL CHECK(cents > 0),
                fdate TEXT NOT NULL, action_id INTEGER NOT NULL CHECK(action_id IN (0,1,2)),
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                account_to_id INTEGER REFERENCES accounts(id), type_id INTEGER NOT NULL REFERENCES categories(id),
                collect INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', images TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
                owner_id INTEGER NOT NULL REFERENCES users(id), review_comment TEXT NOT NULL DEFAULT '',
                reviewed_by INTEGER REFERENCES users(id), reviewed_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                deleted_at TEXT, version INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS flows_owner_date ON flows(owner_id, fdate);
            CREATE INDEX IF NOT EXISTS flows_status ON flows(status, deleted_at);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER REFERENCES users(id), actor_name TEXT NOT NULL,
                action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT,
                detail TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
        """)

    from .ledgers import init_ledgers_db
    init_ledgers_db(app)
    # Add optional identity fields without changing existing account credentials.
    with get_db(app) as connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        for column in ("email", "email_verified_at", "avatar_filename"):
            if column not in columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email COLLATE NOCASE) WHERE email IS NOT NULL")


def write_audit(connection, user, action, entity_type, entity_id, detail=None):
    connection.execute(
        "INSERT INTO audit(actor_id,actor_name,action,entity_type,entity_id,detail,created_at,ledger_id) VALUES (?,?,?,?,?,?,?,?)",
        (user.get("id") if user else None, user.get("name", "") if user else "", action, entity_type,
         str(entity_id) if entity_id is not None else None, json.dumps(detail or {}, ensure_ascii=False), utcnow(), user.get("ledgerId") if user else None),
    )


def public_user(row):
    avatar = row["avatar_filename"] if "avatar_filename" in row.keys() else None
    return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"], "globalRole": row["role"], "canCreateLedgers": row["role"] == "admin", "canManageSystem": row["role"] == "admin", "enabled": bool(row["enabled"]), "avatarUrl": f"/api/profile/avatar?version={avatar}" if avatar else None}


def request_token(request):
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return authorization
    return request.cookies.get("studio_session", "")


def session_user(request, *, required=True):
    token = request_token(request)
    user = None
    if token and len(token) <= 256:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with get_db(request) as connection:
            row = connection.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1",
                (digest, utcnow()),
            ).fetchone()
            if row:
                user = public_user(row)
    if required and user is None:
        raise HTTPException(401, "请登录工作室账本")
    return user


async def auth_user(request: Request):
    return session_user(request)


def selected_ledger_id(request):
    value = request.headers.get("x-ledger-id")
    if value is None or value == "":
        return None
    if not value.isascii() or not value.isdigit() or len(value) > 18 or int(value) < 1:
        raise HTTPException(422, "账本选择无效")
    return int(value)


async def current_user(request: Request):
    from .ledgers import scoped_user
    user = session_user(request)
    with get_db(request) as db:
        return scoped_user(db, user, selected_ledger_id(request))


async def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "此操作需要管理员权限")
    return user


def validate_password(password):
    if not isinstance(password, str) or len(password) < 8 or len(password) > 256:
        raise HTTPException(422, "密码长度应为 8–256 位")
    try:
        password.encode("utf-8")
    except UnicodeError:
        raise HTTPException(422, "密码包含无效字符")
    return password


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return digest, salt


def password_matches(password, row):
    if not isinstance(password, str) or len(password) > 256:
        return False
    try:
        candidate, _ = password_hash(password, row["password_salt"])
    except UnicodeError:
        return False
    return hmac.compare_digest(candidate, row["password_hash"])


def new_session(connection, user_id):
    token = secrets.token_urlsafe(32)
    timestamp = datetime.now(timezone.utc)
    connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (timestamp.isoformat(timespec="microseconds"),))
    connection.execute("INSERT INTO sessions VALUES (?,?,?,?)", (
        hashlib.sha256(token.encode()).hexdigest(), user_id,
        timestamp.isoformat(timespec="microseconds"),
        (timestamp + timedelta(hours=SESSION_HOURS)).isoformat(timespec="microseconds"),
    ))
    return token


def set_session_cookie(response, token, request):
    secure = os.getenv("STUDIO_COOKIE_SECURE", "").lower() in {"true", "1"} or request.url.scheme == "https"
    response.set_cookie("studio_session", token, max_age=SESSION_HOURS * 3600,
                        httponly=True, secure=secure, samesite="lax", path="/")


def money_cents(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise HTTPException(422, "金额必须是有效数字")
    text = str(value).strip()
    if len(text) > 30 or not re.fullmatch(r"-?\d{1,12}(?:\.\d{1,2})?", text):
        raise HTTPException(422, "金额最多两位小数和 12 位整数")
    try:
        cents = int(Decimal(text) * 100)
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "金额无效")
    if positive and cents <= 0:
        raise HTTPException(422, "流水金额必须大于零")
    return cents


def money_text(cents):
    return format(Decimal(cents) / 100, ".2f")


def text_field(value, label, *, maximum=200, required=False):
    if not isinstance(value, str):
        raise HTTPException(422, label + "格式无效")
    value = value.strip()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise HTTPException(422, label + "包含无效字符")
    if len(value) > maximum or required and not value:
        raise HTTPException(422, label + ("不能为空或过长" if required else "过长"))
    return value


def integer_field(value, label, *, allowed=None, minimum=None):
    if type(value) is not int or allowed is not None and value not in allowed or minimum is not None and value < minimum:
        raise HTTPException(422, label + "无效")
    return value


def boolean_field(value, label):
    if type(value) is not bool:
        raise HTTPException(422, label + "必须为布尔值")
    return value


def date_field(value, label="日期"):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(422, label + "必须为 YYYY-MM-DD")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(422, label + "无效")


def month_field(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise HTTPException(422, "月份必须为 YYYY-MM")
    date_field(value + "-01")
    return value


def check_fields(payload, allowed):
    if not isinstance(payload, dict) or set(payload) - set(allowed):
        raise HTTPException(422, "请求包含不支持的字段")


def check_version(payload, row):
    if "version" in payload:
        version = integer_field(payload["version"], "版本", minimum=1)
        if version != row["version"]:
            raise HTTPException(409, "记录已被修改，请刷新后重试")


def success(data=None, msg="成功"):
    return {"code": 0, "msg": msg, "data": data}
