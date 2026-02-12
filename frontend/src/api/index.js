import axios from 'axios'
import router from '@/router'

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
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('api_key')
      router.push('/login')
    }
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api
