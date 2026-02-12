<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api'

const router = useRouter()
const apiKey = ref('')
const error = ref('')
const loading = ref(false)

// 进入 login 页时重新探测后端是否需要认证
onMounted(async () => {
  try {
    const res = await fetch('/api/dashboard/stats')
    if (res.status !== 401) {
      // 后端未启用认证，直接跳转
      router.replace('/dashboard')
    }
  } catch {
    error.value = '无法连接服务器，请检查后端是否正常运行'
  }
})

async function handleLogin() {
  if (!apiKey.value.trim()) {
    error.value = '请输入 API Key'
    return
  }

  loading.value = true
  error.value = ''

  try {
    // 临时设置 header 测试 key 是否有效
    const res = await api.get('/dashboard/stats', {
      headers: { 'X-API-Key': apiKey.value.trim() }
    })
    if (res.code === 0) {
      localStorage.setItem('api_key', apiKey.value.trim())
      router.push('/dashboard')
    } else {
      error.value = '验证失败，请检查 API Key'
    }
  } catch (e) {
    if (e.response?.status === 401) {
      error.value = 'API Key 无效'
    } else {
      error.value = '连接失败，请检查服务是否正常'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-slate-50/50 px-4">
    <div class="w-full max-w-sm">
      <div class="text-center mb-8">
        <h1 class="text-2xl font-bold tracking-tight text-slate-900">Allin-One</h1>
        <p class="text-sm text-slate-400 mt-1">信息聚合与智能分析平台</p>
      </div>

      <div class="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6">
        <h2 class="text-base font-semibold text-slate-800 mb-4">API Key 认证</h2>

        <form @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-slate-600 mb-1.5">API Key</label>
            <input
              v-model="apiKey"
              type="password"
              placeholder="输入你的 API Key"
              class="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 bg-slate-50/50 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all duration-200"
              autofocus
            />
          </div>

          <p v-if="error" class="text-sm text-rose-500">{{ error }}</p>

          <button
            type="submit"
            :disabled="loading"
            class="w-full py-2.5 rounded-xl text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50 transition-all duration-200 shadow-sm shadow-indigo-200"
          >
            {{ loading ? '验证中...' : '登录' }}
          </button>
        </form>
      </div>

      <p class="text-xs text-slate-300 text-center mt-6">
        API Key 在服务端 .env 中通过 API_KEY 配置
      </p>
    </div>
  </div>
</template>
