import { reactive } from "vue";
import { api, setLedgerContext, getLedgerContext } from "./api";
export const state = reactive({
  user: null,
  organization: "我的工作室",
  siteName: "账序",
  authOptions: null,
  needsSetup: false,
  ready: false,
  ledgers: [],
  activeLedger: null,
  switchingLedger: false,
  toasts: [],
});
export const bus = new EventTarget();
export async function refreshSystemOptions() {
  const options = await api("/auth/options");
  state.authOptions = options;
  state.siteName = options.siteName || "账序";
  return options;
}
let nextId = 0;
export function notify(message, type = "success") {
  if (!message || typeof message !== "string") return;
  const id = ++nextId;
  state.toasts.push({ id, message, type });
  setTimeout(
    () => {
      state.toasts = state.toasts.filter((item) => item.id !== id);
    },
    type === "error" ? 6500 : 4000,
  );
}
function savedLedger(userId) {
  try {
    return localStorage.getItem(`ledgerly:active-ledger:${userId}`);
  } catch {
    return null;
  }
}
function rememberLedger() {
  if (!state.user) return;
  try {
    const key = `ledgerly:active-ledger:${state.user.id}`;
    if (state.activeLedger) localStorage.setItem(key, state.activeLedger.id);
    else localStorage.removeItem(key);
  } catch {
    /* Storage is optional; authorization is always verified by the API. */
  }
}
function applySession(data) {
  state.user = data.user || null;
  state.needsSetup = Boolean(data.needsSetup);
  state.organization =
    data.organization?.name || data.organization || "我的工作室";
  state.ledgers = data.ledgers || [];
  state.activeLedger = data.activeLedger || null;
  setLedgerContext(state.activeLedger?.id ?? null);
  rememberLedger();
}
export function clearSession() {
  setLedgerContext(null);
  state.user = null;
  state.ledgers = [];
  state.activeLedger = null;
  state.switchingLedger = false;
}
export async function initSession() {
  try {
    let data;
    try {
      data = await api("/session");
    } catch (error) {
      if (error.status !== 403) throw error;
      setLedgerContext(null);
      data = await api("/session");
    }
    if (data.user) {
      const saved = savedLedger(data.user.id);
      const chosen = data.ledgers?.find((item) => String(item.id) === saved);
      if (chosen && String(data.activeLedger?.id) !== String(chosen.id)) {
        setLedgerContext(chosen.id);
        data = await api("/session");
      }
    }
    applySession(data);
    return data;
  } finally {
    state.ready = true;
  }
}
export async function refreshLedgers() {
  state.ledgers = await api("/ledgers");
  const active = state.ledgers.find(
    (item) => String(item.id) === String(state.activeLedger?.id),
  );
  if (active) {
    state.activeLedger = active;
    if (state.user) state.user = { ...state.user, role: active.role };
  } else if (state.activeLedger) {
    setLedgerContext(null);
    applySession(await api("/session"));
  }
  return state.ledgers;
}
export async function selectLedger(id) {
  if (state.switchingLedger) return;
  if (String(id) === String(state.activeLedger?.id)) return;
  const chosen = state.ledgers.find((item) => String(item.id) === String(id));
  if (!chosen) throw new Error("你尚未加入这个账本，请先接受邀请。");
  const previous = getLedgerContext();
  state.switchingLedger = true;
  bus.dispatchEvent(new Event("ledger-switching"));
  try {
    setLedgerContext(id);
    const data = await api("/session");
    if (String(data.activeLedger?.id) !== String(id))
      throw new Error("无法打开该账本，请刷新账本列表。");
    applySession(data);
    bus.dispatchEvent(new Event("ledger-switched"));
  } catch (error) {
    setLedgerContext(previous);
    throw error;
  } finally {
    state.switchingLedger = false;
  }
}
