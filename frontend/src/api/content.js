import api from './index'

export function listContent(params = {}) {
  return api.get('/content', { params })
}

export function getContent(id) {
  return api.get(`/content/${id}`)
}

export function analyzeContent(id) {
  return api.post(`/content/${id}/analyze`)
}

export function toggleFavorite(id) {
  return api.post(`/content/${id}/favorite`)
}

export function updateNote(id, userNote) {
  return api.patch(`/content/${id}/note`, { user_note: userNote })
}

export function incrementView(id) {
  return api.post(`/content/${id}/view`)
}

export function batchDeleteContent(ids) {
  return api.post('/content/batch-delete', { ids })
}

export function listSourceOptions() {
  return api.get('/sources/options')
}
