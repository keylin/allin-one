<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { listFinanceSources, getFinanceSummary, getTimeseries } from '@/api/finance'
import FinanceChart from '@/components/finance-chart.vue'
import FinanceSummaryCard from '@/components/finance-summary-card.vue'
import ContentDetailModal from '@/components/content-detail-modal.vue'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const toast = useToast()

// Data
const sources = ref([])
const summaries = ref([])
const loading = ref(true)
const chartLoading = ref(false)

// Tabs & Selection
const activeTab = ref('macro')
const selectedSourceId = ref('')
const timeRange = ref('ALL')
const compareMode = ref('raw')

// Chart data
const allSeriesData = ref([])
const chartCategory = ref('macro')
const chartSourceName = ref('')

// Table pagination & highlight
const tableCollapsed = ref(true)
const tablePage = ref(1)
const TABLE_COLLAPSED_SIZE = 10
const TABLE_PAGE_SIZE = 30
const highlightDate = ref(null)
const jumpDate = ref('')
let highlightTimer = null

// Detail modal
const detailModalVisible = ref(false)
const detailContentId = ref(null)

const tabs = [
  { key: 'macro', label: '宏观经济' },
  { key: 'stock', label: 'A股行情' },
  { key: 'fund', label: '基金/ETF' },
]

const timeRanges = [
  { key: '3M', label: '近3月', days: 90 },
  { key: '1Y', label: '近1年', days: 365 },
  { key: '3Y', label: '近3年', days: 1095 },
  { key: '5Y', label: '近5年', days: 1825 },
  { key: 'ALL', label: '全部', days: 0 },
]

const compareModes = [
  { key: 'raw', label: '原始值' },
  { key: 'yoy', label: '同比' },
  { key: 'mom', label: '环比' },
]

const filteredSources = computed(() =>
  sources.value.filter(s => s.category === activeTab.value)
)

const filteredSummaries = computed(() =>
  summaries.value.filter(s => s.category === activeTab.value)
)

const sourceOptions = computed(() =>
  filteredSources.value.map(s => ({ value: s.id, label: s.name }))
)

const selectedSource = computed(() =>
  sources.value.find(s => s.id === selectedSourceId.value)
)

const chartData = computed(() => {
  const range = timeRanges.find(r => r.key === timeRange.value)
  if (!range || range.days === 0) return allSeriesData.value
  const cutoff = dayjs().subtract(range.days, 'day').format('YYYY-MM-DD')
  return allSeriesData.value.filter(p => p.date >= cutoff)
})

const chartZoomStart = computed(() => 0)

// ---- YoY / MoM computation for table ----

function getVal(p) {
  return p.close ?? p.unit_nav ?? p.value ?? null
}

function buildDateMap(series) {
  const map = new Map()
  series.forEach(p => map.set(p.date, p))
  return map
}

const tableData = computed(() => {
  const data = chartData.value
  if (!data.length) return []

  const dateMap = buildDateMap(allSeriesData.value)

  const rows = data.map((p, i) => {
    const cur = getVal(p)

    const prevPoint = i > 0 ? data[i - 1] : null
    const prevVal = prevPoint ? getVal(prevPoint) : null
    let momPct = null
    if (cur != null && prevVal != null && prevVal !== 0) {
      momPct = ((cur - prevVal) / Math.abs(prevVal)) * 100
    }

    const prevYearDate = p.date.replace(/^\d{4}/, y => String(Number(y) - 1))
    const yoyPoint = dateMap.get(prevYearDate)
    const yoyVal = yoyPoint ? getVal(yoyPoint) : null
    let yoyPct = null
    if (cur != null && yoyVal != null && yoyVal !== 0) {
      yoyPct = ((cur - yoyVal) / Math.abs(yoyVal)) * 100
    }

    return { ...p, _momPct: momPct, _yoyPct: yoyPct }
  })

  return rows.slice().reverse()
})

const tableTotalPages = computed(() =>
  Math.ceil(tableData.value.length / TABLE_PAGE_SIZE) || 1
)

const displayedTableData = computed(() => {
  if (tableCollapsed.value) {
    return tableData.value.slice(0, TABLE_COLLAPSED_SIZE)
  }
  const start = (tablePage.value - 1) * TABLE_PAGE_SIZE
  return tableData.value.slice(start, start + TABLE_PAGE_SIZE)
})

