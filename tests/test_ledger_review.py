"""Independent security review: disposable data, real sessions, no production services."""
import importlib
import json
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

_import_data = tempfile.TemporaryDirectory(prefix="studio-ledger-review-import-")
_previous_data = os.environ.get("STUDIO_DATA_DIR")
os.environ["STUDIO_DATA_DIR"] = _import_data.name
try:
    main = importlib.import_module("backend.main")
    core = importlib.import_module("backend.core")
    ledgers = importlib.import_module("backend.ledgers")
finally:
    if _previous_data is None:
        os.environ.pop("STUDIO_DATA_DIR", None)
    else:
        os.environ["STUDIO_DATA_DIR"] = _previous_data


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json().get("data")


@pytest.fixture
def review_app(tmp_path):
    app = main.create_app(tmp_path / "data", tmp_path / "web")
    tokens = {}
    with core.get_db(app) as db:
        for identifier, role in [(1,"admin"),(2,"member"),(3,"member"),(4,"member"),(5,"admin")]:
            db.execute("INSERT INTO users(id,username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (?,?,?,?,1,?,?,?,?)", (identifier,f"review-user-{identifier}",f"虚构用户{identifier}",role,"unused","unused",core.utcnow(),core.utcnow()))
            tokens[identifier] = core.new_session(db, identifier)
        a = ledgers.create_ledger(db, core.public_user(db.execute("SELECT * FROM users WHERE id=1").fetchone()), "虚构私有账本甲")
        b = ledgers.create_ledger(db, core.public_user(db.execute("SELECT * FROM users WHERE id=5").fetchone()), "虚构私有账本乙")
        assert a["id"] == 1 and b["id"] == 2
        for book, user, role in [(1,2,"admin"),(1,3,"member"),(2,2,"admin"),(2,3,"member"),(2,4,"member")]:
            db.execute("INSERT INTO ledger_members VALUES (?,?,?,1,?)", (book,user,role,core.utcnow()))
        db.execute("INSERT INTO settings VALUES ('organization',?)", (json.dumps({"name":"虚构私有账本甲"}),))
    app.state.review_tokens = tokens
    return app


@pytest.fixture
def people(review_app):
    clients = {}
    for identifier in range(1,6):
        client = TestClient(review_app)
        client.cookies.set("studio_session", review_app.state.review_tokens[identifier])
        client.headers["X-Ledger-ID"] = "1" if identifier <= 3 else "2"
        clients[identifier] = client
    yield clients
    for client in clients.values():
        client.close()


def invite(client, book=1, role="admin"):
    return data(client.post(f"/api/ledgers/{book}/invitations", json={"role":role,"expiresInDays":1}))


def register_payload(suffix):
    return {"username":f"review-new-{suffix}","name":"虚构新成员","password":"synthetic-password-123"}


def add_account(client, name):
    return data(client.post("/api/account/addAccount",json={"name":name,"initialMoney":"0","accountType":0}))


def flow_payload(client, account, action=1, **extra):
    category = next(item for item in data(client.get("/api/type/getType")) if action in item["actionIds"])
    return {"money":"123.45","fDate":"2026-09-09","actionId":action,"accountId":account["id"],"typeId":category["id"],"note":"虚构审查流水","collect":False,**extra}


