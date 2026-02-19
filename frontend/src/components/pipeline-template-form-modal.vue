<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { ChevronUp, ChevronDown, X, Plus } from 'lucide-vue-next'
import { getStepDefinitions } from '@/api/pipeline-templates'
import { listPromptTemplates } from '@/api/prompt-templates'
import { useModelOptions } from '@/composables/useModelOptions'

const props = defineProps({
  visible: Boolean,
  template: { type: Object, default: null },
})

const emit = defineEmits(['submit', 'cancel'])

const stepDefinitions = ref({})
const promptTemplates = ref([])
const showStepPicker = ref(false)
const { modelOptions, currentLLMModel } = useModelOptions()

const form = ref({ name: '', description: '' })
const steps = ref([])

// Fetch metadata on mount
onMounted(async () => {
  try {
    const [defRes, ptRes] = await Promise.all([
      getStepDefinitions(),
      listPromptTemplates(),
    ])
    if (defRes.code === 0) stepDefinitions.value = defRes.data
    if (ptRes.code === 0) promptTemplates.value = ptRes.data
  } catch { /* ignore */ }
})

// Reset form when modal opens
watch(() => props.visible, (val) => {
  if (val) {
    showStepPicker.value = false
    if (props.template) {
      form.value = { name: props.template.name, description: props.template.description || '' }
      try {
        const parsed = JSON.parse(props.template.steps_config || '[]')
        steps.value = parsed.map(s => ({ ...s }))
      } catch {
        steps.value = []
      }
    } else {
      form.value = { name: '', description: '' }
      steps.value = []
    }
  }
})

// Step type definitions list for the picker
const stepTypeList = computed(() => {
  return Object.values(stepDefinitions.value)
})

// Get display name for a step type
function getStepDisplayName(stepType) {
  return stepDefinitions.value[stepType]?.display_name || stepType
}

function getStepDescription(stepType) {
  return stepDefinitions.value[stepType]?.description || ''
}

function getConfigSchema(stepType) {
  return stepDefinitions.value[stepType]?.config_schema || {}
}

function getConfigProperties(stepType) {
  const schema = getConfigSchema(stepType)
  return schema.properties || {}
}

// Add a step with default config values
function addStep(stepDef) {
  const config = {}
  const cfgProps = stepDef.config_schema?.properties || {}
  for (const [key, prop] of Object.entries(cfgProps)) {
    if (key === 'model' && currentLLMModel.value) {
      config[key] = currentLLMModel.value
    } else if (prop.default !== undefined) {
      config[key] = prop.default
    } else if (prop.type === 'boolean') {
      config[key] = false
    } else {
      config[key] = ''
    }
  }
  steps.value.push({
    step_type: stepDef.step_type,
    is_critical: stepDef.is_critical_default || false,
    config,
  })
  showStepPicker.value = false
}

function removeStep(index) {
  steps.value.splice(index, 1)
}

function moveStep(index, direction) {
  const target = index + direction
  if (target < 0 || target >= steps.value.length) return
  const temp = steps.value[index]
  steps.value[index] = steps.value[target]
  steps.value[target] = temp
  // Force reactivity
  steps.value = [...steps.value]
}

function handleSubmit() {
  if (!form.value.name.trim()) return
  const data = {
    name: form.value.name,
    description: form.value.description || null,
    steps_config: JSON.stringify(steps.value),
  }
  emit('submit', data)
}

