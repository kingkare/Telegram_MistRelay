<template>
  <el-header class="header">
    <div class="header-content">
      <!-- 左侧:面包屑导航 (桌面端) 或 汉堡包+Logo (移动端) -->
      <div class="header-left">
        <div class="mobile-brand-group md:hidden">
          <el-button
            circle
            text
            class="mobile-hamburger-btn"
            @click="emit('toggleDrawer')"
            title="展开全功能导航抽屉"
          >
            <el-icon :size="20"><Expand /></el-icon>
          </el-button>
          <span class="mobile-logo-text">MistRelay</span>
        </div>

        <el-breadcrumb separator="/" class="breadcrumb hidden md:flex">
          <el-breadcrumb-item :to="{ path: '/dashboard' }" class="breadcrumb-item">
            <el-icon class="breadcrumb-icon"><HomeFilled /></el-icon>
            <span>首页</span>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-if="breadcrumb && route.path !== '/dashboard'">
            {{ breadcrumb }}
          </el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      
      <!-- 右侧:用户信息 -->
      <div class="header-right">
        <div
          v-if="authStore.user?.bin_channel_username || authStore.user?.bin_channel_id"
          class="connection-pill channel-pill"
          style="border-color: rgba(16, 185, 129, 0.35); background: rgba(236, 253, 245, 0.75);"
          @click="router.push('/drive')"
        >
          <span class="connection-dot connection-dot--success" style="background: #10b981;"></span>
          <div class="connection-copy">
            <span class="connection-title">📡 专属频道 · DC{{ authStore.user?.dc_id || 5 }}</span>
            <span class="connection-subtitle">@{{ authStore.user?.bin_channel_username || authStore.user?.bin_channel_id }}</span>
          </div>
        </div>
        <div
          class="connection-pill server-pill"
          :class="{ 'hidden md:flex': authStore.user?.bin_channel_username || authStore.user?.bin_channel_id }"
          @click="authStore.isAdmin ? router.push('/settings') : undefined"
        >
          <span class="connection-dot" :class="connectionStatusClass"></span>
          <div class="connection-copy">
            <span class="connection-title">{{ connectionTitle }}</span>
            <span class="connection-subtitle">{{ connectionSubtitle }}</span>
          </div>
        </div>

        <!-- 新手全景教程与操作手册胶囊 -->
        <div
          class="guide-pill"
          @click="openGuide('quickstart')"
          title="点击查阅 MistRelay 新手全景使用手册与 FAQ"
        >
          <div class="guide-pill-icon-wrap">
            <el-icon><Reading /></el-icon>
          </div>
          <div class="guide-pill-text-wrap">
            <span class="guide-pill-title">新手教程</span>
            <span class="guide-pill-sub">使用指南 & FAQ</span>
          </div>
        </div>

        <el-dropdown trigger="click" @command="handleCommand" placement="bottom-end" class="user-dropdown">
          <div class="user-info">
            <el-avatar :size="40" class="avatar">
              <el-icon><User /></el-icon>
            </el-avatar>
            <div class="user-details">
              <span class="username">{{ authStore.user?.username || '用户' }}</span>
              <span class="user-role">{{ authStore.user?.role === 'admin' ? '系统管理员' : '用户' }}</span>
            </div>
            <el-icon class="dropdown-icon"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu class="user-menu">
              <el-dropdown-item command="password" class="menu-item">
                <el-icon><Lock /></el-icon>
                <span>修改密码</span>
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided class="menu-item logout-item">
                <el-icon><SwitchButton /></el-icon>
                <span>退出登录</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 修改密码对话框（append-to-body 脱离 header 的布局约束） -->
    <el-dialog v-model="passwordDialogVisible" title="修改密码" width="420px" :close-on-click-modal="false" append-to-body>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="80px">
        <el-form-item label="旧密码" prop="oldPassword">
          <el-input v-model="pwdForm.oldPassword" type="password" show-password placeholder="请输入旧密码" />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="pwdForm.newPassword" type="password" show-password placeholder="至少16位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input v-model="pwdForm.confirmPassword" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitPassword">确认修改</el-button>
      </template>
    </el-dialog>
    <!-- 全局新手全景使用手册抽屉 -->
    <UserGuideDrawer ref="guideDrawerRef" />
  </el-header>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { User, ArrowDown, SwitchButton, HomeFilled, Lock, Reading, Expand } from '@element-plus/icons-vue'
