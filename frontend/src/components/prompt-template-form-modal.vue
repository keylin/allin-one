<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  visible: Boolean,
  template: { type: Object, default: null },
})

const emit = defineEmits(['submit', 'cancel'])

const templateTypes = [
  { value: 'news_analysis', label: '新闻分析' },
  { value: 'summary', label: '摘要' },
  { value: 'translation', label: '翻译' },
  { value: 'custom', label: '自定义' },
]

const outputFormats = [
  { value: 'json', label: 'JSON' },
  { value: 'markdown', label: 'Markdown' },
  { value: 'text', label: '纯文本' },
]

const form = ref(getDefaultForm())

function getDefaultForm() {
  return {
    name: '',
    template_type: 'news_analysis',
    system_prompt: '',
    user_prompt: '',
    output_format: 'markdown',
    is_default: false,
  }
}

watch(() => props.visible, (val) => {
  if (val) {
    form.value = props.template
      ? { ...getDefaultForm(), ...props.template }
      : getDefaultForm()
  }
})

function handleSubmit() {
  if (!form.value.name.trim() || !form.value.user_prompt.trim()) return
  const data = { ...form.value }
  if (!data.system_prompt) data.system_prompt = null
  emit('submit', data)
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
          {{ template ? '编辑提示词模板' : '创建提示词模板' }}
        </h3>
        <p class="text-xs text-slate-400 mt-0.5">配置 LLM 分析指令</p>
      </div>

      <form class="p-6 space-y-5" @submit.prevent="handleSubmit">
        <div>
          <label :class="labelClass">名称 *</label>
          <input v-model="form.name" type="text" required :class="inputClass" placeholder="例: 新闻摘要分析" />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label :class="labelClass">模板类型</label>
            <select v-model="form.template_type" :class="selectClass">
              <option v-for="t in templateTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </div>
          <div>
            <label :class="labelClass">输出格式</label>
            <select v-model="form.output_format" :class="selectClass">
              <option v-for="f in outputFormats" :key="f.value" :value="f.value">{{ f.label }}</option>
            </select>
          </div>
        </div>

        <div>
          <label :class="labelClass">System Prompt</label>
          <textarea v-model="form.system_prompt" rows="3" :class="[inputClass, 'font-mono resize-none']" placeholder="系统角色提示词（可选）"></textarea>
        </div>

        <div>
          <label :class="labelClass">User Prompt *</label>
          <textarea v-model="form.user_prompt" rows="6" required :class="[inputClass, 'font-mono resize-none']" placeholder="用户提示词模板，使用 {{content}} 引用内容"></textarea>
        </div>

        <div class="flex items-center gap-3">
          <input v-model="form.is_default" type="checkbox" id="is_default" class="h-4 w-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500" />
          <label for="is_default" class="text-sm font-medium text-slate-700">设为默认模板</label>
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
            {{ template ? '保存修改' : '创建' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
