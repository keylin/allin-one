<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSettings, updateSettings, testLLMConnection, clearExecutions, clearCollections } from '@/api/settings'
import {
  listCredentials, createCredential, deleteCredential, checkCredential, syncRsshub,
  generateBilibiliQrcode, pollBilibiliQrcode,
} from '@/api/credentials'
import { useToast } from '@/composables/useToast'
import QRCode from 'qrcode'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const loading = ref(true)

// ---- Tab ----
const tabs = [
  { id: 'llm', label: 'LLM 配置' },
  { id: 'smtp', label: '邮件推送' },
  { id: 'notify', label: '通知渠道' },
  { id: 'retention', label: '内容保留' },
  { id: 'credentials', label: '平台凭证' },
]

const activeTab = ref(route.query.tab || 'llm')

watch(() => route.query.tab, (tab) => {
  activeTab.value = tab || 'llm'
})

function switchTab(tab) {
  activeTab.value = tab
  const query = { ...route.query, tab }
  if (tab === 'llm') delete query.tab
  router.replace({ query }).catch(() => {})
}

// LLM 测试
const testing = ref(false)
const testResult = ref(null)

// 密码字段可见性
const visiblePasswords = ref({})

function togglePassword(key) {
  visiblePasswords.value[key] = !visiblePasswords.value[key]
}

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
    id: 'llm',
    hasProviderSelect: true,
    keys: [
      { key: 'llm_api_key', label: 'API Key', type: 'password', description: 'LLM 服务的 API Key' },
      { key: 'llm_base_url', label: 'Base URL', type: 'url', description: 'LLM API 地址（OpenAI 兼容）' },
      { key: 'llm_model', label: '模型', type: 'text', description: '模型名称，如 deepseek-chat、qwen-plus、gpt-4o-mini' },
    ],
  },
  {
    title: '邮件推送 (SMTP)',
    icon: 'M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75',
    color: 'text-blue-500 bg-blue-50',
    id: 'smtp',
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
    id: 'notify',
    keys: [
      { key: 'notify_webhook', label: 'Webhook URL', type: 'url', description: '通知 Webhook 地址' },
      { key: 'notify_dingtalk_webhook', label: '钉钉机器人 Webhook', type: 'url', description: '钉钉群机器人 Webhook URL' },
    ],
  },
  {
    title: '内容保留',
    icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z',
    color: 'text-amber-500 bg-amber-50',
    id: 'retention',
    keys: [
      { key: 'default_retention_days', label: '默认保留天数', type: 'number', description: '数据源未单独设置时的全局默认值（0 表示永久保留）' },
      { key: 'execution_retention_days', label: '执行记录保留天数', type: 'number', description: '超过此天数的已完成执行记录将被自动清理（0 表示永久保留）' },
      { key: 'execution_max_count', label: '执行记录数量上限', type: 'number', description: '超过上限的旧记录将被自动清理（0 表示不限制）' },
      { key: 'collection_retention_days', label: '采集记录保留天数', type: 'number', description: '超过此天数的已完成采集记录将被自动清理（0 表示永久保留）' },
      { key: 'collection_max_count', label: '采集记录数量上限', type: 'number', description: '超过上限的旧记录将被自动清理（0 表示不限制）' },
    ],
  },
]

const form = ref({})
const originalForm = ref({})

// 字段级错误
const fieldErrors = ref({})

// 分组保存状态
const groupSaving = ref({})

// 当前激活的设置分组
const activeGroup = computed(() => groups.find(g => g.id === activeTab.value))

// 脏值追踪
const isDirty = computed(() => {
  const dirty = {}
  for (const group of groups) {
    dirty[group.id] = group.keys.some(item => {
      const current = form.value[item.key] ?? ''
      const original = originalForm.value[item.key] ?? ''
      return current !== original
    })
  }
  return dirty
})

