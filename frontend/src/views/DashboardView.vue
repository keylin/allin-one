<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import {
  getDashboardStats,
  getRecentActivity,
  getCollectionTrend,
  getSourceHealth,
  getContentStatusDistribution,
  getStorageStats,
  getDedupStats,
} from '@/api/dashboard'
import { getFinanceSummary } from '@/api/finance'
import { collectSource } from '@/api/sources'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const toast = useToast()

// 数据状态
const stats = ref({
  sources_count: 0, contents_today: 0, contents_yesterday: 0, contents_total: 0,
  pipelines_running: 0, pipelines_failed: 0, pipelines_pending: 0,
})
const activities = ref([])
const trend = ref([])
const sourceHealthList = ref([])
const financeSummaries = ref([])
const contentStatus = ref({ pending: 0, processing: 0, ready: 0, analyzed: 0, failed: 0, total: 0 })
const storageStats = ref({ media: {}, database_bytes: 0, total_bytes: 0 })
const dedupStats = ref({ total_items: 0, duplicate_count: 0, originals_with_dups: 0, dedup_rate: 0, today_duplicates: 0, by_source: [] })
const loading = ref(true)
const collectingId = ref(null)
let timer = null
let failCount = 0

// 趋势图选中日期（仅用于高亮）
const selectedDate = ref(dayjs().format('YYYY-MM-DD'))

async function handleCollectSource(source) {
  collectingId.value = source.id
  try {
    const res = await collectSource(source.id)
    if (res.code === 0) {
      toast.success('采集任务已提交', { title: source.name })
    }
  } finally {
    collectingId.value = null
  }
}

