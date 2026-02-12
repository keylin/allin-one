<script setup>
import { ref, onMounted } from 'vue'
import { getSettings, updateSettings } from '@/api/settings'

const loading = ref(true)
const saving = ref(false)
const saveMessage = ref('')

// LLM Provider 预设
const providerPresets = {
  deepseek: { label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  qwen: { label: '通义千问 (Qwen)', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  openai: { label: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  siliconflow: { label: 'SiliconFlow', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct' },
  custom: { label: '自定义', base_url: '', model: '' },
}

const selectedProvider = ref('custom')

function onProviderChange(provider) {
  selectedProvider.value = provider
  if (provider !== 'custom') {
    const preset = providerPresets[provider]
    form.value.llm_base_url = preset.base_url
    form.value.llm_model = preset.model
  }
}

function detectProvider(baseUrl) {
  if (!baseUrl) return 'custom'
  if (baseUrl.includes('deepseek')) return 'deepseek'
  if (baseUrl.includes('dashscope.aliyuncs.com')) return 'qwen'
  if (baseUrl.includes('api.openai.com')) return 'openai'
  if (baseUrl.includes('siliconflow')) return 'siliconflow'
  return 'custom'
}

// 设置分组定义
const groups = [
  {
    title: 'LLM 配置',
    icon: 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z',
    color: 'text-indigo-500 bg-indigo-50',
    hasProviderSelect: true,
    keys: [
      { key: 'llm_api_key', label: 'API Key', type: 'password', description: 'LLM 服务的 API Key' },
      { key: 'llm_base_url', label: 'Base URL', type: 'text', description: 'LLM API 地址（OpenAI 兼容）' },
      { key: 'llm_model', label: '模型', type: 'text', description: '模型名称，如 deepseek-chat、qwen-plus、gpt-4o-mini' },
    ],
  },
  {
    title: '邮件推送 (SMTP)',
    icon: 'M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75',
    color: 'text-blue-500 bg-blue-50',
    keys: [
      { key: 'smtp_host', label: 'SMTP 服务器', type: 'text', description: '如 smtp.qq.com' },
      { key: 'smtp_port', label: 'SMTP 端口', type: 'text', description: 'SSL: 465, TLS: 587' },
      { key: 'smtp_user', label: 'SMTP 用户名', type: 'text', description: '登录邮箱账号' },
      { key: 'smtp_password', label: 'SMTP 密码', type: 'password', description: '邮箱授权码或密码' },
      { key: 'notify_email', label: '收件人邮箱', type: 'email', description: '多个用逗号分隔' },
    ],
  },
  {
    title: '通知渠道',
    icon: 'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0',
    color: 'text-rose-500 bg-rose-50',
    keys: [
      { key: 'notify_webhook', label: 'Webhook URL', type: 'text', description: '通知 Webhook 地址' },
      { key: 'notify_dingtalk_webhook', label: '钉钉机器人 Webhook', type: 'text', description: '钉钉群机器人 Webhook URL' },
    ],
  },
]

const form = ref({})

onMounted(async () => {
  try {
    const res = await getSettings()
    if (res.code === 0) {
      // 将 {key: {value, description}} 展平为 {key: value}
      const flat = {}
      for (const [k, v] of Object.entries(res.data)) {
        flat[k] = v.value || ''
      }
      form.value = flat
      // 根据已保存的 base_url 自动识别 provider
      selectedProvider.value = detectProvider(flat.llm_base_url)
    }
  } finally {
    loading.value = false
  }
})

async function handleSave() {
  saving.value = true
  saveMessage.value = ''
  try {
    const settings = {}
    for (const group of groups) {
      for (const item of group.keys) {
        settings[item.key] = form.value[item.key] || null
      }
    }
    const res = await updateSettings(settings)
    if (res.code === 0) {
      saveMessage.value = '保存成功'
      setTimeout(() => { saveMessage.value = '' }, 3000)
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-bold text-slate-900 tracking-tight">系统设置</h2>
        <p class="text-sm text-slate-400 mt-0.5">配置 LLM 与通知</p>
      </div>
      <div class="flex items-center gap-3">
        <Transition
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="opacity-0 translate-x-2"
          enter-to-class="opacity-100 translate-x-0"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="opacity-100 translate-x-0"
          leave-to-class="opacity-0 translate-x-2"
        >
          <span v-if="saveMessage" class="text-sm font-medium text-emerald-600 flex items-center gap-1.5">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {{ saveMessage }}
          </span>
        </Transition>
        <button
          class="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 disabled:opacity-50 transition-all duration-200"
          :disabled="saving"
          @click="handleSave"
        >
          <span class="flex items-center gap-1.5">
            <svg v-if="saving" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {{ saving ? '保存中...' : '保存设置' }}
          </span>
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-16">
      <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <div v-else class="space-y-5 max-w-3xl">
      <div v-for="group in groups" :key="group.title" class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <div class="px-6 py-4 bg-slate-50/50 border-b border-slate-100 flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="group.color">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="group.icon" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-slate-800">{{ group.title }}</h3>
        </div>
        <div class="p-6 space-y-5">
          <!-- Provider 快速选择 -->
          <div v-if="group.hasProviderSelect">
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
          <div v-for="item in group.keys" :key="item.key">
            <label class="block text-sm font-medium text-slate-700 mb-1.5">{{ item.label }}</label>
            <input
              v-model="form[item.key]"
              :type="item.type"
              :placeholder="item.description"
              class="w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
            />
            <p class="mt-1.5 text-xs text-slate-400">{{ item.description }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
