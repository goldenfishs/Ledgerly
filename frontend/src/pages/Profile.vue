<script setup>
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  useId,
} from "vue";
import {
  Camera,
  Check,
  KeyRound,
  Mail,
  ShieldCheck,
  UserRound,
  Upload,
  RotateCcw,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { notify, state } from "../lib/app";

const profile = ref(null);
const loading = ref(true);
const failure = ref("");
const busy = ref("");
const avatarInput = ref(null);
const avatarFailed = ref(false);
const errors = reactive({ details: "", password: "", email: "", avatar: "" });
const details = reactive({ username: "", name: "", currentPassword: "" });
const passwords = reactive({
  currentPassword: "",
  newPassword: "",
  confirmation: "",
});
const emailForm = reactive({ email: "", code: "", currentPassword: "" });
const emailCodeId = useId();
const countdown = ref(0);
let countdownTimer;
const usernameChanged = computed(
  () => details.username.trim().toLowerCase() !== profile.value?.username,
);
const dirty = computed(
  () => usernameChanged.value || details.name.trim() !== profile.value?.name,
);
const initial = computed(() => (profile.value?.name || "我").slice(0, 1));
const createdDate = computed(() => {
  if (!profile.value?.createdAt) return "";
  return new Date(profile.value.createdAt).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
});
function applyProfile(value) {
  profile.value = value;
  details.username = value.username;
  details.name = value.name;
  // The personal API carries a global role; preserve the current ledger's role.
  if (state.user?.id === value.id)
    Object.assign(state.user, {
      username: value.username,
      name: value.name,
      avatarUrl: value.avatarUrl,
    });
}
async function load() {
  loading.value = true;
  failure.value = "";
  try {
    applyProfile(await api("/profile"));
    emailForm.email = profile.value.email || "";
  } catch (error) {
    if (error.name !== "AbortError") failure.value = error.message;
  } finally {
    loading.value = false;
  }
}
async function saveDetails() {
  if (busy.value || !dirty.value) return;
  errors.details = "";
  busy.value = "details";
  try {
    applyProfile(
      await api("/profile", {
        method: "PUT",
        body: {
          username: details.username.trim(),
          name: details.name.trim(),
          ...(usernameChanged.value
            ? { currentPassword: details.currentPassword }
            : {}),
        },
      }),
    );
    details.currentPassword = "";
    notify("个人资料已保存");
  } catch (error) {
    if (error.name !== "AbortError") errors.details = error.message;
  } finally {
    busy.value = "";
  }
}
async function changePassword() {
  if (busy.value) return;
  errors.password = "";
  if (passwords.newPassword !== passwords.confirmation) {
    errors.password = "两次输入的新密码不一致";
    return;
  }
  busy.value = "password";
  try {
    await api("/profile/password", {
      method: "POST",
      body: {
        currentPassword: passwords.currentPassword,
        newPassword: passwords.newPassword,
      },
    });
    Object.assign(passwords, {
      currentPassword: "",
      newPassword: "",
      confirmation: "",
    });
    details.currentPassword = "";
    emailForm.currentPassword = "";
    notify("密码已更新，其他设备已退出登录");
  } catch (error) {
    if (error.name !== "AbortError") errors.password = error.message;
  } finally {
    busy.value = "";
  }
}
function applyAvatar(value) {
  profile.value.avatarUrl = value.avatarUrl;
  avatarFailed.value = false;
  if (state.user?.id === profile.value.id)
    state.user.avatarUrl = value.avatarUrl;
}
async function uploadAvatar(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || busy.value) return;
  errors.avatar = "";
  if (file.size > 2 * 1024 * 1024) {
    errors.avatar = "头像文件不能超过 2 MB";
    return;
  }
  busy.value = "avatar";
  try {
    const body = new FormData();
    body.append("file", file);
    applyAvatar(await api("/profile/avatar", { method: "POST", body }));
    notify("头像已更新");
  } catch (error) {
    if (error.name !== "AbortError") errors.avatar = error.message;
  } finally {
    busy.value = "";
  }
}
async function resetAvatar() {
  if (busy.value) return;
  errors.avatar = "";
  busy.value = "avatar";
  try {
    applyAvatar(await api("/profile/avatar", { method: "DELETE" }));
    notify("已恢复默认头像");
  } catch (error) {
    if (error.name !== "AbortError") errors.avatar = error.message;
  } finally {
    busy.value = "";
  }
}
async function sendCode() {
  if (busy.value || countdown.value) return;
  errors.email = "";
  if (!emailForm.email.trim() || !emailForm.currentPassword) {
    errors.email = "请先填写邮箱和当前密码";
    return;
  }
  busy.value = "code";
  try {
    const result = await api("/profile/email/code", {
      method: "POST",
      body: {
        email: emailForm.email.trim(),
        currentPassword: emailForm.currentPassword,
      },
    });
    countdown.value = result.retryAfter || 60;
    clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
      countdown.value = Math.max(0, countdown.value - 1);
      if (!countdown.value) clearInterval(countdownTimer);
    }, 1000);
    notify("验证码已发送，请查看邮箱");
  } catch (error) {
    if (error.name !== "AbortError") errors.email = error.message;
  } finally {
    busy.value = "";
  }
}
async function bindEmail() {
  if (busy.value) return;
  errors.email = "";
  busy.value = "email";
  try {
    applyProfile(
      await api("/profile/email", {
        method: "PUT",
        body: {
          email: emailForm.email.trim(),
          code: emailForm.code.trim(),
          currentPassword: emailForm.currentPassword,
        },
      }),
    );
    emailForm.email = profile.value.email;
    emailForm.code = "";
    emailForm.currentPassword = "";
    notify("邮箱已验证并绑定");
  } catch (error) {
    if (error.name !== "AbortError") errors.email = error.message;
  } finally {
    busy.value = "";
  }
}
onMounted(load);
onBeforeUnmount(() => clearInterval(countdownTimer));
</script>

