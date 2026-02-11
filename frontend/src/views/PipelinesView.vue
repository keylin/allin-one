<script setup>
import { ref, onMounted, computed } from 'vue'
import dayjs from 'dayjs'
import { listPipelines, cancelPipeline, retryPipeline } from '@/api/pipelines'
import { useToast } from '@/composables/useToast'
import PipelineDetailModal from '@/components/pipeline-detail-modal.vue'

const toast = useToast()

const pipelines = ref([])
const total = ref(0)
const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
const filterStatus = ref('')

// 详情弹窗
const showDetail = ref(false)
const detailPipelineId = ref(null)

const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  running: 'bg-indigo-50 text-indigo-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
  paused: 'bg-amber-50 text-amber-700',
  cancelled: 'bg-slate-100 text-slate-400',
}

const statusLabels = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  paused: '已暂停',
  cancelled: '已取消',
}

const progressColors = {
  completed: 'bg-emerald-500',
  running: 'bg-indigo-500',
  failed: 'bg-rose-500',
  pending: 'bg-slate-300',
  paused: 'bg-amber-500',
  cancelled: 'bg-slate-300',
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

async function fetchPipelines() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (filterStatus.value) params.status = filterStatus.value
    const res = await listPipelines(params)
    if (res.code === 0) {
      pipelines.value = res.data
      total.value = res.total
    }
  } finally {
    loading.value = false
  }
}

function handleFilterChange() {
  currentPage.value = 1
  fetchPipelines()
}

function goToPage(page) {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  fetchPipelines()
}

function openDetail(pipeline) {
  detailPipelineId.value = pipeline.id
  showDetail.value = true
}

async function handleCancel(pipeline) {
  const res = await cancelPipeline(pipeline.id)
  if (res.code === 0) {
    toast.success('流水线已取消')
    fetchPipelines()
  }
}

async function handleRetry(pipeline) {
  try {
    const res = await retryPipeline(pipeline.id)
    if (res.code === 0) {
      toast.success(res.message || '流水线已重试')
      fetchPipelines()
    } else {
      toast.error(res.message || '重试失败')
    }
  } catch (error) {
    toast.error('重试请求失败')
  }
}

