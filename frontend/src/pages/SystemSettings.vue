<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import {
  Check,
  Globe2,
  Loader2,
  Mail,
  Send,
  Settings2,
  ShieldCheck,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { initSession, notify, refreshSystemOptions } from "../lib/app";

const loading = ref(true),
  loadError = ref(""),
  siteBusy = ref(false),
  mailBusy = ref(false),
  testBusy = ref(false);
const siteError = ref(""),
  mailError = ref(""),
  testError = ref(""),
  testSuccess = ref("");
const site = reactive({
  siteName: "",
  registrationMode: "invite",
  emailVerificationRequired: false,
});
const mail = reactive({
  enabled: false,
  host: "",
  port: 587,
  security: "starttls",
  username: "",
  password: "",
  fromEmail: "",
  fromName: "",
  clearPassword: false,
});
const passwordConfigured = ref(false),
  savedMail = ref(""),
  recipient = ref("");
const modes = [
  {
    value: "invite",
    title: "仅邀请注册",
    text: "新用户通过账本邀请链接创建账号。",
    icon: ShieldCheck,
  },
  {
    value: "open",
    title: "开放注册",
    text: "任何人可注册，加入账本仍需邀请。",
    icon: Globe2,
  },
  {
    value: "closed",
    title: "关闭注册",
    text: "暂停创建新账号，已有用户可正常加入账本。",
    icon: Settings2,
  },
];
const mailDirty = computed(() => JSON.stringify(mail) !== savedMail.value);
const mailReady = computed(
  () => mail.enabled && !!mail.host && !!mail.fromEmail && !mailDirty.value,
);
function applyMail(data) {
  Object.assign(mail, {
    enabled: !!data.enabled,
    host: data.host || "",
    port: data.port || 587,
    security: data.security || "starttls",
    username: data.username || "",
    fromEmail: data.fromEmail || "",
    fromName: data.fromName || "",
    password: "",
    clearPassword: false,
  });
  passwordConfigured.value = !!data.passwordConfigured;
  savedMail.value = JSON.stringify(mail);
}
async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const [settings, email] = await Promise.all([
      api("/system/settings"),
      api("/system/email"),
    ]);
    Object.assign(site, settings);
    applyMail(email);
  } catch (error) {
    loadError.value = error.message;
  } finally {
    loading.value = false;
  }
}
async function saveSite() {
  if (siteBusy.value) return;
  siteBusy.value = true;
  siteError.value = "";
  try {
    await api("/system/settings", {
      method: "PUT",
      body: {
        siteName: site.siteName.trim(),
        registrationMode: site.registrationMode,
        emailVerificationRequired: site.emailVerificationRequired,
      },
    });
    notify("系统设置已保存");
    await Promise.all([initSession(), refreshSystemOptions()]);
  } catch (error) {
    siteError.value = error.message;
  } finally {
    siteBusy.value = false;
  }
}
async function saveMail() {
  if (mailBusy.value || testBusy.value) return;
  mailBusy.value = true;
  mailError.value = "";
  testSuccess.value = "";
  try {
    const result = await api("/system/email", {
      method: "PUT",
      body: {
        ...mail,
        host: mail.host.trim(),
        fromEmail: mail.fromEmail.trim(),
        fromName: mail.fromName.trim(),
        username: mail.username.trim(),
      },
    });
    applyMail(result);
    notify("邮件发送配置已保存");
  } catch (error) {
    mailError.value = error.message;
  } finally {
    mailBusy.value = false;
  }
}
async function sendTest() {
  if (testBusy.value || mailBusy.value || !mailReady.value) return;
  testBusy.value = true;
  testError.value = "";
  testSuccess.value = "";
  try {
    await api("/system/email/test", {
      method: "POST",
      body: { to: recipient.value.trim() },
    });
    testSuccess.value = "测试邮件已提交发送，请检查收件箱和垃圾邮件。";
  } catch (error) {
    testError.value = error.message;
  } finally {
    testBusy.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="system-page">
    <div class="page-title-row">
      <div>
        <h1>系统设置</h1>
        <p>统一管理注册方式与邮件服务，让团队安心协作。</p>
      </div>
      <span class="system-admin-label"
        ><ShieldCheck :size="14" />系统管理员</span
      >
    </div>
    <div v-if="loading" class="system-loading" role="status">
      <Loader2 class="spin" :size="22" />正在读取系统配置…
    </div>
    <div v-else-if="loadError" class="error-box" role="alert">
      {{ loadError }}
      <button type="button" class="link-btn" @click="load">重新加载</button>
    </div>
    <div v-else class="system-sections">
      <form class="system-card" @submit.prevent="saveSite">
        <header>
          <span class="system-icon lilac"><Settings2 :size="22" /></span>
          <div>
            <h2>系统与注册</h2>
            <p>这些设置对所有账本和用户生效。</p>
          </div>
        </header>
        <label class="field site-name"
          ><span>系统名称</span
          ><input
            v-model="site.siteName"
            required
            maxlength="60"
            placeholder="例如：山海工作室"
            :disabled="siteBusy"
        /></label>
        <fieldset class="mode-fieldset" :disabled="siteBusy">
          <legend>新用户注册方式</legend>
          <div class="registration-modes">
            <label
              v-for="item in modes"
              :key="item.value"
              class="registration-mode"
              :class="{ selected: site.registrationMode === item.value }"
              ><input
                v-model="site.registrationMode"
                type="radio"
                name="registrationMode"
                :value="item.value" /><component
                :is="item.icon"
                :size="19" /><strong>{{ item.title }}</strong
              ><small>{{ item.text }}</small
              ><Check
                v-if="site.registrationMode === item.value"
                class="selected-check"
                :size="14"
            /></label>
          </div>
        </fieldset>
        <label class="system-toggle"
          ><span
            ><strong>注册时必须验证邮箱</strong
            ><small>新账号需通过邮箱验证码验证；已有账号不受影响。</small></span
          ><input
            v-model="site.emailVerificationRequired"
            type="checkbox"
            :disabled="siteBusy"
        /></label>
        <p
          v-if="site.emailVerificationRequired && !mailReady"
          class="system-note amber"
        >
          请先启用并保存邮件服务，再开启邮箱验证。
        </p>
        <p v-else class="system-note">
          未强制验证时，新用户可以先不填写邮箱；填写的邮箱仍需验证码验证。
        </p>
        <div v-if="siteError" class="error-box" role="alert">
          {{ siteError }}
        </div>
        <footer>
          <span>已有账号与账本权限保持不变</span
          ><button class="btn btn-primary" :disabled="siteBusy">
            <Loader2 v-if="siteBusy" class="spin" :size="15" />{{
              siteBusy ? "保存中…" : "保存系统设置"
            }}
          </button>
        </footer>
      </form>

      <section class="system-card">
        <header>
          <span class="system-icon mint"><Mail :size="22" /></span>
          <div>
            <h2>邮件发送服务</h2>
            <p>为注册验证、邮箱绑定和密码找回提供邮件支持。</p>
          </div>
          <span class="mail-status" :class="{ enabled: mailReady }">{{
            mailDirty ? "有未保存的修改" : mailReady ? "已启用" : "未启用"
          }}</span>
        </header>
        <form @submit.prevent="saveMail">
          <label class="system-toggle first-toggle"
            ><span
              ><strong>启用 SMTP 邮件服务</strong
              ><small>使用你的邮箱服务商提供的服务器和授权码。</small></span
            ><input
              v-model="mail.enabled"
              type="checkbox"
              :disabled="mailBusy || testBusy"
          /></label>
          <fieldset class="mail-fields" :disabled="mailBusy || testBusy">
            <div class="system-form-grid">
              <label class="field"
                ><span>SMTP 服务器</span
                ><input
                  v-model="mail.host"
                  :required="mail.enabled"
                  maxlength="253"
                  placeholder="smtp.example.com"
                  autocomplete="off"
              /></label>
              <div class="mail-port-security">
                <label class="field"
                  ><span>端口</span
                  ><input
                    v-model.number="mail.port"
                    type="number"
                    min="1"
                    max="65535"
                    required /></label
                ><label class="field"
                  ><span>连接安全</span
                  ><select v-model="mail.security">
                    <option value="starttls">STARTTLS</option>
                    <option value="ssl">SSL / TLS</option>
                    <option value="none">无加密</option>
                  </select></label
                >
              </div>
              <label class="field"
                ><span>SMTP 登录账号</span
                ><input
                  v-model="mail.username"
                  maxlength="254"
                  placeholder="邮箱地址或服务商指定账号"
                  autocomplete="off"
              /></label>
              <div class="field">
                <label for="smtp-password"
                  >密码或邮箱授权码
                  <small>{{
                    passwordConfigured ? "已配置" : "未配置"
                  }}</small></label
                ><input
                  id="smtp-password"
                  v-model="mail.password"
                  type="password"
                  maxlength="1024"
                  :disabled="mail.clearPassword"
                  :placeholder="
                    passwordConfigured
                      ? '留空保留已保存的授权码'
                      : '输入邮箱服务商提供的授权码'
                  "
                  autocomplete="new-password"
                /><label v-if="passwordConfigured" class="clear-password"
                  ><input
                    v-model="mail.clearPassword"
                    type="checkbox"
                    @change="mail.password = ''"
                  />清除已保存的授权码</label
                >
              </div>
              <label class="field"
                ><span>发件人邮箱</span
                ><input
                  v-model="mail.fromEmail"
                  type="email"
                  :required="mail.enabled"
                  maxlength="254"
                  placeholder="accounts@example.com"
                  autocomplete="off"
              /></label>
              <label class="field"
                ><span>发件人名称</span
                ><input
                  v-model="mail.fromName"
                  maxlength="80"
                  placeholder="例如：山海工作室"
              /></label>
            </div>
          </fieldset>
          <p v-if="mail.security === 'none'" class="system-note amber">
            无加密连接适用于本机邮件服务；连接外部邮箱建议选择 STARTTLS 或 SSL /
            TLS。
          </p>
          <div v-if="mailError" class="error-box" role="alert">
            {{ mailError }}
          </div>
          <footer>
            <span>授权码只在更新时输入，保存后不会回显。</span
            ><button class="btn btn-primary" :disabled="mailBusy || testBusy">
              <Loader2 v-if="mailBusy" class="spin" :size="15" />{{
                mailBusy ? "保存中…" : "保存邮件配置"
              }}
            </button>
          </footer>
        </form>
        <form class="mail-test" @submit.prevent="sendTest">
          <div>
            <h3>发送测试邮件</h3>
            <p>
              {{
                mailDirty
                  ? "请先保存邮件配置，再发送测试。"
                  : "使用已保存的配置，向下方地址发送一封测试邮件。"
              }}
            </p>
          </div>
          <label class="field"
            ><span>测试收件邮箱</span
            ><input
              v-model="recipient"
              type="email"
              required
              maxlength="254"
              placeholder="输入你能查收的邮箱"
              :disabled="testBusy || !mailReady"
              autocomplete="off"
          /></label>
          <button
            class="btn btn-secondary"
            :disabled="testBusy || mailBusy || !mailReady"
          >
            <Loader2 v-if="testBusy" class="spin" :size="15" /><Send
              v-else
              :size="15"
            />{{ testBusy ? "发送中…" : "发送测试邮件" }}
          </button>
          <div v-if="testError" class="error-box test-result" role="alert">
            {{ testError }}
          </div>
          <p v-if="testSuccess" class="test-success test-result" role="status">
            <Check :size="15" />{{ testSuccess }}
          </p>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.system-page {
  max-width: 1100px;
  margin: 0 auto;
}
.page-title-row {
  display: flex;
  gap: 16px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 26px;
}
.page-title-row h1 {
  font-size: 27px;
  letter-spacing: -0.6px;
  margin: 0 0 9px;
}
.page-title-row p {
  color: #858196;
  font-size: 12px;
  line-height: 1.7;
  margin: 0;
}
.system-admin-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  color: #7966af;
  background: #eeebfa;
  border-radius: 8px;
  font-size: 11px;
  padding: 9px 11px;
}
.system-sections {
  display: grid;
  gap: 22px;
}
.system-card {
  padding: 27px 30px 0;
  border: 1px solid #ebe9f2;
  border-radius: 17px;
  background: #fff;
  min-width: 0;
}
.system-card > header {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 27px;
}
.system-icon {
  display: grid;
  place-items: center;
  width: 43px;
  height: 43px;
  border-radius: 13px;
  flex-shrink: 0;
}
.lilac {
  color: #8571c3;
  background: #f0ecfb;
}
.mint {
  color: #60947c;
  background: #eaf5ee;
}
.system-card h2 {
  font-size: 16px;
  margin: 0 0 5px;
}
.system-card header p {
  font-size: 11px;
  line-height: 1.7;
  color: #92909e;
  margin: 0;
}
.site-name {
  max-width: 480px;
}
.mode-fieldset,
.mail-fields {
  margin: 0;
  padding: 0;
  border: 0;
  min-width: 0;
}
.mode-fieldset legend {
  color: #606d80;
  font-size: 12px;
  font-weight: 550;
  margin-bottom: 10px;
}
.registration-modes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.registration-mode {
  position: relative;
  padding: 18px;
  border: 1px solid #eae7f0;
  border-radius: 12px;
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 10px 7px;
  cursor: pointer;
  color: #9990a8;
}
.registration-mode > input {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
}
.registration-mode:has(input:focus-visible) {
  outline: 2px solid #8b73de;
  outline-offset: 3px;
}
.registration-mode strong {
  font-size: 13px;
  color: #665c77;
  font-weight: 550;
}
.registration-mode small {
  grid-column: 1 / -1;
  font-size: 11px;
  line-height: 1.75;
  color: #8d849a;
}
.registration-mode.selected {
  border-color: #aa98e0;
  background: #f7f4fe;
  color: #8b74c5;
}
.selected-check {
  position: absolute;
  right: 9px;
  top: 8px;
}
.system-toggle {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 23px 0 0;
}
.system-toggle strong {
  display: block;
  font-size: 12px;
  font-weight: 550;
  margin-bottom: 7px;
}
.system-toggle small {
  display: block;
  font-size: 11px;
  line-height: 1.75;
  color: #92909f;
}
.system-toggle > input {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}
.first-toggle {
  border-top: 1px solid #f0edf5;
  padding-top: 20px;
  margin-bottom: 24px;
}
.system-note {
  font-size: 11px;
  color: #93909f;
  line-height: 1.75;
  padding: 12px 14px;
  background: #f8f7fb;
  border-radius: 9px;
  margin: 18px 0 22px;
}
.amber {
  background: #fff8e9;
  color: #9d8050;
}
.system-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 22px;
  padding: 19px 0;
  border-top: 1px solid #efedf4;
}
.system-card footer > span {
  font-size: 11px;
  color: #9892a5;
  line-height: 1.6;
}
.system-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 23px;
}
.system-form-grid > * {
  min-width: 0;
}
.mail-port-security {
  display: grid;
  grid-template-columns: 0.7fr 1fr;
  gap: 12px;
}
.field input,
.field select {
  width: 100%;
  min-width: 0;
}
.field > span > small {
  margin-left: 5px;
  font-size: 10px;
  font-weight: 400;
  color: #9c91b3;
}
.clear-password {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 10px;
  color: #9b8eac;
}
.clear-password input {
  width: 13px;
  height: 13px;
  margin: 0;
}
.mail-status {
  margin-left: auto;
  font-size: 10px;
  color: #9b91ac;
  background: #f5f2f9;
  padding: 6px 9px;
  border-radius: 6px;
  white-space: nowrap;
}
.mail-status.enabled {
  color: #64977d;
  background: #edf7f0;
}
.mail-test {
  display: grid;
  align-items: end;
  grid-template-columns: 1fr 1fr auto;
  gap: 18px;
  margin: 0 -30px;
  padding: 24px 30px;
  background: #faf9fd;
  border-top: 1px solid #efedf5;
  border-radius: 0 0 17px 17px;
}
.mail-test h3 {
  font-size: 13px;
  margin: 0 0 7px;
}
.mail-test p {
  color: #948c9f;
  font-size: 11px;
  line-height: 1.7;
  margin: 0;
}
.mail-test .field {
  margin: 0;
}
.test-result {
  grid-column: 1 / -1;
}
.mail-test .test-success {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #5b9475;
}
.system-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 75px 20px;
  color: #93869f;
  font-size: 13px;
}
.spin {
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 950px) {
  .mail-test {
    grid-template-columns: 1fr auto;
  }
  .mail-test > div:first-child {
    grid-column: 1 / -1;
  }
}
@media (max-width: 620px) {
  .page-title-row {
    align-items: flex-start;
  }
  .page-title-row h1 {
    font-size: 23px;
  }
  .system-admin-label {
    font-size: 10px;
    padding: 7px;
  }
  .system-card {
    padding: 21px 18px 0;
  }
  .registration-modes {
    grid-template-columns: 1fr;
    gap: 9px;
  }
  .registration-mode {
    padding: 13px 15px;
    gap: 6px 7px;
  }
  .registration-mode small {
    grid-column: 2;
  }
  .system-form-grid {
    grid-template-columns: 1fr;
  }
  .system-card > header {
    flex-wrap: wrap;
    gap: 10px;
  }
  .mail-status {
    margin-left: 53px;
  }
  .system-card footer {
    flex-wrap: wrap;
  }
  .system-card footer > span {
    width: 100%;
  }
  .mail-test {
    margin: 0 -18px;
    padding: 20px 18px;
    grid-template-columns: 1fr;
    gap: 13px;
  }
  .mail-test > .btn {
    justify-self: start;
  }
}
</style>
