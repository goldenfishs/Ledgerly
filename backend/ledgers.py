"""Ledger memberships, one-use invitations and id-preserving legacy migration."""
import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from .core import (auth_user, check_fields, get_db, integer_field, new_session, password_hash,
                   public_user, set_session_cookie, success, text_field, utcnow, validate_password, write_audit)

router = APIRouter(prefix="/api")
DEFAULT_CATEGORIES = [("主营收入", [0]), ("其他收入", [0]), ("办公费用", [1]), ("人力费用", [1]), ("差旅交通", [1]), ("其他支出", [1]), ("账户转账", [2])]


def init_ledgers_db(app):
    """Add scopes and migrate the original single ledger in one transaction."""
    with get_db(app) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS ledgers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#7892b2', created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS ledger_members (ledger_id INTEGER NOT NULL REFERENCES ledgers(id), user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('admin','member')), enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, PRIMARY KEY(ledger_id,user_id))")
        db.execute("CREATE TABLE IF NOT EXISTS ledger_invitations (id INTEGER PRIMARY KEY AUTOINCREMENT, ledger_id INTEGER NOT NULL REFERENCES ledgers(id), token_hash TEXT NOT NULL UNIQUE, role TEXT NOT NULL, inviter_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT, accepted_at TEXT, accepted_by INTEGER REFERENCES users(id))")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        added_tables = set()
        for table in ("accounts", "categories", "flows", "audit", "studio_invoices"):
            if table in tables:
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if "ledger_id" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN ledger_id INTEGER REFERENCES ledgers(id)")
                    added_tables.add(table)
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_ledger ON {table}(ledger_id)")
        marker = db.execute("SELECT value FROM settings WHERE key='migration_default_ledger_id'").fetchone()
        default_id = json.loads(marker[0]) if marker else None
        old_users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
        migrating = bool(old_users) and not db.execute("SELECT 1 FROM ledgers").fetchone()
        if migrating:
            org = db.execute("SELECT value FROM settings WHERE key='organization'").fetchone()
            name = json.loads(org[0]).get("name", "默认账本") if org else "默认账本"
            creator = next((row["id"] for row in old_users if row["role"] == "admin"), old_users[0]["id"])
            stamp = utcnow()
            default_id = db.execute("INSERT INTO ledgers(name,created_by,created_at,updated_at) VALUES (?,?,?,?)", (name, creator, stamp, stamp)).lastrowid
            for row in old_users:
                db.execute("INSERT INTO ledger_members VALUES (?,?,?,?,?)", (default_id, row["id"], row["role"], row["enabled"], stamp))
            db.execute("INSERT INTO settings VALUES ('migration_default_ledger_id',?)", (json.dumps(default_id),))
        if default_id is not None:
            for table in ("accounts", "categories", "flows", "audit", "studio_invoices"):
                if table in tables and (migrating or table in added_tables):
                    db.execute(f"UPDATE {table} SET ledger_id=? WHERE ledger_id IS NULL", (default_id,))
        app.state.default_ledger_id = default_id


def ledger_record(db, ledger_id, user_id):
    row = db.execute("SELECT l.*,m.role FROM ledgers l JOIN ledger_members m ON m.ledger_id=l.id WHERE l.id=? AND m.user_id=? AND m.enabled=1", (ledger_id, user_id)).fetchone()
    if not row:
        raise HTTPException(403, "你尚未加入此账本，或成员资格已停用")
    count = db.execute("SELECT COUNT(*) FROM ledger_members m JOIN users u ON u.id=m.user_id WHERE m.ledger_id=? AND m.enabled=1 AND u.enabled=1", (ledger_id,)).fetchone()[0]
    return {"id": row["id"], "name": row["name"], "description": row["description"], "color": row["color"], "role": row["role"], "memberCount": count, "createdAt": row["created_at"]}


def list_ledgers(db, user_id):
    return [ledger_record(db, row[0], user_id) for row in db.execute("SELECT ledger_id FROM ledger_members WHERE user_id=? AND enabled=1 ORDER BY ledger_id", (user_id,)).fetchall()]


