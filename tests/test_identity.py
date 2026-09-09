"""System policy and email identity tests. All deliveries are mocked locally."""
import json
import re
import smtplib
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from test_app import app as base_app, admin, create_member, data, SETUP
from backend import core, identity, system


@pytest.fixture
def app(base_app):
    # Also permits running this suite while main.py integration is in progress.
    paths = {route.path for route in base_app.routes}
    if "/api/auth/options" not in paths:
        system.init_system_db(base_app)
        identity.init_identity_db(base_app)
        base_app.include_router(system.router)
        base_app.include_router(identity.router)
    return base_app


@pytest.fixture
def outbox(monkeypatch):
    messages = []
    def deliver(app, config, to, subject, body):
        messages.append({"to": to, "subject": subject, "body": body, "code": re.search(r"(?<![0-9])[0-9]{6}(?![0-9])", body).group(0) if "验证码：" in body else None})
    monkeypatch.setattr(system, "deliver_email", deliver)
    return messages


def configure_mail(admin):
    return data(admin.put("/api/system/email", json={"enabled": True, "host": "smtp.example.test", "port": 587, "security": "starttls", "username": "mailer", "password": "synthetic-smtp-secret", "fromEmail": "mail@example.test", "fromName": "Synthetic Studio"}))


def policy(admin, mode="open", required=False):
    return data(admin.put("/api/system/settings", json={"registrationMode": mode, "emailVerificationRequired": required}))


def register_payload(username="new-member", **kwargs):
    return {"username": username, "name": "Synthetic Member", "password": "synthetic-password", **kwargs}


def send_code(client, email="new@example.test", purpose="register", **kwargs):
    return client.post("/api/auth/email-code", json={"email": email, "purpose": purpose, **kwargs})


def set_email(app, user_id, email="admin@example.test", verified=True):
    with core.get_db(app) as db:
        db.execute("UPDATE users SET email=?,email_verified_at=? WHERE id=?", (email, core.utcnow() if verified else None, user_id))


def clear_sends(app):
    with core.get_db(app) as db:
        db.execute("DELETE FROM email_rate_events")


def test_default_policy_and_no_configuration_leak(app, admin):
    with TestClient(app) as anonymous:
        assert data(anonymous.get("/api/auth/options")) == {"siteName": "账序", "registrationMode": "invite", "emailVerificationRequired": False, "emailEnabled": False}
        data(anonymous.get("/api/system/settings"), 401)
        data(anonymous.get("/api/system/email"), 401)
        data(anonymous.post("/api/auth/register", json=register_payload()), 403)
    result = data(admin.get("/api/system/email"))
    assert result["passwordConfigured"] is False and "passwordEncrypted" not in result and "password" not in result


def test_system_admin_is_independent_of_book_role(app, admin):
    _, member = create_member(admin, app, role="admin")
    try:
        assert data(member.get("/api/session"))["user"]["role"] == "admin"
        for method, endpoint, payload in [("GET", "/system/settings", None), ("PUT", "/system/settings", {"siteName": "intruder"}), ("GET", "/system/email", None), ("PUT", "/system/email", {"enabled": False}), ("POST", "/system/email/test", {"to": "x@example.test"})]:
            data(member.request(method, "/api" + endpoint, **({"json": payload} if payload else {})), 403)
        data(member.post("/api/users", json={**register_payload("legacy-bypass"), "role": "member"}), 403)
        admin.headers["X-Ledger-ID"] = "999999"
        assert data(admin.get("/api/system/settings"))["siteName"] == "账序"
    finally:
        member.close()


def test_policy_validation_and_mail_requirement(admin):
    data(admin.put("/api/system/settings", json={"registrationMode": "bad"}), 422)
    data(admin.put("/api/system/settings", json={"emailVerificationRequired": "true"}), 422)
    data(admin.put("/api/system/settings", json={"siteName": ""}), 422)
    data(admin.put("/api/system/settings", json={"siteName": "x\nBcc:bad"}), 422)
    data(admin.put("/api/system/settings", json={"unexpected": True}), 422)
    data(admin.put("/api/system/settings", json={"emailVerificationRequired": True}), 409)
    configure_mail(admin)
    result = data(admin.put("/api/system/settings", json={"siteName": "我的公司", "emailVerificationRequired": True}))
    assert result["siteName"] == "我的公司"
    data(admin.put("/api/system/email", json={"enabled": False}), 409)
    assert data(admin.get("/api/auth/options"))["emailEnabled"]


