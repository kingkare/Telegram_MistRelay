<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-circle bg-circle-1"></div>
      <div class="bg-circle bg-circle-2"></div>
      <div class="bg-circle bg-circle-3"></div>
    </div>

    <div class="login-card glass-card">
      <!-- 顶部返回官网首页链接 -->
      <div class="login-top-bar">
        <router-link to="/" class="back-home-link">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回官网首页</span>
        </router-link>
      </div>

      <div class="login-header">
        <div class="logo-icon">
          <el-icon :size="36"><Monitor /></el-icon>
        </div>
        <h1 class="text-gradient">MistRelay</h1>
        <p class="login-subtitle">多租户同区极速云盘与媒体中继系统</p>
      </div>

      <!-- 登录 / Telegram 验证码注册 切换标签 -->
      <div class="auth-mode-tabs">
        <button
          type="button"
          class="auth-tab-btn"
          :class="{ active: activeTab === 'login' }"
          @click="activeTab = 'login'"
        >
          账号密码登录
        </button>
        <button
          type="button"
          class="auth-tab-btn"
          :class="{ active: activeTab === 'register' }"
          @click="activeTab = 'register'"
        >
          Telegram 验证码注册
        </button>
      </div>

      <!-- 双页横向滑动表单视口 (零跳动横向滑轨) -->
      <div class="auth-slider-viewport">
        <div class="auth-slider-track" :class="`is-${activeTab}`">
          <!-- Slide 1: 登录表单 -->
          <div
            class="auth-slide login-slide"
            :class="{ 'is-active': activeTab === 'login' }"
            :inert="activeTab !== 'login'"
            :aria-hidden="activeTab !== 'login'"
          >
            <!-- TMA 快速免密登录提示卡片 -->
            <div v-if="inTmaEnvironment" class="tma-quick-box mb-4 p-3 rounded-xl bg-pink-50/80 border border-pink-200/60 text-center">
              <el-button
                type="primary"
                size="large"
                class="w-full !rounded-xl"
                :loading="tmaLoading"
                @click="handleTmaQuickLogin"
              >
                <el-icon class="mr-1.5"><Promotion /></el-icon>
                Telegram 客户端一键免密登录
              </el-button>
              <p class="text-xs text-pink-500 font-medium mt-1.5">已检测到 Telegram 环境，点击即可极速登入</p>
            </div>

            <el-form
              ref="formRef"
              :model="form"
              :rules="rules"
              class="login-form"
              @submit.prevent="handleLogin"
            >
              <el-form-item prop="username">
                <el-input
                  v-model="form.username"
                  placeholder="用户名"
                  size="large"
                  :prefix-icon="User"
                  @keyup.enter="handleLogin"
                />
              </el-form-item>
              <el-form-item prop="password">
                <el-input
                  v-model="form.password"
                  type="password"
                  placeholder="密码"
                  size="large"
                  :prefix-icon="Lock"
                  show-password
                  @keyup.enter="handleLogin"
                />
              </el-form-item>
              <el-form-item prop="serverUrl">
                <el-input
                  v-model="form.serverUrl"
                  placeholder="服务器地址，如 127.0.0.1:8080 或 https://mistrelay.example.com"
                  size="large"
                  :prefix-icon="Link"
                />
              </el-form-item>
              <el-form-item class="login-action-item">
                <el-button
                  type="primary"
                  size="large"
                  class="login-btn"
                  :loading="loading"
                  @click="handleLogin"
                >
                  {{ loading ? '登录中...' : '登 录' }}
                </el-button>
              </el-form-item>
            </el-form>
          </div>

          <!-- Slide 2: 注册表单（保留 .register-panel 类以满足现有测试） -->
          <div
            class="auth-slide register-panel"
            :class="{ 'is-active': activeTab === 'register' }"
            :inert="activeTab !== 'register'"
            :aria-hidden="activeTab !== 'register'"
          >
            <el-form
              ref="regFormRef"
              :model="regForm"
              :rules="regRules"
              class="register-form"
              @submit.prevent="handleRegister"
            >
              <!-- 6 位验证码输入 + 右侧内嵌获取按钮 -->
              <el-form-item prop="code">
                <div class="code-input-group">
                  <el-input
                    v-model="regForm.code"
                    placeholder="输入 6 位数字验证码"
                    maxlength="6"
                    size="large"
                    :prefix-icon="Key"
                  />
                  <a
                    v-if="botRegisterUrl"
                    :href="botRegisterUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="get-code-btn"
                    title="点击跳转 Telegram 私聊机器人获取 6 位验证码"
                  >
                    <el-icon><Promotion /></el-icon>
                    <span>获取验证码</span>
                  </a>
                  <span
                    v-else
                    class="get-code-btn disabled"
                    title="请向主控 Bot 私聊发送 /register"
                  >
                    获取验证码
                  </span>
                </div>
              </el-form-item>

              <el-form-item prop="username">
                <el-input
                  v-model="regForm.username"
                  placeholder="设置云盘登录用户名 (3~32位)"
                  size="large"
                  :prefix-icon="User"
                />
              </el-form-item>

              <el-form-item prop="password">
                <el-input
                  v-model="regForm.password"
                  type="password"
                  placeholder="设置登录密码 (至少 8 位)"
                  size="large"
                  :prefix-icon="Lock"
                  show-password
                />
              </el-form-item>

              <el-form-item>
                <el-select
                  v-model="regForm.targetDcId"
                  placeholder="专属存储频道区域"
                  size="large"
                  style="width: 100%"
                >
                  <template #prefix>
                    <el-icon class="text-sky-500"><Location /></el-icon>
                  </template>
                  <el-option :value="0" label="🌐 自动匹配 Telegram 所属 DC (推荐)" />
                  <el-option :value="5" label="🇸🇬 DC5 亚太/新加坡 (低延迟推荐)" />
                  <el-option :value="1" label="🇺🇸 DC1 美洲/迈阿密 (北美账号)" />
                  <el-option :value="2" label="🇳🇱 DC2 欧洲/阿姆斯特丹 (欧洲账号)" />
                </el-select>
              </el-form-item>

              <el-form-item class="login-action-item">
                <el-button
                  type="primary"
                  size="large"
                  class="login-btn"
                  :loading="regLoading"
                  @click="handleRegister"
                >
                  {{ regLoading ? '正在开通专属频道...' : '立即开通专属云盘' }}
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </div>
      </div>

      <p class="server-hint">
        {{ activeTab === 'login' ? serverHint : '💡 私聊 Bot 发送 /register 获取验证码，系统全自动为您创建物理隔离专属存储频道。' }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { User, Lock, Monitor, Link, Key, ArrowLeft, Promotion, Location } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'
import {
  getDefaultServerBaseUrl,
  getServerBaseUrl,
  isValidServerBaseUrl,
  normalizeServerBaseUrl,
  setServerBaseUrl,
} from '@/utils/runtime'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const regFormRef = ref<FormInstance>()
const loading = ref(false)
const regLoading = ref(false)
const inTmaEnvironment = ref(false)
const tmaLoading = ref(false)

async function handleTmaQuickLogin() {
  tmaLoading.value = true
  try {
    await authStore.loginWithTMA()
    ElMessage.success('Telegram 登录成功！')
    const redirect = (route.query.redirect as string) || '/drive'
    router.replace(redirect)
  } catch (err: any) {
    ElMessage.error(err.message || 'Telegram 登录失败')
  } finally {
    tmaLoading.value = false
  }
}

const activeTab = ref<'login' | 'register'>((route.query.tab as string) === 'register' ? 'register' : 'login')

const botUsername = ref<string>('')
const botRegisterUrl = ref<string>('')

const form = reactive({
  username: '',
  password: '',
  serverUrl: getServerBaseUrl() || getDefaultServerBaseUrl(),
})

const regForm = reactive({
  code: '',
  username: '',
  password: '',
  targetDcId: 0,
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  serverUrl: [{
    validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
      if (!value) {
        callback()
        return
      }

      const normalized = normalizeServerBaseUrl(value)
      if (!/^https?:\/\//i.test(normalized) && !normalized.startsWith('/')) {
        callback(new Error('服务器地址必须是 http(s) 地址'))
        return
      }

      if (!isValidServerBaseUrl(normalized)) {
        callback(new Error('服务器地址格式不正确'))
        return
      }

      callback()
    },
    trigger: 'blur',
  }],
}

const regRules = {
  code: [
    { required: true, message: '请输入 6 位数字验证码', trigger: 'blur' },
    { min: 6, max: 6, message: '验证码必须是 6 位数字', trigger: 'blur' },
  ],
  username: [
    { required: true, message: '请设置云盘登录用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度需在 3~32 位之间', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请设置登录密码', trigger: 'blur' },
    { min: 8, message: '登录密码至少 8 位', trigger: 'blur' },
  ],
}

const serverHint = computed(() => {
  return '浏览器模式可留空走同源服务，也可以填写远程服务器地址。'
})

async function fetchBotInfo() {
  try {
    const { data } = await api.get('/auth/bot-info')
    if (data?.success) {
      const uname = data.bot_username || data.data?.bot_username || ''
      botUsername.value = uname
      botRegisterUrl.value = data.register_deep_link || data.data?.register_deep_link || (uname ? `https://t.me/${uname}?start=register` : '')
    }
  } catch {
    // ignore
  }
}

onMounted(() => {
  if (route.query.tab === 'register') {
    activeTab.value = 'register'
  }
  void fetchBotInfo()
  import('@/utils/tma').then(({ isTelegramMiniApp }) => {
    inTmaEnvironment.value = isTelegramMiniApp()
    if (inTmaEnvironment.value) {
      void handleTmaQuickLogin()
    }
  }).catch(() => undefined)
})

watch(() => route.query.tab, (tab) => {
  if (tab === 'register') {
    activeTab.value = 'register'
  } else if (tab === 'login' || !tab) {
    activeTab.value = 'login'
  }
})

watch(activeTab, () => {
  formRef.value?.clearValidate()
  regFormRef.value?.clearValidate()
})

async function handleLogin() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    setServerBaseUrl(form.serverUrl)
    await authStore.login(form.username, form.password)
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.replace(redirect === '/' ? '/dashboard' : redirect)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (!regFormRef.value) return
  const valid = await regFormRef.value.validate().catch(() => false)
  if (!valid) return

  regLoading.value = true
  try {
    setServerBaseUrl(form.serverUrl)
    const res = await authStore.registerWithTelegram({
      code: regForm.code.trim(),
      username: regForm.username.trim(),
      password: regForm.password,
      target_dc_id: regForm.targetDcId > 0 ? regForm.targetDcId : null,
    })
    ElMessage.success(res.message || '注册成功！已为您开通同 DC 专属存储频道')
    router.replace('/drive')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '注册失败')
  } finally {
    regLoading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: #fdf7f9;
  background-image: 
    radial-gradient(circle at 12% 18%, rgba(255, 117, 151, 0.22) 0%, transparent 45%),
    radial-gradient(circle at 88% 82%, rgba(56, 189, 248, 0.22) 0%, transparent 45%),
    radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.8) 0%, transparent 80%);
}

