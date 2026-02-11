<script setup>
import { ref, onMounted, computed } from 'vue'
import dayjs from 'dayjs'
import { useContentStore } from '@/stores/content'
import { listSources } from '@/api/sources'
import ContentDetailModal from '@/components/content-detail-modal.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'

const store = useContentStore()

// 筛选
const searchQuery = ref('')
const filterStatus = ref('')
const filterMediaType = ref('')
const filterSourceId = ref('')
const sources = ref([])

// 详情弹窗
const showDetail = ref(false)
const detailContentId = ref(null)

// 批量操作
const selectedIds = ref([])
const showBatchDeleteDialog = ref(false)

const statusLabels = {
  pending: '待处理',
  processing: '处理中',
  analyzed: '已分析',
  failed: '失败',
}
const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  processing: 'bg-indigo-50 text-indigo-700',
  analyzed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
}
const mediaLabels = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
  mixed: '混合',
}

const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

function fetchWithFilters() {
  const params = {}
  if (searchQuery.value) params.q = searchQuery.value
  if (filterStatus.value) params.status = filterStatus.value
  if (filterMediaType.value) params.media_type = filterMediaType.value
  if (filterSourceId.value) params.source_id = filterSourceId.value
  store.fetchContent(params)
}

onMounted(async () => {
  fetchWithFilters()
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data
  } catch { /* ignore */ }
})

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

function openDetail(item) {
  detailContentId.value = item.id
  showDetail.value = true
}

async function handleFavorite(id) {
  await store.toggleFavorite(id)
}

async function handleNote(id, note) {
  await store.updateNote(id, note)
}

function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx > -1) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function toggleSelectAll() {
  if (selectedIds.value.length === store.items.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = store.items.map(i => i.id)
  }
}

async function handleBatchDelete() {
  showBatchDeleteDialog.value = false
  await store.batchDelete(selectedIds.value)
  selectedIds.value = []
}

function formatTime(t) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'
}

