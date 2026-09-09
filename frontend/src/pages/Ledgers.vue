<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
} from "vue";
import { useRouter } from "vue-router";
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleAlert,
  FolderHeart,
  Loader2,
  Pencil,
  Plus,
  Search,
  ShieldCheck,
  Users,
  X,
} from "lucide-vue-next";
import { api } from "../lib/api.js";
import { notify, refreshLedgers, selectLedger, state } from "../lib/app.js";

const router = useRouter();
const loading = ref(true);
const error = ref("");
const query = ref("");
const switching = ref(null);
const editor = ref(false);
const selected = ref(null);
const saving = ref(false);
const formError = ref("");
const dialog = ref(null);
const form = reactive({ name: "", description: "", color: "#8B7BD8" });
const colors = [
  { value: "#8B7BD8", label: "丁香紫" },
  { value: "#77A98B", label: "鼠尾草绿" },
  { value: "#E1AA73", label: "杏子橙" },
  { value: "#7FAAD0", label: "天空蓝" },
  { value: "#D38DA8", label: "玫瑰粉" },
  { value: "#B8A584", label: "燕麦米" },
];
let previousFocus = null;
let previousOverflow = "";
let sequence = 0;
const canCreate = computed(() =>
  Boolean(
    state.user?.canCreateLedgers ||
      state.canCreateLedgers ||
      state.user?.globalRole === "admin",
  ),
);
const ledgers = computed(() =>
  Array.isArray(state.ledgers) ? state.ledgers : [],
);
const visible = computed(() => {
  const text = query.value.trim().toLocaleLowerCase();
  return ledgers.value.filter(
    (item) =>
      !text ||
      `${item.name} ${item.description || ""}`
        .toLocaleLowerCase()
        .includes(text),
  );
});
const isCurrent = (item) => String(item.id) === String(state.activeLedger?.id);
const colorOf = (value) =>
  /^#[0-9a-f]{6}$/i.test(value || "") ? value : colors[0].value;

async function load() {
  const current = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    await refreshLedgers();
  } catch (cause) {
    if (current === sequence)
      error.value = cause.message || "账本暂时未能加载，请稍后重试。";
  } finally {
    if (current === sequence) loading.value = false;
  }
}
async function enter(ledger) {
  if (switching.value !== null) return;
  switching.value = ledger.id;
  try {
    await selectLedger(ledger.id);
    await router.push("/overview");
  } catch (cause) {
    notify(cause.message || "切换账本失败，请重试。", "error");
  } finally {
    switching.value = null;
  }
}
function openEditor(ledger = null) {
  if ((!ledger && !canCreate.value) || (ledger && ledger.role !== "admin"))
    return;
  selected.value = ledger;
  Object.assign(form, {
    name: ledger?.name || "",
    description: ledger?.description || "",
    color: colorOf(ledger?.color),
  });
  formError.value = "";
  previousFocus = document.activeElement;
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  editor.value = true;
  nextTick(() => dialog.value?.querySelector("input")?.focus());
}
function closeEditor() {
  if (saving.value) return;
  editor.value = false;
  document.body.style.overflow = previousOverflow;
  if (previousFocus?.isConnected) previousFocus.focus();
}
async function save() {
  if (saving.value) return;
  formError.value = "";
  if (!form.name.trim()) {
    formError.value = "给账本取一个名字吧。";
    return;
  }
  saving.value = true;
  try {
    await api(
      selected.value
        ? `/ledgers/${encodeURIComponent(selected.value.id)}`
        : "/ledgers",
      {
        method: selected.value ? "PUT" : "POST",
        body: {
          name: form.name.trim(),
          description: form.description.trim(),
          color: form.color,
        },
      },
    );
    notify(selected.value ? "账本信息已更新" : "新账本已创建，可以开始记录了");
    saving.value = false;
    closeEditor();
    try {
      await refreshLedgers();
    } catch (cause) {
      notify(
        `账本已保存，但列表暂未刷新。${cause.message || "请重新加载列表。"}`,
        "error",
      );
    }
  } catch (cause) {
    formError.value = cause.message || "账本保存失败，请稍后重试。";
  } finally {
    saving.value = false;
  }
}
function keydown(event) {
  if (!editor.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeEditor();
    return;
  }
  if (event.key !== "Tab") return;
  const items = [
    ...(dialog.value?.querySelectorAll(
      "input:not(:disabled),textarea:not(:disabled),button:not(:disabled)",
    ) || []),
  ].filter((node) => node.getClientRects().length);
  if (!items.length) {
    event.preventDefault();
    return;
  }
  const first = items[0],
    last = items[items.length - 1];
  if (
    event.shiftKey &&
    (document.activeElement === first ||
      !dialog.value.contains(document.activeElement))
  ) {
    event.preventDefault();
    last.focus();
  } else if (
    !event.shiftKey &&
    (document.activeElement === last ||
      !dialog.value.contains(document.activeElement))
  ) {
    event.preventDefault();
    first.focus();
  }
}
onMounted(() => {
  load();
  document.addEventListener("keydown", keydown);
});
onBeforeUnmount(() => {
  sequence++;
  document.removeEventListener("keydown", keydown);
  if (editor.value) document.body.style.overflow = previousOverflow;
});
</script>

