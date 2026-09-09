"""Migration and identity authorization across the assembled Studio application."""
import hashlib
import sqlite3
import stat

import pytest
from fastapi.testclient import TestClient

from test_app import (SETUP, app, admin, data, add_account, add_flow,
                         payload, approve, create_member)
from test_ledgers import current_book, invite, make_book, select
from backend import core, main, system

OLD_USER_COLUMNS = ("id", "username", "name", "role", "enabled", "password_hash", "password_salt", "created_at", "updated_at")
PRESERVED_TABLES = ("sessions", "settings", "ledgers", "ledger_members", "ledger_invitations", "accounts", "categories", "flows", "audit", "studio_invoices")


@pytest.fixture(autouse=True)
def forbid_delivery(monkeypatch):
    def unexpected_delivery(*args, **kwargs):
        raise AssertionError("Integration authorization tests must not send mail")
    monkeypatch.setattr(system, "deliver_email", unexpected_delivery)


def rows(db, table, columns="*"):
    return [tuple(row) for row in db.execute(f"SELECT {columns} FROM {table} ORDER BY rowid")]


def test_upgrading_existing_multi_ledger_database_preserves_identity_and_books(admin, app):
    """Recreate the actual pre-identity schema around existing synthetic books."""
    first = current_book(admin)
    user, member = create_member(admin, app)
    first_account = add_account(admin, "Synthetic migration first", "1234.56")
    first_flow = approve(admin, add_flow(admin, payload(admin, first_account, amount="31.42")))
    second = make_book(admin, "Synthetic migration second")
    pending_invite = invite(admin, second, "member")
    select(admin, second)
    second_account = add_account(admin, "Synthetic migration second", "654.32")
    second_flow = add_flow(admin, payload(admin, second_account, action=1, amount="7.89"))
    token = admin.cookies.get("studio_session")
    member_token = member.cookies.get("studio_session")
    member.close()
    database = app.state.data_dir / "studio.sqlite3"

    # Drop only the just-added identity schema to simulate a saved installation.
    # SQLite's DROP COLUMN preserves the original user table and its foreign keys.
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX users_email_unique")
        for column in ("email", "email_verified_at", "avatar_filename"):
            db.execute(f"ALTER TABLE users DROP COLUMN {column}")
        for table in ("email_challenges", "email_rate_events", "system_settings"):
            db.execute(f"DROP TABLE {table}")
        assert tuple(row[1] for row in db.execute("PRAGMA table_info(users)")) == OLD_USER_COLUMNS
        original_users = rows(db, "users")
        original_tables = {table: rows(db, table) for table in PRESERVED_TABLES}
    key_path = app.state.data_dir / "system.key"
    key_path.unlink()

    migrated = main.create_app(app.state.data_dir, app.state.web_dir)
    key = key_path.read_bytes()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    with core.get_db(migrated) as db:
        assert rows(db, "users", ",".join(OLD_USER_COLUMNS)) == original_users
        assert rows(db, "users", "email,email_verified_at,avatar_filename") == [(None, None, None)] * 2
        assert {table: rows(db, table) for table in PRESERVED_TABLES} == original_tables
        assert list(db.execute("PRAGMA foreign_key_check")) == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT user_id FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0] == 1
        assert db.execute("SELECT token_hash FROM ledger_invitations WHERE id=?", (pending_invite["id"],)).fetchone()[0] == hashlib.sha256(pending_invite["token"].encode()).hexdigest()

    with TestClient(migrated) as restored:
        restored.headers["Authorization"] = "Bearer " + token
        session = data(restored.get("/api/session"))
        assert [book["id"] for book in session["ledgers"]] == [first["id"], second["id"]]
        assert session["user"]["id"] == original_users[0][0]
        select(restored, first)
        assert data(restored.get(f'/api/flow/getFlow/{first_flow["id"]}'))["money"] == "31.42"
        assert data(restored.get("/api/account/getAccount"))[0]["money"] == "1265.98"
        select(restored, second)
        assert data(restored.get(f'/api/flow/getFlow/{second_flow["id"]}'))["money"] == "7.89"
        assert data(restored.get("/api/account/getAccount"))[0]["id"] == second_account["id"]
        assert data(restored.get("/api/profile"))["email"] is None
    with TestClient(migrated) as restored_member:
        restored_member.headers["Authorization"] = "Bearer " + member_token
        assert data(restored_member.get("/api/profile"))["id"] == user["id"]
    repeated = main.create_app(app.state.data_dir, app.state.web_dir)
    assert key_path.read_bytes() == key
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    with core.get_db(repeated) as db:
        assert rows(db, "users", ",".join(OLD_USER_COLUMNS)) == original_users
        assert {table: rows(db, table) for table in PRESERVED_TABLES} == original_tables


def test_username_and_verified_email_login_have_identical_identity(admin, app):
    user, member = create_member(admin, app)
    member.close()
    with core.get_db(app) as db:
        db.execute("UPDATE users SET email='verified@example.test',email_verified_at=? WHERE id=1", (core.utcnow(),))
        db.execute("UPDATE users SET email='unverified@example.test',email_verified_at=NULL WHERE id=?", (user["id"],))
    with TestClient(app) as client:
        by_username = data(client.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}))["user"]
        by_email = data(client.post("/api/auth/login", json={"username": "VERIFIED@EXAMPLE.TEST", "password": SETUP["password"]}))["user"]
        assert by_username == by_email
        data(client.post("/api/auth/login", json={"username": "verified@example.test", "password": "incorrect-password"}), 401)
        data(client.post("/api/auth/login", json={"username": "unverified@example.test", "password": SETUP["password"]}), 401)
        assert data(client.post("/api/auth/login", json={"username": user["username"], "password": SETUP["password"]}))["user"]["id"] == user["id"]
        with core.get_db(app) as db:
            db.execute("UPDATE users SET enabled=0 WHERE id=1")
        data(client.post("/api/auth/login", json={"username": "verified@example.test", "password": SETUP["password"]}), 401)
        data(client.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}), 401)


