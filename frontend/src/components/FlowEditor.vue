<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ArrowRightLeft,
  Check,
  ChevronDown,
  CircleAlert,
  FileText,
  Loader2,
  LockKeyhole,
  ReceiptText,
  ShieldCheck,
  Star,
  Wallet,
  X,
} from "lucide-vue-next";
import { api } from "../lib/api.js";
import { bus, notify, state } from "../lib/app.js";
import { today } from "../lib/format.js";

const props = defineProps({
  modelValue: Boolean,
  flowId: [Number, String],
  initialType: { type: Number, default: 1 },
});
const emit = defineEmits(["update:modelValue", "saved"]);
const panel = ref(null);
const confirmPanel = ref(null);
const amountInput = ref(null);
const loading = ref(false);
const saving = ref(false);
const typesLoading = ref(false);
const error = ref("");
const typeError = ref("");
const accounts = ref([]);
const actions = ref([]);
const typeTree = ref([]);
const original = ref(null);
const selectedHandle = ref(1);
const showDiscard = ref(false);
const baseline = ref("");
const form = reactive({
  money: "",
  actionId: "",
  accountId: "",
  accountToId: "",
  typeId: "",
  fDate: "",
  note: "",
  collect: false,
  images: [],
});
let loadSequence = 0;
let typeSequence = 0;
let opening = false;
let previousFocus = null;
let previousOverflow = "";
let wasOpen = false;

const isEdit = computed(
  () =>
    props.flowId !== undefined && props.flowId !== null && props.flowId !== "",
);
const isAdmin = computed(() => state.user?.role === "admin");
const status = computed(
  () => original.value?.status || original.value?.reviewStatus || "pending",
);
const readOnly = computed(
  () => isEdit.value && !isAdmin.value && status.value === "approved",
);
const action = computed(() =>
  actions.value.find((item) => String(item.id) === String(form.actionId)),
);
const sourceAccount = computed(() =>
  accounts.value.find((item) => String(item.id) === String(form.accountId)),
);
const destinationAccount = computed(() =>
  accounts.value.find((item) => String(item.id) === String(form.accountToId)),
);
const isTransfer = computed(
  () => Number(action.value?.handle ?? selectedHandle.value) === 2,
);
const visibleActions = computed(() =>
  actions.value.filter((item) => Number(item.handle) === selectedHandle.value),
);
const changed = computed(() => baseline.value && baseline.value !== snapshot());
const kinds = [
  { value: 1, label: "支出", icon: ArrowUpRight },
  { value: 0, label: "收入", icon: ArrowDownLeft },
  { value: 2, label: "转账", icon: ArrowRightLeft },
];
const categoryOptions = computed(() => {
  const output = [];
  const seen = new Set();
  function visit(items, parents = []) {
    for (const item of items || []) {
      if (seen.has(String(item.id))) continue;
      seen.add(String(item.id));
      const label = [...parents, item.tname || item.name || "未命名分类"];
      const children = item.childrenTypes || item.children || [];
      if (children.length) visit(children, label);
      else
        output.push({
          id: item.id,
          label: label.join(" / "),
          disabled: Boolean(item.archive || item.disable),
        });
    }
  }
  visit(typeTree.value);
  if (
    original.value?.type &&
    String(form.typeId) === String(original.value.type.id) &&
    !output.some((item) => String(item.id) === String(form.typeId))
  ) {
    output.push({
      id: original.value.type.id,
      label: `${original.value.type.tname || "原有分类"}（当前记录）`,
      disabled: false,
    });
  }
  return output;
});

function snapshot() {
  return JSON.stringify({ ...form, images: [...form.images] });
}
function accountName(item) {
  return item?.name || item?.aname || "未命名账户";
}
function enabled(item) {
  return !item.disable && !item.disabled;
}
function asArray(value) {
  return Array.isArray(value)
    ? value
    : value?.items || value?.accounts || value?.actions || [];
}

