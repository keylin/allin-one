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

// 观看记录：一部片多次观看，各自有日期/评分/感想
export function addWatchLog(contentId, data = {}) {
  return api.post(`/films/${contentId}/logs`, data)
}

export function updateWatchLog(contentId, logId, data) {
  return api.put(`/films/${contentId}/logs/${logId}`, data)
}

export function deleteWatchLog(contentId, logId) {
  return api.delete(`/films/${contentId}/logs/${logId}`)
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

// 配色：待看 = 浅靛蓝（想看的低优先级），想看 = 品牌靛蓝，在看 = 琥珀，看过 = 翠绿，弃了 = 中性灰（不是错误，不用红）
export const WATCH_STATUS_OPTIONS = [
  { value: 'unmarked', label: '未标记', color: 'bg-slate-100 text-slate-500', active: 'bg-slate-600 text-white border-slate-600' },
  { value: 'backlog', label: '待看', color: 'bg-indigo-100 text-indigo-700', active: 'bg-indigo-100 text-indigo-700 border-indigo-300' },
  { value: 'want', label: '想看', color: 'bg-indigo-600 text-white', active: 'bg-indigo-600 text-white border-indigo-600' },
  { value: 'watching', label: '在看', color: 'bg-amber-500 text-white', active: 'bg-amber-500 text-white border-amber-500' },
  { value: 'watched', label: '看过', color: 'bg-emerald-600 text-white', active: 'bg-emerald-600 text-white border-emerald-600' },
  { value: 'dropped', label: '弃了', color: 'bg-slate-500 text-white', active: 'bg-slate-500 text-white border-slate-500' },
]

export function statusMeta(status) {
  return WATCH_STATUS_OPTIONS.find(o => o.value === status) || WATCH_STATUS_OPTIONS[0]
}

// 库内国家统一存 ISO 3166-1 两位码，展示时转中文；港澳台用短名，认不出的原样显示
const REGION_OVERRIDES = { HK: '中国香港', MO: '中国澳门', TW: '中国台湾', SU: '苏联' }
let regionNames = null
try { regionNames = new Intl.DisplayNames(['zh-CN'], { type: 'region' }) } catch { /* 老浏览器：退回显示代码 */ }

export function countryLabel(code) {
  if (!code) return ''
  if (REGION_OVERRIDES[code]) return REGION_OVERRIDES[code]
  if (!regionNames || !/^[A-Z]{2}$/.test(code)) return code
  try { return regionNames.of(code) || code } catch { return code }
}
