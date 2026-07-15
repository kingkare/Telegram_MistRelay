<template>
  <div class="pc-list pc-drive-list">
    <div class="pc-drive-list-header" aria-hidden="true">
      <span>名称</span>
      <span>类型</span>
      <span>大小</span>
      <span>日期</span>
      <span></span>
    </div>
    <div
      v-for="item in items"
      :key="getItemKey(item)"
      class="pc-list-row pc-drive-list-row"
      role="button"
      tabindex="0"
      @click="$emit('open', item)"
      @keydown.enter="$emit('open', item)"
      @keydown.space.prevent="$emit('open', item)"
    >
      <span class="pc-drive-list-name">
        <span class="pc-drive-list-icon">
          <el-icon :size="18">
            <Folder v-if="isTelegramDriveFolder(item)" />
            <VideoPlay v-else-if="isVideo(item)" />
            <Picture v-else-if="isImage(item)" />
            <Headset v-else-if="isAudio(item)" />
            <Document v-else />
          </el-icon>
        </span>
        <span class="pc-drive-list-title" :title="getTitle(item)">{{ getTitle(item) }}</span>
      </span>
      <span>{{ getTypeLabel(item) }}</span>
      <span>{{ getSize(item) }}</span>
      <span>{{ getDate(item) }}</span>
      <button
        v-if="showDelete"
        class="pc-drive-list-delete"
        type="button"
        title="删除"
        @click.stop="$emit('delete', item)"
      >
        <el-icon :size="16"><Delete /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Delete, Document, Folder, Headset, Picture, VideoPlay } from '@element-plus/icons-vue'
import {
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveItem,
} from '@/api'
import { formatDate, formatSize } from '@/utils/formatters'

withDefaults(defineProps<{
  items: TelegramDriveItem[]
  showDelete?: boolean
}>(), {
  showDelete: true,
})

defineEmits<{
  open: [item: TelegramDriveItem]
  delete: [item: TelegramDriveItem]
}>()

function getItemKey(item: TelegramDriveItem): string {
  return isTelegramDriveFolder(item) ? `folder-${item.media_group_id}` : item.file_unique_id
}

function getTitle(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) {
    return item.file_name || item.media_group_id
  }
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

function getTypeLabel(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) return '相册'
  if (isVideo(item)) return '视频'
  if (isImage(item)) return '图片'
  if (isAudio(item)) return '音频'
  return '文件'
}

function getSize(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) {
    return `${item.item_count || 0} 个 · ${formatSize(item.total_size || 0)}`
  }
  return formatSize(item.file_size || 0)
}

function getDate(item: TelegramDriveItem): string {
  return formatDate(item.message_date)
}

function isImage(item: TelegramDriveItem): boolean {
  return isTelegramDriveFile(item) && Boolean(item.mime_type?.startsWith('image/'))
}

function isVideo(item: TelegramDriveItem): boolean {
  return isTelegramDriveFile(item) && Boolean(item.mime_type?.startsWith('video/'))
}

function isAudio(item: TelegramDriveItem): boolean {
  return isTelegramDriveFile(item) && Boolean(item.mime_type?.startsWith('audio/'))
}
</script>

<style scoped>
.pc-drive-list-row {
  grid-template-columns: minmax(220px, 1fr) 96px 128px 156px 40px;
  width: 100%;
  border-top: 0;
  border-right: 0;
  border-left: 0;
  background: transparent;
  color: var(--pc-color-text-muted);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.pc-drive-list-header {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 96px 128px 156px 40px;
  gap: 12px;
  align-items: center;
  min-height: 36px;
  padding: 0 12px;
  border-bottom: 1px solid var(--pc-color-border);
  background: var(--pc-color-surface-soft);
  color: var(--pc-color-text-muted);
  font-size: 11px;
  font-weight: 650;
}

.pc-drive-list-delete {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: var(--pc-radius-md);
  background: transparent;
  color: var(--pc-color-text-muted);
  cursor: pointer;
}

.pc-drive-list-delete:hover {
  background: var(--pc-color-accent-soft);
  color: var(--pc-color-danger);
}

.pc-drive-list-row:hover {
  background: #f7f7fc;
}

.pc-drive-list-row:focus-visible {
  position: relative;
  outline: 2px solid var(--pc-color-primary);
  outline-offset: -2px;
}

.pc-drive-list-name {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 10px;
  color: var(--pc-color-text);
}

.pc-drive-list-icon {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface-soft);
  color: var(--pc-color-primary-strong);
  flex: 0 0 auto;
}

.pc-drive-list-title {
  min-width: 0;
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 820px) {
  .pc-drive-list-header,
  .pc-drive-list-row {
    grid-template-columns: minmax(180px, 1fr) 92px 40px;
  }

  .pc-drive-list-header span:nth-child(2),
  .pc-drive-list-header span:nth-child(4),
  .pc-drive-list-row > span:nth-child(2),
  .pc-drive-list-row > span:nth-child(4) {
    display: none;
  }
}
</style>