.login-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.bg-circle {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
}

.bg-circle-1 {
  width: 520px;
  height: 520px;
  background: rgba(255, 117, 151, 0.22);
  top: -8%;
  left: -6%;
  animation: float 10s ease-in-out infinite;
}

.bg-circle-2 {
  width: 480px;
  height: 480px;
  background: rgba(56, 189, 248, 0.22);
  bottom: -6%;
  right: -4%;
  animation: float 12s ease-in-out infinite reverse;
}

.bg-circle-3 {
  width: 320px;
  height: 320px;
  background: rgba(255, 182, 193, 0.25);
  top: 35%;
  right: 18%;
  animation: float 14s ease-in-out infinite;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0) scale(1);
  }
  50% {
    transform: translateY(-24px) scale(1.05);
  }
}

.login-card {
  width: 460px;
  max-width: 92vw;
  padding: 28px 32px 24px;
  border-radius: 24px;
  position: relative;
  z-index: 1;
  background: rgba(255, 255, 255, 0.88) !important;
  backdrop-filter: blur(24px) !important;
  -webkit-backdrop-filter: blur(24px) !important;
  border: 1px solid rgba(255, 143, 171, 0.28) !important;
  box-shadow: 0 20px 50px -12px rgba(255, 117, 151, 0.2), 0 10px 25px -8px rgba(56, 189, 248, 0.15) !important;
  /* fixed height stability: zero vertical card bounce */
}

