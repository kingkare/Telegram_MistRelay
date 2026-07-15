<template>
  <teleport to="body">
    <div v-if="currentItem" class="pc-preview" @click.self="close">
      <div class="pc-preview-toolbar">
        <button class="pc-preview-icon-button" type="button" title="关闭" @click="close">
          <el-icon :size="20"><Close /></el-icon>
        </button>
        <div class="pc-preview-title" :title="getTitle(currentItem)">
          {{ getTitle(currentItem) }}
        </div>
        <button class="pc-preview-icon-button" type="button" title="下载" @click="emit('download', currentItem)">
          <el-icon :size="20"><Download /></el-icon>
        </button>
        <button class="pc-preview-icon-button" type="button" title="另存为" @click="emit('save-as', currentItem)">
          <el-icon :size="20"><FolderOpened /></el-icon>
        </button>
        <button class="pc-preview-icon-button danger" type="button" title="删除" @click="emit('delete', currentItem)">
          <el-icon :size="20"><Delete /></el-icon>
        </button>
      </div>

      <button
        class="pc-preview-nav previous"
        type="button"
        title="上一个"
        :disabled="!hasPrevious"
        @click="showPrevious"
      >
        <el-icon :size="28"><ArrowLeft /></el-icon>
      </button>

      <div class="pc-preview-stage">
        <img
          v-if="isImage(currentItem)"
          class="pc-preview-media"
          :src="streamUrl"
          :alt="getTitle(currentItem)"
        >
        <video
          v-else-if="isVideo(currentItem)"
          class="pc-preview-media"
          :src="streamUrl"
          controls
          autoplay
        />
        <div v-else class="pc-preview-non-media">
          <el-icon :size="54"><Document /></el-icon>
          <div class="pc-preview-non-media-title">{{ getTitle(currentItem) }}</div>
          <div class="pc-preview-non-media-actions">
            <button class="pc-button pc-button-primary" type="button" @click="emit('download', currentItem)">
              下载
            </button>
            <button class="pc-button" type="button" @click="emit('save-as', currentItem)">
              另存为
            </button>
          </div>
        </div>
      </div>

      <button
        class="pc-preview-nav next"
        type="button"
        title="下一个"
        :disabled="!hasNext"
        @click="showNext"
      >
        <el-icon :size="28"><ArrowRight /></el-icon>
      </button>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { ArrowLeft, ArrowRight, Close, Delete, Document, Download, FolderOpened } from '@element-plus/icons-vue'
import {
  isTelegramDriveFile,
  type TelegramDriveItem,
} from '@/api'
import { buildAuthorizedStreamUrl } from '@/utils/runtime'

const props = defineProps<{
  modelValue: TelegramDriveItem | null
  items: TelegramDriveItem[]
}>()

const emit = defineEmits<{
  'update:modelValue': [item: TelegramDriveItem | null]
  close: []
  download: [item: TelegramDriveItem]
  'save-as': [item: TelegramDriveItem]
  delete: [item: TelegramDriveItem]
}>()

const currentItem = computed(() => props.modelValue)
const currentIndex = computed(() => {
  if (!currentItem.value) return -1
  return previewableItems.value.findIndex(item => getItemKey(item) === getItemKey(currentItem.value!))
})
const previewableItems = computed(() => props.items.filter(isTelegramDriveFile))
const hasPrevious = computed(() => currentIndex.value > 0)
const hasNext = computed(() => currentIndex.value >= 0 && currentIndex.value < previewableItems.value.length - 1)
const streamUrl = computed(() => {
  const item = currentItem.value
  return item && isTelegramDriveFile(item) && item.stream_url
    ? buildAuthorizedStreamUrl(item.stream_url)
    : ''
})

function getItemKey(item: TelegramDriveItem): string {
  return isTelegramDriveFile(item) ? item.file_unique_id : `folder-${item.media_group_id}`
}

function getTitle(item: TelegramDriveItem): string {
  if (!isTelegramDriveFile(item)) return item.file_name || item.media_group_id
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

function isImage(item: TelegramDriveItem): boolean {
  return isTelegramDriveFile(item) && Boolean(item.mime_type?.startsWith('image/')) && Boolean(item.stream_url)
}

function isVideo(item: TelegramDriveItem): boolean {
  return isTelegramDriveFile(item) && Boolean(item.mime_type?.startsWith('video/')) && Boolean(item.stream_url)
}

function close() {
  emit('update:modelValue', null)
  emit('close')
}

function showPrevious() {
  if (!hasPrevious.value) return
  emit('update:modelValue', previewableItems.value[currentIndex.value - 1])
}

function showNext() {
  if (!hasNext.value) return
  emit('update:modelValue', previewableItems.value[currentIndex.value + 1])
}

function handleKeydown(event: KeyboardEvent) {
  if (!currentItem.value) return
  if (event.key === 'Escape') close()
  if (event.key === 'ArrowLeft') showPrevious()
  if (event.key === 'ArrowRight') showNext()
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<style scoped>
.pc-preview {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) 64px;
  grid-template-rows: 58px minmax(0, 1fr);
  background: rgba(24, 25, 40, 0.94);
  color: #ffffff;
}

.pc-preview-toolbar {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 42px 42px 42px;
  gap: 8px;
  align-items: center;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(31, 32, 51, 0.72);
  backdrop-filter: blur(16px);
}

.pc-preview-title {
  min-width: 0;
  overflow: hidden;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-preview-icon-button,
.pc-preview-nav {
  display: inline-grid;
  place-items: center;
  border: 0;
  border-radius: var(--pc-radius-md);
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  cursor: pointer;
}

.pc-preview-icon-button {
  width: 40px;
  height: 40px;
}

.pc-preview-icon-button:hover,
.pc-preview-nav:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.18);
}

.pc-preview-icon-button.danger:hover {
  background: rgba(217, 75, 75, 0.9);
}

.pc-preview-nav {
  width: 48px;
  height: 72px;
  align-self: center;
  justify-self: center;
}

.pc-preview-nav:disabled {
  opacity: 0.28;
  cursor: default;
}

.pc-preview-stage {
  display: grid;
  place-items: center;
  min-width: 0;
  min-height: 0;
  padding: 18px;
}

.pc-preview-media {
  max-width: 100%;
  max-height: 100%;
  border-radius: var(--pc-radius-md);
  object-fit: contain;
}

.pc-preview-non-media {
  display: grid;
  justify-items: center;
  gap: 14px;
  max-width: 420px;
  padding: 24px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: var(--pc-radius-md);
  background: rgba(255, 255, 255, 0.08);
}

.pc-preview-non-media-title {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-preview-non-media-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
</style>
