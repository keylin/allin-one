import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

export const useSyncStore = defineStore('sync', () => {
  const status = ref({
    apple_books_last_sync: null,
    wechat_read_last_sync: null,
    bilibili_last_sync: null,
    apple_books_book_count: 0,
    wechat_read_book_count: 0,
    bilibili_video_count: 0,
    apple_books_status: 'idle',
    wechat_read_status: 'idle',
    bilibili_status: 'idle',
    apple_books_error: null,
    wechat_read_error: null,
    bilibili_error: null,
  })

  const isSyncing = computed(() =>
    status.value.apple_books_status === 'syncing' ||
    status.value.wechat_read_status === 'syncing' ||
    status.value.bilibili_status === 'syncing'
  )

  async function loadStatus() {
    try {
      const s = await invoke('get_sync_status')
      status.value = { ...status.value, ...s }
    } catch (e) {
      console.error('Failed to load sync status:', e)
    }
  }

  async function syncNow() {
    try {
      const results = await invoke('sync_now')
      return results
    } catch (e) {
      console.error('Sync failed:', e)
      throw e
    }
  }

  async function syncPlatform(platform) {
    try {
      const result = await invoke('sync_platform', { platform })
      return result
    } catch (e) {
      console.error(`Sync ${platform} failed:`, e)
      throw e
    }
  }

  // Listen for real-time status updates from Rust
  async function startListening() {
    await listen('sync-status-changed', (event) => {
      status.value = { ...status.value, ...event.payload }
    })
  }

  function relativeTime(isoString) {
    if (!isoString) return null
    const now = new Date()
    const then = new Date(isoString)
    const diffMs = now - then
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMins / 60)
    const diffDays = Math.floor(diffHours / 24)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    return `${diffDays}d ago`
  }

  return {
    status,
    isSyncing,
    loadStatus,
    syncNow,
    syncPlatform,
    startListening,
    relativeTime,
  }
})
