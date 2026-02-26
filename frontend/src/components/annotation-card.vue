<script setup>
import { ref } from 'vue'
import { colorMap, colorOptions, annotationColor } from '@/config/annotation-colors'
import { formatTimeFull } from '@/utils/time'

const props = defineProps({
  annotation: { type: Object, required: true },
  showBookInfo: { type: Boolean, default: false },
  editable: { type: Boolean, default: false },
})

const emit = defineEmits(['update', 'delete', 'click-book'])

const editing = ref(false)
const editNote = ref('')
const editColor = ref('')

function startEdit() {
  editNote.value = props.annotation.note || ''
  editColor.value = props.annotation.color || 'yellow'
  editing.value = true
}

function cancelEdit() {
  editing.value = false
}

function saveEdit() {
  emit('update', {
    id: props.annotation.id,
    note: editNote.value,
    color: editColor.value,
  })
  editing.value = false
}

function handleDelete() {
  emit('delete', props.annotation.id)
}
</script>

<template>
  <div class="group/card flex gap-3 px-4 py-3.5 hover:bg-slate-50/80 transition-colors">
    <!-- Color bar -->
    <div class="w-1 shrink-0 rounded-full self-stretch" :class="annotationColor(annotation.color)" />
    <!-- Content -->
    <div class="flex-1 min-w-0">
      <!-- Book info (cross-book mode) -->
      <p
        v-if="showBookInfo && annotation.book_title"
        class="text-xs text-slate-400 mb-1 truncate cursor-pointer hover:text-indigo-500 transition-colors"
        @click="emit('click-book', annotation.content_id)"
      >
        {{ annotation.book_title }}
        <span v-if="annotation.book_author" class="text-slate-300">· {{ annotation.book_author }}</span>
      </p>

      <!-- Selected text -->
      <p v-if="annotation.selected_text" class="text-sm text-slate-700 leading-relaxed">
        {{ annotation.selected_text }}
      </p>

      <!-- Note (view mode) -->
      <p v-if="annotation.note && !editing" class="text-xs text-slate-500 mt-1.5 italic">
        {{ annotation.note }}
      </p>

      <!-- Inline edit mode -->
      <div v-if="editing" class="mt-2 space-y-2">
        <textarea
          v-model="editNote"
          rows="2"
          class="w-full text-sm text-slate-700 bg-white border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 resize-none transition-all"
          placeholder="添加笔记..."
        />
        <!-- Color picker -->
        <div class="flex items-center gap-2">
          <button
            v-for="c in colorOptions"
            :key="c"
            @click="editColor = c"
            class="w-5 h-5 rounded-full transition-all duration-150"
            :class="[
              colorMap[c],
              editColor === c ? 'ring-2 ring-offset-1 ring-slate-400 scale-110' : 'opacity-60 hover:opacity-100',
            ]"
          />
        </div>
        <div class="flex items-center gap-2">
          <button
            @click="saveEdit"
            class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            保存
          </button>
          <button
            @click="cancelEdit"
            class="px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors"
          >
            取消
          </button>
        </div>
      </div>

      <!-- Meta row -->
      <div class="flex items-center gap-1.5 mt-1.5 text-[10px] text-slate-300">
        <span v-if="annotation.location" class="text-slate-400">{{ annotation.location }}</span>
        <span v-if="annotation.location && annotation.created_at" class="text-slate-200">·</span>
        <span>{{ formatTimeFull(annotation.created_at) }}</span>
      </div>
    </div>

    <!-- Action buttons (desktop hover) -->
    <div v-if="editable && !editing" class="shrink-0 flex items-start gap-1 opacity-0 group-hover/card:opacity-100 transition-opacity">
      <button
        @click.stop="startEdit"
        class="p-1.5 text-slate-300 hover:text-indigo-500 rounded-lg hover:bg-indigo-50 transition-all"
        title="编辑"
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
        </svg>
      </button>
      <button
        @click.stop="handleDelete"
        class="p-1.5 text-slate-300 hover:text-rose-500 rounded-lg hover:bg-rose-50 transition-all"
        title="删除"
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
      </button>
    </div>
  </div>
</template>
