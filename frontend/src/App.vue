<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute, useRouter, isNavigationFailure } from "vue-router";
import {
  LayoutDashboard,
  ArrowLeftRight,
  Wallet,
  ChartNoAxesCombined,
  ReceiptText,
  Users,
  Settings2,
  History,
  Plus,
  Menu,
  ChevronRight,
  LogOut,
  CheckCircle2,
  AlertCircle,
  BookOpen,
  ChevronDown,
  Check,
  ArrowUpRight,
  UserRound,
  SlidersHorizontal,
} from "lucide-vue-next";
import {
  state,
  initSession,
  notify,
  bus,
  selectLedger,
  refreshLedgers,
  clearSession,
  refreshSystemOptions,
} from "./lib/app";
import { api } from "./lib/api";
import FlowEditor from "./components/FlowEditor.vue";
import Login from "./pages/Login.vue";
const route = useRoute(),
  router = useRouter();
const menuOpen = ref(false),
  ledgerMenu = ref(false),
  editor = ref(false),
  sessionError = ref(""),
  logoutOpen = ref(false);
const isPublicPage = computed(() => Boolean(route.meta.public));
const avatarError = ref(false);
const avatarUrl = computed(() => !avatarError.value && state.user?.avatarUrl);
watch(
  () => state.user?.avatarUrl,
  () => {
    avatarError.value = false;
  },
);
const navigation = [
  {
    label: "我的空间",
    items: [
      { to: "/overview", name: "工作台", icon: LayoutDashboard },
      { to: "/ledgers", name: "我的账本", icon: BookOpen, any: true },
    ],
  },
  {
    label: "日常记账",
    items: [
      { to: "/transactions", name: "收支流水", icon: ArrowLeftRight },
      { to: "/accounts", name: "资金账户", icon: Wallet },
      { to: "/invoices", name: "发票凭证", icon: ReceiptText },
      { to: "/analysis", name: "统计报表", icon: ChartNoAxesCombined },
    ],
  },
  {
    label: "账本协作",
    items: [
      { to: "/team", name: "账本成员", icon: Users, admin: true },
      { to: "/audit", name: "操作日志", icon: History, admin: true },
      { to: "/settings", name: "账本设置", icon: Settings2 },
    ],
  },
  {
    label: "账号与系统",
    items: [
      { to: "/profile", name: "个人中心", icon: UserRound, any: true },
      {
        to: "/system",
        name: "系统设置",
        icon: SlidersHorizontal,
        any: true,
        systemAdmin: true,
      },
    ],
  },
];
const groups = computed(() =>
  navigation
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          (item.any || state.activeLedger) &&
          (!item.admin || state.user?.role === "admin") &&
          (!item.systemAdmin || state.user?.globalRole === "admin"),
      ),
    }))
    .filter((group) => group.items.length),
);
const userInitial = computed(() => state.user?.name?.slice(0, 1) || "我");
const activeColor = computed(() => state.activeLedger?.color || "#7863db");
function guard() {
  if (!state.ready || state.switchingLedger || isPublicPage.value) return;
  if (!state.user && route.path != "/login")
    router.replace({ path: "/login", query: { redirect: route.fullPath } });
  else if (state.user && !state.activeLedger && !route.meta.anyLedger)
    router.replace("/ledgers");
  else if (
    state.user &&
    (route.path === "/login" ||
      (route.meta.admin && state.user.role !== "admin") ||
      (route.meta.systemAdmin && state.user.globalRole !== "admin"))
  )
    router.replace(state.activeLedger ? "/overview" : "/ledgers");
}
async function start() {
  sessionError.value = "";
  try {
    await router.isReady();
    await initSession();
    await refreshSystemOptions().catch(() => {});
    guard();
  } catch (error) {
    sessionError.value = error.message;
  }
}
watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false;
    ledgerMenu.value = false;
    document.title = `${route.meta.title || "工作台"} · ${state.siteName}`;
    guard();
  },
);
watch(
  () => state.siteName,
  () => {
    document.title = `${route.meta.title || "工作台"} · ${state.siteName}`;
  },
);
watch(
  () => state.user,
  (user) => {
    if (
      !user ||
      (route.meta.admin && user.role !== "admin") ||
      (route.meta.systemAdmin && user.globalRole !== "admin")
    )
      guard();
  },
);
watch(
  () => [state.activeLedger?.id, state.user?.role],
  () => {
    editor.value = false;
    ledgerMenu.value = false;
  },
);
function expired() {
  clearSession();
  editor.value = false;
  guard();
}
function openFlow() {
  if (state.activeLedger) editor.value = true;
  else router.push("/ledgers");
}
function saved() {
  editor.value = false;
  bus.dispatchEvent(new Event("ledger-change"));
}
async function switchTo(id) {
  if (state.switchingLedger || String(id) === String(state.activeLedger?.id)) {
    ledgerMenu.value = false;
    return;
  }
  if (editor.value) {
    notify("请先保存或关闭正在填写的流水。", "error");
    return;
  }
  // Route guards let an open invoice or unfinished upload stop the switch.
  const failure = await router.push("/ledgers");
  if (failure && isNavigationFailure(failure) && route.path != "/ledgers")
    return;
  try {
    await selectLedger(id);
    await router.replace("/overview");
    notify(`已切换到「${state.activeLedger.name}」`);
  } catch (error) {
    notify(error.message, "error");
  }
}
let checkingAccess = false;
async function checkAccess() {
  if (checkingAccess || !state.user || state.switchingLedger) return;
  checkingAccess = true;
  try {
    await refreshLedgers();
    guard();
  } catch {
  } finally {
    checkingAccess = false;
  }
}
async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
    clearSession();
    logoutOpen.value = false;
    editor.value = false;
    router.replace("/login");
  } catch (error) {
    notify(error.message, "error");
  }
}
function keydown(event) {
  if (event.key === "Escape") {
    ledgerMenu.value = false;
    menuOpen.value = false;
  }
}
onMounted(() => {
  start();
  window.addEventListener("session-expired", expired);
  window.addEventListener("ledger-access-check", checkAccess);
  window.addEventListener("focus", checkAccess);
  document.addEventListener("keydown", keydown);
  bus.addEventListener("new-flow", openFlow);
});
onUnmounted(() => {
  window.removeEventListener("session-expired", expired);
  window.removeEventListener("ledger-access-check", checkAccess);
  window.removeEventListener("focus", checkAccess);
  document.removeEventListener("keydown", keydown);
  bus.removeEventListener("new-flow", openFlow);
});
</script>
<template>
  <div v-if="sessionError" class="startup">
    <AlertCircle :size="36" />
    <h1>暂时无法打开账本</h1>
    <p>{{ sessionError }}</p>
    <button class="btn btn-primary" @click="start">重新连接</button>
  </div>
  <div v-else-if="!state.ready" class="startup">
    <span class="brand-symbol"><BookOpen :size="23" /></span
    ><span class="spinner"></span>
    <p>正在打开你的账本…</p>
  </div>
  <RouterView v-else-if="isPublicPage" />
  <Login v-else-if="!state.user" />
  <div v-else class="app-shell">
    <div v-if="menuOpen" class="mobile-scrim" @click="menuOpen = false"></div>
    <aside class="sidebar" :class="{ open: menuOpen }">
      <RouterLink
        to="/overview"
        class="brand sidebar-brand"
        :aria-label="`${state.siteName}，返回工作台`"
        :title="state.siteName"
      >
        <span class="sidebar-brand-mark" aria-hidden="true">
          <BookOpen :size="21" :stroke-width="1.8" />
        </span>
        <span class="sidebar-brand-name">{{ state.siteName }}</span>
        <span v-if="state.siteName === '账序'" class="sidebar-brand-english"
          >Ledgerly</span
        >
      </RouterLink>
      <div class="ledger-selector">
        <button
          class="workspace-switch"
          aria-label="切换账本"
          :aria-expanded="ledgerMenu"
          :disabled="state.switchingLedger"
          @click="ledgerMenu = !ledgerMenu"
        >
          <span
            class="org-icon"
            :style="{ color: activeColor, background: activeColor + '15' }"
            ><BookOpen :size="18" /></span
          ><span class="selected-book-text"
            ><strong>{{ state.activeLedger?.name || "选择一个账本" }}</strong
            ><small>{{
              state.activeLedger
                ? state.user.role === "admin"
                  ? "账本管理员"
                  : "账本成员"
                : "创建或接受邀请加入"
            }}</small></span
          ><ChevronDown :size="15" />
        </button>
        <template v-if="ledgerMenu"
          ><button
            class="ledger-menu-scrim"
            aria-label="关闭账本列表"
            @click="ledgerMenu = false"
          ></button>
          <div class="ledger-menu" role="menu" aria-label="账本列表">
            <p>切换账本</p>
            <button
              v-for="ledger in state.ledgers"
              :key="ledger.id"
              role="menuitem"
              :class="{ selected: ledger.id === state.activeLedger?.id }"
              @click="switchTo(ledger.id)"
            >
              <span
                class="ledger-menu-icon"
                :style="{
                  background: (ledger.color || '#7863db') + '18',
                  color: ledger.color || '#7863db',
                }"
                ><BookOpen :size="17" /></span
              ><span
                >{{ ledger.name
                }}<small>{{
                  ledger.role === "admin" ? "管理员" : "成员"
                }}</small></span
              ><Check v-if="ledger.id === state.activeLedger?.id" :size="15" />
            </button>
            <div v-if="!state.ledgers.length" class="ledger-menu-empty">
              还没有加入的账本
            </div>
            <RouterLink to="/ledgers" class="ledger-menu-manage"
              ><Plus :size="16" />{{
                state.user.canCreateLedgers
                  ? "创建 / 管理账本"
                  : "查看我的账本"
              }}<ArrowUpRight :size="14"
            /></RouterLink></div
        ></template>
      </div>
      <nav aria-label="主导航">
        <div v-for="group in groups" :key="group.label" class="nav-group">
          <p>{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: route.path === item.to }"
            ><component
              :is="item.icon"
              :size="19"
              :stroke-width="1.7" /><span>{{ item.name }}</span
            ><i v-if="route.path === item.to" class="nav-indicator"></i
          ></RouterLink>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="sidebar-note">
          <span class="note-dots"><i></i><i></i><i></i></span>
          <p>一本账，一群人<br /><span>把每笔收支打理好</span></p>
        </div>
        <div class="profile-row">
          <button
            class="profile-open"
            aria-label="打开个人中心"
            @click="router.push('/profile')"
          >
            <span class="avatar"
              ><img
                v-if="avatarUrl"
                :src="avatarUrl"
                alt=""
                @error="avatarError = true"
              /><template v-else>{{ userInitial }}</template></span
            ><span
              ><strong>{{ state.user.name }}</strong
              ><small>{{
                state.user.canCreateLedgers ? "管理员" : "我的账号"
              }}</small></span
            >
          </button>
          <button
            class="icon-btn profile-logout"
            aria-label="退出登录"
            title="退出登录"
            @click="logoutOpen = true"
          >
            <LogOut :size="16" />
          </button>
        </div>
      </div>
    </aside>
    <div class="app-main">
      <header class="topbar">
        <div class="breadcrumbs">
          <button
            class="icon-btn menu-toggle"
            aria-label="展开导航"
            @click="menuOpen = !menuOpen"
          >
            <Menu :size="20" /></button
          ><span>{{ state.activeLedger?.name || "我的空间" }}</span
          ><ChevronRight :size="13" /><strong>{{ route.meta.title }}</strong>
        </div>
        <div class="top-actions">
          <span v-if="state.activeLedger" class="secure-chip"
            ><i :style="{ background: activeColor }"></i
            >{{ state.activeLedger.memberCount ?? 1 }} 位成员</span
          ><button
            v-if="state.activeLedger"
            class="btn btn-primary btn-sm"
            :disabled="state.switchingLedger"
            @click="openFlow"
          >
            <Plus :size="17" />记一笔</button
          ><RouterLink
            to="/profile"
            class="avatar avatar-small"
            aria-label="个人中心"
            ><img
              v-if="avatarUrl"
              :src="avatarUrl"
              alt=""
              @error="avatarError = true"
            /><template v-else>{{ userInitial }}</template></RouterLink
          >
        </div>
      </header>
      <main class="page-body">
        <div v-if="state.switchingLedger" class="loading-state">
          <span class="spinner"></span>正在切换账本…
        </div>
        <div
          v-else-if="!state.activeLedger && !route.meta.anyLedger"
          class="loading-state"
        >
          <span class="spinner"></span>
        </div>
        <RouterView
          v-else
          :key="`${state.user.id}:${state.user.role}:${state.activeLedger?.id || 'none'}`"
        />
      </main>
      <footer class="app-footer">
        <span>{{ state.siteName }} · 让记账轻一点</span
        ><span>{{ state.activeLedger?.name || state.organization }}</span>
      </footer>
    </div>
    <FlowEditor
      v-if="state.activeLedger && !state.switchingLedger"
      :key="`${state.activeLedger.id}:${state.user.role}`"
      v-model="editor"
      @saved="saved"
    />
    <div
      v-if="logoutOpen"
      class="modal-backdrop"
      @click.self="logoutOpen = false"
    >
      <section
        class="dialog card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="logout-title"
      >
        <h2 id="logout-title">退出登录？</h2>
        <p class="muted">已保存的账本和记录会保留。</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="logoutOpen = false">
            取消</button
          ><button class="btn btn-primary" @click="logout">退出登录</button>
        </div>
      </section>
    </div>
  </div>
  <div class="toast-stack" role="status" aria-live="polite">
    <div
      v-for="toast in state.toasts"
      :key="toast.id"
      class="toast"
      :class="toast.type"
    >
      <AlertCircle v-if="toast.type === 'error'" :size="18" /><CheckCircle2
        v-else
        :size="18"
      />{{ toast.message }}
    </div>
  </div>
</template>