def test_cross_ledger_lists_single_records_and_references_are_isolated(people):
    a, b = people[1], people[5]
    account_a = add_account(a,"虚构甲账户")
    account_b = add_account(b,"虚构乙账户")
    values_a, values_b = flow_payload(a,account_a), flow_payload(b,account_b)
    flow_a = data(a.post("/api/flow/addFlow",json=values_a))
    flow_b = data(b.post("/api/flow/addFlow",json=values_b))
    assert [row["id"] for row in data(a.get("/api/account/getAccount"))] == [account_a["id"]]
    assert [row["id"] for row in data(a.get("/api/flow/getFlowListMain/3/0/2026-09"))["flows"]] == [flow_a["id"]]
    assert all(row["typeId"] != flow_b["typeId"] for row in data(a.get("/api/dashboard?month=2026-09"))["recent"])
    assert data(a.post("/api/screen/getFlowByScreen",json={"ownerId":5,"accountId":account_b["id"],"types":[flow_b["typeId"]]}))["flows"] == []
    attempts = [
        ("GET",f'/api/account/getAccount/{account_b["id"]}',None),
        ("PUT",f'/api/account/updateAccount/{account_b["id"]}',{"name":"changed"}),
        ("DELETE",f'/api/account/deleteAccount/{account_b["id"]}',None),
        ("PUT",f'/api/type/updateType/{flow_b["typeId"]}',{"tname":"changed"}),
        ("DELETE",f'/api/type/deleteType/{flow_b["typeId"]}',None),
        ("GET",f'/api/flow/getFlow/{flow_b["id"]}',None),
        ("PUT",f'/api/flow/updateFlow/{flow_b["id"]}',{**values_a,"version":1}),
        ("DELETE",f'/api/flow/deleteFlow/{flow_b["id"]}?version=1',None),
        ("PUT",f'/api/flow/collectFlow/{flow_b["id"]}/1',None),
        ("POST",f'/api/flow/reviewFlow/{flow_b["id"]}',{"status":"approved","version":1}),
    ]
    for method,path,body in attempts:
        data(a.request(method,path,**({"json":body} if body is not None else {})),404)
    for fields in [{"accountId":account_b["id"]},{"typeId":flow_b["typeId"]},{"actionId":2,"accountToId":account_b["id"],"typeId":next(item["id"] for item in data(a.get("/api/type/getType")) if 2 in item["actionIds"])}]:
        data(a.post("/api/flow/addFlow",json={**values_a,**fields}),422)
        data(a.put(f'/api/flow/updateFlow/{flow_a["id"]}',json={**values_a,**fields,"version":1}),422)
    data(a.post("/api/type/addType",json={"tname":"invalid parent","parent":flow_b["typeId"],"actionIds":[1]}),422)
    data(a.put(f'/api/type/updateType/{flow_a["typeId"]}',json={"parent":flow_b["typeId"]}),422)
    assert data(b.get(f'/api/flow/getFlow/{flow_b["id"]}'))["version"] == 1
    assert data(b.get(f'/api/account/getAccount/{account_b["id"]}'))["enable"] is True
    assert len(data(a.get("/api/flow/getFlowListMain/3/0/2026-09"))["flows"]) == 1


def test_global_admin_cannot_manage_unjoined_ledger(people):
    a = people[1]
    assert [record["id"] for record in data(a.get("/api/ledgers"))] == [1]
    for method,path,body in [
        ("PUT","/api/ledgers/2",{"name":"forbidden"}),
        ("GET","/api/ledgers/2/members",None),
        ("PUT","/api/ledgers/2/members/4",{"role":"admin"}),
        ("DELETE","/api/ledgers/2/members/4",None),
        ("GET","/api/ledgers/2/invitations",None),
        ("POST","/api/ledgers/2/invitations",{"role":"admin"}),
    ]:
        data(a.request(method,path,**({"json":body} if body else {})),403)
    a.headers["X-Ledger-ID"] = "2"
    for path in ["/api/users","/api/account/getAccount","/api/type/getType","/api/audit","/api/settings","/api/dashboard"]:
        data(a.get(path),403)


def test_shared_user_profile_and_membership_changes_do_not_cross_ledgers(review_app, people):
    admin, book_admin, shared = people[1],people[2],people[3]
    for client in [admin,book_admin]:
        data(client.put("/api/users/3",json={"name":"hijacked profile"}),403)
        data(client.put("/api/users/3",json={"password":"hijacked-password"}),403)
        data(client.put("/api/users/4",json={"name":"outsider"}),404)
    data(admin.put("/api/users/3",json={"enabled":False,"role":"admin"}))
    data(shared.get("/api/account/getAccount"),403)
    shared.headers["X-Ledger-ID"] = "2"
    data(shared.get("/api/account/getAccount"))
    with core.get_db(review_app) as db:
        user = db.execute("SELECT * FROM users WHERE id=3").fetchone()
        other = db.execute("SELECT * FROM ledger_members WHERE ledger_id=2 AND user_id=3").fetchone()
        assert user["name"] == "虚构用户3" and user["password_hash"] == "unused" and user["enabled"] == 1
        assert other["role"] == "member" and other["enabled"] == 1


