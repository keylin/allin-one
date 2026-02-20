<script setup>
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { ref, watch, computed } from 'vue'
import ToastNotification from '@/components/toast-notification.vue'

const route = useRoute()
const router = useRouter()

const sidebarOpen = ref(false)

// 顶部导航栏项目（内容消费）
const topNavItems = [
  { path: '/feed', label: '首页', icon: 'M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25' },
  { path: '/favorites', label: '收藏', icon: 'M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z' },
  { path: '/finance', label: '数据', icon: 'M3 3v18h18M7 16l4-4 3 3 5-6' },
]

// 侧边栏项目（管理功能）
const sidebarNavItems = [
  { path: '/dashboard', label: '仪表盘', group: null, icon: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z' },
  { path: '/sources', label: '数据源', group: '管理', icon: 'M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z' },
  { path: '/content', label: '内容库', group: '管理', icon: 'M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z' },
  { path: '/pipelines', label: '流水线', group: '管理', icon: 'M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5' },
  { path: '/media', label: '媒体管理', group: '管理', icon: 'M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-1.5-3.75h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5' },
  { path: '/settings', label: '系统设置', group: '系统', icon: 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z M15 12a3 3 0 11-6 0 3 3 0 016 0z' },
]

// 按分组聚合，保留顺序
const sidebarGroups = computed(() => {
  const result = []
  let currentGroup = undefined
  for (const item of sidebarNavItems) {
    if (item.group !== currentGroup) {
      currentGroup = item.group
      result.push({ label: item.group, items: [] })
    }
    result[result.length - 1].items.push(item)
  }
  return result
})

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
  <div class="app-root">
    <!-- Global Toast Notifications -->
    <ToastNotification />

    <!-- Login 页面：不显示导航 -->
    <template v-if="isLoginPage">
      <main class="flex-1 overflow-auto">
        <RouterView />
      </main>
    </template>

    <template v-else>
    <!-- ===== 顶部导航栏 ===== -->
    <header class="top-navbar">
      <div class="top-navbar-inner">
        <!-- 移动端侧边栏触发按钮（最左侧） -->
        <button
          class="mobile-menu-btn"
          @click="sidebarOpen = true"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>
        <!-- 品牌（移动端隐藏） -->
        <div class="top-navbar-brand">
          <h1>Allin-One</h1>
        </div>
        <!-- 导航标签 -->
        <nav class="top-navbar-tabs">
          <RouterLink
            v-for="item in topNavItems"
            :key="item.path"
            :to="item.path"
            class="top-tab"
            :class="{ active: isActive(item.path) }"
          >
            <svg class="top-tab-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="item.icon" />
            </svg>
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
        <!-- 右侧占位（桌面端保持居中对称） -->
        <div class="top-navbar-right"></div>
      </div>
    </header>

    <!-- 下方：侧边栏 + 主内容 -->
    <div class="below-topbar">
      <!-- Mobile Sidebar Overlay -->
      <Transition
        enter-active-class="transition-opacity duration-300"
        enter-from-class="opacity-0"
        leave-active-class="transition-opacity duration-200"
        leave-to-class="opacity-0"
      >
        <div
          v-if="sidebarOpen"
          class="sidebar-overlay"
          @click="sidebarOpen = false"
        ></div>
      </Transition>

      <!-- Sidebar -->
      <aside
        class="sidebar"
        :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'"
      >
        <div class="sidebar-header">
          <h2 class="sidebar-brand">Allin-One</h2>
          <button
            class="sidebar-close-btn"
            @click="sidebarOpen = false"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <nav class="sidebar-nav">
          <RouterLink
            v-for="item in sidebarNavItems"
            :key="item.path"
            :to="item.path"
            class="sidebar-link"
            :class="{ active: isActive(item.path) }"
          >
            <svg
              class="sidebar-link-icon"
              :class="{ active: isActive(item.path) }"
              fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"
            >
              <path stroke-linecap="round" stroke-linejoin="round" :d="item.icon" />
            </svg>
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="sidebar-footer">
          <button
            v-if="hasApiKey"
            @click="handleLogout"
            class="sidebar-logout-btn"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
            </svg>
            <span>退出登录</span>
          </button>
          <span class="sidebar-version">v1.0.0</span>
        </div>
      </aside>

      <!-- Main Content -->
      <main class="main-content">
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" :key="$route.path" />
          </Transition>
        </RouterView>
      </main>
    </div>
    </template>
  </div>
</template>

<style scoped>
/* ===== Layout Root ===== */
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  background: rgb(248 250 252 / 0.5);
}

/* ===== Top Navigation Bar ===== */
.top-navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 30;
  height: calc(48px + env(safe-area-inset-top, 0px));
  padding-top: env(safe-area-inset-top, 0px);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid rgb(226 232 240 / 0.6);
}

