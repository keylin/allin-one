<script setup>
import { ref, computed } from 'vue'

defineOptions({ name: 'JsonTreeNode' })

const props = defineProps({
  data: { type: [Object, Array, String, Number, Boolean], default: null },
  nodeKey: { type: String, default: null },
  nodeValue: { default: undefined },
  depth: { type: Number, default: 0 },
  defaultExpandDepth: { type: Number, default: 2 },
  isLast: { type: Boolean, default: true },
  isRoot: { type: Boolean, default: true },
})

const STRING_TRUNCATE_LENGTH = 200

// Root-level: parse data prop
const parsedData = computed(() => {
  if (!props.isRoot) return null
  if (props.data == null) return null
  if (typeof props.data === 'object') return props.data
  if (typeof props.data === 'string') {
    try {
      return JSON.parse(props.data)
    } catch {
      return null // parse failed, will fallback
    }
  }
  return props.data
})

const parseFailed = computed(() => {
  if (!props.isRoot) return false
  return props.data != null && parsedData.value === null && typeof props.data === 'string'
})

// The actual value this node represents
const value = computed(() => props.isRoot ? parsedData.value : props.nodeValue)

const isObject = computed(() => value.value !== null && typeof value.value === 'object' && !Array.isArray(value.value))
const isArray = computed(() => Array.isArray(value.value))
const isExpandable = computed(() => isObject.value || isArray.value)

const expanded = ref(props.depth < props.defaultExpandDepth)

const entries = computed(() => {
  if (isObject.value) return Object.entries(value.value)
  if (isArray.value) return value.value.map((v, i) => [String(i), v])
  return []
})

const previewText = computed(() => {
  if (isObject.value) {
    const keys = Object.keys(value.value).length
    return `{${keys} key${keys !== 1 ? 's' : ''}}`
  }
  if (isArray.value) {
    return `Array(${value.value.length})`
  }
  return ''
})

// String truncation
const stringExpanded = ref(false)
const isLongString = computed(() => typeof value.value === 'string' && value.value.length > STRING_TRUNCATE_LENGTH)
const displayString = computed(() => {
  if (typeof value.value !== 'string') return ''
  if (isLongString.value && !stringExpanded.value) {
    return value.value.slice(0, STRING_TRUNCATE_LENGTH) + '...'
  }
  return value.value
})

function valueClass(val) {
  if (val === null || val === undefined) return 'text-slate-500 italic'
  switch (typeof val) {
    case 'string': return 'text-emerald-400'
    case 'number': return 'text-sky-400'
    case 'boolean': return 'text-violet-400'
    default: return 'text-slate-300'
  }
}

function formatPrimitive(val) {
  if (val === null) return 'null'
  if (val === undefined) return 'undefined'
  if (typeof val === 'string') return `"${displayString.value}"`
  return String(val)
}

function toggle() {
  expanded.value = !expanded.value
}
</script>

<template>
  <!-- Root wrapper -->
  <div v-if="isRoot" class="font-mono text-xs leading-relaxed max-h-[70vh] overflow-auto custom-scrollbar">
    <!-- Parse failed fallback -->
    <pre v-if="parseFailed" class="text-slate-200 whitespace-pre-wrap break-words">{{ data }}</pre>
    <!-- Primitive at root level -->
    <span v-else-if="!isExpandable" :class="valueClass(value)">{{ formatPrimitive(value) }}</span>
    <!-- Expandable root -->
    <JsonTreeNode
      v-else
      :node-value="value"
      :depth="0"
      :default-expand-depth="defaultExpandDepth"
      :is-root="false"
      :is-last="true"
    />
  </div>

  <!-- Recursive node (non-root) -->
  <div v-else class="select-text">
    <!-- Key + expandable value -->
    <div class="flex items-start">
      <!-- Indent -->
      <span v-if="nodeKey !== null" class="shrink-0" :style="{ width: depth * 16 + 'px' }"></span>
      <span v-else :style="{ width: depth * 16 + 'px' }"></span>

      <!-- Toggle arrow for expandable -->
      <button
        v-if="isExpandable"
        class="shrink-0 w-4 h-4 flex items-center justify-center text-slate-500 hover:text-slate-300 transition-colors mr-0.5"
        @click="toggle"
      >
        <svg
          class="w-3 h-3 transition-transform duration-150"
          :class="{ 'rotate-90': expanded }"
          fill="currentColor"
          viewBox="0 0 20 20"
        >
          <path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
        </svg>
      </button>
      <span v-else class="shrink-0 w-4 mr-0.5"></span>

      <!-- Key name -->
      <span v-if="nodeKey !== null" class="text-indigo-400 shrink-0">"{{ nodeKey }}"</span>
      <span v-if="nodeKey !== null" class="text-slate-500 mx-1">:</span>

      <!-- Expandable: bracket + preview when collapsed -->
      <template v-if="isExpandable">
        <span class="text-slate-400 cursor-pointer hover:text-slate-200" @click="toggle">
          {{ isArray ? '[' : '{' }}
        </span>
        <span v-if="!expanded" class="text-slate-600 cursor-pointer hover:text-slate-400 mx-1" @click="toggle">
          {{ previewText }}
        </span>
        <span v-if="!expanded" class="text-slate-400 cursor-pointer hover:text-slate-200" @click="toggle">
          {{ isArray ? ']' : '}' }}{{ isLast ? '' : ',' }}
        </span>
      </template>

      <!-- Primitive value -->
      <template v-else>
        <span :class="valueClass(value)">{{ formatPrimitive(value) }}</span>
        <button
          v-if="isLongString"
          class="ml-2 text-indigo-500 hover:text-indigo-300 transition-colors text-[10px] shrink-0"
          @click="stringExpanded = !stringExpanded"
        >
          {{ stringExpanded ? 'show less' : 'show more' }}
        </button>
        <span v-if="!isLast" class="text-slate-500">,</span>
      </template>
    </div>

    <!-- Expanded children -->
    <template v-if="isExpandable && expanded">
      <JsonTreeNode
        v-for="([k, v], i) in entries"
        :key="k"
        :node-key="k"
        :node-value="v"
        :depth="depth + 1"
        :default-expand-depth="defaultExpandDepth"
        :is-root="false"
        :is-last="i === entries.length - 1"
      />
      <!-- Closing bracket -->
      <div class="flex">
        <span :style="{ width: depth * 16 + 'px' }"></span>
        <span class="w-4 mr-0.5"></span>
        <span class="text-slate-400">{{ isArray ? ']' : '}' }}{{ isLast ? '' : ',' }}</span>
      </div>
    </template>
  </div>
</template>
