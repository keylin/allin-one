<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSettings, updateSettings } from '@/api/settings'
import { useToast } from '@/composables/useToast'

import LlmSettings from '@/components/settings/llm-settings.vue'
import NotificationSettings from '@/components/settings/notification-settings.vue'
import RetentionSettings from '@/components/settings/retention-settings.vue'
import SchedulingSettings from '@/components/settings/scheduling-settings.vue'
import CredentialSettings from '@/components/settings/credential-settings.vue'

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
  { id: 'scheduling', label: '智能调度' },
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

// ---- Settings form ----
const form = ref({})
const originalForm = ref({})

// 字段级错误
const fieldErrors = ref({})

// 分组保存状态
const groupSaving = ref({})

// 设置分组定义（用于验证和保存逻辑）
const groups = [
  {
    id: 'llm',
    title: 'LLM 配置',
    keys: [
      { key: 'llm_api_key', label: 'API Key', type: 'password' },
      { key: 'llm_base_url', label: 'Base URL', type: 'url' },
      { key: 'llm_model', label: '模型', type: 'text' },
    ],
  },
  {
    id: 'smtp',
    title: '邮件推送 (SMTP)',
    keys: [
      { key: 'smtp_host', type: 'text' },
      { key: 'smtp_port', type: 'text' },
      { key: 'smtp_user', type: 'text' },
      { key: 'smtp_password', type: 'password' },
      { key: 'notify_email', type: 'email' },
    ],
  },
  {
    id: 'notify',
    title: '通知渠道',
    keys: [
      { key: 'notify_webhook', type: 'url' },
      { key: 'notify_dingtalk_webhook', type: 'url' },
    ],
  },
  {
    id: 'retention',
    title: '内容保留',
    keys: [
      { key: 'cleanup_content_time', type: 'time' },
      { key: 'cleanup_records_time', type: 'time' },
      { key: 'default_retention_days', type: 'number' },
      { key: 'collection_retention_days', type: 'number' },
      { key: 'collection_min_keep', type: 'number' },
      { key: 'execution_retention_days', type: 'number' },
      { key: 'execution_max_count', type: 'number' },
    ],
  },
  {
    id: 'scheduling',
    title: '智能调度',
    keys: [
      { key: 'schedule_min_interval', type: 'number' },
      { key: 'schedule_max_interval', type: 'number' },
      { key: 'schedule_base_interval', type: 'number' },
      { key: 'schedule_lookback_window', type: 'number' },
      { key: 'schedule_activity_high', type: 'number' },
      { key: 'schedule_activity_medium', type: 'number' },
      { key: 'schedule_activity_low', type: 'number' },
    ],
  },
]

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

  // ========== 智能调度参数专用验证 ==========
  if (type === 'number') {
    const num = parseFloat(value)

    if (key === 'schedule_min_interval' && num < 60) {
      fieldErrors.value[key] = '最小间隔不能低于 60 秒'
      return
    }

    if (key === 'schedule_max_interval') {
      const minInterval = parseFloat(form.value.schedule_min_interval || 300)
      if (num <= minInterval) {
        fieldErrors.value[key] = `最大间隔必须大于最小间隔（${minInterval} 秒）`
        return
      }
    }

    if (key === 'schedule_base_interval') {
      const minInterval = parseFloat(form.value.schedule_min_interval || 300)
      const maxInterval = parseFloat(form.value.schedule_max_interval || 86400)
      if (num < minInterval || num > maxInterval) {
        fieldErrors.value[key] = `基础间隔应在 ${minInterval}-${maxInterval} 秒之间`
        return
      }
    }

    if (key === 'schedule_lookback_window') {
      if (num < 3 || num > 50) {
        fieldErrors.value[key] = '历史窗口范围应在 3-50 之间'
        return
      }
      if (!Number.isInteger(num)) {
        fieldErrors.value[key] = '历史窗口必须为整数'
        return
      }
    }

    if (key.startsWith('schedule_activity_')) {
      if (num <= 0) {
        fieldErrors.value[key] = '活跃度阈值必须为正数'
        return
      }

      const high = parseFloat(form.value.schedule_activity_high || 5.0)
      const medium = parseFloat(form.value.schedule_activity_medium || 2.0)
      const low = parseFloat(form.value.schedule_activity_low || 0.5)

      if (key === 'schedule_activity_high' && num <= medium) {
        fieldErrors.value[key] = '高活跃阈值必须大于中活跃阈值'
        return
      }
      if (key === 'schedule_activity_medium') {
        if (num >= high) {
          fieldErrors.value[key] = '中活跃阈值必须小于高活跃阈值'
          return
        }
        if (num <= low) {
          fieldErrors.value[key] = '中活跃阈值必须大于低活跃阈值'
          return
        }
      }
      if (key === 'schedule_activity_low' && num >= medium) {
        fieldErrors.value[key] = '低活跃阈值必须小于中活跃阈值'
        return
      }
    }
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

// ---- Time conversion ----
function utcTimeToLocal(utcTime) {
  if (!utcTime) return ''
  try {
    const [h, m] = utcTime.split(':').map(Number)
    const utcDate = new Date()
    utcDate.setUTCHours(h, m, 0, 0)
    const localH = String(utcDate.getHours()).padStart(2, '0')
    const localM = String(utcDate.getMinutes()).padStart(2, '0')
    return `${localH}:${localM}`
  } catch {
    return ''
  }
}

function localTimeToUTC(localTime) {
  if (!localTime) return ''
  try {
    const [h, m] = localTime.split(':').map(Number)
    const localDate = new Date()
    localDate.setHours(h, m, 0, 0)
    const utcH = String(localDate.getUTCHours()).padStart(2, '0')
    const utcM = String(localDate.getUTCMinutes()).padStart(2, '0')
    return `${utcH}:${utcM}`
  } catch {
    return ''
  }
}

// ---- Save group ----
async function saveGroup(groupId) {
  const group = groups.find(g => g.id === groupId)
  const errors = validateGroup(group)
  if (Object.keys(errors).length) return

  groupSaving.value[groupId] = true
  try {
    const settings = {}
    for (const item of group.keys) {
      let value = form.value[item.key] || null
      if ((item.key === 'cleanup_content_time' || item.key === 'cleanup_records_time') && value) {
        value = localTimeToUTC(value)
      }
      if (value !== null && value !== undefined) {
        value = String(value)
      }
      settings[item.key] = value
    }
    const res = await updateSettings(settings)
    if (res.code === 0) {
      toast.success(`${group.title} 已保存`)
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

// ---- Handle form updates from child ----
function handleFormUpdate(updatedFields) {
  form.value = { ...form.value, ...updatedFields }
}

// ---- Refresh settings (called by retention after manual cleanup) ----
async function refreshSettings() {
  try {
    const settingsRes = await getSettings()
    if (settingsRes.code === 0) {
      const flat = {}
      for (const [k, v] of Object.entries(settingsRes.data)) {
        let value = v.value || ''
        if (k === 'cleanup_content_time' || k === 'cleanup_records_time') {
          value = utcTimeToLocal(value)
        }
        flat[k] = value
      }
      form.value = { ...form.value, ...flat }
      originalForm.value = { ...originalForm.value, ...flat }
    }
  } catch {
    // ignore refresh errors
  }
}

// ---- LLM settings ref ----
const llmSettingsRef = ref(null)

// ---- Load settings ----
onMounted(async () => {
  try {
    const settingsRes = await getSettings()
    if (settingsRes.code === 0) {
      const flat = {}
      for (const [k, v] of Object.entries(settingsRes.data)) {
        let value = v.value || ''
        if (k === 'cleanup_content_time' || k === 'cleanup_records_time') {
          value = utcTimeToLocal(value)
        }
        flat[k] = value
      }
      form.value = flat
      originalForm.value = { ...flat }
    }
  } finally {
    loading.value = false
    // After loading is false, the LLM tab renders — wait for nextTick to call initProvider
    await nextTick()
    if (llmSettingsRef.value && form.value.llm_base_url) {
      llmSettingsRef.value.initProvider(form.value.llm_base_url)
    }
  }
})
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

    <!-- Tab content -->
    <template v-else>
      <!-- LLM 配置 -->
      <div v-if="activeTab === 'llm'" class="flex-1 overflow-y-auto">
        <LlmSettings
          ref="llmSettingsRef"
          :form="form"
          :field-errors="fieldErrors"
          :is-dirty="isDirty.llm"
          :group-saving="!!groupSaving.llm"
          @update:form="handleFormUpdate"
          @validate-field="validateField"
          @save="saveGroup('llm')"
        />
      </div>

      <!-- 邮件推送 (SMTP) -->
      <div v-else-if="activeTab === 'smtp'" class="flex-1 overflow-y-auto">
        <NotificationSettings
          group-id="smtp"
          :form="form"
          :field-errors="fieldErrors"
          :is-dirty="isDirty.smtp"
          :group-saving="!!groupSaving.smtp"
          @update:form="handleFormUpdate"
          @validate-field="validateField"
          @save="saveGroup('smtp')"
        />
      </div>

      <!-- 通知渠道 -->
      <div v-else-if="activeTab === 'notify'" class="flex-1 overflow-y-auto">
        <NotificationSettings
          group-id="notify"
          :form="form"
          :field-errors="fieldErrors"
          :is-dirty="isDirty.notify"
          :group-saving="!!groupSaving.notify"
          @update:form="handleFormUpdate"
          @validate-field="validateField"
          @save="saveGroup('notify')"
        />
      </div>

      <!-- 内容保留 -->
      <div v-else-if="activeTab === 'retention'" class="flex-1 overflow-y-auto">
        <RetentionSettings
          :form="form"
          :field-errors="fieldErrors"
          :is-dirty="isDirty.retention"
          :group-saving="!!groupSaving.retention"
          @update:form="handleFormUpdate"
          @validate-field="validateField"
          @save="saveGroup('retention')"
          @refresh-settings="refreshSettings"
        />
      </div>

      <!-- 智能调度 -->
      <div v-else-if="activeTab === 'scheduling'" class="flex-1 overflow-y-auto">
        <SchedulingSettings
          :form="form"
          :field-errors="fieldErrors"
          :is-dirty="isDirty.scheduling"
          :group-saving="!!groupSaving.scheduling"
          @update:form="handleFormUpdate"
          @validate-field="validateField"
          @save="saveGroup('scheduling')"
        />
      </div>

      <!-- 平台凭证 -->
      <div v-else-if="activeTab === 'credentials'" class="flex-1 overflow-y-auto">
        <CredentialSettings />
      </div>
    </template>
  </div>
</template>
