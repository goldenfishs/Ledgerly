"""Independent Studio API tests, using synthetic records and temporary databases."""
import hashlib
import importlib
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# The ASGI production entry point has a global app. Its import is isolated too.
_import_data = tempfile.TemporaryDirectory(prefix="studio-test-import-")
_previous_data = os.environ.get("STUDIO_DATA_DIR")
os.environ["STUDIO_DATA_DIR"] = _import_data.name
try:
    main = importlib.import_module("backend.main")
    core = importlib.import_module("backend.core")
finally:
    if _previous_data is None:
        os.environ.pop("STUDIO_DATA_DIR", None)
    else:
        os.environ["STUDIO_DATA_DIR"] = _previous_data

SETUP = {"username": "synthetic-admin", "password": "synthetic-password", "name": "Synthetic Admin", "organization": "Synthetic Studio"}


@pytest.fixture
def app(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html><body>Synthetic Studio</body></html>")
    (web / "asset.css").write_text("body { color: black }")
    return main.create_app(tmp_path / "data", web)


@pytest.fixture
def admin(app):
    with TestClient(app) as client:
        response = client.post("/api/auth/setup", json=SETUP)
        assert response.status_code == 200, response.text
        yield client


def data(response, expected=200):
    assert response.status_code == expected, response.text
    body = response.json()
    assert body["code"] == 0 if expected == 200 else body["code"] == expected
    return body.get("data")


def add_account(client, name="Synthetic Account", initial="1000.00", kind=0):
    return data(client.post("/api/account/addAccount", json={"name": name, "initialMoney": initial, "accountType": kind}))


def categories(client):
    return data(client.get("/api/type/getType"))


def payload(client, account, action=0, amount="100.00", **extra):
    category = next(item for item in categories(client) if action in item["actionIds"])
    return {"money": amount, "fDate": "2026-09-09", "actionId": action, "accountId": account["id"], "typeId": category["id"], "collect": False, "note": "Synthetic transaction", **extra}


def add_flow(client, values):
    return data(client.post("/api/flow/addFlow", json=values))


def approve(client, flow):
    return data(client.post(f'/api/flow/reviewFlow/{flow["id"]}', json={"status": "approved", "comment": "Synthetic review", "version": flow["version"]}))


def create_member(admin, app, username="synthetic-member", role="member"):
    user = data(admin.post("/api/users", json={"username": username, "name": username, "password": "synthetic-password", "role": role}))
    client = TestClient(app)
    data(client.post("/api/auth/login", json={"username": username, "password": "synthetic-password"}))
    return user, client


def test_first_setup_has_no_seeded_finances_and_is_once(app):
    with TestClient(app) as client:
        assert data(client.get("/api/session")) == {"needsSetup": True, "user": None, "ledgers": [], "activeLedger": None}
        result = client.post("/api/auth/setup", json=SETUP)
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert "token" not in result.json()["data"]
        assert data(client.get("/api/session"))["user"]["role"] == "admin"
        assert data(client.get("/api/account/getAccount")) == []
        assert data(client.get("/api/flow/getFlowListMain/3/0/2026-09"))["flows"] == []
        data(client.post("/api/auth/setup", json=SETUP), 409)
        with core.get_db(app) as connection:
            user = connection.execute("SELECT * FROM users").fetchone()
            assert user["password_hash"] != SETUP["password"]
            token = client.cookies.get("studio_session")
            stored = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
            assert stored != token and stored == hashlib.sha256(token.encode()).hexdigest()


def test_parallel_setup_creates_only_one_admin(app):
    def attempt(index):
        with TestClient(app) as client:
            return client.post("/api/auth/setup", json={**SETUP, "username": f"synthetic-{index}"}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [1, 2]))
    assert sorted(results) == [200, 409]
    with core.get_db(app) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_login_logout_expiry_and_envelopes(admin, app):
    token = admin.cookies.get("studio_session")
    data(admin.post("/api/auth/logout"))
    data(admin.get("/api/me"), 401)
    assert data(admin.get("/api/session"))["needsSetup"] is False
    data(admin.get("/api/me", headers={"Authorization": token}), 401)
    data(admin.post("/api/auth/login", json={"username": SETUP["username"], "password": "wrong-password"}), 401)
    data(admin.post("/api/auth/login", json={"username": SETUP["username"], "password": SETUP["password"]}))
    with core.get_db(app) as connection:
        connection.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    data(admin.get("/api/me"), 401)
    data(admin.get("/api/no-such-route"), 404)


