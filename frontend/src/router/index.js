import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/DashboardView.vue') },
  { path: '/feed', component: () => import('@/views/FeedView.vue') },
  { path: '/sources', component: () => import('@/views/SourcesView.vue') },
  { path: '/content', component: () => import('@/views/ContentView.vue') },
  { path: '/pipelines', component: () => import('@/views/PipelinesView.vue') },
  { path: '/video-download', component: () => import('@/views/VideoView.vue') },
  { path: '/prompt-templates', component: () => import('@/views/TemplatesView.vue') },
  { path: '/settings', component: () => import('@/views/SettingsView.vue') },
]

export default createRouter({ history: createWebHistory(), routes })
