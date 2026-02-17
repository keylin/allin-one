<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { listPipelines, cancelPipeline, cancelAllPipelines, retryPipeline } from '@/api/pipelines'
import { useToast } from '@/composables/useToast'
import PipelineDetailPanel from '@/components/pipeline-detail-panel.vue'
import DetailDrawer from '@/components/detail-drawer.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const pipelines = ref([])
const execTotal = ref(0)
const execLoading = ref(false)
const currentPage = ref(Number(route.query.page) || 1)
const pageSize = ref(20)
const filterStatus = ref(route.query.status || '')

const selectedExecId = ref(null)
const drawerVisible = ref(false)

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

const triggerLabels = {
  manual: '手动',
  scheduled: '定时',
  api: 'API',
  webhook: 'Webhook',
  favorite: '收藏',
}

const progressColors = {
  completed: 'bg-emerald-500',
  running: 'bg-indigo-500',
  failed: 'bg-rose-500',
  pending: 'bg-slate-300',
  paused: 'bg-amber-500',
  cancelled: 'bg-slate-300',
}

const totalPages = computed(() => Math.max(1, Math.ceil(execTotal.value / pageSize.value)))

async function fetchPipelines() {
  execLoading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (filterStatus.value) params.status = filterStatus.value
    const res = await listPipelines(params)
    if (res.code === 0) {
      pipelines.value = res.data
      execTotal.value = res.total
    }
  } finally {
    execLoading.value = false
  }
}

function syncExecQueryParams() {
  const query = {}
  if (filterStatus.value) query.status = filterStatus.value
  if (currentPage.value > 1) query.page = String(currentPage.value)
  router.replace({ query }).catch(() => {})
}

function handleFilterChange() {
  currentPage.value = 1
  syncExecQueryParams()
  fetchPipelines()
}

function goToPage(page) {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  syncExecQueryParams()
  fetchPipelines()
}

function selectExec(pipeline) {
  selectedExecId.value = pipeline.id
  drawerVisible.value = true
}

function closeDrawer() {
  drawerVisible.value = false
}

async function handleCancel(pipeline) {
  const res = await cancelPipeline(pipeline.id)
  if (res.code === 0) {
    toast.success('流水线已取消')
    fetchPipelines()
  }
}

const hasActivePipelines = computed(() =>
  pipelines.value.some(p => p.status === 'pending' || p.status === 'running')
)

const showCancelAllDialog = ref(false)

async function handleCancelAll() {
  showCancelAllDialog.value = false
  try {
    const res = await cancelAllPipelines()
    if (res.code === 0) {
      toast.success(res.message || '已取消全部流水线')
      fetchPipelines()
    } else {
      toast.error(res.message || '取消失败')
    }
  } catch {
    toast.error('取消请求失败')
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
  } catch {
    toast.error('重试请求失败')
  }
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => {
  fetchPipelines()
})
</script>

