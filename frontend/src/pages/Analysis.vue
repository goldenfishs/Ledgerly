<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  ArrowDownLeft,
  ArrowDownWideNarrow,
  ArrowUpRight,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Download,
  FileBarChart2,
  Layers3,
  Loader2,
  Percent,
  RefreshCw,
  Search,
  ShieldCheck,
  TrendingUp,
  Wallet,
} from "lucide-vue-next";
import TrendChart from "../components/TrendChart.vue";
import CategoryChart from "../components/CategoryChart.vue";
import { api } from "../lib/api.js";
import { bus, notify, state } from "../lib/app.js";
import { downloadCsv, money, monthLabel, today } from "../lib/format.js";

const month = ref(today().slice(0, 7));
const data = ref(null);
const loading = ref(true);
const error = ref("");
const chartMode = ref("monthly");
const categoryQuery = ref("");
const descending = ref(true);
let sequence = 0;
const colors = [
  "#6e8ae0",
  "#81c6b2",
  "#d6b383",
  "#a59aca",
  "#e4a195",
  "#94b8d2",
];
const isAdmin = computed(() => state.user?.role === "admin");
const scopeLabel = computed(() =>
  isAdmin.value ? "组织已审核流水" : "本人已审核流水",
);
const categories = computed(() =>
  Array.isArray(data.value?.categories) ? data.value.categories : [],
);
const expense = computed(() => Number(data.value?.expense || 0));
const income = computed(() => Number(data.value?.income || 0));
const net = computed(() => Number(data.value?.net || 0));
const margin = computed(() =>
  income.value > 0 ? (net.value / income.value) * 100 : null,
);
const points = computed(() => {
  const items =
    chartMode.value === "monthly" ? data.value?.monthly : data.value?.trend;
  return Array.isArray(items) ? items : [];
});
const filteredCategories = computed(() => {
  const search = categoryQuery.value.trim().toLocaleLowerCase();
  return categories.value
    .map((item, index) => ({
      ...item,
      color: colors[index % colors.length],
      share:
        expense.value > 0 ? (Number(item.amount) / expense.value) * 100 : 0,
    }))
    .filter(
      (item) =>
        !search || String(item.name).toLocaleLowerCase().includes(search),
    )
    .sort((a, b) =>
      descending.value
        ? Number(b.amount) - Number(a.amount)
        : Number(a.amount) - Number(b.amount),
    );
});
const highestCategory = computed(
  () =>
    [...categories.value].sort(
      (a, b) => Number(b.amount) - Number(a.amount),
    )[0],
);
const firstMonth = computed(() => data.value?.monthly?.[0]?.month);
const formatted = (value) =>
  loading.value || error.value ? "—" : money(value);

async function load() {
  const current = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await api("/dashboard", { query: { month: month.value } });
    if (current === sequence) data.value = result;
  } catch (cause) {
    if (current === sequence)
      error.value = cause.message || "暂时无法读取统计数据，请稍后重试。";
  } finally {
    if (current === sequence) loading.value = false;
  }
}
function shiftMonth(offset) {
  const [year, value] = month.value.split("-").map(Number);
  const date = new Date(year, value - 1 + offset, 1);
  month.value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
function selectMonth(event) {
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value))
    month.value = event.target.value;
}
function exportReport() {
  if (!data.value || loading.value || error.value) return;
  const rows = [
    ["统计范围", scopeLabel.value],
    [
      "统计类型",
      "期间",
      "项目",
      "收入（元）",
      "支出（元）",
      "结余（元）",
      "支出占比",
    ],
    [
      "当月汇总",
      month.value,
      "全部已审核收支",
      data.value.income,
      data.value.expense,
      data.value.net,
      "",
    ],
    ...(data.value.monthly || []).map((item) => [
      "月度趋势",
      item.month,
      "已审核收支",
      item.income,
      item.expense,
      (Number(item.income) - Number(item.expense)).toFixed(2),
      "",
    ]),
    ...(data.value.trend || []).map((item) => [
      "每日趋势",
      item.date,
      "已审核收支",
      item.income,
      item.expense,
      (Number(item.income) - Number(item.expense)).toFixed(2),
      "",
    ]),
    ...categories.value.map((item) => [
      "支出分类",
      month.value,
      item.name,
      "",
      item.amount,
      "",
      `${expense.value > 0 ? ((Number(item.amount) / expense.value) * 100).toFixed(2) : "0.00"}%`,
    ]),
  ];
  downloadCsv(rows, `账序-统计报表-${month.value}.csv`);
  notify("统计报表已导出，仅包含当前权限可见的已审核数据");
}
watch(month, () => {
  categoryQuery.value = "";
  load();
});
onMounted(() => {
  load();
  bus.addEventListener("ledger-change", load);
});
onBeforeUnmount(() => {
  sequence++;
  bus.removeEventListener("ledger-change", load);
});
</script>

