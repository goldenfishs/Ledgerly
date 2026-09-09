<script setup>
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";
import { Loader2 } from "lucide-vue-next";
import { api } from "../lib/api";
const props = defineProps({
  modelValue: { type: String, default: "" },
  email: { type: String, default: "" },
  purpose: { type: String, default: "register" },
  invitationToken: String,
  disabled: Boolean,
  enabled: { type: Boolean, default: true },
});
const emit = defineEmits(["update:modelValue"]);
const codeId = useId();
const sending = ref(false),
  error = ref(""),
  message = ref(""),
  retryAt = ref(0),
  now = ref(Date.now());
const remaining = computed(() =>
  Math.max(0, Math.ceil((retryAt.value - now.value) / 1000)),
);
const timer = setInterval(() => {
  now.value = Date.now();
}, 1000);
watch(
  () => props.email,
  () => {
    error.value = "";
    message.value = "";
    emit("update:modelValue", "");
  },
);
onBeforeUnmount(() => clearInterval(timer));
async function send() {
  if (sending.value || props.disabled || !props.enabled || remaining.value)
    return;
  error.value = "";
  message.value = "";
  const address = props.email.trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
    error.value = "请先填写有效的邮箱地址。";
    return;
  }
  sending.value = true;
  try {
    const result = await api("/auth/email-code", {
      method: "POST",
      body: {
        email: address,
        purpose: props.purpose,
        ...(props.invitationToken
          ? { invitationToken: props.invitationToken }
          : {}),
      },
    });
    retryAt.value = Date.now() + (Number(result.retryAfter) || 60) * 1000;
    now.value = Date.now();
    if (props.email.trim() === address)
      message.value =
        props.purpose === "reset-password"
          ? "如果此邮箱已验证并关联账号，你将收到验证码，请查看收件箱。"
          : "若此邮箱可用于注册，验证码将发送至邮箱。请查看收件箱，10 分钟内有效。";
  } catch (cause) {
    error.value = cause.message;
  } finally {
    sending.value = false;
  }
}
</script>
<template>
  <div class="email-code-group">
    <div class="field">
      <label :for="codeId">邮箱验证码</label>
      <div class="email-code-row">
        <input
          :id="codeId"
          :value="modelValue"
          @input="
            emit(
              'update:modelValue',
              $event.target.value.replace(/\D/g, '').slice(0, 6),
            )
          "
          inputmode="numeric"
          autocomplete="one-time-code"
          pattern="[0-9]{6}"
          minlength="6"
          maxlength="6"
          placeholder="6 位验证码"
          required
          :disabled="disabled || !enabled"
        /><button
          type="button"
          class="btn btn-secondary"
          :disabled="
            disabled || sending || !enabled || !email.trim() || remaining > 0
          "
          @click="send"
        >
          <Loader2 v-if="sending" :size="14" class="code-spin" />{{
            sending
              ? "发送中…"
              : remaining
                ? `${remaining} 秒后重发`
                : "获取验证码"
          }}
        </button>
      </div>
    </div>
    <p v-if="!enabled" class="code-error">
      邮件服务暂未启用，请联系系统管理员。
    </p>
    <p v-if="error" class="code-error" role="alert">{{ error }}</p>
    <p v-if="message" class="code-message" role="status">{{ message }}</p>
  </div>
</template>
<style scoped>
.email-code-group {
  margin-bottom: 18px;
}
.email-code-group .field {
  margin-bottom: 0;
}
.email-code-row {
  display: flex;
  gap: 9px;
}
.email-code-row input {
  min-width: 0;
  width: 100%;
}
.email-code-row button {
  flex-shrink: 0;
  padding-inline: 12px;
  font-size: 11px;
}
.code-error,
.code-message {
  font-size: 11px;
  line-height: 1.8;
  margin: 8px 0 0;
}
.code-error {
  color: #be7265;
}
.code-message {
  color: #6f977f;
}
.code-spin {
  animation: code-spin 0.9s linear infinite;
}
@keyframes code-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 350px) {
  .email-code-row {
    flex-wrap: wrap;
  }
}
</style>