def test_smtp_password_encrypted_persistent_and_never_returned(app, admin, outbox):
    result = configure_mail(admin)
    assert result["passwordConfigured"] and "passwordEncrypted" not in result
    with core.get_db(app) as db:
        raw = db.execute("SELECT value FROM system_settings WHERE key='mail'").fetchone()[0]
        assert "synthetic-smtp-secret" not in raw
        original = json.loads(raw)["passwordEncrypted"]
        audit = str([dict(row) for row in db.execute("SELECT * FROM audit")])
        assert "synthetic-smtp-secret" not in audit
    key = Path(app.state.data_dir) / "system.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert app.state.mail_cipher.decrypt(original.encode()).decode() == "synthetic-smtp-secret"
    system.init_system_db(app)
    assert app.state.mail_cipher.decrypt(original.encode()).decode() == "synthetic-smtp-secret"
    assert data(admin.put("/api/system/email", json={"fromName": "Changed", "password": ""}))["passwordConfigured"]
    with core.get_db(app) as db:
        assert system.mail_config(db)["passwordEncrypted"] == original
    data(admin.post("/api/system/email/test", json={"to": "test@example.test"}))
    assert outbox[-1]["to"] == "test@example.test"
    assert data(admin.put("/api/system/email", json={"clearPassword": True}))["passwordConfigured"] is False


@pytest.mark.parametrize("value", [None, True, "bad", "x@example.test\r\nBcc:y@example.test", "Name <x@example.test>", "x..y@example.test", "x@-example.test", "x@example..test", "x@localhost", "x" * 65 + "@example.test", "x@example.test;evil"])
def test_email_rejects_malformed_and_header_injection(value):
    with pytest.raises(HTTPException) as error:
        identity.normalize_email(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize("payload", [{"port": 0}, {"port": 65536}, {"port": True}, {"host": "https://smtp.example.test"}, {"host": "smtp.example.test:25"}, {"host": "x\r\nY:bad"}, {"security": "auto"}, {"fromName": "x\nBcc:bad"}, {"fromEmail": False}, {"username": "x\nPASS bad"}, {"password": []}, {"passwordEncrypted": "injected"}, {"password": "new", "clearPassword": True}])
def test_smtp_validation(admin, payload):
    data(admin.put("/api/system/email", json=payload), 422)


def test_open_registration_creates_member_without_implicit_ledger(app, admin):
    policy(admin)
    with TestClient(app) as anonymous:
        user = data(anonymous.post("/api/auth/register", json=register_payload()))["user"]
        assert user["globalRole"] == "member"
        session = data(anonymous.get("/api/session"))
        assert session["ledgers"] == [] and session["activeLedger"] is None
        data(anonymous.post("/api/ledgers", json={"name": "forbidden"}), 403)
    assert data(admin.get("/api/system/settings"))["registrationMode"] == "open"


def test_registration_with_email_requires_proof_even_when_optional(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(anonymous.post("/api/auth/register", json=register_payload(email="new@example.test")), 422)
        data(send_code(anonymous))
        code = outbox[-1]["code"]
        data(anonymous.post("/api/auth/register", json=register_payload(email="new@example.test", emailCode=code)))
        with core.get_db(app) as db:
            user = db.execute("SELECT * FROM users WHERE username='new-member'").fetchone()
            assert user["email"] == "new@example.test" and user["email_verified_at"]
        data(anonymous.post("/api/auth/register", json=register_payload("other-member", email="new@example.test", emailCode=code)), 409)


def test_required_email_and_closed_policy(app, admin, outbox):
    configure_mail(admin)
    policy(admin, required=True)
    with TestClient(app) as anonymous:
        data(anonymous.post("/api/auth/register", json=register_payload()), 422)
        data(send_code(anonymous))
        policy(admin, mode="closed", required=True)
        data(anonymous.post("/api/auth/register", json=register_payload(email="new@example.test", emailCode=outbox[-1]["code"])), 403)
        data(send_code(anonymous, email="other@example.test"), 403)


def test_invitation_registration_cannot_bypass_policy_or_code_context(app, admin, outbox):
    configure_mail(admin)
    policy(admin, mode="invite", required=True)
    book = data(admin.get("/api/session"))["activeLedger"]
    one = data(admin.post(f'/api/ledgers/{book["id"]}/invitations', json={"role": "member", "expiresInDays": 7}))
    two = data(admin.post(f'/api/ledgers/{book["id"]}/invitations', json={"role": "member", "expiresInDays": 7}))
    with TestClient(app) as anonymous:
        data(send_code(anonymous), 403)
        data(send_code(anonymous, invitationToken=one["token"]))
        values = register_payload(email="new@example.test", emailCode=outbox[-1]["code"])
        data(anonymous.post(f'/api/invitations/{two["token"]}/register', json=values), 422)
        policy(admin, mode="closed", required=True)
        data(anonymous.post(f'/api/invitations/{one["token"]}/register', json=values), 403)
        policy(admin, mode="invite", required=True)
        assert data(anonymous.post(f'/api/invitations/{one["token"]}/register', json=values))["ledgerId"] == book["id"]


def test_send_limits_persist_across_app_reinitialization(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous))
        system.init_system_db(app)
        data(send_code(anonymous), 429)
        assert len(outbox) == 1


def test_wrong_codes_are_rate_limited_even_when_transaction_rolls_back(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous))
    for _ in range(10):
        with pytest.raises(HTTPException) as error:
            with core.get_db(app) as db:
                db.execute("BEGIN IMMEDIATE")
                identity.consume_email_code(db, app, "new@example.test", "register", "invalid")
        assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        with core.get_db(app) as db:
            identity.consume_email_code(db, app, "new@example.test", "register", outbox[-1]["code"])
    assert error.value.status_code == 429


