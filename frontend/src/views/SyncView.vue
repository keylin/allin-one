<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { getSyncStatus, setupEbookSync, setupVideoSync, triggerSync, linkCredential, streamSyncProgress } from '@/api/sync'
import { listCredentials } from '@/api/credentials'
import { formatTimeShort } from '@/utils/time'
import { useToast } from '@/composables/useToast'

const { success, error: showError } = useToast()

const loading = ref(false)
const plugins = ref([])

// 同步进度状态: { [source_type]: { progressId, status, phase, message, current, total, controller } }
const syncStates = ref({})

// 凭证选项: { [platform]: [{id, display_name, status}] }
const credentialOptions = ref({})
// 凭证选择: { [source_type]: selectedCredentialId }
const selectedCredentials = ref({})

// 换绑凭证状态: { [source_type]: true }
const rebindingType = ref({})

// B站同步选项
const bilibiliOptions = ref({ sync_type: 'favorites', media_id: '' })
// 显示B站选项面板
const showBilibiliPanel = ref(false)

const PLUGIN_META = {
  'sync.apple_books': {
    color: 'slate',
    platform: 'apple_books',
    setupFn: () => setupEbookSync('sync.apple_books'),
    commands: (apiUrl) => [
      `python scripts/apple-books-sync.py --api-url ${apiUrl}`,
    ],
  },
  'sync.wechat_read': {
    color: 'emerald',
    platform: 'wechat_read',
    setupFn: () => setupEbookSync('sync.wechat_read'),
    commands: (apiUrl) => [
      `python scripts/wechat-read-sync.py --api-url ${apiUrl} --cookie "YOUR_COOKIE"`,
    ],
  },
  'sync.bilibili': {
    color: 'pink',
    platform: 'bilibili',
    setupFn: () => setupVideoSync('sync.bilibili'),
    commands: (apiUrl) => [
      `python scripts/bilibili-sync.py --api-url ${apiUrl} --cookie "SESSDATA=xxx" --type favorites --media-id YOUR_ID`,
      `python scripts/bilibili-sync.py --api-url ${apiUrl} --cookie "SESSDATA=xxx" --type history`,
    ],
  },
}

const apiUrl = window.location.origin

// 折叠状态 per plugin
const expandedCommands = ref({})

function toggleCommands(sourceType) {
  expandedCommands.value[sourceType] = !expandedCommands.value[sourceType]
}

async function fetchStatus() {
  loading.value = true
  try {
    const res = await getSyncStatus()
    if (res.code === 0) {
      plugins.value = res.data.plugins
      // script 模式插件自动展开脚本命令
      for (const p of res.data.plugins) {
        if (p.sync_mode === 'script' && p.configured) {
          expandedCommands.value[p.source_type] = true
        }
      }
    }
  } finally {
    loading.value = false
  }
}

async function fetchCredentials() {
  try {
    const res = await listCredentials()
    if (res.code === 0) {
      // 按 platform 分组
      const grouped = {}
      for (const cred of res.data) {
        const platform = cred.platform
        if (!grouped[platform]) grouped[platform] = []
        grouped[platform].push(cred)
      }
      credentialOptions.value = grouped
    }
  } catch {
    // silently fail
  }
}

async function handleSetup(plugin) {
  const meta = PLUGIN_META[plugin.source_type]
  if (!meta) return
  try {
    const res = await meta.setupFn()
    if (res.code === 0) {
      success(`${plugin.name} 同步源已初始化`)
      await fetchStatus()
    } else {
      showError(res.message || '初始化失败')
    }
  } catch {
    showError('初始化失败')
  }
}

async function handleLinkCredential(plugin) {
  const credId = selectedCredentials.value[plugin.source_type]
  if (!credId) {
    showError('请选择凭证')
    return
  }
  try {
    const res = await linkCredential(plugin.source_type, credId)
    if (res.code === 0) {
      success(res.message || '凭证已绑定')
      await fetchStatus()
    } else {
      showError(res.message || '绑定失败')
    }
  } catch {
    showError('绑定失败')
  }
}