<template>
  <div class="flex-1 overflow-y-auto">
    <div class="px-4 py-4">
      <!-- Status filter pills -->
      <div class="flex items-center gap-1.5 flex-wrap mb-4">
        <span class="text-xs text-slate-400 mr-1">{{ execTotal }} 条记录</span>
        <button
          class="px-3 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
          :class="filterStatus === ''
            ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
            : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
          @click="filterStatus = ''; handleFilterChange()"
        >
          全部
        </button>
        <button
          v-for="(label, value) in statusLabels"
          :key="value"
          class="px-3 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
          :class="filterStatus === value
            ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
            : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
          @click="filterStatus = value; handleFilterChange()"
        >
          {{ label }}
        </button>
        <button
          v-if="hasActivePipelines"
          class="ml-auto px-3 py-1.5 text-xs font-medium rounded-lg border border-rose-200 text-rose-600 hover:bg-rose-50 transition-all duration-200"
          @click="showCancelAllDialog = true"
        >
          取消全部
        </button>
      </div>

      <!-- Loading -->
      <div v-if="execLoading" class="flex items-center justify-center py-16">
        <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <!-- Empty -->
      <div v-else-if="pipelines.length === 0" class="text-center py-16">
        <div class="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
          </svg>
        </div>
        <p class="text-sm text-slate-500 font-medium mb-1">暂无执行记录</p>
        <p class="text-xs text-slate-400">采集内容后流水线会自动运行</p>
      </div>

      <!-- Desktop table -->
      <template v-else>
        <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
          <table class="w-full">
            <thead class="bg-slate-50/80">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">内容</th>
                <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">模板</th>
                <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">触发</th>
                <th class="px-4 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">进度</th>
                <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">状态</th>
                <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">时间</th>
                <th class="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr
                v-for="p in pipelines"
                :key="p.id"
                class="hover:bg-slate-50/50 cursor-pointer transition-colors duration-150"
                :class="{ 'bg-indigo-50/40': selectedExecId === p.id && drawerVisible }"
                @click="selectExec(p)"
              >
                <td class="px-4 py-3 text-sm font-medium text-slate-800 max-w-[240px] truncate">{{ p.content_title || p.content_id }}</td>
                <td class="px-4 py-3 text-sm text-slate-500 truncate max-w-[120px]">{{ p.template_name || '-' }}</td>
                <td class="px-4 py-3 text-sm text-slate-500">{{ triggerLabels[p.trigger_source] || p.trigger_source }}</td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-2 justify-center">
                    <div class="w-16 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div
                        class="h-1.5 rounded-full transition-all duration-500"
                        :class="progressColors[p.status] || 'bg-slate-300'"
                        :style="{ width: p.total_steps > 0 ? `${(p.current_step / p.total_steps) * 100}%` : '0%' }"
                      ></div>
                    </div>
                    <span class="text-xs text-slate-400 tabular-nums">{{ p.current_step }}/{{ p.total_steps }}</span>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md" :class="statusStyles[p.status] || 'bg-slate-100 text-slate-600'">
                    {{ statusLabels[p.status] || p.status }}
                  </span>
                </td>
                <td class="px-4 py-3 text-sm text-slate-400">{{ formatTime(p.created_at) }}</td>
                <td class="px-4 py-3 text-right" @click.stop>
                  <button
                    v-if="p.status === 'running' || p.status === 'pending'"
                    class="px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200"
                    @click="handleCancel(p)"
                  >
                    取消
                  </button>
                  <button
                    v-if="p.status === 'failed'"
                    class="px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all duration-200"
                    @click="handleRetry(p)"
                  >
                    重试
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Mobile cards -->
        <div class="md:hidden space-y-2">
          <div
            v-for="p in pipelines"
            :key="p.id"
            class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4 cursor-pointer transition-all duration-200 hover:border-indigo-300"
            :class="{ 'border-indigo-400 ring-1 ring-indigo-400/20': selectedExecId === p.id && drawerVisible }"
            @click="selectExec(p)"
          >
            <div class="flex items-start justify-between gap-2 mb-1.5">
              <span class="text-sm font-medium text-slate-800 line-clamp-1">{{ p.content_title || p.content_id }}</span>
              <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md shrink-0" :class="statusStyles[p.status] || 'bg-slate-100 text-slate-600'">
                {{ statusLabels[p.status] || p.status }}
              </span>
            </div>
            <div class="flex items-center gap-2 mb-1.5">
              <div class="flex-1 bg-slate-100 rounded-full h-1 overflow-hidden">
                <div
                  class="h-1 rounded-full transition-all duration-500"
                  :class="progressColors[p.status] || 'bg-slate-300'"
                  :style="{ width: p.total_steps > 0 ? `${(p.current_step / p.total_steps) * 100}%` : '0%' }"
                ></div>
              </div>
              <span class="text-[10px] text-slate-400 tabular-nums shrink-0">{{ p.current_step }}/{{ p.total_steps }}</span>
            </div>
            <div class="flex items-center justify-between text-[11px] text-slate-400">
              <div class="flex items-center gap-2">
                <span>{{ p.template_name || '-' }}</span>
                <span class="text-slate-200">|</span>
                <span>{{ triggerLabels[p.trigger_source] || p.trigger_source }}</span>
              </div>
              <span>{{ formatTime(p.created_at) }}</span>
            </div>
            <div v-if="p.status === 'running' || p.status === 'pending' || p.status === 'failed'" class="flex items-center gap-1.5 mt-2 pt-2 border-t border-slate-100" @click.stop>
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

        <!-- Pagination -->
        <div v-if="execTotal > pageSize" class="flex items-center justify-between mt-4">
          <span class="text-sm text-slate-400">{{ currentPage }} / {{ totalPages }} 页</span>
          <div class="flex items-center gap-2">
            <button
              class="px-3 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 transition-all"
              :disabled="currentPage <= 1"
              @click="goToPage(currentPage - 1)"
            >上一页</button>
            <button
              class="px-3 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 transition-all"
              :disabled="currentPage >= totalPages"
              @click="goToPage(currentPage + 1)"
            >下一页</button>
          </div>
        </div>
      </template>
    </div>

    <!-- Exec Detail Drawer -->
    <DetailDrawer :visible="drawerVisible" @close="closeDrawer">
      <PipelineDetailPanel
        v-if="selectedExecId"
        :pipeline-id="selectedExecId"
        @cancel="fetchPipelines"
        @retry="fetchPipelines"
      />
    </DetailDrawer>

    <!-- Cancel All Dialog -->
    <ConfirmDialog
      :visible="showCancelAllDialog"
      title="取消全部流水线"
      message="确定要取消所有等待中和运行中的流水线吗？"
      confirm-text="全部取消"
      :danger="true"
      @confirm="handleCancelAll"
      @cancel="showCancelAllDialog = false"
    />
  </div>
</template>
