<template>
  <el-drawer
    v-model="visible"
    direction="ltr"
    size="285px"
    :with-header="false"
    class="mobile-nav-drawer"
  >
    <div class="drawer-container">
      <!-- 顶部品牌与用户信息 -->
      <div class="drawer-header">
        <div class="brand-row">
          <div class="logo-icon-wrapper">
            <el-icon :size="22" class="logo-icon"><Cpu /></el-icon>
          </div>
          <span class="logo-text">MistRelay</span>
          <el-button
            circle
            text
            class="close-btn"
            :icon="Close"
            @click="visible = false"
          />
        </div>

        <div class="user-card" v-if="authStore.user">
          <el-avatar :size="42" class="drawer-avatar">
            <el-icon><User /></el-icon>
          </el-avatar>
          <div class="user-meta">
            <div class="user-name-row">
              <span class="username">{{ authStore.user.username }}</span>
              <el-tag size="small" :type="authStore.isAdmin ? 'danger' : 'info'" effect="light" class="role-tag">
                {{ authStore.isAdmin ? '管理员' : '用户' }}
              </el-tag>
            </div>
            <span class="user-dc" v-if="authStore.user.bin_channel_username || authStore.user.bin_channel_id">
              📡 DC{{ authStore.user.dc_id || 5 }} · @{{ authStore.user.bin_channel_username || authStore.user.bin_channel_id }}
            </span>
          </div>
        </div>
      </div>

      <!-- 导航主体列表 -->
      <div class="drawer-menu-list">
        <div class="menu-section-title">核心导航</div>
        <router-link
          v-for="item in primaryRoutes"
          :key="item.path"
          :to="item.path"
          class="menu-link-item"
          :class="{ 'is-active': activeRoute === item.path }"
          @click="visible = false"
        >
          <el-icon class="menu-icon"><component :is="item.icon" /></el-icon>
          <span class="menu-title">{{ item.title }}</span>
        </router-link>

        <template v-if="authStore.isAdmin">
          <div class="menu-section-title">集群管理中台</div>
          <router-link
            v-for="item in adminRoutes"
            :key="item.path"
            :to="item.path"
            class="menu-link-item"
            :class="{ 'is-active': activeRoute === item.path }"
            @click="visible = false"
          >
            <el-icon class="menu-icon"><component :is="item.icon" /></el-icon>
            <span class="menu-title">{{ item.title }}</span>
          </router-link>
        </template>
      </div>

      <!-- 底部操作区 -->
      <div class="drawer-footer">
        <button type="button" class="footer-action-btn" @click="handleOpenGuide">
          <el-icon><Reading /></el-icon>
          <span>新手教程与 FAQ</span>
        </button>
        <button type="button" class="footer-action-btn logout-btn" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon>
          <span>退出登录</span>
        </button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  Cpu,
  Close,
  User,
  Odometer,
  Download,
  Folder,
  Share,
  Connection,
  MagicStick,
  Box,
  Headset,
  Setting,
  Reading,
  SwitchButton
} from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  openGuide: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (val: boolean) => emit('update:modelValue', val)
})

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const activeRoute = computed(() => route.path)

const primaryRoutes = [
  { path: '/dashboard', title: '仪表板', icon: Odometer },
  { path: '/downloads', title: '任务中心', icon: Download },
  { path: '/drive', title: 'TG网盘', icon: Folder },
  { path: '/edge-nodes', title: '边缘分流', icon: Share }
]

const adminRoutes = [
  { path: '/bots', title: '集群管理', icon: Connection },
  { path: '/botfather', title: '自动铸机', icon: MagicStick },
  { path: '/users', title: '用户管理', icon: User },
  { path: '/cache', title: '缓存管理', icon: Box },
  { path: '/customer-service', title: 'AI客服', icon: Headset },
  { path: '/settings', title: '系统设置', icon: Setting }
]

function handleOpenGuide() {
  visible.value = false
  emit('openGuide')
}

function handleLogout() {
  visible.value = false
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
:deep(.el-drawer) {
  background: rgba(255, 255, 255, 0.98) !important;
  backdrop-filter: blur(20px);
}

:deep(.el-drawer__body) {
  padding: 0;
  height: 100%;
}

.drawer-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding-bottom: env(safe-area-inset-bottom, 12px);
  padding-top: env(safe-area-inset-top, 0px);
}

.drawer-header {
  padding: 16px 18px 14px;
  border-bottom: 1px solid rgba(255, 143, 171, 0.18);
  background: linear-gradient(180deg, rgba(255, 245, 247, 0.8) 0%, rgba(255, 255, 255, 0.4) 100%);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 10px;
  position: relative;
}

.logo-icon-wrapper {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-primary);
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.35);
  color: white;
}

.logo-text {
  font-size: 19px;
  font-weight: 800;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  flex: 1;
}

.close-btn {
  color: #9ca3af;
  font-size: 18px;
}

.user-card {
  margin-top: 14px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.22);
  border-radius: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.drawer-avatar {
  background: var(--gradient-primary);
  color: white;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(255, 117, 151, 0.3);
}

.user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.user-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.username {
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-tag {
  height: 20px;
  padding: 0 6px;
  font-size: 10px;
  border-radius: 6px;
}

.user-dc {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-menu-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
}

.menu-section-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: #9ca3af;
  padding: 8px 10px 4px;
  letter-spacing: 0.5px;
}

.menu-link-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin: 3px 0;
  border-radius: 12px;
  color: #4b5563;
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  transition: all 0.18s ease;
  border: 1px solid transparent;
}

.menu-icon {
  font-size: 17px;
  color: #6b7280;
  transition: color 0.18s ease;
}

.menu-link-item:hover,
.menu-link-item:active {
  background: rgba(255, 143, 171, 0.12);
  color: #ff7597;
}

.menu-link-item:hover .menu-icon,
.menu-link-item:active .menu-icon {
  color: #ff7597;
}

.menu-link-item.is-active {
  background: linear-gradient(90deg, rgba(255, 117, 151, 0.16) 0%, rgba(56, 189, 248, 0.08) 100%);
  border-color: rgba(255, 117, 151, 0.35);
  color: #ff7597;
  font-weight: 700;
  box-shadow: 0 3px 10px rgba(255, 117, 151, 0.12);
}

.menu-link-item.is-active .menu-icon {
  color: #ff7597;
}

.drawer-footer {
  padding: 12px 14px;
  border-top: 1px solid rgba(255, 143, 171, 0.18);
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: rgba(255, 255, 255, 0.6);
}

.footer-action-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 143, 171, 0.2);
  background: rgba(255, 255, 255, 0.8);
  color: #4b5563;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.footer-action-btn:hover,
.footer-action-btn:active {
  background: rgba(255, 143, 171, 0.15);
  color: #ff7597;
  border-color: rgba(255, 143, 171, 0.4);
}

.logout-btn {
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.2);
}

.logout-btn:hover,
.logout-btn:active {
  background: rgba(239, 68, 68, 0.08);
  color: #dc2626;
  border-color: rgba(239, 68, 68, 0.35);
}
</style>
