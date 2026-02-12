<script setup>
import { ref, onMounted, computed } from 'vue'
import dayjs from 'dayjs'
import { useSourcesStore } from '@/stores/sources'
import { useToast } from '@/composables/useToast'
import SourceFormModal from '@/components/source-form-modal.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'
import { importOPML, exportOPML, getCollectionHistory } from '@/api/sources'

const store = useSourcesStore()
const toast = useToast()

const fileInputRef = ref(null)

// 采集历史弹窗
const showHistoryModal = ref(false)
const historySource = ref(null)
const historyRecords = ref([])
const historyLoading = ref(false)
const historyPage = ref(1)
const historyPageSize = ref(20)
const historyTotal = ref(0)

const searchQuery = ref('')
const filterType = ref('')

const showFormModal = ref(false)
const editingSource = ref(null)
const showDeleteDialog = ref(false)
const deletingSource = ref(null)
const showCascadeDialog = ref(false)
const cascadeCount = ref(0)
const collectingId = ref(null)

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

const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

function fetchWithFilters() {
  const params = {}
  if (searchQuery.value) params.q = searchQuery.value
  if (filterType.value) params.source_type = filterType.value
  store.fetchSources(params)
}

onMounted(() => fetchWithFilters())

function handleSearch() {
  store.currentPage = 1
  fetchWithFilters()
}

function handleFilterChange() {
  store.currentPage = 1
  fetchWithFilters()
}

function goToPage(page) {
  if (page < 1 || page > totalPages.value) return
  store.currentPage = page
  fetchWithFilters()
}

function openCreate() {
  editingSource.value = null
  showFormModal.value = true
}

function openEdit(source) {
  editingSource.value = source
  showFormModal.value = true
}

async function handleFormSubmit(formData) {
  let res
  if (editingSource.value) {
    res = await store.updateSource(editingSource.value.id, formData)
  } else {
    res = await store.createSource(formData)
  }
  if (res.code === 0) showFormModal.value = false
}

function openDelete(source) {
  deletingSource.value = source
  showDeleteDialog.value = true
}

async function handleDelete() {
  showDeleteDialog.value = false
  const res = await store.deleteSource(deletingSource.value.id)
  if (res.code === 1) {
    cascadeCount.value = res.data.content_count
    showCascadeDialog.value = true
  }
}

async function handleCascadeDelete() {
  showCascadeDialog.value = false
  await store.deleteSource(deletingSource.value.id, true)
}

async function handleCollect(source) {
  collectingId.value = source.id
  try {
    const res = await store.collectSource(source.id)
    if (res.code === 0) {
      toast.success(`发现 ${res.data.items_new} 条新内容`, { title: source.name })
    } else {
      toast.error(res.message || '采集失败', { title: source.name })
    }
    fetchWithFilters()
  } catch (e) {
    toast.error('采集请求失败', { title: source.name })
  } finally {
    collectingId.value = null
  }
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm') : '-'
}

function formatInterval(seconds) {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
  return `${Math.round(seconds / 3600)}小时`
}

// OPML 导入导出
function triggerFileImport() {
  fileInputRef.value?.click()
}

async function handleFileImport(event) {
  const file = event.target.files?.[0]
  if (!file) return

  try {
    const res = await importOPML(file)
    if (res.code === 0) {
      toast.success(`导入完成: 新增 ${res.data.created} 个源，跳过 ${res.data.skipped} 个`)
      fetchWithFilters()
    } else {
      toast.error(res.message || '导入失败')
    }
  } catch (error) {
    toast.error('导入 OPML 失败')
  } finally {
    // 清空 input，允许重复选择同一文件
    event.target.value = ''
  }
}

function handleExport() {
  // 直接打开下载链接
  window.open(exportOPML(), '_blank')
  toast.success('正在导出 OPML 文件')
}

// 采集历史
async function openHistory(source) {
  historySource.value = source
  historyPage.value = 1
  showHistoryModal.value = true
  await fetchHistory()
}

