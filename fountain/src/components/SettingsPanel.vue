<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow'
import { confirm } from '@tauri-apps/plugin-dialog'
import { useSettingsStore } from '../stores/settings.js'
import CredentialForm from './CredentialForm.vue'

const settingsStore = useSettingsStore()
const { settings, save, testConnection } = settingsStore

const saving = ref(false)
const testResult = ref(null)
const testing = ref(false)
const showCredForm = ref(false)
const credPlatform = ref('')

// Unsaved change tracking
const originalSettings = ref(null)
const isDirty = computed(() => {
  if (!originalSettings.value) return false
  return JSON.stringify(settings) !== JSON.stringify(originalSettings.value)
})

let unlisten = null
let skipCloseCheck = false

onMounted(async () => {
  await settingsStore.load()
  originalSettings.value = JSON.parse(JSON.stringify(settings))

  const appWindow = getCurrentWebviewWindow()
  unlisten = await appWindow.onCloseRequested(async (event) => {
    if (skipCloseCheck || !isDirty.value) return
    event.preventDefault()
    const ok = await confirm('You have unsaved changes. Close without saving?', {
      title: 'Unsaved Changes',
      kind: 'warning',
      okLabel: 'Close Anyway',
      cancelLabel: 'Keep Editing',
    })
    if (ok) {
      skipCloseCheck = true
      appWindow.close()
    }
  })
})

onUnmounted(() => {
  if (unlisten) unlisten()
})

async function handleSave() {
  saving.value = true
  try {
    await save()
    originalSettings.value = JSON.parse(JSON.stringify(settings))
    setTimeout(() => { saving.value = false }, 500)
  } catch (e) {
    alert('Failed to save settings: ' + e)
    saving.value = false
  }
}

async function handleTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testConnection(settings.server_url, settings.api_key)
  } catch (e) {
    testResult.value = { ok: false, message: e.toString() }
  } finally {
    testing.value = false
  }
}

function openCred(platform) {
  credPlatform.value = platform
  showCredForm.value = true
}

function onCredSaved() {
  showCredForm.value = false
}
</script>

