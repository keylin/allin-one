<script setup>
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { ref, watch, computed } from 'vue'
import ToastNotification from '@/components/toast-notification.vue'

const route = useRoute()
const router = useRouter()

const sidebarOpen = ref(false)

// 顶部导航栏项目（内容消费）
const topNavItems = [
  { path: '/feed', label: '首页', icon: 'M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z' },
  { path: '/favorites', label: '收藏', icon: 'M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z' },
  { path: '/finance', label: '数据', icon: 'M3 3v18h18M7 16l4-4 3 3 5-6' },
]

// 侧边栏项目（管理功能）
const sidebarNavItems = [
  { path: '/dashboard', label: '仪表盘', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { path: '/sources', label: '数据源', icon: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' },
  { path: '/content', label: '内容库', icon: 'M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4' },
  { path: '/pipelines', label: '流水线', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
  { path: '/videos', label: '视频管理', icon: 'M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z' },
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
        <!-- 品牌 -->
        <div class="top-navbar-brand">
          <h1>Allin-One</h1>
        </div>
        <!-- 居中导航标签 -->
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
        <!-- 右侧占位（保持居中对称） -->
        <div class="top-navbar-right">
          <!-- 移动端汉堡菜单 -->
          <button
            class="mobile-menu-btn"
            @click="sidebarOpen = true"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          </button>
        </div>
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
        <div class="sidebar-header md:hidden">
          <h2>管理面板</h2>
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
          <div class="text-xs text-slate-300">v1.0.0</div>
          <button
            v-if="hasApiKey"
            @click="handleLogout"
            class="sidebar-logout-btn"
            title="退出登录"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
            </svg>
          </button>
        </div>
      </aside>

      <!-- Main Content -->
      <main class="main-content">
        <RouterView />
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
  background: rgb(248 250 252 / 0.5);
}

/* ===== Top Navigation Bar ===== */
.top-navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 30;
  height: 48px;
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
  margin-top: 48px;
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
}

.sidebar-header {
  padding: 16px 16px 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-header h2 {
  font-size: 14px;
  font-weight: 600;
  color: rgb(51 65 85);
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
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13.5px;
  text-decoration: none;
  transition: all 0.2s ease;
  color: rgb(100 116 139);
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
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-logout-btn {
  color: rgb(148 163 184);
  background: none;
  border: none;
  cursor: pointer;
  transition: color 0.15s ease;
}

.sidebar-logout-btn:hover {
  color: rgb(71 85 105);
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
    min-width: auto;
  }

  .top-navbar-right {
    min-width: auto;
  }

  .mobile-menu-btn {
    display: flex;
  }

  .sidebar {
    position: fixed;
    top: 48px;
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
    inset: 48px 0 0 0;
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
</style>
