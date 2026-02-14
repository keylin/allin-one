<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { listPipelines, cancelPipeline, cancelAllPipelines, retryPipeline, testStep } from '@/api/pipelines'
import { listTemplates, createTemplate, updateTemplate, deleteTemplate, getStepDefinitions } from '@/api/pipeline-templates'
import { listPromptTemplates, createPromptTemplate, updatePromptTemplate, deletePromptTemplate } from '@/api/prompt-templates'
import { listContent } from '@/api/content'
import { useToast } from '@/composables/useToast'
import { useModelOptions } from '@/composables/useModelOptions'
import PipelineDetailPanel from '@/components/pipeline-detail-panel.vue'
import DetailDrawer from '@/components/detail-drawer.vue'
import PipelineTemplateFormModal from '@/components/pipeline-template-form-modal.vue'
import PromptTemplateFormModal from '@/components/prompt-template-form-modal.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'

const route = useRoute()
const router = useRouter()
const toast = useToast()

// ---- Tab ----
const activeTab = ref(route.query.tab || 'executions')

function switchTab(tab) {
  activeTab.value = tab
  selectedExecId.value = null
  drawerVisible.value = false
  const query = { ...route.query, tab }
  if (tab === 'executions') delete query.tab
  router.replace({ query }).catch(() => {})
}

// =======================================================
// ================  执行记录 Tab  ========================
// =======================================================
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
  if (activeTab.value !== 'executions') query.tab = activeTab.value
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

// =======================================================
// ==============  流水线模板 Tab  =========================
// =======================================================
const pipelineTemplates = ref([])
const ptLoading = ref(false)
const stepDefs = ref({})

async function fetchStepDefinitions() {
  try {
    const res = await getStepDefinitions()
    if (res.code === 0) stepDefs.value = res.data
  } catch { /* ignore */ }
}

async function fetchPipelineTemplates() {
  ptLoading.value = true
  try {
    const res = await listTemplates()
    if (res.code === 0) pipelineTemplates.value = res.data
  } finally {
    ptLoading.value = false
  }
}

function parseSteps(stepsConfig) {
  try {
    return JSON.parse(stepsConfig || '[]')
  } catch {
    return []
  }
}

function getStepDisplayName(stepType) {
  return stepDefs.value[stepType]?.display_name || stepType
}

const showPTFormModal = ref(false)
const editingPT = ref(null)

function startCreatePT() {
  editingPT.value = null
  showPTFormModal.value = true
}

function startEditPT(tpl) {
  editingPT.value = tpl
  showPTFormModal.value = true
}

async function handlePTSubmit(formData) {
  let res
  if (editingPT.value) {
    res = await updateTemplate(editingPT.value.id, formData)
  } else {
    res = await createTemplate(formData)
  }
  if (res.code === 0) {
    showPTFormModal.value = false
    await fetchPipelineTemplates()
  }
}

const showDeletePTDialog = ref(false)
const deletingPTId = ref(null)

function openDeletePT(id) {
  deletingPTId.value = id
  showDeletePTDialog.value = true
}

async function handleDeletePT() {
  showDeletePTDialog.value = false
  const res = await deleteTemplate(deletingPTId.value)
  if (res.code === 0) {
    await fetchPipelineTemplates()
  }
}

// ---- Step Debug ----
const selectedStep = ref(null)
const contentList = ref([])
const selectedContentId = ref('')
const stepConfigForm = ref({})
const testInput = ref('{}')
const testing = ref(false)
const testResult = ref(null)
const testRequest = ref(null)
const contentSearch = ref('')
let contentSearchTimer = null
const { modelOptions, currentLLMModel } = useModelOptions()

const stepDefList = computed(() =>
  Object.entries(stepDefs.value).map(([key, def]) => ({ key, ...def }))
)

const currentStepDef = computed(() => selectedStep.value ? stepDefs.value[selectedStep.value] : null)

const configProps = computed(() => currentStepDef.value?.config_schema?.properties || {})

const filteredContentList = computed(() => {
  if (!contentSearch.value) return contentList.value
  const q = contentSearch.value.toLowerCase()
  return contentList.value.filter(c =>
    (c.title && c.title.toLowerCase().includes(q)) ||
    (c.source_name && c.source_name.toLowerCase().includes(q))
  )
})

