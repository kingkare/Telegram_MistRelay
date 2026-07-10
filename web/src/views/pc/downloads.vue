<template>
  <section class="pc-downloads-view">
    <div class="pc-downloads-header">
      <div class="pc-downloads-heading">
        <h1>下载</h1>
        <p>{{ concurrencyText }}</p>
      </div>
      <div class="pc-downloads-header-actions">
        <el-button :icon="RefreshRight" @click="downloads.drainQueue">继续队列</el-button>
        <el-button
          :icon="Delete"
          :disabled="downloads.finishedTasks.length === 0"
          @click="clearFinished"
        >
          清理完成项
        </el-button>
      </div>
    </div>

    <div class="pc-downloads-stats">
      <div v-for="item in stats" :key="item.label" class="pc-card pc-download-stat">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </div>

    <div class="pc-downloads-toolbar">
      <el-segmented v-model="activeFilter" :options="filterOptions" />
    </div>

    <div v-if="filteredTasks.length" class="pc-download-task-list">
      <article v-for="task in filteredTasks" :key="task.id" class="pc-card pc-download-task">
        <div class="pc-download-task-main">
          <div class="pc-download-file-icon" aria-hidden="true">
            <el-icon :size="22"><Document /></el-icon>
          </div>
          <div class="pc-download-task-body">
            <div class="pc-download-task-title-row">
              <h2>{{ task.fileName }}</h2>
              <el-tag :type="getStatusTagType(task.status)" effect="light">
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
              :stroke-width="8"
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
        </div>

        <div class="pc-download-task-actions">
          <el-button
            v-if="canCancel(task)"
            :icon="Close"
            @click="cancelTask(task)"
          >
            取消
          </el-button>
          <el-button
            v-if="canRetry(task)"
            :icon="RefreshRight"
            @click="retryTask(task)"
          >
            重试
          </el-button>
          <el-button
            v-if="task.status === 'completed'"
            :icon="Document"
            @click="openFile(task)"
          >
            打开
          </el-button>
          <el-button
            v-if="task.status === 'completed'"
            :icon="FolderOpened"
            @click="openFolder(task)"
          >
            文件夹
          </el-button>
          <el-button
            v-if="task.status !== 'downloading'"
            :icon="Delete"
            text
            type="danger"
            @click="removeTask(task)"
          >
            移除
          </el-button>
        </div>
      </article>
    </div>

    <div v-else class="pc-empty-state pc-downloads-empty">
      <div class="pc-anime-asset pc-anime-download-complete pc-downloads-empty-art" aria-hidden="true"></div>
      <div class="pc-downloads-empty-title">暂无下载任务</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Delete, Document, FolderOpened, RefreshRight } from '@element-plus/icons-vue'
import {
  usePcDownloadsStore,
  type DownloadTaskStatus,
  type PcDownloadTask,
} from '@/stores/pcDownloads'
import { usePcPreferencesStore } from '@/stores/pcPreferences'
import { formatDate, formatSize, truncatePath } from '@/utils/formatters'

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

const stats = computed(() => [
  { label: '下载中', value: downloads.activeCount },
  { label: '排队', value: downloads.totalQueued },
  { label: '已完成', value: downloads.completedTasks.length },
  { label: '需处理', value: downloads.failedTasks.length + downloads.interruptedTasks.length },
])

const concurrencyText = computed(() => (
  `${downloads.activeCount}/${preferences.maxConcurrentTasks} 个任务运行中`
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

async function clearFinished() {
  try {
    await ElMessageBox.confirm('清理已完成、失败和已取消任务？', '清理任务', {
      confirmButtonText: '清理',
      cancelButtonText: '返回',
      type: 'warning',
    })
    downloads.clearFinished()
  } catch (error) {
    const message = getErrorMessage(error, '清理失败')
    if (message) ElMessage.error(message)
  }
}
</script>

<style scoped>
.pc-downloads-view {
  display: grid;
  gap: 16px;
}

.pc-downloads-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.pc-downloads-heading {
  min-width: 0;
}

.pc-downloads-heading h1 {
  margin: 0;
  font-size: 22px;
  line-height: 1.25;
}

.pc-downloads-heading p {
  margin: 4px 0 0;
  color: var(--pc-color-text-muted);
  font-size: 13px;
}

.pc-downloads-header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.pc-downloads-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.pc-download-stat {
  display: grid;
  gap: 4px;
  min-height: 72px;
  padding: 12px;
}

.pc-download-stat span {
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-download-stat strong {
  font-size: 22px;
  line-height: 1.2;
}

.pc-downloads-toolbar {
  display: flex;
  justify-content: space-between;
  min-width: 0;
  overflow-x: auto;
}

.pc-download-task-list {
  display: grid;
  gap: 10px;
}

.pc-download-task {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  padding: 14px;
}

.pc-download-task-main {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
}

.pc-download-file-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface-soft);
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
  font-size: 15px;
  font-weight: 650;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-download-path {
  margin-top: 4px;
  overflow: hidden;
  color: var(--pc-color-text-muted);
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-download-progress {
  margin-top: 10px;
}

.pc-download-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, auto));
  gap: 12px;
  margin-top: 8px;
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-download-error {
  margin-top: 8px;
  color: var(--pc-color-danger);
  font-size: 12px;
  line-height: 1.4;
}

.pc-download-task-actions {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  justify-content: flex-end;
  gap: 8px;
  min-width: 236px;
}

.pc-downloads-empty {
  min-height: 360px;
}

.pc-downloads-empty-art {
  width: min(280px, 62vw);
}

.pc-downloads-empty-title {
  color: var(--pc-color-text);
  font-size: 15px;
  font-weight: 650;
}

@media (max-width: 960px) {
  .pc-downloads-header,
  .pc-download-task {
    grid-template-columns: 1fr;
  }

  .pc-downloads-header {
    display: grid;
  }

  .pc-downloads-header-actions,
  .pc-download-task-actions {
    justify-content: flex-start;
  }

  .pc-downloads-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pc-download-task-actions {
    min-width: 0;
  }
}

@media (max-width: 640px) {
  .pc-download-task-main {
    grid-template-columns: 1fr;
  }

  .pc-download-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
