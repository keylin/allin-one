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

export function updateFilmMeta(contentId, data) {
  return api.put(`/films/${contentId}/meta`, data, { timeout: 60000 })
}

export function relinkFilm(contentId, tmdbId, kind = 'movie') {
  return api.post(`/films/${contentId}/relink`, { tmdb_id: tmdbId, kind }, { timeout: 60000 })
}

export function setDoubanLink(contentId, payload = {}) {
  return api.post(`/films/${contentId}/douban`, payload, { timeout: 60000 })
}

export function clearDoubanLink(contentId) {
  return api.delete(`/films/${contentId}/douban`)
}

export function setupFilmSync() {
  return api.post('/films/sync/setup')
}

// 配色：想看 = 品牌靛蓝，在看 = 琥珀，看过 = 翠绿，弃了 = 中性灰（不是错误，不用红）
export const WATCH_STATUS_OPTIONS = [
  { value: 'unmarked', label: '未标记', color: 'bg-slate-100 text-slate-500', active: 'bg-slate-600 text-white border-slate-600' },
  { value: 'want', label: '想看', color: 'bg-indigo-600 text-white', active: 'bg-indigo-600 text-white border-indigo-600' },
  { value: 'watching', label: '在看', color: 'bg-amber-500 text-white', active: 'bg-amber-500 text-white border-amber-500' },
  { value: 'watched', label: '看过', color: 'bg-emerald-600 text-white', active: 'bg-emerald-600 text-white border-emerald-600' },
  { value: 'dropped', label: '弃了', color: 'bg-slate-500 text-white', active: 'bg-slate-500 text-white border-slate-500' },
]

export function statusMeta(status) {
  return WATCH_STATUS_OPTIONS.find(o => o.value === status) || WATCH_STATUS_OPTIONS[0]
}
