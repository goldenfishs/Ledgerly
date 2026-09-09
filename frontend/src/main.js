import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Login from "./pages/Login.vue";
import { notify } from "./lib/app";
import "./style.css";
import "./theme.css";
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/overview" },
    {
      path: "/ledgers",
      name: "ledgers",
      component: () => import("./pages/Ledgers.vue"),
      meta: { title: "我的账本", anyLedger: true },
    },
    {
      path: "/invite/:token",
      name: "invite",
      component: () => import("./pages/Invite.vue"),
      meta: { title: "加入账本", public: true },
    },
    {
      path: "/profile",
      component: () => import("./pages/Profile.vue"),
      meta: { title: "个人中心", anyLedger: true },
    },
    {
      path: "/system",
      component: () => import("./pages/SystemSettings.vue"),
      meta: { title: "系统设置", systemAdmin: true, anyLedger: true },
    },
    {
      path: "/register",
      component: () => import("./pages/Register.vue"),
      meta: { title: "注册账号", public: true },
    },
    {
      path: "/recover",
      component: () => import("./pages/Recover.vue"),
      meta: { title: "找回密码", public: true },
    },
    {
      path: "/login",
      component: Login,
      meta: { title: "登录" },
    },
    {
      path: "/overview",
      component: () => import("./pages/Overview.vue"),
      meta: { title: "工作台", group: "工作空间" },
    },
    {
      path: "/transactions",
      component: () => import("./pages/Transactions.vue"),
      meta: { title: "收支流水", group: "账务管理" },
    },
    {
      path: "/accounts",
      component: () => import("./pages/Accounts.vue"),
      meta: { title: "资金账户", group: "账务管理" },
    },
    {
      path: "/analysis",
      component: () => import("./pages/Analysis.vue"),
      meta: { title: "统计报表", group: "账务管理" },
    },
    {
      path: "/invoices",
      component: () => import("./pages/Invoices.vue"),
      meta: { title: "发票凭证", group: "账务管理" },
    },
    {
      path: "/team",
      component: () => import("./pages/Team.vue"),
      meta: { title: "账本成员", group: "团队与设置", admin: true },
    },
    {
      path: "/audit",
      component: () => import("./pages/Audit.vue"),
      meta: { title: "操作日志", group: "团队与设置", admin: true },
    },
    {
      path: "/settings",
      component: () => import("./pages/Settings.vue"),
      meta: { title: "账本设置", group: "团队与设置" },
    },
    { path: "/:pathMatch(.*)*", redirect: "/overview" },
  ],
  scrollBehavior: () => ({ top: 0 }),
});
router.onError(() => notify("页面暂时无法加载，请刷新页面后重试。", "error"));
createApp(App).use(router).mount("#app");
