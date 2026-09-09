import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { api, setLedgerContext } from '../frontend/src/lib/api.js';

const originalFetch = globalThis.fetch;
globalThis.location = { origin: 'http://127.0.0.1:10671' };
globalThis.window = new EventTarget();
afterEach(() => { setLedgerContext(null); globalThis.fetch = originalFetch; });
const response = data => Response.json({ code: 0, data });

test('all ledger requests use the selected context, including file downloads', async () => {
  setLedgerContext(17);
  globalThis.fetch = async (url, options) => {
    assert.equal(options.headers.get('X-Ledger-ID'), '17');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(url.searchParams.get('month'), '2026-09');
    return new Response('invoice-original');
  };
  const result = await api('/invoices/1/file', { blob: true, query: { month: '2026-09' }, headers: { 'X-Ledger-ID': '99' } });
  assert.equal(await result.text(), 'invoice-original');
});

test('switching ledgers aborts outstanding requests and rejects late responses', async () => {
  setLedgerContext(1);
  let finish, requestSignal;
  globalThis.fetch = (_, options) => { requestSignal = options.signal; return new Promise(resolve => { finish = resolve; }); };
  const pending = api('/flows');
  setLedgerContext(2);
  assert.equal(requestSignal.aborted, true);
  finish(response([{ ledgerId: 1 }]));
  await assert.rejects(pending, { name: 'AbortError' });
});

test('old JSON cannot reach a new ledger when switching during body parsing', async () => {
  setLedgerContext(1);
  let finish, parsing;
  const started = new Promise(resolve => { parsing = resolve; });
  globalThis.fetch = async () => ({ ok: true, status: 200, json: () => { parsing(); return new Promise(resolve => { finish = resolve; }); } });
  const pending = api('/dashboard');
  await started;
  setLedgerContext(2);
  finish({ code: 0, data: { balance: 123 } });
  await assert.rejects(pending, { name: 'AbortError' });
});

test('old downloads cannot be offered after the selected ledger changes', async () => {
  setLedgerContext(1);
  let finish, parsing;
  const started = new Promise(resolve => { parsing = resolve; });
  globalThis.fetch = async () => ({ ok: true, blob: () => { parsing(); return new Promise(resolve => { finish = resolve; }); } });
  const pending = api('/invoices/1/file', { blob: true });
  await started;
  setLedgerContext(2);
  finish(new Blob(['old ledger file']));
  await assert.rejects(pending, { name: 'AbortError' });
});

test('clearing a session clears the ledger header and preserves null data', async () => {
  setLedgerContext(3);
  setLedgerContext(null);
  globalThis.fetch = async (_, options) => {
    assert.equal(options.headers.has('X-Ledger-ID'), false);
    return response(null);
  };
  assert.equal(await api('/session'), null);
});

test('permission failures request membership refresh without treating them as logout', async () => {
  setLedgerContext(4);
  let checks = 0, expirations = 0;
  const check = () => { checks++; }, expire = () => { expirations++; };
  window.addEventListener('ledger-access-check', check);
  window.addEventListener('session-expired', expire);
  try {
    globalThis.fetch = async () => Response.json({ detail: 'membership removed' }, { status: 403 });
    await assert.rejects(api('/accounts'), { status: 403 });
    assert.equal(checks, 1);
    assert.equal(expirations, 0);
  } finally {
    window.removeEventListener('ledger-access-check', check);
    window.removeEventListener('session-expired', expire);
  }
});

test('personal, system and auth permission denials do not refresh ledger membership or expire the session', async () => {
  setLedgerContext(4);
  let checks = 0, expirations = 0;
  const check = () => { checks++; }, expire = () => { expirations++; };
  window.addEventListener('ledger-access-check', check);
  window.addEventListener('session-expired', expire);
  try {
    globalThis.fetch = async () => Response.json({ code: 403, msg: 'operation not allowed', data: null }, { status: 403 });
    for (const path of ['/profile', '/profile/email/code', '/system/settings', '/system/email', '/auth/register', '/auth/reset-password']) {
      await assert.rejects(api(path), { status: 403, message: 'operation not allowed' });
      assert.equal(checks, 0, `${path} must not be treated as a ledger membership failure`);
      assert.equal(expirations, 0, `${path} must not log out an authenticated user`);
    }
  } finally {
    window.removeEventListener('ledger-access-check', check);
    window.removeEventListener('session-expired', expire);
  }
});

test('personal and system authentication failures expire the session, while auth form failures remain local', async () => {
  setLedgerContext(4);
  let checks = 0, expirations = 0;
  const check = () => { checks++; }, expire = () => { expirations++; };
  window.addEventListener('ledger-access-check', check);
  window.addEventListener('session-expired', expire);
  try {
    globalThis.fetch = async () => Response.json({ code: 401, msg: 'authentication required', data: null }, { status: 401 });
    const protectedPaths = ['/profile', '/profile/password', '/profile/avatar', '/system/settings', '/system/email'];
    for (const [index, path] of protectedPaths.entries()) {
      await assert.rejects(api(path), { status: 401 });
      assert.equal(expirations, index + 1, `${path} must notify the app that authentication expired`);
      assert.equal(checks, 0, `${path} must not refresh ledger membership`);
    }
    for (const path of ['/auth/login', '/auth/register', '/auth/reset-password']) {
      await assert.rejects(api(path), { status: 401 });
      assert.equal(expirations, protectedPaths.length, `${path} must keep its authentication error in the form`);
      assert.equal(checks, 0);
    }
  } finally {
    window.removeEventListener('ledger-access-check', check);
    window.removeEventListener('session-expired', expire);
  }
});
