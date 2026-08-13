<template>
  <teleport to="body">
    <div
      v-if="currentItem"
      ref="dialogRef"
      class="pc-preview"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pc-preview-title"
      tabindex="-1"
      @click.self="close"
    >
      <div class="pc-preview-toolbar" role="toolbar" aria-label="文件预览工具栏">
        <button
          class="pc-preview-icon-button"
          type="button"
          title="关闭"
          aria-label="关闭预览"
          aria-keyshortcuts="Escape"
          @click="close"
        >
          <el-icon :size="20"><Close /></el-icon>
        </button>

        <div class="pc-preview-heading">
          <div id="pc-preview-title" class="pc-preview-title" :title="getTitle(currentItem)">
            {{ getTitle(currentItem) }}
          </div>
          <div class="pc-preview-meta">
            <span v-if="currentMeta">{{ currentMeta }}</span>
            <span class="pc-preview-count" aria-live="polite">{{ previewCount }}</span>
          </div>
        </div>

        <div class="pc-preview-actions">
          <button
            class="pc-preview-icon-button"
            type="button"
            title="下载"
            aria-label="下载当前文件"
            @click="emit('download', currentItem)"
          >
            <el-icon :size="20"><Download /></el-icon>
          </button>
          <button
            class="pc-preview-icon-button"
            type="button"
            title="另存为"
            aria-label="将当前文件另存为"
            @click="emit('save-as', currentItem)"
          >
            <el-icon :size="20"><FolderOpened /></el-icon>
          </button>
          <button
            v-if="allowDelete"
            class="pc-preview-icon-button danger"
            type="button"
            title="删除"
            aria-label="删除当前文件"
            @click="emit('delete', currentItem)"
          >
            <el-icon :size="20"><Delete /></el-icon>
          </button>
        </div>
      </div>

      <button
        class="pc-preview-nav previous"
        type="button"
        title="上一个"
        aria-label="预览上一个文件"
        aria-keyshortcuts="ArrowLeft"
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
          :aria-label="getTitle(currentItem)"
          controls
          autoplay
          playsinline
        />
        <div v-else class="pc-preview-non-media">
          <el-icon :size="54"><Document /></el-icon>
          <div class="pc-preview-non-media-title" :title="getTitle(currentItem)">
            {{ getTitle(currentItem) }}
          </div>
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
        aria-label="预览下一个文件"
        aria-keyshortcuts="ArrowRight"
        :disabled="!hasNext"
        @click="showNext"
      >
        <el-icon :size="28"><ArrowRight /></el-icon>
      </button>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Close, Delete, Document, Download, FolderOpened } from '@element-plus/icons-vue'
import {
  isTelegramDriveFile,
  type TelegramDriveItem,
} from '@/api'
import { buildAuthorizedStreamUrl } from '@/utils/runtime'

const props = withDefaults(defineProps<{
  modelValue: TelegramDriveItem | null
  items: TelegramDriveItem[]
  allowDelete?: boolean
}>(), {
  allowDelete: true,
})

const emit = defineEmits<{
  'update:modelValue': [item: TelegramDriveItem | null]
  close: []
  download: [item: TelegramDriveItem]
  'save-as': [item: TelegramDriveItem]
  delete: [item: TelegramDriveItem]
}>()

const dialogRef = ref<HTMLDivElement | null>(null)
const currentItem = computed(() => props.modelValue)
const previewableItems = computed(() => props.items.filter(isTelegramDriveFile))
const currentIndex = computed(() => {
  if (!currentItem.value) return -1
  return previewableItems.value.findIndex(item => getItemKey(item) === getItemKey(currentItem.value!))
})
const hasPrevious = computed(() => currentIndex.value > 0)
const hasNext = computed(() => currentIndex.value >= 0 && currentIndex.value < previewableItems.value.length - 1)
const previewCount = computed(() => {
  if (currentIndex.value < 0 || previewableItems.value.length === 0) return '1 / 1'
  return `${currentIndex.value + 1} / ${previewableItems.value.length}`
})
const currentMeta = computed(() => {
  const item = currentItem.value
  if (!item || !isTelegramDriveFile(item)) return ''

  return [
    item.mime_type || '',
    formatFileSize(item.file_size),
    item.width && item.height ? `${item.width} x ${item.height}` : '',
    formatDate(item.message_date),
  ].filter(Boolean).join(' · ')
})
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

