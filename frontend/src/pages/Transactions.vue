<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute } from "vue-router";
import {
  ArrowDownLeft,
  ArrowRightLeft,
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  Download,
  FileText,
  Loader2,
  Plus,
  ReceiptText,
  RefreshCw,
  Search,
  ShieldCheck,
  Star,
  Trash2,
  Wallet,
  X,
} from "lucide-vue-next";
import FlowEditor from "../components/FlowEditor.vue";
import { api } from "../lib/api.js";
import { bus, notify, state } from "../lib/app.js";
import { money, monthLabel, today } from "../lib/format.js";

const month = ref(today().slice(0, 7));
const route = useRoute();
const rows = ref([]);
const accounts = ref([]);
const loading = ref(true);
const error = ref("");
const query = ref("");
const selectedAccount = ref("");
const selectedStatus = ref(
  ["pending", "approved", "rejected"].includes(route.query.status)
    ? route.query.status
    : "",
);
const selectedHandle = ref(3);
const onlyCollected = ref(false);
const page = ref(1);
const pageSize = 15;
const editorOpen = ref(false);
const editorId = ref(null);
const editorInitial = ref(1);
const collecting = ref(new Set());
const actionDialog = ref(null);
const actionPanel = ref(null);
const dialogBusy = ref(false);
const dialogError = ref("");
const reviewComment = ref("");
let loadSequence = 0;
let previousFocus = null;
let previousOverflow = "";

const isAdmin = computed(() => state.user?.role === "admin");
const tabs = [
  { value: 3, label: "全部流水" },
  { value: 1, label: "支出", icon: ArrowUpRight },
  { value: 0, label: "收入", icon: ArrowDownLeft },
  { value: 2, label: "转账", icon: ArrowRightLeft },
];
const statuses = { pending: "待审核", approved: "已审核", rejected: "已驳回" };
const directions = { 0: "income", 1: "expense", 2: "transfer" };

