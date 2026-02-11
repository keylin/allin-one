<script setup>
const props = defineProps({
  visible: Boolean,
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '确定要执行此操作吗？' },
  confirmText: { type: String, default: '确定' },
  cancelText: { type: String, default: '取消' },
  danger: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <Transition name="modal">
    <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="emit('cancel')"></div>
      <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-md p-6 transform transition-all">
        <div class="flex items-start gap-4">
          <div
            class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            :class="danger ? 'bg-rose-50' : 'bg-indigo-50'"
          >
            <svg
              class="w-5 h-5"
              :class="danger ? 'text-rose-600' : 'text-indigo-600'"
              fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"
            >
              <path v-if="danger" stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              <path v-else stroke-linecap="round" stroke-linejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div class="flex-1">
            <h3 class="text-base font-semibold text-slate-900 tracking-tight">{{ title }}</h3>
            <p class="text-sm text-slate-500 mt-1.5 leading-relaxed">{{ message }}</p>
          </div>
        </div>
        <div class="flex justify-end gap-3 mt-6">
          <button
            class="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
            @click="emit('cancel')"
          >
            {{ cancelText }}
          </button>
          <button
            class="px-4 py-2.5 text-sm font-medium text-white rounded-xl shadow-sm transition-all duration-200"
            :class="danger ? 'bg-rose-600 hover:bg-rose-700 active:bg-rose-800 shadow-rose-200' : 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 shadow-indigo-200'"
            @click="emit('confirm')"
          >
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