<template>
  <div class="analysis-page">
    <header class="page-header analysis-heading">
      <div>
        <div class="analysis-eyebrow">FINANCIAL INSIGHTS</div>
        <h1>统计报表<span>.</span></h1>
        <p>让数据呈现经营脉络，为下一步决策提供依据。</p>
      </div>
      <button
        class="btn btn-secondary export-report"
        type="button"
        :disabled="loading || Boolean(error) || !data"
        @click="exportReport"
      >
        <Download :size="16" />导出报表
      </button>
    </header>
    <div class="analysis-controls">
      <div class="report-month">
        <CalendarDays :size="17" /><button
          class="icon-btn"
          type="button"
          aria-label="上个月"
          @click="shiftMonth(-1)"
        >
          <ChevronLeft :size="16" /></button
        ><label
          ><span>{{ monthLabel(month) }}</span
          ><input
            :value="month"
            type="month"
            aria-label="选择报表月份"
            @change="selectMonth" /><ChevronDown :size="13" /></label
        ><button
          class="icon-btn"
          type="button"
          aria-label="下个月"
          @click="shiftMonth(1)"
        >
          <ChevronRight :size="16" /></button
        ><button
          v-if="month !== today().slice(0, 7)"
          class="return-current"
          type="button"
          @click="month = today().slice(0, 7)"
        >
          本月
        </button>
      </div>
      <span class="report-scope"
        ><ShieldCheck :size="13" />{{ scopeLabel }} · 人民币 CNY</span
      >
    </div>

    <section class="report-summary" aria-label="月度统计指标">
      <article class="summary-card">
        <div>
          <span>本月收入</span
          ><span class="summary-icon income"><ArrowDownLeft :size="17" /></span>
        </div>
        <strong><small>¥</small>{{ formatted(data?.income) }}</strong>
        <p>已审核的收入流水</p>
      </article>
      <article class="summary-card">
        <div>
          <span>本月支出</span
          ><span class="summary-icon expense"><ArrowUpRight :size="17" /></span>
        </div>
        <strong><small>¥</small>{{ formatted(data?.expense) }}</strong>
        <p>已审核的支出流水</p>
      </article>
      <article class="summary-card">
        <div>
          <span>本月结余</span
          ><span class="summary-icon net"><Wallet :size="17" /></span>
        </div>
        <strong :class="{ negative: !loading && !error && net < 0 }"
          ><small>¥</small>{{ formatted(data?.net) }}</strong
        >
        <p>收入减去支出，转账不计入</p>
      </article>
      <article class="summary-card">
        <div>
          <span>结余率</span
          ><span class="summary-icon rate"><Percent :size="16" /></span>
        </div>
        <strong
          >{{ loading || error || margin === null ? "—" : margin.toFixed(1)
          }}<small
            v-if="!loading && !error && margin !== null"
            class="percent-sign"
            >%</small
          ></strong
        >
        <p>
          {{
            !loading && !error && income === 0
              ? "当月暂无收入，暂不计算比率"
              : "当月结余 ÷ 当月收入"
          }}
        </p>
      </article>
    </section>

    <div v-if="error" class="card report-error">
      <CircleAlert :size="29" />
      <h2>统计数据暂时无法加载</h2>
      <p>{{ error }}</p>
      <button class="btn btn-secondary" type="button" @click="load">
        <RefreshCw :size="15" />重新加载
      </button>
    </div>
    <template v-else>
      <div class="charts-grid">
        <section class="card trend-panel">
          <header class="chart-header">
            <div>
              <h2><TrendingUp :size="17" />收支趋势</h2>
              <p>
                {{
                  chartMode === "monthly"
                    ? "观察过去 12 个月的资金变化"
                    : "查看当月每一天的收支记录"
                }}
              </p>
            </div>
            <div class="chart-switch" role="group" aria-label="趋势时间范围">
              <button
                type="button"
                :class="{ active: chartMode === 'monthly' }"
                :aria-pressed="chartMode === 'monthly'"
                @click="chartMode = 'monthly'"
              >
                近 12 月</button
              ><button
                type="button"
                :class="{ active: chartMode === 'daily' }"
                :aria-pressed="chartMode === 'daily'"
                @click="chartMode = 'daily'"
              >
                本月每日
              </button>
            </div>
          </header>
          <div class="chart-caption">
            <div class="chart-legend">
              <span><i class="income"></i>收入</span
              ><span><i class="expense"></i>支出</span>
            </div>
            <span
              >{{
                chartMode === "monthly" && firstMonth
                  ? `${firstMonth} 至 ${month}`
                  : monthLabel(month)
              }}
              · 单位：元</span
            >
          </div>
          <div v-if="loading" class="chart-loading">
            <Loader2 class="spin" :size="22" /><span>正在汇总已审核数据…</span>
          </div>
          <div v-else class="trend-wrap">
            <TrendChart :points="points" :monthly="chartMode === 'monthly'" />
          </div>
          <footer class="trend-note">
            <ShieldCheck :size="12" /><span
              >待审核与已驳回记录不纳入统计，内部转账不计入收支。</span
            >
          </footer>
        </section>
        <section class="card category-panel">
          <header class="chart-header">
            <div>
              <h2><Layers3 :size="17" />支出构成</h2>
              <p>本月支出按用途分类</p>
            </div>
            <span class="category-count"
              >{{ loading ? "—" : categories.length }} 个分类</span
            >
          </header>
          <div v-if="loading" class="chart-loading donut-loading">
            <Loader2 class="spin" :size="22" /><span>正在整理支出分类…</span>
          </div>
          <CategoryChart v-else :items="categories" />
        </section>
      </div>

      <section class="card breakdown-panel">
        <header class="breakdown-header">
          <div>
            <h2>支出分类明细</h2>
            <p>
              {{
                !loading && highestCategory
                  ? `「${highestCategory.name}」是本月占比最高的支出分类`
                  : "每一项支出，拆开来看更清楚"
              }}
            </p>
          </div>
          <div class="breakdown-tools">
            <label class="category-search"
              ><Search :size="14" /><input
                v-model="categoryQuery"
                type="search"
                placeholder="查找分类"
                aria-label="查找支出分类" /></label
            ><button
              type="button"
              class="sort-button"
              :title="descending ? '切换为金额从低到高' : '切换为金额从高到低'"
              @click="descending = !descending"
            >
              <ArrowDownWideNarrow :size="14" /><span>{{
                descending ? "金额从高到低" : "金额从低到高"
              }}</span>
            </button>
          </div>
        </header>
        <div v-if="loading" class="breakdown-loading">
          <div v-for="number in 3" :key="number">
            <i></i><span></span><b></b>
          </div>
        </div>
        <div v-else-if="!filteredCategories.length" class="breakdown-empty">
          <FileBarChart2 :size="27" /><strong>{{
            categoryQuery ? "没有找到对应分类" : "这个月还没有已审核支出"
          }}</strong>
          <p>
            {{
              categoryQuery
                ? "试试其他关键词，或清空搜索条件。"
                : "支出流水通过审核后，将自动归入对应分类。"
            }}
          </p>
          <button
            v-if="categoryQuery"
            type="button"
            @click="categoryQuery = ''"
          >
            清除搜索
          </button>
        </div>
        <table v-else class="breakdown-table">
          <thead>
            <tr>
              <th>分类</th>
              <th>支出金额</th>
              <th>占总支出</th>
              <th class="distribution-heading">支出分布</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(category, index) in filteredCategories"
              :key="category.id || category.name"
            >
              <td>
                <span class="category-rank">{{
                  String(index + 1).padStart(2, "0")
                }}</span
                ><span
                  class="category-marker"
                  :style="{ background: category.color }"
                ></span
                ><span class="category-name">{{ category.name }}</span>
              </td>
              <td class="category-amount">
                <small>¥</small>{{ money(category.amount) }}
              </td>
              <td class="category-share">
                {{ category.share.toFixed(1) }}<small>%</small>
              </td>
              <td class="distribution-cell">
                <div class="distribution-track">
                  <div
                    :style="{
                      width: `${Math.min(100, Math.max(0, category.share))}%`,
                      background: category.color,
                    }"
                  ></div>
                </div>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td>本月全部支出合计</td>
              <td class="category-amount">
                <small>¥</small>{{ money(data.expense) }}
              </td>
              <td class="category-share">
                {{ expense > 0 ? "100" : "0" }}<small>%</small>
              </td>
              <td class="distribution-cell"></td>
            </tr>
          </tfoot>
        </table>
        <footer class="breakdown-footer">
          <span>{{
            loading
              ? "正在读取…"
              : `共 ${categories.length} 个支出分类${categoryQuery ? `，当前显示 ${filteredCategories.length} 个` : ""}`
          }}</span
          ><span>分类占比以本月全部已审核支出为基数</span>
        </footer>
      </section>
    </template>
    <div class="analysis-footnote">
      <ShieldCheck :size="13" /><span
        >{{ isAdmin ? "组织统计视图" : "个人统计视图，仅显示本人记录" }} ·
        汇总数据随审核结果实时更新</span
      >
    </div>
  </div>
