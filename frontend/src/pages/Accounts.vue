<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from "vue";
import {
  Wallet,
  Plus,
  Landmark,
  CreditCard,
  MoreHorizontal,
  X,
  ShieldCheck,
  Archive,
  ArrowUpRight,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { state, notify, bus } from "../lib/app";
import { money } from "../lib/format";
const accounts = ref([]),
  loading = ref(true),
  error = ref(""),
  filter = ref("active"),
  editor = ref(false),
  saving = ref(false),
  formError = ref(""),
  selected = ref(null),
  archiveTarget = ref(null);
const form = reactive({
  name: "",
  initialMoney: "0.00",
  accountType: 0,
  card: "",
  enable: true,
});
const admin = computed(() => state.user?.role === "admin");
const visible = computed(() =>
  accounts.value.filter(
    (a) =>
      filter.value === "all" ||
      (filter.value === "active" ? a.enable : !a.enable),
  ),
);
const assetTotal = computed(() =>
  accounts.value
    .filter((a) => a.accountType === 0)
    .reduce((n, a) => n + Number(a.money), 0),
);
const debtTotal = computed(() =>
  accounts.value
    .filter((a) => a.accountType === 1)
    .reduce((n, a) => n + Number(a.money), 0),
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    accounts.value = await api("/account/getAccount");
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function open(account) {
  selected.value = account || null;
  Object.assign(form, {
    name: account?.name || "",
    initialMoney: account?.initialMoney ?? "0.00",
    accountType: account?.accountType ?? 0,
    card: account?.card || "",
    enable: account?.enable ?? true,
  });
  formError.value = "";
  editor.value = true;
}
async function save() {
  saving.value = true;
  formError.value = "";
  try {
    await api(
      selected.value
        ? `/account/updateAccount/${selected.value.id}`
        : "/account/addAccount",
      {
        method: selected.value ? "PUT" : "POST",
        body: { ...form, accountType: Number(form.accountType) },
      },
    );
    editor.value = false;
    notify(selected.value ? "账户已更新" : "账户已创建");
    await load();
    bus.dispatchEvent(new Event("ledger-change"));
  } catch (e) {
    formError.value = e.message;
  } finally {
    saving.value = false;
  }
}
async function archive() {
  saving.value = true;
  try {
    await api(`/account/deleteAccount/${archiveTarget.value.id}`, {
      method: "DELETE",
    });
    archiveTarget.value = null;
    notify("账户已归档，历史记录保留");
    await load();
    bus.dispatchEvent(new Event("ledger-change"));
  } catch (e) {
    notify(e.message, "error");
  } finally {
    saving.value = false;
  }
}
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
        <div class="page-eyebrow">ACCOUNTS & BALANCES</div>
        <h1>资金账户</h1>
        <p>
          {{
            admin
              ? "管理当前账本的资金账户与余额。"
              : "当前账本可使用的账户，余额由账本管理员管理。"
          }}
        </p>
      </div>
      <button v-if="admin" class="btn btn-primary" @click="open()">
        <Plus :size="16" />添加账户
      </button>
    </div>
    <div class="metrics-grid accounts-metrics" v-if="admin">
      <div class="card metric">
        <div class="metric-top">
          资产余额<span class="metric-icon"><Wallet :size="17" /></span>
        </div>
        <div class="metric-value"><small>¥</small>{{ money(assetTotal) }}</div>
        <div class="metric-foot">包含全部资产账户</div>
      </div>
      <div class="card metric">
        <div class="metric-top">
          负债余额<span class="metric-icon orange"
            ><CreditCard :size="17"
          /></span>
        </div>
        <div class="metric-value"><small>¥</small>{{ money(debtTotal) }}</div>
        <div class="metric-foot">待偿还金额，以正数表示</div>
      </div>
      <div class="card metric">
        <div class="metric-top">
          账户净资产<span class="metric-icon green"
            ><Landmark :size="17"
          /></span>
        </div>
        <div class="metric-value">
          <small>¥</small>{{ money(assetTotal - debtTotal) }}
        </div>
        <div class="metric-foot">资产余额 − 负债余额</div>
      </div>
    </div>
    <div class="row-between" style="margin-bottom: 20px">
      <div class="tabs">
        <button
          :class="{ active: filter === 'active' }"
          @click="filter = 'active'"
        >
          使用中</button
        ><button
          v-if="admin"
          :class="{ active: filter === 'archived' }"
          @click="filter = 'archived'"
        >
          已归档</button
        ><button :class="{ active: filter === 'all' }" @click="filter = 'all'">
          全部账户
        </button>
      </div>
      <span class="muted small">{{ visible.length }} 个账户</span>
    </div>
    <div v-if="error" class="error-box">
      {{ error }} <button class="link-btn" @click="load">重试</button>
    </div>
    <div v-if="loading" class="loading-state">
      <span class="spinner"></span>正在读取账户…
    </div>
    <div v-else-if="!visible.length" class="card empty-state">
      <Wallet :size="36" :stroke-width="1.2" />
      <h3>
        {{ filter === "archived" ? "暂无归档账户" : "添加账户，开启清晰记账" }}
      </h3>
      <p>
        {{
          admin
            ? "可按银行账户、备用金或支付平台分别管理。"
            : "管理员添加账户后，会显示在这里。"
        }}
      </p>
      <button
        v-if="admin && filter !== 'archived'"
        class="btn btn-primary btn-sm"
        @click="open()"
      >
        <Plus :size="14" />添加第一个账户
      </button>
    </div>
    <div v-else class="account-grid">
      <article
        class="card account-card"
        v-for="account in visible"
        :key="account.id"
      >
        <div class="row-between">
          <span class="account-symbol"
            ><CreditCard v-if="account.accountType === 1" :size="21" /><Landmark
              v-else
              :size="21" /></span
          ><button
            v-if="admin"
            class="icon-btn"
            :aria-label="'编辑账户 ' + account.name"
            @click="open(account)"
          >
            <MoreHorizontal :size="19" />
          </button>
        </div>
        <div class="row-between">
          <h3>{{ account.name }}</h3>
          <span
            class="badge"
            :class="
              !account.enable
                ? ''
                : account.accountType === 1
                  ? 'badge-amber'
                  : 'badge-blue'
            "
            >{{
              !account.enable
                ? "已归档"
                : account.accountType === 1
                  ? "负债账户"
                  : "资产账户"
            }}</span
          >
        </div>
        <p class="muted small">{{ account.card || "未填写账户备注" }}</p>
        <div v-if="admin" class="account-balance">
          <span
            class="muted"
            style="font-size: 16px; font-weight: 400; margin-right: 6px"
            >¥</span
          >{{ money(account.money) }}
        </div>
        <div
          v-else
          class="account-balance"
          style="font-size: 13px; color: #9aa6b9"
        >
          <ShieldCheck
            :size="15"
            style="vertical-align: middle; margin-right: 5px"
          />余额仅管理员可见
        </div>
        <div class="row-between account-foot">
          <span>{{
            admin
              ? "期初余额 ¥" + money(account.initialMoney)
              : "可提交收支及转账"
          }}</span
          ><button
            v-if="admin && account.enable"
            class="link-btn"
            :aria-label="'归档账户 ' + account.name"
            @click="archiveTarget = account"
          >
            <Archive :size="13" />归档
          </button>
        </div>
      </article>
    </div>
    <div class="info-box" style="margin-top: 22px">
      <ShieldCheck :size="16" /><span
        >余额由期初金额和已审核流水自动计算。归档账户保留历史流水与余额，不能用于新记账。</span
      >
    </div>
    <div
      v-if="editor"
      class="modal-backdrop"
      @click.self="!saving && (editor = false)"
    >
      <form
        class="dialog card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="account-title"
        @submit.prevent="save"
      >
        <div class="dialog-header">
          <div>
            <h2 id="account-title">
              {{ selected ? "编辑账户" : "添加资金账户" }}
            </h2>
            <p class="muted small">给每一笔资金，一个清楚的归属。</p>
          </div>
          <button
            class="icon-btn"
            type="button"
            aria-label="关闭账户表单"
            @click="editor = false"
            :disabled="saving"
          >
            <X :size="19" />
          </button>
        </div>
        <label class="field"
          ><span>账户名称</span
          ><input
            v-model.trim="form.name"
            required
            maxlength="80"
            placeholder="例如：公司基本户 / 备用金"
        /></label>
        <div class="form-grid">
          <label class="field"
            ><span>账户类型</span
            ><select v-model.number="form.accountType">
              <option :value="0">资产账户</option>
              <option :value="1">负债账户</option>
            </select></label
          ><label class="field"
            ><span
              >期初{{ form.accountType === 1 ? "负债" : "余额" }}（元）</span
            ><input
              v-model="form.initialMoney"
              type="number"
              step="0.01"
              required
              inputmode="decimal"
            /><small>建立账本时的余额</small></label
          >
        </div>
        <label class="field"
          ><span>账户备注 <span class="muted">· 选填</span></span
          ><input
            v-model.trim="form.card"
            maxlength="100"
            placeholder="开户行、账号尾号或用途" /></label
        ><label v-if="selected" class="checkbox-line"
          ><input type="checkbox" v-model="form.enable" />启用此账户</label
        >
        <div v-if="selected" class="info-box">
          修改期初余额会影响当前余额，请依据实际账务核对。
        </div>
        <div v-if="formError" class="error-box" role="alert">
          {{ formError }}
        </div>
        <div class="dialog-actions">
          <button
            class="btn btn-secondary"
            type="button"
            @click="editor = false"
            :disabled="saving"
          >
            取消</button
          ><button class="btn btn-primary" :disabled="saving">
            {{ saving ? "保存中…" : "保存账户" }}
          </button>
        </div>
      </form>
    </div>
    <div
      v-if="archiveTarget"
      class="modal-backdrop"
      @click.self="!saving && (archiveTarget = null)"
    >
      <section
        class="dialog card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="archive-title"
      >
        <h2 id="archive-title">归档“{{ archiveTarget.name }}”？</h2>
        <p class="muted">
          历史流水和余额会保留。归档后不能用于新记账，可在“已归档”中重新启用。
        </p>
        <div class="dialog-actions">
          <button
            class="btn btn-secondary"
            @click="archiveTarget = null"
            :disabled="saving"
          >
            取消</button
          ><button class="btn btn-primary" @click="archive" :disabled="saving">
            确认归档
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
<style scoped>
.accounts-metrics {
  grid-template-columns: repeat(3, 1fr);
}
.checkbox-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 17px;
  color: #78859a;
}
.account-card .account-symbol {
  margin-bottom: 16px;
}
.account-card .row-between:first-child {
  align-items: flex-start;
}
.account-card h3 {
  overflow-wrap: anywhere;
}
.account-card > p {
  height: 19px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 760px) {
  .accounts-metrics {
    grid-template-columns: 1fr;
  }
  .accounts-metrics .metric {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 10px;
  }
  .accounts-metrics .metric-top {
    margin: 0;
    display: block;
    align-self: center;
  }
  .accounts-metrics .metric-icon {
    display: none;
  }
  .accounts-metrics .metric-foot {
    grid-column: span 2;
    margin: 0;
  }
}
</style>
