<template>
  <main class="pc-client pc-login-page">
    <section class="pc-login-visual" aria-hidden="true">
      <img :src="loginHeroUrl" alt="">
    </section>

    <section class="pc-login-panel">
      <div class="pc-login-heading">
        <img class="pc-login-mark" :src="appMarkUrl" alt="">
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
              :disabled="loading"
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
          :disabled="checking"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { Link, Lock, User } from '@element-plus/icons-vue'
import appMarkUrl from '@/assets/pc-theme/app-mark.svg'
import loginHeroUrl from '@/assets/pc-theme/illustrations/login-hero.svg'
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
const verifiedServerUrl = ref('')

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

watch(() => form.serverUrl, (value) => {
  if (verifiedServerUrl.value === normalizeServerBaseUrl(value)) return
  verifiedServerUrl.value = ''
  message.value = ''
})

function setMessage(text: string, type: MessageType) {
  message.value = text
  messageType.value = type
}

async function validateForm(): Promise<boolean> {
  if (!formRef.value) return false
  return formRef.value.validate().catch(() => false)
}

async function handleConnectionTest(): Promise<boolean> {
  if (checking.value) return false

  const valid = await formRef.value?.validateField('serverUrl').catch(() => false)
  if (valid === false) return false

  const requestedUrl = normalizeServerBaseUrl(form.serverUrl)
  checking.value = true
  try {
    const result = await checkServerConnection(requestedUrl)

    // Ignore a stale response if the user edited the address while the check ran.
    if (normalizeServerBaseUrl(form.serverUrl) !== requestedUrl) return false

    if (result.ok) {
      const normalizedUrl = normalizeServerBaseUrl(result.serverBaseUrl)
      form.serverUrl = normalizedUrl
      verifiedServerUrl.value = normalizedUrl
      setServerBaseUrl(normalizedUrl)
      setMessage(result.message, 'success')
      return true
    }

    verifiedServerUrl.value = ''
    setMessage(result.message, 'error')
    return false
  } finally {
    checking.value = false
  }
}

async function handleLogin() {
  if (loading.value || checking.value || !(await validateForm())) return

  loading.value = true
  try {
    const normalizedUrl = normalizeServerBaseUrl(form.serverUrl)
    if (verifiedServerUrl.value !== normalizedUrl) {
      const connectionOk = await handleConnectionTest()
      if (!connectionOk) return
    }

    setServerBaseUrl(normalizedUrl)
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
  grid-template-columns: minmax(480px, 1fr) minmax(360px, 410px);
  align-items: center;
  gap: clamp(52px, 7vw, 108px);
  min-height: 100vh;
  padding: 48px clamp(44px, 7vw, 112px);
  background: var(--pc-color-bg, #f6f8fc);
}

.pc-login-visual {
  display: grid;
  place-items: center;
  min-width: 0;
}

.pc-login-visual img {
  display: block;
  width: 100%;
  height: auto;
  max-height: calc(100vh - 96px);
  object-fit: contain;
}

.pc-login-panel {
  width: 100%;
  min-width: 0;
  padding: 12px 0;
}

.pc-login-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.pc-login-mark {
  width: 40px;
  height: 40px;
  border-radius: var(--pc-radius-md);
  box-shadow: 0 5px 14px rgba(58, 71, 158, 0.18);
}

.pc-login-heading h1 {
  margin: 0;
  color: var(--pc-color-text);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.pc-login-heading p {
  margin: 3px 0 0;
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

@media (max-width: 1080px) {
  .pc-login-page {
    grid-template-columns: 1fr;
    gap: 24px;
    padding: 28px;
  }

  .pc-login-visual {
    display: none;
  }

  .pc-login-panel {
    max-width: 430px;
    justify-self: center;
  }
}
</style>
