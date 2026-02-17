<script setup>
import { ref, watch } from 'vue'
import dayjs from 'dayjs'
import { getPipeline, cancelPipeline, retryPipeline } from '@/api/pipelines'
import { formatTimeFull } from '@/utils/time'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  pipelineId: { type: String, default: null },
})

const emit = defineEmits(['cancel', 'retry'])
const toast = useToast()

const detail = ref(null)
const loading = ref(false)

const triggerLabels = {
  manual: '手动',
  scheduled: '定时',
  api: 'API',
  webhook: 'Webhook',
  favorite: '收藏',
}

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

watch(() => props.pipelineId, async (newId) => {
  if (newId) {
    loading.value = true
    detail.value = null
    try {
      const res = await getPipeline(newId)
      if (res.code === 0) detail.value = res.data
    } finally {
      loading.value = false
    }
  } else {
    detail.value = null
  }
}, { immediate: true })

async function handleCancel() {
  if (!detail.value) return
  const res = await cancelPipeline(detail.value.id)
  if (res.code === 0) {
    toast.success('流水线已取消')
    emit('cancel')
    // Refresh detail
    const refreshRes = await getPipeline(detail.value.id)
    if (refreshRes.code === 0) detail.value = refreshRes.data
  }
}

async function handleRetry() {
  if (!detail.value) return
  try {
    const res = await retryPipeline(detail.value.id)
    if (res.code === 0) {
      toast.success(res.message || '流水线已重试')
      emit('retry')
    } else {
      toast.error(res.message || '重试失败')
    }
  } catch {
    toast.error('重试请求失败')
  }
}

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
  <template v-if="pipelineId">
    <!-- Loading -->
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <template v-else-if="detail">
      <!-- Scrollable content -->
      <div class="flex-1 overflow-y-auto p-6 space-y-5">
        <!-- Header -->
        <div>
          <h2 class="text-xl font-bold text-slate-900 mb-1">{{ detail.content_title || detail.content_id }}</h2>
          <p class="text-sm text-slate-400">{{ detail.template_name || '无模板' }}</p>
        </div>

        <!-- Summary grid -->
        <div class="grid grid-cols-2 gap-3">
          <div class="bg-slate-50 rounded-xl p-3.5">
            <span class="text-xs text-slate-400 block mb-1">状态</span>
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md" :class="statusStyles[detail.status]">
              {{ statusLabels[detail.status] || detail.status }}
            </span>
          </div>
          <div class="bg-slate-50 rounded-xl p-3.5">
            <span class="text-xs text-slate-400 block mb-1">触发方式</span>
            <span class="text-sm text-slate-700 font-medium">{{ triggerLabels[detail.trigger_source] || detail.trigger_source }}</span>
          </div>
          <div class="bg-slate-50 rounded-xl p-3.5">
            <span class="text-xs text-slate-400 block mb-1">开始时间</span>
            <span class="text-sm text-slate-700">{{ formatTime(detail.started_at) }}</span>
          </div>
          <div class="bg-slate-50 rounded-xl p-3.5">
            <span class="text-xs text-slate-400 block mb-1">完成时间</span>
            <span class="text-sm text-slate-700">{{ formatTime(detail.completed_at) }}</span>
          </div>
        </div>

        <!-- Error -->
        <div v-if="detail.error_message" class="p-4 bg-rose-50 border border-rose-100 rounded-xl text-sm text-rose-700 leading-relaxed">
          {{ detail.error_message }}
        </div>

        <!-- Steps Timeline -->
        <div>
          <h3 class="text-sm font-semibold text-slate-700 mb-3">步骤执行</h3>
          <div v-if="detail.steps.length === 0" class="text-sm text-slate-400 text-center py-6">无步骤记录</div>
          <div v-else class="space-y-2.5">
            <div
              v-for="step in detail.steps"
              :key="step.id"
              class="flex items-start gap-3 p-3.5 rounded-xl border transition-all duration-200"
              :class="step.status === 'failed' ? 'border-rose-200 bg-rose-50/30' : 'border-slate-100 hover:border-slate-200'"
            >
              <div
                class="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
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
                <div class="flex items-center gap-2 text-xs text-slate-400 mt-1">
                  <span>{{ formatTime(step.started_at) }} ~ {{ formatTime(step.completed_at) }}</span>
                  <span v-if="formatDuration(step.started_at, step.completed_at)" class="inline-flex px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded font-medium">
                    {{ formatDuration(step.started_at, step.completed_at) }}
                  </span>
                </div>
                <div v-if="step.error_message" class="text-xs text-rose-600 mt-1.5 bg-rose-50 rounded-lg px-2 py-1">{{ step.error_message }}</div>
                <details v-if="step.output_data" class="mt-1.5">
                  <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-600 transition-colors">查看输出</summary>
                  <pre class="mt-1 text-xs text-slate-500 bg-slate-50 rounded-lg p-2 overflow-x-auto max-h-36 overflow-y-auto border border-slate-100 leading-relaxed">{{ formatOutput(step.output_data) }}</pre>
                </details>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Action bar -->
      <div class="flex items-center gap-2 px-6 py-3 border-t border-slate-100 shrink-0 bg-white">
        <button
          v-if="detail.status === 'running' || detail.status === 'pending'"
          class="px-4 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
          @click="handleCancel"
        >
          取消
        </button>
        <button
          v-if="detail.status === 'failed'"
          class="px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
          @click="handleRetry"
        >
          重试
        </button>
        <span class="text-xs text-slate-400 ml-auto">
          {{ detail.current_step }}/{{ detail.total_steps }} 步
        </span>
      </div>
    </template>
  </template>
</template>
