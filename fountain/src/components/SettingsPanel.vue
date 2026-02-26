<script setup>
import { ref, onMounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { useSettingsStore } from '../stores/settings.js'
import CredentialForm from './CredentialForm.vue'

const settingsStore = useSettingsStore()
const { settings, save, testConnection } = settingsStore

const saving = ref(false)
const testResult = ref(null)
const testing = ref(false)
const showCredForm = ref(false)
const credPlatform = ref('')

onMounted(() => settingsStore.load())

async function handleSave() {
  saving.value = true
  try {
    await save()
    // Show brief success indication
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
    <div class="flex items-center px-5 py-4 border-b border-gray-100">
      <span class="text-base font-semibold text-gray-800">Settings</span>
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
                placeholder="Optional API key"
                class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
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
              Update Cookies
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
    <div v-if="!showCredForm" class="px-5 py-4 border-t border-gray-100 flex justify-end">
      <button
        @click="handleSave"
        :disabled="saving"
        class="px-5 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-60"
      >
        {{ saving ? 'Saved ✓' : 'Save Settings' }}
      </button>
    </div>
  </div>
</template>
