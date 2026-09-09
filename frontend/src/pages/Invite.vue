<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCheck,
  CircleAlert,
  Clock3,
  Eye,
  EyeOff,
  HeartHandshake,
  Loader2,
  LogIn,
  ShieldCheck,
  UserRound,
  Users,
} from "lucide-vue-next";
import { api } from "../lib/api.js";
import {
  initSession,
  notify,
  refreshLedgers,
  selectLedger,
  state,
} from "../lib/app.js";
import { dateTime } from "../lib/format.js";
import EmailCodeField from "../components/EmailCodeField.vue";

const route = useRoute(),
  router = useRouter();
const invitation = ref(null),
  loading = ref(true),
  loadError = ref(""),
  missing = ref(false),
  busy = ref(false),
  error = ref(""),
  mode = ref("choice"),
  joined = ref(null),
  showPassword = ref(false),
  registrationOptions = ref(null),
  registrationError = ref("");
const now = ref(Date.now());
const form = reactive({
  name: "",
  username: "",
  password: "",
  confirmPassword: "",
  email: "",
  emailCode: "",
});
const canRegister = computed(
  () =>
    registrationOptions.value &&
    registrationOptions.value.registrationMode !== "closed",
);
const requiresCode = computed(
  () =>
    registrationOptions.value?.emailVerificationRequired || !!form.email.trim(),
);
let sequence = 0;
const token = computed(() =>
  typeof route.params.token === "string" ? route.params.token : "",
);
const invitePath = computed(() => `/invite/${encodeURIComponent(token.value)}`);
const loginDestination = computed(() => ({
  path: "/login",
  query: { redirect: invitePath.value },
}));
const inviteStatus = computed(() => {
  if (!invitation.value) return "";
  if (["accepted", "used"].includes(invitation.value.status)) return "accepted";
  if (invitation.value.status === "revoked") return "revoked";
  if (
    invitation.value.status === "expired" ||
    (invitation.value.expiresAt &&
      new Date(invitation.value.expiresAt).getTime() <= now.value)
  )
    return "expired";
  return "pending";
});
const role = computed(() =>
  (joined.value?.ledger?.role || invitation.value?.role) === "admin"
    ? "管理员"
    : "成员",
);
const unavailable = computed(() => {
  if (missing.value)
    return {
      title: "没有找到这份邀请",
      description: "链接可能不完整或已失效，请联系账本管理员重新发送邀请。",
      icon: CircleAlert,
    };
  if (inviteStatus.value === "expired")
    return {
      title: "这份邀请已经过期",
      description: "请联系邀请人生成新的链接，再回来一起记账。",
      icon: Clock3,
    };
  if (inviteStatus.value === "revoked")
    return {
      title: "这份邀请已被撤销",
      description: "原链接无法继续使用。如需加入，请联系账本管理员重新邀请。",
      icon: CircleAlert,
    };
  if (inviteStatus.value === "accepted")
    return {
      title: "这份邀请已经被接受",
      description:
        "每份邀请仅限一人使用。如果你已加入，可在自己的账本列表中继续查看。",
      icon: CheckCheck,
    };
  return null;
});

