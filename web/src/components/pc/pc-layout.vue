<template>
  <div class="pc-client pc-shell">
    <aside class="pc-sidebar" aria-label="PC navigation">
      <div class="pc-brand">
        <span class="pc-brand-mark">M</span>
        <span class="pc-brand-name">MistRelay</span>
      </div>

      <nav class="pc-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          :to="item.to"
          class="pc-sidebar-link"
          active-class="is-active"
        >
          <component :is="item.icon" class="pc-nav-icon" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </aside>

    <section class="pc-main">
      <header class="pc-toolbar">
        <h1 class="pc-page-title">{{ currentTitle }}</h1>
      </header>

      <main class="pc-content">
        <RouterView />
      </main>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { Clock, Download, FolderOpened, Setting } from '@element-plus/icons-vue'

const route = useRoute()

const navItems = [
  { name: 'PcDrive', label: '网盘', to: '/pc/drive', icon: FolderOpened },
  { name: 'PcRecent', label: '最近', to: '/pc/recent', icon: Clock },
  { name: 'PcDownloads', label: '下载', to: '/pc/downloads', icon: Download },
  { name: 'PcSettings', label: '设置', to: '/pc/settings', icon: Setting },
]

const currentTitle = computed(() => {
  const current = navItems.find(item => item.name === route.name)
  return current?.label || 'MistRelay'
})
</script>

<style scoped>
.pc-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 0 10px 12px;
  border-bottom: 1px solid var(--pc-color-border);
}

.pc-brand-mark {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-primary);
  color: #ffffff;
  font-weight: 700;
}

.pc-brand-name {
  min-width: 0;
  color: var(--pc-color-text);
  font-size: 15px;
  font-weight: 700;
}

.pc-nav {
  display: grid;
  gap: 4px;
}

.pc-nav-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.pc-page-title {
  margin: 0;
  color: var(--pc-color-text);
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
}
</style>
