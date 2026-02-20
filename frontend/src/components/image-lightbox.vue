<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  images: { type: Array, default: () => [] },
  startIndex: { type: Number, default: 0 },
})

const emit = defineEmits(['close'])

// --- State ---
const currentIndex = ref(0)
const hint = ref('')
let hintTimer = null

// Sync startIndex when lightbox opens
watch(() => props.visible, (val) => {
  if (val) {
    currentIndex.value = props.startIndex
    hint.value = ''
    translateX.value = 0
  }
})

// --- Computed ---
const currentSrc = computed(() => props.images[currentIndex.value] || '')
const total = computed(() => props.images.length)
const isFirst = computed(() => currentIndex.value === 0)
const isLast = computed(() => currentIndex.value === total.value - 1)

// --- Navigation ---
function showHint(msg) {
  hint.value = msg
  clearTimeout(hintTimer)
  hintTimer = setTimeout(() => { hint.value = '' }, 1500)
}

function goPrev() {
  if (currentIndex.value > 0) {
    currentIndex.value--
    translateX.value = 0
  } else {
    showHint('已是第一张')
  }
}

function goNext() {
  if (currentIndex.value < total.value - 1) {
    currentIndex.value++
    translateX.value = 0
  } else {
    showHint('已是最后一张')
  }
}

function close() {
  emit('close')
}

// --- Keyboard ---
function onKeydown(e) {
  if (!props.visible) return
  if (e.key === 'Escape') close()
  else if (e.key === 'ArrowLeft') goPrev()
  else if (e.key === 'ArrowRight') goNext()
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  clearTimeout(hintTimer)
})

// --- Touch gesture ---
const translateX = ref(0)
let touchStartX = 0
let touchStartY = 0
let touchLocked = false   // direction locked
let touchIsHorizontal = false
let isSwiping = false

function onTouchStart(e) {
  if (e.touches.length !== 1) return
  touchStartX = e.touches[0].clientX
  touchStartY = e.touches[0].clientY
  touchLocked = false
  touchIsHorizontal = false
  isSwiping = false
  translateX.value = 0
}

function onTouchMove(e) {
  if (e.touches.length !== 1) return
  const dx = e.touches[0].clientX - touchStartX
  const dy = e.touches[0].clientY - touchStartY

  // Lock direction on first significant movement
  if (!touchLocked) {
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return
    touchLocked = true
    touchIsHorizontal = Math.abs(dx) > Math.abs(dy)
  }

  if (!touchIsHorizontal) return

  e.preventDefault()
  isSwiping = true

  // Apply damping at boundaries
  const atBoundary = (dx > 0 && isFirst.value) || (dx < 0 && isLast.value)
  translateX.value = atBoundary ? dx * 0.3 : dx
}

function onTouchEnd() {
  if (!isSwiping) return

  const THRESHOLD = 60
  const dx = translateX.value

  if (Math.abs(dx) > THRESHOLD) {
    if (dx < 0 && !isLast.value) {
      goNext()
    } else if (dx > 0 && !isFirst.value) {
      goPrev()
    } else {
      // At boundary — bounce back + hint
      translateX.value = 0
      showHint(dx > 0 ? '已是第一张' : '已是最后一张')
    }
  } else {
    translateX.value = 0
  }

  isSwiping = false
}

// Expose for parent keyboard guard
defineExpose({ visible: computed(() => props.visible) })
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="visible"
        class="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 backdrop-blur-sm"
        @click.self="close"
        @touchstart.passive="onTouchStart"
        @touchmove="onTouchMove"
        @touchend.passive="onTouchEnd"
      >
        <!-- Close button -->
        <button
          class="absolute top-4 right-4 z-10 p-2 rounded-full bg-white/10 text-white/80 hover:bg-white/20 hover:text-white transition-all"
          @click="close"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <!-- Counter -->
        <div v-if="total > 1" class="absolute top-4 left-4 z-10 px-3 py-1.5 rounded-full bg-white/10 text-white/80 text-sm font-medium tabular-nums">
          {{ currentIndex + 1 }} / {{ total }}
        </div>

        <!-- Previous -->
        <button
          v-if="total > 1"
          class="absolute left-3 md:left-6 z-10 p-2 md:p-3 rounded-full transition-all hidden md:block"
          :class="isFirst
            ? 'bg-white/5 text-white/20 cursor-default'
            : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'"
          @click.stop="goPrev"
        >
          <svg class="w-5 h-5 md:w-6 md:h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>

        <!-- Image -->
        <img
          :key="currentSrc"
          :src="currentSrc"
          referrerpolicy="no-referrer"
          class="max-w-[92vw] max-h-[88vh] object-contain rounded-lg shadow-2xl select-none pointer-events-none"
          :style="{ transform: `translateX(${translateX}px)`, transition: isSwiping ? 'none' : 'transform 0.25s ease-out' }"
        />

        <!-- Next -->
        <button
          v-if="total > 1"
          class="absolute right-3 md:right-6 z-10 p-2 md:p-3 rounded-full transition-all hidden md:block"
          :class="isLast
            ? 'bg-white/5 text-white/20 cursor-default'
            : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'"
          @click.stop="goNext"
        >
          <svg class="w-5 h-5 md:w-6 md:h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </button>

        <!-- Boundary hint -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          enter-from-class="opacity-0 translate-y-2"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-300 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 -translate-y-1"
        >
          <div
            v-if="hint"
            class="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 px-4 py-2 rounded-full bg-white/15 text-white/90 text-sm font-medium backdrop-blur-sm"
          >
            {{ hint }}
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
