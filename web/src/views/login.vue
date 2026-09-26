<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-circle bg-circle-1"></div>
      <div class="bg-circle bg-circle-2"></div>
      <div class="bg-circle bg-circle-3"></div>
    </div>

    <div class="login-card glass-card animate-scale-in">
      <div class="login-header">
        <div class="logo-icon">
          <el-icon :size="36"><Monitor /></el-icon>
        </div>
        <h1 class="text-gradient">MistRelay</h1>
        <p class="login-subtitle">媒体中继管理系统</p>
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
        <el-form-item>
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

      <p class="server-hint">
        {{ serverHint }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { User, Lock, Monitor, Link } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  getDefaultServerBaseUrl,
  getServerBaseUrl,
  isValidServerBaseUrl,
  normalizeServerBaseUrl,
  setServerBaseUrl,
} from '@/utils/runtime'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  serverUrl: getServerBaseUrl() || getDefaultServerBaseUrl(),
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
    trigger: 'blur'
  }],
}

const serverHint = computed(() => {
  return '浏览器模式可留空走同源服务，也可以填写远程服务器地址。'
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
    router.replace('/')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '登录失败')
  } finally {
    loading.value = false
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
    radial-gradient(circle at 12% 18%, rgba(255, 143, 171, 0.22) 0%, transparent 45%),
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
  width: 420px;
  max-width: 90vw;
  padding: 42px 38px 30px;
  border-radius: 24px;
  position: relative;
  z-index: 1;
  background: rgba(255, 255, 255, 0.82) !important;
  backdrop-filter: blur(24px) !important;
  -webkit-backdrop-filter: blur(24px) !important;
  border: 1px solid rgba(255, 143, 171, 0.28) !important;
  box-shadow: 0 20px 50px -12px rgba(255, 117, 151, 0.2), 0 10px 25px -8px rgba(56, 189, 248, 0.15) !important;
  transition: all 0.3s ease;
}

.login-card:hover {
  box-shadow: 0 24px 60px -10px rgba(255, 117, 151, 0.28), 0 12px 30px -6px rgba(56, 189, 248, 0.2) !important;
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.logo-icon {
  width: 68px;
  height: 68px;
  border-radius: 18px;
  background: var(--gradient-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
  color: #fff;
  box-shadow: 0 8px 24px rgba(255, 117, 151, 0.4), 0 4px 12px rgba(56, 189, 248, 0.25);
  transition: transform 0.3s ease;
}

.logo-icon:hover {
  transform: rotate(5deg) scale(1.06);
}

.login-header h1 {
  font-size: 28px;
  font-weight: 800;
  margin: 0 0 6px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.login-subtitle {
  color: #64748b;
  font-size: 14px;
  margin: 0;
  font-weight: 500;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(255, 143, 171, 0.25) inset;
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.7);
  transition: all 0.2s ease;
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1.5px #ff7597 inset;
  background: rgba(255, 255, 255, 0.95);
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px #ff7597 inset, 0 0 14px rgba(255, 117, 151, 0.25) !important;
  background: #ffffff;
}

.server-hint {
  margin: 8px 4px 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.login-btn {
  width: 100%;
  border-radius: 14px;
  height: 46px;
  font-size: 16px;
  font-weight: 600;
  background: var(--gradient-primary);
  border: none;
  transition: all 0.3s ease;
  box-shadow: 0 6px 20px rgba(255, 117, 151, 0.35);
  margin-top: 6px;
}

.login-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(255, 117, 151, 0.5), 0 4px 14px rgba(56, 189, 248, 0.3);
}

.login-btn:active {
  transform: translateY(0);
}
</style>