def test_expired_code_and_resend_invalidate_previous(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous))
        old_code = outbox[-1]["code"]
        with core.get_db(app) as db:
            db.execute("UPDATE email_challenges SET expires_at='2000-01-01'")
        data(anonymous.post("/api/auth/register", json=register_payload(email="new@example.test", emailCode=old_code)), 422)
        clear_sends(app)
        data(send_code(anonymous))
        assert len(outbox) == 2
        code = outbox[-1]["code"]
        if code != old_code:
            data(anonymous.post("/api/auth/register", json=register_payload(email="new@example.test", emailCode=old_code)), 422)
        data(anonymous.post("/api/auth/register", json=register_payload(email="new@example.test", emailCode=code)))


def test_code_purpose_and_owner_cannot_be_swapped(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous))
        data(anonymous.post("/api/auth/reset-password", json={"email": "new@example.test", "emailCode": outbox[-1]["code"], "newPassword": "a-different-password"}), 422)
    with core.get_db(app) as db:
        row = db.execute("SELECT * FROM email_challenges").fetchone()
        assert outbox[-1]["code"] not in row["code_hash"] and row["consumed_at"] is None


def test_reset_response_does_not_disclose_missing_unverified_or_disabled_accounts(app, admin, outbox):
    configure_mail(admin)
    with TestClient(app) as anonymous:
        missing = send_code(anonymous, "missing@example.test", "reset-password")
        set_email(app, 1, "unverified@example.test", verified=False)
        unverified = send_code(anonymous, "unverified@example.test", "reset-password")
        set_email(app, 1, "disabled@example.test")
        with core.get_db(app) as db:
            db.execute("UPDATE users SET enabled=0 WHERE id=1")
        disabled = send_code(anonymous, "disabled@example.test", "reset-password")
        assert missing.status_code == unverified.status_code == disabled.status_code == 200
        assert missing.json() == unverified.json() == disabled.json()
        assert outbox == []


def test_reset_revokes_all_sessions_and_cannot_be_replayed(app, admin, outbox):
    configure_mail(admin)
    set_email(app, 1)
    with TestClient(app) as other, TestClient(app) as anonymous:
        data(other.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}))
        data(send_code(anonymous, "ADMIN@example.test", "reset-password"))
        values = {"email": "admin@example.test", "emailCode": outbox[-1]["code"], "newPassword": "a-different-password"}
        data(anonymous.post("/api/auth/reset-password", json=values))
        data(admin.get("/api/me"), 401)
        data(other.get("/api/me"), 401)
        data(anonymous.post("/api/auth/reset-password", json=values), 422)
        data(anonymous.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}), 401)
        data(anonymous.post("/api/auth/login", json={"username": SETUP["username"], "password": "a-different-password"}))


