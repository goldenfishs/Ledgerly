"""System-wide policy and mail delivery; never derives privilege from a ledger role."""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from collections import OrderedDict
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from .core import auth_user, boolean_field, check_fields, get_db, integer_field, success, text_field, utcnow, write_audit

router = APIRouter(prefix="/api")
POLICY_DEFAULTS = {"siteName": "账序", "registrationMode": "invite", "emailVerificationRequired": False}
MAIL_DEFAULTS = {"enabled": False, "host": "", "port": 587, "security": "starttls", "username": "", "fromEmail": "", "fromName": "账序", "passwordEncrypted": ""}
APP_VERSION = os.getenv("LEDGERLY_VERSION", "0.1.0")
REPOSITORY_URL = "https://github.com/goldenfishs/Ledgerly"
CONTAINER_IMAGE = os.getenv("LEDGERLY_IMAGE", "ghcr.io/goldenfishs/ledgerly")
UPDATE_COMMAND = os.getenv(
    "LEDGERLY_UPDATE_COMMAND",
    "docker compose pull ledgerly && docker compose up -d --no-deps ledgerly",
)


class AttemptLimiter:
    """Verification throttling independent of caller transaction rollbacks."""
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def check(self, key, limit=10, seconds=600):
        now = time.monotonic()
        with self.lock:
            values = [value for value in self.entries.get(key, []) if now - value < seconds]
            if len(values) >= limit:
                raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(seconds)})
            self.entries[key] = values + [now]
            self.entries.move_to_end(key)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)


def init_system_db(app):
    with get_db(app) as db:
        db.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    path = Path(app.state.data_dir) / "system.key"
    if not path.exists():
        temporary = path.with_name(".system-key-" + secrets.token_hex(8))
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(Fernet.generate_key())
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    os.chmod(path, 0o600)
    key = path.read_bytes()
    app.state.mail_cipher = Fernet(key)
    app.state.email_hmac_key = hashlib.sha256(key + b"studio-email-challenge").digest()
    app.state.email_verify_limiter = AttemptLimiter()


def read_setting(db, key, defaults):
    row = db.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    return {**defaults, **(json.loads(row["value"]) if row else {})}


def save_setting(db, key, value):
    db.execute("INSERT INTO system_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))


def system_config(db):
    return read_setting(db, "policy", POLICY_DEFAULTS)


def mail_config(db):
    return read_setting(db, "mail", MAIL_DEFAULTS)


def mail_available(db):
    config = mail_config(db)
    return bool(config["enabled"] and config["host"] and config["fromEmail"])


def _version_tuple(value):
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?", str(value or "").strip())
    return tuple(int(part or 0) for part in match.groups()) if match else None


def version_info(app):
    """Return cached public release metadata without granting Docker access."""
    now = time.monotonic()
    cached = getattr(app.state, "version_info", None)
    if cached and now - cached["checkedMonotonic"] < 300:
        return {key: value for key, value in cached.items() if key != "checkedMonotonic"}
    result = {
        "currentVersion": APP_VERSION,
        "latestVersion": None,
        "updateAvailable": False,
        "releaseUrl": REPOSITORY_URL + "/releases",
        "releaseNotes": "",
        "image": CONTAINER_IMAGE,
        "updateCommand": UPDATE_COMMAND,
        "status": "checking",
    }
    try:
        response = httpx.get(
            REPOSITORY_URL.replace("github.com", "api.github.com/repos") + "/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Ledgerly-Version-Checker"},
            timeout=4,
        )
        if response.status_code == 200:
            payload = response.json()
            tag = str(payload.get("tag_name") or "").strip()
            latest = _version_tuple(tag)
            current = _version_tuple(APP_VERSION)
            if latest:
                result.update({
                    "latestVersion": tag.lstrip("v"),
                    "updateAvailable": bool(current and latest > current),
                    "releaseUrl": payload.get("html_url") or result["releaseUrl"],
                    "releaseNotes": str(payload.get("body") or "")[:4000],
                    "status": "available" if current and latest > current else "latest",
                })
            else:
                result["status"] = "unavailable"
        elif response.status_code == 404:
            result["status"] = "unavailable"
        else:
            result["status"] = "error"
    except (httpx.HTTPError, ValueError, TypeError):
        result["status"] = "error"
    result["checkedMonotonic"] = now
    app.state.version_info = result
    return {key: value for key, value in result.items() if key != "checkedMonotonic"}


