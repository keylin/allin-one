import api from './index'

export function getFinancePresets() {
  return api.get('/finance/presets')
}

export function listFinanceSources() {
  return api.get('/finance/sources')
}

export function getFinanceSummary() {
  return api.get('/finance/summary')
}

export function getTimeseries(sourceId, params = {}) {
  return api.get(`/finance/timeseries/${sourceId}`, { params })
}
