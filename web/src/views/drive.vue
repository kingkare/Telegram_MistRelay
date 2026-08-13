<template>
  <div class="drive-page">
    <el-card shadow="hover">
      <template #header>
        <div class="drive-header">
          <div>
            <h2>Telegram 频道网盘</h2>
            <p class="drive-header-subtitle">第三方网盘已废弃，这里只管理 TG 频道中的媒体文件。</p>
          </div>
          <div class="drive-header-actions">
            <el-button :icon="RefreshRight" @click="refreshAll" :loading="loading">刷新</el-button>
            <el-button type="danger" :icon="Delete" @click="handleClearAll" :disabled="items.length === 0">
              清空 TG 网盘
            </el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="16" class="stats-row">
        <el-col :xs="12" :sm="6">
          <el-statistic title="文件总数" :value="usageStats?.total_count || 0" />
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-statistic title="占用空间" :value="formatBytes(usageStats?.total_size || 0)" />
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-statistic title="视频" :value="usageStats?.videos || 0" />
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-statistic title="图片" :value="usageStats?.images || 0" />
        </el-col>
      </el-row>

      <div class="toolbar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索文件名或描述"
          clearable
          class="search-input"
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select v-model="typeFilter" placeholder="类型" class="type-select" @change="handleSearch">
          <el-option label="全部" value="" />
          <el-option label="视频" value="video" />
          <el-option label="图片" value="image" />
          <el-option label="音频" value="audio" />
          <el-option label="文档" value="document" />
        </el-select>
        <el-select v-model="sortOption" class="sort-select" @change="handleSearch">
          <el-option label="时间 新→旧" value="message_date-desc" />
          <el-option label="时间 旧→新" value="message_date-asc" />
          <el-option label="大小 大→小" value="file_size-desc" />
          <el-option label="大小 小→大" value="file_size-asc" />
          <el-option label="名称 A→Z" value="file_name-asc" />
          <el-option label="名称 Z→A" value="file_name-desc" />
        </el-select>
        <el-radio-group v-model="viewMode">
          <el-radio-button label="list"><el-icon><List /></el-icon></el-radio-button>
          <el-radio-button label="grid"><el-icon><Grid /></el-icon></el-radio-button>
        </el-radio-group>
      </div>

      <div class="breadcrumb-bar">
        <el-button v-if="isInsideGroup" :icon="ArrowLeft" text @click="goRoot">返回根目录</el-button>
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>
            <span class="breadcrumb-link" @click="goRoot">TG网盘</span>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-if="isInsideGroup">{{ currentFolderName }}</el-breadcrumb-item>
        </el-breadcrumb>
      </div>

      <div v-if="items.length" class="selection-toolbar">
        <el-checkbox
          :model-value="allPageSelected"
          :indeterminate="somePageSelected"
          :disabled="loading || batchDeleting"
          @change="toggleSelectPage(Boolean($event))"
        >
          全选本页
        </el-checkbox>
        <span class="selection-count">已选 {{ selectedItems.length }} 项</span>
        <div class="selection-actions">
          <el-button
            :icon="Download"
            :disabled="selectedFiles.length === 0 || loading || batchDeleting"
            @click="handleBatchDownload"
          >
            下载文件<span v-if="selectedFiles.length">（{{ selectedFiles.length }}）</span>
          </el-button>
          <el-button
            type="danger"
            :icon="Delete"
            :disabled="selectedItems.length === 0 || loading"
            :loading="batchDeleting"
            @click="handleBatchDelete"
          >
            批量删除<span v-if="selectedItems.length">（{{ selectedItems.length }}）</span>
          </el-button>
          <el-button
            v-if="selectedItems.length"
            text
            :disabled="batchDeleting"
            @click="clearSelection"
          >
            取消选择
          </el-button>
        </div>
      </div>

      <el-table
        v-if="viewMode === 'list'"
        :data="items"
        v-loading="loading"
        style="width: 100%; margin-top: 20px"
        @row-click="handleOpen"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column width="48" align="center">
          <template #header>
            <el-checkbox
              :model-value="allPageSelected"
              :indeterminate="somePageSelected"
              :disabled="loading || batchDeleting"
              aria-label="全选本页"
              @click.stop
              @change="toggleSelectPage(Boolean($event))"
            />
          </template>
          <template #default="{ row }">
            <el-checkbox
              :model-value="isSelected(row)"
              :disabled="batchDeleting"
              :aria-label="`选择 ${getFileName(row)}`"
              @click.stop
              @change="toggleItemSelection(row, Boolean($event))"
            />
          </template>
        </el-table-column>
        <el-table-column label="名称" min-width="260">
          <template #default="{ row }">
            <div class="file-name">
              <el-icon :size="18">
                <Folder v-if="isFolder(row)" />
                <Picture v-else-if="isImage(row)" />
                <VideoPlay v-else-if="isVideo(row)" />
                <Headset v-else-if="isAudio(row)" />
                <Document v-else />
              </el-icon>
              <span>{{ getFileName(row) }}</span>
              <el-tag v-if="isFolder(row)" size="small" type="warning">{{ row.item_count || 0 }} 个文件</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ getTypeLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="大小" width="130">
          <template #default="{ row }">{{ formatBytes(getDisplaySize(row)) }}</template>
        </el-table-column>
        <el-table-column label="内容" width="120">
          <template #default="{ row }">
            <span v-if="isFolder(row)">{{ row.item_count || 0 }} 个文件</span>
            <span v-else>#{{ row.message_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatDate(row.message_date) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" align="center">
          <template #default="{ row }">
            <el-button-group>
              <el-button v-if="isFolder(row)" type="primary" link :icon="Folder" @click.stop="enterFolder(row)">
                打开
              </el-button>
              <el-button v-else type="primary" link :icon="View" @click.stop="handlePreview(row)">
                预览
              </el-button>
              <el-button v-if="isFile(row)" type="success" link :icon="Download" @click.stop="handleDownload(row)">
                下载
              </el-button>
              <el-button type="danger" link :icon="Delete" @click.stop="handleDelete(row)" />
            </el-button-group>
          </template>
        </el-table-column>
      </el-table>

      <div v-else v-loading="loading" class="grid-view">
        <div
          v-for="item in items"
          :key="getItemKey(item)"
          class="grid-item"
          :class="{ 'is-selected': isSelected(item) }"
          @click="handleOpen(item)"
        >
          <el-checkbox
            class="grid-item-checkbox"
            :model-value="isSelected(item)"
            :disabled="batchDeleting"
            :aria-label="`选择 ${getFileName(item)}`"
            @click.stop
            @change="toggleItemSelection(item, Boolean($event))"
          />
          <div class="grid-item-preview">
            <el-image v-if="!isFolder(item) && isImage(item)" :src="getStreamUrl(item)" fit="cover" class="grid-thumbnail" lazy>
              <template #error><el-icon :size="44"><Picture /></el-icon></template>
            </el-image>
            <div v-else class="grid-placeholder">
              <el-icon :size="48">
                <Folder v-if="isFolder(item)" />
                <VideoPlay v-else-if="isVideo(item)" />
                <Headset v-else-if="isAudio(item)" />
                <Document v-else />
              </el-icon>
            </div>
            <el-tag class="type-badge" size="small">{{ getTypeLabel(item) }}</el-tag>
          </div>
          <div class="grid-item-name" :title="getFileName(item)">{{ getFileName(item) }}</div>
          <div class="grid-item-meta">
            <span v-if="isFolder(item)">{{ item.item_count || 0 }} 个文件 · {{ formatBytes(getDisplaySize(item)) }}</span>
            <span v-else>{{ formatBytes(getDisplaySize(item)) }} · #{{ item.message_id }}</span>
          </div>
          <div class="grid-item-actions">
            <el-button v-if="isFolder(item)" circle size="small" type="primary" :icon="Folder" @click.stop="enterFolder(item)" title="打开" />
            <el-button v-else circle size="small" type="primary" :icon="View" @click.stop="handlePreview(item)" title="预览" />
            <el-button v-if="isFile(item)" circle size="small" type="success" :icon="Download" @click.stop="handleDownload(item)" title="下载" />
            <el-button circle size="small" type="danger" :icon="Delete" @click.stop="handleDelete(item)" />
          </div>
        </div>
      </div>

      <el-empty v-if="!loading && items.length === 0" :description="isInsideGroup ? '此媒体组暂无文件' : 'TG 频道网盘暂无文件'" />

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="loadItems"
          @size-change="handlePageSizeChange"
        />
      </div>
    </el-card>

    <el-image-viewer
      v-if="showPreview && previewType === 'image'"
      :url-list="[previewUrl]"
      @close="closePreview"
      hide-on-click-modal
    />

    <el-dialog
      v-model="showPreview"
      v-if="previewType === 'video'"
      :title="getFileName(previewItem)"
      width="80%"
      destroy-on-close
      @close="closePreview"
      center
      class="video-dialog"
    >
      <div class="video-container">
        <VideoPlayer v-if="previewUrl" :src="previewUrl" :type="getVideoType(previewItem)" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Delete, Document, Download, Folder, Grid, Headset, List, Picture, RefreshRight, Search, VideoPlay, View } from '@element-plus/icons-vue'
