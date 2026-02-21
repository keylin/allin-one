import api from './index'

export function getDashboardStats() {
  return api.get('/dashboard/stats')
}

export function getRecentActivity(limit = 10) {
  return api.get('/dashboard/recent-activity', { params: { limit } })
}

export function getCollectionTrend(days = 7) {
  return api.get('/dashboard/collection-trend', { params: { days } })
}

export function getSourceHealth() {
  return api.get('/dashboard/source-health')
}

export function getDailyStats(date) {
  return api.get('/dashboard/daily-stats', { params: { date } })
}

export function getContentStatusDistribution() {
  return api.get('/dashboard/content-status-distribution')
}

export function getStorageStats() {
  return api.get('/dashboard/storage-stats')
}