</template>

<style scoped>
.analysis-page {
  max-width: 1500px;
  margin: 0 auto;
}
.analysis-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 25px;
}
.analysis-eyebrow {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #8f9bad;
  margin-bottom: 9px;
}
.analysis-heading h1 {
  font-size: 29px;
  letter-spacing: 0.2px;
  color: #22354d;
  font-weight: 650;
  line-height: 1.25;
  margin: 0 0 10px;
}
.analysis-heading h1 > span {
  color: #5880bd;
  margin-left: 3px;
}
.analysis-heading p {
  font-size: 12px;
  color: #929cab;
  margin: 0;
  line-height: 1.8;
}
.export-report {
  font-size: 11px;
  height: 40px;
  white-space: nowrap;
}
.analysis-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 21px;
}
.report-month {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #91a0b3;
}
.report-month > .icon-btn {
  border: 0;
  width: 26px;
  height: 29px;
  background: transparent;
  color: #8b9bb0;
}
.report-month > label {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 550;
  color: #526883;
  white-space: nowrap;
}
.report-month input {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  cursor: pointer;
}
.report-month input::-webkit-calendar-picker-indicator {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  cursor: pointer;
}
.report-month > label > svg {
  color: #9eacbc;
}
.return-current {
  font: inherit;
  font-size: 10px;
  color: #7291ba;
  background: #eef3f8;
  border: 1px solid #e2eaf2;
  border-radius: 5px;
  padding: 3px 7px;
  cursor: pointer;
}
.report-scope {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 9px;
  color: #a2afbf;
}
.report-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 17px;
  margin-bottom: 24px;
}
.summary-card {
  padding: 20px 23px 18px;
  background: #fffefa;
  border: 1px solid #e6e9e8;
  border-radius: 13px;
  box-shadow: 0 3px 12px #182e4a03;
  min-width: 0;
}
.summary-card > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #909fb1;
  font-size: 10px;
}
.summary-icon {
  display: grid;
  place-items: center;
  width: 29px;
  height: 29px;
  border-radius: 9px;
}
.summary-icon.income {
  color: #7b96ce;
  background: #eef2fa;
}
.summary-icon.expense {
  color: #84b09b;
  background: #edf5ef;
}
.summary-icon.net {
  color: #c1a274;
  background: #f9f3e8;
}
.summary-icon.rate {
  color: #a495c0;
  background: #f3f0f8;
}
.summary-card > strong {
  display: block;
  margin: 8px 0 10px;
  font-size: clamp(23px, 2.1vw, 31px);
  font-weight: 600;
  color: #354660;
  letter-spacing: -0.6px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.summary-card > strong > small {
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0;
  color: #9aa9bd;
  margin-right: 5px;
}
.summary-card .percent-sign {
  margin-left: 4px;
  margin-right: 0;
}
.summary-card p {
  font-size: 9px;
  margin: 0;
  color: #aab4c2;
}
.summary-card .negative {
  color: #a27d70;
}
.charts-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(295px, 1fr);
  gap: 22px;
  margin-bottom: 24px;
}
.trend-panel,
.category-panel,
.breakdown-panel {
  background: #fffefa;
  border: 1px solid #e6e9e8;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 3px 12px #182e4a03;
  min-width: 0;
}
.chart-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 15px;
  padding: 23px 24px 0;
}
.chart-header h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #53677f;
  margin: 0 0 8px;
}
.chart-header h2 svg {
  color: #94a6bc;
}
.chart-header p {
  font-size: 9px;
  color: #a5b0bf;
  margin: 0;
}
.chart-switch {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 3px;
  background: #f1f3f0;
  border: 1px solid #e9ece7;
  border-radius: 7px;
}
.chart-switch button {
  font: inherit;
  font-size: 9px;
  color: #a0aebb;
  border: 0;
  background: none;
  border-radius: 5px;
  padding: 5px 9px;
  white-space: nowrap;
  cursor: pointer;
}
.chart-switch button.active {
  background: #fff;
  color: #7895c4;
  box-shadow: 0 1px 4px #23364c09;
}
.chart-caption {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  padding: 24px 26px 10px;
  font-size: 8px;
  color: #adb7c5;
}
.chart-legend {
  display: flex;
  align-items: center;
  gap: 18px;
}
.chart-legend > span {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 9px;
  color: #8f9caf;
}
.chart-legend i {
  width: 7px;
  height: 7px;
  border-radius: 2px;
}
.chart-legend i.income {
  background: #6f8ce1;
}
.chart-legend i.expense {
  background: #6bc2ad;
}
.trend-wrap {
  padding: 10px 25px 16px;
  height: 290px;
}
.trend-wrap :deep(.line-chart) {
  height: 100%;
  width: 100%;
}
.trend-wrap :deep(svg) {
  width: 100%;
  height: 100%;
  overflow: visible;
}
.trend-wrap :deep(svg text) {
  fill: #aeb8c6;
  font-size: 9px;
}
.trend-note {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 12px 25px;
  border-top: 1px solid #eef0eb;
  color: #adb7c4;
  font-size: 8px;
  line-height: 1.7;
}
.category-count {
  font-size: 9px;
  color: #a6b1c1;
  border: 1px solid #e7ebe5;
  border-radius: 5px;
  padding: 3px 7px;
  white-space: nowrap;
}
.category-panel :deep(.category-chart) {
  padding-top: 25px;
}
.category-panel :deep(.donut-hole) {
  background: #fffefa;
}
.chart-loading {
  min-height: 306px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 13px;
  color: #a5b3c6;
  font-size: 11px;
}
.donut-loading {
  min-height: 380px;
}
.breakdown-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
}
.breakdown-header h2 {
  font-size: 13px;
  font-weight: 600;
  color: #53677f;
  margin: 0 0 7px;
}
.breakdown-header p {
  font-size: 9px;
  color: #a5b0bf;
  margin: 0;
  max-width: 430px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.breakdown-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}
