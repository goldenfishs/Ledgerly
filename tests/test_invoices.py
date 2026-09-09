"""Owner-isolated invoice tests using synthetic attachments, real local sessions and mocked OCR."""
import asyncio
import hashlib
import io
import json
import sqlite3
from pathlib import Path

import fitz
import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from PIL import Image

from backend import core, invoices
from backend.ledgers import create_ledger


def image_bytes(color="white", format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(stream, format=format)
    return stream.getvalue()


def pdf_bytes():
    with fitz.open() as document:
        document.new_page().insert_text((30, 40), "FICTIONAL TEST INVOICE - NOT FOR REIMBURSEMENT")
        document.new_page().insert_text((30, 40), "SECOND TEST PAGE")
        return document.tobytes()


@pytest.fixture
def app(tmp_path):
    app = FastAPI()
    app.state.data_dir = tmp_path
    app.state.llm_config_path = tmp_path / "not-configured.ini"
    core.init_db(app)
    invoices.init_invoices(app)
    app.include_router(invoices.router)
    tokens = {}
    with core.get_db(app) as db:
        for identifier, name, role in [(1, "测试成员甲", "member"), (2, "测试成员乙", "member"), (3, "测试管理员", "admin")]:
            db.execute("INSERT INTO users(id,username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (?,?,?,?,1,?,?,?,?)", (identifier, f"test{identifier}", name, role, "unused", "unused", core.utcnow(), core.utcnow()))
            tokens[identifier] = core.new_session(db, identifier)
        first_ledger = create_ledger(db, core.public_user(db.execute("SELECT * FROM users WHERE id=3").fetchone()), "虚构测试账本一")
        second_ledger = create_ledger(db, core.public_user(db.execute("SELECT * FROM users WHERE id=1").fetchone()), "虚构测试账本二")
        assert first_ledger["id"] == 1 and second_ledger["id"] == 2
        for ledger_id, user_id in [(1, 1), (1, 2), (2, 3)]:
            db.execute("INSERT INTO ledger_members VALUES (?,?,'member',1,?)", (ledger_id, user_id, core.utcnow()))
    app.state.tokens = tokens
    return app


@pytest.fixture
def clients(app):
    with TestClient(app) as first, TestClient(app) as second, TestClient(app) as admin:
        for identifier, client in enumerate([first, second, admin], 1):
            client.cookies.set("studio_session", app.state.tokens[identifier])
            client.headers["X-Ledger-ID"] = "1"
        yield first, second, admin


def upload(client, content=None, name="synthetic.png"):
    response = client.post("/api/invoices", files={"file": (name, image_bytes() if content is None else content, "application/octet-stream")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0 and body["msg"] == "ok"
    return body["data"]


def url(record):
    return "/api/invoices/" + record["id"]


def test_owner_isolation_and_per_owner_deduplication(clients):
    first, second, admin = clients
    one = upload(first)["invoice"]
    two = upload(second)["invoice"]
    assert one["id"] != two["id"]
    assert one["ownerId"] == 1 and one["ownerName"] == "测试成员甲"
    assert upload(first)["duplicate"] is True
    for client, expected in [(first, [one["id"]]), (second, [two["id"]]), (admin, [one["id"], two["id"]])]:
        data = client.get("/api/invoices").json()["data"]
        assert sorted(item["id"] for item in data["items"]) == sorted(expected)
    attempts = [("GET", "", {}), ("GET", "/file", {}), ("GET", "/preview", {}),
                ("PATCH", "", {"json": {"version": 1, "seller": "intruder"}}),
                ("DELETE", "?version=1", {}), ("POST", "/restore?version=1", {}),
                ("POST", "/recognize", {"json": {"version": 1}})]
    for method, suffix, kwargs in attempts:
        response = second.request(method, url(one) + suffix, **kwargs)
        assert response.status_code == 404, (method, suffix, response.text)
    assert first.get(url(one)).json()["data"]["version"] == 1
    assert admin.get(url(one) + "/file").content == image_bytes()


def test_actual_cookie_auth_required_on_every_route(app):
    with TestClient(app) as client:
        for method, path in [("GET", ""), ("POST", ""), ("GET", "/unknown"), ("GET", "/unknown/file"), ("GET", "/unknown/preview"), ("PATCH", "/unknown"), ("DELETE", "/unknown?version=1"), ("POST", "/unknown/restore?version=1"), ("POST", "/unknown/recognize")]:
            response = client.request(method, "/api/invoices" + path, headers={"user_id": "1"}, json={"version": 1})
            assert response.status_code == 401
        client.cookies.set("studio_session", "forged-session")
        assert client.get("/api/invoices").status_code == 401


def test_disabled_member_loses_invoice_access(app, clients):
    first, _, _ = clients
    record = upload(first)["invoice"]
    with core.get_db(app) as db:
        db.execute("UPDATE users SET enabled=0 WHERE id=1")
    assert first.get(url(record) + "/file").status_code == 401
    assert first.get("/api/invoices").status_code == 401


@pytest.mark.parametrize("content,name", [(b"", "empty.png"), (b"plain text", "fake.jpg"), (b"%PDF-broken", "broken.pdf"), (image_bytes(format="GIF"), "hidden.png"), (b'<svg onload="alert(1)"></svg>', "unsafe.png")])
def test_invalid_files_rejected_without_records(clients, content, name):
    client = clients[0]
    response = client.post("/api/invoices", files={"file": (name, content, "image/png")})
    assert response.status_code == 422
    assert client.get("/api/invoices").json()["data"]["items"] == []


def test_size_limit(clients, monkeypatch):
    monkeypatch.setattr(invoices, "MAX_FILE_SIZE", 40)
    assert clients[0].post("/api/invoices", files={"file": ("large.png", image_bytes())}).status_code == 413


def test_pdf_preview_and_original_persist(app, clients):
    client = clients[0]
    content = pdf_bytes()
    record = upload(client, content, "sample.pdf")["invoice"]
    assert record["page_count"] == 2 and record["mime_type"] == "application/pdf"
    preview = client.get(url(record) + "/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(preview.content)) as image:
        assert max(image.size) <= 1800
    original = client.get(url(record) + "/file")
    assert original.content == content
    assert original.headers["cache-control"] == "private, no-store"
    invoices.init_invoices(app)
    assert client.get(url(record)).json()["data"]["has_file"]
    assert len(list((app.state.data_dir / "invoices").iterdir())) == 1


def test_metadata_validation_search_and_concurrency(clients):
    client = clients[0]
    record = upload(client)["invoice"]
    fields = {"version": 1, "invoice_number": "TEST20260908001", "invoice_date": "2026-09-08", "seller": "测试公司（虚构）", "buyer": "测试购买方", "amount": "116.45", "tax_amount": "7", "total_amount": "123.45", "status": "confirmed", "category": "办公", "notes": '<img src=x onerror="alert(1)">'}
    response = client.patch(url(record), json=fields)
    assert response.status_code == 200
    edited = response.json()["data"]
    assert edited["tax_amount"] == "7.00" and edited["version"] == 2 and edited["status"] == "confirmed"
    assert edited["notes"] == fields["notes"]
    assert client.patch(url(record), json=fields).status_code == 409
    assert client.patch(url(record), json={"seller": "without version"}).status_code == 422
    assert len(client.get("/api/invoices?q=测试公司&status=confirmed&category=办公").json()["data"]["items"]) == 1
    assert client.get("/api/invoices?q=absent").json()["data"]["items"] == []


@pytest.mark.parametrize("fields", [{"amount": "NaN"}, {"amount": "1.001"}, {"amount": True}, {"invoice_date": "2026-02-30"}, {"invoice_number": "x" * 129}, {"notes": "x" * 4001}, {"category": "invalid"}, {"status": "processing"}, {"ownerId": 2}, {"ownerName": "another"}, {"seller": {}}, {"status": "confirmed"}])
def test_bad_metadata_preserves_record(clients, fields):
    client = clients[0]
    record = upload(client)["invoice"]
    response = client.patch(url(record), json={"version": 1, **fields})
    assert response.status_code == 422, response.text
    assert client.get(url(record)).json()["data"]["version"] == 1


def test_zero_and_negative_amounts(clients):
    client = clients[0]
    record = upload(client)["invoice"]
    response = client.patch(url(record), json={"version": 1, "amount": "-10.00", "tax_amount": "0", "total_amount": "-10", "status": "confirmed"})
    assert response.status_code == 200
    assert response.json()["data"]["total_amount"] == "-10.00"


def test_admin_delete_restore_and_audit_keep_owner(app, clients):
    first, _, admin = clients
    record = upload(first)["invoice"]
    assert admin.delete(url(record)).status_code == 422
    deleted = admin.delete(url(record) + "?version=1").json()["data"]
    assert deleted["deleted_at"] and deleted["ownerId"] == 1
    assert first.get("/api/invoices").json()["data"]["items"] == []
    assert len(first.get("/api/invoices?trash=true").json()["data"]["items"]) == 1
    assert first.patch(url(record), json={"version": 2, "seller": "trash edit"}).status_code == 409
    assert first.post(url(record) + "/recognize", json={"version": 2}).status_code == 409
    duplicate = upload(first)
    assert duplicate["duplicate"] and duplicate["invoice"]["deleted_at"]
    assert admin.post(url(record) + "/restore?version=1").status_code == 409
    restored = admin.post(url(record) + "/restore?version=2").json()["data"]
    assert restored["deleted_at"] is None and restored["ownerId"] == 1 and restored["version"] == 3
    assert first.get(url(record) + "/file").content == image_bytes()
    with core.get_db(app) as db:
        events = db.execute("SELECT actor_id,action FROM audit WHERE entity_id=?", (record["id"],)).fetchall()
    assert [(row["actor_id"], row["action"]) for row in events] == [(1,"invoice.upload"), (3,"invoice.delete"), (3,"invoice.restore")]


def test_ocr_success_keeps_review_and_original(clients, monkeypatch):
    async def provider(request, content, mime):
        assert content and mime.startswith("image/")
        return {"invoice_number": "TEST-001", "amount": "116.45", "tax_amount": "7", "total_amount": "123.45"}
    monkeypatch.setattr(invoices, "recognize_with_provider", provider)
    record = upload(clients[0])["invoice"]
    response = clients[0].post(url(record) + "/recognize", json={"version": 1})
    recognized = response.json()["data"]
    assert response.status_code == 200 and recognized["status"] == "review"
    assert recognized["version"] == 3 and recognized["total_amount"] == "123.45" and recognized["has_file"]


@pytest.mark.parametrize("result", [[], {"amount": "Infinity"}, {"category": "其他"}, {"seller": "test", "status": "confirmed"}, {"seller": "test", "ownerId": 3}])
def test_invalid_ocr_can_retry_or_edit(clients, monkeypatch, result):
    async def provider(*args):
        return result
    monkeypatch.setattr(invoices, "recognize_with_provider", provider)
    client = clients[0]
    record = upload(client)["invoice"]
    error = client.post(url(record) + "/recognize", json={"version": 1}).json()["data"]
    assert error["status"] == "error" and error["error"] and error["has_file"]
    async def recovered(*args):
        return {"total_amount": "1.00", "seller": "Recovered"}
    monkeypatch.setattr(invoices, "recognize_with_provider", recovered)
    retried = client.post(url(record) + "/recognize", json={"version": error["version"]}).json()["data"]
    assert retried["status"] == "review" and retried["ownerId"] == 1
    saved = client.patch(url(record), json={"version": retried["version"], "status": "confirmed", "total_amount": "25"}).json()["data"]
    assert saved["status"] == "confirmed" and saved["error"] == ""


def test_missing_model_keeps_file(clients, monkeypatch):
    for name in ["STUDIO_LLM_API_KEY", "STUDIO_LLM_BASE_URL", "STUDIO_LLM_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    record = upload(clients[0])["invoice"]
    error = clients[0].post(url(record) + "/recognize", json={"version": 1}).json()["data"]
    assert error["status"] == "error" and "尚未配置" in error["error"]
    assert clients[0].get(url(record) + "/file").status_code == 200


def test_ocr_does_not_overwrite_concurrent_manual_edits(app, monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def provider(*args):
            entered.set()
            await release.wait()
            return {"total_amount": "999.00", "seller": "stale OCR"}
        monkeypatch.setattr(invoices, "recognize_with_provider", provider)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"Authorization": app.state.tokens[1]}) as client:
            record = (await client.post("/api/invoices", files={"file": ("test.png", image_bytes())})).json()["data"]["invoice"]
            task = asyncio.create_task(client.post(url(record) + "/recognize", json={"version": 1}))
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert (await client.post(url(record) + "/recognize", json={"version": 2})).status_code == 409
            edit = await client.patch(url(record), json={"version": 2, "seller": "manual", "total_amount": "25", "status": "confirmed"})
            assert edit.status_code == 200
            release.set()
            assert (await task).status_code == 409
            current = (await client.get(url(record))).json()["data"]
            assert current["seller"] == "manual" and current["total_amount"] == "25.00"
    asyncio.run(run())


def test_processing_recovered_on_restart(app, clients):
    record = upload(clients[0])["invoice"]
    with core.get_db(app) as db:
        row = db.execute("SELECT * FROM studio_invoices WHERE id=?", (record["id"],)).fetchone()
        data = invoices.decode(row)
        data["status"] = "processing"
        invoices.write_record(db, data, row["version"])
    invoices.init_invoices(app)
    recovered = clients[0].get(url(record)).json()["data"]
    assert recovered["status"] == "error" and "重启" in recovered["error"]


def test_model_config_read_only_and_request_simulated(app, monkeypatch):
    path = app.state.data_dir / "test-model.ini"
    content = "[easy-accounts]\napi_key=synthetic-test-key\nurl=https://provider.invalid/v1\nmodel=synthetic-model\n"
    path.write_text(content)
    app.state.llm_config_path = path
    for name in ["STUDIO_LLM_API_KEY", "STUDIO_LLM_BASE_URL", "STUDIO_LLM_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    request = Request({"type":"http", "app":app})
    original = httpx.AsyncClient
    seen = []
    def handler(req):
        seen.append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer synthetic-test-key"
        return httpx.Response(200, json={"choices":[{"message":{"content":'{"total_amount":"123.45","seller":"Synthetic"}'}}]})
    monkeypatch.setattr(invoices.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(invoices.recognize_with_provider(request, image_bytes(), "image/png"))
    assert result["total_amount"] == "123.45" and seen[0]["model"] == "synthetic-model"
    assert path.read_text() == content


def test_same_owner_can_upload_identical_file_in_separate_ledgers(clients):
    first, _, admin = clients
    first.headers["X-Ledger-ID"] = "1"
    one = upload(first)["invoice"]
    first.headers["X-Ledger-ID"] = "2"
    other = upload(first)
    assert other["duplicate"] is False
    two = other["invoice"]
    assert one["id"] != two["id"] and one["ledgerId"] == 1 and two["ledgerId"] == 2
    assert upload(first)["duplicate"] is True
    assert [record["id"] for record in first.get("/api/invoices").json()["data"]["items"]] == [two["id"]]
    first.headers["X-Ledger-ID"] = "1"
    assert upload(first)["invoice"]["id"] == one["id"]
    assert [record["id"] for record in first.get("/api/invoices").json()["data"]["items"]] == [one["id"]]
    admin.headers["X-Ledger-ID"] = "1"
    assert [record["id"] for record in admin.get("/api/invoices").json()["data"]["items"]] == [one["id"]]


@pytest.mark.parametrize("method,suffix,kwargs", [
    ("GET", "", {}), ("GET", "/file", {}), ("GET", "/preview", {}),
    ("PATCH", "", {"json": {"version": 1, "seller": "wrong ledger"}}),
    ("DELETE", "?version=1", {}), ("POST", "/restore?version=1", {}),
    ("POST", "/recognize", {"json": {"version": 1}}),
])
def test_every_invoice_route_hides_other_ledger_even_from_ledger_admin(clients, method, suffix, kwargs):
    first, _, _ = clients
    first.headers["X-Ledger-ID"] = "1"
    record = upload(first)["invoice"]
    first.headers["X-Ledger-ID"] = "2"  # The same owner is an administrator here.
    response = first.request(method, url(record) + suffix, **kwargs)
    assert response.status_code == 404
    first.headers["X-Ledger-ID"] = "1"
    current = first.get(url(record)).json()["data"]
    assert current["version"] == 1 and current["status"] == "pending" and current["ledgerId"] == 1


def test_global_admin_uses_membership_role_for_invoice_scope(clients):
    first, second, admin = clients
    first.headers["X-Ledger-ID"] = "2"  # Global member, ledger administrator.
    admin.headers["X-Ledger-ID"] = "2"  # Global administrator, ledger member.
    record = upload(first)["invoice"]
    own_record = upload(admin)["invoice"]
    assert len(first.get("/api/invoices").json()["data"]["items"]) == 2
    assert [row["id"] for row in admin.get("/api/invoices").json()["data"]["items"]] == [own_record["id"]]
    assert admin.get(url(record)).status_code == 404
    assert admin.get(url(record) + "/file").status_code == 404
    assert admin.patch(url(record), json={"version": 1, "seller": "not permitted"}).status_code == 404
    second.headers["X-Ledger-ID"] = "2"  # No membership in this ledger.
    assert second.get("/api/invoices").status_code in (403, 404)
    assert second.get(url(record) + "/file").status_code in (403, 404)


@pytest.mark.parametrize("fields", [{"ledgerId": 2}, {"ledger_id": 2}])
def test_request_metadata_cannot_move_invoice_to_another_ledger(clients, fields):
    record = upload(clients[0])["invoice"]
    response = clients[0].patch(url(record), json={"version": 1, **fields})
    assert response.status_code == 422
    current = clients[0].get(url(record)).json()["data"]
    assert current["ledgerId"] == 1 and current["version"] == 1


def test_trash_and_restore_remain_in_original_ledger(clients):
    first = clients[0]
    one = upload(first)["invoice"]
    first.delete(url(one) + "?version=1")
    first.headers["X-Ledger-ID"] = "2"
    assert first.get("/api/invoices?trash=true").json()["data"]["items"] == []
    two = upload(first)
    assert not two["duplicate"] and not two["invoice"]["deleted_at"]
    assert first.post(url(one) + "/restore?version=2").status_code == 404
    first.headers["X-Ledger-ID"] = "1"
    assert first.get("/api/invoices?trash=true").json()["data"]["items"][0]["id"] == one["id"]
    restored = first.post(url(one) + "/restore?version=2").json()["data"]
    assert restored["ledgerId"] == 1 and restored["id"] == one["id"]


def test_ocr_writeback_keeps_ledger_selected_when_request_started(app, monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def provider(*args):
            entered.set()
            await release.wait()
            return {"seller": "OCR in ledger one", "total_amount": "123.45"}
        monkeypatch.setattr(invoices, "recognize_with_provider", provider)
        headers = {"Authorization": app.state.tokens[1], "X-Ledger-ID": "1"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers) as client:
            one = (await client.post("/api/invoices", files={"file": ("one.png", image_bytes())})).json()["data"]["invoice"]
            recognition = asyncio.create_task(client.post(url(one) + "/recognize", json={"version": 1}))
            await asyncio.wait_for(entered.wait(), timeout=5)
            client.headers["X-Ledger-ID"] = "2"
            two = (await client.post("/api/invoices", files={"file": ("two.png", image_bytes())})).json()["data"]["invoice"]
            edited = await client.patch(url(two), json={"version": 1, "seller": "Manual in ledger two", "total_amount": "25", "status": "confirmed"})
            assert edited.status_code == 200
            assert (await client.get(url(one))).status_code == 404
            release.set()
            response = await recognition
            assert response.status_code == 200 and response.json()["data"]["ledgerId"] == 1
            other = (await client.get(url(two))).json()["data"]
            assert other["seller"] == "Manual in ledger two" and other["total_amount"] == "25.00"
            client.headers["X-Ledger-ID"] = "1"
            original = (await client.get(url(one))).json()["data"]
            assert original["seller"] == "OCR in ledger one" and original["ledgerId"] == 1
            assert (await client.get(url(two))).status_code == 404
        with core.get_db(app) as db:
            events = db.execute("SELECT DISTINCT ledger_id FROM audit WHERE entity_id=?", (one["id"],)).fetchall()
            assert [row["ledger_id"] for row in events] == [1]
    asyncio.run(run())


def test_write_record_checks_ledger_and_owner_even_for_same_id(app, clients):
    record = upload(clients[0])["invoice"]
    for key, value in [("ledgerId", 2), ("ownerId", 2)]:
        with pytest.raises(HTTPException) as error:
            with core.get_db(app) as db:
                forged = {**record, key: value, "seller": "wrong scope"}
                invoices.write_record(db, forged, 1)
        assert getattr(error.value, "status_code", None) == 409
    current = clients[0].get(url(record)).json()["data"]
    assert current["version"] == 1 and current["seller"] == ""


def legacy_invoice_application(directory, *, null_ledger_column=False):
    """Create the exact old invoice table in a temporary database, without initializing new core."""
    app = FastAPI()
    app.state.data_dir = directory
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "invoices").mkdir()
    saved = []
    with sqlite3.connect(directory / "studio.sqlite3") as db:
        db.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE studio_invoices (id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, data TEXT NOT NULL, sha256 TEXT NOT NULL, stored_filename TEXT NOT NULL, version INTEGER NOT NULL, UNIQUE(owner_id,sha256));
            CREATE INDEX studio_invoices_owner ON studio_invoices(owner_id);
        """)
        stamp = "2026-09-09T12:00:00+00:00"
        for identifier, role in [(1, "admin"), (2, "member")]:
            db.execute("INSERT INTO users(id,username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (?,?,?,?,1,?,?,?,?)", (identifier, f"legacy{identifier}", f"虚构旧用户{identifier}", role, "unused", "unused", stamp, stamp))
        db.execute("INSERT INTO settings VALUES ('organization',?)", (json.dumps({"name":"虚构原工作室"}),))
        for index, status, deleted, version, owner in [(1,"confirmed",None,7,1), (2,"review",stamp,3,2), (3,"processing",None,4,2)]:
            record = {"id": f"legacy-invoice-{index}", "name": f"旧虚构样票{index}.png", "ownerId": owner, "ownerName": f"虚构旧用户{owner}", "invoice_number": f"TEST-LEGACY-{index}", "invoice_date": "2026-09-08", "seller": "虚构旧销售方", "buyer": "虚构旧购买方", "amount": "116.45", "tax_amount": "7.00", "total_amount": "123.45", "category": "办公", "notes": "仅用于迁移验收，不可报销", "status": status, "error": "", "created_at": stamp, "updated_at": stamp, "deleted_at": deleted, "has_file": True, "version": version, "mime_type": "image/png", "file_size": 0, "page_count": 1}
            content = image_bytes({1:"white",2:"green",3:"blue"}[index])
            record["file_size"] = len(content)
            filename = f"legacy-original-{index}.png"
            path = directory / "invoices" / filename
            path.write_bytes(content)
            data = json.dumps(record, ensure_ascii=False)
            digest = hashlib.sha256(content).hexdigest()
            db.execute("INSERT INTO studio_invoices VALUES (?,?,?,?,?,?)", (record["id"], owner, data, digest, filename, version))
            saved.append({"record":record,"raw":data,"content":content,"filename":filename,"digest":digest,"mtime":path.stat().st_mtime_ns})
        if null_ledger_column:
            db.execute("ALTER TABLE studio_invoices ADD COLUMN ledger_id INTEGER")
    return app, saved


def test_legacy_invoice_migration_preserves_records_originals_and_versions(tmp_path):
    app, saved = legacy_invoice_application(tmp_path)
    core.init_db(app)  # Core assigns the original records to a real default ledger first.
    default_id = app.state.default_ledger_id
    assert default_id is not None
    invoices.init_invoices(app)
    app.include_router(invoices.router)
    with core.get_db(app) as db:
        rows = {row["id"]:row for row in db.execute("SELECT * FROM studio_invoices")}
        assert len(rows) == len(saved)
        for entry in saved:
            row = rows[entry["record"]["id"]]
            assert row["ledger_id"] == default_id
            assert row["owner_id"] == entry["record"]["ownerId"]
            assert row["stored_filename"] == entry["filename"] and row["sha256"] == entry["digest"]
            if entry["record"]["status"] != "processing":
                assert row["data"] == entry["raw"] and row["version"] == entry["record"]["version"]
            else:
                recovered = invoices.decode(row)
                assert recovered["status"] == "error" and recovered["version"] == 5 and "重启" in recovered["error"]
        assert next(column for column in db.execute("PRAGMA table_info(studio_invoices)") if column["name"] == "ledger_id")["notnull"] == 1
        unique_columns = []
        for index in db.execute("PRAGMA index_list(studio_invoices)"):
            if index["unique"]:
                unique_columns.append(tuple(row["name"] for row in db.execute('PRAGMA index_info("' + index["name"] + '")')))
        assert ("ledger_id","owner_id","sha256") in unique_columns
        assert ("owner_id","sha256") not in unique_columns
        token = core.new_session(db, 1)
        user = core.public_user(db.execute("SELECT * FROM users WHERE id=1").fetchone())
        other = create_ledger(db, user, "虚构迁移后新账本")
    for entry in saved:
        path = tmp_path / "invoices" / entry["filename"]
        assert path.read_bytes() == entry["content"] and path.stat().st_mtime_ns == entry["mtime"]
    with TestClient(app) as client:
        client.cookies.set("studio_session", token)
        client.headers["X-Ledger-ID"] = str(default_id)
        original = saved[0]
        assert client.get(url(original["record"]) + "/file").content == original["content"]
        assert upload(client, original["content"])["invoice"]["id"] == original["record"]["id"]
        assert client.get("/api/invoices?trash=true").json()["data"]["items"][0]["id"] == saved[1]["record"]["id"]
        client.headers["X-Ledger-ID"] = str(other["id"])
        uploaded = upload(client, original["content"])
        assert not uploaded["duplicate"] and uploaded["invoice"]["ledgerId"] == other["id"]
        assert client.get(url(original["record"]) + "/file").status_code == 404
    with core.get_db(app) as db:
        snapshot = [(row["id"],row["ledger_id"],row["data"],row["version"]) for row in db.execute("SELECT * FROM studio_invoices ORDER BY id")]
    core.init_db(app)
    invoices.init_invoices(app)
    with core.get_db(app) as db:
        assert [(row["id"],row["ledger_id"],row["data"],row["version"]) for row in db.execute("SELECT * FROM studio_invoices ORDER BY id")] == snapshot
    assert len(list((tmp_path / "invoices").iterdir())) == 4


@pytest.mark.parametrize("null_ledger_column", [False, True])
def test_unassigned_legacy_invoices_fail_closed_without_losing_data(tmp_path, null_ledger_column):
    app, saved = legacy_invoice_application(tmp_path, null_ledger_column=null_ledger_column)
    with pytest.raises(RuntimeError, match="迁移"):
        invoices.init_invoices(app)
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM studio_invoices").fetchone()[0] == 3
        assert db.execute("SELECT name FROM sqlite_master WHERE name='studio_invoices_ledger_migration'").fetchone() is None
        assert [row["data"] for row in db.execute("SELECT data FROM studio_invoices ORDER BY id")] == [entry["raw"] for entry in saved]
    assert all((tmp_path / "invoices" / entry["filename"]).read_bytes() == entry["content"] for entry in saved)
    core.init_db(app)
    invoices.init_invoices(app)
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM studio_invoices WHERE ledger_id=?", (app.state.default_ledger_id,)).fetchone()[0] == 3


def test_empty_legacy_invoice_table_can_migrate_before_first_ledger(tmp_path):
    app = FastAPI()
    app.state.data_dir = tmp_path
    core.init_db(app)
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM ledgers").fetchone()[0] == 0
        db.execute("CREATE TABLE studio_invoices(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,data TEXT NOT NULL,sha256 TEXT NOT NULL,stored_filename TEXT NOT NULL,version INTEGER NOT NULL,UNIQUE(owner_id,sha256))")
    invoices.init_invoices(app)
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM studio_invoices").fetchone()[0] == 0
        assert "ledger_id" in {column["name"] for column in db.execute("PRAGMA table_info(studio_invoices)")}
