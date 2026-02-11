<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import dayjs from 'dayjs'
import { getDashboardStats, getRecentActivity } from '@/api/dashboard'

const stats = ref({ sources_count: 0, contents_today: 0, pipelines_running: 0, pipelines_failed: 0 })
const activities = ref([])
const loading = ref(true)
let timer = null

const statCards = [
  { key: 'sources_count', label: '数据源', subtitle: '已配置', accent: 'indigo', icon: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' },
  { key: 'contents_today', label: '今日内容', subtitle: '新采集', accent: 'emerald', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  { key: 'pipelines_running', label: '运行中', subtitle: '流水线', accent: 'amber', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
  { key: 'pipelines_failed', label: '失败', subtitle: '需关注', accent: 'rose', icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z' },
]

const accentClasses = {
  indigo: { bg: 'bg-indigo-50', icon: 'text-indigo-600', number: 'text-indigo-700' },
  emerald: { bg: 'bg-emerald-50', icon: 'text-emerald-600', number: 'text-emerald-700' },
  amber: { bg: 'bg-amber-50', icon: 'text-amber-600', number: 'text-amber-700' },
  rose: { bg: 'bg-rose-50', icon: 'text-rose-600', number: 'text-rose-700' },
}

const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  running: 'bg-indigo-50 text-indigo-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
  cancelled: 'bg-slate-100 text-slate-400',
}

const statusLabels = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const triggerLabels = {
  scheduled: '定时',
  manual: '手动',
  api: 'API',
  webhook: 'Webhook',
}

async function fetchData() {
  try {
    const [statsRes, actRes] = await Promise.all([getDashboardStats(), getRecentActivity()])
    if (statsRes.code === 0) stats.value = statsRes.data
    if (actRes.code === 0) activities.value = actRes.data
  } finally {
    loading.value = false
  }
}

function formatTime(t) {
  return t ? dayjs(t).format('MM-DD HH:mm') : '-'
}

onMounted(() => {
  fetchData()
  timer = setInterval(fetchData, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="p-4 md:p-8 max-w-7xl mx-auto">
    <div class="mb-8">
      <h2 class="text-2xl font-bold tracking-tight text-slate-900">仪表盘</h2>
      <p class="text-sm text-slate-400 mt-1">系统概览与最近活动</p>
    </div>

    <!-- Stat Cards -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      <div
        v-for="card in statCards"
        :key="card.key"
        class="bg-white rounded-xl border border-slate-200/60 p-5 shadow-sm hover:shadow-md transition-shadow duration-300"
      >
        <div class="flex items-center justify-between mb-3">
          <div
            class="w-10 h-10 rounded-xl flex items-center justify-center"
            :class="accentClasses[card.accent].bg"
          >
            <svg class="w-5 h-5" :class="accentClasses[card.accent].icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="card.icon" />
            </svg>
          </div>
        </div>
        <div
          class="text-3xl font-bold tracking-tight"
          :class="accentClasses[card.accent].number"
        >
          {{ loading ? '-' : stats[card.key] }}
        </div>
        <div class="text-sm text-slate-500 mt-1">{{ card.label }}</div>
        <div class="text-xs text-slate-300">{{ card.subtitle }}</div>
      </div>
    </div>

    <!-- Recent Activity -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-100">
        <h3 class="text-sm font-semibold text-slate-700 tracking-tight">最近流水线活动</h3>
      </div>

      <div v-if="loading" class="py-16 text-center text-slate-300">
        <svg class="w-8 h-8 mx-auto mb-3 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <span class="text-sm">加载中...</span>
      </div>

      <div v-else-if="activities.length === 0" class="py-16 text-center">
        <svg class="w-12 h-12 mx-auto mb-3 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
        <p class="text-sm text-slate-400">暂无活动记录</p>
      </div>

      <table v-else class="w-full">
        <thead>
          <tr class="border-b border-slate-100">
            <th class="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">内容</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">模板</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">状态</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">进度</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">触发</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in activities" :key="a.id" class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors duration-150">
            <td class="px-6 py-4 text-sm text-slate-700 font-medium max-w-[200px] truncate">{{ a.content_title || '-' }}</td>
            <td class="px-6 py-4 text-sm text-slate-500">{{ a.template_name || '-' }}</td>
            <td class="px-6 py-4">
              <span class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg" :class="statusStyles[a.status] || 'bg-slate-100 text-slate-500'">
                {{ statusLabels[a.status] || a.status }}
              </span>
            </td>
            <td class="px-6 py-4">
              <div class="flex items-center gap-2">
                <div class="w-16 bg-slate-100 rounded-full h-1.5">
                  <div
                    class="h-1.5 rounded-full transition-all duration-500"
                    :class="a.status === 'failed' ? 'bg-rose-400' : a.status === 'completed' ? 'bg-emerald-400' : 'bg-indigo-400'"
                    :style="{ width: a.total_steps > 0 ? `${(a.current_step / a.total_steps) * 100}%` : '0%' }"
                  ></div>
                </div>
                <span class="text-xs text-slate-400">{{ a.current_step }}/{{ a.total_steps }}</span>
              </div>
            </td>
            <td class="px-6 py-4">
              <span class="text-xs text-slate-400">{{ triggerLabels[a.trigger_source] || a.trigger_source }}</span>
            </td>
            <td class="px-6 py-4 text-sm text-slate-400">{{ formatTime(a.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
