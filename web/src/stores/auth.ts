import { defineStore } from 'pinia'
import { api } from '@/api'
import {
  clearAuthTokens,
  getAuthToken,
  getRefreshToken,
  setAuthToken,
  setRefreshToken,
} from '@/utils/runtime'

export interface UserInfo {
  id: number
  username: string
  role: string
  tg_user_id?: number | null
  tg_username?: string | null
  dc_id?: number | null
  bin_channel_id?: number | null
  bin_channel_username?: string | null
}

interface AuthState {
  token: string | null
  refreshToken: string | null
  user: UserInfo | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: getAuthToken(),
    refreshToken: getRefreshToken(),
    user: null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    isAdmin: (state) => !state.user || state.user.role === 'admin',
  },
  actions: {
    async loginWithTMA() {
      const { authenticateWithTelegramMiniApp } = await import('@/utils/tma')
      const res = await authenticateWithTelegramMiniApp()
      if (res.success && res.user) {
        this.token = getAuthToken()
        this.refreshToken = getRefreshToken()
        this.user = res.user
        return res
      }
      throw new Error(res.error || 'TMA 登录失败')
    },

    async login(username: string, password: string) {
      const { data } = await api.post('/auth/login', { username, password })
      if (!data.success) throw new Error(data.error || '登录失败')
      this.token = data.token
      this.refreshToken = data.refresh_token || null
      this.user = data.user
      setAuthToken(data.token)
      if (data.refresh_token) {
        setRefreshToken(data.refresh_token)
      }
    },

    async registerWithTelegram(payload: {
      code: string
      username: string
      password: string
      target_dc_id?: number | null
    }) {
      const { data } = await api.post('/auth/register', payload)
      if (!data.success) throw new Error(data.error || '注册失败')
      this.token = data.token
      this.refreshToken = data.refresh_token || null
      this.user = data.user
      setAuthToken(data.token)
      if (data.refresh_token) {
        setRefreshToken(data.refresh_token)
      }
      return data
    },

    async fetchUser() {
      const token = getAuthToken()
      if (!token) return
      this.token = token
      this.refreshToken = getRefreshToken()
      try {
        const { data } = await api.get('/auth/me')
        if (data.success) {
          this.user = data.user
        } else {
          this.logout()
        }
      } catch (error: unknown) {
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status === 401) {
          this.logout()
        }
      }
    },

    logout() {
      const refreshToken = getRefreshToken()
      if (refreshToken) {
        void api.post('/auth/logout', { refresh_token: refreshToken }).catch(() => undefined)
      }
      this.token = null
      this.refreshToken = null
      this.user = null
      clearAuthTokens()
    },
  },
})
