<template>
  <section ref="viewRoot" class="pc-drive-view" data-testid="pc-drive-view">
    <div class="pc-drive-pathbar">
      <el-tooltip v-if="drive.isInsideMediaGroup" content="返回网盘" placement="bottom">
        <el-button
          class="pc-drive-icon-button"
          :icon="ArrowLeft"
          aria-label="返回网盘"
          @click="leaveMediaGroup"
        />
      </el-tooltip>

      <div class="pc-drive-path">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>
            <button
              v-if="drive.isInsideMediaGroup"
              class="pc-drive-crumb"
              type="button"
              @click="leaveMediaGroup"
            >
              网盘
            </button>
            <span v-else class="pc-drive-crumb-current">网盘</span>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-if="drive.isInsideMediaGroup">
            <span class="pc-drive-crumb-current" :title="drive.currentFolderName">
              {{ drive.currentFolderName }}
            </span>
          </el-breadcrumb-item>
        </el-breadcrumb>
      </div>

      <el-button
        v-if="hasFilters"
        class="pc-drive-clear-filters"
        text
        :icon="CircleClose"
        @click="resetFilters"
      >
        清除筛选
      </el-button>
      <span class="pc-drive-result-count">{{ drive.total }} 项</span>
      <el-segmented
        v-model="driveViewMode"
        class="pc-drive-view-mode"
        :options="viewModeOptions"
        aria-label="文件视图"
      />
      <el-tooltip content="刷新" placement="bottom">
        <el-button
          class="pc-drive-icon-button"
          :icon="RefreshRight"
          :loading="drive.loading"
          aria-label="刷新"
          @click="refresh"
        />
      </el-tooltip>
    </div>

    <div class="pc-drive-querybar">
      <el-input
        v-model="searchDraft"
        class="pc-drive-search"
        placeholder="搜索文件名或描述"
        clearable
        :prefix-icon="Search"
        @keyup.enter="applySearch"
        @clear="applySearch"
      />
      <el-select
        :model-value="drive.typeFilter"
        class="pc-drive-select"
        aria-label="文件类型"
        @change="handleTypeChange"
      >
        <el-option label="全部类型" value="" />
        <el-option label="视频" value="video" />
        <el-option label="图片" value="image" />
        <el-option label="音频" value="audio" />
        <el-option label="文档" value="document" />
      </el-select>
      <el-select
        :model-value="sortValue"
        class="pc-drive-sort"
        aria-label="排序方式"
        @change="handleSortChange"
      >
        <el-option label="时间 新到旧" value="message_date-desc" />
        <el-option label="时间 旧到新" value="message_date-asc" />
        <el-option label="大小 大到小" value="file_size-desc" />
        <el-option label="大小 小到大" value="file_size-asc" />
        <el-option label="名称 A 到 Z" value="file_name-asc" />
        <el-option label="名称 Z 到 A" value="file_name-desc" />
      </el-select>
      <el-tooltip content="搜索" placement="bottom">
        <el-button
          class="pc-drive-search-button"
          type="primary"
          :icon="Search"
          aria-label="搜索"
          @click="applySearch"
        />
      </el-tooltip>
    </div>

    <div v-if="drive.loading" class="pc-media-grid" aria-label="正在加载文件">
      <div
        v-for="index in 18"
        :key="index"
        class="pc-card pc-media-card pc-drive-skeleton"
        aria-hidden="true"
      >
        <span class="pc-media-cover pc-drive-skeleton-cover"></span>
        <span class="pc-media-body pc-drive-skeleton-body">
          <span></span>
          <span></span>
        </span>
      </div>
    </div>

    <PcStatePanel
      v-else-if="drive.error"
      asset="connection-error"
      :title="drive.error"
      action-label="重试"
      :action-icon="RefreshRight"
      @action="refresh"
    />

    <DriveGrid
      v-else-if="drive.items.length && preferences.driveViewMode === 'grid'"
      :items="drive.items"
      @open="handleOpen"
      @delete="confirmDelete"
    />

    <DriveList
      v-else-if="drive.items.length"
      :items="drive.items"
      @open="handleOpen"
      @delete="confirmDelete"
    />

    <PcStatePanel
      v-else
      asset="empty-drive"
      :title="emptyTitle"
      :action-label="hasFilters ? '清除筛选' : undefined"
      :action-icon="hasFilters ? CircleClose : undefined"
      @action="resetFilters"
    />

    <div v-if="drive.total > drive.pageSize" class="pc-drive-pagination">
      <el-pagination
        :current-page="drive.page"
        :page-size="drive.pageSize"
        :page-sizes="[20, 40, 80, 120]"
        :total="drive.total"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />
    </div>

    <MediaPreview
      v-model="previewItem"
      :items="drive.items"
      @download="handlePreviewDownload"
      @save-as="handlePreviewSaveAs"
      @delete="confirmDelete"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CircleClose, RefreshRight, Search } from '@element-plus/icons-vue'
import DriveGrid from '@/components/pc/drive-grid.vue'
import DriveList from '@/components/pc/drive-list.vue'
import MediaPreview from '@/components/pc/media-preview.vue'
import PcStatePanel from '@/components/pc/pc-state-panel.vue'
import {
  deleteTelegramGroup,
  deleteTelegramItem,
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveItem,
} from '@/api'
import { usePcDriveStore } from '@/stores/pcDrive'
import { usePcPreferencesStore, type DriveViewMode } from '@/stores/pcPreferences'
import { usePcRecentStore } from '@/stores/pcRecent'
import { queueTelegramDownload } from '@/utils/pcDownload'

