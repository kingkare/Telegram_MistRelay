<template>
  <el-container class="app-layout">
    <div class="ambient-glow glow-sakura"></div>
    <div class="ambient-glow glow-sky"></div>
    <div class="ambient-glow glow-center"></div>

    <AppSidebar @collapse-change="handleCollapseChange" />
    <el-container class="main-container" :style="{ marginLeft: sidebarWidth }">
      <AppHeader />
      <el-main class="main-content">
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
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import AppSidebar from './app-sidebar.vue'
import AppHeader from './app-header.vue'

const isCollapsed = ref(false)

const sidebarWidth = computed(() => {
  return isCollapsed.value ? '64px' : '240px'
})

function handleCollapseChange(collapsed: boolean) {
  isCollapsed.value = collapsed
}
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
  filter: blur(80px);
  pointer-events: none;
  z-index: 0;
  opacity: 0.65;
}

.glow-sakura {
  top: -100px;
  left: 10%;
  width: 480px;
  height: 480px;
  background: radial-gradient(circle, rgba(255, 143, 171, 0.35) 0%, rgba(255, 182, 193, 0.05) 70%, transparent 100%);
  animation: floatSlow 12s ease-in-out infinite alternate;
}

.glow-sky {
  bottom: -80px;
  right: 5%;
  width: 520px;
  height: 520px;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.28) 0%, rgba(125, 211, 252, 0.05) 70%, transparent 100%);
  animation: floatSlow 14s ease-in-out infinite alternate-reverse;
}

.glow-center {
  top: 40%;
  left: 45%;
  width: 360px;
  height: 360px;
  background: radial-gradient(circle, rgba(255, 192, 203, 0.2) 0%, rgba(224, 242, 254, 0.08) 70%, transparent 100%);
  animation: pulse 8s ease-in-out infinite;
}

.main-container {
  @apply transition-all duration-300 ease-in-out;
  min-height: 100vh;
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
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

.loading-container {
  @apply p-6;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-radius: 16px;
  border: 1px solid rgba(255, 143, 171, 0.2);
}
</style>