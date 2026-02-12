<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import dayjs from 'dayjs'
import { listTemplates, createTemplate, updateTemplate, deleteTemplate, getStepDefinitions } from '@/api/pipeline-templates'
import { listPromptTemplates, createPromptTemplate, updatePromptTemplate, deletePromptTemplate } from '@/api/prompt-templates'
import { testStep } from '@/api/pipelines'
import { listContent } from '@/api/content'
import PromptTemplateFormModal from '@/components/prompt-template-form-modal.vue'
import PipelineTemplateFormModal from '@/components/pipeline-template-form-modal.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'

// Tab — default to steps (原子能力)
const activeTab = ref('steps')

// ---- Step Definitions (shared) ----
const stepDefs = ref({})

async function fetchStepDefinitions() {
  try {
    const res = await getStepDefinitions()
    if (res.code === 0) stepDefs.value = res.data
  } catch { /* ignore */ }
}

const stepDefList = computed(() =>
  Object.entries(stepDefs.value).map(([key, def]) => ({ key, ...def }))
)

// ---- Atomic Step Test (inline panel) ----
const selectedStep = ref(null) // key string of the step being debugged
const contentList = ref([])
const selectedContentId = ref('')
const stepConfig = ref('{}')
const testInput = ref('{}')
const testing = ref(false)
const testResult = ref(null)

const currentStepDef = computed(() => selectedStep.value ? stepDefs.value[selectedStep.value] : null)

const configPlaceholder = computed(() => {
  if (!currentStepDef.value?.config_schema?.properties) return '{}'
  const schema = currentStepDef.value.config_schema.properties
  const example = {}
  for (const [key, prop] of Object.entries(schema)) {
    example[key] = prop.default ?? prop.enum?.[0] ?? ''
  }
  return JSON.stringify(example, null, 2)
})

async function fetchContentList() {
  try {
    const res = await listContent({ page_size: 50 })
    if (res.code === 0) contentList.value = res.data
  } catch { /* ignore */ }
}

function startDebugStep(stepKey) {
  selectedStep.value = stepKey
  testResult.value = null
  // auto-fill default config
  const def = stepDefs.value[stepKey]
  if (def?.config_schema?.properties) {
    const defaults = {}
    for (const [key, prop] of Object.entries(def.config_schema.properties)) {
      if (prop.default !== undefined) defaults[key] = prop.default
    }
    stepConfig.value = JSON.stringify(defaults, null, 2)
  } else {
    stepConfig.value = '{}'
  }
  selectedContentId.value = ''
  testInput.value = '{}'
  // lazy load content list
  if (contentList.value.length === 0) fetchContentList()
}

function closeDebugPanel() {
  selectedStep.value = null
  testResult.value = null
}

watch(() => selectedStep.value, () => {
  testResult.value = null
})

async function handleTest() {
  if (!selectedStep.value) return
  let parsedConfig, parsedInput
  try {
    parsedConfig = JSON.parse(stepConfig.value || '{}')
  } catch {
    testResult.value = { status: 'error', error: 'step_config JSON 格式错误' }
    return
  }
  try {
    parsedInput = JSON.parse(testInput.value || '{}')
  } catch {
    testResult.value = { status: 'error', error: 'test_input JSON 格式错误' }
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const res = await testStep({
      step_type: selectedStep.value,
      content_id: selectedContentId.value || undefined,
      step_config: parsedConfig,
      test_input: parsedInput,
    })
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

// ---- Pipeline Templates ----
const pipelineTemplates = ref([])
const ptLoading = ref(false)

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
  if (res.code === 0) await fetchPipelineTemplates()
}

// ---- Prompt Templates ----
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

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm') : '-'
}

const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'