@pytest.mark.parametrize("target", ["self", "other"])
@pytest.mark.parametrize("change,status", [({"name": "Unauthorized rename"}, 403), ({"password": "unauthorized-new-password"}, 403), ({"name": "Unauthorized rename", "enabled": False}, 403), ({"username": "unauthorized-login"}, 422)])
def test_legacy_users_route_cannot_change_global_identity_even_for_self(admin, app, target, change, status):
    user, member = create_member(admin, app)
    target_id = 1 if target == "self" else user["id"]
    with core.get_db(app) as db:
        before = tuple(db.execute("SELECT username,name,password_hash,password_salt,enabled FROM users WHERE id=?", (target_id,)).fetchone())
        sessions = rows(db, "sessions")
        memberships = rows(db, "ledger_members")
    data(admin.put(f"/api/users/{target_id}", json=change), status)
    with core.get_db(app) as db:
        assert tuple(db.execute("SELECT username,name,password_hash,password_salt,enabled FROM users WHERE id=?", (target_id,)).fetchone()) == before
        assert rows(db, "sessions") == sessions
        assert rows(db, "ledger_members") == memberships
    assert data(member.get("/api/profile"))["id"] == user["id"]
    member.close()


def invited_admin(admin, app):
    book = current_book(admin)
    invitation = invite(admin, book, "admin")
    client = TestClient(app)
    result = data(client.post(f'/api/invitations/{invitation["token"]}/register', json={"username": "invited-book-admin", "name": "Synthetic Book Admin", "password": SETUP["password"]}))
    assert result["user"]["globalRole"] == "member"
    select(client, book)
    assert data(client.get("/api/session"))["user"]["role"] == "admin"
    return client, result["user"]


@pytest.mark.parametrize("mode", ["invite", "closed", "open"])
def test_invited_ledger_admin_cannot_bypass_signup_policy_with_legacy_creation(admin, app, mode):
    book_admin, _ = invited_admin(admin, app)
    data(admin.put("/api/system/email", json={"enabled": True, "host": "smtp.example.test", "fromEmail": "studio@example.test", "password": "synthetic-smtp-secret"}))
    data(admin.put("/api/system/settings", json={"registrationMode": mode, "emailVerificationRequired": True}))
    body = {"username": "manually-created", "name": "Synthetic Manual Account", "password": SETUP["password"], "role": "admin"}
    data(book_admin.post("/api/users", json=body), 403)
    data(book_admin.post("/api/auth/register", json={key: value for key, value in body.items() if key != "role"}), 422 if mode == "open" else 403)
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username='manually-created'").fetchone()[0] == 0
    created = data(admin.post("/api/users", json=body))
    with core.get_db(app) as db:
        row = db.execute("SELECT role,email FROM users WHERE id=?", (created["id"],)).fetchone()
        assert row["role"] == "member" and row["email"] is None
        assert db.execute("SELECT role FROM ledger_members WHERE user_id=?", (created["id"],)).fetchone()[0] == "admin"
    book_admin.close()


def test_book_admin_and_unaffiliated_user_cannot_read_smtp_or_system_config(admin, app):
    book_admin, user = invited_admin(admin, app)
    configured = data(admin.put("/api/system/email", json={"enabled": True, "host": "private-smtp.example.test", "fromEmail": "studio@example.test", "username": "synthetic-smtp-user", "password": "synthetic-smtp-secret"}))
    assert configured["passwordConfigured"]
    assert "password" not in configured and "passwordEncrypted" not in configured
    assert "synthetic-smtp-secret" not in str(configured)
    with core.get_db(app) as db:
        storage = db.execute("SELECT value FROM system_settings WHERE key='mail'").fetchone()[0]
        assert "synthetic-smtp-secret" not in storage
    for path in ("/api/system/settings", "/api/system/email"):
        response = book_admin.get(path)
        data(response, 403)
        assert "private-smtp.example.test" not in response.text
        assert "synthetic-smtp-secret" not in response.text
    data(book_admin.put("/api/system/email", json={"password": "cannot-replace-secret"}), 403)
    data(book_admin.post("/api/system/email/test", json={"to": "no-email-sent@example.test"}), 403)
    book = current_book(admin)
    data(admin.delete(f'/api/ledgers/{book["id"]}/members/{user["id"]}'))
    session = data(book_admin.get("/api/session"))
    assert session["ledgers"] == [] and session["activeLedger"] is None
    assert data(book_admin.get("/api/profile"))["id"] == user["id"]
    changed = data(book_admin.put("/api/profile", json={"username": user["username"], "name": "Still allowed without a ledger"}))
    assert changed["name"] == "Still allowed without a ledger"
    data(book_admin.get("/api/account/getAccount"), 403)
    data(book_admin.get("/api/system/email"), 403)
    data(book_admin.get("/api/system/settings"), 403)
    book_admin.close()