function normalize(row) {
  return {
    ...row,
    handle: Number(row.handle ?? row.action?.handle ?? 1),
    fdate: String(row.fdate || row.fDate || "").slice(0, 10),
    tname: row.tname || row.type?.tname || "未分类",
    hname: row.hname || row.action?.hname || "",
    aname:
      row.aname ||
      row.account?.name ||
      row.account?.aname ||
      row.accountName ||
      "未指定账户",
    toAName:
      row.toAName ||
      row.toaname ||
      row.toAname ||
      row.accountTo?.name ||
      row.accountTo?.aname ||
      row.accountToName ||
      "",
    status: row.status || row.reviewStatus || "approved",
    ownerName:
      row.ownerName ||
      row.owner?.name ||
      row.user?.name ||
      row.createdByName ||
      row.created_by_name ||
      "",
    collect: Boolean(row.collect),
    exempt: Boolean(row.exempt ?? row.action?.exempt),
  };
}
function cents(value) {
  const match = String(value ?? "0").match(/^(-?)(\d+)(?:\.(\d{0,2}))?$/);
  return match
    ? (match[1] ? -1n : 1n) *
        (BigInt(match[2]) * 100n + BigInt((match[3] || "").padEnd(2, "0")))
    : 0n;
}
function decimal(value) {
  const absolute = value < 0n ? -value : value;
  return `${value < 0n ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}
const monthly = computed(() => {
  let income = 0n,
    expense = 0n;
  for (const row of rows.value) {
    if (row.exempt || row.status !== "approved") continue;
    if (row.handle === 0) income += cents(row.money);
    if (row.handle === 1) expense += cents(row.money);
  }
  return {
    income: decimal(income),
    expense: decimal(expense),
    net: decimal(income - expense),
    pending: rows.value.filter((row) => row.status === "pending").length,
  };
});
const filtered = computed(() => {
  const search = query.value.trim().toLocaleLowerCase();
  const account = accounts.value.find(
    (item) => String(item.id) === selectedAccount.value,
  );
  return rows.value
    .filter((row) => {
      if (selectedHandle.value !== 3 && row.handle !== selectedHandle.value)
        return false;
      if (selectedStatus.value && row.status !== selectedStatus.value)
        return false;
      if (onlyCollected.value && !row.collect) return false;
      if (selectedAccount.value) {
        const ids = [
          row.accountId,
          row.account?.id,
          row.accountToId,
          row.accountTo?.id,
        ]
          .filter((value) => value !== undefined && value !== null)
          .map(String);
        if (
          !ids.includes(selectedAccount.value) &&
          !(
            account &&
            [row.aname, row.toAName].includes(account.name || account.aname)
          )
        )
          return false;
      }
      return (
        !search ||
        [
          row.note,
          row.tname,
          row.hname,
          row.aname,
          row.toAName,
          row.ownerName,
          row.money,
          row.fdate,
        ].some((value) =>
          String(value || "")
            .toLocaleLowerCase()
            .includes(search),
        )
      );
    })
    .sort(
      (a, b) =>
        b.fdate.localeCompare(a.fdate) ||
        String(b.id).localeCompare(String(a.id), undefined, { numeric: true }),
    );
});
const pageCount = computed(() =>
  Math.max(1, Math.ceil(filtered.value.length / pageSize)),
);
const displayed = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
);
const rangeStart = computed(() =>
  filtered.value.length ? (page.value - 1) * pageSize + 1 : 0,
);
const rangeEnd = computed(() =>
  Math.min(page.value * pageSize, filtered.value.length),
);
const activeFilters = computed(() =>
  Boolean(
    query.value ||
      selectedAccount.value ||
      selectedStatus.value ||
      onlyCollected.value ||
      selectedHandle.value !== 3,
  ),
);
const filteredTotal = computed(() => {
  const values = filtered.value.filter(
    (row) => row.status === "approved" && !row.exempt && row.handle !== 2,
  );
  return decimal(
    values.reduce(
      (sum, row) =>
        sum + (row.handle === 0 ? cents(row.money) : -cents(row.money)),
      0n,
    ),
  );
});
const dialogTitle = computed(() =>
  actionDialog.value?.kind === "delete"
    ? "删除这笔流水？"
    : actionDialog.value?.kind === "reject"
      ? "驳回这笔流水"
      : "确认通过审核？",
);
const dialogPrimary = computed(() =>
  actionDialog.value?.kind === "delete"
    ? "确认删除"
    : actionDialog.value?.kind === "reject"
      ? "驳回申请"
      : "通过审核",
);

async function load() {
  const sequence = ++loadSequence;
  loading.value = true;
  error.value = "";
  try {
    const [data, accountData] = await Promise.all([
      api(`/flow/getFlowListMain/3/0/${encodeURIComponent(month.value)}`),
      api("/account/getAccount"),
    ]);
    if (sequence !== loadSequence) return;
    rows.value = (
      Array.isArray(data) ? data : data?.flows || data?.items || []
    ).map(normalize);
    accounts.value = Array.isArray(accountData)
      ? accountData
      : accountData?.items || [];
    page.value = Math.min(page.value, pageCount.value);
  } catch (cause) {
    if (sequence === loadSequence)
      error.value = cause.message || "无法读取流水，请检查网络后重试。";
  } finally {
    if (sequence === loadSequence) loading.value = false;
  }
}
function shiftMonth(amount) {
  const [year, value] = month.value.split("-").map(Number);
  const date = new Date(year, value - 1 + amount, 1);
  month.value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
function updateMonth(event) {
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value))
    month.value = event.target.value;
}
function clearFilters() {
  query.value = "";
  selectedAccount.value = "";
  selectedStatus.value = "";
  onlyCollected.value = false;
  selectedHandle.value = 3;
}
function openEditor(row = null) {
  editorId.value = row?.id ?? null;
  editorInitial.value = row
    ? row.handle
    : selectedHandle.value === 3
      ? 1
      : selectedHandle.value;
  editorOpen.value = true;
}
function canEdit(row) {
  return isAdmin.value || row.status !== "approved";
}
function amountPrefix(row) {
  return row.handle === 0 ? "+" : row.handle === 1 ? "−" : "";
}
function accountLabel(row) {
  return row.handle === 2 && row.toAName
    ? `${row.aname} → ${row.toAName}`
    : row.aname;
}
function dateLabel(value) {
  if (!value) return "日期未填写";
  const parts = value.split("-");
  return `${Number(parts[1])}月${Number(parts[2])}日`;
}
function weekday(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  return new Date(`${value}T12:00:00`).toLocaleDateString("zh-CN", {
    weekday: "short",
  });
}

async function toggleCollect(row) {
  if (collecting.value.has(row.id) || !canEdit(row)) return;
  collecting.value = new Set([...collecting.value, row.id]);
  try {
    const result = await api(
      `/flow/collectFlow/${encodeURIComponent(row.id)}/${row.collect ? 0 : 1}`,
      { method: "PUT" },
    );
    if (result?.id !== undefined) Object.assign(row, normalize(result));
    else row.collect = !row.collect;
    notify(row.collect ? "已收藏这笔流水" : "已取消收藏");
  } catch (cause) {
    notify(cause.message || "收藏状态更新失败", "error");
  } finally {
    const ids = new Set(collecting.value);
    ids.delete(row.id);
    collecting.value = ids;
  }
}

function openAction(kind, row) {
  if (
    (kind === "delete" && !canEdit(row)) ||
    (kind !== "delete" && (!isAdmin.value || row.status !== "pending"))
  )
    return;
  previousFocus = document.activeElement;
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  actionDialog.value = { kind, row };
  dialogError.value = "";
  reviewComment.value = "";
  nextTick(() => actionPanel.value?.querySelector("button")?.focus());
}
function closeAction() {
  if (dialogBusy.value) return;
  actionDialog.value = null;
  document.body.style.overflow = previousOverflow;
  if (previousFocus?.isConnected) previousFocus.focus();
}
async function performAction() {
  if (!actionDialog.value || dialogBusy.value) return;
  const { kind, row } = actionDialog.value;
  if (kind === "reject" && !reviewComment.value.trim()) {
    dialogError.value = "请填写驳回原因，方便提交人修改。";
    return;
  }
  dialogBusy.value = true;
  dialogError.value = "";
  try {
    if (kind === "delete")
      await api(`/flow/deleteFlow/${encodeURIComponent(row.id)}`, {
        method: "DELETE",
        query: { version: row.version },
      });
    else
      await api(`/flow/reviewFlow/${encodeURIComponent(row.id)}`, {
        method: "POST",
        body: {
          status: kind === "approve" ? "approved" : "rejected",
          comment: reviewComment.value.trim(),
          version: row.version,
        },
      });
    notify(
      kind === "delete"
        ? "流水已删除"
        : kind === "approve"
          ? "已通过审核"
          : "已驳回，提交人可以修改后重新提交",
    );
    dialogBusy.value = false;
    closeAction();
    bus.dispatchEvent(new Event("ledger-change"));
  } catch (cause) {
    dialogError.value = cause.message || "操作未完成，请稍后重试。";
  } finally {
    dialogBusy.value = false;
  }
}
function keydown(event) {
  if (!actionDialog.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeAction();
    return;
  }
  if (event.key !== "Tab") return;
  const nodes = [
    ...(actionPanel.value?.querySelectorAll(
      "button:not(:disabled),textarea:not(:disabled)",
    ) || []),
  ];
  if (!nodes.length) {
    event.preventDefault();
    return;
  }
  const first = nodes[0],
    last = nodes[nodes.length - 1];
  if (
    event.shiftKey &&
    (document.activeElement === first ||
      !actionPanel.value.contains(document.activeElement))
  ) {
    event.preventDefault();
    last.focus();
  } else if (
    !event.shiftKey &&
    (document.activeElement === last ||
      !actionPanel.value.contains(document.activeElement))
  ) {
    event.preventDefault();
    first.focus();
  }
}

function exportCsv() {
  if (!filtered.value.length) return;
  const cell = (value) => {
    let text = String(value ?? "");
    if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  const headers = [
    "日期",
    "收支",
    "操作",
    "分类",
    "金额（元）",
    "来源账户",
    "转入账户",
    "状态",
    "提交人",
    "备注",
    "收藏",
    "不计入统计",
  ];
  const lines = [
    headers,
    ...filtered.value.map((row) => [
      row.fdate,
      row.handle === 0 ? "收入" : row.handle === 1 ? "支出" : "转账",
      row.hname,
      row.tname,
      row.money,
      row.aname,
      row.toAName,
      statuses[row.status] || row.status,
      row.ownerName,
      row.note,
      row.collect ? "是" : "否",
      row.exempt ? "是" : "否",
    ]),
  ];
  const blob = new Blob(
    ["\ufeff", lines.map((line) => line.map(cell).join(",")).join("\r\n")],
    { type: "text/csv;charset=utf-8;" },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `账序-流水-${month.value}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notify(`已导出当前筛选的 ${filtered.value.length} 条流水`);
}

watch(month, () => {
  page.value = 1;
  load();
});
watch(
  () => route.query.status,
  (value) => {
    selectedStatus.value = ["pending", "approved", "rejected"].includes(value)
      ? value
      : "";
  },
);
watch(
  [query, selectedAccount, selectedStatus, selectedHandle, onlyCollected],
  () => {
    page.value = 1;
  },
);
watch(pageCount, (value) => {
  if (page.value > value) page.value = value;
});
onMounted(() => {
  load();
  bus.addEventListener("ledger-change", load);
  document.addEventListener("keydown", keydown);
});
onBeforeUnmount(() => {
  loadSequence++;
  bus.removeEventListener("ledger-change", load);
  document.removeEventListener("keydown", keydown);
  if (actionDialog.value) document.body.style.overflow = previousOverflow;
});
</script>

