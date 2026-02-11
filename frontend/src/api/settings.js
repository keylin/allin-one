import api from './index'

export function getSettings() {
  return api.get('/settings')
}

export function updateSettings(settings) {
  return api.put('/settings', { settings })
}
