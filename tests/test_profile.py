"""Personal settings use only synthetic accounts and captured mail delivery."""
import io
import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from test_app import SETUP, app, admin, core, create_member, data
from backend import system


def image_bytes(kind="PNG", color="tomato", size=(96, 64), **save):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=kind, **save)
    return output.getvalue()


def upload(client, raw=None, filename="portrait.png"):
    return client.post("/api/profile/avatar", files={"file": (filename, raw if raw is not None else image_bytes(), "image/png")})


@pytest.fixture
def captured_mail(app, monkeypatch):
    messages = []
    monkeypatch.setattr(system, "deliver_email", lambda app, config, to, subject, body: messages.append({"to": to, "subject": subject, "body": body}))
    with core.get_db(app) as db:
        system.save_setting(db, "mail", {**system.MAIL_DEFAULTS, "enabled": True, "host": "mail.example.test", "fromEmail": "studio@example.test"})
    return messages


def mail_code(messages):
    return re.search(r"(?<!\d)\d{6}(?!\d)", messages[-1]["body"]).group()


def email_payload(email="synthetic@example.test", **extra):
    return {"email": email, "currentPassword": SETUP["password"], **extra}


def test_profile_requires_session_and_does_not_depend_on_ledger(app, admin):
    with TestClient(app) as anonymous:
        data(anonymous.get("/api/profile"), 401)
        data(anonymous.get("/api/profile/avatar"), 401)
    with core.get_db(app) as db:
        db.execute("DELETE FROM ledger_members")
    result = data(admin.get("/api/profile", headers={"X-Ledger-ID": "999999"}))
    assert result["username"] == SETUP["username"]
    assert result["globalRole"] == "admin"
    assert result["avatarUrl"] is None
    assert result["email"] is None and not result["emailVerified"]
    assert not result["emailVerificationAvailable"]
    assert not {"password_hash", "password_salt"} & result.keys()


def test_name_change_preserves_login_and_financial_owner(admin, app):
    before = data(admin.get("/api/session"))["user"]
    result = data(admin.put("/api/profile", json={"username": SETUP["username"], "name": "Changed Name"}))
    assert result["name"] == "Changed Name" and result["id"] == before["id"]
    assert data(admin.get("/api/session"))["user"]["name"] == "Changed Name"
    with core.get_db(app) as db:
        assert db.execute("SELECT user_id FROM ledger_members").fetchone()[0] == before["id"]


def test_rename_requires_password_and_unique_account(admin, app):
    create_member(admin, app)
    body = {"username": "new-name", "name": SETUP["name"]}
    data(admin.put("/api/profile", json=body), 400)
    data(admin.put("/api/profile", json={**body, "currentPassword": "incorrect-password"}), 400)
    body["currentPassword"] = SETUP["password"]
    data(admin.put("/api/profile", json={**body, "username": "synthetic-member"}), 409)
    assert data(admin.put("/api/profile", json={**body, "username": "New-Name"}))["username"] == "new-name"
    with TestClient(app) as other:
        data(other.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}), 401)
        data(other.post("/api/auth/login", json={"username": "new-name", "password": SETUP["password"]}))


@pytest.mark.parametrize("changes", [{"username": "ab"}, {"username": "invalid@name"}, {"username": "../evil"}, {"name": " "}, {"role": "admin"}, {"email": "unverified@example.test"}, {"avatar_filename": "../private"}])
def test_profile_rejects_invalid_or_protected_fields(admin, changes):
    data(admin.put("/api/profile", json={"username": SETUP["username"], "name": SETUP["name"], **changes}), 422)


def test_password_change_rotates_cookie_and_revokes_other_sessions(admin, app):
    with TestClient(app) as other:
        data(other.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}))
        old_token = admin.cookies.get("studio_session")
        result = admin.post("/api/profile/password", json={"currentPassword": SETUP["password"], "newPassword": "changed-synthetic-password"})
        assert data(result) == {"changed": True}
        assert admin.cookies.get("studio_session") != old_token
        assert "HttpOnly" in result.headers["set-cookie"]
        assert data(admin.get("/api/profile"))["username"] == SETUP["username"]
        data(other.get("/api/profile"), 401)
        data(other.get("/api/profile", headers={"Authorization": "Bearer " + old_token}), 401)
        data(other.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}), 401)
        data(other.post("/api/auth/login", json={"username": SETUP["username"], "password": "changed-synthetic-password"}))
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


