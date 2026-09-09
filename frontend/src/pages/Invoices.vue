<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import {
  Receipt,
  UploadCloud,
  Plus,
  Search,
  Trash2,
  RotateCcw,
  RefreshCw,
  Check,
  X,
  Download,
  FileText,
  ScanLine,
  ShieldCheck,
  LoaderCircle,
  AlertCircle,
  Wallet,
  Clock3,
  Users,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { state, notify } from "../lib/app";
import { dateTime } from "../lib/format";

const categories = ["餐饮", "交通", "住宿", "办公", "购物", "其他"];
const statuses = {
  pending: "待识别",
  processing: "识别中",
  review: "待核对",
  confirmed: "已确认",
  error: "识别失败",
};
const records = ref([]),
  loading = ref(true),
  failure = ref(""),
  trash = ref(false);
const query = ref(""),
  category = ref(""),
  status = ref(""),
  dragging = ref(false);
const picker = ref(null),
  queue = ref([]),
  queueBusy = ref(false),
  drawer = ref(null),
  panel = ref(null),
  confirm = ref(null);
let requestId = 0,
  openId = 0,
  disposed = false,
  poll,
  restoreFocus;
const admin = computed(() => state.user?.role === "admin");
const fields = [
  "seller",
  "buyer",
  "invoice_number",
  "invoice_date",
  "amount",
  "tax_amount",
  "total_amount",
  "category",
  "notes",
];
const filtered = computed(() =>
  records.value.filter(
    (record) =>
      (!category.value || record.category === category.value) &&
      (!status.value || record.status === status.value) &&
      [
        "name",
        "seller",
        "buyer",
        "invoice_number",
        "notes",
        "invoice_date",
        ...(admin.value ? ["ownerName"] : []),
      ].some((key) =>
        String(record[key] || "")
          .toLocaleLowerCase()
          .includes(query.value.trim().toLocaleLowerCase()),
      ),
  ),
);
const pending = computed(
  () =>
    records.value.filter((record) =>
      ["pending", "processing", "error"].includes(record.status),
    ).length,
);
const review = computed(
  () => records.value.filter((record) => record.status === "review").length,
);
const processed = computed(
  () =>
    queue.value.filter(
      (item) => !["waiting", "uploading", "recognizing"].includes(item.phase),
    ).length,
);
const total = computed(() =>
  centsText(
    records.value.reduce(
      (sum, row) => sum + (toCents(row.total_amount) ?? 0n),
      0n,
    ),
  ),
);
const dirty = computed(
  () =>
    drawer.value?.form &&
    drawer.value.baseline !== JSON.stringify(drawer.value.form),
);
const mismatch = computed(() => {
  const form = drawer.value?.form;
  if (!form) return false;
  const a = toCents(form.amount),
    t = toCents(form.tax_amount),
    total = toCents(form.total_amount);
  return a !== null && t !== null && total !== null && a + t !== total;
});
function toCents(value) {
  const match = String(value ?? "")
    .trim()
    .match(/^(-?)(\d+)(?:\.(\d{1,2}))?$/);
  return match
    ? (match[1] ? -1n : 1n) *
        (BigInt(match[2]) * 100n + BigInt((match[3] || "").padEnd(2, "0")))
    : null;
}
function centsText(value) {
  const absolute = value < 0n ? -value : value;
  return `${value < 0n ? "-" : ""}${String(absolute / 100n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${String(absolute % 100n).padStart(2, "0")}`;
}
function money(value) {
  const result = toCents(value);
  return result === null ? "—" : `¥ ${centsText(result)}`;
}
function bytes(value) {
  return value >= 1048576
    ? `${(value / 1048576).toFixed(1)} MB`
    : `${Math.max(1, Math.round((value || 0) / 1024))} KB`;
}
const endpoint = (record) => `/invoices/${encodeURIComponent(record.id)}`;
function resetFilters() {
  query.value = "";
  category.value = "";
  status.value = "";
}
async function load(quiet = false) {
  const sequence = ++requestId;
  if (!quiet) {
    loading.value = true;
    failure.value = "";
  }
  try {
    const data = await api("/invoices", { query: { trash: trash.value } });
    if (sequence !== requestId || disposed) return;
    records.value = data.items || [];
    failure.value = "";
  } catch (error) {
    if (sequence === requestId && !quiet) failure.value = error.message;
  } finally {
    if (sequence === requestId) loading.value = false;
  }
}
function put(record) {
  const index = records.value.findIndex((item) => item.id === record.id);
  if (Boolean(record.deleted_at) !== trash.value) {
    if (index >= 0) records.value.splice(index, 1);
  } else if (index >= 0) records.value[index] = record;
  else records.value.unshift(record);
}
function switchTrash(value) {
  if (trash.value === value) return;
  trash.value = value;
  resetFilters();
  load();
}
function fileError(file) {
  if (
    !/\.(jpe?g|png|webp|pdf)$/i.test(file.name) ||
    (file.type &&
      !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(
        file.type,
      ))
  )
    return "请选择 JPG、PNG、WEBP 或 PDF 文件";
  if (!file.size) return "文件为空，请重新选择";
  if (file.size > 15 * 1024 * 1024) return "文件超过 15 MB，请压缩后重试";
  return "";
}
function enqueue(files) {
  for (const file of files) {
    const error = fileError(file);
    queue.value.push({
      key: crypto.randomUUID(),
      file,
      name: file.name,
      size: file.size,
      phase: error ? "error" : "waiting",
      message: error || "等待保存原件",
      record: null,
    });
  }
  runQueue();
}
async function runQueue() {
  if (queueBusy.value || disposed) return;
  queueBusy.value = true;
  try {
    let item;
    while (
      !disposed &&
      (item = queue.value.find((entry) => entry.phase === "waiting"))
    ) {
      try {
        item.phase = "uploading";
        item.message = "正在保存原件…";
        const form = new FormData();
        form.append("file", item.file);
        const saved = await api("/invoices", { method: "POST", body: form });
        item.record = saved.invoice;
        put(saved.invoice);
        if (saved.duplicate) {
          item.phase = "duplicate";
          item.message = saved.invoice.deleted_at
            ? "相同原件已在回收站，可查看并恢复"
            : "已找到相同原件，保留已有核对结果";
        } else {
          item.phase = "recognizing";
          item.message = "原件已保存，正在识别…";
          const recognized = await api(`${endpoint(saved.invoice)}/recognize`, {
            method: "POST",
            body: { version: saved.invoice.version },
          });
          item.record = recognized;
          put(recognized);
          item.phase = recognized.status === "error" ? "error" : "done";
          item.message =
            recognized.status === "error"
              ? `${recognized.error}；原件已保存，可手动填写`
              : "识别完成，打开详情核对并保存";
        }
      } catch (error) {
        item.phase = "error";
        item.message = `${item.record ? "原件已保存。" : ""}${error.message}`;
        if (item.record) {
          try {
            item.record = await api(endpoint(item.record));
            put(item.record);
          } catch {}
        }
      } finally {
        item.file = null;
      }
    }
  } finally {
    queueBusy.value = false;
    if (!disposed) await load(true);
  }
}
function ask(title, description, action = "确认", danger = false) {
  if (confirm.value) return Promise.resolve(false);
  return new Promise((resolve) => {
    confirm.value = { title, description, action, danger, resolve };
    nextTick(() => document.querySelector(".iv-confirm button")?.focus());
  });
}
function answer(value) {
  const dialog = confirm.value;
  confirm.value = null;
  dialog?.resolve(value);
  nextTick(() => panel.value?.focus());
}
function releasePreview(target) {
  if (target?.preview) URL.revokeObjectURL(target.preview);
}
function adopt(target, record) {
  releasePreview(target);
  target.record = record;
  target.form = Object.fromEntries(
    fields.map((key) => [key, record[key] ?? ""]),
  );
  target.baseline = JSON.stringify(target.form);
  target.error = "";
  target.preview = "";
  target.previewError = "";
  target.busy = false;
  target.loading = false;
}
async function closeDrawer(force = false) {
  if (!drawer.value) return true;
  if (!force && drawer.value.busy) {
    notify("正在处理，请完成后再关闭", "error");
    return false;
  }
  if (
    !force &&
    dirty.value &&
    !(await ask(
      "放弃未保存的修改？",
      "当前填写内容还未保存，放弃后将恢复上次保存的信息。",
      "放弃修改",
      true,
    ))
  )
    return false;
  releasePreview(drawer.value);
  drawer.value.abort.abort();
  drawer.value = null;
  document.body.style.overflow = "";
  if (restoreFocus?.isConnected) restoreFocus.focus();
  return true;
}
async function openRecord(record) {
  if (!(await closeDrawer())) return;
  const sequence = ++openId;
  restoreFocus = document.activeElement;
  drawer.value = {
    record,
    loading: true,
    form: null,
    baseline: "",
    busy: false,
    preview: "",
    previewError: "",
    error: "",
    abort: new AbortController(),
  };
  const target = drawer.value;
  document.body.style.overflow = "hidden";
  nextTick(() => panel.value?.focus());
  try {
    const fresh = await api(endpoint(record), { signal: target.abort.signal });
    if (sequence !== openId || drawer.value !== target) return;
    adopt(target, fresh);
    loadPreview(target);
  } catch (error) {
    if (drawer.value === target && error.name !== "AbortError") {
      target.loading = false;
      target.error = error.message;
    }
  }
}
async function loadPreview(target) {
  const id = target.record.id;
  try {
    const blob = await api(`${endpoint(target.record)}/preview`, {
      blob: true,
      signal: target.abort.signal,
    });
    if (drawer.value !== target || target.record.id !== id) return;
    releasePreview(target);
    target.preview = URL.createObjectURL(blob);
  } catch (error) {
    if (drawer.value === target && error.name !== "AbortError")
      target.previewError = error.message;
  }
}
async function download() {
  const target = drawer.value;
  try {
    const blob = await api(`${endpoint(target.record)}/file`, {
      blob: true,
      signal: target.abort.signal,
    });
    const url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = target.record.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (error) {
    if (error.name !== "AbortError") notify(error.message, "error");
  }
}
async function refreshDrawer() {
  const target = drawer.value;
  if (target.busy) return;
  if (
    dirty.value &&
    !(await ask(
      "读取最新记录？",
      "当前未保存的内容将由服务端最新记录替换。",
      "读取最新记录",
    ))
  )
    return;
  target.busy = true;
  try {
    const record = await api(endpoint(target.record));
    if (drawer.value !== target) return;
    adopt(target, record);
    put(record);
    loadPreview(target);
  } catch (error) {
    target.busy = false;
    target.error = error.message;
  }
}
async function save() {
  const target = drawer.value;
  if (
    target.busy ||
    target.record.deleted_at ||
    target.record.status === "processing"
  )
    return;
  target.error = "";
  const body = {
    ...target.form,
    status: "confirmed",
    version: target.record.version,
  };
  for (const name of ["amount", "tax_amount", "total_amount"]) {
    const value = String(body[name]).trim();
    if (value && !/^-?\d{1,16}(?:\.\d{1,2})?$/.test(value)) {
      target.error = "金额最多保留两位小数，整数部分不超过 16 位";
      return;
    }
    body[name] = value || null;
  }
  if (body.total_amount === null) {
    target.error = "请填写价税合计，再确认保存";
    return;
  }
  target.busy = true;
  try {
    const record = await api(endpoint(target.record), {
      method: "PATCH",
      body,
    });
    if (drawer.value !== target) return;
    adopt(target, record);
    put(record);
    loadPreview(target);
    notify("发票已确认保存");
  } catch (error) {
    target.busy = false;
    target.error =
      error.status === 409
        ? "记录已被更新，你的填写尚未保存，请读取最新记录后重新核对。"
        : error.message;
  }
}
async function recognize() {
  const target = drawer.value;
  if (
    target.busy ||
    target.record.deleted_at ||
    target.record.status === "processing"
  )
    return;
  if (
    (dirty.value || ["review", "confirmed"].includes(target.record.status)) &&
    !(await ask(
      "重新识别原件？",
      "将重新提取原件信息，替换相关字段和未保存的内容，完成后请再次核对。",
      "重新识别",
    ))
  )
    return;
  target.busy = true;
  target.error = "";
  try {
    const record = await api(`${endpoint(target.record)}/recognize`, {
      method: "POST",
      body: { version: target.record.version },
    });
    if (drawer.value !== target) return;
    adopt(target, record);
    put(record);
    loadPreview(target);
    notify(
      record.status === "error"
        ? "识别未完成，可手动填写或重试"
        : "识别完成，请核对后保存",
      record.status === "error" ? "error" : "success",
    );
  } catch (error) {
    target.busy = false;
    target.error = error.message;
  }
}
async function remove() {
  const target = drawer.value;
  if (
    target.busy ||
    !(await ask(
      "将发票移入回收站？",
      "原件和已保存的信息会保留，可随时恢复。未保存的修改将被放弃。",
      "移入回收站",
      true,
    ))
  )
    return;
  target.busy = true;
  try {
    const record = await api(endpoint(target.record), {
      method: "DELETE",
      query: { version: target.record.version },
    });
    put(record);
    await closeDrawer(true);
    notify("已移入回收站");
  } catch (error) {
    target.busy = false;
    target.error = error.message;
  }
}
async function restore() {
  const target = drawer.value;
  if (target.busy) return;
  target.busy = true;
  try {
    const record = await api(`${endpoint(target.record)}/restore`, {
      method: "POST",
      query: { version: target.record.version },
    });
    put(record);
    await closeDrawer(true);
    notify("发票已恢复，可在全部发票中查看");
  } catch (error) {
    target.busy = false;
    target.error = error.message;
  }
}
function beforeUnload(event) {
  if (queueBusy.value || drawer.value?.busy || dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
function keyboard(event) {
  const container = confirm.value
    ? document.querySelector(".iv-confirm")
    : panel.value;
  if (!container) return;
  if (event.key === "Escape") {
    event.preventDefault();
    confirm.value ? answer(false) : closeDrawer();
  }
  if (event.key === "Tab") {
    const nodes = [
      ...container.querySelectorAll(
        "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
      ),
    ].filter((node) => node.getClientRects().length);
    const first = nodes[0],
      last = nodes[nodes.length - 1];
    if (!first) {
      event.preventDefault();
      return;
    }
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        !container.contains(document.activeElement))
    ) {
      event.preventDefault();
      last.focus();
    } else if (
      !event.shiftKey &&
      (document.activeElement === last ||
        !container.contains(document.activeElement))
    ) {
      event.preventDefault();
      first.focus();
    }
  }
}
onBeforeRouteLeave(async () => {
  if (queueBusy.value || drawer.value?.busy) {
    notify("发票正在处理，请完成后离开", "error");
    return false;
  }
  if (
    dirty.value &&
    !(await ask(
      "离开发票凭证？",
      "当前填写的内容尚未保存，离开会放弃这些修改。",
      "离开页面",
      true,
    ))
  )
    return false;
  return true;
});
onMounted(() => {
  load();
  window.addEventListener("beforeunload", beforeUnload);
  document.addEventListener("keydown", keyboard);
  poll = setInterval(() => {
    if (records.value.some((row) => row.status === "processing")) load(true);
  }, 5000);
});
onBeforeUnmount(() => {
  disposed = true;
  clearInterval(poll);
  releasePreview(drawer.value);
  drawer.value?.abort.abort();
  document.body.style.overflow = "";
  window.removeEventListener("beforeunload", beforeUnload);
  document.removeEventListener("keydown", keyboard);
  confirm.value?.resolve(false);
});
</script>

<template>
  <section class="iv-page">
    <div class="iv-heading">
      <div>
        <div class="iv-eyebrow">DOCUMENTS</div>
        <h1>发票凭证</h1>
        <p>
          {{
            admin
              ? "当前账本的每一张凭证，集中归档、清楚核对。"
              : "上传原件，核对信息，让每一笔支出有据可查。"
          }}
        </p>
      </div>
      <button class="iv-button iv-primary" @click="picker.click()">
        <Plus :size="17" />上传发票
      </button>
    </div>
    <input
      ref="picker"
      type="file"
      multiple
      accept=".jpg,.jpeg,.png,.webp,.pdf"
      hidden
      @change="
        enqueue([...$event.target.files]);
        $event.target.value = '';
      "
    />
    <div class="iv-stats">
      <div class="iv-stat">
        <div>
          <span>{{
            trash ? "回收站发票" : admin ? "账本发票" : "我的发票"
          }}</span
          ><Receipt :size="18" />
        </div>
        <strong>{{ loading ? "—" : records.length }}<small>张</small></strong>
        <p>原件与记录一起保存</p>
      </div>
      <div class="iv-stat">
        <div><span>价税合计</span><Wallet :size="18" /></div>
        <strong class="iv-stat-money"
          ><small>¥</small>{{ loading ? "—" : total }}</strong
        >
        <p>已填写的含税金额汇总</p>
      </div>
      <div class="iv-stat">
        <div><span>待核对</span><ScanLine :size="18" /></div>
        <strong>{{ loading ? "—" : review }}<small>张</small></strong>
        <p>核对识别结果后确认</p>
      </div>
      <div class="iv-stat">
        <div><span>待处理</span><Clock3 :size="18" /></div>
        <strong>{{ loading ? "—" : pending }}<small>张</small></strong>
        <p>等待识别或需要重试</p>
      </div>
    </div>
    <div
      class="iv-drop"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="
        dragging = false;
        enqueue([...$event.dataTransfer.files]);
      "
    >
      <div class="iv-drop-icon"><UploadCloud :size="25" /></div>
      <div>
        <strong>拖入发票，开始整理</strong>
        <p>JPG、PNG、WEBP、PDF · 单个不超过 15 MB · PDF 识别第一页</p>
      </div>
      <button class="iv-button" @click="picker.click()">选择文件</button>
    </div>
    <section v-if="queue.length" class="iv-queue" aria-live="polite">
      <div class="iv-queue-header">
        <strong
          >{{ queueBusy ? "正在整理发票" : "本次处理完成" }}
          <span>{{ processed }} / {{ queue.length }}</span></strong
        ><button class="iv-link" :disabled="queueBusy" @click="queue = []">
          收起已完成
        </button>
      </div>
      <div v-for="item in queue" :key="item.key" class="iv-queue-row">
        <LoaderCircle
          v-if="['uploading', 'recognizing'].includes(item.phase)"
          class="iv-spin"
          :size="17"
        /><AlertCircle
          v-else-if="item.phase === 'error'"
          class="iv-red"
          :size="17"
        /><Check v-else :size="17" />
        <div>
          <strong>{{ item.name }}</strong>
          <p>{{ item.message }}</p>
        </div>
        <button
          v-if="item.record"
          class="iv-link"
          @click="openRecord(item.record)"
        >
          查看
        </button>
      </div>
    </section>
    <section class="iv-records">
      <div class="iv-toolbar">
        <div class="iv-tabs">
          <button :class="{ active: !trash }" @click="switchTrash(false)">
            全部发票<span v-if="!trash">{{ records.length }}</span></button
          ><button :class="{ active: trash }" @click="switchTrash(true)">
            <Trash2 :size="15" />回收站
          </button>
        </div>
        <button
          class="iv-icon-button"
          aria-label="刷新发票"
          :disabled="loading"
          @click="load()"
        >
          <RefreshCw :size="17" :class="{ 'iv-spin': loading }" />
        </button>
      </div>
      <div class="iv-filters">
        <label class="iv-search"
          ><Search :size="17" /><input
            v-model="query"
            type="search"
            :placeholder="
              admin ? '搜索销售方、票号或所属成员' : '搜索销售方、票号或文件名'
            "
            aria-label="搜索发票" /></label
        ><select v-model="category" aria-label="发票分类">
          <option value="">全部分类</option>
          <option v-for="item in categories" :key="item">
            {{ item }}
          </option></select
        ><select v-model="status" aria-label="发票状态">
          <option value="">全部状态</option>
          <option v-for="(label, key) in statuses" :key="key" :value="key">
            {{ label }}
          </option>
        </select>
      </div>
      <div v-if="loading" class="iv-empty">
        <LoaderCircle :size="29" class="iv-spin" />
        <h3>正在读取发票</h3>
        <p>稍等，正在获取最新记录</p>
      </div>
      <div v-else-if="failure" class="iv-empty">
        <AlertCircle :size="30" />
        <h3>暂时无法读取发票</h3>
        <p>{{ failure }}</p>
        <button class="iv-button" @click="load()">重新加载</button>
      </div>
      <div v-else-if="!filtered.length" class="iv-empty">
        <div class="iv-empty-icon"><Receipt :size="32" /></div>
        <h3>
          {{
            query || category || status
              ? "没有找到匹配的发票"
              : trash
                ? "回收站是空的"
                : "从第一张凭证开始"
          }}
        </h3>
        <p>
          {{
            query || category || status
              ? "试试其他关键词，或清除筛选条件。"
              : trash
                ? "删除的发票会保留在这里，可以随时恢复。"
                : "上传图片或 PDF，自动提取信息，核对后安心归档。"
          }}
        </p>
        <button
          v-if="query || category || status"
          class="iv-button"
          @click="resetFilters"
        >
          清除筛选</button
        ><button
          v-else-if="!trash"
          class="iv-button iv-primary"
          @click="picker.click()"
        >
          <Plus :size="16" />上传第一张发票
        </button>
      </div>
      <div v-else class="iv-table-wrap">
        <table class="iv-table">
          <thead>
            <tr>
              <th>发票 / 销售方</th>
              <th v-if="admin">所属成员</th>
              <th>分类</th>
              <th>价税合计</th>
              <th>开票日期</th>
              <th>状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in filtered" :key="record.id">
              <td>
                <div class="iv-identity">
                  <span
                    class="iv-file-icon"
                    :class="{ pdf: record.mime_type === 'application/pdf' }"
                    ><FileText :size="19"
                  /></span>
                  <div>
                    <button class="iv-record-name" @click="openRecord(record)">
                      {{ record.seller || record.name }}</button
                    ><small>{{
                      record.invoice_number
                        ? `票号 ${record.invoice_number}`
                        : record.name
                    }}</small>
                  </div>
                </div>
              </td>
              <td v-if="admin">
                <span class="iv-owner"
                  ><Users :size="14" />{{ record.ownerName }}</span
                >
              </td>
              <td>
                <span class="iv-category">{{ record.category }}</span>
              </td>
              <td class="iv-amount">{{ money(record.total_amount) }}</td>
              <td class="iv-date">{{ record.invoice_date || "待填写" }}</td>
              <td>
                <span class="iv-status" :class="record.status"
                  ><i></i>{{ statuses[record.status] || "待识别" }}</span
                >
              </td>
              <td>
                <button class="iv-link" @click="openRecord(record)">
                  查看
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="iv-table-footer">
        <span>{{
          loading
            ? "读取中…"
            : `共 ${records.length} 张 · 当前显示 ${filtered.length} 张`
        }}</span
        ><span
          ><ShieldCheck :size="14" />{{
            admin ? "管理员可管理账本发票" : "仅本人和管理员可查看"
          }}</span
        >
      </div>
    </section>
  </section>
  <Teleport to="body">
    <div v-if="drawer" class="iv-mask" @click.self="closeDrawer()">
      <section
        ref="panel"
        class="iv-drawer"
        tabindex="-1"
        role="dialog"
        aria-modal="true"
        aria-labelledby="iv-title"
        :aria-busy="drawer.busy"
        :inert="Boolean(confirm)"
      >
        <header class="iv-drawer-header">
          <div>
            <div class="iv-title-row">
              <h2 id="iv-title">
                {{
                  drawer.record.deleted_at ? "回收站 · 发票详情" : "核对发票"
                }}
              </h2>
              <span class="iv-status" :class="drawer.record.status">{{
                statuses[drawer.record.status]
              }}</span>
            </div>
            <p>{{ drawer.record.name }}</p>
          </div>
          <button
            class="iv-icon-button"
            aria-label="关闭详情"
            :disabled="drawer.busy"
            @click="closeDrawer()"
          >
            <X :size="21" />
          </button>
        </header>
        <div v-if="drawer.loading" class="iv-empty">
          <LoaderCircle class="iv-spin" :size="30" />
          <p>正在读取最新记录…</p>
        </div>
        <div v-else-if="!drawer.form" class="iv-empty">
          <AlertCircle :size="30" />
          <p>{{ drawer.error }}</p>
          <button class="iv-button" @click="openRecord(drawer.record)">
            重新加载
          </button>
        </div>
        <template v-else
          ><div class="iv-drawer-main">
            <aside class="iv-preview">
              <div class="iv-preview-header">
                <strong>发票原件</strong
                ><button class="iv-link" @click="download">
                  <Download :size="15" />下载原件
                </button>
              </div>
              <div class="iv-image-stage">
                <img
                  v-if="drawer.preview"
                  :src="drawer.preview"
                  :alt="`发票原件：${drawer.record.name}`"
                />
                <div v-else class="iv-empty">
                  <AlertCircle
                    v-if="drawer.previewError"
                    :size="25"
                  /><LoaderCircle v-else class="iv-spin" :size="25" />
                  <p>{{ drawer.previewError || "正在加载预览…" }}</p>
                </div>
              </div>
              <p class="iv-preview-caption">
                <ShieldCheck :size="14" />{{ bytes(drawer.record.file_size) }} ·
                {{
                  drawer.record.mime_type === "application/pdf"
                    ? `PDF 共 ${drawer.record.page_count || 1} 页，预览和识别仅处理第一页`
                    : "原件已保存，可下载查看完整图片"
                }}
              </p>
            </aside>
            <div class="iv-details">
              <div
                class="iv-banner"
                :class="{ error: drawer.record.status === 'error' }"
              >
                <AlertCircle
                  v-if="drawer.record.status === 'error'"
                  :size="18"
                /><ScanLine v-else :size="18" /><span>{{
                  drawer.record.deleted_at
                    ? "这张发票已移入回收站，恢复后可继续编辑。"
                    : drawer.record.status === "error"
                      ? `${drawer.record.error}。可重试或直接手动填写。`
                      : drawer.record.status === "processing"
                        ? "正在识别，请稍后读取最新记录。"
                        : drawer.record.status === "confirmed"
                          ? "发票已确认，修改后请再次核对并保存。"
                          : "请对照原件核对金额、日期和发票号码，再确认保存。"
                }}</span>
              </div>
              <div v-if="admin" class="iv-owner-line">
                <Users :size="14" />所属成员
                <strong>{{ drawer.record.ownerName }}</strong>
              </div>
              <form id="iv-form" @submit.prevent="save">
                <fieldset
                  :disabled="
                    drawer.busy ||
                    Boolean(drawer.record.deleted_at) ||
                    drawer.record.status === 'processing'
                  "
                >
                  <h3>基本信息</h3>
                  <div class="iv-fields">
                    <label class="full"
                      >销售方<input
                        v-model.trim="drawer.form.seller"
                        maxlength="512"
                        placeholder="填写销售方名称" /></label
                    ><label class="full"
                      >购买方<input
                        v-model.trim="drawer.form.buyer"
                        maxlength="512"
                        placeholder="填写购买方名称" /></label
                    ><label class="full"
                      >发票号码<input
                        v-model.trim="drawer.form.invoice_number"
                        maxlength="128"
                        placeholder="填写完整发票号码" /></label
                    ><label
                      >开票日期<input
                        v-model="drawer.form.invoice_date"
                        type="date" /></label
                    ><label
                      >用途分类<select v-model="drawer.form.category">
                        <option v-for="item in categories" :key="item">
                          {{ item }}
                        </option>
                      </select></label
                    >
                  </div>
                  <h3 class="iv-amount-heading">金额与备注</h3>
                  <div class="iv-fields">
                    <label
                      >未税金额（元）<input
                        v-model.trim="drawer.form.amount"
                        inputmode="decimal"
                        maxlength="20"
                        placeholder="0.00" /></label
                    ><label
                      >税额（元）<input
                        v-model.trim="drawer.form.tax_amount"
                        inputmode="decimal"
                        maxlength="20"
                        placeholder="0.00" /></label
                    ><label class="full"
                      >价税合计（元）<input
                        v-model.trim="drawer.form.total_amount"
                        inputmode="decimal"
                        maxlength="20"
                        placeholder="请核对含税总金额" /></label
                    ><label class="full"
                      >备注<textarea
                        v-model="drawer.form.notes"
                        maxlength="4000"
                        rows="3"
                        placeholder="报销用途、项目或其他补充信息…"
                      ></textarea>
                    </label>
                  </div>
                </fieldset>
                <p v-if="mismatch" class="iv-form-warning">
                  <AlertCircle
                    :size="15"
                  />未税金额与税额之和不等于价税合计，请对照原件核对。
                </p>
                <div v-if="drawer.error" class="iv-form-error" role="alert">
                  {{ drawer.error
                  }}<button
                    type="button"
                    class="iv-link"
                    :disabled="drawer.busy"
                    @click="refreshDrawer"
                  >
                    读取最新记录
                  </button>
                </div>
              </form>
              <div class="iv-metadata">
                <span>上传时间 {{ dateTime(drawer.record.created_at) }}</span
                ><span>最后更新 {{ dateTime(drawer.record.updated_at) }}</span>
              </div>
            </div>
          </div>
          <footer class="iv-drawer-footer">
            <template v-if="drawer.record.deleted_at"
              ><span>原件和发票信息均已保留</span
              ><button
                class="iv-button iv-primary"
                :disabled="drawer.busy"
                @click="restore"
              >
                <RotateCcw :size="16" />恢复发票
              </button></template
            ><template v-else
              ><button
                class="iv-button iv-danger"
                :disabled="drawer.busy || drawer.record.status === 'processing'"
                @click="remove"
              >
                <Trash2 :size="16" />删除
              </button>
              <div>
                <button
                  v-if="drawer.record.status === 'processing'"
                  class="iv-button"
                  :disabled="drawer.busy"
                  @click="refreshDrawer"
                >
                  <RefreshCw :size="16" />刷新识别结果</button
                ><button
                  v-else
                  class="iv-button"
                  :disabled="drawer.busy"
                  @click="recognize"
                >
                  <LoaderCircle
                    v-if="drawer.busy"
                    :size="16"
                    class="iv-spin"
                  /><ScanLine v-else :size="16" />{{
                    drawer.busy
                      ? "处理中…"
                      : drawer.record.status === "pending"
                        ? "开始识别"
                        : "重新识别"
                  }}</button
                ><button
                  class="iv-button iv-primary"
                  type="submit"
                  form="iv-form"
                  :disabled="
                    drawer.busy || drawer.record.status === 'processing'
                  "
                >
                  <Check :size="16" />确认并保存
                </button>
              </div></template
            >
          </footer></template
        >
      </section>
    </div>
    <div v-if="confirm" class="iv-confirm-mask" @click.self="answer(false)">
      <section
        class="iv-confirm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="iv-confirm-title"
      >
        <h2 id="iv-confirm-title">{{ confirm.title }}</h2>
        <p>{{ confirm.description }}</p>
        <div>
          <button class="iv-button" @click="answer(false)">取消</button
          ><button
            class="iv-button"
            :class="confirm.danger ? 'iv-danger-solid' : 'iv-primary'"
            @click="answer(true)"
          >
            {{ confirm.action }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.iv-page {
  color: #172337;
  --iv-line: #e8edf3;
  --iv-blue: #2563eb;
  font-size: 14px;
}
.iv-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 28px;
}
.iv-eyebrow {
  font-size: 11px;
  letter-spacing: 2px;
  color: #8190a5;
  font-weight: 700;
  margin-bottom: 9px;
}
.iv-heading h1 {
  font-size: 28px;
  letter-spacing: -0.8px;
  margin: 0 0 9px;
  font-weight: 700;
}
.iv-heading p {
  margin: 0;
  color: #8490a1;
  font-size: 13px;
}
.iv-button,
.iv-icon-button,
.iv-link,
.iv-tabs button,
.iv-record-name {
  font: inherit;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  text-decoration: none;
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
}
.iv-button {
  border: 1px solid #dfe6ef;
  color: #475569;
  background: #fff;
  border-radius: 8px;
  padding: 10px 15px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.iv-button:hover {
  background: #f8fafc;
  border-color: #c7d2e0;
}
.iv-primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
  box-shadow: 0 3px 7px #2563eb19;
}
.iv-primary:hover {
  background: #1d4ed8;
  border-color: #1d4ed8;
}
.iv-icon-button {
  background: transparent;
  border: 0;
  color: #8190a3;
  border-radius: 7px;
  padding: 8px;
}
.iv-icon-button:hover {
  background: #f1f5f9;
  color: #334155;
}
.iv-link {
  background: none;
  border: 0;
  padding: 3px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
}
.iv-button:disabled,
.iv-icon-button:disabled,
.iv-link:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.iv-button:focus-visible,
.iv-icon-button:focus-visible,
.iv-link:focus-visible,
.iv-tabs button:focus-visible,
.iv-record-name:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 2px;
}
.iv-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 17px;
  margin-bottom: 22px;
}
.iv-stat {
  background: #fff;
  border: 1px solid var(--iv-line);
  border-radius: 11px;
  padding: 20px;
  min-width: 0;
}
.iv-stat > div {
  display: flex;
  justify-content: space-between;
  color: #8591a3;
  font-size: 12px;
}
.iv-stat > div svg {
  color: #91a4c0;
}
.iv-stat > strong {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 28px;
  font-weight: 650;
  letter-spacing: -1px;
  margin: 16px 0 7px;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.iv-stat > strong small {
  color: #9ba5b3;
  font-size: 12px;
  letter-spacing: 0;
  font-weight: 400;
}
.iv-stat > strong.iv-stat-money {
  font-size: 26px;
}
.iv-stat > p {
  color: #9ba5b3;
  font-size: 11px;
  margin: 0;
}
.iv-drop {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px;
  border: 1px dashed #cad7eb;
  border-radius: 10px;
  background: #f8faff;
  margin-bottom: 24px;
}
.iv-drop.dragging {
  background: #edf4ff;
  border-color: #2563eb;
}
.iv-drop-icon {
  width: 46px;
  height: 46px;
  flex-shrink: 0;
  border-radius: 11px;
  background: #eaf1ff;
  display: grid;
  place-items: center;
  color: #477bdb;
}
.iv-drop > div:nth-child(2) {
  flex: 1;
}
.iv-drop strong {
  font-size: 14px;
  font-weight: 600;
}
.iv-drop p {
  font-size: 11px;
  color: #91a0b4;
  margin: 7px 0 0;
}
.iv-records,
.iv-queue {
  border: 1px solid var(--iv-line);
  border-radius: 11px;
  background: #fff;
  overflow: hidden;
}
.iv-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid var(--iv-line);
  height: 61px;
}
.iv-tabs {
  display: flex;
  height: 100%;
  gap: 26px;
}
.iv-tabs button {
  position: relative;
  background: none;
  border: 0;
  padding: 0;
  color: #8b97a8;
  font-size: 13px;
}
.iv-tabs button.active {
  color: #2563eb;
  font-weight: 600;
}
.iv-tabs button.active:after {
  content: "";
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 2px;
  background: #2563eb;
}
.iv-tabs button span {
  font-size: 10px;
  padding: 2px 6px;
  background: #edf4ff;
  border-radius: 4px;
  margin-left: 1px;
}
.iv-filters {
  display: flex;
  gap: 10px;
  padding: 18px 20px;
}
.iv-search {
  display: flex;
  align-items: center;
  gap: 9px;
  max-width: 390px;
  width: 100%;
  color: #93a1b4;
  border: 1px solid #e4eaf2;
  border-radius: 7px;
  padding: 0 11px;
}
.iv-search input {
  padding: 10px 0;
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  outline: none;
  font: inherit;
  font-size: 12px;
  color: #334155;
}
.iv-search:focus-within {
  outline: 2px solid #bfdbfe;
  border-color: #93c5fd;
}
.iv-filters select {
  border: 1px solid #e4eaf2;
  border-radius: 7px;
  font: inherit;
  font-size: 12px;
  color: #64748b;
  background: #fff;
  padding: 9px 26px 9px 11px;
  min-width: 106px;
}
.iv-filters input::placeholder {
  color: #a0aaba;
}
.iv-table-wrap {
  overflow-x: auto;
}
.iv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  text-align: left;
  white-space: nowrap;
}
.iv-table th {
  background: #f9fbfd;
  color: #91a0b2;
  font-size: 11px;
  font-weight: 500;
  padding: 12px 17px;
  border-top: 1px solid #f0f3f7;
  border-bottom: 1px solid #eef2f7;
}
.iv-table th:first-child,
.iv-table td:first-child {
  padding-left: 21px;
}
.iv-table td {
  padding: 18px 17px;
  border-bottom: 1px solid #f0f3f7;
}
.iv-table tbody tr:last-child td {
  border-bottom: 0;
}
.iv-table tbody tr:hover {
  background: #fcfdff;
}
.iv-identity {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 170px;
}
.iv-identity > div {
  min-width: 0;
  max-width: 240px;
}
.iv-file-icon {
  width: 35px;
  height: 39px;
  flex-shrink: 0;
  background: #eef5ff;
  border: 1px solid #e5edfa;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #759bd8;
}
.iv-file-icon.pdf {
  background: #fff3f0;
  border-color: #fbe7e0;
  color: #d88c72;
}
.iv-record-name {
  font-weight: 600;
  background: none;
  border: 0;
  color: #334155;
  padding: 0;
  max-width: 240px;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}