// Keep the upstream liability/exemption semantics. An exemption may apply to
// either side of a transfer; exempting a liability account is not supported.
function accountRestriction(item, side, candidate = action.value) {
  if (
    !item ||
    !candidate ||
    Number(item.accountType) !== 1 ||
    !candidate.exempt
  )
    return "";
  if (Number(candidate.handle) !== 2) return "负债账户不支持免计统计操作";
  const mode = Number(candidate.exemptMode || 0);
  if (
    (side === "from" && [1, 3].includes(mode)) ||
    (side === "to" && [2, 3].includes(mode))
  )
    return "此操作不能豁免负债账户";
  return "";
}
function actionRestriction(candidate) {
  return (
    accountRestriction(sourceAccount.value, "from", candidate) ||
    (Number(candidate.handle) === 2
      ? accountRestriction(destinationAccount.value, "to", candidate)
      : "")
  );
}

async function loadTypes(actionId, preserve = false) {
  const sequence = ++typeSequence;
  typeError.value = "";
  if (!preserve) form.typeId = "";
  typeTree.value = [];
  if (actionId === "" || actionId === null || actionId === undefined) {
    typesLoading.value = false;
    return;
  }
  typesLoading.value = true;
  try {
    const data = await api(
      `/type/getTypeByActionId/${encodeURIComponent(actionId)}`,
    );
    if (sequence !== typeSequence || !props.modelValue) return;
    typeTree.value = asArray(data);
    if (
      !preserve &&
      categoryOptions.value.length === 1 &&
      !categoryOptions.value[0].disabled
    )
      form.typeId = String(categoryOptions.value[0].id);
  } catch (cause) {
    if (sequence === typeSequence)
      typeError.value = cause.message || "分类加载失败，请重试。";
  } finally {
    if (sequence === typeSequence) typesLoading.value = false;
  }
}

async function initialize() {
  const sequence = ++loadSequence;
  opening = true;
  loading.value = true;
  error.value = "";
  original.value = null;
  typeTree.value = [];
  baseline.value = "";
  selectedHandle.value = [0, 1, 2].includes(Number(props.initialType))
    ? Number(props.initialType)
    : 1;
  Object.assign(form, {
    money: "",
    actionId: "",
    accountId: "",
    accountToId: "",
    typeId: "",
    fDate: today(),
    note: "",
    collect: false,
    images: [],
  });
  try {
    const [actionData, accountData, record] = await Promise.all([
      api("/action/getAction"),
      api("/account/getAccount"),
      isEdit.value
        ? api(`/flow/getFlow/${encodeURIComponent(props.flowId)}`)
        : Promise.resolve(null),
    ]);
    if (sequence !== loadSequence || !props.modelValue) return;
    actions.value = asArray(actionData);
    accounts.value = asArray(accountData);
    if (isEdit.value && !record)
      throw new Error("这条流水不存在，或你没有访问权限。");
    if (record) {
      original.value = record;
      for (const item of [record.account, record.accountTo].filter(Boolean)) {
        if (
          !accounts.value.some(
            (existing) => String(existing.id) === String(item.id),
          )
        )
          accounts.value.push({ ...item, name: accountName(item) });
      }
      if (
        record.action &&
        !actions.value.some(
          (item) => String(item.id) === String(record.action.id),
        )
      )
        actions.value.push(record.action);
      Object.assign(form, {
        money: String(record.money ?? ""),
        actionId: String(record.action?.id ?? record.actionId ?? ""),
        accountId: String(record.account?.id ?? record.accountId ?? ""),
        accountToId: String(record.accountTo?.id ?? record.accountToId ?? ""),
        typeId: String(record.type?.id ?? record.typeId ?? ""),
        fDate: String(record.fdate || record.fDate || today()).slice(0, 10),
        note: record.note || "",
        collect: Boolean(record.collect),
        images: Array.isArray(record.images) ? [...record.images] : [],
      });
      selectedHandle.value = Number(
        record.action?.handle ?? record.handle ?? props.initialType,
      );
    } else {
      const first =
        actions.value.find(
          (item) =>
            Number(item.handle) === selectedHandle.value &&
            !item.exempt &&
            enabled(item),
        ) ||
        actions.value.find(
          (item) =>
            Number(item.handle) === selectedHandle.value && enabled(item),
        );
      if (first) form.actionId = String(first.id);
      if (
        accounts.value.length === 1 &&
        !accountRestriction(accounts.value[0], "from")
      )
        form.accountId = String(accounts.value[0].id);
    }
    await loadTypes(form.actionId, Boolean(record));
    if (sequence !== loadSequence || !props.modelValue) return;
    baseline.value = snapshot();
    await nextTick();
    if (!readOnly.value) amountInput.value?.focus();
  } catch (cause) {
    if (sequence === loadSequence)
      error.value = cause.message || "记账信息加载失败，请重试。";
  } finally {
    if (sequence === loadSequence) {
      loading.value = false;
      opening = false;
      await nextTick();
      if (props.modelValue && !readOnly.value) amountInput.value?.focus();
    }
  }
}

