<script setup>
import { ref, watch, onMounted, computed } from 'vue'
import { getStepDefinitions } from '@/api/pipeline-templates'
import { testStep } from '@/api/pipelines'
import { listContent } from '@/api/content'

const props = defineProps({
  visible: Boolean,
})

const emit = defineEmits(['close'])

const stepDefs = ref({})
const contentList = ref([])
const loadingDefs = ref(true)

// 表单
const selectedStep = ref('')
const selectedContentId = ref('')
const stepConfig = ref('{}')
const testInput = ref('{}')

// 结果
const testing = ref(false)
const testResult = ref(null)

const currentStepDef = computed(() => stepDefs.value[selectedStep.value] || null)

const configPlaceholder = computed(() => {
  if (!currentStepDef.value?.config_schema?.properties) return '{}'
  const schema = currentStepDef.value.config_schema.properties
  const example = {}
  for (const [key, prop] of Object.entries(schema)) {
    example[key] = prop.default ?? prop.enum?.[0] ?? ''
  }
  return JSON.stringify(example, null, 2)
})

onMounted(async () => {
  try {
    const [defRes, contentRes] = await Promise.all([
      getStepDefinitions(),
      listContent({ page_size: 50 }),
    ])
    if (defRes.code === 0) stepDefs.value = defRes.data
    if (contentRes.code === 0) contentList.value = contentRes.data
  } finally {
    loadingDefs.value = false
  }
})

watch(() => selectedStep.value, () => {
  testResult.value = null
  // 自动填充默认配置
  if (currentStepDef.value?.config_schema?.properties) {
    const schema = currentStepDef.value.config_schema.properties
    const defaults = {}
    for (const [key, prop] of Object.entries(schema)) {
      if (prop.default !== undefined) defaults[key] = prop.default
    }
    stepConfig.value = JSON.stringify(defaults, null, 2)
  } else {
    stepConfig.value = '{}'
  }
})

watch(() => props.visible, (val) => {
  if (val) {
    testResult.value = null
  }
})

async function handleTest() {
  if (!selectedStep.value) return

  // 校验 JSON
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

const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
</script>

<template>
  <Transition
    enter-active-class="transition-all duration-200 ease-out"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition-all duration-150 ease-in"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="visible"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="emit('close')"
    >
      <div class="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-5 border-b border-slate-100">
          <div>
            <h3 class="text-lg font-semibold text-slate-900 tracking-tight">步骤测试台</h3>
            <p class="text-xs text-slate-400 mt-0.5">独立运行单个原子操作，验证配置和排查问题</p>
          </div>
          <button
            @click="emit('close')"
            class="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto p-6 space-y-5">
          <!-- Step Type -->
          <div>
            <label class="block text-sm font-medium text-slate-700 mb-1.5">步骤类型 *</label>
            <select v-model="selectedStep" :class="selectClass">
              <option value="">选择要测试的步骤...</option>
              <option v-for="(def, key) in stepDefs" :key="key" :value="key">
                {{ def.display_name }} ({{ key }})
              </option>
            </select>
            <p v-if="currentStepDef" class="mt-1.5 text-xs text-slate-400">{{ currentStepDef.description }}</p>
          </div>

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

          <!-- Test Input (previous_steps) -->
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

            <!-- Success result -->
            <div v-if="testResult.status === 'success' && testResult.result" class="p-4 bg-white">
              <label class="block text-xs font-medium text-slate-500 mb-2">输出结果</label>
              <pre class="p-3 bg-slate-900 text-slate-100 rounded-lg text-xs overflow-x-auto max-h-64 overflow-y-auto">{{ JSON.stringify(testResult.result, null, 2) }}</pre>
            </div>

            <!-- Error detail -->
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
    </div>
  </Transition>
</template>