async function load() {
  const current = ++sequence;
  loading.value = true;
  loadError.value = "";
  missing.value = false;
  registrationError.value = "";
  try {
    if (!token.value) {
      missing.value = true;
      return;
    }
    const [result, authOptions] = await Promise.all([
      api(`/invitations/${encodeURIComponent(token.value)}`),
      api("/auth/options").catch((cause) => {
        if (current === sequence) registrationError.value = cause.message;
        return null;
      }),
    ]);
    if (current === sequence) {
      invitation.value = result;
      registrationOptions.value = authOptions;
    }
  } catch (cause) {
    if (current !== sequence) return;
    invitation.value = null;
    if (cause.status === 404) missing.value = true;
    else loadError.value = cause.message || "暂时无法读取邀请，请稍后重试。";
  } finally {
    if (current === sequence) loading.value = false;
  }
}
async function completeJoin(result) {
  // The invitation is consumed before session refresh. Keep this success state
  // even if a subsequent network request fails; never retry account creation.
  joined.value = result;
  form.password = "";
  form.confirmPassword = "";
  if (invitation.value) invitation.value.status = "accepted";
  try {
    await initSession();
    await refreshLedgers();
  } catch (cause) {
    error.value = `已加入成功，但账本列表暂未刷新。点击「进入账本」可以重试。${cause.message || ""}`;
  }
}
async function accept() {
  if (
    busy.value ||
    inviteStatus.value !== "pending" ||
    !state.user ||
    joined.value
  )
    return;
  busy.value = true;
  error.value = "";
  try {
    await completeJoin(
      await api(`/invitations/${encodeURIComponent(token.value)}/accept`, {
        method: "POST",
      }),
    );
  } catch (cause) {
    error.value = cause.message || "暂时无法接受邀请，请重试。";
    if (cause.status === 410 || cause.status === 404) await load();
    if (cause.status === 401) {
      await initSession();
      await router.push(loginDestination.value);
    }
  } finally {
    busy.value = false;
  }
}
async function register() {
  if (
    busy.value ||
    inviteStatus.value !== "pending" ||
    joined.value ||
    state.user ||
    !canRegister.value
  )
    return;
  error.value = "";
  if (!form.name.trim()) {
    error.value = "请填写你的称呼。";
    return;
  }
  if (!/^[a-zA-Z0-9_.-]{3,40}$/.test(form.username.trim())) {
    error.value = "账号请使用 3–40 位字母、数字、点、下划线或短横线。";
    return;
  }
  if (form.password.length < 8 || form.password.length > 256) {
    error.value = "密码长度需要为 8–256 位字符。";
    return;
  }
  if (form.password !== form.confirmPassword) {
    error.value = "两次输入的密码不一致，请重新确认。";
    return;
  }
  busy.value = true;
  try {
    const result = await api(
      `/invitations/${encodeURIComponent(token.value)}/register`,
      {
        method: "POST",
        body: {
          username: form.username.trim().toLowerCase(),
          name: form.name.trim(),
          password: form.password,
          ...(form.email.trim()
            ? { email: form.email.trim(), emailCode: form.emailCode }
            : {}),
        },
      },
    );
    await completeJoin(result);
  } catch (cause) {
    error.value = cause.message || "创建账号失败，请检查填写内容后重试。";
    if (cause.status === 410 || cause.status === 404) await load();
  } finally {
    busy.value = false;
  }
}
async function enterLedger() {
  if (busy.value || !joined.value) return;
  busy.value = true;
  error.value = "";
  try {
    await initSession();
    await refreshLedgers();
    const id = joined.value.ledgerId ?? joined.value.ledger?.id;
    if (id === null || id === undefined) {
      await router.replace("/ledgers");
      return;
    }
    await selectLedger(id);
    notify("欢迎加入，开始一起记账吧");
    await router.replace("/overview");
  } catch (cause) {
    error.value = cause.message || "暂时无法打开账本，请稍后再试。";
  } finally {
    busy.value = false;
  }
}
async function switchAccount() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api("/auth/logout", { method: "POST" });
    await initSession();
    await router.push(loginDestination.value);
  } catch (cause) {
    error.value = cause.message || "暂时无法切换账号，请重试。";
  } finally {
    busy.value = false;
  }
}
watch(
  token,
  () => {
    joined.value = null;
    invitation.value = null;
    error.value = "";
    mode.value = "choice";
    Object.assign(form, {
      name: "",
      username: "",
      password: "",
      confirmPassword: "",
      email: "",
      emailCode: "",
    });
    load();
  },
  { immediate: true },
);
const clock = setInterval(() => {
  now.value = Date.now();
}, 30000);
onBeforeUnmount(() => {
  sequence++;
  clearInterval(clock);
  form.password = "";
  form.confirmPassword = "";
});
</script>

