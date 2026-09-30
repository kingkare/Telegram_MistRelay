/**
 * Telegram Mini App (TMA) 适配器
 * 提供 Telegram 客户端内宿主检测、生命周期管理与静默验签登录
 */

import { api } from '@/api'
import { setAuthToken, setRefreshToken } from '@/utils/runtime'
import type { Router } from 'vue-router'

export interface TelegramWebAppUser {
  id: number
  is_bot?: boolean
  first_name: string
  last_name?: string
  username?: string
  language_code?: string
}

export interface TelegramWebApp {
  initData: string
  initDataUnsafe: {
    query_id?: string
    user?: TelegramWebAppUser
    auth_date?: string
    hash?: string
    start_param?: string
  }
  version: string
  platform: string
  colorScheme: 'light' | 'dark'
  themeParams: Record<string, string>
  isExpanded: boolean
  viewportHeight: number
  viewportStableHeight: number
  headerColor: string
  backgroundColor: string
  BackButton: {
    isVisible: boolean
    onClick(callback: () => void): void
    offClick(callback: () => void): void
    show(): void
    hide(): void
  }
  ready(): void
  expand(): void
  close(): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  enableClosingConfirmation(): void
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}

/**
 * 判断当前是否处于 Telegram Mini App (TMA) 环境中
 */
export function isTelegramMiniApp(): boolean {
  if (typeof window === 'undefined') return false
  const tg = window.Telegram?.WebApp
  return !!(tg && typeof tg.initData === 'string' && tg.initData.length > 0)
}

/**
 * 获取 Telegram WebApp 实例
 */
export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === 'undefined') return null
  return window.Telegram?.WebApp || null
}

/**
 * 执行 Telegram Mini App 免密登录
 */
export async function authenticateWithTelegramMiniApp(): Promise<{ success: boolean; user?: any; error?: string }> {
  const tg = getTelegramWebApp()
  if (!tg || !tg.initData) {
    return { success: false, error: '非 Telegram Mini App 宿主环境' }
  }

  try {
    const { data } = await api.post('/auth/tma', {
      init_data: tg.initData,
    })

    if (data.success && data.token) {
      setAuthToken(data.token)
      if (data.refresh_token) {
        setRefreshToken(data.refresh_token)
      }
      return { success: true, user: data.user }
    } else {
      return { success: false, error: data.error || 'TMA 登录验证失败' }
    }
  } catch (error: any) {
    const msg = error.response?.data?.error || error.message || 'TMA 认证网络异常'
    return { success: false, error: msg }
  }
}

/**
 * 初始化 Telegram Mini App 视口与原生按键导航
 */
export function setupTelegramMiniApp(router: Router): void {
  const tg = getTelegramWebApp()
  if (!tg || !isTelegramMiniApp()) return

  try {
    tg.ready()
    tg.expand()
    if (tg.enableClosingConfirmation) {
      tg.enableClosingConfirmation()
    }
    if (tg.setHeaderColor) {
      tg.setHeaderColor('#fcf6f8')
    }
    if (tg.setBackgroundColor) {
      tg.setBackgroundColor('#fcf6f8')
    }

    // 绑定 Telegram 顶栏原生返回按键
    tg.BackButton.onClick(() => {
      if (window.history.length > 1) {
        router.back()
      } else {
        router.push('/drive')
      }
    })

    // 根据当前路由动态显示/隐藏原生返回键
    router.afterEach((to) => {
      const isTopLevel = ['/drive', '/downloads', '/dashboard', '/edge-nodes'].includes(to.path)
      if (isTopLevel) {
        tg.BackButton.hide()
      } else {
        tg.BackButton.show()
      }
    })
  } catch (err) {
    console.warn('[TMA] Failed to initialize WebApp controls:', err)
  }
}
