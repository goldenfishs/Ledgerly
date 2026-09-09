<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Loader2,
  UserRoundPlus,
} from "lucide-vue-next";
import AuthFrame from "../components/AuthFrame.vue";
import EmailCodeField from "../components/EmailCodeField.vue";
import { api } from "../lib/api";
import { initSession, state } from "../lib/app";
const router = useRouter();
const options = ref(null),
  loading = ref(true),
  error = ref(""),
  busy = ref(false),
  showPassword = ref(false),
  registered = ref(false);
const form = reactive({
  name: "",
  username: "",
  email: "",
  emailCode: "",
  password: "",
  confirmPassword: "",
});
const requiresCode = computed(
  () => options.value?.emailVerificationRequired || !!form.email.trim(),
);
const canRegister = computed(() => options.value?.registrationMode === "open");
async function load() {
  loading.value = true;
  error.value = "";
  try {
    options.value = await api("/auth/options");
    state.siteName = options.value.siteName || "账序";
  } catch (cause) {
    error.value = cause.message;
  } finally {
    loading.value = false;
  }
}
async function enter() {
  busy.value = true;
  try {
    await initSession();
    await router.replace(state.activeLedger ? "/overview" : "/ledgers");
  } catch (cause) {
    error.value = `账号已创建，暂时无法进入系统。${cause.message}`;
  } finally {
    busy.value = false;
  }
}
async function register() {
  if (busy.value || !canRegister.value || registered.value) return;
  error.value = "";
  if (form.password !== form.confirmPassword) {
    error.value = "两次输入的密码不一致，请重新确认。";
    return;
  }
  busy.value = true;
  try {
    await api("/auth/register", {
      method: "POST",
      body: {
        name: form.name.trim(),
        username: form.username.trim().toLowerCase(),
        password: form.password,
        ...(form.email.trim()
          ? { email: form.email.trim(), emailCode: form.emailCode }
          : {}),
      },
    });
    registered.value = true;
    form.password = "";
    form.confirmPassword = "";
    form.emailCode = "";
    await enter();
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <AuthFrame
    :title="registered ? '账号已创建' : '创建你的账号'"
    :description="
      registered
        ? '欢迎加入账序，接下来可以通过邀请加入团队账本。'
        : '一个账号，和团队一起管理每个账本。'
    "
  >
    <template #icon
      ><span class="register-symbol"
        ><Check v-if="registered" :size="25" /><UserRoundPlus
          v-else
          :size="25" /></span
    ></template>
    <div v-if="loading" class="register-status" role="status">
      <Loader2 :size="20" class="spin" />正在读取注册设置…
    </div>
    <template v-else-if="registered"
      ><div v-if="error" class="error-box" role="alert">{{ error }}</div>
      <button
        class="btn btn-primary register-submit"
        :disabled="busy"
        @click="enter"
      >
        {{ busy ? "正在进入…" : "进入系统" }}<ArrowRight :size="16" /></button
    ></template>
    <div v-else-if="!options">
      <div class="error-box" role="alert">{{ error }}</div>
      <button
        type="button"
        class="btn btn-secondary register-submit"
        @click="load"
      >
        重新加载
      </button>
    </div>
    <template v-else-if="!canRegister"
      ><div class="registration-note">
        {{
          options.registrationMode === "closed"
            ? "系统暂时关闭新用户注册。已有账号可以继续登录和接受账本邀请。"
            : "当前仅限邀请注册。请联系账本管理员获取邀请链接，再通过链接创建账号。"
        }}
      </div>
      <RouterLink to="/login" class="btn btn-primary register-submit"
        >返回登录<ArrowRight :size="16" /></RouterLink
    ></template>
    <form v-else @submit.prevent="register">
      <label class="field"
        ><span>你的称呼</span
        ><input
          v-model="form.name"
          required
          maxlength="80"
          placeholder="伙伴们怎么称呼你？"
          autocomplete="name"
          :disabled="busy"
      /></label>
      <label class="field"
        ><span>登录账号</span
        ><input
          v-model.trim="form.username"
          required
          minlength="3"
          maxlength="40"
          pattern="[a-zA-Z0-9_.\-]{3,40}"
          placeholder="3–40 位字母、数字或 . _ -"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          :disabled="busy"
      /></label>
      <label class="field"
        ><span
          >邮箱
          <small v-if="!options.emailVerificationRequired">选填</small></span
        ><input
          v-model.trim="form.email"
          type="email"
          maxlength="254"
          :required="options.emailVerificationRequired"
          placeholder="用于安全验证和找回密码"
          autocomplete="email"
          :disabled="busy || !options.emailEnabled"
        /><small v-if="!options.emailEnabled"
          >邮件服务暂未启用，{{
            options.emailVerificationRequired
              ? "请联系系统管理员。"
              : "可以先不填写邮箱。"
          }}</small
        ></label
      >
      <EmailCodeField
        v-if="requiresCode"
        v-model="form.emailCode"
        :email="form.email"
        :enabled="options.emailEnabled"
        :disabled="busy"
      />
      <label class="field"
        ><span>设置密码</span>
        <div class="password-wrap">
          <input
            v-model="form.password"
            aria-label="设置密码"
            :type="showPassword ? 'text' : 'password'"
            required
            minlength="8"
            maxlength="256"
            placeholder="至少 8 位字符"
            autocomplete="new-password"
            :disabled="busy"
          /><button
            type="button"
            class="icon-btn"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <EyeOff v-if="showPassword" :size="16" /><Eye v-else :size="16" />
          </button></div
      ></label>
      <label class="field"
        ><span>确认密码</span
        ><input
          v-model="form.confirmPassword"
          :type="showPassword ? 'text' : 'password'"
          required
          minlength="8"
          maxlength="256"
          placeholder="再次输入密码"
          autocomplete="new-password"
          :disabled="busy"
      /></label>
      <div v-if="error" class="error-box" role="alert">{{ error }}</div>
      <button
        class="btn btn-primary register-submit"
        :disabled="busy || (requiresCode && !options.emailEnabled)"
      >
        <Loader2 v-if="busy" :size="16" class="spin" />{{
          busy ? "正在创建…" : "创建账号"
        }}<ArrowRight v-if="!busy" :size="16" />
      </button>
      <p class="register-foot">
        已有账号？<RouterLink to="/login">返回登录</RouterLink>
      </p>
    </form>
  </AuthFrame>
</template>
<style scoped>
.register-symbol {
  display: grid;
  place-items: center;
  width: 49px;
  height: 49px;
  border-radius: 15px;
  background: #efebfa;
  color: #927cbe;
}
.register-status {
  display: flex;
  gap: 10px;
  justify-content: center;
  align-items: center;
  padding: 30px 0;
  color: #9b8aaa;
  font-size: 12px;
}
.register-submit {
  width: 100%;
  margin-top: 12px;
}
.register-foot {
  text-align: center;
  margin: 21px 0 0;
  font-size: 12px;
  color: #a194ae;
}
.register-foot a {
  margin-left: 7px;
  color: #8b70b9;
}
.registration-note {
  padding: 17px;
  border-radius: 11px;
  background: #f8f5fc;
  font-size: 12px;
  line-height: 1.9;
  color: #8e7a9e;
}
.field > span > small {
  font-weight: 400;
  margin-left: 5px;
  color: #a99bb4;
}
.spin {
  animation: register-spin 0.9s linear infinite;
}
@keyframes register-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