<template>
  <main class="invitation-page">
    <header class="invitation-brand">
      <RouterLink
        :to="state.user ? '/ledgers' : '/login'"
        :title="state.siteName"
        :aria-label="state.siteName"
        ><span><BookOpen :size="21" /></span
        ><strong
          >{{ state.siteName
          }}<small v-if="state.siteName === '账序'">Ledgerly</small></strong
        ></RouterLink
      >
    </header>
    <div class="invitation-stage">
      <section
        v-if="loading"
        class="invitation-card loading-invitation"
        aria-live="polite"
      >
        <Loader2 :size="27" class="spin" />
        <p>正在打开这份邀请…</p>
      </section>
      <section v-else-if="loadError" class="invitation-card state-card">
        <div class="state-illustration peach"><CircleAlert :size="32" /></div>
        <h1>暂时无法打开邀请</h1>
        <p>{{ loadError }}</p>
        <button class="btn btn-primary" type="button" @click="load">
          重新加载
        </button>
      </section>
      <section
        v-else-if="joined"
        class="invitation-card state-card joined-card"
      >
        <div class="success-illustration">
          <CheckCheck :size="37" /><span><Check :size="12" /></span>
        </div>
        <span class="joined-label">已经加入啦</span>
        <h1>欢迎一起记账</h1>
        <p>
          你已成为「{{ joined.ledger?.name || invitation?.ledgerName }}」的{{
            role
          }}。接下来，去看看这个账本吧。
        </p>
        <div class="joined-ledger">
          <span><BookOpen :size="22" /></span>
          <div>
            <strong>{{ joined.ledger?.name || invitation?.ledgerName }}</strong
            ><small
              ><ShieldCheck v-if="role === '管理员'" :size="12" /><UserRound
                v-else
                :size="12"
              />{{ role
              }}<template v-if="joined.ledger?.memberCount">
                · {{ joined.ledger.memberCount }} 位成员</template
              ></small
            >
          </div>
        </div>
        <div v-if="error" class="error-box invite-error" role="alert">
          {{ error }}
        </div>
        <button
          class="btn btn-primary wide-button"
          type="button"
          :disabled="busy"
          @click="enterLedger"
        >
          <Loader2 v-if="busy" :size="16" class="spin" />{{
            busy ? "正在打开账本…" : "进入账本"
          }}<ArrowRight v-if="!busy" :size="16" /></button
        ><RouterLink class="quiet-link" to="/ledgers"
          >查看我的全部账本</RouterLink
        >
      </section>
      <section v-else-if="unavailable" class="invitation-card state-card">
        <div
          class="state-illustration"
          :class="inviteStatus === 'accepted' ? 'mint' : 'peach'"
        >
          <component :is="unavailable.icon" :size="32" />
        </div>
        <h1>{{ unavailable.title }}</h1>
        <p>{{ unavailable.description }}</p>
        <div v-if="invitation?.ledgerName" class="closed-invitation">
          <BookOpen :size="16" /><span>{{ invitation.ledgerName }}</span>
        </div>
        <RouterLink
          class="btn btn-secondary"
          :to="state.user ? '/ledgers' : '/login'"
          >{{ state.user ? "查看我的账本" : "返回登录" }}<ArrowRight :size="15"
        /></RouterLink>
      </section>
      <section v-else-if="invitation" class="invitation-card" :aria-busy="busy">
        <div class="invitation-art" aria-hidden="true">
          <span class="person mint"><UserRound :size="25" /></span
          ><span class="center-book"><BookOpen :size="30" /></span
          ><span class="person peach"><UserRound :size="25" /></span
          ><i><HeartHandshake :size="18" /></i>
        </div>
        <div class="invitation-heading">
          <p>{{ invitation.inviterName || "账本管理员" }} 邀请你</p>
          <h1>一起把账记清楚</h1>
          <span>加入账本，与伙伴们从容协作。</span>
        </div>
        <div class="invited-ledger">
          <span class="invited-book"><BookOpen :size="23" /></span>
          <div>
            <h2>{{ invitation.ledgerName }}</h2>
            <p>
              <ShieldCheck v-if="role === '管理员'" :size="12" /><UserRound
                v-else
                :size="12"
              />以{{ role }}身份加入
            </p>
          </div>
        </div>
        <div class="role-explanation">
          <Check :size="13" /><span>{{
            role === "管理员"
              ? "管理账本成员，查看和审核这个账本中的所有收支。"
              : "记录自己的收支和凭证，提交给管理员审核。"
          }}</span>
        </div>
        <template v-if="state.user"
          ><div class="invitation-divider"></div>
          <div class="signed-in-account">
            <span class="account-avatar">{{
              (state.user.name || state.user.username || "我").slice(0, 1)
            }}</span>
            <div>
              <span>你将使用这个账号加入</span
              ><strong
                >{{ state.user.name || state.user.username
                }}<small>@{{ state.user.username }}</small></strong
              >
            </div>
            <button type="button" :disabled="busy" @click="switchAccount">
              换个账号
            </button>
          </div>
          <div v-if="error" class="error-box invite-error" role="alert">
            {{ error }}
          </div>
          <button
            class="btn btn-primary wide-button"
            type="button"
            :disabled="busy"
            @click="accept"
          >
            <Loader2 v-if="busy" :size="16" class="spin" /><Check
              v-else
              :size="16"
            />{{ busy ? "正在加入…" : "接受邀请，加入账本" }}
          </button></template
        >
        <template v-else-if="mode === 'choice'"
          ><div class="invitation-divider"></div>
          <p class="join-instruction">登录你的账号，即可接受这份邀请。</p>
          <RouterLink class="btn btn-primary wide-button" :to="loginDestination"
            ><LogIn :size="17" />登录后加入<ArrowRight :size="16"
          /></RouterLink>
          <div v-if="canRegister" class="new-account-option">
            <span>第一次使用账序？</span
            ><button
              type="button"
              @click="
                mode = 'register';
                error = '';
              "
            >
              创建账号并加入
            </button>
          </div>
          <p v-else class="registration-policy-note">
            {{
              registrationError
                ? "暂时无法读取注册设置，请稍后刷新重试。"
                : "新用户注册暂时关闭，已有账号仍可登录并接受邀请。"
            }}
          </p></template
        >
        <form
          v-else-if="canRegister"
          class="invite-register"
          @submit.prevent="register"
        >
          <div class="register-header">
            <h2>为你创建一个账号</h2>
            <button
              type="button"
              :disabled="busy"
              @click="
                mode = 'choice';
                error = '';
              "
            >
              <ArrowLeft :size="13" />已有账号
            </button>
          </div>
          <label class="field"
            ><span>你的称呼</span
            ><input
              v-model="form.name"
              autocomplete="name"
              required
              maxlength="80"
              placeholder="伙伴们怎么称呼你？"
              :disabled="busy" /></label
          ><label class="field"
            ><span>登录账号</span
            ><input
              v-model="form.username"
              autocomplete="username"
              autocapitalize="none"
              spellcheck="false"
              required
              minlength="3"
              maxlength="40"
              pattern="[a-zA-Z0-9_.\-]{3,40}"
              placeholder="3–40 位字母、数字或 . _ -"
              :disabled="busy" /></label
          ><label class="field"
            ><span
              >邮箱
              <small v-if="!registrationOptions.emailVerificationRequired"
                >选填</small
              ></span
            ><input
              v-model.trim="form.email"
              type="email"
              maxlength="254"
              :required="registrationOptions.emailVerificationRequired"
              placeholder="用于安全验证和找回密码"
              autocomplete="email"
              :disabled="busy || !registrationOptions.emailEnabled"
            /><small v-if="!registrationOptions.emailEnabled"
              >邮件服务暂未启用，{{
                registrationOptions.emailVerificationRequired
                  ? "请联系系统管理员。"
                  : "可以先不填写邮箱。"
              }}</small
            ></label
          >
          <EmailCodeField
            v-if="requiresCode"
            v-model="form.emailCode"
            :email="form.email"
            :invitation-token="token"
            :enabled="registrationOptions.emailEnabled"
            :disabled="busy"
          />
          <label class="field"
            ><span>设置密码</span>
            <div class="invite-password">
              <input
                v-model="form.password"
                aria-label="设置密码"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="new-password"
                required
                minlength="8"
                maxlength="256"
                placeholder="至少 8 位字符"
                :disabled="busy"
              /><button
                type="button"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                :disabled="busy"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" :size="16" /><Eye
                  v-else
                  :size="16"
                />
              </button></div></label
          ><label class="field"
            ><span>再确认一次密码</span
            ><input
              v-model="form.confirmPassword"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="new-password"
              required
              minlength="8"
              maxlength="256"
              placeholder="再次输入密码"
              :disabled="busy"
          /></label>
          <div v-if="error" class="error-box invite-error" role="alert">
            {{ error
            }}<RouterLink :to="loginDestination"
              >已有账号？登录后加入</RouterLink
            >
          </div>
          <button
            class="btn btn-primary wide-button"
            type="submit"
            :disabled="
              busy || (requiresCode && !registrationOptions.emailEnabled)
            "
          >
            <Loader2 v-if="busy" class="spin" :size="16" />{{
              busy ? "正在创建并加入…" : "创建账号并加入账本"
            }}<ArrowRight v-if="!busy" :size="16" />
          </button>
        </form>
        <footer class="invitation-expiry">
          <Clock3 :size="11" /><span
            >{{ dateTime(invitation.expiresAt) }} 前有效 ·
            邀请仅限一人接受</span
          >
        </footer>
      </section>
      <p class="invitation-footer">
        <ShieldCheck :size="12" />加入邀请中的账本，其他账本仍由各自权限管理。
      </p>
    </div>
  </main>