function selectKind(kind) {
  if (readOnly.value || saving.value || selectedHandle.value === kind) return;
  selectedHandle.value = kind;
  const first =
    actions.value.find(
      (item) =>
        Number(item.handle) === kind &&
        !item.exempt &&
        enabled(item) &&
        !actionRestriction(item),
    ) ||
    actions.value.find(
      (item) =>
        Number(item.handle) === kind &&
        enabled(item) &&
        !actionRestriction(item),
    );
  form.actionId = first ? String(first.id) : "";
  if (kind !== 2) form.accountToId = "";
}

watch(
  () => form.actionId,
  (value, previous) => {
    if (opening || value === previous || !props.modelValue) return;
    if (action.value) selectedHandle.value = Number(action.value.handle);
    if (!isTransfer.value) form.accountToId = "";
    loadTypes(value);
  },
);

function normalizeMoney(value) {
  const text = String(value).trim();
  if (
    !/^\d+(?:\.\d{1,2})?$/.test(text) ||
    !Number.isFinite(Number(text)) ||
    Number(text) <= 0
  )
    return null;
  const [integer, decimal = ""] = text.split(".");
  return `${integer.replace(/^0+(?=\d)/, "")}.${decimal.padEnd(2, "0")}`;
}

async function save() {
  if (loading.value || saving.value || readOnly.value) return;
  error.value = "";
  const amount = normalizeMoney(form.money);
  if (!amount) {
    error.value = "请填写大于 0 的金额，最多保留两位小数。";
    amountInput.value?.focus();
    return;
  }
  if (!action.value || !sourceAccount.value || !form.typeId || !form.fDate) {
    error.value = "请补全操作、账户、分类和日期。";
    return;
  }
  if (!enabled(action.value)) {
    error.value = "此操作已停用，请选择可用操作。";
    return;
  }
  if (typesLoading.value || typeError.value) {
    error.value = "请等待分类加载完成，或重试后再保存。";
    return;
  }
  if (isTransfer.value && !destinationAccount.value) {
    error.value = "请选择转入账户。";
    return;
  }
  if (isTransfer.value && form.accountId === form.accountToId) {
    error.value = "转出和转入账户不能相同。";
    return;
  }
  const restriction = actionRestriction(action.value);
  if (restriction) {
    error.value = restriction;
    return;
  }
  if (
    !categoryOptions.value.some(
      (item) => String(item.id) === String(form.typeId) && !item.disabled,
    )
  ) {
    error.value = "请选择此操作下的可用分类。";
    return;
  }
  saving.value = true;
  try {
    const body = {
      money: amount,
      fDate: form.fDate,
      actionId: action.value.id,
      accountId: sourceAccount.value.id,
      typeId: categoryOptions.value.find(
        (item) => String(item.id) === String(form.typeId),
      ).id,
      collect: form.collect,
      note: form.note.trim(),
      images: [...form.images],
      ...(isTransfer.value ? { accountToId: destinationAccount.value.id } : {}),
      ...(isEdit.value && original.value?.version !== undefined
        ? { version: original.value.version }
        : {}),
    };
    const result = await api(
      isEdit.value
        ? `/flow/updateFlow/${encodeURIComponent(props.flowId)}`
        : "/flow/addFlow",
      { method: isEdit.value ? "PUT" : "POST", body },
    );
    baseline.value = snapshot();
    notify(
      result?.status === "pending"
        ? isAdmin.value
          ? "流水已保存，等待审核"
          : "已提交，等待管理员审核"
        : "流水已更新",
    );
    bus.dispatchEvent(new Event("ledger-change"));
    emit("saved", result);
    emit("update:modelValue", false);
  } catch (cause) {
    error.value = cause.message || "保存失败，请稍后重试。";
  } finally {
    saving.value = false;
  }
}