async function fetchHistory() {
  if (!historySource.value) return

  historyLoading.value = true
  try {
    const res = await getCollectionHistory(historySource.value.id, {
      page: historyPage.value,
      page_size: historyPageSize.value,
    })
    if (res.code === 0) {
      historyRecords.value = res.data
      historyTotal.value = res.total
    }
  } catch (error) {
    toast.error('获取采集历史失败')
  } finally {
    historyLoading.value = false
  }
}

function goToHistoryPage(page) {
  const totalPages = Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value))
  if (page < 1 || page > totalPages) return
  historyPage.value = page
  fetchHistory()
}
</script>

<template>
  <div class="p-4 md:p-8 max-w-7xl mx-auto">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
      <div>
        <h2 class="text-2xl font-bold tracking-tight text-slate-900">数据源管理</h2>
        <p class="text-sm text-slate-400 mt-1">配置信息采集来源与调度</p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <!-- OPML 导入 -->
        <input
          ref="fileInputRef"
          type="file"
          accept=".opml,.xml"
          class="hidden"
          @change="handleFileImport"
        />
        <button
          class="px-3.5 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200 flex items-center gap-2"
          @click="triggerFileImport"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
          </svg>
          <span class="hidden sm:inline">导入 OPML</span>
          <span class="sm:hidden">导入</span>
        </button>

        <!-- OPML 导出 -->
        <button
          class="px-3.5 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200 flex items-center gap-2"
          @click="handleExport"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          <span class="hidden sm:inline">导出 OPML</span>
          <span class="sm:hidden">导出</span>
        </button>

        <!-- 添加数据源 -->
        <button
          class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 transition-all duration-200 shadow-sm shadow-indigo-200 flex items-center gap-2"
          @click="openCreate"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          添加数据源
        </button>
      </div>
    </div>

    <!-- Search + Filter -->
    <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mb-6">
      <div class="relative flex-1">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索名称或描述..."
          class="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
          @keyup.enter="handleSearch"
        />
        <svg class="absolute left-3.5 top-3 h-4 w-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <div class="flex items-center gap-3">
        <select
          v-model="filterType"
          class="flex-1 sm:flex-none px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer"
          @change="handleFilterChange"
        >
          <option value="">全部类型</option>
          <option v-for="(label, value) in typeLabels" :key="value" :value="value">{{ label }}</option>
        </select>
        <button
          class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
          @click="handleSearch"
        >
          搜索
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="text-center py-16 text-slate-300">
      <svg class="w-8 h-8 mx-auto mb-3 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm">加载中...</span>
    </div>

    <!-- Empty -->
    <div v-else-if="store.sources.length === 0" class="text-center py-16">
      <svg class="w-16 h-16 mx-auto mb-4 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
      <p class="text-slate-400 mb-4">暂无数据源</p>
      <button
        class="px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-xl hover:bg-indigo-50 transition-all duration-200"
        @click="openCreate"
      >
        添加第一个数据源
      </button>
    </div>

    <!-- Table (Desktop) -->
    <div v-else>
      <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <table class="w-full">
          <thead>
            <tr class="border-b border-slate-100">
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">名称</th>
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">类型</th>
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">URL</th>
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">流水线</th>
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">调度</th>
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">最近采集</th>
              <th class="px-6 py-3.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">状态</th>
              <th class="px-6 py-3.5 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="source in store.sources" :key="source.id" class="border-b border-slate-50 last:border-0 hover:bg-slate-50/50 transition-colors duration-150">
              <td class="px-6 py-4">
                <div class="text-sm font-medium text-slate-800">{{ source.name }}</div>
                <div v-if="source.description" class="text-xs text-slate-400 truncate max-w-[200px] mt-0.5">{{ source.description }}</div>
              </td>
              <td class="px-6 py-4">
                <span class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg" :class="typeStyles[source.source_type] || 'bg-slate-100 text-slate-600'">
                  {{ typeLabels[source.source_type] || source.source_type }}
                </span>
              </td>
              <td class="px-6 py-4 text-sm text-slate-400 max-w-[180px] truncate" :title="source.url">
                {{ source.url || '-' }}
              </td>
              <td class="px-6 py-4 text-sm text-slate-500">
                {{ source.pipeline_template_name || '-' }}
              </td>
              <td class="px-6 py-4 text-sm text-slate-500">
                <template v-if="source.schedule_enabled">
                  {{ formatInterval(source.schedule_interval) }}
                </template>
                <span v-else class="text-slate-300">已禁用</span>
              </td>
              <td class="px-6 py-4 text-sm text-slate-400">
                {{ formatTime(source.last_collected_at) }}
              </td>
              <td class="px-6 py-4">
                <span
                  class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg"
                  :class="source.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'"
                >
                  {{ source.is_active ? '活跃' : '停用' }}
                </span>
              </td>
              <td class="px-6 py-4 text-right">
                <div class="flex items-center justify-end gap-1">
                  <button
                    class="px-2.5 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors duration-150 disabled:opacity-50"
                    :disabled="collectingId === source.id"
                    @click="handleCollect(source)"
                  >
                    <span v-if="collectingId === source.id" class="flex items-center gap-1">
                      <svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>
                      采集中
                    </span>
                    <span v-else>采集</span>
                  </button>
                  <button
                    class="px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 rounded-lg transition-colors duration-150"
                    @click="openHistory(source)"
                    title="查看采集历史"
                  >
                    历史
                  </button>
                  <button
                    class="px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 rounded-lg transition-colors duration-150"
                    @click="openEdit(source)"
                  >
                    编辑
                  </button>
                  <button
                    class="px-2.5 py-1.5 text-xs font-medium text-rose-500 hover:bg-rose-50 rounded-lg transition-colors duration-150"
                    @click="openDelete(source)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Pagination -->
        <div v-if="store.total > store.pageSize" class="flex items-center justify-between px-6 py-4 border-t border-slate-100">
          <span class="text-sm text-slate-400">
            共 {{ store.total }} 条，第 {{ store.currentPage }}/{{ totalPages }} 页
          </span>
          <div class="flex items-center gap-1">
            <button
              class="px-3 py-1.5 text-sm text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-150"
              :disabled="store.currentPage <= 1"
              @click="goToPage(store.currentPage - 1)"
            >
              上一页
            </button>
            <button
              class="px-3 py-1.5 text-sm text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-150"
              :disabled="store.currentPage >= totalPages"
              @click="goToPage(store.currentPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>

      <!-- Mobile Cards -->
      <div class="md:hidden space-y-3">
        <div v-for="source in store.sources" :key="source.id" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
          <div class="flex items-start justify-between gap-3 mb-3">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-semibold text-slate-800">{{ source.name }}</div>
              <div v-if="source.description" class="text-xs text-slate-400 truncate mt-0.5">{{ source.description }}</div>
            </div>
            <span
              class="inline-flex px-2 py-0.5 text-xs font-medium rounded-lg shrink-0"
              :class="source.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'"
            >
              {{ source.is_active ? '活跃' : '停用' }}
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-2 mb-3">
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-lg" :class="typeStyles[source.source_type] || 'bg-slate-100 text-slate-600'">
              {{ typeLabels[source.source_type] || source.source_type }}
            </span>
            <span v-if="source.schedule_enabled" class="text-xs text-slate-400">
              {{ formatInterval(source.schedule_interval) }}
            </span>
            <span v-else class="text-xs text-slate-300">调度已禁用</span>
          </div>
          <div v-if="source.url" class="text-xs text-slate-400 truncate mb-3" :title="source.url">{{ source.url }}</div>
          <div class="text-xs text-slate-400 mb-3">
            最近采集: {{ formatTime(source.last_collected_at) }}
          </div>
          <div class="flex items-center gap-1.5 pt-3 border-t border-slate-100">
            <button
              class="flex-1 px-3 py-2 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors disabled:opacity-50"
              :disabled="collectingId === source.id"
              @click="handleCollect(source)"
            >
              {{ collectingId === source.id ? '采集中...' : '采集' }}
            </button>
            <button
              class="px-3 py-2 text-xs font-medium text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
              @click="openHistory(source)"
            >
              历史
            </button>
            <button
              class="px-3 py-2 text-xs font-medium text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
              @click="openEdit(source)"
            >
              编辑
            </button>
            <button
              class="px-3 py-2 text-xs font-medium text-rose-500 hover:bg-rose-50 rounded-lg transition-colors"
              @click="openDelete(source)"
            >
              删除
            </button>
          </div>
        </div>

        <!-- Mobile Pagination -->
        <div v-if="store.total > store.pageSize" class="flex items-center justify-between pt-2">
          <span class="text-sm text-slate-400">
            {{ store.currentPage }}/{{ totalPages }}
          </span>
          <div class="flex items-center gap-1">
            <button
              class="px-3 py-1.5 text-sm text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-150"
              :disabled="store.currentPage <= 1"
              @click="goToPage(store.currentPage - 1)"
            >
              上一页
            </button>
            <button
              class="px-3 py-1.5 text-sm text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-150"
              :disabled="store.currentPage >= totalPages"
              @click="goToPage(store.currentPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </div>

    <SourceFormModal
      :visible="showFormModal"
      :source="editingSource"
      @submit="handleFormSubmit"
      @cancel="showFormModal = false"
    />

    <ConfirmDialog
      :visible="showDeleteDialog"
      title="删除数据源"
      :message="`确定要删除「${deletingSource?.name}」吗？`"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDelete"
      @cancel="showDeleteDialog = false"
    />

    <ConfirmDialog
      :visible="showCascadeDialog"
      title="数据源有关联内容"
      :message="`该数据源关联 ${cascadeCount} 条内容，是否一并删除？`"
      confirm-text="全部删除"
      :danger="true"
      @confirm="handleCascadeDelete"
      @cancel="showCascadeDialog = false"
    />

    <!-- 采集历史弹窗 -->
    <Transition
      enter-active-class="transition-all duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-all duration-150"
      leave-to-class="opacity-0"
    >
      <div v-if="showHistoryModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="showHistoryModal = false">
        <div class="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col">
          <div class="flex items-center justify-between p-6 border-b border-slate-100">
            <h3 class="text-lg font-bold text-slate-900">采集历史 - {{ historySource?.name }}</h3>
            <button @click="showHistoryModal = false" class="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="flex-1 overflow-y-auto p-6">
            <div v-if="historyLoading" class="flex items-center justify-center py-16">
              <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
            </div>
            <div v-else-if="historyRecords.length === 0" class="text-center py-16 text-slate-400">暂无采集记录</div>
            <div v-else class="space-y-3">
              <div v-for="record in historyRecords" :key="record.id" class="p-4 bg-slate-50 rounded-xl border border-slate-200/60">
                <div class="flex items-center justify-between mb-2">
                  <span class="text-sm font-medium" :class="record.status === 'completed' ? 'text-emerald-600' : record.status === 'failed' ? 'text-rose-600' : 'text-slate-600'">
                    {{ record.status === 'completed' ? '✓ 成功' : record.status === 'failed' ? '✗ 失败' : '进行中' }}
                  </span>
                  <span class="text-xs text-slate-400">{{ formatTime(record.started_at) }}</span>
                </div>
                <div class="grid grid-cols-2 gap-3 text-sm">
                  <div><span class="text-slate-500">发现:</span> <span class="font-medium">{{ record.items_found || 0 }} 条</span></div>
                  <div><span class="text-slate-500">新增:</span> <span class="font-medium text-emerald-600">{{ record.items_new || 0 }} 条</span></div>
                </div>
                <div v-if="record.error_message" class="mt-2 text-xs text-rose-500 truncate">{{ record.error_message }}</div>
              </div>
            </div>
          </div>
          <div v-if="historyTotal > historyPageSize" class="flex items-center justify-between p-4 border-t border-slate-100">
            <span class="text-sm text-slate-400">共 {{ historyTotal }} 条</span>
            <div class="flex gap-2">
              <button :disabled="historyPage <= 1" @click="goToHistoryPage(historyPage - 1)" class="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-40">上一页</button>
              <button :disabled="historyPage >= Math.ceil(historyTotal / historyPageSize)" @click="goToHistoryPage(historyPage + 1)" class="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-40">下一页</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
