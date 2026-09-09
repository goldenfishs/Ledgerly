<script setup>
import { computed } from "vue";
import { money } from "../lib/format";
const props = defineProps({ items: { type: Array, default: () => [] } });
const colors = [
  "#6e8ae0",
  "#81c6b2",
  "#d6b383",
  "#a59aca",
  "#e4a195",
  "#94b8d2",
];
const total = computed(() =>
  props.items.reduce((a, c) => a + Number(c.amount), 0),
);
const segments = computed(() => {
  let start = 0;
  return props.items.map((item, i) => {
    const percent = (Number(item.amount) / total.value) * 100;
    const itemResult = {
      ...item,
      color: colors[i % colors.length],
      percent,
      start,
    };
    start += percent;
    return itemResult;
  });
});
const gradient = computed(() =>
  total.value
    ? "conic-gradient(" +
      segments.value
        .map((s) => `${s.color} ${s.start}% ${s.start + s.percent}%`)
        .join(",") +
      ")"
    : "#edf1f7",
);
</script>
<template>
  <div class="category-chart">
    <div class="donut-wrap">
      <div
        class="donut"
        :style="{ background: gradient }"
        role="img"
        :aria-label="'支出分类占比，总支出' + money(total) + '元'"
      >
        <div class="donut-hole">
          <span>本月总支出</span
          ><strong><small>¥</small>{{ money(total) }}</strong
          ><small>{{ items.length }} 个支出分类</small>
        </div>
      </div>
    </div>
    <div v-if="!items.length" class="category-empty">暂无已审核的支出记录</div>
    <div v-else class="category-legend">
      <div v-for="(item, i) in segments.slice(0, 5)" :key="item.id || i">
        <i :style="{ background: item.color }"></i><span>{{ item.name }}</span
        ><b>{{ item.percent.toFixed(1) }}%</b
        ><small>¥{{ money(item.amount) }}</small>
      </div>
      <p v-if="items.length > 5" class="muted small">
        另有 {{ items.length - 5 }} 个分类，详见统计报表
      </p>
    </div>
  </div>
</template>
<style scoped>
.category-chart {
  padding: 20px 25px 24px;
}
.donut-wrap {
  display: flex;
  justify-content: center;
  padding: 0 0 22px;
}
.donut {
  width: 170px;
  height: 170px;
  border-radius: 50%;
  padding: 20px;
  transform: rotate(-90deg);
}
.donut-hole {
  background: white;
  height: 100%;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  transform: rotate(90deg);
}
.donut-hole > span {
  font-size: 9px;
  color: #98a4b5;
}
.donut-hole > strong {
  font-size: 19px;
  font-weight: 600;
  color: #485873;
  letter-spacing: -0.5px;
  margin: 9px 0 7px;
}
.donut-hole strong small {
  font-size: 12px;
  margin-right: 3px;
  font-weight: 400;
  color: #9aa7ba;
}
.donut-hole > small {
  font-size: 8px;
  color: #afb7c5;
}
.category-legend {
  display: grid;
  gap: 12px;
}
.category-legend > div {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
}
.category-legend i {
  width: 6px;
  height: 6px;
  border-radius: 2px;
}
.category-legend span {
  color: #78859b;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.category-legend b {
  color: #8d99ac;
  font-weight: 400;
  width: 38px;
}
.category-legend small {
  color: #6f7d94;
  font-size: 10px;
  min-width: 66px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.category-empty {
  text-align: center;
  color: #a9b3c3;
  font-size: 11px;
  padding: 9px 0 20px;
}
</style>