import {
  browseTelegramDrive,
  clearTelegramDrive,
  deleteTelegramBatch,
  deleteTelegramGroup,
  deleteTelegramItem,
  getTelegramUsage,
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveFile,
  type TelegramDriveFolder,
  type TelegramDriveItem,
  type TelegramUsageStats,
} from '@/api'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { resolveServerUrl } from '@/utils/runtime'

const items = ref<TelegramDriveItem[]>([])
const usageStats = ref<TelegramUsageStats | null>(null)
const loading = ref(false)
const searchKeyword = ref('')
const typeFilter = ref('')
const sortOption = ref('message_date-desc')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const viewMode = ref<'list' | 'grid'>('list')
const showPreview = ref(false)
const previewItem = ref<TelegramDriveItem | null>(null)
const previewType = ref<'image' | 'video' | 'unknown'>('unknown')
const previewUrl = ref('')
const currentMediaGroupId = ref('')
const currentFolderName = ref('')
const selectedKeys = ref(new Set<string>())
const batchDeleting = ref(false)

const isInsideGroup = computed(() => Boolean(currentMediaGroupId.value))
const selectedItems = computed(() => items.value.filter(item => selectedKeys.value.has(getItemKey(item))))
const selectedFiles = computed(() => selectedItems.value.filter(isFile))
const allPageSelected = computed(() => (
  items.value.length > 0 && items.value.every(item => selectedKeys.value.has(getItemKey(item)))
))
const somePageSelected = computed(() => (
  selectedItems.value.length > 0 && !allPageSelected.value
))