def test_concurrent_registration_can_consume_code_only_once(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous))
    code = outbox[-1]["code"]
    def attempt(username):
        with TestClient(app) as client:
            return client.post("/api/auth/register", json=register_payload(username, email="new@example.test", emailCode=code)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(attempt, ["concurrent-a", "concurrent-b"]))
    assert statuses == [200, 409]
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE email='new@example.test'").fetchone()[0] == 1


def test_concurrent_password_reset_can_succeed_only_once(app, admin, outbox):
    configure_mail(admin)
    set_email(app, 1)
    with TestClient(app) as anonymous:
        data(send_code(anonymous, "admin@example.test", "reset-password"))
    values = {"email": "admin@example.test", "emailCode": outbox[-1]["code"], "newPassword": "concurrent-new-password"}
    def attempt(_):
        with TestClient(app) as client:
            return client.post("/api/auth/reset-password", json=values).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == [200, 422]


def test_invitation_and_public_registration_cannot_elevate_global_role(app, admin):
    policy(admin)
    book = data(admin.get("/api/session"))["activeLedger"]
    invitation = data(admin.post(f'/api/ledgers/{book["id"]}/invitations', json={"role": "admin", "expiresInDays": 7}))
    with TestClient(app) as anonymous:
        data(anonymous.post("/api/auth/register", json={**register_payload(), "role": "admin"}), 422)
        user = data(anonymous.post(f'/api/invitations/{invitation["token"]}/register', json=register_payload()))["user"]
        assert user["role"] == "admin" and user["globalRole"] == "member"
        data(anonymous.put("/api/system/settings", json={"registrationMode": "open"}), 403)


def test_public_email_code_cannot_issue_authenticated_binding_challenges(app, admin):
    configure_mail(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous, purpose="bind-email"), 422)
        data(send_code(anonymous, purpose="reset-password", invitationToken="injected"), 422)


def test_registration_failure_rolls_back_code_consumption(app, admin, outbox):
    configure_mail(admin)
    policy(admin)
    with TestClient(app) as anonymous:
        data(send_code(anonymous))
        values = register_payload(SETUP["username"], email="new@example.test", emailCode=outbox[-1]["code"])
        data(anonymous.post("/api/auth/register", json=values), 409)
        values["username"] = "valid-new-member"
        data(anonymous.post("/api/auth/register", json=values))


def test_failed_delivery_invalidates_code_and_redacts_smtp_error(app, admin, monkeypatch):
    configure_mail(admin)
    policy(admin)
    def fail(*args, **kwargs):
        raise HTTPException(502, "邮件发送失败，请管理员检查 SMTP 配置和服务状态")
    monkeypatch.setattr(system, "deliver_email", fail)
    with TestClient(app) as anonymous:
        data(send_code(anonymous), 502)
        with core.get_db(app) as db:
            row = db.execute("SELECT * FROM email_challenges").fetchone()
            assert row["consumed_at"] is not None and row["delivered_at"] is None
        set_email(app, 1)
        # SMTP failures remain indistinguishable from an unknown reset address.
        data(send_code(anonymous, "admin@example.test", "reset-password"))


@pytest.mark.parametrize("security", ["starttls", "ssl", "none"])
def test_mail_transport_uses_selected_tls_mode_and_encrypted_secret(app, admin, monkeypatch, security):
    configure_mail(admin)
    data(admin.put("/api/system/email", json={"security": security}))
    calls = []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            calls.append(("connect", host, port, kwargs))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): calls.append(("ehlo",))
        def starttls(self, **kwargs): calls.append(("tls", kwargs))
        def login(self, username, password): calls.append(("login", username, password))
        def send_message(self, message): calls.append(("message", message))
    monkeypatch.setattr(system.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(system.smtplib, "SMTP_SSL", SMTP)
    data(admin.post("/api/system/email/test", json={"to": "test@example.test"}))
    assert ("login", "mailer", "synthetic-smtp-secret") in calls
    assert any(call[0] == "tls" for call in calls) == (security == "starttls")
    assert ("context" in calls[0][3]) == (security == "ssl")
    assert calls[-1][1]["To"] == "test@example.test"


def test_smtp_server_exception_never_leaks_credentials(app, admin, monkeypatch):
    configure_mail(admin)
    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPAuthenticationError(535, b"sensitive synthetic-smtp-secret")
    monkeypatch.setattr(system.smtplib, "SMTP", BrokenSMTP)
    response = admin.post("/api/system/email/test", json={"to": "test@example.test"})
    data(response, 502)
    assert "sensitive" not in response.text and "synthetic-smtp-secret" not in response.text
