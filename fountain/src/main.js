import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import './assets/main.css'
import App from './App.vue'
import TrayPopover from './components/TrayPopover.vue'
import SettingsPanel from './components/SettingsPanel.vue'

const routes = [
  { path: '/', component: TrayPopover },
  { path: '/settings', component: SettingsPanel },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

const pinia = createPinia()
const app = createApp(App)

app.use(pinia)
app.use(router)
app.mount('#app')
