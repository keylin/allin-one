import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

// 请求拦截器：自动附带 API Key
api.interceptors.request.use((config) => {
  const apiKey = localStorage.getItem('api_key')
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey
  }
  return config
})

// 响应拦截器：解包 + 401 跳转登录
// 注意：不导入 router 以避免循环依赖，使用 window.location 跳转
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401 && !window.location.pathname.startsWith('/login')) {
      localStorage.removeItem('api_key')
      window.location.href = '/login'
    }
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api
