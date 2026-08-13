<template>
  <section class="pc-downloads-view">
    <div class="pc-downloads-toolbar">
      <div class="pc-downloads-filter-scroll">
        <el-segmented
          v-model="activeFilter"
          class="pc-downloads-filter"
          :options="filterOptions"
          data-testid="pc-download-filter"
        />
      </div>

      <div class="pc-downloads-summary">
        <span class="pc-downloads-concurrency">
          <span
            class="pc-downloads-running-dot"
            :class="{ 'is-active': downloads.activeCount > 0 }"
            aria-hidden="true"
          ></span>
          {{ concurrencyText }}
        </span>
        <el-tooltip content="清除已完成任务" placement="bottom">
          <el-button
            class="pc-downloads-clear-button"
            :icon="Delete"
            :disabled="downloads.completedTasks.length === 0"
            aria-label="清除已完成任务"
            @click="clearCompleted"
          />
        </el-tooltip>
      </div>
    </div>

    <div
      v-if="filteredTasks.length"
      class="pc-download-task-list"
      data-testid="pc-download-task-list"
    >
      <article v-for="task in filteredTasks" :key="task.id" class="pc-download-task">
        <div class="pc-download-file-icon" aria-hidden="true">
          <el-icon :size="18"><Document /></el-icon>
        </div>

        <div class="pc-download-task-body">
          <div class="pc-download-task-title-row">
            <h2 :title="task.fileName">{{ task.fileName }}</h2>
            <el-tag :type="getStatusTagType(task.status)" effect="light" size="small">
              {{ getStatusLabel(task.status) }}
            </el-tag>
          </div>
          <div class="pc-download-path" :title="task.savePath">
            {{ truncatePath(task.savePath, 96) }}
          </div>
          <el-progress
            class="pc-download-progress"
            :percentage="getProgressPercentage(task)"
            :status="getProgressStatus(task.status)"
            :stroke-width="6"
          />
          <div class="pc-download-meta">
            <span>{{ formatSize(task.downloadedBytes) }} / {{ formatSize(task.totalBytes) }}</span>
            <span>{{ formatSpeed(task.speedBytesPerSecond) }}</span>
            <span>{{ task.threads }} 线程</span>
            <span>{{ formatUpdatedAt(task.updatedAt) }}</span>
          </div>
          <div v-if="task.error?.message" class="pc-download-error">
            {{ task.error.message }}
          </div>
        </div>

        <div class="pc-download-task-actions">
          <el-tooltip v-if="canCancel(task)" content="取消下载" placement="top">
            <el-button
              class="pc-download-action-button"
              :icon="Close"
              circle
              aria-label="取消下载"
              @click="cancelTask(task)"
            />
          </el-tooltip>
          <el-tooltip v-if="canRetry(task)" content="重新下载" placement="top">
            <el-button
              class="pc-download-action-button"
              :icon="RefreshRight"
              circle
              aria-label="重新下载"
              @click="retryTask(task)"
            />
          </el-tooltip>
          <el-tooltip v-if="task.status === 'completed'" content="打开文件" placement="top">
            <el-button
              class="pc-download-action-button"
              :icon="View"
              circle
              aria-label="打开文件"
              @click="openFile(task)"
            />
          </el-tooltip>
          <el-tooltip v-if="task.status === 'completed'" content="打开所在文件夹" placement="top">
            <el-button
              class="pc-download-action-button"
              :icon="FolderOpened"
              circle
              aria-label="打开所在文件夹"
              @click="openFolder(task)"
            />
          </el-tooltip>
          <el-tooltip v-if="task.status !== 'downloading'" content="移除记录" placement="top">
            <el-button
              class="pc-download-action-button is-danger"
              :icon="Delete"
              circle
              aria-label="移除记录"
              @click="removeTask(task)"
            />
          </el-tooltip>
        </div>
      </article>
    </div>

    <PcStatePanel
      v-else-if="downloads.tasks.length === 0"
      class="pc-downloads-empty"
      asset="download-idle"
      title="暂无下载任务"
    />

    <div v-else class="pc-downloads-filter-empty" data-testid="pc-download-filter-empty">
      <span>当前筛选下没有任务</span>
      <el-button @click="activeFilter = 'all'">查看全部</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Delete, Document, FolderOpened, RefreshRight, View } from '@element-plus/icons-vue'