@pytest.mark.parametrize("payload,status", [({"currentPassword": "incorrect-password", "newPassword": "new-password"}, 400), ({"currentPassword": SETUP["password"], "newPassword": "short"}, 422), ({"currentPassword": SETUP["password"], "newPassword": SETUP["password"]}, 422), ({"currentPassword": SETUP["password"], "newPassword": "new-password", "userId": 2}, 422)])
def test_bad_password_changes_keep_current_session(admin, payload, status):
    token = admin.cookies.get("studio_session")
    data(admin.post("/api/profile/password", json=payload), status)
    assert admin.cookies.get("studio_session") == token
    data(admin.get("/api/profile"))


def test_password_verification_is_rate_limited(admin):
    for _ in range(10):
        data(admin.post("/api/profile/password", json={"currentPassword": "incorrect-password", "newPassword": "new-password"}), 400)
    data(admin.post("/api/profile/password", json={"currentPassword": "incorrect-password", "newPassword": "new-password"}), 429)


@pytest.mark.parametrize("kind", ["JPEG", "PNG", "WEBP"])
def test_avatar_is_real_image_resized_and_private(admin, app, kind):
    url = data(upload(admin, image_bytes(kind)))["avatarUrl"]
    assert url.startswith("/api/profile/avatar?version=")
    assert data(admin.get("/api/session"))["user"]["avatarUrl"] == url
    response = admin.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(response.content)) as avatar:
        assert avatar.size == (512, 512)
        assert avatar.format == "WEBP"
    _, member = create_member(admin, app)
    data(member.get(url), 404)
    data(member.get(url + "&userId=1"), 404)
    member.close()


def test_avatar_strips_exif_and_replace_delete_cleanup(admin, app):
    exif = Image.Exif()
    exif[270] = "Synthetic private metadata"
    url = data(upload(admin, image_bytes("JPEG", exif=exif)))["avatarUrl"]
    response = admin.get(url)
    with Image.open(io.BytesIO(response.content)) as avatar:
        assert not avatar.getexif()
    assert b"Synthetic private metadata" not in response.content
    directory = app.state.data_dir / "avatars"
    first = next(directory.iterdir())
    next_url = data(upload(admin, image_bytes(color="blue")))["avatarUrl"]
    assert next_url != url and not first.exists()
    assert len(list(directory.iterdir())) == 1
    assert data(admin.delete("/api/profile/avatar"))["avatarUrl"] is None
    assert list(directory.iterdir()) == []
    data(admin.get(next_url), 404)
    data(admin.delete("/api/profile/avatar"))


