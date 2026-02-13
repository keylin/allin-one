<script setup>
import { ref, watch, computed } from 'vue'
import dayjs from 'dayjs'
import { getCollectionHistory } from '@/api/sources'

const props = defineProps({
  source: { type: Object, default: null },
  collectingId: { type: [String, null], default: null },
  togglingId: { type: [String, null], default: null },
})

const emit = defineEmits(['edit', 'delete', 'toggle-active', 'collect', 'history-page'])

const historyRecords = ref([])
const historyLoading = ref(false)
const historyPage = ref(1)
const historyPageSize = 10
const historyTotal = ref(0)

const mediaTypeLabels = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
  mixed: '混合',
  data: '数据',
}

const typeLabels = {
  'rss.hub': 'RSSHub',
  'rss.standard': 'RSS/Atom',
  'api.akshare': 'AkShare',
  'web.scraper': '网页抓取',
  'file.upload': '文件上传',
  'account.bilibili': 'B站账号',
  'account.generic': '其他账号',
  'user.note': '用户笔记',
  'system.notification': '系统通知',
}

const typeStyles = {
  'rss.hub': 'bg-orange-50 text-orange-700',
  'rss.standard': 'bg-amber-50 text-amber-700',
  'api.akshare': 'bg-violet-50 text-violet-700',
  'web.scraper': 'bg-cyan-50 text-cyan-700',
  'file.upload': 'bg-slate-100 text-slate-600',
  'account.bilibili': 'bg-pink-50 text-pink-700',
  'account.generic': 'bg-indigo-50 text-indigo-700',
  'user.note': 'bg-emerald-50 text-emerald-700',
  'system.notification': 'bg-sky-50 text-sky-700',
}

watch(() => props.source?.id, async (newId) => {
  if (newId) {
    historyPage.value = 1
    await fetchHistory()
  } else {
    historyRecords.value = []
    historyTotal.value = 0
  }
}, { immediate: true })

async function fetchHistory() {
  if (!props.source?.id) return
  historyLoading.value = true
  try {
    const res = await getCollectionHistory(props.source.id, {
      page: historyPage.value,
      page_size: historyPageSize,
    })
    if (res.code === 0) {
      historyRecords.value = res.data
      historyTotal.value = res.total
    }
  } catch { /* ignore */ }
  finally {
    historyLoading.value = false
  }
}

function goToHistoryPage(page) {
  const totalPages = Math.max(1, Math.ceil(historyTotal.value / historyPageSize))
  if (page < 1 || page > totalPages) return
  historyPage.value = page
  fetchHistory()
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm') : '-'
}

function formatInterval(seconds) {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
  return `${Math.round(seconds / 3600)}小时`
}
</script>

