import api from './index'

export function uploadEbook(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/ebook/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
    onUploadProgress: onProgress || undefined,
  })
}

export function listEbooks(params = {}) {
  return api.get('/ebook/list', { params })
}

export function getEbookDetail(contentId) {
  return api.get(`/ebook/${contentId}`)
}

export function deleteEbook(contentId) {
  return api.delete(`/ebook/${contentId}`)
}

export function getEbookFileUrl(contentId) {
  return `/api/ebook/${contentId}/file`
}

export function fetchEbookBlob(contentId) {
  return api.get(`/ebook/${contentId}/file`, {
    responseType: 'blob',
    timeout: 120000,
  })
}

export function getReadingProgress(contentId) {
  return api.get(`/ebook/${contentId}/progress`)
}

export function updateReadingProgress(contentId, data) {
  return api.put(`/ebook/${contentId}/progress`, data)
}

// Annotations
export function listAnnotations(contentId) {
  return api.get(`/ebook/${contentId}/annotations`)
}

export function createAnnotation(contentId, data) {
  return api.post(`/ebook/${contentId}/annotations`, data)
}

export function updateAnnotation(contentId, annotationId, data) {
  return api.put(`/ebook/${contentId}/annotations/${annotationId}`, data)
}

export function deleteAnnotation(contentId, annotationId) {
  return api.delete(`/ebook/${contentId}/annotations/${annotationId}`)
}

// Bookmarks
export function listBookmarks(contentId) {
  return api.get(`/ebook/${contentId}/bookmarks`)
}

export function createBookmark(contentId, data) {
  return api.post(`/ebook/${contentId}/bookmarks`, data)
}

export function deleteBookmark(contentId, bookmarkId) {
  return api.delete(`/ebook/${contentId}/bookmarks/${bookmarkId}`)
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
