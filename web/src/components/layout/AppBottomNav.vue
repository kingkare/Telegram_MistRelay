<template>
  <nav class="app-bottom-nav md:hidden" aria-label="移动端主导航">
    <div class="nav-container">
      <router-link
        to="/dashboard"
        class="nav-tab"
        :class="{ 'is-active': activeRoute === '/dashboard' }"
      >
        <div class="tab-icon-wrap">
          <el-icon :size="20"><Odometer /></el-icon>
        </div>
        <span class="tab-label">仪表板</span>
      </router-link>

      <router-link
        to="/downloads"
        class="nav-tab"
        :class="{ 'is-active': activeRoute === '/downloads' || activeRoute === '/tasks' }"
      >
        <div class="tab-icon-wrap">
          <el-icon :size="20"><Download /></el-icon>
        </div>
        <span class="tab-label">任务</span>
      </router-link>

      <router-link
        to="/drive"
        class="nav-tab nav-tab--primary"
        :class="{ 'is-active': activeRoute === '/drive' }"
      >
        <div class="tab-icon-wrap primary-icon">
          <el-icon :size="22"><Folder /></el-icon>
        </div>
        <span class="tab-label">TG网盘</span>
      </router-link>

      <router-link
        to="/edge-nodes"
        class="nav-tab"
        :class="{ 'is-active': activeRoute === '/edge-nodes' }"
      >
        <div class="tab-icon-wrap">
          <el-icon :size="20"><Share /></el-icon>
        </div>
        <span class="tab-label">分流</span>
      </router-link>

      <button
        type="button"
        class="nav-tab"
        :class="{ 'is-active': isDrawerOpen }"
        @click="emit('toggleDrawer')"
      >
        <div class="tab-icon-wrap">
          <el-icon :size="20"><Menu /></el-icon>
        </div>
        <span class="tab-label">更多</span>
      </button>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Odometer,
  Download,
  Folder,
  Share,
  Menu
} from '@element-plus/icons-vue'

defineProps<{
  isDrawerOpen?: boolean
}>()

const emit = defineEmits<{
  toggleDrawer: []
}>()

const route = useRoute()
const activeRoute = computed(() => route.path)
</script>

<style scoped>
.app-bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 45;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid rgba(255, 143, 171, 0.25);
  box-shadow: 0 -4px 20px rgba(255, 117, 151, 0.1);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  touch-action: manipulation;
  contain: layout style paint;
}

.nav-container {
  display: flex;
  align-items: center;
  justify-content: space-around;
  height: 58px;
  max-width: 540px;
  margin: 0 auto;
  padding: 0 4px;
}

.nav-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  height: 100%;
  color: #6b7280;
  text-decoration: none;
  background: transparent;
  border: none;
  outline: none;
  cursor: pointer;
  padding: 4px 0 2px;
  transition: transform 0.15s ease, color 0.15s ease;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}

.nav-tab:active {
  transform: scale(0.92);
}

.tab-icon-wrap {
  width: 28px;
  height: 28px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.tab-label {
  font-size: 11px;
  font-weight: 500;
  line-height: 1.2;
  margin-top: 2px;
  transition: color 0.2s ease, font-weight 0.2s ease;
}

.nav-tab.is-active {
  color: #ff7597;
}

.nav-tab.is-active .tab-icon-wrap {
  background: rgba(255, 117, 151, 0.12);
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.2);
}

.nav-tab.is-active .tab-label {
  font-weight: 700;
  color: #ff7597;
}

/* TG 网盘核心突出大卡效果 */
.nav-tab--primary .primary-icon {
  background: var(--gradient-primary);
  color: white;
  width: 32px;
  height: 32px;
  border-radius: 12px;
  box-shadow: 0 3px 10px rgba(255, 117, 151, 0.35);
  transform: translateY(-4px);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.nav-tab--primary.is-active .primary-icon {
  transform: translateY(-6px) scale(1.08);
  box-shadow: 0 6px 16px rgba(255, 117, 151, 0.5);
}

.nav-tab--primary .tab-label {
  margin-top: 0px;
}
</style>
