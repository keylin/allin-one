<script setup>
import { ref, onMounted } from 'vue'
import { getSyncStatus, setupEbookSync, setupVideoSync } from '@/api/sync'
import { formatTimeShort } from '@/utils/time'
import { useToast } from '@/composables/useToast'

const { success, error: showError } = useToast()

const loading = ref(false)
const plugins = ref([])

const PLUGIN_META = {
  'sync.apple_books': {
    color: 'slate',
    setupFn: () => setupEbookSync('sync.apple_books'),
    commands: (apiUrl) => [
      `python scripts/apple-books-sync.py --api-url ${apiUrl}`,
    ],
  },
  'sync.wechat_read': {
    color: 'emerald',
    setupFn: () => setupEbookSync('sync.wechat_read'),
    commands: (apiUrl) => [
      `python scripts/wechat-read-sync.py --api-url ${apiUrl} --cookie "YOUR_COOKIE"`,
    ],
  },
  'sync.bilibili': {
    color: 'pink',
    setupFn: () => setupVideoSync('sync.bilibili'),
    credentialLink: '/settings?tab=credentials',
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
    }
  } finally {
    loading.value = false
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
  } catch (e) {
    showError('初始化失败')
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
  if (!plugin.configured) return '未配置'
  if (!plugin.last_sync_at) return '待同步'
  return '已同步'
}

function getStatusClass(plugin) {
  if (!plugin.configured) return 'bg-slate-100 text-slate-500'
  if (!plugin.last_sync_at) return 'bg-amber-50 text-amber-600'
  return 'bg-emerald-50 text-emerald-600'
}

function getCardBorder(plugin) {
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

onMounted(fetchStatus)
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <!-- Header -->
      <div class="mb-6">
        <h1 class="text-xl font-bold tracking-tight text-gray-900">同步管理</h1>
        <p class="mt-1 text-sm text-gray-500">管理外部平台数据同步插件，查看状态与运行脚本命令</p>
      </div>

      <!-- Loading -->
      <div v-if="loading && !plugins.length" class="flex items-center justify-center py-20">
        <div class="w-6 h-6 border-2 border-indigo-200 border-t-indigo-500 rounded-full animate-spin"></div>
      </div>

      <!-- Cards Grid -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="plugin in plugins"
          :key="plugin.source_type"
          class="bg-white rounded-xl border p-5 transition-all duration-200 hover:shadow-sm"
          :class="getCardBorder(plugin)"
        >
          <!-- Top: Icon + Name + Badge -->
          <div class="flex items-start justify-between mb-3">
            <div class="flex items-center gap-3">
              <!-- Platform Icon -->
              <div
                class="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                :class="plugin.configured ? 'bg-slate-50' : 'bg-slate-50/50'"
              >
                <!-- Apple Books -->
                <svg v-if="plugin.source_type === 'sync.apple_books'" class="w-5 h-5" :class="getIconColor(plugin)" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                <!-- WeChat Read -->
                <svg v-else-if="plugin.source_type === 'sync.wechat_read'" class="w-5 h-5" :class="getIconColor(plugin)" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                <!-- Bilibili -->
                <svg v-else-if="plugin.source_type === 'sync.bilibili'" class="w-5 h-5" :class="getIconColor(plugin)" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.91 11.672a.375.375 0 010 .656l-5.603 3.113a.375.375 0 01-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112z" />
                </svg>
              </div>
              <div>
                <h3 class="font-semibold text-sm text-gray-900">{{ plugin.name }}</h3>
                <span class="text-xs" :class="plugin.category === 'ebook' ? 'text-indigo-400' : 'text-pink-400'">
                  {{ plugin.category === 'ebook' ? '电子书' : '视频' }}
                </span>
              </div>
            </div>
            <!-- Status Badge -->
            <span
              class="px-2 py-0.5 rounded-full text-xs font-medium"
              :class="getStatusClass(plugin)"
            >
              {{ getStatusLabel(plugin) }}
            </span>
          </div>

          <!-- Description -->
          <p class="text-xs text-gray-400 mb-4 leading-relaxed">{{ plugin.description }}</p>

          <!-- Stats (configured only) -->
          <div v-if="plugin.configured && plugin.last_sync_at" class="mb-4">
            <div class="flex items-center gap-4 text-xs">
              <div class="flex items-center gap-1 text-gray-500">
                <svg class="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
                </svg>
                <span>{{ plugin.stats.total_items || 0 }} 条目</span>
              </div>
              <div v-if="plugin.stats.total_annotations != null" class="flex items-center gap-1 text-gray-500">
                <svg class="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
                </svg>
                <span>{{ plugin.stats.total_annotations }} 标注</span>
              </div>
            </div>
            <div class="mt-2 text-xs text-gray-400">
              上次同步：{{ formatTimeShort(plugin.last_sync_at) }}
            </div>
          </div>

          <!-- Waiting for first sync hint -->
          <div v-if="plugin.configured && !plugin.last_sync_at" class="mb-4">
            <p class="text-xs text-amber-500">运行脚本开始首次同步</p>
          </div>

          <!-- Source ID (configured) -->
          <div v-if="plugin.configured" class="mb-3">
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
          </div>

          <!-- Script commands (configured, collapsible) -->
          <div v-if="plugin.configured && PLUGIN_META[plugin.source_type]">
            <button
              class="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors mb-2"
              @click="toggleCommands(plugin.source_type)"
            >
              <svg
                class="w-3.5 h-3.5 transition-transform duration-200"
                :class="expandedCommands[plugin.source_type] ? 'rotate-90' : ''"
                fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
              <span>脚本命令</span>
            </button>
            <Transition
              enter-active-class="transition-all duration-200 ease-out"
              enter-from-class="opacity-0 max-h-0"
              enter-to-class="opacity-100 max-h-96"
              leave-active-class="transition-all duration-150 ease-in"
              leave-from-class="opacity-100 max-h-96"
              leave-to-class="opacity-0 max-h-0"
            >
              <div v-if="expandedCommands[plugin.source_type]" class="overflow-hidden">
                <div
                  v-for="(cmd, idx) in PLUGIN_META[plugin.source_type].commands(apiUrl)"
                  :key="idx"
                  class="group relative mb-2"
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

          <!-- Actions -->
          <div class="mt-4 pt-3 border-t border-slate-100 flex items-center gap-2">
            <!-- Not configured: Setup button -->
            <button
              v-if="!plugin.configured"
              class="px-3 py-1.5 text-xs font-medium text-white bg-indigo-500 hover:bg-indigo-600 rounded-lg transition-colors"
              @click="handleSetup(plugin)"
            >
              初始化
            </button>
            <!-- Bilibili: credential link -->
            <router-link
              v-if="plugin.source_type === 'sync.bilibili' && PLUGIN_META[plugin.source_type]?.credentialLink"
              :to="PLUGIN_META[plugin.source_type].credentialLink"
              class="px-3 py-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 bg-slate-50 hover:bg-slate-100 rounded-lg transition-colors"
            >
              配置凭证
            </router-link>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="!loading && !plugins.length" class="text-center py-20 text-gray-400 text-sm">
        暂无同步插件
      </div>
    </div>
  </div>
</template>
