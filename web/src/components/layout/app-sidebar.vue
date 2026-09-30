<template>
  <el-aside
    :width="isCollapse ? '64px' : '240px'"
    class="sidebar"
    :class="{ 'is-collapsed': isCollapse }"
  >
    <div class="logo-container">
      <div v-if="!isCollapse" class="logo">
        <div class="logo-icon-wrapper">
          <el-icon :size="26" class="logo-icon"><Cpu /></el-icon>
        </div>
        <span class="logo-text">MistRelay</span>
      </div>
      <div v-else class="logo-icon-wrapper collapsed" title="MistRelay">
        <el-icon :size="22" class="logo-icon"><Cpu /></el-icon>
      </div>
    </div>
    
    <el-menu
      :default-active="activeRoute"
      :collapse="isCollapse"
      :collapse-transition="false"
      router
      class="sidebar-menu"
      background-color="transparent"
      text-color="#4b5563"
      active-text-color="#ff7597"
      popper-class="sidebar-menu-popper"
      popper-effect="light"
    >
      <el-menu-item index="/dashboard" class="menu-item">
        <el-icon><Odometer /></el-icon>
        <template #title>仪表板</template>
      </el-menu-item>
      
      <el-menu-item index="/downloads" class="menu-item">
        <el-icon><Download /></el-icon>
        <template #title>任务中心</template>
      </el-menu-item>
      
      <el-menu-item index="/drive" class="menu-item">
        <el-icon><Folder /></el-icon>
        <template #title>TG网盘</template>
      </el-menu-item>
      
      <el-menu-item index="/edge-nodes" class="menu-item">
        <el-icon><Share /></el-icon>
        <template #title>边缘分流</template>
      </el-menu-item>
      
      <el-menu-item v-if="authStore.isAdmin" index="/bots" class="menu-item">
        <el-icon><Connection /></el-icon>
        <template #title>集群管理</template>
      </el-menu-item>
      
      <el-menu-item v-if="authStore.isAdmin" index="/botfather" class="menu-item">
        <el-icon><MagicStick /></el-icon>
        <template #title>自动铸机</template>
      </el-menu-item>
      
      <el-menu-item v-if="authStore.isAdmin" index="/users" class="menu-item">
        <el-icon><User /></el-icon>
        <template #title>用户管理</template>
      </el-menu-item>

      <el-menu-item v-if="authStore.isAdmin" index="/cache" class="menu-item">
        <el-icon><Box /></el-icon>
        <template #title>缓存管理</template>
      </el-menu-item>
      
      <el-menu-item v-if="authStore.isAdmin" index="/customer-service" class="menu-item">
        <el-icon><Headset /></el-icon>
        <template #title>AI客服</template>
      </el-menu-item>

      <el-menu-item v-if="authStore.isAdmin" index="/settings" class="menu-item">
        <el-icon><Setting /></el-icon>
        <template #title>系统设置</template>
      </el-menu-item>
    </el-menu>
    
    <div class="sidebar-footer">
      <el-tooltip
        :content="isCollapse ? '展开侧边栏' : '收起侧边栏'"
        placement="right"
        :disabled="!isCollapse"
        popper-class="sidebar-menu-popper"
        :show-after="200"
      >
        <el-button
          :icon="isCollapse ? Expand : Fold"
          text
          @click="toggleCollapse"
          class="collapse-btn"
          :class="{ 'is-collapsed': isCollapse }"
          aria-label="切换侧边栏"
        />
      </el-tooltip>
    </div>
  </el-aside>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  Share,
  Cpu,
  Odometer,
  Download,
  Folder,
  Box,
  Connection,
  User,
  MagicStick,
  Headset,
  Setting,
  Expand,
  Fold
} from '@element-plus/icons-vue'

const route = useRoute()
const authStore = useAuthStore()
const isCollapse = ref(false)

const activeRoute = computed(() => route.path)

const emit = defineEmits<{
  collapseChange: [collapsed: boolean]
}>()

const mobileBreakpoint = 768
let isMobileViewport = false

