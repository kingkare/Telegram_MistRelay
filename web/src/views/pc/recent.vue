<template>
  <section class="pc-recent-view">
    <div class="pc-recent-tabs-header">
      <div
        class="pc-recent-tabs"
        role="tablist"
        aria-label="最近文件来源"
        data-testid="pc-recent-tabs"
      >
        <button
          id="pc-recent-tab-server"
          class="pc-recent-tab"
          :class="{ 'is-active': activeTab === 'server' }"
          type="button"
          role="tab"
          aria-controls="pc-recent-panel-server"
          :aria-selected="activeTab === 'server'"
          :tabindex="activeTab === 'server' ? 0 : -1"
          @click="activeTab = 'server'"
          @keydown.right.prevent="selectTab('local')"
        >
          最近入库
        </button>
        <button
          id="pc-recent-tab-local"
          class="pc-recent-tab"
          :class="{ 'is-active': activeTab === 'local' }"
          type="button"
          role="tab"
          aria-controls="pc-recent-panel-local"
          :aria-selected="activeTab === 'local'"
          :tabindex="activeTab === 'local' ? 0 : -1"
          @click="activeTab = 'local'"
          @keydown.left.prevent="selectTab('server')"
        >
          本机最近
        </button>
      </div>

      <el-tooltip v-if="activeTab === 'server'" content="刷新最近入库" placement="bottom">
        <el-button
          class="pc-recent-icon-button"
          :icon="RefreshRight"
          :loading="serverLoading"
          aria-label="刷新最近入库"
          @click="loadServerRecent"
        />
      </el-tooltip>
      <el-tooltip v-else content="清除本机记录" placement="bottom">
        <el-button
          class="pc-recent-icon-button"
          :icon="Delete"
          :disabled="!recent.records.length"
          aria-label="清除本机记录"
          @click="clearLocalRecent"
        />
      </el-tooltip>
    </div>

    <div
      v-if="activeTab === 'server'"
      id="pc-recent-panel-server"
      class="pc-recent-panel"
      role="tabpanel"
      aria-labelledby="pc-recent-tab-server"
    >
      <div v-if="serverLoading" class="pc-media-grid" aria-label="正在加载最近入库">
        <div
          v-for="index in 12"
          :key="index"
          class="pc-card pc-media-card pc-recent-skeleton"
          aria-hidden="true"
        >
          <span class="pc-media-cover pc-recent-skeleton-cover"></span>
          <span class="pc-media-body pc-recent-skeleton-body">
            <span></span>
            <span></span>
          </span>
        </div>
      </div>
      <PcStatePanel
        v-else-if="serverError"
        asset="connection-error"
        :title="serverError"
        action-label="重试"
        :action-icon="RefreshRight"
        @action="loadServerRecent"
      />
      <DriveGrid
        v-else-if="serverItems.length"
        :items="serverItems"
        :show-delete="false"
        @open="handleOpen"
      />
      <PcStatePanel v-else asset="empty-drive" title="暂无最近入库" />
    </div>

    <div
      v-else
      id="pc-recent-panel-local"
      class="pc-recent-panel"
      role="tabpanel"
      aria-labelledby="pc-recent-tab-local"
    >
      <div
        v-if="recent.records.length"
        class="pc-local-recent-list"
        data-testid="pc-local-recent-list"
      >
        <button
          v-for="record in recent.records"
          :key="record.id"
          class="pc-local-recent-row"
          type="button"
          @click="handleOpen(record.item)"
        >
          <span class="pc-local-recent-icon" aria-hidden="true">
            <el-icon :size="18">
              <Folder v-if="isTelegramDriveFolder(record.item)" />
              <Document v-else />
            </el-icon>
          </span>
          <span class="pc-local-recent-file">
            <strong :title="getItemTitle(record.item)">{{ getItemTitle(record.item) }}</strong>
            <span>{{ getItemMeta(record.item) }}</span>
          </span>
          <span class="pc-local-recent-action" :class="`is-${record.action}`">
            <el-icon :size="14">
              <Download v-if="record.action === 'download'" />
              <View v-else />
            </el-icon>
            {{ record.action === 'download' ? '已下载' : '已预览' }}
          </span>
          <time class="pc-local-recent-time" :datetime="record.accessedAt">
            {{ formatDate(record.accessedAt) }}
          </time>
        </button>
      </div>

      <PcStatePanel v-else asset="empty-drive" title="暂无本机记录" />
    </div>

    <MediaPreview
      v-model="previewItem"
      :items="previewItems"
      :allow-delete="false"
      @download="handleDownload"
      @save-as="handleSaveAs"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Document, Download, Folder, RefreshRight, View } from '@element-plus/icons-vue'