<template>
  <div class="h-full flex flex-col bg-white">
    <!-- Header -->
    <div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">
      <span class="text-base font-semibold text-gray-800">Settings</span>
      <span v-if="isDirty" class="text-xs text-amber-600 font-medium">● Unsaved changes</span>
    </div>

    <div class="flex-1 overflow-y-auto">
      <!-- Credential form overlay -->
      <div v-if="showCredForm" class="p-4">
        <div class="flex items-center mb-3">
          <button @click="showCredForm = false" class="text-gray-400 hover:text-gray-600 mr-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
          </button>
          <span class="text-sm font-medium text-gray-700">Login — {{ credPlatform }}</span>
        </div>
        <CredentialForm :platform="credPlatform" @saved="onCredSaved" @close="showCredForm = false" />
      </div>

      <div v-else class="p-5 space-y-6">
        <!-- Server section -->
        <section>
          <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Server</h2>
          <div class="space-y-3">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Server URL</label>
              <input
                v-model="settings.server_url"
                type="url"
                placeholder="https://your-server.com"
                class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
              <input
                v-model="settings.api_key"
                type="password"
                placeholder="Optional — set in Allin-One server settings"
                class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p class="mt-1 text-xs text-gray-400">Leave blank if your server has no auth</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                @click="handleTest"
                :disabled="!settings.server_url || testing"
                class="px-3 py-1.5 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-40"
              >
                {{ testing ? 'Testing...' : 'Test Connection' }}
              </button>
              <span v-if="testResult" class="text-sm" :class="testResult.ok ? 'text-green-600' : 'text-red-500'">
                {{ testResult.ok ? '✓ ' : '✗ ' }}{{ testResult.message }}
              </span>
            </div>
          </div>
        </section>

        <!-- Apple Books section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">📚 Apple Books</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.apple_books_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.apple_books_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.apple_books_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <p class="text-xs text-gray-400">
              Reads from ~/Library/Containers/com.apple.iBooksX/... (no auth required)
            </p>
          </div>
        </section>

        <!-- WeChat Read section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">📖 微信读书</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.wechat_read_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.wechat_read_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.wechat_read_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <button
              @click="openCred('wechat_read')"
              class="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
              Update Login
            </button>
          </div>
        </section>

        <!-- Bilibili section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">🎬 Bilibili</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.bilibili_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.bilibili_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.bilibili_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <button
              @click="openCred('bilibili')"
              class="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
              Login with QR Code
            </button>
          </div>
        </section>

        <!-- Kindle section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">📖 Kindle</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.kindle_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.kindle_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.kindle_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">Clippings file path (optional)</label>
              <input
                v-model="settings.kindle_clippings_path"
                type="text"
                placeholder="Auto-detect from connected Kindle"
                class="w-full px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <p class="text-xs text-gray-400">
              Reads highlights from My Clippings.txt. Connect your Kindle or set path above.
            </p>
          </div>
        </section>

        <!-- Safari Bookmarks section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">🧭 Safari Bookmarks</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.safari_bookmarks_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.safari_bookmarks_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.bookmarks_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <p class="text-xs text-gray-400">
              Reads from ~/Library/Safari/Bookmarks.plist (no auth required)
            </p>
          </div>
        </section>

        <!-- Chrome Bookmarks section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">🌐 Chrome Bookmarks</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.chrome_bookmarks_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.chrome_bookmarks_enabled" class="space-y-2">
            <p class="text-xs text-gray-400">
              Auto-detects Chrome, Brave, or Edge. Shares interval with Safari bookmarks.
            </p>
            <div>
              <label class="block text-xs text-gray-500 mb-1">Custom bookmarks path (optional)</label>
              <input
                v-model="settings.chrome_bookmarks_path"
                type="text"
                placeholder="Auto-detect Chrome/Brave/Edge"
                class="w-full px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        </section>

        <!-- Douban section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">🐟 豆瓣</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.douban_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.douban_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.douban_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <button
              @click="openCred('douban')"
              class="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
              Update Login
            </button>
          </div>
        </section>

        <!-- Zhihu section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">💬 知乎</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.zhihu_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.zhihu_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.zhihu_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <button
              @click="openCred('zhihu')"
              class="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
              Update Login
            </button>
          </div>
        </section>

        <!-- GitHub Stars section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">⭐ GitHub Stars</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.github_stars_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.github_stars_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.github_stars_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <button
              @click="openCred('github_stars')"
              class="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
              Update Token
            </button>
          </div>
        </section>

        <!-- Twitter / X section -->
        <section>
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">🐦 Twitter / X</h2>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settings.twitter_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-600">Enabled</span>
            </label>
          </div>
          <div v-if="settings.twitter_enabled" class="space-y-2">
            <div class="flex items-center gap-3">
              <label class="text-sm text-gray-600 whitespace-nowrap">Sync every</label>
              <input
                v-model.number="settings.twitter_interval_hours"
                type="number" min="1" max="168"
                class="w-20 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <span class="text-sm text-gray-500">hours</span>
            </div>
            <button
              @click="openCred('twitter')"
              class="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
              Update Login
            </button>
          </div>
        </section>

        <!-- General section -->
        <section>
          <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">General</h2>
          <div class="space-y-2">
            <label class="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" v-model="settings.autostart" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-700">Launch at login</span>
            </label>
            <label class="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" v-model="settings.notifications_enabled" class="w-4 h-4 accent-blue-600" />
              <span class="text-sm text-gray-700">Show sync notifications</span>
            </label>
          </div>
        </section>
      </div>
    </div>

    <!-- Footer -->
    <div v-if="!showCredForm" class="px-5 py-4 border-t border-gray-100 flex items-center justify-end gap-3">
      <span v-if="isDirty" class="text-xs text-gray-400">Unsaved changes will be lost if you close this window</span>
      <button
        @click="handleSave"
        :disabled="saving"
        class="px-5 py-2 text-sm font-medium text-white rounded-lg transition-colors disabled:opacity-60"
        :class="isDirty ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-400 hover:bg-gray-500'"
      >
        {{ saving ? 'Saved ✓' : 'Save Settings' }}
      </button>
    </div>
  </div>
</template>