async function handleRebindCredential(plugin) {
  const credId = selectedCredentials.value[plugin.source_type]
  if (!credId) {
    showError('请选择凭证')
    return
  }
  try {
    const res = await linkCredential(plugin.source_type, credId)
    if (res.code === 0) {
      success(res.message || '凭证已换绑')
      rebindingType.value[plugin.source_type] = false
      await fetchStatus()
      await fetchCredentials()
    } else {
      showError(res.message || '换绑失败')
    }
  } catch {
    showError('换绑失败')
  }
}

function canSync(plugin) {
  // script 模式不支持在线同步
  if (plugin.sync_mode === 'script') return false
  const needsCredential = plugin.credential_required !== false
  const credentialOk = !needsCredential || (plugin.credential_id && plugin.credential_status === 'active')
  return plugin.configured
    && credentialOk
    && !plugin.is_syncing
    && !syncStates.value[plugin.source_type]
}

async function handleSync(plugin) {
  // B站需要选项面板
  if (plugin.source_type === 'sync.bilibili') {
    showBilibiliPanel.value = true
    return
  }
  // 其他平台直接同步
  await doSync(plugin.source_type, {})
}

async function confirmBilibiliSync() {
  showBilibiliPanel.value = false
  const opts = { ...bilibiliOptions.value }
  await doSync('sync.bilibili', opts)
}

async function doSync(sourceType, options) {
  try {
    const res = await triggerSync(sourceType, options)
    if (res.code !== 0) {
      showError(res.message || '触发同步失败')
      return
    }

    const { progress_id } = res.data

    // 初始化进度状态
    syncStates.value[sourceType] = {
      progressId: progress_id,
      status: 'pending',
      phase: '',
      message: '正在排队...',
      current: 0,
      total: 0,
      controller: null,
    }

    // 开启 SSE
    const controller = streamSyncProgress(
      progress_id,
      // onUpdate
      (event) => {
        const state = syncStates.value[sourceType]
        if (state) {
          state.status = event.status
          state.phase = event.phase
          state.message = event.message
          state.current = event.current
          state.total = event.total
        }
      },
      // onDone
      (event) => {
        const state = syncStates.value[sourceType]
        if (event && event.status === 'failed') {
          showError(event.error_message || '同步失败')
        } else if (event && event.result_data) {
          const r = event.result_data
          const parts = []
          if (r.new_videos) parts.push(`新增 ${r.new_videos} 条视频`)
          if (r.updated_videos) parts.push(`更新 ${r.updated_videos} 条`)
          if (r.new_books) parts.push(`新增 ${r.new_books} 本`)
          if (r.updated_books) parts.push(`更新 ${r.updated_books} 本`)
          if (r.new_annotations) parts.push(`新增 ${r.new_annotations} 条标注`)
          success(`同步完成: ${parts.join(', ') || '无新增数据'}`)
        } else {
          success('同步完成')
        }
        // 清除状态并刷新
        delete syncStates.value[sourceType]
        fetchStatus()
      },
      // onError
      (msg) => {
        showError(`同步错误: ${msg}`)
        delete syncStates.value[sourceType]
        fetchStatus()
      },
    )

    syncStates.value[sourceType].controller = controller
  } catch {
    showError('触发同步失败')
  }
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    success('已复制到剪贴板')
  } catch {
    showError('复制失败')
  }
}

function copySourceId(id) {
  copyToClipboard(id)
}

function getStatusLabel(plugin) {
  if (syncStates.value[plugin.source_type]) return '同步中'
  if (plugin.is_syncing) return '同步中'
  if (!plugin.configured) return '未配置'
  if (!plugin.last_sync_at) return '待同步'
  return '已同步'
}