function resetTableState() {
  tableCollapsed.value = true
  tablePage.value = 1
  highlightDate.value = null
  jumpDate.value = ''
}

function expandTable() {
  tableCollapsed.value = false
  tablePage.value = 1
}

function collapseTable() {
  tableCollapsed.value = true
  tablePage.value = 1
}

function navigateToDate(date) {
  if (!date || !tableData.value.length) return

  // tableData is sorted descending (newest first), find closest date
  let bestIdx = 0
  let bestDiff = Infinity
  for (let i = 0; i < tableData.value.length; i++) {
    const diff = Math.abs(tableData.value[i].date.localeCompare(date))
    // Exact match → use immediately
    if (tableData.value[i].date === date) { bestIdx = i; break }
    // For string-based date comparison, find the nearest
    const absDiff = Math.abs(new Date(tableData.value[i].date) - new Date(date))
    if (absDiff < bestDiff) { bestDiff = absDiff; bestIdx = i }
  }

  // Expand table and go to the right page
  tableCollapsed.value = false
  tablePage.value = Math.floor(bestIdx / TABLE_PAGE_SIZE) + 1
  highlightDate.value = tableData.value[bestIdx].date

  // Scroll the row into view after DOM update
  nextTick(() => {
    const row = document.querySelector(`[data-date="${highlightDate.value}"]`)
    if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })

  // Auto-clear highlight after 3s
  clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => { highlightDate.value = null }, 3000)
}

function handleChartDateClick(date) {
  navigateToDate(date)
}

function handleJumpDate() {
  if (jumpDate.value) navigateToDate(jumpDate.value)
}

async function fetchData() {
  loading.value = true
  try {
    const [srcRes, sumRes] = await Promise.all([
      listFinanceSources(),
      getFinanceSummary(),
    ])
    if (srcRes.code === 0) sources.value = srcRes.data
    if (sumRes.code === 0) summaries.value = sumRes.data

    if (!selectedSourceId.value && filteredSources.value.length) {
      selectedSourceId.value = filteredSources.value[0].id
    }
  } catch {
    toast.error('加载金融数据失败')
  } finally {
    loading.value = false
  }
}

async function fetchTimeseries() {
  if (!selectedSourceId.value) {
    allSeriesData.value = []
    return
  }
  chartLoading.value = true
  try {
    const res = await getTimeseries(selectedSourceId.value, { limit: 5000 })
    if (res.code === 0 && res.data) {
      allSeriesData.value = res.data.series
      chartCategory.value = res.data.category || 'macro'
      chartSourceName.value = res.data.source_name || ''
    }
  } catch {
    toast.error('加载图表数据失败')
  } finally {
    chartLoading.value = false
  }
}

function selectSource(sourceId) {
  selectedSourceId.value = sourceId
}

function viewAnalysis(contentId) {
  detailContentId.value = contentId
  detailModalVisible.value = true
}

function formatValue(point) {
  if (point.close !== undefined && point.close !== null) return Number(point.close).toFixed(2)
  if (point.unit_nav !== undefined && point.unit_nav !== null) return Number(point.unit_nav).toFixed(4)
  if (point.value !== undefined && point.value !== null) {
    const v = Number(point.value)
    if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
    return v.toFixed(2)
  }
  return '-'
}

function formatPct(pct) {
  if (pct == null) return null
  return pct.toFixed(2)
}

// Watch tab change: auto-select first source
watch(activeTab, () => {
  const filtered = filteredSources.value
  if (filtered.length) {
    selectedSourceId.value = filtered[0].id
  } else {
    selectedSourceId.value = ''
    allSeriesData.value = []
  }
  resetTableState()
})

// Watch source change: re-fetch data
watch(selectedSourceId, () => {
  resetTableState()
  if (selectedSourceId.value) fetchTimeseries()
})

// Watch time range change: reset table pagination
watch(timeRange, () => {
  resetTableState()
})