</template>

<style scoped>
.registration-policy-note {
  margin: 18px 0 0;
  font-size: 11px;
  text-align: center;
  line-height: 1.8;
  color: #a08aac;
}
.invitation-page {
  min-height: 100dvh;
  background:
    radial-gradient(ellipse at 12% 15%, #f0eafa77, transparent 40%),
    radial-gradient(ellipse at 85% 80%, #e9f4ec88, transparent 40%), #fcfafe;
  color: #675671;
  padding: 30px 40px 35px;
}
.invitation-brand {
  max-width: 1180px;
  margin: auto;
}
.invitation-brand > a {
  display: inline-flex;
  max-width: 100%;
  min-width: 0;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}
.invitation-brand > a > span {
  flex-shrink: 0;
  width: 38px;
  height: 40px;
  background: #eee6f9;
  color: #9b7bc1;
  display: grid;
  place-items: center;
  border-radius: 12px;
}
.invitation-brand strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 18px;
  font-weight: 600;
  color: #816196;
  letter-spacing: 0.4px;
}
.invitation-brand small {
  margin-left: 10px;
  font-size: 9px;
  font-weight: 400;
  color: #b5a0c3;
  letter-spacing: 0.5px;
}
.invitation-stage {
  width: 480px;
  max-width: 100%;
  margin: 35px auto 0;
}
.invitation-card {
  background: #fff;
  border: 1px solid #eae0f2;
  border-radius: 23px;
  padding: 33px 37px 26px;
  box-shadow: 0 10px 40px #8f70ae09;
}
.invitation-art {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  height: 91px;
  margin: 0 auto 22px;
  width: 190px;
}
.invitation-art .person {
  width: 52px;
  height: 57px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  transform: rotate(-9deg);
  border: 3px solid #fff;
}
.mint {
  background: #ecf6ef;
  color: #8cae94;
}
.peach {
  background: #fcf0e5;
  color: #c3a081;
}
.invitation-art .person:last-of-type {
  transform: rotate(9deg);
}
.center-book {
  width: 68px;
  height: 74px;
  background: #f0e8fc;
  color: #a381c5;
  border: 3px solid #fff;
  border-radius: 18px;
  display: grid;
  place-items: center;
  margin-inline: -9px;
  z-index: 1;
  transform: translateY(-7px);
}
.invitation-art > i {
  width: 29px;
  height: 29px;
  background: #f9eecb;
  color: #cab373;
  border: 3px solid #fff;
  display: grid;
  place-items: center;
  border-radius: 10px;
  position: absolute;
  bottom: 1px;
  left: 80px;
  z-index: 2;
  transform: rotate(-7deg);
}
.invitation-heading {
  text-align: center;
  margin-bottom: 25px;
}
.invitation-heading > p {
  font-size: 12px;
  color: #a58bb9;
  margin: 0 0 9px;
}
.invitation-heading h1 {
  font-size: 25px;
  font-weight: 550;
  letter-spacing: -0.5px;
  color: #735282;
  margin: 0 0 10px;
}
.invitation-heading > span {
  font-size: 11px;
  color: #b29bc2;
}
.invited-ledger {
  display: flex;
  align-items: center;
  gap: 13px;
  background: #f8f3fc;
  border: 1px solid #ede2f6;
  border-radius: 13px;
  padding: 17px 18px;
}
.invited-book {
  width: 42px;
  height: 45px;
  background: #ece0f8;
  color: #a07cbd;
  display: grid;
  place-items: center;
  border-radius: 12px;
  flex-shrink: 0;
}
.invited-ledger h2 {
  font-size: 16px;
  font-weight: 550;
  line-height: 1.5;
  overflow-wrap: anywhere;
  color: #8b63a3;
  margin: 0 0 7px;
  letter-spacing: -0.3px;
}
.invited-ledger p {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #b091c5;
  margin: 0;
}
.role-explanation {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  color: #baa2cc;
  font-size: 10px;
  line-height: 1.8;
  margin: 12px 4px 0;
}
.role-explanation > svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: #a98ebd;
}
.invitation-divider {
  height: 1px;
  background: #f1e8f8;
  margin: 24px 0 21px;
}
.join-instruction {
  font-size: 11px;
  color: #b49bc7;
  text-align: center;
  margin: 0 0 15px;
}
.wide-button {
  width: 100%;
  min-height: 44px;
  font-size: 12px;
  border-radius: 10px;
  justify-content: center;
  gap: 9px;
}
.wide-button > svg:last-child:not(:first-child) {
  margin-left: auto;
}
.wide-button > svg:first-child:not(:last-child) {
  margin-right: auto;
}
.new-account-option {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 19px 0 5px;
  font-size: 11px;
  color: #bfa7d0;
}
.new-account-option > button,
.register-header > button {
  border: 0;
  background: none;
  color: #a580c3;
  font: inherit;
  font-size: 11px;
  padding: 0;
  cursor: pointer;
}
.new-account-option > button:hover {
  text-decoration: underline;
}
.invitation-expiry {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 5px;
  border-top: 1px solid #f4edf9;
  padding-top: 18px;
  margin-top: 24px;
  color: #c7b1d8;
  font-size: 9px;
  line-height: 1.7;
}
.invitation-expiry > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.invitation-footer {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  gap: 5px;
  color: #c7b3d5;
  font-size: 9px;
  line-height: 1.8;
  text-align: center;
  margin: 19px 10px 0;
}
.invitation-footer > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.signed-in-account {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 21px;
}
.account-avatar {
  width: 37px;
  height: 39px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: #f3edf9;
  color: #af8cc9;
  font-size: 14px;
  flex-shrink: 0;
}
.signed-in-account > div {
  flex: 1;
  min-width: 0;
}
.signed-in-account > div > span {
  display: block;
  color: #c0a6d2;
  font-size: 9px;
  margin-bottom: 5px;
}
.signed-in-account strong {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: #9370ad;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.signed-in-account strong > small {
  font-size: 9px;
  color: #c1a8d1;
  font-weight: 400;
  margin-left: 5px;
}
.signed-in-account > button {
  font: inherit;
  font-size: 9px;
  color: #b28dcc;
  background: none;
  border: 0;
  padding: 5px 0;
  cursor: pointer;
  white-space: nowrap;
}
.invite-error {
  font-size: 11px;
  line-height: 1.8;
  margin: 0 0 15px;
}
.invite-error > a {
  display: block;
  color: #a278c0;
  font-size: 10px;
  margin-top: 5px;
  text-decoration: underline;
}
.invite-register {
  margin-top: 23px;
}
.register-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid #f1e8f8;
  padding-top: 21px;
  margin-bottom: 21px;
}
.register-header h2 {
  font-size: 14px;
  color: #9c74b5;
  font-weight: 500;
  margin: 0;
}
.register-header > button {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
}
.invite-register .field {
  margin-bottom: 17px;
}
.invite-register .field > span {
  font-size: 11px;
  color: #ad8fc2;
  margin-bottom: 1px;
}
.invite-register .field input {
  font-size: 12px;
  border-color: #eaddf5;
  background: #fff;
  border-radius: 9px;
  color: #9674ab;
  min-height: 42px;
}
.invite-register .field input::placeholder {
  font-size: 10px;
  color: #c8afd8;
}
.invite-password {
  position: relative;
}
.invite-password input {
  width: 100%;
  padding-right: 40px;
}
.invite-password > button {
  position: absolute;
  right: 11px;
  top: 50%;
  transform: translateY(-50%);
  padding: 0;
  border: 0;
  background: none;
  color: #c0a3d3;
  display: flex;
  align-items: center;
  cursor: pointer;
}
.state-card {
  text-align: center;
  padding-top: 38px;
  padding-bottom: 32px;
}
.state-illustration {
  width: 74px;
  height: 77px;
  border-radius: 23px;
  display: grid;
  place-items: center;
  margin: 0 auto 25px;
  transform: rotate(-6deg);
}
.state-illustration > svg {
  transform: rotate(6deg);
}
.state-card h1 {
  font-size: 23px;
  font-weight: 550;
  letter-spacing: -0.4px;
  color: #866193;
  margin: 0 0 15px;
}
.state-card > p {
  font-size: 12px;
  color: #b295c5;
  line-height: 1.9;
  margin: 0 auto 24px;
  max-width: 330px;
  overflow-wrap: anywhere;
}
.state-card > .btn:not(.wide-button) {
  font-size: 12px;
  margin-top: 3px;
}
.closed-invitation {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: #f9f4fd;
  border: 1px solid #f0e5f8;
  color: #b998ce;
  padding: 9px 13px;
  border-radius: 9px;
  font-size: 11px;
  margin: 0 auto 20px;
  max-width: 100%;
  overflow-wrap: anywhere;
}
.closed-invitation + .btn {
  display: flex;
  width: max-content;
  margin: auto;
}
.loading-invitation {
  min-height: 355px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 16px;
  color: #bd9dd5;
}
.loading-invitation p {
  font-size: 12px;
  margin: 0;
}
.success-illustration {
  width: 84px;
  height: 87px;
  background: #eef7f0;
  color: #a0c1a7;
  display: grid;
  place-items: center;
  position: relative;
  margin: 1px auto 24px;
  border-radius: 26px;
  transform: rotate(-5deg);
}
.success-illustration > svg {
  transform: rotate(5deg);
}
.success-illustration > span {
  position: absolute;
  bottom: -4px;
  right: -2px;
  border: 3px solid #fff;
  width: 24px;
  height: 24px;
  background: #f8ebc3;
  color: #c8b06e;
  border-radius: 50%;
  display: grid;
  place-items: center;
}
.joined-label {
  font-size: 10px;
  color: #b1c4b3;
  background: #f3f9f3;
  border: 1px solid #e9f2e9;
  padding: 4px 8px;
  border-radius: 6px;
  display: inline-block;
  margin: 0 0 13px;
}
.joined-card h1 {
  margin-bottom: 13px;
}
.joined-ledger {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
  background: #f7f2fc;
  border: 1px solid #ece0f5;
  border-radius: 12px;
  padding: 16px;
  margin: 0 0 23px;
}
.joined-ledger > span {
  display: grid;
  place-items: center;
  width: 40px;
  height: 43px;
  border-radius: 11px;
  background: #ecdef8;
  color: #b491d0;
  flex-shrink: 0;
}
.joined-ledger strong {
  font-size: 14px;
  color: #a07ab8;
  font-weight: 500;
  display: block;
  overflow-wrap: anywhere;
}
.joined-ledger small {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #c1a4d4;
  font-size: 10px;
  margin-top: 6px;
}
.quiet-link {
  display: inline-block;
  margin-top: 19px;
  font-size: 11px;
  color: #b59ac9;
}
.quiet-link:hover {
  text-decoration: underline;
}
.spin {
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
/* Keep text legible against the pastel surfaces. */
.invitation-heading h1,
.state-card h1 {
  color: #624c72;
}
.invited-ledger h2,
.joined-ledger strong {
  color: #76548d;
}
.invitation-heading > span,
.modal-description,
.state-card > p {
  color: #9b86ab;
}
.invitation-expiry,
.invitation-footer {
  color: #ae9bbd;
}
.role-explanation {
  color: #a28bb4;
}
.join-instruction,
.new-account-option {
  color: #a38bb6;
}
.new-account-option > button,
.register-header > button {
  color: #8963a9;
}
.signed-in-account strong {
  color: #856198;
}
.invite-register .field > span {
  color: #9476a9;
}
.invite-register .field input {
  color: #795b8d;
}
.register-header h2 {
  color: #826098;
}
.signed-in-account > div > span {
  color: #a791b7;
}
@media (max-width: 640px) {
  .invitation-page {
    padding: 23px 19px 27px;
  }
  .invitation-brand {
    padding: 0 5px;
  }
  .invitation-brand > a > span {
    width: 33px;
    height: 35px;
    border-radius: 10px;
  }
  .invitation-brand strong {
    font-size: 16px;
  }
  .invitation-brand small {
    font-size: 8px;
  }
  .invitation-stage {
    margin-top: 27px;
    width: 455px;
  }
  .invitation-card {
    padding: 28px 27px 24px;
    border-radius: 19px;
  }
  .invitation-art {
    margin-bottom: 20px;
    height: 82px;
  }
  .invitation-heading h1 {
    font-size: 24px;
  }
  .invitation-heading > p {
    font-size: 11px;
  }
  .invitation-heading > span {
    font-size: 10px;
  }
  .invited-ledger {
    padding: 15px 16px;
    gap: 11px;
  }
  .invited-ledger h2 {
    font-size: 15px;
  }
  .invited-book {
    width: 39px;
    height: 42px;
  }
  .role-explanation {
    font-size: 9px;
    gap: 5px;
  }
  .invitation-divider {
    margin: 22px 0 19px;
  }
  .join-instruction {
    font-size: 10px;
  }
  .wide-button {
    font-size: 11px;
    min-height: 43px;
  }
  .new-account-option {
    font-size: 10px;
    gap: 5px;
    margin-top: 18px;
  }
  .new-account-option > button {
    font-size: 10px;
  }
  .invitation-expiry {
    font-size: 8px;
    padding-top: 16px;
    margin-top: 22px;
  }
  .invitation-footer {
    font-size: 8px;
    margin-top: 17px;
  }
  .register-header h2 {
    font-size: 13px;
  }
  .register-header > button {
    font-size: 9px;
  }
  .invite-register .field > span {
    font-size: 10px;
  }
  .invite-register .field input {
    font-size: 13px;
    min-height: 43px;
  }
  .invite-register .field input::placeholder {
    font-size: 10px;
  }
  .invite-register .field {
    margin-bottom: 16px;
  }
  .state-card h1 {
    font-size: 22px;
  }
  .state-card > p {
    font-size: 11px;
  }
  .state-card {
    padding-top: 34px;
    padding-bottom: 29px;
  }
  .state-illustration {
    width: 66px;
    height: 70px;
    border-radius: 21px;
  }
  .success-illustration {
    width: 75px;
    height: 79px;
    border-radius: 23px;
  }
  .signed-in-account > div > span {
    font-size: 8px;
  }
  .signed-in-account strong {
    font-size: 11px;
  }
  .signed-in-account strong > small {
    font-size: 8px;
  }
  .signed-in-account > button {
    font-size: 9px;
  }
  .account-avatar {
    width: 33px;
    height: 36px;
  }
  .loading-invitation {
    min-height: 320px;
  }
  .joined-ledger strong {
    font-size: 13px;
  }
  .quiet-link {
    font-size: 10px;
  }
}
@media (max-width: 370px) {
  .invitation-page {
    padding: 20px 14px 25px;
  }
  .invitation-card {
    padding: 26px 22px 22px;
  }
  .invitation-heading h1 {
    font-size: 22px;
  }
  .invited-ledger {
    padding: 13px 14px;
  }
  .signed-in-account {
    gap: 8px;
  }
  .signed-in-account strong > small {
    display: block;
    margin: 3px 0 0;
  }
  .new-account-option {
    gap: 4px;
    font-size: 9px;
  }
  .new-account-option > button {
    font-size: 9px;
  }
  .invitation-footer {
    font-size: 7px;
    margin-inline: 3px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}

/* Keep the invitation easy to read without a dark marketing section. */
.invitation-page .invitation-brand strong,
.invitation-page .invitation-heading h1,
.invitation-page .state-card h1 {
  color: #584266;
}
.invitation-page .invitation-heading > p,
.invitation-page .invitation-heading > span,
.invitation-page .invited-ledger p,
.invitation-page .role-explanation,
.invitation-page .join-instruction,
.invitation-page .new-account-option,
.invitation-page .state-card > p,
.invitation-page .invitation-expiry,
.invitation-page .invitation-footer {
  color: #81758e;
  font-size: 12px;
}
.invitation-page .invited-ledger h2,
.invitation-page .joined-ledger strong {
  color: #675073;
}
.invitation-page .new-account-option > button,
.invitation-page .register-header > button,
.invitation-page .quiet-link,
.invitation-page .signed-in-account > button {
  color: #7863bd;
  font-size: 12px;
}
.invitation-page .signed-in-account > div > span,
.invitation-page .signed-in-account strong > small,
.invitation-page .joined-ledger small,
.invitation-page .invite-register .field > span {
  color: #81758e;
  font-size: 12px;
}
.invitation-page .signed-in-account strong {
  color: #65516f;
  font-size: 13px;
}
.invitation-page .invite-register .field input {
  font-size: 13px;
  color: #67506f;
}
.invitation-page .invite-register .field input::placeholder {
  font-size: 12px;
  color: #9b8ca5;
}
.invitation-page .joined-label {
  color: #6e8d73;
  font-size: 11px;
}
.invitation-page .closed-invitation {
  color: #81758e;
  font-size: 12px;
}
@media (max-width: 640px) {
  .invitation-page .invitation-heading > p,
  .invitation-page .invitation-heading > span,
  .invitation-page .invited-ledger p,
  .invitation-page .role-explanation,
  .invitation-page .join-instruction,
  .invitation-page .new-account-option,
  .invitation-page .invitation-expiry,
  .invitation-page .invitation-footer {
    font-size: 11px;
  }
  .invitation-page .signed-in-account > div > span,
  .invitation-page .signed-in-account strong > small,
  .invitation-page .signed-in-account > button {
    font-size: 10px;
  }
  .invitation-page .new-account-option > button,
  .invitation-page .register-header > button {
    font-size: 11px;
  }
  .invitation-page .wide-button {
    font-size: 12px;
  }
}
</style>
