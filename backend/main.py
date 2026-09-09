"""Independent multi-user Studio ledger; never connects to the original database."""
import calendar
import hashlib
import importlib
import json
import os
import re
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .core import (
    ACTIONS, LoginLimiter, SameOriginMiddleware, boolean_field, check_fields, check_version, current_user, date_field,
    get_db, init_db, integer_field, auth_user, selected_ledger_id, money_cents, money_text, month_field, new_session,
    password_hash, password_matches, public_user, request_token, require_admin,
    session_user, set_session_cookie, success, text_field, utcnow, validate_password,
    write_audit,
)

from .ledgers import (router as ledgers_router, list_ledgers, scoped_user, create_ledger,
                      members as ledger_members_list, change_member, ledger_record)


def user_scope(user, prefix=""):
    clause, args = f" AND {prefix}ledger_id=?", [user["ledgerId"]]
    if user["role"] != "admin":
        clause += f" AND {prefix}owner_id=?"
        args.append(user["id"])
    return clause, args


def account_records(connection, user, *, enabled_only=False):
    rows = connection.execute("SELECT * FROM accounts WHERE ledger_id=? ORDER BY enabled DESC,id", (user["ledgerId"],)).fetchall()
    balances = {row["id"]: row["initial_cents"] for row in rows}
    account_types = {row["id"]: row["account_type"] for row in rows}
    if user["role"] == "admin":
        for flow in connection.execute("SELECT cents,action_id,account_id,account_to_id FROM flows WHERE status='approved' AND deleted_at IS NULL AND ledger_id=?", (user["ledgerId"],)):
            source = flow["account_id"]
            direction = 1 if flow["action_id"] == 0 else -1
            balances[source] += direction * flow["cents"] * (-1 if account_types[source] == 1 else 1)
            if flow["action_id"] == 2:
                target = flow["account_to_id"]
                balances[target] += flow["cents"] * (-1 if account_types[target] == 1 else 1)
    return [{"id": row["id"], "name": row["name"], "aname": row["name"],
             "money": money_text(balances[row["id"]]) if user["role"] == "admin" else None,
             "initialMoney": money_text(row["initial_cents"]) if user["role"] == "admin" else None,
             "accountType": row["account_type"], "card": row["card"] if user["role"] == "admin" else "",
             "enable": bool(row["enabled"]), "disable": not bool(row["enabled"])}
            for row in rows if not enabled_only or row["enabled"]]


def category_record(row):
    return {"id": row["id"], "tname": row["name"], "name": row["name"], "parent": row["parent"],
            "actionIds": json.loads(row["action_ids"]), "enable": bool(row["enabled"]),
            "disable": not bool(row["enabled"]), "archive": not bool(row["enabled"]), "child": [], "childrenTypes": []}


def category_tree(connection, user, *, include_disabled=False, action_id=None):
    rows = connection.execute("SELECT * FROM categories WHERE ledger_id=? ORDER BY id", (user["ledgerId"],)).fetchall()
    nodes = {row["id"]: category_record(row) for row in rows if (include_disabled or row["enabled"]) and (action_id is None or action_id in json.loads(row["action_ids"]))}
    roots = []
    for node in nodes.values():
        if node["parent"] in nodes:
            parent = nodes[node["parent"]]
            parent["child"].append(node)
            parent["childrenTypes"].append(node)
        else:
            roots.append(node)
    return roots