def test_member_permissions_and_record_isolation(admin, app):
    account = add_account(admin)
    user1, member1 = create_member(admin, app, "synthetic-one")
    user2, member2 = create_member(admin, app, "synthetic-two")
    try:
        flow = add_flow(member1, payload(admin, account))
        assert flow["ownerId"] == user1["id"] and flow["status"] == "pending"
        assert flow["account"]["money"] is None
        data(member2.get(f'/api/flow/getFlow/{flow["id"]}'), 404)
        data(member2.put(f'/api/flow/updateFlow/{flow["id"]}', json=payload(admin, account)), 404)
        data(member2.delete(f'/api/flow/deleteFlow/{flow["id"]}'), 404)
        assert data(member2.get("/api/flow/getFlowListMain/3/0/2026-09"))["flows"] == []
        for path in ("/api/users", "/api/audit"):
            data(member1.get(path), 403)
        data(member1.post("/api/account/addAccount", json={"name": "Forbidden"}), 403)
        data(member1.post("/api/type/addType", json={"tname": "Forbidden"}), 403)
        data(member1.put("/api/settings", json={"organization": "Forbidden"}), 403)
        data(member1.post(f'/api/flow/reviewFlow/{flow["id"]}', json={"status": "approved"}), 403)
        for item in data(member1.get("/api/account/getAccount")):
            assert item["money"] is None and item["initialMoney"] is None and item["card"] == ""
        own = data(member1.get("/api/dashboard?month=2026-09"))
        assert own["assets"] is None and own["pendingCount"] == 1
        assert data(member2.get("/api/dashboard?month=2026-09"))["pendingCount"] == 0
    finally:
        member1.close()
        member2.close()


def test_only_approval_changes_balance_and_totals(admin, app):
    account = add_account(admin)
    member_user, member = create_member(admin, app)
    try:
        flow = add_flow(member, payload(admin, account))
        before = data(admin.get("/api/dashboard?month=2026-09"))
        assert before["income"] == "0.00" and before["assets"] == "1000.00" and before["pendingCount"] == 1
        approved = approve(admin, flow)
        after = data(admin.get("/api/dashboard?month=2026-09"))
        assert after["income"] == "100.00" and after["assets"] == "1100.00" and after["pendingCount"] == 0
        assert data(member.get("/api/dashboard?month=2026-09"))["income"] == "100.00"
        data(member.put(f'/api/flow/updateFlow/{flow["id"]}', json=payload(admin, account, amount="200")), 403)
        data(member.delete(f'/api/flow/deleteFlow/{flow["id"]}'), 403)
        data(member.put(f'/api/flow/collectFlow/{flow["id"]}/1'), 403)
        edited = data(admin.put(f'/api/flow/updateFlow/{flow["id"]}', json=payload(admin, account, amount="250", version=approved["version"])))
        assert edited["status"] == "approved"
        assert data(admin.get("/api/dashboard?month=2026-09"))["assets"] == "1250.00"
        assert any(item["action"] == "edit_approved" for item in data(admin.get("/api/audit")))
        data(admin.delete(f'/api/flow/deleteFlow/{flow["id"]}'))
        assert data(admin.get("/api/dashboard?month=2026-09"))["assets"] == "1000.00"
    finally:
        member.close()


