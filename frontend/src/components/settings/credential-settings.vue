<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  listCredentials, createCredential, updateCredential, deleteCredential,
  checkCredential, syncRsshub,
  generateBilibiliQrcode, pollBilibiliQrcode,
} from '@/api/credentials'
import { useToast } from '@/composables/useToast'
import QRCode from 'qrcode'

const toast = useToast()

// ---- 平台凭证 ----
const credentials = ref([])
const credLoading = ref(false)
const credActionLoading = ref({})

// 内联编辑
const editingId = ref(null)
const editingValue = ref('')

function startEditing(id) {
  editingId.value = id
  editingValue.value = ''
}

function cancelEditing() {
  editingId.value = null
  editingValue.value = ''
}

async function handleUpdateCredential(id) {
  const val = editingValue.value.trim()
  if (!val) return
  credActionLoading.value[id] = 'updating'
  try {
    const res = await updateCredential(id, { credential_data: val })
    if (res.code === 0) {
      toast.success('凭证已更新')
      cancelEditing()
      await loadCredentials()
    } else {
      toast.error(res.message || '更新失败')
    }
  } finally {
    delete credActionLoading.value[id]
  }
}

// B站扫码
const biliAuthStatus = ref('idle')
const biliQrcodeKey = ref('')
const qrcodeCanvas = ref(null)
let biliPollTimer = null

async function loadCredentials() {
  credLoading.value = true
  try {
    const res = await listCredentials()
    if (res.code === 0) credentials.value = res.data
  } finally {
    credLoading.value = false
  }
}

async function handleCheckCredential(id) {
  credActionLoading.value[id] = 'checking'
  try {
    const res = await checkCredential(id)
    if (res.code === 0) {
      const cred = credentials.value.find(c => c.id === id)
      if (cred) cred.status = res.data.valid ? 'active' : 'expired'
      if (res.data.valid) {
        toast.success('凭证有效')
      } else {
        toast.error(res.message || '凭证已失效')
      }
    }
  } finally {
    delete credActionLoading.value[id]
  }
}

async function handleSyncRsshub(id) {
  credActionLoading.value[id] = 'syncing'
  try {
    await syncRsshub(id)
  } finally {
    delete credActionLoading.value[id]
  }
}

async function handleDeleteCredential(id, force = false) {
  const cred = credentials.value.find(c => c.id === id)
  if (!force && !confirm(`确认删除凭证「${cred?.display_name}」？`)) return
  credActionLoading.value[id] = 'deleting'
  try {
    const res = await deleteCredential(id, { force })
    if (res.code === 0) {
      credentials.value = credentials.value.filter(c => c.id !== id)
      toast.success('凭证已删除')
    } else if (res.code === 1 && res.data?.source_count) {
      // 有数据源引用，询问是否强制删除
      const count = res.data.source_count
      if (confirm(`该凭证被 ${count} 个数据源引用。\n强制删除将解除所有关联，确认继续？`)) {
        await handleDeleteCredential(id, true)
      }
    } else {
      toast.error(res.message || '删除失败')
    }
  } finally {
    delete credActionLoading.value[id]
  }
}

async function startBiliAuth() {
  biliAuthStatus.value = 'loading'
  try {
    const res = await generateBilibiliQrcode()
    if (res.code !== 0) {
      biliAuthStatus.value = 'error'
      return
    }
    biliQrcodeKey.value = res.data.qrcode_key
    biliAuthStatus.value = 'waiting'

    await nextTick()
    if (qrcodeCanvas.value) {
      QRCode.toCanvas(qrcodeCanvas.value, res.data.url, { width: 200, margin: 2 })
    }

    clearBiliPoll()
    biliPollTimer = setInterval(pollBiliStatus, 2000)
  } catch {
    biliAuthStatus.value = 'error'
  }
}

async function pollBiliStatus() {
  if (!biliQrcodeKey.value) return
  try {
    const res = await pollBilibiliQrcode(biliQrcodeKey.value)
    if (res.code !== 0) return
    const status = res.data.status
    if (status === 'waiting') {
      biliAuthStatus.value = 'waiting'
    } else if (status === 'scanned') {
      biliAuthStatus.value = 'scanned'
    } else if (status === 'expired') {
      biliAuthStatus.value = 'expired'
      clearBiliPoll()
    } else if (status === 'success') {
      biliAuthStatus.value = 'success'
      clearBiliPoll()
      await loadCredentials()
    }
  } catch { /* ignore poll errors */ }
}