@pytest.mark.parametrize("raw,status", [(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", 422), (b"", 422), (b"not an image", 422), (b"x" * (2 * 1024 * 1024 + 1), 413), (image_bytes("GIF"), 422), (image_bytes(size=(4001, 4000)), 422)])
def test_avatar_rejects_unsafe_or_large_uploads(admin, raw, status):
    data(upload(admin, raw), status)
    assert data(admin.get("/api/profile"))["avatarUrl"] is None


def test_avatar_rejects_animated_webp(admin):
    output = io.BytesIO()
    Image.new("RGB", (12, 12), "red").save(output, format="WEBP", save_all=True, append_images=[Image.new("RGB", (12, 12), "blue")], duration=100, loop=0)
    data(upload(admin, output.getvalue()), 422)


def test_mail_unconfigured_still_allows_personal_settings(admin):
    data(admin.post("/api/profile/email/code", json=email_payload()), 503)
    assert not data(admin.get("/api/profile"))["emailVerificationAvailable"]
    data(upload(admin))


def test_email_binding_verifies_password_and_code_then_normalizes(admin, app, captured_mail):
    assert data(admin.get("/api/profile"))["emailVerificationAvailable"]
    data(admin.post("/api/profile/email/code", json=email_payload(currentPassword="incorrect-password")), 400)
    assert captured_mail == []
    sent = data(admin.post("/api/profile/email/code", json=email_payload("NEW@EXAMPLE.TEST")))
    assert sent == {"expiresIn": 600, "retryAfter": 60}
    assert captured_mail[-1]["to"] == "new@example.test"
    code = mail_code(captured_mail)
    assert code not in str(sent)
    data(admin.put("/api/profile/email", json=email_payload("new@example.test", code=code, currentPassword="incorrect-password")), 400)
    data(admin.put("/api/profile/email", json=email_payload("new@example.test", code="000000" if code != "000000" else "111111")), 422)
    bound = data(admin.put("/api/profile/email", json=email_payload("new@example.test", code=code)))
    assert bound["email"] == "new@example.test" and bound["emailVerified"]
    data(admin.put("/api/profile/email", json=email_payload("new@example.test", code=code)), 422)
    assert "email" not in data(admin.get("/api/session"))["user"]
    data(admin.post("/api/profile/email/code", json=email_payload("new@example.test")), 422)


def test_email_code_cannot_be_used_by_another_account(admin, app, captured_mail):
    data(admin.post("/api/profile/email/code", json=email_payload()))
    code = mail_code(captured_mail)
    _, member = create_member(admin, app)
    data(member.put("/api/profile/email", json=email_payload(code=code)), 422)
    assert data(member.get("/api/profile"))["email"] is None
    data(admin.put("/api/profile/email", json=email_payload(code=code)))
    data(member.post("/api/profile/email/code", json=email_payload()), 409)
    member.close()


def test_email_binding_unique_case_insensitive_and_atomic(admin, app, captured_mail):
    user, member = create_member(admin, app)
    data(admin.post("/api/profile/email/code", json=email_payload()))
    code = mail_code(captured_mail)
    with core.get_db(app) as db:
        db.execute("UPDATE users SET email='SYNTHETIC@EXAMPLE.TEST',email_verified_at=? WHERE id=?", (core.utcnow(), user["id"]))
    data(admin.put("/api/profile/email", json=email_payload(code=code)), 409)
    assert data(admin.get("/api/profile"))["email"] is None
    with core.get_db(app) as db:
        db.execute("UPDATE users SET email=NULL,email_verified_at=NULL WHERE id=?", (user["id"],))
    assert data(admin.put("/api/profile/email", json=email_payload(code=code)))["emailVerified"]
    member.close()


def test_binding_does_not_expose_email_to_ledger_members(admin, app, captured_mail):
    _, member = create_member(admin, app)
    data(admin.post("/api/profile/email/code", json=email_payload()))
    data(admin.put("/api/profile/email", json=email_payload(code=mail_code(captured_mail))))
    ledger_id = data(admin.get("/api/session"))["activeLedger"]["id"]
    members = data(admin.get(f"/api/ledgers/{ledger_id}/members"))
    assert all("email" not in user for user in members)
    member.close()


@pytest.mark.parametrize("change", ["password", "email"])
def test_security_changes_invalidate_pending_reset_codes(admin, app, captured_mail, change):
    with core.get_db(app) as db:
        db.execute("UPDATE users SET email='old@example.test',email_verified_at=?", (core.utcnow(),))
    data(admin.post("/api/auth/email-code", json={"email": "old@example.test", "purpose": "reset-password"}))
    reset_code = mail_code(captured_mail)
    if change == "password":
        data(admin.post("/api/profile/password", json={"currentPassword": SETUP["password"], "newPassword": "new-synthetic-password"}))
    else:
        data(admin.post("/api/profile/email/code", json=email_payload("new@example.test")))
        data(admin.put("/api/profile/email", json=email_payload("new@example.test", code=mail_code(captured_mail))))
    with core.get_db(app) as db:
        pending = db.execute("SELECT COUNT(*) FROM email_challenges WHERE purpose='reset-password' AND consumed_at IS NULL").fetchone()[0]
        assert pending == 0
    data(admin.post("/api/auth/reset-password", json={"email": "old@example.test", "emailCode": reset_code, "newPassword": "attacker-cannot-use-this"}), 422)