def test_rejection_resubmission_and_optimistic_versions(admin, app):
    account = add_account(admin)
    _, member = create_member(admin, app)
    try:
        flow = add_flow(member, payload(admin, account))
        data(admin.post(f'/api/flow/reviewFlow/{flow["id"]}', json={"status": "rejected", "comment": ""}), 422)
        rejected = data(admin.post(f'/api/flow/reviewFlow/{flow["id"]}', json={"status": "rejected", "comment": "Please correct amount", "version": flow["version"]}))
        assert rejected["status"] == "rejected"
        data(member.put(f'/api/flow/updateFlow/{flow["id"]}', json=payload(admin, account, version=flow["version"])), 409)
        revised = data(member.put(f'/api/flow/updateFlow/{flow["id"]}', json=payload(admin, account, amount="80", version=rejected["version"])))
        assert revised["status"] == "pending" and revised["reviewComment"] == ""
        approve(admin, revised)
        assert data(admin.get("/api/dashboard?month=2026-09"))["income"] == "80.00"
    finally:
        member.close()


def test_transfer_and_liability_balance_semantics(admin):
    bank = add_account(admin, "Synthetic bank", "1000")
    cash = add_account(admin, "Synthetic cash", "0")
    credit = add_account(admin, "Synthetic liability", "200", 1)
    first = add_flow(admin, payload(admin, bank, action=2, amount="100", accountToId=cash["id"]))
    approve(admin, first)
    balances = {item["id"]: item["money"] for item in data(admin.get("/api/account/getAccount"))}
    assert balances[bank["id"]] == "900.00" and balances[cash["id"]] == "100.00"
    second = add_flow(admin, payload(admin, bank, action=2, amount="50", accountToId=credit["id"]))
    approve(admin, second)
    third = add_flow(admin, payload(admin, credit, action=1, amount="25"))
    approve(admin, third)
    balances = {item["id"]: item["money"] for item in data(admin.get("/api/account/getAccount"))}
    assert balances[credit["id"]] == "175.00"
    dashboard = data(admin.get("/api/dashboard?month=2026-09"))
    assert dashboard["income"] == "0.00" and dashboard["expense"] == "25.00" and dashboard["assets"] == "775.00"
    data(admin.post("/api/flow/addFlow", json=payload(admin, bank, action=2, accountToId=bank["id"])), 422)


@pytest.mark.parametrize("bad", [{"money": "0"}, {"money": "-1"}, {"money": "0.001"}, {"money": "NaN"}, {"money": True}, {"fDate": "2026-02-30"}, {"actionId": 9}, {"ownerId": 999}, {"status": "approved"}, {"accountId": 999999}, {"images": ["../../secret"]}])
def test_invalid_amounts_references_and_forged_ownership(admin, bad):
    account = add_account(admin)
    data(admin.post("/api/flow/addFlow", json={**payload(admin, account), **bad}), 422)
    assert data(admin.get("/api/flow/getFlowListMain/3/0/2026-09"))["flows"] == []


def test_decimal_precision_and_database_integer_storage(admin, app):
    account = add_account(admin, initial="0")
    for amount in ("0.10", "0.20"):
        approve(admin, add_flow(admin, payload(admin, account, amount=amount)))
    assert data(admin.get("/api/account/getAccount"))[0]["money"] == "0.30"
    with core.get_db(app) as connection:
        assert [row[0] for row in connection.execute("SELECT cents FROM flows ORDER BY id")] == [10, 20]
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_last_admin_and_immediate_role_disable_password_changes(admin, app):
    admin_id = data(admin.get("/api/me"))["id"]
    data(admin.put(f"/api/users/{admin_id}", json={"enabled": False}), 409)
    data(admin.put(f"/api/users/{admin_id}", json={"role": "member"}), 409)
    user, promoted = create_member(admin, app)
    try:
        data(promoted.get("/api/users"), 403)
        data(admin.put(f'/api/users/{user["id"]}', json={"role": "admin"}))
        data(promoted.get("/api/users"))
        data(admin.put(f'/api/users/{user["id"]}', json={"role": "member"}))
        data(promoted.get("/api/users"), 403)
        data(admin.put(f'/api/users/{user["id"]}', json={"password": "new-synthetic-password"}), 403)
        data(promoted.post("/api/profile/password", json={"currentPassword": "synthetic-password", "newPassword": "new-synthetic-password"}))
        data(promoted.get("/api/me"))  # Password change renews this session only.
        data(promoted.post("/api/auth/login", json={"username": user["username"], "password": "synthetic-password"}), 401)
        data(promoted.post("/api/auth/login", json={"username": user["username"], "password": "new-synthetic-password"}))
        data(admin.put(f'/api/users/{user["id"]}', json={"enabled": False}))
        data(promoted.get("/api/me"))  # Ledger suspension is not global logout.
        assert data(promoted.get("/api/ledgers")) == []
        data(promoted.get("/api/account/getAccount"), 403)
    finally:
        promoted.close()
    audit = json.dumps(data(admin.get("/api/audit")))
    assert "synthetic-password" not in audit and "password_hash" not in audit


