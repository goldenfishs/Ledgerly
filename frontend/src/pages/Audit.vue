<script setup>
import { computed, onMounted, ref } from "vue";
import {
  History,
  Search,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  LockKeyhole,
  UserRound,
  ArrowRight,
  Activity,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { state } from "../lib/app";
import { dateTime } from "../lib/format";

const records = ref([]),
  loading = ref(true),
  failure = ref(""),
  query = ref(""),
  entity = ref(""),
  expanded = ref(new Set());
const admin = computed(() => state.user?.role === "admin");
const entities = {
  organization: "账本设置",
  ledger: "账本",
  member: "账本成员",
  invitation: "账本邀请",
  user: "账号",
  account: "资金账户",
  category: "收支分类",
  flow: "收支流水",
  invoice: "发票凭证",
};
const actions = {
  setup: "初始化账本",
  invite: "生成邀请",
  revoke: "撤销邀请",
  join: "加入账本",
  role: "调整角色",
  remove: "移除成员",
  login: "登录",
  create: "新增",
  update: "修改",
  archive: "归档",
  delete: "删除",
  collect: "更新收藏",
  review: "审核",
  edit_approved: "修改已审核流水",
  "invoice.upload": "上传发票",
  "invoice.update": "更新发票",
  "invoice.delete": "删除发票",
  "invoice.restore": "恢复发票",
  "invoice.recognize": "识别发票",
};
const fieldNames = {
  name: "名称",
  tname: "分类名称",
  aname: "账户名称",
  username: "登录账号",
  role: "角色",
  enabled: "启用状态",
  enable: "启用状态",
  initialMoney: "初始余额",
  money: "金额",
  amount: "未税金额",
  tax_amount: "税额",
  total_amount: "价税合计",
  status: "状态",
  previousStatus: "原状态",
  from: "原状态",
  to: "新状态",
  comment: "审核说明",
  reviewComment: "审核说明",
  note: "备注",
  notes: "备注",
  fdate: "发生日期",
  date: "日期",
  invoice_date: "开票日期",
  ownerId: "归属成员编号",
  ownerName: "归属成员",
  accountId: "账户编号",
  accountToId: "转入账户编号",
  typeId: "分类编号",
  actionId: "收支类型",
  actionIds: "适用类型",
  collect: "收藏",
  accountType: "账户类型",
  parent: "父分类编号",
  passwordReset: "重置密码",
  fileType: "文件类型",
  seller: "销售方",
  buyer: "购买方",
  invoice_number: "发票号码",
  organization: "账本名称",
  description: "账本介绍",
  color: "账本颜色",
  expiresAt: "邀请到期时间",
  invitationId: "邀请编号",
};
const statusNames = {
  pending: "待审核",
  approved: "已通过",
  rejected: "已驳回",
  review: "待核对",
  confirmed: "已确认",
  error: "识别失败",
  processing: "识别中",
};
function printable(value, key = "") {
  if (value === null || value === undefined || value === "") return "未设置";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (key === "role") return value === "admin" ? "管理员" : "成员";
  if (["status", "previousStatus", "from", "to"].includes(key))
    return statusNames[value] || String(value);
  if (key === "actionId")
    return { 0: "收入", 1: "支出", 2: "转账" }[value] || String(value);
  if (key === "accountType")
    return Number(value) === 1 ? "负债账户" : "资产账户";
  if (key === "fileType")
    return (
      {
        "image/png": "PNG 图片",
        "image/jpeg": "JPEG 图片",
        "image/webp": "WEBP 图片",
        "application/pdf": "PDF 文件",
      }[value] || String(value)
    );
  if (Array.isArray(value))
    return (
      value
        .map((item) =>
          key === "actionIds"
            ? { 0: "收入", 1: "支出", 2: "转账" }[item] || item
            : typeof item === "object"
              ? item.name || item.tname || "关联记录"
              : item,
        )
        .join("、") || "无"
    );
  if (typeof value === "object")
    return value.name || value.tname || value.aname || "已更新";
  return String(value);
}
function pairs(record) {
  const detail = record.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return [];
  const result = [];
  const before =
    detail.before && typeof detail.before === "object" ? detail.before : {};
  const after =
    detail.after && typeof detail.after === "object" ? detail.after : {};
  const isChange = Boolean(detail.before || detail.after);
  if (isChange) {
    for (const key of new Set([
      ...Object.keys(before),
      ...Object.keys(after),
    ])) {
      if (
        !fieldNames[key] ||
        JSON.stringify(before[key]) === JSON.stringify(after[key]) ||
        !(key in after)
      )
        continue;
      result.push({
        label: fieldNames[key],
        before: printable(before[key], key),
        after: printable(after[key], key),
        changed: true,
      });
    }
  }
  for (const [key, value] of Object.entries(detail)) {
    if (!fieldNames[key]) continue;
    result.push({
      label: fieldNames[key],
      after: printable(value, key),
      changed: false,
    });
  }
  return result;
}
function summary(record) {
  const details = pairs(record);
  if (!details.length)
    return record.action === "login"
      ? "通过身份验证，进入工作区"
      : "操作已记录";
  return details
    .slice(0, 2)
    .map((item) => `${item.label}：${item.after}`)
    .join(" · ");
}
const filtered = computed(() =>
  records.value.filter((record) => {
    if (entity.value && record.entityType !== entity.value) return false;
    const terms = [
      record.actorName,
      actions[record.action] || "操作",
      entities[record.entityType] || "记录",
      record.entityId,
      summary(record),
      ...pairs(record).map(
        (item) => `${item.label} ${item.before || ""} ${item.after}`,
      ),
    ]
      .join(" ")
      .toLowerCase();
    return terms.includes(query.value.trim().toLowerCase());
  }),
);
const actorCount = computed(
  () =>
    new Set(records.value.map((record) => record.actorId ?? record.actorName))
      .size,
);
const todayCount = computed(() => {
  const today = new Date().toLocaleDateString("zh-CN");
  return records.value.filter(
    (record) =>
      new Date(record.createdAt).toLocaleDateString("zh-CN") === today,
  ).length;
});
async function load() {
  if (!admin.value) {
    loading.value = false;
    return;
  }
  loading.value = true;
  failure.value = "";
  try {
    records.value = await api("/audit", { query: { limit: 500 } });
  } catch (error) {
    failure.value = error.message;
  } finally {
    loading.value = false;
  }
}
function toggle(id) {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expanded.value = next;
}
function tone(record) {
  return ["delete", "archive", "invoice.delete"].includes(record.action)
    ? "badge-red"
    : ["create", "setup", "invoice.upload", "invoice.restore"].includes(
          record.action,
        )
      ? "badge-green"
      : record.action === "login"
        ? ""
        : "badge-blue";
}
onMounted(load);
</script>

<template>
  <div class="page-header">
    <div>
      <div class="page-eyebrow">ACTIVITY LOG</div>
      <h1>操作日志</h1>
      <p>了解谁在何时更新了账目，让每一次改动都有记录。</p>
    </div>
    <button
      v-if="admin"
      class="btn btn-secondary"
      :disabled="loading"
      @click="load"
    >
      <RefreshCw :size="16" />刷新记录
    </button>
  </div>
  <section v-if="!admin" class="card empty-state">
    <LockKeyhole :size="35" />
    <h3>此页面仅供管理员查看</h3>
    <p>本账本的操作记录由管理员统一管理。</p>
  </section>
  <template v-else>
    <div class="au-overview">
      <div class="card au-metric">
        <span class="au-metric-icon"><History :size="20" /></span>
        <div>
          <span>近期操作</span
          ><strong
            >{{ loading ? "—" : records.length }}<small>条</small></strong
          >
        </div>
      </div>
      <div class="card au-metric">
        <span class="au-metric-icon green"><Activity :size="20" /></span>
        <div>
          <span>今日操作</span
          ><strong>{{ loading ? "—" : todayCount }}<small>条</small></strong>
        </div>
      </div>
      <div class="card au-metric">
        <span class="au-metric-icon purple"><UserRound :size="20" /></span>
        <div>
          <span>参与成员</span
          ><strong>{{ loading ? "—" : actorCount }}<small>人</small></strong>
        </div>
      </div>
    </div>
    <section class="card">
      <div class="table-toolbar">
        <div class="search-box au-search">
          <Search :size="16" /><input
            v-model="query"
            type="search"
            placeholder="搜索成员、操作或改动内容"
            aria-label="搜索操作记录"
          />
        </div>
        <div class="filters">
          <select v-model="entity" aria-label="记录类型">
            <option value="">全部记录类型</option>
            <option v-for="(label, key) in entities" :key="key" :value="key">
              {{ label }}
            </option>
          </select>
        </div>
      </div>
      <div v-if="loading" class="loading-state">
        <span class="spinner"></span>正在读取操作记录…
      </div>
      <div v-else-if="failure" class="empty-state">
        <History :size="32" />
        <h3>暂时无法读取操作记录</h3>
        <p>{{ failure }}</p>
        <button class="btn btn-secondary" @click="load">重新加载</button>
      </div>
      <div v-else-if="!filtered.length" class="empty-state">
        <History :size="34" />
        <h3>{{ query || entity ? "没有找到匹配记录" : "还没有操作记录" }}</h3>
        <p>
          {{
            query || entity
              ? "试试其他关键词或记录类型。"
              : "本账本的成员、账目和设置改动会展示在这里。"
          }}
        </p>
        <button
          v-if="query || entity"
          class="btn btn-secondary"
          @click="
            query = '';
            entity = '';
          "
        >
          清除筛选
        </button>
      </div>
      <div v-else class="table-wrap">
        <table class="au-table">
          <thead>
            <tr>
              <th>操作成员</th>
              <th>操作</th>
              <th>记录类型</th>
              <th>操作时间</th>
              <th class="text-right">详情</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="record in filtered" :key="record.id"
              ><tr>
                <td>
                  <div class="au-actor">
                    <span class="avatar">{{
                      (record.actorName || "系统").slice(0, 1)
                    }}</span>
                    <div>
                      <strong>{{ record.actorName || "系统" }}</strong>
                      <div class="table-sub">{{ summary(record) }}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <span class="badge" :class="tone(record)">{{
                    actions[record.action] || "更新记录"
                  }}</span>
                </td>
                <td>
                  <span class="au-entity">{{
                    entities[record.entityType] || "其他记录"
                  }}</span
                  ><span
                    v-if="record.entityId"
                    class="au-id"
                    :title="String(record.entityId)"
                    >#{{
                      String(record.entityId).length > 12
                        ? String(record.entityId).slice(0, 8)
                        : record.entityId
                    }}</span
                  >
                </td>
                <td class="au-time">{{ dateTime(record.createdAt) }}</td>
                <td class="text-right">
                  <button
                    class="icon-btn"
                    :aria-label="
                      expanded.has(record.id) ? '收起操作详情' : '展开操作详情'
                    "
                    :aria-expanded="expanded.has(record.id)"
                    :aria-controls="`audit-detail-${record.id}`"
                    @click="toggle(record.id)"
                  >
                    <ChevronDown
                      v-if="expanded.has(record.id)"
                      :size="17"
                    /><ChevronRight v-else :size="17" />
                  </button>
                </td>
              </tr>
              <tr v-if="expanded.has(record.id)" class="au-detail-row">
                <td :id="`audit-detail-${record.id}`" colspan="5">
                  <div class="au-detail">
                    <div class="au-detail-heading">
                      <ShieldCheck :size="15" /><strong>{{
                        actions[record.action] || "更新记录"
                      }}</strong
                      ><span
                        >{{ entities[record.entityType] || "记录"
                        }}{{
                          record.entityId ? ` · ${record.entityId}` : ""
                        }}</span
                      >
                    </div>
                    <dl v-if="pairs(record).length" class="au-pairs">
                      <div v-for="(item, index) in pairs(record)" :key="index">
                        <dt>{{ item.label }}</dt>
                        <dd>
                          <template v-if="item.changed"
                            ><span class="au-before">{{ item.before }}</span
                            ><ArrowRight :size="13" /></template
                          ><span :class="{ 'au-after': item.changed }">{{
                            item.after
                          }}</span>
                        </dd>
                      </div>
                    </dl>
                    <p v-else class="au-no-detail">
                      {{
                        record.action === "login"
                          ? "该成员已成功登录工作区。"
                          : "此次操作已记录，没有额外的字段变更。"
                      }}
                    </p>
                  </div>
                </td>
              </tr></template
            >
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <span
          >最近 {{ records.length }} 条记录 · 当前显示
          {{ filtered.length }} 条</span
        ><span class="au-foot"
          ><ShieldCheck :size="13" />最多展示最近 500 条操作</span
        >
      </div>
    </section>
  </template>
