<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

const props = defineProps({
  platform: { type: String, required: true }, // 'bilibili' | 'wechat_read' | 'douban' | 'zhihu' | 'github_stars' | 'twitter'
})

const emit = defineEmits(['saved', 'close'])

// ─── Bilibili QR login ─────────────────────────────────────────────────────
const qrState = ref('idle') // idle | loading | ready | scanning | confirmed | expired
const qrImageUrl = ref('')
const qrKey = ref('')
let pollTimer = null
let qrTimeoutId = null
const QR_TIMEOUT_MS = 5 * 60 * 1000 // 5 minutes

// ─── WeChat Read ──────────────────────────────────────────────────────────
const webviewState = ref('idle') // idle | opening | waiting | success
const wrSkey = ref('')
const wrVid = ref('')

// ─── GitHub Stars ─────────────────────────────────────────────────────────
const githubToken = ref('')

// ─── Twitter ──────────────────────────────────────────────────────────────
const twitterAuthToken = ref('')
const twitterCt0Captured = ref(false) // true once WebView auto-captured ct0

// ─── Shared validation state ──────────────────────────────────────────────
const validating = ref(false)
const isValid = ref(null)

// ─── Event listeners cleanup ──────────────────────────────────────────────
let unlistenCookieCaptured = null

onMounted(async () => {
  if (props.platform === 'bilibili') {
    startQrLogin()
  }
  if (props.platform === 'wechat_read') {
    unlistenCookieCaptured = await listen('wechat-cookies-captured', () => {
      webviewState.value = 'success'
      setTimeout(() => emit('saved'), 1000)
    })
  }
  if (props.platform === 'douban') {
    unlistenCookieCaptured = await listen('douban-cookies-captured', () => {
      webviewState.value = 'success'
      setTimeout(() => emit('saved'), 1000)
    })
  }
  if (props.platform === 'zhihu') {
    unlistenCookieCaptured = await listen('zhihu-cookies-captured', () => {
      webviewState.value = 'success'
      setTimeout(() => emit('saved'), 1000)
    })
  }
  if (props.platform === 'twitter') {
    unlistenCookieCaptured = await listen('twitter-ct0-captured', () => {
      twitterCt0Captured.value = true
    })
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (qrTimeoutId) clearTimeout(qrTimeoutId)
  if (unlistenCookieCaptured) unlistenCookieCaptured()
})

// ─── Bilibili QR ──────────────────────────────────────────────────────────
async function startQrLogin() {
  qrState.value = 'loading'
  qrKey.value = ''
  qrImageUrl.value = ''
  try {
    const resp = await invoke('start_bilibili_qr_login')
    qrKey.value = resp.qrcode_key
    qrImageUrl.value = resp.qr_image_url
    qrState.value = 'ready'
    startPolling()
  } catch (e) {
    qrState.value = 'idle'
    alert('Failed to generate QR code: ' + e)
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer)
  if (qrTimeoutId) clearTimeout(qrTimeoutId)

  pollTimer = setInterval(async () => {
    if (!qrKey.value) return
    try {
      const resp = await invoke('poll_bilibili_qr_status', { qrcodeKey: qrKey.value })
      if (resp.code === 86090) {
        qrState.value = 'scanning'
      } else if (resp.code === 86038) {
        qrState.value = 'expired'
        clearInterval(pollTimer)
        clearTimeout(qrTimeoutId)
      } else if (resp.is_success) {
        qrState.value = 'confirmed'
        clearInterval(pollTimer)
        clearTimeout(qrTimeoutId)
        setTimeout(() => emit('saved'), 1000)
      }
    } catch (e) {
      console.error('QR poll error:', e)
    }
  }, 2000)

  // Client-side 5-minute timeout: stop polling and mark as expired
  qrTimeoutId = setTimeout(() => {
    if (qrState.value === 'ready' || qrState.value === 'scanning') {
      qrState.value = 'expired'
      clearInterval(pollTimer)
    }
  }, QR_TIMEOUT_MS)
}

// ─── WeChat Read WebView login ─────────────────────────────────────────────
async function openWechatWebView() {
  webviewState.value = 'opening'
  try {
    await invoke('open_wechat_webview')
    webviewState.value = 'waiting'
  } catch (e) {
    webviewState.value = 'idle'
    alert('Failed to open browser window: ' + e)
  }
}

function cancelWebview() {
  invoke('close_wechat_webview').catch(() => {})
  webviewState.value = 'idle'
}

// ─── Douban WebView login ──────────────────────────────────────────────────
async function openDoubanWebView() {
  webviewState.value = 'opening'
  try {
    await invoke('open_douban_webview')
    webviewState.value = 'waiting'
  } catch (e) {
    webviewState.value = 'idle'
    alert('Failed to open browser window: ' + e)
  }
}

function cancelDoubanWebview() {
  webviewState.value = 'idle'
}

// ─── Zhihu WebView login ───────────────────────────────────────────────────
async function openZhihuWebView() {
  webviewState.value = 'opening'
  try {
    await invoke('open_zhihu_webview')
    webviewState.value = 'waiting'
  } catch (e) {
    webviewState.value = 'idle'
    alert('Failed to open browser window: ' + e)
  }
}

function cancelZhihuWebview() {
  webviewState.value = 'idle'
}

// ─── GitHub Stars ─────────────────────────────────────────────────────────
async function saveGithubToken() {
  if (!githubToken.value) return
  isValid.value = null
  validating.value = true
  try {
    await invoke('set_credential', { key: 'github_token', value: githubToken.value })
    const valid = await invoke('validate_github_token')
    isValid.value = valid
    if (valid) {
      setTimeout(() => emit('saved'), 800)
    }
  } catch (e) {
    isValid.value = false
    alert('Failed to save token: ' + e)
  } finally {
    validating.value = false
  }
}

// ─── Twitter ──────────────────────────────────────────────────────────────
async function openTwitterWebView() {
  webviewState.value = 'opening'
  try {
    await invoke('open_twitter_webview')
    webviewState.value = 'waiting'
  } catch (e) {
    webviewState.value = 'idle'
    alert('Failed to open browser window: ' + e)
  }
}

async function saveTwitterCookies() {
  if (!twitterAuthToken.value) return
  isValid.value = null
  validating.value = true
  try {
    // We need ct0 — check if already stored or prompt
    let ct0 = ''
    try {
      ct0 = await invoke('get_credential', { key: 'twitter_ct0' }) || ''
    } catch {}
    if (!ct0) {
      alert('ct0 is required. Please open the browser window first to capture it automatically.')
      return
    }
    await invoke('save_twitter_cookies', { authToken: twitterAuthToken.value, ct0 })
    isValid.value = true
    setTimeout(() => emit('saved'), 800)
  } catch (e) {
    isValid.value = false
    alert('Failed to save Twitter credentials: ' + e)
  } finally {
    validating.value = false
  }
}

// ─── WeChat Read manual cookie form ───────────────────────────────────────
async function saveWechatCookies() {
  if (!wrSkey.value || !wrVid.value) return
  validating.value = true
  try {
    await invoke('set_credential', { key: 'wechat_read_skey', value: wrSkey.value })
    await invoke('set_credential', { key: 'wechat_read_vid', value: wrVid.value })
    const valid = await invoke('validate_wechat_read_cookie')
    isValid.value = valid
    if (valid) {
      setTimeout(() => emit('saved'), 800)
    }
  } catch (e) {
    isValid.value = false
    alert('Failed to save cookies: ' + e)
  } finally {
    validating.value = false
  }
}
</script>

<template>
  <div class="p-4">

    <!-- ── Bilibili: QR Login ───────────────────────────────────────────── -->
    <template v-if="platform === 'bilibili'">
      <h3 class="font-semibold text-gray-800 mb-1">Bilibili Login</h3>
      <p class="text-xs text-gray-500 mb-4">Scan with Bilibili mobile app</p>

      <div class="flex flex-col items-center gap-3">
        <div v-if="qrState === 'loading'" class="w-48 h-48 bg-gray-100 rounded-lg flex items-center justify-center">
          <svg class="w-8 h-8 text-gray-400 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        </div>

        <div v-else-if="qrState === 'ready' || qrState === 'scanning'" class="relative">
          <img :src="qrImageUrl" alt="QR Code" class="w-48 h-48 rounded-lg border border-gray-200" />
          <div v-if="qrState === 'scanning'" class="absolute inset-0 bg-white/80 rounded-lg flex items-center justify-center">
            <span class="text-sm font-medium text-blue-600">Scanned! Confirm in app...</span>
          </div>
        </div>

        <div v-else-if="qrState === 'confirmed'" class="w-48 h-48 bg-green-50 rounded-lg flex flex-col items-center justify-center gap-2">
          <span class="text-4xl">✓</span>
          <span class="text-sm font-medium text-green-700">Login successful!</span>
        </div>

        <div v-else-if="qrState === 'expired'" class="w-48 h-48 bg-gray-100 rounded-lg flex flex-col items-center justify-center gap-2">
          <span class="text-3xl text-gray-400">⏱</span>
          <span class="text-sm text-gray-500">QR code expired</span>
          <button @click="startQrLogin" class="px-3 py-1 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700">
            Refresh
          </button>
        </div>

        <p v-if="qrState === 'ready'" class="text-xs text-gray-400 text-center">
          Open Bilibili app → Scan QR · Expires in 5 min
        </p>
      </div>
    </template>

    <!-- ── WeChat Read: Login ──────────────────────────────────────────── -->
    <template v-else-if="platform === 'wechat_read'">
      <h3 class="font-semibold text-gray-800 mb-3">微信读书 Login</h3>

      <!-- WebView: waiting for login -->
      <template v-if="webviewState === 'waiting'">
        <div class="text-center py-4">
          <div class="text-3xl mb-2">🌐</div>
          <p class="text-sm font-medium text-gray-700 mb-1">Browser window opened</p>
          <p class="text-xs text-gray-500 mb-4 leading-relaxed">
            Log in to WeChat Read in the browser window.<br>
            Cookies will be captured automatically once logged in.
          </p>
          <button @click="cancelWebview" class="text-xs text-gray-400 hover:text-gray-600 underline">
            Cancel — enter cookies manually
          </button>
        </div>
      </template>

      <!-- WebView: success -->
      <template v-else-if="webviewState === 'success'">
        <div class="text-center py-6">
          <div class="text-4xl mb-2">✓</div>
          <p class="text-sm font-medium text-green-700">Logged in! Cookies saved.</p>
        </div>
      </template>

      <!-- Default: show browser login option + manual fallback -->
      <template v-else>
        <!-- Recommended: browser login -->
        <div class="mb-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
          <p class="text-xs text-blue-800 font-medium mb-1">Recommended: Login with browser</p>
          <p class="text-xs text-blue-600 mb-2">
            Opens WeChat Read in an in-app window. Cookies are captured automatically — no DevTools needed.
          </p>
          <button
            @click="openWechatWebView"
            :disabled="webviewState === 'opening'"
            class="w-full py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-60"
          >
            {{ webviewState === 'opening' ? 'Opening...' : '🌐 Open Browser Window' }}
          </button>
        </div>

        <!-- Divider -->
        <div class="flex items-center gap-2 mb-3">
          <div class="flex-1 border-t border-gray-200"></div>
          <span class="text-xs text-gray-400">or enter cookies manually</span>
          <div class="flex-1 border-t border-gray-200"></div>
        </div>

        <!-- Manual: cookie form -->
        <p class="text-xs text-gray-500 mb-3">
          Open <a href="https://weread.qq.com" target="_blank" class="text-blue-500 underline">weread.qq.com</a>,
          login, then open DevTools → Application → Cookies and copy the values below.
        </p>

        <div class="space-y-3">
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">wr_skey</label>
            <input
              v-model="wrSkey"
              type="password"
              placeholder="paste wr_skey value"
              class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">wr_vid</label>
            <input
              v-model="wrVid"
              type="text"
              placeholder="paste wr_vid value"
              class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div class="mt-3 flex items-center gap-2">
          <div v-if="isValid === true" class="text-xs text-green-600 font-medium">✓ Valid</div>
          <div v-else-if="isValid === false" class="text-xs text-red-500">✗ Invalid cookies</div>
        </div>

        <button
          @click="saveWechatCookies"
          :disabled="!wrSkey || !wrVid || validating"
          class="mt-4 w-full py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {{ validating ? 'Validating...' : 'Save & Validate' }}
        </button>
      </template>
    </template>

    <!-- ── Douban: WebView Login ───────────────────────────────────────── -->
    <template v-else-if="platform === 'douban'">
      <h3 class="font-semibold text-gray-800 mb-3">豆瓣 Login</h3>

      <template v-if="webviewState === 'waiting'">
        <div class="text-center py-4">
          <div class="text-3xl mb-2">🐟</div>
          <p class="text-sm font-medium text-gray-700 mb-1">Browser window opened</p>
          <p class="text-xs text-gray-500 mb-4 leading-relaxed">
            Log in to 豆瓣 in the browser window.<br>
            Cookies will be captured automatically once logged in.
          </p>
          <button @click="cancelDoubanWebview" class="text-xs text-gray-400 hover:text-gray-600 underline">
            Cancel
          </button>
        </div>
      </template>

      <template v-else-if="webviewState === 'success'">
        <div class="text-center py-6">
          <div class="text-4xl mb-2">✓</div>
          <p class="text-sm font-medium text-green-700">Logged in! Cookies saved.</p>
        </div>
      </template>

      <template v-else>
        <div class="mb-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
          <p class="text-xs text-blue-800 font-medium mb-1">Login with browser</p>
          <p class="text-xs text-blue-600 mb-2">
            Opens 豆瓣 in an in-app window. Cookies are captured automatically after login.
          </p>
          <button
            @click="openDoubanWebView"
            :disabled="webviewState === 'opening'"
            class="w-full py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-60"
          >
            {{ webviewState === 'opening' ? 'Opening...' : '🌐 Open Browser Window' }}
          </button>
        </div>
      </template>
    </template>

    <!-- ── GitHub Stars: PAT ──────────────────────────────────────────── -->
    <template v-else-if="platform === 'github_stars'">
      <h3 class="font-semibold text-gray-800 mb-3">GitHub Stars</h3>

      <p class="text-xs text-gray-500 mb-3 leading-relaxed">
        Create a Personal Access Token at
        <span class="text-blue-500">github.com → Settings → Developer settings → Personal access tokens</span>.
        No special scopes needed for public stars; add <code class="bg-gray-100 px-1 rounded">read:user</code> for private ones.
      </p>

      <div class="space-y-3">
        <div>
          <label class="block text-xs font-medium text-gray-700 mb-1">Personal Access Token</label>
          <input
            v-model="githubToken"
            type="password"
            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
            class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div class="mt-3 flex items-center gap-2">
        <div v-if="isValid === true" class="text-xs text-green-600 font-medium">✓ Token valid</div>
        <div v-else-if="isValid === false" class="text-xs text-red-500">✗ Invalid token</div>
      </div>

      <button
        @click="saveGithubToken"
        :disabled="!githubToken || validating"
        class="mt-4 w-full py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {{ validating ? 'Validating...' : 'Save & Validate' }}
      </button>
    </template>

    <!-- ── Twitter / X: Semi-auto login ───────────────────────────────── -->
    <template v-else-if="platform === 'twitter'">
      <h3 class="font-semibold text-gray-800 mb-3">Twitter / X Login</h3>

      <!-- Step 1: Open WebView to capture ct0 -->
      <div class="mb-4 p-3 rounded-lg border" :class="twitterCt0Captured ? 'bg-green-50 border-green-200' : 'bg-blue-50 border-blue-100'">
        <p class="text-xs font-medium mb-1" :class="twitterCt0Captured ? 'text-green-800' : 'text-blue-800'">
          {{ twitterCt0Captured ? '✓ Step 1 done — ct0 captured' : 'Step 1: Open browser and login' }}
        </p>
        <p v-if="twitterCt0Captured" class="text-xs text-green-700 mt-1">
          The browser window is still open — go there now, right-click → Inspect → Application → Cookies → x.com, then copy the <code class="bg-green-100 px-0.5 rounded">auth_token</code> value into Step 2 below.
        </p>
        <p v-if="!twitterCt0Captured" class="text-xs text-blue-600 mb-2">
          Opens x.com in an in-app window. The <code class="bg-blue-100 px-0.5 rounded">ct0</code> token will be captured automatically after login.
        </p>
        <button
          v-if="!twitterCt0Captured"
          @click="openTwitterWebView"
          :disabled="webviewState === 'opening' || webviewState === 'waiting'"
          class="w-full py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-60"
        >
          {{ webviewState === 'opening' ? 'Opening...' : webviewState === 'waiting' ? 'Waiting for login...' : '🌐 Open Browser Window' }}
        </button>
      </div>

      <!-- Step 2: Manually enter auth_token -->
      <div class="mb-4 p-3 bg-amber-50 rounded-lg border border-amber-100">
        <p class="text-xs font-medium text-amber-800 mb-1">Step 2: Copy auth_token from DevTools</p>
        <p class="text-xs text-amber-700 leading-relaxed">
          In the browser window → right-click → Inspect → Application → Cookies → x.com → find <code class="bg-amber-100 px-0.5 rounded">auth_token</code> and copy the value.
        </p>
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-700 mb-1">auth_token</label>
        <input
          v-model="twitterAuthToken"
          type="password"
          placeholder="paste auth_token value"
          class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div class="mt-3 flex items-center gap-2">
        <div v-if="isValid === true" class="text-xs text-green-600 font-medium">✓ Login successful</div>
        <div v-else-if="isValid === false" class="text-xs text-red-500">✗ Invalid credentials</div>
      </div>

      <button
        @click="saveTwitterCookies"
        :disabled="!twitterAuthToken || validating"
        class="mt-4 w-full py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {{ validating ? 'Verifying...' : 'Save & Verify' }}
      </button>
    </template>

    <!-- ── Zhihu: WebView Login ────────────────────────────────────────── -->
    <template v-else-if="platform === 'zhihu'">
      <h3 class="font-semibold text-gray-800 mb-3">知乎 Login</h3>

      <template v-if="webviewState === 'waiting'">
        <div class="text-center py-4">
          <div class="text-3xl mb-2">💬</div>
          <p class="text-sm font-medium text-gray-700 mb-1">Browser window opened</p>
          <p class="text-xs text-gray-500 mb-4 leading-relaxed">
            Log in to 知乎 in the browser window.<br>
            Cookies will be captured automatically once logged in.
          </p>
          <button @click="cancelZhihuWebview" class="text-xs text-gray-400 hover:text-gray-600 underline">
            Cancel
          </button>
        </div>
      </template>

      <template v-else-if="webviewState === 'success'">
        <div class="text-center py-6">
          <div class="text-4xl mb-2">✓</div>
          <p class="text-sm font-medium text-green-700">Logged in! Cookies saved.</p>
        </div>
      </template>

      <template v-else>
        <div class="mb-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
          <p class="text-xs text-blue-800 font-medium mb-1">Login with browser</p>
          <p class="text-xs text-blue-600 mb-2">
            Opens 知乎 in an in-app window. Cookies are captured automatically after login.
          </p>
          <button
            @click="openZhihuWebView"
            :disabled="webviewState === 'opening'"
            class="w-full py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-60"
          >
            {{ webviewState === 'opening' ? 'Opening...' : '🌐 Open Browser Window' }}
          </button>
        </div>
      </template>
    </template>

  </div>
</template>