def test_archive_categories_and_accounts_preserves_history(admin):
    account = add_account(admin)
    flow = add_flow(admin, payload(admin, account))
    parent = data(admin.post("/api/type/addType", json={"tname": "Synthetic parent", "actionIds": [1]}))
    child = data(admin.post("/api/type/addType", json={"tname": "Synthetic child", "parent": parent["id"], "actionIds": [1]}))
    data(admin.put(f'/api/type/updateType/{parent["id"]}', json={"parent": child["id"]}), 422)
    data(admin.delete(f'/api/type/deleteType/{parent["id"]}'))
    assert not any(item["id"] == parent["id"] for item in categories(admin))
    archived = next(item for item in data(admin.get("/api/type/getType/noLimit")) if item["id"] == parent["id"])
    assert archived["enable"] is False and archived["child"][0]["enable"] is False
    data(admin.delete(f'/api/account/deleteAccount/{account["id"]}'))
    data(admin.get(f'/api/flow/getFlow/{flow["id"]}'))
    data(admin.post("/api/flow/addFlow", json=payload(admin, account)), 422)


def test_filters_and_member_owner_query_forbidden(admin, app):
    account = add_account(admin)
    first = add_flow(admin, payload(admin, account, note="Synthetic 100% marked", collect=True))
    second = add_flow(admin, payload(admin, account, note="Synthetic other", fDate="2026-08-01"))
    assert len(data(admin.get("/api/flow/getFlowListMain/3/1/2026-09"))["flows"]) == 1
    filtered = data(admin.post("/api/screen/getFlowByScreen", json={"note": "%", "chooseHandle": 3}))
    assert [row["id"] for row in filtered["flows"]] == [first["id"]]
    filtered = data(admin.post("/api/screen/getFlowByScreen", json={"startDate": "2026-08", "singleMonth": True, "chooseHandle": 0}))
    assert [row["id"] for row in filtered["flows"]] == [second["id"]]
    user, member = create_member(admin, app)
    try:
        data(member.post("/api/screen/getFlowByScreen", json={"ownerId": 1}), 403)
    finally:
        member.close()


def test_settings_static_routes_and_data_isolation(admin, app, tmp_path):
    assert data(admin.get("/api/settings"))["organization"] == "Synthetic Studio"
    data(admin.put("/api/settings", json={"organization": "Renamed Synthetic Studio"}))
    assert data(admin.get("/api/settings"))["name"] == "Renamed Synthetic Studio"
    data(admin.put("/api/settings", json={"apiKey": "forbidden"}), 422)
    assert admin.get("/dashboard").status_code == 200
    assert admin.get("/asset.css").headers["content-type"].startswith("text/css")
    assert admin.get("/%2e%2e/data/studio.sqlite3").status_code == 404
    other = main.create_app(tmp_path / "other-data", tmp_path / "other-web")
    with TestClient(other) as second:
        assert data(second.get("/api/session"))["needsSetup"] is True
        data(second.get("/api/account/getAccount"), 401)


@pytest.mark.parametrize('criteria', [{'startDate': 42, 'singleMonth': True}, {'singleMonth': 'yes'}, {'collect': 1}, {'startDate': '2026-09-30', 'endDate': '2026-09-01'}, {'startDate': '2026-09-bad', 'singleMonth': True}])
def test_search_validation(admin, criteria):
    data(admin.post('/api/screen/getFlowByScreen', json=criteria), 422)