// 字段校验
function validateField(key, type) {
  const value = form.value[key]
  if (!value) {
    delete fieldErrors.value[key]
    return
  }
  if (type === 'url' && !/^https?:\/\/.+/.test(value)) {
    fieldErrors.value[key] = '应以 http:// 或 https:// 开头'
    return
  }
  if (type === 'email') {
    const emails = value.split(',').map(e => e.trim())
    const invalid = emails.some(e => e && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e))
    if (invalid) {
      fieldErrors.value[key] = '邮箱格式不正确'
      return
    }
  }
  if (type === 'number' && isNaN(value)) {
    fieldErrors.value[key] = '请输入数字'
    return
  }
  delete fieldErrors.value[key]
}

function validateGroup(group) {
  const errors = {}
  for (const item of group.keys) {
    validateField(item.key, item.type)
    if (fieldErrors.value[item.key]) {
      errors[item.key] = fieldErrors.value[item.key]
    }
  }
  return errors
}

// 分组保存
async function saveGroup(groupId) {
  const group = groups.find(g => g.id === groupId)
  const errors = validateGroup(group)
  if (Object.keys(errors).length) return

  groupSaving.value[groupId] = true
  try {
    const settings = {}
    for (const item of group.keys) {
      settings[item.key] = form.value[item.key] || null
    }
    const res = await updateSettings(settings)
    if (res.code === 0) {
      toast.success(`${group.title} 已保存`)
      // 更新快照
      for (const item of group.keys) {
        originalForm.value[item.key] = form.value[item.key]
      }
    } else {
      toast.error(res.message || '保存失败')
    }
  } catch (e) {
    toast.error('保存失败: ' + (e.message || '网络错误'))
  } finally {
    groupSaving.value[groupId] = false
  }
}

// ---- 手动清理 ----
const clearingExecutions = ref(false)
const clearingCollections = ref(false)
const confirmDialog = ref({ visible: false, title: '', message: '', onConfirm: null })

function showConfirm(title, message, onConfirm) {
  confirmDialog.value = { visible: true, title, message, onConfirm }
}

function closeConfirm() {
  confirmDialog.value = { visible: false, title: '', message: '', onConfirm: null }
}

function handleClearExecutions() {
  showConfirm(
    '清理执行记录',
    '将删除所有已完成、失败、已取消的执行记录及其步骤数据。正在运行和等待中的记录不受影响。确定继续？',
    async () => {
      closeConfirm()
      clearingExecutions.value = true
      try {
        const res = await clearExecutions()
        if (res.code === 0) {
          toast.success(`已清理 ${res.data.deleted} 条执行记录`)
        } else {
          toast.error(res.message || '清理失败')
        }
      } catch (e) {
        toast.error('清理失败: ' + (e.message || '网络错误'))
      } finally {
        clearingExecutions.value = false
      }
    }
  )
}

function handleClearCollections() {
  showConfirm(
    '清理采集记录',
    '将删除所有已完成和失败的采集记录。正在运行的记录不受影响。确定继续？',
    async () => {
      closeConfirm()
      clearingCollections.value = true
      try {
        const res = await clearCollections()
        if (res.code === 0) {
          toast.success(`已清理 ${res.data.deleted} 条采集记录`)
        } else {
          toast.error(res.message || '清理失败')
        }
      } catch (e) {
        toast.error('清理失败: ' + (e.message || '网络错误'))
      } finally {
        clearingCollections.value = false
      }
    }
  )
}

// ---- 平台凭证 ----
const credentials = ref([])
const credLoading = ref(false)
const credActionLoading = ref({})

// B站扫码
const biliAuthStatus = ref('idle')
const biliQrcodeKey = ref('')
const qrcodeCanvas = ref(null)
let biliPollTimer = null

async function loadCredentials() {
  credLoading.value = true
  try {
    const res = await listCredentials()
    if (res.code === 0) credentials.value = res.data
  } finally {
    credLoading.value = false
  }
}

async function handleCheckCredential(id) {
  credActionLoading.value[id] = 'checking'
  try {
    const res = await checkCredential(id)
    if (res.code === 0) {
      const cred = credentials.value.find(c => c.id === id)
      if (cred) cred.status = res.data.valid ? 'active' : 'expired'
    }
  } finally {
    delete credActionLoading.value[id]
  }
}

async function handleSyncRsshub(id) {
  credActionLoading.value[id] = 'syncing'
  try {
    await syncRsshub(id)
  } finally {
    delete credActionLoading.value[id]
  }
}