function formatTime(t) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => fetchPipelines())
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-bold text-slate-900 tracking-tight">流程监控</h2>
        <p class="text-sm text-slate-400 mt-0.5">查看流水线执行状态与进度</p>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="flex items-center gap-3 mb-5">
      <select
        v-model="filterStatus"
        class="px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer"
        @change="handleFilterChange"
      >
        <option value="">全部状态</option>
        <option v-for="(label, value) in statusLabels" :key="value" :value="value">{{ label }}</option>
      </select>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-16">
      <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty -->
    <div v-else-if="pipelines.length === 0" class="text-center py-16">
      <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
        <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
      </div>
      <p class="text-sm text-slate-400">暂无执行记录</p>
    </div>

    <!-- Table (Desktop) -->
    <div v-else>
      <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <table class="w-full">
          <thead class="bg-slate-50/80">
            <tr>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">内容</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">模板</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">状态</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">进度</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">触发</th>
              <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">创建时间</th>
              <th class="px-6 py-3.5 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="p in pipelines" :key="p.id" class="hover:bg-slate-50/50 transition-colors duration-150">
              <td class="px-6 py-3.5">
                <button class="text-sm font-medium text-slate-800 hover:text-indigo-600 truncate max-w-[200px] text-left transition-colors duration-200" @click="openDetail(p)">
                  {{ p.content_title || p.content_id }}
                </button>
              </td>
              <td class="px-6 py-3.5 text-sm text-slate-500">{{ p.template_name || '-' }}</td>
              <td class="px-6 py-3.5">
                <span class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg" :class="statusStyles[p.status] || 'bg-slate-100 text-slate-600'">
                  {{ statusLabels[p.status] || p.status }}
                </span>
              </td>
              <td class="px-6 py-3.5">
                <div class="flex items-center gap-2.5">
                  <div class="flex-1 bg-slate-100 rounded-full h-1.5 max-w-[80px] overflow-hidden">
                    <div
                      class="h-1.5 rounded-full transition-all duration-500"
                      :class="progressColors[p.status] || 'bg-slate-300'"
                      :style="{ width: p.total_steps > 0 ? `${(p.current_step / p.total_steps) * 100}%` : '0%' }"
                    ></div>
                  </div>
                  <span class="text-xs text-slate-400 tabular-nums">{{ p.current_step }}/{{ p.total_steps }}</span>
                </div>
              </td>
              <td class="px-6 py-3.5 text-sm text-slate-500">{{ p.trigger_source }}</td>
              <td class="px-6 py-3.5 text-sm text-slate-400">{{ formatTime(p.created_at) }}</td>
              <td class="px-6 py-3.5 text-right">
                <div class="flex items-center justify-end gap-1.5">
                  <button
                    class="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200"
                    @click="openDetail(p)"
                  >
                    详情
                  </button>
                  <button
                    v-if="p.status === 'running' || p.status === 'pending'"
                    class="px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200"
                    @click="handleCancel(p)"
                  >
                    取消
                  </button>
                  <button
                    v-if="p.status === 'failed'"
                    class="px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all duration-200"
                    @click="handleRetry(p)"
                  >
                    重试
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="total > pageSize" class="flex items-center justify-between px-6 py-3.5 border-t border-slate-100 bg-slate-50/50">
          <span class="text-sm text-slate-400">共 {{ total }} 条，第 {{ currentPage }}/{{ totalPages }} 页</span>
          <div class="flex items-center gap-2">
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="currentPage <= 1"
              @click="goToPage(currentPage - 1)"
            >
              上一页
            </button>
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="currentPage >= totalPages"
              @click="goToPage(currentPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>

      <!-- Mobile Cards -->
      <div class="md:hidden space-y-3">
        <div v-for="p in pipelines" :key="p.id" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4" @click="openDetail(p)">
          <div class="flex items-start justify-between gap-2 mb-3">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-semibold text-slate-800 line-clamp-2">{{ p.content_title || p.content_id }}</div>
              <div class="text-xs text-slate-400 mt-0.5">{{ p.template_name || '-' }}</div>
            </div>
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-lg shrink-0" :class="statusStyles[p.status] || 'bg-slate-100 text-slate-600'">
              {{ statusLabels[p.status] || p.status }}
            </span>
          </div>
          <div class="flex items-center gap-3 mb-3">
            <div class="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
              <div
                class="h-1.5 rounded-full transition-all duration-500"
                :class="progressColors[p.status] || 'bg-slate-300'"
                :style="{ width: p.total_steps > 0 ? `${(p.current_step / p.total_steps) * 100}%` : '0%' }"
              ></div>
            </div>
            <span class="text-xs text-slate-400 tabular-nums shrink-0">{{ p.current_step }}/{{ p.total_steps }}</span>
          </div>
          <div class="flex items-center justify-between text-xs text-slate-400">
            <div class="flex items-center gap-3">
              <span>{{ p.trigger_source }}</span>
              <span>{{ formatTime(p.created_at) }}</span>
            </div>
            <div class="flex items-center gap-1.5" @click.stop>
              <button
                v-if="p.status === 'running' || p.status === 'pending'"
                class="px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200"
                @click="handleCancel(p)"
              >
                取消
              </button>
              <button
                v-if="p.status === 'failed'"
                class="px-2.5 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all duration-200"
                @click="handleRetry(p)"
              >
                重试
              </button>
            </div>
          </div>
        </div>

        <!-- Mobile Pagination -->
        <div v-if="total > pageSize" class="flex items-center justify-between pt-2">
          <span class="text-sm text-slate-400">{{ currentPage }}/{{ totalPages }}</span>
          <div class="flex items-center gap-2">
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="currentPage <= 1"
              @click="goToPage(currentPage - 1)"
            >
              上一页
            </button>
            <button
              class="px-3.5 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200"
              :disabled="currentPage >= totalPages"
              @click="goToPage(currentPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </div>

    <PipelineDetailModal
      :visible="showDetail"
      :pipeline-id="detailPipelineId"
      @close="showDetail = false"
    />
  </div>
</template>