function getStatusClass(plugin) {
  if (syncStates.value[plugin.source_type] || plugin.is_syncing) return 'bg-blue-50 text-blue-600'
  if (!plugin.configured) return 'bg-slate-100 text-slate-500'
  if (!plugin.last_sync_at) return 'bg-amber-50 text-amber-600'
  return 'bg-emerald-50 text-emerald-600'
}

function getCardBorder(plugin) {
  if (syncStates.value[plugin.source_type] || plugin.is_syncing) return 'border-blue-200'
  if (!plugin.configured) return 'border-dashed border-slate-200'
  if (!plugin.last_sync_at) return 'border-slate-200'
  return 'border-indigo-100'
}

function getIconColor(plugin) {
  if (!plugin.configured) return 'text-slate-300'
  const meta = PLUGIN_META[plugin.source_type]
  const colorMap = {
    slate: 'text-slate-600',
    emerald: 'text-emerald-600',
    pink: 'text-pink-500',
  }
  return colorMap[meta?.color] || 'text-slate-600'
}

function getCredentialStatusLabel(status) {
  const map = { active: '有效', expired: '过期', error: '异常' }
  return map[status] || status
}

function getCredentialStatusClass(status) {
  const map = {
    active: 'bg-emerald-50 text-emerald-600',
    expired: 'bg-red-50 text-red-600',
    error: 'bg-amber-50 text-amber-600',
  }
  return map[status] || 'bg-slate-100 text-slate-500'
}

function getAvailableCredentials(plugin) {
  const meta = PLUGIN_META[plugin.source_type]
  if (!meta) return []
  return credentialOptions.value[meta.platform] || []
}

function getProgressPercent(state) {
  if (!state || !state.total) return 0
  return Math.round((state.current / state.total) * 100)
}

onMounted(() => {
  fetchStatus()
  fetchCredentials()
})

