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

export function getRecentContent(limit = 8) {
  return api.get('/dashboard/recent-content', { params: { limit } })
}

export function getDailyStats(date) {
  return api.get('/dashboard/daily-stats', { params: { date } })
}
