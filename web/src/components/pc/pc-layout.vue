<template>
  <div class="pc-client pc-shell">
    <aside class="pc-sidebar" aria-label="PC navigation">
      <div class="pc-brand">
        <span class="pc-brand-mark" aria-hidden="true">
          <el-icon :size="19"><Promotion /></el-icon>
        </span>
        <span class="pc-brand-copy">
          <span class="pc-brand-name">MistRelay</span>
          <span class="pc-brand-edition">DESKTOP</span>
        </span>
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

      <div class="pc-sidebar-footer">
        <div class="pc-sidebar-account">
          <span class="pc-sidebar-avatar">{{ accountInitial }}</span>
          <span class="pc-sidebar-account-copy">
            <strong>{{ accountName }}</strong>
            <span :title="serverLabel">{{ serverLabel }}</span>
          </span>
        </div>
      </div>
    </aside>

    <section class="pc-main">
      <header class="pc-toolbar">
        <div class="pc-page-heading">
          <span class="pc-page-context">MistRelay</span>
          <h1 class="pc-page-title">{{ currentTitle }}</h1>
        </div>
        <div class="pc-toolbar-status" :title="serverLabel">
          <span class="pc-status-dot" aria-hidden="true"></span>
          <span>{{ serverLabel }}</span>
        </div>
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
import { Clock, Download, FolderOpened, Promotion, Setting } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getServerBaseUrl } from '@/utils/runtime'

const route = useRoute()
const auth = useAuthStore()

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

const accountName = computed(() => auth.user?.username || 'MistRelay')
const accountInitial = computed(() => accountName.value.trim().slice(0, 1).toUpperCase() || 'M')
const serverLabel = computed(() => {
  const serverUrl = getServerBaseUrl()
  if (!serverUrl) return '本地服务'
  try {
    return new URL(serverUrl).host
  } catch {
    return serverUrl.replace(/^https?:\/\//i, '')
  }
})
</script>

<style scoped>
.pc-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 48px;
  padding: 0 8px 15px;
  border-bottom: 1px solid var(--pc-color-border);
}

.pc-brand-mark {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--pc-radius-md);
  background: var(--pc-gradient-brand);
  color: #ffffff;
  box-shadow: 0 5px 12px rgba(89, 101, 215, 0.24);
  flex: 0 0 auto;
}

.pc-brand-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.pc-brand-name {
  min-width: 0;
  color: var(--pc-color-text);
  font-size: 15px;
  font-weight: 750;
  line-height: 1.2;
}

.pc-brand-edition {
  color: var(--pc-color-text-muted);
  font-size: 9px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: 0;
}

.pc-nav {
  display: grid;
  gap: 5px;
  margin-top: 18px;
}

.pc-nav-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.pc-sidebar-footer {
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--pc-color-border);
}

.pc-sidebar-account {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 4px 6px;
}

.pc-sidebar-avatar {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid #d9dcf5;
  border-radius: 50%;
  background: var(--pc-color-accent-soft);
  color: var(--pc-color-accent);
  font-size: 12px;
  font-weight: 750;
  flex: 0 0 auto;
}

.pc-sidebar-account-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.pc-sidebar-account-copy strong,
.pc-sidebar-account-copy span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-sidebar-account-copy strong {
  color: var(--pc-color-text);
  font-size: 12px;
  font-weight: 650;
}

.pc-sidebar-account-copy span {
  color: var(--pc-color-text-muted);
  font-size: 10px;
}

.pc-page-heading {
  display: flex;
  align-items: baseline;
  min-width: 0;
  gap: 8px;
}

.pc-page-context {
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-page-context::after {
  margin-left: 8px;
  color: var(--pc-color-border-strong);
  content: "/";
}

.pc-page-title {
  margin: 0;
  color: var(--pc-color-text);
  font-size: 18px;
  font-weight: 750;
  line-height: 1.2;
}

.pc-toolbar-status {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  max-width: 280px;
  margin-left: auto;
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-toolbar-status span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--pc-color-success);
  box-shadow: 0 0 0 3px rgba(60, 155, 115, 0.12);
  flex: 0 0 auto;
}

@media (max-width: 720px) {
  .pc-brand {
    min-height: auto;
    padding: 0;
    border-bottom: 0;
  }

  .pc-nav {
    display: flex;
    justify-content: flex-end;
    min-width: 0;
    margin-top: 0;
    overflow-x: auto;
  }

  .pc-sidebar-link {
    flex: 0 0 auto;
    padding: 0 9px;
  }

  .pc-sidebar-link::before {
    top: auto;
    right: 10px;
    bottom: 1px;
    left: 10px;
    width: auto;
    height: 2px;
    transform: scaleX(0.5);
  }

  .pc-sidebar-link.is-active::before {
    transform: scaleX(1);
  }

  .pc-page-context {
    display: none;
  }
}
</style>