onMounted(() => {
  fetchData().then(() => {
    if (selectedSourceId.value) fetchTimeseries()
  })
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Sticky header -->
    <div class="px-4 pt-3 pb-2 space-y-2.5 sticky top-0 bg-white z-10 border-b border-slate-100 shrink-0">
      <!-- Tab pills + 添加按钮 -->
      <div class="flex items-center justify-between gap-2">
        <div class="inline-flex items-center gap-0.5 p-1 bg-slate-100 rounded-xl">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="px-3 py-1.5 sm:px-4 sm:py-2 text-xs sm:text-sm font-medium rounded-lg transition-all duration-200"
        :class="activeTab === tab.key
          ? 'bg-white text-slate-800 shadow-sm'
          : 'text-slate-500 hover:text-slate-700'"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
        </div>
        <button
          class="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors shrink-0"
          @click="router.push('/sources')"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span class="hidden sm:inline">添加数据源</span>
        </button>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty state -->
    <div v-else-if="!filteredSources.length" class="text-center py-24">
      <div class="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
        <svg class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 3v18h18 M7 16l4-4 3 3 5-6" />
        </svg>
      </div>
      <h3 class="text-base font-semibold text-slate-700 mb-1">暂无{{ tabs.find(t => t.key === activeTab)?.label }}数据源</h3>
      <p class="text-sm text-slate-400 mb-5">添加一个 AkShare 数据源开始追踪金融数据</p>
      <button
        class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
        @click="router.push('/sources')"
      >
        前往添加
      </button>
    </div>

    <template v-else>
      <!-- 摘要卡片横排网格 -->
      <div v-if="filteredSummaries.length" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 mb-6">
        <FinanceSummaryCard
          v-for="s in filteredSummaries"
          :key="s.source_id"
          :name="s.name"
          :value="s.value"
          :date="s.date"
          :change="s.change"
          :category="s.category"
          :active="selectedSourceId === s.source_id"
          @click="selectSource(s.source_id)"
        />
      </div>

      <!-- 无摘要时的来源按钮 -->
      <div v-else-if="filteredSources.length" class="flex flex-wrap gap-2 mb-6">
        <button
          v-for="s in filteredSources"
          :key="s.id"
          class="px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200"
          :class="selectedSourceId === s.id
            ? 'bg-indigo-50 text-indigo-700 border border-indigo-300'
            : 'bg-white text-slate-600 border border-slate-200 hover:border-slate-300'"
          @click="selectSource(s.id)"
        >
          {{ s.name }}
        </button>
      </div>

      <!-- 控制栏 -->
      <div v-if="selectedSourceId" class="mb-5 space-y-2">
        <!-- 来源选择 + 数据量 -->
        <div class="flex items-center gap-2">
          <select
            v-model="selectedSourceId"
            class="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none min-w-0 max-w-[180px] sm:max-w-none"
          >
            <option v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>

          <span v-if="selectedSource" class="text-xs text-slate-400 shrink-0">
            {{ chartData.length }} / {{ allSeriesData.length }} 条
          </span>
        </div>

        <!-- 时间范围 + 对比模式 -->
        <div class="flex items-center justify-between gap-2 sm:justify-start">
          <!-- 时间范围 pills -->
          <div class="flex items-center gap-0.5 p-0.5 bg-slate-100 rounded-lg">
            <button
              v-for="r in timeRanges"
              :key="r.key"
              class="px-2 py-1 sm:px-2.5 text-xs font-medium rounded-md transition-all duration-200"
              :class="timeRange === r.key
                ? 'bg-white text-slate-700 shadow-sm'
                : 'text-slate-400 hover:text-slate-600'"
              @click="timeRange = r.key"
            >
              {{ r.label }}
            </button>
          </div>

          <!-- 对比模式 pills -->
          <div class="flex items-center gap-0.5 p-0.5 bg-slate-100 rounded-lg">
            <button
              v-for="m in compareModes"
              :key="m.key"
              class="px-2 py-1 sm:px-2.5 text-xs font-medium rounded-md transition-all duration-200"
              :class="compareMode === m.key
                ? 'bg-white text-slate-700 shadow-sm'
                : 'text-slate-400 hover:text-slate-600'"
              @click="compareMode = m.key"
            >
              {{ m.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- 图表 -->
      <div v-if="selectedSourceId" class="space-y-5">
        <div class="bg-white rounded-2xl border border-slate-200/60 shadow-sm overflow-hidden">
          <div class="px-2 py-2">
            <FinanceChart
              :series="chartData"
              :category="chartCategory"
              :source-name="chartSourceName"
              :loading="chartLoading"
              :compare-mode="compareMode"
              :zoom-start="chartZoomStart"
              @date-click="handleChartDateClick"
            />
          </div>
        </div>

        <!-- 告警提示 -->
        <div v-if="chartData.some(p => p.alert)" class="p-3 bg-amber-50 border border-amber-200 rounded-xl">
          <div class="flex items-center gap-2 text-sm text-amber-700">
            <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span class="font-medium">告警触发:</span>
            <span v-for="point in chartData.filter(p => p.alert)" :key="point.date" class="mr-2">
              {{ point.alert.label }} ({{ point.date }}: {{ point.alert.value }})
            </span>
          </div>
        </div>

        <!-- 数据明细表 -->
        <div v-if="tableData.length" class="bg-white rounded-2xl border border-slate-200/60 shadow-sm overflow-hidden">
          <div class="px-4 py-3 sm:px-5 sm:py-4 border-b border-slate-100 flex items-center justify-between gap-2 sm:gap-3">
            <div class="flex items-center gap-2 sm:gap-3">
              <h3 class="text-sm font-semibold text-slate-700">数据明细</h3>
              <span class="text-xs text-slate-400">
                共 {{ tableData.length }} 条<template v-if="!tableCollapsed"> · 第 {{ tablePage }}/{{ tableTotalPages }} 页</template>
              </span>
            </div>
            <div class="flex items-center gap-2">
              <!-- 日期跳转 (大屏显示) -->
              <div class="hidden sm:inline-flex items-center gap-1">
                <input
                  v-model="jumpDate"
                  type="date"
                  class="px-2 py-1 text-xs border border-slate-200 rounded-lg bg-white text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none w-[130px]"
                  placeholder="跳转日期"
                  @keydown.enter="handleJumpDate"
                />
                <button
                  class="px-2 py-1 text-xs font-medium text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-md transition-colors"
                  :class="{ 'opacity-40 pointer-events-none': !jumpDate }"
                  @click="handleJumpDate"
                >
                  跳转
                </button>
              </div>
              <!-- 展开/收起 -->
              <button
                v-if="tableData.length > TABLE_COLLAPSED_SIZE"
                class="inline-flex items-center gap-1 text-xs font-medium text-indigo-500 hover:text-indigo-700 transition-colors"
                @click="tableCollapsed ? expandTable() : collapseTable()"
              >
                {{ tableCollapsed ? '查看全部' : '收起' }}
                <svg class="w-3.5 h-3.5 transition-transform duration-200" :class="{ 'rotate-180': !tableCollapsed }" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-slate-100">
                  <th class="px-3 py-2.5 sm:px-5 sm:py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">日期</th>
                  <th class="px-3 py-2.5 sm:px-5 sm:py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">
                    {{ chartCategory === 'stock' ? '收盘' : chartCategory === 'fund' && tableData[0]?.unit_nav !== undefined ? '净值' : '值' }}
                  </th>
                  <th class="px-3 py-2.5 sm:px-5 sm:py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">
                    <span class="inline-flex items-center gap-1">
                      环比
                      <span class="hidden sm:inline text-[10px] text-slate-300 font-normal normal-case">(MoM)</span>
                    </span>
                  </th>
                  <th class="px-3 py-2.5 sm:px-5 sm:py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">
                    <span class="inline-flex items-center gap-1">
                      同比
                      <span class="hidden sm:inline text-[10px] text-slate-300 font-normal normal-case">(YoY)</span>
                    </span>
                  </th>
                  <th v-if="chartCategory === 'stock'" class="hidden sm:table-cell px-3 py-2.5 sm:px-5 sm:py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">开盘</th>
                  <th v-if="chartCategory === 'stock'" class="hidden sm:table-cell px-3 py-2.5 sm:px-5 sm:py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">最高</th>
                  <th v-if="chartCategory === 'stock'" class="hidden sm:table-cell px-3 py-2.5 sm:px-5 sm:py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">最低</th>
                  <th class="px-3 py-2.5 sm:px-5 sm:py-3 text-center text-xs font-medium text-slate-400 uppercase tracking-wider">分析</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="point in displayedTableData"
                  :key="point.date"
                  :data-date="point.date"
                  class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors duration-300"
                  :class="highlightDate === point.date ? 'bg-indigo-50/70 ring-1 ring-inset ring-indigo-200' : ''"
                >
                  <td class="px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-slate-600 font-medium">{{ point.date }}</td>
                  <td class="px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-slate-700 text-right font-mono">{{ formatValue(point) }}</td>
                  <td class="px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-right font-mono">
                    <span v-if="formatPct(point._momPct) !== null"
                      :class="point._momPct > 0 ? 'text-red-500' : point._momPct < 0 ? 'text-emerald-500' : 'text-slate-400'"
                    >
                      {{ point._momPct > 0 ? '+' : '' }}{{ formatPct(point._momPct) }}%
                    </span>
                    <span v-else class="text-slate-300">-</span>
                  </td>
                  <td class="px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-right font-mono">
                    <span v-if="formatPct(point._yoyPct) !== null"
                      :class="point._yoyPct > 0 ? 'text-red-500' : point._yoyPct < 0 ? 'text-emerald-500' : 'text-slate-400'"
                    >
                      {{ point._yoyPct > 0 ? '+' : '' }}{{ formatPct(point._yoyPct) }}%
                    </span>
                    <span v-else class="text-slate-300">-</span>
                  </td>
                  <td v-if="chartCategory === 'stock'" class="hidden sm:table-cell px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-slate-500 text-right font-mono">{{ point.open != null ? Number(point.open).toFixed(2) : '-' }}</td>
                  <td v-if="chartCategory === 'stock'" class="hidden sm:table-cell px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-slate-500 text-right font-mono">{{ point.high != null ? Number(point.high).toFixed(2) : '-' }}</td>
                  <td v-if="chartCategory === 'stock'" class="hidden sm:table-cell px-3 py-2.5 sm:px-5 sm:py-3 text-xs text-slate-500 text-right font-mono">{{ point.low != null ? Number(point.low).toFixed(2) : '-' }}</td>
                  <td class="px-3 py-2.5 sm:px-5 sm:py-3 text-center">
                    <button
                      v-if="point.analysis_id"
                      class="text-xs text-indigo-500 hover:text-indigo-700 font-medium transition-colors"
                      @click="viewAnalysis(point.analysis_id)"
                    >
                      查看
                    </button>
                    <span v-else class="text-slate-300 text-xs">-</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 分页器 (仅展开模式且超过一页时显示) -->
          <div v-if="!tableCollapsed && tableTotalPages > 1" class="px-4 py-3 sm:px-5 border-t border-slate-100 flex items-center justify-between">
            <span class="text-xs text-slate-400">
              第 {{ (tablePage - 1) * TABLE_PAGE_SIZE + 1 }}-{{ Math.min(tablePage * TABLE_PAGE_SIZE, tableData.length) }} 条
            </span>
            <div class="flex items-center gap-1">
              <button
                class="px-2.5 py-1 text-xs font-medium rounded-md transition-all duration-200"
                :class="tablePage > 1
                  ? 'text-slate-600 hover:bg-slate-100'
                  : 'text-slate-300 cursor-not-allowed'"
                :disabled="tablePage <= 1"
                @click="tablePage--"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <template v-for="p in tableTotalPages" :key="p">
                <button
                  v-if="p === 1 || p === tableTotalPages || (p >= tablePage - 1 && p <= tablePage + 1)"
                  class="min-w-[28px] px-1.5 py-1 text-xs font-medium rounded-md transition-all duration-200"
                  :class="p === tablePage
                    ? 'bg-indigo-50 text-indigo-600'
                    : 'text-slate-500 hover:bg-slate-100'"
                  @click="tablePage = p"
                >
                  {{ p }}
                </button>
                <span
                  v-else-if="p === tablePage - 2 || p === tablePage + 2"
                  class="text-xs text-slate-300 px-0.5"
                >...</span>
              </template>
              <button
                class="px-2.5 py-1 text-xs font-medium rounded-md transition-all duration-200"
                :class="tablePage < tableTotalPages
                  ? 'text-slate-600 hover:bg-slate-100'
                  : 'text-slate-300 cursor-not-allowed'"
                :disabled="tablePage >= tableTotalPages"
                @click="tablePage++"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 未选择来源 -->
      <div v-else class="text-center py-16">
        <svg class="w-12 h-12 text-slate-200 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 3v18h18 M7 16l4-4 3 3 5-6" />
        </svg>
        <p class="text-sm text-slate-400">选择一个指标查看详情</p>
      </div>
    </template>

      </div>
    </div>

    <!-- Content Detail Modal -->
    <ContentDetailModal
      :visible="detailModalVisible"
      :content-id="detailContentId"
      @close="detailModalVisible = false"
    />
  </div>
</template>