</template>

<style scoped>
.au-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 23px;
}
.au-metric {
  padding: 21px 23px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.au-metric-icon {
  width: 43px;
  height: 43px;
  display: grid;
  place-items: center;
  background: #eef3fe;
  color: #8ba2d9;
  border-radius: 11px;
}
.au-metric-icon.green {
  background: #edf7f3;
  color: #8dbdaa;
}
.au-metric-icon.purple {
  background: #f3effc;
  color: #ada0d0;
}
.au-metric > div > span {
  font-size: 11px;
  color: #98a4b7;
}
.au-metric strong {
  font-size: 25px;
  color: #5e6f89;
  display: flex;
  align-items: baseline;
  gap: 7px;
  font-weight: 550;
  margin-top: 8px;
  font-variant-numeric: tabular-nums;
}
.au-metric strong small {
  font-size: 10px;
  color: #a6afbd;
  font-weight: 400;
}
.au-search {
  width: 360px;
  max-width: 100%;
}
.au-actor {
  display: flex;
  gap: 11px;
  align-items: center;
}
.au-actor .avatar {
  width: 32px;
  height: 32px;
  font-size: 11px;
  color: #96a9ce;
  background: #f0f4fc;
  border-color: #f8faff;
}
.au-actor > div {
  min-width: 0;
  max-width: 320px;
}
.au-actor strong {
  font-weight: 550;
  font-size: 12px;
  color: #62738d;
}
.au-actor .table-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 300px;
  font-size: 10px;
  margin-top: 6px;
}
.au-entity {
  color: #8d9aad;
  font-size: 11px;
}
.au-id {
  font-size: 9px;
  color: #a8b3c3;
  margin-left: 6px;
  letter-spacing: 0.3px;
}
.au-time {
  font-size: 10px;
  color: #96a2b5;
  font-variant-numeric: tabular-nums;
}
.au-detail-row td {
  padding: 0 !important;
  white-space: normal;
}
.au-detail {
  background: #f8fafd;
  border-top: 1px solid #edf1f7;
  border-bottom: 1px solid #edf1f7;
  padding: 21px 26px 23px;
}
.au-detail-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #a3b1c6;
  font-size: 11px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.au-detail-heading strong {
  font-size: 11px;
  color: #7c8faa;
  font-weight: 500;
}
.au-detail-heading > span {
  font-size: 10px;
  overflow-wrap: anywhere;
}
.au-pairs {
  margin: 0;
  display: grid;
  gap: 11px;
}
.au-pairs > div {
  display: flex;
  gap: 25px;
  align-items: baseline;
}
.au-pairs dt {
  font-size: 11px;
  min-width: 85px;
  color: #9ba9bc;
}
.au-pairs dd {
  display: flex;
  align-items: center;
  gap: 11px;
  flex-wrap: wrap;
  margin: 0;
  font-size: 11px;
  color: #7b8ea8;
  line-height: 1.8;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  min-width: 0;
}
.au-pairs dd span {
  max-width: 650px;
  overflow-wrap: anywhere;
}
.au-pairs dd svg {
  color: #b3bfd0;
}
.au-before {
  color: #a3aebe;
}
.au-after {
  color: #6584ba;
}
.au-no-detail {
  font-size: 11px;
  color: #a3afc0;
  margin: 0;
}
.au-foot {
  font-size: 10px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.pagination {
  gap: 12px;
}
@media (max-width: 760px) {
  .au-overview {
    gap: 10px;
  }
  .au-metric {
    padding: 16px 12px;
    gap: 9px;
    align-items: flex-start;
    flex-direction: column;
  }
  .au-metric-icon {
    width: 30px;
    height: 30px;
    border-radius: 8px;
  }
  .au-metric-icon svg {
    width: 16px;
  }
  .au-metric strong {
    font-size: 23px;
    margin-top: 6px;
  }
  .au-metric > div > span {
    font-size: 10px;
  }
  .au-actor > div {
    max-width: 180px;
  }
  .au-actor .table-sub {
    max-width: 175px;
  }
  .au-actor .avatar {
    width: 28px;
    height: 28px;
  }
  .au-detail {
    padding: 19px;
  }
  .au-pairs > div {
    gap: 13px;
  }
  .au-pairs dt {
    min-width: 70px;
    font-size: 10px;
  }
  .au-pairs dd {
    font-size: 10px;
    gap: 7px;
  }
  .pagination {
    padding: 15px;
    flex-wrap: wrap;
    font-size: 10px;
  }
  .au-search {
    width: 100%;
  }
}
</style>
