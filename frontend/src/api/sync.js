import api from './index'

export function getSyncStatus() {
  return api.get('/sync/status')
}

export { setupEbookSync } from './ebook'

export function setupVideoSync(sourceType = 'sync.bilibili') {
  return api.post('/video/sync/setup', null, { params: { source_type: sourceType } })
}