const resultMetrics = computed(() => {
  if (!testResult.value?.result || testResult.value.status !== 'success') return []
  const r = testResult.value.result
  const metrics = []
  if (r.status) metrics.push({ label: '状态', value: r.status })
  if (r.title) metrics.push({ label: '标题', value: r.title.length > 40 ? r.title.substring(0, 40) + '...' : r.title })
  if (r.text !== undefined || r.full_text !== undefined) {
    const text = r.text || r.full_text || ''
    metrics.push({ label: '文本长度', value: typeof text === 'string' ? text.length.toLocaleString() + '字' : '-' })
  }
  if (r.method) metrics.push({ label: '抓取方式', value: r.method })
  if (r.platform) metrics.push({ label: '平台', value: r.platform })
  if (r.duration !== undefined) metrics.push({ label: '时长', value: r.duration + 's' })
  if (r.file_size !== undefined) {
    const mb = (r.file_size / 1024 / 1024).toFixed(1)
    metrics.push({ label: '文件大小', value: mb + ' MB' })
  }
  if (r.target_language) metrics.push({ label: '目标语言', value: r.target_language })
  if (r.source) metrics.push({ label: '来源', value: r.source })
  if (r.channel) metrics.push({ label: '推送渠道', value: r.channel })
  if (r.reason) metrics.push({ label: '原因', value: r.reason })
  if (metrics.length === 0 && typeof r === 'object') {
    metrics.push({ label: '返回字段', value: Object.keys(r).join(', ') })
  }
  return metrics
})

async function fetchContentList(query) {
  try {
    const params = { page_size: 50 }
    if (query) params.q = query
    const res = await listContent(params)
    if (res.code === 0) contentList.value = res.data
  } catch { /* ignore */ }
}

function onContentSearch() {
  clearTimeout(contentSearchTimer)
  contentSearchTimer = setTimeout(() => {
    fetchContentList(contentSearch.value || undefined)
  }, 300)
}

function startDebugStep(stepKey) {
  if (selectedStep.value === stepKey) {
    selectedStep.value = null
    testResult.value = null
    return
  }
  selectedStep.value = stepKey
  testResult.value = null
  const def = stepDefs.value[stepKey]
  const form = {}
  if (def?.config_schema?.properties) {
    for (const [key, prop] of Object.entries(def.config_schema.properties)) {
      if (key === 'model' && currentLLMModel.value) {
        form[key] = currentLLMModel.value
      } else if (prop.default !== undefined) {
        form[key] = prop.default
      } else if (prop.type === 'boolean') {
        form[key] = false
      } else {
        form[key] = ''
      }
    }
  }
  stepConfigForm.value = form
  selectedContentId.value = ''
  testInput.value = '{}'
  contentSearch.value = ''
  if (contentList.value.length === 0) fetchContentList()
}

async function handleTest() {
  if (!selectedStep.value) return
  let parsedInput
  try {
    parsedInput = JSON.parse(testInput.value || '{}')
  } catch {
    testResult.value = { status: 'error', error: 'test_input JSON 格式错误' }
    return
  }
  const payload = {
    step_type: selectedStep.value,
    content_id: selectedContentId.value || undefined,
    step_config: { ...stepConfigForm.value },
    test_input: parsedInput,
  }
  testRequest.value = payload
  testing.value = true
  testResult.value = null
  try {
    const res = await testStep(payload)
    if (res.code === 0) {
      testResult.value = res.data
    } else {
      testResult.value = { status: 'error', error: res.message }
    }
  } catch (err) {
    testResult.value = { status: 'error', error: err.message || '请求失败' }
  } finally {
    testing.value = false
  }
}

// =======================================================
// ==============  提示词模板 Tab  =========================
// =======================================================
const promptTemplates = ref([])
const prLoading = ref(false)
const showPromptForm = ref(false)
const editingPrompt = ref(null)
const showDeletePrDialog = ref(false)
const deletingPrId = ref(null)

const typeLabels = {
  news_analysis: '新闻分析',
  summary: '摘要',
  translation: '翻译',
  custom: '自定义',
}

const typeStyles = {
  news_analysis: 'bg-indigo-50 text-indigo-700',
  summary: 'bg-emerald-50 text-emerald-700',
  translation: 'bg-violet-50 text-violet-700',
  custom: 'bg-slate-100 text-slate-600',
}

async function fetchPromptTemplates() {
  prLoading.value = true
  try {
    const res = await listPromptTemplates()
    if (res.code === 0) promptTemplates.value = res.data
  } finally {
    prLoading.value = false
  }
}

