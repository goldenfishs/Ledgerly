<script setup>
import { onMounted, reactive, ref } from "vue";
import {
  ArrowLeft,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
} from "lucide-vue-next";
import AuthFrame from "../components/AuthFrame.vue";
import EmailCodeField from "../components/EmailCodeField.vue";
import { api } from "../lib/api";
import { clearSession, state } from "../lib/app";
const options = ref(null),
  loading = ref(true),
  error = ref(""),
  busy = ref(false),
  complete = ref(false),
  showPassword = ref(false);
const form = reactive({
  email: "",
  emailCode: "",
  password: "",
  confirmPassword: "",
});
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
async function reset() {
  if (busy.value || !options.value?.emailEnabled || complete.value) return;
  error.value = "";
  if (form.password !== form.confirmPassword) {
    error.value = "两次输入的密码不一致，请重新确认。";
    return;
  }
  busy.value = true;
  try {
    await api("/auth/reset-password", {
      method: "POST",
      body: {
        email: form.email.trim(),
        emailCode: form.emailCode,
        newPassword: form.password,
      },
    });
    complete.value = true;
    clearSession();
    form.password = "";
    form.confirmPassword = "";
    form.emailCode = "";
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
    :title="complete ? '密码已更新' : '找回密码'"
    :description="
      complete
        ? '请使用新密码重新登录，你之前的登录会话已失效。'
        : '使用账号已验证的邮箱，安全地重新设置密码。'
    "
  >
    <template #icon
      ><span class="recover-symbol"
        ><Check v-if="complete" :size="25" /><KeyRound
          v-else
          :size="25" /></span
    ></template>
    <div v-if="loading" class="recover-status" role="status">
      <Loader2 :size="20" class="spin" />正在读取安全设置…
    </div>
    <div v-else-if="!options">
      <div class="error-box" role="alert">{{ error }}</div>
      <button
        type="button"
        class="btn btn-secondary recover-submit"
        @click="load"
      >
        重新加载
      </button>
    </div>
    <p v-else-if="!options.emailEnabled" class="recover-note">
      系统尚未启用邮件服务，暂时无法通过邮箱找回密码。请联系系统管理员。
    </p>
    <form v-else-if="!complete" @submit.prevent="reset">
      <label class="field"
        ><span>已验证的邮箱</span
        ><input
          v-model.trim="form.email"
          type="email"
          required
          maxlength="254"
          placeholder="输入账号绑定并验证过的邮箱"
          autocomplete="email"
          :disabled="busy"
      /></label>
      <EmailCodeField
        v-model="form.emailCode"
        :email="form.email"
        purpose="reset-password"
        :disabled="busy"
      />
      <label class="field"
        ><span>新密码</span>
        <div class="password-wrap">
          <input
            v-model="form.password"
            aria-label="新密码"
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
        ><span>确认新密码</span
        ><input
          v-model="form.confirmPassword"
          :type="showPassword ? 'text' : 'password'"
          required
          minlength="8"
          maxlength="256"
          placeholder="再次输入新密码"
          autocomplete="new-password"
          :disabled="busy"
      /></label>
      <div v-if="error" class="error-box" role="alert">{{ error }}</div>
      <button class="btn btn-primary recover-submit" :disabled="busy">
        <Loader2 v-if="busy" :size="16" class="spin" />{{
          busy ? "正在更新…" : "更新密码"
        }}
      </button>
    </form>
    <RouterLink
      to="/login"
      :class="complete ? 'btn btn-primary recover-submit' : 'recover-back'"
      ><ArrowLeft :size="14" />返回登录</RouterLink
    >
  </AuthFrame>
</template>
<style scoped>
.recover-symbol {
  display: grid;
  place-items: center;
  width: 49px;
  height: 49px;
  border-radius: 15px;
  background: #eaf4ee;
  color: #83a58f;
}
.recover-status {
  display: flex;
  gap: 10px;
  justify-content: center;
  align-items: center;
  padding: 30px 0;
  color: #9b8aaa;
  font-size: 12px;
}
.recover-submit {
  width: 100%;
  margin-top: 12px;
}
.recover-note {
  padding: 17px;
  border-radius: 11px;
  background: #fff6e7;
  font-size: 12px;
  line-height: 1.9;
  color: #aa9166;
}
.recover-back {
  display: flex;
  align-items: center;
  gap: 5px;
  justify-content: center;
  margin-top: 23px;
  color: #8b70b9;
  font-size: 12px;
  text-decoration: none;
}
.spin {
  animation: recover-spin 0.9s linear infinite;
}
@keyframes recover-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
