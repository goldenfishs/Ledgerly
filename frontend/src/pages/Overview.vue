<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ArrowRight,
  Wallet,
  ChartNoAxesCombined,
  CalendarDays,
  Clock3,
  Plus,
  ReceiptText,
  Users,
  ChevronRight,
  ArrowLeftRight,
  Sparkles,
  ShieldCheck,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { state, bus } from "../lib/app";
import { money, monthKey } from "../lib/format";
import TrendChart from "../components/TrendChart.vue";
import CategoryChart from "../components/CategoryChart.vue";
const month = ref(monthKey()),
  data = ref(null),
  error = ref(""),
  loading = ref(false);
let sequence = 0;
async function load() {
  const seq = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await api("/dashboard", { query: { month: month.value } });
    if (seq === sequence) data.value = result;
  } catch (e) {
    if (seq === sequence) error.value = e.message;
  } finally {
    if (seq === sequence) loading.value = false;
  }
}
const admin = computed(() => state.user?.role === "admin");
const greeting = computed(() => {
  const h = new Date().getHours();
  return h < 12 ? "上午好" : h < 18 ? "下午好" : "晚上好";
});
const statuses = { pending: "待审核", approved: "已通过", rejected: "已驳回" };
watch(month, load);
onMounted(() => {
  load();
  bus.addEventListener("ledger-change", load);
});
onUnmounted(() => bus.removeEventListener("ledger-change", load));
</script>
<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-eyebrow">WORKSPACE OVERVIEW</div>
        <h1>
          {{ greeting }}，{{ state.user?.name || "" }}
          <span class="greeting-dot">☀</span>
        </h1>
        <p>{{ state.activeLedger?.name }}的每笔收支，都清清楚楚。</p>
      </div>
      <div class="header-actions">
        <label class="period-control"
          ><CalendarDays :size="15" /><input
            v-model="month"
            type="month"
            aria-label="工作台月份"
        /></label>
      </div>
    </div>
    <div v-if="error" class="error-box">
      {{ error }} <button class="link-btn" @click="load">重试</button>
    </div>
    <div v-if="loading && !data" class="loading-state">
      <span class="spinner"></span>正在整理工作区数据…
    </div>
    <template v-if="data"
      ><div class="notice-banner" v-if="data.pendingCount">
        <Clock3 :size="17" /><span
          >有 <strong>{{ data.pendingCount }} 笔流水</strong
          >{{
            admin
              ? "等待审核，处理后将更新账户余额。"
              : "等待管理员审核，可在收支流水中查看进度。"
          }}</span
        ><RouterLink to="/transactions?status=pending" class="link-btn"
          >{{ admin ? "前往审核" : "查看进度" }}<ArrowRight :size="13"
        /></RouterLink>
      </div>
      <div class="notice-banner" v-else-if="!data.accounts.length">
        <Sparkles :size="17" /><span>{{
          admin
            ? "新账本已准备好。先添加资金账户，再记录第一笔收支。"
            : "账本已就绪。管理员添加资金账户后，即可开始提交收支。"
        }}</span
        ><RouterLink v-if="admin" to="/accounts" class="link-btn"
          >添加账户<ArrowRight :size="13"
        /></RouterLink>
      </div>
      <section class="metrics-grid" aria-label="月度财务概览">
        <article class="card metric">
          <div class="metric-top">
            本月收入<span class="metric-icon green"
              ><ArrowDownLeft :size="17"
            /></span>
          </div>
          <div class="metric-value">
            <small>¥</small>{{ money(data.income) }}
          </div>
          <div class="metric-foot">
            <span class="text-green">已审核入账</span
            ><span>· {{ admin ? "全体成员" : "我的提交" }}</span>
          </div>
        </article>
        <article class="card metric">
          <div class="metric-top">
            本月支出<span class="metric-icon orange"
              ><ArrowUpRight :size="17"
            /></span>
          </div>
          <div class="metric-value">
            <small>¥</small>{{ money(data.expense) }}
          </div>
          <div class="metric-foot">资金去向，每一笔有据可循</div>
        </article>
        <article class="card metric">
          <div class="metric-top">
            本月结余<span class="metric-icon"
              ><ChartNoAxesCombined :size="17"
            /></span>
          </div>
          <div class="metric-value"><small>¥</small>{{ money(data.net) }}</div>
          <div class="metric-foot">收入 − 支出<span>· 不含账户转账</span></div>
        </article>
        <article class="card metric">
          <div class="metric-top">
            {{ admin ? "账户净资产" : "我的待审核"
            }}<span class="metric-icon purple"
              ><Wallet v-if="admin" :size="17" /><Clock3 v-else :size="17"
            /></span>
          </div>
          <div class="metric-value">
            <small>{{ admin ? "¥" : "" }}</small
            >{{ admin ? money(data.assets) : data.pendingCount
            }}<small v-if="!admin" style="margin-left: 7px; font-size: 12px"
              >笔</small
            >
          </div>
          <div class="metric-foot">
            {{ admin ? "全部账户余额 − 负债余额" : "提交后等待管理员确认入账" }}
          </div>
        </article>
      </section>
      <div class="section-grid">
        <section class="card">
          <div class="card-head">
            <div>
              <h2>收支趋势</h2>
              <p>每一天的资金流动，一目了然</p>
            </div>
            <div class="legend">
              <span><i></i>收入</span><span><i class="green"></i>支出</span>
            </div>
          </div>
          <TrendChart :points="data.trend" />
        </section>
        <section class="card">
          <div class="card-head">
            <div>
              <h2>支出构成</h2>
              <p>了解资金花在了哪里</p>
            </div>
            <RouterLink to="/analysis" class="link-btn"
              ><ChevronRight :size="17"
            /></RouterLink>
          </div>
          <CategoryChart :items="data.categories" />
        </section>
      </div>
      <div class="section-grid">
        <section class="card recent-card">
          <div class="card-head">
            <div>
              <h2>最近流水</h2>
              <p>
                {{ admin ? "当前账本的最新收支记录" : "你提交的最新收支记录" }}
              </p>
            </div>
            <RouterLink to="/transactions" class="link-btn"
              >查看全部<ArrowRight :size="13"
            /></RouterLink>
          </div>
          <div v-if="!data.recent.length" class="empty-state">
            <ArrowLeftRight :size="32" :stroke-width="1.2" />
            <h3>账本的第一页，等你来记录</h3>
            <p>记下收入与支出，让团队的每一笔资金都有迹可循。</p>
            <button
              class="btn btn-secondary btn-sm"
              @click="bus.dispatchEvent(new Event('new-flow'))"
            >
              <Plus :size="14" />记录第一笔
            </button>
          </div>
          <div v-else class="table-wrap" style="margin-top: 20px">
            <table>
              <thead>
                <tr>
                  <th>收支项目</th>
                  <th>日期 / 经办人</th>
                  <th>状态</th>
                  <th class="text-right">金额</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in data.recent.slice(0, 5)" :key="row.id">
                  <td>
                    <div style="display: flex; gap: 10px; align-items: center">
                      <span
                        class="recent-type"
                        :class="
                          row.action.handle === 0
                            ? 'income'
                            : row.action.handle === 1
                              ? 'expense'
                              : ''
                        "
                        ><ArrowDownLeft
                          v-if="row.action.handle === 0"
                          :size="15" /><ArrowUpRight
                          v-else-if="row.action.handle === 1"
                          :size="15" /><ArrowLeftRight v-else :size="15"
                      /></span>
                      <div>
                        <div class="table-main">
                          {{ row.type?.tname || row.action.hname }}
                        </div>
                        <div class="table-sub">{{ row.account?.name }}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    {{ row.fdate }}
                    <div class="table-sub">{{ row.ownerName }}</div>
                  </td>
                  <td>
                    <span
                      class="badge"
                      :class="{
                        'badge-green': row.status === 'approved',
                        'badge-amber': row.status === 'pending',
                        'badge-red': row.status === 'rejected',
                      }"
                      >{{ statuses[row.status] }}</span
                    >
                  </td>
                  <td
                    class="text-right amount"
                    :class="
                      row.action.handle === 0
                        ? 'text-green'
                        : row.action.handle === 1
                          ? 'text-red'
                          : ''
                    "
                  >
                    {{
                      row.action.handle === 0
                        ? "+"
                        : row.action.handle === 1
                          ? "−"
                          : ""
                    }}{{ money(row.money) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="card">
          <div class="card-head">
            <div>
              <h2>常用操作</h2>
              <p>把日常工作，处理得更简单</p>
            </div>
          </div>
          <div class="quick-list">
            <button
              class="quick-link quick-button"
              @click="bus.dispatchEvent(new Event('new-flow'))"
            >
              <span class="quick-icon"><Plus :size="18" /></span>
              <div>
                <strong>记录一笔收支</strong>
                <p>支出、收入或账户间转账</p>
              </div>
              <ChevronRight :size="15" /></button
            ><RouterLink to="/invoices" class="quick-link"
              ><span class="quick-icon purple"><ReceiptText :size="18" /></span>
              <div>
                <strong>整理发票凭证</strong>
                <p>上传、识别与归档，集中管理</p>
              </div>
              <ChevronRight :size="15" /></RouterLink
            ><RouterLink
              :to="admin ? '/team' : '/transactions'"
              class="quick-link"
              ><span class="quick-icon green"
                ><Users v-if="admin" :size="18" /><ShieldCheck
                  v-else
                  :size="18"
              /></span>
              <div>
                <strong>{{
                  admin ? "邀请伙伴一起记账" : "查看审核进度"
                }}</strong>
                <p>
                  {{
                    admin
                      ? "一起管理账本，分工更清楚"
                      : "跟进提交记录，及时处理驳回"
                  }}
                </p>
              </div>
              <ChevronRight :size="15"
            /></RouterLink>
          </div>
          <div class="workspace-tip">
            <ShieldCheck :size="15" /><span
              >仅审核通过的流水计入余额和报表</span
            >
          </div>
        </section>
      </div></template
    >
  </div>
</template>
<style scoped>
.greeting-dot {
  color: #e6b66d;
  font-size: 23px;
  font-weight: 300;
  margin-left: 4px;
}
.quick-button {
  border: 0;
  border-bottom: 1px solid #f0f3f7;
  background: none;
  width: 100%;
  text-align: left;
}
.workspace-tip {
  margin: 6px 23px 23px;
  background: #f8fafc;
  padding: 12px 10px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #9babbe;
  font-size: 9px;
  border-radius: 6px;
}
.recent-card .card-head {
  padding-bottom: 2px;
}
</style>
