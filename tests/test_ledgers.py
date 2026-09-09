"""Multi-ledger permissions, invitations and id-preserving migration tests."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from test_app import app, admin, data, add_account, add_flow, payload, approve, create_member, SETUP
from backend import core, main, ledgers


def current_book(client):
    return data(client.get('/api/session'))['activeLedger']


def make_book(admin, name='Synthetic second ledger'):
    return data(admin.post('/api/ledgers', json={'name':name,'description':'Synthetic ledger isolation test','color':'#7892b2'}))


def select(client, ledger):
    client.headers['X-Ledger-ID'] = str(ledger['id'])


def invite(admin, book, role='member'):
    return data(admin.post(f'/api/ledgers/{book["id"]}/invitations', json={'role':role,'expiresInDays':7}))


def join(client, invitation):
    return data(client.post(f'/api/invitations/{invitation["token"]}/accept'))


def test_full_financial_isolation_and_cross_book_references(admin):
    first = current_book(admin)
    one_account = add_account(admin, 'Only First', '1000')
    one_flow = approve(admin, add_flow(admin, payload(admin, one_account, amount='12.34')))
    one_type = one_flow['typeId']
    second = make_book(admin)
    select(admin, second)
    assert data(admin.get('/api/account/getAccount')) == []
    assert data(admin.get('/api/flow/getFlowListMain/3/0/2026-09'))['flows'] == []
    dashboard = data(admin.get('/api/dashboard?month=2026-09'))
    assert dashboard['assets'] == '0.00' and dashboard['income'] == '0.00'
    assert not any(entry['entityType']=='flow' for entry in data(admin.get('/api/audit')))
    two_account = add_account(admin, 'Only Second', '500')
    two_flow = add_flow(admin, payload(admin, two_account, action=1, amount='5'))
    attempted = [
        ('GET', f'/api/account/getAccount/{one_account["id"]}', {}),
        ('PUT', f'/api/account/updateAccount/{one_account["id"]}', {'json':{'name':'intruder'}}),
        ('DELETE', f'/api/account/deleteAccount/{one_account["id"]}', {}),
        ('GET', f'/api/flow/getFlow/{one_flow["id"]}', {}),
        ('PUT', f'/api/flow/updateFlow/{one_flow["id"]}', {'json':payload(admin,two_account)}),
        ('DELETE', f'/api/flow/deleteFlow/{one_flow["id"]}', {}),
        ('PUT', f'/api/flow/collectFlow/{one_flow["id"]}/1', {}),
        ('POST', f'/api/flow/reviewFlow/{one_flow["id"]}', {'json':{'status':'rejected','comment':'intruder'}}),
        ('PUT', f'/api/type/updateType/{one_type}', {'json':{'tname':'intruder'}}),
        ('DELETE', f'/api/type/deleteType/{one_type}', {}),
    ]
    for method,path,kwargs in attempted:
        data(admin.request(method,path,**kwargs),404)
    data(admin.post('/api/flow/addFlow',json=payload(admin,one_account)),422)
    data(admin.post('/api/flow/addFlow',json=payload(admin,two_account,typeId=one_type)),422)
    data(admin.post('/api/flow/addFlow',json=payload(admin,two_account,action=2,accountToId=one_account['id'])),422)
    data(admin.post('/api/type/addType',json={'tname':'intruder','parent':one_type,'actionIds':[0]}),422)
    data(admin.put('/api/settings',json={'name':'Renamed Second'}))
    assert data(admin.get('/api/settings'))['name']=='Renamed Second'
    assert data(admin.get('/api/session'))['organization']['name']=='Renamed Second'
    select(admin,first)
    assert data(admin.get('/api/settings'))['name']==first['name']
    assert data(admin.get('/api/session'))['organization']['name']==SETUP['organization']
    assert data(admin.get('/api/account/getAccount'))[0]['money']=='1012.34'
    assert [r['id'] for r in data(admin.get('/api/flow/getFlowListMain/3/0/2026-09'))['flows']]==[one_flow['id']]


def test_effective_roles_platform_privileges_and_no_implicit_access(admin,app):
    first=current_book(admin)
    user,member=create_member(admin,app)
    second=make_book(admin)
    try:
        joined=join(member,invite(admin,second,'admin'))
        assert joined['user']['role']=='admin' and joined['user']['globalRole']=='member'
        select(member,second)
        assert current_book(member)['role']=='admin'
        add_account(member,'Local admin account')
        data(member.post('/api/ledgers',json={'name':'Not a platform admin'}),403)
        select(member,first)
        data(member.post('/api/account/addAccount',json={'name':'No privilege here'}),403)
        data(member.get(f'/api/ledgers/{first["id"]}/members'),403)
        select(admin,second)
        self_id=data(admin.get('/api/me'))['id']
        data(admin.delete(f'/api/ledgers/{second["id"]}/members/{self_id}'))
        assert second['id'] not in [book['id'] for book in data(admin.get('/api/ledgers'))]
        data(admin.get('/api/account/getAccount'),403)
        data(admin.get(f'/api/ledgers/{second["id"]}/members'),403)
        data(admin.get(f'/api/ledgers/{second["id"]}/invitations'),403)
        data(admin.put(f'/api/ledgers/{second["id"]}',json={'name':'Platform bypass'}),403)
        make_book(admin,'Platform admin can still create')
    finally:member.close()


def test_member_removal_and_legacy_users_scope(admin,app):
    first=current_book(admin)
    user,member=create_member(admin,app)
    second=make_book(admin)
    try:
        join(member,invite(admin,second))
        select(admin,second)
        assert {u['id'] for u in data(admin.get('/api/users'))}=={1,user['id']}
        data(admin.put(f'/api/users/{user["id"]}',json={'password':'cross-ledger-hijack'}),403)
        data(admin.put(f'/api/users/{user["id"]}',json={'name':'Cross-ledger rename'}),403)
        data(admin.put(f'/api/users/{user["id"]}',json={'enabled':False}))
        select(member,second)
        data(member.get('/api/account/getAccount'),403)
        select(member,first)
        data(member.get('/api/account/getAccount'))
        data(member.get('/api/me'))
        data(admin.delete(f'/api/ledgers/{second["id"]}/members/{user["id"]}'))
        data(admin.put(f'/api/users/{user["id"]}',json={'role':'admin'}),404)
        assert user['id'] not in [u['id'] for u in data(admin.get('/api/users'))]
        data(admin.delete(f'/api/ledgers/{second["id"]}/members/1'),409)
        data(admin.put(f'/api/ledgers/{second["id"]}/members/1',json={'role':'member'}),409)
        data(admin.put('/api/users/1',json={'enabled':False}),409)
    finally:member.close()


def test_non_member_can_login_join_and_see_only_public_invitation(admin,app):
    book=current_book(admin)
    user,member=create_member(admin,app)
    invitation=invite(admin,book)
    try:
        data(admin.delete(f'/api/ledgers/{book["id"]}/members/{user["id"]}'))
        assert data(member.get('/api/ledgers'))==[]
        session=data(member.get('/api/session'))
        assert session['user'] and session['activeLedger'] is None
        assert session['organization']['name']=='我的工作室'
        data(member.get('/api/account/getAccount'),403)
        data(member.post('/api/auth/logout'))
        data(member.post('/api/auth/login',json={'username':user['username'],'password':'synthetic-password'}))
        with TestClient(app) as anonymous:
            public=data(anonymous.get(f'/api/invitations/{invitation["token"]}'))
            assert set(public)=={'ledgerName','inviterName','role','expiresAt','status'}
            assert public['status']=='pending'
            data(anonymous.post(f'/api/invitations/{invitation["token"]}/accept'),401)
        joined=join(member,invitation)
        assert joined['ledgerId']==book['id']
        data(member.get('/api/account/getAccount'))
        data(member.post(f'/api/invitations/{invitation["token"]}/accept'),410)
    finally:member.close()


def test_invitation_register_hash_only_revoke_expiry_and_replay(admin,app):
    book=current_book(admin)
    fresh=invite(admin,book,'admin')
    with core.get_db(app) as db:
        stored=db.execute('SELECT token_hash FROM ledger_invitations WHERE id=?',(fresh['id'],)).fetchone()[0]
        assert stored==hashlib.sha256(fresh['token'].encode()).hexdigest() and stored!=fresh['token']
    assert 'token' not in data(admin.get(f'/api/ledgers/{book["id"]}/invitations'))[0]
    assert fresh['token'] not in json.dumps(data(admin.get('/api/audit')))
    with TestClient(app) as invitee:
        registered=data(invitee.post(f'/api/invitations/{fresh["token"]}/register',json={'username':'new-invited','name':'Invited','password':'synthetic-password'}))
        assert registered['user']['role']=='admin' and registered['user']['globalRole']=='member'
        assert data(invitee.get('/api/session'))['activeLedger']['id']==book['id']
        assert data(invitee.get(f'/api/invitations/{fresh["token"]}'))['status']=='accepted'
        data(invitee.post(f'/api/invitations/{fresh["token"]}/register',json={'username':'second-invited','name':'Other','password':'synthetic-password'}),410)
    revoked=invite(admin,book)
    data(admin.delete(f'/api/ledgers/{book["id"]}/invitations/{revoked["id"]}'))
    assert data(admin.get(f'/api/invitations/{revoked["token"]}'))['status']=='revoked'
    data(admin.post(f'/api/invitations/{revoked["token"]}/accept'),410)
    expired=invite(admin,book)
    with core.get_db(app) as db:db.execute("UPDATE ledger_invitations SET expires_at='2000-01-01' WHERE id=?",(expired['id'],))
    assert data(admin.get(f'/api/invitations/{expired["token"]}'))['status']=='expired'
    data(admin.post(f'/api/invitations/{expired["token"]}/accept'),410)
    data(admin.get('/api/invitations/not-a-token'),404)


def test_invitation_consume_is_atomic(admin,app):
    book=current_book(admin)
    invitation=invite(admin,book)
    def attempt(index):
        with TestClient(app) as client:
            return client.post(f'/api/invitations/{invitation["token"]}/register',json={'username':f'parallel-user-{index}','name':'Synthetic','password':'synthetic-password'}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(attempt,[1,2]))
    assert sorted(results)==[200,410]
    with core.get_db(app) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username LIKE 'parallel-user-%'").fetchone()[0]==1


@pytest.mark.parametrize('header',['-1','NaN','1.2','999999999999999999999'])
def test_invalid_ledger_header_fails_closed(admin,header):
    data(admin.get('/api/account/getAccount',headers={'X-Ledger-ID':header}),422)


def test_existing_single_ledger_migration_preserves_rows_credentials_and_ids(tmp_path,monkeypatch):
    directory=tmp_path/'legacy'; directory.mkdir()
    old=SimpleNamespace(state=SimpleNamespace(data_dir=directory))
    with monkeypatch.context() as patch:
        patch.setattr(ledgers,'init_ledgers_db',lambda app:None)
        core.init_db(old)
    digest,salt=core.password_hash('synthetic-old-password')
    with core.get_db(old) as db:
        stamp=core.utcnow()
        db.execute("INSERT INTO users(id,username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (41,'legacy-admin','Legacy Admin','admin',1,?,?,?,?)",(digest,salt,stamp,stamp))
        db.execute("INSERT INTO users(id,username,name,role,enabled,password_hash,password_salt,created_at,updated_at) VALUES (42,'legacy-member','Legacy Member','member',1,?,?,?,?)",(digest,salt,stamp,stamp))
        token=core.new_session(db,41)
        db.execute("INSERT INTO settings VALUES ('organization',?)",(json.dumps({'name':'Legacy Studio'}),))
        db.execute("INSERT INTO accounts VALUES (71,'Legacy Bank',100000,0,'',1,?,?)",(stamp,stamp))
        db.execute("INSERT INTO categories VALUES (81,'Legacy Income',NULL,'[0]',1,?,?)",(stamp,stamp))
        db.execute("INSERT INTO flows VALUES (91,1234,'2026-09-09',0,71,NULL,81,1,'Legacy note','[]','approved',42,'Reviewed',41,?,?,?,NULL,7)",(stamp,stamp,stamp))
        db.execute("INSERT INTO audit VALUES (101,41,'Legacy Admin','review','flow','91','{}',?)",(stamp,))
    migrated=main.create_app(directory)
    with TestClient(migrated) as client:
        client.cookies.set('studio_session',token)
        session=data(client.get('/api/session'))
        book=session['activeLedger'];assert book['name']=='Legacy Studio'
        assert session['user']['id']==41
        records=data(client.get('/api/flow/getFlowListMain/3/0/2026-09'))['flows']
        assert len(records)==1 and records[0]['id']==91 and records[0]['version']==7 and records[0]['note']=='Legacy note'
        assert data(client.get('/api/account/getAccount'))[0]['money']=='1012.34'
        assert {u['id'] for u in data(client.get('/api/users'))}=={41,42}
        assert data(client.get('/api/audit'))[0]['id']==101
        with core.get_db(migrated) as db:
            before={table:[tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in ['users','accounts','categories','flows','audit','ledgers','ledger_members']}
            assert db.execute('SELECT password_hash,password_salt FROM users WHERE id=41').fetchone()[:]==(digest,salt)
        main.create_app(directory)
        with core.get_db(migrated) as db:
            after={table:[tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in before}
        assert before==after


def test_simultaneous_admin_removal_preserves_one_admin(admin,app):
    book=current_book(admin)
    second_user,second=create_member(admin,app,'second-admin',role='admin')
    first_id=data(admin.get('/api/me'))['id']
    sessions=[(first_id,admin.cookies.get('studio_session')),(second_user['id'],second.cookies.get('studio_session'))]
    def attempt(pair):
        identifier,token=pair
        with TestClient(app) as client:
            client.cookies.set('studio_session',token)
            return client.delete(f'/api/ledgers/{book["id"]}/members/{identifier}').status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(attempt,sessions))
        assert sorted(results)==[200,409]
        with core.get_db(app) as db:
            assert db.execute("SELECT COUNT(*) FROM ledger_members WHERE ledger_id=? AND role='admin' AND enabled=1",(book['id'],)).fetchone()[0]==1
    finally:second.close()