function close() {
  if (saving.value) return;
  if (changed.value && !readOnly.value) {
    showDiscard.value = true;
    nextTick(() => confirmPanel.value?.querySelector("button")?.focus());
    return;
  }
  emit("update:modelValue", false);
}
function discard() {
  showDiscard.value = false;
  baseline.value = "";
  emit("update:modelValue", false);
}
function keepEditing() {
  showDiscard.value = false;
  nextTick(() => amountInput.value?.focus());
}
function keydown(event) {
  if (!props.modelValue) return;
  if (event.key === "Escape") {
    event.preventDefault();
    showDiscard.value ? keepEditing() : close();
    return;
  }
  if (event.key !== "Tab") return;
  const root = showDiscard.value ? confirmPanel.value : panel.value;
  const targets = [
    ...(root?.querySelectorAll(
      "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
    ) || []),
  ].filter((item) => item.getClientRects().length);
  if (!targets.length) {
    event.preventDefault();
    root?.focus();
    return;
  }
  const first = targets[0],
    last = targets[targets.length - 1];
  if (
    event.shiftKey &&
    (document.activeElement === first || !root.contains(document.activeElement))
  ) {
    event.preventDefault();
    last.focus();
  } else if (
    !event.shiftKey &&
    (document.activeElement === last || !root.contains(document.activeElement))
  ) {
    event.preventDefault();
    first.focus();
  }
}
function beforeUnload(event) {
  if (props.modelValue && (changed.value || saving.value)) {
    event.preventDefault();
    event.returnValue = "";
  }
}