<template>
  <div class="transactions-page">
    <header class="page-header transactions-heading">
      <div>
        <div class="page-eyebrow">TRANSACTIONS</div>
        <h1>收支流水<span class="heading-dot">.</span></h1>
        <p>
          {{
            isAdmin
              ? "当前账本的收入与支出，清楚记录，轻松核对。"
              : "记录工作中的每一笔收支，提交后由管理员审核。"
          }}
        </p>
      </div>
      <div class="heading-actions">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="loading || !filtered.length || Boolean(error)"
          @click="exportCsv"
        >
          <Download :size="16" /><span>导出流水</span></button
        ><button class="btn btn-primary" type="button" @click="openEditor()">
          <Plus :size="18" />记一笔
        </button>
      </div>
    </header>

    <section class="month-overview" aria-label="本月收支概览">
      <div class="month-control">
        <div class="month-card-heading">
          <span class="month-heading-label"
            ><CalendarDays :size="17" />账本月份</span
          >
          <div class="month-stepper" role="group" aria-label="切换月份">
            <button
              class="icon-btn"
              type="button"
              aria-label="上个月"
              @click="shiftMonth(-1)"
            >
              <ChevronLeft :size="16" />
            </button>
            <button
              class="icon-btn"
              type="button"
              aria-label="下个月"
              @click="shiftMonth(1)"
            >
              <ChevronRight :size="16" />
            </button>
          </div>
        </div>
        <div class="month-picker">
          <label
            ><span>{{ monthLabel(month).replaceAll(" ", "") }}</span
            ><input
              :value="month"
              type="month"
              aria-label="选择月份"
              @change="updateMonth" /><ChevronDown :size="14"
          /></label>
        </div>
        <button
          v-if="month !== today().slice(0, 7)"
          class="back-to-now"
          type="button"
          @click="month = today().slice(0, 7)"
        >
          回到本月</button
        ><span v-else class="month-caption"
          >{{ rows.length }} 笔记录 · 仅汇总已审核收支</span
        >
      </div>
      <div class="month-stat">
        <span><i class="metric-dot income"></i>本月收入</span
        ><strong :class="{ faded: loading }"
          ><small>¥</small>{{ error ? "—" : money(monthly.income) }}</strong
        ><small>已审核 · 不含豁免操作</small>
      </div>
      <div class="month-stat">
        <span><i class="metric-dot expense"></i>本月支出</span
        ><strong :class="{ faded: loading }"
          ><small>¥</small>{{ error ? "—" : money(monthly.expense) }}</strong
        ><small>已审核 · 不含内部转账</small>
      </div>
      <div class="month-stat">
        <span><i class="metric-dot net"></i>本月结余</span
        ><strong :class="{ faded: loading }"
          ><small>¥</small>{{ error ? "—" : money(monthly.net) }}</strong
        ><small>收入与支出的差额</small>
      </div>
    </section>

    <section
      v-if="!loading && !error && monthly.pending"
      class="pending-banner"
    >
      <div class="pending-icon"><Clock3 :size="18" /></div>
      <div>
        <strong>{{ monthly.pending }} 笔流水等待审核</strong>
        <p>
          {{
            isAdmin
              ? "核对提交信息后，通过或驳回申请。待审核金额不会计入上方汇总。"
              : "管理员审核通过后，将计入正式收支汇总。"
          }}
        </p>
      </div>
      <button type="button" @click="selectedStatus = 'pending'">
        查看待审核<ChevronRight :size="15" />
      </button>
    </section>

    <section class="card ledger-card" aria-label="流水记录">
      <div class="table-toolbar">
        <div class="flow-tabs" role="group" aria-label="收支类型">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            type="button"
            :class="{ active: selectedHandle === tab.value }"
            :aria-pressed="selectedHandle === tab.value"
            @click="selectedHandle = tab.value"
          >
            <component :is="tab.icon" v-if="tab.icon" :size="14" />{{ tab.label
            }}<span v-if="tab.value === 3" class="tab-number">{{
              rows.length
            }}</span>
          </button>
        </div>
        <button
          class="icon-btn refresh-button"
          type="button"
          aria-label="刷新流水"
          title="刷新流水"
          :disabled="loading"
          @click="load"
        >
          <RefreshCw :size="16" :class="{ spin: loading }" />
        </button>
      </div>
      <div class="filter-row">
        <label class="search-input"
          ><Search :size="16" /><input
            v-model="query"
            type="search"
            placeholder="搜索备注、分类或交易金额…"
            aria-label="搜索流水" /></label
        ><label class="filter-select"
          ><Wallet :size="14" /><select
            v-model="selectedAccount"
            aria-label="筛选账户"
          >
            <option value="">全部账户</option>
            <option
              v-for="account in accounts"
              :key="account.id"
              :value="String(account.id)"
            >
              {{ account.name || account.aname }}
            </option></select
          ><ChevronDown :size="13" /></label
        ><label class="filter-select"
          ><ShieldCheck :size="14" /><select
            v-model="selectedStatus"
            aria-label="筛选审核状态"
          >
            <option value="">全部状态</option>
            <option value="pending">待审核</option>
            <option value="approved">已审核</option>
            <option value="rejected">已驳回</option></select
          ><ChevronDown :size="13" /></label
        ><button
          class="collection-filter"
          type="button"
          :class="{ active: onlyCollected }"
          :aria-pressed="onlyCollected"
          aria-label="只看收藏"
          @click="onlyCollected = !onlyCollected"
        >
          <Star :size="15" /><span>收藏</span>
        </button>
      </div>

      <div v-if="loading" class="table-loading" aria-live="polite">
        <div v-for="index in 5" :key="index" class="skeleton-row">
          <i></i><span></span><span></span><span></span><span></span>
        </div>
        <span class="sr-only">正在加载流水</span>
      </div>
      <div v-else-if="error" class="empty-state">
        <div class="empty-icon error"><CircleAlert :size="28" /></div>
        <h2>流水暂时未能加载</h2>
        <p>{{ error }}</p>
        <button class="btn btn-secondary" type="button" @click="load">
          <RefreshCw :size="15" />重新加载
        </button>
      </div>
      <div v-else-if="!filtered.length" class="empty-state">
        <div class="empty-icon">
          <Search v-if="activeFilters" :size="29" /><ReceiptText
            v-else
            :size="30"
          />
        </div>
        <h2>
          {{
            activeFilters ? "没有找到符合条件的流水" : "这个月，从一笔记录开始"
          }}
        </h2>
        <p>
          {{
            activeFilters
              ? "换个关键词，或清除筛选后重新查找。"
              : "记录收入、支出与账户转账，让每笔资金流向都有依据。"
          }}
        </p>
        <button
          v-if="activeFilters"
          class="btn btn-secondary"
          type="button"
          @click="clearFilters"
        >
          清除筛选</button
        ><button
          v-else
          class="btn btn-primary"
          type="button"
          @click="openEditor()"
        >
          <Plus :size="16" />记录第一笔
        </button>
      </div>
      <template v-else>
        <div class="desktop-table">
          <table>
            <thead>
              <tr>
                <th class="favorite-column">
                  <span class="sr-only">收藏</span>
                </th>
                <th>交易信息</th>
                <th>账户</th>
                <th class="amount-column">金额 / 元</th>
                <th>日期</th>
                <th>状态</th>
                <th class="action-column">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in displayed" :key="row.id">
                <td class="favorite-column">
                  <button
                    class="star-button"
                    type="button"
                    :class="{ selected: row.collect }"
                    :aria-label="row.collect ? '取消收藏' : '收藏流水'"
                    :disabled="collecting.has(row.id) || !canEdit(row)"
                    @click="toggleCollect(row)"
                  >
                    <Star :size="14" />
                  </button>
                </td>
                <td>
                  <div class="transaction-identity">
                    <div
                      class="transaction-icon"
                      :class="directions[row.handle]"
                    >
                      <ArrowDownLeft
                        v-if="row.handle === 0"
                        :size="17"
                      /><ArrowRightLeft
                        v-else-if="row.handle === 2"
                        :size="17"
                      /><ArrowUpRight v-else :size="17" />
                    </div>
                    <div class="transaction-description">
                      <button
                        class="row-title"
                        type="button"
                        :title="row.tname"
                        @click="openEditor(row)"
                      >
                        {{ row.tname.replace(/——/g, " / ") }}</button
                      ><span :title="row.note || row.hname"
                        >{{ row.note || row.hname || "暂无备注"
                        }}<FileText
                          v-if="row.hasImages || row.images?.length"
                          :size="11"
                      /></span>
                    </div>
                  </div>
                </td>
                <td>
                  <div class="account-cell" :title="accountLabel(row)">
                    {{ accountLabel(row) }}
                  </div>
                  <small v-if="isAdmin && row.ownerName" class="owner-name">{{
                    row.ownerName
                  }}</small>
                </td>
                <td class="amount-column">
                  <span class="row-amount" :class="directions[row.handle]"
                    >{{ amountPrefix(row) }}{{ money(row.money) }}</span
                  ><small v-if="row.exempt" class="exempt-label"
                    >不计入统计</small
                  >
                </td>
                <td>
                  <span class="date-value">{{ dateLabel(row.fdate) }}</span
                  ><small class="weekday">{{ weekday(row.fdate) }}</small>
                </td>
                <td>
                  <span class="review-status" :class="row.status"
                    ><i></i>{{ statuses[row.status] || row.status }}</span
                  >
                </td>
                <td class="action-column">
                  <div
                    v-if="isAdmin && row.status === 'pending'"
                    class="approval-buttons"
                  >
                    <button
                      class="approval-button"
                      type="button"
                      title="通过审核"
                      aria-label="通过审核"
                      @click="openAction('approve', row)"
                    >
                      <Check :size="16" /></button
                    ><button
                      class="approval-button reject"
                      type="button"
                      title="驳回"
                      aria-label="驳回"
                      @click="openAction('reject', row)"
                    >
                      <X :size="15" />
                    </button>
                  </div>
                  <div v-else class="row-actions">
                    <button
                      type="button"
                      class="view-button"
                      @click="openEditor(row)"
                    >
                      {{ canEdit(row) ? "编辑" : "详情" }}</button
                    ><button
                      v-if="canEdit(row)"
                      type="button"
                      class="delete-button"
                      aria-label="删除流水"
                      title="删除流水"
                      @click="openAction('delete', row)"
                    >
                      <Trash2 :size="14" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mobile-transactions">
          <article
            v-for="row in displayed"
            :key="row.id"
            class="mobile-transaction"
          >
            <div class="mobile-row-top">
              <div class="transaction-identity">
                <div class="transaction-icon" :class="directions[row.handle]">
                  <ArrowDownLeft
                    v-if="row.handle === 0"
                    :size="18"
                  /><ArrowRightLeft
                    v-else-if="row.handle === 2"
                    :size="18"
                  /><ArrowUpRight v-else :size="18" />
                </div>
                <div class="transaction-description">
                  <button
                    type="button"
                    class="row-title"
                    @click="openEditor(row)"
                  >
                    {{ row.tname.replace(/——/g, " / ") }}</button
                  ><span>{{ row.note || row.hname || accountLabel(row) }}</span>
                </div>
              </div>
              <span class="row-amount" :class="directions[row.handle]"
                >{{ amountPrefix(row) }}{{ money(row.money) }}</span
              >
            </div>
            <div class="mobile-row-meta">
              <span>{{ dateLabel(row.fdate) }} · {{ accountLabel(row) }}</span
              ><span class="review-status" :class="row.status"
                ><i></i>{{ statuses[row.status] || row.status }}</span
              >
            </div>
            <div class="mobile-row-actions">
              <button
                class="star-button"
                type="button"
                :class="{ selected: row.collect }"
                :disabled="collecting.has(row.id) || !canEdit(row)"
                @click="toggleCollect(row)"
              >
                <Star :size="13" />{{ row.collect ? "已收藏" : "收藏" }}</button
              ><span v-if="isAdmin && row.ownerName" class="owner-name">{{
                row.ownerName
              }}</span>
              <div v-if="isAdmin && row.status === 'pending'">
                <button
                  class="mobile-approve"
                  type="button"
                  @click="openAction('approve', row)"
                >
                  <Check :size="13" />通过</button
                ><button
                  class="mobile-reject"
                  type="button"
                  @click="openAction('reject', row)"
                >
                  驳回
                </button>
              </div>
              <div v-else>
                <button
                  class="view-button"
                  type="button"
                  @click="openEditor(row)"
                >
                  {{ canEdit(row) ? "编辑" : "查看详情" }}</button
                ><button
                  v-if="canEdit(row)"
                  class="delete-button"
                  type="button"
                  aria-label="删除流水"
                  @click="openAction('delete', row)"
                >
                  <Trash2 :size="13" />
                </button>
              </div>
            </div>
          </article>
        </div>
      </template>
      <footer class="table-footer">
        <div>
          <span v-if="!error"
            >共 {{ filtered.length }} 笔<span v-if="filtered.length"
              >，显示 {{ rangeStart }}–{{ rangeEnd }}</span
            ></span
          ><span v-else>读取未完成</span
          ><span
            v-if="!loading && !error && activeFilters && filtered.length"
            class="filtered-net"
            >筛选内已审核净额 <b>¥ {{ money(filteredTotal) }}</b></span
          >
        </div>
        <nav class="pagination" aria-label="流水分页">
          <button
            class="icon-btn"
            type="button"
            :disabled="page === 1 || loading"
            aria-label="上一页"
            @click="page--"
          >
            <ChevronLeft :size="15" /></button
          ><span
            ><b>{{ page }}</b> / {{ pageCount }}</span
          ><button
            class="icon-btn"
            type="button"
            :disabled="page >= pageCount || loading"
            aria-label="下一页"
            @click="page++"
          >
            <ChevronRight :size="15" />
          </button>
        </nav>
      </footer>
    </section>
    <div class="ledger-footnote">
      <ShieldCheck :size="13" /><span>{{
        isAdmin
          ? "当前账本 · 重要操作可在日志中查看"
          : "个人提交记录 · 审核通过后计入组织账本"
      }}</span>
    </div>
    <FlowEditor
      v-model="editorOpen"
      :flow-id="editorId"
      :initial-type="editorInitial"
    />

    <Teleport to="body"
      ><div
        v-if="actionDialog"
        class="action-overlay"
        @mousedown.self="closeAction"
      >
        <section
          ref="actionPanel"
          class="action-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="action-dialog-title"
          :aria-busy="dialogBusy"
          tabindex="-1"
        >
          <header>
            <div class="dialog-symbol" :class="actionDialog.kind">
              <Trash2 v-if="actionDialog.kind === 'delete'" :size="23" /><X
                v-else-if="actionDialog.kind === 'reject'"
                :size="23"
              /><ShieldCheck v-else :size="24" />
            </div>
            <button
              class="icon-btn"
              type="button"
              aria-label="关闭确认"
              :disabled="dialogBusy"
              @click="closeAction"
            >
              <X :size="18" />
            </button>
          </header>
          <h2 id="action-dialog-title">{{ dialogTitle }}</h2>
          <p>
            {{
              actionDialog.kind === "delete"
                ? "删除后将无法恢复。请确认这笔记录不再需要保留。"
                : actionDialog.kind === "approve"
                  ? "请核对金额与用途。审核通过后，这笔记录将计入组织收支。"
                  : "填写原因，帮助提交人核对信息后重新提交。"
            }}
          </p>
          <div class="dialog-transaction">
            <span
              >{{ actionDialog.row.tname
              }}<small
                >{{ actionDialog.row.fdate }} ·
                {{ actionDialog.row.aname }}</small
              ></span
            ><strong>¥ {{ money(actionDialog.row.money) }}</strong>
          </div>
          <label
            v-if="actionDialog.kind !== 'delete'"
            class="field review-comment"
            ><span>{{
              actionDialog.kind === "reject" ? "驳回原因" : "审核备注（选填）"
            }}</span
            ><textarea
              v-model="reviewComment"
              :disabled="dialogBusy"
              rows="3"
              maxlength="500"
              :placeholder="
                actionDialog.kind === 'reject'
                  ? '例如：请补充支出用途或核对交易金额…'
                  : '补充本次审核的说明…'
              "
            />
          </label>
          <div v-if="dialogError" class="error-box dialog-error" role="alert">
            {{ dialogError }}
          </div>
          <footer>
            <button
              class="btn btn-secondary"
              type="button"
              :disabled="dialogBusy"
              @click="closeAction"
            >
              取消</button
            ><button
              class="btn"
              :class="
                actionDialog.kind === 'approve' ? 'btn-primary' : 'btn-danger'
              "
              type="button"
              :disabled="dialogBusy"
              @click="performAction"
            >
              <Loader2 v-if="dialogBusy" :size="15" class="spin" />{{
                dialogBusy ? "正在处理…" : dialogPrimary
              }}
            </button>
          </footer>
        </section>
      </div></Teleport
    >
  </div>
