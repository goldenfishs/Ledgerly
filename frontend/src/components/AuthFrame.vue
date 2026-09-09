<script setup>
import { BookOpen } from "lucide-vue-next";
import { state } from "../lib/app";
defineProps({ title: String, description: String });
</script>
<template>
  <main class="auth-frame">
    <header class="auth-brand">
      <RouterLink
        to="/login"
        :title="state.siteName"
        :aria-label="`${state.siteName}，返回登录`"
        ><span><BookOpen :size="21" /></span
        ><strong
          >{{ state.siteName
          }}<small v-if="state.siteName === '账序'">Ledgerly</small></strong
        ></RouterLink
      >
    </header>
    <section class="auth-card">
      <div class="auth-card-heading">
        <slot name="icon" />
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
      <slot />
    </section>
    <p class="auth-footer">清晰记录，从容协作</p>
  </main>
</template>
<style scoped>
.auth-frame {
  min-height: 100dvh;
  padding: 30px 28px;
  background:
    radial-gradient(ellipse at 15% 0, #f0ebfb99, transparent 45%),
    radial-gradient(ellipse at 90% 90%, #eaf4ee88, transparent 40%), #f9f9fc;
}
.auth-brand {
  max-width: 1160px;
  margin: auto;
}
.auth-brand a {
  display: inline-flex;
  max-width: 100%;
  min-width: 0;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}
.auth-brand a > span {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  height: 37px;
  width: 37px;
  border-radius: 11px;
  color: #8a75c5;
  background: #efeafa;
}
.auth-brand strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 18px;
  font-weight: 600;
  color: #625976;
}
.auth-brand small {
  margin-left: 10px;
  font-size: 11px;
  color: #a296b5;
  font-weight: 400;
}
.auth-card {
  width: 460px;
  max-width: 100%;
  margin: 35px auto 0;
  padding: 30px 35px;
  border: 1px solid #eae5f1;
  border-radius: 20px;
  box-shadow: 0 12px 36px #8874a007;
  background: #fff;
}
.auth-card-heading {
  margin-bottom: 27px;
}
.auth-card-heading h1 {
  font-size: 25px;
  letter-spacing: -0.4px;
  font-weight: 600;
  margin: 17px 0 10px;
  color: #51455f;
}
.auth-card-heading p {
  color: #928699;
  font-size: 12px;
  line-height: 1.85;
  margin: 0;
}
.auth-footer {
  text-align: center;
  color: #ada3b6;
  font-size: 11px;
  margin: 23px 0 0;
}
@media (max-width: 520px) {
  .auth-frame {
    padding: 22px 16px;
  }
  .auth-card {
    margin-top: 26px;
    padding: 26px 23px;
  }
  .auth-card-heading h1 {
    font-size: 23px;
  }
}
</style>
