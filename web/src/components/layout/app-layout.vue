<template>
  <el-container class="app-layout">
    <div class="ambient-glow glow-sakura"></div>
    <div class="ambient-glow glow-sky"></div>
    <div class="ambient-glow glow-center"></div>

    <!-- 桌面端侧边栏 (移动端隐藏) -->
    <AppSidebar v-if="!isMobile" @collapse-change="handleCollapseChange" />

    <el-container
      class="main-container"
      :style="{ marginLeft: isMobile ? '0px' : sidebarWidth }"
      :class="{ 'is-mobile-layout': isMobile }"
    >
      <AppHeader
        :is-mobile="isMobile"
        @toggle-drawer="mobileDrawerVisible = !mobileDrawerVisible"
        @open-guide="handleOpenGuide"
      />
      <el-main class="main-content" :class="{ 'main-content--mobile': isMobile }">
        <router-view v-slot="{ Component }">
          <Suspense>
            <component :is="Component" />
            <template #fallback>
              <div class="loading-container">
                <el-skeleton :rows="8" animated />
              </div>
            </template>
          </Suspense>
        </router-view>
      </el-main>
    </el-container>

    <!-- 移动端底部高频导航栏 -->
    <AppBottomNav
      v-if="isMobile"
      :is-drawer-open="mobileDrawerVisible"
      @toggle-drawer="mobileDrawerVisible = !mobileDrawerVisible"
    />

    <!-- 移动端全局全功能导航抽屉 -->
    <AppMobileDrawer
      v-model="mobileDrawerVisible"
      @open-guide="handleOpenGuide"
    />
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import AppSidebar from './app-sidebar.vue'
import AppHeader from './app-header.vue'
import AppBottomNav from './AppBottomNav.vue'
import AppMobileDrawer from './AppMobileDrawer.vue'

const isCollapsed = ref(false)
const isMobile = ref(false)
const mobileDrawerVisible = ref(false)

const sidebarWidth = computed(() => {
  return isCollapsed.value ? '64px' : '240px'
})

function handleCollapseChange(collapsed: boolean) {
  isCollapsed.value = collapsed
}

function updateViewport() {
  if (typeof window !== 'undefined') {
    isMobile.value = window.innerWidth < 768
  }
}

function handleOpenGuide() {
  // 通过自定义事件广播触发新手教程抽屉
  window.dispatchEvent(new CustomEvent('mistrelay:open-guide', { detail: 'quickstart' }))
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>

<style scoped>
.app-layout {
  @apply min-h-screen;
  background-color: #fcf6f8;
  position: relative;
  overflow-x: hidden;
}

/* 二次元柔和双色光晕背景球 */
.ambient-glow {
  position: fixed;
  border-radius: 9999px;
  pointer-events: none;
  z-index: 0;
  opacity: 0.65;
}

.glow-sakura {
  top: -120px;
  left: 8%;
  width: 560px;
  height: 560px;
  background: radial-gradient(circle, rgba(255, 143, 171, 0.28) 0%, rgba(255, 182, 193, 0.08) 55%, transparent 75%);
}

.glow-sky {
  bottom: -100px;
  right: 4%;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.22) 0%, rgba(125, 211, 252, 0.06) 55%, transparent 75%);
}

.glow-center {
  top: 36%;
  left: 42%;
  width: 440px;
  height: 440px;
  background: radial-gradient(circle, rgba(255, 192, 203, 0.16) 0%, rgba(224, 242, 254, 0.06) 55%, transparent 75%);
}

.main-container {
  transition: margin-left 0.25s ease-in-out;
  min-height: 100vh;
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
}

.main-container.is-mobile-layout {
  margin-left: 0 !important;
  width: 100% !important;
  max-width: 100vw !important;
  overflow-x: hidden;
}

:deep(.el-container.main-container) {
  width: 100%;
  max-width: 100%;
  overflow-x: hidden;
}

:deep(.el-header) {
  width: 100% !important;
  max-width: 100%;
  padding: 0;
  margin: 0;
}

.main-content {
  @apply p-6;
  min-height: calc(100vh - 64px);
  animation: fadeIn 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.main-content--mobile {
  padding: 12px 10px calc(72px + env(safe-area-inset-bottom, 0px)) !important;
  min-height: calc(100vh - 56px);
  overflow-x: hidden;
}

.loading-container {
  @apply p-6;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-radius: 16px;
  border: 1px solid rgba(255, 143, 171, 0.2);
}
</style>
