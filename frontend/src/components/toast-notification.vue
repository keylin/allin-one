<script setup>
import { useToast } from '@/composables/useToast'
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from 'lucide-vue-next'

const { toasts, removeToast } = useToast()

// Toast 类型配置（使用 Lucide 图标）
const typeConfig = {
  success: {
    bg: 'bg-emerald-50 border-emerald-200',
    icon: 'text-emerald-600',
    title: 'text-emerald-900',
    message: 'text-emerald-700',
    component: CheckCircle2
  },
  error: {
    bg: 'bg-rose-50 border-rose-200',
    icon: 'text-rose-600',
    title: 'text-rose-900',
    message: 'text-rose-700',
    component: XCircle
  },
  warning: {
    bg: 'bg-amber-50 border-amber-200',
    icon: 'text-amber-600',
    title: 'text-amber-900',
    message: 'text-amber-700',
    component: AlertTriangle
  },
  info: {
    bg: 'bg-blue-50 border-blue-200',
    icon: 'text-blue-600',
    title: 'text-blue-900',
    message: 'text-blue-700',
    component: Info
  }
}

const getTypeConfig = (type) => typeConfig[type] || typeConfig.info
</script>

<template>
  <!-- Toast Container (右上角固定) -->
  <div class="fixed top-4 right-4 z-50 flex flex-col gap-3 pointer-events-none">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="pointer-events-auto min-w-[320px] max-w-md rounded-xl border shadow-lg transition-all duration-200"
        :class="getTypeConfig(toast.type).bg"
      >
        <div class="flex items-start gap-3 p-4">
          <!-- Icon (Lucide) -->
          <component
            :is="getTypeConfig(toast.type).component"
            :class="getTypeConfig(toast.type).icon"
            :size="20"
            class="flex-shrink-0 mt-0.5"
          />

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <h4
              v-if="toast.title"
              class="text-sm font-semibold mb-1"
              :class="getTypeConfig(toast.type).title"
            >
              {{ toast.title }}
            </h4>
            <p
              class="text-sm leading-relaxed"
              :class="getTypeConfig(toast.type).message"
            >
              {{ toast.message }}
            </p>
          </div>

          <!-- Close Button (Lucide) -->
          <button
            @click="removeToast(toast.id)"
            class="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="关闭"
          >
            <X :size="16" />
          </button>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
/* Toast 动画 */
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%) scale(0.9);
}

.toast-move {
  transition: transform 0.3s ease;
}
</style>