import DriveGrid from '@/components/pc/drive-grid.vue'
import MediaPreview from '@/components/pc/media-preview.vue'
import PcStatePanel from '@/components/pc/pc-state-panel.vue'
import {
  browseTelegramDrive,
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveItem,
} from '@/api'
import { usePcDriveStore } from '@/stores/pcDrive'
import { usePcRecentStore } from '@/stores/pcRecent'
import { formatDate, formatSize } from '@/utils/formatters'
import { queueTelegramDownload } from '@/utils/pcDownload'

type RecentTab = 'server' | 'local'

const router = useRouter()
const drive = usePcDriveStore()
const recent = usePcRecentStore()
const activeTab = ref<RecentTab>('server')
const serverItems = ref<TelegramDriveItem[]>([])
const serverLoading = ref(false)
const serverError = ref('')
const previewItem = ref<TelegramDriveItem | null>(null)

const localRecentItems = computed(() => recent.records.map(record => record.item))
const previewItems = computed(() => (
  activeTab.value === 'server' ? serverItems.value : localRecentItems.value
).filter(isTelegramDriveFile))

async function selectTab(tab: RecentTab) {
  activeTab.value = tab
  await nextTick()
  document.getElementById(`pc-recent-tab-${tab}`)?.focus()
}

onMounted(() => {
  recent.reload()
  loadServerRecent()
})

async function loadServerRecent() {
  serverLoading.value = true
  serverError.value = ''
  try {
    const response = await browseTelegramDrive({
      page: 1,
      page_size: 12,
      sort_by: 'message_date',
      sort_desc: true,
    })
    if (!response.success) {
      throw new Error(response.error || '加载最近入库失败')
    }
    serverItems.value = response.items
  } catch (error: any) {
    serverError.value = error.response?.data?.error || error.message || '加载最近入库失败'
  } finally {
    serverLoading.value = false
  }
}

async function handleOpen(item: TelegramDriveItem) {
  if (isTelegramDriveFolder(item)) {
    try {
      const loading = drive.enterMediaGroup(item)
      await router.push('/pc/drive')
      await loading
    } catch {
      ElMessage.error(drive.error || '加载相册失败')
    }
    return
  }

  if (isTelegramDriveFile(item)) {
    recent.addRecent(item, 'preview')
    previewItem.value = item
  }
}

async function queueDownload(item: TelegramDriveItem, saveAs = false) {
  if (!isTelegramDriveFile(item)) return

  try {
    const task = await queueTelegramDownload(item, { saveAs })
    recent.addRecent(item, 'download')
    ElMessage.success(`已加入下载队列：${task.fileName}`)
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || '加入下载队列失败')
  }
}

function handleDownload(item: TelegramDriveItem) {
  return queueDownload(item)
}

function handleSaveAs(item: TelegramDriveItem) {
  return queueDownload(item, true)
}

function getItemTitle(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) return item.file_name || item.media_group_id
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

function getItemMeta(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) {
    return `${item.item_count || 0} 个文件 · ${formatSize(item.total_size || 0)}`
  }
  return `${item.mime_type || '文件'} · ${formatSize(item.file_size || 0)}`
}