import {
  usePcDownloadsStore,
  type DownloadTaskStatus,
  type PcDownloadTask,
} from '@/stores/pcDownloads'
import { usePcPreferencesStore } from '@/stores/pcPreferences'
import { formatDate, formatSize, truncatePath } from '@/utils/formatters'
import PcStatePanel from '@/components/pc/pc-state-panel.vue'

type DownloadFilter = 'all' | DownloadTaskStatus

const downloads = usePcDownloadsStore()
const preferences = usePcPreferencesStore()
const activeFilter = ref<DownloadFilter>('all')

const filterOptions = computed(() => [
  { label: `全部 ${downloads.tasks.length}`, value: 'all' },
  { label: `下载中 ${downloads.downloadingTasks.length}`, value: 'downloading' },
  { label: `排队 ${downloads.queuedTasks.length}`, value: 'queued' },
  { label: `完成 ${downloads.completedTasks.length}`, value: 'completed' },
  { label: `失败 ${downloads.failedTasks.length}`, value: 'failed' },
  { label: `中断 ${downloads.interruptedTasks.length}`, value: 'interrupted' },
  { label: `取消 ${downloads.cancelledTasks.length}`, value: 'cancelled' },
])

const filteredTasks = computed(() => {
  if (activeFilter.value === 'all') return downloads.tasks
  return downloads.tasks.filter(task => task.status === activeFilter.value)
})

const concurrencyText = computed(() => (
  `${downloads.activeCount}/${preferences.maxConcurrentTasks} 运行中 · ${downloads.totalQueued} 排队`
))

function getStatusLabel(status: DownloadTaskStatus): string {
  const labels: Record<DownloadTaskStatus, string> = {
    queued: '排队中',
    downloading: '下载中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    interrupted: '已中断',
  }
  return labels[status]
}

function getStatusTagType(status: DownloadTaskStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'downloading') return 'warning'
  return 'info'
}

function getProgressStatus(status: DownloadTaskStatus): 'success' | 'exception' | 'warning' | undefined {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  if (status === 'cancelled' || status === 'interrupted') return 'warning'
  return undefined
}

function getProgressPercentage(task: PcDownloadTask): number {
  if (task.status === 'completed') return 100
  if (!task.totalBytes) return task.downloadedBytes > 0 ? 1 : 0
  return Math.min(100, Math.max(0, Math.round((task.downloadedBytes / task.totalBytes) * 100)))
}

function formatSpeed(speedBytesPerSecond: number): string {
  return speedBytesPerSecond > 0 ? `${formatSize(speedBytesPerSecond)}/s` : '-'
}

function formatUpdatedAt(value: string): string {
  return value ? formatDate(value) : '-'
}

function canCancel(task: PcDownloadTask): boolean {
  return task.status === 'queued' || task.status === 'downloading'
}

function canRetry(task: PcDownloadTask): boolean {
  return task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled'
}

function isDialogDismissed(error: unknown): boolean {
  return error === 'cancel' || error === 'close'
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (isDialogDismissed(error)) return ''
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as { message?: unknown }).message || fallback)
  }
  return typeof error === 'string' && error ? error : fallback
}

async function cancelTask(task: PcDownloadTask) {
  try {
    if (task.status === 'downloading') {
      await ElMessageBox.confirm(`取消「${task.fileName}」？`, '取消下载', {
        confirmButtonText: '取消下载',
        cancelButtonText: '返回',
        type: 'warning',
      })
    }
    await downloads.cancelTask(task.id)
    ElMessage.success('已取消')
  } catch (error) {
    const message = getErrorMessage(error, '取消失败')
    if (message) ElMessage.error(message)
  }
}

function retryTask(task: PcDownloadTask) {
  downloads.retryTask(task.id)
  ElMessage.success('已重新排队')
}