.iv-identity small {
  display: block;
  color: #a1abb9;
  font-size: 10px;
  margin-top: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 235px;
}
.iv-category {
  background: #f3f5f8;
  padding: 4px 7px;
  color: #8090a2;
  border-radius: 4px;
  font-size: 11px;
}
.iv-amount {
  font-weight: 600;
  color: #32445c;
  font-variant-numeric: tabular-nums;
}
.iv-date {
  color: #8b99aa;
  font-size: 11px;
}
.iv-status {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  font-size: 10px;
  background: #f1f5f9;
  color: #8493a5;
  padding: 5px 7px;
  border-radius: 5px;
  white-space: nowrap;
}
.iv-status i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
}
.iv-status.review {
  background: #fff6e6;
  color: #bb8833;
}
.iv-status.confirmed {
  background: #edf8f3;
  color: #369c75;
}
.iv-status.error {
  background: #fff0ee;
  color: #ca776b;
}
.iv-status.processing {
  background: #eff4ff;
  color: #4e80d3;
}
.iv-owner {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #8090a4;
  font-size: 11px;
}
.iv-table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid var(--iv-line);
  padding: 14px 20px;
  color: #a0abba;
  font-size: 10px;
}
.iv-table-footer > span:last-child {
  display: flex;
  align-items: center;
  gap: 5px;
}
.iv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 48px 25px 54px;
  color: #91a1b5;
  min-height: 220px;
  gap: 12px;
}
.iv-empty-icon {
  width: 67px;
  height: 67px;
  background: #f2f6fc;
  border: 1px solid #e8eef6;
  border-radius: 18px;
  display: grid;
  place-items: center;
  margin-bottom: 3px;
  color: #8aa8d1;
}
.iv-empty h3 {
  font-size: 15px;
  color: #65758c;
  font-weight: 500;
  margin: 0;
}
.iv-empty p {
  font-size: 12px;
  line-height: 1.7;
  max-width: 380px;
  margin: 0 0 3px;
  overflow-wrap: anywhere;
}
.iv-queue {
  margin-bottom: 22px;
}
.iv-queue-header {
  padding: 13px 18px;
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #edf1f6;
  font-size: 12px;
}
.iv-queue-header strong {
  font-weight: 500;
}
.iv-queue-header span {
  color: #9ca8b7;
  margin-left: 10px;
}
.iv-queue-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 18px;
  color: #80a18f;
}
.iv-queue-row + .iv-queue-row {
  border-top: 1px solid #f2f5f8;
}
.iv-queue-row > svg {
  flex-shrink: 0;
}
.iv-queue-row > div {
  flex: 1;
  min-width: 0;
}
.iv-queue-row strong {
  display: block;
  font-size: 12px;
  color: #56657a;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.iv-queue-row p {
  font-size: 11px;
  color: #95a1b1;
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}
.iv-red {
  color: #d48b80;
}
.iv-spin {
  animation: iv-spin 1s linear infinite;
}
@keyframes iv-spin {
  to {
    transform: rotate(360deg);
  }
}
.iv-mask,
.iv-confirm-mask {
  position: fixed;
  inset: 0;
  background: #14213b55;
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
  backdrop-filter: blur(2px);
  color: #26364c;
  font-family: inherit;
}
.iv-drawer {
  width: min(1020px, 96vw);
  height: 100%;
  background: #fff;
  box-shadow: -10px 0 50px #17223a18;
  display: flex;
  flex-direction: column;
  outline: none;
}
.iv-drawer-header {
  padding: 24px 28px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 1px solid #e9eef4;
  gap: 20px;
  flex-shrink: 0;
}
.iv-drawer-header > div {
  min-width: 0;
}
.iv-title-row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.iv-title-row h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}
.iv-drawer-header p {
  font-size: 11px;
  color: #97a3b3;
  margin: 8px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 720px;
}
.iv-drawer-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  min-height: 0;
  flex: 1;
}
.iv-preview {
  background: #f7f9fc;
  padding: 23px;
  border-right: 1px solid #e9eef4;
  overflow: auto;
}
.iv-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.iv-preview-header strong {
  font-size: 12px;
  font-weight: 600;
}
.iv-image-stage {
  background: #eaf0f6;
  border: 1px solid #e3eaf3;
  border-radius: 8px;
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.iv-image-stage img {
  display: block;
  max-width: 100%;
  height: auto;
  object-fit: contain;
}
.iv-preview-caption {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  color: #9ca9bb;
  font-size: 10px;
  line-height: 1.8;
  margin: 14px 0;
}
.iv-preview-caption svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.iv-details {
  padding: 24px;
  overflow-y: auto;
  min-width: 0;
}
.iv-banner {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  background: #f0f6ff;
  border: 1px solid #e2edfe;
  color: #7891b9;
  padding: 12px;
  border-radius: 7px;
  font-size: 11px;
  line-height: 1.7;
  margin-bottom: 23px;
}
.iv-banner.error {
  background: #fff6f3;
  border-color: #fae7e1;
  color: #bb8b7b;
}
.iv-banner svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.iv-owner-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #94a0b0;
  font-size: 11px;
  margin-bottom: 20px;
}
.iv-owner-line strong {
  color: #60748e;
  font-weight: 500;
}
.iv-details fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.iv-details h3 {
  font-size: 12px;
  color: #5d6f87;
  margin: 0 0 15px;
  font-weight: 600;
}
.iv-details .iv-amount-heading {
  margin-top: 24px;
  padding-top: 22px;
  border-top: 1px solid #edf1f6;
}
.iv-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 12px;
}
.iv-fields label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 11px;
  color: #94a0b0;
  min-width: 0;
}
.iv-fields .full {
  grid-column: 1/-1;
}
.iv-fields input,
.iv-fields select,
.iv-fields textarea {
  font: inherit;
  font-size: 12px;
  color: #4e617a;
  border: 1px solid #dfe6f0;
  border-radius: 6px;
  background: #fff;
  padding: 10px 11px;
  min-width: 0;
  max-width: 100%;
  width: 100%;
  box-sizing: border-box;
  outline: none;
}
.iv-fields input:focus,
.iv-fields select:focus,
.iv-fields textarea:focus {
  border-color: #93b9fa;
  box-shadow: 0 0 0 3px #eaf2ff;
}
.iv-fields input::placeholder,
.iv-fields textarea::placeholder {
  color: #b7bfcb;
}
.iv-fields textarea {
  resize: vertical;
  min-height: 80px;
  line-height: 1.7;
}
.iv-fields :disabled {
  background: #f7f9fc;
  color: #a3adbd;
}
.iv-form-warning {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 11px;
  line-height: 1.7;
  color: #b9955f;
  background: #fffaf0;
  padding: 10px;
  border-radius: 5px;
}
.iv-form-warning svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.iv-form-error {
  font-size: 12px;
  line-height: 1.8;
  color: #c27870;
  margin-top: 15px;
  overflow-wrap: anywhere;
}
.iv-form-error button {
  display: block;
  margin-top: 5px;
}
.iv-metadata {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 10px;
  color: #acb6c3;
  margin-top: 25px;
}
.iv-drawer-footer {
  border-top: 1px solid #e9eef4;
  padding: 18px 25px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}
