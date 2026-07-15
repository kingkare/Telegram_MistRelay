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
      <span class="pc-media-cover pc-drive-cover" :class="getCoverClass(item)">
        <img
          v-if="getCoverUrl(item) && !failedCovers.has(getItemKey(item))"
          :src="getCoverUrl(item)"
          :alt="getTitle(item)"
          loading="lazy"
          @error="markCoverFailed(item)"
        >
        <span v-else class="pc-drive-cover-fallback">
          <span class="pc-drive-fallback-icon">
            <el-icon :size="32">
              <Folder v-if="isTelegramDriveFolder(item)" />
              <VideoPlay v-else-if="isVideo(item)" />
              <Picture v-else-if="isImage(item)" />
              <Headset v-else-if="isAudio(item)" />
              <Document v-else />
            </el-icon>
          </span>
          <span class="pc-drive-type-label">{{ getTypeLabel(item) }}</span>
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

function getTypeLabel(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) return 'ALBUM'
  if (isVideo(item)) return 'VIDEO'
  if (isImage(item)) return 'IMAGE'
  if (isAudio(item)) return 'AUDIO'
  const title = getTitle(item)
  const extension = title.includes('.') ? title.split('.').pop() : ''
  return extension?.slice(0, 6).toUpperCase() || 'FILE'
}

function getCoverClass(item: TelegramDriveItem): string {
  if (isTelegramDriveFolder(item)) return 'is-album'
  if (isVideo(item)) return 'is-video'
  if (isImage(item)) return 'is-image'
  if (isAudio(item)) return 'is-audio'
  return 'is-file'
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
  border: 1px solid var(--pc-color-border);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.pc-drive-card:hover {
  border-color: #c8ccef;
  box-shadow: var(--pc-shadow-md);
  transform: translateY(-2px);
}

.pc-drive-card:focus-visible {
  outline: 3px solid var(--pc-color-focus);
  outline-offset: 2px;
}

.pc-drive-cover {
  position: relative;
  display: block;
}

.pc-drive-cover.is-album {
  background: linear-gradient(135deg, #ebeefe, #f2eafe);
}

.pc-drive-cover.is-video {
  background: linear-gradient(135deg, #e8edff, #eef4fb);
}

.pc-drive-cover.is-image {
  background: linear-gradient(135deg, #e8f2fa, #f1effd);
}

.pc-drive-cover.is-audio {
  background: linear-gradient(135deg, #f3ebfb, #ecefff);
}

.pc-drive-cover.is-file {
  background: linear-gradient(135deg, #edf0f6, #f5f6fa);
}

.pc-drive-cover img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pc-drive-cover-fallback {
  display: grid;
  align-content: center;
  place-items: center;
  gap: 9px;
  width: 100%;
  height: 100%;
  color: var(--pc-color-primary-strong);
}

.pc-drive-fallback-icon {
  display: inline-grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border: 1px solid rgba(98, 109, 231, 0.16);
  border-radius: var(--pc-radius-md);
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 5px 14px rgba(55, 61, 94, 0.08);
}

.pc-drive-type-label {
  color: var(--pc-color-text-muted);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0;
}

.pc-album-badge {
  position: absolute;
  right: 8px;
  bottom: 8px;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: var(--pc-radius-sm);
  background: rgba(37, 42, 61, 0.76);
  color: #ffffff;
  font-size: 12px;
  font-weight: 650;
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
  border: 1px solid rgba(207, 212, 227, 0.88);
  background: rgba(255, 255, 255, 0.9);
  color: #697086;
  box-shadow: 0 3px 9px rgba(55, 61, 94, 0.1);
  cursor: pointer;
}

.pc-drive-delete-button:hover {
  border-color: var(--pc-color-danger);
  background: var(--pc-color-danger);
  color: #ffffff;
}
</style>
