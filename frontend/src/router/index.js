import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/feed' },
  { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  { path: '/dashboard', component: () => import('@/views/DashboardView.vue') },
  { path: '/feed', component: () => import('@/views/FeedView.vue') },
  { path: '/favorites', component: () => import('@/views/FavoritesView.vue') },
  { path: '/sources', component: () => import('@/views/SourcesView.vue') },
  { path: '/content', component: () => import('@/views/ContentView.vue') },
  { path: '/pipelines', component: () => import('@/views/PipelinesView.vue') },
  { path: '/processing', redirect: '/pipelines' },
  { path: '/prompt-templates', redirect: '/pipelines?tab=prompts' },
  { path: '/media', component: () => import('@/views/media-view.vue') },
  { path: '/videos', redirect: '/media' },
  { path: '/video-download', redirect: '/media' },
  { path: '/ebook', component: () => import('@/views/EbookView.vue') },
  { path: '/sync', component: () => import('@/views/SyncView.vue') },
  { path: '/reading', component: () => import('@/views/ReadingView.vue') },
  { path: '/finance', component: () => import('@/views/FinanceView.vue') },
  { path: '/settings', component: () => import('@/views/SettingsView.vue') },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/views/NotFoundView.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

// 认证守卫：检测后端是否启用了 API Key 认证
let authRequired = null // null = 未检测, true/false = 已确认

router.beforeEach(async (to) => {
  if (to.meta.public) return true

  // 已有 api_key 则放行
  if (localStorage.getItem('api_key')) return true

  // 首次访问时探测后端是否需要认证
  if (authRequired === null) {
    try {
      const res = await fetch('/api/dashboard/stats')
      authRequired = res.status === 401
    } catch {
      // 网络错误时保守重定向到 login，不缓存结果以便下次重试
      return '/login'
    }
  }

  if (authRequired) {
    return '/login'
  }

  return true
})

export default router