.top-navbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  padding: 0 20px;
}

.top-navbar-brand {
  flex: 0 0 auto;
  min-width: 120px;
}

.top-navbar-brand h1 {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: rgb(15 23 42);
}

.top-navbar-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.top-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 500;
  color: rgb(100 116 139);
  text-decoration: none;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.top-tab:hover {
  color: rgb(51 65 85);
  background: rgb(241 245 249 / 0.8);
}

.top-tab.active {
  color: rgb(15 23 42);
  background: rgb(241 245 249);
  font-weight: 600;
}

.top-tab-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.top-navbar-right {
  flex: 0 0 auto;
  min-width: 120px;
  display: flex;
  justify-content: flex-end;
}

.mobile-menu-btn {
  display: none;
  padding: 6px;
  color: rgb(100 116 139);
  border-radius: 8px;
  transition: all 0.15s ease;
  border: none;
  background: none;
  cursor: pointer;
}

.mobile-menu-btn:hover {
  background: rgb(241 245 249);
  color: rgb(51 65 85);
}

/* ===== Below Top Bar ===== */
.below-topbar {
  display: flex;
  flex: 1;
  margin-top: calc(48px + env(safe-area-inset-top, 0px));
  overflow: hidden;
}

/* ===== Sidebar ===== */
.sidebar {
  width: 208px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: transform 0.3s ease;
  background: white;
  border-right: 1px solid rgb(226 232 240 / 0.6);
}

.sidebar-header {
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgb(226 232 240 / 0.5);
  flex-shrink: 0;
}

.sidebar-brand {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: rgb(15 23 42);
}

.sidebar-close-btn {
  padding: 4px;
  color: rgb(148 163 184);
  border: none;
  background: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sidebar-close-btn:hover {
  color: rgb(71 85 105);
  background: rgb(241 245 249);
}

.sidebar-group-label {
  padding: 14px 14px 5px;
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: rgb(148 163 184);
}

.sidebar-nav {
  flex: 1;
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.sidebar-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13.5px;
  text-decoration: none;
  transition: all 0.2s ease;
  color: rgb(100 116 139);
}

.sidebar-link:active {
  transform: scale(0.98);
}

.sidebar-link:hover {
  background: rgba(255, 255, 255, 0.6);
  color: rgb(51 65 85);
}

.sidebar-link.active {
  background: white;
  color: rgb(15 23 42);
  font-weight: 500;
  box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.05);
}

.sidebar-link-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  color: rgb(148 163 184);
  transition: color 0.2s ease;
}

.sidebar-link:hover .sidebar-link-icon {
  color: rgb(100 116 139);
}

.sidebar-link-icon.active {
  color: rgb(51 65 85);
}

.sidebar-footer {
  padding: 12px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid rgb(226 232 240 / 0.5);
  flex-shrink: 0;
}

.sidebar-logout-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 8px;
  color: rgb(148 163 184);
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s ease;
}

.sidebar-logout-btn:hover {
  color: rgb(71 85 105);
  background: rgb(241 245 249);
}

.sidebar-version {
  font-size: 11px;
  color: rgb(203 213 225);
  padding-right: 4px;
}

/* ===== Sidebar Overlay (Mobile) ===== */
.sidebar-overlay {
  display: none;
}

/* ===== Main Content ===== */
.main-content {
  flex: 1;
  overflow: hidden;
}

/* ===== Media Queries ===== */
@media (max-width: 767px) {
  .top-navbar-brand {
    display: none;
  }

  .top-navbar-right {
    display: none;
  }

  .mobile-menu-btn {
    display: flex;
    flex-shrink: 0;
  }

  .top-navbar-tabs {
    position: static;
    transform: none;
    flex: 1;
    justify-content: center;
  }

  .top-tab {
    padding: 6px 12px;
    font-size: 13px;
  }

  .sidebar {
    position: fixed;
    top: calc(48px + env(safe-area-inset-top, 0px));
    left: 0;
    bottom: 0;
    z-index: 50;
    width: 240px;
    background: rgba(248, 250, 252, 0.95);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }

  .sidebar-overlay {
    display: block;
    position: fixed;
    inset: calc(48px + env(safe-area-inset-top, 0px)) 0 0 0;
    z-index: 49;
    background: rgb(15 23 42 / 0.4);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
  }
}

@media (min-width: 768px) {
  .sidebar-header {
    display: none;
  }
}

/* ===== Page Transition ===== */
.page-enter-active {
  transition: opacity 0.15s ease;
}

.page-leave-active {
  transition: opacity 0.1s ease;
}

.page-enter-from {
  opacity: 0;
}

.page-leave-to {
  opacity: 0;
}
</style>