.login-top-bar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.back-home-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  text-decoration: none;
  transition: all 0.2s ease;
  padding: 4px 8px;
  border-radius: 8px;
}

.back-home-link:hover {
  color: #ff7597;
  background: rgba(255, 117, 151, 0.1);
  transform: translateX(-2px);
}

.login-header {
  text-align: center;
  margin-bottom: 20px;
}

.logo-icon {
  width: 58px;
  height: 58px;
  border-radius: 18px;
  background: var(--gradient-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 10px;
  color: #fff;
  box-shadow: 0 8px 24px rgba(255, 117, 151, 0.4), 0 4px 12px rgba(56, 189, 248, 0.25);
}

.login-header h1 {
  font-size: 26px;
  font-weight: 800;
  margin: 0 0 4px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.login-subtitle {
  color: #64748b;
  font-size: 13px;
  margin: 0;
  font-weight: 500;
}

.auth-mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 5px;
  border-radius: 14px;
  background: rgba(241, 245, 249, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.2);
  margin-bottom: 20px;
}

.auth-tab-btn {
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.22s ease;
}

.auth-tab-btn:hover:not(.active) {
  color: #ff7597;
  background: rgba(255, 117, 151, 0.06);
}

.auth-tab-btn.active {
  background: #fff;
  color: #ff7597;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.18);
}

/* 双页横向滑动视口与滑轨 (零跳动架构) */
.auth-slider-viewport {
  width: 100%;
  overflow: hidden;
  position: relative;
  min-height: 310px;
}

.auth-slider-track {
  display: flex;
  width: 200%;
  transition: transform 0.35s cubic-bezier(0.25, 1, 0.5, 1);
  will-change: transform;
}

.auth-slider-track.is-login {
  transform: translateX(0);
}

.auth-slider-track.is-register {
  transform: translateX(-50%);
}

.auth-slide {
  width: 50%;
  flex-shrink: 0;
  box-sizing: border-box;
  padding: 0 2px;
  transition: opacity 0.28s ease, filter 0.28s ease;
  will-change: opacity, filter;
}

.auth-slide:not(.is-active) {
  opacity: 0;
  pointer-events: none;
  filter: blur(1px);
}

.auth-slide.is-active {
  opacity: 1;
  pointer-events: auto;
  filter: none;
}

.auth-slide :deep(.el-form-item) {
  margin-bottom: 16px;
}

.auth-slide :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.auth-slide :deep(.el-input__wrapper) {
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(255, 143, 171, 0.25) inset;
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.7);
  transition: all 0.2s ease;
}

