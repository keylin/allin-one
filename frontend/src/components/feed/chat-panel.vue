<script setup>
const props = defineProps({
  messages: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  input: { type: String, default: '' },
})

const emit = defineEmits(['update:input', 'send', 'cancel', 'clear', 'keydown'])
</script>

<template>
  <!-- AI 对话消息（嵌入内容区域） -->
  <div v-if="messages.length" class="space-y-3 pt-0">
    <div class="flex items-center gap-2 text-xs text-slate-400">
      <div class="flex-1 border-t border-slate-200"></div>
      <span>AI 对话</span>
      <div class="flex-1 border-t border-slate-200"></div>
    </div>
    <div
      v-for="(msg, idx) in messages"
      :key="idx"
      class="flex"
      :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
    >
      <div
        class="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed transition-all duration-200"
        :class="msg.role === 'user'
          ? 'bg-indigo-600 text-white rounded-br-md shadow-sm'
          : 'bg-slate-50 text-slate-700 rounded-bl-md border border-slate-200/50'"
      >
        <div
          v-if="msg.role === 'assistant'"
          class="prose prose-sm max-w-none chat-markdown"
          v-html="msg.renderedContent || ''"
        ></div>
        <template v-else>{{ msg.content }}</template>
        <span
          v-if="msg.role === 'assistant' && loading && idx === messages.length - 1"
          class="inline-block w-1.5 h-4 bg-slate-400 ml-0.5 animate-pulse rounded-sm align-middle"
        ></span>
      </div>
    </div>
    <slot name="messages-end"></slot>
  </div>
</template>

<style scoped>
/* AI 对话气泡内 markdown */
.chat-markdown :deep(p) {
  margin-bottom: 0.5em;
  line-height: 1.6;
}
.chat-markdown :deep(p:last-child) {
  margin-bottom: 0;
}
.chat-markdown :deep(code) {
  background: rgba(0,0,0,0.04);
  padding: 0.15em 0.3em;
  border-radius: 0.25em;
  font-size: 0.9em;
}
.chat-markdown :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 0.75em;
  border-radius: 0.5em;
  overflow-x: auto;
  margin: 0.5em 0;
}
.chat-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.chat-markdown :deep(ul),
.chat-markdown :deep(ol) {
  padding-left: 1.25em;
  margin-bottom: 0.5em;
}
.chat-markdown :deep(li) {
  margin-bottom: 0.25em;
}
.chat-markdown :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}
</style>
