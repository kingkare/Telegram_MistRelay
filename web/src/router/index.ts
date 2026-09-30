import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { shouldUseHashHistory } from '@/utils/runtime'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Landing',
    component: () => import('@/views/landing.vue'),
    meta: { public: true },
  },
  {
    path: '/landing',
    redirect: (to) => ({ path: '/', query: to.query }),
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login.vue'),
    meta: { public: true },
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
    component: () => import('@/views/settings.vue'),
    meta: { adminOnly: true },
  },
  {
    path: '/drive',
    name: 'Drive',
    component: () => import('@/views/drive.vue')
  },
  {
    path: '/edge-nodes',
    name: 'EdgeNodes',
    component: () => import('@/views/edge-nodes.vue')
  },
  {
    path: '/bots',
    name: 'Bots',
    component: () => import('@/views/bots.vue'),
    meta: { adminOnly: true },
  },
  {
    path: '/botfather',
    name: 'BotFather',
    component: () => import('@/views/botfather.vue'),
    meta: { adminOnly: true },
  },
  {
    path: '/customer-service',
    name: 'CustomerService',
    component: () => import('@/views/customer-service.vue'),
    meta: { adminOnly: true },
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('@/views/users.vue'),
    meta: { adminOnly: true },
  },
  {
    path: '/cache',
    name: 'Cache',
    component: () => import('@/views/cache.vue'),
    meta: { adminOnly: true },
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

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.isLoggedIn) {
    const { isTelegramMiniApp } = await import('@/utils/tma')
    if (isTelegramMiniApp()) {
      try {
        await auth.loginWithTMA()
      } catch (err) {
        console.warn('TMA auto-login attempted but failed:', err)
      }
    }
  }
  if (!to.meta.public && !auth.isLoggedIn) {
    return {
      name: 'Login',
      query: { redirect: to.fullPath },
    }
  }
  if (auth.isLoggedIn && !auth.user) {
    await auth.fetchUser()
  }
  if (to.meta.adminOnly && auth.user && auth.user.role !== 'admin') {
    return { path: '/drive' }
  }
  if (to.name === 'Login' && auth.isLoggedIn) {
    return { path: '/dashboard' }
  }
  if (to.name === 'Landing' && auth.isLoggedIn && !to.query.preview) {
    return { path: '/dashboard' }
  }
})