<template>
  <template v-if="source">
    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto p-6 space-y-6">
      <!-- Header -->
      <div>
        <div class="flex items-center gap-3 mb-2">
          <h2 class="text-xl font-bold text-slate-900">{{ source.name }}</h2>
          <span
            class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg"
            :class="source.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'"
          >
            {{ source.is_active ? '活跃' : '停用' }}
          </span>
        </div>
        <p v-if="source.description" class="text-sm text-slate-500 leading-relaxed">{{ source.description }}</p>
      </div>

      <!-- Info grid -->
      <div class="grid grid-cols-2 gap-4">
        <div class="bg-slate-50 rounded-xl p-4">
          <span class="text-xs text-slate-400 block mb-1">类型</span>
          <span
            class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg"
            :class="typeStyles[source.source_type] || 'bg-slate-100 text-slate-600'"
          >
            {{ typeLabels[source.source_type] || source.source_type }}
          </span>
        </div>
        <div class="bg-slate-50 rounded-xl p-4">
          <span class="text-xs text-slate-400 block mb-1">调度</span>
          <span v-if="source.schedule_enabled" class="text-sm text-slate-700 font-medium">
            每 {{ formatInterval(source.schedule_interval) }}
          </span>
          <span v-else class="text-sm text-slate-400">已禁用</span>
        </div>
        <div class="bg-slate-50 rounded-xl p-4">
          <span class="text-xs text-slate-400 block mb-1">流水线模板</span>
          <span class="text-sm text-slate-700 font-medium">{{ source.pipeline_template_name || '未绑定' }}</span>
          <div v-if="source.pipeline_routing_names && Object.keys(source.pipeline_routing_names).length" class="mt-2 space-y-1">
            <div v-for="(name, mt) in source.pipeline_routing_names" :key="mt" class="flex items-center gap-2">
              <span class="inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded bg-indigo-50 text-indigo-600">{{ mediaTypeLabels[mt] || mt }}</span>
              <span class="text-xs text-slate-500">{{ name }}</span>
            </div>
          </div>
        </div>
        <div class="bg-slate-50 rounded-xl p-4">
          <span class="text-xs text-slate-400 block mb-1">最近采集</span>
          <span class="text-sm text-slate-700">{{ formatTime(source.last_collected_at) }}</span>
        </div>
      </div>

      <!-- URL -->
      <div v-if="source.url" class="bg-slate-50 rounded-xl p-4">
        <span class="text-xs text-slate-400 block mb-1">URL</span>
        <a :href="source.url" target="_blank" class="text-sm text-indigo-600 hover:underline break-all">
          {{ source.url }}
        </a>
      </div>

      <!-- Collection history -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-slate-700">采集历史</h3>
          <span v-if="historyTotal > 0" class="text-xs text-slate-400">共 {{ historyTotal }} 条</span>
        </div>

        <div v-if="historyLoading" class="flex items-center justify-center py-8">
          <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <div v-else-if="historyRecords.length === 0" class="text-center py-8">
          <p class="text-sm text-slate-400">暂无采集记录</p>
        </div>

        <div v-else class="space-y-2">
          <div v-for="record in historyRecords" :key="record.id" class="p-3 bg-slate-50 rounded-lg border border-slate-100">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-xs font-medium" :class="record.status === 'completed' ? 'text-emerald-600' : record.status === 'failed' ? 'text-rose-600' : 'text-slate-600'">
                {{ record.status === 'completed' ? '成功' : record.status === 'failed' ? '失败' : '采集中' }}
              </span>
              <span class="text-xs text-slate-400">{{ formatTime(record.started_at) }}</span>
            </div>
            <div class="flex items-center gap-4 text-xs text-slate-500">
              <span>发现 {{ record.items_found || 0 }} 条</span>
              <span class="text-emerald-600">新增 {{ record.items_new || 0 }} 条</span>
            </div>
            <div v-if="record.error_message" class="mt-1.5 text-xs text-rose-500 truncate">{{ record.error_message }}</div>
          </div>

          <!-- History pagination -->
          <div v-if="historyTotal > historyPageSize" class="flex items-center justify-between pt-2">
            <span class="text-xs text-slate-400">{{ historyPage }}/{{ Math.ceil(historyTotal / historyPageSize) }}</span>
            <div class="flex gap-1.5">
              <button
                :disabled="historyPage <= 1"
                @click="goToHistoryPage(historyPage - 1)"
                class="px-2.5 py-1 text-xs border border-slate-200 rounded-lg disabled:opacity-40 transition-all"
              >上一页</button>
              <button
                :disabled="historyPage >= Math.ceil(historyTotal / historyPageSize)"
                @click="goToHistoryPage(historyPage + 1)"
                class="px-2.5 py-1 text-xs border border-slate-200 rounded-lg disabled:opacity-40 transition-all"
              >下一页</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Action bar -->
    <div class="flex items-center gap-2 px-6 py-3 border-t border-slate-100 shrink-0 bg-white">
      <button
        class="px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors disabled:opacity-50"
        :disabled="collectingId === source.id"
        @click="emit('collect', source)"
      >
        <span v-if="collectingId === source.id" class="flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>
          采集中
        </span>
        <span v-else>立即采集</span>
      </button>
      <button
        class="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
        @click="emit('edit', source)"
      >
        编辑
      </button>
      <button
        class="px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        :class="source.is_active ? 'text-slate-500 hover:bg-slate-100' : 'text-emerald-600 hover:bg-emerald-50'"
        :disabled="togglingId === source.id"
        @click="emit('toggle-active', source)"
      >
        {{ source.is_active ? '停用' : '启用' }}
      </button>
      <button
        class="px-4 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-colors ml-auto"
        @click="emit('delete', source)"
      >
        删除
      </button>
    </div>
  </template>
</template>
