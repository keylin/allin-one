import api from './index'

export function getDashboardStats() {
  return api.get('/dashboard/stats')
}

export function getRecentActivity(limit = 10) {
  return api.get('/dashboard/recent-activity', { params: { limit } })
}
