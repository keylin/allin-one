<script setup>
import { ref, computed, watch, toRef, onMounted } from 'vue'
import { useScrollLock } from '@/composables/useScrollLock'
import { useToast } from '@/composables/useToast'
import { submitContent, uploadContent } from '@/api/content'
import { listTemplates } from '@/api/pipeline-templates'

const props = defineProps({
  visible: Boolean,
  source: { type: Object, default: null },
})

const emit = defineEmits(['success', 'cancel'])
useScrollLock(toRef(props, 'visible'))
const toast = useToast()

const templates = ref([])
const submitting = ref(false)

const form = ref({
  title: '',
  content: '',
  url: '',
  pipeline_template_id: '',
})

const fileRef = ref(null)
const selectedFile = ref(null)

const isFileUpload = computed(() => props.source?.source_type === 'file.upload')

watch(() => props.visible, async (val) => {
  if (val) {
    form.value = {
      title: '',
      content: '',
      url: '',
      pipeline_template_id: props.source?.pipeline_template_id || '',
    }
    selectedFile.value = null
    if (fileRef.value) fileRef.value.value = ''
  }
})

onMounted(async () => {
  try {
    const res = await listTemplates()
    if (res.code === 0) templates.value = res.data
  } catch { /* ignore */ }
})

function handleFileSelect(event) {
  const file = event.target.files?.[0]
  if (file) {
    selectedFile.value = file
    if (!form.value.title) {
      form.value.title = file.name
    }
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function handleSubmit() {
  if (!props.source) return
  if (!form.value.title.trim() && !isFileUpload.value) return
  if (isFileUpload.value && !selectedFile.value) return

  submitting.value = true
  try {
    let res
    if (isFileUpload.value) {
      const fd = new FormData()
      fd.append('file', selectedFile.value)
      fd.append('source_id', props.source.id)
      if (form.value.title) fd.append('title', form.value.title)
      if (form.value.pipeline_template_id) fd.append('pipeline_template_id', form.value.pipeline_template_id)
      res = await uploadContent(fd)
    } else {
      res = await submitContent({
        source_id: props.source.id,
        title: form.value.title,
        content: form.value.content || null,
        url: form.value.url || null,
        pipeline_template_id: form.value.pipeline_template_id || null,
      })
    }

    if (res.code === 0) {
      emit('success', res.data)
    } else {
      toast.error(res.message || '提交失败')
    }
  } catch (e) {
    toast.error('提交请求失败')
  } finally {
    submitting.value = false
  }
}

const inputClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-base sm:text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200'
const selectClass = 'w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-base sm:text-sm text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200 appearance-none cursor-pointer'
const labelClass = 'block text-sm font-medium text-slate-700 mb-1.5'
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="emit('cancel')"></div>
    <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
      <div class="sticky top-0 bg-white border-b border-slate-100 px-6 py-5 rounded-t-2xl z-10">
        <h3 class="text-lg font-semibold text-slate-900 tracking-tight">
          {{ isFileUpload ? '上传文件' : '添加内容' }}
        </h3>
        <p class="text-xs text-slate-400 mt-0.5">
          提交到「{{ source?.name }}」
        </p>
      </div>

      <form class="p-6 space-y-5" @submit.prevent="handleSubmit">
        <!-- 文件上传 -->
        <div v-if="isFileUpload">
          <label :class="labelClass">文件 *</label>
          <div
            class="relative border-2 border-dashed border-slate-200 rounded-xl p-6 text-center hover:border-indigo-300 transition-colors cursor-pointer"
            @click="fileRef?.click()"
          >
            <input
              ref="fileRef"
              type="file"
              class="hidden"
              @change="handleFileSelect"
            />
            <template v-if="selectedFile">
              <div class="flex items-center justify-center gap-3">
                <svg class="w-8 h-8 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <div class="text-left">
                  <p class="text-sm font-medium text-slate-700">{{ selectedFile.name }}</p>
                  <p class="text-xs text-slate-400">{{ formatFileSize(selectedFile.size) }}</p>
                </div>
              </div>
              <p class="text-xs text-slate-400 mt-2">点击重新选择</p>
            </template>
            <template v-else>
              <svg class="w-10 h-10 text-slate-300 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <p class="text-sm text-slate-500">点击选择文件</p>
              <p class="text-xs text-slate-400 mt-1">支持图片、视频、音频、文档等格式</p>
            </template>
          </div>
        </div>

        <!-- 标题 -->
        <div>
          <label :class="labelClass">{{ isFileUpload ? '标题（可选）' : '标题 *' }}</label>
          <input
            v-model="form.title"
            type="text"
            :class="inputClass"
            :placeholder="isFileUpload ? '留空则使用文件名' : '输入标题'"
            :required="!isFileUpload"
          />
        </div>

        <!-- 内容 (仅文本提交) -->
        <div v-if="!isFileUpload">
          <label :class="labelClass">内容</label>
          <textarea
            v-model="form.content"
            rows="8"
            :class="[inputClass, 'resize-none font-mono text-sm']"
            placeholder="输入文本内容（支持 Markdown）..."
          ></textarea>
        </div>

        <!-- URL (仅文本提交) -->
        <div v-if="!isFileUpload">
          <label :class="labelClass">关联 URL</label>
          <input
            v-model="form.url"
            type="text"
            :class="inputClass"
            placeholder="https://..."
          />
          <p class="mt-1 text-xs text-slate-400">可选，关联的外部链接</p>
        </div>

        <!-- 流水线模板 -->
        <div>
          <label :class="labelClass">处理流水线</label>
          <select v-model="form.pipeline_template_id" :class="selectClass">
            <option value="">不处理</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <p class="mt-1 text-xs text-slate-400">选择后将自动触发流水线处理</p>
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
            :disabled="submitting"
            class="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200 disabled:opacity-50"
          >
            {{ submitting ? '提交中...' : (isFileUpload ? '上传' : '提交') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
