<script setup>
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue'])

const operators = [
  { value: '>', label: '>' },
  { value: '>=', label: '>=' },
  { value: '<', label: '<' },
  { value: '<=', label: '<=' },
  { value: '==', label: '==' },
]

const fieldOptions = [
  { value: '_value', label: '主要值 (_value)' },
  { value: '_ohlcv.close', label: '收盘价' },
  { value: '_ohlcv.volume', label: '成交量' },
  { value: '_nav.unit_nav', label: '单位净值' },
]

function addRule() {
  const updated = [...props.modelValue, { field: '_value', operator: '>', threshold: '', label: '' }]
  emit('update:modelValue', updated)
}

function removeRule(index) {
  const updated = props.modelValue.filter((_, i) => i !== index)
  emit('update:modelValue', updated)
}

function updateRule(index, key, value) {
  const updated = [...props.modelValue]
  updated[index] = { ...updated[index], [key]: value }
  emit('update:modelValue', updated)
}

const inputClass = 'px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'px-2 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center justify-between">
      <label class="text-xs font-medium text-slate-600">告警规则 (可选)</label>
      <button
        type="button"
        class="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-medium text-indigo-600 hover:bg-indigo-50 rounded-md transition-colors"
        @click="addRule"
      >
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>
        添加规则
      </button>
    </div>

    <div v-if="!modelValue.length" class="text-xs text-slate-400 py-2">
      暂无告警规则。当采集的数据满足条件时会在数据中标记告警。
    </div>

    <div
      v-for="(rule, idx) in modelValue"
      :key="idx"
      class="flex items-center gap-2 p-2.5 bg-white border border-slate-200 rounded-xl"
    >
      <select :value="rule.field" @change="updateRule(idx, 'field', $event.target.value)" :class="selectClass" style="width: 110px;">
        <option v-for="f in fieldOptions" :key="f.value" :value="f.value">{{ f.label }}</option>
      </select>
      <select :value="rule.operator" @change="updateRule(idx, 'operator', $event.target.value)" :class="selectClass" style="width: 55px;">
        <option v-for="op in operators" :key="op.value" :value="op.value">{{ op.label }}</option>
      </select>
      <input
        :value="rule.threshold"
        @input="updateRule(idx, 'threshold', $event.target.value)"
        type="number"
        step="any"
        :class="inputClass"
        style="width: 90px;"
        placeholder="阈值"
      />
      <input
        :value="rule.label"
        @input="updateRule(idx, 'label', $event.target.value)"
        type="text"
        :class="[inputClass, 'flex-1']"
        placeholder="描述 (可选)"
      />
      <button
        type="button"
        class="p-1 text-slate-400 hover:text-rose-500 transition-colors shrink-0"
        @click="removeRule(idx)"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  </div>
</template>