function clearBiliPoll() {
  if (biliPollTimer) {
    clearInterval(biliPollTimer)
    biliPollTimer = null
  }
}

function resetBiliAuth() {
  clearBiliPoll()
  biliAuthStatus.value = 'idle'
  biliQrcodeKey.value = ''
}

// Twitter 凭证
const twitterAuthToken = ref('')
const twitterSaving = ref(false)
const twitterSaveResult = ref(null)

// 微信读书凭证
const wechatCookie = ref('')
const wechatSaving = ref(false)
const wechatSaveResult = ref(null)

async function handleSaveTwitter() {
  const token = twitterAuthToken.value.trim()
  if (!token) return
  twitterSaving.value = true
  twitterSaveResult.value = null
  try {
    const res = await createCredential({
      platform: 'twitter',
      credential_type: 'auth_token',
      credential_data: token,
      display_name: 'Twitter 账号',
    })
    if (res.code === 0) {
      twitterSaveResult.value = { success: true, message: '凭证已保存并同步至 RSSHub' }
      twitterAuthToken.value = ''
      await loadCredentials()
    } else {
      twitterSaveResult.value = { success: false, message: res.message || '保存失败' }
    }
  } catch (e) {
    twitterSaveResult.value = { success: false, message: '保存失败: ' + (e.message || '网络错误') }
  } finally {
    twitterSaving.value = false
  }
}

async function handleSaveWechat() {
  const cookie = wechatCookie.value.trim()
  if (!cookie) return
  wechatSaving.value = true
  wechatSaveResult.value = null
  try {
    const res = await createCredential({
      platform: 'wechat_read',
      credential_type: 'cookie',
      credential_data: cookie,
      display_name: '微信读书',
    })
    if (res.code === 0) {
      const reason = res.data?.validation_reason
      if (reason) {
        // 凭证已保存但验证失败
        wechatSaveResult.value = { success: false, message: res.message }
      } else {
        wechatSaveResult.value = { success: true, message: '凭证已保存' }
      }
      wechatCookie.value = ''
      await loadCredentials()
    } else {
      wechatSaveResult.value = { success: false, message: res.message || '保存失败' }
    }
  } catch (e) {
    wechatSaveResult.value = { success: false, message: '保存失败: ' + (e.message || '网络错误') }
  } finally {
    wechatSaving.value = false
  }
}

const statusBadge = (status) => {
  switch (status) {
    case 'active': return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    case 'expired': return 'bg-amber-50 text-amber-700 border-amber-200'
    case 'error': return 'bg-rose-50 text-rose-700 border-rose-200'
    default: return 'bg-slate-50 text-slate-600 border-slate-200'
  }
}

const statusLabel = (status) => {
  switch (status) {
    case 'active': return '有效'
    case 'expired': return '已过期'
    case 'error': return '异常'
    default: return status
  }
}

onMounted(() => {
  loadCredentials()
})

onBeforeUnmount(() => {
  clearBiliPoll()
})
</script>

