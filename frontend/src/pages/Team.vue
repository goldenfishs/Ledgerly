<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  CircleAlert,
  Clock3,
  Copy,
  Link,
  Loader2,
  MailPlus,
  Search,
  ShieldCheck,
  UserMinus,
  UserRound,
  UserRoundCog,
  Users,
  X,
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

const router = useRouter();
const members = ref([]),
  invitations = ref([]),
  loading = ref(true),
  error = ref(""),
  query = ref(""),
  tab = ref("members");
const modal = ref(null),
  panel = ref(null),
  linkInput = ref(null),
  busy = ref(false),
  modalError = ref(""),
  copyError = ref(""),
  copied = ref(false),
  generated = ref(null);
const now = ref(Date.now());
const form = reactive({ role: "member", expiresInDays: 7 });
let sequence = 0,
  previousFocus = null,
  previousOverflow = "";
const ledger = computed(() => state.activeLedger);
const isAdmin = computed(() => ledger.value?.role === "admin");
const activeAdmins = computed(() =>
  members.value.filter(
    (member) => member.enabled !== false && member.role === "admin",
  ),
);
const visibleMembers = computed(() =>
  members.value.filter((member) =>
    `${member.name} ${member.username}`
      .toLocaleLowerCase()
      .includes(query.value.trim().toLocaleLowerCase()),
  ),
);
const pendingInvitations = computed(() =>
  invitations.value.filter((item) => invitationStatus(item) === "pending"),
);
const invitationLink = computed(() =>
  generated.value?.token
    ? `${location.origin}/invite/${encodeURIComponent(generated.value.token)}`
    : "",
);
const statusLabels = {
  pending: "待接受",
  accepted: "已接受",
  expired: "已过期",
  revoked: "已撤销",
};
const modalTitle = computed(
  () =>
    ({
      invite: "邀请伙伴加入账本",
      link: "邀请链接已准备好",
      role: "调整账本内的角色",
      remove: "取消这位成员的访问？",
      revoke: "撤销这份邀请？",
    })[modal.value?.kind] || "",
);
const isSelf = (member) => String(member.id) === String(state.user?.id);
const lastAdmin = (member) =>
  member.role === "admin" &&
  member.enabled !== false &&
  activeAdmins.value.length <= 1;
const roleLabel = (value) => (value === "admin" ? "管理员" : "成员");

