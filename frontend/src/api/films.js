import api from './index'

export function listFilms(params = {}) {
  return api.get('/films', { params })
}

export function getFilm(contentId) {
  return api.get(`/films/${contentId}`)
}

export function getFilmStats() {
  return api.get('/films/stats')
}

export function searchTmdb(q, year = null) {
  return api.get('/films/search', { params: { q, ...(year ? { year } : {}) } })
}

export function createFilm(data) {
  return api.post('/films', data)
}

export function updateWatchRecord(contentId, data) {
  return api.put(`/films/${contentId}/record`, data)
}

export function updateFilmNote(contentId, userNote) {
  return api.put(`/films/${contentId}/note`, { user_note: userNote })
}

export function batchRecords(items) {
  return api.post('/films/records/batch', { items })
}

export function deleteFilm(contentId) {
  return api.delete(`/films/${contentId}`)
}

export function enrichMissing(limit = 30) {
  return api.post('/films/enrich-missing', null, { params: { limit }, timeout: 180000 })
}

export function enrichFilm(contentId) {
  return api.post(`/films/${contentId}/enrich`, null, { timeout: 60000 })
}

export function setupFilmSync() {
  return api.post('/films/sync/setup')
}

export const WATCH_STATUS_OPTIONS = [
  { value: 'unmarked', label: '未标记', color: 'bg-slate-100 text-slate-500' },
  { value: 'want', label: '想看', color: 'bg-sky-50 text-sky-600' },
  { value: 'watching', label: '在看', color: 'bg-amber-50 text-amber-600' },
  { value: 'watched', label: '看过', color: 'bg-emerald-50 text-emerald-600' },
  { value: 'dropped', label: '弃了', color: 'bg-rose-50 text-rose-500' },
]

export function statusMeta(status) {
  return WATCH_STATUS_OPTIONS.find(o => o.value === status) || WATCH_STATUS_OPTIONS[0]
}
