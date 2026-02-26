<script setup>
import { ref, onMounted, computed } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { WebviewWindow } from '@tauri-apps/api/webviewWindow'
import SyncStatus from './SyncStatus.vue'
import CredentialForm from './CredentialForm.vue'
import { useSyncStore } from '../stores/sync.js'
import { useSettingsStore } from '../stores/settings.js'

const syncStore = useSyncStore()
const settingsStore = useSettingsStore()

const showCredForm = ref(false)
const credPlatform = ref('')
const serverOk = ref(null)

onMounted(async () => {
  await settingsStore.load()
  await syncStore.loadStatus()
  await syncStore.startListening()

  // Check server connection
  if (settingsStore.settings.server_url) {
    const result = await settingsStore.testConnection(
      settingsStore.settings.server_url,
      settingsStore.settings.api_key
    )
    serverOk.value = result.ok
  }
})

async function syncAll() {
  try {
    await syncStore.syncNow()
  } catch (e) {
    console.error(e)
  }
}

async function syncOne(platform) {
  try {
    await syncStore.syncPlatform(platform)
  } catch (e) {
    console.error(e)
  }
}

function openCredForm(platform) {
  credPlatform.value = platform
  showCredForm.value = true
}

function closeCredForm() {
  showCredForm.value = false
}

async function onCredSaved() {
  showCredForm.value = false
  await syncStore.loadStatus()
}

function openSettings() {
  const win = new WebviewWindow('settings')
  win.show()
  win.setFocus()
}

const serverHost = computed(() => {
  try {
    return new URL(settingsStore.settings.server_url).hostname || 'Not configured'
  } catch {
    return settingsStore.settings.server_url || 'Not configured'
  }
})

const s = computed(() => syncStore.status)
const settings = computed(() => settingsStore.settings)
</script>