import UserGuideDrawer from '@/components/UserGuideDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import { changePassword } from '@/api'
import { checkServerConnection } from '@/utils/connection'
import { getServerBaseUrl } from '@/utils/runtime'

defineProps<{
  isMobile?: boolean
}>()

const emit = defineEmits<{
  toggleDrawer: []
  openGuide: []
}>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const guideDrawerRef = ref<InstanceType<typeof UserGuideDrawer> | null>(null)

function openGuide(tab = 'quickstart') {
  if (guideDrawerRef.value) {
    guideDrawerRef.value.open(tab)
  }
  window.dispatchEvent(new CustomEvent('open-user-guide', { detail: { tab } }))
}
const connectionState = ref<'idle' | 'success' | 'error'>('idle')
const connectionMessage = ref('正在检查连接')
let connectionTimer: number | null = null

function onCustomOpenGuide(e: Event) {
  const detail = (e as CustomEvent).detail || 'quickstart'
  openGuide(detail)
}

onMounted(() => {
  window.addEventListener('mistrelay:open-guide', onCustomOpenGuide)
  if (!authStore.user) {
    authStore.fetchUser()
  }

  void refreshConnectionStatus()
  connectionTimer = window.setInterval(() => {
    void refreshConnectionStatus()
  }, 30000)
})

onUnmounted(() => {
  window.removeEventListener('mistrelay:open-guide', onCustomOpenGuide)
  if (connectionTimer !== null) {
    window.clearInterval(connectionTimer)
  }
})

const breadcrumb = computed(() => {
  const routeMap: Record<string, string> = {
    '/dashboard': '仪表板',
    '/downloads': '任务中心',
    '/tasks': '任务队列',
    '/settings': '系统设置',
    '/system': '容器管理',
    '/logs': '系统日志',
    '/drive': 'TG网盘',
    '/cache': '缓存管理',
    '/bots': '集群管理',
    '/botfather': '自动铸机',
    '/users': '用户管理',
  }
  return routeMap[route.path]
})

const connectionTitle = computed(() => {
  const serverBaseUrl = getServerBaseUrl()

  if (!serverBaseUrl) {
    return '同源服务'
  }

  try {
    return new URL(serverBaseUrl).host
  } catch {
    return serverBaseUrl
  }
})

const connectionSubtitle = computed(() => {
  if (connectionState.value === 'success') return '服务器在线'
  if (connectionState.value === 'error') return connectionMessage.value
  return '检查连接中'
})

const connectionStatusClass = computed(() => {
  if (connectionState.value === 'success') return 'connection-dot--success'
  if (connectionState.value === 'error') return 'connection-dot--error'
  return 'connection-dot--idle'
})

async function refreshConnectionStatus() {
  const result = await checkServerConnection()
  connectionState.value = result.ok ? 'success' : 'error'
  connectionMessage.value = result.message
}