def test_organization_disclosure_requires_authenticated_session(admin, app):
    assert data(admin.get('/api/session'))['organization']['name'] == 'Synthetic Studio'
    with TestClient(app) as anonymous:
        assert 'organization' not in data(anonymous.get('/api/session'))


def test_balance_aggregation_can_exceed_single_transaction_limit(admin):
    account = add_account(admin, initial='999999999999.99')
    approve(admin, add_flow(admin, payload(admin, account, amount='1.00')))
    assert data(admin.get('/api/dashboard?month=2026-09'))['assets'] == '1000000000000.99'


@pytest.mark.parametrize('headers', [
    {'Origin': 'http://attacker.invalid'},
    {'Origin': 'http://testserver:7777', 'Sec-Fetch-Site': 'same-site'},
    {'Origin': 'null'},
    {'Origin': 'http://user@testserver'},
    {'Sec-Fetch-Site': 'cross-site'},
    {'Sec-Fetch-Site': 'same-site'},
])
def test_browser_cross_origin_writes_rejected(admin, headers):
    data(admin.put('/api/settings', json={'name': 'Forged change'}, headers=headers), 403)
    data(admin.post('/api/auth/logout', headers=headers), 403)
    data(admin.post('/api/invoices', files={'file': ('synthetic.png', b'not-an-image')}, headers=headers), 403)
    assert data(admin.get('/api/settings'))['name'] == 'Synthetic Studio'


def test_same_origin_browser_and_opaque_script_sessions_work(admin):
    headers = {'Origin': 'http://testserver', 'Sec-Fetch-Site': 'same-origin'}
    data(admin.put('/api/settings', json={'name': 'Legitimate change'}, headers=headers))
    data(admin.put('/api/settings', json={'name': 'Script change'}))


def test_competing_edit_and_approval_cannot_silently_overwrite(admin, app):
    account = add_account(admin)
    flow = add_flow(admin, payload(admin, account, amount='100'))
    cookie = admin.cookies.get('studio_session')
    values = payload(admin, account, amount='200', version=flow['version'])
    def attempt(mode):
        with TestClient(app) as client:
            client.cookies.set('studio_session', cookie)
            if mode == 'review':
                return client.post(f'/api/flow/reviewFlow/{flow["id"]}', json={'status':'approved','comment':'Reviewed original amount','version':flow['version']}).status_code
            return client.put(f'/api/flow/updateFlow/{flow["id"]}', json=values).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ['review', 'edit']))
    assert sorted(results) == [200, 409]
    result = data(admin.get(f'/api/flow/getFlow/{flow["id"]}'))
    assert (result['status'],result['money']) in [('approved','100.00'),('pending','200.00')]
    assert data(admin.get('/api/dashboard?month=2026-09'))['income'] in ['100.00','0.00']


def test_dashboard_pending_matches_selected_month(admin):
    account = add_account(admin)
    add_flow(admin, payload(admin, account, fDate='2026-08-31'))
    add_flow(admin, payload(admin, account, fDate='2026-09-01'))
    dashboard = data(admin.get('/api/dashboard?month=2026-09'))
    assert dashboard['pendingCount'] == 1 and dashboard['allPendingCount'] == 2


def test_llm_path_comes_only_from_server_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIO_LLM_CONFIG_PATH', '/synthetic/config/llm_config.ini')
    created = main.create_app(tmp_path / 'configured-data')
    assert created.state.llm_config_path == '/synthetic/config/llm_config.ini'


def test_login_password_attempts_are_rate_limited(admin, app):
    with TestClient(app) as visitor:
        for _ in range(10):
            data(visitor.post('/api/auth/login', json={'username': SETUP['username'], 'password': 'wrong-synthetic-password'}), 401)
        limited = visitor.post('/api/auth/login', json={'username': SETUP['username'], 'password': 'wrong-synthetic-password'})
        data(limited, 429)
        assert limited.headers['retry-after'] == '60'
