<script setup>
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { ref, watch, computed } from 'vue'
import ToastNotification from '@/components/toast-notification.vue'

const route = useRoute()
const router = useRouter()

const sidebarOpen = ref(false)

const navItems = [
  { path: '/feed', label: '信息流', icon: 'M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z' },
  { path: '/favorites', label: '我的收藏', icon: 'M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z' },
  { path: '/dashboard', label: '仪表盘', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { path: '/sources', label: '数据源', icon: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' },
  { path: '/content', label: '内容库', icon: 'M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4' },
  { path: '/pipelines', label: '流水线', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
  { path: '/videos', label: '视频管理', icon: 'M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z' },
  { path: '/finance', label: '金融数据', icon: 'M3 3v18h18M7 16l4-4 3 3 5-6' },
  { path: '/settings', label: '系统设置', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z' },
]

const isActive = (path) => route.path === path
const isLoginPage = computed(() => route.path === '/login')
const hasApiKey = computed(() => !!localStorage.getItem('api_key'))

function handleLogout() {
  localStorage.removeItem('api_key')
  router.push('/login')
}

// 路由切换时自动关闭侧边栏
watch(() => route.path, () => {
  sidebarOpen.value = false
})
</script>

<template>
  <div class="flex h-screen bg-slate-50/50">
    <!-- Global Toast Notifications -->
    <ToastNotification />

    <!-- Login 页面：不显示侧边栏 -->
    <template v-if="isLoginPage">
      <main class="flex-1 overflow-auto">
        <RouterView />
      </main>
    </template>

    <template v-else>
    <!-- Mobile Header -->
    <div class="fixed top-0 left-0 right-0 z-40 md:hidden bg-white/80 backdrop-blur-md border-b border-slate-200/60">
      <div class="flex items-center justify-between px-4 h-14">
        <button
          class="p-2 -ml-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          @click="sidebarOpen = true"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>
        <h1 class="text-sm font-bold tracking-tight text-slate-900">Allin-One</h1>
        <div class="w-10"></div>
      </div>
    </div>

    <!-- Mobile Sidebar Overlay -->
    <Transition
      enter-active-class="transition-opacity duration-300"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-200"
      leave-to-class="opacity-0"
    >
      <div
        v-if="sidebarOpen"
        class="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm md:hidden"
        @click="sidebarOpen = false"
      ></div>
    </Transition>

    <!-- Sidebar -->
    <aside
      class="fixed md:static inset-y-0 left-0 z-50 w-60 bg-slate-50/80 md:bg-transparent flex flex-col transform transition-transform duration-300 ease-in-out md:translate-x-0"
      :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="p-5 flex items-center justify-between">
        <div>
          <h1 class="text-lg font-bold tracking-tight text-slate-900">Allin-One</h1>
          <p class="text-xs text-slate-400 mt-0.5">信息聚合与智能分析</p>
        </div>
        <button
          class="md:hidden p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          @click="sidebarOpen = false"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="group flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200"
          :class="isActive(item.path)
            ? 'bg-white text-slate-900 font-medium shadow-sm'
            : 'text-slate-500 hover:bg-white/60 hover:text-slate-700'"
        >
          <svg
            class="w-5 h-5 shrink-0 transition-colors duration-200"
            :class="isActive(item.path) ? 'text-slate-700' : 'text-slate-400 group-hover:text-slate-500'"
            fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"
          >
            <path stroke-linecap="round" stroke-linejoin="round" :d="item.icon" />
          </svg>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="p-4 flex items-center justify-between">
        <div class="text-xs text-slate-300">v1.0.0</div>
        <button
          v-if="hasApiKey"
          @click="handleLogout"
          class="text-xs text-slate-400 hover:text-slate-600 transition-colors"
          title="退出登录"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
          </svg>
        </button>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-hidden pt-14 md:pt-0">
      <RouterView />
    </main>
    </template>
  </div>
</template>
