<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { listTemplates } from '@/api/pipeline-templates'
import { generateBilibiliQrcode, pollBilibiliQrcode } from '@/api/sources'
import QRCode from 'qrcode'

const props = defineProps({
  visible: Boolean,
  source: { type: Object, default: null },
})

const emit = defineEmits(['submit', 'cancel'])

const sourceTypes = [
  { value: 'rss.hub', label: 'RSSHub' },
  { value: 'rss.standard', label: 'RSS/Atom' },
  { value: 'api.akshare', label: 'AkShare' },
  { value: 'web.scraper', label: '网页抓取' },
  { value: 'file.upload', label: '文件上传' },
  { value: 'account.bilibili', label: 'B站账号' },
  { value: 'account.generic', label: '其他账号' },
  { value: 'user.note', label: '用户笔记' },
  { value: 'system.notification', label: '系统通知' },
]

const mediaTypes = [
  { value: 'text', label: '文本' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
  { value: 'audio', label: '音频' },
  { value: 'mixed', label: '混合' },
]

const templates = ref([])
const form = ref(getDefaultForm())

// 结构化配置（替代 config_json 文本框）
const configForm = ref({})

// B站授权状态
const biliAuthStatus = ref('idle') // idle | loading | waiting | scanned | success | expired | error
const biliQrcodeUrl = ref('')
const biliQrcodeKey = ref('')
const qrcodeCanvas = ref(null)
let biliPollTimer = null

function getDefaultForm() {
  return {
    name: '',
    source_type: 'rss.hub',
    url: '',
    description: '',
    media_type: 'text',
    schedule_enabled: true,
    schedule_interval: 3600,
    pipeline_template_id: '',
    config_json: '',
  }
}

function getDefaultConfig(sourceType) {
  switch (sourceType) {
    case 'rss.hub':
      return { rsshub_route: '' }
    case 'web.scraper':
      return { item_selector: '', title_selector: '', link_selector: 'a', link_attr: 'href', author_selector: '', use_browserless: false }
    case 'api.akshare':
      return { indicator: '', params: '', title_field: '', id_fields: '' }
    case 'account.bilibili':
      return { cookie: '', type: 'dynamic', media_id: '', max_items: 20 }
    case 'account.generic':
      return { api_url: '', method: 'GET', headers: '', items_path: '', title_field: 'title', url_field: 'url', id_field: 'id' }
    default:
      return {}
  }
}

function deserializeConfig(jsonStr, sourceType) {
  const defaults = getDefaultConfig(sourceType)
  try {
    const parsed = JSON.parse(jsonStr || '{}')
    const merged = { ...defaults, ...parsed }
    // 数组 → 逗号分隔字符串 (用于表单显示)
    if (Array.isArray(merged.id_fields)) {
      merged.id_fields = merged.id_fields.join(', ')
    }
    // 对象 → JSON 字符串 (用于 textarea 显示)
    if (merged.params && typeof merged.params === 'object') {
      merged.params = JSON.stringify(merged.params, null, 2)
    }
    if (merged.headers && typeof merged.headers === 'object') {
      merged.headers = JSON.stringify(merged.headers, null, 2)
    }
    return merged
  } catch {
    return { ...defaults }
  }
}

function serializeConfig() {
  const cfg = { ...configForm.value }
  // 清理空值（保留 false 和 0）
  Object.keys(cfg).forEach(k => {
    if (cfg[k] === '' || cfg[k] === null || cfg[k] === undefined) delete cfg[k]
  })
  // 显式移除 false 的布尔值（collector 用 .get() 默认就是 false）
  if (cfg.use_browserless === false) delete cfg.use_browserless
  // 解析 JSON 字段
  if (typeof cfg.params === 'string' && cfg.params) {
    try { cfg.params = JSON.parse(cfg.params) } catch { /* keep as string */ }
  }
  if (typeof cfg.headers === 'string' && cfg.headers) {
    try { cfg.headers = JSON.parse(cfg.headers) } catch { /* keep as string */ }
  }
  // 解析逗号分隔字段
  if (typeof cfg.id_fields === 'string' && cfg.id_fields) {
    cfg.id_fields = cfg.id_fields.split(',').map(s => s.trim()).filter(Boolean)
  }
  // 数值转换
  if (cfg.max_items !== undefined) cfg.max_items = Number(cfg.max_items) || 20
  return Object.keys(cfg).length ? JSON.stringify(cfg) : null
}

// 需要 URL 字段的类型
const needsUrl = computed(() => !['account.bilibili', 'file.upload', 'user.note', 'system.notification'].includes(form.value.source_type))

// 有结构化配置的类型
const hasStructuredConfig = computed(() => ['rss.hub', 'web.scraper', 'api.akshare', 'account.bilibili', 'account.generic'].includes(form.value.source_type))

// 无额外配置的类型
const noConfigTypes = ['rss.standard', 'file.upload', 'user.note', 'system.notification']

watch(() => props.visible, (val) => {
  if (val) {
    if (props.source) {
      form.value = { ...getDefaultForm(), ...props.source, pipeline_template_id: props.source.pipeline_template_id || '' }
      configForm.value = deserializeConfig(props.source.config_json, props.source.source_type)
      // 已有 bilibili cookie 时标记已授权
      if (props.source.source_type === 'account.bilibili' && configForm.value.cookie) {
        biliAuthStatus.value = 'success'
      }
    } else {
      form.value = getDefaultForm()
      configForm.value = getDefaultConfig(form.value.source_type)
      biliAuthStatus.value = 'idle'
    }
  } else {
    clearBiliPoll()
    biliAuthStatus.value = 'idle'
    biliQrcodeUrl.value = ''
    biliQrcodeKey.value = ''
  }
})

watch(() => form.value.source_type, (newType) => {
  configForm.value = getDefaultConfig(newType)
  // 自动设置媒体类型
  if (newType === 'account.bilibili') {
    form.value.media_type = 'mixed'
  }
  // 清理 bilibili 相关状态
  clearBiliPoll()
  biliAuthStatus.value = 'idle'
  biliQrcodeUrl.value = ''
  biliQrcodeKey.value = ''
})

onMounted(async () => {
  try {
    const res = await listTemplates()
    if (res.code === 0) templates.value = res.data
  } catch { /* ignore */ }
})

onBeforeUnmount(() => {
  clearBiliPoll()
})

function handleSubmit() {
  if (!form.value.name.trim()) return
  const data = { ...form.value }
  if (!data.pipeline_template_id) data.pipeline_template_id = null
  if (!data.url) data.url = null
  if (!data.description) data.description = null
  // 序列化结构化配置
  if (hasStructuredConfig.value) {
    data.config_json = serializeConfig()
  } else {
    if (!data.config_json) data.config_json = null
  }
  emit('submit', data)
}

// ---- B站扫码授权 ----

async function startBiliAuth() {
  biliAuthStatus.value = 'loading'
  try {
    const res = await generateBilibiliQrcode()
    if (res.code !== 0) {
      biliAuthStatus.value = 'error'
      return
    }
    biliQrcodeUrl.value = res.data.url
    biliQrcodeKey.value = res.data.qrcode_key
    biliAuthStatus.value = 'waiting'

    // 渲染二维码
    await nextTick()
    if (qrcodeCanvas.value) {
      QRCode.toCanvas(qrcodeCanvas.value, res.data.url, { width: 200, margin: 2 })
    }

    // 开始轮询
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
      configForm.value.cookie = res.data.cookie
      clearBiliPoll()
    }
  } catch { /* ignore poll errors */ }
}

