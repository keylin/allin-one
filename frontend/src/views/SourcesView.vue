<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { useSourcesStore } from '@/stores/sources'
import { useToast } from '@/composables/useToast'
import { useScrollLock } from '@/composables/useScrollLock'
import SourceFormModal from '@/components/source-form-modal.vue'
import ContentSubmitModal from '@/components/content-submit-modal.vue'
import SourceDetailPanel from '@/components/source-detail-panel.vue'
import DetailDrawer from '@/components/detail-drawer.vue'
import { importOPML, exportOPML } from '@/api/sources'

const route = useRoute()
const router = useRouter()
const store = useSourcesStore()
const toast = useToast()

const fileInputRef = ref(null)

const searchQuery = ref(route.query.q || '')
const filterType = ref(route.query.type || '')
const filterCategory = ref(route.query.category || '')
const sortBy = ref(route.query.sort_by || 'created_at')
const sortOrder = ref(route.query.sort_order || 'desc')

const showFormModal = ref(false)
const editingSource = ref(null)
const deletingSource = ref(null)
const togglingId = ref(null)
const showDeleteDialog = ref(false)
const deleteContentChecked = ref(false)
const collectingId = ref(null)
const collectingAll = ref(false)
const showSubmitModal = ref(false)
const submitTargetSource = ref(null)

// Batch ops
const selectedIds = ref([])
const showBatchDeleteDialog = ref(false)
const batchDeleteContentChecked = ref(false)
const batchContentCount = ref(0)

useScrollLock(showDeleteDialog)
useScrollLock(showBatchDeleteDialog)

// Detail drawer
const selectedSource = ref(null)
const drawerVisible = ref(false)

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

const USER_SOURCE_TYPES = new Set(['user.note', 'file.upload', 'system.notification'])

function isUserSource(source) {
  return USER_SOURCE_TYPES.has(source.source_type)
}

const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

function getDisplayUrl(source) {
  if (USER_SOURCE_TYPES.has(source.source_type)) return '-'
  if (source.source_type === 'rss.hub' && source.config_json) {
    try {
      const config = JSON.parse(source.config_json)
      return config.rsshub_route || '-'
    } catch {
      return '-'
    }
  }
  return source.url || '-'
}

function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (filterType.value) query.type = filterType.value
  if (filterCategory.value) query.category = filterCategory.value
  if (sortBy.value !== 'created_at') query.sort_by = sortBy.value
  if (sortOrder.value !== 'desc') query.sort_order = sortOrder.value
  if (store.currentPage > 1) query.page = String(store.currentPage)
  router.replace({ query }).catch(() => {})
}

function fetchWithFilters() {
  const params = {}
  if (searchQuery.value) params.q = searchQuery.value
  if (filterType.value) params.source_type = filterType.value
  if (filterCategory.value) params.category = filterCategory.value
  if (sortBy.value) params.sort_by = sortBy.value
  if (sortOrder.value) params.sort_order = sortOrder.value
  store.fetchSources(params)
  syncQueryParams()
}

onMounted(() => {
  if (route.query.page) store.currentPage = parseInt(route.query.page) || 1
  if (route.query.sort_by) sortBy.value = route.query.sort_by
  if (route.query.sort_order) sortOrder.value = route.query.sort_order
  if (route.query.category) filterCategory.value = route.query.category
  fetchWithFilters()
})

function handleSearch() {
  store.currentPage = 1
  fetchWithFilters()
}

function handleFilterChange() {
  store.currentPage = 1
  fetchWithFilters()
}

function handleSort(field) {
  if (sortBy.value === field) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = field
    sortOrder.value = 'desc'
  }
  store.currentPage = 1
  fetchWithFilters()
}

function goToPage(page) {
  if (page < 1 || page > totalPages.value) return
  store.currentPage = page
  fetchWithFilters()
}

let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => handleSearch(), 300)
}

