import api from './index'

export function uploadEbook(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/ebook/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
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
  // Returns the URL for direct fetch (with auth header handled separately)
  return `/api/ebook/${contentId}/file`
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
