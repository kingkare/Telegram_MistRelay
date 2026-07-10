<template>
  <div class="pc-media-grid">
    <article
      v-for="item in items"
      :key="getItemKey(item)"
      class="pc-card pc-media-card pc-drive-card"
      role="button"
      tabindex="0"
      @click="$emit('open', item)"
      @keydown.enter="$emit('open', item)"
      @keydown.space.prevent="$emit('open', item)"
    >
      <span class="pc-media-cover pc-drive-cover">
        <img
          v-if="getCoverUrl(item) && !failedCovers.has(getItemKey(item))"
          :src="getCoverUrl(item)"
          :alt="getTitle(item)"
          loading="lazy"
          @error="markCoverFailed(item)"
        >
        <span v-else class="pc-drive-cover-fallback">
          <el-icon :size="36">
            <Folder v-if="isTelegramDriveFolder(item)" />
            <VideoPlay v-else-if="isVideo(item)" />
            <Picture v-else-if="isImage(item)" />
            <Headset v-else-if="isAudio(item)" />
            <Document v-else />
          </el-icon>
        </span>
        <button
          v-if="showDelete"
          class="pc-drive-delete-button"
          type="button"
          title="删除"
          @click.stop="$emit('delete', item)"
        >
          <el-icon :size="16"><Delete /></el-icon>
        </button>
        <span v-if="isTelegramDriveFolder(item)" class="pc-album-badge">相册</span>
      </span>

      <span class="pc-media-body">
        <span class="pc-media-title" :title="getTitle(item)">{{ getTitle(item) }}</span>
        <span class="pc-media-meta">{{ getMeta(item) }}</span>
      </span>
    </article>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Delete, Document, Folder, Headset, Picture, VideoPlay } from '@element-plus/icons-vue'
import {
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveItem,
} from '@/api'
import { buildAuthorizedStreamUrl } from '@/utils/runtime'
import { formatSize } from '@/utils/formatters'

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

const failedCovers = ref(new Set<string>())

function getItemKey(item: TelegramDriveItem): string {
  return isTelegramDriveFolder(item) ? `folder-${item.media_group_id}` : item.file_unique_id
}

function getTitle(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) {
    return item.file_name || item.media_group_id
  }
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

function getCoverUrl(item: TelegramDriveItem): string {
  return item.thumbnail_url ? buildAuthorizedStreamUrl(item.thumbnail_url) : ''
}

function getMeta(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) {
    return `${item.item_count || 0} 个文件 · ${formatSize(item.total_size || 0)}`
  }
  return formatSize(item.file_size || 0)
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

function markCoverFailed(item: TelegramDriveItem) {
  failedCovers.value = new Set(failedCovers.value).add(getItemKey(item))
}
</script>

<style scoped>
.pc-drive-card {
  width: 100%;
  padding: 0;
  border: 0;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.pc-drive-card:hover {
  box-shadow: var(--pc-shadow-md);
  transform: translateY(-1px);
}

.pc-drive-cover {
  position: relative;
  display: block;
}

.pc-drive-cover img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pc-drive-cover-fallback {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  color: var(--pc-color-primary-strong);
}

.pc-album-badge {
  position: absolute;
  right: 8px;
  bottom: 8px;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: var(--pc-radius-sm);
  background: rgba(32, 48, 57, 0.72);
  color: #ffffff;
  font-size: 12px;
  line-height: 18px;
}

.pc-drive-delete-button {
  position: absolute;
  top: 8px;
  right: 8px;
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: var(--pc-radius-md);
  background: rgba(32, 48, 57, 0.72);
  color: #ffffff;
  cursor: pointer;
}

.pc-drive-delete-button:hover {
  background: var(--pc-color-danger);
}
</style>
