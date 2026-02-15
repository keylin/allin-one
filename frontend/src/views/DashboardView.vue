<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import {
  getDashboardStats,
  getRecentActivity,
  getCollectionTrend,
  getSourceHealth,
  getRecentContent,
  getDailyStats,
} from '@/api/dashboard'
import { getFinanceSummary } from '@/api/finance'
import { collectSource } from '@/api/sources'
import { useToast } from '@/composables/useToast'

const router = useRouter()

const stats = ref({
  sources_count: 0, contents_today: 0, contents_yesterday: 0, contents_total: 0,
  pipelines_running: 0, pipelines_failed: 0, pipelines_pending: 0,
})
const activities = ref([])
const trend = ref([])
const sourceHealthList = ref([])
const recentContentList = ref([])
const financeSummaries = ref([])
const toast = useToast()
const loading = ref(true)
const collectingId = ref(null)
let timer = null

// 日详情相关
const selectedDate = ref(dayjs().format('YYYY-MM-DD'))
const dailyStats = ref(null)
const loadingDaily = ref(false)

// --- 统计卡片 ---
const statCards = [
  { key: 'sources_count', label: '数据源', subtitle: '已配置', accent: 'indigo', link: '/sources', icon: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' },
  { key: 'contents_today', label: '今日采集', subtitle: '新内容', accent: 'emerald', link: '/content', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  { key: 'pipelines_running', label: '运行中', subtitle: '流水线', accent: 'amber', link: '/pipelines', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
  { key: 'pipelines_failed', label: '失败', subtitle: '需关注', accent: 'rose', link: '/pipelines', icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z' },
]

const accentClasses = {
  indigo: { bg: 'bg-indigo-50', icon: 'text-indigo-600', number: 'text-indigo-700' },
  emerald: { bg: 'bg-emerald-50', icon: 'text-emerald-600', number: 'text-emerald-700' },
  amber: { bg: 'bg-amber-50', icon: 'text-amber-600', number: 'text-amber-700' },
  rose: { bg: 'bg-rose-50', icon: 'text-rose-600', number: 'text-rose-700' },
}

// --- 采集趋势 ---
const trendMax = computed(() => Math.max(...trend.value.map(t => t.count), 1))

// --- 今昨对比 ---
const todayChange = computed(() => {
  const today = stats.value.contents_today
  const yesterday = stats.value.contents_yesterday
  if (yesterday === 0) return 0
  return today - yesterday
})

// --- 数据源健康统计 ---
const healthSummary = computed(() => {
  const h = { healthy: 0, warning: 0, error: 0, disabled: 0 }
  sourceHealthList.value.forEach(s => h[s.health]++)
  return h
})

// --- 活动表格 ---
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
const triggerLabels = {
  scheduled: '定时', manual: '手动', api: 'API', webhook: 'Webhook',
}

const contentStatusStyles = {
  pending: 'bg-slate-100 text-slate-500',
  processing: 'bg-indigo-50 text-indigo-600',
  ready: 'bg-sky-50 text-sky-600',
  analyzed: 'bg-emerald-50 text-emerald-600',
  failed: 'bg-rose-50 text-rose-600',
}

const healthStyles = {
  healthy: { dot: 'bg-emerald-400', text: 'text-emerald-600', label: '正常' },
  warning: { dot: 'bg-amber-400', text: 'text-amber-600', label: '告警' },
  error: { dot: 'bg-rose-400', text: 'text-rose-600', label: '异常' },
  disabled: { dot: 'bg-slate-300', text: 'text-slate-400', label: '已禁用' },
}

async function fetchData() {
  try {
    const [statsRes, actRes, trendRes, healthRes, contentRes, finRes] = await Promise.all([
      getDashboardStats(),
      getRecentActivity(),
      getCollectionTrend(7),
      getSourceHealth(),
      getRecentContent(6),
      getFinanceSummary().catch(() => ({ code: -1 })),
    ])
    if (statsRes.code === 0) stats.value = statsRes.data
    if (actRes.code === 0) activities.value = actRes.data
    if (trendRes.code === 0) trend.value = trendRes.data
    if (healthRes.code === 0) sourceHealthList.value = healthRes.data
    if (contentRes.code === 0) recentContentList.value = contentRes.data
    if (finRes.code === 0) financeSummaries.value = finRes.data.slice(0, 4)
  } catch (e) {
    toast.error('仪表盘数据加载失败，请稍后刷新重试')
  } finally {
    loading.value = false
  }
}

async function fetchDailyStats(date) {
  loadingDaily.value = true
  try {
    const res = await getDailyStats(date)
    if (res.code === 0) {
      dailyStats.value = res.data
    }
  } catch (e) {
    toast.error('日统计数据加载失败')
  } finally {
    loadingDaily.value = false
  }
}

function selectDate(date) {
  selectedDate.value = date
  fetchDailyStats(date)
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('MM-DD HH:mm') : '-'
}

async function handleCollect(source) {
  collectingId.value = source.id
  try {
    await collectSource(source.id)
    fetchData()
  } finally {
    collectingId.value = null
  }
}

function formatDay(dateStr) {
  return dayjs.utc(dateStr).local().format('MM/DD')
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
  fetchDailyStats(selectedDate.value)
  timer = setInterval(fetchData, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div
        v-for="card in statCards"
        :key="card.key"
        class="bg-white rounded-xl border border-slate-200/60 p-5 shadow-sm hover:shadow-md hover:border-slate-300 transition-all duration-300 cursor-pointer"
        @click="router.push(card.link)"
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
          <svg class="w-4 h-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
        <div class="flex items-baseline gap-2">
          <div
            class="text-3xl font-bold tracking-tight"
            :class="accentClasses[card.accent].number"
          >
            {{ loading ? '-' : stats[card.key] }}
          </div>
          <!-- 今昨对比（仅"今日采集"卡片） -->
          <div v-if="card.key === 'contents_today' && !loading && stats.contents_yesterday !== undefined" class="flex items-center gap-0.5">
            <svg
              v-if="todayChange > 0"
              class="w-3 h-3 text-emerald-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              stroke-width="2.5"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
            </svg>
            <svg
              v-else-if="todayChange < 0"
              class="w-3 h-3 text-rose-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              stroke-width="2.5"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
            <span
              class="text-xs font-medium"
              :class="todayChange > 0 ? 'text-emerald-500' : todayChange < 0 ? 'text-rose-500' : 'text-slate-400'"
            >
              {{ todayChange > 0 ? '+' : '' }}{{ todayChange }}
            </span>
          </div>
        </div>
        <div class="text-sm text-slate-500 mt-1">{{ card.label }}</div>
        <div class="text-xs text-slate-300">{{ card.subtitle }}</div>
      </div>
    </div>

    <!-- 金融数据概览 -->
    <div v-if="financeSummaries.length" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-5 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold text-slate-700">金融数据概览</h3>
        <button
          class="text-xs text-indigo-500 hover:text-indigo-700 transition-colors"
          @click="router.push('/finance')"
        >
          查看全部
        </button>
      </div>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div
          v-for="item in financeSummaries"
          :key="item.source_id"
          class="px-3 py-2.5 rounded-lg bg-slate-50/50 cursor-pointer hover:bg-slate-100 transition-colors"
          @click="router.push('/finance')"
        >
          <div class="text-xs text-slate-500 mb-1 truncate">{{ item.name }}</div>
          <div class="flex items-end gap-2">
            <span class="text-base font-bold text-slate-900">
              {{ item.value != null ? (Math.abs(item.value) >= 1e4 ? (item.value / 1e4).toFixed(2) + '万' : item.value.toFixed(2)) : '-' }}
            </span>
            <span
              v-if="item.change != null"
              class="text-xs font-medium mb-0.5"
              :class="item.change > 0 ? 'text-red-500' : item.change < 0 ? 'text-emerald-500' : 'text-slate-400'"
            >
              {{ item.change > 0 ? '+' : '' }}{{ item.change.toFixed(2) }}
            </span>
          </div>
          <div v-if="item.date" class="text-[10px] text-slate-300 mt-0.5">{{ item.date }}</div>
        </div>
      </div>
    </div>

    <!-- 采集趋势 + 数据源健康 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
      <!-- 采集趋势 -->
      <div class="lg:col-span-2 bg-white rounded-xl border border-slate-200/60 shadow-sm p-5">
        <div class="flex items-center justify-between mb-5">
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

        <div v-else-if="trend.length > 0" class="flex items-end gap-2 h-40">
          <div
            v-for="day in trend"
            :key="day.date"
            class="flex-1 flex flex-col items-center gap-1.5 cursor-pointer"
            @click="selectDate(day.date)"
          >
            <!-- 数量标签 -->
            <span class="text-[10px] font-medium" :class="selectedDate === day.date ? 'text-indigo-600' : 'text-slate-500'">
              {{ day.count || '' }}
            </span>
            <!-- 柱子 -->
            <div class="w-full flex justify-center">
              <div
                class="w-full max-w-[36px] rounded-t-md transition-all duration-300"
                :class="selectedDate === day.date
                  ? 'bg-indigo-600 shadow-md'
                  : day.count > 0
                    ? 'bg-indigo-400 hover:bg-indigo-500'
                    : 'bg-slate-100'"
                :style="{ height: `${Math.max(day.count / trendMax * 100, 4)}px` }"
                :title="`${day.date}: ${day.count} 条`"
              ></div>
            </div>
            <!-- 日期 + 选中指示器 -->
            <div class="flex flex-col items-center gap-0.5">
              <span class="text-[10px]" :class="selectedDate === day.date ? 'text-indigo-600 font-semibold' : 'text-slate-400'">
                {{ formatDayLabel(day.date) }}
              </span>
              <div
                v-if="selectedDate === day.date"
                class="w-1 h-1 rounded-full bg-indigo-600"
              ></div>
            </div>
          </div>
        </div>

        <!-- 日详情面板 -->
        <div v-if="selectedDate" class="mt-6 pt-5 border-t border-slate-100">
          <!-- 加载状态 -->
          <div v-if="loadingDaily" class="flex items-center justify-center py-6">
            <svg class="w-5 h-5 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>

          <!-- 空状态 -->
          <div v-else-if="dailyStats && dailyStats.collection_total === 0" class="flex flex-col items-center justify-center py-6">
            <svg class="w-10 h-10 text-slate-200 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
            </svg>
            <p class="text-xs text-slate-400">{{ formatDayLabel(selectedDate) }}无采集记录</p>
          </div>

          <!-- 日详情内容 -->
          <div v-else-if="dailyStats">
            <!-- 概况行 -->
            <div class="flex items-center gap-4 text-xs mb-4">
              <div class="flex items-center gap-1.5">
                <span class="text-slate-400">采集</span>
                <span class="font-semibold text-slate-700">{{ dailyStats.collection_total }}</span>
                <span class="text-slate-400">次</span>
              </div>
              <div class="w-px h-3 bg-slate-200"></div>
              <div class="flex items-center gap-1.5">
                <span class="text-slate-400">成功率</span>
                <span class="font-semibold" :class="dailyStats.success_rate >= 90 ? 'text-emerald-600' : dailyStats.success_rate >= 70 ? 'text-amber-600' : 'text-rose-600'">
                  {{ dailyStats.success_rate }}%
                </span>
              </div>
              <div class="w-px h-3 bg-slate-200"></div>
              <div class="flex items-center gap-1.5">
                <span class="text-slate-400">发现</span>
                <span class="font-semibold text-indigo-600">{{ dailyStats.items_found }}</span>
                <span class="text-slate-400">条</span>
              </div>
              <div class="w-px h-3 bg-slate-200"></div>
              <div class="flex items-center gap-1.5">
                <span class="text-slate-400">新增</span>
                <span class="font-semibold text-emerald-600">{{ dailyStats.items_new }}</span>
                <span class="text-slate-400">条</span>
              </div>
            </div>

            <!-- Top 数据源排行 -->
            <div v-if="dailyStats.top_sources.length > 0" class="space-y-2">
              <h4 class="text-xs font-medium text-slate-500 mb-2">Top 数据源</h4>
              <div
                v-for="source in dailyStats.top_sources.slice(0, 5)"
                :key="source.source_id"
                class="flex items-center gap-2"
              >
                <div class="flex-1 min-w-0">
                  <div class="text-xs text-slate-700 truncate">{{ source.source_name }}</div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                  <span class="text-xs font-medium text-emerald-600">+{{ source.items_new }}</span>
                  <div class="w-16 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                    <div
                      class="h-1.5 bg-emerald-400 rounded-full"
                      :style="{ width: `${(source.items_new / dailyStats.items_new) * 100}%` }"
                    ></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 数据源健康 -->
      <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-slate-700">数据源健康</h3>
          <button
            class="text-xs text-indigo-500 hover:text-indigo-700 transition-colors"
            @click="router.push('/sources')"
          >
            查看全部
          </button>
        </div>

        <div v-if="loading" class="flex items-center justify-center h-32">
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

          <!-- 异常源列表（只展示有问题的） -->
          <div v-if="sourceHealthList.filter(s => s.health !== 'healthy').length > 0" class="space-y-2.5 max-h-[160px] overflow-y-auto">
            <div
              v-for="s in sourceHealthList.filter(s => s.health !== 'healthy')"
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
                @click="handleCollect(s)"
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
    </div>

    <!-- 最新内容 + 活动表格 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- 最新采集内容 -->
      <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-700">最新内容</h3>
          <button
            class="text-xs text-indigo-500 hover:text-indigo-700 transition-colors"
            @click="router.push('/content')"
          >
            查看全部
          </button>
        </div>

        <div v-if="loading" class="py-12 text-center">
          <svg class="w-6 h-6 mx-auto animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <div v-else-if="recentContentList.length === 0" class="py-12 text-center">
          <p class="text-sm text-slate-400">暂无内容</p>
        </div>

        <div v-else class="divide-y divide-slate-50">
          <div
            v-for="item in recentContentList"
            :key="item.id"
            class="px-5 py-3.5 hover:bg-slate-50/50 transition-colors cursor-pointer"
            @click="router.push('/content')"
          >
            <div class="flex items-start gap-2.5">
              <div class="flex-1 min-w-0">
                <div class="text-xs font-medium text-slate-700 line-clamp-1">{{ item.title }}</div>
                <div class="flex items-center gap-2 mt-1.5">
                  <span
                    class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md"
                    :class="contentStatusStyles[item.status] || 'bg-slate-100 text-slate-500'"
                  >
                    {{ statusLabels[item.status] || item.status }}
                  </span>
                  <span v-if="item.source_name" class="text-[10px] text-slate-300 truncate max-w-[100px]">
                    {{ item.source_name }}
                  </span>
                </div>
              </div>
              <span class="text-[10px] text-slate-300 shrink-0 pt-0.5">{{ formatTime(item.collected_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 流水线活动 -->
      <div class="lg:col-span-2 bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-700">流水线活动</h3>
          <button
            class="text-xs text-indigo-500 hover:text-indigo-700 transition-colors"
            @click="router.push('/pipelines')"
          >
            查看全部
          </button>
        </div>

        <div v-if="loading" class="py-16 text-center">
          <svg class="w-6 h-6 mx-auto animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <div v-else-if="activities.length === 0" class="py-16 text-center">
          <svg class="w-12 h-12 mx-auto mb-3 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
          <p class="text-sm text-slate-400">暂无活动记录</p>
        </div>

        <!-- Desktop Table -->
        <table v-else class="hidden md:table w-full">
          <thead>
            <tr class="border-b border-slate-100">
              <th class="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">内容</th>
              <th class="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">模板</th>
              <th class="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">状态</th>
              <th class="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">进度</th>
              <th class="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">触发</th>
              <th class="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in activities" :key="a.id" class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors duration-150">
              <td class="px-5 py-3.5 text-xs text-slate-700 font-medium max-w-[180px] truncate">{{ a.content_title || '-' }}</td>
              <td class="px-5 py-3.5 text-xs text-slate-500">{{ a.template_name || '-' }}</td>
              <td class="px-5 py-3.5">
                <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md" :class="statusStyles[a.status] || 'bg-slate-100 text-slate-500'">
                  {{ statusLabels[a.status] || a.status }}
                </span>
              </td>
              <td class="px-5 py-3.5">
                <div class="flex items-center gap-2">
                  <div class="w-14 bg-slate-100 rounded-full h-1.5">
                    <div
                      class="h-1.5 rounded-full transition-all duration-500"
                      :class="a.status === 'failed' ? 'bg-rose-400' : a.status === 'completed' ? 'bg-emerald-400' : 'bg-indigo-400'"
                      :style="{ width: a.total_steps > 0 ? `${(a.current_step / a.total_steps) * 100}%` : '0%' }"
                    ></div>
                  </div>
                  <span class="text-[10px] text-slate-400">{{ a.current_step }}/{{ a.total_steps }}</span>
                </div>
              </td>
              <td class="px-5 py-3.5">
                <span class="text-[10px] text-slate-400">{{ triggerLabels[a.trigger_source] || a.trigger_source }}</span>
              </td>
              <td class="px-5 py-3.5 text-xs text-slate-400">{{ formatTime(a.created_at) }}</td>
            </tr>
          </tbody>
        </table>

        <!-- Mobile Activity Cards -->
        <div v-if="!loading && activities.length > 0" class="md:hidden divide-y divide-slate-100">
          <div v-for="a in activities" :key="a.id" class="p-4">
            <div class="flex items-start justify-between gap-2 mb-2">
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium text-slate-700 line-clamp-1">{{ a.content_title || '-' }}</div>
                <div class="text-xs text-slate-400 mt-0.5">{{ a.template_name || '-' }}</div>
              </div>
              <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md shrink-0" :class="statusStyles[a.status] || 'bg-slate-100 text-slate-500'">
                {{ statusLabels[a.status] || a.status }}
              </span>
            </div>
            <div class="flex items-center gap-3 mb-2">
              <div class="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  class="h-1.5 rounded-full transition-all duration-500"
                  :class="a.status === 'failed' ? 'bg-rose-400' : a.status === 'completed' ? 'bg-emerald-400' : 'bg-indigo-400'"
                  :style="{ width: a.total_steps > 0 ? `${(a.current_step / a.total_steps) * 100}%` : '0%' }"
                ></div>
              </div>
              <span class="text-xs text-slate-400 shrink-0">{{ a.current_step }}/{{ a.total_steps }}</span>
            </div>
            <div class="flex items-center gap-3 text-xs text-slate-400">
              <span>{{ triggerLabels[a.trigger_source] || a.trigger_source }}</span>
              <span>{{ formatTime(a.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

      </div>
    </div>
  </div>
</template>