function formatFileSize(bytes?: number): string {
  if (!Number.isFinite(bytes) || bytes === undefined || bytes < 0) return ''
  if (bytes === 0) return '0 B'

  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / (1024 ** unitIndex)
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
}

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
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

const focusableSelector = [
  'a[href]',
  'button:not(:disabled)',
  'input:not(:disabled)',
  'select:not(:disabled)',
  'textarea:not(:disabled)',
  'audio[controls]',
  'video[controls]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')
const elementPlusDialogSelector = [
  '.el-overlay-message-box',
  '.el-overlay-dialog',
  '.el-message-box',
  '.el-dialog',
].join(',')

let triggerElement: HTMLElement | null = null

function getFocusableElements(): HTMLElement[] {
  const dialog = dialogRef.value
  if (!dialog) return []

  return Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).filter(element => (
    element.tabIndex >= 0 &&
    element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility !== 'hidden'
  ))
}

function trapFocus(event: KeyboardEvent) {
  const dialog = dialogRef.value
  if (!dialog) return

  const focusableElements = getFocusableElements()
  if (!focusableElements.length) {
    event.preventDefault()
    dialog.focus({ preventScroll: true })
    return
  }

  const firstElement = focusableElements[0]
  const lastElement = focusableElements[focusableElements.length - 1]
  const activeElement = document.activeElement

  if (event.shiftKey) {
    if (activeElement === firstElement || activeElement === dialog || !dialog.contains(activeElement)) {
      event.preventDefault()
      lastElement.focus({ preventScroll: true })
    }
    return
  }

  if (activeElement === lastElement || activeElement === dialog || !dialog.contains(activeElement)) {
    event.preventDefault()
    firstElement.focus({ preventScroll: true })
  }
}

function isElementPlusDialogActive(): boolean {
  return Array.from(document.querySelectorAll<HTMLElement>(elementPlusDialogSelector)).some(element => (
    element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility !== 'hidden'
  ))
}

function isElementPlusDialogTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(elementPlusDialogSelector))
}

function isShortcutControl(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false

  return Boolean(target.closest([
    'input',
    'select',
    'textarea',
    'audio',
    'video',
    '[contenteditable]:not([contenteditable="false"])',
    '[role="combobox"]',
    '[role="slider"]',
    '[role="spinbutton"]',
    '[role="textbox"]',
  ].join(',')))
}

function restoreTriggerFocus() {
  const target = triggerElement
  triggerElement = null
  if (target?.isConnected) target.focus({ preventScroll: true })
}

function handleKeydown(event: KeyboardEvent) {
  if (!currentItem.value) return
  if (isElementPlusDialogActive() || isElementPlusDialogTarget(event.target)) return

  if (event.key === 'Tab') {
    trapFocus(event)
    return
  }

  if (event.defaultPrevented || isShortcutControl(event.target)) return
  if (event.key === 'Escape') close()
  if (event.key === 'ArrowLeft') showPrevious()
  if (event.key === 'ArrowRight') showNext()
}

watch(
  () => Boolean(currentItem.value),
  async (isOpen, wasOpen) => {
    if (isOpen && !wasOpen) {
      const activeElement = document.activeElement
      triggerElement = activeElement instanceof HTMLElement && activeElement !== document.body
        ? activeElement
        : null
      await nextTick()
      dialogRef.value?.focus({ preventScroll: true })
      return
    }

    if (!isOpen && wasOpen) {
      await nextTick()
      restoreTriggerFocus()
    }
  },
  { immediate: true, flush: 'post' },
)

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  restoreTriggerFocus()
})
</script>

<style scoped>
.pc-preview {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) 64px;
  grid-template-rows: 64px minmax(0, 1fr);
  background: rgba(20, 23, 32, 0.96);
  color: #ffffff;
}

.pc-preview:focus {
  outline: none;
}

.pc-preview-toolbar {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(27, 30, 41, 0.94);
}

.pc-preview-heading {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.pc-preview-title {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 600;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-preview-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: rgba(255, 255, 255, 0.68);
  font-size: 11px;
  line-height: 14px;
}

.pc-preview-meta > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-preview-count {
  flex: none;
  font-variant-numeric: tabular-nums;
}

.pc-preview-actions {
  display: flex;
  align-items: center;
  gap: 8px;
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

.pc-preview-icon-button:focus-visible,
.pc-preview-nav:focus-visible {
  outline: 3px solid rgba(137, 155, 255, 0.72);
  outline-offset: 2px;
}

.pc-preview-icon-button.danger:hover {
  background: var(--pc-color-danger, #c53f56);
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
