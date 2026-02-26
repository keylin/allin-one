<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'

const props = defineProps({
  platform: { type: String, required: true }, // 'bilibili' | 'wechat_read'
})

const emit = defineEmits(['saved', 'close'])

// Bilibili QR login state
const qrState = ref('idle') // idle | loading | ready | scanning | confirmed | expired
const qrImageUrl = ref('')
const qrKey = ref('')
let pollTimer = null

// WeChat Read cookie form
const wrSkey = ref('')
const wrVid = ref('')

// Validation state
const validating = ref(false)
const isValid = ref(null)

onMounted(() => {
  if (props.platform === 'bilibili') {
    startQrLogin()
  }
})

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
  pollTimer = setInterval(async () => {
    if (!qrKey.value) return
    try {
      const resp = await invoke('poll_bilibili_qr_status', { qrcodeKey: qrKey.value })
      if (resp.code === 86090) {
        qrState.value = 'scanning'
      } else if (resp.code === 86038) {
        qrState.value = 'expired'
        clearInterval(pollTimer)
      } else if (resp.is_success) {
        qrState.value = 'confirmed'
        clearInterval(pollTimer)
        setTimeout(() => emit('saved'), 1000)
      }
    } catch (e) {
      console.error('QR poll error:', e)
    }
  }, 2000)
}

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

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="p-4">
    <!-- Bilibili: QR Login -->
    <template v-if="platform === 'bilibili'">
      <h3 class="font-semibold text-gray-800 mb-3">Bilibili Login</h3>
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
          Open Bilibili app → Scan QR
        </p>
      </div>
    </template>

    <!-- WeChat Read: Cookie form -->
    <template v-else-if="platform === 'wechat_read'">
      <h3 class="font-semibold text-gray-800 mb-1">WeChat Reading Cookies</h3>
      <p class="text-xs text-gray-500 mb-4">
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
  </div>
</template>