watch(
  () => props.modelValue,
  async (visible) => {
    if (visible) {
      wasOpen = true;
      previousFocus = document.activeElement;
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      document.addEventListener("keydown", keydown);
      window.addEventListener("beforeunload", beforeUnload);
      await nextTick();
      panel.value?.focus();
      initialize();
    } else {
      if (!wasOpen) return;
      wasOpen = false;
      loadSequence++;
      typeSequence++;
      opening = false;
      showDiscard.value = false;
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", keydown);
      window.removeEventListener("beforeunload", beforeUnload);
      if (previousFocus?.isConnected) previousFocus.focus();
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  loadSequence++;
  typeSequence++;
  if (props.modelValue) document.body.style.overflow = previousOverflow;
  document.removeEventListener("keydown", keydown);
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>

<template>
  <Teleport to="body">
    <Transition name="editor">
      <div v-if="modelValue" class="editor-overlay" @mousedown.self="close">
        <section
          ref="panel"
          class="flow-editor"
          role="dialog"
          aria-modal="true"
          aria-labelledby="flow-editor-title"
          tabindex="-1"
          :inert="showDiscard || undefined"
          :aria-busy="loading || saving"
        >
          <header class="editor-heading">
            <div class="editor-heading-icon"><ReceiptText :size="21" /></div>
            <div>
              <span class="editor-eyebrow">让每笔收支，都有迹可循</span>
              <h2 id="flow-editor-title">
                {{ readOnly ? "流水详情" : isEdit ? "编辑流水" : "记一笔" }}
              </h2>
            </div>
            <button
              class="icon-btn close-editor"
              type="button"
              aria-label="关闭记账窗口"
              :disabled="saving"
              @click="close"
            >
              <X :size="20" />
            </button>
          </header>
          <div v-if="loading" class="editor-loading">
            <Loader2 class="spin" :size="25" /><span>正在读取账户与分类…</span>
          </div>
          <form
            v-else
            id="flow-editor-form"
            class="editor-body"
            @submit.prevent="save"
          >
            <div v-if="readOnly" class="editor-info">
              <LockKeyhole :size="17" /><span
                >这笔流水已通过审核。需要修改时，请联系管理员。</span
              >
            </div>
            <div
              v-else-if="original?.status === 'rejected'"
              class="editor-info rejected"
            >
              <CircleAlert :size="17" /><span
                >审核未通过{{
                  original.reviewComment || original.review_comment
                    ? `：${original.reviewComment || original.review_comment}`
                    : "。请修改后重新提交。"
                }}</span
              >
            </div>
            <div class="kind-tabs" role="group" aria-label="流水方向">
              <button
                v-for="kind in kinds"
                :key="kind.value"
                type="button"
                :class="{ selected: selectedHandle === kind.value }"
                :disabled="readOnly || saving"
                :aria-pressed="selectedHandle === kind.value"
                @click="selectKind(kind.value)"
              >
                <component :is="kind.icon" :size="17" />{{ kind.label }}
              </button>
            </div>
            <label class="amount-field"
              ><span>{{
                isTransfer
                  ? "转账金额"
                  : selectedHandle === 0
                    ? "收入金额"
                    : "支出金额"
              }}</span>
              <div>
                <b>¥</b
                ><input
                  ref="amountInput"
                  v-model="form.money"
                  type="text"
                  inputmode="decimal"
                  placeholder="0.00"
                  aria-label="金额"
                  autocomplete="off"
                  :disabled="readOnly || saving"
                  maxlength="18"
                />
              </div>
              <small>人民币 · CNY</small></label
            >
            <div class="editor-fields">
              <label class="field span-two"
                ><span>收支操作 <i>*</i></span>
                <div class="select-wrap">
                  <select
                    v-model="form.actionId"
                    :disabled="readOnly || saving"
                  >
                    <option value="" disabled>选择操作</option>
                    <option
                      v-for="item in visibleActions"
                      :key="item.id"
                      :value="String(item.id)"
                      :disabled="
                        !enabled(item) || Boolean(actionRestriction(item))
                      "
                    >
                      {{ item.hname }}{{ item.exempt ? " · 不计入统计" : ""
                      }}{{
                        actionRestriction(item) ? " · 不支持已选负债账户" : ""
                      }}{{ !enabled(item) ? " · 已停用" : "" }}
                    </option></select
                  ><ChevronDown :size="16" /></div
              ></label>
              <label class="field" :class="{ 'span-two': !isTransfer }"
                ><span
                  >{{ isTransfer ? "转出账户" : "收支账户" }} <i>*</i></span
                >
                <div class="select-wrap">
                  <select
                    v-model="form.accountId"
                    :disabled="readOnly || saving"
                  >
                    <option value="" disabled>选择账户</option>
                    <option
                      v-for="item in accounts"
                      :key="item.id"
                      :value="String(item.id)"
                      :disabled="Boolean(accountRestriction(item, 'from'))"
                    >
                      {{ accountName(item)
                      }}{{ Number(item.accountType) === 1 ? " · 负债" : ""
                      }}{{
                        accountRestriction(item, "from")
                          ? " · 不支持此操作"
                          : ""
                      }}
                    </option></select
                  ><Wallet :size="16" /></div
              ></label>
              <label v-if="isTransfer" class="field"
                ><span>转入账户 <i>*</i></span>
                <div class="select-wrap">
                  <select
                    v-model="form.accountToId"
                    :disabled="readOnly || saving"
                  >
                    <option value="" disabled>选择账户</option>
                    <option
                      v-for="item in accounts"
                      :key="item.id"
                      :value="String(item.id)"
                      :disabled="
                        String(item.id) === form.accountId ||
                        Boolean(accountRestriction(item, 'to'))
                      "
                    >
                      {{ accountName(item)
                      }}{{ Number(item.accountType) === 1 ? " · 负债" : ""
                      }}{{
                        accountRestriction(item, "to") ? " · 不支持此操作" : ""
                      }}
                    </option></select
                  ><ArrowRightLeft :size="16" /></div
              ></label>
              <label class="field"
                ><span>分类 <i>*</i></span>
                <div class="select-wrap">
                  <select
                    v-model="form.typeId"
                    :disabled="readOnly || saving || typesLoading"
                  >
                    <option value="" disabled>
                      {{ typesLoading ? "正在读取…" : "选择分类" }}
                    </option>
                    <option
                      v-for="item in categoryOptions"
                      :key="item.id"
                      :value="String(item.id)"
                      :disabled="item.disabled"
                    >
                      {{ item.label }}
                    </option></select
                  ><ChevronDown :size="16" /></div
              ></label>
              <label class="field"
                ><span>记账日期 <i>*</i></span
                ><input
                  v-model="form.fDate"
                  type="date"
                  :disabled="readOnly || saving"
                  required
              /></label>
              <div v-if="typeError" class="category-error span-two">
                {{ typeError
                }}<button type="button" @click="loadTypes(form.actionId, true)">
                  重新加载
                </button>
              </div>
              <div
                v-if="!accounts.length || !actions.length"
                class="category-error span-two"
              >
                {{
                  !accounts.length
                    ? "还没有可用账户，请先由管理员添加账户。"
                    : "没有可用收支操作，请先由管理员配置。"
                }}
              </div>
              <label class="field span-two"
                ><span>备注 <small>选填</small></span
                ><textarea
                  v-model="form.note"
                  rows="3"
                  placeholder="记下交易对象、项目用途或报销说明…"
                  maxlength="200"
                  :disabled="readOnly || saving"
                /><small class="note-counter"
                  >{{ form.note.length }} / 200</small
                ></label
              >
            </div>
            <div class="editor-options">
              <label class="collect-switch"
                ><input
                  v-model="form.collect"
                  type="checkbox"
                  :disabled="readOnly || saving"
                /><Star :size="17" :class="{ filled: form.collect }" /><span
                  >收藏这笔流水</span
                ></label
              ><span v-if="action?.exempt" class="exempt-note"
                >不计入收支统计</span
              >
            </div>
            <div v-if="form.images.length" class="attachment-note">
              <FileText :size="16" />已保留
              {{ form.images.length }} 张原有凭证，保存时保持附件不变。
            </div>
            <div v-if="error" class="error-box editor-error" role="alert">
              <CircleAlert :size="17" /><span>{{ error }}</span
              ><button
                v-if="!accounts.length || !actions.length"
                type="button"
                @click="initialize"
              >
                重试
              </button>
            </div>
          </form>
          <footer class="editor-footer">
            <div class="submit-note">
              <ShieldCheck :size="15" /><span>{{
                readOnly
                  ? "已审核的财务记录"
                  : isAdmin
                    ? status === "approved"
                      ? "保存后更新已审核流水"
                      : "保存记录后再完成审核"
                    : "提交后由管理员审核"
              }}</span>
            </div>
            <button
              class="btn btn-secondary"
              type="button"
              :disabled="saving"
              @click="close"
            >
              {{ readOnly ? "关闭" : "取消" }}</button
            ><button
              v-if="!readOnly"
              class="btn btn-primary"
              type="submit"
              form="flow-editor-form"
              :disabled="saving || loading || typesLoading"
            >
              <Loader2 v-if="saving" :size="16" class="spin" /><Check
                v-else
                :size="16"
              />{{ saving ? "正在保存…" : isAdmin ? "确认保存" : "提交审核" }}
            </button>
          </footer>
        </section>
      </div>
    </Transition>
    <div
      v-if="modelValue && showDiscard"
      class="discard-overlay"
      @mousedown.self="keepEditing"
    >
      <section
        ref="confirmPanel"
        class="discard-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="discard-title"
        tabindex="-1"
      >
        <div class="discard-icon"><CircleAlert :size="23" /></div>
        <h3 id="discard-title">还有未保存的修改</h3>
        <p>离开后，本次填写的内容不会保留。</p>
        <div>
          <button class="btn btn-secondary" type="button" @click="keepEditing">
            继续填写</button
          ><button class="btn discard-button" type="button" @click="discard">
            放弃修改
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: #16243d66;
  backdrop-filter: blur(5px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.flow-editor {
  width: 570px;
  max-height: calc(100dvh - 48px);
  display: flex;
  flex-direction: column;
  background: #fffefa;
  border: 1px solid #ffffff80;
  border-radius: 22px;
  box-shadow: 0 28px 100px #14243b30;
  outline: none;
  overflow: hidden;
  color: #24324a;
}
.editor-heading {
  display: flex;
  gap: 13px;
  align-items: center;
  padding: 23px 27px 20px;
  border-bottom: 1px solid #eceeea;
}
.editor-heading-icon {
  width: 42px;
  height: 45px;
  border: 1px solid #e4e9f0;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #4773c4;
  background: #f2f5fa;
}
.editor-eyebrow {
  font-size: 10px;
  letter-spacing: 1px;
  color: #8c95a4;
}
.editor-heading h2 {
  font-size: 21px;
  letter-spacing: 0.4px;
  margin: 2px 0 0;
  font-weight: 650;
}
.close-editor {
  margin-left: auto;
}
.editor-body {
  overflow: auto;
  padding: 23px 28px 25px;
}
.editor-loading {
  min-height: 360px;
  display: flex;
  flex-direction: column;
  gap: 15px;
  align-items: center;
  justify-content: center;
  color: #8190a4;
  font-size: 13px;
}
.kind-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 5px;
  padding: 5px;
  background: #f0f2f1;
  border-radius: 11px;
}
.kind-tabs button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  background: transparent;
  color: #84909f;
  border-radius: 8px;
  padding: 10px 0;
  font-size: 12px;
  cursor: pointer;
  font-weight: 550;
}
.kind-tabs button.selected {
  color: #3466b9;
  background: #fff;
  box-shadow: 0 2px 5px #21344909;
}
.kind-tabs button:disabled {
  cursor: default;
}
.amount-field {
  display: block;
  margin: 25px 0 27px;
}
.amount-field > span {
  font-size: 11px;
  color: #7d8798;
}
.amount-field > div {
  display: flex;
  align-items: baseline;
  gap: 11px;
  padding: 6px 0 5px;
}
.amount-field b {
  font-size: 25px;
  font-weight: 500;
  color: #65758c;
}
.amount-field input {
  width: 100%;
  min-width: 0;
  border: 0;
  background: none;
  padding: 0;
  font: inherit;
  font-size: 42px;
  font-weight: 550;
  line-height: 1.5;
  letter-spacing: -1.3px;
  font-variant-numeric: tabular-nums;
  color: #23364e;
  outline: 0;
}
.amount-field input::placeholder {
  color: #c6cdd5;
}
.amount-field small {
  font-size: 10px;
  color: #a3adba;
  letter-spacing: 0.5px;
}
.editor-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 15px;
}
.span-two {
  grid-column: 1/-1;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.field > span {
  font-size: 11px;
  color: #657488;
}
.field i {
  color: #b2b9c3;
  font-style: normal;
}
.field small {
  font-size: 10px;
  color: #a7b0bb;
  margin-left: 5px;
}
.field input,
.field select,
.field textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid #e2e7ea;
  border-radius: 9px;
  padding: 11px 12px;
  background: #fff;
  color: #35445a;
  font: inherit;
  font-size: 12px;
  outline-offset: 2px;
}
.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: #6991cb;
  outline: 2px solid #e9f0fb;
}
.field textarea {
  resize: vertical;
  min-height: 79px;
}
.field :disabled {
  background: #f5f6f4;
  color: #798699;
  cursor: default;
}
.field .note-counter {
  align-self: flex-end;
  font-size: 9px;
  margin-top: -3px;
}
.select-wrap {
  position: relative;
}
.select-wrap select {
  appearance: none;
  padding-right: 37px;
}
.select-wrap svg {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: #99a4b0;
  pointer-events: none;
}
.editor-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 15px;
}
.collect-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #718197;
  cursor: pointer;
}
.collect-switch input {
  accent-color: #416db9;
  width: 14px;
  height: 14px;
  margin: 0 2px 0 0;
}
.collect-switch svg {
  color: #a2adba;
}
.collect-switch svg.filled {
  fill: #f6e8bc;
  color: #c5a757;
}
.exempt-note {
  font-size: 10px;
  color: #9b8968;
  background: #f7f0e4;
  padding: 3px 7px;
  border-radius: 5px;
}
.attachment-note {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 10px;
  color: #919ba8;
  margin-top: 17px;
}
.editor-error {
  display: flex;
  gap: 9px;
  margin-top: 20px;
  font-size: 12px;
  align-items: flex-start;
}
.editor-error svg {
  flex-shrink: 0;
}
.editor-error button,
.category-error button {
  background: none;
  color: #4977bd;
  border: 0;
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
  white-space: nowrap;
}
.category-error {
  font-size: 11px;
  color: #bd725c;
  line-height: 1.8;
}
.editor-info {
  display: flex;
  gap: 9px;
  font-size: 11px;
  line-height: 1.8;
  color: #687fa1;
  background: #f0f5fa;
  border: 1px solid #e2eaf3;
  border-radius: 9px;
  padding: 11px 12px;
  margin-bottom: 20px;
}
.editor-info svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.editor-info.rejected {
  color: #ae7662;
  background: #fcf2e9;
  border-color: #f0dfcf;
}
.editor-footer {
  display: flex;
  align-items: center;
  gap: 9px;
  border-top: 1px solid #e8ecea;
  padding: 18px 26px;
  background: #fcfcf8;
}
.editor-footer .btn {
  font-size: 11px;
  min-height: 39px;
  white-space: nowrap;
}
.submit-note {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 10px;
  color: #939eac;
  margin-right: auto;
}
.spin {
  animation: spin 1s linear infinite;
}
.discard-overlay {
  position: fixed;
  inset: 0;
  z-index: 1110;
  background: #16243d66;
  display: grid;
  place-items: center;
  padding: 24px;
}
.discard-dialog {
  width: 370px;
  max-width: 100%;
  padding: 27px;
  background: #fffefa;
  border-radius: 18px;
  box-shadow: 0 22px 70px #12223826;
  color: #24324a;
}
.discard-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  color: #bb8b57;
  background: #fbf0e4;
  border-radius: 12px;
  margin-bottom: 16px;
}
.discard-dialog h3 {
  margin: 0;
  font-size: 18px;
}
.discard-dialog p {
  font-size: 12px;
  color: #8a94a3;
  margin: 10px 0 24px;
}
.discard-dialog > div:last-child {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.discard-button {
  background: #b86650;
  color: #fff;
}
.editor-enter-active,
.editor-leave-active {
  transition: opacity 0.18s;
}
.editor-enter-active .flow-editor,
.editor-leave-active .flow-editor {
  transition: transform 0.18s;
}
.editor-enter-from,
.editor-leave-to {
  opacity: 0;
}
.editor-enter-from .flow-editor,
.editor-leave-to .flow-editor {
  transform: translateY(16px);
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 640px) {
  .editor-overlay {
    padding: 0;
    align-items: flex-end;
  }
  .flow-editor {
    width: 100%;
    max-height: 96dvh;
    border-radius: 22px 22px 0 0;
    border: 0;
  }
  .editor-heading {
    padding: 19px 21px 17px;
  }
  .editor-heading h2 {
    font-size: 20px;
  }
  .editor-body {
    padding: 20px 22px 25px;
  }
  .amount-field {
    margin: 23px 0;
  }
  .amount-field input {
    font-size: 38px;
  }
  .editor-fields {
    gap: 17px 12px;
  }
  .field input,
  .field select,
  .field textarea {
    font-size: 13px;
    padding: 12px 10px;
  }
  .field input[type="date"] {
    font-size: 12px;
  }
  .editor-footer {
    padding: 15px 20px max(15px, env(safe-area-inset-bottom));
    gap: 8px;
  }
  .submit-note {
    font-size: 9px;
    max-width: 112px;
    line-height: 1.5;
    gap: 5px;
  }
  .submit-note svg {
    flex-shrink: 0;
  }
  .editor-footer .btn {
    padding: 0 13px;
    font-size: 11px;
  }
  .editor-heading-icon {
    width: 38px;
    height: 41px;
  }
  .editor-eyebrow {
    font-size: 9px;
  }
  .editor-error {
    font-size: 11px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .editor-enter-active,
  .editor-leave-active,
  .editor-enter-active .flow-editor,
  .editor-leave-active .flow-editor {
    transition: none;
  }
  .spin {
    animation: none;
  }
}
</style>
