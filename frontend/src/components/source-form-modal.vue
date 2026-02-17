<script setup>
import { ref, computed, watch, toRef, onMounted } from 'vue'
import { listTemplates } from '@/api/pipeline-templates'
import { useScrollLock } from '@/composables/useScrollLock'
import { listCredentialOptions } from '@/api/credentials'
import FinancePresetPicker from '@/components/finance-preset-picker.vue'
import FinanceAlertConfig from '@/components/finance-alert-config.vue'

const props = defineProps({
  visible: Boolean,
  source: { type: Object, default: null },
})

const emit = defineEmits(['submit', 'cancel'])
useScrollLock(toRef(props, 'visible'))

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

const templates = ref([])
const form = ref(getDefaultForm())

// 结构化配置（替代 config_json 文本框）
const configForm = ref({})

// AkShare 预设
const aksharePresetSelected = ref(false)
const akshareUserParams = ref([])
const akshareAlerts = ref([])

// B站凭证下拉
const biliCredentials = ref([])


function getDefaultForm() {
  return {
    name: '',
    source_type: 'rss.hub',
    url: '',
    description: '',
    schedule_enabled: true,
    schedule_mode: 'auto',
    schedule_interval_override: null,
    calculated_interval: null,
    pipeline_template_id: '',
    config_json: '',
    credential_id: '',
    auto_cleanup_enabled: false,
    retention_days: null,
  }
}