async function handleDeleteCredential(id) {
  const cred = credentials.value.find(c => c.id === id)
  if (!confirm(`确认删除凭证「${cred?.display_name}」？`)) return
  credActionLoading.value[id] = 'deleting'
  try {
    const res = await deleteCredential(id)
    if (res.code === 0) {
      credentials.value = credentials.value.filter(c => c.id !== id)
      toast.success('凭证已删除')
    } else {
      toast.error(res.message || '删除失败')
    }
  } finally {
    delete credActionLoading.value[id]
  }
}

async function startBiliAuth() {
  biliAuthStatus.value = 'loading'
  try {
    const res = await generateBilibiliQrcode()
    if (res.code !== 0) {
      biliAuthStatus.value = 'error'
      return
    }
    biliQrcodeKey.value = res.data.qrcode_key
    biliAuthStatus.value = 'waiting'

    await nextTick()
    if (qrcodeCanvas.value) {
      QRCode.toCanvas(qrcodeCanvas.value, res.data.url, { width: 200, margin: 2 })
    }

    clearBiliPoll()
    biliPollTimer = setInterval(pollBiliStatus, 2000)
  } catch {
    biliAuthStatus.value = 'error'
  }
}

async function pollBiliStatus() {
  if (!biliQrcodeKey.value) return
  try {
    const res = await pollBilibiliQrcode(biliQrcodeKey.value)
    if (res.code !== 0) return
    const status = res.data.status
    if (status === 'waiting') {
      biliAuthStatus.value = 'waiting'
    } else if (status === 'scanned') {
      biliAuthStatus.value = 'scanned'
    } else if (status === 'expired') {
      biliAuthStatus.value = 'expired'
      clearBiliPoll()
    } else if (status === 'success') {
      biliAuthStatus.value = 'success'
      clearBiliPoll()
      await loadCredentials()
    }
  } catch { /* ignore poll errors */ }
}

function clearBiliPoll() {
  if (biliPollTimer) {
    clearInterval(biliPollTimer)
    biliPollTimer = null
  }
}

function resetBiliAuth() {
  clearBiliPoll()
  biliAuthStatus.value = 'idle'
  biliQrcodeKey.value = ''
}

// Twitter 凭证
const twitterAuthToken = ref('')
const twitterSaving = ref(false)
const twitterSaveResult = ref(null)

async function handleSaveTwitter() {
  const token = twitterAuthToken.value.trim()
  if (!token) return
  twitterSaving.value = true
  twitterSaveResult.value = null
  try {
    const res = await createCredential({
      platform: 'twitter',
      credential_type: 'auth_token',
      credential_data: token,
      display_name: 'Twitter 账号',
    })
    if (res.code === 0) {
      twitterSaveResult.value = { success: true, message: '凭证已保存并同步至 RSSHub' }
      twitterAuthToken.value = ''
      await loadCredentials()
    } else {
      twitterSaveResult.value = { success: false, message: res.message || '保存失败' }
    }
  } catch (e) {
    twitterSaveResult.value = { success: false, message: '保存失败: ' + (e.message || '网络错误') }
  } finally {
    twitterSaving.value = false
  }
}

const statusBadge = (status) => {
  switch (status) {
    case 'active': return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    case 'expired': return 'bg-amber-50 text-amber-700 border-amber-200'
    case 'error': return 'bg-rose-50 text-rose-700 border-rose-200'
    default: return 'bg-slate-50 text-slate-600 border-slate-200'
  }
}

const statusLabel = (status) => {
  switch (status) {
    case 'active': return '有效'
    case 'expired': return '已过期'
    case 'error': return '异常'
    default: return status
  }
}

