<script setup>
import { ref, computed } from 'vue'
import { testLLMConnection } from '@/api/settings'

const props = defineProps({
  form: { type: Object, required: true },
  fieldErrors: { type: Object, required: true },
  isDirty: { type: Boolean, required: true },
  groupSaving: { type: Boolean, required: false, default: false },
})

const emit = defineEmits(['update:form', 'save', 'validate-field'])

// LLM Provider presets
const providerPresets = {
  deepseek: { label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  qwen: { label: '通义千问 (Qwen)', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  openai: { label: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  siliconflow: { label: 'SiliconFlow', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct' },
  custom: { label: '自定义', base_url: '', model: '' },
}

const selectedProvider = ref('custom')

function initProvider(baseUrl) {
  selectedProvider.value = detectProvider(baseUrl)
}

function detectProvider(baseUrl) {
  if (!baseUrl) return 'custom'
  if (baseUrl.includes('deepseek')) return 'deepseek'
  if (baseUrl.includes('dashscope.aliyuncs.com')) return 'qwen'
  if (baseUrl.includes('api.openai.com')) return 'openai'
  if (baseUrl.includes('siliconflow')) return 'siliconflow'
  return 'custom'
}

function onProviderChange(provider) {
  selectedProvider.value = provider
  if (provider !== 'custom') {
    const preset = providerPresets[provider]
    updateField('llm_base_url', preset.base_url)
    updateField('llm_model', preset.model)
  }
}

// Password visibility
const visiblePasswords = ref({})

function togglePassword(key) {
  visiblePasswords.value[key] = !visiblePasswords.value[key]
}

// LLM test
const testing = ref(false)
const testResult = ref(null)

async function handleTestLLM() {
  const key = props.form.llm_api_key
  if (!key) {
    testResult.value = { success: false, message: '请先填写 API Key' }
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const res = await testLLMConnection({
      api_key: key,
      base_url: props.form.llm_base_url,
      model: props.form.llm_model,
    })
    if (res.code === 0) {
      testResult.value = { success: true, message: `连接成功 (${res.data.model})` }
    } else {
      testResult.value = { success: false, message: res.message }
    }
  } catch (e) {
    testResult.value = { success: false, message: '请求失败: ' + (e.message || '网络错误') }
  } finally {
    testing.value = false
  }
}

function updateField(key, value) {
  emit('update:form', { ...props.form, [key]: value })
}

// Group definition
const group = {
  title: 'LLM 配置',
  icon: 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z',
  color: 'text-indigo-500 bg-indigo-50',
  id: 'llm',
  keys: [
    { key: 'llm_api_key', label: 'API Key', type: 'password', description: 'LLM 服务的 API Key' },
    { key: 'llm_base_url', label: 'Base URL', type: 'url', description: 'LLM API 地址（OpenAI 兼容）' },
    { key: 'llm_model', label: '模型', type: 'text', description: '模型名称，如 deepseek-chat、qwen-plus、gpt-4o-mini' },
  ],
}

defineExpose({ initProvider })
</script>

<template>
  <div class="px-4 py-4 max-w-3xl">
    <!-- 分组标题 -->
    <div class="flex items-center gap-3 mb-5">
      <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="group.color">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" :d="group.icon" />
        </svg>
      </div>
      <h3 class="text-sm font-semibold text-slate-800">{{ group.title }}</h3>
    </div>

    <div class="space-y-5">
      <!-- Provider 快速选择 -->
      <div>
        <label class="block text-sm font-medium text-slate-700 mb-1.5">服务商</label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="(preset, key) in providerPresets"
            :key="key"
            class="px-3 py-1.5 text-sm rounded-lg border transition-all duration-200"
            :class="selectedProvider === key
              ? 'bg-indigo-50 border-indigo-300 text-indigo-700 font-medium shadow-sm'
              : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'"
            @click="onProviderChange(key)"
          >
            {{ preset.label }}
          </button>
        </div>
        <p class="mt-1.5 text-xs text-slate-400">选择服务商自动填充 Base URL 和模型，也可选「自定义」手动输入</p>
      </div>

      <!-- 表单字段 -->
      <div v-for="item in group.keys" :key="item.key">
        <label class="block text-sm font-medium text-slate-700 mb-1.5">{{ item.label }}</label>
        <div class="relative">
          <input
            :value="form[item.key]"
            :type="item.type === 'password' && !visiblePasswords[item.key] ? 'password' : 'text'"
            :placeholder="item.description"
            class="w-full px-3.5 py-2.5 bg-white border rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 outline-none transition-all duration-200"
            :class="[
              fieldErrors[item.key]
                ? 'border-rose-300 focus:ring-rose-500/20 focus:border-rose-400'
                : 'border-slate-200 focus:ring-indigo-500/20 focus:border-indigo-400',
              item.type === 'password' ? 'pr-10' : ''
            ]"
            @input="updateField(item.key, $event.target.value)"
            @blur="$emit('validate-field', item.key, item.type)"
          />
          <!-- 密码显示/隐藏切换 -->
          <button
            v-if="item.type === 'password'"
            type="button"
            class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
            @click="togglePassword(item.key)"
          >
            <svg v-if="visiblePasswords[item.key]" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        </div>
        <!-- 字段错误 -->
        <p v-if="fieldErrors[item.key]" class="mt-1.5 text-xs text-rose-500">{{ fieldErrors[item.key] }}</p>
        <p v-else class="mt-1.5 text-xs text-slate-400">{{ item.description }}</p>
      </div>

      <!-- LLM 测试连接 -->
      <div class="pt-2 border-t border-slate-100">
        <div class="flex items-center gap-3">
          <button
            class="px-4 py-2 text-sm font-medium rounded-lg border transition-all duration-200 disabled:opacity-50"
            :class="testing
              ? 'bg-slate-50 border-slate-200 text-slate-400'
              : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50 hover:border-slate-300'"
            :disabled="testing || !form.llm_api_key || !form.llm_base_url || !form.llm_model"
            @click="handleTestLLM"
          >
            <span class="flex items-center gap-1.5">
              <svg v-if="testing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
              </svg>
              {{ testing ? '测试中...' : '测试连接' }}
            </span>
          </button>
          <Transition
            enter-active-class="transition-all duration-300 ease-out"
            enter-from-class="opacity-0 translate-x-2"
            enter-to-class="opacity-100 translate-x-0"
            leave-active-class="transition-all duration-200 ease-in"
            leave-from-class="opacity-100"
            leave-to-class="opacity-0"
          >
            <span
              v-if="testResult"
              class="text-sm flex items-center gap-1.5"
              :class="testResult.success ? 'text-emerald-600' : 'text-rose-600'"
            >
              <svg v-if="testResult.success" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              {{ testResult.message }}
            </span>
          </Transition>
        </div>
        <p class="mt-1.5 text-xs text-slate-400">使用当前填写的配置发送一条测试消息，验证 API Key 和模型是否可用</p>
      </div>
    </div>

    <!-- 分组保存按钮 -->
    <div class="mt-6 pt-4 border-t border-slate-100">
      <button
        class="px-5 py-2.5 text-sm font-medium text-white rounded-xl shadow-sm transition-all duration-200 disabled:opacity-50"
        :class="isDirty
          ? 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 shadow-indigo-200'
          : 'bg-slate-300 cursor-not-allowed'"
        :disabled="groupSaving || !isDirty"
        @click="$emit('save')"
      >
        <span class="flex items-center gap-1.5">
          <svg v-if="groupSaving" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {{ groupSaving ? '保存中...' : '保存LLM 配置' }}
        </span>
      </button>
    </div>
  </div>
</template>