function getDefaultConfig(sourceType) {
  switch (sourceType) {
    case 'rss.hub':
      return { rsshub_route: '' }
    case 'web.scraper':
      return { item_selector: '', title_selector: '', link_selector: 'a', link_attr: 'href', author_selector: '', use_browserless: false }
    case 'api.akshare':
      return { indicator: '', category: '', params: '', title_field: '', id_fields: '', date_field: '', value_field: '', max_history: 120 }
    case 'account.bilibili':
      return { cookie: '', type: 'dynamic', media_id: '', max_items: 20 }
    case 'account.generic':
      return { api_url: '', method: 'GET', headers: '', items_path: '', title_field: 'title', url_field: 'url', id_field: 'id' }
    case 'rss.standard':
      return {}
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
    // AkShare 对象字段 → JSON 字符串
    if (merged.ohlcv_fields && typeof merged.ohlcv_fields === 'object') {
      merged.ohlcv_fields = JSON.stringify(merged.ohlcv_fields)
    }
    if (merged.nav_fields && typeof merged.nav_fields === 'object') {
      merged.nav_fields = JSON.stringify(merged.nav_fields)
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
  // JSON 对象字段 (akshare)
  if (typeof cfg.ohlcv_fields === 'string' && cfg.ohlcv_fields) {
    try { cfg.ohlcv_fields = JSON.parse(cfg.ohlcv_fields) } catch { delete cfg.ohlcv_fields }
  }
  if (typeof cfg.nav_fields === 'string' && cfg.nav_fields) {
    try { cfg.nav_fields = JSON.parse(cfg.nav_fields) } catch { delete cfg.nav_fields }
  }
  // 数值转换
  if (cfg.max_items !== undefined) cfg.max_items = Number(cfg.max_items) || 20
  if (cfg.max_history !== undefined) cfg.max_history = Number(cfg.max_history) || 120
  // AkShare alerts
  if (form.value.source_type === 'api.akshare' && akshareAlerts.value.length) {
    cfg.alerts = akshareAlerts.value.filter(a => a.threshold !== '' && a.threshold !== null).map(a => ({
      ...a,
      threshold: Number(a.threshold),
    }))
  }
  return Object.keys(cfg).length ? JSON.stringify(cfg) : null
}

// 有结构化配置的类型
const hasStructuredConfig = computed(() => ['rss.hub', 'rss.standard', 'web.scraper', 'api.akshare', 'account.bilibili', 'account.generic'].includes(form.value.source_type))

// 无额外配置的类型
const noConfigTypes = ['file.upload', 'user.note', 'system.notification']

watch(() => props.visible, async (val) => {
  if (val) {
    if (props.source) {
      form.value = {
        ...getDefaultForm(), ...props.source,
        pipeline_template_id: props.source.pipeline_template_id || '',
        credential_id: props.source.credential_id || '',
      }
      configForm.value = deserializeConfig(props.source.config_json, props.source.source_type)
      // 已有 akshare 配置时标记为已选预设
      if (props.source.source_type === 'api.akshare' && configForm.value.indicator) {
        aksharePresetSelected.value = true
        // 恢复 alerts
        try {
          const parsed = JSON.parse(props.source.config_json || '{}')
          akshareAlerts.value = parsed.alerts || []
        } catch { akshareAlerts.value = [] }
      }
    } else {
      form.value = getDefaultForm()
      configForm.value = getDefaultConfig(form.value.source_type)
      aksharePresetSelected.value = false
      akshareUserParams.value = []
      akshareAlerts.value = []
    }
    // 加载 B站凭证下拉
    try {
      const res = await listCredentialOptions({ platform: 'bilibili' })
      if (res.code === 0) biliCredentials.value = res.data
    } catch { /* ignore */ }
  } else {
    aksharePresetSelected.value = false
    akshareUserParams.value = []
    akshareAlerts.value = []
  }
})

watch(() => form.value.source_type, (newType) => {
  configForm.value = getDefaultConfig(newType)
  // 清理 akshare 状态
  aksharePresetSelected.value = false
  akshareUserParams.value = []
  akshareAlerts.value = []
})

onMounted(async () => {
  try {
    const res = await listTemplates()
    if (res.code === 0) templates.value = res.data
  } catch { /* ignore */ }
})

function handleSubmit() {
  if (!form.value.name.trim()) return
  const data = { ...form.value }
  if (!data.pipeline_template_id) data.pipeline_template_id = null
  if (!data.credential_id) data.credential_id = null
  if (!data.url) data.url = null
  if (!data.description) data.description = null
  if (!data.retention_days) data.retention_days = null
  if (!data.schedule_interval_override) data.schedule_interval_override = null
  // 移除只读的 calculated_interval（由服务端计算）
  delete data.calculated_interval
  // 序列化结构化配置
  if (hasStructuredConfig.value) {
    data.config_json = serializeConfig()
  } else {
    if (!data.config_json) data.config_json = null
  }
  emit('submit', data)
}

// ---- AkShare 预设选择 ----

function handlePresetSelect(preset) {
  aksharePresetSelected.value = true
  akshareUserParams.value = preset.user_params || []

  // Auto-fill form name if empty
  if (!form.value.name && preset.name) {
    form.value.name = preset.name
  }

  // For AkShare presets, use fixed mode with preset interval
  form.value.schedule_mode = 'fixed'
  form.value.schedule_interval_override = preset.schedule_interval || 3600

  // Build configForm
  const cfg = preset.config
  configForm.value = {
    indicator: cfg.indicator || '',
    category: cfg.category || '',
    params: cfg.params ? JSON.stringify(cfg.params, null, 2) : '',
    title_field: cfg.title_field || '',
    id_fields: Array.isArray(cfg.id_fields) ? cfg.id_fields.join(', ') : (cfg.id_fields || ''),
    date_field: cfg.date_field || '',
    value_field: cfg.value_field || '',
    max_history: cfg.max_history || 120,
  }
  // Pass through specialized fields as JSON
  if (cfg.ohlcv_fields) configForm.value.ohlcv_fields = JSON.stringify(cfg.ohlcv_fields)
  if (cfg.nav_fields) configForm.value.nav_fields = JSON.stringify(cfg.nav_fields)

  // If custom, show full form
  if (preset.isCustom) {
    aksharePresetSelected.value = false
    configForm.value = getDefaultConfig('api.akshare')
  }
}

function resetAksharePreset() {
  aksharePresetSelected.value = false
  akshareUserParams.value = []
  akshareAlerts.value = []
  configForm.value = getDefaultConfig('api.akshare')
}

function formatInterval(seconds) {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
  return `${Math.round(seconds / 3600)}小时`
}

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
          {{ source ? '编辑数据源' : '新增数据源' }}
        </h3>
        <p class="text-xs text-slate-400 mt-0.5">配置信息采集来源</p>
      </div>

      <form class="p-6 space-y-5" @submit.prevent="handleSubmit">
        <!-- 名称 -->
        <div>
          <label :class="labelClass">名称 *</label>
          <input v-model="form.name" type="text" required :class="inputClass" placeholder="例: 少数派 RSS" />
        </div>

        <!-- 数据源类型 -->
        <div>
          <label :class="labelClass">数据源类型 *</label>
          <select v-model="form.source_type" :class="selectClass">
            <option v-for="t in sourceTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </div>

        <!-- ========== 核心配置层（类型相关，紧跟类型选择） ========== -->

        <!-- RSSHub -->
        <div v-if="form.source_type === 'rss.hub'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">RSSHub 配置</h4>
          <div>
            <label :class="labelClass">RSSHub 路由 *</label>
            <input
              v-model="configForm.rsshub_route"
              type="text"
              :class="inputClass"
              placeholder="/bilibili/user/video/12345?limit=20"
              required
            />
            <p class="mt-1 text-xs text-slate-400">
              RSSHub 路由路径（以 / 开头，可包含查询参数），参考
              <a href="https://docs.rsshub.app" target="_blank" class="text-indigo-500 hover:underline">RSSHub 文档</a>
            </p>
          </div>
        </div>

        <!-- RSS Standard -->
        <div v-else-if="form.source_type === 'rss.standard'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">RSS/Atom 配置</h4>
          <div>
            <label :class="labelClass">Feed URL *</label>
            <input
              v-model="form.url"
              type="text"
              :class="inputClass"
              placeholder="https://example.com/feed.xml"
              required
            />
          </div>
        </div>

        <!-- Web Scraper -->
        <div v-else-if="form.source_type === 'web.scraper'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">网页抓取配置</h4>
          <div>
            <label :class="labelClass">目标 URL *</label>
            <input v-model="form.url" type="text" :class="inputClass" placeholder="https://example.com/articles" />
          </div>
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
          <div class="flex items-center justify-between">
            <h4 class="text-sm font-semibold text-slate-800">AkShare 配置</h4>
            <button
              v-if="aksharePresetSelected"
              type="button"
              class="text-xs text-slate-500 hover:text-slate-700 transition-colors"
              @click="resetAksharePreset"
            >
              重选预设
            </button>
          </div>

          <!-- Step 1: Preset picker (when not yet selected) -->
          <div v-if="!aksharePresetSelected && !source">
            <p class="text-xs text-slate-500 mb-3">选择预设指标或自定义配置</p>
            <FinancePresetPicker @select="handlePresetSelect" />
          </div>

          <!-- Step 2: Config form (after preset selected or editing) -->
          <template v-else>
            <!-- User params (e.g. symbol for stock) -->
            <div v-if="akshareUserParams.length" class="space-y-3 p-3 bg-amber-50/50 border border-amber-200/50 rounded-xl">
              <p class="text-xs font-medium text-amber-700">请填写以下参数:</p>
              <div v-for="param in akshareUserParams" :key="param">
                <label :class="labelClass">{{ param }} *</label>
                <input
                  :value="configForm.params ? (JSON.parse(configForm.params || '{}')[param] || '') : ''"
                  @input="(() => { const p = JSON.parse(configForm.params || '{}'); p[param] = $event.target.value; configForm.params = JSON.stringify(p, null, 2) })()"
                  type="text"
                  :class="inputClass"
                  :placeholder="param === 'symbol' ? '例: 000001 (股票代码)' : param"
                />
              </div>
            </div>

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
                <label :class="labelClass">分类</label>
                <select v-model="configForm.category" :class="selectClass">
                  <option value="">自动</option>
                  <option value="macro">宏观经济</option>
                  <option value="stock">A股行情</option>
                  <option value="fund">基金/ETF</option>
                </select>
              </div>
              <div>
                <label :class="labelClass">首次采集上限</label>
                <input v-model.number="configForm.max_history" type="number" min="10" max="5000" :class="inputClass" />
              </div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label :class="labelClass">标题字段</label>
                <input v-model="configForm.title_field" type="text" :class="inputClass" placeholder="日期" />
              </div>
              <div>
                <label :class="labelClass">日期字段</label>
                <input v-model="configForm.date_field" type="text" :class="inputClass" placeholder="日期" />
              </div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label :class="labelClass">ID 字段（逗号分隔）</label>
                <input v-model="configForm.id_fields" type="text" :class="inputClass" placeholder="日期" />
              </div>
              <div>
                <label :class="labelClass">数值字段</label>
                <input v-model="configForm.value_field" type="text" :class="inputClass" placeholder="全国居民消费价格指数" />
              </div>
            </div>

            <!-- Alert config -->
            <FinanceAlertConfig v-model="akshareAlerts" />
          </template>
        </div>

        <!-- Bilibili -->
        <div v-else-if="form.source_type === 'account.bilibili'" :class="sectionClass">
          <h4 class="text-sm font-semibold text-slate-800">B站账号配置</h4>

          <!-- 凭证选择 -->
          <div>
            <label :class="labelClass">关联凭证</label>
            <select v-model="form.credential_id" :class="selectClass">
              <option value="">不使用凭证（手动填写 Cookie）</option>
              <option v-for="c in biliCredentials" :key="c.id" :value="c.id">
                {{ c.display_name }}
                <template v-if="c.status !== 'active'"> ({{ c.status }})</template>
              </option>
            </select>
            <p class="mt-1.5 text-xs text-slate-400">
              <router-link to="/settings" class="text-indigo-500 hover:text-indigo-600 hover:underline transition-colors">前往设置管理凭证</router-link>
            </p>
          </div>

          <!-- 手动 Cookie 输入（当未选凭证时显示） -->
          <div v-if="!form.credential_id">
            <label :class="labelClass">Cookie</label>
            <input v-model="configForm.cookie" type="text" :class="inputClass" placeholder="SESSDATA=xxx; bili_jct=xxx" />
            <p class="mt-1.5 text-xs text-slate-400">建议在设置页通过扫码授权自动获取</p>
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

        <!-- ========== 辅助配置层 ========== -->

        <!-- 描述 -->
        <div>
          <label :class="labelClass">描述</label>
          <textarea v-model="form.description" rows="2" :class="[inputClass, 'resize-none']" placeholder="可选描述"></textarea>
        </div>

        <!-- 后置处理模板 -->
        <div>
          <label :class="labelClass">后置处理流水线</label>
          <select v-model="form.pipeline_template_id" :class="selectClass">
            <option value="">不绑定（仅自动预处理）</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <p class="mt-1 text-xs text-slate-400">预处理（媒体下载）自动执行，此处配置后续的分析、翻译、推送等</p>
        </div>

        <!-- 高级设置（折叠面板） -->
        <details class="group">
          <summary class="flex items-center justify-between cursor-pointer select-none p-4 bg-slate-50/50 rounded-xl border border-slate-100 hover:bg-slate-50 transition-colors">
            <span class="text-sm font-semibold text-slate-800">高级设置</span>
            <svg class="w-4 h-4 text-slate-400 transition-transform group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </summary>
          <div class="mt-4 space-y-5 pl-1">
            <!-- 定时采集 -->
            <div>
              <h4 class="text-sm font-medium text-slate-700 mb-2">定时调度</h4>
              <div class="flex items-center gap-3">
                <input
                  v-model="form.schedule_enabled"
                  type="checkbox"
                  id="schedule_enabled"
                  class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                />
                <label for="schedule_enabled" class="text-sm text-slate-600">启用定时采集</label>
              </div>

              <template v-if="form.schedule_enabled">
                <div class="mt-3">
                  <label :class="labelClass">调度模式</label>
                  <select v-model="form.schedule_mode" :class="selectClass">
                    <option value="auto">智能调度（根据活跃度自动调整）</option>
                    <option value="fixed">固定间隔</option>
                    <option value="manual">仅手动采集</option>
                  </select>
                </div>

                <!-- 固定模式：显示间隔输入框 -->
                <div v-if="form.schedule_mode === 'fixed'" class="mt-3">
                  <label :class="labelClass">采集间隔 (秒)</label>
                  <input v-model.number="form.schedule_interval_override" type="number" min="60" :class="inputClass" placeholder="例: 3600 (1小时)" />
                </div>

                <!-- 自动模式：显示系统计算的间隔（只读） -->
                <div v-else-if="form.schedule_mode === 'auto' && form.calculated_interval" class="mt-3">
                  <label :class="labelClass">当前计算间隔</label>
                  <div class="px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-600">
                    {{ formatInterval(form.calculated_interval) }}
                    <span class="text-xs text-slate-400 ml-2">(系统根据采集历史自动调整)</span>
                  </div>
                </div>

                <!-- 手动模式：提示信息 -->
                <div v-else-if="form.schedule_mode === 'manual'" class="mt-3">
                  <p class="text-sm text-slate-500 px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl">
                    手动模式下，数据源不会自动采集，仅通过手动触发或 API 调用采集。
                  </p>
                </div>
              </template>

              <p class="mt-2 text-xs text-slate-400">
                智能调度根据数据源的历史采集情况（新增内容数、成功率、趋势）动态调整采集频率。
              </p>
            </div>

            <!-- 内容保留 -->
            <div>
              <h4 class="text-sm font-medium text-slate-700 mb-2">内容保留</h4>
              <div class="flex items-center gap-3">
                <input
                  v-model="form.auto_cleanup_enabled"
                  type="checkbox"
                  id="auto_cleanup_enabled"
                  class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                />
                <label for="auto_cleanup_enabled" class="text-sm text-slate-600">启用自动清理</label>
              </div>
              <div v-if="form.auto_cleanup_enabled" class="mt-3">
                <label :class="labelClass">保留天数</label>
                <input v-model.number="form.retention_days" type="number" min="1" :class="inputClass" placeholder="留空则使用全局默认值" />
              </div>
              <p class="mt-2 text-xs text-slate-400">超过保留期的内容将自动删除，收藏或有笔记的内容不受影响</p>
            </div>
          </div>
        </details>

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