.iv-drawer-footer > div {
  display: flex;
  gap: 10px;
}
.iv-drawer-footer > span {
  font-size: 11px;
  color: #97a4b6;
}
.iv-danger {
  border-color: #edd9d6;
  color: #bb8179;
  background: #fff;
}
.iv-danger:hover {
  background: #fff5f3;
  border-color: #e8c5bf;
}
.iv-confirm-mask {
  align-items: center;
  justify-content: center;
  z-index: 1100;
  padding: 20px;
  background: #14213b66;
}
.iv-confirm {
  width: min(410px, 100%);
  padding: 26px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 20px 80px #1b2c4233;
}
.iv-confirm h2 {
  font-size: 17px;
  margin: 0 0 13px;
  font-weight: 600;
}
.iv-confirm p {
  font-size: 13px;
  line-height: 1.8;
  color: #8b99ad;
  margin: 0;
}
.iv-confirm > div {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 25px;
}
.iv-danger-solid {
  background: #c46e63;
  border-color: #c46e63;
  color: #fff;
}
.iv-danger-solid:hover {
  background: #ac5c52;
  border-color: #ac5c52;
}
@media (max-width: 1100px) {
  .iv-stats {
    gap: 12px;
  }
  .iv-stat {
    padding: 16px;
  }
  .iv-stat > strong.iv-stat-money {
    font-size: 22px;
  }
  .iv-drawer {
    width: min(900px, 100vw);
  }
}
@media (max-width: 720px) {
  .iv-heading {
    margin-bottom: 22px;
    gap: 12px;
  }
  .iv-heading h1 {
    font-size: 23px;
  }
  .iv-heading p {
    font-size: 11px;
    line-height: 1.6;
  }
  .iv-heading .iv-button {
    padding: 10px 11px;
  }
  .iv-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .iv-stat > strong,
  .iv-stat > strong.iv-stat-money {
    font-size: 23px;
  }
  .iv-stat > p {
    font-size: 10px;
  }
  .iv-drop {
    flex-wrap: wrap;
    gap: 12px;
    padding: 18px;
  }
  .iv-drop > div:nth-child(2) {
    min-width: 160px;
  }
  .iv-drop p {
    font-size: 10px;
    line-height: 1.8;
  }
  .iv-drop > .iv-button {
    width: 100%;
    margin-top: 2px;
  }
  .iv-drop-icon {
    width: 39px;
    height: 39px;
  }
  .iv-filters {
    flex-wrap: wrap;
    padding: 14px;
    gap: 8px;
  }
  .iv-search {
    max-width: none;
    box-sizing: border-box;
    flex-basis: 100%;
  }
  .iv-filters select {
    flex: 1;
    min-width: 0;
  }
  .iv-toolbar {
    padding: 0 14px;
  }
  .iv-table-footer {
    padding: 13px;
    flex-wrap: wrap;
  }
  .iv-drawer {
    width: 100vw;
  }
  .iv-drawer-header {
    padding: 19px;
  }
  .iv-drawer-main {
    display: block;
    overflow-y: auto;
  }
  .iv-preview {
    padding: 19px;
    border-right: 0;
    border-bottom: 1px solid #e9eef4;
    overflow: visible;
  }
  .iv-image-stage {
    min-height: 150px;
    max-height: 360px;
  }
  .iv-image-stage img {
    max-height: 360px;
    width: 100%;
    object-fit: contain;
  }
  .iv-details {
    padding: 20px;
    overflow: visible;
  }
  .iv-drawer-footer {
    padding: 13px 14px;
  }
  .iv-drawer-footer .iv-button {
    padding: 10px 9px;
    font-size: 11px;
    gap: 5px;
  }
  .iv-drawer-footer > div {
    gap: 6px;
  }
  .iv-drawer-footer .iv-button svg {
    width: 14px;
  }
  .iv-confirm {
    padding: 23px;
  }
  .iv-table {
    font-size: 11px;
  }
  .iv-record-name {
    max-width: 175px;
  }
  .iv-identity > div {
    max-width: 175px;
  }
  .iv-title-row h2 {
    font-size: 17px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .iv-spin {
    animation: none;
  }
  .iv-button,
  .iv-icon-button,
  .iv-link {
    transition: none;
  }
}
</style>