function invitationStatus(item) {
  if (
    ["accepted", "used"].includes(item.status) ||
    item.acceptedAt ||
    item.usedAt
  )
    return "accepted";
  if (item.status === "revoked" || item.revokedAt) return "revoked";
  if (
    item.status === "expired" ||
    (item.expiresAt && new Date(item.expiresAt).getTime() <= now.value)
  )
    return "expired";
  return "pending";
}
async function load() {
  const current = ++sequence;
  if (!ledger.value?.id || !isAdmin.value) {
    loading.value = false;
    members.value = [];
    invitations.value = [];
    return;
  }
  loading.value = true;
  error.value = "";
  const id = encodeURIComponent(ledger.value.id);
  try {
    const [people, links] = await Promise.all([
      api(`/ledgers/${id}/members`),
      api(`/ledgers/${id}/invitations`),
    ]);
    if (current !== sequence) return;
    members.value = Array.isArray(people) ? people : people?.items || [];
    invitations.value = Array.isArray(links) ? links : links?.items || [];
  } catch (cause) {
    if (current === sequence)
      error.value = cause.message || "暂时无法读取成员，请重试。";
  } finally {
    if (current === sequence) loading.value = false;
  }
}
function openModal(kind, item = null) {
  if (!isAdmin.value || (kind === "remove" && lastAdmin(item))) return;
  modal.value = { kind, item, ledgerId: ledger.value.id };
  form.role = kind === "role" ? item.role : "member";
  form.expiresInDays = 7;
  modalError.value = "";
  copyError.value = "";
  copied.value = false;
  if (kind === "invite") generated.value = null;
  previousFocus = document.activeElement;
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  nextTick(() => panel.value?.querySelector("button")?.focus());
}
function closeModal() {
  if (busy.value) return;
  modal.value = null;
  document.body.style.overflow = previousOverflow;
  if (previousFocus?.isConnected) previousFocus.focus();
}
async function createInvitation() {
  if (busy.value || !modal.value) return;
  busy.value = true;
  modalError.value = "";
  try {
    generated.value = await api(
      `/ledgers/${encodeURIComponent(modal.value.ledgerId)}/invitations`,
      {
        method: "POST",
        body: { role: form.role, expiresInDays: Number(form.expiresInDays) },
      },
    );
    if (!generated.value?.token)
      throw new Error("服务没有返回邀请链接，请刷新邀请列表后重试。");
    modal.value.kind = "link";
    await load();
    await nextTick();
    linkInput.value?.focus();
    linkInput.value?.select();
  } catch (cause) {
    modalError.value = cause.message || "邀请链接创建失败，请重试。";
  } finally {
    busy.value = false;
  }
}
async function copyInvitation() {
  if (!invitationLink.value) return;
  copyError.value = "";
  try {
    if (!navigator.clipboard?.writeText)
      throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(invitationLink.value);
    copied.value = true;
    notify("链接已复制，可以分享给要邀请的人");
  } catch {
    copyError.value = "未能自动复制。请选中上方链接，手动复制后分享。";
    await nextTick();
    linkInput.value?.focus();
    linkInput.value?.select();
  }
}
async function performAction() {
  if (busy.value || !modal.value) return;
  const { kind, item, ledgerId } = modal.value;
  if (kind === "role" && form.role === item.role) {
    closeModal();
    return;
  }
  if (
    (kind === "remove" || (kind === "role" && form.role !== "admin")) &&
    lastAdmin(item)
  ) {
    modalError.value = "账本需要至少保留一位启用中的管理员。";
    return;
  }
  busy.value = true;
  modalError.value = "";
  try {
    const base = `/ledgers/${encodeURIComponent(ledgerId)}`;
    if (kind === "role")
      await api(`${base}/members/${encodeURIComponent(item.id)}`, {
        method: "PUT",
        body: { role: form.role },
      });
    else if (kind === "remove")
      await api(`${base}/members/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
      });
    else if (kind === "revoke")
      await api(`${base}/invitations/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
      });
    busy.value = false;
    closeModal();
    notify(
      kind === "role"
        ? "账本角色已更新"
        : kind === "remove"
          ? "已取消该成员对本账本的访问"
          : "邀请已撤销，原链接不再可用",
    );
    await refreshLedgers();
    if (kind !== "revoke" && isSelf(item)) {
      if (kind === "remove") {
        if (state.ledgers?.length) await selectLedger(state.ledgers[0].id);
        await router.replace("/ledgers");
      } else {
        await initSession();
        await router.replace("/overview");
      }
    } else await load();
  } catch (cause) {
    modalError.value = cause.message || "操作未完成，请重试。";
    if (!modal.value) notify(modalError.value, "error");
  } finally {
    busy.value = false;
  }
}
function keydown(event) {
  if (!modal.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeModal();
    return;
  }
  if (event.key !== "Tab") return;
  const items = [
    ...(panel.value?.querySelectorAll(
      "button:not(:disabled),input:not(:disabled),select:not(:disabled)",
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
      !panel.value.contains(document.activeElement))
  ) {
    event.preventDefault();
    last.focus();
  } else if (
    !event.shiftKey &&
    (document.activeElement === last ||
      !panel.value.contains(document.activeElement))
  ) {
    event.preventDefault();
    first.focus();
  }
}
watch(
  () => ledger.value?.id,
  () => {
    query.value = "";
    tab.value = "members";
    load();
  },
  { immediate: true },
);
document.addEventListener("keydown", keydown);
const clock = setInterval(() => {
  now.value = Date.now();
}, 60000);
onBeforeUnmount(() => {
  sequence++;
  clearInterval(clock);
  document.removeEventListener("keydown", keydown);
  if (modal.value) document.body.style.overflow = previousOverflow;
});
</script>

<template>
  <div class="ledger-team">
    <header class="page-header people-heading">
      <div>
        <h1>一起记账的人</h1>
        <p>
          邀请伙伴加入「{{
            ledger?.name || "当前账本"
          }}」，在各自的角色里轻松协作。
        </p>
      </div>
      <button
        v-if="isAdmin"
        class="btn btn-primary"
        type="button"
        @click="openModal('invite')"
      >
        <MailPlus :size="17" />邀请成员
      </button>
    </header>
    <div v-if="!isAdmin" class="card people-empty">
      <ShieldCheck :size="32" />
      <h2>成员管理由账本管理员负责</h2>
      <p>需要邀请伙伴或调整权限时，请联系这个账本的管理员。</p>
      <RouterLink class="btn btn-secondary" to="/ledgers"
        >查看我的账本</RouterLink
      >
    </div>
    <template v-else>
      <section class="people-summary">
        <div class="people-stat mint">
          <span><Users :size="23" /></span>
          <div>
            <strong
              >{{ loading ? "—" : members.length }}<small>位伙伴</small></strong
            >
            <p>在这个账本里一起协作</p>
          </div>
        </div>
        <div class="people-stat lilac">
          <span><ShieldCheck :size="23" /></span>
          <div>
            <strong
              >{{ loading ? "—" : activeAdmins.length
              }}<small>位管理员</small></strong
            >
            <p>负责成员、账务与审核</p>
          </div>
        </div>
        <div class="people-stat peach">
          <span><Link :size="22" /></span>
          <div>
            <strong
              >{{ loading ? "—" : pendingInvitations.length
              }}<small>份邀请</small></strong
            >
            <p>等待新伙伴接受</p>
          </div>
        </div>
      </section>
      <section class="card people-card">
        <div class="people-toolbar">
          <div class="people-tabs" role="group" aria-label="成员与邀请">
            <button
              type="button"
              :class="{ active: tab === 'members' }"
              :aria-pressed="tab === 'members'"
              @click="tab = 'members'"
            >
              账本成员<span>{{ members.length }}</span></button
            ><button
              type="button"
              :class="{ active: tab === 'invitations' }"
              :aria-pressed="tab === 'invitations'"
              @click="tab = 'invitations'"
            >
              邀请记录<span>{{ invitations.length }}</span>
            </button>
          </div>
          <label v-if="tab === 'members'" class="people-search"
            ><Search :size="14" /><input
              v-model="query"
              type="search"
              placeholder="搜索姓名或账号"
              aria-label="搜索账本成员" /></label
          ><span v-else class="invitation-hint">邀请链接仅限一人使用</span>
        </div>
        <div v-if="error" class="people-empty">
          <CircleAlert :size="30" />
          <h2>暂时无法加载</h2>
          <p>{{ error }}</p>
          <button class="btn btn-secondary" type="button" @click="load">
            重新加载
          </button>
        </div>
        <div v-else-if="loading" class="people-loading">
          <Loader2 class="spin" :size="23" /><span>正在读取账本成员…</span>
        </div>
        <template v-else-if="tab === 'members'"
          ><div v-if="!visibleMembers.length" class="people-empty">
            <Search :size="30" />
            <h2>没有找到这位伙伴</h2>
            <p>换个姓名或账号，或者清空搜索条件。</p>
            <button
              v-if="query"
              class="btn btn-secondary"
              type="button"
              @click="query = ''"
            >
              清空搜索
            </button>
          </div>
          <div v-else>
            <article
              v-for="(member, index) in visibleMembers"
              :key="member.id"
              class="member-row"
            >
              <span
                class="member-avatar"
                :class="['mint', 'lilac', 'peach', 'butter'][index % 4]"
                >{{
                  (member.name || member.username || "成").slice(0, 1)
                }}</span
              >
              <div class="member-identity">
                <div>
                  <strong>{{ member.name || member.username }}</strong
                  ><span v-if="isSelf(member)" class="self-pill">我</span
                  ><span v-if="member.enabled === false" class="disabled-pill"
                    >已停用</span
                  >
                </div>
                <small>@{{ member.username }}</small>
              </div>
              <div class="member-role">
                <ShieldCheck
                  v-if="member.role === 'admin'"
                  :size="13"
                /><UserRound v-else :size="13" />{{ roleLabel(member.role) }}
              </div>
              <div class="member-actions">
                <button type="button" @click="openModal('role', member)">
                  <UserRoundCog :size="14" /><span>调整角色</span></button
                ><button
                  class="remove-member"
                  type="button"
                  :disabled="lastAdmin(member)"
                  :title="
                    lastAdmin(member)
                      ? '账本需要至少保留一位管理员'
                      : '取消此成员对账本的访问'
                  "
                  :aria-label="`取消${member.name || member.username}的账本访问`"
                  @click="openModal('remove', member)"
                >
                  <UserMinus :size="15" />
                </button>
              </div>
            </article></div
        ></template>
        <template v-else
          ><div v-if="!invitations.length" class="people-empty">
            <MailPlus :size="32" />
            <h2>发出第一份邀请吧</h2>
            <p>生成链接后分享给伙伴，对方可以登录或注册加入。</p>
            <button
              class="btn btn-primary"
              type="button"
              @click="openModal('invite')"
            >
              邀请成员
            </button>
          </div>
          <div v-else>
            <article
              v-for="invitation in invitations"
              :key="invitation.id"
              class="invitation-row"
            >
              <span class="invite-row-icon"><Link :size="18" /></span>
              <div class="invitation-info">
                <strong>{{ roleLabel(invitation.role) }}邀请</strong
                ><span
                  >{{
                    invitationStatus(invitation) === "pending"
                      ? "有效期至"
                      : "原有效期至"
                  }}
                  {{ dateTime(invitation.expiresAt) }}</span
                ><small v-if="invitation.acceptedByName"
                  >已由 {{ invitation.acceptedByName }} 接受</small
                >
              </div>
              <span class="invite-state" :class="invitationStatus(invitation)"
                ><i></i>{{ statusLabels[invitationStatus(invitation)] }}</span
              ><button
                v-if="invitationStatus(invitation) === 'pending'"
                class="revoke-button"
                type="button"
                @click="openModal('revoke', invitation)"
              >
                撤销邀请</button
              ><span v-else class="invitation-done">{{
                invitationStatus(invitation) === "accepted"
                  ? "已完成"
                  : "不可再使用"
              }}</span>
            </article>
          </div></template
        >
        <footer class="people-card-footer">
          <BookOpen :size="12" /><span
            >这里的角色与访问权限仅作用于「{{ ledger?.name }}」</span
          >
        </footer>
      </section>
      <div class="role-explainer">
        <div>
          <span class="role-symbol lilac"><ShieldCheck :size="18" /></span>
          <p>
            <strong>管理员</strong
            >管理本账本成员、查看账本全量流水，并进行审核。
          </p>
        </div>
        <div>
          <span class="role-symbol mint"><UserRound :size="18" /></span>
          <p><strong>成员</strong>提交自己的流水与凭证，审核通过后计入账本。</p>
        </div>
      </div>
    </template>

    <Teleport to="body"
      ><div
        v-if="modal"
        class="modal-backdrop people-modal"
        @mousedown.self="closeModal"
      >
        <section
          ref="panel"
          class="dialog card people-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="people-dialog-title"
          :aria-busy="busy"
        >
          <header class="dialog-header">
            <div>
              <span class="people-dialog-icon"
                ><CheckCheck
                  v-if="modal.kind === 'link'"
                  :size="25" /><UserMinus
                  v-else-if="modal.kind === 'remove'"
                  :size="24" /><ShieldCheck
                  v-else-if="modal.kind === 'role'"
                  :size="24" /><MailPlus v-else :size="25"
              /></span>
              <h2 id="people-dialog-title">{{ modalTitle }}</h2>
            </div>
            <button
              class="icon-btn"
              type="button"
              aria-label="关闭成员操作"
              :disabled="busy"
              @click="closeModal"
            >
              <X :size="18" />
            </button>
          </header>
          <template v-if="modal.kind === 'invite'"
            ><p class="modal-description">
              创建一份专属邀请，分享给要加入「{{ ledger?.name }}」的伙伴。
            </p>
            <fieldset class="invite-role-options">
              <legend>加入后的角色</legend>
              <label :class="{ chosen: form.role === 'member' }"
                ><input
                  v-model="form.role"
                  type="radio"
                  name="invitation-role"
                  value="member"
                  :disabled="busy" /><UserRound :size="20" /><span
                  ><strong>成员</strong
                  ><small>记录自己的收支，提交审核</small></span
                ><Check v-if="form.role === 'member'" :size="16" /></label
              ><label :class="{ chosen: form.role === 'admin' }"
                ><input
                  v-model="form.role"
                  type="radio"
                  name="invitation-role"
                  value="admin"
                  :disabled="busy" /><ShieldCheck :size="20" /><span
                  ><strong>管理员</strong
                  ><small>管理账本、成员与全量流水</small></span
                ><Check v-if="form.role === 'admin'" :size="16"
              /></label>
            </fieldset>
            <label class="field expiration-field"
              ><span>邀请有效期</span>
              <div>
                <Clock3 :size="15" /><select
                  v-model.number="form.expiresInDays"
                  :disabled="busy"
                >
                  <option :value="1">1 天</option>
                  <option :value="7">7 天</option>
                  <option :value="30">30 天</option></select
                ><ChevronDown :size="14" /></div
            ></label>
            <p class="invitation-smallprint">
              一个链接只能由一位新成员接受，你可以随时撤销尚未使用的邀请。
            </p></template
          >
          <template v-else-if="modal.kind === 'link'"
            ><p class="modal-description">
              复制链接，分享给要邀请的人。对方将以<strong>{{
                roleLabel(generated?.role || form.role)
              }}</strong
              >身份加入「{{ ledger?.name }}」。
            </p>
            <div class="generated-link">
              <label for="generated-invitation-link">邀请链接</label
              ><input
                id="generated-invitation-link"
                ref="linkInput"
                :value="invitationLink"
                readonly
                @focus="$event.target.select()"
              /><button
                class="btn btn-primary"
                type="button"
                @click="copyInvitation"
              >
                <Check v-if="copied" :size="16" /><Copy v-else :size="16" />{{
                  copied ? "链接已复制" : "复制邀请链接"
                }}
              </button>
            </div>
            <p class="invite-expiration">
              <Clock3 :size="12" />{{ dateTime(generated?.expiresAt) }} 前有效 ·
              仅限一人接受
            </p>
            <p class="invitation-smallprint">
              完整链接只在创建时显示，请在关闭前复制。之后仍可在邀请记录中查看状态或撤销。
            </p>
            <p v-if="copyError" class="copy-error" role="alert">
              {{ copyError }}
            </p></template
          >
          <template v-else-if="modal.kind === 'role'"
            ><p class="modal-description">
              调整 {{ modal.item.name || modal.item.username }} 在「{{
                ledger?.name
              }}」中的权限。其他账本的角色保持不变。
            </p>
            <label class="field role-select"
              ><span>账本角色</span
              ><select v-model="form.role" :disabled="busy">
                <option value="member" :disabled="lastAdmin(modal.item)">
                  成员
                </option>
                <option value="admin">管理员</option>
              </select></label
            >
            <p class="role-description">
              {{
                form.role === "admin"
                  ? "管理员可邀请和管理成员，查看并审核这个账本的全部流水。"
                  : "成员可以提交自己的流水和凭证，由管理员审核后记入账本。"
              }}
            </p>
            <p v-if="lastAdmin(modal.item)" class="invitation-smallprint">
              这是本账本最后一位启用中的管理员，需要先添加另一位管理员才能调整。
            </p></template
          >
          <template v-else-if="modal.kind === 'remove'"
            ><p class="modal-description">
              <strong>{{ modal.item.name || modal.item.username }}</strong>
              将无法继续访问「{{ ledger?.name }}」。
            </p>
            <div class="removal-note">
              <ShieldCheck :size="17" /><span
                >已提交的流水、凭证和审核记录会保留。该用户的账号与其他账本不受影响。</span
              >
            </div></template
          >
          <template v-else-if="modal.kind === 'revoke'"
            ><p class="modal-description">
              撤销后，这份{{
                roleLabel(modal.item.role)
              }}邀请的原链接将立即失效。如果之后仍需邀请，可以重新创建链接。
            </p></template
          >
          <div v-if="modalError" class="error-box" role="alert">
            {{ modalError }}
          </div>
          <footer class="dialog-actions">
            <button
              class="btn btn-secondary"
              type="button"
              :disabled="busy"
              @click="closeModal"
            >
              {{ modal.kind === "link" ? "完成" : "取消" }}</button
            ><button
              v-if="modal.kind === 'invite'"
              class="btn btn-primary"
              type="button"
              :disabled="busy"
              @click="createInvitation"
            >
              <Loader2 v-if="busy" :size="15" class="spin" /><Link
                v-else
                :size="15"
              />{{ busy ? "正在创建…" : "生成邀请链接" }}</button
            ><button
              v-else-if="modal.kind !== 'link'"
              class="btn"
              :class="
                ['remove', 'revoke'].includes(modal.kind)
                  ? 'btn-danger'
                  : 'btn-primary'
              "
              type="button"
              :disabled="busy"
              @click="performAction"
            >
              <Loader2 v-if="busy" :size="15" class="spin" />{{
                busy
                  ? "正在处理…"
                  : modal.kind === "role"
                    ? "保存角色"
                    : modal.kind === "remove"
                      ? "取消成员访问"
                      : "撤销邀请"
              }}
            </button>
          </footer>
        </section>
      </div></Teleport
    >
  </div>
</template>

<style scoped>
.ledger-team {
  max-width: 1140px;
  margin: auto;
  color: #65566f;
}
.people-heading {
  margin-bottom: 27px;
}
.people-heading h1 {
  font-size: 29px;
  letter-spacing: -0.4px;
}
.people-heading p {
  font-size: 13px;
  line-height: 1.8;
  max-width: 590px;
}
.people-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 19px;
  margin-bottom: 27px;
}
.people-stat {
  display: flex;
  align-items: center;
  gap: 17px;
  padding: 23px 24px;
  border-radius: 15px;
  border: 1px solid transparent;
}
.mint {
  background: #f0f7f2;
  color: #7a9d87;
  border-color: #e1eee5;
}
.lilac {
  background: #f5f1fb;
  color: #9680b3;
  border-color: #ebe2f4;
}
.peach {
  background: #fcf3ed;
  color: #b58d72;
  border-color: #f3e6db;
}
.butter {
  background: #fbf8e9;
  color: #ab9e69;
}
.people-stat > span {
  width: 47px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: #ffffff70;
  flex-shrink: 0;
}
.people-stat strong {
  font-size: 28px;
  line-height: 1.4;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.people-stat strong small {
  font-size: 11px;
  margin-left: 7px;
  font-weight: 400;
}
.people-stat p {
  font-size: 10px;
  margin: 5px 0 0;
  opacity: 0.88;
}
.people-card {
  border-radius: 15px;
  border-color: #eae5ef;
  overflow: hidden;
}
.people-toolbar {
  padding: 0 23px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  border-bottom: 1px solid #eeeaf3;
}
.people-tabs {
  display: flex;
  gap: 26px;
}
.people-tabs > button {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  border: 0;
  background: none;
  font: inherit;
  font-size: 12px;
  color: #9c8bac;
  padding: 21px 0 19px;
  cursor: pointer;
}
.people-tabs > button.active {
  color: #896cae;
}
.people-tabs > button.active:after {
  position: absolute;
  content: "";
  bottom: -1px;
  left: 0;
  right: 0;
  height: 2px;
  background: #ac8ecd;
  border-radius: 4px;
}
.people-tabs > button > span {
  font-size: 9px;
  background: #f6f1fb;
  border-radius: 5px;
  min-width: 19px;
  text-align: center;
  padding: 1px 5px;
  color: #a189bc;
}
.people-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #ece6f2;
  border-radius: 8px;
  background: #fcfafe;
  color: #ad9ebd;
  width: 190px;
}
.people-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  background: none;
  outline: 0;
  font: inherit;
  font-size: 10px;
  color: #7e6e8e;
}
.people-search input::placeholder {
  color: #b4a5c2;
}
.people-search:focus-within {
  outline: 2px solid #eae1f6;
}
.invitation-hint {
  font-size: 10px;
  color: #ae9abc;
}
.member-row {
  display: flex;
  align-items: center;
  gap: 15px;
  padding: 21px 25px;
  border-bottom: 1px solid #f1edf5;
}
.member-row:last-child {
  border: 0;
}
.member-avatar {
  width: 42px;
  height: 44px;
  border-radius: 13px;
  display: grid;
  place-items: center;
  font-size: 16px;
  flex-shrink: 0;
}
.member-identity {
  min-width: 0;
  flex: 1;
}
.member-identity > div {
  display: flex;
  align-items: center;
  gap: 7px;
}
.member-identity strong {
  font-size: 13px;
  color: #736080;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.member-identity small {
  display: block;
  font-size: 10px;
  color: #a994b8;
  margin-top: 5px;
}
.self-pill,
.disabled-pill {
  font-size: 8px;
  line-height: 1.5;
  border-radius: 4px;
  padding: 2px 5px;
  background: #f5f0fa;
  color: #a189bc;
  white-space: nowrap;
}
.disabled-pill {
  background: #f5f2f2;
  color: #a69696;
}
.member-role {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #9c82b2;
  font-size: 11px;
  width: 100px;
}
.member-actions {
  display: flex;
  align-items: center;
  gap: 19px;
  margin-left: 20px;
}
.member-actions > button {
  display: flex;
  align-items: center;
  gap: 5px;
  border: 0;
  background: none;
  font: inherit;
  font-size: 10px;
  color: #9b7fb2;
  cursor: pointer;
  padding: 5px;
}
.member-actions > .remove-member {
  color: #b49ac4;
  padding: 7px;
}
.member-actions > .remove-member:hover {
  color: #b98778;
  background: #fbf3ee;
  border-radius: 6px;
}
.member-actions > button:disabled {
  opacity: 0.35;
  cursor: default;
}
.people-card-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  border-top: 1px solid #f0eaf5;
  padding: 15px 25px;
  color: #b09abd;
  font-size: 9px;
}
.role-explainer {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 25px;
  margin: 23px 5px 0;
}
.role-explainer > div {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.role-symbol {
  width: 30px;
  height: 31px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.role-explainer p {
  font-size: 10px;
  color: #a48cb6;
  line-height: 1.9;
  margin: 0;
}
.role-explainer strong {
  display: block;
  font-size: 11px;
  font-weight: 500;
  color: #8c70a4;
  margin-bottom: 4px;
}
.people-empty,
.people-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 285px;
  padding: 38px 24px;
  text-align: center;
}
.people-empty > svg {
  color: #b39aca;
  margin-bottom: 19px;
}
.people-empty h2 {
  font-size: 16px;
  font-weight: 500;
  color: #896a9f;
  margin: 0 0 9px;
}
.people-empty p {
  font-size: 12px;
  color: #ac94bb;
  line-height: 1.8;
  margin: 0 0 20px;
  max-width: 440px;
}
.people-loading {
  color: #a991bf;
  gap: 13px;
  font-size: 12px;
}
.invitation-row {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 21px 25px;
  border-bottom: 1px solid #f1edf5;
}
.invitation-row:last-child {
  border: 0;
}
.invite-row-icon {
  width: 38px;
  height: 40px;
  border-radius: 11px;
  background: #f6f1fc;
  color: #a889c2;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.invitation-info {
  min-width: 0;
  flex: 1;
}
.invitation-info strong {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: #886b9f;
}
.invitation-info > span,
.invitation-info > small {
  display: block;
  font-size: 9px;
  color: #ac91bd;
  margin-top: 5px;
}
.invite-state {
  display: flex;
  align-items: center;
  gap: 5px;
  background: #f6f3f9;
  border-radius: 5px;
  padding: 4px 7px;
  color: #a88bb9;
  font-size: 9px;
  white-space: nowrap;
}
.invite-state i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
}
.invite-state.pending {
  background: #fbf6e8;
  color: #b49d60;
}
.invite-state.accepted {
  background: #eef7ef;
  color: #80a484;
}
.invite-state.expired {
  background: #f7f4f2;
  color: #aa9384;
}
.invite-state.revoked {
  background: #f8f1f6;
  color: #a88c9f;
}
.revoke-button {
  border: 0;
  background: none;
  color: #9e7cb4;
  font: inherit;
  font-size: 10px;
  padding: 7px 0 7px 15px;
  cursor: pointer;
  white-space: nowrap;
}
.invitation-done {
  font-size: 9px;
  color: #b9a1c7;
  min-width: 70px;
  text-align: right;
}
.people-modal {
  z-index: 1200;
}
.people-dialog {
  border-radius: 20px;
  background: #fff;
  border-color: #eae0f3;
  width: 490px;
}
.people-dialog-icon {
  width: 46px;
  height: 47px;
  display: grid;
  place-items: center;
  background: #f3ebfc;
  color: #a080c0;
  border-radius: 13px;
  margin-bottom: 18px;
}
.people-dialog h2 {
  font-size: 20px;
  color: #755687;
  letter-spacing: -0.3px;
}
.people-dialog .dialog-header {
  margin-bottom: 15px;
}
.modal-description {
  font-size: 12px !important;
  line-height: 1.9;
  color: #9c82af;
  margin: 0 0 22px;
  overflow-wrap: anywhere;
}
.modal-description strong {
  font-weight: 500;
  color: #8d68a5;
  margin: 0 3px;
}
.invite-role-options {
  border: 0;
  margin: 0 0 22px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.invite-role-options legend {
  font-size: 11px;
  color: #a185b3;
  margin-bottom: 11px;
}
.invite-role-options label {
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  padding: 13px 15px;
  border: 1px solid #eee5f6;
  border-radius: 10px;
  color: #aa8cbd;
  cursor: pointer;
}
.invite-role-options label.chosen {
  background: #f9f4ff;
  border-color: #d7c1e9;
  color: #9571b0;
}
.invite-role-options input {
  position: absolute;
  opacity: 0;
  inset: 0;
  cursor: pointer;
  z-index: 1;
}
.invite-role-options input:focus-visible + svg {
  outline: 2px solid #c8afe0;
  outline-offset: 4px;
}
.invite-role-options label > span {
  flex: 1;
}
.invite-role-options strong {
  display: block;
  font-size: 12px;
  font-weight: 500;
}
.invite-role-options small {
  display: block;
  font-size: 10px;
  color: #b095c3;
  margin-top: 4px;
}
.expiration-field {
  margin-bottom: 14px;
}
.expiration-field > span,
.role-select > span {
  font-size: 11px;
  color: #9878ae;
}
.expiration-field > div {
  display: flex;
  align-items: center;
  position: relative;
  border: 1px solid #ebdff5;
  border-radius: 9px;
  padding: 0 12px;
  color: #ad91c1;
}
.expiration-field select {
  border: 0;
  background: none;
  appearance: none;
  flex: 1;
  font: inherit;
  font-size: 12px;
  color: #9571ad;
  padding: 11px 10px;
  outline: 0;
}
.expiration-field > div > svg:last-child {
  pointer-events: none;
}
.invitation-smallprint {
  font-size: 10px !important;
  color: #b599c9;
  line-height: 1.9;
  margin: 13px 0 0;
}
.generated-link {
  border: 1px solid #e8d9f7;
  background: #faf6ff;
  border-radius: 13px;
  padding: 17px;
}
.generated-link > label {
  display: block;
  font-size: 10px;
  color: #a183b8;
  margin-bottom: 9px;
}
.generated-link > input {
  font-size: 11px;
  background: #fff;
  color: #906dac;
  border: 1px solid #eaddf5;
  border-radius: 8px;
  width: 100%;
  padding: 11px 10px;
}
.generated-link > .btn {
  width: 100%;
  margin-top: 12px;
  font-size: 12px;
}
.invite-expiration {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 9px !important;
  color: #ae8fc4;
  margin: 12px 0 0;
}
.copy-error {
  font-size: 11px !important;
  line-height: 1.8;
  color: #ad7b75;
  margin: 13px 0 0;
}
.role-select {
  margin-bottom: 15px;
}
.role-select select {
  font-size: 12px;
  border-color: #e9daf5;
  border-radius: 9px;
}
.role-description {
  font-size: 11px !important;
  line-height: 1.8;
  color: #a181b6;
}
.removal-note {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 14px 15px;
  background: #f6f2fc;
  border: 1px solid #eee5f7;
  border-radius: 10px;
  color: #9e7bb7;
  font-size: 11px;
  line-height: 1.9;
}
.removal-note > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.people-dialog .error-box {
  font-size: 11px;
  margin-top: 17px;
}
.people-dialog .dialog-actions {
  margin-top: 25px;
}
.people-dialog .dialog-actions .btn {
  font-size: 12px;
}
.spin {
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1050px) {
  .people-stat {
    padding: 21px 20px;
    gap: 13px;
  }
  .people-stat strong {
    font-size: 26px;
  }
  .people-stat strong small {
    font-size: 10px;
    margin-left: 5px;
  }
  .people-stat p {
    font-size: 9px;
  }
  .people-stat > span {
    width: 41px;
    height: 43px;
  }
  .people-summary {
    gap: 14px;
  }
  .member-role {
    width: 83px;
  }
  .member-actions {
    gap: 12px;
    margin-left: 10px;
  }
}
@media (max-width: 680px) {
  .people-heading {
    align-items: flex-start;
    gap: 14px;
    margin-bottom: 22px;
  }
  .people-heading h1 {
    font-size: 25px;
  }
  .people-heading p {
    font-size: 11px;
    max-width: 285px;
  }
  .people-heading > .btn {
    font-size: 11px;
    padding: 8px 11px;
    margin-top: 7px;
  }
  .people-heading > .btn > svg {
    width: 15px;
  }
  .people-summary {
    gap: 10px;
    margin-bottom: 21px;
  }
  .people-stat {
    padding: 16px 14px;
    flex-direction: column;
    align-items: flex-start;
    gap: 11px;
    border-radius: 12px;
  }
  .people-stat > span {
    width: 32px;
    height: 34px;
    border-radius: 10px;
  }
  .people-stat > span > svg {
    width: 19px;
  }
  .people-stat strong {
    font-size: 23px;
  }
  .people-stat strong small {
    font-size: 9px;
    margin-left: 3px;
  }
  .people-stat p {
    font-size: 8px;
    line-height: 1.7;
    margin-top: 5px;
  }
  .people-toolbar {
    padding: 0 17px;
    gap: 10px;
    flex-wrap: wrap;
  }
  .people-tabs {
    gap: 22px;
  }
  .people-tabs > button {
    font-size: 11px;
    padding: 18px 0 16px;
    gap: 6px;
  }
  .people-search {
    width: 166px;
    padding: 7px 9px;
  }
  .people-search input {
    font-size: 9px;
  }
  .invitation-hint {
    font-size: 8px;
  }
  .member-row {
    padding: 19px 18px;
    gap: 11px;
  }
  .member-avatar {
    width: 36px;
    height: 38px;
    font-size: 14px;
    border-radius: 11px;
  }
  .member-identity strong {
    font-size: 12px;
  }
  .member-identity small {
    font-size: 9px;
  }
  .member-role {
    font-size: 10px;
    width: auto;
    gap: 4px;
  }
  .member-role > svg {
    width: 11px;
  }
  .member-actions {
    margin-left: 4px;
    gap: 6px;
  }
  .member-actions > button {
    padding: 4px;
    font-size: 9px;
  }
  .member-actions > button > span {
    display: none;
  }
  .member-actions > .remove-member {
    padding: 5px;
  }
  .people-card-footer {
    font-size: 8px;
    padding: 13px 18px;
    align-items: flex-start;
    line-height: 1.8;
  }
  .people-card-footer > svg {
    flex-shrink: 0;
    margin-top: 2px;
  }
  .role-explainer {
    gap: 18px;
    margin-top: 20px;
  }
  .role-explainer p {
    font-size: 9px;
  }
  .role-explainer strong {
    font-size: 10px;
  }
  .role-symbol {
    width: 26px;
    height: 27px;
    border-radius: 8px;
  }
  .role-symbol > svg {
    width: 15px;
  }
  .role-explainer > div {
    gap: 8px;
  }
  .people-empty h2 {
    font-size: 14px;
  }
  .people-empty p {
    font-size: 11px;
  }
  .people-empty,
  .people-loading {
    min-height: 260px;
  }
  .invitation-row {
    padding: 19px 17px;
    gap: 10px;
    flex-wrap: wrap;
  }
  .invite-row-icon {
    width: 32px;
    height: 34px;
  }
  .invite-row-icon > svg {
    width: 16px;
  }
  .invitation-info strong {
    font-size: 11px;
  }
  .invitation-info > span {
    font-size: 8px;
  }
  .invite-state {
    font-size: 8px;
    padding: 3px 6px;
  }
  .revoke-button {
    font-size: 9px;
    padding-left: 6px;
  }
  .invitation-done {
    font-size: 8px;
    min-width: 51px;
  }
  .people-dialog {
    padding: 24px;
    border-radius: 18px;
  }
  .people-dialog h2 {
    font-size: 19px;
  }
  .people-dialog-icon {
    width: 42px;
    height: 44px;
  }
  .modal-description {
    font-size: 11px !important;
  }
  .invite-role-options strong {
    font-size: 11px;
  }
  .invite-role-options small {
    font-size: 9px;
  }
  .people-dialog .dialog-actions .btn {
    font-size: 11px;
  }
}
@media (max-width: 440px) {
  .people-toolbar {
    padding-bottom: 13px;
  }
  .people-tabs {
    width: 100%;
    gap: 25px;
  }
  .people-tabs > button {
    padding-bottom: 14px;
  }
  .people-search {
    width: 100%;
    padding: 8px 10px;
  }
  .people-search input {
    font-size: 10px;
  }
  .invitation-hint {
    padding-bottom: 0;
    margin-top: -1px;
    font-size: 9px;
  }
  .people-summary {
    gap: 8px;
  }
  .people-stat {
    padding: 14px 12px;
  }
  .people-stat strong {
    font-size: 21px;
  }
  .people-stat strong small {
    font-size: 8px;
  }
  .people-stat p {
    font-size: 7px;
  }
  .member-row {
    gap: 9px;
    padding: 18px 15px;
  }
  .member-role {
    font-size: 9px;
  }
  .member-identity strong {
    font-size: 11px;
  }
  .member-avatar {
    width: 32px;
    height: 34px;
  }
  .member-actions {
    gap: 3px;
    margin-left: 1px;
  }
  .member-actions > button > svg {
    width: 13px;
  }
  .member-actions > .remove-member > svg {
    width: 14px;
  }
  .member-identity > div {
    gap: 5px;
  }
  .role-explainer {
    grid-template-columns: 1fr;
    gap: 15px;
  }
  .role-explainer p {
    font-size: 10px;
  }
  .role-explainer strong {
    font-size: 11px;
  }
  .invitation-info {
    flex-basis: calc(100% - 114px);
  }
  .revoke-button,
  .invitation-done {
    margin-left: 42px;
    margin-top: -5px;
    font-size: 9px;
    padding: 0;
  }
  .people-heading > .btn {
    font-size: 10px;
    padding: 8px 10px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}

/* High-contrast copy on the soft color palette. */
.ledger-team .people-heading p,
.ledger-team .people-stat p,
.ledger-team .people-stat strong small {
  color: #81758e;
  font-size: 12px;
}
.ledger-team .people-stat strong {
  color: #685575;
}
.ledger-team .people-tabs > button {
  font-size: 13px;
  color: #81758e;
}
.ledger-team .people-tabs > button.active {
  color: #7863bd;
}
.ledger-team .member-identity strong,
.ledger-team .invitation-info strong,
.ledger-team .people-empty h2 {
  color: #574361;
  font-size: 14px;
}
.ledger-team .member-identity small,
.ledger-team .member-role,
.ledger-team .invitation-info > span,
.ledger-team .invitation-info > small,
.ledger-team .invitation-hint,
.ledger-team .people-card-footer,
.ledger-team .role-explainer p,
.ledger-team .people-empty p,
.ledger-team .invitation-done {
  color: #81758e;
  font-size: 12px;
}
.ledger-team .role-explainer strong {
  color: #685276;
  font-size: 13px;
}
.ledger-team .member-actions > button,
.ledger-team .revoke-button {
  color: #80629a;
  font-size: 12px;
}
.ledger-team .people-search input {
  color: #65526f;
  font-size: 12px;
}
.ledger-team .people-search input::placeholder {
  color: #9d90a8;
}
.ledger-team .invite-state,
.ledger-team .self-pill,
.ledger-team .disabled-pill {
  font-size: 11px;
}
.ledger-team .invite-state.pending {
  color: #9d813a;
}
.ledger-team .invite-state.accepted {
  color: #66866d;
}
.ledger-team .invite-state.expired,
.ledger-team .invite-state.revoked {
  color: #88758e;
}
.people-dialog h2 {
  color: #584260;
}
.people-dialog .modal-description,
.people-dialog .invite-role-options legend,
.people-dialog .invite-role-options small,
.people-dialog .expiration-field > span,
.people-dialog .role-select > span,
.people-dialog .role-description,
.people-dialog .removal-note,
.people-dialog .invitation-smallprint,
.people-dialog .invite-expiration {
  color: #81758e;
  font-size: 12px !important;
}
.people-dialog .invite-role-options strong {
  font-size: 13px;
  color: #685077;
}
.people-dialog .modal-description strong {
  color: #715281;
}
.people-dialog .generated-link > label {
  font-size: 12px;
  color: #81758e;
}
.people-dialog .generated-link > input,
.people-dialog .expiration-field select,
.people-dialog .role-select select {
  font-size: 13px;
  color: #6f527f;
}
@media (max-width: 680px) {
  .ledger-team .people-heading p,
  .ledger-team .people-stat p,
  .ledger-team .people-stat strong small,
  .ledger-team .member-identity small,
  .ledger-team .member-role,
  .ledger-team .people-card-footer,
  .ledger-team .role-explainer p,
  .ledger-team .invitation-info > span,
  .ledger-team .invitation-done {
    font-size: 11px;
  }
  .ledger-team .people-stat p {
    font-size: 10px;
  }
  .ledger-team .people-stat strong small {
    font-size: 10px;
  }
  .ledger-team .member-identity strong,
  .ledger-team .invitation-info strong {
    font-size: 12px;
  }
  .ledger-team .member-role {
    gap: 3px;
  }
  .ledger-team .invite-state,
  .ledger-team .self-pill,
  .ledger-team .disabled-pill {
    font-size: 9px;
  }
  .ledger-team .revoke-button {
    font-size: 11px;
  }
  .people-dialog .invite-role-options small {
    font-size: 11px !important;
  }
}
</style>