// 修改密码
const passwordDialogVisible = ref(false)
const pwdLoading = ref(false)
const pwdFormRef = ref<FormInstance>()
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const pwdRules = {
  oldPassword: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 16, max: 512, message: '密码长度必须为16-512位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_: any, value: string, callback: any) => {
        if (value !== pwdForm.newPassword) callback(new Error('两次密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function submitPassword() {
  if (!pwdFormRef.value) return
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdLoading.value = true
  try {
    const res = await changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    if (res.success) {
      ElMessage.success('密码修改成功，请重新登录')
      passwordDialogVisible.value = false
      authStore.logout()
      router.push('/login')
    } else {
      ElMessage.error(res.error || '修改失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || '修改失败')
  } finally {
    pwdLoading.value = false
  }
}

function handleCommand(command: string) {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
    ElMessage.success('已退出登录')
  } else if (command === 'password') {
    pwdForm.oldPassword = ''
    pwdForm.newPassword = ''
    pwdForm.confirmPassword = ''
    passwordDialogVisible.value = true
  }
}
</script>

<style scoped>
.header {
  background: rgba(255, 255, 255, 0.95) !important;
  border-bottom: 1px solid rgba(255, 143, 171, 0.2);
  height: 64px !important;
  width: 100% !important;
  position: sticky;
  top: 0;
  z-index: 100;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  flex-shrink: 0;
  box-shadow: 0 4px 20px -6px rgba(255, 143, 171, 0.08), 0 2px 8px -2px rgba(56, 189, 248, 0.06);
}

.mobile-brand-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mobile-hamburger-btn {
  color: #ff7597;
  padding: 6px;
  font-size: 18px;
}

.mobile-hamburger-btn:hover {
  background: rgba(255, 143, 171, 0.15);
}

.mobile-logo-text {
  font-size: 16px;
  font-weight: 800;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  user-select: none;
}

.header-content {
  @apply flex items-center justify-between;
  height: 100%;
  padding: 0 24px;
  max-width: 100%;
}

.header-left {
  @apply flex items-center flex-1;
  min-width: 0;
}

.breadcrumb {
  @apply text-sm;
}

:deep(.el-breadcrumb__inner) {
  @apply font-medium text-gray-600;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}

:deep(.el-breadcrumb__inner.is-link) {
  @apply text-gray-500;
  transition: color 0.2s;
}

:deep(.el-breadcrumb__inner.is-link:hover) {
  color: #ff7597;
  transform: translateX(2px);
}

:deep(.el-breadcrumb__separator) {
  @apply text-gray-400 mx-2;
}

.breadcrumb-icon {
  @apply text-gray-500;
  font-size: 16px;
  transition: all 0.2s ease;
}

:deep(.el-breadcrumb__inner.is-link:hover) .breadcrumb-icon {
  color: #ff7597;
  transform: scale(1.1);
}

.guide-pill {
  @apply flex items-center gap-2;
  padding: 6px 12px;
  border-radius: 14px;
  border: 1px solid rgba(255, 143, 171, 0.3);
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.1) 0%, rgba(56, 189, 248, 0.08) 100%);
  cursor: pointer;
  transition: all 0.25s ease;
  user-select: none;
}

.guide-pill:hover {
  border-color: rgba(255, 117, 151, 0.55);
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.18) 0%, rgba(56, 189, 248, 0.14) 100%);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.2);
  transform: translateY(-1px);
}

.guide-pill-icon-wrap {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.3);
  flex-shrink: 0;
}

.guide-pill-text-wrap {
  @apply flex flex-col;
  min-width: 0;
}

.guide-pill-title {
  font-size: 12.5px;
  font-weight: 700;
  color: #ff7597;
  line-height: 1.2;
  white-space: nowrap;
}

.guide-pill-sub {
  font-size: 10px;
  color: #6b7280;
  line-height: 1.2;
  margin-top: 1px;
  white-space: nowrap;
}

.header-right {
  @apply flex items-center gap-3;
  flex-shrink: 0;
}

.connection-pill {
  @apply flex items-center gap-3;
  min-width: 220px;
  padding: 8px 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 143, 171, 0.22);
  background: rgba(255, 255, 255, 0.72);
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease;
}

.connection-pill:hover {
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 8px 20px rgba(255, 117, 151, 0.14), 0 4px 10px rgba(56, 189, 248, 0.1);
  transform: translateY(-1px);
  background: rgba(255, 255, 255, 0.92);
}

.connection-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  flex-shrink: 0;
  box-shadow: 0 0 0 6px rgba(148, 163, 184, 0.12);
}

.connection-dot--success {
  background: #38bdf8;
  box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.25), 0 0 10px rgba(56, 189, 248, 0.5);
}

.connection-dot--error {
  background: #ef4444;
  box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.12);
}

.connection-dot--idle {
  background: #f59e0b;
  box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.12);
}

.connection-copy {
  @apply flex flex-col;
  min-width: 0;
}

