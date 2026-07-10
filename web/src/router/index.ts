import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PcLayout from '@/components/pc/pc-layout.vue'
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
    path: '/pc/login',
    name: 'PcLogin',
    component: () => import('@/views/pc/login.vue'),
    meta: { public: true, pc: true },
  },
  {
    path: '/pc',
    component: PcLayout,
    meta: { pc: true },
    children: [
      {
        path: '',
        redirect: '/pc/drive',
      },
      {
        path: 'drive',
        name: 'PcDrive',
        component: () => import('@/views/pc/drive.vue'),
      },
      {
        path: 'recent',
        name: 'PcRecent',
        component: () => import('@/views/pc/recent.vue'),
      },
      {
        path: 'downloads',
        name: 'PcDownloads',
        component: () => import('@/views/pc/downloads.vue'),
      },
      {
        path: 'settings',
        name: 'PcSettings',
        component: () => import('@/views/pc/settings.vue'),
      },
    ],
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
      name: to.meta.pc ? 'PcLogin' : 'Login',
      query: { redirect: to.fullPath },
    }
  }
  if (to.name === 'Login' && auth.isLoggedIn) {
    return { path: '/' }
  }
  if (to.name === 'PcLogin' && auth.isLoggedIn) {
    return { path: '/pc/drive' }
  }
})