</template>

<style scoped>
.transactions-page {
  max-width: 1500px;
  margin: 0 auto;
}
.transactions-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 25px;
  margin-bottom: 27px;
}
.page-eyebrow {
  font-size: 9px;
  letter-spacing: 2px;
  font-weight: 600;
  color: #8f9bad;
  margin-bottom: 9px;
}
.transactions-heading h1 {
  font-size: 29px;
  letter-spacing: 0.2px;
  color: #22354d;
  font-weight: 650;
  line-height: 1.25;
  margin: 0 0 10px;
}
.heading-dot {
  color: #5880bd;
  margin-left: 3px;
}
.transactions-heading p {
  font-size: 12px;
  color: #929cab;
  margin: 0;
  line-height: 1.8;
}
.heading-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.heading-actions .btn {
  font-size: 11px;
  height: 40px;
  white-space: nowrap;
}
.month-overview {
  display: grid;
  grid-template-columns: 1.15fr 1fr 1fr 1fr;
  border: 1px solid #e6e9e8;
  border-radius: 15px;
  background: #fffefa;
  box-shadow: 0 3px 12px #182e4a03;
  margin-bottom: 24px;
  padding: 25px 0;
}
.month-control {
  padding: 0 25px;
  min-width: 0;
  container: transaction-month / inline-size;
}
.month-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  font-size: 10px;
  color: #8996a7;
}
.month-heading-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}
.month-heading-label svg {
  color: #92a0b2;
  flex-shrink: 0;
}
.month-stepper {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}
.month-stepper .icon-btn {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  padding: 0;
  border: 0;
  background: #faf9fc;
  color: #8c829a;
}
.month-stepper .icon-btn:hover {
  background: #f0ebfc;
  color: #7863c7;
}
.month-picker {
  min-width: 0;
  margin: 7px 0 8px;
}
.month-picker > label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  position: relative;
  min-width: 0;
  min-height: 36px;
  font-size: 20px;
  font-weight: 600;
  white-space: nowrap;
  color: #34465f;
  cursor: pointer;
}
.month-picker > label svg {
  color: #9aa6b8;
  flex-shrink: 0;
}
.month-picker > label:focus-within {
  outline: 2px solid #c8bcea;
  outline-offset: 3px;
  border-radius: 5px;
}
.month-picker input {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  height: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  cursor: pointer;
}
.month-picker input::-webkit-calendar-picker-indicator {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  cursor: pointer;
}
.month-caption,
.back-to-now {
  font-size: 9px;
  color: #a7afba;
}
.back-to-now {
  border: 0;
  background: none;
  color: #5c7cad;
  padding: 0;
  cursor: pointer;
}
.month-stat {
  border-left: 1px solid #eceeec;
  padding: 0 27px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 9px;
  min-width: 0;
}
.month-stat > span {
  font-size: 10px;
  color: #8a97a8;
  display: flex;
  align-items: center;
  gap: 7px;
}
.metric-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  display: inline-block;
}
.metric-dot.income {
  background: #7ca993;
}
.metric-dot.expense {
  background: #c79479;
}
.metric-dot.net {
  background: #7d9fc8;
}
.month-stat strong {
  font-size: clamp(19px, 2.1vw, 29px);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.6px;
  color: #2b3c54;
  white-space: nowrap;
}
.month-stat strong > small {
  font-size: 15px;
  font-weight: 450;
  color: #92a0b3;
  margin-right: 4px;
}
.month-stat > small {
  font-size: 9px;
  color: #a8b1bd;
}
.faded {
  opacity: 0.4;
}
.pending-banner {
  display: flex;
  gap: 12px;
  align-items: center;
  background: #f6f5ed;
  border: 1px solid #eae8d8;
  border-radius: 11px;
  padding: 14px 18px;
  margin: 0 0 20px;
}
.pending-icon {
  display: grid;
  place-items: center;
  background: #eee9d7;
  color: #a5905a;
  width: 33px;
  height: 33px;
  border-radius: 9px;
  flex-shrink: 0;
}
.pending-banner strong {
  font-size: 11px;
  font-weight: 550;
  color: #7e744f;
}
.pending-banner p {
  font-size: 10px;
  color: #a69d81;
  margin: 3px 0 0;
}
.pending-banner > button {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
  font-size: 10px;
  border: 0;
  background: none;
  color: #96885d;
  cursor: pointer;
  white-space: nowrap;
}
.ledger-card {
  background: #fffefa;
  border: 1px solid #e6e9e8;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 3px 12px #182e4a03;
}
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 23px;
  border-bottom: 1px solid #e9ece9;
}
.flow-tabs {
  display: flex;
  gap: 26px;
}
.flow-tabs > button {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 20px 0 17px;
  color: #8b97a7;
  background: none;
  border: 0;
  cursor: pointer;
  font-size: 11px;
  white-space: nowrap;
}
.flow-tabs > button.active {
  color: #406eb4;
  font-weight: 600;
}
.flow-tabs > button.active:after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 2px;
  background: #527bbd;
}
.tab-number {
  background: #eef1f5;
  color: #7b8ba0;
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 2px;
}
.refresh-button {
  width: 29px;
  height: 29px;
  background: transparent;
}
.filter-row {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 18px 23px;
}
.search-input {
  display: flex;
  align-items: center;
  gap: 9px;
  max-width: 380px;
  flex: 1;
  margin-right: auto;
  background: #f6f7f4;
  border: 1px solid #e9ece7;
  border-radius: 8px;
  padding: 9px 11px;
  color: #a2adba;
}
.search-input:focus-within {
  outline: 2px solid #dce7f7;
  border-color: #7f9fce;
}
.search-input input {
  min-width: 0;
  width: 100%;
  border: 0;
  background: none;
  outline: 0;
  font: inherit;
  font-size: 10px;
  color: #42516a;
}
.search-input input::placeholder {
  color: #a4aebc;
}
.filter-select {
  display: flex;
  align-items: center;
  gap: 6px;
  position: relative;
  border: 1px solid #e6eae7;
  border-radius: 8px;
  padding: 0 10px;
  color: #96a3b5;
  height: 35px;
  min-width: 111px;
}
.filter-select select {
  border: 0;
  background: none;
  appearance: none;
  outline: 0;
  color: #778699;
  font: inherit;
  font-size: 10px;
  padding: 0 17px 0 0;
  max-width: 150px;
  cursor: pointer;
  min-width: 67px;
}
.filter-select > svg:last-child {
  position: absolute;
  right: 8px;
  pointer-events: none;
}
.collection-filter {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  border: 1px solid #e6eae7;
  border-radius: 8px;
  padding: 0 10px;
  font: inherit;
  font-size: 10px;
  background: none;
  color: #91a0b3;
  height: 35px;
  cursor: pointer;
}
.collection-filter.active {
  background: #f8f3e5;
  border-color: #e8daba;
  color: #ac9153;
}
.collection-filter.active svg {
  fill: #e8d9ad;
}
.desktop-table {
  overflow-x: auto;
}
.desktop-table table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  text-align: left;
  min-width: 720px;
}
.desktop-table th {
  padding: 12px 12px;
  background: #f6f7f4;
  font-size: 9px;
  font-weight: 500;
  color: #919dad;
  border-block: 1px solid #e9ece8;
}
.desktop-table td {
  border-bottom: 1px solid #ecefea;
  padding: 19px 12px;
  font-size: 11px;
  vertical-align: middle;
}
.desktop-table tr:last-child td {
  border-bottom: 0;
}
.desktop-table tbody tr:hover {
  background: #fafbf8;
}
.desktop-table th:nth-child(2) {
  width: 29%;
}
.desktop-table th:nth-child(3) {
  width: 18%;
}
.desktop-table th:nth-child(4) {
  width: 14%;
}
.desktop-table th:nth-child(5) {
  width: 12%;
}
.desktop-table th:nth-child(6) {
  width: 13%;
}
.desktop-table .favorite-column {
  width: 40px;
  padding-left: 22px;
  padding-right: 0;
}
.desktop-table .action-column {
  width: 85px;
  padding-right: 20px;
}
.amount-column {
  text-align: right;
  padding-right: 25px !important;
}
.transaction-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.transaction-icon {
  width: 34px;
  height: 35px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  flex: 0 0 auto;
}
.transaction-icon.income {
  background: #eef5ef;
  color: #73a088;
}
.transaction-icon.expense {
  background: #f7f0e8;
  color: #ba977b;
}
.transaction-icon.transfer {
  background: #eef2f8;
  color: #7f97b9;
}
.transaction-description {
  min-width: 0;
  flex: 1;
}
.row-title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  font-size: 11px;
  font-weight: 550;
  color: #44546b;
  padding: 0;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
}
.row-title:hover {
  color: #426fb4;
}
.transaction-description > span {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 9px;
  color: #a0aab7;
  margin-top: 5px;
  max-width: 235px;
}
.transaction-description > span svg {
  flex-shrink: 0;
}
.account-cell {
  font-size: 10px;
  color: #8290a3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.owner-name {
  display: block;
  font-size: 9px;
  color: #b0b7c1;
  margin-top: 4px;
}
.row-amount {
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.2px;
  white-space: nowrap;
}
.row-amount.income {
  color: #69917f;
}
.row-amount.expense {
  color: #586578;
}
.row-amount.transfer {
  color: #7892b2;
}
.exempt-label {
  display: block;
  margin-top: 4px;
  color: #ab9d82;
  font-size: 8px;
}
.date-value {
  color: #8794a5;
  font-size: 10px;
}
.weekday {
  display: block;
  margin-top: 4px;
  color: #b1b9c4;
  font-size: 8px;
}
.review-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 7px;
  border-radius: 5px;
  font-size: 9px;
  white-space: nowrap;
  background: #f4f5f5;
  color: #929dad;
}
.review-status i {
  width: 4px;
  height: 4px;
  background: currentColor;
  border-radius: 50%;
}
.review-status.approved {
  color: #779982;
  background: #f0f6ef;
}
.review-status.pending {
  color: #b39963;
  background: #f9f4e7;
}
.review-status.rejected {
  color: #bb8a7d;
  background: #faf0ed;
}
.star-button {
  border: 0;
  background: none;
  padding: 3px;
  color: #c2cad3;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  font: inherit;
  font-size: 9px;
}
.star-button.selected {
  color: #c5ad6d;
}
.star-button.selected svg {
  fill: #f0e3b8;
}
.row-actions,
.approval-buttons {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
}
.view-button {
  font: inherit;
  font-size: 10px;
  color: #7d95b7;
  background: none;
  border: 0;
  padding: 4px 0;
  cursor: pointer;
}
.delete-button {
  display: inline-flex;
  color: #b6bfc9;
  background: none;
  border: 0;
  padding: 4px;
  cursor: pointer;
}
.delete-button:hover {
  color: #b47565;
}
.approval-button {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  background: #f0f5ef;
  color: #769785;
  border: 1px solid #e2ebdf;
  border-radius: 6px;
  cursor: pointer;
}
.approval-button.reject {
  background: #faf4f0;
  color: #b59a8e;
  border-color: #eee5df;
}
.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 22px;
  border-top: 1px solid #e9ece8;
  font-size: 9px;
  color: #a0abba;
  gap: 12px;
}
.table-footer > div {
  display: flex;
  gap: 19px;
  align-items: center;
}
.filtered-net {
  color: #b0b9c5;
}
.filtered-net b {
  font-weight: 500;
  color: #7d8b9f;
  margin-left: 5px;
  font-variant-numeric: tabular-nums;
}
.pagination {
  display: flex;
  gap: 12px;
  align-items: center;
  white-space: nowrap;
}
.pagination > span {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: #a7b2bf;
}
.pagination b {
  font-weight: 600;
  color: #7185a0;
}
.pagination .icon-btn {
  width: 26px;
  height: 26px;
  border: 1px solid #e8ece8;
  border-radius: 6px;
}
.pagination button:disabled {
  opacity: 0.35;
  cursor: default;
}
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  min-height: 350px;
  padding: 40px 25px;
  text-align: center;
}
.empty-icon {
  width: 65px;
  height: 69px;
  border-radius: 18px;
  border: 1px solid #e7ecec;
  background: #f1f5f7;
  color: #8da6bd;
  display: grid;
  place-items: center;
  transform: rotate(-5deg);
  margin-bottom: 20px;
}
.empty-icon svg {
  transform: rotate(5deg);
}
.empty-icon.error {
  color: #b5937e;
  background: #f8f0e8;
  border-color: #efdfd0;
}
.empty-state h2 {
  font-size: 15px;
  font-weight: 550;
  color: #61718a;
  margin: 0 0 9px;
}
.empty-state p {
  font-size: 11px;
  line-height: 1.9;
  color: #a3adba;
  margin: 0 0 22px;
  max-width: 430px;
}
.empty-state .btn {
  font-size: 11px;
}
.skeleton-row {
  padding: 23px;
  display: flex;
  align-items: center;
  gap: 25px;
  border-top: 1px solid #eff1ed;
  animation: pulse 1.3s infinite;
}
.skeleton-row i {
  width: 34px;
  height: 35px;
  background: #f1f3ef;
  border-radius: 9px;
}
.skeleton-row span {
  width: 14%;
  height: 13px;
  background: #f1f3ef;
  border-radius: 4px;
}
.skeleton-row span:first-of-type {
  width: 26%;
}
.ledger-footnote {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 21px 0 2px;
  font-size: 9px;
  color: #afb8c3;
}
.mobile-transactions {
  display: none;
}
.action-overlay {
  position: fixed;
  inset: 0;
  z-index: 1090;
  background: #16243d66;
  backdrop-filter: blur(4px);
  display: grid;
  place-items: center;
  padding: 24px;
}
.action-dialog {
  width: 430px;
  max-width: 100%;
  max-height: 90dvh;
  overflow: auto;
  background: #fffefa;
  border: 1px solid #fff;
  border-radius: 20px;
  box-shadow: 0 25px 90px #16273c33;
  padding: 26px;
  color: #2c3b52;
  outline: 0;
}
.action-dialog header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.dialog-symbol {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  background: #edf3ee;
  color: #789880;
  border-radius: 12px;
}
.dialog-symbol.delete,
.dialog-symbol.reject {
  background: #fbf0e9;
  color: #ba8f79;
}
.action-dialog h2 {
  font-size: 19px;
  font-weight: 600;
  margin: 0 0 10px;
}
.action-dialog > p {
  font-size: 12px;
  line-height: 1.9;
  color: #9aa4b2;
  margin: 0 0 21px;
}
.dialog-transaction {
  background: #f5f6f3;
  border: 1px solid #e9ece6;
  border-radius: 10px;
  padding: 13px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  margin-bottom: 20px;
}
.dialog-transaction > span {
  font-size: 12px;
  color: #6a7a90;
}
.dialog-transaction small {
  display: block;
  font-size: 9px;
  color: #a6afbb;
  margin-top: 5px;
}
.dialog-transaction strong {
  font-size: 18px;
  white-space: nowrap;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.review-comment {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.review-comment > span {
  font-size: 11px;
  color: #8996a8;
}
.review-comment textarea {
  border: 1px solid #e5e9e5;
  border-radius: 8px;
  padding: 11px;
  background: #fff;
  font: inherit;
  font-size: 12px;
  resize: vertical;
  min-height: 75px;
  color: #52637b;
}
.review-comment textarea::placeholder {
  color: #b0b9c4;
}
.dialog-error {
  font-size: 11px;
  margin-top: 15px;
}
.action-dialog footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 9px;
  margin-top: 24px;
}
.action-dialog .btn {
  font-size: 11px;
  min-height: 38px;
}
.btn-danger {
  background: #b77663;
  color: #fff;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.spin {
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes pulse {
  50% {
    opacity: 0.45;
  }
}
@media (min-width: 1500px) {
  .desktop-table td {
    padding-block: 21px;
  }
  .month-overview {
    padding-block: 29px;
  }
  .month-stat strong {
    font-size: 31px;
  }
  .row-title {
    font-size: 12px;
  }
  .transaction-description > span {
    font-size: 10px;
  }
  .row-amount {
    font-size: 14px;
  }
}
@media (max-width: 1100px) {
  .month-control {
    padding: 0 17px;
  }
  .month-stat {
    padding: 0 20px;
  }
  .month-stat strong {
    font-size: 24px;
  }
  .month-caption {
    font-size: 8px;
  }
  .filter-row {
    padding: 16px 18px;
    gap: 8px;
  }
  .collection-filter span {
    display: none;
  }
  .collection-filter {
    padding: 0 9px;
  }
  .flow-tabs {
    gap: 23px;
  }
  .desktop-table .favorite-column {
    width: 31px;
    padding-left: 14px;
  }
  .desktop-table td,
  .desktop-table th {
    padding-left: 9px;
    padding-right: 9px;
  }
  .desktop-table .action-column {
    padding-right: 14px;
  }
  .transaction-identity {
    gap: 9px;
  }
  .transaction-description > span {
    max-width: 190px;
  }
  .amount-column {
    padding-right: 18px !important;
  }
  .filtered-net {
    display: none;
  }
  .heading-actions .btn {
    padding-inline: 13px;
  }
}
@media (max-width: 850px) {
  .month-overview {
    grid-template-columns: 1fr 1fr;
    padding: 0;
  }
  .month-control {
    padding: 21px 23px;
    border-bottom: 1px solid #eceeec;
  }
  .month-stat {
    padding: 20px 24px;
  }
  .month-stat:nth-child(2) {
    border-bottom: 1px solid #eceeec;
  }
  .month-stat:nth-child(3) {
    border-left: 0;
  }
  .month-stat strong {
    font-size: 27px;
  }
  .transactions-heading h1 {
    font-size: 27px;
  }
  .transactions-heading p {
    font-size: 11px;
    max-width: 390px;
  }
  .filter-select {
    min-width: 98px;
    padding-left: 9px;
  }
  .filter-select > svg:first-child {
    display: none;
  }
  .filter-select select {
    min-width: 67px;
    font-size: 9px;
  }
  .search-input {
    max-width: none;
  }
  .desktop-table th:nth-child(2) {
    width: 25%;
  }
  .desktop-table th:nth-child(3) {
    width: 17%;
  }
  .desktop-table th:nth-child(5) {
    width: 11%;
  }
  .transaction-icon {
    width: 30px;
    height: 32px;
  }
  .transaction-description > span {
    max-width: 160px;
  }
  .table-toolbar {
    padding-inline: 18px;
  }
  .pending-banner p {
    font-size: 9px;
    max-width: 430px;
  }
  .pending-banner {
    padding: 12px 15px;
  }
}
@media (max-width: 680px) {
  .transactions-heading {
    gap: 15px;
    align-items: flex-start;
    margin-bottom: 21px;
  }
  .page-eyebrow {
    font-size: 8px;
    letter-spacing: 1.5px;
    margin-bottom: 8px;
  }
  .transactions-heading h1 {
    font-size: 25px;
    margin-bottom: 7px;
  }
  .transactions-heading p {
    font-size: 10px;
    max-width: 240px;
  }
  .heading-actions {
    gap: 7px;
    padding-top: 14px;
  }
  .heading-actions .btn {
    font-size: 10px;
    height: 35px;
    padding-inline: 12px;
  }
  .heading-actions .btn-secondary {
    width: 35px;
    padding: 0;
  }
  .heading-actions .btn-secondary span {
    display: none;
  }
  .heading-actions .btn-primary svg {
    width: 15px;
  }
  .month-overview {
    margin-bottom: 18px;
    border-radius: 13px;
  }
  .month-stat {
    gap: 8px;
    padding: 17px 20px;
  }
  .month-control {
    padding: 18px 17px 17px;
  }
  .month-stat > span {
    font-size: 9px;
  }
  .month-stat strong {
    font-size: 25px;
  }
  .month-stat > small {
    font-size: 8px;
  }
  .month-stat strong > small {
    font-size: 14px;
  }
  .pending-banner {
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 18px;
  }
  .pending-icon {
    width: 29px;
    height: 31px;
  }
  .pending-banner strong {
    font-size: 10px;
  }
  .pending-banner p {
    max-width: 265px;
    font-size: 9px;
    line-height: 1.7;
  }
  .pending-banner > button {
    font-size: 9px;
    gap: 2px;
    margin-top: 6px;
  }
  .ledger-card {
    border-radius: 13px;
  }
  .table-toolbar {
    padding-inline: 16px;
  }
  .flow-tabs {
    gap: 20px;
  }
  .flow-tabs > button {
    font-size: 10px;
    padding-top: 18px;
    padding-bottom: 16px;
    gap: 4px;
  }
  .flow-tabs > button svg {
    display: none;
  }
  .tab-number {
    font-size: 8px;
    padding: 0 4px;
  }
  .refresh-button {
    width: 25px;
    height: 25px;
  }
  .filter-row {
    padding: 14px 15px;
    flex-wrap: wrap;
    gap: 8px;
  }
  .search-input {
    flex: 0 0 100%;
    max-width: none;
    padding: 10px 11px;
  }
  .search-input input {
    font-size: 11px;
  }
  .filter-select {
    flex: 1;
    height: 33px;
    padding-left: 10px;
  }
  .filter-select select {
    width: 100%;
    font-size: 10px;
    padding-right: 20px;
  }
  .filter-select > svg:first-child {
    display: block;
    width: 13px;
  }
  .collection-filter {
    height: 33px;
    padding: 0 10px;
  }
  .collection-filter span {
    display: inline;
    font-size: 10px;
  }
  .desktop-table {
    display: none;
  }
  .mobile-transactions {
    display: block;
  }
  .mobile-transaction {
    padding: 19px 17px 13px;
    border-top: 1px solid #ecefea;
  }
  .mobile-transaction:first-child {
    border-top: 0;
  }
  .mobile-row-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .mobile-row-top .transaction-identity {
    flex: 1;
    min-width: 0;
    gap: 11px;
  }
  .mobile-row-top .transaction-icon {
    width: 35px;
    height: 37px;
  }
  .mobile-row-top .row-title {
    font-size: 12px;
    max-width: 205px;
  }
  .mobile-row-top .transaction-description > span {
    font-size: 10px;
    max-width: 215px;
    margin-top: 5px;
  }
  .mobile-row-top .row-amount {
    font-size: 15px;
  }
  .mobile-row-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    padding-left: 46px;
    margin-top: 13px;
  }
  .mobile-row-meta > span:first-child {
    font-size: 9px;
    color: #a0adbd;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .review-status {
    font-size: 8px;
    padding: 3px 6px;
    gap: 4px;
  }
  .mobile-row-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-left: 44px;
    margin-top: 13px;
    min-height: 20px;
  }
  .mobile-row-actions .owner-name {
    margin: 0;
    font-size: 8px;
  }
  .mobile-row-actions > div:last-child {
    display: flex;
    align-items: center;
    gap: 15px;
    margin-left: auto;
  }
  .mobile-row-actions .star-button {
    font-size: 9px;
  }
  .mobile-row-actions .view-button {
    font-size: 9px;
    color: #859aba;
  }
  .mobile-row-actions .delete-button {
    padding: 2px;
  }
  .mobile-approve {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    background: none;
    border: 0;
    font: inherit;
    font-size: 9px;
    color: #7c9d84;
    cursor: pointer;
    padding: 2px;
  }
  .mobile-reject {
    background: none;
    border: 0;
    font: inherit;
    font-size: 9px;
    color: #b19b8b;
    cursor: pointer;
    padding: 2px;
  }
  .table-footer {
    padding: 13px 16px;
    font-size: 8px;
  }
  .pagination {
    gap: 10px;
  }
  .pagination .icon-btn {
    width: 24px;
    height: 24px;
  }
  .pagination > span {
    font-size: 9px;
  }
  .empty-state {
    min-height: 320px;
    padding: 35px 20px;
  }
  .empty-state h2 {
    font-size: 14px;
  }
  .empty-state p {
    font-size: 10px;
    max-width: 280px;
  }
  .empty-state .btn {
    font-size: 10px;
  }
  .empty-icon {
    width: 58px;
    height: 63px;
    border-radius: 16px;
  }
  .ledger-footnote {
    font-size: 8px;
    margin-top: 18px;
    gap: 4px;
  }
  .ledger-footnote svg {
    width: 12px;
  }
  .skeleton-row {
    padding: 24px 17px;
    gap: 16px;
  }
  .skeleton-row span:nth-last-child(1) {
    display: none;
  }
  .skeleton-row span:first-of-type {
    width: 36%;
  }
  .action-dialog {
    padding: 23px;
    border-radius: 17px;
  }
  .action-dialog h2 {
    font-size: 18px;
  }
  .action-dialog > p {
    font-size: 11px;
  }
  .action-overlay {
    padding: 20px;
  }
}
@media (max-width: 390px) {
  .flow-tabs {
    gap: 15px;
  }
  .month-stat strong {
    font-size: 22px;
  }
  .month-stat {
    padding-inline: 16px;
  }
  .mobile-row-top .transaction-description > span {
    max-width: 170px;
  }
  .mobile-row-top .row-title {
    max-width: 160px;
  }
  .mobile-row-top .row-amount {
    font-size: 14px;
  }
  .pending-banner p {
    max-width: 220px;
  }
  .pending-banner > button {
    font-size: 8px;
  }
  .heading-actions .btn-primary {
    padding-inline: 9px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin,
  .skeleton-row {
    animation: none;
  }
}
@container transaction-month (max-width: 190px) {
  .month-heading-label svg {
    display: none;
  }
  .month-picker > label {
    font-size: 18px;
  }
}
@container transaction-month (max-width: 140px) {
  .month-picker > label {
    font-size: 16px;
    gap: 2px;
  }
  .month-picker > label > svg {
    width: 12px;
    height: 12px;
  }
}
</style>