async function openFile(task: PcDownloadTask) {
  try {
    await downloads.openTaskFile(task.id)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '打开文件失败') || '打开文件失败')
  }
}

async function openFolder(task: PcDownloadTask) {
  try {
    await downloads.openTaskFolder(task.id)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '打开文件夹失败') || '打开文件夹失败')
  }
}

async function removeTask(task: PcDownloadTask) {
  try {
    await ElMessageBox.confirm(`移除「${task.fileName}」？`, '移除任务', {
      confirmButtonText: '移除',
      cancelButtonText: '返回',
      type: 'warning',
    })
    downloads.removeTask(task.id)
  } catch (error) {
    const message = getErrorMessage(error, '移除失败')
    if (message) ElMessage.error(message)
  }
}

async function clearCompleted() {
  try {
    await ElMessageBox.confirm('清除全部已完成的下载任务？', '清除已完成任务', {
      confirmButtonText: '清除',
      cancelButtonText: '返回',
      type: 'warning',
    })
    downloads.clearCompleted()
    ElMessage.success('已清除完成项')
  } catch (error) {
    const message = getErrorMessage(error, '清除失败')
    if (message) ElMessage.error(message)
  }
}
</script>

<style scoped>
.pc-downloads-view {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.pc-downloads-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
}

.pc-downloads-filter-scroll {
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
}

.pc-downloads-filter {
  min-width: max-content;
}

.pc-downloads-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.pc-downloads-concurrency {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--pc-color-text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.pc-downloads-running-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--pc-color-text-subtle);
}

.pc-downloads-running-dot.is-active {
  background: var(--pc-color-success);
}

.pc-downloads-clear-button {
  width: 32px;
  min-width: 32px;
  height: 32px;
  padding: 0;
}

.pc-download-task-list {
  overflow: hidden;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface);
}

.pc-download-task {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) 128px;
  gap: 12px;
  align-items: start;
  min-width: 0;
  padding: 13px 12px;
  border-bottom: 1px solid var(--pc-color-border);
  transition: background-color 140ms ease;
}

.pc-download-task:last-child {
  border-bottom: 0;
}

.pc-download-task:hover {
  background: var(--pc-color-surface-soft);
}

.pc-download-file-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-primary-soft);
  color: var(--pc-color-primary-strong);
}

.pc-download-task-body {
  min-width: 0;
}

.pc-download-task-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.pc-download-task-title-row h2 {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--pc-color-text);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-download-task-title-row :deep(.el-tag) {
  flex: 0 0 auto;
}

.pc-download-path {
  margin-top: 3px;
  overflow: hidden;
  color: var(--pc-color-text-muted);
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-download-progress {
  margin-top: 8px;
}

.pc-download-progress :deep(.el-progress__text) {
  min-width: 35px;
  font-size: 11px !important;
}

.pc-download-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 14px;
  margin-top: 6px;
  color: var(--pc-color-text-muted);
  font-size: 11px;
  line-height: 1.35;
}

.pc-download-error {
  margin-top: 6px;
  color: var(--pc-color-danger);
  font-size: 12px;
  line-height: 1.4;
}

.pc-download-task-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  width: 128px;
  min-height: 32px;
}

.pc-download-action-button {
  width: 30px;
  min-width: 30px;
  height: 30px;
  margin: 0;
  padding: 0;
}

.pc-download-action-button.is-danger {
  color: var(--pc-color-danger);
}

.pc-downloads-empty {
  min-height: 360px;
}

.pc-downloads-filter-empty {
  display: grid;
  place-items: center;
  gap: 12px;
  min-height: 240px;
  border: 1px dashed var(--pc-color-border-strong);
  border-radius: var(--pc-radius-md);
  color: var(--pc-color-text-muted);
  font-size: 13px;
}

@media (max-width: 860px) {
  .pc-downloads-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .pc-downloads-summary {
    justify-content: space-between;
  }

  .pc-download-task {
    grid-template-columns: 36px minmax(0, 1fr);
  }

  .pc-download-task-actions {
    grid-column: 2;
    justify-content: flex-start;
    width: auto;
  }
}
</style>