const sortParams = computed(() => {
  const [sortBy, order] = sortOption.value.split('-')
  return {
    sort_by: sortBy || 'message_date',
    sort_desc: order !== 'asc',
  }
})

function getFileName(item?: TelegramDriveItem | null): string {
  if (!item) return ''
  return item.file_name || `telegram_${item.message_id}`
}

function getDownloadFileName(item?: TelegramDriveItem | null): string {
  if (!item) return ''
  if (isFile(item) && item.download_file_name) return item.download_file_name

  if (item.stream_url) {
    try {
      const pathname = new URL(item.stream_url, window.location.origin).pathname
      const encodedName = pathname.split('/').filter(Boolean).pop()
      if (encodedName) {
        return decodeURIComponent(encodedName)
      }
    } catch {
      const encodedName = item.stream_url.split('?')[0]?.split('/').filter(Boolean).pop()
      if (encodedName) {
        try {
          return decodeURIComponent(encodedName)
        } catch {
          return encodedName
        }
      }
    }
  }

  return getFileName(item)
}

function getItemKey(item: TelegramDriveItem): string {
  return isFolder(item) ? `folder-${item.media_group_id}` : item.file_unique_id
}

function isSelected(item: TelegramDriveItem): boolean {
  return selectedKeys.value.has(getItemKey(item))
}

function clearSelection() {
  selectedKeys.value = new Set()
}

function toggleItemSelection(item: TelegramDriveItem, selected: boolean) {
  const next = new Set(selectedKeys.value)
  const key = getItemKey(item)
  if (selected) next.add(key)
  else next.delete(key)
  selectedKeys.value = next
}

function toggleSelectPage(selected: boolean) {
  selectedKeys.value = selected
    ? new Set(items.value.map(getItemKey))
    : new Set()
}

function getStreamUrl(item: TelegramDriveItem): string {
  return isFile(item) && item.stream_url ? resolveServerUrl(item.stream_url) : ''
}

function getDownloadUrl(item: TelegramDriveItem): string {
  const url = getStreamUrl(item)
  if (!url) return ''
  const downloadUrl = new URL(url, window.location.origin)
  downloadUrl.searchParams.set('download', '1')
  return downloadUrl.toString()
}

function isFolder(item?: TelegramDriveItem | null): item is TelegramDriveFolder {
  return isTelegramDriveFolder(item)
}

function isFile(item?: TelegramDriveItem | null): item is TelegramDriveFile {
  return isTelegramDriveFile(item)
}

function getDisplaySize(item: TelegramDriveItem): number {
  return isFolder(item) ? item.total_size ?? 0 : item.file_size ?? 0
}

function isImage(item?: TelegramDriveItem | null): boolean {
  return Boolean(item?.mime_type?.startsWith('image/'))
}