<template>
  <div class="profile-page">
    <div class="page-heading">
      <div>
        <h1>个人中心</h1>
        <p>管理你的个人资料、登录安全和联系邮箱。</p>
      </div>
    </div>
    <div v-if="loading" class="profile-empty" role="status">
      正在读取个人资料…
    </div>
    <div v-else-if="failure" class="profile-empty" role="alert">
      <p>{{ failure }}</p>
      <button class="btn" @click="load">重新加载</button>
    </div>
    <template v-else-if="profile">
      <section class="profile-hero">
        <div class="profile-avatar-wrap">
          <div class="profile-avatar">
            <img
              v-if="profile.avatarUrl && !avatarFailed"
              :src="profile.avatarUrl"
              alt="我的头像"
              @error="avatarFailed = true"
            /><span v-else>{{ initial }}</span>
          </div>
          <button
            class="profile-camera"
            aria-label="更换头像"
            :disabled="Boolean(busy)"
            @click="avatarInput?.click()"
          >
            <Camera :size="15" />
          </button>
        </div>
        <div class="profile-identity">
          <div class="profile-name">
            <h2>{{ profile.name }}</h2>
            <span class="profile-role">{{
              profile.globalRole === "admin" ? "系统管理员" : "工作室成员"
            }}</span>
          </div>
          <p>@{{ profile.username }}</p>
          <small v-if="createdDate">{{ createdDate }}加入</small>
        </div>
        <div class="profile-avatar-actions">
          <button
            class="btn"
            :disabled="Boolean(busy)"
            @click="avatarInput?.click()"
          >
            <Upload :size="15" />{{
              busy === "avatar" ? "处理中…" : "上传头像"
            }}</button
          ><button
            v-if="profile.avatarUrl"
            class="profile-text-button"
            :disabled="Boolean(busy)"
            @click="resetAvatar"
          >
            <RotateCcw :size="13" />恢复默认</button
          ><small>JPG、PNG、WebP · 2 MB 以内</small>
        </div>
        <input
          ref="avatarInput"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          hidden
          aria-label="选择头像文件"
          @change="uploadAvatar"
        />
        <p
          v-if="errors.avatar"
          class="profile-error profile-avatar-error"
          role="alert"
        >
          {{ errors.avatar }}
        </p>
      </section>
      <div class="profile-grid">
        <section class="profile-card">
          <header>
            <span class="profile-section-icon lavender"
              ><UserRound :size="19"
            /></span>
            <div>
              <h2>基本资料</h2>
              <p>让协作伙伴更容易认出你</p>
            </div>
          </header>
          <form autocomplete="off" @submit.prevent="saveDetails">
            <label class="field"
              ><span>显示名称</span
              ><input
                v-model="details.name"
                maxlength="80"
                required
                placeholder="你希望大家如何称呼你"
                :disabled="Boolean(busy)"
            /></label>
            <label class="field"
              ><span>登录账号</span
              ><input
                v-model="details.username"
                minlength="3"
                maxlength="40"
                pattern="[A-Za-z0-9_.\-]{3,40}"
                required
                autocomplete="off"
                spellcheck="false"
                :disabled="Boolean(busy)"
              /><small>3–40 位字母、数字、点、下划线或短横线</small></label
            >
            <label v-if="usernameChanged" class="field"
              ><span>当前密码（确认修改账号）</span
              ><input
                v-model="details.currentPassword"
                type="password"
                autocomplete="off"
                maxlength="256"
                required
                :disabled="Boolean(busy)"
              /><small
                >修改后，请使用新账号登录；已有账本和数据保留。</small
              ></label
            >
            <p v-if="errors.details" class="profile-error" role="alert">
              {{ errors.details }}
            </p>
            <div class="profile-form-footer">
              <button class="btn primary" :disabled="Boolean(busy) || !dirty">
                <Check :size="15" />{{
                  busy === "details" ? "保存中…" : "保存资料"
                }}
              </button>
            </div>
          </form>
        </section>
        <section class="profile-card">
          <header>
            <span class="profile-section-icon mint"
              ><KeyRound :size="19"
            /></span>
            <div>
              <h2>登录密码</h2>
              <p>定期更新密码，保护你的账号</p>
            </div>
          </header>
          <form autocomplete="off" @submit.prevent="changePassword">
            <label class="field"
              ><span>当前密码</span
              ><input
                v-model="passwords.currentPassword"
                type="password"
                autocomplete="off"
                required
                maxlength="256"
                placeholder="输入正在使用的密码"
                :disabled="Boolean(busy)"
            /></label>
            <div class="profile-password-pair">
              <label class="field"
                ><span>新密码</span
                ><input
                  v-model="passwords.newPassword"
                  type="password"
                  autocomplete="new-password"
                  required
                  minlength="8"
                  maxlength="256"
                  placeholder="至少 8 位"
                  :disabled="Boolean(busy)" /></label
              ><label class="field"
                ><span>确认新密码</span
                ><input
                  v-model="passwords.confirmation"
                  type="password"
                  autocomplete="new-password"
                  required
                  minlength="8"
                  maxlength="256"
                  placeholder="再次输入新密码"
                  :disabled="Boolean(busy)"
              /></label>
            </div>
            <p class="profile-security-note">
              <ShieldCheck
                :size="15"
              />更新后，其他设备会退出登录，当前设备保持登录。
            </p>
            <p v-if="errors.password" class="profile-error" role="alert">
              {{ errors.password }}
            </p>
            <div class="profile-form-footer">
              <button class="btn" :disabled="Boolean(busy)">
                {{ busy === "password" ? "更新中…" : "更新密码" }}
              </button>
            </div>
          </form>
        </section>
        <section class="profile-card profile-email-card">
          <header>
            <span class="profile-section-icon peach"><Mail :size="19" /></span>
            <div>
              <h2>联系邮箱</h2>
              <p>验证邮箱后，可用于登录和找回密码</p>
            </div>
            <span v-if="profile.emailVerified" class="profile-verified"
              ><Check :size="13" />已验证</span
            >
          </header>
          <div v-if="profile.email" class="profile-email-current">
            <span>当前邮箱</span><strong>{{ profile.email }}</strong
            ><span v-if="!profile.emailVerified" class="profile-unverified"
              >待验证</span
            >
          </div>
          <div
            v-if="!profile.emailVerificationAvailable"
            class="profile-email-unavailable"
          >
            <Mail :size="19" />
            <div>
              <strong>邮箱验证暂未开启</strong>
              <p>
                管理员配置邮件发送服务后，你就可以绑定或更换邮箱。个人资料、头像和密码仍可正常修改。
              </p>
            </div>
          </div>
          <form v-else autocomplete="off" @submit.prevent="bindEmail">
            <div class="profile-email-fields">
              <label class="field"
                ><span>{{ profile.email ? "绑定新邮箱" : "邮箱地址" }}</span
                ><input
                  v-model="emailForm.email"
                  type="email"
                  autocomplete="off"
                  required
                  maxlength="254"
                  placeholder="name@company.com"
                  :disabled="Boolean(busy)"
                  @input="emailForm.code = ''" /></label
              ><label class="field"
                ><span>当前密码（验证身份）</span
                ><input
                  v-model="emailForm.currentPassword"
                  type="password"
                  autocomplete="off"
                  required
                  maxlength="256"
                  placeholder="输入当前密码"
                  :disabled="Boolean(busy)"
              /></label>
              <div class="field">
                <label :for="emailCodeId">邮箱验证码</label>
                <div class="profile-code-row">
                  <input
                    :id="emailCodeId"
                    v-model="emailForm.code"
                    type="text"
                    inputmode="numeric"
                    pattern="[0-9]{6}"
                    autocomplete="one-time-code"
                    required
                    maxlength="6"
                    placeholder="6 位验证码"
                    :disabled="Boolean(busy)"
                  /><button
                    type="button"
                    class="btn"
                    :disabled="
                      Boolean(busy) ||
                      countdown > 0 ||
                      !emailForm.email.trim() ||
                      !emailForm.currentPassword
                    "
                    @click="sendCode"
                  >
                    {{
                      busy === "code"
                        ? "发送中…"
                        : countdown
                          ? `${countdown} 秒后重发`
                          : "发送验证码"
                    }}
                  </button>
                </div>
              </div>
            </div>
            <p v-if="errors.email" class="profile-error" role="alert">
              {{ errors.email }}
            </p>
            <div class="profile-form-footer">
              <small>验证码 10 分钟内有效，更换邮箱前需验证当前密码。</small
              ><button class="btn" :disabled="Boolean(busy)">
                {{ busy === "email" ? "验证中…" : "验证并绑定" }}
              </button>
            </div>
          </form>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.profile-page {
  max-width: 1180px;
  margin: 0 auto;
}
.page-heading {
  margin-bottom: 24px;
}
.page-heading h1 {
  margin: 0 0 8px;
  font-size: 27px;
}
.page-heading p {
  color: #9290a1;
  margin: 0;
  font-size: 13px;
}
.profile-hero {
  position: relative;
  display: flex;
  gap: 22px;
  align-items: center;
  padding: 27px 30px;
  margin-bottom: 24px;
  border: 1px solid #eae7f4;
  border-radius: 18px;
  background: linear-gradient(112deg, #f0ebfd 0%, #faf8ff 48%, #fff 100%);
}
.profile-avatar-wrap {
  position: relative;
  flex-shrink: 0;
}
.profile-avatar {
  width: 80px;
  height: 80px;
  overflow: hidden;
  border-radius: 25px;
  background: #ded5f8;
  border: 3px solid white;
  display: grid;
  place-items: center;
  color: #7760b4;
  font-size: 29px;
  font-weight: 600;
}
.profile-avatar img {
  height: 100%;
  width: 100%;
  object-fit: cover;
}
.profile-camera {
  position: absolute;
  right: -3px;
  bottom: -2px;
  width: 28px;
  height: 28px;
  padding: 0;
  display: grid;
  place-items: center;
  background: white;
  border: 1px solid #e6e0f2;
  color: #8068bd;
  border-radius: 10px;
  cursor: pointer;
}
.profile-identity {
  min-width: 0;
  flex: 1;
}
.profile-name {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.profile-name h2 {
  font-size: 21px;
  margin: 0;
  color: #464058;
  overflow-wrap: anywhere;
}
.profile-role {
  color: #8b76b7;
  background: #ebe5f9;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 10px;
  white-space: nowrap;
}
.profile-identity p {
  margin: 6px 0;
  color: #8d839f;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.profile-identity small {
  color: #a198b0;
  font-size: 11px;
}
.profile-avatar-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
}
.profile-avatar-actions small {
  font-size: 10px;
  color: #a198b0;
}
.profile-text-button {
  background: none;
  border: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #8d839f;
  cursor: pointer;
}
.profile-avatar-error {
  flex-basis: 100%;
}
.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.profile-card {
  background: #fff;
  border: 1px solid #eae8f1;
  border-radius: 18px;
  padding: 26px;
  min-width: 0;
}
.profile-card header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 26px;
}
.profile-section-icon {
  display: grid;
  place-items: center;
  width: 39px;
  height: 39px;
  border-radius: 12px;
  flex-shrink: 0;
}
.lavender {
  background: #f0eafa;
  color: #977bbb;
}
.mint {
  background: #e9f5ef;
  color: #7da990;
}
.peach {
  background: #fff0e6;
  color: #c28e6f;
}
.profile-card header h2 {
  font-size: 15px;
  margin: 0 0 5px;
  color: #4e485e;
}
.profile-card header p {
  font-size: 11px;
  color: #a19aaa;
  margin: 0;
}
.profile-card form {
  display: flex;
  flex-direction: column;
  gap: 19px;
}
.profile-card .field {
  margin: 0;
  min-width: 0;
}
.profile-card .field > span,
.profile-card .field > label {
  font-size: 12px;
  color: #736b82;
}
.profile-card .field input {
  width: 100%;
  min-width: 0;
  background: #fdfcfe;
  font-size: 12px;
  height: 41px;
  border: 1px solid #e7e2ed;
}
.profile-card .field small {
  color: #a39baa;
  font-size: 10px;
  line-height: 1.7;
}
.profile-password-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 13px;
}
.profile-security-note {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  color: #95a49b;
  background: #f3f8f5;
  padding: 11px 12px;
  border-radius: 9px;
  font-size: 11px;
  line-height: 1.8;
  margin: 0;
}
.profile-security-note svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.profile-form-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  align-items: center;
  margin-top: 3px;
}
.profile-form-footer small {
  margin-right: auto;
  color: #a198ac;
  font-size: 11px;
  line-height: 1.7;
}
.profile-error {
  color: #b45164;
  background: #fcf0f3;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.7;
  margin: 0;
}
.profile-email-card {
  grid-column: 1 / -1;
}
.profile-verified {
  margin-left: auto;
  color: #6a967f;
  background: #edf7f1;
  padding: 5px 9px;
  border-radius: 7px;
  display: flex;
  gap: 4px;
  align-items: center;
  font-size: 11px;
}
.profile-email-current {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  margin: -2px 0 20px;
  align-items: center;
}
.profile-email-current > span {
  color: #a198ac;
}
.profile-email-current strong {
  color: #655d75;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.profile-email-current .profile-unverified {
  color: #bd9567;
  font-size: 10px;
}
.profile-email-unavailable {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  background: #faf8fd;
  padding: 17px 19px;
  border-radius: 11px;
  color: #a59abb;
}
.profile-email-unavailable > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.profile-email-unavailable strong {
  font-size: 12px;
  color: #82738f;
  font-weight: 500;
}
.profile-email-unavailable p {
  font-size: 11px;
  line-height: 1.8;
  margin: 6px 0 0;
  color: #a399ad;
}
.profile-email-fields {
  display: grid;
  grid-template-columns: 1fr 1fr 1.3fr;
  gap: 16px;
}
.profile-code-row {
  display: flex;
  gap: 8px;
}
.profile-code-row input {
  flex: 1;
}
.profile-code-row .btn {
  white-space: nowrap;
  font-size: 11px;
  padding: 0 12px;
}
.profile-empty {
  padding: 60px 20px;
  text-align: center;
  color: #9a90aa;
}
.profile-card .btn,
.profile-hero .btn {
  font-size: 12px;
  min-height: 36px;
  white-space: nowrap;
}
@media (max-width: 1120px) {
  .profile-email-fields {
    grid-template-columns: 1fr 1fr;
  }
  .profile-email-fields > :last-child {
    grid-column: 1 / -1;
  }
  .profile-code-row {
    max-width: 400px;
  }
  .profile-password-pair {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 820px) {
  .profile-grid {
    grid-template-columns: 1fr;
    gap: 18px;
  }
  .profile-hero {
    padding: 23px;
    flex-wrap: wrap;
  }
  .profile-avatar-actions {
    width: 100%;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: flex-start;
  }
  .profile-card {
    padding: 23px;
  }
  .profile-password-pair {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 520px) {
  .profile-hero {
    gap: 17px;
    padding: 22px 19px;
  }
  .profile-avatar {
    width: 64px;
    height: 64px;
    border-radius: 21px;
    font-size: 24px;
  }
  .profile-name h2 {
    font-size: 19px;
  }
  .profile-card {
    padding: 21px 18px;
  }
  .profile-password-pair,
  .profile-email-fields {
    grid-template-columns: 1fr;
  }
  .profile-email-fields > :last-child {
    grid-column: auto;
  }
  .profile-form-footer {
    flex-wrap: wrap;
  }
  .profile-form-footer small {
    width: 100%;
  }
  .profile-role {
    font-size: 9px;
  }
  .profile-avatar-actions small {
    width: 100%;
  }
  .profile-card header {
    gap: 9px;
  }
  .profile-verified {
    padding: 4px 6px;
    font-size: 10px;
  }
}
</style>
