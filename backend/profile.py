"""Personal account settings, independent of ledger membership."""
import io
import re
import secrets
import sqlite3
import warnings
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .core import (auth_user, check_fields, get_db, new_session, password_hash,
                   password_matches, public_user, set_session_cookie, success,
                   text_field, utcnow, validate_password)

router = APIRouter(prefix="/api/profile")
MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000


def own_row(db, user):
    row = db.execute("SELECT * FROM users WHERE id=? AND enabled=1", (user["id"],)).fetchone()
    if row is None:
        raise HTTPException(401, "请重新登录")
    return row


def verify_current_password(request, payload, row):
    request.app.state.login_limiter.check(request, "profile:" + str(row["id"]))
    if not password_matches(payload.get("currentPassword"), row):
        raise HTTPException(400, "当前密码不正确")


def profile_record(db, row):
    from .system import mail_available
    return {**public_user(row), "email": row["email"],
            "emailVerified": bool(row["email"] and row["email_verified_at"]),
            "createdAt": row["created_at"], "emailVerificationAvailable": mail_available(db)}


@router.get("")
def get_profile(request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        return success(profile_record(db, own_row(db, user)))


@router.put("")
def update_profile(request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    check_fields(payload, {"username", "name", "currentPassword"})
    username = text_field(payload.get("username"), "账号", maximum=40, required=True).lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
        raise HTTPException(422, "账号使用 3–40 位字母、数字、点、下划线或短横线")
    name = text_field(payload.get("name"), "显示名称", maximum=80, required=True)
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        row = own_row(db, user)
        if username != row["username"]:
            verify_current_password(request, payload, row)
        try:
            db.execute("UPDATE users SET username=?,name=?,updated_at=? WHERE id=?", (username, name, utcnow(), user["id"]))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "这个账号已被使用，请换一个")
        return success(profile_record(db, own_row(db, user)))


@router.post("/password")
def change_password(request: Request, response: Response, payload: dict = Body(...), user=Depends(auth_user)):
    check_fields(payload, {"currentPassword", "newPassword"})
    password = validate_password(payload.get("newPassword"))
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        row = own_row(db, user)
        verify_current_password(request, payload, row)
        if password == payload.get("currentPassword"):
            raise HTTPException(422, "新密码应与当前密码不同")
        digest, salt = password_hash(password)
        db.execute("UPDATE users SET password_hash=?,password_salt=?,updated_at=? WHERE id=?", (digest, salt, utcnow(), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.execute("UPDATE email_challenges SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL", (utcnow(), user["id"]))
        token = new_session(db, user["id"])
    set_session_cookie(response, token, request)
    return success({"changed": True})


def avatar_directory(request):
    directory = Path(request.app.state.data_dir) / "avatars"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def remove_avatar_file(directory, filename):
    if filename and re.fullmatch(r"[a-f0-9]{48}\.webp", filename):
        try:
            (directory / filename).unlink(missing_ok=True)
        except OSError:
            # A cleanup failure must not undo a successfully saved profile.
            pass


def normalized_avatar(raw):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(422, "头像仅支持 JPG、PNG 或 WebP 图片")
                if source.width * source.height > MAX_AVATAR_PIXELS:
                    raise HTTPException(422, "图片尺寸过大，请选择不超过 1600 万像素的图片")
                if getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(422, "请选择静态图片作为头像")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                resized = ImageOps.fit(oriented.convert("RGBA"), (512, 512), method=Image.Resampling.LANCZOS)
                flattened = Image.new("RGB", (512, 512), "white")
                flattened.paste(resized, mask=resized.getchannel("A"))
                output = io.BytesIO()
                flattened.save(output, format="WEBP", quality=88, method=4)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "图片无法读取或尺寸过大，请换一张图片")


@router.post("/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...), user=Depends(auth_user)):
    try:
        raw = await file.read(MAX_AVATAR_BYTES + 1)
    finally:
        await file.close()
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "头像文件不能超过 2 MB")
    if not raw:
        raise HTTPException(422, "请选择头像图片")
    encoded = await run_in_threadpool(normalized_avatar, raw)
    directory = avatar_directory(request)
    filename = secrets.token_hex(24) + ".webp"
    path = directory / filename
    try:
        with path.open("xb") as output:
            output.write(encoded)
        with get_db(request) as db:
            db.execute("BEGIN IMMEDIATE")
            old = own_row(db, user)["avatar_filename"]
            db.execute("UPDATE users SET avatar_filename=?,updated_at=? WHERE id=?", (filename, utcnow(), user["id"]))
            result = public_user(own_row(db, user))["avatarUrl"]
    except BaseException:
        remove_avatar_file(directory, filename)
        raise
    remove_avatar_file(directory, old)
    return success({"avatarUrl": result})


@router.get("/avatar")
def get_avatar(request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        filename = own_row(db, user)["avatar_filename"]
    if not filename or not re.fullmatch(r"[a-f0-9]{48}\.webp", filename):
        raise HTTPException(404, "尚未设置头像")
    path = avatar_directory(request) / filename
    if not path.is_file():
        raise HTTPException(404, "头像图片不存在，请重新上传")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/avatar")
def delete_avatar(request: Request, user=Depends(auth_user)):
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        old = own_row(db, user)["avatar_filename"]
        db.execute("UPDATE users SET avatar_filename=NULL,updated_at=? WHERE id=?", (utcnow(), user["id"]))
    remove_avatar_file(avatar_directory(request), old)
    return success({"avatarUrl": None})


def require_available_email(db, email, user):
    if db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND id<>?", (email, user["id"])).fetchone():
        raise HTTPException(409, "这个邮箱已绑定其他账号")


@router.post("/email/code")
def send_email_code(request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    from .identity import issue_verification_code, normalize_email
    check_fields(payload, {"email", "currentPassword"})
    email = normalize_email(payload.get("email"))
    with get_db(request) as db:
        row = own_row(db, user)
        verify_current_password(request, payload, row)
        require_available_email(db, email, user)
        if row["email"] == email and row["email_verified_at"]:
            raise HTTPException(422, "这个邮箱已经验证，无需重复绑定")
    return success(issue_verification_code(request, email, purpose="bind-email", user_id=user["id"]))


@router.put("/email")
def bind_email(request: Request, payload: dict = Body(...), user=Depends(auth_user)):
    from .identity import consume_email_code, normalize_email
    check_fields(payload, {"email", "code", "currentPassword"})
    email = normalize_email(payload.get("email"))
    with get_db(request) as db:
        db.execute("BEGIN IMMEDIATE")
        verify_current_password(request, payload, own_row(db, user))
        require_available_email(db, email, user)
        consume_email_code(db, request.app, email, "bind-email", payload.get("code"), user_id=user["id"])
        try:
            db.execute("UPDATE users SET email=?,email_verified_at=?,updated_at=? WHERE id=?", (email, utcnow(), utcnow(), user["id"]))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "这个邮箱已绑定其他账号")
        db.execute("UPDATE email_challenges SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL", (utcnow(), user["id"]))
        return success(profile_record(db, own_row(db, user)))
