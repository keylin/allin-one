<script setup>
const props = defineProps({
  form: { type: Object, required: true },
  fieldErrors: { type: Object, required: true },
  isDirty: { type: Boolean, required: true },
  groupSaving: { type: Boolean, required: false, default: false },
})

const emit = defineEmits(['update:form', 'save', 'validate-field'])

// Group definition
const group = {
  title: '智能调度',
  icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z',
  color: 'text-violet-500 bg-violet-50',
  keys: [
    {
      key: 'schedule_min_interval',
      label: '最小采集间隔（秒）',
      type: 'number',
      description: '防止过度抓取的保护下限，推荐值 300（5分钟）'
    },
    {
      key: 'schedule_max_interval',
      label: '最大采集间隔（秒）',
      type: 'number',
      description: '确保数据源每天至少检查一次，推荐值 86400（24小时）'
    },
    {
      key: 'schedule_base_interval',
      label: '基础采集间隔（秒）',
      type: 'number',
      description: '用于新源和中等活跃源的默认间隔，推荐值 3600（1小时）'
    },
    {
      key: 'schedule_lookback_window',
      label: '历史统计窗口',
      type: 'number',
      description: '计算活跃度时统计最近 N 次采集记录，推荐值 10（范围 3-50）'
    },
    {
      key: 'schedule_activity_high',
      label: '高活跃阈值',
      type: 'number',
      description: '新增内容均值超过此值视为高活跃，缩短采集间隔（推荐值 5.0）'
    },
    {
      key: 'schedule_activity_medium',
      label: '中活跃阈值',
      type: 'number',
      description: '新增内容均值超过此值视为中活跃（推荐值 2.0）'
    },
    {
      key: 'schedule_activity_low',
      label: '低活跃阈值',
      type: 'number',
      description: '新增内容均值低于此值视为低活跃，延长采集间隔（推荐值 0.5）'
    },
  ],
}

function updateField(key, value) {
  emit('update:form', { ...props.form, [key]: value })
}
</script>

<template>
  <div class="px-4 py-4 max-w-3xl">
    <!-- 分组标题 -->
    <div class="flex items-center gap-3 mb-5">
      <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="group.color">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" :d="group.icon" />
        </svg>
      </div>
      <h3 class="text-sm font-semibold text-slate-800">{{ group.title }}</h3>
    </div>

    <div class="space-y-5">
      <!-- 表单字段 -->
      <div v-for="item in group.keys" :key="item.key">
        <label class="block text-sm font-medium text-slate-700 mb-1.5">{{ item.label }}</label>
        <div class="relative">
          <input
            :value="form[item.key]"
            type="number"
            :placeholder="item.description"
            class="w-full px-3.5 py-2.5 bg-white border rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 outline-none transition-all duration-200"
            :class="fieldErrors[item.key]
              ? 'border-rose-300 focus:ring-rose-500/20 focus:border-rose-400'
              : 'border-slate-200 focus:ring-indigo-500/20 focus:border-indigo-400'"
            @input="updateField(item.key, $event.target.value)"
            @blur="$emit('validate-field', item.key, item.type)"
          />
        </div>
        <!-- 字段错误 -->
        <p v-if="fieldErrors[item.key]" class="mt-1.5 text-xs text-rose-500">{{ fieldErrors[item.key] }}</p>
        <p v-else class="mt-1.5 text-xs text-slate-400">{{ item.description }}</p>
      </div>
    </div>

    <!-- 算法说明区域 -->
    <div class="mt-6 pt-5 border-t border-slate-100">
      <div class="flex items-start gap-3 p-4 bg-violet-50/50 rounded-xl border border-violet-100">
        <div class="shrink-0 mt-0.5">
          <svg class="w-5 h-5 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <h4 class="text-sm font-semibold text-violet-900 mb-1.5">智能调度算法说明</h4>
          <div class="text-xs text-violet-700 leading-relaxed space-y-1">
            <p>系统根据数据源的历史采集记录（新增内容数量、成功率、趋势）自动计算下次采集间隔：</p>
            <ul class="list-disc list-inside space-y-0.5 ml-2">
              <li><strong>高活跃源</strong>（新增 ≥ 5）：缩短间隔至 50%，快速抓取</li>
              <li><strong>中活跃源</strong>（新增 2-5）：缩短间隔至 75%</li>
              <li><strong>低活跃源</strong>（新增 < 0.5）：延长间隔至 150%，节省资源</li>
              <li><strong>失败退避</strong>：连续失败时指数延长间隔（2^n 倍），最高至 24 小时</li>
            </ul>
            <p class="mt-2 text-violet-600">修改这些参数会影响所有设为「自动调度」模式的数据源。</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 分组保存按钮 -->
    <div class="mt-6 pt-4 border-t border-slate-100">
      <button
        class="px-5 py-2.5 text-sm font-medium text-white rounded-xl shadow-sm transition-all duration-200 disabled:opacity-50"
        :class="isDirty
          ? 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 shadow-indigo-200'
          : 'bg-slate-300 cursor-not-allowed'"
        :disabled="groupSaving || !isDirty"
        @click="$emit('save')"
      >
        <span class="flex items-center gap-1.5">
          <svg v-if="groupSaving" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {{ groupSaving ? '保存中...' : '保存智能调度' }}
        </span>
      </button>
    </div>
  </div>
</template>