@pytest.mark.parametrize("change",["remove","demote","disable"])
def test_removed_or_demoted_inviter_cannot_reenter_using_old_admin_invitation(review_app, people, change):
    token = invite(people[2])["token"]
    if change == "remove":
        data(people[1].delete("/api/ledgers/1/members/2"))
    elif change == "demote":
        data(people[1].put("/api/ledgers/1/members/2",json={"role":"member"}))
    else:
        data(people[1].put("/api/users/2",json={"enabled":False}))
    response = people[2].post(f"/api/invitations/{token}/accept")
    assert response.status_code in (403,410), response.text
    with TestClient(review_app) as newcomer:
        response = newcomer.post(f"/api/invitations/{token}/register",json=register_payload(change))
        assert response.status_code in (403,410), response.text
    with core.get_db(review_app) as db:
        membership = db.execute("SELECT * FROM ledger_members WHERE ledger_id=1 AND user_id=2").fetchone()
        assert not membership or membership["role"] != "admin" or not membership["enabled"]
        assert db.execute("SELECT COUNT(*) FROM users WHERE username=?",(register_payload(change)["username"],)).fetchone()[0] == 0
        assert db.execute("SELECT revoked_at FROM ledger_invitations").fetchone()[0] is not None


@pytest.mark.parametrize("change_sql",[
    "UPDATE ledger_members SET role='member' WHERE ledger_id=1 AND user_id=2",
    "UPDATE ledger_members SET enabled=0 WHERE ledger_id=1 AND user_id=2",
    "UPDATE users SET enabled=0 WHERE id=2",
])
def test_invitation_consumption_rechecks_inviter_permission_even_without_revocation(review_app, people, change_sql):
    token = invite(people[2])["token"]
    with core.get_db(review_app) as db:
        db.execute(change_sql)
    response = people[4].post(f"/api/invitations/{token}/accept")
    assert response.status_code in (403,410), response.text
    with TestClient(review_app) as newcomer:
        response = newcomer.post(f"/api/invitations/{token}/register",json=register_payload("recheck"))
        assert response.status_code in (403,410), response.text
    with core.get_db(review_app) as db:
        assert db.execute("SELECT 1 FROM ledger_members WHERE ledger_id=1 AND user_id=4").fetchone() is None
        assert db.execute("SELECT 1 FROM users WHERE username='review-new-recheck'").fetchone() is None


@pytest.mark.parametrize("state",["expired","revoked","accepted"])
def test_unusable_invites_reject_accept_and_registration_without_side_effects(review_app, people, state):
    invitation = invite(people[1])
    if state == "expired":
        with core.get_db(review_app) as db:
            db.execute("UPDATE ledger_invitations SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(invitation["id"],))
    elif state == "revoked":
        data(people[1].delete(f'/api/ledgers/1/invitations/{invitation["id"]}'))
    else:
        data(people[4].post(f'/api/invitations/{invitation["token"]}/accept'))
    with core.get_db(review_app) as db:
        before = (db.execute("SELECT COUNT(*) FROM users").fetchone()[0],db.execute("SELECT COUNT(*) FROM ledger_members").fetchone()[0])
    data(people[5].post(f'/api/invitations/{invitation["token"]}/accept'),410)
    with TestClient(review_app) as client:
        data(client.post(f'/api/invitations/{invitation["token"]}/register',json=register_payload(state)),410)
    with core.get_db(review_app) as db:
        after = (db.execute("SELECT COUNT(*) FROM users").fetchone()[0],db.execute("SELECT COUNT(*) FROM ledger_members").fetchone()[0])
    assert before == after


def test_invitation_is_single_use_under_concurrent_acceptance(review_app, people):
    token = invite(people[1])["token"]
    barrier = Barrier(2)
    def accept(user_id):
        with TestClient(review_app) as client:
            client.cookies.set("studio_session",review_app.state.review_tokens[user_id])
            barrier.wait(timeout=5)
            return client.post(f"/api/invitations/{token}/accept").status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(accept,[4,5]))
    assert sorted(results) == [200,410]
    with core.get_db(review_app) as db:
        assert db.execute("SELECT COUNT(*) FROM ledger_members WHERE ledger_id=1 AND user_id IN (4,5)").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ledger_invitations WHERE accepted_at IS NOT NULL").fetchone()[0] == 1


