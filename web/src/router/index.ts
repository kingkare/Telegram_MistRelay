import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getDefaultRoutePath, shouldUseHashHistory } from '@/utils/runtime'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    redirect: () => getDefaultRoutePath()
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/dashboard.vue')
  },
  {
    path: '/downloads',
    name: 'Downloads',
    component: () => import('@/views/downloads.vue')
  },
  {
    path: '/tasks',
    redirect: '/downloads?tab=queue'
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/settings.vue')
  },
  {
    path: '/drive',
    name: 'Drive',
    component: () => import('@/views/drive.vue')
  },
  {
    path: '/bots',
    name: 'Bots',
    component: () => import('@/views/bots.vue')
  },
  {
    path: '/botfather',
    name: 'BotFather',
    component: () => import('@/views/botfather.vue')
  },
  {
    path: '/cache',
    name: 'Cache',
    component: () => import('@/views/cache.vue')
  },
  {
    path: '/system',
    redirect: '/settings?tab=container'
  },
  {
    path: '/logs',
    redirect: '/settings?tab=app-logs'
  }
]

export const router = createRouter({
  history: shouldUseHashHistory()
    ? createWebHashHistory(import.meta.env.BASE_URL || '/')
    : createWebHistory(import.meta.env.BASE_URL || '/'),
  routes
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return {
      name: 'Login',
      query: { redirect: to.fullPath },
    }
  }
  if (to.name === 'Login' && auth.isLoggedIn) {
    return { path: '/' }
  }
})
