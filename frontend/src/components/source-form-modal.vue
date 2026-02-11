<script setup>
import { ref, watch, onMounted } from 'vue'
import { listTemplates } from '@/api/pipeline-templates'

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

watch(() => props.visible, (val) => {
  if (val) {
    form.value = props.source
      ? { ...getDefaultForm(), ...props.source, pipeline_template_id: props.source.pipeline_template_id || '' }
      : getDefaultForm()
  }
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
  if (!data.config_json) data.config_json = null
  if (!data.url) data.url = null
  if (!data.description) data.description = null
  emit('submit', data)
}

const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
const labelClass = 'block text-sm font-medium text-slate-700 mb-1.5'
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
        <div>
          <label :class="labelClass">名称 *</label>
          <input v-model="form.name" type="text" required :class="inputClass" placeholder="例: 少数派 RSS" />
        </div>

        <div class="grid grid-cols-2 gap-4">
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

        <div>
          <label :class="labelClass">URL</label>
          <input v-model="form.url" type="text" :class="inputClass" placeholder="订阅或抓取地址" />
        </div>

        <div>
          <label :class="labelClass">描述</label>
          <textarea v-model="form.description" rows="2" :class="[inputClass, 'resize-none']" placeholder="可选描述"></textarea>
        </div>

        <div>
          <label :class="labelClass">关联流水线模板</label>
          <select v-model="form.pipeline_template_id" :class="selectClass">
            <option value="">不绑定</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>

        <div class="grid grid-cols-2 gap-4">
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

        <div>
          <label :class="labelClass">扩展配置 (JSON)</label>
          <textarea v-model="form.config_json" rows="3" :class="[inputClass, 'font-mono resize-none']" placeholder='{"rsshub_route": "/bilibili/user/video/12345"}'></textarea>
        </div>

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
