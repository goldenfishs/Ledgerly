<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import {
  Building2,
  ShieldCheck,
  FolderTree,
  Plus,
  Search,
  Pencil,
  Archive,
  RotateCcw,
  X,
  Check,
  Settings2,
  LockKeyhole,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { state, notify, refreshLedgers } from "../lib/app";

const admin = computed(() => state.user?.role === "admin");
const organization = ref(""),
  savedName = ref(""),
  roots = ref([]),
  loading = ref(true),
  failure = ref(""),
  saving = ref(false),
  organizationError = ref("");
const query = ref(""),
  showArchived = ref(false),
  actionFilter = ref("");
const editor = ref(null),
  archiveTarget = ref(null),
  modal = ref(null),
  busy = ref(false),
  mutationError = ref("");
const actionNames = { 0: "收入", 1: "支出", 2: "转账" };
const flat = computed(() =>
  roots.value.flatMap((root) => [
    { ...root, depth: 0 },
    ...(root.child || root.childrenTypes || []).map((child) => ({
      ...child,
      depth: 1,
      parentName: root.tname || root.name,
      parentEnabled: root.enable,
    })),
  ]),
);
const visible = computed(() =>
  flat.value.filter(
    (item) =>
      (showArchived.value || item.enable) &&
      (actionFilter.value === "" ||
        item.actionIds.includes(Number(actionFilter.value))) &&
      `${item.tname || item.name} ${item.parentName || ""}`
        .toLowerCase()
        .includes(query.value.trim().toLowerCase()),
  ),
);
const activeCount = computed(
  () => flat.value.filter((item) => item.enable).length,
);
const parentOptions = computed(() =>
  roots.value.filter((item) => item.enable && item.id !== editor.value?.id),
);
const allowedActions = computed(() =>
  editor.value?.parent
    ? parentOptions.value.find((item) => item.id === editor.value.parent)
        ?.actionIds || []
    : [0, 1, 2],
);
const hasChildren = computed(
  () =>
    editor.value?.id &&
    roots.value.some(
      (root) =>
        root.id === editor.value.id &&
        (root.child || root.childrenTypes || []).length,
    ),
);
async function load() {
  loading.value = true;
  failure.value = "";
  try {
    const [settings, categories] = await Promise.all([
      api("/settings"),
      api("/type/getType/noLimit"),
    ]);
    organization.value = settings.name || settings.organization || "";
    savedName.value = organization.value;
    roots.value = categories || [];
  } catch (error) {
    failure.value = error.message;
  } finally {
    loading.value = false;
  }
}
async function reloadCategories() {
  roots.value = await api("/type/getType/noLimit");
}
async function saveOrganization() {
  if (!admin.value || saving.value) return;
  organizationError.value = "";
  if (!organization.value.trim()) {
    organizationError.value = "请填写账本名称";
    return;
  }
  saving.value = true;
  try {
    const result = await api("/settings", {
      method: "PUT",
      body: { name: organization.value.trim() },
    });
    savedName.value = result.name;
    organization.value = result.name;
    if (state.activeLedger) state.activeLedger.name = result.name;
    await refreshLedgers();
    notify("账本设置已保存");
  } catch (error) {
    organizationError.value = error.message;
  } finally {
    saving.value = false;
  }
}
function openEditor(item = null) {
  if (!admin.value) return;
  mutationError.value = "";
  editor.value = item
    ? {
        id: item.id,
        tname: item.tname || item.name,
        parent: item.parent || null,
        actionIds: [...item.actionIds],
        enable: Boolean(item.enable),
      }
    : { tname: "", parent: null, actionIds: [0, 1, 2], enable: true };
  nextTick(() => modal.value?.querySelector("input")?.focus());
}
function changeParent() {
  editor.value.actionIds = editor.value.actionIds.filter((action) =>
    allowedActions.value.includes(action),
  );
  if (!editor.value.actionIds.length)
    editor.value.actionIds = [...allowedActions.value];
}
async function saveCategory() {
  if (busy.value || !admin.value) return;
  mutationError.value = "";
  if (!editor.value.tname.trim()) {
    mutationError.value = "请填写分类名称";
    return;
  }
  if (!editor.value.actionIds.length) {
    mutationError.value = "至少选择一种适用收支类型";
    return;
  }
  busy.value = true;
  const body = {
    tname: editor.value.tname.trim(),
    parent: editor.value.parent,
    actionIds: editor.value.actionIds,
    enable: editor.value.enable,
  };
  try {
    await api(
      editor.value.id ? `/type/updateType/${editor.value.id}` : "/type/addType",
      { method: editor.value.id ? "PUT" : "POST", body },
    );
    editor.value = null;
    notify("分类已保存");
    await reloadCategories();
  } catch (error) {
    mutationError.value = error.message;
  } finally {
    busy.value = false;
  }
}
function confirmArchive(item) {
  if (!admin.value) return;
  archiveTarget.value = item;
  mutationError.value = "";
  nextTick(() => modal.value?.querySelector("button")?.focus());
}
async function archiveCategory() {
  if (busy.value || !admin.value) return;
  busy.value = true;
  try {
    await api(`/type/deleteType/${archiveTarget.value.id}`, {
      method: "DELETE",
    });
    archiveTarget.value = null;
    notify("分类已归档，历史流水保持可查");
    await reloadCategories();
  } catch (error) {
    mutationError.value = error.message;
  } finally {
    busy.value = false;
  }
}
async function restoreCategory(item) {
  if (busy.value || !admin.value) return;
  busy.value = true;
  try {
    await api(`/type/updateType/${item.id}`, {
      method: "PUT",
      body: {
        tname: item.tname || item.name,
        parent: item.parent || null,
        actionIds: item.actionIds,
        enable: true,
      },
    });
    notify("分类已恢复");
    await reloadCategories();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    busy.value = false;
  }
}
function closeModal() {
  if (!busy.value) {
    editor.value = null;
    archiveTarget.value = null;
  }
}
function keydown(event) {
  if (!editor.value && !archiveTarget.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeModal();
  }
  if (event.key === "Tab") {
    const nodes = [
      ...modal.value.querySelectorAll(
        "button:not(:disabled),input:not(:disabled),select:not(:disabled)",
      ),
    ].filter((node) => node.getClientRects().length);
    if (!nodes.length) return;
    if (
      event.shiftKey &&
      (document.activeElement === nodes[0] ||
        !modal.value.contains(document.activeElement))
    ) {
      event.preventDefault();
      nodes.at(-1).focus();
    } else if (
      !event.shiftKey &&
      (document.activeElement === nodes.at(-1) ||
        !modal.value.contains(document.activeElement))
    ) {
      event.preventDefault();
      nodes[0].focus();
    }
  }
}
onMounted(() => {
  load();
  document.addEventListener("keydown", keydown);
});
onBeforeUnmount(() => document.removeEventListener("keydown", keydown));
</script>

<template>
  <div class="page-header">
    <div>
      <div class="page-eyebrow">WORKSPACE SETTINGS</div>
      <h1>账本设置</h1>
      <p>维护账本信息与收支分类，让团队使用同一套记账规则。</p>
    </div>
  </div>
  <div v-if="loading" class="card loading-state">
    <span class="spinner"></span>正在读取设置…
  </div>
  <div v-else-if="failure" class="card empty-state">
    <Settings2 :size="32" />
    <h3>暂时无法读取设置</h3>
    <p>{{ failure }}</p>
    <button class="btn btn-secondary" @click="load">重新加载</button>
  </div>
  <template v-else>
    <div class="settings-grid st-overview">
      <section class="card settings-card">
        <div class="st-section-title">
          <span><Building2 :size="20" /></span>
          <div>
            <h2>账本信息</h2>
            <p class="muted small">账本名称会显示在账本列表和导航中</p>
          </div>
        </div>
        <form @submit.prevent="saveOrganization">
          <label class="field"
            ><span>账本名称</span
            ><input
              v-model="organization"
              :readonly="!admin"
              :disabled="saving"
              maxlength="120"
              placeholder="填写公司或账本名称"
          /></label>
          <div class="st-currency">
            <span>记账币种</span><strong>人民币 CNY <small>¥</small></strong>
          </div>
          <p v-if="organizationError" class="error-box" role="alert">
            {{ organizationError }}
          </p>
          <div class="st-save">
            <span class="muted small">{{
              admin ? "仅更新当前账本" : "账本信息由管理员维护"
            }}</span
            ><button
              v-if="admin"
              class="btn btn-primary btn-sm"
              :disabled="saving || organization.trim() === savedName"
            >
              <Check :size="15" />{{ saving ? "保存中…" : "保存设置" }}
            </button>
          </div>
        </form>
      </section>
      <section class="card settings-card">
        <div class="st-section-title">
          <span class="green"><ShieldCheck :size="20" /></span>
          <div>
            <h2>团队权限</h2>
            <p class="muted small">按角色分工，共同维护清楚的账目</p>
          </div>
        </div>
        <div class="st-role">
          <span class="badge badge-blue">管理员</span>
          <p>管理团队、账户和分类，审核流水，查看团队账目与操作记录。</p>
        </div>
        <div class="st-role">
          <span class="badge badge-green">成员</span>
          <p>提交自己的流水，整理自己的发票凭证，查看审核进度。</p>
        </div>
        <div class="st-access">
          <LockKeyhole :size="14" />你当前的角色：<strong>{{
            admin ? "管理员" : "成员"
          }}</strong>
        </div>
      </section>
    </div>
    <section class="card">
      <div class="card-head st-category-head">
        <div>
          <h2>
            收支分类 <span class="st-count">{{ activeCount }}</span>
          </h2>
          <p>分类用于整理流水，支持一级分类和子分类</p>
        </div>
        <button
          v-if="admin"
          class="btn btn-primary btn-sm"
          @click="openEditor()"
        >
          <Plus :size="16" />新增分类
        </button>
      </div>
      <div class="table-toolbar st-category-tools">
        <div class="search-box">
          <Search :size="16" /><input
            v-model="query"
            placeholder="搜索分类名称"
            aria-label="搜索分类"
          />
        </div>
        <div class="filters">
          <select v-model="actionFilter" aria-label="适用类型">
            <option value="">全部收支类型</option>
            <option value="0">收入</option>
            <option value="1">支出</option>
            <option value="2">转账</option></select
          ><label class="st-check"
            ><input v-model="showArchived" type="checkbox" />显示已归档</label
          >
        </div>
      </div>
      <div v-if="!visible.length" class="empty-state">
        <FolderTree :size="32" />
        <h3>
          {{
            query || actionFilter !== "" ? "没有匹配的分类" : "还没有可用分类"
          }}
        </h3>
        <p>
          {{
            admin
              ? "创建常用分类，让每一笔收支都有清晰归属。"
              : "分类由管理员统一维护。"
          }}
        </p>
        <button
          v-if="admin && !flat.length"
          class="btn btn-primary btn-sm"
          @click="openEditor()"
        >
          新增分类
        </button>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>分类名称</th>
              <th>适用类型</th>
              <th>状态</th>
              <th v-if="admin" class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in visible"
              :key="item.id"
              :class="{ 'st-archived': !item.enable }"
            >
              <td>
                <div class="st-category-name" :class="{ child: item.depth }">
                  <span class="st-tree-mark" v-if="item.depth">└</span
                  ><span class="st-folder"><FolderTree :size="15" /></span>
                  <div>
                    <span class="table-main">{{
                      item.tname || item.name
                    }}</span>
                    <div v-if="item.parentName" class="table-sub">
                      {{ item.parentName }} / 子分类
                    </div>
                  </div>
                </div>
              </td>
              <td>
                <div class="st-action-tags">
                  <span
                    v-for="action in item.actionIds"
                    :key="action"
                    class="badge"
                    :class="
                      action === 0
                        ? 'badge-green'
                        : action === 1
                          ? 'badge-amber'
                          : 'badge-blue'
                    "
                    >{{ actionNames[action] }}</span
                  >
                </div>
              </td>
              <td>
                <span class="badge" :class="item.enable ? 'badge-green' : ''">{{
                  item.enable ? "使用中" : "已归档"
                }}</span>
              </td>
              <td v-if="admin" class="text-right">
                <div class="st-row-actions">
                  <button
                    class="icon-btn"
                    :aria-label="`编辑${item.tname}`"
                    title="编辑分类"
                    :disabled="busy || (item.depth && !item.parentEnabled)"
                    @click="openEditor(item)"
                  >
                    <Pencil :size="15" /></button
                  ><button
                    v-if="item.enable"
                    class="icon-btn"
                    :aria-label="`归档${item.tname}`"
                    title="归档分类"
                    :disabled="busy"
                    @click="confirmArchive(item)"
                  >
                    <Archive :size="15" /></button
                  ><button
                    v-else
                    class="icon-btn"
                    :aria-label="`恢复${item.tname}`"
                    :title="
                      item.depth && !item.parentEnabled
                        ? '请先恢复父分类'
                        : '恢复分类'
                    "
                    :disabled="busy || (item.depth && !item.parentEnabled)"
                    @click="restoreCategory(item)"
                  >
                    <RotateCcw :size="15" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <span
          >共 {{ flat.length }} 个分类 · 当前显示 {{ visible.length }} 个</span
        ><span>{{ admin ? "归档不会删除已有流水" : "分类由管理员维护" }}</span>
      </div>
    </section>
  </template>
  <Teleport to="body"
    ><div
      v-if="editor || archiveTarget"
      class="modal-backdrop"
      @click.self="closeModal"
    >
      <section
        ref="modal"
        class="card dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="st-modal-title"
      >
        <div class="dialog-header">
          <div>
            <h2 id="st-modal-title">
              {{ editor ? (editor.id ? "编辑分类" : "新增分类") : "归档分类" }}
            </h2>
            <p class="muted small">
              {{
                editor
                  ? "设置分类名称与适用的收支类型"
                  : "保留历史数据，停止用于新流水"
              }}
            </p>
          </div>
          <button
            class="icon-btn"
            :disabled="busy"
            aria-label="关闭"
            @click="closeModal"
          >
            <X :size="20" />
          </button>
        </div>
        <form v-if="editor" @submit.prevent="saveCategory">
          <label class="field"
            ><span>分类名称</span
            ><input
              v-model="editor.tname"
              maxlength="80"
              :disabled="busy"
              placeholder="例如：办公采购" /></label
          ><label class="field"
            ><span>上级分类</span
            ><select
              v-model="editor.parent"
              :disabled="busy || hasChildren"
              @change="changeParent"
            >
              <option :value="null">无，作为一级分类</option>
              <option
                v-for="item in parentOptions"
                :key="item.id"
                :value="item.id"
              >
                {{ item.tname || item.name }}
              </option></select
            ><small>{{
              hasChildren
                ? "包含子分类的分类保留为一级分类"
                : "子分类会沿用父分类允许的收支类型"
            }}</small></label
          >
          <div class="field">
            <span>适用收支类型</span>
            <div class="st-action-options">
              <label v-for="(name, id) in actionNames" :key="id"
                ><input
                  v-model="editor.actionIds"
                  type="checkbox"
                  :value="Number(id)"
                  :disabled="busy || !allowedActions.includes(Number(id))"
                />{{ name }}</label
              >
            </div>
          </div>
          <p v-if="mutationError" class="error-box" role="alert">
            {{ mutationError }}
          </p>
          <div class="dialog-actions">
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="busy"
              @click="closeModal"
            >
              取消</button
            ><button class="btn btn-primary" :disabled="busy">
              {{ busy ? "保存中…" : "保存分类" }}
            </button>
          </div>
        </form>
        <template v-else
          ><p>
            确定归档「{{ archiveTarget.tname || archiveTarget.name }}」？{{
              archiveTarget.depth ? "" : "它的子分类也会一并归档。"
            }}已有流水仍可查看，之后可以恢复分类。
          </p>
          <p v-if="mutationError" class="error-box" role="alert">
            {{ mutationError }}
          </p>
          <div class="dialog-actions">
            <button
              class="btn btn-secondary"
              :disabled="busy"
              @click="closeModal"
            >
              取消</button
            ><button
              class="btn btn-danger"
              :disabled="busy"
              @click="archiveCategory"
            >
              {{ busy ? "归档中…" : "确认归档" }}
            </button>
          </div></template
        >
      </section>
    </div></Teleport
  >
</template>

<style scoped>
.st-overview {
  margin-bottom: 24px;
}
.st-section-title {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 25px;
}
.st-section-title > span {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: #eff3fe;
  color: #7894d8;
  display: grid;
  place-items: center;
}
.st-section-title > span.green {
  background: #eef8f2;
  color: #72b49c;
}
.st-section-title h2 {
  font-size: 15px;
  margin: 0 0 6px;
}
.st-section-title p {
  font-size: 11px;
  margin: 0;
}
.st-currency {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0 22px;
  color: #939ead;
  font-size: 12px;
}
.st-currency strong {
  color: #63738c;
  font-weight: 500;
}
.st-currency small {
  font-size: 12px;
  background: #f2f5fa;
  padding: 5px 9px;
  border-radius: 5px;
  margin-left: 6px;
  color: #94a3b9;
}
.st-save {
  padding-top: 18px;
  border-top: 1px solid #edf1f6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  min-height: 57px;
}
.st-save .small {
  font-size: 10px;
}
.st-role {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  margin: 0 0 18px;
}
.st-role p {
  font-size: 12px;
  color: #939eb0;
  margin: 0;
  line-height: 1.9;
}
.st-role .badge {
  margin-top: 2px;
  flex-shrink: 0;
}
.st-access {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #99a6b9;
  background: #f8fafd;
  border-radius: 7px;
  padding: 13px;
  margin-top: 20px;
}
.st-access strong {
  font-weight: 500;
  color: #6980a5;
}
.st-count {
  display: inline-block;
  font-size: 10px;
  color: #8e9eb6;
  background: #f2f5fa;
  padding: 3px 6px;
  border-radius: 4px;
  margin-left: 6px;
  vertical-align: middle;
}
.st-category-head {
  padding-bottom: 20px;
}
.st-category-tools {
  border-top: 1px solid #edf1f6;
}
.st-category-tools .search-box {
  max-width: 330px;
  width: 100%;
}
.st-check {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: #929db0;
  white-space: nowrap;
}
.st-check input {
  margin: 0;
}
.st-category-name {
  display: flex;
  gap: 10px;
  align-items: center;
}
.st-folder {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: #f1f5fe;
  color: #8fa5ce;
}
.st-category-name.child {
  margin-left: 13px;
}
.st-tree-mark {
  color: #c7d0df;
}
.st-action-tags {
  display: flex;
  gap: 6px;
}
.st-row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
}
.st-archived .table-main {
  color: #9ea8b7;
}
.st-action-options {
  display: flex;
  gap: 24px;
  padding: 6px 0 12px;
}
.st-action-options label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #8190a6;
}
.st-action-options input {
  margin: 0;
}
.dialog-header p {
  margin: 0;
}
.field input:read-only {
  background: #f9fbfe;
  color: #8291a6;
}
.pagination span:last-child {
  font-size: 10px;
}
@media (max-width: 760px) {
  .settings-card {
    padding: 21px;
  }
  .st-category-tools {
    align-items: flex-start;
  }
  .st-category-tools .search-box {
    max-width: none;
  }
  .st-category-tools .filters {
    width: 100%;
    justify-content: space-between;
  }
  .st-role {
    gap: 10px;
  }
  .st-role p {
    font-size: 11px;
  }
  .st-save {
    flex-wrap: wrap;
  }
  .st-category-head {
    gap: 10px;
  }
  .st-category-head p {
    font-size: 10px;
  }
  .pagination {
    padding: 15px;
    gap: 12px;
  }
  .pagination span {
    font-size: 10px;
  }
  .st-action-tags {
    gap: 3px;
  }
  .st-action-tags .badge {
    padding: 4px 5px;
  }
}
</style>
