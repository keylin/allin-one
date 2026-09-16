<script setup>
import { computed, ref } from 'vue'

/**
 * 五星评分（支持半星），底层数据是 1~10 的整数：整星 = 2n，半星 = 2n-1。
 * 点星的左半边给半星、右半边给整星；再点当前值即清除。
 */
const props = defineProps({
  modelValue: { type: Number, default: null },   // 1~10 或 null
  size: { type: String, default: 'sm' },          // xs / sm / md / lg
  readonly: { type: Boolean, default: false },
  showValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const hover = ref(null) // 悬停预览值（1~10）

const sizeClass = computed(() => ({ xs: 'w-3 h-3', sm: 'w-3.5 h-3.5', md: 'w-5 h-5', lg: 'w-7 h-7' }[props.size] || 'w-3.5 h-3.5'))
const shown = computed(() => hover.value ?? props.modelValue ?? 0)

function fillOf(star) {
  const v = shown.value
  if (v >= star * 2) return 'full'
  if (v === star * 2 - 1) return 'half'
  return 'empty'
}

function valueFromEvent(star, event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const x = (event.clientX ?? rect.left + rect.width) - rect.left
  return x < rect.width / 2 ? star * 2 - 1 : star * 2
}

function onMove(star, event) {
  if (props.readonly) return
  hover.value = valueFromEvent(star, event)
}

function onLeave() {
  hover.value = null
}

function onClick(star, event) {
  if (props.readonly) return
  const v = valueFromEvent(star, event)
  hover.value = null
  emit('update:modelValue', v === props.modelValue ? null : v)
}
</script>

<template>
  <span class="inline-flex items-center gap-0.5" :class="readonly ? '' : 'cursor-pointer'" @mouseleave="onLeave">
    <span
      v-for="star in 5"
      :key="star"
      class="relative inline-block"
      :class="sizeClass"
      @mousemove="onMove(star, $event)"
      @click.stop="onClick(star, $event)"
    >
      <!-- 底层空星 -->
      <svg class="absolute inset-0 w-full h-full text-slate-200" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.5l2.9 6.2 6.8.8-5 4.7 1.3 6.8L12 17.7 5.9 21l1.4-6.8-5-4.7 6.8-.8z" /></svg>
      <!-- 填充（整星或左半） -->
      <svg
        v-if="fillOf(star) !== 'empty'"
        class="absolute inset-0 w-full h-full text-amber-400"
        :style="fillOf(star) === 'half' ? 'clip-path: inset(0 50% 0 0)' : ''"
        viewBox="0 0 24 24" fill="currentColor"
      ><path d="M12 2.5l2.9 6.2 6.8.8-5 4.7 1.3 6.8L12 17.7 5.9 21l1.4-6.8-5-4.7 6.8-.8z" /></svg>
    </span>
    <span v-if="showValue && (modelValue || hover)" class="ml-1 text-[11px] text-slate-400 tabular-nums">{{ (shown / 2).toFixed(1).replace('.0', '') }} / 5</span>
  </span>
</template>