onMounted(async () => {
  try {
    const [settingsRes] = await Promise.all([
      getSettings(),
      loadCredentials(),
    ])
    if (settingsRes.code === 0) {
      const flat = {}
      for (const [k, v] of Object.entries(settingsRes.data)) {
        flat[k] = v.value || ''
      }
      form.value = flat
      originalForm.value = { ...flat }
      selectedProvider.value = detectProvider(flat.llm_base_url)
    }
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  clearBiliPoll()
})

async function handleTestLLM() {
  const key = form.value.llm_api_key
  if (!key) {
    testResult.value = { success: false, message: '请先填写 API Key' }
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const res = await testLLMConnection({
      api_key: key,
      base_url: form.value.llm_base_url,
      model: form.value.llm_model,
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
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tab 栏 -->
    <div class="bg-white shrink-0">
      <div class="border-b border-slate-100 px-4 pt-3 pb-0">
        <div class="flex items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200 whitespace-nowrap"
            :class="activeTab === tab.id
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'"
            @click="switchTab(tab.id)"
          >
            {{ tab.label }}
            <span v-if="isDirty[tab.id]" class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 ml-1 align-middle" />
          </button>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- 设置分组 Tab -->
    <div v-else-if="activeGroup" :key="activeGroup.id" class="flex-1 overflow-y-auto">
      <div class="px-4 py-4 max-w-3xl">
        <!-- 分组标题 -->
        <div class="flex items-center gap-3 mb-5">
          <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="activeGroup.color">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="activeGroup.icon" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-slate-800">{{ activeGroup.title }}</h3>
        </div>

        <div class="space-y-5">
          <!-- Provider 快速选择 -->
          <div v-if="activeGroup.hasProviderSelect">
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
          <div v-for="item in activeGroup.keys" :key="item.key">
            <label class="block text-sm font-medium text-slate-700 mb-1.5">{{ item.label }}</label>
            <div class="relative">
              <input
                v-model="form[item.key]"
                :type="item.type === 'password' && !visiblePasswords[item.key] ? 'password' : 'text'"
                :placeholder="item.description"
                class="w-full px-3.5 py-2.5 bg-white border rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 outline-none transition-all duration-200"
                :class="[
                  fieldErrors[item.key]
                    ? 'border-rose-300 focus:ring-rose-500/20 focus:border-rose-400'
                    : 'border-slate-200 focus:ring-indigo-500/20 focus:border-indigo-400',
                  item.type === 'password' ? 'pr-10' : ''
                ]"
                @blur="validateField(item.key, item.type)"
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
          <div v-if="activeGroup.id === 'llm'" class="pt-2 border-t border-slate-100">
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
            :class="isDirty[activeGroup.id]
              ? 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 shadow-indigo-200'
              : 'bg-slate-300 cursor-not-allowed'"
            :disabled="groupSaving[activeGroup.id] || !isDirty[activeGroup.id]"
            @click="saveGroup(activeGroup.id)"
          >
            <span class="flex items-center gap-1.5">
              <svg v-if="groupSaving[activeGroup.id]" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              {{ groupSaving[activeGroup.id] ? '保存中...' : `保存${activeGroup.title}` }}
            </span>
          </button>
        </div>

        <!-- 手动清理区域 (仅 retention tab) -->
        <div v-if="activeGroup.id === 'retention'" class="mt-6 pt-5 border-t border-slate-100">
          <h4 class="text-sm font-semibold text-slate-700 mb-1">手动清理</h4>
          <p class="text-xs text-slate-400 mb-4">立即清理已完成/失败的历史记录，不影响正在运行的任务</p>
          <div class="flex flex-wrap gap-3">
            <button
              class="px-4 py-2.5 text-sm font-medium text-rose-600 bg-white border border-rose-200 rounded-xl hover:bg-rose-50 hover:border-rose-300 active:bg-rose-100 disabled:opacity-50 transition-all duration-200"
              :disabled="clearingExecutions"
              @click="handleClearExecutions"
            >
              <span class="flex items-center gap-1.5">
                <svg v-if="clearingExecutions" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
                {{ clearingExecutions ? '清理中...' : '清理执行记录' }}
              </span>
            </button>
            <button
              class="px-4 py-2.5 text-sm font-medium text-rose-600 bg-white border border-rose-200 rounded-xl hover:bg-rose-50 hover:border-rose-300 active:bg-rose-100 disabled:opacity-50 transition-all duration-200"
              :disabled="clearingCollections"
              @click="handleClearCollections"
            >
              <span class="flex items-center gap-1.5">
                <svg v-if="clearingCollections" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
                {{ clearingCollections ? '清理中...' : '清理采集记录' }}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 平台凭证 Tab ========== -->
    <div v-else-if="activeTab === 'credentials'" class="flex-1 overflow-y-auto">
        <div class="px-4 py-4 max-w-3xl">
          <!-- 添加凭证区域 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <!-- B站扫码 -->
            <div class="p-4 bg-white rounded-xl border border-slate-200/60 shadow-sm">
              <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2">
                  <div class="w-7 h-7 rounded-lg flex items-center justify-center bg-pink-50 text-pink-500">
                    <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M17.813 4.653h.854c1.51.054 2.769.578 3.773 1.574 1.004.995 1.524 2.249 1.56 3.76v7.36c-.036 1.51-.556 2.769-1.56 3.773s-2.262 1.524-3.773 1.56H5.333c-1.51-.036-2.769-.556-3.773-1.56S.036 18.858 0 17.347v-7.36c.036-1.511.556-2.765 1.56-3.76 1.004-.996 2.262-1.52 3.773-1.574h.774l-1.174-1.12a1.234 1.234 0 0 1-.373-.906c0-.356.124-.658.373-.907l.027-.027c.267-.249.573-.373.92-.373.347 0 .653.124.92.373L9.653 4.44c.071.071.134.142.187.213h4.267a.836.836 0 0 1 .16-.213l2.853-2.747c.267-.249.573-.373.92-.373.347 0 .662.151.929.4.267.249.391.551.391.907 0 .355-.124.657-.373.906zM5.333 7.24c-.746.018-1.373.276-1.88.773-.506.498-.769 1.13-.786 1.894v7.52c.017.764.28 1.395.786 1.893.507.498 1.134.756 1.88.773h13.334c.746-.017 1.373-.275 1.88-.773.506-.498.769-1.129.786-1.893v-7.52c-.017-.765-.28-1.396-.786-1.894-.507-.497-1.134-.755-1.88-.773zM8 11.107c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373zm8 0c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373z"/>
                    </svg>
                  </div>
                  <h4 class="text-sm font-semibold text-slate-700">B站凭证</h4>
                </div>
                <button
                  class="px-3 py-1.5 text-xs font-medium text-white bg-pink-500 rounded-lg hover:bg-pink-600 active:bg-pink-700 transition-all duration-200"
                  @click="startBiliAuth"
                >
                  扫码登录
                </button>
              </div>

              <!-- 扫码状态 -->
              <Transition
                enter-active-class="transition-all duration-300 ease-out"
                enter-from-class="opacity-0 -translate-y-2"
                enter-to-class="opacity-100 translate-y-0"
                leave-active-class="transition-all duration-200 ease-in"
                leave-from-class="opacity-100"
                leave-to-class="opacity-0"
              >
                <div v-if="biliAuthStatus !== 'idle'" class="mt-3 p-3 bg-slate-50 rounded-lg border border-slate-100">
                  <div v-if="biliAuthStatus === 'loading'" class="flex items-center gap-2 text-sm text-slate-500">
                    <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                    正在生成二维码...
                  </div>

                  <div v-else-if="biliAuthStatus === 'waiting' || biliAuthStatus === 'scanned'" class="flex flex-col items-center gap-3">
                    <canvas ref="qrcodeCanvas" class="rounded-lg border border-slate-200"></canvas>
                    <p class="text-sm font-medium" :class="biliAuthStatus === 'scanned' ? 'text-amber-600' : 'text-slate-600'">
                      {{ biliAuthStatus === 'scanned' ? '已扫码，请在手机上确认' : '请使用 B站 App 扫描二维码' }}
                    </p>
                    <div v-if="biliAuthStatus === 'waiting'" class="flex items-center gap-1.5 text-xs text-slate-400">
                      <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                      等待扫码中...
                    </div>
                    <button type="button" class="text-xs text-slate-400 hover:text-slate-600 transition-colors" @click="resetBiliAuth">取消</button>
                  </div>

                  <div v-else-if="biliAuthStatus === 'success'" class="flex items-center gap-2 text-sm text-emerald-600">
                    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                    凭证已保存
                    <button type="button" class="ml-2 text-xs text-slate-400 hover:text-slate-600 transition-colors" @click="resetBiliAuth">关闭</button>
                  </div>

                  <div v-else-if="biliAuthStatus === 'expired' || biliAuthStatus === 'error'" class="flex items-center gap-2 text-sm text-rose-600">
                    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
                    {{ biliAuthStatus === 'expired' ? '二维码已过期' : '生成失败' }}
                    <button type="button" class="ml-2 text-xs text-slate-500 hover:text-slate-700 underline transition-colors" @click="startBiliAuth">重试</button>
                    <button type="button" class="text-xs text-slate-400 hover:text-slate-600 transition-colors" @click="resetBiliAuth">关闭</button>
                  </div>
                </div>
              </Transition>
            </div>

            <!-- Twitter 凭证 -->
            <div class="p-4 bg-white rounded-xl border border-slate-200/60 shadow-sm">
              <div class="flex items-center gap-2 mb-3">
                <div class="w-7 h-7 rounded-lg flex items-center justify-center bg-sky-50 text-slate-800">
                  <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                  </svg>
                </div>
                <h4 class="text-sm font-semibold text-slate-700">Twitter 凭证</h4>
              </div>
              <div class="flex gap-2">
                <input
                  v-model="twitterAuthToken"
                  type="password"
                  placeholder="粘贴 auth_token 值"
                  class="flex-1 min-w-0 px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-sky-500/20 focus:border-sky-400 outline-none transition-all duration-200"
                />
                <button
                  class="px-3.5 py-2.5 text-sm font-medium text-white bg-slate-800 rounded-xl hover:bg-slate-900 active:bg-black disabled:opacity-50 transition-all duration-200 whitespace-nowrap"
                  :disabled="twitterSaving || !twitterAuthToken.trim()"
                  @click="handleSaveTwitter"
                >
                  {{ twitterSaving ? '保存中...' : '保存' }}
                </button>
              </div>
              <p class="mt-2 text-xs text-slate-400">
                获取方式：登录 x.com → F12 → Application → Cookies → 复制 <code class="px-1 py-0.5 bg-slate-100 rounded text-slate-500">auth_token</code>
              </p>
              <Transition
                enter-active-class="transition-all duration-300 ease-out"
                enter-from-class="opacity-0 translate-y-1"
                enter-to-class="opacity-100 translate-y-0"
                leave-active-class="transition-all duration-200 ease-in"
                leave-from-class="opacity-100"
                leave-to-class="opacity-0"
              >
                <p v-if="twitterSaveResult" class="mt-2 text-sm flex items-center gap-1.5"
                   :class="twitterSaveResult.success ? 'text-emerald-600' : 'text-rose-600'">
                  <svg v-if="twitterSaveResult.success" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                  </svg>
                  {{ twitterSaveResult.message }}
                </p>
              </Transition>
            </div>
          </div>

          <!-- 凭证列表 -->
          <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
            <div class="px-5 py-3 bg-slate-50/50 border-b border-slate-100">
              <h4 class="text-sm font-semibold text-slate-700">已保存的凭证</h4>
            </div>

            <div v-if="credLoading" class="flex items-center justify-center py-8">
              <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
            </div>

            <div v-else-if="credentials.length === 0" class="text-center py-8">
              <p class="text-sm text-slate-400">暂无凭证，使用上方操作添加</p>
            </div>

            <div v-else class="divide-y divide-slate-100">
              <div
                v-for="cred in credentials"
                :key="cred.id"
                class="flex items-center justify-between p-4 hover:bg-slate-50/50 transition-colors"
              >
                <div class="flex items-center gap-3 min-w-0">
                  <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                       :class="cred.platform === 'bilibili' ? 'bg-pink-50 text-pink-500' : cred.platform === 'twitter' ? 'bg-sky-50 text-slate-800' : 'bg-slate-100 text-slate-500'">
                    <svg v-if="cred.platform === 'bilibili'" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M17.813 4.653h.854c1.51.054 2.769.578 3.773 1.574 1.004.995 1.524 2.249 1.56 3.76v7.36c-.036 1.51-.556 2.769-1.56 3.773s-2.262 1.524-3.773 1.56H5.333c-1.51-.036-2.769-.556-3.773-1.56S.036 18.858 0 17.347v-7.36c.036-1.511.556-2.765 1.56-3.76 1.004-.996 2.262-1.52 3.773-1.574h.774l-1.174-1.12a1.234 1.234 0 0 1-.373-.906c0-.356.124-.658.373-.907l.027-.027c.267-.249.573-.373.92-.373.347 0 .653.124.92.373L9.653 4.44c.071.071.134.142.187.213h4.267a.836.836 0 0 1 .16-.213l2.853-2.747c.267-.249.573-.373.92-.373.347 0 .662.151.929.4.267.249.391.551.391.907 0 .355-.124.657-.373.906zM5.333 7.24c-.746.018-1.373.276-1.88.773-.506.498-.769 1.13-.786 1.894v7.52c.017.764.28 1.395.786 1.893.507.498 1.134.756 1.88.773h13.334c.746-.017 1.373-.275 1.88-.773.506-.498.769-1.129.786-1.893v-7.52c-.017-.765-.28-1.396-.786-1.894-.507-.497-1.134-.755-1.88-.773zM8 11.107c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373zm8 0c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373z"/>
                    </svg>
                    <svg v-else-if="cred.platform === 'twitter'" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                    </svg>
                    <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
                    </svg>
                  </div>
                  <div class="min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-slate-800 truncate">{{ cred.display_name }}</span>
                      <span class="px-1.5 py-0.5 text-xs font-medium rounded border" :class="statusBadge(cred.status)">
                        {{ statusLabel(cred.status) }}
                      </span>
                    </div>
                    <p class="text-xs text-slate-400 mt-0.5">
                      {{ cred.platform }} &middot; {{ cred.credential_data }} &middot;
                      {{ cred.source_count }} 个数据源引用
                    </p>
                  </div>
                </div>

                <div class="flex items-center gap-1.5 shrink-0 ml-3 flex-wrap">
                  <button
                    v-if="['bilibili', 'twitter'].includes(cred.platform)"
                    class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 transition-all duration-200"
                    :disabled="!!credActionLoading[cred.id]"
                    @click="handleCheckCredential(cred.id)"
                  >
                    {{ credActionLoading[cred.id] === 'checking' ? '检测中...' : '检测' }}
                  </button>
                  <button
                    v-if="['bilibili', 'twitter'].includes(cred.platform)"
                    class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 transition-all duration-200"
                    :disabled="!!credActionLoading[cred.id]"
                    @click="handleSyncRsshub(cred.id)"
                  >
                    {{ credActionLoading[cred.id] === 'syncing' ? '同步中...' : '同步 RSSHub' }}
                  </button>
                  <button
                    class="px-2.5 py-1.5 text-xs font-medium text-rose-600 bg-white border border-rose-200 rounded-lg hover:bg-rose-50 hover:border-rose-300 disabled:opacity-50 transition-all duration-200"
                    :disabled="!!credActionLoading[cred.id]"
                    @click="handleDeleteCredential(cred.id)"
                  >
                    {{ credActionLoading[cred.id] === 'deleting' ? '删除中...' : '删除' }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
    </div>

    <!-- ========== 确认对话框 ========== -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-all duration-200 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-all duration-150 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="confirmDialog.visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="closeConfirm" />
          <div class="relative bg-white rounded-2xl shadow-xl max-w-sm w-full p-6">
            <div class="flex items-center gap-3 mb-3">
              <div class="w-10 h-10 rounded-full bg-rose-50 flex items-center justify-center shrink-0">
                <svg class="w-5 h-5 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </div>
              <h3 class="text-base font-semibold text-slate-800">{{ confirmDialog.title }}</h3>
            </div>
            <p class="text-sm text-slate-500 leading-relaxed mb-5 pl-[52px]">{{ confirmDialog.message }}</p>
            <div class="flex justify-end gap-2">
              <button
                class="px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
                @click="closeConfirm"
              >
                取消
              </button>
              <button
                class="px-4 py-2 text-sm font-medium text-white bg-rose-500 rounded-xl hover:bg-rose-600 active:bg-rose-700 shadow-sm transition-all duration-200"
                @click="confirmDialog.onConfirm?.()"
              >
                确认清理
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>


