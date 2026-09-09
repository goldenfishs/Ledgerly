"""Invitation-aware registration and single-use email verification codes."""
import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, Response

from . import system
from .core import check_fields, get_db, new_session, password_hash, public_user, set_session_cookie, success, text_field, utcnow, validate_password
from .system import normalize_email

router = APIRouter(prefix="/api")
CODE_SECONDS = 600
RESEND_SECONDS = 60


def init_identity_db(app):
    with get_db(app) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS email_challenges (
                id TEXT PRIMARY KEY,email TEXT NOT NULL,purpose TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id),context TEXT NOT NULL DEFAULT '',
                code_hash TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,
                delivered_at TEXT,consumed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS email_challenges_target ON email_challenges(email,purpose,user_id,context,created_at);
            CREATE TABLE IF NOT EXISTS email_rate_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,email_hash TEXT NOT NULL,
                source_hash TEXT NOT NULL,purpose TEXT NOT NULL,created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS email_rate_target ON email_rate_events(email_hash,created_at);
            CREATE INDEX IF NOT EXISTS email_rate_source ON email_rate_events(source_hash,created_at);
        """)


def invitation_context(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""


def code_digest(app, identifier, email, purpose, context, user_id, code):
    value = "\x00".join((identifier, email, purpose, context, str(user_id or ""), code))
    return hmac.new(app.state.email_hmac_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def record_send_attempt(db, request, email, purpose):
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).isoformat(timespec="microseconds")
    minute_ago = (now - timedelta(seconds=RESEND_SECONDS)).isoformat(timespec="microseconds")
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    source = request.client.host if request.client else "unknown"
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if db.execute("SELECT 1 FROM email_rate_events WHERE email_hash=? AND created_at>?", (email_hash, minute_ago)).fetchone():
        raise HTTPException(429, "验证码已发送，请一分钟后重试", headers={"Retry-After": str(RESEND_SECONDS)})
    email_count = db.execute("SELECT COUNT(*) FROM email_rate_events WHERE email_hash=? AND created_at>?", (email_hash, hour_ago)).fetchone()[0]
    source_count = db.execute("SELECT COUNT(*) FROM email_rate_events WHERE source_hash=? AND created_at>?", (source_hash, hour_ago)).fetchone()[0]
    global_count = db.execute("SELECT COUNT(*) FROM email_rate_events WHERE created_at>?", (hour_ago,)).fetchone()[0]
    if email_count >= 5 or source_count >= 20 or global_count >= 200:
        raise HTTPException(429, "邮件请求过于频繁，请稍后再试", headers={"Retry-After": "3600"})
    db.execute("DELETE FROM email_rate_events WHERE created_at<?", (hour_ago,))
    db.execute("INSERT INTO email_rate_events(email_hash,source_hash,purpose,created_at) VALUES (?,?,?,?)", (email_hash, source_hash, purpose, now.isoformat(timespec="microseconds")))


def finish_delivery(app, config, email, subject, body, challenge_id, *, suppress_error=False):
    try:
        system.deliver_email(app, config, email, subject, body)
    except HTTPException:
        with get_db(app) as db:
            db.execute("UPDATE email_challenges SET consumed_at=? WHERE id=?", (utcnow(), challenge_id))
        if not suppress_error:
            raise
    else:
        with get_db(app) as db:
            db.execute("UPDATE email_challenges SET delivered_at=? WHERE id=? AND consumed_at IS NULL", (utcnow(), challenge_id))


def issue_verification_code(request, email, purpose="bind-email", user_id=None, *, context="", invitation_token=None, background=None):
    email = normalize_email(email)
    if purpose not in {"register", "reset-password", "bind-email"}:
        raise HTTPException(422, "验证码用途无效")
    if purpose == "bind-email" and user_id is None:
        raise HTTPException(401, "请先登录")
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        policy = system.system_config(db)
        if purpose == "register":
            if policy["registrationMode"] == "closed":
                raise HTTPException(403, "管理员已关闭新用户注册")
            if invitation_token:
                from .ledgers import token_row
                token_row(db, invitation_token, usable=True)
                context = invitation_context(invitation_token)
            elif policy["registrationMode"] != "open":
                raise HTTPException(403, "请通过管理员的邀请链接注册")
        if not system.mail_available(db):
            raise HTTPException(503, "管理员尚未启用邮箱服务")
        record_send_attempt(db, request, email, purpose)
        config = system.mail_config(db)
        should_send = True
        if purpose == "reset-password":
            row = db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND email_verified_at IS NOT NULL AND enabled=1", (email,)).fetchone()
            user_id = row["id"] if row else None
            should_send = row is not None
        elif purpose == "register":
            should_send = db.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone() is None
        if should_send:
            identifier = secrets.token_hex(24)
            code = f"{secrets.randbelow(1_000_000):06d}"
            now = datetime.now(timezone.utc)
            stamp = now.isoformat(timespec="microseconds")
            db.execute("DELETE FROM email_challenges WHERE expires_at<?", ((now - timedelta(days=1)).isoformat(timespec="microseconds"),))
            db.execute("UPDATE email_challenges SET consumed_at=? WHERE email=? AND purpose=? AND consumed_at IS NULL", (stamp, email, purpose))
            db.execute("INSERT INTO email_challenges(id,email,purpose,user_id,context,code_hash,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?)", (identifier, email, purpose, user_id, context, code_digest(request.app, identifier, email, purpose, context, user_id, code), stamp, (now + timedelta(seconds=CODE_SECONDS)).isoformat(timespec="microseconds")))
    if should_send:
        action = {"register": "注册账号", "reset-password": "重置密码", "bind-email": "绑定邮箱"}[purpose]
        subject = policy["siteName"] + " · " + action + "验证码"
        body = f"您正在{action}。\n\n验证码：{code}\n\n验证码在 10 分钟内有效，仅可使用一次。请勿将验证码提供给他人。\n如果不是您本人操作，请忽略此邮件。"
        if background is not None:
            background.add_task(finish_delivery, request.app, config, email, subject, body, identifier, suppress_error=True)
        else:
            finish_delivery(request.app, config, email, subject, body, identifier)
    return {"expiresIn": CODE_SECONDS, "retryAfter": RESEND_SECONDS}


def consume_email_code(db, app, email, purpose, code, user_id=None, *, context=""):
    email = normalize_email(email)
    app.state.email_verify_limiter.check(("email-code", email, purpose, user_id))
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(422, "验证码无效或已过期")
    row = db.execute("SELECT * FROM email_challenges WHERE email=? AND purpose=? AND user_id IS ? AND context=? AND consumed_at IS NULL AND delivered_at IS NOT NULL AND expires_at>? ORDER BY created_at DESC LIMIT 1", (email, purpose, user_id, context, utcnow())).fetchone()
    if row is None or not hmac.compare_digest(row["code_hash"], code_digest(app, row["id"], email, purpose, context, user_id, code)):
        raise HTTPException(422, "验证码无效或已过期")
    updated = db.execute("UPDATE email_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL", (utcnow(), row["id"])).rowcount
    if updated != 1:
        raise HTTPException(422, "验证码无效或已过期")


def validate_registration(db, app, payload, *, invited=False, invitation_token=None):
    """Call inside the same transaction as creating the account/invitation membership."""
    config = system.system_config(db)
    if config["registrationMode"] == "closed":
        raise HTTPException(403, "管理员已关闭新用户注册")
    if not invited and config["registrationMode"] != "open":
        raise HTTPException(403, "请通过管理员的邀请链接注册")
    raw_email = payload.get("email")
    if raw_email in (None, ""):
        if config["emailVerificationRequired"]:
            raise HTTPException(422, "注册时需要验证邮箱")
        if payload.get("emailCode"):
            raise HTTPException(422, "请填写验证码对应的邮箱")
        return {"email": None, "email_verified_at": None}
    email = normalize_email(raw_email)
    if db.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone():
        raise HTTPException(409, "此邮箱已被使用，请登录或使用其他邮箱")
    consume_email_code(db, app, email, "register", payload.get("emailCode"), context=invitation_context(invitation_token))
    return {"email": email, "email_verified_at": utcnow()}


@router.post("/auth/email-code")
def send_email_code(request: Request, background: BackgroundTasks, payload: dict = Body(...)):
    check_fields(payload, {"email", "purpose", "invitationToken"})
    purpose = payload.get("purpose")
    if purpose not in ("register", "reset-password"):
        raise HTTPException(422, "验证码用途无效")
    token = payload.get("invitationToken")
    if token is not None and (not isinstance(token, str) or len(token) > 256):
        raise HTTPException(422, "邀请链接无效")
    if purpose != "register" and token:
        raise HTTPException(422, "验证码用途无效")
    result = issue_verification_code(request, payload.get("email"), purpose, invitation_token=token, background=background if purpose == "reset-password" else None)
    return success(result, "若该邮箱可用于此操作，验证码将发送至邮箱，请检查收件箱")


@router.post("/auth/register")
def register(request: Request, response: Response, payload: dict = Body(...)):
    check_fields(payload, {"username", "name", "password", "email", "emailCode"})
    username = text_field(payload.get("username"), "用户名", maximum=40, required=True).lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
        raise HTTPException(422, "用户名使用 3–40 位字母、数字、点、下划线或短横线")
    name = text_field(payload.get("name"), "姓名", maximum=80, required=True)
    request.app.state.login_limiter.check(request, "register:" + username)
    with get_db(request) as db:
        if system.system_config(db)["registrationMode"] != "open":
            raise HTTPException(403, "当前不允许公开注册，请联系管理员")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            raise HTTPException(409, "请先初始化系统管理员")
    digest, salt = password_hash(validate_password(payload.get("password")))
    try:
        with get_db(request) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise HTTPException(409, "用户名已被使用")
            verified = validate_registration(db, request.app, payload)
            stamp = utcnow()
            identifier = db.execute("INSERT INTO users(username,name,role,enabled,password_hash,password_salt,created_at,updated_at,email,email_verified_at) VALUES (?,?,'member',1,?,?,?,?,?,?)", (username, name, digest, salt, stamp, stamp, verified["email"], verified["email_verified_at"])).lastrowid
            token = new_session(db, identifier)
            user = public_user(db.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(409, "用户名或邮箱已被使用") from None
    set_session_cookie(response, token, request)
    return success({"user": user}, "账号已注册，请通过邀请链接加入账本")


@router.post("/auth/reset-password")
def reset_password(request: Request, response: Response, payload: dict = Body(...)):
    check_fields(payload, {"email", "emailCode", "newPassword"})
    email = normalize_email(payload.get("email"))
    request.app.state.login_limiter.check(request, "reset:" + email)
    digest, salt = password_hash(validate_password(payload.get("newPassword")))
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND email_verified_at IS NOT NULL AND enabled=1", (email,)).fetchone()
        consume_email_code(db, request.app, email, "reset-password", payload.get("emailCode"), user_id=row["id"] if row else None)
        if row is None:
            raise HTTPException(422, "验证码无效或已过期")
        db.execute("UPDATE users SET password_hash=?,password_salt=?,updated_at=? WHERE id=?", (digest, salt, utcnow(), row["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        db.execute("UPDATE email_challenges SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL", (utcnow(), row["id"]))
    response.delete_cookie("studio_session", path="/")
    return success(None, "密码已重置，请使用新密码登录")