def public_mail(config):
    return {**{key: value for key, value in config.items() if key != "passwordEncrypted"}, "passwordConfigured": bool(config["passwordEncrypted"])}


async def require_system_admin(user=Depends(auth_user)):
    if user["globalRole"] != "admin":
        raise HTTPException(403, "此操作需要系统管理员权限")
    return user


def header_text(value, label, maximum=200):
    result = text_field(value, label, maximum=maximum)
    if any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise HTTPException(422, label + "包含无效字符")
    return result


def normalize_email(value):
    if not isinstance(value, str) or len(value) > 254:
        raise HTTPException(422, "邮箱地址格式无效")
    email = value.strip().lower()
    # Only mailbox addresses are accepted, never display names or SMTP headers.
    if not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}@[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", email):
        raise HTTPException(422, "邮箱地址格式无效")
    local, domain = email.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or ".." in local or "." not in domain or any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in domain.split(".")):
        raise HTTPException(422, "邮箱地址格式无效")
    return email


def mail_values(payload, previous, app):
    check_fields(payload, set(MAIL_DEFAULTS) - {"passwordEncrypted"} | {"password", "clearPassword"})
    result = {**previous}
    if "enabled" in payload:
        result["enabled"] = boolean_field(payload["enabled"], "邮件服务开关")
    if "host" in payload:
        host = header_text(payload["host"], "SMTP 服务器", 253)
        if host:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host) or any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in host.split(".")):
                    raise HTTPException(422, "SMTP 服务器只填写域名或 IP 地址")
        result["host"] = host
    if "port" in payload:
        result["port"] = integer_field(payload["port"], "SMTP 端口", minimum=1)
        if result["port"] > 65535:
            raise HTTPException(422, "SMTP 端口无效")
    if "security" in payload:
        if payload["security"] not in ("starttls", "ssl", "none"):
            raise HTTPException(422, "SMTP 加密方式无效")
        result["security"] = payload["security"]
    for key, label in (("username", "SMTP 用户名"), ("fromName", "发件人名称")):
        if key in payload:
            result[key] = header_text(payload[key], label, 254 if key == "username" else 80)
    if "fromEmail" in payload:
        if not isinstance(payload["fromEmail"], str):
            raise HTTPException(422, "发件邮箱格式无效")
        result["fromEmail"] = normalize_email(payload["fromEmail"]) if payload["fromEmail"] else ""
    clear = boolean_field(payload.get("clearPassword", False), "清除密码")
    password = payload.get("password", "")
    if not isinstance(password, str) or len(password) > 1024 or "\x00" in password:
        raise HTTPException(422, "SMTP 密码格式无效")
    try:
        encoded = password.encode("utf-8")
    except UnicodeError:
        raise HTTPException(422, "SMTP 密码格式无效")
    if clear and password:
        raise HTTPException(422, "清除密码与填写新密码不能同时选择")
    if clear:
        result["passwordEncrypted"] = ""
    elif password:
        result["passwordEncrypted"] = app.state.mail_cipher.encrypt(encoded).decode("ascii")
    if result["enabled"] and not (result["host"] and result["fromEmail"]):
        raise HTTPException(422, "启用邮件服务前请填写服务器和发件邮箱")
    return result