def flow_record(connection, row, user, cache=None):
    if cache is None:
        cache = {"accounts": {item["id"]: item for item in account_records(connection, user)},
                 "types": {item["id"]: category_record(item) for item in connection.execute("SELECT * FROM categories WHERE ledger_id=?", (user["ledgerId"],))},
                 "users": {item["id"]: item["name"] for item in connection.execute("SELECT DISTINCT u.id,u.name FROM users u WHERE u.id IN (SELECT user_id FROM ledger_members WHERE ledger_id=?) OR u.id IN (SELECT owner_id FROM flows WHERE ledger_id=?)", (user["ledgerId"], user["ledgerId"]))}}
    account = cache["accounts"].get(row["account_id"])
    account_to = cache["accounts"].get(row["account_to_id"])
    category = cache["types"].get(row["type_id"])
    return {"id": row["id"], "money": money_text(row["cents"]), "fdate": row["fdate"],
            "actionId": row["action_id"], "accountId": row["account_id"], "accountToId": row["account_to_id"], "typeId": row["type_id"],
            "action": ACTIONS[row["action_id"]], "account": account, "accountTo": account_to, "type": category,
            "handle": row["action_id"], "hname": ACTIONS[row["action_id"]]["hname"],
            "aname": account["name"] if account else "", "toAName": account_to["name"] if account_to else "",
            "tname": category["tname"] if category else "", "collect": bool(row["collect"]), "exempt": False,
            "note": row["note"], "images": json.loads(row["images"]), "hasImages": bool(json.loads(row["images"])),
            "status": row["status"], "ownerId": row["owner_id"], "ownerName": cache["users"].get(row["owner_id"], ""),
            "reviewComment": row["review_comment"], "reviewedBy": row["reviewed_by"], "reviewedAt": row["reviewed_at"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"], "version": row["version"]}


def flow_records(connection, rows, user):
    cache = {"accounts": {item["id"]: item for item in account_records(connection, user)},
             "types": {item["id"]: category_record(item) for item in connection.execute("SELECT * FROM categories WHERE ledger_id=?", (user["ledgerId"],))},
             "users": {item["id"]: item["name"] for item in connection.execute("SELECT DISTINCT u.id,u.name FROM users u WHERE u.id IN (SELECT user_id FROM ledger_members WHERE ledger_id=?) OR u.id IN (SELECT owner_id FROM flows WHERE ledger_id=?)", (user["ledgerId"], user["ledgerId"]))}}
    return [flow_record(connection, row, user, cache) for row in rows]


def visible_flow(connection, flow_id, user, *, writable=False):
    scope, params = user_scope(user)
    row = connection.execute("SELECT * FROM flows WHERE id=? AND deleted_at IS NULL" + scope, [flow_id] + params).fetchone()
    if row is None:
        raise HTTPException(404, "流水不存在")
    if writable and user["role"] != "admin" and row["status"] == "approved":
        raise HTTPException(403, "已审核流水只能由管理员修改")
    return row


def flow_values(connection, payload, user, existing=None):
    check_fields(payload, {"money", "fDate", "actionId", "accountId", "accountToId", "typeId", "collect", "note", "images", "version"})
    # Updates require the same complete, explicit financial fields as creation.
    amount = money_cents(payload.get("money"), positive=True)
    fdate = date_field(payload.get("fDate"), "记账日期")
    action_id = integer_field(payload.get("actionId"), "收支类型", allowed={0, 1, 2})
    account_id = integer_field(payload.get("accountId"), "账户", minimum=1)
    account_to_id = payload.get("accountToId")
    if action_id == 2:
        account_to_id = integer_field(account_to_id, "转入账户", minimum=1)
        if account_id == account_to_id:
            raise HTTPException(422, "转出和转入账户不能相同")
    elif account_to_id not in (None, 0):
        raise HTTPException(422, "只有转账可以选择转入账户")
    else:
        account_to_id = None
    for key, selected in (("account_id", account_id), ("account_to_id", account_to_id)):
        if selected is None:
            continue
        account = connection.execute("SELECT * FROM accounts WHERE id=? AND ledger_id=?", (selected, user["ledgerId"])).fetchone()
        if not account or not account["enabled"] and not (existing and existing[key] == selected):
            raise HTTPException(422, "账户不存在或已归档")
    type_id = integer_field(payload.get("typeId"), "分类", minimum=1)
    category = connection.execute("SELECT * FROM categories WHERE id=? AND ledger_id=?", (type_id, user["ledgerId"])).fetchone()
    if not category or not category["enabled"] and not (existing and existing["type_id"] == type_id):
        raise HTTPException(422, "分类不存在或已归档")
    if action_id not in json.loads(category["action_ids"]):
        raise HTTPException(422, "分类不适用于此收支类型")
    collect = boolean_field(payload.get("collect", False), "收藏")
    note = text_field(payload.get("note", ""), "备注", maximum=2000)
    images = payload.get("images", [])
    if not isinstance(images, list) or len(images) > 10 or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}", item) or ".." in item for item in images):
        raise HTTPException(422, "附件标识无效")
    return (amount, fdate, action_id, account_id, account_to_id, type_id, int(collect), note, json.dumps(images))


def ledger_totals(rows):
    income = sum(row["cents"] for row in rows if row["status"] == "approved" and row["action_id"] == 0)
    expense = sum(row["cents"] for row in rows if row["status"] == "approved" and row["action_id"] == 1)
    return {"totalIn": money_text(income), "totalOut": money_text(expense), "totalEarn": money_text(income - expense)}


def organization(connection):
    row = connection.execute("SELECT value FROM settings WHERE key='organization'").fetchone()
    return json.loads(row["value"]) if row else {"name": "工作室账本"}


def create_app(data_dir=None, web_dir=None):
    app = FastAPI(title="Ledgerly 账序", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.login_limiter = LoginLimiter()
    app.state.llm_config_path = os.getenv("STUDIO_LLM_CONFIG_PATH", "")
    app.add_middleware(SameOriginMiddleware, public_origin=os.getenv("STUDIO_PUBLIC_ORIGIN", ""))
    app.state.data_dir = Path(data_dir or os.getenv("STUDIO_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data")))
    app.state.web_dir = Path(web_dir or os.getenv("STUDIO_WEB_DIR", str(Path(__file__).resolve().parents[1] / "frontend" / "dist")))
    init_db(app)
    from . import system, identity, profile
    system.init_system_db(app)
    identity.init_identity_db(app)
    app.include_router(system.router)
    app.include_router(identity.router)
    app.include_router(profile.router)
    app.include_router(ledgers_router)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"code": exc.status_code, "msg": str(exc.detail), "data": None}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={"code": 422, "msg": "请求格式无效，请检查必填字段", "data": None})

    @app.get("/api/health")
    async def health():
        return success({"status": "ok", "service": "studio"})

    @app.get("/api/session")
    async def session(request: Request):
        with get_db(request) as connection:
            needs_setup = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        user = session_user(request, required=False)
        result = {"needsSetup": needs_setup, "user": user, "ledgers": [], "activeLedger": None}
        if user:
            with get_db(request) as connection:
                result["organization"] = {"name": "我的工作室"}
                result["ledgers"] = list_ledgers(connection, user["id"])
                if result["ledgers"]:
                    active_user = scoped_user(connection, user, selected_ledger_id(request), fallback=True)
                    result["user"] = active_user
                    result["activeLedger"] = next(item for item in result["ledgers"] if item["id"] == active_user["ledgerId"])
                    result["organization"] = {"name": result["activeLedger"]["name"]}
        return success(result)

    @app.post("/api/auth/setup")
    async def setup(request: Request, response: Response, payload: dict = Body(...)):
        check_fields(payload, {"username", "password", "name", "organization"})
        username = text_field(payload.get("username"), "用户名", maximum=40, required=True).lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
            raise HTTPException(422, "用户名使用 3–40 位字母、数字、点、下划线或短横线")
        name = text_field(payload.get("name"), "姓名", maximum=80, required=True)
        org = text_field(payload.get("organization"), "组织名称", maximum=120, required=True)
        with get_db(request) as connection:
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise HTTPException(409, "账本已初始化，请登录")
        digest, salt = password_hash(validate_password(payload.get("password")))
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise HTTPException(409, "账本已初始化，请登录")
            timestamp = utcnow()
            user_id = connection.execute("INSERT INTO users(username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (?,?,'admin',1,?,?,?,?)", (username, name, digest, salt, timestamp, timestamp)).lastrowid
            connection.execute("INSERT INTO settings VALUES ('organization',?)", (json.dumps({"name": org}, ensure_ascii=False),))
            user = public_user(connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
            ledger = create_ledger(connection, user, org)
            user = scoped_user(connection, user, ledger["id"])
            app.state.default_ledger_id = ledger["id"]
            token = new_session(connection, user_id)
            write_audit(connection, user, "setup", "organization", None, {"name": org})
        set_session_cookie(response, token, request)
        return success({"user": user}, "账本已创建")

    @app.post("/api/auth/login")
    async def login(request: Request, response: Response, payload: dict = Body(...)):
        check_fields(payload, {"username", "password"})
        username = text_field(payload.get("username"), "用户名或邮箱", maximum=254, required=True).lower()
        request.app.state.login_limiter.check(request, username)
        with get_db(request) as connection:
            row = connection.execute("SELECT * FROM users WHERE username=? OR (email=? COLLATE NOCASE AND email_verified_at IS NOT NULL)", (username, username)).fetchone()
            candidate = row or {"password_salt": "00" * 16, "password_hash": "00" * 32}
            valid = password_matches(payload.get("password"), candidate)
            if not row or not row["enabled"] or not valid:
                raise HTTPException(401, "用户名或密码错误")
            token = new_session(connection, row["id"])
            user = public_user(row)
            write_audit(connection, user, "login", "user", user["id"])
        set_session_cookie(response, token, request)
        return success({"user": user})

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        token = request_token(request)
        if token:
            with get_db(request) as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie("studio_session", path="/")
        return success(None, "已退出")

    @app.get("/api/auth/me")
    @app.get("/api/me")
    async def me(user=Depends(auth_user)):
        return success(user)

    @app.get("/api/users")
    async def users(request: Request, user=Depends(require_admin)):
        with get_db(request) as connection:
            return success(ledger_members_list(connection, user["ledgerId"]))

    @app.post("/api/users")
    async def create_user(request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        if user["globalRole"] != "admin":
            raise HTTPException(403, "请通过邀请注册添加成员")
        check_fields(payload, {"username", "name", "password", "role", "enabled"})
        username = text_field(payload.get("username"), "用户名", maximum=40, required=True).lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
            raise HTTPException(422, "用户名格式无效")
        name = text_field(payload.get("name"), "姓名", maximum=80, required=True)
        role = payload.get("role", "member")
        if role not in ("admin", "member"):
            raise HTTPException(422, "角色无效")
        enabled = boolean_field(payload.get("enabled", True), "启用状态")
        digest, salt = password_hash(validate_password(payload.get("password")))
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                raise HTTPException(409, "此用户名已被使用，请通过邀请加入现有账号")
            timestamp = utcnow()
            user_id = connection.execute("INSERT INTO users(username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (?,?,'member',1,?,?,?,?)", (username, name, digest, salt, timestamp, timestamp)).lastrowid
            connection.execute("INSERT INTO ledger_members VALUES (?,?,?,?,?)", (user["ledgerId"], user_id, role, int(enabled), timestamp))
            write_audit(connection, user, "create", "member", user_id, {"name": name, "role": role, "enabled": enabled})
            return success(next(item for item in ledger_members_list(connection, user["ledgerId"]) if item["id"] == user_id))

    @app.put("/api/users/{user_id}")
    async def update_user(user_id: int, request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        check_fields(payload, {"name", "role", "enabled", "password"})
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT u.* FROM users u JOIN ledger_members m ON m.user_id=u.id WHERE u.id=? AND m.ledger_id=?", (user_id, user["ledgerId"])).fetchone()
            if not row:
                raise HTTPException(404, "成员不在当前账本")
            name = text_field(payload.get("name", row["name"]), "姓名", maximum=80, required=True)
            reset_password = "password" in payload and payload["password"] not in (None, "")
            changing_global = name != row["name"] or reset_password
            if changing_global:
                raise HTTPException(403, "账号资料请在个人中心修改，密码可在个人中心或邮箱找回流程中重设")
            enabled = boolean_field(payload["enabled"], "启用状态") if "enabled" in payload else None
            change_member(connection, user["ledgerId"], user_id, role=payload.get("role"), enabled=enabled)
            digest, salt = row["password_hash"], row["password_salt"]
            if reset_password:
                digest, salt = password_hash(validate_password(payload["password"]))
                connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            connection.execute("UPDATE users SET name=?,password_hash=?,password_salt=?,updated_at=? WHERE id=?", (name, digest, salt, utcnow(), user_id))
            write_audit(connection, user, "update", "member", user_id, {"role": payload.get("role"), "enabled": enabled, "passwordReset": reset_password})
            return success(next(item for item in ledger_members_list(connection, user["ledgerId"]) if item["id"] == user_id))

    @app.get("/api/account/getAccount")
    @app.get("/api/account/getAccountNoLimit")
    async def accounts(request: Request, user=Depends(current_user)):
        with get_db(request) as connection:
            return success(account_records(connection, user))

    @app.get("/api/account/getAccount/{account_id}")
    async def one_account(account_id: int, request: Request, user=Depends(current_user)):
        with get_db(request) as connection:
            account = next((item for item in account_records(connection, user) if item["id"] == account_id), None)
            if account is None:
                raise HTTPException(404, "账户不存在")
            return success(account)

    @app.post("/api/account/addAccount")
    async def create_account(request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        check_fields(payload, {"name", "initialMoney", "money", "accountType", "card", "enable"})
        name = text_field(payload.get("name"), "账户名称", maximum=80, required=True)
        cents = money_cents(payload.get("initialMoney", payload.get("money", "0")))
        kind = integer_field(payload.get("accountType", 0), "账户类型", allowed={0, 1})
        card = text_field(payload.get("card", ""), "账户备注", maximum=100)
        enabled = boolean_field(payload.get("enable", True), "启用状态")
        with get_db(request) as connection:
            timestamp = utcnow()
            account_id = connection.execute("INSERT INTO accounts(name,initial_cents,account_type,card,enabled,created_at,updated_at,ledger_id) VALUES (?,?,?,?,?,?,?,?)", (name, cents, kind, card, int(enabled), timestamp, timestamp, user["ledgerId"])).lastrowid
            write_audit(connection, user, "create", "account", account_id, {"name": name, "initialMoney": money_text(cents), "accountType": kind})
            return success(next(item for item in account_records(connection, user) if item["id"] == account_id))

    @app.put("/api/account/updateAccount/{account_id}")
    async def update_account(account_id: int, request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        check_fields(payload, {"name", "initialMoney", "money", "accountType", "card", "enable"})
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id=? AND ledger_id=?", (account_id, user["ledgerId"])).fetchone()
            if not row:
                raise HTTPException(404, "账户不存在")
            name = text_field(payload.get("name", row["name"]), "账户名称", maximum=80, required=True)
            cents = money_cents(payload.get("initialMoney", payload.get("money", money_text(row["initial_cents"]))))
            kind = integer_field(payload.get("accountType", row["account_type"]), "账户类型", allowed={0, 1})
            if kind != row["account_type"] and connection.execute("SELECT 1 FROM flows WHERE ledger_id=? AND (account_id=? OR account_to_id=?) LIMIT 1", (user["ledgerId"], account_id, account_id)).fetchone():
                raise HTTPException(409, "已有流水的账户不能更改资产/负债类型")
            card = text_field(payload.get("card", row["card"]), "账户备注", maximum=100)
            enabled = boolean_field(payload.get("enable", bool(row["enabled"])), "启用状态")
            connection.execute("UPDATE accounts SET name=?,initial_cents=?,account_type=?,card=?,enabled=?,updated_at=? WHERE id=? AND ledger_id=?", (name, cents, kind, card, int(enabled), utcnow(), account_id, user["ledgerId"]))
            write_audit(connection, user, "update", "account", account_id, {"before": {"name": row["name"], "initialMoney": money_text(row["initial_cents"]), "enable": bool(row["enabled"])}, "after": {"name": name, "initialMoney": money_text(cents), "enable": enabled}})
            return success(next(item for item in account_records(connection, user) if item["id"] == account_id))

    @app.delete("/api/account/deleteAccount/{account_id}")
    async def archive_account(account_id: int, request: Request, user=Depends(require_admin)):
        with get_db(request) as connection:
            result = connection.execute("UPDATE accounts SET enabled=0,updated_at=? WHERE id=? AND ledger_id=?", (utcnow(), account_id, user["ledgerId"]))
            if not result.rowcount:
                raise HTTPException(404, "账户不存在")
            write_audit(connection, user, "archive", "account", account_id)
        return success()

    @app.get("/api/action/getAction")
    @app.get("/api/action/getAllAction")
    async def actions(user=Depends(current_user)):
        return success(ACTIONS)

    @app.get("/api/type/getType")
    async def categories(request: Request, user=Depends(current_user)):
        with get_db(request) as connection:
            return success(category_tree(connection, user))

    @app.get("/api/type/getType/noLimit")
    async def all_categories(request: Request, user=Depends(current_user)):
        with get_db(request) as connection:
            return success(category_tree(connection, user, include_disabled=True))

    @app.get("/api/type/getTypeByActionId/{action_id}")
    async def action_categories(action_id: int, request: Request, user=Depends(current_user)):
        integer_field(action_id, "收支类型", allowed={0, 1, 2})
        with get_db(request) as connection:
            return success(category_tree(connection, user, action_id=action_id))

    def category_values(connection, payload, user, existing=None):
        check_fields(payload, {"tname", "name", "parent", "actionIds", "enable"})
        name = text_field(payload.get("tname", payload.get("name", existing["name"] if existing else None)), "分类名称", maximum=80, required=True)
        parent = payload.get("parent", existing["parent"] if existing else None)
        if parent in (0, -1):
            parent = None
        action_ids = payload.get("actionIds", json.loads(existing["action_ids"]) if existing else [0, 1, 2])
        if not isinstance(action_ids, list) or not action_ids or any(type(item) is not int or item not in {0, 1, 2} for item in action_ids):
            raise HTTPException(422, "请选择适用的收支类型")
        action_ids = sorted(set(action_ids))
        enabled = boolean_field(payload.get("enable", bool(existing["enabled"]) if existing else True), "启用状态")
        if parent is not None:
            integer_field(parent, "父分类", minimum=1)
            root = connection.execute("SELECT * FROM categories WHERE id=? AND ledger_id=?", (parent, user["ledgerId"])).fetchone()
            if not root or root["parent"] is not None or not root["enabled"] or existing and existing["id"] == parent:
                raise HTTPException(422, "父分类不存在、已归档或层级无效")
            if existing and connection.execute("SELECT 1 FROM categories WHERE parent=? AND ledger_id=?", (existing["id"], user["ledgerId"])).fetchone():
                raise HTTPException(422, "包含子分类的分类不能变成子分类")
            if not set(action_ids).issubset(json.loads(root["action_ids"])):
                raise HTTPException(422, "子分类适用类型必须包含在父分类中")
        if existing:
            for child in connection.execute("SELECT action_ids FROM categories WHERE parent=? AND ledger_id=?", (existing["id"], user["ledgerId"])):
                if not set(json.loads(child["action_ids"])).issubset(action_ids):
                    raise HTTPException(422, "请先调整子分类的适用类型")
        return name, parent, json.dumps(action_ids), int(enabled)

    @app.post("/api/type/addType")
    async def create_category(request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            values = category_values(connection, payload, user)
            timestamp = utcnow()
            category_id = connection.execute("INSERT INTO categories(name,parent,action_ids,enabled,created_at,updated_at,ledger_id) VALUES (?,?,?,?,?,?,?)", (*values, timestamp, timestamp, user["ledgerId"])).lastrowid
            write_audit(connection, user, "create", "category", category_id, {"name": values[0]})
            return success(category_record(connection.execute("SELECT * FROM categories WHERE id=? AND ledger_id=?", (category_id, user["ledgerId"])).fetchone()))

    @app.put("/api/type/updateType/{category_id}")
    async def update_category(category_id: int, request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM categories WHERE id=? AND ledger_id=?", (category_id, user["ledgerId"])).fetchone()
            if not row:
                raise HTTPException(404, "分类不存在")
            values = category_values(connection, payload, user, row)
            connection.execute("UPDATE categories SET name=?,parent=?,action_ids=?,enabled=?,updated_at=? WHERE id=? AND ledger_id=?", (*values, utcnow(), category_id, user["ledgerId"]))
            if not values[3]:
                connection.execute("UPDATE categories SET enabled=0,updated_at=? WHERE parent=? AND ledger_id=?", (utcnow(), category_id, user["ledgerId"]))
            write_audit(connection, user, "update", "category", category_id, {"before": category_record(row), "after": payload})
            return success(category_record(connection.execute("SELECT * FROM categories WHERE id=? AND ledger_id=?", (category_id, user["ledgerId"])).fetchone()))

    @app.delete("/api/type/deleteType/{category_id}")
    async def archive_category(category_id: int, request: Request, user=Depends(require_admin)):
        with get_db(request) as connection:
            if not connection.execute("SELECT 1 FROM categories WHERE id=? AND ledger_id=?", (category_id, user["ledgerId"])).fetchone():
                raise HTTPException(404, "分类不存在")
            connection.execute("UPDATE categories SET enabled=0,updated_at=? WHERE ledger_id=? AND (id=? OR parent=?)", (utcnow(), user["ledgerId"], category_id, category_id))
            write_audit(connection, user, "archive", "category", category_id)
        return success()

    @app.get("/api/flow/getFlowListMain/{handle}/{collect}/{month}")
    async def month_flows(handle: int, collect: int, month: str, request: Request, user=Depends(current_user)):
        integer_field(handle, "收支筛选", allowed={0, 1, 2, 3})
        integer_field(collect, "收藏筛选", allowed={0, 1})
        month_field(month)
        scope, params = user_scope(user)
        query = "SELECT * FROM flows WHERE deleted_at IS NULL AND substr(fdate,1,7)=?" + scope
        params = [month] + params
        if handle != 3:
            query += " AND action_id=?"
            params.append(handle)
        if collect:
            query += " AND collect=1"
        with get_db(request) as connection:
            rows = connection.execute(query + " ORDER BY fdate DESC,id DESC", params).fetchall()
            return success({"flows": flow_records(connection, rows, user), **ledger_totals(rows)})

    @app.post("/api/screen/getFlowByScreen")
    async def search_flows(request: Request, payload: dict = Body(...), user=Depends(current_user)):
        check_fields(payload, {"startDate", "endDate", "singleMonth", "accountId", "chooseHandle", "collect", "actions", "types", "note", "status", "ownerId"})
        scope, params = user_scope(user)
        query = "SELECT * FROM flows WHERE deleted_at IS NULL" + scope
        if "singleMonth" in payload:
            boolean_field(payload["singleMonth"], "月份筛选")
        if "collect" in payload:
            boolean_field(payload["collect"], "收藏筛选")
        if payload.get("startDate"):
            start = payload["startDate"]
            if not isinstance(start, str):
                raise HTTPException(422, "开始日期无效")
            if payload.get("singleMonth"):
                if len(start) != 7:
                    date_field(start)
                month_field(start[:7])
                query += " AND substr(fdate,1,7)=?"
                params.append(start[:7])
            else:
                query += " AND fdate>=?"
                params.append(date_field(start))
        if payload.get("endDate") and not payload.get("singleMonth"):
            query += " AND fdate<=?"
            end = date_field(payload["endDate"])
            if payload.get("startDate") and end < payload["startDate"]:
                raise HTTPException(422, "结束日期不能早于开始日期")
            params.append(end)
        if payload.get("accountId") not in (None, 0, -1):
            account_id = integer_field(payload["accountId"], "账户", minimum=1)
            query += " AND (account_id=? OR account_to_id=?)"
            params += [account_id, account_id]
        handle = payload.get("chooseHandle", 3)
        integer_field(handle, "收支筛选", allowed={0, 1, 2, 3})
        if handle != 3:
            query += " AND action_id=?"
            params.append(handle)
        if payload.get("collect"):
            query += " AND collect=1"
        for field, column, allowed in (("actions", "action_id", {0, 1, 2}), ("types", "type_id", None)):
            if payload.get(field):
                values = payload[field]
                if not isinstance(values, list) or len(values) > 100:
                    raise HTTPException(422, "筛选列表无效")
                for value in values:
                    integer_field(value, "筛选ID", allowed=allowed, minimum=0 if allowed else 1)
                query += " AND " + column + " IN (" + ",".join("?" for _ in values) + ")"
                params.extend(values)
        if payload.get("note"):
            query += " AND note LIKE ? ESCAPE '\\'"
            text = text_field(payload["note"], "搜索内容", maximum=200)
            params.append("%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if payload.get("status"):
            if payload["status"] not in ("pending", "approved", "rejected"):
                raise HTTPException(422, "审核状态无效")
            query += " AND status=?"
            params.append(payload["status"])
        if payload.get("ownerId") is not None:
            if user["role"] != "admin":
                raise HTTPException(403, "成员不能查询其他成员的数据")
            query += " AND owner_id=?"
            params.append(integer_field(payload["ownerId"], "成员", minimum=1))
        with get_db(request) as connection:
            rows = connection.execute(query + " ORDER BY fdate DESC,id DESC", params).fetchall()
            return success({"flows": flow_records(connection, rows, user), **ledger_totals(rows), "typeList": []})

    @app.get("/api/flow/getFlow/{flow_id}")
    async def one_flow(flow_id: int, request: Request, user=Depends(current_user)):
        with get_db(request) as connection:
            return success(flow_record(connection, visible_flow(connection, flow_id, user), user))

    @app.post("/api/flow/addFlow")
    async def create_flow(request: Request, payload: dict = Body(...), user=Depends(current_user)):
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            values = flow_values(connection, payload, user)
            timestamp = utcnow()
            flow_id = connection.execute("INSERT INTO flows(cents,fdate,action_id,account_id,account_to_id,type_id,collect,note,images,status,owner_id,created_at,updated_at,ledger_id) VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)", (*values, user["id"], timestamp, timestamp, user["ledgerId"])).lastrowid
            write_audit(connection, user, "create", "flow", flow_id, {"money": money_text(values[0]), "status": "pending"})
            return success(flow_record(connection, visible_flow(connection, flow_id, user), user))

    @app.put("/api/flow/updateFlow/{flow_id}")
    async def update_flow(flow_id: int, request: Request, payload: dict = Body(...), user=Depends(current_user)):
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = visible_flow(connection, flow_id, user, writable=True)
            check_version(payload, row)
            values = flow_values(connection, payload, user, row)
            status = row["status"] if user["role"] == "admin" and row["status"] == "approved" else "pending"
            comment = row["review_comment"] if status == "approved" else ""
            reviewer = row["reviewed_by"] if status == "approved" else None
            reviewed_at = row["reviewed_at"] if status == "approved" else None
            before = flow_record(connection, row, user)
            connection.execute("UPDATE flows SET cents=?,fdate=?,action_id=?,account_id=?,account_to_id=?,type_id=?,collect=?,note=?,images=?,status=?,review_comment=?,reviewed_by=?,reviewed_at=?,updated_at=?,version=version+1 WHERE id=? AND ledger_id=?", (*values, status, comment, reviewer, reviewed_at, utcnow(), flow_id, user["ledgerId"]))
            after = flow_record(connection, visible_flow(connection, flow_id, user), user)
            write_audit(connection, user, "edit_approved" if row["status"] == "approved" else "update", "flow", flow_id, {"before": before, "after": after})
            return success(after)

    @app.delete("/api/flow/deleteFlow/{flow_id}")
    async def delete_flow(flow_id: int, request: Request, version: int | None = None, user=Depends(current_user)):
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = visible_flow(connection, flow_id, user, writable=True)
            check_version({"version": version} if version is not None else {}, row)
            connection.execute("UPDATE flows SET deleted_at=?,updated_at=?,version=version+1 WHERE id=? AND ledger_id=?", (utcnow(), utcnow(), flow_id, user["ledgerId"]))
            write_audit(connection, user, "delete", "flow", flow_id, {"previousStatus": row["status"], "money": money_text(row["cents"]), "ownerId": row["owner_id"]})
        return success()

    @app.put("/api/flow/collectFlow/{flow_id}/{collect}")
    async def collect_flow(flow_id: int, collect: int, request: Request, user=Depends(current_user)):
        integer_field(collect, "收藏状态", allowed={0, 1})
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = visible_flow(connection, flow_id, user, writable=True)
            connection.execute("UPDATE flows SET collect=?,updated_at=?,version=version+1 WHERE id=? AND ledger_id=?", (collect, utcnow(), flow_id, user["ledgerId"]))
            write_audit(connection, user, "collect", "flow", flow_id, {"collect": bool(collect)})
            return success(flow_record(connection, visible_flow(connection, flow_id, user), user))

    @app.post("/api/flow/reviewFlow/{flow_id}")
    async def review_flow(flow_id: int, request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        check_fields(payload, {"status", "comment", "version"})
        status = payload.get("status")
        if status not in ("approved", "rejected"):
            raise HTTPException(422, "请选择通过或驳回")
        comment = text_field(payload.get("comment", ""), "审核说明", maximum=1000)
        if status == "rejected" and not comment:
            raise HTTPException(422, "驳回时请填写原因")
        with get_db(request) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = visible_flow(connection, flow_id, user)
            check_version(payload, row)
            connection.execute("UPDATE flows SET status=?,review_comment=?,reviewed_by=?,reviewed_at=?,updated_at=?,version=version+1 WHERE id=? AND ledger_id=?", (status, comment, user["id"], utcnow(), utcnow(), flow_id, user["ledgerId"]))
            write_audit(connection, user, "review", "flow", flow_id, {"from": row["status"], "to": status, "comment": comment})
            return success(flow_record(connection, visible_flow(connection, flow_id, user), user))

    @app.get("/api/dashboard")
    async def dashboard(request: Request, month: str | None = None, user=Depends(current_user)):
        selected = month_field(month or date.today().strftime("%Y-%m"))
        year, month_number = map(int, selected.split("-"))
        scope, params = user_scope(user)
        with get_db(request) as connection:
            all_rows = connection.execute("SELECT * FROM flows WHERE deleted_at IS NULL" + scope + " ORDER BY fdate DESC,id DESC", params).fetchall()
            rows = [row for row in all_rows if row["fdate"].startswith(selected)]
            totals = ledger_totals(rows)
            accounts = account_records(connection, user)
            assets = None if user["role"] != "admin" else money_text(sum(int(Decimal(item["money"]) * 100) * (-1 if item["accountType"] else 1) for item in accounts))
            trend = []
            for day in range(1, calendar.monthrange(year, month_number)[1] + 1):
                fdate = f"{selected}-{day:02d}"
                total = ledger_totals([row for row in rows if row["fdate"] == fdate])
                trend.append({"date": fdate, "income": total["totalIn"], "expense": total["totalOut"]})
            names = {row["id"]: row["name"] for row in connection.execute("SELECT id,name FROM categories WHERE ledger_id=?", (user["ledgerId"],))}
            expenses = {}
            for row in rows:
                if row["status"] == "approved" and row["action_id"] == 1:
                    expenses[row["type_id"]] = expenses.get(row["type_id"], 0) + row["cents"]
            categories = [{"id": key, "name": names.get(key, "其他"), "amount": money_text(value)} for key, value in sorted(expenses.items(), key=lambda item: item[1], reverse=True)]
            monthly = []
            for offset in range(11, -1, -1):
                absolute = year * 12 + month_number - 1 - offset
                key = f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
                total = ledger_totals([row for row in all_rows if row["fdate"].startswith(key)])
                monthly.append({"month": key, "income": total["totalIn"], "expense": total["totalOut"]})
            return success({"month": selected, "income": totals["totalIn"], "expense": totals["totalOut"], "net": totals["totalEarn"], "assets": assets,
                            "pendingCount": sum(row["status"] == "pending" for row in rows), "allPendingCount": sum(row["status"] == "pending" for row in all_rows), "trend": trend, "categories": categories,
                            "recent": flow_records(connection, rows[:8], user), "accounts": accounts, "monthly": monthly})

    @app.get("/api/settings")
    async def get_settings(request: Request, user=Depends(current_user)):
        with get_db(request) as connection:
            book = ledger_record(connection, user["ledgerId"], user["id"])
            return success({"organization": book["name"], "name": book["name"], "currency": "CNY"})

    @app.put("/api/settings")
    async def update_settings(request: Request, payload: dict = Body(...), user=Depends(require_admin)):
        check_fields(payload, {"organization", "name"})
        name = text_field(payload.get("organization", payload.get("name")), "组织名称", maximum=120, required=True)
        with get_db(request) as connection:
            before = ledger_record(connection, user["ledgerId"], user["id"])
            connection.execute("UPDATE ledgers SET name=?,updated_at=? WHERE id=?", (name, utcnow(), user["ledgerId"]))
            write_audit(connection, user, "update", "ledger", user["ledgerId"], {"before": before, "after": {"name": name}})
        return success({"organization": name, "name": name, "currency": "CNY"})

    @app.get("/api/audit")
    async def audit(request: Request, limit: int = Query(default=100, ge=1, le=500), user=Depends(require_admin)):
        with get_db(request) as connection:
            return success([{"id": row["id"], "actorId": row["actor_id"], "actorName": row["actor_name"], "action": row["action"], "entityType": row["entity_type"], "entityId": row["entity_id"], "detail": json.loads(row["detail"]), "createdAt": row["created_at"]} for row in connection.execute("SELECT * FROM audit WHERE ledger_id=? ORDER BY id DESC LIMIT ?", (user["ledgerId"], limit))])

    # Invoice module shares this app's database and authentication. During the
    # initial scaffold it may not yet exist; missing dependencies must still fail.
    try:
        invoice_module = importlib.import_module(".invoices", package=__package__)
    except ModuleNotFoundError as exc:
        if exc.name != __package__ + ".invoices":
            raise
    else:
        invoice_module.init_invoices(app)
        app.include_router(invoice_module.router)

    @app.get("/{path:path}")
    async def static_app(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        root = app.state.web_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(404, "文件不存在")
        if target.is_file():
            return FileResponse(target)
        if Path(path).suffix and path not in ("", "index.html"):
            raise HTTPException(404, "文件不存在")
        index = root / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"code": 503, "msg": "前端尚未构建", "data": None}, status_code=503)

    return app


app = create_app()
