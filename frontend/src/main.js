import { createApp } from 'vue'
import { createPinia } from 'pinia'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import App from './App.vue'
import router from './router'
import './assets/main.css'

dayjs.extend(utc)

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