def test_invitation_is_single_use_under_concurrent_registration(review_app, people):
    token = invite(people[1],role="member")["token"]
    barrier = Barrier(2)
    def register(index):
        with TestClient(review_app) as client:
            barrier.wait(timeout=5)
            return client.post(f"/api/invitations/{token}/register",json=register_payload(f"parallel-{index}")).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register,[1,2]))
    assert sorted(results) == [200,410]
    with core.get_db(review_app) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username LIKE 'review-new-parallel-%'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ledger_members WHERE ledger_id=1 AND user_id>5").fetchone()[0] == 1


def test_concurrent_admin_removals_preserve_an_enabled_ledger_admin(review_app):
    barrier = Barrier(2)
    def remove(actor,target):
        with TestClient(review_app) as client:
            client.cookies.set("studio_session",review_app.state.review_tokens[actor])
            barrier.wait(timeout=5)
            return client.delete(f"/api/ledgers/1/members/{target}").status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [executor.submit(remove,1,2),executor.submit(remove,2,1)]
        results = [task.result() for task in tasks]
    assert sorted(results) == [200,403]
    with core.get_db(review_app) as db:
        assert db.execute("SELECT COUNT(*) FROM ledger_members WHERE ledger_id=1 AND role='admin' AND enabled=1").fetchone()[0] == 1


def test_session_does_not_expose_legacy_default_book_to_other_members(people):
    result = data(people[4].get("/api/session"))  # This person only belongs to ledger two.
    assert [ledger["id"] for ledger in result["ledgers"]] == [2]
    assert result["activeLedger"]["id"] == 2
    assert "虚构私有账本甲" not in json.dumps(result,ensure_ascii=False)


def test_accept_racing_registration_consumes_once_without_orphan_account(review_app, people):
    token = invite(people[1],role="member")["token"]
    barrier = Barrier(2)
    def act(register):
        with TestClient(review_app) as client:
            if not register:
                client.cookies.set("studio_session",review_app.state.review_tokens[4])
            barrier.wait(timeout=5)
            return client.post(f'/api/invitations/{token}/{"register" if register else "accept"}',**({"json":register_payload("mixed")} if register else {})).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(act,[False,True]))
    assert sorted(statuses) == [200,410]
    with core.get_db(review_app) as db:
        accepted_by = db.execute("SELECT accepted_by FROM ledger_invitations").fetchone()[0]
        created = db.execute("SELECT id FROM users WHERE username='review-new-mixed'").fetchone()
        assert bool(created) == (statuses[1] == 200)
        assert accepted_by == (created[0] if created else 4)
        assert db.execute("SELECT COUNT(*) FROM ledger_members WHERE ledger_id=1 AND user_id IN (4,6)").fetchone()[0] == 1


def test_parallel_registration_with_same_username_does_not_consume_losing_invite(review_app, people):
    tokens = [invite(people[1],role="member")["token"] for _ in range(2)]
    barrier = Barrier(2)
    def register(token):
        with TestClient(review_app) as client:
            barrier.wait(timeout=5)
            return client.post(f"/api/invitations/{token}/register",json=register_payload("same-name")).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register,tokens))
    assert sorted(results) == [200,409]
    with core.get_db(review_app) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username='review-new-same-name'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ledger_invitations WHERE accepted_at IS NULL").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ledger_members WHERE ledger_id=1 AND user_id>5").fetchone()[0] == 1


