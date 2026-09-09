<script setup>
import { ref, reactive, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import { Eye, EyeOff, ArrowRight, ShieldCheck, Check } from "lucide-vue-next";
import { state, initSession } from "../lib/app";
import { api } from "../lib/api";
const router = useRouter(),
  route = useRoute();
const form = reactive({
    username: "",
    password: "",
    name: "",
    organization: "",
  }),
  busy = ref(false),
  error = ref(""),
  showPassword = ref(false),
  options = ref(null);
onMounted(async () => {
  try {
    options.value = await api("/auth/options");
    state.siteName = options.value.siteName || "账序";
  } catch {
    /* Login remains available when optional registration settings fail. */
  }
});
async function submit() {
  if (busy.value) return;
  error.value = "";
  busy.value = true;
  try {
    await api(state.needsSetup ? "/auth/setup" : "/auth/login", {
      method: "POST",
      body: state.needsSetup
        ? form
        : { username: form.username, password: form.password },
    });
    await initSession();
    const destination =
      typeof route.query.redirect === "string" &&
      route.query.redirect.startsWith("/") &&
      !route.query.redirect.startsWith("//")
        ? route.query.redirect
        : "/overview";
    router.replace(destination === "/login" ? "/overview" : destination);
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="login-page">
    <section class="login-story">
      <div class="brand" :title="state.siteName">
        <span class="brand-symbol">L<span></span></span>
        <div>
          <strong
            >{{ state.siteName
            }}<span v-if="state.siteName === '账序'">Ledgerly</span></strong
          ><small>让每一笔，都井然有序</small>
        </div>
      </div>
      <div class="login-story-content">
        <div class="page-eyebrow" style="color: #677fa7">
          YOUR BUSINESS, IN BALANCE
        </div>
        <h1>把账理清楚，<br /><span>把精力留给创造。</span></h1>
        <p>
          为公司与工作室打造的协作账本。<br />从第一笔收支，到每一次团队审核，<br />让资金的来去清晰，让协作更从容。
        </p>
        <div class="login-tags">
          <span><Check :size="14" />收支管理</span
          ><span><Check :size="14" />凭证归档</span
          ><span><Check :size="14" />团队协作</span>
        </div>
        <div class="login-preview" aria-hidden="true">
          <div class="login-preview-head">
            <span>每一笔努力，都有迹可循</span><span>LEDGERLY</span>
          </div>
          <div class="preview-chart">
            <i
              v-for="(height, index) in [
                27, 39, 33, 52, 45, 68, 57, 76, 68, 85, 78, 100,
              ]"
              :key="index"
              :style="{ height: height + '%' }"
            ></i>
          </div>
        </div>
      </div>
      <div class="login-story-footer">清晰记录 · 从容协作</div>
    </section>
    <section class="login-form-side">
      <form class="login-form" @submit.prevent="submit">
        <div class="page-eyebrow">
          {{ state.needsSetup ? "LET’S GET STARTED" : "WELCOME BACK" }}
        </div>
        <h2>{{ state.needsSetup ? "创建你的工作区" : "欢迎回到工作区" }}</h2>
        <p class="muted">
          {{
            state.needsSetup
              ? "从一个账本开始，让团队财务井然有序。"
              : `登录${options?.siteName || "账序"}，继续处理今天的财务工作。`
          }}
        </p>
        <template v-if="state.needsSetup"
          ><label class="field"
            ><span>工作区名称</span
            ><input
              v-model.trim="form.organization"
              placeholder="例如：山海设计工作室"
              required
              maxlength="80"
              autocomplete="organization" /></label
          ><label class="field"
            ><span>管理员姓名</span
            ><input
              v-model.trim="form.name"
              placeholder="你的称呼"
              required
              maxlength="50"
              autocomplete="name" /></label></template
        ><label class="field"
          ><span>{{ state.needsSetup ? "登录账号" : "账号或邮箱" }}</span
          ><input
            v-model.trim="form.username"
            :placeholder="
              state.needsSetup ? '设置登录账号' : '输入账号或已验证的邮箱'
            "
            required
            :maxlength="state.needsSetup ? 40 : 254"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false" /></label
        ><label class="field"
          ><span>{{ state.needsSetup ? "设置密码" : "登录密码" }}</span>
          <div class="password-wrap">
            <input
              v-model="form.password"
              :aria-label="state.needsSetup ? '设置密码' : '登录密码'"
              :type="showPassword ? 'text' : 'password'"
              :placeholder="state.needsSetup ? '至少 8 位字符' : '输入密码'"
              required
              :minlength="state.needsSetup ? 8 : 1"
              maxlength="256"
              :autocomplete="
                state.needsSetup ? 'new-password' : 'current-password'
              "
            /><button
              class="icon-btn"
              type="button"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" :size="16" /><Eye v-else :size="16" />
            </button></div
        ></label>
        <div v-if="error" class="error-box" role="alert">{{ error }}</div>
        <button class="btn btn-primary" :disabled="busy">
          <span v-if="busy" class="spinner"></span
          >{{
            busy
              ? "正在进入…"
              : state.needsSetup
                ? "创建工作区并进入"
                : "登录工作区"
          }}<ArrowRight v-if="!busy" :size="16" />
        </button>
        <div v-if="!state.needsSetup" class="login-account-links">
          <RouterLink v-if="options?.registrationMode === 'open'" to="/register"
            >创建新账号</RouterLink
          >
          <span v-else>{{
            options?.registrationMode === "closed"
              ? "新用户注册已关闭"
              : options?.registrationMode === "invite"
                ? "通过邀请链接注册"
                : ""
          }}</span>
          <RouterLink to="/recover">忘记密码？</RouterLink>
        </div>
        <p class="login-foot">
          <ShieldCheck :size="13" />{{
            state.needsSetup
              ? "你将成为首位管理员，可创建账本并邀请同事加入。"
              : options?.registrationMode === "open"
                ? "注册账号后，通过邀请加入团队账本。"
                : options?.registrationMode === "closed"
                  ? "已有账号仍可通过邀请加入新的账本。"
                  : "通过管理员的邀请链接，可以注册账号并加入账本。"
          }}<br />同一个账号，管理多个账本 · 权限按账本分配
        </p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.login-story {
  min-width: 0;
}
.login-story .brand-symbol {
  flex-shrink: 0;
}
.login-story .brand > div {
  min-width: 0;
  overflow: hidden;
}
.login-story .brand strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.login-account-links {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 17px;
  font-size: 11px;
}
.login-account-links a {
  color: #8b76bd;
  text-decoration: none;
}
.login-account-links a:hover {
  text-decoration: underline;
}
.login-account-links > span {
  color: #a49ab0;
}
</style>