const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-base sm:text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-base sm:text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
const labelClass = 'block text-sm font-medium text-slate-700 mb-1.5'
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="emit('cancel')"></div>
    <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
      <!-- Header -->
      <div class="sticky top-0 bg-white border-b border-slate-100 px-6 py-5 rounded-t-2xl z-10 shrink-0">
        <h3 class="text-lg font-semibold text-slate-900 tracking-tight">
          {{ template ? '编辑流水线模板' : '新增流水线模板' }}
        </h3>
        <p class="text-xs text-slate-400 mt-0.5">配置处理步骤与参数</p>
      </div>

      <!-- Scrollable Content -->
      <div class="overflow-y-auto flex-1 p-6 space-y-6">
        <!-- Basic Info -->
        <div class="space-y-4">
          <div>
            <label :class="labelClass">模板名称 *</label>
            <input v-model="form.name" type="text" :class="inputClass" placeholder="例: 文章分析" />
          </div>
          <div>
            <label :class="labelClass">描述</label>
            <input v-model="form.description" type="text" :class="inputClass" placeholder="可选描述" />
          </div>
        </div>

        <!-- Steps Section -->
        <div>
          <label :class="labelClass">处理步骤</label>

          <!-- Steps List -->
          <div v-if="steps.length > 0" class="space-y-3 mb-4">
            <div
              v-for="(step, idx) in steps"
              :key="idx"
              class="bg-slate-50/80 border border-slate-200/60 rounded-xl p-4"
            >
              <!-- Step Header -->
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                  <!-- Move Buttons -->
                  <div class="flex flex-col gap-0.5">
                    <button
                      type="button"
                      class="p-0.5 text-slate-400 hover:text-slate-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      :disabled="idx === 0"
                      @click="moveStep(idx, -1)"
                    >
                      <ChevronUp class="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      class="p-0.5 text-slate-400 hover:text-slate-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      :disabled="idx === steps.length - 1"
                      @click="moveStep(idx, 1)"
                    >
                      <ChevronDown class="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <!-- Step Info -->
                  <div>
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-medium text-slate-400">#{{ idx + 1 }}</span>
                      <span class="text-sm font-semibold text-slate-800">{{ getStepDisplayName(step.step_type) }}</span>
                    </div>
                    <p class="text-xs text-slate-400 mt-0.5">{{ getStepDescription(step.step_type) }}</p>
                  </div>
                </div>

                <!-- Right Controls -->
                <div class="flex items-center gap-3">
                  <label class="flex items-center gap-1.5 cursor-pointer">
                    <input
                      v-model="step.is_critical"
                      type="checkbox"
                      class="h-3.5 w-3.5 text-rose-500 border-slate-300 rounded focus:ring-rose-400"
                    />
                    <span class="text-xs text-slate-500">关键步骤</span>
                  </label>
                  <button
                    type="button"
                    class="p-1 text-slate-400 hover:text-rose-500 transition-colors"
                    @click="removeStep(idx)"
                  >
                    <X class="w-4 h-4" />
                  </button>
                </div>
              </div>

              <!-- Step Config -->
              <div
                v-if="Object.keys(getConfigProperties(step.step_type)).length > 0"
                class="mt-3 pt-3 border-t border-slate-200/60"
              >
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div
                    v-for="(prop, propKey) in getConfigProperties(step.step_type)"
                    :key="propKey"
                  >
                    <label class="block text-xs font-medium text-slate-500 mb-1">
                      {{ prop.description || propKey }}
                    </label>

                    <!-- Enum → select -->
                    <select
                      v-if="prop.enum"
                      v-model="step.config[propKey]"
                      :class="selectClass"
                      class="!py-2 !text-xs"
                    >
                      <option v-for="opt in prop.enum" :key="opt" :value="opt">{{ opt }}</option>
                    </select>

                    <!-- Boolean → checkbox -->
                    <label
                      v-else-if="prop.type === 'boolean'"
                      class="flex items-center gap-2 py-2"
                    >
                      <input
                        v-model="step.config[propKey]"
                        type="checkbox"
                        class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                      />
                      <span class="text-xs text-slate-600">{{ prop.description || propKey }}</span>
                    </label>

                    <!-- prompt_template_id → prompt template dropdown -->
                    <select
                      v-else-if="propKey === 'prompt_template_id'"
                      v-model="step.config[propKey]"
                      :class="selectClass"
                      class="!py-2 !text-xs"
                    >
                      <option value="">不绑定</option>
                      <option v-for="pt in promptTemplates" :key="pt.id" :value="pt.id">{{ pt.name }}</option>
                    </select>

                    <!-- model → model preset dropdown -->
                    <select
                      v-else-if="propKey === 'model'"
                      v-model="step.config[propKey]"
                      :class="selectClass"
                      class="!py-2 !text-xs"
                    >
                      <option value="">系统默认</option>
                      <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
                    </select>

                    <!-- Default string → text input -->
                    <input
                      v-else
                      v-model="step.config[propKey]"
                      type="text"
                      :class="inputClass"
                      class="!py-2 !text-xs"
                      :placeholder="prop.default || ''"
                    />
                  </div>
                </div>
              </div>

              <!-- No config -->
              <div
                v-else
                class="mt-3 pt-3 border-t border-slate-200/60"
              >
                <p class="text-xs text-slate-400">无需配置</p>
              </div>
            </div>
          </div>

          <!-- Empty State -->
          <div v-else class="mb-4 py-8 text-center border border-dashed border-slate-200 rounded-xl">
            <p class="text-sm text-slate-400">尚未添加步骤，点击下方按钮添加</p>
          </div>

          <!-- Add Step Button -->
          <div class="relative">
            <button
              type="button"
              class="w-full py-3 border-2 border-dashed border-slate-200 rounded-xl text-sm font-medium text-slate-400 hover:border-indigo-300 hover:text-indigo-500 transition-all duration-200 flex items-center justify-center gap-1.5"
              @click="showStepPicker = !showStepPicker"
            >
              <Plus class="w-4 h-4" />
              添加步骤
            </button>

            <!-- Step Type Picker -->
            <div
              v-if="showStepPicker"
              class="mt-2 bg-white border border-slate-200 rounded-xl shadow-lg overflow-hidden"
            >
              <button
                v-for="def in stepTypeList"
                :key="def.step_type"
                type="button"
                class="w-full px-4 py-3 text-left hover:bg-indigo-50 transition-colors duration-150 border-b border-slate-100 last:border-b-0"
                @click="addStep(def)"
              >
                <span class="text-sm font-medium text-slate-800">{{ def.display_name }}</span>
                <p class="text-xs text-slate-400 mt-0.5">{{ def.description }}</p>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="sticky bottom-0 bg-white border-t border-slate-100 px-6 py-4 rounded-b-2xl z-10 shrink-0">
        <div class="flex justify-end gap-3">
          <button
            type="button"
            class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
            @click="emit('cancel')"
          >
            取消
          </button>
          <button
            type="button"
            class="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
            @click="handleSubmit"
          >
            {{ template ? '保存修改' : '创建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