// --- 统计卡片配置 ---
const statCards = [
  { key: 'sources_count', label: '数据源', accent: 'indigo', link: '/sources', icon: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' },
  { key: 'contents_today', label: '今日采集', accent: 'emerald', link: '/content', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  { key: 'pipelines_running', label: '运行中', accent: 'amber', link: '/pipelines', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
  { key: 'pipelines_failed', label: '失败', accent: 'rose', link: '/pipelines', icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z' },
]

const accentClasses = {
  indigo: { bg: 'bg-indigo-50', icon: 'text-indigo-600', number: 'text-indigo-700' },
  emerald: { bg: 'bg-emerald-50', icon: 'text-emerald-600', number: 'text-emerald-700' },
  amber: { bg: 'bg-amber-50', icon: 'text-amber-600', number: 'text-amber-700' },
  rose: { bg: 'bg-rose-50', icon: 'text-rose-600', number: 'text-rose-700' },
}

// --- 今昨对比 ---
const todayChange = computed(() => {
  const today = stats.value.contents_today
  const yesterday = stats.value.contents_yesterday
  if (yesterday === 0) return 0
  return today - yesterday
})

// --- 内容状态分布 ---
const statusChartData = computed(() => {
  const total = contentStatus.value.total || 1
  const items = [
    { key: 'analyzed', label: '已分析', count: contentStatus.value.analyzed, color: '#10b981', percent: Math.round(contentStatus.value.analyzed / total * 100) },
    { key: 'ready', label: '已就绪', count: contentStatus.value.ready, color: '#0ea5e9', percent: Math.round(contentStatus.value.ready / total * 100) },
    { key: 'processing', label: '处理中', count: contentStatus.value.processing, color: '#6366f1', percent: Math.round(contentStatus.value.processing / total * 100) },
    { key: 'pending', label: '待处理', count: contentStatus.value.pending, color: '#94a3b8', percent: Math.round(contentStatus.value.pending / total * 100) },
    { key: 'failed', label: '失败', count: contentStatus.value.failed, color: '#f43f5e', percent: Math.round(contentStatus.value.failed / total * 100) },
  ]
  return items.filter(i => i.count > 0)
})

// --- 采集趋势 ---
const trendMax = computed(() => Math.max(...trend.value.map(t => t.count), 1))

// --- 数据源健康统计 ---
const healthSummary = computed(() => {
  const h = { healthy: 0, warning: 0, error: 0, disabled: 0 }
  sourceHealthList.value.forEach(s => h[s.health]++)
  return h
})

const unhealthySources = computed(() =>
  sourceHealthList.value.filter(s => s.health !== 'healthy')
)

// --- 存储格式化 ---
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

// --- 活动状态样式 ---
const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  running: 'bg-indigo-50 text-indigo-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
  cancelled: 'bg-slate-100 text-slate-400',
}
const statusLabels = {
  pending: '等待中', running: '运行中', completed: '已完成',
  failed: '失败', cancelled: '已取消',
}
const healthStyles = {
  healthy: { dot: 'bg-emerald-400', text: 'text-emerald-600', label: '正常' },
  warning: { dot: 'bg-amber-400', text: 'text-amber-600', label: '告警' },
  error: { dot: 'bg-rose-400', text: 'text-rose-600', label: '异常' },
  disabled: { dot: 'bg-slate-300', text: 'text-slate-400', label: '已禁用' },
}

function storageBarClass(bytes) {
  const ratio = bytes / (storageStats.value.total_bytes || 1)
  if (ratio > 0.9) return 'bg-rose-400'
  if (ratio > 0.7) return 'bg-amber-400'
  return null // 使用默认颜色
}

// --- 数据获取 ---
async function fetchData() {
  const results = await Promise.allSettled([
    getDashboardStats(),
    getRecentActivity(8),
    getCollectionTrend(7),
    getSourceHealth(),
    getFinanceSummary(),
    getContentStatusDistribution(),
    getStorageStats(),
    getDedupStats(),
  ])

  const handlers = [
    (res) => { stats.value = res.data },
    (res) => { activities.value = res.data },
    (res) => { trend.value = res.data },
    (res) => { sourceHealthList.value = res.data },
    (res) => { financeSummaries.value = res.data.slice(0, 4) },
    (res) => { contentStatus.value = res.data },
    (res) => { storageStats.value = res.data },
    (res) => { dedupStats.value = res.data },
  ]

  let hasError = false
  results.forEach((result, i) => {
    if (result.status === 'fulfilled' && result.value?.code === 0) {
      handlers[i](result.value)
    } else if (result.status === 'rejected') {
      hasError = true
    }
  })

  if (hasError) {
    failCount++
    if (failCount >= 3 && timer) {
      clearInterval(timer)
      timer = null
      toast.error('自动刷新已暂停，请检查网络后刷新页面')
    }
  } else {
    failCount = 0
  }

  loading.value = false
}

function selectDate(date) {
  selectedDate.value = date
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('MM-DD HH:mm') : '-'
}

function formatDayLabel(dateStr) {
  const d = dayjs(dateStr)
  const today = dayjs().format('YYYY-MM-DD')
  const yesterday = dayjs().subtract(1, 'day').format('YYYY-MM-DD')
  if (dateStr === today) return '今天'
  if (dateStr === yesterday) return '昨天'
  return d.format('MM/DD')
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
  <div class="flex flex-col h-full">
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4 space-y-5">

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <div
        v-for="card in statCards"
        :key="card.key"
        class="bg-white rounded-xl border border-slate-200/60 p-4 shadow-sm hover:shadow-md hover:border-slate-300 transition-all duration-300 cursor-pointer"
        @click="router.push(card.link)"
      >
        <div class="flex items-center justify-between mb-2">
          <div class="w-9 h-9 rounded-lg flex items-center justify-center" :class="accentClasses[card.accent].bg">
            <svg class="w-5 h-5" :class="accentClasses[card.accent].icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="card.icon" />
            </svg>
          </div>
          <svg class="w-4 h-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
        <div class="flex items-baseline gap-2">
          <div class="text-2xl font-bold tracking-tight" :class="accentClasses[card.accent].number">
            {{ loading ? '-' : stats[card.key] }}
          </div>
          <div v-if="card.key === 'contents_today' && !loading && todayChange !== 0" class="flex items-center gap-0.5">
            <svg v-if="todayChange > 0" class="w-3 h-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
            </svg>
            <svg v-else class="w-3 h-3 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
            <span class="text-xs font-medium" :class="todayChange > 0 ? 'text-emerald-500' : 'text-rose-500'">
              {{ todayChange > 0 ? '+' : '' }}{{ todayChange }}
            </span>
          </div>
        </div>
        <div class="text-sm text-slate-500 mt-0.5">{{ card.label }}</div>
      </div>
    </div>

    <!-- 金融数据概览 -->
    <div v-if="financeSummaries.length" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-semibold text-slate-700">金融数据概览</h3>
        <router-link to="/finance" class="text-xs text-indigo-500 hover:text-indigo-700">查看全部</router-link>
      </div>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div
          v-for="item in financeSummaries"
          :key="item.source_id"
          class="px-3 py-2 rounded-lg bg-slate-50/50 cursor-pointer hover:bg-slate-100 transition-colors"
          @click="router.push('/finance')"
        >
          <div class="text-xs text-slate-500 mb-1 truncate">{{ item.name }}</div>
          <div class="flex items-end gap-2">
            <span class="text-base font-bold text-slate-900">
              {{ item.value != null ? (Math.abs(item.value) >= 1e4 ? (item.value / 1e4).toFixed(2) + '万' : item.value.toFixed(2)) : '-' }}
            </span>
            <span v-if="item.change != null" class="text-xs font-medium mb-0.5" :class="item.change > 0 ? 'text-red-500' : item.change < 0 ? 'text-emerald-500' : 'text-slate-400'">
              {{ item.change > 0 ? '+' : '' }}{{ item.change.toFixed(2) }}
            </span>
          </div>
          <div v-if="item.date" class="text-[10px] text-slate-300 mt-0.5">{{ item.date }}</div>
        </div>
      </div>
    </div>

    <!-- 内容状态分布 + 采集趋势 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-5">
      <!-- 内容状态分布 -->
      <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-slate-700">内容状态分布</h3>
          <span class="text-xs text-slate-400">共 {{ contentStatus.total }} 条</span>
        </div>

        <div v-if="loading" class="flex items-center justify-center h-40">
          <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <div v-else class="flex flex-col sm:flex-row items-center gap-4">
          <!-- 环形图 -->
          <div class="relative w-28 h-28 shrink-0">
            <svg viewBox="0 0 36 36" class="w-full h-full -rotate-90">
              <circle cx="18" cy="18" r="15.9" fill="none" stroke="#f1f5f9" stroke-width="3"></circle>
              <template v-for="(item, idx) in statusChartData" :key="item.key">
                <circle
                  cx="18" cy="18" r="15.9"
                  fill="none"
                  :stroke="item.color"
                  stroke-width="3"
                  :stroke-dasharray="`${item.percent} ${100 - item.percent}`"
                  :stroke-dashoffset="statusChartData.slice(0, idx).reduce((sum, i) => sum - i.percent, 0)"
                  class="transition-all duration-500"
                ></circle>
              </template>
            </svg>
            <div class="absolute inset-0 flex items-center justify-center">
              <div class="text-center">
                <div class="text-lg font-bold text-slate-700">{{ contentStatus.total }}</div>
                <div class="text-[10px] text-slate-400">总计</div>
              </div>
            </div>
          </div>

          <!-- 图例 -->
          <div class="flex-1 space-y-2">
            <router-link
              v-for="item in statusChartData"
              :key="item.key"
              :to="`/content?status=${item.key}`"
              class="flex items-center justify-between px-2 py-1.5 rounded-lg hover:bg-slate-50 transition-colors"
            >
              <div class="flex items-center gap-2">
                <div class="w-2.5 h-2.5 rounded-full" :style="{ backgroundColor: item.color }"></div>
                <span class="text-xs text-slate-600">{{ item.label }}</span>
              </div>
              <div class="flex items-center gap-1.5">
                <span class="text-xs font-medium text-slate-700">{{ item.count }}</span>
                <span class="text-[10px] text-slate-400">{{ item.percent }}%</span>
              </div>
            </router-link>
          </div>
        </div>
      </div>

      <!-- 采集趋势 -->
      <div class="lg:col-span-2 bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-slate-700">近 7 天采集趋势</h3>
          <span class="text-xs text-slate-400">
            总计 {{ trend.reduce((s, t) => s + t.count, 0) }} 条
          </span>
        </div>

        <div v-if="loading" class="flex items-center justify-center h-40">
          <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <div v-else-if="trend.length > 0" class="space-y-4">
          <!-- 柱状图 -->
          <div class="flex items-end gap-2 h-32">
            <div
              v-for="day in trend"
              :key="day.date"
              class="flex-1 flex flex-col items-center gap-1 cursor-pointer group"
              @click="selectDate(day.date)"
            >
              <span class="text-[10px] font-medium opacity-0 group-hover:opacity-100 transition-opacity" :class="selectedDate === day.date ? 'text-indigo-600' : 'text-slate-500'">
                {{ day.count }}
              </span>
              <div class="w-full flex justify-center">
                <div
                  class="w-full max-w-[36px] rounded-t-md transition-all duration-300"
                  :class="selectedDate === day.date
                    ? 'bg-indigo-600 shadow-md'
                    : day.count > 0
                      ? 'bg-indigo-400 group-hover:bg-indigo-500'
                      : 'bg-slate-100'"
                  :style="{ height: `${Math.max(day.count / trendMax * 100, 4)}px` }"
                  :title="`${day.date}: ${day.count} 条`"
                ></div>
              </div>
              <div class="flex flex-col items-center gap-0.5">
                <span class="text-[10px]" :class="selectedDate === day.date ? 'text-indigo-600 font-semibold' : 'text-slate-400'">
                  {{ formatDayLabel(day.date) }}
                </span>
                <div v-if="selectedDate === day.date" class="w-1 h-1 rounded-full bg-indigo-600"></div>
              </div>
            </div>
          </div>

          <!-- 成功率指示器 -->
          <div class="flex items-center gap-3 pt-3 border-t border-slate-100">
            <template v-for="day in trend" :key="day.date">
              <div
                v-if="day.collection_total > 0"
                class="flex-1 text-center"
              >
                <div class="flex items-center justify-center gap-1">
                  <div
                    class="w-1.5 h-1.5 rounded-full"
                    :class="day.success_rate >= 90 ? 'bg-emerald-400' : day.success_rate >= 70 ? 'bg-amber-400' : 'bg-rose-400'"
                  ></div>
                  <span class="text-[10px]" :class="day.success_rate >= 90 ? 'text-emerald-600' : day.success_rate >= 70 ? 'text-amber-600' : 'text-rose-600'">
                    {{ day.success_rate }}%
                  </span>
                </div>
              </div>
              <div v-else class="flex-1 text-center">
                <span class="text-[10px] text-slate-300">-</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据源健康 + 存储空间 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <!-- 数据源健康 -->
      <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-slate-700">数据源健康</h3>
          <router-link to="/sources" class="text-xs text-indigo-500 hover:text-indigo-700">查看全部</router-link>
        </div>

        <div v-if="loading" class="flex items-center justify-center h-24">
          <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <template v-else>
          <!-- 健康摘要 -->
          <div class="flex items-center gap-4 mb-4 pb-4 border-b border-slate-100">
            <div v-for="(style, key) in healthStyles" :key="key" class="flex items-center gap-1.5" :class="!healthSummary[key] ? 'opacity-40' : ''">
              <div class="w-2 h-2 rounded-full" :class="style.dot"></div>
              <span class="text-xs" :class="style.text">{{ healthSummary[key] }}</span>
            </div>
          </div>

          <!-- 异常源列表 -->
          <div v-if="unhealthySources.length > 0" class="space-y-2 max-h-[140px] overflow-y-auto">
            <div
              v-for="s in unhealthySources"
              :key="s.id"
              class="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-slate-50/50"
            >
              <div class="w-2 h-2 rounded-full shrink-0" :class="healthStyles[s.health].dot"></div>
              <div class="flex-1 min-w-0">
                <div class="text-xs font-medium text-slate-700 truncate">{{ s.name }}</div>
                <div class="text-[10px] text-slate-400">
                  <span v-if="s.health === 'error'">连续失败 {{ s.consecutive_failures }} 次</span>
                  <span v-else-if="s.health === 'warning'">失败 {{ s.consecutive_failures }} 次</span>
                  <span v-else>已禁用</span>
                </div>
              </div>
              <button
                v-if="s.health === 'error' || s.health === 'warning'"
                class="px-2 py-1 text-[10px] font-medium text-indigo-600 hover:bg-indigo-50 rounded-md transition-colors shrink-0 disabled:opacity-40"
                :disabled="collectingId === s.id"
                @click="handleCollectSource(s)"
              >
                {{ collectingId === s.id ? '...' : '重试' }}
              </button>
            </div>
          </div>
          <div v-else class="flex flex-col items-center justify-center py-6">
            <div class="w-10 h-10 bg-emerald-50 rounded-full flex items-center justify-center mb-2">
              <svg class="w-5 h-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <span class="text-xs text-slate-400">全部数据源运行正常</span>
          </div>
        </template>
      </div>

      <!-- 存储空间 -->
      <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-slate-700">存储空间</h3>
          <span class="text-xs text-slate-400">总计 {{ formatBytes(storageStats.total_bytes) }}</span>
        </div>

        <div v-if="loading" class="flex items-center justify-center h-24">
          <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <div v-else class="space-y-3">
          <!-- 视频 -->
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center shrink-0">
              <svg class="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>
            <div class="flex-1">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs text-slate-600">视频</span>
                <span class="text-xs font-medium text-slate-700">{{ formatBytes(storageStats.media?.video_bytes || 0) }}</span>
              </div>
              <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  class="h-1.5 rounded-full"
                  :class="storageBarClass(storageStats.media?.video_bytes || 0) || 'bg-purple-400'"
                  :style="{ width: `${(storageStats.media?.video_bytes || 0) / (storageStats.total_bytes || 1) * 100}%` }"
                ></div>
              </div>
            </div>
          </div>

          <!-- 图片 -->
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center shrink-0">
              <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            </div>
            <div class="flex-1">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs text-slate-600">图片</span>
                <span class="text-xs font-medium text-slate-700">{{ formatBytes(storageStats.media?.image_bytes || 0) }}</span>
              </div>
              <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  class="h-1.5 rounded-full"
                  :class="storageBarClass(storageStats.media?.image_bytes || 0) || 'bg-emerald-400'"
                  :style="{ width: `${(storageStats.media?.image_bytes || 0) / (storageStats.total_bytes || 1) * 100}%` }"
                ></div>
              </div>
            </div>
          </div>

          <!-- 音频 -->
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center shrink-0">
              <svg class="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
              </svg>
            </div>
            <div class="flex-1">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs text-slate-600">音频</span>
                <span class="text-xs font-medium text-slate-700">{{ formatBytes(storageStats.media?.audio_bytes || 0) }}</span>
              </div>
              <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  class="h-1.5 rounded-full"
                  :class="storageBarClass(storageStats.media?.audio_bytes || 0) || 'bg-amber-400'"
                  :style="{ width: `${(storageStats.media?.audio_bytes || 0) / (storageStats.total_bytes || 1) * 100}%` }"
                ></div>
              </div>
            </div>
          </div>

          <!-- 数据库 -->
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
              <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
              </svg>
            </div>
            <div class="flex-1">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs text-slate-600">数据库</span>
                <span class="text-xs font-medium text-slate-700">{{ formatBytes(storageStats.database_bytes) }}</span>
              </div>
              <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  class="h-1.5 rounded-full"
                  :class="storageBarClass(storageStats.database_bytes) || 'bg-indigo-400'"
                  :style="{ width: `${storageStats.database_bytes / (storageStats.total_bytes || 1) * 100}%` }"
                ></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 内容去重统计 -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold text-slate-700">内容去重统计</h3>
        <router-link to="/content?duplicates_only=1" class="text-xs text-indigo-500 hover:text-indigo-700">查看重复内容</router-link>
      </div>

      <div v-if="loading" class="flex items-center justify-center h-24">
        <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <template v-else-if="dedupStats.duplicate_count > 0">
        <!-- 指标卡片 -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <div class="bg-slate-50/50 rounded-lg p-3">
            <div class="flex items-center gap-2 mb-2">
              <div class="w-7 h-7 rounded-md flex items-center justify-center bg-amber-50">
                <svg class="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </div>
            </div>
            <div class="text-xl font-bold tracking-tight text-amber-700">{{ dedupStats.duplicate_count }}</div>
            <div class="text-xs text-slate-500 mt-0.5">重复内容</div>
          </div>
          <div class="bg-slate-50/50 rounded-lg p-3">
            <div class="flex items-center gap-2 mb-2">
              <div class="w-7 h-7 rounded-md flex items-center justify-center" :class="dedupStats.dedup_rate > 20 ? 'bg-rose-50' : 'bg-emerald-50'">
                <svg class="w-4 h-4" :class="dedupStats.dedup_rate > 20 ? 'text-rose-600' : 'text-emerald-600'" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
                </svg>
              </div>
            </div>
            <div class="text-xl font-bold tracking-tight" :class="dedupStats.dedup_rate > 20 ? 'text-rose-700' : 'text-emerald-700'">{{ dedupStats.dedup_rate }}%</div>
            <div class="text-xs text-slate-500 mt-0.5">去重率</div>
          </div>
          <div class="bg-slate-50/50 rounded-lg p-3">
            <div class="flex items-center gap-2 mb-2">
              <div class="w-7 h-7 rounded-md flex items-center justify-center bg-indigo-50">
                <svg class="w-4 h-4 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
              </div>
            </div>
            <div class="text-xl font-bold tracking-tight text-indigo-700">{{ dedupStats.originals_with_dups }}</div>
            <div class="text-xs text-slate-500 mt-0.5">被重复原件</div>
          </div>
          <div class="bg-slate-50/50 rounded-lg p-3">
            <div class="flex items-center gap-2 mb-2">
              <div class="w-7 h-7 rounded-md flex items-center justify-center bg-emerald-50">
                <svg class="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
            </div>
            <div class="text-xl font-bold tracking-tight text-emerald-700">{{ dedupStats.today_duplicates }}</div>
            <div class="text-xs text-slate-500 mt-0.5">今日重复</div>
          </div>
        </div>

        <!-- 按数据源分布 -->
        <div v-if="dedupStats.by_source.length > 0">
          <div class="text-xs text-slate-400 mb-2.5">按数据源分布 (Top {{ dedupStats.by_source.length }})</div>
          <div class="space-y-2">
            <div v-for="src in dedupStats.by_source" :key="src.source_id" class="flex items-center gap-3">
              <div class="w-20 text-xs text-slate-600 truncate shrink-0" :title="src.source_name">{{ src.source_name }}</div>
              <div class="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
                <div
                  class="h-2 rounded-full transition-all duration-500"
                  :class="src.dedup_rate > 20 ? 'bg-amber-400' : 'bg-indigo-400'"
                  :style="{ width: `${src.duplicate_count / dedupStats.by_source[0].duplicate_count * 100}%` }"
                ></div>
              </div>
              <div class="text-xs text-slate-500 shrink-0 w-20 text-right">
                {{ src.duplicate_count }} <span class="text-slate-400">({{ src.dedup_rate }}%)</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-else-if="!loading" class="flex flex-col items-center justify-center py-6">
        <div class="w-10 h-10 bg-emerald-50 rounded-full flex items-center justify-center mb-2">
          <svg class="w-5 h-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <span class="text-xs text-slate-400">暂无重复内容</span>
      </div>
    </div>

    <!-- 流水线活动（精简版） -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
      <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-slate-700">流水线活动</h3>
        <router-link to="/pipelines" class="text-xs text-indigo-500 hover:text-indigo-700">查看全部</router-link>
      </div>

      <div v-if="loading" class="py-12 text-center">
        <svg class="w-6 h-6 mx-auto animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <div v-else-if="activities.length === 0" class="py-12 text-center">
        <svg class="w-10 h-10 mx-auto mb-2 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
        <p class="text-sm text-slate-400">暂无活动记录</p>
      </div>

      <table v-else class="hidden md:table w-full">
        <thead>
          <tr class="border-b border-slate-100">
            <th class="px-4 py-2.5 text-left text-xs font-medium text-slate-400">内容</th>
            <th class="px-4 py-2.5 text-left text-xs font-medium text-slate-400">模板</th>
            <th class="px-4 py-2.5 text-left text-xs font-medium text-slate-400">状态</th>
            <th class="px-4 py-2.5 text-left text-xs font-medium text-slate-400">进度</th>
            <th class="px-4 py-2.5 text-left text-xs font-medium text-slate-400">时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in activities" :key="a.id" class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
            <td class="px-4 py-2.5 text-xs text-slate-700 font-medium max-w-[180px] truncate">{{ a.content_title || '-' }}</td>
            <td class="px-4 py-2.5 text-xs text-slate-500">{{ a.template_name || '-' }}</td>
            <td class="px-4 py-2.5">
              <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md" :class="statusStyles[a.status] || 'bg-slate-100 text-slate-500'">
                {{ statusLabels[a.status] || a.status }}
              </span>
            </td>
            <td class="px-4 py-2.5">
              <div class="flex items-center gap-2">
                <div class="w-12 bg-slate-100 rounded-full h-1.5">
                  <div
                    class="h-1.5 rounded-full transition-all duration-500"
                    :class="a.status === 'failed' ? 'bg-rose-400' : a.status === 'completed' ? 'bg-emerald-400' : 'bg-indigo-400'"
                    :style="{ width: a.total_steps > 0 ? `${(a.current_step / a.total_steps) * 100}%` : '0%' }"
                  ></div>
                </div>
                <span class="text-[10px] text-slate-400">{{ a.current_step }}/{{ a.total_steps }}</span>
              </div>
            </td>
            <td class="px-4 py-2.5 text-xs text-slate-400">{{ formatTime(a.created_at) }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Mobile -->
      <div v-if="!loading && activities.length > 0" class="md:hidden divide-y divide-slate-100">
        <div v-for="a in activities" :key="a.id" class="p-3">
          <div class="flex items-start justify-between gap-2 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-slate-700 line-clamp-1">{{ a.content_title || '-' }}</div>
              <div class="text-xs text-slate-400 mt-0.5">{{ a.template_name || '-' }}</div>
            </div>
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md shrink-0" :class="statusStyles[a.status] || 'bg-slate-100 text-slate-500'">
              {{ statusLabels[a.status] || a.status }}
            </span>
          </div>
          <div class="flex items-center gap-2 text-xs text-slate-400">
            <span>{{ a.current_step }}/{{ a.total_steps }}</span>
            <span>{{ formatTime(a.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>

      </div>
    </div>
  </div>
</template>
