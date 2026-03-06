import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tracedInvoke } from '../lib/logger'
import { error as logError } from '@tauri-apps/plugin-log'

const DEFAULT_SETTINGS = {
  server_url: '',
  api_key: '',
  apple_books_enabled: true,
  wechat_read_enabled: false,
  bilibili_enabled: false,
  kindle_enabled: false,
  safari_bookmarks_enabled: false,
  chrome_bookmarks_enabled: false,
  apple_books_interval_hours: 6,
  wechat_read_interval_hours: 12,
  bilibili_interval_hours: 6,
  kindle_interval_hours: 24,
  bookmarks_interval_hours: 6,
  autostart: false,
  notifications_enabled: true,
  apple_books_db_path: null,
  kindle_clippings_path: null,
  safari_bookmarks_path: null,
  chrome_bookmarks_path: null,
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref({ ...DEFAULT_SETTINGS })
  const loaded = ref(false)

  async function load() {
    try {
      const s = await tracedInvoke('get_settings')
      // Mutate in-place to preserve object reference for destructured consumers
      Object.assign(settings.value, DEFAULT_SETTINGS, s)
      loaded.value = true
    } catch (e) {
      logError(`Failed to load settings: ${e}`)
    }
  }

  async function save() {
    // Sanitize number fields: v-model.number can produce "" or NaN when input is cleared
    const payload = { ...settings.value }
    const numberFields = [
      'apple_books_interval_hours', 'wechat_read_interval_hours', 'bilibili_interval_hours',
      'kindle_interval_hours', 'bookmarks_interval_hours',
    ]
    for (const field of numberFields) {
      const v = payload[field]
      if (typeof v !== 'number' || isNaN(v)) {
        payload[field] = DEFAULT_SETTINGS[field] || 6
      }
    }
    try {
      await tracedInvoke('save_settings', { settings: payload })
    } catch (e) {
      logError(`Failed to save settings: ${e}`)
      throw e
    }
  }

  async function testConnection(url, apiKey) {
    return await tracedInvoke('test_server_connection', {
      serverUrl: url,
      apiKey: apiKey,
    })
  }

  return { settings, loaded, load, save, testConnection }
})
