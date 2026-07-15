<template>
  <main class="pc-client pc-login-page">
    <section class="pc-login-visual" aria-hidden="true">
      <div class="pc-anime-asset pc-anime-login-hero"></div>
    </section>

    <section class="pc-login-panel pc-card">
      <div class="pc-login-heading">
        <span class="pc-login-mark">M</span>
        <div>
          <h1>MistRelay</h1>
          <p>桌面客户端</p>
        </div>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="pc-login-form"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="服务器地址" prop="serverUrl">
          <div class="pc-server-row">
            <el-input
              v-model="form.serverUrl"
              placeholder="https://mistrelay.example.com"
              :prefix-icon="Link"
              size="large"
              @keyup.enter="handleLogin"
            />
            <el-button
              class="pc-test-button"
              :loading="checking"
              @click="handleConnectionTest"
            >
              测试
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            :prefix-icon="User"
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <el-alert
          v-if="message"
          class="pc-login-alert"
          :title="message"
          :type="messageType"
          :closable="false"
          show-icon
        />

        <el-button
          type="primary"
          class="pc-login-submit"
          size="large"
          :loading="loading"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { Link, Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { checkServerConnection } from '@/utils/connection'
import {
  getDefaultServerBaseUrl,
  getServerBaseUrl,
  isValidServerBaseUrl,
  normalizeServerBaseUrl,
  setServerBaseUrl,
} from '@/utils/runtime'

type MessageType = 'success' | 'warning' | 'info' | 'error'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const checking = ref(false)
const message = ref('')
const messageType = ref<MessageType>('info')

const form = reactive({
  serverUrl: getServerBaseUrl() || getDefaultServerBaseUrl(),
  username: '',
  password: '',
})

const rules: FormRules = {
  serverUrl: [
    { required: true, message: '请输入服务器地址', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        const normalized = normalizeServerBaseUrl(value || '')
        if (!normalized) {
          callback(new Error('请输入服务器地址'))
          return
        }

        if (!/^https?:\/\//i.test(normalized)) {
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
    },
  ],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function setMessage(text: string, type: MessageType) {
  message.value = text
  messageType.value = type
}

async function validateForm(): Promise<boolean> {
  if (!formRef.value) return false
  return formRef.value.validate().catch(() => false)
}

async function handleConnectionTest(): Promise<boolean> {
  const valid = await formRef.value?.validateField('serverUrl').catch(() => false)
  if (valid === false) return false

  checking.value = true
  try {
    const result = await checkServerConnection(form.serverUrl)
    if (result.ok) {
      form.serverUrl = result.serverBaseUrl
      setServerBaseUrl(result.serverBaseUrl)
      setMessage(result.message, 'success')
      return true
    }

    setMessage(result.message, 'error')
    return false
  } finally {
    checking.value = false
  }
}

async function handleLogin() {
  if (!(await validateForm())) return

  loading.value = true
  try {
    const connectionOk = await handleConnectionTest()
    if (!connectionOk) return

    setServerBaseUrl(form.serverUrl)
    await authStore.login(form.username, form.password)
    const redirect = typeof route.query.redirect === 'string'
      ? route.query.redirect
      : '/pc/drive'
    router.replace(redirect.startsWith('/pc') ? redirect : '/pc/drive')
  } catch (error: any) {
    setMessage(error.response?.data?.error || error.message || '登录失败', 'error')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.pc-login-page {
  display: grid;
  grid-template-columns: minmax(460px, 1fr) minmax(360px, 420px);
  align-items: center;
  gap: clamp(36px, 5vw, 76px);
  min-height: 100vh;
  padding: 42px clamp(28px, 6vw, 88px);
  background: #f8f9fc;
}

.pc-login-visual {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface);
  box-shadow: 0 18px 44px rgba(55, 61, 94, 0.1);
}

.pc-login-panel {
  width: 100%;
  padding: 30px;
  box-shadow: 0 14px 38px rgba(55, 61, 94, 0.08);
}

.pc-login-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.pc-login-mark {
  display: inline-grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--pc-radius-md);
  background: var(--pc-gradient-brand);
  color: #ffffff;
  font-weight: 800;
  box-shadow: 0 7px 16px rgba(89, 101, 215, 0.24);
}

.pc-login-heading h1 {
  margin: 0;
  color: var(--pc-color-text);
  font-size: 22px;
  line-height: 1.2;
}

.pc-login-heading p {
  margin: 2px 0 0;
  color: var(--pc-color-text-muted);
  font-size: 13px;
}

.pc-login-form {
  display: grid;
  gap: 2px;
}

.pc-server-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px;
  gap: 8px;
  width: 100%;
}

.pc-test-button {
  height: 40px;
}

.pc-login-alert {
  margin: 2px 0 12px;
}

.pc-login-submit {
  width: 100%;
  height: 42px;
  border-radius: var(--pc-radius-md);
}

.pc-login-form :deep(.el-form-item__label) {
  color: var(--pc-color-text);
  font-weight: 600;
}

.pc-login-form :deep(.el-input__wrapper) {
  border-radius: var(--pc-radius-md);
  box-shadow: 0 0 0 1px var(--pc-color-border) inset;
}

.pc-login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--pc-color-primary) inset;
}

@media (max-width: 920px) {
  .pc-login-page {
    grid-template-columns: 1fr;
    gap: 24px;
    padding: 24px;
  }

  .pc-login-panel {
    max-width: 430px;
    justify-self: center;
  }
}
</style>