def scoped_user(db, user, ledger_id=None, *, fallback=False):
    ledgers = list_ledgers(db, user["id"])
    if ledger_id is None:
        selected = ledgers[0] if ledgers else None
    else:
        selected = next((item for item in ledgers if item["id"] == ledger_id), None)
        if selected is None and fallback:
            selected = ledgers[0] if ledgers else None
    if selected is None:
        raise HTTPException(403, "请先加入或选择可访问的账本")
    return {**user, "globalRole": user.get("globalRole", user["role"]), "canCreateLedgers": user.get("globalRole", user["role"]) == "admin", "role": selected["role"], "ledgerId": selected["id"]}


def require_ledger_admin(db, ledger_id, user):
    member = scoped_user(db, user, ledger_id)
    if member["role"] != "admin":
        raise HTTPException(403, "此操作需要当前账本管理员权限")
    return member


def create_ledger(db, user, name, description="", color="#7892b2"):
    stamp = utcnow()
    identifier = db.execute("INSERT INTO ledgers(name,description,color,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?)", (name, description, color, user["id"], stamp, stamp)).lastrowid
    db.execute("INSERT INTO ledger_members VALUES (?,?,'admin',1,?)", (identifier, user["id"], stamp))
    for category, actions in DEFAULT_CATEGORIES:
        db.execute("INSERT INTO categories(name,action_ids,created_at,updated_at,ledger_id) VALUES (?,?,?,?,?)", (category, json.dumps(actions), stamp, stamp, identifier))
    write_audit(db, {**user, "ledgerId": identifier}, "create", "ledger", identifier, {"name": name})
    return ledger_record(db, identifier, user["id"])


def member_record(row):
    return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["member_role"], "enabled": bool(row["member_enabled"] and row["enabled"])}


def members(db, ledger_id):
    return [member_record(row) for row in db.execute("SELECT u.*,m.role member_role,m.enabled member_enabled FROM users u JOIN ledger_members m ON m.user_id=u.id WHERE m.ledger_id=? ORDER BY u.id", (ledger_id,))]