<template>
  <div class="w-[360px] bg-white rounded-xl shadow-2xl border border-gray-100 overflow-hidden select-none">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-100">
      <div class="flex items-center gap-2">
        <span class="text-base font-semibold text-gray-800">Fountain</span>
      </div>
      <div class="flex items-center gap-1 no-drag">
        <button
          @click="syncAll"
          :disabled="syncStore.isSyncing || !settings.server_url"
          title="Sync all platforms"
          class="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors disabled:opacity-40"
        >
          <svg class="w-4 h-4" :class="{ 'animate-spin': syncStore.isSyncing }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
        <button
          @click="openSettings"
          title="Settings"
          class="p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded-md transition-colors"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </div>

    <!-- No server configured — onboarding card -->
    <div v-if="!settings.server_url" class="px-4 py-5">
      <div class="bg-blue-50 border border-blue-100 rounded-xl p-4">
        <div class="flex items-center gap-2 mb-2">
          <span class="text-base">👋</span>
          <span class="text-sm font-semibold text-blue-900">Welcome to Fountain</span>
        </div>
        <p class="text-xs text-blue-700 mb-3 leading-relaxed">
          Connect to your Allin-One server to start syncing your reading and video data.
        </p>
        <div class="space-y-1.5 mb-4">
          <div class="flex items-center gap-2 text-xs text-blue-700">
            <span class="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold flex-shrink-0">1</span>
            Open Settings and enter your server URL
          </div>
          <div class="flex items-center gap-2 text-xs text-blue-700">
            <span class="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold flex-shrink-0">2</span>
            Enable platforms and configure credentials
          </div>
          <div class="flex items-center gap-2 text-xs text-blue-700">
            <span class="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold flex-shrink-0">3</span>
            Click Sync to push your data
          </div>
        </div>
        <button
          @click="openSettings"
          class="w-full py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
        >
          Open Settings →
        </button>
      </div>
    </div>

    <!-- Platform sync cards -->
    <template v-else>
      <!-- Credential form overlay -->
      <div v-if="showCredForm" class="relative">
        <div class="flex items-center px-4 py-2 bg-gray-50 border-b border-gray-100">
          <button @click="closeCredForm" class="text-gray-400 hover:text-gray-600 mr-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
          </button>
          <span class="text-sm font-medium text-gray-700">Login</span>
        </div>
        <CredentialForm :platform="credPlatform" @saved="onCredSaved" @close="closeCredForm" />
      </div>

      <template v-else>
        <div class="divide-y divide-gray-50">
          <SyncStatus
            v-if="settings.apple_books_enabled"
            icon="📚"
            name="Apple Books"
            platform="apple_books"
            :status="s.apple_books_status"
            :last-sync="s.apple_books_last_sync"
            :item-count="s.apple_books_book_count"
            item-label="books"
            :error="s.apple_books_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('apple_books')"
          />
          <SyncStatus
            v-if="settings.wechat_read_enabled"
            icon="📖"
            name="微信读书"
            platform="wechat_read"
            :status="s.wechat_read_status"
            :last-sync="s.wechat_read_last_sync"
            :item-count="s.wechat_read_book_count"
            item-label="books"
            :error="s.wechat_read_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('wechat_read')"
            @fix-auth="openCredForm('wechat_read')"
          />
          <SyncStatus
            v-if="settings.bilibili_enabled"
            icon="🎬"
            name="Bilibili"
            platform="bilibili"
            :status="s.bilibili_status"
            :last-sync="s.bilibili_last_sync"
            :item-count="s.bilibili_video_count"
            item-label="videos"
            :error="s.bilibili_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('bilibili')"
            @fix-auth="openCredForm('bilibili')"
          />
          <SyncStatus
            v-if="settings.kindle_enabled"
            icon="📖"
            name="Kindle"
            platform="kindle"
            :status="s.kindle_status"
            :last-sync="s.kindle_last_sync"
            :item-count="s.kindle_book_count"
            item-label="books"
            :error="s.kindle_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('kindle')"
          />
          <SyncStatus
            v-if="settings.safari_bookmarks_enabled"
            icon="🧭"
            name="Safari Bookmarks"
            platform="safari_bookmarks"
            :status="s.safari_bookmarks_status"
            :last-sync="s.safari_bookmarks_last_sync"
            :item-count="s.safari_bookmarks_count"
            item-label="bookmarks"
            :error="s.safari_bookmarks_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('safari_bookmarks')"
          />
          <SyncStatus
            v-if="settings.chrome_bookmarks_enabled"
            icon="🌐"
            name="Chrome Bookmarks"
            platform="chrome_bookmarks"
            :status="s.chrome_bookmarks_status"
            :last-sync="s.chrome_bookmarks_last_sync"
            :item-count="s.chrome_bookmarks_count"
            item-label="bookmarks"
            :error="s.chrome_bookmarks_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('chrome_bookmarks')"
          />
          <SyncStatus
            v-if="settings.douban_enabled"
            icon="🐟"
            name="豆瓣"
            platform="douban"
            :status="s.douban_status"
            :last-sync="s.douban_last_sync"
            :item-count="s.douban_book_count + s.douban_movie_count"
            item-label="items"
            :error="s.douban_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('douban')"
            @fix-auth="openCredForm('douban')"
          />
          <SyncStatus
            v-if="settings.zhihu_enabled"
            icon="💬"
            name="知乎"
            platform="zhihu"
            :status="s.zhihu_status"
            :last-sync="s.zhihu_last_sync"
            :item-count="s.zhihu_item_count"
            item-label="items"
            :error="s.zhihu_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('zhihu')"
            @fix-auth="openCredForm('zhihu')"
          />
          <SyncStatus
            v-if="settings.github_stars_enabled"
            icon="⭐"
            name="GitHub Stars"
            platform="github_stars"
            :status="s.github_stars_status"
            :last-sync="s.github_stars_last_sync"
            :item-count="s.github_stars_count"
            item-label="stars"
            :error="s.github_stars_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('github_stars')"
            @fix-auth="openCredForm('github_stars')"
          />
          <SyncStatus
            v-if="settings.twitter_enabled"
            icon="🐦"
            name="Twitter / X"
            platform="twitter"
            :status="s.twitter_status"
            :last-sync="s.twitter_last_sync"
            :item-count="s.twitter_tweet_count"
            item-label="tweets"
            :error="s.twitter_error"
            :enabled="!!settings.server_url"
            @sync="syncOne('twitter')"
            @fix-auth="openCredForm('twitter')"
          />

          <div v-if="!settings.apple_books_enabled && !settings.wechat_read_enabled && !settings.bilibili_enabled && !settings.kindle_enabled && !settings.safari_bookmarks_enabled && !settings.chrome_bookmarks_enabled && !settings.douban_enabled && !settings.zhihu_enabled && !settings.github_stars_enabled && !settings.twitter_enabled"
               class="px-4 py-6 text-center text-gray-400 text-sm">
            No platforms enabled. Open Settings to configure.
          </div>
        </div>
      </template>
    </template>

    <!-- Footer: server status -->
    <div class="px-4 py-2 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
      <div class="flex items-center gap-1.5">
        <div class="w-1.5 h-1.5 rounded-full"
          :class="serverOk === null ? 'bg-gray-300' : serverOk ? 'bg-green-400' : 'bg-red-400'"
        ></div>
        <span class="text-xs text-gray-400 font-mono">{{ serverHost }}</span>
      </div>
      <span v-if="syncStore.isSyncing" class="text-xs text-blue-500">Syncing...</span>
    </div>
  </div>
</template>
