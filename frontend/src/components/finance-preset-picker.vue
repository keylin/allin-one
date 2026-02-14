<script setup>
import { ref, computed, onMounted } from 'vue'
import { getFinancePresets } from '@/api/finance'

const props = defineProps({
  modelValue: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'select'])

const presets = ref({})
const loading = ref(true)
const activeCategory = ref('macro')
const showCustom = ref(false)

const categories = computed(() =>
  Object.entries(presets.value).map(([key, val]) => ({
    key,
    label: val.label,
    count: val.indicators?.length || 0,
  }))
)

const indicators = computed(() =>
  presets.value[activeCategory.value]?.indicators || []
)

onMounted(async () => {
  try {
    const res = await getFinancePresets()
    if (res.code === 0) {
      presets.value = res.data
    }
  } catch { /* ignore */ }
  loading.value = false
})

function selectPreset(preset) {
  const now = new Date()
  const oneYearAgo = `${now.getFullYear() - 1}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`

  // Build config from preset
  const config = {
    indicator: preset.indicator,
    category: activeCategory.value,
    params: { ...preset.params },
    title_field: preset.title_field || '',
    id_fields: preset.id_fields || [],
    date_field: preset.date_field || '',
    max_history: preset.max_history || 120,
  }

  // Copy specialized fields
  if (preset.value_field) config.value_field = preset.value_field
  if (preset.ohlcv_fields) config.ohlcv_fields = preset.ohlcv_fields
  if (preset.nav_fields) config.nav_fields = preset.nav_fields

  // Auto-fill start_date for stock/fund
  if (config.params.start_date === '') {
    config.params.start_date = oneYearAgo
  }

  emit('select', {
    config,
    name: preset.label,
    schedule_interval: preset.schedule_interval || 3600,
    user_params: preset.user_params || [],
  })
}

function selectCustom() {
  showCustom.value = true
  emit('select', {
    config: {
      indicator: '',
      category: '',
      params: {},
      title_field: '',
      id_fields: [],
      date_field: '',
      max_history: 120,
    },
    name: '',
    schedule_interval: 3600,
    user_params: [],
    isCustom: true,
  })
}

const categoryIcons = {
  macro: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
  stock: 'M3 3v18h18 M7 16l4-4 3 3 5-6',
  fund: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1',
}
</script>

<template>
  <div class="space-y-4">
    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-8">
      <svg class="w-5 h-5 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <template v-else>
      <!-- Category tabs -->
      <div class="flex items-center gap-1 p-1 bg-slate-100 rounded-lg">
        <button
          v-for="cat in categories"
          :key="cat.key"
          type="button"
          class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200"
          :class="activeCategory === cat.key
            ? 'bg-white text-slate-700 shadow-sm'
            : 'text-slate-500 hover:text-slate-700'"
          @click="activeCategory = cat.key"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" :d="categoryIcons[cat.key] || categoryIcons.macro" />
          </svg>
          {{ cat.label }}
        </button>
      </div>

      <!-- Preset cards -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <button
          v-for="preset in indicators"
          :key="preset.key"
          type="button"
          class="text-left p-3 rounded-xl border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/30 transition-all duration-200 group"
          @click="selectPreset(preset)"
        >
          <div class="flex items-center gap-2">
            <div class="w-6 h-6 rounded-md bg-slate-50 group-hover:bg-indigo-50 flex items-center justify-center shrink-0 transition-colors">
              <svg class="w-3 h-3 text-slate-400 group-hover:text-indigo-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" :d="categoryIcons[activeCategory] || categoryIcons.macro" />
              </svg>
            </div>
            <div class="min-w-0">
              <div class="text-xs font-medium text-slate-700 group-hover:text-indigo-700 truncate transition-colors">{{ preset.label }}</div>
              <div class="text-[10px] text-slate-400 truncate">{{ preset.indicator }}</div>
            </div>
          </div>
          <div v-if="preset.user_params && preset.user_params.length" class="mt-1.5 flex items-center gap-1">
            <span v-for="p in preset.user_params" :key="p" class="inline-flex px-1.5 py-0.5 bg-amber-50 text-amber-600 text-[10px] font-medium rounded">
              需填: {{ p }}
            </span>
          </div>
        </button>

        <!-- Custom option -->
        <button
          type="button"
          class="text-left p-3 rounded-xl border border-dashed border-slate-300 hover:border-indigo-400 hover:bg-slate-50 transition-all duration-200 group"
          @click="selectCustom"
        >
          <div class="flex items-center gap-2">
            <div class="w-6 h-6 rounded-md bg-slate-50 flex items-center justify-center shrink-0">
              <svg class="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
              </svg>
            </div>
            <div>
              <div class="text-xs font-medium text-slate-500">自定义指标</div>
              <div class="text-[10px] text-slate-400">手动填写 akshare 函数名</div>
            </div>
          </div>
        </button>
      </div>
    </template>
  </div>
</template>
