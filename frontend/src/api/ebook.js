import api from './index'

export function listEbooks(params = {}) {
  return api.get('/ebook/list', { params })
}

export function getEbookDetail(contentId) {
  return api.get(`/ebook/${contentId}`)
}

export function deleteEbook(contentId) {
  return api.delete(`/ebook/${contentId}`)
}

// Annotations (read-only)
export function listAnnotations(contentId) {
  return api.get(`/ebook/${contentId}/annotations`)
}

// Cross-book annotations
export function listRecentAnnotations(limit = 10) {
  return api.get('/ebook/annotations/recent', { params: { limit } })
}

// Metadata
export function updateEbookMetadata(contentId, data) {
  return api.put(`/ebook/${contentId}/metadata`, data)
}

export function searchBookMetadata(contentId, query = '') {
  const params = query ? { query } : {}
  return api.get(`/ebook/${contentId}/metadata/search`, { params })
}

export function applyBookMetadata(contentId, data) {
  return api.post(`/ebook/${contentId}/metadata/apply`, data)
}

export function getEbookFilters() {
  return api.get('/ebook/filters')
}

// Ebook Sync (Apple Books / 微信读书等)
export function getEbookSyncStatus(sourceId) {
  const params = sourceId ? { source_id: sourceId } : {}
  return api.get('/ebook/sync/status', { params })
}

export function setupEbookSync(sourceType = 'sync.apple_books') {
  return api.post('/ebook/sync/setup', null, { params: { source_type: sourceType } })
}