.auth-slide :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1.5px #ff7597 inset;
  background: rgba(255, 255, 255, 0.95);
}

.auth-slide :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px #ff7597 inset, 0 0 14px rgba(255, 117, 151, 0.25) !important;
  background: #ffffff;
}

.login-slide .login-form {
  display: flex;
  flex-direction: column;
}

.login-slide .login-action-item {
  margin-top: 6px;
}

/* 一体化验证码输入组 */
.code-input-group {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.code-input-group :deep(.el-input) {
  flex: 1;
}

.get-code-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 40px;
  padding: 0 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, #0ea5e9 0%, #38bdf8 100%);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.25);
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.get-code-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.38);
}

.get-code-btn.disabled {
  background: #cbd5e1;
  color: #94a3b8;
  box-shadow: none;
  cursor: not-allowed;
}

.server-hint {
  margin: 12px 4px 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
  text-align: center;
  min-height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-btn {
  width: 100%;
  border-radius: 14px;
  height: 46px;
  font-size: 15px;
  font-weight: 600;
  background: var(--gradient-primary);
  border: none;
  transition: all 0.3s ease;
  box-shadow: 0 6px 20px rgba(255, 117, 151, 0.35);
  margin-top: 2px;
}

.login-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(255, 117, 151, 0.5), 0 4px 14px rgba(56, 189, 248, 0.3);
}
</style>