function selectSource(source) {
  selectedSource.value = source
  drawerVisible.value = true
}

function closeDrawer() {
  drawerVisible.value = false
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
  if (res.code === 0) {
    showFormModal.value = false
    if (editingSource.value && selectedSource.value?.id === editingSource.value.id) {
      const updated = store.sources.find(s => s.id === editingSource.value.id)
      if (updated) selectedSource.value = updated
    }
  }
}

function handleDelete(source) {
  deletingSource.value = source
  deleteContentChecked.value = false
  showDeleteDialog.value = true
}

async function confirmDelete() {
  showDeleteDialog.value = false
  const cascade = deleteContentChecked.value
  const res = await store.deleteSource(deletingSource.value.id, cascade)
  if (res.code === 0) {
    const msg = cascade ? '已删除数据源及关联内容' : '已删除数据源'
    toast.success(msg, { title: deletingSource.value.name })
    if (selectedSource.value?.id === deletingSource.value.id) {
      selectedSource.value = null
      drawerVisible.value = false
    }
  }
}

async function handleToggleActive(source) {
  togglingId.value = source.id
  try {
    const newState = !source.is_active
    const res = await store.updateSource(source.id, { is_active: newState })
    if (res.code === 0) {
      toast.success(newState ? '已启用' : '已停用', { title: source.name })
      fetchWithFilters()
      if (selectedSource.value?.id === source.id) {
        selectedSource.value = { ...selectedSource.value, is_active: newState }
      }
    }
  } finally {
    togglingId.value = null
  }
}

function openSubmitContent(source) {
  submitTargetSource.value = source
  showSubmitModal.value = true
}

function handleSubmitSuccess() {
  showSubmitModal.value = false
  toast.success('内容提交成功', { title: submitTargetSource.value?.name })
}

async function handleCollect(source) {
  collectingId.value = source.id
  try {
    const res = await store.collectSource(source.id)
    if (res.code === 0) {
      toast.success('采集任务已提交', { title: source.name })
      setTimeout(() => fetchWithFilters(), 2000)
    } else {
      toast.error(res.message || '采集失败', { title: source.name })
    }
  } catch {
    toast.error('采集请求失败', { title: source.name })
  } finally {
    collectingId.value = null
  }
}

async function handleCollectAll() {
  collectingAll.value = true
  try {
    const res = await store.collectAll()
    if (res.code === 0) {
      const d = res.data
      let msg = `${d.sources_queued} 个采集任务已提交`
      if (d.sources_skipped > 0) msg += `，${d.sources_skipped} 个已在队列中`
      toast.success(msg, { title: '一键采集' })
    } else {
      toast.error(res.message || '采集失败')
    }
  } catch {
    toast.error('采集请求失败')
  } finally {
    collectingAll.value = false
  }
}

function toggleSelect(id, event) {
  if (event) event.stopPropagation()
  const idx = selectedIds.value.indexOf(id)
  if (idx > -1) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function toggleSelectAll() {
  if (selectedIds.value.length === store.sources.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = store.sources.map(s => s.id)
  }
}

function openBatchDeleteDialog() {
  batchDeleteContentChecked.value = false
  batchContentCount.value = store.sources
    .filter(s => selectedIds.value.includes(s.id))
    .reduce((sum, s) => sum + (s.content_count || 0), 0)
  showBatchDeleteDialog.value = true
}

async function confirmBatchDelete() {
  showBatchDeleteDialog.value = false
  const cascade = batchDeleteContentChecked.value
  const res = await store.batchDelete(selectedIds.value, cascade)
  if (res.code === 0) {
    const msg = cascade
      ? `已删除 ${res.data.deleted} 个数据源及关联内容`
      : `已删除 ${res.data.deleted} 个数据源`
    toast.success(msg)
    selectedIds.value = []
  }
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('MM-DD HH:mm') : '-'
}

function formatInterval(seconds) {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
  return `${Math.round(seconds / 3600)}小时`
}

function isOverdue(nextCollectionAt) {
  if (!nextCollectionAt) return false
  return dayjs.utc(nextCollectionAt).local().isBefore(dayjs())
}

// OPML import/export
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
  } catch {
    toast.error('导入 OPML 失败')
  } finally {
    event.target.value = ''
  }
}