function setCollapse(nextValue: boolean) {
  if (isCollapse.value === nextValue) return
  isCollapse.value = nextValue
  emit('collapseChange', isCollapse.value)
}

function syncCollapseWithViewport() {
  const nextIsMobile = window.innerWidth <= mobileBreakpoint
  if (nextIsMobile === isMobileViewport) return
  isMobileViewport = nextIsMobile
  if (nextIsMobile) {
    setCollapse(true)
  } else {
    setCollapse(false)
  }
}

function toggleCollapse() {
  setCollapse(!isCollapse.value)
}

onMounted(() => {
  isMobileViewport = window.innerWidth <= mobileBreakpoint
  if (isMobileViewport) {
    setCollapse(true)
  }
  window.addEventListener('resize', syncCollapseWithViewport)
})

onUnmounted(() => {
  window.removeEventListener('resize', syncCollapseWithViewport)
})
</script>

<style scoped>
.sidebar {
  background: rgba(255, 255, 255, 0.96);
  @apply h-screen fixed left-0 top-0 z-50;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 4px 0 24px rgba(255, 117, 151, 0.08);
  border-right: 1px solid rgba(255, 143, 171, 0.22);
  display: flex;
  flex-direction: column;
}

.logo-container {
  @apply h-16 flex items-center justify-center;
  @apply px-4;
  border-bottom: 1px solid rgba(255, 143, 171, 0.18);
  background: rgba(255, 255, 255, 0.6);
  transition: padding 0.25s ease;
  flex-shrink: 0;
}

.sidebar.is-collapsed .logo-container {
  padding: 0 !important;
}

.logo {
  @apply flex items-center gap-3 font-bold text-xl;
}

.logo-icon-wrapper {
  @apply w-10 h-10 rounded-2xl flex items-center justify-center;
  background: var(--gradient-primary);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.35);
  transition: all 0.25s ease;
}

.logo-icon-wrapper.collapsed {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  margin: 0 auto;
}

.logo-icon {
  @apply text-white;
}

.logo-text {
  @apply whitespace-nowrap;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 800;
  letter-spacing: -0.5px;
}

.sidebar-menu {
  @apply border-none;
  height: calc(100vh - 128px);
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px 10px;
  flex: 1 1 auto;
  transition: padding 0.25s ease;
}

/* 二次元细滚动条 */
.sidebar-menu::-webkit-scrollbar {
  width: 4px;
}

.sidebar-menu::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar-menu::-webkit-scrollbar-thumb {
  background: rgba(255, 143, 171, 0.3);
  border-radius: 9999px;
}

/* 展开态下的菜单项 */
.sidebar-menu:deep(.el-menu-item) {
  border-radius: 12px;
  margin: 4px 0;
  padding: 0 14px;
  font-weight: 500;
  border: 1px solid transparent;
  position: relative;
  overflow: hidden;
  transition: background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.sidebar-menu:deep(.el-menu-item):before {
  content: '';
  position: absolute;
  left: 0;
  top: 15%;
  width: 4px;
  height: 70%;
  border-radius: 0 4px 4px 0;
  background: var(--gradient-primary);
  transform: scaleY(0);
  transition: transform 0.18s ease;
}

.sidebar-menu:deep(.el-menu-item:hover) {
  background: rgba(255, 143, 171, 0.1);
  border-color: rgba(255, 143, 171, 0.25);
  color: #ff7597 !important;
}

.sidebar-menu:deep(.el-menu-item:hover):before {
  transform: scaleY(1);
}

.sidebar-menu:deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(255, 117, 151, 0.16) 0%, rgba(56, 189, 248, 0.08) 100%);
  border-color: rgba(255, 117, 151, 0.35);
  color: #ff7597 !important;
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.15);
}

.sidebar-menu:deep(.el-menu-item.is-active):before {
  transform: scaleY(1);
}

.sidebar-menu:deep(.el-menu-item .el-icon) {
  transition: color 0.16s ease, transform 0.16s ease;
  font-size: 18px;
}

.sidebar-menu:deep(.el-menu-item:hover .el-icon) {
  color: #ff7597;
}

