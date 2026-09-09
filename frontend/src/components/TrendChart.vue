<script setup>
import { computed } from "vue";
import { money } from "../lib/format";
const props = defineProps({
  points: { type: Array, default: () => [] },
  monthly: Boolean,
});
const maximum = computed(
  () =>
    Math.max(
      100,
      ...props.points.flatMap((p) => [Number(p.income), Number(p.expense)]),
    ) * 1.15,
);
const point = (item, index, key) =>
  `${35 + (index / Math.max(props.points.length - 1, 1)) * 590},${195 - (Number(item[key]) / maximum.value) * 175}`;
const path = (key) =>
  props.points
    .map((item, index) => (index ? "L" : "M") + point(item, index, key))
    .join(" ");
const ticks = computed(() =>
  [0, 1, 2, 3, 4].map((i) => ({
    y: 195 - i * 43.75,
    value: (maximum.value * i) / 4,
  })),
);
const hasData = computed(() =>
  props.points.some((p) => Number(p.income) || Number(p.expense)),
);
const axis = (value) =>
  value >= 10000
    ? (value / 10000).toFixed(1) + "万"
    : Math.round(value).toLocaleString();
</script>
<template>
  <div class="line-chart">
    <svg
      viewBox="0 0 650 230"
      role="img"
      :aria-label="monthly ? '近12个月收支趋势' : '本月每日收支趋势'"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="income-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#7391e4" stop-opacity=".12" />
          <stop offset="100%" stop-color="#7391e4" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g v-for="tick in ticks" :key="tick.y">
        <line
          x1="35"
          x2="625"
          :y1="tick.y"
          :y2="tick.y"
          stroke="#edf1f7"
          stroke-dasharray="3 4"
        />
        <text x="28" :y="tick.y + 3" text-anchor="end">
          {{ axis(tick.value) }}
        </text>
      </g>
      <template v-if="hasData">
        <path
          :d="path('income') + ' L625,195 L35,195 Z'"
          fill="url(#income-fill)"
        />
        <path
          :d="path('income')"
          fill="none"
          stroke="#6f8ce1"
          stroke-width="2.5"
          stroke-linejoin="round"
        />
        <path
          :d="path('expense')"
          fill="none"
          stroke="#6bc2ad"
          stroke-width="2.5"
          stroke-linejoin="round"
        />
        <g v-for="(p, i) in points" :key="i">
          <circle
            :cx="35 + (i / Math.max(points.length - 1, 1)) * 590"
            :cy="195 - (Number(p.income) / maximum) * 175"
            r="3"
            fill="#6f8ce1"
          >
            <title>{{ p.date || p.month }} 收入 ¥{{ money(p.income) }}</title>
          </circle>
          <circle
            :cx="35 + (i / Math.max(points.length - 1, 1)) * 590"
            :cy="195 - (Number(p.expense) / maximum) * 175"
            r="3"
            fill="#6bc2ad"
          >
            <title>{{ p.date || p.month }} 支出 ¥{{ money(p.expense) }}</title>
          </circle>
        </g>
      </template>
      <text v-else x="335" y="111" text-anchor="middle" style="font-size: 11px">
        审核通过的流水将在这里汇成趋势
      </text>
      <template v-for="(p, i) in points" :key="i">
        <text
          v-if="
            i === 0 ||
            i === points.length - 1 ||
            i % Math.ceil(points.length / 7) === 0
          "
          :x="35 + (i / Math.max(points.length - 1, 1)) * 590"
          y="222"
          text-anchor="middle"
        >
          {{
            monthly
              ? p.month.slice(5) + "月"
              : p.date.slice(5).replace("-", "/")
          }}
        </text>
      </template>
    </svg>
  </div>
</template>