def deliver_email(app, config, to, subject, body):
    """One delivery through saved settings. Errors deliberately omit server replies."""
    if not config["enabled"] or not config["host"] or not config["fromEmail"]:
        raise HTTPException(503, "管理员尚未启用邮箱服务")
    message = EmailMessage()
    message["From"] = formataddr((config["fromName"], config["fromEmail"]))
    message["To"] = normalize_email(to)
    message["Subject"] = subject
    message.set_content(body)
    try:
        password = app.state.mail_cipher.decrypt(config["passwordEncrypted"].encode("ascii")).decode("utf-8") if config["passwordEncrypted"] else ""
        context = ssl.create_default_context()
        client_type = smtplib.SMTP_SSL if config["security"] == "ssl" else smtplib.SMTP
        options = {"timeout": 10}
        if config["security"] == "ssl":
            options["context"] = context
        with client_type(config["host"], config["port"], **options) as client:
            client.ehlo()
            if config["security"] == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if config["username"]:
                client.login(config["username"], password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException, InvalidToken, UnicodeError, ValueError):
        raise HTTPException(502, "邮件发送失败，请管理员检查 SMTP 配置和服务状态") from None


@router.get("/auth/options")
def auth_options(request: Request):
    with get_db(request) as db:
        return success({**system_config(db), "emailEnabled": mail_available(db)})


@router.get("/system/version")
def get_version(request: Request, user=Depends(auth_user)):
    return success(version_info(request.app))


@router.get("/system/settings")
def get_system_settings(request: Request, user=Depends(require_system_admin)):
    with get_db(request) as db:
        return success(system_config(db))


@router.put("/system/settings")
def update_system_settings(request: Request, payload: dict = Body(...), user=Depends(require_system_admin)):
    check_fields(payload, set(POLICY_DEFAULTS))
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        result = system_config(db)
        if "siteName" in payload:
            result["siteName"] = header_text(payload["siteName"], "系统名称", 60)
            if not result["siteName"]:
                raise HTTPException(422, "系统名称不能为空")
        if "registrationMode" in payload:
            if payload["registrationMode"] not in ("invite", "open", "closed"):
                raise HTTPException(422, "注册方式无效")
            result["registrationMode"] = payload["registrationMode"]
        if "emailVerificationRequired" in payload:
            result["emailVerificationRequired"] = boolean_field(payload["emailVerificationRequired"], "注册邮箱验证")
        if result["emailVerificationRequired"] and not mail_available(db):
            raise HTTPException(409, "请先启用邮箱服务，再要求注册时验证邮箱")
        save_setting(db, "policy", result)
        write_audit(db, user, "update", "system-settings", None, result)
    return success(result, "系统设置已保存")


@router.get("/system/email")
def get_mail_settings(request: Request, user=Depends(require_system_admin)):
    with get_db(request) as db:
        return success(public_mail(mail_config(db)))


@router.put("/system/email")
def update_mail_settings(request: Request, payload: dict = Body(...), user=Depends(require_system_admin)):
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        result = mail_values(payload, mail_config(db), request.app)
        if not result["enabled"] and system_config(db)["emailVerificationRequired"]:
            raise HTTPException(409, "请先关闭注册邮箱验证要求，再停用邮箱服务")
        save_setting(db, "mail", result)
        write_audit(db, user, "update", "system-email", None, {"enabled": result["enabled"], "passwordChanged": bool(payload.get("password") or payload.get("clearPassword"))})
    return success(public_mail(result), "邮件配置已保存")


@router.post("/system/email/test")
def test_mail(request: Request, payload: dict = Body(...), user=Depends(require_system_admin)):
    check_fields(payload, {"to"})
    to = normalize_email(payload.get("to"))
    request.app.state.email_verify_limiter.check(("mail-test", user["id"]), limit=5, seconds=600)
    with get_db(request) as db:
        config = mail_config(db)
        site_name = system_config(db)["siteName"]
    deliver_email(request.app, config, to, site_name + " · 邮件配置测试", "这是一封邮件配置测试邮件。收到此邮件说明当前 SMTP 配置可以发送邮件。")
    return success(None, "测试邮件已发送")
