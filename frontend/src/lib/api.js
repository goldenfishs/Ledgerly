export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let activeLedgerId = null;
let generation = 0;
const pendingRequests = new Set();
export function setLedgerContext(id) {
  const next = id == null ? null : String(id);
  if (next === activeLedgerId) return;
  activeLedgerId = next;
  generation += 1;
  for (const controller of pendingRequests) controller.abort();
  pendingRequests.clear();
}
export function getLedgerContext() {
  return activeLedgerId;
}
function interrupted() {
  return new DOMException("账本已切换，请重新操作。", "AbortError");
}

export async function api(path, options = {}) {
  const { query, body, blob, signal, ...rest } = options;
  const url = new URL(
    `/api${path.startsWith("/") ? path : `/${path}`}`,
    location.origin,
  );
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "")
      url.searchParams.set(key, value);
  }
  const headers = new Headers(rest.headers);
  if (activeLedgerId !== null) headers.set("X-Ledger-ID", activeLedgerId);
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }
  const requestGeneration = generation;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abort, { once: true });
  pendingRequests.add(controller);
  try {
    let response;
    try {
      response = await fetch(url, {
        ...rest,
        headers,
        body: payload,
        signal: controller.signal,
        credentials: "same-origin",
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new ApiError("暂时无法连接服务，请检查网络后重试。", 0);
    }
    if (requestGeneration !== generation) throw interrupted();
    if (blob && response.ok) {
      const result = await response.blob();
      if (requestGeneration !== generation) throw interrupted();
      return result;
    }
    let result;
    try {
      result = await response.json();
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new ApiError("服务返回异常，请稍后重试。", response.status);
    }
    if (requestGeneration !== generation) throw interrupted();
    if (
      !response.ok ||
      (result.code !== undefined && result.code !== 0) ||
      result.success === false
    ) {
      const detail = result.msg || result.message || result.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((x) => x.msg).join("；")
            : "操作未完成，请检查填写内容。";
      if (
        response.status === 401 &&
        !path.startsWith("/auth/") &&
        path !== "/session" &&
        !path.startsWith("/invitations/")
      )
        window.dispatchEvent(new Event("session-expired"));
      if (
        response.status === 403 &&
        activeLedgerId !== null &&
        !path.startsWith("/ledgers") &&
        !path.startsWith("/invitations/") &&
        !path.startsWith("/profile") &&
        !path.startsWith("/system/") &&
        !path.startsWith("/auth/") &&
        path !== "/session"
      )
        window.dispatchEvent(new Event("ledger-access-check"));
      throw new ApiError(message, response.status);
    }
    return Object.hasOwn(result, "data") ? result.data : result;
  } finally {
    pendingRequests.delete(controller);
    signal?.removeEventListener("abort", abort);
  }
}