<template>
  <div class="ledgers-page">
    <header class="page-header ledger-heading">
      <div>
        <h1>我的账本</h1>
        <p>把不同项目的收支分开，把需要一起记账的人聚在一起。</p>
      </div>
      <button
        v-if="canCreate"
        class="btn btn-primary"
        type="button"
        @click="openEditor()"
      >
        <Plus :size="17" />创建账本
      </button>
    </header>
    <section class="ledger-intro">
      <div class="intro-illustration"><BookOpen :size="31" /><span></span></div>
      <div>
        <strong>每一个项目，都有自己的账本</strong>
        <p>
          账户、流水、凭证和成员都按账本独立管理。切换账本，继续你手上的工作。
        </p>
      </div>
      <span class="intro-count"
        ><b>{{ loading ? "—" : ledgers.length }}</b> 个账本</span
      >
    </section>
    <div class="ledger-toolbar">
      <span>{{ query ? `找到 ${visible.length} 个账本` : "你加入的账本" }}</span
      ><label class="ledger-search"
        ><Search :size="15" /><input
          v-model="query"
          type="search"
          placeholder="搜索账本"
          aria-label="搜索账本"
      /></label>
    </div>
    <div v-if="loading" class="ledger-grid" aria-live="polite">
      <div v-for="index in 3" :key="index" class="ledger-skeleton">
        <span></span><i></i><i></i>
      </div>
      <span class="sr-only">正在读取账本</span>
    </div>
    <div v-else-if="error" class="ledger-empty card">
      <CircleAlert :size="31" />
      <h2>暂时无法读取账本</h2>
      <p>{{ error }}</p>
      <button class="btn btn-secondary" type="button" @click="load">
        重新加载
      </button>
    </div>
    <div v-else-if="!visible.length" class="ledger-empty card">
      <FolderHeart :size="34" />
      <h2>{{ query ? "没有找到这个账本" : "还没有加入账本" }}</h2>
      <p>
        {{
          query
            ? "换个名字，或清空搜索再试试。"
            : canCreate
              ? "创建第一个账本，开始整理收支与团队协作。"
              : "请账本管理员发给你邀请链接，接受邀请后就能在这里找到它。"
        }}
      </p>
      <button
        v-if="query"
        class="btn btn-secondary"
        type="button"
        @click="query = ''"
      >
        清空搜索</button
      ><button
        v-else-if="canCreate"
        class="btn btn-primary"
        type="button"
        @click="openEditor()"
      >
        <Plus :size="16" />创建第一个账本
      </button>
    </div>
    <section v-else class="ledger-grid" aria-label="账本列表">
      <article
        v-for="ledger in visible"
        :key="ledger.id"
        class="ledger-card"
        :class="{ current: isCurrent(ledger) }"
        :style="{
          '--ledger-accent': colorOf(ledger.color),
          '--ledger-tint': `${colorOf(ledger.color)}12`,
        }"
      >
        <header>
          <div class="ledger-book"><BookOpen :size="25" /></div>
          <div class="ledger-card-actions">
            <span v-if="isCurrent(ledger)" class="current-label"
              ><Check :size="11" />当前账本</span
            ><button
              v-if="ledger.role === 'admin'"
              class="icon-btn ledger-edit"
              type="button"
              aria-label="编辑账本信息"
              title="编辑账本信息"
              @click="openEditor(ledger)"
            >
              <Pencil :size="15" />
            </button>
          </div>
        </header>
        <h2>{{ ledger.name }}</h2>
        <p>
          {{ ledger.description || "属于这个项目的每一笔，都记录在这里。" }}
        </p>
        <div class="ledger-meta">
          <span><Users :size="13" />{{ ledger.memberCount ?? "—" }} 位成员</span
          ><span
            ><ShieldCheck v-if="ledger.role === 'admin'" :size="13" />{{
              ledger.role === "admin" ? "账本管理员" : "账本成员"
            }}</span
          >
        </div>
        <footer>
          <button
            type="button"
            class="enter-ledger"
            :disabled="switching !== null"
            @click="enter(ledger)"
          >
            <span>{{
              switching === ledger.id
                ? "正在打开…"
                : isCurrent(ledger)
                  ? "继续记账"
                  : "打开账本"
            }}</span
            ><Loader2
              v-if="switching === ledger.id"
              class="spin"
              :size="16"
            /><ArrowRight v-else :size="17" />
          </button>
        </footer>
      </article>
      <button
        v-if="canCreate && !query"
        class="new-ledger-card"
        type="button"
        @click="openEditor()"
      >
        <span><Plus :size="25" /></span><strong>为新项目建个账本</strong>
        <p>让每一份收支各有归属</p>
      </button>
    </section>
    <p class="ledger-footnote">
      <ShieldCheck
        :size="12"
      />你只能访问自己加入的账本，角色权限由各账本管理员设置。
    </p>
    <Teleport to="body"
      ><div
        v-if="editor"
        class="modal-backdrop ledger-modal"
        @mousedown.self="closeEditor"
      >
        <form
          ref="dialog"
          class="dialog card ledger-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ledger-editor-title"
          :aria-busy="saving"
          @submit.prevent="save"
        >
          <div class="dialog-header">
            <div>
              <span
                class="dialog-book"
                :style="{ color: form.color, background: `${form.color}12` }"
                ><BookOpen :size="23"
              /></span>
              <h2 id="ledger-editor-title">
                {{ selected ? "编辑账本" : "创建新账本" }}
              </h2>
              <p>
                {{
                  selected
                    ? "更新名称与颜色，让账本更容易找到。"
                    : "取一个好认的名字，再邀请伙伴一起记账。"
                }}
              </p>
            </div>
            <button
              class="icon-btn"
              type="button"
              aria-label="关闭账本编辑"
              :disabled="saving"
              @click="closeEditor"
            >
              <X :size="18" />
            </button>
          </div>
          <label class="field"
            ><span>账本名称</span
            ><input
              v-model="form.name"
              required
              maxlength="80"
              placeholder="例如：春日设计工作室"
              :disabled="saving" /></label
          ><label class="field"
            ><span>简单介绍 <small>选填</small></span
            ><textarea
              v-model="form.description"
              rows="3"
              maxlength="500"
              placeholder="这个账本用来记录什么？"
              :disabled="saving"
            />
          </label>
          <fieldset class="ledger-colors">
            <legend>选个颜色</legend>
            <label
              v-for="color in colors"
              :key="color.value"
              :title="color.label"
              ><input
                v-model="form.color"
                type="radio"
                name="ledger-color"
                :value="color.value"
                :disabled="saving"
                :aria-label="color.label" /><span
                :style="{ background: color.value }"
                ><Check v-if="form.color === color.value" :size="17" /></span
            ></label>
          </fieldset>
          <div v-if="formError" class="error-box" role="alert">
            {{ formError }}
          </div>
          <div class="dialog-actions">
            <button
              class="btn btn-secondary"
              type="button"
              :disabled="saving"
              @click="closeEditor"
            >
              取消</button
            ><button class="btn btn-primary" type="submit" :disabled="saving">
              <Loader2 v-if="saving" class="spin" :size="15" />{{
                saving ? "正在保存…" : selected ? "保存修改" : "创建账本"
              }}
            </button>
          </div>
        </form>
      </div></Teleport
    >
  </div>