@pytest.mark.parametrize("register",[False,True])
def test_invitation_consumption_rolls_back_all_writes_if_audit_fails(review_app, people, monkeypatch, register):
    token = invite(people[1],role="member")["token"]
    original_audit = ledgers.write_audit
    def fail_audit(*args,**kwargs):
        raise RuntimeError("synthetic storage failure")
    monkeypatch.setattr(ledgers,"write_audit",fail_audit)
    with TestClient(review_app,raise_server_exceptions=False) as client:
        if not register:
            client.cookies.set("studio_session",review_app.state.review_tokens[4])
        response = client.post(f'/api/invitations/{token}/{"register" if register else "accept"}',**({"json":register_payload("rollback")} if register else {}))
        assert response.status_code == 500
    with core.get_db(review_app) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 5
        assert db.execute("SELECT 1 FROM ledger_members WHERE ledger_id=1 AND user_id=4").fetchone() is None
        assert db.execute("SELECT accepted_at FROM ledger_invitations").fetchone()[0] is None
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 5
    monkeypatch.setattr(ledgers,"write_audit",original_audit)
    data(people[4].post(f"/api/invitations/{token}/accept"))


def test_legacy_migration_failure_rolls_back_scoping_without_altering_original_rows(tmp_path,monkeypatch):
    directory = tmp_path / "legacy"
    directory.mkdir()
    with sqlite3.connect(directory / "studio.sqlite3") as db:
        db.executescript("""
            CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE,name TEXT NOT NULL,role TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,password_hash TEXT NOT NULL,password_salt TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,initial_cents INTEGER NOT NULL DEFAULT 0,account_type INTEGER NOT NULL DEFAULT 0,card TEXT NOT NULL DEFAULT '',enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        """)
        db.execute("INSERT INTO users VALUES (41,'legacy-review','虚构原管理员','admin',1,'unchanged-hash','unchanged-salt','2026-01-01','2026-01-01')")
        db.execute("INSERT INTO accounts VALUES (27,'虚构原账户',12345,0,'',1,'2026-01-01','2026-01-01')")
        db.execute("INSERT INTO settings VALUES ('organization',?)",(json.dumps({"name":"虚构原账本"}),))
    class App:
        pass
    app = App()
    app.state = App()
    app.state.data_dir = directory
    original_utcnow = ledgers.utcnow
    def fail_timestamp():
        raise RuntimeError("synthetic migration interruption")
    monkeypatch.setattr(ledgers,"utcnow",fail_timestamp)
    with pytest.raises(RuntimeError,match="synthetic migration interruption"):
        core.init_db(app)
    with core.get_db(app) as db:
        assert "ledger_id" not in {column["name"] for column in db.execute("PRAGMA table_info(accounts)")}
        assert db.execute("SELECT name FROM sqlite_master WHERE name='ledgers'").fetchone() is None
        assert db.execute("SELECT id,initial_cents FROM accounts").fetchone()[:] == (27,12345)
        assert db.execute("SELECT password_hash FROM users WHERE id=41").fetchone()[0] == "unchanged-hash"
    monkeypatch.setattr(ledgers,"utcnow",original_utcnow)
    core.init_db(app)
    with core.get_db(app) as db:
        snapshot = {table:[tuple(row) for row in db.execute(f"SELECT * FROM {table}")] for table in ["users","accounts","ledger_members","ledgers"]}
        assert snapshot["accounts"][0][0] == 27 and snapshot["accounts"][0][-1] == app.state.default_ledger_id
    core.init_db(app)
    with core.get_db(app) as db:
        assert {table:[tuple(row) for row in db.execute(f"SELECT * FROM {table}")] for table in snapshot} == snapshot
