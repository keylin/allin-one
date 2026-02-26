<script setup>
import { ref } from 'vue'
import { colorMap, colorOptions } from '@/config/annotation-colors'

const emit = defineEmits(['submit', 'cancel'])

const selectedText = ref('')
const note = ref('')
const color = ref('yellow')
const location = ref('')

function handleSubmit() {
  if (!selectedText.value.trim() && !note.value.trim()) return
  emit('submit', {
    selected_text: selectedText.value.trim() || null,
    note: note.value.trim() || null,
    color: color.value,
    location: location.value.trim() || null,
    type: note.value.trim() && !selectedText.value.trim() ? 'note' : 'highlight',
  })
  selectedText.value = ''
  note.value = ''
  color.value = 'yellow'
  location.value = ''
}
</script>

<template>
  <div class="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
    <h4 class="text-sm font-medium text-slate-700">添加标注</h4>
    <textarea
      v-model="selectedText"
      rows="2"
      class="w-full text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white resize-none transition-all"
      placeholder="划线文本..."
    />
    <textarea
      v-model="note"
      rows="2"
      class="w-full text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white resize-none transition-all"
      placeholder="笔记（可选）..."
    />
    <input
      v-model="location"
      type="text"
      class="w-full text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white transition-all"
      placeholder="章节名（可选）..."
    />
    <!-- Color picker -->
    <div class="flex items-center gap-2">
      <span class="text-xs text-slate-400">颜色</span>
      <button
        v-for="c in colorOptions"
        :key="c"
        @click="color = c"
        class="w-5 h-5 rounded-full transition-all duration-150"
        :class="[
          colorMap[c],
          color === c ? 'ring-2 ring-offset-1 ring-slate-400 scale-110' : 'opacity-60 hover:opacity-100',
        ]"
      />
    </div>
    <div class="flex items-center gap-2 pt-1">
      <button
        @click="handleSubmit"
        :disabled="!selectedText.trim() && !note.trim()"
        class="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        添加
      </button>
      <button
        @click="emit('cancel')"
        class="px-4 py-1.5 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors"
      >
        取消
      </button>
    </div>
  </div>
</template>