<template>
  <div class="px-4 py-4 max-w-3xl">
    <!-- 添加凭证区域 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <!-- B站扫码 -->
      <div class="p-4 bg-white rounded-xl border border-slate-200/60 shadow-sm">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div class="w-7 h-7 rounded-lg flex items-center justify-center bg-pink-50 text-pink-500">
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17.813 4.653h.854c1.51.054 2.769.578 3.773 1.574 1.004.995 1.524 2.249 1.56 3.76v7.36c-.036 1.51-.556 2.769-1.56 3.773s-2.262 1.524-3.773 1.56H5.333c-1.51-.036-2.769-.556-3.773-1.56S.036 18.858 0 17.347v-7.36c.036-1.511.556-2.765 1.56-3.76 1.004-.996 2.262-1.52 3.773-1.574h.774l-1.174-1.12a1.234 1.234 0 0 1-.373-.906c0-.356.124-.658.373-.907l.027-.027c.267-.249.573-.373.92-.373.347 0 .653.124.92.373L9.653 4.44c.071.071.134.142.187.213h4.267a.836.836 0 0 1 .16-.213l2.853-2.747c.267-.249.573-.373.92-.373.347 0 .662.151.929.4.267.249.391.551.391.907 0 .355-.124.657-.373.906zM5.333 7.24c-.746.018-1.373.276-1.88.773-.506.498-.769 1.13-.786 1.894v7.52c.017.764.28 1.395.786 1.893.507.498 1.134.756 1.88.773h13.334c.746-.017 1.373-.275 1.88-.773.506-.498.769-1.129.786-1.893v-7.52c-.017-.765-.28-1.396-.786-1.894-.507-.497-1.134-.755-1.88-.773zM8 11.107c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373zm8 0c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373z"/>
              </svg>
            </div>
            <h4 class="text-sm font-semibold text-slate-700">B站凭证</h4>
          </div>
          <button
            class="px-3 py-1.5 text-xs font-medium text-white bg-pink-500 rounded-lg hover:bg-pink-600 active:bg-pink-700 transition-all duration-200"
            @click="startBiliAuth"
          >
            扫码登录
          </button>
        </div>

        <!-- 扫码状态 -->
        <Transition
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="opacity-0 -translate-y-2"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div v-if="biliAuthStatus !== 'idle'" class="mt-3 p-3 bg-slate-50 rounded-lg border border-slate-100">
            <div v-if="biliAuthStatus === 'loading'" class="flex items-center gap-2 text-sm text-slate-500">
              <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              正在生成二维码...
            </div>

            <div v-else-if="biliAuthStatus === 'waiting' || biliAuthStatus === 'scanned'" class="flex flex-col items-center gap-3">
              <canvas ref="qrcodeCanvas" class="rounded-lg border border-slate-200"></canvas>
              <p class="text-sm font-medium" :class="biliAuthStatus === 'scanned' ? 'text-amber-600' : 'text-slate-600'">
                {{ biliAuthStatus === 'scanned' ? '已扫码，请在手机上确认' : '请使用 B站 App 扫描二维码' }}
              </p>
              <div v-if="biliAuthStatus === 'waiting'" class="flex items-center gap-1.5 text-xs text-slate-400">
                <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                等待扫码中...
              </div>
              <button type="button" class="text-xs text-slate-400 hover:text-slate-600 transition-colors" @click="resetBiliAuth">取消</button>
            </div>

            <div v-else-if="biliAuthStatus === 'success'" class="flex items-center gap-2 text-sm text-emerald-600">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              凭证已保存
              <button type="button" class="ml-2 text-xs text-slate-400 hover:text-slate-600 transition-colors" @click="resetBiliAuth">关闭</button>
            </div>

            <div v-else-if="biliAuthStatus === 'expired' || biliAuthStatus === 'error'" class="flex items-center gap-2 text-sm text-rose-600">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
              {{ biliAuthStatus === 'expired' ? '二维码已过期' : '生成失败' }}
              <button type="button" class="ml-2 text-xs text-slate-500 hover:text-slate-700 underline transition-colors" @click="startBiliAuth">重试</button>
              <button type="button" class="text-xs text-slate-400 hover:text-slate-600 transition-colors" @click="resetBiliAuth">关闭</button>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Twitter 凭证 -->
      <div class="p-4 bg-white rounded-xl border border-slate-200/60 shadow-sm">
        <div class="flex items-center gap-2 mb-3">
          <div class="w-7 h-7 rounded-lg flex items-center justify-center bg-sky-50 text-slate-800">
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
            </svg>
          </div>
          <h4 class="text-sm font-semibold text-slate-700">Twitter 凭证</h4>
        </div>
        <div class="flex gap-2">
          <input
            v-model="twitterAuthToken"
            type="password"
            placeholder="粘贴 auth_token 值"
            class="flex-1 min-w-0 px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-sky-500/20 focus:border-sky-400 outline-none transition-all duration-200"
          />
          <button
            class="px-3.5 py-2.5 text-sm font-medium text-white bg-slate-800 rounded-xl hover:bg-slate-900 active:bg-black disabled:opacity-50 transition-all duration-200 whitespace-nowrap"
            :disabled="twitterSaving || !twitterAuthToken.trim()"
            @click="handleSaveTwitter"
          >
            {{ twitterSaving ? '保存中...' : '保存' }}
          </button>
        </div>
        <p class="mt-2 text-xs text-slate-400">
          获取方式：登录 x.com → F12 → Application → Cookies → 复制 <code class="px-1 py-0.5 bg-slate-100 rounded text-slate-500">auth_token</code>
        </p>
        <Transition
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="opacity-0 translate-y-1"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <p v-if="twitterSaveResult" class="mt-2 text-sm flex items-center gap-1.5"
             :class="twitterSaveResult.success ? 'text-emerald-600' : 'text-rose-600'">
            <svg v-if="twitterSaveResult.success" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            {{ twitterSaveResult.message }}
          </p>
        </Transition>
      </div>

      <!-- 微信读书凭证 -->
      <div class="p-4 bg-white rounded-xl border border-slate-200/60 shadow-sm">
        <div class="flex items-center gap-2 mb-3">
          <div class="w-7 h-7 rounded-lg flex items-center justify-center bg-emerald-50 text-emerald-600">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
            </svg>
          </div>
          <h4 class="text-sm font-semibold text-slate-700">微信读书凭证</h4>
        </div>
        <div class="flex gap-2">
          <input
            v-model="wechatCookie"
            type="password"
            placeholder="粘贴 Cookie 值"
            class="flex-1 min-w-0 px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400 outline-none transition-all duration-200"
          />
          <button
            class="px-3.5 py-2.5 text-sm font-medium text-white bg-emerald-600 rounded-xl hover:bg-emerald-700 active:bg-emerald-800 disabled:opacity-50 transition-all duration-200 whitespace-nowrap"
            :disabled="wechatSaving || !wechatCookie.trim()"
            @click="handleSaveWechat"
          >
            {{ wechatSaving ? '保存中...' : '保存' }}
          </button>
        </div>
        <p class="mt-2 text-xs text-slate-400">
          获取方式：登录 weread.qq.com → F12 → Network → 刷新页面 → 点击任意请求 → 复制 Request Headers 中的 <code class="px-1 py-0.5 bg-slate-100 rounded text-slate-500">Cookie</code> 值
        </p>
        <p class="mt-1 text-xs text-slate-400">
          Cookie 有效期约 1.5 小时，过期后需重新获取
        </p>
        <Transition
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="opacity-0 translate-y-1"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <p v-if="wechatSaveResult" class="mt-2 text-sm flex items-center gap-1.5"
             :class="wechatSaveResult.success ? 'text-emerald-600' : 'text-rose-600'">
            <svg v-if="wechatSaveResult.success" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            {{ wechatSaveResult.message }}
          </p>
        </Transition>
      </div>
    </div>

    <!-- 凭证列表 -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
      <div class="px-5 py-3 bg-slate-50/50 border-b border-slate-100">
        <h4 class="text-sm font-semibold text-slate-700">已保存的凭证</h4>
      </div>

      <div v-if="credLoading" class="flex items-center justify-center py-8">
        <svg class="w-6 h-6 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <div v-else-if="credentials.length === 0" class="text-center py-8">
        <p class="text-sm text-slate-400">暂无凭证，使用上方操作添加</p>
      </div>

      <div v-else class="divide-y divide-slate-100">
        <div
          v-for="cred in credentials"
          :key="cred.id"
          class="hover:bg-slate-50/50 transition-colors"
        >
          <div class="flex items-center justify-between p-4">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                 :class="cred.platform === 'bilibili' ? 'bg-pink-50 text-pink-500' : cred.platform === 'twitter' ? 'bg-sky-50 text-slate-800' : cred.platform === 'wechat_read' ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500'">
              <svg v-if="cred.platform === 'bilibili'" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17.813 4.653h.854c1.51.054 2.769.578 3.773 1.574 1.004.995 1.524 2.249 1.56 3.76v7.36c-.036 1.51-.556 2.769-1.56 3.773s-2.262 1.524-3.773 1.56H5.333c-1.51-.036-2.769-.556-3.773-1.56S.036 18.858 0 17.347v-7.36c.036-1.511.556-2.765 1.56-3.76 1.004-.996 2.262-1.52 3.773-1.574h.774l-1.174-1.12a1.234 1.234 0 0 1-.373-.906c0-.356.124-.658.373-.907l.027-.027c.267-.249.573-.373.92-.373.347 0 .653.124.92.373L9.653 4.44c.071.071.134.142.187.213h4.267a.836.836 0 0 1 .16-.213l2.853-2.747c.267-.249.573-.373.92-.373.347 0 .662.151.929.4.267.249.391.551.391.907 0 .355-.124.657-.373.906zM5.333 7.24c-.746.018-1.373.276-1.88.773-.506.498-.769 1.13-.786 1.894v7.52c.017.764.28 1.395.786 1.893.507.498 1.134.756 1.88.773h13.334c.746-.017 1.373-.275 1.88-.773.506-.498.769-1.129.786-1.893v-7.52c-.017-.765-.28-1.396-.786-1.894-.507-.497-1.134-.755-1.88-.773zM8 11.107c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373zm8 0c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373z"/>
              </svg>
              <svg v-else-if="cred.platform === 'twitter'" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
              </svg>
              <svg v-else-if="cred.platform === 'wechat_read'" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
              </svg>
            </div>
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-slate-800 truncate">{{ cred.display_name }}</span>
                <span class="px-1.5 py-0.5 text-xs font-medium rounded border" :class="statusBadge(cred.status)">
                  {{ statusLabel(cred.status) }}
                </span>
              </div>
              <p class="text-xs text-slate-400 mt-0.5">
                {{ cred.platform }} &middot; {{ cred.credential_data }} &middot;
                {{ cred.source_count }} 个数据源引用
              </p>
            </div>
          </div>

          <div class="flex items-center gap-1.5 shrink-0 ml-3 flex-wrap">
            <button
              v-if="['bilibili', 'twitter', 'wechat_read'].includes(cred.platform)"
              class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 transition-all duration-200"
              :disabled="!!credActionLoading[cred.id]"
              @click="handleCheckCredential(cred.id)"
            >
              {{ credActionLoading[cred.id] === 'checking' ? '检测中...' : '检测' }}
            </button>
            <button
              class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 transition-all duration-200"
              :disabled="!!credActionLoading[cred.id] || editingId === cred.id"
              @click="startEditing(cred.id)"
            >
              更新
            </button>
            <button
              v-if="['bilibili', 'twitter'].includes(cred.platform)"
              class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 transition-all duration-200"
              :disabled="!!credActionLoading[cred.id]"
              @click="handleSyncRsshub(cred.id)"
            >
              {{ credActionLoading[cred.id] === 'syncing' ? '同步中...' : '同步 RSSHub' }}
            </button>
            <button
              class="px-2.5 py-1.5 text-xs font-medium text-rose-600 bg-white border border-rose-200 rounded-lg hover:bg-rose-50 hover:border-rose-300 disabled:opacity-50 transition-all duration-200"
              :disabled="!!credActionLoading[cred.id]"
              @click="handleDeleteCredential(cred.id)"
            >
              {{ credActionLoading[cred.id] === 'deleting' ? '删除中...' : '删除' }}
            </button>
          </div>
        </div>

        <!-- 内联编辑区 -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          enter-from-class="opacity-0 -translate-y-1 max-h-0"
          enter-to-class="opacity-100 translate-y-0 max-h-20"
          leave-active-class="transition-all duration-150 ease-in"
          leave-from-class="opacity-100 max-h-20"
          leave-to-class="opacity-0 max-h-0"
        >
          <div v-if="editingId === cred.id" class="px-4 pb-4 flex items-center gap-2">
            <input
              v-model="editingValue"
              type="password"
              placeholder="粘贴新的凭证值"
              class="flex-1 min-w-0 px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
              @keyup.enter="handleUpdateCredential(cred.id)"
              @keyup.escape="cancelEditing"
            />
            <button
              class="px-3 py-2 text-xs font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50 transition-all duration-200 whitespace-nowrap"
              :disabled="!editingValue.trim() || credActionLoading[cred.id] === 'updating'"
              @click="handleUpdateCredential(cred.id)"
            >
              {{ credActionLoading[cred.id] === 'updating' ? '保存中...' : '保存' }}
            </button>
            <button
              class="px-3 py-2 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-all duration-200 whitespace-nowrap"
              @click="cancelEditing"
            >
              取消
            </button>
          </div>
        </Transition>
      </div>
    </div>
    </div>
  </div>
</template>