</template>

<style scoped>
.ledgers-page {
  max-width: 1160px;
  margin: auto;
}
.ledger-heading {
  margin-bottom: 25px;
}
.ledger-heading h1 {
  font-size: 29px;
  letter-spacing: -0.4px;
}
.ledger-heading p {
  font-size: 13px;
  line-height: 1.8;
  max-width: 540px;
}
.ledger-intro {
  display: flex;
  align-items: center;
  gap: 19px;
  padding: 25px 28px;
  border: 1px solid #e9e4f3;
  background: #f5f1fb;
  border-radius: 17px;
  margin-bottom: 32px;
}
.intro-illustration {
  position: relative;
  flex: 0 0 auto;
  width: 60px;
  height: 60px;
  border-radius: 18px;
  background: #eae3f8;
  display: grid;
  place-items: center;
  color: #9680c4;
  transform: rotate(-6deg);
}
.intro-illustration > svg {
  transform: rotate(6deg);
}
.intro-illustration > span {
  position: absolute;
  right: -4px;
  bottom: -2px;
  width: 17px;
  height: 17px;
  border-radius: 6px;
  background: #f3dda8;
  border: 3px solid #f5f1fb;
}
.ledger-intro strong {
  font-size: 15px;
  font-weight: 550;
  color: #67597b;
}
.ledger-intro p {
  font-size: 12px;
  color: #a093b0;
  line-height: 1.8;
  margin: 7px 0 0;
  max-width: 610px;
}
.intro-count {
  margin-left: auto;
  white-space: nowrap;
  font-size: 11px;
  color: #a79cb5;
  display: flex;
  align-items: baseline;
  gap: 7px;
}
.intro-count b {
  font-size: 28px;
  font-weight: 500;
  color: #8c7ca5;
}
.ledger-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 17px;
}
.ledger-toolbar > span {
  font-size: 13px;
  color: #8d8598;
}
.ledger-search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border: 1px solid #e9e5ed;
  border-radius: 9px;
  padding: 9px 11px;
  color: #b2aabb;
  width: 200px;
}
.ledger-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  background: none;
  outline: 0;
  font: inherit;
  font-size: 11px;
  color: #7a7088;
}
.ledger-search input::placeholder {
  color: #b6aebf;
}
.ledger-search:focus-within {
  outline: 2px solid #e9e1f6;
}
.ledger-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}
.ledger-card {
  background: #fff;
  border: 1px solid #e9e6ed;
  border-radius: 16px;
  padding: 23px 23px 0;
  display: flex;
  flex-direction: column;
  min-height: 269px;
  transition:
    border-color 0.15s,
    transform 0.15s;
  min-width: 0;
}
.ledger-card.current {
  border-color: #d6cbe9;
  box-shadow: 0 0 0 2px #eee7f636;
}
.ledger-card:hover {
  border-color: var(--ledger-accent);
  transform: translateY(-2px);
}
.ledger-card > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
}
.ledger-book {
  width: 47px;
  height: 49px;
  display: grid;
  place-items: center;
  border-radius: 13px;
  color: var(--ledger-accent);
  background: var(--ledger-tint);
}
.ledger-card-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}
.current-label {
  display: flex;
  gap: 4px;
  align-items: center;
  font-size: 9px;
  color: #9a89b4;
  background: #f6f2fb;
  border: 1px solid #ede5f6;
  border-radius: 6px;
  padding: 4px 6px;
  white-space: nowrap;
}
.ledger-edit {
  width: 28px;
  height: 28px;
  color: #b6acbf;
  box-shadow: none;
}
.ledger-card h2 {
  font-size: 17px;
  font-weight: 550;
  letter-spacing: -0.3px;
  color: #61546e;
  line-height: 1.5;
  margin: 0 0 9px;
  overflow-wrap: anywhere;
}
.ledger-card > p {
  font-size: 11px;
  color: #aaa0b5;
  line-height: 1.8;
  margin: 0 0 18px;
  min-height: 38px;
  overflow-wrap: anywhere;
}
.ledger-meta {
  display: flex;
  align-items: center;
  gap: 15px;
  font-size: 10px;
  color: #b4a9bf;
  margin-bottom: 19px;
}
.ledger-meta > span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.ledger-card > footer {
  margin-top: auto;
  border-top: 1px solid #f0edf3;
}
.enter-ledger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 0;
  background: none;
  padding: 15px 0;
  font: inherit;
  font-size: 11px;
  color: var(--ledger-accent);
  cursor: pointer;
}
.enter-ledger:disabled {
  opacity: 0.55;
}
.new-ledger-card {
  border: 1px dashed #dcd4e5;
  background: #faf8fc;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 35px 20px;
  min-height: 269px;
  cursor: pointer;
  transition: background 0.15s;
}
.new-ledger-card:hover {
  background: #f4eefb;
}
.new-ledger-card > span {
  width: 45px;
  height: 47px;
  background: #f0eaf8;
  border-radius: 13px;
  display: grid;
  place-items: center;
  color: #b19dce;
  margin-bottom: 17px;
}
.new-ledger-card strong {
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  color: #a191b5;
}
.new-ledger-card p {
  font-size: 11px;
  color: #bbadc9;
  margin: 8px 0 0;
}
.ledger-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 45px 25px;
  min-height: 300px;
  text-align: center;
}
.ledger-empty > svg {
  color: #b8a7cc;
  margin-bottom: 20px;
}
.ledger-empty h2 {
  font-size: 17px;
  font-weight: 500;
  color: #82708f;
  margin: 0 0 11px;
}
.ledger-empty p {
  font-size: 12px;
  color: #afa0bb;
  max-width: 440px;
  line-height: 1.8;
  margin: 0 0 22px;
}
.ledger-footnote {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  color: #b7adbf;
  font-size: 10px;
  margin-top: 30px;
  line-height: 1.8;
  text-align: center;
}
.ledger-skeleton {
  border: 1px solid #ece7f1;
  background: #fff;
  border-radius: 16px;
  padding: 25px;
  min-height: 269px;
  animation: pulse 1.5s infinite;
}
.ledger-skeleton > span {
  display: block;
  width: 48px;
  height: 49px;
  border-radius: 13px;
  background: #f2edf7;
  margin-bottom: 26px;
}
.ledger-skeleton > i {
  display: block;
  height: 13px;
  width: 66%;
  border-radius: 4px;
  background: #f5f1f8;
  margin-bottom: 15px;
}
.ledger-skeleton > i:last-child {
  width: 92%;
  height: 9px;
}
.ledger-modal {
  z-index: 1200;
}
.ledger-dialog {
  border-radius: 19px;
  border: 1px solid #e9e2ef;
  background: #fff;
}
.ledger-dialog .dialog-header {
  margin-bottom: 25px;
}
.dialog-book {
  display: grid;
  place-items: center;
  width: 44px;
  height: 45px;
  border-radius: 12px;
  margin-bottom: 17px;
}
.ledger-dialog h2 {
  font-size: 20px;
  color: #61516f;
  letter-spacing: -0.3px;
}
.ledger-dialog .dialog-header p {
  font-size: 12px;
  color: #aaa0b4;
  margin: 9px 0 0;
  line-height: 1.8;
}
.ledger-dialog .field {
  margin-bottom: 20px;
}
.ledger-dialog .field > span {
  font-size: 12px;
  color: #96879f;
}
.ledger-dialog .field input,
.ledger-dialog .field textarea {
  font-size: 13px;
  border-radius: 9px;
  border-color: #e7dfef;
  background: #fefdfd;
}
.ledger-dialog .field textarea {
  resize: vertical;
  min-height: 82px;
}
.ledger-dialog .field small {
  font-size: 10px;
  color: #bcb0c5;
  margin-left: 5px;
}
.ledger-colors {
  border: 0;
  padding: 0;
  margin: 3px 0 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.ledger-colors legend {
  font-size: 12px;
  color: #96879f;
  margin-bottom: 13px;
}
.ledger-colors label {
  position: relative;
  cursor: pointer;
}
.ledger-colors input {
  position: absolute;
  opacity: 0;
  inset: 0;
  width: 30px;
  height: 30px;
  cursor: pointer;
}
.ledger-colors label > span {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  border: 3px solid #fff;
  box-shadow: 0 0 0 1px transparent;
}
.ledger-colors input:checked + span {
  box-shadow: 0 0 0 1px #baaad2;
}
.ledger-colors input:focus-visible + span {
  outline: 2px solid #b3a0cf;
  outline-offset: 3px;
}
.ledger-dialog .error-box {
  font-size: 12px;
}
.spin {
  animation: spin 0.9s linear infinite;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
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
@media (max-width: 1050px) {
  .ledger-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .ledger-intro p {
    max-width: 460px;
  }
  .intro-count {
    font-size: 10px;
    gap: 5px;
  }
  .intro-count b {
    font-size: 24px;
  }
}
@media (max-width: 640px) {
  .ledger-heading {
    align-items: flex-start;
    gap: 14px;
    margin-bottom: 21px;
  }
  .ledger-heading h1 {
    font-size: 26px;
  }
  .ledger-heading p {
    font-size: 11px;
    max-width: 240px;
  }
  .ledger-heading > .btn {
    font-size: 11px;
    padding: 9px 12px;
    margin-top: 8px;
  }
  .ledger-intro {
    padding: 20px 18px;
    gap: 13px;
    margin-bottom: 25px;
    border-radius: 14px;
  }
  .intro-illustration {
    width: 44px;
    height: 46px;
    border-radius: 13px;
  }
  .intro-illustration > svg {
    width: 25px;
  }
  .ledger-intro strong {
    font-size: 12px;
  }
  .ledger-intro p {
    font-size: 10px;
    line-height: 1.8;
  }
  .intro-count {
    display: none;
  }
  .ledger-toolbar {
    margin-bottom: 15px;
  }
  .ledger-toolbar > span {
    font-size: 11px;
  }
  .ledger-search {
    width: 165px;
    padding: 8px 10px;
  }
  .ledger-search input {
    font-size: 10px;
  }
  .ledger-grid {
    gap: 15px;
  }
  .ledger-card {
    padding: 18px 18px 0;
    border-radius: 14px;
    min-height: 256px;
  }
  .ledger-card > header {
    margin-bottom: 17px;
  }
  .ledger-book {
    width: 39px;
    height: 41px;
    border-radius: 11px;
  }
  .ledger-book svg {
    width: 22px;
  }
  .current-label {
    font-size: 8px;
    padding: 3px 5px;
    gap: 2px;
  }
  .current-label svg {
    width: 9px;
  }
  .ledger-card-actions {
    gap: 1px;
  }
  .ledger-edit {
    width: 23px;
    height: 23px;
  }
  .ledger-card h2 {
    font-size: 15px;
  }
  .ledger-card > p {
    font-size: 10px;
    margin-bottom: 15px;
    min-height: 36px;
  }
  .ledger-meta {
    gap: 8px;
    font-size: 8px;
    flex-wrap: wrap;
    margin-bottom: 17px;
  }
  .ledger-meta svg {
    width: 11px;
  }
  .enter-ledger {
    font-size: 10px;
    padding: 13px 0;
  }
  .new-ledger-card {
    min-height: 256px;
    padding: 25px 15px;
    border-radius: 14px;
  }
  .new-ledger-card strong {
    font-size: 11px;
  }
  .new-ledger-card p {
    font-size: 9px;
  }
  .new-ledger-card > span {
    width: 40px;
    height: 42px;
  }
  .ledger-footnote {
    font-size: 9px;
    align-items: flex-start;
    padding: 0 8px;
    margin-top: 25px;
  }
  .ledger-footnote svg {
    flex-shrink: 0;
    margin-top: 2px;
  }
  .ledger-dialog {
    padding: 24px;
  }
  .ledger-dialog .field {
    margin-bottom: 19px;
  }
  .ledger-colors {
    gap: 10px;
  }
  .ledger-dialog h2 {
    font-size: 19px;
  }
  .ledger-dialog .dialog-header p {
    font-size: 11px;
  }
  .ledger-skeleton {
    min-height: 256px;
    padding: 20px;
  }
}
@media (max-width: 430px) {
  .ledger-grid {
    grid-template-columns: 1fr;
  }
  .ledger-card {
    min-height: 242px;
    padding: 22px 23px 0;
  }
  .ledger-card h2 {
    font-size: 17px;
  }
  .ledger-card > p {
    font-size: 11px;
    min-height: 0;
  }
  .ledger-card > header {
    margin-bottom: 18px;
  }
  .ledger-book {
    width: 44px;
    height: 46px;
  }
  .ledger-meta {
    font-size: 10px;
    gap: 17px;
  }
  .ledger-meta svg {
    width: 12px;
  }
  .current-label {
    font-size: 9px;
    padding: 4px 7px;
    gap: 4px;
  }
  .ledger-edit {
    width: 27px;
    height: 27px;
  }
  .enter-ledger {
    font-size: 11px;
    padding: 14px 0;
  }
  .new-ledger-card {
    min-height: 175px;
  }
  .new-ledger-card > span {
    width: 38px;
    height: 39px;
    margin-bottom: 12px;
  }
  .new-ledger-card strong {
    font-size: 12px;
  }
  .new-ledger-card p {
    font-size: 10px;
  }
  .ledger-heading > .btn {
    font-size: 10px;
    padding: 8px 10px;
  }
  .ledger-heading > .btn svg {
    width: 14px;
  }
  .ledger-search {
    width: 150px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .ledger-card {
    transition: none;
  }
  .ledger-card:hover {
    transform: none;
  }
  .spin,
  .ledger-skeleton {
    animation: none;
  }
}

/* Pastel color belongs to surfaces; reading and actions retain contrast. */
.ledgers-page .ledger-intro strong,
.ledgers-page .ledger-card h2,
.ledgers-page .ledger-empty h2 {
  color: #50405f;
}
.ledgers-page .ledger-heading p,
.ledgers-page .ledger-intro p,
.ledgers-page .ledger-card > p,
.ledgers-page .ledger-meta,
.ledgers-page .ledger-toolbar > span,
.ledgers-page .ledger-empty p,
.ledgers-page .new-ledger-card p,
.ledgers-page .ledger-footnote {
  color: #81758e;
  font-size: 12px;
}
.ledgers-page .intro-count,
.ledgers-page .current-label {
  color: #78658b;
  font-size: 11px;
}
.ledgers-page .intro-count b {
  color: #685576;
}
.ledgers-page .enter-ledger,
.ledgers-page .new-ledger-card strong {
  color: #7863bd;
  font-size: 12px;
}
.ledgers-page .ledger-search input {
  font-size: 12px;
  color: #65556f;
}
.ledgers-page .ledger-search input::placeholder {
  color: #9a8ea6;
}
.ledger-dialog h2 {
  color: #50405f;
}
.ledger-dialog .dialog-header p,
.ledger-dialog .field > span,
.ledger-dialog .field small,
.ledger-colors legend {
  color: #81758e;
  font-size: 12px;
}
.ledger-dialog .field input,
.ledger-dialog .field textarea {
  color: #5f4e70;
  font-size: 13px;
}
.ledger-dialog .field input::placeholder,
.ledger-dialog .field textarea::placeholder {
  color: #9d91a7;
}
@media (max-width: 640px) {
  .ledgers-page .ledger-heading p,
  .ledgers-page .ledger-intro p,
  .ledgers-page .ledger-card > p,
  .ledgers-page .ledger-meta,
  .ledgers-page .ledger-footnote {
    font-size: 11px;
  }
  .ledgers-page .ledger-card > p {
    min-height: 39px;
  }
  .ledgers-page .ledger-meta {
    gap: 8px;
  }
  .ledgers-page .current-label {
    font-size: 9px;
  }
  .ledgers-page .new-ledger-card p {
    font-size: 11px;
  }
}
</style>