// 清理 SSE 连接
onUnmounted(() => {
  for (const state of Object.values(syncStates.value)) {
    if (state.controller) {
      state.controller.abort()
    }
  }
})
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="max-w-2xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <!-- Header -->
      <div class="mb-6">
        <h1 class="text-xl font-bold tracking-tight text-gray-900">同步管理</h1>
        <p class="mt-1 text-sm text-gray-500">管理外部平台数据同步，绑定凭证一键同步</p>
      </div>

      <!-- Loading -->
      <div v-if="loading && !plugins.length" class="flex items-center justify-center py-20">
        <div class="w-6 h-6 border-2 border-indigo-200 border-t-indigo-500 rounded-full animate-spin"></div>
      </div>

      <!-- Card List -->
      <div v-else class="space-y-2">
        <div
          v-for="plugin in plugins"
          :key="plugin.source_type"
          class="bg-white rounded-xl border px-4 py-3 transition-all duration-200 hover:shadow-sm"
          :class="getCardBorder(plugin)"
        >
          <!-- Row 1: Icon + Name + Tags + Status -->
          <div class="flex items-center justify-between gap-3">
            <div class="flex items-center gap-3 min-w-0">
              <!-- Platform Icon -->
              <div
                class="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                :class="plugin.configured ? 'bg-slate-50' : 'bg-slate-50/50'"
              >
                <svg v-if="plugin.source_type === 'sync.apple_books'" class="w-[18px] h-[18px]" :class="getIconColor(plugin)" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                <svg v-else-if="plugin.source_type === 'sync.wechat_read'" class="w-[18px] h-[18px]" :class="getIconColor(plugin)" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                <svg v-else-if="plugin.source_type === 'sync.bilibili'" class="w-[18px] h-[18px]" :class="getIconColor(plugin)" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.91 11.672a.375.375 0 010 .656l-5.603 3.113a.375.375 0 01-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112z" />
                </svg>
              </div>
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <h3 class="font-semibold text-sm text-gray-900">{{ plugin.name }}</h3>
                  <span class="px-1.5 py-0.5 rounded text-[10px] font-medium" :class="plugin.category === 'ebook' ? 'bg-indigo-50 text-indigo-400' : 'bg-pink-50 text-pink-400'">
                    {{ plugin.category === 'ebook' ? '电子书' : '视频' }}
                  </span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-50 text-slate-400">
                    {{ plugin.sync_mode === 'script' ? '脚本' : '在线' }}
                  </span>
                </div>
                <p class="text-xs text-gray-400 mt-0.5 truncate">{{ plugin.description }}</p>
              </div>
            </div>
            <!-- Status Badge -->
            <span
              class="px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0"
              :class="getStatusClass(plugin)"
            >
              {{ getStatusLabel(plugin) }}
            </span>
          </div>

          <!-- Row 2: Stats inline (configured + has synced) -->
          <div v-if="plugin.configured && plugin.last_sync_at && !syncStates[plugin.source_type]" class="mt-2 flex items-center gap-3 text-xs text-gray-400">
            <span class="flex items-center gap-1">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
              </svg>
              <span class="text-gray-500">{{ plugin.stats.total_items || 0 }} 条目</span>
            </span>
            <span v-if="plugin.stats.total_annotations != null" class="flex items-center gap-1">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
              </svg>
              <span class="text-gray-500">{{ plugin.stats.total_annotations }} 标注</span>
            </span>
            <span class="text-gray-300">·</span>
            <span>{{ formatTimeShort(plugin.last_sync_at) }}</span>
          </div>

          <!-- Row 2 alt: Progress Bar (syncing) -->
          <div v-if="syncStates[plugin.source_type]" class="mt-2">
            <div class="flex items-center gap-2 mb-1.5">
              <div class="w-3.5 h-3.5 border-2 border-indigo-200 border-t-indigo-500 rounded-full animate-spin flex-shrink-0"></div>
              <span class="text-xs text-gray-600 truncate flex-1">{{ syncStates[plugin.source_type].message || '同步中...' }}</span>
              <span v-if="syncStates[plugin.source_type].total > 0" class="text-xs text-gray-400 flex-shrink-0">
                {{ syncStates[plugin.source_type].current }} / {{ syncStates[plugin.source_type].total }}
              </span>
            </div>
            <div v-if="syncStates[plugin.source_type].total > 0" class="w-full bg-slate-100 rounded-full h-1.5">
              <div
                class="bg-indigo-500 h-1.5 rounded-full transition-all duration-300"
                :style="{ width: getProgressPercent(syncStates[plugin.source_type]) + '%' }"
              ></div>
            </div>
          </div>

          <!-- Row 2 alt: Waiting hint (configured but never synced) -->
          <div v-if="plugin.configured && !plugin.last_sync_at && !syncStates[plugin.source_type]" class="mt-1.5">
            <p class="text-xs text-amber-500">{{ plugin.sync_mode === 'script' ? '请在本机运行脚本完成首次同步' : (plugin.credential_required === false || plugin.credential_id) ? '点击「立即同步」开始首次同步' : '绑定凭证后开始同步' }}</p>
          </div>

          <!-- Row 3: Credential + Actions -->
          <div v-if="plugin.configured" class="mt-2 flex items-center justify-between gap-3">
            <!-- Left: Credential info -->
            <div class="flex items-center gap-2 min-w-0 flex-1">
              <!-- Credential bound -->
              <template v-if="plugin.credential_required !== false && plugin.credential_id && !rebindingType[plugin.source_type]">
                <svg class="w-3.5 h-3.5 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
                </svg>
                <span class="text-xs text-gray-500 truncate">{{ plugin.credential_name }}</span>
                <span
                  class="px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0"
                  :class="getCredentialStatusClass(plugin.credential_status)"
                >
                  {{ getCredentialStatusLabel(plugin.credential_status) }}
                </span>
                <button
                  class="text-xs text-gray-400 hover:text-indigo-500 transition-colors flex-shrink-0"
                  @click="rebindingType[plugin.source_type] = true"
                >
                  换绑
                </button>
              </template>
              <!-- Rebinding: inline select (same as unbound) -->
              <template v-else-if="plugin.credential_required !== false && plugin.credential_id && rebindingType[plugin.source_type]">
                <select
                  v-model="selectedCredentials[plugin.source_type]"
                  class="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300 max-w-[180px]"
                >
                  <option value="" disabled selected>选择凭证</option>
                  <option
                    v-for="cred in getAvailableCredentials(plugin)"
                    :key="cred.id"
                    :value="cred.id"
                  >
                    {{ cred.display_name }} ({{ cred.status === 'active' ? '有效' : '过期' }})
                  </option>
                </select>
                <button
                  class="px-2 py-1 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors flex-shrink-0"
                  @click="handleRebindCredential(plugin)"
                >
                  绑定
                </button>
                <button
                  class="text-xs text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
                  @click="rebindingType[plugin.source_type] = false"
                >
                  取消
                </button>
              </template>
              <!-- Credential not bound: inline select -->
              <template v-else-if="plugin.credential_required !== false && !plugin.credential_id">
                <select
                  v-model="selectedCredentials[plugin.source_type]"
                  class="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300 max-w-[180px]"
                >
                  <option value="" disabled selected>选择凭证</option>
                  <option
                    v-for="cred in getAvailableCredentials(plugin)"
                    :key="cred.id"
                    :value="cred.id"
                  >
                    {{ cred.display_name }} ({{ cred.status === 'active' ? '有效' : '过期' }})
                  </option>
                </select>
                <button
                  class="px-2 py-1 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors flex-shrink-0"
                  @click="handleLinkCredential(plugin)"
                >
                  绑定
                </button>
                <router-link
                  to="/settings?tab=credentials"
                  class="text-gray-300 hover:text-gray-500 flex-shrink-0"
                  title="新建凭证"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                </router-link>
              </template>
            </div>
            <!-- Right: Action buttons -->
            <div class="flex items-center gap-2 flex-shrink-0">
              <button
                v-if="canSync(plugin)"
                class="px-3 py-1 text-xs font-medium text-white bg-indigo-500 hover:bg-indigo-600 rounded-lg transition-colors flex items-center gap-1.5"
                @click="handleSync(plugin)"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                </svg>
                立即同步
              </button>
              <span
                v-if="syncStates[plugin.source_type] || plugin.is_syncing"
                class="px-3 py-1 text-xs font-medium text-blue-500 bg-blue-50 rounded-lg flex items-center gap-1.5"
              >
                <div class="w-3 h-3 border-2 border-blue-200 border-t-blue-500 rounded-full animate-spin"></div>
                同步中
              </span>
              <router-link
                v-if="!plugin.credential_id && plugin.credential_required !== false"
                to="/settings?tab=credentials"
                class="px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 bg-slate-50 hover:bg-slate-100 rounded-lg transition-colors"
              >
                配置凭证
              </router-link>
            </div>
          </div>

          <!-- Not configured: Setup action -->
          <div v-if="!plugin.configured" class="mt-2">
            <button
              class="px-3 py-1 text-xs font-medium text-white bg-indigo-500 hover:bg-indigo-600 rounded-lg transition-colors"
              @click="handleSetup(plugin)"
            >
              初始化
            </button>
          </div>

          <!-- Collapsible: Developer info (Source ID + Script commands) -->
          <div v-if="plugin.configured && PLUGIN_META[plugin.source_type]" class="mt-2">
            <button
              class="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
              @click="toggleCommands(plugin.source_type)"
            >
              <svg
                class="w-3 h-3 transition-transform duration-200"
                :class="expandedCommands[plugin.source_type] ? 'rotate-90' : ''"
                fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
              </svg>
              <span>开发者信息</span>
            </button>
            <Transition
              enter-active-class="transition-all duration-200 ease-out"
              enter-from-class="opacity-0 max-h-0"
              enter-to-class="opacity-100 max-h-[32rem]"
              leave-active-class="transition-all duration-150 ease-in"
              leave-from-class="opacity-100 max-h-[32rem]"
              leave-to-class="opacity-0 max-h-0"
            >
              <div v-if="expandedCommands[plugin.source_type]" class="overflow-hidden mt-2 space-y-2">
                <!-- Source ID -->
                <div class="flex items-center gap-2">
                  <span class="text-xs text-gray-400">Source ID:</span>
                  <code class="text-xs bg-slate-50 text-slate-600 px-1.5 py-0.5 rounded font-mono select-all">{{ plugin.source_id }}</code>
                  <button
                    class="text-gray-300 hover:text-gray-500 transition-colors"
                    title="复制 Source ID"
                    @click="copySourceId(plugin.source_id)"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                    </svg>
                  </button>
                </div>
                <!-- Script commands -->
                <div
                  v-for="(cmd, idx) in PLUGIN_META[plugin.source_type].commands(apiUrl)"
                  :key="idx"
                  class="group relative"
                >
                  <pre class="text-xs bg-slate-50 border border-slate-100 rounded-lg p-3 pr-8 overflow-x-auto text-slate-600 font-mono whitespace-pre-wrap break-all leading-relaxed">{{ cmd }}</pre>
                  <button
                    class="absolute top-2 right-2 p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-white transition-all opacity-0 group-hover:opacity-100"
                    title="复制命令"
                    @click="copyToClipboard(cmd)"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                    </svg>
                  </button>
                </div>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="!loading && !plugins.length" class="text-center py-20 text-gray-400 text-sm">
        暂无同步插件
      </div>

      <!-- Bilibili Options Modal -->
      <Teleport to="body">
        <Transition
          enter-active-class="transition-opacity duration-200"
          enter-from-class="opacity-0"
          enter-to-class="opacity-100"
          leave-active-class="transition-opacity duration-150"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div v-if="showBilibiliPanel" class="fixed inset-0 z-50 flex items-center justify-center">
            <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="showBilibiliPanel = false"></div>
            <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-sm mx-4">
              <h3 class="font-semibold text-sm text-gray-900 mb-4">B站同步选项</h3>
              <div class="mb-4">
                <label class="block text-xs text-gray-500 mb-1.5">同步类型</label>
                <select
                  v-model="bilibiliOptions.sync_type"
                  class="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                >
                  <option value="favorites">收藏夹</option>
                  <option value="history">历史记录</option>
                  <option value="dynamic">动态</option>
                </select>
              </div>
              <div v-if="bilibiliOptions.sync_type === 'favorites'" class="mb-4">
                <label class="block text-xs text-gray-500 mb-1.5">收藏夹 ID</label>
                <input
                  v-model="bilibiliOptions.media_id"
                  type="text"
                  placeholder="输入收藏夹 media_id"
                  class="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                />
                <p class="mt-1 text-xs text-gray-400">在收藏夹页面 URL 中获取 fid 参数</p>
              </div>
              <div class="flex justify-end gap-2">
                <button
                  class="px-4 py-2 text-xs font-medium text-gray-500 hover:text-gray-700 bg-slate-50 hover:bg-slate-100 rounded-lg transition-colors"
                  @click="showBilibiliPanel = false"
                >
                  取消
                </button>
                <button
                  class="px-4 py-2 text-xs font-medium text-white bg-indigo-500 hover:bg-indigo-600 rounded-lg transition-colors"
                  :disabled="bilibiliOptions.sync_type === 'favorites' && !bilibiliOptions.media_id"
                  @click="confirmBilibiliSync"
                >
                  开始同步
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </Teleport>
    </div>
  </div>
</template>