const inputClass = 'px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-bold text-slate-900 tracking-tight">内容库</h2>
        <p class="text-sm text-slate-400 mt-0.5">管理所有采集到的内容数据</p>
      </div>
      <button
        v-if="selectedIds.length > 0"
        class="px-4 py-2.5 text-sm font-medium text-white bg-rose-600 rounded-xl hover:bg-rose-700 active:bg-rose-800 shadow-sm shadow-rose-200 transition-all duration-200"
        @click="showBatchDeleteDialog = true"
      >
        <span class="flex items-center gap-1.5">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
          </svg>
          删除选中 ({{ selectedIds.length }})
        </span>
      </button>
    </div>

    <!-- 筛选 -->
    <div class="flex items-center gap-3 mb-5 flex-wrap">
      <div class="relative flex-1 max-w-sm">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索标题..."
          :class="[inputClass, 'w-full pl-10 pr-3.5']"
          @keyup.enter="handleSearch"
        />
        <svg class="absolute left-3.5 top-3 h-4 w-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
      </div>
      <select v-model="filterSourceId" :class="selectClass" @change="handleFilterChange">
        <option value="">全部来源</option>
        <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="filterStatus" :class="selectClass" @change="handleFilterChange">
        <option value="">全部状态</option>
        <option v-for="(label, value) in statusLabels" :key="value" :value="value">{{ label }}</option>
      </select>
      <select v-model="filterMediaType" :class="selectClass" @change="handleFilterChange">
        <option value="">全部类型</option>
        <option v-for="(label, value) in mediaLabels" :key="value" :value="value">{{ label }}</option>
      </select>
      <button
        class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
        @click="handleSearch"
      >
        搜索
      </button>
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="flex items-center justify-center py-16">
      <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty -->
    <div v-else-if="store.items.length === 0" class="text-center py-16">
      <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
        <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
      </div>
      <p class="text-sm text-slate-400">暂无内容</p>
    </div>

    <!-- Table (Desktop) -->
    <div v-else>
      <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <table class="w-full">
          <thead class="bg-slate-50/80">
            <tr>
              <th class="px-6 py-3.5 text-left w-8">
                <input type="checkbox" class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500" :checked="selectedIds.length === store.items.length && store.items.length > 0" @change="toggleSelectAll" />
              </th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">标题</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">来源</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">状态</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">采集时间</th>
              <th class="px-6 py-3.5 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="item in store.items" :key="item.id" class="hover:bg-slate-50/50 transition-colors duration-150">
              <td class="px-6 py-3.5">
                <input type="checkbox" class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500" :checked="selectedIds.includes(item.id)" @change="toggleSelect(item.id)" />
              </td>
              <td class="px-6 py-3.5">
                <div class="flex items-center gap-2">
                  <svg v-if="item.is_favorited" class="w-4 h-4 text-amber-400 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                  </svg>
                  <button class="text-sm font-medium text-slate-800 hover:text-indigo-600 text-left truncate max-w-[300px] transition-colors duration-200" @click="openDetail(item)">
                    {{ item.title }}
                  </button>
                </div>
              </td>
              <td class="px-6 py-3.5 text-sm text-slate-500">{{ item.source_name || '-' }}</td>
              <td class="px-6 py-3.5">
                <span class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg" :class="statusStyles[item.status] || 'bg-slate-100 text-slate-600'">
                  {{ statusLabels[item.status] || item.status }}
                </span>
              </td>
              <td class="px-6 py-3.5 text-sm text-slate-500">{{ mediaLabels[item.media_type] || item.media_type }}</td>
              <td class="px-6 py-3.5 text-sm text-slate-400">{{ formatTime(item.collected_at) }}</td>
              <td class="px-6 py-3.5 text-right">
                <button
                  class="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200"
                  :class="item.is_favorited ? 'text-amber-600 hover:bg-amber-50' : 'text-slate-500 hover:bg-slate-100'"
                  @click="handleFavorite(item.id)"
                >
                  {{ item.is_favorited ? '取消收藏' : '收藏' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="store.total > store.pageSize" class="flex items-center justify-between px-6 py-3.5 border-t border-slate-100 bg-slate-50/50">
          <span class="text-sm text-slate-400">共 {{ store.total }} 条，第 {{ store.currentPage }}/{{ totalPages }} 页</span>
          <div class="flex items-center gap-2">
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="store.currentPage <= 1"
              @click="goToPage(store.currentPage - 1)"
            >
              上一页
            </button>
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
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
        <div v-for="item in store.items" :key="item.id" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4" @click="openDetail(item)">
          <div class="flex items-start gap-3 mb-2">
            <input type="checkbox" class="h-4 w-4 mt-0.5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500 shrink-0" :checked="selectedIds.includes(item.id)" @change.stop="toggleSelect(item.id)" @click.stop />
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5 mb-1">
                <svg v-if="item.is_favorited" class="w-3.5 h-3.5 text-amber-400 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                </svg>
                <span class="text-sm font-semibold text-slate-800 line-clamp-2">{{ item.title }}</span>
              </div>
              <div class="flex flex-wrap items-center gap-2 text-xs">
                <span class="text-slate-500">{{ item.source_name || '-' }}</span>
                <span class="inline-flex px-2 py-0.5 font-medium rounded-md" :class="statusStyles[item.status] || 'bg-slate-100 text-slate-600'">
                  {{ statusLabels[item.status] || item.status }}
                </span>
                <span class="text-slate-400">{{ mediaLabels[item.media_type] || item.media_type }}</span>
              </div>
              <div class="flex items-center justify-between mt-2">
                <span class="text-xs text-slate-400">{{ formatTime(item.collected_at) }}</span>
                <button
                  class="px-2.5 py-1 text-xs font-medium rounded-lg transition-all duration-200"
                  :class="item.is_favorited ? 'text-amber-600 hover:bg-amber-50' : 'text-slate-500 hover:bg-slate-100'"
                  @click.stop="handleFavorite(item.id)"
                >
                  {{ item.is_favorited ? '取消收藏' : '收藏' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Mobile Pagination -->
        <div v-if="store.total > store.pageSize" class="flex items-center justify-between pt-2">
          <span class="text-sm text-slate-400">{{ store.currentPage }}/{{ totalPages }}</span>
          <div class="flex items-center gap-2">
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="store.currentPage <= 1"
              @click="goToPage(store.currentPage - 1)"
            >
              上一页
            </button>
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="store.currentPage >= totalPages"
              @click="goToPage(store.currentPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </div>

    <ContentDetailModal
      :visible="showDetail"
      :content-id="detailContentId"
      @close="showDetail = false"
      @favorite="handleFavorite"
      @note="handleNote"
    />

    <ConfirmDialog
      :visible="showBatchDeleteDialog"
      title="批量删除"
      :message="`确定要删除选中的 ${selectedIds.length} 条内容吗？`"
      confirm-text="删除"
      :danger="true"
      @confirm="handleBatchDelete"
      @cancel="showBatchDeleteDialog = false"
    />
  </div>
</template>