function handleExport() {
  window.open(exportOPML(), '_blank')
  toast.success('正在导出 OPML 文件')
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Hidden file input -->
    <input
      ref="fileInputRef"
      type="file"
      accept=".opml,.xml,text/xml,application/xml,text/x-opml"
      class="hidden"
      @change="handleFileImport"
    />

    <!-- Sticky header -->
    <div class="px-4 pt-3 pb-2 space-y-2.5 sticky top-0 bg-white z-10 border-b border-slate-100 shrink-0">
      <!-- Header -->
      <div class="flex items-center justify-between gap-2">
        <p class="text-xs text-slate-400">{{ store.total }} 个数据源</p>
        <div class="flex items-center gap-2">
          <button
            class="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all disabled:opacity-50"
            title="一键采集全部"
            :disabled="collectingAll"
            @click="handleCollectAll"
          >
            <svg v-if="collectingAll" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
            </svg>
          </button>
          <button
            class="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-all"
            title="导入 OPML"
            @click="triggerFileImport"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </button>
          <button
            class="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-all"
            title="导出 OPML"
            @click="handleExport"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
          </button>
          <button
            class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-all flex items-center gap-1.5"
            @click="openCreate"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            新增
          </button>
        </div>
      </div>

      <!-- Batch action bar -->
      <div v-if="selectedIds.length > 0" class="flex items-center gap-2">
        <span class="text-sm text-slate-500">已选 {{ selectedIds.length }}</span>
        <button
          class="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-all duration-200"
          @click="openBatchDeleteDialog"
        >批量删除</button>
        <button
          class="px-3 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 rounded-lg transition-all duration-200"
          @click="selectedIds = []"
        >取消</button>
      </div>

      <!-- Filter bar -->
      <div v-else class="flex flex-wrap items-center gap-3">
      <!-- Category tabs -->
      <div class="flex items-center gap-1 bg-slate-100/60 rounded-lg p-0.5">
        <button
          v-for="cat in [{value: '', label: '全部'}, {value: 'network', label: '网络'}, {value: 'user', label: '用户'}]"
          :key="cat.value"
          class="px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200"
          :class="filterCategory === cat.value ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
          @click="filterCategory = cat.value; handleFilterChange()"
        >{{ cat.label }}</button>
      </div>
      <div class="relative flex-1 min-w-[200px] max-w-sm">
        <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索名称..."
          class="w-full bg-white rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all"
          @input="onSearchInput"
        />
      </div>
      <select
        v-model="filterType"
        @change="handleFilterChange"
        class="bg-white text-sm text-slate-600 rounded-lg px-3 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer"
      >
        <option value="">全部类型</option>
        <optgroup label="网络数据">
          <option value="rss.hub">RSSHub</option>
          <option value="rss.standard">RSS/Atom</option>
          <option value="api.akshare">AkShare</option>
          <option value="web.scraper">网页抓取</option>
          <option value="account.bilibili">B站账号</option>
          <option value="account.generic">其他账号</option>
        </optgroup>
        <optgroup label="用户数据">
          <option value="user.note">用户笔记</option>
          <option value="file.upload">文件上传</option>
          <option value="system.notification">系统通知</option>
        </optgroup>
      </select>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">

    <!-- Loading -->
    <div v-if="store.loading" class="flex items-center justify-center py-16">
      <svg class="w-8 h-8 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty -->
    <div v-else-if="store.sources.length === 0" class="text-center py-16">
      <div class="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
        <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
      </div>
      <p class="text-sm text-slate-500 font-medium mb-1">暂无数据源</p>
      <button
        class="text-sm text-indigo-600 hover:text-indigo-700"
        @click="openCreate"
      >
        添加第一个数据源
      </button>
    </div>

    <!-- Desktop table -->
    <template v-else>
      <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <table class="w-full">
          <thead class="bg-slate-50/80">
            <tr>
              <th class="w-10 px-4 py-3">
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  :checked="selectedIds.length === store.sources.length && store.sources.length > 0"
                  @change="toggleSelectAll"
                />
              </th>
              <th
                class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100/80 transition-colors select-none"
                @click="handleSort('name')"
              >
                <div class="flex items-center gap-1.5">
                  <span>名称</span>
                  <svg v-if="sortBy === 'name'" class="w-3.5 h-3.5 shrink-0" :class="sortOrder === 'asc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">URL</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">流水线</th>
              <th
                class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100/80 transition-colors select-none"
                @click="handleSort('calculated_interval')"
              >
                <div class="flex items-center gap-1.5">
                  <span>调度</span>
                  <svg v-if="sortBy === 'calculated_interval'" class="w-3.5 h-3.5 shrink-0" :class="sortOrder === 'asc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </th>
              <th
                class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100/80 transition-colors select-none"
                @click="handleSort('last_collected_at')"
              >
                <div class="flex items-center gap-1.5">
                  <span>最近采集</span>
                  <svg v-if="sortBy === 'last_collected_at'" class="w-3.5 h-3.5 shrink-0" :class="sortOrder === 'asc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </th>
              <th
                class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100/80 transition-colors select-none"
                @click="handleSort('next_collection_at')"
              >
                <div class="flex items-center gap-1.5">
                  <span>下次采集</span>
                  <svg v-if="sortBy === 'next_collection_at'" class="w-3.5 h-3.5 shrink-0" :class="sortOrder === 'asc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </th>
              <th class="px-4 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">状态</th>
              <th class="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr
              v-for="source in store.sources"
              :key="source.id"
              class="hover:bg-slate-50/50 cursor-pointer transition-colors duration-150"
              :class="[
                { 'bg-indigo-50/40': selectedSource?.id === source.id && drawerVisible },
                { 'opacity-60': !source.is_active }
              ]"
              @click="selectSource(source)"
            >
              <td class="w-10 px-4 py-3" @click.stop>
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  :checked="selectedIds.includes(source.id)"
                  @change="toggleSelect(source.id, $event)"
                />
              </td>
              <td class="px-4 py-3 text-sm font-medium text-slate-800 max-w-[180px] truncate">{{ source.name }}</td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md"
                  :class="typeStyles[source.source_type] || 'bg-slate-100 text-slate-600'"
                >
                  {{ typeLabels[source.source_type] || source.source_type }}
                </span>
              </td>
              <td class="px-4 py-3 text-sm text-slate-400 max-w-[200px] truncate">{{ getDisplayUrl(source) }}</td>
              <td class="px-4 py-3 text-sm text-slate-500 truncate max-w-[120px]">{{ source.pipeline_template_name || '-' }}</td>
              <td class="px-4 py-3 text-sm text-slate-500">
                <span v-if="!source.schedule_enabled" class="text-slate-300">禁用</span>
                <span v-else-if="source.schedule_mode === 'manual'" class="text-slate-400">手动</span>
                <span v-else-if="source.schedule_mode === 'fixed' && source.schedule_interval_override">
                  每{{ formatInterval(source.schedule_interval_override) }}
                </span>
                <span v-else-if="source.schedule_mode === 'auto' && source.calculated_interval" class="text-indigo-600">
                  智能 {{ formatInterval(source.calculated_interval) }}
                </span>
                <span v-else class="text-slate-300">-</span>
              </td>
              <td class="px-4 py-3 text-sm text-slate-400">{{ formatTime(source.last_collected_at) }}</td>
              <td class="px-4 py-3 text-sm text-slate-400">
                <span v-if="source.next_collection_at" :class="{ 'text-amber-600 font-medium': isOverdue(source.next_collection_at) }">
                  {{ formatTime(source.next_collection_at) }}
                </span>
                <span v-else class="text-slate-300">-</span>
              </td>
              <td class="px-4 py-3 text-center">
                <span
                  class="inline-flex w-2 h-2 rounded-full"
                  :class="source.is_active ? 'bg-emerald-400' : 'bg-slate-300'"
                ></span>
              </td>
              <td class="px-4 py-3 text-right" @click.stop>
                <div class="flex items-center justify-end gap-1">
                  <button
                    v-if="isUserSource(source)"
                    class="px-2 py-1 text-xs font-medium text-emerald-600 hover:bg-emerald-50 rounded-lg transition-all duration-200"
                    @click="openSubmitContent(source)"
                  >
                    添加内容
                  </button>
                  <button
                    v-else
                    class="px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all duration-200 disabled:opacity-50"
                    :disabled="collectingId === source.id"
                    @click="handleCollect(source)"
                  >
                    {{ collectingId === source.id ? '采集中...' : '采集' }}
                  </button>
                  <button
                    class="px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200"
                    @click="openEdit(source)"
                  >
                    编辑
                  </button>
                  <button
                    class="px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 rounded-lg transition-all duration-200"
                    @click="handleDelete(source)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Mobile cards -->
      <div class="md:hidden space-y-2">
        <div
          v-for="source in store.sources"
          :key="source.id"
          class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4 cursor-pointer transition-all duration-200 hover:border-indigo-300"
          :class="[
            { 'border-indigo-400 ring-1 ring-indigo-400/20': selectedSource?.id === source.id && drawerVisible },
            { 'opacity-60': !source.is_active }
          ]"
          @click="selectSource(source)"
        >
          <div class="flex items-start justify-between gap-2 mb-1.5">
            <span class="text-sm font-medium text-slate-800 line-clamp-1">{{ source.name }}</span>
            <span
              class="inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded shrink-0"
              :class="typeStyles[source.source_type] || 'bg-slate-100 text-slate-600'"
            >
              {{ typeLabels[source.source_type] || source.source_type }}
            </span>
          </div>
          <div v-if="source.url" class="text-xs text-slate-400 truncate mb-1">{{ source.url }}</div>
          <div class="flex items-center gap-3 text-xs text-slate-400">
            <span v-if="!source.schedule_enabled" class="text-slate-300">调度禁用</span>
            <span v-else-if="source.schedule_mode === 'manual'" class="text-slate-400">手动</span>
            <span v-else-if="source.schedule_mode === 'fixed' && source.schedule_interval_override">
              每{{ formatInterval(source.schedule_interval_override) }}
            </span>
            <span v-else-if="source.schedule_mode === 'auto' && source.calculated_interval" class="text-indigo-600">
              智能 {{ formatInterval(source.calculated_interval) }}
            </span>
            <span v-else class="text-slate-300">-</span>
            <span class="text-slate-200">|</span>
            <span>{{ formatTime(source.last_collected_at) }}</span>
            <span
              class="ml-auto inline-flex w-1.5 h-1.5 rounded-full shrink-0"
              :class="source.is_active ? 'bg-emerald-400' : 'bg-slate-300'"
            ></span>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="store.total > store.pageSize" class="flex items-center justify-between mt-4">
        <span class="text-sm text-slate-400">{{ store.currentPage }} / {{ totalPages }} 页</span>
        <div class="flex items-center gap-2">
          <button
            class="px-3 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            :disabled="store.currentPage <= 1 || store.loading"
            @click="goToPage(store.currentPage - 1)"
          >上一页</button>
          <button
            class="px-3 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            :disabled="store.currentPage >= totalPages || store.loading"
            @click="goToPage(store.currentPage + 1)"
          >下一页</button>
        </div>
      </div>
    </template>

      </div>
    </div>

    <!-- Detail Drawer -->
    <DetailDrawer :visible="drawerVisible" @close="closeDrawer">
      <SourceDetailPanel
        v-if="selectedSource"
        :source="selectedSource"
        :collecting-id="collectingId"
        :toggling-id="togglingId"
        @edit="openEdit"
        @delete="handleDelete"
        @toggle-active="handleToggleActive"
        @collect="handleCollect"
      />
    </DetailDrawer>

    <!-- Modals -->
    <SourceFormModal
      :visible="showFormModal"
      :source="editingSource"
      @submit="handleFormSubmit"
      @cancel="showFormModal = false"
    />

    <ContentSubmitModal
      :visible="showSubmitModal"
      :source="submitTargetSource"
      @success="handleSubmitSuccess"
      @cancel="showSubmitModal = false"
    />

    <!-- 单个删除确认 -->
    <Transition name="modal">
      <div v-if="showDeleteDialog" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="showDeleteDialog = false"></div>
        <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-md p-6 transform transition-all">
          <div class="flex items-start gap-4">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-rose-50">
              <svg class="w-5 h-5 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div class="flex-1">
              <h3 class="text-base font-semibold text-slate-900 tracking-tight">删除数据源</h3>
              <p class="text-sm text-slate-500 mt-1.5 leading-relaxed">
                确定要删除「{{ deletingSource?.name }}」吗？
              </p>
              <label
                v-if="deletingSource?.content_count > 0"
                class="flex items-center gap-2 mt-3 px-3 py-2.5 rounded-xl bg-slate-50 cursor-pointer select-none group"
              >
                <input
                  v-model="deleteContentChecked"
                  type="checkbox"
                  class="w-4 h-4 rounded border-slate-300 text-rose-600 focus:ring-rose-500"
                />
                <span class="text-sm text-slate-600 group-hover:text-slate-800">
                  同时删除 {{ deletingSource.content_count }} 条关联内容
                  <span class="text-xs text-slate-400">（不可恢复）</span>
                </span>
              </label>
            </div>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button
              class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
              @click="showDeleteDialog = false"
            >取消</button>
            <button
              class="px-4 py-2.5 text-sm font-medium text-white rounded-xl shadow-sm transition-all duration-200 bg-rose-600 hover:bg-rose-700 active:bg-rose-800 shadow-rose-200"
              @click="confirmDelete"
            >删除</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 批量删除确认 -->
    <Transition name="modal">
      <div v-if="showBatchDeleteDialog" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="showBatchDeleteDialog = false"></div>
        <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-md p-6 transform transition-all">
          <div class="flex items-start gap-4">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-rose-50">
              <svg class="w-5 h-5 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div class="flex-1">
              <h3 class="text-base font-semibold text-slate-900 tracking-tight">批量删除</h3>
              <p class="text-sm text-slate-500 mt-1.5 leading-relaxed">
                确定要删除选中的 {{ selectedIds.length }} 个数据源吗？
              </p>
              <label
                v-if="batchContentCount > 0"
                class="flex items-center gap-2 mt-3 px-3 py-2.5 rounded-xl bg-slate-50 cursor-pointer select-none group"
              >
                <input
                  v-model="batchDeleteContentChecked"
                  type="checkbox"
                  class="w-4 h-4 rounded border-slate-300 text-rose-600 focus:ring-rose-500"
                />
                <span class="text-sm text-slate-600 group-hover:text-slate-800">
                  同时删除 {{ batchContentCount }} 条关联内容
                  <span class="text-xs text-slate-400">（不可恢复）</span>
                </span>
              </label>
            </div>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button
              class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
              @click="showBatchDeleteDialog = false"
            >取消</button>
            <button
              class="px-4 py-2.5 text-sm font-medium text-white rounded-xl shadow-sm transition-all duration-200 bg-rose-600 hover:bg-rose-700 active:bg-rose-800 shadow-rose-200"
              @click="confirmBatchDelete"
            >删除</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
