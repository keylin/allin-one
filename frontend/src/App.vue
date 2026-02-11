<script setup>
import { RouterView, RouterLink } from 'vue-router'

const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: '📊' },
  { path: '/feed', label: '信息流', icon: '📰' },
  { path: '/sources', label: '数据源', icon: '🔗' },
  { path: '/content', label: '内容库', icon: '📁' },
  { path: '/pipelines', label: '流程监控', icon: '⚙️' },
  { path: '/video-download', label: '视频下载', icon: '🎬' },
  { path: '/prompt-templates', label: '提示词', icon: '💬' },
  { path: '/settings', label: '设置', icon: '🔧' },
]
</script>

<template>
  <div class="flex h-screen bg-gray-50">
    <!-- Sidebar -->
    <aside class="w-56 bg-white border-r border-gray-200 flex flex-col">
      <div class="p-4 border-b border-gray-200">
        <h1 class="text-xl font-bold text-gray-800">Allin-One</h1>
        <p class="text-xs text-gray-400 mt-1">信息聚合与智能分析</p>
      </div>
      <nav class="flex-1 p-2 space-y-1">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100 transition-colors"
          active-class="bg-blue-50 text-blue-700 font-medium"
        >
          <span>{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-auto">
      <RouterView />
    </main>
  </div>
</template>