onMounted(() => {
  fetchStepDefinitions()
  fetchPipelineTemplates()
  fetchPromptTemplates()
})
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="mb-6">
      <h2 class="text-xl font-bold text-slate-900 tracking-tight">信息处理</h2>
      <p class="text-sm text-slate-400 mt-0.5">原子能力管理、流水线模板与提示词模板</p>
    </div>

    <!-- Tab -->
    <div class="flex items-center gap-1 mb-6 bg-slate-100 rounded-xl p-1 max-w-fit">
      <button
        class="px-5 py-2 text-sm font-medium rounded-lg transition-all duration-200"
        :class="activeTab === 'steps'
          ? 'bg-white text-slate-900 shadow-sm'
          : 'text-slate-500 hover:text-slate-700'"
        @click="activeTab = 'steps'"
      >
        原子能力
      </button>
      <button
        class="px-5 py-2 text-sm font-medium rounded-lg transition-all duration-200"
        :class="activeTab === 'pipeline'
          ? 'bg-white text-slate-900 shadow-sm'
          : 'text-slate-500 hover:text-slate-700'"
        @click="activeTab = 'pipeline'"
      >
        流水线模板
      </button>
      <button
        class="px-5 py-2 text-sm font-medium rounded-lg transition-all duration-200"
        :class="activeTab === 'prompt'
          ? 'bg-white text-slate-900 shadow-sm'
          : 'text-slate-500 hover:text-slate-700'"
        @click="activeTab = 'prompt'"
      >
        提示词模板
      </button>
    </div>

    <!-- ========== 原子能力 Tab ========== -->
    <div v-if="activeTab === 'steps'">
      <!-- Step Cards Grid -->
      <div v-if="stepDefList.length === 0" class="text-center py-16">
        <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
          <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
          </svg>
        </div>
        <p class="text-sm text-slate-400">加载中...</p>
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="step in stepDefList"
          :key="step.key"
          class="bg-white rounded-xl border shadow-sm p-5 transition-all duration-200 hover:shadow-md"
          :class="selectedStep === step.key ? 'border-indigo-300 ring-2 ring-indigo-100' : 'border-slate-200/60 hover:border-slate-300/60'"
        >
          <div class="flex items-start justify-between gap-3 mb-3">
            <div class="flex-1 min-w-0">
              <h4 class="text-sm font-semibold text-slate-900">{{ step.display_name }}</h4>
              <span class="inline-flex mt-1.5 px-2 py-0.5 text-xs font-mono font-medium rounded-md bg-slate-100 text-slate-500">
                {{ step.key }}
              </span>
            </div>
            <button
              class="shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200"
              :class="selectedStep === step.key
                ? 'text-indigo-700 bg-indigo-100 hover:bg-indigo-200'
                : 'text-indigo-600 bg-indigo-50 hover:bg-indigo-100'"
              @click="selectedStep === step.key ? closeDebugPanel() : startDebugStep(step.key)"
            >
              {{ selectedStep === step.key ? '收起' : '调试' }}
            </button>
          </div>

          <p v-if="step.description" class="text-xs text-slate-400 leading-relaxed mb-3">{{ step.description }}</p>

          <!-- Config Schema Parameters -->
          <div v-if="step.config_schema?.properties && Object.keys(step.config_schema.properties).length > 0">
            <div class="text-xs font-medium text-slate-500 mb-1.5">配置参数</div>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="(prop, propKey) in step.config_schema.properties"
                :key="propKey"
                class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md bg-slate-50 text-slate-500 font-mono"
              >
                {{ propKey }}
                <span v-if="step.config_schema.required?.includes(propKey)" class="text-rose-400">*</span>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== Inline Test Panel ===== -->
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0 -translate-y-2"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div v-if="selectedStep" class="mt-6 bg-white rounded-xl border border-indigo-200 shadow-sm overflow-hidden">
          <div class="px-6 py-4 bg-indigo-50/50 border-b border-indigo-100 flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">
                调试: {{ currentStepDef?.display_name }}
                <span class="ml-2 text-xs font-mono font-normal text-slate-400">{{ selectedStep }}</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">独立运行单个原子操作，验证配置和排查问题</p>
            </div>
            <button
              class="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-white/60 rounded-lg transition-colors"
              @click="closeDebugPanel"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="p-6 space-y-5">
            <!-- Content Select -->
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1.5">目标内容</label>
              <select v-model="selectedContentId" :class="selectClass">
                <option value="">不选择 (使用模拟输入)</option>
                <option v-for="c in contentList" :key="c.id" :value="c.id">
                  {{ c.title?.substring(0, 60) }} [{{ c.status }}]
                </option>
              </select>
              <p class="mt-1.5 text-xs text-slate-400">选择一条已有内容进行真实测试，或留空使用模拟输入</p>
            </div>

            <!-- Step Config -->
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1.5">步骤配置 (JSON)</label>
              <textarea
                v-model="stepConfig"
                rows="4"
                :class="[inputClass, 'font-mono text-xs resize-none']"
                :placeholder="configPlaceholder"
              ></textarea>
            </div>

            <!-- Test Input -->
            <div v-if="!selectedContentId">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">模拟输入 (previous_steps JSON)</label>
              <textarea
                v-model="testInput"
                rows="3"
                :class="[inputClass, 'font-mono text-xs resize-none']"
                placeholder='{"enrich_content": {"status": "enriched", "text": "测试内容..."}}'
              ></textarea>
              <p class="mt-1.5 text-xs text-slate-400">模拟前序步骤的输出，作为当前步骤的输入</p>
            </div>

            <!-- Run Button -->
            <div>
              <button
                class="w-full sm:w-auto px-6 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 disabled:opacity-50 transition-all duration-200"
                :disabled="!selectedStep || testing"
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

            <!-- Result -->
            <div v-if="testResult" class="rounded-xl border overflow-hidden" :class="testResult.status === 'success' ? 'border-emerald-200' : 'border-rose-200'">
              <div class="px-4 py-3 flex items-center gap-2" :class="testResult.status === 'success' ? 'bg-emerald-50' : 'bg-rose-50'">
                <svg v-if="testResult.status === 'success'" class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <svg v-else class="w-5 h-5 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                <span class="text-sm font-semibold" :class="testResult.status === 'success' ? 'text-emerald-800' : 'text-rose-800'">
                  {{ testResult.status === 'success' ? '测试通过' : '测试失败' }}
                </span>
                <span v-if="testResult.elapsed_seconds" class="text-xs text-slate-400 ml-auto">
                  {{ testResult.elapsed_seconds }}s
                </span>
              </div>

              <div v-if="testResult.status === 'success' && testResult.result" class="p-4 bg-white">
                <label class="block text-xs font-medium text-slate-500 mb-2">输出结果</label>
                <pre class="p-3 bg-slate-900 text-slate-100 rounded-lg text-xs overflow-x-auto max-h-64 overflow-y-auto">{{ JSON.stringify(testResult.result, null, 2) }}</pre>
              </div>

              <div v-if="testResult.status === 'error'" class="p-4 bg-white space-y-3">
                <div>
                  <label class="block text-xs font-medium text-rose-600 mb-1">错误信息</label>
                  <p class="text-sm text-slate-800 font-mono">{{ testResult.error }}</p>
                </div>
                <details v-if="testResult.traceback" class="group">
                  <summary class="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700 select-none">
                    查看完整堆栈
                    <svg class="w-3.5 h-3.5 inline-block ml-0.5 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                  </summary>
                  <pre class="mt-2 p-3 bg-slate-900 text-rose-300 rounded-lg text-xs overflow-x-auto max-h-48 overflow-y-auto">{{ testResult.traceback }}</pre>
                </details>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <!-- ========== Pipeline Templates Tab ========== -->
    <div v-if="activeTab === 'pipeline'">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-semibold text-slate-800">流水线模板</h3>
        <button
          class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
          @click="startCreatePT"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新建模板
          </span>
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

      <!-- List -->
      <div v-else class="space-y-3">
        <div v-for="tpl in pipelineTemplates" :key="tpl.id" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-5 hover:border-slate-300/60 transition-all duration-200">
          <div class="flex items-center justify-between">
            <div>
              <div class="flex items-center gap-2">
                <span class="text-sm font-semibold text-slate-900">{{ tpl.name }}</span>
                <span v-if="tpl.is_builtin" class="text-xs px-2 py-0.5 bg-slate-100 text-slate-500 rounded-md font-medium">内置</span>
              </div>
              <p v-if="tpl.description" class="text-xs text-slate-400 mt-1.5 leading-relaxed">{{ tpl.description }}</p>
              <!-- Step Pills -->
              <div v-if="parseSteps(tpl.steps_config).length > 0" class="flex flex-wrap gap-1.5 mt-2">
                <span
                  v-for="(step, idx) in parseSteps(tpl.steps_config)"
                  :key="idx"
                  class="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-md bg-indigo-50 text-indigo-600"
                >
                  <span v-if="step.is_critical" class="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0"></span>
                  {{ getStepDisplayName(step.step_type) }}
                </span>
              </div>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                v-if="!tpl.is_builtin"
                class="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200"
                @click="startEditPT(tpl)"
              >
                编辑
              </button>
              <button
                v-if="!tpl.is_builtin"
                class="px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200"
                @click="openDeletePT(tpl.id)"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== Prompt Templates Tab ========== -->
    <div v-if="activeTab === 'prompt'">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-semibold text-slate-800">提示词模板</h3>
        <button
          class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
          @click="openCreatePrompt"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新建模板
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

      <!-- Table (Desktop) -->
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
  </div>
</template>
