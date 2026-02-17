<script setup>
import { ref, watch, toRef } from 'vue'
import dayjs from 'dayjs'
import { getPipeline } from '@/api/pipelines'
import { formatTimeFull } from '@/utils/time'
import { useScrollLock } from '@/composables/useScrollLock'

const triggerLabels = {
  manual: '手动',
  scheduled: '定时',
  api: 'API',
  webhook: 'Webhook',
  favorite: '收藏',
}

const props = defineProps({
  visible: Boolean,
  pipelineId: { type: String, default: null },
})

const emit = defineEmits(['close'])
useScrollLock(toRef(props, 'visible'))

const detail = ref(null)
const loading = ref(false)

const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  running: 'bg-indigo-50 text-indigo-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
  skipped: 'bg-slate-50 text-slate-400',
  cancelled: 'bg-slate-100 text-slate-400',
}

const statusLabels = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  skipped: '已跳过',
  cancelled: '已取消',
}

const stepTypeLabels = {
  enrich_content: '内容富化',
  localize_media: '媒体本地化',
  extract_audio: '音频提取',
  transcribe_content: '语音转文字',
  translate_content: '内容翻译',
  analyze_content: '模型分析',
  publish_content: '消息推送',
}

const stepIconColors = {
  completed: 'bg-emerald-500 text-white',
  running: 'bg-indigo-500 text-white animate-pulse',
  failed: 'bg-rose-500 text-white',
  pending: 'bg-slate-200 text-slate-500',
  skipped: 'bg-slate-100 text-slate-400',
}

watch(() => props.visible, async (val) => {
  if (val && props.pipelineId) {
    loading.value = true
    try {
      const res = await getPipeline(props.pipelineId)
      if (res.code === 0) detail.value = res.data
    } finally {
      loading.value = false
    }
  }
})

function formatTime(t) {
  return formatTimeFull(t)
}

function formatDuration(startedAt, completedAt) {
  if (!startedAt || !completedAt) return null
  const start = dayjs.utc(startedAt)
  const end = dayjs.utc(completedAt)
  const seconds = end.diff(start, 'second')
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}时${m}分`
}

function formatOutput(data) {
  if (!data) return ''
  try {
    const parsed = typeof data === 'string' ? JSON.parse(data) : data
    return JSON.stringify(parsed, null, 2)
  } catch {
    return String(data)
  }
}
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="emit('close')"></div>
    <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
      <div class="sticky top-0 bg-white border-b border-slate-100 px-6 py-5 rounded-t-2xl flex items-center justify-between z-10">
        <div>
          <h3 class="text-lg font-semibold text-slate-900 tracking-tight">流水线详情</h3>
          <p v-if="detail" class="text-xs text-slate-400 mt-0.5">
            {{ detail.content_title || detail.content_id }} | {{ detail.template_name || '-' }}
          </p>
        </div>
        <button class="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-200" @click="emit('close')">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div v-if="loading" class="flex-1 flex items-center justify-center py-16">
        <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <div v-else-if="detail" class="flex-1 overflow-y-auto p-6">
        <!-- Summary -->
        <div class="grid grid-cols-2 gap-4 mb-6">
          <div class="bg-slate-50 rounded-xl p-4">
            <span class="text-xs text-slate-400 block mb-1">状态</span>
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md" :class="statusStyles[detail.status]">
              {{ statusLabels[detail.status] || detail.status }}
            </span>
          </div>
          <div class="bg-slate-50 rounded-xl p-4">
            <span class="text-xs text-slate-400 block mb-1">触发方式</span>
            <span class="text-sm text-slate-700 font-medium">{{ triggerLabels[detail.trigger_source] || detail.trigger_source }}</span>
          </div>
          <div class="bg-slate-50 rounded-xl p-4">
            <span class="text-xs text-slate-400 block mb-1">开始时间</span>
            <span class="text-sm text-slate-700">{{ formatTime(detail.started_at) }}</span>
          </div>
          <div class="bg-slate-50 rounded-xl p-4">
            <span class="text-xs text-slate-400 block mb-1">完成时间</span>
            <span class="text-sm text-slate-700">{{ formatTime(detail.completed_at) }}</span>
          </div>
        </div>

        <div v-if="detail.error_message" class="mb-6 p-4 bg-rose-50 border border-rose-100 rounded-xl text-sm text-rose-700 leading-relaxed">
          {{ detail.error_message }}
        </div>

        <!-- Steps Timeline -->
        <h4 class="text-sm font-semibold text-slate-700 mb-4 tracking-tight">步骤执行</h4>
        <div v-if="detail.steps.length === 0" class="text-sm text-slate-400 text-center py-8">无步骤记录</div>
        <div v-else class="space-y-3">
          <div
            v-for="(step, idx) in detail.steps"
            :key="step.id"
            class="flex items-start gap-4 p-4 rounded-xl border transition-all duration-200"
            :class="step.status === 'failed' ? 'border-rose-200 bg-rose-50/30' : 'border-slate-100 hover:border-slate-200'"
          >
            <div
              class="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
              :class="stepIconColors[step.status] || 'bg-slate-200 text-slate-500'"
            >
              {{ step.step_index + 1 }}
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-medium text-slate-800">{{ stepTypeLabels[step.step_type] || step.step_type }}</span>
                <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md" :class="statusStyles[step.status]">
                  {{ statusLabels[step.status] || step.status }}
                </span>
                <span v-if="step.is_critical" class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md bg-rose-50 text-rose-600">关键</span>
              </div>
              <div class="flex items-center gap-2 text-xs text-slate-400 mt-1.5">
                <span>{{ formatTime(step.started_at) }} ~ {{ formatTime(step.completed_at) }}</span>
                <span v-if="formatDuration(step.started_at, step.completed_at)" class="inline-flex px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded font-medium">
                  {{ formatDuration(step.started_at, step.completed_at) }}
                </span>
              </div>
              <div v-if="step.error_message" class="text-xs text-rose-600 mt-1.5 bg-rose-50 rounded-lg px-2 py-1">{{ step.error_message }}</div>
              <details v-if="step.output_data" class="mt-2">
                <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-600 transition-colors">查看输出</summary>
                <pre class="mt-1.5 text-xs text-slate-500 bg-slate-50 rounded-lg p-2.5 overflow-x-auto max-h-40 overflow-y-auto border border-slate-100 leading-relaxed">{{ formatOutput(step.output_data) }}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