def change_member(db, ledger_id, user_id, *, role=None, enabled=None, remove=False):
    row = db.execute("SELECT * FROM ledger_members WHERE ledger_id=? AND user_id=?", (ledger_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "成员不在当前账本")
    next_role = role if role is not None else row["role"]
    next_enabled = enabled if enabled is not None else bool(row["enabled"])
    if next_role not in ("admin", "member"):
        raise HTTPException(422, "角色无效")
    if row["role"] == "admin" and row["enabled"] and (remove or next_role != "admin" or not next_enabled):
        count = db.execute("SELECT COUNT(*) FROM ledger_members m JOIN users u ON u.id=m.user_id WHERE m.ledger_id=? AND m.role='admin' AND m.enabled=1 AND u.enabled=1", (ledger_id,)).fetchone()[0]
        if count <= 1:
            raise HTTPException(409, "必须保留至少一位启用的账本管理员")
    if row["role"] == "admin" and (remove or next_role != "admin" or not next_enabled):
        db.execute("UPDATE ledger_invitations SET revoked_at=? WHERE ledger_id=? AND inviter_id=? AND accepted_at IS NULL AND revoked_at IS NULL", (utcnow(), ledger_id, user_id))
    if remove:
        db.execute("DELETE FROM ledger_members WHERE ledger_id=? AND user_id=?", (ledger_id, user_id))
    else:
        db.execute("UPDATE ledger_members SET role=?,enabled=? WHERE ledger_id=? AND user_id=?", (next_role, int(next_enabled), ledger_id, user_id))


def validated_ledger_payload(payload, previous=None):
    check_fields(payload, {"name", "description", "color"})
    previous = previous or {}
    name = text_field(payload.get("name", previous.get("name")), "账本名称", maximum=120, required=True)
    description = text_field(payload.get("description", previous.get("description", "")), "账本说明", maximum=1000)
    color = payload.get("color", previous.get("color", "#7892b2"))
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise HTTPException(422, "账本颜色必须为六位十六进制颜色")
    return name, description, color


@router.get("/ledgers")
async def get_ledgers(request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        return success(list_ledgers(db, user["id"]))


@router.post("/ledgers")
async def add_ledger(request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    if user["globalRole"] != "admin":
        raise HTTPException(403, "只有平台管理员可以创建账本")
    values = validated_ledger_payload(payload)
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        return success(create_ledger(db, user, *values))


@router.put("/ledgers/{ledger_id}")
async def edit_ledger(ledger_id: int, request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_ledger_admin(db, ledger_id, user)
        previous = ledger_record(db, ledger_id, user["id"])
        values = validated_ledger_payload(payload, previous)
        db.execute("UPDATE ledgers SET name=?,description=?,color=?,updated_at=? WHERE id=?", (*values, utcnow(), ledger_id))
        write_audit(db, actor, "update", "ledger", ledger_id, {"before": previous, "after": payload})
        return success(ledger_record(db, ledger_id, user["id"]))


@router.get("/ledgers/{ledger_id}/members")
async def get_members(ledger_id: int, request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        require_ledger_admin(db, ledger_id, user)
        return success(members(db, ledger_id))


@router.put("/ledgers/{ledger_id}/members/{user_id}")
async def edit_member(ledger_id: int, user_id: int, request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    check_fields(payload, {"role"})
    if payload.get("role") not in ("admin", "member"):
        raise HTTPException(422, "角色无效")
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_ledger_admin(db, ledger_id, user)
        change_member(db, ledger_id, user_id, role=payload["role"])
        write_audit(db, actor, "role", "member", user_id, payload)
        return success(next(item for item in members(db, ledger_id) if item["id"] == user_id))


@router.delete("/ledgers/{ledger_id}/members/{user_id}")
async def remove_member(ledger_id: int, user_id: int, request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_ledger_admin(db, ledger_id, user)
        change_member(db, ledger_id, user_id, remove=True)
        write_audit(db, actor, "remove", "member", user_id)
    return success()


def invitation_status(row):
    if row["accepted_at"]:
        return "accepted"
    if row["revoked_at"] or "inviter_active" in row.keys() and not row["inviter_active"]:
        return "revoked"
    if row["expires_at"] <= utcnow():
        return "expired"
    return "pending"


def token_row(db, token, *, usable=False):
    if len(token) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", token):
        raise HTTPException(404, "邀请不存在")
    row = db.execute("SELECT i.*,l.name ledger_name,u.name inviter_name,(u.enabled=1 AND m.enabled=1 AND m.role='admin') inviter_active FROM ledger_invitations i JOIN ledgers l ON l.id=i.ledger_id JOIN users u ON u.id=i.inviter_id LEFT JOIN ledger_members m ON m.ledger_id=i.ledger_id AND m.user_id=i.inviter_id WHERE i.token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row:
        raise HTTPException(404, "邀请不存在")
    if usable and invitation_status(row) != "pending":
        raise HTTPException(410, "邀请已使用、过期或撤销，请联系账本管理员重新邀请")
    return row


@router.get("/ledgers/{ledger_id}/invitations")
async def get_invitations(ledger_id: int, request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        require_ledger_admin(db, ledger_id, user)
        return success([{"id": row["id"], "role": row["role"], "expiresAt": row["expires_at"], "createdAt": row["created_at"], "status": invitation_status(row)} for row in db.execute("SELECT * FROM ledger_invitations WHERE ledger_id=? ORDER BY id DESC", (ledger_id,))])


@router.post("/ledgers/{ledger_id}/invitations")
async def invite(ledger_id: int, request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    check_fields(payload, {"role", "expiresInDays"})
    role = payload.get("role", "member")
    if role not in ("admin", "member"):
        raise HTTPException(422, "邀请角色无效")
    days = integer_field(payload.get("expiresInDays", 7), "有效天数", minimum=1)
    if days > 30:
        raise HTTPException(422, "邀请有效期最多 30 天")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="microseconds")
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_ledger_admin(db, ledger_id, user)
        identifier = db.execute("INSERT INTO ledger_invitations(ledger_id,token_hash,role,inviter_id,expires_at,created_at) VALUES (?,?,?,?,?,?)", (ledger_id, hashlib.sha256(token.encode()).hexdigest(), role, user["id"], expires, utcnow())).lastrowid
        write_audit(db, actor, "invite", "invitation", identifier, {"role": role, "expiresAt": expires})
        return success({"id": identifier, "token": token, "expiresAt": expires, "role": role})


@router.delete("/ledgers/{ledger_id}/invitations/{invitation_id}")
async def revoke_invitation(ledger_id: int, invitation_id: int, request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_ledger_admin(db, ledger_id, user)
        row = db.execute("SELECT * FROM ledger_invitations WHERE id=? AND ledger_id=?", (invitation_id, ledger_id)).fetchone()
        if not row:
            raise HTTPException(404, "邀请不存在")
        if row["accepted_at"]:
            raise HTTPException(410, "邀请已使用，请在成员管理中调整权限")
        db.execute("UPDATE ledger_invitations SET revoked_at=? WHERE id=? AND ledger_id=?", (utcnow(), invitation_id, ledger_id))
        write_audit(db, actor, "revoke", "invitation", invitation_id)
    return success()


@router.get("/invitations/{token}")
async def public_invitation(token: str, request: Request):
    with get_db(request) as db:
        row = token_row(db, token)
        return success({"ledgerName": row["ledger_name"], "inviterName": row["inviter_name"], "role": row["role"], "expiresAt": row["expires_at"], "status": invitation_status(row)})


def consume_invitation(db, row, user):
    previous = db.execute("SELECT * FROM ledger_members WHERE ledger_id=? AND user_id=?", (row["ledger_id"], user["id"])).fetchone()
    if previous is None:
        db.execute("INSERT INTO ledger_members VALUES (?,?,?,1,?)", (row["ledger_id"], user["id"], row["role"], utcnow()))
    elif not previous["enabled"]:
        db.execute("UPDATE ledger_members SET enabled=1,role=? WHERE ledger_id=? AND user_id=?", (row["role"], row["ledger_id"], user["id"]))
    db.execute("UPDATE ledger_invitations SET accepted_at=?,accepted_by=? WHERE id=?", (utcnow(), user["id"], row["id"]))
    actor = scoped_user(db, user, row["ledger_id"])
    write_audit(db, actor, "join", "ledger", row["ledger_id"], {"invitationId": row["id"]})
    return {"ledgerId": row["ledger_id"], "ledger": ledger_record(db, row["ledger_id"], user["id"]), "user": actor}


@router.post("/invitations/{token}/accept")
async def accept_invitation(token: str, request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        return success(consume_invitation(db, token_row(db, token, usable=True), user))


@router.post("/invitations/{token}/register")
async def register_invitation(token: str, request: Request, response: Response, payload: dict = Body(...)):
    from .identity import validate_registration
    from .system import system_config
    check_fields(payload, {"username", "name", "password", "email", "emailCode"})
    username = text_field(payload.get("username"), "用户名", maximum=40, required=True).lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
        raise HTTPException(422, "用户名使用 3–40 位字母、数字、点、下划线或短横线")
    name = text_field(payload.get("name"), "姓名", maximum=80, required=True)
    with get_db(request) as db:
        token_row(db, token, usable=True)
        if system_config(db)["registrationMode"] == "closed":
            raise HTTPException(403, "管理员已关闭新用户注册")
    request.app.state.login_limiter.check(request, "invite:" + username)
    digest, salt = password_hash(validate_password(payload.get("password")))
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        row = token_row(db, token, usable=True)
        if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise HTTPException(409, "用户名已存在，请登录后接受邀请")
        verified = validate_registration(db, request.app, payload, invited=True, invitation_token=token)
        stamp = utcnow()
        try:
            identifier = db.execute("INSERT INTO users(username,name,role,enabled,password_hash,password_salt,created_at,updated_at,email,email_verified_at) VALUES (?,?,'member',1,?,?,?,?,?,?)", (username, name, digest, salt, stamp, stamp, verified["email"], verified["email_verified_at"])).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名或邮箱已被使用") from None
        user = public_user(db.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone())
        result = consume_invitation(db, row, user)
        session = new_session(db, identifier)
    set_session_cookie(response, session, request)
    return success(result)
