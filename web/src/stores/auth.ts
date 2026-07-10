import { defineStore } from 'pinia'
import { api } from '@/api'
import {
  clearAuthTokens,
  getAuthToken,
  getRefreshToken,
  setAuthToken,
  setRefreshToken,
} from '@/utils/runtime'

interface UserInfo {
  id: number
  username: string
  role: string
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
  },
  actions: {
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

    async fetchUser() {
      const token = getAuthToken()
      if (!token) return
      this.token = token
      this.refreshToken = getRefreshToken()
      try {
        const { data } = await api.get('/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (data.success) {
          this.user = data.user
        } else {
          this.logout()
        }
      } catch {
        this.logout()
      }
    },

    logout() {
      this.token = null
      this.refreshToken = null
      this.user = null
      clearAuthTokens()
    },
  },
})
