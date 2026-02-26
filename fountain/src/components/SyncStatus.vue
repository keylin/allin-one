<script setup>
defineProps({
  icon: { type: String, required: true },
  name: { type: String, required: true },
  platform: { type: String, required: true },
  status: { type: String, default: 'idle' },  // idle | syncing | success | error | needs_auth
  lastSync: { type: String, default: null },
  itemCount: { type: Number, default: 0 },
  itemLabel: { type: String, default: 'items' },
  error: { type: String, default: null },
  enabled: { type: Boolean, default: true },
})

const emit = defineEmits(['sync', 'fix-auth'])

function relativeTime(isoString) {
  if (!isoString) return null
  const now = new Date()
  const then = new Date(isoString)
  const diffMs = now - then
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  return `${diffDays}d ago`
}
</script>

<template>
  <div class="px-4 py-3 hover:bg-gray-50 transition-colors" :class="{ 'opacity-50': !enabled }">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2.5">
        <span class="text-lg leading-none">{{ icon }}</span>
        <div>
          <div class="flex items-center gap-1.5">
            <span class="font-medium text-gray-800">{{ name }}</span>
            <!-- Status badge -->
            <span v-if="status === 'syncing'" class="inline-flex items-center gap-1 text-xs text-blue-600">
              <svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              Syncing...
            </span>
            <span v-else-if="status === 'success'" class="text-xs text-green-600">
              ✓ {{ lastSync ? relativeTime(lastSync) : 'done' }}
            </span>
            <span v-else-if="status === 'error'" class="text-xs text-red-500">✗ Error</span>
            <span v-else-if="status === 'needs_auth'" class="text-xs text-amber-500">⚠ Auth expired</span>
            <span v-else-if="lastSync" class="text-xs text-gray-400">{{ relativeTime(lastSync) }}</span>
          </div>
          <div v-if="itemCount > 0" class="text-xs text-gray-400 mt-0.5">
            {{ itemCount.toLocaleString() }} {{ itemLabel }}
          </div>
          <div v-if="error && status === 'error'" class="text-xs text-red-400 mt-0.5 max-w-[200px] truncate">
            {{ error }}
          </div>
        </div>
      </div>

      <div class="flex items-center gap-1.5 no-drag">
        <button
          v-if="status === 'needs_auth'"
          @click="emit('fix-auth')"
          class="px-2 py-1 text-xs font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-md transition-colors"
        >
          Fix Auth
        </button>
        <button
          v-else
          @click="emit('sync')"
          :disabled="status === 'syncing' || !enabled"
          class="px-2 py-1 text-xs font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Sync
        </button>
      </div>
    </div>
  </div>
</template>

