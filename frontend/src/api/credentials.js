import api from './index'

export function listCredentials(params = {}) {
  return api.get('/credentials', { params })
}

export function createCredential(data) {
  return api.post('/credentials', data)
}

export function updateCredential(id, data) {
  return api.put(`/credentials/${id}`, data)
}

export function deleteCredential(id) {
  return api.delete(`/credentials/${id}`)
}

export function listCredentialOptions(params = {}) {
  return api.get('/credentials/options', { params })
}

export function generateBilibiliQrcode() {
  return api.post('/credentials/bilibili/qrcode/generate')
}

export function pollBilibiliQrcode(key) {
  return api.get('/credentials/bilibili/qrcode/poll', { params: { qrcode_key: key } })
}

export function checkCredential(id) {
  return api.post(`/credentials/${id}/check`)
}

export function syncRsshub(id) {
  return api.post(`/credentials/${id}/sync-rsshub`)
}