const drive = usePcDriveStore()
const preferences = usePcPreferencesStore()
const recent = usePcRecentStore()
const viewRoot = ref<HTMLElement | null>(null)
const searchDraft = ref(drive.search)
const previewItem = ref<TelegramDriveItem | null>(null)

const viewModeOptions = [
  { label: '网格', value: 'grid' },
  { label: '列表', value: 'list' },
]

const driveViewMode = computed({
  get: () => preferences.driveViewMode,
  set: (value: DriveViewMode) => preferences.setDriveViewMode(value),
})
const sortValue = computed(() => `${drive.sortBy}-${drive.sortDesc ? 'desc' : 'asc'}`)
const hasFilters = computed(() => Boolean(drive.search || drive.typeFilter))
const emptyTitle = computed(() => {
  if (hasFilters.value) return '没有匹配的文件'
  if (drive.isInsideMediaGroup) return '此相册暂无文件'
  return '网盘暂无文件'
})

onMounted(() => {
  if (!drive.items.length) void refresh()
})

function scrollContentTop() {
  const content = viewRoot.value?.closest('.pc-content')
  content?.scrollTo({ top: 0, behavior: 'smooth' })
}

async function refresh() {
  try {
    await drive.refresh()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function applySearch() {
  try {
    await drive.setSearch(searchDraft.value)
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function handleTypeChange(value: string | number | boolean) {
  try {
    await drive.setTypeFilter(String(value))
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function handleSortChange(value: string | number | boolean) {
  const [sortBy, order] = String(value).split('-')
  try {
    await drive.setSort(sortBy || 'message_date', order !== 'asc')
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function resetFilters() {
  searchDraft.value = ''
  try {
    await drive.resetFilters()
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function handlePageChange(page: number) {
  try {
    await drive.setPage(page)
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function handlePageSizeChange(pageSize: number) {
  try {
    await drive.setPageSize(pageSize)
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function leaveMediaGroup() {
  try {
    await drive.leaveMediaGroup()
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
  }
}

async function handleOpen(item: TelegramDriveItem) {
  if (isTelegramDriveFile(item)) {
    recent.addRecent(item, 'preview')
    previewItem.value = item
    return
  }
  if (!isTelegramDriveFolder(item)) return

  try {
    await drive.enterMediaGroup(item)
    scrollContentTop()
  } catch {
    // The persistent error state provides the retry path.
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

function handlePreviewDownload(item: TelegramDriveItem) {
  return queueDownload(item)
}

function handlePreviewSaveAs(item: TelegramDriveItem) {
  return queueDownload(item, true)
}

function getItemKey(item: TelegramDriveItem): string {
  return isTelegramDriveFolder(item) ? `folder-${item.media_group_id}` : item.file_unique_id
}

function getItemTitle(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) return item.file_name || item.media_group_id
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

async function confirmDelete(item: TelegramDriveItem) {
  const isFolder = isTelegramDriveFolder(item)
  const targetName = `${isFolder ? '相册' : '文件'}「${getItemTitle(item)}」`

  try {
    await ElMessageBox.confirm(`确定删除 ${targetName} 吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })

    const response = isFolder
      ? await deleteTelegramGroup(item.media_group_id)
      : await deleteTelegramItem(item.message_id)
    if (!response.success) throw new Error(response.error || '删除失败')

    if (previewItem.value && getItemKey(previewItem.value) === getItemKey(item)) {
      previewItem.value = null
    }
    ElMessage.success(response.message || '删除成功')
    await refresh()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<style scoped>
.pc-drive-view {
  display: grid;
  gap: 12px;
}

.pc-drive-pathbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
}

.pc-drive-path {
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

.pc-drive-crumb {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--pc-color-primary-strong);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.pc-drive-crumb-current {
  display: inline-block;
  max-width: min(40vw, 480px);
  overflow: hidden;
  color: var(--pc-color-text);
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
}

.pc-drive-result-count {
  min-width: max-content;
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-drive-clear-filters {
  flex: 0 0 auto;
}

.pc-drive-view-mode {
  flex: 0 0 auto;
}

.pc-drive-querybar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 116px 158px 34px;
  gap: 8px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface);
}

.pc-drive-search,
.pc-drive-select,
.pc-drive-sort {
  min-width: 0;
}

.pc-drive-icon-button,
.pc-drive-search-button {
  width: 34px;
  min-width: 34px;
  padding: 0;
}

.pc-drive-skeleton {
  pointer-events: none;
}

.pc-drive-skeleton-cover,
.pc-drive-skeleton-body span {
  background: linear-gradient(90deg, #eceff4 18%, #f8f9fb 46%, #eceff4 72%);
  background-size: 220% 100%;
  animation: pc-drive-skeleton 1.3s ease infinite;
}

.pc-drive-skeleton-body {
  display: grid;
  align-content: center;
  gap: 6px;
}

.pc-drive-skeleton-body span {
  display: block;
  width: 74%;
  height: 8px;
  border-radius: 4px;
}

.pc-drive-skeleton-body span:last-child {
  width: 42%;
  height: 7px;
}

.pc-drive-pagination {
  display: flex;
  justify-content: flex-end;
  min-height: 44px;
  padding-top: 10px;
  border-top: 1px solid var(--pc-color-border);
}

@keyframes pc-drive-skeleton {
  from {
    background-position: 160% 0;
  }

  to {
    background-position: -60% 0;
  }
}

@media (max-width: 860px) {
  .pc-drive-querybar {
    grid-template-columns: 1fr 1fr 34px;
  }

  .pc-drive-search {
    grid-column: 1 / -1;
  }

  .pc-drive-pathbar {
    flex-wrap: wrap;
  }

  .pc-drive-path {
    flex-basis: 50%;
  }
}
</style>
