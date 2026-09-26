<template>
  <el-aside :width="isCollapse ? '64px' : '240px'" class="sidebar">
    <div class="logo-container">
      <div v-if="!isCollapse" class="logo">
        <div class="logo-icon-wrapper">
          <el-icon :size="26" class="logo-icon"><Cpu /></el-icon>
        </div>
        <span class="logo-text">MistRelay</span>
      </div>
      <div v-else class="logo-icon-wrapper collapsed">
        <el-icon :size="26" class="logo-icon"><Cpu /></el-icon>
      </div>
    </div>
    
    <el-menu
      :default-active="activeRoute"
      :collapse="isCollapse"
      router
      class="sidebar-menu"
      background-color="transparent"
      text-color="#4b5563"
      active-text-color="#ff7597"
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
      
      <el-menu-item index="/bots" class="menu-item">
        <el-icon><Connection /></el-icon>
        <template #title>集群管理</template>
      </el-menu-item>
      
      <el-menu-item index="/botfather" class="menu-item">
        <el-icon><MagicStick /></el-icon>
        <template #title>自动铸机</template>
      </el-menu-item>
      
      <el-menu-item index="/cache" class="menu-item">
        <el-icon><Box /></el-icon>
        <template #title>缓存管理</template>
      </el-menu-item>
      
      <el-menu-item index="/settings" class="menu-item">
        <el-icon><Setting /></el-icon>
        <template #title>系统设置</template>
      </el-menu-item>
      
    </el-menu>
    
    <div class="sidebar-footer">
      <el-button
        :icon="isCollapse ? Expand : Fold"
        circle
        text
        @click="toggleCollapse"
        class="collapse-btn"
      />
    </div>
  </el-aside>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Cpu,
  Odometer,
  Download,
  Folder,
  Box,
  Connection,
  MagicStick,
  Setting,
  Expand,
  Fold
} from '@element-plus/icons-vue'

const route = useRoute()
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
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  @apply h-screen fixed left-0 top-0 transition-all duration-300 ease-in-out z-50;
  box-shadow: 4px 0 24px rgba(255, 117, 151, 0.1);
  border-right: 1px solid rgba(255, 143, 171, 0.22);
}

.logo-container {
  @apply h-16 flex items-center justify-center;
  @apply px-4;
  border-bottom: 1px solid rgba(255, 143, 171, 0.18);
  background: rgba(255, 255, 255, 0.4);
}

.logo {
  @apply flex items-center gap-3 font-bold text-xl;
  animation: slideInLeft 0.5s ease-out;
}

.logo-icon-wrapper {
  @apply w-10 h-10 rounded-2xl flex items-center justify-center;
  background: var(--gradient-primary);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.35);
  animation: glow 3s ease-in-out infinite;
}

.logo-icon-wrapper.collapsed {
  @apply w-11 h-11;
}

.logo-icon {
  @apply text-white;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.15));
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
  padding: 12px 10px;
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

.sidebar-menu:deep(.el-menu-item) {
  border-radius: 12px;
  margin: 4px 0;
  padding: 0 14px;
  font-weight: 500;
  border: 1px solid transparent;
  position: relative;
  overflow: hidden;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
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
  transition: transform 0.25s ease;
}

.sidebar-menu:deep(.el-menu-item:hover) {
  background: rgba(255, 143, 171, 0.1);
  border-color: rgba(255, 143, 171, 0.25);
  color: #ff7597 !important;
  transform: translateX(3px);
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
  transition: transform 0.25s ease;
  font-size: 18px;
}

.sidebar-menu:deep(.el-menu-item:hover .el-icon) {
  transform: scale(1.15);
  color: #ff7597;
}

.sidebar-menu:deep(.el-menu-item.is-active .el-icon) {
  color: #ff7597;
  filter: drop-shadow(0 0 6px rgba(255, 117, 151, 0.5));
}

.sidebar-menu:deep(.el-menu--collapse .el-menu-item) {
  @apply flex items-center justify-center;
}

.sidebar-footer {
  @apply h-16 flex items-center justify-center;
  border-top: 1px solid rgba(255, 143, 171, 0.18);
  background: rgba(255, 255, 255, 0.4);
}

.collapse-btn {
  color: #9ca3af;
  transition: all 0.25s ease;
}

.collapse-btn:hover {
  color: #ff7597;
  background: rgba(255, 143, 171, 0.12);
  transform: scale(1.1);
  box-shadow: 0 2px 10px rgba(255, 117, 151, 0.25);
}
</style>