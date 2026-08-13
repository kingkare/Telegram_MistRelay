<template>
  <div class="pc-client pc-shell">
    <aside class="pc-sidebar" aria-label="PC 客户端导航">
      <div class="pc-brand">
        <img class="pc-brand-mark" :src="appMark" alt="">
        <span class="pc-brand-copy">
          <strong>MistRelay</strong>
          <span>DESKTOP</span>
        </span>
      </div>

      <nav class="pc-nav" aria-label="主要功能">
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          :to="item.to"
          class="pc-sidebar-link"
          :class="{ 'is-active': route.name === item.name }"
          :title="item.label"
          :aria-label="item.label"
        >
          <component :is="item.icon" class="pc-nav-icon" aria-hidden="true" />
          <span class="pc-nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="pc-sidebar-footer">
        <RouterLink
          to="/pc/settings"
          class="pc-sidebar-account"
          title="账户与服务器设置"
          aria-label="账户与服务器设置"
        >
          <span class="pc-sidebar-avatar" aria-hidden="true">{{ accountInitial }}</span>
          <span class="pc-sidebar-account-copy">
            <strong>{{ accountName }}</strong>
            <span :title="serverLabel">{{ serverLabel }}</span>
          </span>
        </RouterLink>
      </div>
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
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { Clock, Download, FolderOpened, Setting } from '@element-plus/icons-vue'
import appMark from '@/assets/pc-theme/app-mark.svg'
import { useAuthStore } from '@/stores/auth'
import { getServerBaseUrl } from '@/utils/runtime'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const navItems = [
  { name: 'PcDrive', label: '网盘', to: '/pc/drive', icon: FolderOpened },
  { name: 'PcRecent', label: '最近', to: '/pc/recent', icon: Clock },
  { name: 'PcDownloads', label: '下载', to: '/pc/downloads', icon: Download },
  { name: 'PcSettings', label: '设置', to: '/pc/settings', icon: Setting },
]

const currentTitle = computed(() => (
  navItems.find(item => item.name === route.name)?.label || 'MistRelay'
))
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

onMounted(async () => {
  if (!auth.isLoggedIn || auth.user) return
  await auth.fetchUser()
  if (!auth.isLoggedIn) await router.replace('/pc/login')
})
</script>

<style scoped>
.pc-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 8px 12px;
  border-bottom: 1px solid var(--pc-color-border);
}

.pc-brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  box-shadow: 0 4px 10px rgba(58, 71, 158, 0.18);
  flex: 0 0 auto;
}

.pc-brand-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.pc-brand-copy strong {
  color: var(--pc-color-text);
  font-size: 15px;
  font-weight: 700;
  line-height: 19px;
}

.pc-brand-copy span {
  color: var(--pc-color-text-subtle);
  font-size: 9px;
  font-weight: 600;
  line-height: 12px;
}

.pc-nav {
  display: grid;
  gap: 4px;
  margin-top: 12px;
}

.pc-nav-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.pc-sidebar-footer {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--pc-color-border);
}

.pc-sidebar-account {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  padding: 7px 8px;
  border-radius: var(--pc-radius-md);
  color: inherit;
  text-decoration: none;
  transition: background-color 140ms ease;
}

.pc-sidebar-account:hover,
.pc-sidebar-account:focus-visible {
  background: var(--pc-color-surface-soft);
}

.pc-sidebar-account:focus-visible {
  outline: 3px solid var(--pc-color-focus);
  outline-offset: 2px;
}

.pc-sidebar-avatar {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid #d8dcf1;
  border-radius: 50%;
  background: var(--pc-color-primary-soft);
  color: var(--pc-color-primary-strong);
  font-size: 12px;
  font-weight: 700;
  flex: 0 0 auto;
}

.pc-sidebar-account-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
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
  font-weight: 600;
  line-height: 16px;
}

.pc-sidebar-account-copy span {
  color: var(--pc-color-text-muted);
  font-size: 10px;
  line-height: 14px;
}

.pc-page-title {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--pc-color-text);
  font-size: 18px;
  font-weight: 700;
  line-height: 24px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .pc-brand {
    justify-content: center;
    padding-right: 0;
    padding-left: 0;
  }

  .pc-brand-copy,
  .pc-nav-label,
  .pc-sidebar-account-copy {
    display: none;
  }

  .pc-sidebar-account {
    justify-content: center;
    padding-right: 0;
    padding-left: 0;
  }
}
</style>