function openCreatePrompt() {
  editingPrompt.value = null
  showPromptForm.value = true
}

function openEditPrompt(tpl) {
  editingPrompt.value = tpl
  showPromptForm.value = true
}

async function handlePromptSubmit(formData) {
  let res
  if (editingPrompt.value) {
    res = await updatePromptTemplate(editingPrompt.value.id, formData)
  } else {
    res = await createPromptTemplate(formData)
  }
  if (res.code === 0) {
    showPromptForm.value = false
    await fetchPromptTemplates()
  }
}

function openDeletePrompt(id) {
  deletingPrId.value = id
  showDeletePrDialog.value = true
}

async function handleDeletePrompt() {
  showDeletePrDialog.value = false
  const res = await deletePromptTemplate(deletingPrId.value)
  if (res.code === 0) await fetchPromptTemplates()
}

// =======================================================
// ==============  Shared  ================================
// =======================================================
const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => {
  fetchPipelines()
  fetchStepDefinitions()
  fetchPipelineTemplates()
  fetchPromptTemplates()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tab 栏 -->
    <div class="border-b border-slate-100 bg-white px-4 pt-3 pb-0 shrink-0">
      <div class="flex items-center gap-1">
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'executions'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('executions')"
        >
          执行记录
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'templates'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('templates')"
        >
          流水线模板
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'prompts'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('prompts')"
        >
          提示词模板
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'debug'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('debug')"
        >
          单步骤验证
        </button>
      </div>
    </div>

    <!-- ========== 执行记录 Tab (full-width table + Drawer) ========== -->
    <div v-if="activeTab === 'executions'" class="flex-1 overflow-y-auto">
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
    </div>

    <!-- ========== 流水线模板 Tab (full-width card grid) ========== -->
    <div v-if="activeTab === 'templates'" class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">
        <div class="flex items-center justify-between mb-4">
          <p class="text-xs text-slate-400">{{ pipelineTemplates.length }} 个模板</p>
          <button
            class="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
            @click="startCreatePT"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            新增
          </button>
        </div>

        <!-- Loading -->
        <div v-if="ptLoading" class="flex items-center justify-center py-16">
          <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <!-- Empty -->
        <div v-else-if="pipelineTemplates.length === 0" class="text-center py-16">
          <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
            <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <p class="text-sm text-slate-400">暂无模板</p>
        </div>

        <!-- Card grid -->
        <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div
            v-for="tpl in pipelineTemplates"
            :key="tpl.id"
            class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-5 cursor-pointer hover:border-indigo-300 hover:shadow-md transition-all duration-200"
            @click="startEditPT(tpl)"
          >
            <div class="flex items-center gap-2 mb-2">
              <span class="text-sm font-semibold text-slate-900">{{ tpl.name }}</span>
              <span v-if="tpl.is_builtin" class="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded-md font-medium">内置</span>
            </div>
            <p v-if="tpl.description" class="text-xs text-slate-400 line-clamp-2 mb-3">{{ tpl.description }}</p>
            <div v-if="parseSteps(tpl.steps_config).length > 0" class="flex flex-wrap gap-1 mb-3">
              <span
                v-for="(step, idx) in parseSteps(tpl.steps_config)"
                :key="idx"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-medium rounded-md bg-indigo-50 text-indigo-600"
              >
                <span v-if="step.is_critical" class="w-1 h-1 rounded-full bg-rose-400 shrink-0"></span>
                {{ getStepDisplayName(step.step_type) }}
              </span>
            </div>
            <div class="flex items-center justify-between pt-3 border-t border-slate-100">
              <span class="text-[11px] text-slate-400">{{ formatTime(tpl.updated_at) }}</span>
              <button
                v-if="!tpl.is_builtin"
                class="px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200"
                @click.stop="openDeletePT(tpl.id)"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 提示词模板 Tab (full width) ========== -->
    <div v-if="activeTab === 'prompts'" class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">
        <div class="flex items-center justify-end mb-4">
          <button
            class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
            @click="openCreatePrompt"
          >
            <span class="flex items-center gap-1.5">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              新增
            </span>
          </button>
        </div>

        <!-- Loading -->
        <div v-if="prLoading" class="flex items-center justify-center py-16">
          <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <!-- Empty -->
        <div v-else-if="promptTemplates.length === 0" class="text-center py-16">
          <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
            <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
            </svg>
          </div>
          <p class="text-sm text-slate-400">暂无模板</p>
        </div>

        <!-- Table -->
        <div v-else>
          <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
            <table class="w-full">
              <thead class="bg-slate-50/80">
                <tr>
                  <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">名称</th>
                  <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
                  <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">输出格式</th>
                  <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">默认</th>
                  <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">更新时间</th>
                  <th class="px-6 py-3.5 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                <tr v-for="tpl in promptTemplates" :key="tpl.id" class="hover:bg-slate-50/50 transition-colors duration-150">
                  <td class="px-6 py-3.5 text-sm font-medium text-slate-900">{{ tpl.name }}</td>
                  <td class="px-6 py-3.5">
                    <span class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg" :class="typeStyles[tpl.template_type] || 'bg-slate-100 text-slate-600'">
                      {{ typeLabels[tpl.template_type] || tpl.template_type }}
                    </span>
                  </td>
                  <td class="px-6 py-3.5 text-sm text-slate-500">{{ tpl.output_format }}</td>
                  <td class="px-6 py-3.5">
                    <span v-if="tpl.is_default" class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md bg-emerald-50 text-emerald-600">是</span>
                    <span v-else class="text-sm text-slate-300">-</span>
                  </td>
                  <td class="px-6 py-3.5 text-sm text-slate-400">{{ formatTime(tpl.updated_at) }}</td>
                  <td class="px-6 py-3.5 text-right">
                    <div class="flex items-center justify-end gap-1.5">
                      <button class="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200" @click="openEditPrompt(tpl)">编辑</button>
                      <button class="px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200" @click="openDeletePrompt(tpl.id)">删除</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Mobile Cards -->
          <div class="md:hidden space-y-3">
            <div v-for="tpl in promptTemplates" :key="tpl.id" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
              <div class="flex items-start justify-between gap-2 mb-2">
                <div class="text-sm font-semibold text-slate-900">{{ tpl.name }}</div>
                <span v-if="tpl.is_default" class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md bg-emerald-50 text-emerald-600 shrink-0">默认</span>
              </div>
              <div class="flex flex-wrap items-center gap-2 mb-3 text-xs">
                <span class="inline-flex px-2 py-0.5 font-medium rounded-lg" :class="typeStyles[tpl.template_type] || 'bg-slate-100 text-slate-600'">
                  {{ typeLabels[tpl.template_type] || tpl.template_type }}
                </span>
                <span class="text-slate-400">{{ tpl.output_format }}</span>
                <span class="text-slate-400">{{ formatTime(tpl.updated_at) }}</span>
              </div>
              <div class="flex items-center gap-1.5 pt-3 border-t border-slate-100">
                <button class="flex-1 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200" @click="openEditPrompt(tpl)">编辑</button>
                <button class="flex-1 px-3 py-2 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200" @click="openDeletePrompt(tpl.id)">删除</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 单步骤验证 Tab (full width) ========== -->
    <div v-if="activeTab === 'debug'" class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">
        <!-- Loading -->
        <div v-if="stepDefList.length === 0" class="text-center py-16">
          <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
            <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
            </svg>
          </div>
          <p class="text-sm text-slate-400">加载中...</p>
        </div>

        <div v-else class="space-y-5">
          <!-- Step type pills -->
          <div>
            <p class="text-sm text-slate-500 mb-3">选择一个步骤类型，独立运行并验证配置</p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="step in stepDefList"
                :key="step.key"
                class="px-4 py-2 text-sm font-medium rounded-xl border transition-all duration-200"
                :class="selectedStep === step.key
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm shadow-indigo-200'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300 hover:text-indigo-600'"
                @click="startDebugStep(step.key)"
              >
                {{ step.display_name }}
              </button>
            </div>
          </div>

          <!-- Step description -->
          <div v-if="selectedStep && currentStepDef" class="flex items-center gap-3 px-4 py-3 bg-indigo-50/60 border border-indigo-100 rounded-xl">
            <span class="text-sm font-mono font-medium text-indigo-600">{{ selectedStep }}</span>
            <span class="w-px h-4 bg-indigo-200"></span>
            <span class="text-sm text-slate-600">{{ currentStepDef.description }}</span>
          </div>

          <!-- Two-column layout: config (left) + result (right) -->
          <div v-if="selectedStep" class="flex flex-col md:flex-row gap-5">
            <!-- Left: Config -->
            <div class="w-full md:w-1/2 md:sticky md:top-4 md:self-start">
              <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-5 md:p-6 space-y-5">
                <!-- Step Config -->
                <div v-if="Object.keys(configProps).length > 0">
                  <label class="block text-sm font-medium text-slate-700 mb-3">步骤配置</label>
                  <div class="grid grid-cols-1 gap-4">
                    <div v-for="(prop, propKey) in configProps" :key="propKey">
                      <label class="block text-xs font-medium text-slate-500 mb-1.5">{{ prop.description || propKey }}</label>
                      <select v-if="prop.enum" v-model="stepConfigForm[propKey]" :class="selectClass">
                        <option v-for="opt in prop.enum" :key="opt" :value="opt">{{ opt }}</option>
                      </select>
                      <label v-else-if="prop.type === 'boolean'" class="flex items-center gap-2.5 py-2.5 px-3.5 bg-white border border-slate-200 rounded-xl cursor-pointer hover:border-slate-300 transition-colors">
                        <input v-model="stepConfigForm[propKey]" type="checkbox" class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500" />
                        <span class="text-sm text-slate-700">{{ prop.description || propKey }}</span>
                      </label>
                      <select v-else-if="propKey === 'prompt_template_id'" v-model="stepConfigForm[propKey]" :class="selectClass">
                        <option value="">不绑定</option>
                        <option v-for="pt in promptTemplates" :key="pt.id" :value="pt.id">{{ pt.name }}</option>
                      </select>
                      <select v-else-if="propKey === 'model'" v-model="stepConfigForm[propKey]" :class="selectClass">
                        <option value="">系统默认</option>
                        <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
                      </select>
                      <input v-else v-model="stepConfigForm[propKey]" type="text" :class="inputClass" :placeholder="String(prop.default ?? '')" />
                    </div>
                  </div>
                </div>
                <div v-else class="text-sm text-slate-400">该步骤无需配置参数</div>

                <!-- Content Select -->
                <div>
                  <label class="block text-sm font-medium text-slate-700 mb-1.5">目标内容</label>
                  <div class="space-y-2">
                    <input v-model="contentSearch" type="text" :class="inputClass" placeholder="搜索内容标题..." @input="onContentSearch" />
                    <select v-model="selectedContentId" :class="selectClass">
                      <option value="">不选择 (使用模拟输入)</option>
                      <option v-for="c in filteredContentList" :key="c.id" :value="c.id">{{ c.title?.substring(0, 60) || '(无标题)' }} [{{ c.status }}]</option>
                    </select>
                  </div>
                  <p class="mt-1.5 text-xs text-slate-400">选择一条已有内容进行真实测试，或留空使用模拟输入</p>
                </div>

                <!-- Test Input -->
                <details class="group">
                  <summary class="cursor-pointer text-sm font-medium text-slate-500 hover:text-slate-700 select-none flex items-center gap-1.5">
                    <svg class="w-4 h-4 transition-transform duration-200 group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                    </svg>
                    高级: 模拟前序步骤输出
                  </summary>
                  <div class="mt-3">
                    <textarea v-model="testInput" rows="4" :class="[inputClass, 'font-mono text-xs resize-none']" placeholder='{"enrich_content": {"status": "enriched", "text": "测试内容..."}}'></textarea>
                    <p class="mt-1.5 text-xs text-slate-400">JSON 格式，模拟前序步骤的输出作为当前步骤的输入</p>
                  </div>
                </details>

                <!-- Run Button -->
                <div>
                  <button
                    class="w-full px-6 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 disabled:opacity-50 transition-all duration-200"
                    :disabled="testing"
                    @click="handleTest"
                  >
                    <span class="flex items-center justify-center gap-2">
                      <svg v-if="testing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                      </svg>
                      <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
                      </svg>
                      {{ testing ? '执行中...' : '运行测试' }}
                    </span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Right: Result -->
            <div class="w-full md:w-1/2">
              <!-- Empty state -->
              <div v-if="!testResult" class="flex flex-col items-center justify-center py-16 px-6 bg-white rounded-xl border border-slate-200/60 border-dashed">
                <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mb-4">
                  <svg class="w-6 h-6 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                  </svg>
                </div>
                <p class="text-sm font-medium text-slate-400">运行测试查看结果</p>
                <p class="text-xs text-slate-300 mt-1">配置参数后点击「运行测试」</p>
              </div>

              <!-- Result panel -->
              <div v-else class="rounded-xl border overflow-hidden" :class="testResult.status === 'success' ? 'border-emerald-200' : 'border-rose-200'">
                <!-- Status Header -->
                <div class="px-5 py-3.5 flex items-center gap-2" :class="testResult.status === 'success' ? 'bg-emerald-50' : 'bg-rose-50'">
                  <svg v-if="testResult.status === 'success'" class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <svg v-else class="w-5 h-5 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                  </svg>
                  <span class="text-sm font-semibold" :class="testResult.status === 'success' ? 'text-emerald-800' : 'text-rose-800'">
                    {{ testResult.status === 'success' ? '测试通过' : '测试失败' }}
                  </span>
                  <span v-if="testResult.elapsed_seconds" class="text-xs text-slate-400 ml-auto tabular-nums">{{ testResult.elapsed_seconds }}s</span>
                </div>

                <!-- Success -->
                <div v-if="testResult.status === 'success' && testResult.result" class="p-5 bg-white space-y-4">
                  <div v-if="resultMetrics.length > 0" class="grid grid-cols-2 gap-3">
                    <div v-for="(m, idx) in resultMetrics" :key="idx" class="px-3.5 py-2.5 bg-slate-50 rounded-xl border border-slate-100">
                      <div class="text-xs text-slate-400 mb-0.5">{{ m.label }}</div>
                      <div class="text-sm font-semibold text-slate-800 truncate" :title="m.value">{{ m.value }}</div>
                    </div>
                  </div>
                  <details class="group">
                    <summary class="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700 select-none flex items-center gap-1.5">
                      <svg class="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                      查看原始 JSON
                    </summary>
                    <pre class="mt-2 p-3 bg-slate-900 text-slate-100 rounded-lg text-xs overflow-x-auto max-h-64 overflow-y-auto">{{ JSON.stringify(testResult.result, null, 2) }}</pre>
                  </details>
                </div>

                <!-- Error -->
                <div v-if="testResult.status === 'error'" class="p-5 bg-white space-y-3">
                  <div>
                    <label class="block text-xs font-medium text-rose-600 mb-1">错误信息</label>
                    <p class="text-sm text-slate-800 font-mono">{{ testResult.error }}</p>
                  </div>
                  <details v-if="testResult.traceback" class="group">
                    <summary class="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700 select-none flex items-center gap-1.5">
                      <svg class="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                      查看完整堆栈
                    </summary>
                    <pre class="mt-2 p-3 bg-slate-900 text-rose-300 rounded-lg text-xs overflow-x-auto max-h-48 overflow-y-auto">{{ testResult.traceback }}</pre>
                  </details>
                </div>

                <!-- Request/Response -->
                <div class="px-5 pb-4 pt-0 bg-white space-y-2 border-t border-slate-100">
                  <details v-if="testRequest" class="group">
                    <summary class="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700 select-none flex items-center gap-1.5 pt-3">
                      <svg class="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                      请求参数
                    </summary>
                    <pre class="mt-2 p-3 bg-slate-900 text-sky-300 rounded-lg text-xs overflow-x-auto max-h-48 overflow-y-auto">{{ JSON.stringify(testRequest, null, 2) }}</pre>
                  </details>
                  <details class="group">
                    <summary class="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700 select-none flex items-center gap-1.5">
                      <svg class="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                      完整响应
                    </summary>
                    <pre class="mt-2 p-3 bg-slate-900 text-slate-100 rounded-lg text-xs overflow-x-auto max-h-64 overflow-y-auto">{{ JSON.stringify(testResult, null, 2) }}</pre>
                  </details>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modals -->
    <PipelineTemplateFormModal
      :visible="showPTFormModal"
      :template="editingPT"
      @submit="handlePTSubmit"
      @cancel="showPTFormModal = false"
    />

    <PromptTemplateFormModal
      :visible="showPromptForm"
      :template="editingPrompt"
      @submit="handlePromptSubmit"
      @cancel="showPromptForm = false"
    />

    <ConfirmDialog
      :visible="showDeletePTDialog"
      title="删除流水线模板"
      message="确定要删除该模板吗？"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDeletePT"
      @cancel="showDeletePTDialog = false"
    />

    <ConfirmDialog
      :visible="showDeletePrDialog"
      title="删除提示词模板"
      message="确定要删除该模板吗？"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDeletePrompt"
      @cancel="showDeletePrDialog = false"
    />

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
