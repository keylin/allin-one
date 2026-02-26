import { defineStore } from 'pinia'
import { ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'

const DEFAULT_SETTINGS = {
  server_url: '',
  api_key: '',
  apple_books_enabled: true,
  wechat_read_enabled: false,
  bilibili_enabled: false,
  apple_books_interval_hours: 6,
  wechat_read_interval_hours: 12,
  bilibili_interval_hours: 6,
  autostart: false,
  notifications_enabled: true,
  apple_books_db_path: null,
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref({ ...DEFAULT_SETTINGS })
  const loaded = ref(false)

  async function load() {
    try {
      const s = await invoke('get_settings')
      settings.value = { ...DEFAULT_SETTINGS, ...s }
      loaded.value = true
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  }

  async function save() {
    try {
      await invoke('save_settings', { settings: settings.value })
    } catch (e) {
      console.error('Failed to save settings:', e)
      throw e
    }
  }

  async function testConnection(url, apiKey) {
    return await invoke('test_server_connection', {
      serverUrl: url,
      apiKey: apiKey,
    })
  }

  return { settings, loaded, load, save, testConnection }
})