.connection-title {
  @apply text-sm font-semibold text-gray-800;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.connection-subtitle {
  @apply text-xs text-gray-500;
  line-height: 1.2;
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-dropdown {
  @apply cursor-pointer;
}

.user-info {
  @apply flex items-center gap-3 cursor-pointer;
  padding: 6px 14px;
  border-radius: 14px;
  transition: all 0.3s ease;
  border: 1px solid rgba(255, 143, 171, 0.18);
  background: rgba(255, 255, 255, 0.72);
}

.user-info:hover {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.12), rgba(56, 189, 248, 0.08));
  border-color: rgba(255, 117, 151, 0.35);
  box-shadow: 0 6px 18px rgba(255, 117, 151, 0.18);
  transform: translateY(-1px);
}

.avatar {
  background: var(--gradient-primary);
  @apply text-white;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.35);
  transition: all 0.3s ease;
}

.user-info:hover .avatar {
  box-shadow: 0 6px 16px rgba(255, 117, 151, 0.5);
  transform: scale(1.05) rotate(3deg);
}

.user-details {
  @apply flex flex-col items-start;
  min-width: 0;
}

.username {
  @apply text-gray-900 font-semibold text-sm;
  line-height: 1.3;
  white-space: nowrap;
}

.user-role {
  @apply text-gray-500 text-xs;
  line-height: 1.3;
  margin-top: 2px;
}

.dropdown-icon {
  @apply text-gray-400;
  font-size: 14px;
  transition: all 0.3s ease;
  flex-shrink: 0;
  margin-left: 4px;
}

.user-info:hover .dropdown-icon {
  color: #ff7597;
  transform: translateY(2px);
}

.user-menu {
  @apply mt-2;
  min-width: 180px;
  border-radius: 14px;
  box-shadow: 0 16px 36px rgba(255, 117, 151, 0.16), 0 8px 16px rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(255, 143, 171, 0.22);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(16px);
  overflow: hidden;
}

.menu-item {
  @apply flex items-center gap-3;
  padding: 12px 20px;
  transition: all 0.2s ease;
}

.menu-item:hover {
  background: linear-gradient(90deg, rgba(255, 117, 151, 0.12), rgba(56, 189, 248, 0.08));
}

.menu-item :deep(.el-icon) {
  font-size: 18px;
  color: #ff7597;
  transition: transform 0.2s ease;
}

.menu-item:hover :deep(.el-icon) {
  transform: scale(1.15);
}

.menu-item :deep(span) {
  @apply text-sm font-medium;
}

.logout-item {
  border-top: 1px solid rgba(229, 231, 235, 0.8);
}

.logout-item :deep(.el-icon) {
  color: #ef4444;
}

.logout-item:hover {
  background: linear-gradient(90deg, rgba(239, 68, 68, 0.08), rgba(220, 38, 38, 0.05));
}

@media (max-width: 768px) {
  .header {
    height: 56px !important;
  }

  .header-content {
    padding: 0 10px;
    gap: 6px;
    height: 56px;
  }

  .header-left {
    flex-shrink: 0;
    min-width: max-content;
  }

  .mobile-brand-group {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }

  .mobile-hamburger-btn {
    padding: 4px;
  }

  .mobile-logo-text {
    font-size: 15px;
    font-weight: 800;
  }

  .guide-pill {
    display: none !important;
  }

  .channel-pill + .server-pill {
    display: none !important;
  }

  .header-right {
    gap: 6px;
    min-width: 0;
    flex-shrink: 1;
    justify-content: flex-end;
  }

  .connection-pill {
    min-width: 0;
    max-width: 140px;
    padding: 4px 8px;
    height: 32px;
    border-radius: 10px;
  }

  .connection-subtitle {
    display: none !important;
  }

  .connection-title {
    font-size: 11px;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .breadcrumb {
    display: none;
  }

  .user-details,
  .dropdown-icon {
    display: none;
  }

  .user-info {
    padding: 2px;
  }

  .user-info .avatar {
    width: 32px !important;
    height: 32px !important;
  }
}
</style>