async function clearLocalRecent() {
  try {
    await ElMessageBox.confirm('清除当前服务器的全部本机最近记录？', '清除本机记录', {
      confirmButtonText: '清除',
      cancelButtonText: '返回',
      type: 'warning',
    })
    recent.clearCurrentServer()
    previewItem.value = null
    ElMessage.success('本机记录已清除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error('清除本机记录失败')
    }
  }
}
</script>

<style scoped>
.pc-recent-view,
.pc-recent-panel {
  display: grid;
  min-width: 0;
}

.pc-recent-view {
  gap: 16px;
}

.pc-recent-panel {
  gap: 14px;
}

.pc-recent-tabs-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  min-height: 41px;
  border-bottom: 1px solid var(--pc-color-border);
}

.pc-recent-tabs {
  display: flex;
  align-self: stretch;
  min-width: 0;
  flex: 1;
}

.pc-recent-tab {
  position: relative;
  height: 40px;
  padding: 0 20px;
  border: 0;
  background: transparent;
  color: var(--pc-color-text-muted);
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.pc-recent-tab::after {
  position: absolute;
  right: 20px;
  bottom: -1px;
  left: 20px;
  height: 2px;
  background: var(--pc-color-primary);
  content: '';
  opacity: 0;
}

.pc-recent-tab:hover,
.pc-recent-tab.is-active {
  color: var(--pc-color-primary-strong);
}

.pc-recent-tab.is-active::after {
  opacity: 1;
}

.pc-recent-tab:focus-visible {
  outline: 2px solid var(--pc-color-primary);
  outline-offset: -3px;
}

.pc-recent-icon-button {
  width: 32px;
  min-width: 32px;
  height: 32px;
  padding: 0;
}

.pc-recent-skeleton {
  pointer-events: none;
}

.pc-recent-skeleton-cover,
.pc-recent-skeleton-body span {
  background: linear-gradient(90deg, #eceff4 18%, #f8f9fb 46%, #eceff4 72%);
  background-size: 220% 100%;
  animation: pc-recent-skeleton 1.3s ease infinite;
}

.pc-recent-skeleton-body {
  display: grid;
  align-content: center;
  gap: 6px;
}

.pc-recent-skeleton-body span {
  display: block;
  width: 74%;
  height: 8px;
  border-radius: 4px;
}

.pc-recent-skeleton-body span:last-child {
  width: 42%;
  height: 7px;
}

.pc-local-recent-list {
  overflow: hidden;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface);
}

.pc-local-recent-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) 92px 166px;
  gap: 12px;
  align-items: center;
  width: 100%;
  min-height: 58px;
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid var(--pc-color-border);
  background: transparent;
  color: var(--pc-color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease;
}

.pc-local-recent-row:last-child {
  border-bottom: 0;
}

.pc-local-recent-row:hover {
  background: var(--pc-color-surface-soft);
}

.pc-local-recent-row:focus-visible {
  position: relative;
  z-index: 1;
  outline: 2px solid var(--pc-color-primary);
  outline-offset: -2px;
}

.pc-local-recent-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-primary-soft);
  color: var(--pc-color-primary-strong);
}

.pc-local-recent-file {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.pc-local-recent-file strong,
.pc-local-recent-file span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-local-recent-file strong {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
}

.pc-local-recent-file span,
.pc-local-recent-time {
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-local-recent-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  justify-self: start;
  color: var(--pc-color-text-muted);
  font-size: 12px;
  font-weight: 500;
}

.pc-local-recent-action.is-download {
  color: var(--pc-color-success);
}

.pc-local-recent-action.is-preview {
  color: var(--pc-color-primary-strong);
}

.pc-local-recent-time {
  text-align: right;
  white-space: nowrap;
}

@keyframes pc-recent-skeleton {
  from {
    background-position: 160% 0;
  }

  to {
    background-position: -60% 0;
  }
}

@media (max-width: 760px) {
  .pc-local-recent-row {
    grid-template-columns: 36px minmax(0, 1fr) 88px;
  }

  .pc-local-recent-time {
    display: none;
  }
}
</style>