function clearBiliPoll() {
  if (biliPollTimer) {
    clearInterval(biliPollTimer)
    biliPollTimer = null
  }
}

const biliStatusText = computed(() => {
  switch (biliAuthStatus.value) {
    case 'loading': return '正在生成二维码...'
    case 'waiting': return '请使用B站 App 扫描二维码'
    case 'scanned': return '已扫码，请在手机上确认'
    case 'success': return '授权成功'
    case 'expired': return '二维码已过期'
    case 'error': return '生成二维码失败'
    default: return ''
  }
})

const biliStatusColor = computed(() => {
  switch (biliAuthStatus.value) {
    case 'success': return 'text-emerald-600'
    case 'expired': case 'error': return 'text-red-500'
    case 'scanned': return 'text-amber-600'
    default: return 'text-slate-500'
  }
})

const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
const labelClass = 'block text-sm font-medium text-slate-700 mb-1.5'
const sectionClass = 'space-y-4 p-4 bg-slate-50/50 rounded-xl border border-slate-100'
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="emit('cancel')"></div>
    <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
      <div class="sticky top-0 bg-white border-b border-slate-100 px-6 py-5 rounded-t-2xl z-10">
        <h3 class="text-lg font-semibold text-slate-900 tracking-tight">
          {{ source ? '编辑数据源' : '添加数据源' }}
        </h3>
        <p class="text-xs text-slate-400 mt-0.5">配置信息采集来源</p>
      </div>

      <form class="p-6 space-y-5" @submit.prevent="handleSubmit">
        <!-- 名称 -->
        <div>
          <label :class="labelClass">名称 *</label>
          <input v-model="form.name" type="text" required :class="inputClass" placeholder="例: 少数派 RSS" />
        </div>

        <!-- 类型 + 媒体类型 -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label :class="labelClass">数据源类型 *</label>
            <select v-model="form.source_type" :class="selectClass">
              <option v-for="t in sourceTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </div>
          <div>
            <label :class="labelClass">媒体类型</label>
            <select v-model="form.media_type" :class="selectClass">
              <option v-for="t in mediaTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </div>
        </div>

        <!-- URL（按类型显示） -->
        <div v-if="needsUrl">
          <label :class="labelClass">URL</label>
          <input v-model="form.url" type="text" :class="inputClass" placeholder="订阅或抓取地址" />
        </div>

        <!-- 描述 -->
        <div>
          <label :class="labelClass">描述</label>
          <textarea v-model="form.description" rows="2" :class="[inputClass, 'resize-none']" placeholder="可选描述"></textarea>
        </div>

        <!-- 关联模板 -->
        <div>
          <label :class="labelClass">关联流水线模板</label>
          <select v-model="form.pipeline_template_id" :class="selectClass">
            <option value="">不绑定</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>

        <!-- 定时采集 -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div class="flex items-center gap-3 pt-6">
            <input
              v-model="form.schedule_enabled"
              type="checkbox"
              id="schedule_enabled"
              class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
            />
            <label for="schedule_enabled" class="text-sm font-medium text-slate-700">启用定时采集</label>
          </div>
          <div>
            <label :class="labelClass">采集间隔 (秒)</label>
            <input v-model.number="form.schedule_interval" type="number" min="60" :class="inputClass" />
          </div>
        </div>

        <!-- ========== 结构化配置区域 ========== -->

        <!-- RSSHub -->
        <div v-if="form.source_type === 'rss.hub'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">RSSHub 配置</h4>
          <div>
            <label :class="labelClass">RSSHub 路由</label>
            <input v-model="configForm.rsshub_route" type="text" :class="inputClass" placeholder="/bilibili/user/video/12345" />
            <p class="mt-1 text-xs text-slate-400">RSSHub 路由路径，参考 <a href="https://docs.rsshub.app" target="_blank" class="text-indigo-500 hover:underline">RSSHub 文档</a></p>
          </div>
        </div>

        <!-- RSS Standard -->
        <div v-else-if="form.source_type === 'rss.standard'" :class="sectionClass">
          <p class="text-sm text-slate-500">标准 RSS/Atom 订阅，只需在上方填写 Feed URL 即可。</p>
        </div>

        <!-- Web Scraper -->
        <div v-else-if="form.source_type === 'web.scraper'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">网页抓取配置</h4>
          <div>
            <label :class="labelClass">条目选择器 *</label>
            <input v-model="configForm.item_selector" type="text" :class="inputClass" placeholder=".article-item" />
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label :class="labelClass">标题选择器</label>
              <input v-model="configForm.title_selector" type="text" :class="inputClass" placeholder="h2" />
            </div>
            <div>
              <label :class="labelClass">链接选择器</label>
              <input v-model="configForm.link_selector" type="text" :class="inputClass" placeholder="a" />
            </div>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label :class="labelClass">链接属性</label>
              <input v-model="configForm.link_attr" type="text" :class="inputClass" placeholder="href" />
            </div>
            <div>
              <label :class="labelClass">作者选择器</label>
              <input v-model="configForm.author_selector" type="text" :class="inputClass" placeholder=".author" />
            </div>
          </div>
          <div class="flex items-center gap-3">
            <input
              v-model="configForm.use_browserless"
              type="checkbox"
              id="use_browserless"
              class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
            />
            <label for="use_browserless" class="text-sm text-slate-700">使用无头浏览器（动态页面）</label>
          </div>
        </div>

        <!-- AkShare -->
        <div v-else-if="form.source_type === 'api.akshare'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">AkShare 配置</h4>
          <div>
            <label :class="labelClass">指标名称 *</label>
            <input v-model="configForm.indicator" type="text" :class="inputClass" placeholder="macro_china_cpi" />
          </div>
          <div>
            <label :class="labelClass">参数 (JSON)</label>
            <textarea v-model="configForm.params" rows="2" :class="[inputClass, 'font-mono resize-none text-xs']" placeholder='{"start_date": "20240101"}'></textarea>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label :class="labelClass">标题字段</label>
              <input v-model="configForm.title_field" type="text" :class="inputClass" placeholder="date" />
            </div>
            <div>
              <label :class="labelClass">ID 字段（逗号分隔）</label>
              <input v-model="configForm.id_fields" type="text" :class="inputClass" placeholder="date,indicator" />
            </div>
          </div>
        </div>

        <!-- Bilibili -->
        <div v-else-if="form.source_type === 'account.bilibili'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">B站账号配置</h4>

          <!-- 授权区域 -->
          <div class="p-4 bg-white rounded-xl border border-slate-200">
            <div class="flex items-center justify-between mb-3">
              <span class="text-sm font-medium text-slate-700">账号授权</span>
              <span v-if="biliAuthStatus === 'success'" class="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-50 text-emerald-700 text-xs font-medium rounded-full">
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                已授权
              </span>
            </div>

            <!-- 未授权 / 过期 -->
            <div v-if="biliAuthStatus === 'idle' || biliAuthStatus === 'expired' || biliAuthStatus === 'error'">
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-white bg-pink-500 rounded-lg hover:bg-pink-600 active:bg-pink-700 transition-all duration-200"
                @click="startBiliAuth"
              >
                {{ biliAuthStatus === 'expired' ? '重新扫码' : '扫码授权' }}
              </button>
              <p v-if="biliAuthStatus === 'expired'" class="mt-2 text-xs text-red-500">二维码已过期，请重新扫码</p>
              <p v-if="biliAuthStatus === 'error'" class="mt-2 text-xs text-red-500">生成二维码失败，请重试</p>
            </div>

            <!-- 加载中 -->
            <div v-else-if="biliAuthStatus === 'loading'" class="flex items-center gap-2 text-sm text-slate-500">
              <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              正在生成二维码...
            </div>

            <!-- QR 码展示 -->
            <div v-else-if="biliAuthStatus === 'waiting' || biliAuthStatus === 'scanned'" class="flex flex-col items-center gap-3">
              <canvas ref="qrcodeCanvas" class="rounded-lg border border-slate-200"></canvas>
              <p :class="['text-sm font-medium', biliStatusColor]">{{ biliStatusText }}</p>
              <div v-if="biliAuthStatus === 'waiting'" class="flex items-center gap-1.5 text-xs text-slate-400">
                <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                等待扫码中...
              </div>
            </div>

            <!-- 已授权 -->
            <div v-else-if="biliAuthStatus === 'success'" class="space-y-2">
              <p class="text-sm text-emerald-600">Cookie 已获取，可正常采集。</p>
              <button
                type="button"
                class="text-xs text-slate-500 hover:text-slate-700 underline transition-colors"
                @click="startBiliAuth"
              >
                重新授权
              </button>
            </div>
          </div>

          <!-- 采集参数 -->
          <div>
            <label :class="labelClass">采集类型</label>
            <select v-model="configForm.type" :class="selectClass">
              <option value="dynamic">动态</option>
              <option value="favorites">收藏夹</option>
              <option value="history">历史记录</option>
            </select>
          </div>
          <div v-if="configForm.type === 'favorites'">
            <label :class="labelClass">收藏夹 ID</label>
            <input v-model="configForm.media_id" type="text" :class="inputClass" placeholder="收藏夹 media_id" />
          </div>
          <div>
            <label :class="labelClass">最大条目数</label>
            <input v-model.number="configForm.max_items" type="number" min="1" max="100" :class="inputClass" />
          </div>
        </div>

        <!-- Generic Account -->
        <div v-else-if="form.source_type === 'account.generic'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">通用账号配置</h4>
          <div>
            <label :class="labelClass">API 地址 *</label>
            <input v-model="configForm.api_url" type="text" :class="inputClass" placeholder="https://api.example.com/posts" />
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label :class="labelClass">请求方式</label>
              <select v-model="configForm.method" :class="selectClass">
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
            </div>
            <div>
              <label :class="labelClass">数据路径 *</label>
              <input v-model="configForm.items_path" type="text" :class="inputClass" placeholder="data.items" />
            </div>
          </div>
          <div>
            <label :class="labelClass">请求头 (JSON)</label>
            <textarea v-model="configForm.headers" rows="2" :class="[inputClass, 'font-mono resize-none text-xs']" placeholder='{"Authorization": "Bearer xxx"}'></textarea>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label :class="labelClass">标题字段</label>
              <input v-model="configForm.title_field" type="text" :class="inputClass" placeholder="title" />
            </div>
            <div>
              <label :class="labelClass">URL 字段</label>
              <input v-model="configForm.url_field" type="text" :class="inputClass" placeholder="url" />
            </div>
            <div>
              <label :class="labelClass">ID 字段</label>
              <input v-model="configForm.id_field" type="text" :class="inputClass" placeholder="id" />
            </div>
          </div>
        </div>

        <!-- File Upload / User Note / System Notification -->
        <div v-else-if="noConfigTypes.includes(form.source_type)" :class="sectionClass">
          <p class="text-sm text-slate-500">
            <template v-if="form.source_type === 'file.upload'">文件上传类型无需额外配置。</template>
            <template v-else-if="form.source_type === 'user.note'">用户笔记类型无需额外配置。</template>
            <template v-else>系统通知类型无需额外配置。</template>
          </p>
        </div>

        <!-- 按钮 -->
        <div class="flex justify-end gap-3 pt-5 border-t border-slate-100">
          <button
            type="button"
            class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
            @click="emit('cancel')"
          >
            取消
          </button>
          <button
            type="submit"
            class="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
          >
            {{ source ? '保存修改' : '创建' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