.category-search {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid #e6eae5;
  border-radius: 7px;
  padding: 7px 10px;
  color: #9facbf;
  background: #f9faf7;
  width: 145px;
}
.category-search input {
  font: inherit;
  font-size: 9px;
  color: #71859f;
  min-width: 0;
  width: 100%;
  outline: 0;
  border: 0;
  background: none;
}
.category-search input::placeholder {
  color: #a9b4c5;
}
.sort-button {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: none;
  color: #99a9bd;
  font: inherit;
  font-size: 9px;
  cursor: pointer;
  white-space: nowrap;
}
.breakdown-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.breakdown-table th {
  font-size: 9px;
  font-weight: 500;
  text-align: left;
  color: #98a7bb;
  background: #f6f7f3;
  padding: 12px 24px;
  border-block: 1px solid #eaede7;
}
.breakdown-table th:first-child {
  width: 34%;
}
.breakdown-table th:nth-child(2) {
  width: 22%;
  text-align: right;
}
.breakdown-table th:nth-child(3) {
  width: 18%;
  text-align: right;
}
.breakdown-table th:nth-child(4) {
  width: 26%;
  padding-left: 40px;
}
.breakdown-table td {
  padding: 18px 24px;
  border-bottom: 1px solid #eef0e9;
  font-size: 11px;
}
.breakdown-table tbody tr:last-child td {
  border-bottom: 0;
}
.breakdown-table td:first-child {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.category-rank {
  display: inline-block;
  width: 26px;
  color: #b4bdcb;
  font-size: 9px;
  font-variant-numeric: tabular-nums;
}
.category-marker {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 2px;
  margin: 0 11px 1px 0;
}
.category-name {
  font-size: 11px;
  color: #778aa4;
}
.breakdown-table .category-amount {
  text-align: right;
  font-size: 12px;
  font-weight: 550;
  color: #657892;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.category-amount small {
  font-size: 10px;
  font-weight: 400;
  color: #a2b0c3;
  margin-right: 5px;
}
.breakdown-table .category-share {
  text-align: right;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: #91a0b6;
}
.category-share small {
  font-size: 9px;
  margin-left: 2px;
}
.breakdown-table .distribution-cell {
  padding-left: 40px;
  padding-right: 30px;
}
.distribution-track {
  height: 5px;
  background: #f0f3ef;
  border-radius: 4px;
  width: 100%;
}
.distribution-track > div {
  height: 100%;
  border-radius: 4px;
  min-width: 2px;
}
.breakdown-table tfoot td {
  background: #f9faf7;
  border-block: 1px solid #e9ede5;
  padding-top: 14px;
  padding-bottom: 14px;
  color: #8b9ab0;
  font-size: 10px;
}
.breakdown-table tfoot .category-amount {
  font-size: 13px;
  color: #6f84a2;
}
.breakdown-footer {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 25px;
  color: #acb7c7;
  font-size: 8px;
}
.breakdown-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 25px;
  color: #a6b3c7;
  border-top: 1px solid #edf0e8;
}
.breakdown-empty > svg {
  margin-bottom: 15px;
  color: #b8c6d5;
}
.breakdown-empty strong {
  font-size: 12px;
  font-weight: 500;
  color: #8598b1;
}
.breakdown-empty p {
  font-size: 10px;
  color: #acb8c8;
  margin: 9px 0 0;
}
.breakdown-empty > button {
  border: 0;
  background: none;
  color: #7c9aca;
  font: inherit;
  font-size: 10px;
  margin-top: 16px;
  cursor: pointer;
}
.breakdown-loading > div {
  display: flex;
  align-items: center;
  gap: 17px;
  padding: 23px 26px;
  border-top: 1px solid #eef0eb;
  animation: pulse 1.3s infinite;
}
.breakdown-loading i {
  width: 6px;
  height: 6px;
  background: #e8ede5;
}
.breakdown-loading span {
  height: 12px;
  width: 30%;
  border-radius: 4px;
  background: #f0f3ec;
}
.breakdown-loading b {
  height: 12px;
  width: 13%;
  border-radius: 4px;
  background: #f0f3ec;
  margin-left: auto;
  margin-right: 25%;
}
.report-error {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  min-height: 330px;
  background: #fffefa;
  border: 1px solid #e6e9e8;
  border-radius: 14px;
  padding: 30px;
  color: #bba18b;
}
.report-error h2 {
  font-size: 15px;
  color: #8394ad;
  font-weight: 500;
  margin: 19px 0 9px;
}
.report-error p {
  font-size: 11px;
  color: #a3afc0;
  margin: 0 0 20px;
  max-width: 500px;
  line-height: 1.8;
  text-align: center;
}
.report-error .btn {
  font-size: 10px;
}
.analysis-footnote {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  font-size: 9px;
  color: #aab6c6;
  margin: 21px 0 3px;
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
  .trend-wrap {
    height: 325px;
  }
  .summary-card > strong {
    font-size: 32px;
  }
  .category-panel :deep(.category-chart) {
    padding-top: 29px;
  }
  .category-panel :deep(.donut) {
    width: 180px;
    height: 180px;
  }
  .breakdown-table td {
    padding-block: 20px;
  }
}
@media (max-width: 1150px) {
  .summary-card {
    padding: 18px;
  }
  .summary-card > strong {
    font-size: 26px;
  }
  .report-summary {
    gap: 12px;
  }
  .charts-grid {
    grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr);
    gap: 18px;
  }
  .chart-header {
    padding: 20px 20px 0;
    gap: 9px;
  }
  .chart-header h2 {
    font-size: 12px;
  }
  .chart-switch button {
    padding: 4px 7px;
    font-size: 8px;
  }
  .chart-caption {
    padding: 23px 20px 8px;
    font-size: 7px;
  }
  .trend-wrap {
    padding-inline: 17px;
    height: 277px;
  }
  .trend-note {
    padding-inline: 20px;
    font-size: 7px;
  }
  .breakdown-header {
    padding: 21px;
  }
  .breakdown-tools {
    gap: 9px;
  }
  .category-search {
    width: 125px;
  }
  .sort-button {
    font-size: 8px;
  }
  .breakdown-table th,
  .breakdown-table td {
    padding-inline: 21px;
  }
}
@media (max-width: 850px) {
  .analysis-heading h1 {
    font-size: 27px;
  }
  .analysis-heading p {
    font-size: 11px;
  }
  .summary-card {
    padding: 17px 16px;
  }
  .summary-card > strong {
    font-size: 23px;
  }
  .summary-card p {
    font-size: 8px;
  }
  .summary-card > div {
    font-size: 9px;
  }
  .summary-icon {
    width: 25px;
    height: 25px;
    border-radius: 7px;
  }
  .summary-icon svg {
    width: 15px;
  }
  .charts-grid {
    grid-template-columns: 1fr;
    gap: 20px;
  }
  .trend-wrap {
    height: 295px;
    padding-inline: 22px;
  }
  .category-panel :deep(.category-chart) {
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: center;
    gap: 22px;
    padding: 25px 35px 26px;
  }
  .category-panel :deep(.donut-wrap) {
    padding: 0;
  }
  .category-panel :deep(.category-legend) {
    gap: 15px;
  }
  .category-panel :deep(.category-empty) {
    text-align: left;
  }
  .donut-loading {
    min-height: 230px;
  }
  .report-scope {
    font-size: 8px;
  }
  .breakdown-tools {
    gap: 8px;
  }
  .category-search {
    width: 120px;
  }
  .sort-button span {
    display: none;
  }
  .sort-button {
    padding: 8px;
  }
  .breakdown-header p {
    max-width: 320px;
  }
  .chart-header {
    padding: 22px 24px 0;
  }
  .chart-header h2 {
    font-size: 13px;
  }
  .chart-switch button {
    font-size: 9px;
    padding: 5px 9px;
  }
  .chart-caption {
    font-size: 8px;
    padding: 23px 24px 10px;
  }
  .trend-note {
    font-size: 8px;
    padding-inline: 24px;
  }
  .category-count {
    font-size: 8px;
  }
  .analysis-footnote {
    font-size: 8px;
  }
}
@media (max-width: 620px) {
  .analysis-heading {
    margin-bottom: 21px;
    gap: 14px;
  }
  .analysis-heading h1 {
    font-size: 25px;
    margin-bottom: 8px;
  }
  .analysis-eyebrow {
    font-size: 8px;
    letter-spacing: 1.4px;
    margin-bottom: 8px;
  }
  .analysis-heading p {
    font-size: 10px;
    max-width: 260px;
  }
  .export-report {
    font-size: 10px;
    height: 35px;
    padding-inline: 11px;
    gap: 6px;
  }
  .export-report svg {
    width: 14px;
  }
  .analysis-controls {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 18px;
  }
  .report-month {
    gap: 7px;
  }
  .report-month > label {
    font-size: 13px;
  }
  .report-month > svg {
    width: 15px;
  }
  .report-month > .icon-btn {
    width: 22px;
    height: 25px;
  }
  .report-scope {
    font-size: 8px;
    gap: 4px;
  }
  .report-scope svg {
    width: 11px;
  }
  .report-summary {
    grid-template-columns: 1fr 1fr;
    gap: 11px;
    margin-bottom: 20px;
  }
  .summary-card {
    padding: 15px 18px 14px;
    border-radius: 12px;
  }
  .summary-card > strong {
    font-size: 27px;
    margin: 9px 0 9px;
  }
  .summary-card > strong > small {
    font-size: 14px;
  }
  .summary-card p {
    font-size: 8px;
  }
  .summary-card > div {
    font-size: 10px;
  }
  .summary-icon {
    width: 26px;
    height: 26px;
  }
  .charts-grid {
    gap: 19px;
    margin-bottom: 20px;
  }
  .trend-panel,
  .category-panel,
  .breakdown-panel {
    border-radius: 12px;
  }
  .chart-header {
    padding: 18px 18px 0;
  }
  .chart-header h2 {
    font-size: 12px;
    margin-bottom: 7px;
    gap: 6px;
  }
  .chart-header h2 svg {
    width: 15px;
  }
  .chart-header p {
    font-size: 8px;
  }
  .chart-switch button {
    font-size: 8px;
    padding: 5px 7px;
  }
  .chart-switch {
    gap: 1px;
    padding: 2px;
    border-radius: 6px;
  }
  .chart-caption {
    padding: 21px 18px 7px;
    gap: 7px;
    font-size: 7px;
  }
  .chart-legend {
    gap: 12px;
  }
  .chart-legend > span {
    font-size: 8px;
    gap: 5px;
  }
  .chart-legend i {
    width: 6px;
    height: 6px;
  }
  .trend-wrap {
    height: 233px;
    padding: 11px 13px 17px 7px;
  }
  .trend-note {
    font-size: 7px;
    padding: 10px 17px;
    gap: 4px;
  }
  .trend-note svg {
    width: 10px;
    flex-shrink: 0;
  }
  .category-panel :deep(.category-chart) {
    grid-template-columns: 1fr 1fr;
    padding: 24px 20px;
    gap: 17px;
  }
  .category-panel :deep(.donut) {
    width: 135px;
    height: 135px;
    padding: 16px;
  }
  .category-panel :deep(.donut-hole > strong) {
    font-size: 16px;
    margin: 8px 0 6px;
  }
  .category-panel :deep(.donut-hole > span) {
    font-size: 8px;
  }
  .category-panel :deep(.donut-hole > small) {
    font-size: 7px;
  }
  .category-panel :deep(.category-legend) {
    gap: 12px;
  }
  .category-panel :deep(.category-legend > div) {
    font-size: 9px;
    gap: 5px;
  }
  .category-panel :deep(.category-legend small) {
    display: none;
  }
  .category-panel :deep(.category-legend b) {
    font-size: 8px;
    width: 30px;
  }
  .category-panel :deep(.category-legend i) {
    width: 5px;
    height: 5px;
    flex-shrink: 0;
  }
  .category-panel :deep(.category-empty) {
    font-size: 9px;
    line-height: 1.8;
  }
  .category-count {
    font-size: 7px;
    padding: 3px 6px;
  }
  .breakdown-header {
    padding: 19px 17px;
    gap: 12px;
    align-items: flex-start;
    flex-direction: column;
  }
  .breakdown-header h2 {
    font-size: 12px;
  }
  .breakdown-header p {
    font-size: 8px;
    max-width: 300px;
  }
  .breakdown-tools {
    width: 100%;
    justify-content: space-between;
    gap: 12px;
  }
  .category-search {
    width: 185px;
    padding: 7px 9px;
  }
  .category-search input {
    font-size: 9px;
  }
  .sort-button span {
    display: inline;
    font-size: 8px;
  }
  .breakdown-table th {
    font-size: 8px;
    padding: 11px 17px;
  }
  .breakdown-table td {
    padding: 15px 17px;
  }
  .breakdown-table th:first-child {
    width: 46%;
  }
  .breakdown-table th:nth-child(2) {
    width: 32%;
  }
  .breakdown-table th:nth-child(3) {
    width: 22%;
  }
  .distribution-heading,
  .distribution-cell {
    display: none;
  }
  .category-rank {
    font-size: 8px;
    width: 20px;
  }
  .category-marker {
    width: 5px;
    height: 5px;
    margin-right: 7px;
  }
  .category-name {
    font-size: 10px;
  }
  .breakdown-table .category-amount {
    font-size: 11px;
  }
  .category-amount small {
    font-size: 8px;
    margin-right: 3px;
  }
  .breakdown-table .category-share {
    font-size: 9px;
  }
  .category-share small {
    font-size: 8px;
  }
  .breakdown-table tfoot td {
    font-size: 8px;
    padding-top: 13px;
    padding-bottom: 13px;
  }
  .breakdown-table tfoot .category-amount {
    font-size: 12px;
  }
  .breakdown-footer {
    padding: 12px 17px;
    font-size: 7px;
    gap: 10px;
  }
  .breakdown-footer > span:last-child {
    max-width: 170px;
    text-align: right;
  }
  .breakdown-empty {
    min-height: 210px;
    padding: 25px 20px;
  }
  .breakdown-empty strong {
    font-size: 11px;
  }
  .breakdown-empty p {
    font-size: 9px;
    line-height: 1.8;
    text-align: center;
  }
  .analysis-footnote {
    font-size: 7px;
    gap: 4px;
    margin-top: 18px;
  }
  .analysis-footnote svg {
    width: 11px;
  }
  .chart-loading {
    min-height: 255px;
    font-size: 10px;
  }
  .donut-loading {
    min-height: 190px;
  }
  .report-error {
    min-height: 290px;
  }
  .report-error h2 {
    font-size: 14px;
  }
  .report-error p {
    font-size: 10px;
  }
}
@media (max-width: 370px) {
  .summary-card {
    padding-inline: 14px;
  }
  .summary-card > strong {
    font-size: 24px;
  }
  .category-panel :deep(.category-chart) {
    gap: 12px;
    padding-inline: 16px;
  }
  .category-panel :deep(.donut) {
    width: 124px;
    height: 124px;
    padding: 15px;
  }
  .category-search {
    width: 165px;
  }
  .breakdown-table th,
  .breakdown-table td {
    padding-inline: 13px;
  }
  .category-rank {
    width: 17px;
  }
  .chart-switch button {
    font-size: 7px;
    padding: 5px 6px;
  }
  .trend-wrap {
    height: 215px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin,
  .breakdown-loading > div {
    animation: none;
  }
}
</style>