function isVideo(item?: TelegramDriveItem | null): boolean {
  return Boolean(item?.mime_type?.startsWith('video/'))
}

function isAudio(item?: TelegramDriveItem | null): boolean {
  return Boolean(item?.mime_type?.startsWith('audio/'))
}

function getTypeLabel(item: TelegramDriveItem): string {
  if (isFolder(item)) return '媒体组文件夹'
  if (isVideo(item)) return '视频'
  if (isImage(item)) return '图片'
  if (isAudio(item)) return '音频'
  return '文档'
}

function getVideoType(item?: TelegramDriveItem | null): string {
  return item?.mime_type || ''
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function formatDate(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN')
}

async function loadUsage() {
  try {
    const response = await getTelegramUsage()
    if (response.success && response.data) {
      usageStats.value = response.data
    }
  } catch (error) {
    console.error('加载 TG 网盘统计失败:', error)
  }
}

async function loadItems() {
  clearSelection()
  loading.value = true
  try {
    const response = await browseTelegramDrive({
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchKeyword.value || undefined,
      type: typeFilter.value || undefined,
      media_group_id: currentMediaGroupId.value || undefined,
      ...sortParams.value,
    })

    if (response.success) {
      items.value = response.items || []
      total.value = response.total || 0
    } else {
      items.value = []
      total.value = 0
      ElMessage.error(response.error || '加载 TG 网盘失败')
    }
  } catch (error: any) {
    console.error('加载 TG 网盘失败:', error)
    items.value = []
    total.value = 0
    ElMessage.error(error.message || '加载 TG 网盘失败')
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadUsage(), loadItems()])
}

function handleSearch() {
  currentPage.value = 1
  loadItems()
}

function enterFolder(item: TelegramDriveItem) {
  if (!item.media_group_id) return
  currentMediaGroupId.value = item.media_group_id
  currentFolderName.value = getFileName(item)
  currentPage.value = 1
  loadItems()
}

function goRoot() {
  if (!isInsideGroup.value) return
  currentMediaGroupId.value = ''
  currentFolderName.value = ''
  currentPage.value = 1
  loadItems()
}

function handlePageSizeChange() {
  currentPage.value = 1
  loadItems()
}

function handleDownload(item: TelegramDriveItem) {
  if (isFolder(item)) {
    ElMessage.info('请进入媒体组后下载组内文件')
    return
  }

  const url = getDownloadUrl(item)
  if (!url) {
    ElMessage.warning('此文件暂无可用直链')
    return
  }

  const link = document.createElement('a')
  link.href = url
  link.download = getDownloadFileName(item)
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function handleBatchDownload() {
  const files = selectedFiles.value
  if (!files.length) return

  let started = 0
  for (const item of files) {
    const url = getDownloadUrl(item)
    if (!url) continue

    const link = document.createElement('a')
    link.href = url
    link.download = getDownloadFileName(item)
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    document.body.appendChild(link)
    link.click()
    link.remove()
    started += 1
  }

  const skippedFolders = selectedItems.value.length - files.length
  if (started) {
    ElMessage.success(`已开始下载 ${started} 个文件`)
  }
  if (skippedFolders) {
    ElMessage.info(`已跳过 ${skippedFolders} 个媒体组文件夹`)
  }
}

function handleOpen(item: TelegramDriveItem) {
  if (isFolder(item)) {
    enterFolder(item)
    return
  }
  handlePreview(item)
}

function handlePreview(item: TelegramDriveItem) {
  const url = getStreamUrl(item)
  if (!url) {
    ElMessage.warning('此文件暂无可用直链')
    return
  }

  if (isImage(item)) {
    previewType.value = 'image'
  } else if (isVideo(item)) {
    previewType.value = 'video'
  } else {
    handleDownload(item)
    return
  }

  previewItem.value = item
  previewUrl.value = url
  showPreview.value = true
}

function closePreview() {
  showPreview.value = false
  previewItem.value = null
  previewType.value = 'unknown'
  previewUrl.value = ''
}

async function handleDelete(item: TelegramDriveItem) {
  const shouldDeleteGroup = isFolder(item) || (!isInsideGroup.value && Boolean(item.media_group_id))
  const targetName = shouldDeleteGroup ? `媒体组文件夹「${getFileName(item)}」` : `文件「${getFileName(item)}」`

  try {
    await ElMessageBox.confirm(`确定要删除 ${targetName} 吗？会同步删除频道消息和数据库记录。`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })

    loading.value = true
    const response = shouldDeleteGroup && item.media_group_id
      ? await deleteTelegramGroup(item.media_group_id)
      : isFile(item)
        ? await deleteTelegramItem(item.message_id)
        : { success: false, error: '无法定位要删除的文件' }

    if (response.success) {
      ElMessage.success(response.message || '删除成功')
      if (shouldDeleteGroup && isInsideGroup.value) {
        currentMediaGroupId.value = ''
        currentFolderName.value = ''
      }
      await refreshAll()
    } else {
      ElMessage.error(response.error || '删除失败')
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('删除 TG 网盘文件失败:', error)
      ElMessage.error(error.message || '删除失败')
    }
  } finally {
    loading.value = false
  }
}

