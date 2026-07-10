<template>
  <section class="pc-drive-view">
    <div class="pc-drive-actions">
      <el-button
        v-if="drive.isInsideMediaGroup"
        :icon="ArrowLeft"
        @click="leaveMediaGroup"
      >
        返回
      </el-button>
      <div class="pc-drive-path">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>
            <button class="pc-drive-crumb" type="button" @click="leaveMediaGroup">网盘</button>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-if="drive.isInsideMediaGroup">
            <span class="pc-drive-crumb-current">{{ drive.currentFolderName }}</span>
          </el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <el-segmented
        v-model="driveViewMode"
        class="pc-drive-view-mode"
        :options="viewModeOptions"
      />
      <el-button :icon="RefreshRight" :loading="drive.loading" @click="refresh">
        刷新
      </el-button>
    </div>

    <div class="pc-drive-toolbar">
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
        placeholder="类型"
        @change="handleTypeChange"
      >
        <el-option label="全部" value="" />
        <el-option label="视频" value="video" />
        <el-option label="图片" value="image" />
        <el-option label="音频" value="audio" />
        <el-option label="文档" value="document" />
      </el-select>
      <el-select
        :model-value="sortValue"
        class="pc-drive-sort"
        @change="handleSortChange"
      >
        <el-option label="时间 新到旧" value="message_date-desc" />
        <el-option label="时间 旧到新" value="message_date-asc" />
        <el-option label="大小 大到小" value="file_size-desc" />
        <el-option label="大小 小到大" value="file_size-asc" />
        <el-option label="名称 A到Z" value="file_name-asc" />
        <el-option label="名称 Z到A" value="file_name-desc" />
      </el-select>
      <el-button :icon="Search" @click="applySearch">搜索</el-button>
    </div>

    <el-alert
      v-if="drive.error"
      class="pc-drive-alert"
      :title="drive.error"
      type="error"
      :closable="false"
      show-icon
    />

    <div v-if="drive.loading" class="pc-media-grid">
      <div v-for="index in 12" :key="index" class="pc-card pc-drive-skeleton" />
    </div>

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

    <div v-else class="pc-empty-state">
      <div class="pc-anime-asset pc-anime-empty-drive pc-drive-empty-art" aria-hidden="true"></div>
      <div class="pc-drive-empty-title">
        {{ drive.isInsideMediaGroup ? '此相册暂无文件' : '暂无文件' }}
      </div>
    </div>

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
import { ArrowLeft, RefreshRight, Search } from '@element-plus/icons-vue'
import DriveGrid from '@/components/pc/drive-grid.vue'
import DriveList from '@/components/pc/drive-list.vue'
import MediaPreview from '@/components/pc/media-preview.vue'
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

onMounted(() => {
  if (!drive.items.length) {
    refresh()
  }
})

async function refresh() {
  try {
    await drive.refresh()
  } catch {
    ElMessage.error(drive.error || '加载网盘失败')
  }
}

async function applySearch() {
  try {
    await drive.setSearch(searchDraft.value)
  } catch {
    ElMessage.error(drive.error || '搜索失败')
  }
}

async function handleTypeChange(value: string | number | boolean) {
  try {
    await drive.setTypeFilter(String(value))
  } catch {
    ElMessage.error(drive.error || '筛选失败')
  }
}

async function handleSortChange(value: string | number | boolean) {
  const [sortBy, order] = String(value).split('-')
  try {
    await drive.setSort(sortBy || 'message_date', order !== 'asc')
  } catch {
    ElMessage.error(drive.error || '排序失败')
  }
}

async function handlePageChange(page: number) {
  try {
    await drive.setPage(page)
  } catch {
    ElMessage.error(drive.error || '加载分页失败')
  }
}

async function handlePageSizeChange(pageSize: number) {
  try {
    await drive.setPageSize(pageSize)
  } catch {
    ElMessage.error(drive.error || '加载分页失败')
  }
}

async function leaveMediaGroup() {
  try {
    await drive.leaveMediaGroup()
  } catch {
    ElMessage.error(drive.error || '加载网盘失败')
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
  } catch {
    ElMessage.error(drive.error || '加载相册失败')
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
  if (isTelegramDriveFolder(item)) {
    return item.file_name || item.media_group_id
  }
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

async function confirmDelete(item: TelegramDriveItem) {
  const isFolder = isTelegramDriveFolder(item)
  const targetName = `${isFolder ? '相册' : '文件'}「${getItemTitle(item)}」`

  try {
    await ElMessageBox.confirm(
      `确定删除 ${targetName} 吗？`,
      '删除确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )

    const response = isFolder
      ? await deleteTelegramGroup(item.media_group_id)
      : await deleteTelegramItem(item.message_id)

    if (!response.success) {
      throw new Error(response.error || '删除失败')
    }

    if (previewItem.value && getItemKey(previewItem.value) === getItemKey(item)) {
      previewItem.value = null
    }
    ElMessage.success(response.message || '删除成功')
    await drive.refresh()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<style scoped>
.pc-drive-view {
  display: grid;
  gap: 16px;
}

.pc-drive-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
}

.pc-drive-path {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--pc-color-text);
  font-size: 16px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-drive-crumb {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--pc-color-primary-strong);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.pc-drive-crumb-current {
  color: var(--pc-color-text);
  font-weight: 700;
}

.pc-drive-view-mode {
  flex: 0 0 auto;
}

.pc-drive-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 128px 160px auto;
  gap: 10px;
  align-items: center;
}

.pc-drive-search,
.pc-drive-select,
.pc-drive-sort {
  min-width: 0;
}

.pc-drive-alert {
  max-width: 720px;
}

.pc-drive-skeleton {
  aspect-ratio: 4 / 3;
  background:
    linear-gradient(90deg, rgba(238, 247, 244, 0.72), rgba(255, 255, 255, 0.92), rgba(238, 247, 244, 0.72));
  background-size: 220% 100%;
  animation: pc-skeleton 1.4s ease infinite;
}

.pc-drive-empty-art {
  width: min(320px, 72vw);
}

.pc-drive-empty-title {
  color: var(--pc-color-text-muted);
  font-size: 14px;
}

.pc-drive-pagination {
  display: flex;
  justify-content: flex-end;
}

@keyframes pc-skeleton {
  from {
    background-position: 160% 0;
  }

  to {
    background-position: -60% 0;
  }
}

@media (max-width: 820px) {
  .pc-drive-toolbar {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