.sidebar-menu:deep(.el-menu-item.is-active .el-icon) {
  color: #ff7597;
  filter: drop-shadow(0 0 6px rgba(255, 117, 151, 0.5));
}

/* ========== 折叠收起态 (is-collapsed) 专属二次元晶莹胶囊体系 ========== */
.sidebar.is-collapsed .sidebar-menu {
  padding: 10px 0 !important;
  width: 64px !important;
}

.sidebar.is-collapsed :deep(.el-menu--collapse) {
  width: 64px !important;
  border-right: none !important;
}

.sidebar.is-collapsed :deep(.el-menu-item) {
  width: 44px !important;
  height: 44px !important;
  line-height: 44px !important;
  margin: 6px auto !important;
  padding: 0 !important;
  border-radius: 12px !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  border: 1px solid transparent;
  position: relative !important;
  box-sizing: border-box !important;
  overflow: visible !important;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

/* 隐藏左侧穿模指示条 */
.sidebar.is-collapsed :deep(.el-menu-item):before {
  display: none !important;
  content: none !important;
}

/* 消除 Element Plus 折叠态 tooltip trigger 的固有边距，实现彻底绝对居中 */
.sidebar.is-collapsed :deep(.el-menu-tooltip__trigger) {
  position: absolute !important;
  left: 0 !important;
  top: 0 !important;
  width: 100% !important;
  height: 100% !important;
  padding: 0 !important;
  margin: 0 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  box-sizing: border-box !important;
}

/* 图标轴线居中与微调 */
.sidebar.is-collapsed :deep(.el-menu-item .el-icon) {
  margin: 0 !important;
  font-size: 20px !important;
  width: 20px !important;
  height: 20px !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  text-align: center !important;
  flex-shrink: 0 !important;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 折叠态普通项悬停动效 */
.sidebar.is-collapsed :deep(.el-menu-item:hover:not(.is-active)) {
  background: rgba(255, 143, 171, 0.12) !important;
  border-color: rgba(255, 143, 171, 0.3) !important;
  transform: scale(1.06);
}

.sidebar.is-collapsed :deep(.el-menu-item:hover:not(.is-active) .el-icon) {
  color: #ff7597 !important;
  transform: scale(1.1);
}

/* 折叠态活跃胶囊：晨曦流光双色高亮 + 樱花外发光 */
.sidebar.is-collapsed :deep(.el-menu-item.is-active) {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.22) 0%, rgba(56, 189, 248, 0.16) 100%) !important;
  border: 1px solid rgba(255, 117, 151, 0.45) !important;
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.24) !important;
  color: #ff7597 !important;
}

.sidebar.is-collapsed :deep(.el-menu-item.is-active .el-icon) {
  color: #ff7597 !important;
  filter: drop-shadow(0 0 6px rgba(255, 117, 151, 0.65)) !important;
}

/* 底部收折切换栏 */
.sidebar-footer {
  @apply h-16 flex items-center justify-center;
  border-top: 1px solid rgba(255, 143, 171, 0.18);
  background: rgba(255, 255, 255, 0.4);
  transition: padding 0.25s ease;
  flex-shrink: 0;
}

.sidebar.is-collapsed .sidebar-footer {
  padding: 0 !important;
}

.collapse-btn {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  color: #9ca3af;
  border: 1px solid transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.collapse-btn:hover {
  color: #ff7597;
  background: rgba(255, 143, 171, 0.12);
  border-color: rgba(255, 143, 171, 0.25);
  transform: scale(1.08);
  box-shadow: 0 2px 10px rgba(255, 117, 151, 0.2);
}

.collapse-btn.is-collapsed {
  background: rgba(255, 143, 171, 0.08);
  border-color: rgba(255, 143, 171, 0.18);
  color: #ff7597;
}

.collapse-btn.is-collapsed:hover {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.2) 0%, rgba(56, 189, 248, 0.15) 100%);
  border-color: rgba(255, 117, 151, 0.4);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.25);
}

.collapse-btn :deep(.el-icon) {
  font-size: 20px;
}
</style>