async function handleBatchDelete() {
  const selection = selectedItems.value
  if (!selection.length) return

  const messageIds = selection.filter(isFile).map(item => item.message_id)
  const mediaGroupIds = selection.filter(isFolder).map(item => item.media_group_id)

  try {
    await ElMessageBox.confirm(
      `确定删除已选 ${selection.length} 项吗？媒体组文件夹会连同组内频道消息一起删除。`,
      '批量删除',
      {
        confirmButtonText: '删除所选',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )

    batchDeleting.value = true
    const response = await deleteTelegramBatch({
      message_ids: messageIds,
      media_group_ids: mediaGroupIds,
    })
    if (!response.success) throw new Error(response.error || '批量删除失败')

    clearSelection()
    ElMessage.success(response.message || `已删除 ${selection.length} 项`)
    await refreshAll()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    console.error('批量删除 TG 网盘文件失败:', error)
    ElMessage.error(error.response?.data?.error || error.message || '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

async function handleClearAll() {
  try {
    await ElMessageBox.confirm('确定要清空整个 TG 频道网盘吗？此操作会删除所有频道消息和本地记录。', '清空 TG 网盘', {
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      type: 'warning',
    })

    loading.value = true
    const response = await clearTelegramDrive()
    if (response.success) {
      ElMessage.success(response.message || 'TG 网盘已清空')
      await refreshAll()
    } else {
      ElMessage.error(response.error || '清空失败')
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('清空 TG 网盘失败:', error)
      ElMessage.error(error.message || '清空失败')
    }
  } finally {
    loading.value = false
  }
}

watch(sortOption, handleSearch)

onMounted(refreshAll)
</script>

<style scoped>
.drive-page {
  padding: 20px;
}

.drive-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.drive-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.drive-header-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
}

.drive-header-actions,
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stats-row {
  margin-bottom: 20px;
}

.toolbar {
  padding: 16px;
  background: #f8fafc;
  border-radius: 12px;
}

.search-input {
  width: 280px;
}

.type-select,
.sort-select {
  width: 150px;
}


.breadcrumb-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 10px 4px 0;
}

.breadcrumb-link {
  color: #409eff;
  cursor: pointer;
}

.breadcrumb-link:hover {
  text-decoration: underline;
}

.selection-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  margin-top: 12px;
  padding: 6px 10px;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #f8fafc;
}

.selection-count {
  color: #64748b;
  font-size: 13px;
  white-space: nowrap;
}

.selection-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.file-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.grid-view {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  margin-top: 20px;
  min-height: 160px;
}

.grid-item {
  position: relative;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.grid-item:hover {
  border-color: #409eff;
  box-shadow: 0 8px 18px rgba(64, 158, 255, 0.14);
  transform: translateY(-2px);
}

.grid-item.is-selected {
  border-color: #409eff;
  background: #f0f7ff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.14);
}

.grid-item-checkbox {
  position: absolute;
  z-index: 2;
  top: 10px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
}

.grid-item-preview {
  position: relative;
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  border-radius: 10px;
  overflow: hidden;
}

.grid-thumbnail {
  width: 100%;
  height: 100%;
}

.grid-placeholder {
  color: #64748b;
}

.type-badge {
  position: absolute;
  right: 8px;
  top: 8px;
}

.grid-item-name {
  margin-top: 10px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grid-item-meta {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.grid-item-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 10px;
}

.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

.video-container {
  width: 100%;
  min-height: 500px;
  background: #000;
}

.video-container :deep(.video-js) {
  min-height: 500px;
}

@media (max-width: 768px) {
  .drive-page {
    padding: 0;
  }

  .toolbar > * {
    width: 100% !important;
  }

  .pagination-container {
    justify-content: flex-start;
    overflow-x: auto;
  }

  .selection-toolbar,
  .selection-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .selection-actions {
    width: 100%;
    margin-left: 0;
  }

  .selection-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .video-container,
  .video-container :deep(.video-js) {
    min-height: 260px;
  }
}
</style>
