import { createRouter, createWebHashHistory } from 'vue-router'
import JobsView from './views/JobsView.vue'
import ConfigView from './views/ConfigView.vue'
import ChatView from './views/ChatView.vue'

// Hash history: no server-side SPA fallback needed when FastAPI serves the app.
const routes = [
  { path: '/', redirect: '/jobs' },
  { path: '/jobs', name: 'jobs', component: JobsView },
  { path: '/chat', name: 'chat', component: ChatView },
  { path: '/config', name: 'config', component: ConfigView },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
