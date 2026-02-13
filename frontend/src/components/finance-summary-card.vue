<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, required: true },
  value: { type: Number, default: null },
  date: { type: String, default: null },
  change: { type: Number, default: null },
  category: { type: String, default: 'macro' },
  active: { type: Boolean, default: false },
})

defineEmits(['click'])

const displayValue = computed(() => {
  if (props.value === null || props.value === undefined) return '-'
  // Compact large numbers
  if (Math.abs(props.value) >= 1e8) return (props.value / 1e8).toFixed(2) + '亿'
  if (Math.abs(props.value) >= 1e4) return (props.value / 1e4).toFixed(2) + '万'
  // Keep reasonable precision
  if (Math.abs(props.value) < 10) return props.value.toFixed(4)
  if (Math.abs(props.value) < 1000) return props.value.toFixed(2)
  return props.value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
})

const changeDisplay = computed(() => {
  if (props.change === null || props.change === undefined) return null
  const sign = props.change > 0 ? '+' : ''
  if (Math.abs(props.change) >= 1e4) return sign + (props.change / 1e4).toFixed(2) + '万'
  if (Math.abs(props.change) < 0.01) return sign + props.change.toFixed(4)
  return sign + props.change.toFixed(2)
})

const isUp = computed(() => props.change !== null && props.change > 0)
const isDown = computed(() => props.change !== null && props.change < 0)

const categoryIcons = {
  macro: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
  stock: 'M3 3v18h18 M7 16l4-4 3 3 5-6',
  fund: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1',
}
</script>

<template>
  <div
    class="group relative bg-white rounded-xl border p-4 cursor-pointer transition-all duration-200 hover:shadow-md"
    :class="active
      ? 'border-indigo-300 shadow-sm shadow-indigo-100 ring-1 ring-indigo-200'
      : 'border-slate-200/60 hover:border-slate-300'"
    @click="$emit('click')"
  >
    <div class="flex items-start justify-between mb-2">
      <div class="flex items-center gap-2 min-w-0">
        <div class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
          :class="active ? 'bg-indigo-50' : 'bg-slate-50 group-hover:bg-slate-100'"
        >
          <svg class="w-3.5 h-3.5" :class="active ? 'text-indigo-500' : 'text-slate-400'" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" :d="categoryIcons[category] || categoryIcons.macro" />
          </svg>
        </div>
        <span class="text-xs font-medium text-slate-600 truncate">{{ name }}</span>
      </div>
    </div>

    <div class="flex items-end justify-between">
      <div>
        <div class="text-lg font-bold tracking-tight text-slate-900">{{ displayValue }}</div>
        <div class="flex items-center gap-1.5 mt-0.5">
          <span
            v-if="changeDisplay !== null"
            class="text-xs font-medium"
            :class="isUp ? 'text-red-500' : isDown ? 'text-emerald-500' : 'text-slate-400'"
          >
            <span v-if="isUp">&#9650;</span>
            <span v-else-if="isDown">&#9660;</span>
            {{ changeDisplay }}
          </span>
          <span v-if="date" class="text-[10px] text-slate-300">{{ date }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
