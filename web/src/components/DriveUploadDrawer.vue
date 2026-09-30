<template>
  <div class="drive-uploader-container">
    <!-- 悬浮小气泡徽标 (当抽屉折叠且存在任务时展示) -->
    <transition name="fade-scale">
      <div
        v-if="tasks.length > 0 && isCollapsed"
        class="uploader-floating-pill glass-card"
        @click="isCollapsed = false"
        :title="floatingTooltip"
      >
        <div class="pill-icon-wrap" :class="{ 'is-active': activeCount > 0 }">
          <el-icon v-if="activeCount > 0" class="is-spinning"><Loading /></el-icon>
          <el-icon v-else-if="failedCount > 0" class="text-danger"><WarningFilled /></el-icon>
          <el-icon v-else class="text-success"><CircleCheckFilled /></el-icon>
        </div>
        <div class="pill-content">
          <span class="pill-title">{{ activeCount > 0 ? `上传中 (${activeCount})` : '上传完成' }}</span>
          <span class="pill-sub">{{ overallProgress }}%</span>
        </div>
        <el-icon class="pill-expand-icon"><ArrowUp /></el-icon>
      </div>
    </transition>

    <!-- 展开式现代浮动任务面板 -->
    <transition name="slide-up">
      <div
        v-if="tasks.length > 0 && !isCollapsed"
        class="uploader-panel glass-card"
      >
        <!-- 任务面板头部 -->
        <div class="panel-header">
          <div class="panel-title-group">
            <h3 class="panel-title text-gradient-sakura">上传任务管理</h3>
            <span class="panel-badge">
              {{ completedCount }}/{{ tasks.length }} 完成
            </span>
          </div>

          <div class="panel-actions">
            <el-button
              size="small"
              type="primary"
              link
              :icon="Plus"
              @click="triggerFileInput"
              title="继续添加文件"
            >
              添加
            </el-button>
            <el-button
              v-if="completedCount > 0"
              size="small"
              type="info"
              link
              :icon="Delete"
              @click="clearCompleted"
              title="清除已完成任务"
            >
              清理
            </el-button>
            <el-button
              size="small"
              type="info"
              link
              :icon="Minus"
              @click="isCollapsed = true"
              title="折叠为浮动胶囊"
            >
              折叠
            </el-button>
            <el-button
              size="small"
              type="info"
              link
              :icon="Close"
              @click="handleCloseAll"
              title="关闭上传面板"
            >
              关闭
            </el-button>
          </div>
        </div>

        <!-- 任务列表容器 -->
        <div class="panel-body">
          <div
            v-for="task in tasks"
            :key="task.id"
            class="task-item"
            :class="[`status-${task.status}`]"
          >
            <!-- 左侧类型图标 -->
            <div class="task-icon-wrap">
              <el-icon :size="24">
                <VideoPlay v-if="task.category === 'video'" />
                <Picture v-else-if="task.category === 'image'" />
                <Headset v-else-if="task.category === 'audio'" />
                <Document v-else />
              </el-icon>
            </div>

            <!-- 中间信息与双阶段进度条 -->
            <div class="task-info">
              <div class="task-header-row">
                <span class="task-filename" :title="task.name">{{ task.name }}</span>
                <span class="task-filesize">{{ formatBytes(task.size) }}</span>
              </div>

              <!-- 双阶段进度条 -->
              <div class="progress-bar-wrapper">
                <div
                  class="progress-bar-fill"
                  :class="{
                    'is-tg-stage': task.status === 'uploading_tg',
                    'is-completed': task.status === 'completed',
                    'is-failed': task.status === 'failed'
                  }"
                  :style="{ width: `${getTaskDisplayPercent(task)}%` }"
                />
              </div>

              <!-- 状态详情文案 -->
              <div class="task-status-row">
                <span class="task-status-text">
                  <template v-if="task.status === 'waiting'">
                    <span class="text-muted">⏳ 排队等待上传...</span>
                  </template>
                  <template v-else-if="task.status === 'uploading'">
                    <span class="text-primary">
                      📦 本地分片 {{ task.chunkProgress }}%
                      <span v-if="task.speed" class="status-speed">({{ task.speed }})</span>
                      <span v-if="task.eta" class="status-eta">• {{ task.eta }}</span>
                    </span>
                  </template>
                  <template v-else-if="task.status === 'uploading_tg'">
                    <span class="text-purple">
                      ⚡ 正在转存至 Telegram 频道...
                      <span v-if="task.tgProgress > 0">({{ Math.round(task.tgProgress * 100) }}%)</span>
                    </span>
                  </template>
                  <template v-else-if="task.status === 'completed'">
                    <span class="text-success">
                      ✅ 已转存入库就绪
                    </span>
                  </template>
                  <template v-else-if="task.status === 'failed'">
                    <span class="text-danger" :title="task.error">
                      ❌ 上传失败: {{ task.error || '未知错误' }}
                    </span>
                  </template>
                  <template v-else-if="task.status === 'cancelled'">
                    <span class="text-muted">已取消</span>
                  </template>
                </span>

                <span class="task-percent-label">
                  {{ getTaskDisplayPercent(task) }}%
                </span>
              </div>
            </div>

            <!-- 右侧快捷操作按钮 -->
            <div class="task-action-wrap">
              <el-button
                v-if="task.status === 'failed'"
                size="small"
                circle
                type="warning"
                :icon="RefreshRight"
                @click="retryTask(task)"
                title="重新上传此文件"
              />
              <el-button
                v-else-if="task.status === 'waiting' || task.status === 'uploading' || task.status === 'uploading_tg'"
                size="small"
                circle
                type="danger"
                plain
                :icon="Close"
                @click="cancelTask(task)"
                title="取消此文件上传"
              />
              <el-button
                v-else-if="task.status === 'completed'"
                size="small"
                circle
                type="success"
                plain
                :icon="CircleCheckFilled"
                disabled
              />
              <el-button
                v-else
                size="small"
                circle
                :icon="Delete"
                @click="removeTask(task)"
                title="移除任务"
              />
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 隐藏式原生文件多选框 -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      style="display: none;"
      @change="handleFileInputChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  VideoPlay,
  Picture,
  Headset,
  Document,
  Loading,
  CircleCheckFilled,
  WarningFilled,
  ArrowUp,
  Minus,
  Close,
  Plus,
  Delete,
  RefreshRight
} from '@element-plus/icons-vue'
import {
  initTelegramUpload,
  uploadTelegramChunk,
  finishTelegramUpload,
  getTelegramUploadStatus,
  cancelTelegramUpload,
} from '@/api'
import { formatBytes } from '@/utils/formatters'

// 5MB 切片大小
const CHUNK_SIZE = 5 * 1024 * 1024
const MAX_CONCURRENT = 2

export interface UploadTask {
  id: string
  file: File
  name: string
  size: number
  category: 'video' | 'image' | 'audio' | 'document'
  status: 'waiting' | 'uploading' | 'uploading_tg' | 'completed' | 'failed' | 'cancelled'
  chunkProgress: number
  tgProgress: number
  speed: string
  eta: string
  error: string
  uploadId?: string
  totalChunks: number
  uploadedChunks: number
  abortController?: AbortController
  pollTimer?: any
}

const emit = defineEmits<{
  (e: 'upload-success', media: any): void
}>()

const tasks = ref<UploadTask[]>([])
const isCollapsed = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 统计值
const activeCount = computed(() =>
  tasks.value.filter(t => t.status === 'uploading' || t.status === 'uploading_tg' || t.status === 'waiting').length
)
const completedCount = computed(() =>
  tasks.value.filter(t => t.status === 'completed').length
)
const failedCount = computed(() =>
  tasks.value.filter(t => t.status === 'failed').length
)

const overallProgress = computed(() => {
  if (tasks.value.length === 0) return 0
  const sum = tasks.value.reduce((acc, t) => acc + getTaskDisplayPercent(t), 0)
  return Math.round(sum / tasks.value.length)
})

const floatingTooltip = computed(() => {
  return `上传任务: ${completedCount.value}/${tasks.value.length} 完成 (${overallProgress.value}%) - 点击展开`
})

function getTaskCategory(filename: string): 'video' | 'image' | 'audio' | 'document' {
  const lower = filename.toLowerCase()
  if (/\.(mp4|mkv|mov|avi|webm|flv|wmv|m4v)$/.test(lower)) return 'video'
  if (/\.(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/.test(lower)) return 'image'
  if (/\.(mp3|flac|m4a|wav|ogg|opus|aac)$/.test(lower)) return 'audio'
  return 'document'
}

function getTaskDisplayPercent(task: UploadTask): number {
  if (task.status === 'completed') return 100
  if (task.status === 'uploading_tg') {
    // TG 阶段映射到 80% ~ 99%
    const tgVal = task.tgProgress > 0 ? task.tgProgress : 0.2
    return Math.min(99, Math.round(80 + tgVal * 19))
  }
  if (task.status === 'uploading') {
    // 本地切片阶段映射到 0% ~ 80%
    return Math.round((task.chunkProgress / 100) * 80)
  }
  return 0
}

function triggerFileInput() {
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
    fileInputRef.value.click()
  }
}

function handleFileInputChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    addFiles(target.files)
  }
}

function addFiles(fileList: FileList | File[]) {
  const files = Array.from(fileList)
  if (files.length === 0) return

  let addedCount = 0
  for (const f of files) {
    // 校验大小：2GB 上限
    if (f.size > 2 * 1024 * 1024 * 1024) {
      ElMessage.warning(`文件 "${f.name}" 超过 Telegram 2GB 单文件限制，已跳过`)
      continue
    }
    if (f.size <= 0) {
      ElMessage.warning(`文件 "${f.name}" 大小为 0 字节，已跳过`)
      continue
    }

    const totalChunks = Math.max(1, Math.ceil(f.size / CHUNK_SIZE))
    const task: UploadTask = {
      id: `${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
      file: f,
      name: f.name,
      size: f.size,
      category: getTaskCategory(f.name),
      status: 'waiting',
      chunkProgress: 0,
      tgProgress: 0,
      speed: '',
      eta: '',
      error: '',
      totalChunks,
      uploadedChunks: 0,
    }
    tasks.value.unshift(task)
    addedCount++
  }

  if (addedCount > 0) {
    isCollapsed.value = false
    ElMessage.success(`已添加 ${addedCount} 个文件至上传队列`)
    scheduleNext()
  }
}

function scheduleNext() {
  const currentRunning = tasks.value.filter(
    t => t.status === 'uploading' || t.status === 'uploading_tg'
  ).length

  if (currentRunning >= MAX_CONCURRENT) return

  const nextTask = tasks.value.find(t => t.status === 'waiting')
  if (nextTask) {
    void executeUpload(nextTask)
    scheduleNext()
  }
}

async function executeUpload(task: UploadTask) {
  task.status = 'uploading'
  task.error = ''
  task.chunkProgress = 0
  task.tgProgress = 0

  let lastBytes = 0
  let lastTime = Date.now()

  try {
    // 1. 初始化上传会话
    const initRes = await initTelegramUpload({
      filename: task.name,
      file_size: task.size,
      chunk_size: CHUNK_SIZE,
      mime_type: task.file.type || '',
    })

    if (!initRes.success || !initRes.upload_id) {
      throw new Error(initRes.error || '初始化上传会话失败')
    }

    task.uploadId = initRes.upload_id
    task.totalChunks = initRes.total_chunks || task.totalChunks

    // 2. 顺序切片分块上传
    for (let idx = 0; idx < task.totalChunks; idx++) {
      if ((task.status as string) === 'cancelled') {
        return
      }

      const start = idx * CHUNK_SIZE
      const end = Math.min(task.size, start + CHUNK_SIZE)
      const chunkBlob = task.file.slice(start, end)

      await uploadTelegramChunk(
        task.uploadId,
        idx,
        chunkBlob,
        (progressEvent) => {
          if (progressEvent.total) {
            const currentChunkLoaded = progressEvent.loaded
            const totalUploadedBytes = start + currentChunkLoaded
            task.chunkProgress = Math.min(99, Math.round((totalUploadedBytes / task.size) * 100))

            // 计算传输速率与 ETA
            const now = Date.now()
            const timeDelta = (now - lastTime) / 1000
            if (timeDelta >= 0.5) {
              const bytesDelta = totalUploadedBytes - lastBytes
              const bytesPerSec = bytesDelta / timeDelta
              task.speed = `${formatBytes(bytesPerSec)}/s`

              const remainBytes = task.size - totalUploadedBytes
              if (bytesPerSec > 0) {
                const remainSec = Math.round(remainBytes / bytesPerSec)
                task.eta = remainSec > 60 ? `剩余 ${Math.ceil(remainSec / 60)} 分钟` : `剩余 ${remainSec} 秒`
              }
              lastBytes = totalUploadedBytes
              lastTime = now
            }
          }
        }
      )

      task.uploadedChunks = idx + 1
    }

    task.chunkProgress = 100
    task.speed = ''
    task.eta = ''

    // 3. 通知服务端开始合并与转存至 Telegram 频道
    task.status = 'uploading_tg'
    const finishRes = await finishTelegramUpload(task.uploadId)

    if (finishRes.status === 'completed') {
      task.status = 'completed'
      task.tgProgress = 1.0
      ElMessage.success(`文件 "${task.name}" 上传并转存成功`)
      emit('upload-success', finishRes.media)
      scheduleNext()
      return
    }

    // 4. 轮询云端转存入库状态
    pollTelegramStatus(task)

  } catch (err: any) {
    if ((task.status as string) !== 'cancelled') {
      task.status = 'failed'
      const errMsg = err?.response?.data?.error || err?.message || '上传异常'
      task.error = errMsg
      ElMessage.error(`"${task.name}" 上传失败: ${errMsg}`)
    }
  } finally {
    scheduleNext()
  }
}

function pollTelegramStatus(task: UploadTask) {
  if (!task.uploadId) return

  let pollCount = 0
  task.pollTimer = setInterval(async () => {
    pollCount++
    if (task.status !== 'uploading_tg') {
      clearInterval(task.pollTimer)
      return
    }

    try {
      const statusRes = await getTelegramUploadStatus(task.uploadId!)
      if (statusRes.tg_progress !== undefined) {
        task.tgProgress = statusRes.tg_progress
      }

      if (statusRes.status === 'completed') {
        clearInterval(task.pollTimer)
        task.status = 'completed'
        task.tgProgress = 1.0
        ElMessage.success(`文件 "${task.name}" 已成功入库至 TG 网盘`)
        emit('upload-success', statusRes.media)
        scheduleNext()
      } else if (statusRes.status === 'failed') {
        clearInterval(task.pollTimer)
        task.status = 'failed'
        task.error = statusRes.error || 'TG 转存入库失败'
        ElMessage.error(`"${task.name}" 云端转存失败: ${task.error}`)
        scheduleNext()
      } else if (pollCount > 300) { // 5分钟超时
        clearInterval(task.pollTimer)
        task.status = 'failed'
        task.error = '转存处理超时，请刷新网盘确认'
        scheduleNext()
      }
    } catch (e: any) {
      // 偶发网络抖动忽略，持续轮询
    }
  }, 1000)
}

async function retryTask(task: UploadTask) {
  if (task.pollTimer) clearInterval(task.pollTimer)
  task.status = 'waiting'
  task.error = ''
  task.chunkProgress = 0
  task.tgProgress = 0
  scheduleNext()
}

async function cancelTask(task: UploadTask) {
  if (task.pollTimer) clearInterval(task.pollTimer)
  task.status = 'cancelled'

  if (task.uploadId) {
    try {
      await cancelTelegramUpload(task.uploadId)
    } catch (e) {
      // 忽略取消请求错误
    }
  }
  scheduleNext()
}

function removeTask(task: UploadTask) {
  if (task.pollTimer) clearInterval(task.pollTimer)
  const idx = tasks.value.findIndex(t => t.id === task.id)
  if (idx !== -1) {
    tasks.value.splice(idx, 1)
  }
}

function clearCompleted() {
  tasks.value = tasks.value.filter(t => t.status !== 'completed' && t.status !== 'cancelled')
}

function handleCloseAll() {
  if (activeCount.value > 0) {
    ElMessageBox.confirm('当前仍有文件在上传中，折叠还是全部取消？', '提示', {
      confirmButtonText: '折叠后台继续',
      cancelButtonText: '取消全部上传',
      type: 'warning',
      distinguishCancelAndClose: true,
    }).then(() => {
      isCollapsed.value = true
    }).catch((action) => {
      if (action === 'cancel') {
        tasks.value.forEach(t => {
          if (t.status === 'uploading' || t.status === 'uploading_tg' || t.status === 'waiting') {
            void cancelTask(t)
          }
        })
        tasks.value = []
      }
    })
  } else {
    tasks.value = []
  }
}

onUnmounted(() => {
  tasks.value.forEach(t => {
    if (t.pollTimer) clearInterval(t.pollTimer)
  })
})

// 对外暴露方法
defineExpose({
  addFiles,
  triggerFileInput,
  openDrawer: () => { isCollapsed.value = false },
  closeDrawer: () => { isCollapsed.value = true },
  clearCompleted,
})
</script>

<style scoped>
.drive-uploader-container {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 2800;
  pointer-events: none;
}

/* 浮动小胶囊样式 */
.uploader-floating-pill {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 183, 197, 0.4);
  box-shadow: 0 10px 30px rgba(255, 105, 180, 0.15), 0 4px 12px rgba(0, 0, 0, 0.05);
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
}

.uploader-floating-pill:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 36px rgba(255, 105, 180, 0.25);
  border-color: rgba(255, 154, 179, 0.7);
}

.pill-icon-wrap {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 240, 245, 0.8);
  color: #ff6b8b;
  font-size: 16px;
}

.pill-icon-wrap.is-active {
  background: linear-gradient(135deg, rgba(255, 107, 139, 0.15), rgba(124, 77, 255, 0.15));
  color: #ff4081;
}

.is-spinning {
  animation: spin 1s linear infinite;
}

.pill-content {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.pill-title {
  font-size: 13px;
  font-weight: 600;
  color: #2d3748;
}

.pill-sub {
  font-size: 11px;
  font-weight: 700;
  color: #ff4081;
}

.pill-expand-icon {
  font-size: 14px;
  color: #718096;
}

/* 展开式任务管理器卡片 */
.uploader-panel {
  pointer-events: auto;
  width: 440px;
  max-width: calc(100vw - 32px);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 183, 197, 0.45);
  border-radius: 18px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15), 0 0 20px rgba(255, 183, 197, 0.2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-height: 520px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(255, 245, 247, 0.4);
}

.panel-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.panel-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 9999px;
  background: rgba(255, 107, 139, 0.12);
  color: #ff4081;
  font-weight: 600;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.panel-body {
  padding: 10px 12px;
  overflow-y: auto;
  max-height: 440px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 单条任务项样式 */
.task-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.6);
  transition: all 0.2s ease;
}

.task-item:hover {
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

.task-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(255, 183, 197, 0.25), rgba(124, 77, 255, 0.15));
  color: #ff4081;
  flex-shrink: 0;
}

.task-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.task-filename {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-filesize {
  font-size: 11px;
  color: #64748b;
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.progress-bar-wrapper {
  height: 6px;
  border-radius: 9999px;
  background: rgba(226, 232, 240, 0.8);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  border-radius: 9999px;
  background: linear-gradient(90deg, #ff758c, #ff7eb3);
  transition: width 0.2s ease;
}

.progress-bar-fill.is-tg-stage {
  background: linear-gradient(90deg, #8a2be2, #4facfe);
  animation: pulse-stream 1.5s ease-in-out infinite;
}

.progress-bar-fill.is-completed {
  background: linear-gradient(90deg, #10b981, #059669);
}

.progress-bar-fill.is-failed {
  background: linear-gradient(90deg, #ef4444, #dc2626);
}

.task-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.task-status-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-speed {
  font-weight: 600;
  margin-left: 2px;
}

.status-eta {
  color: #64748b;
  margin-left: 4px;
}

.task-percent-label {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.task-action-wrap {
  flex-shrink: 0;
}

/* 颜色工具类 */
.text-primary { color: #ff4081; }
.text-purple { color: #7c4dff; }
.text-success { color: #10b981; }
.text-danger { color: #ef4444; }
.text-muted { color: #94a3b8; }

.text-gradient-sakura {
  background: linear-gradient(135deg, #ff4081 0%, #7c4dff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

/* 动画定义 */
@keyframes spin {
  100% { transform: rotate(360deg); }
}

@keyframes pulse-stream {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.75; }
}

.fade-scale-enter-active,
.fade-scale-leave-active {
  transition: all 0.25s ease;
}
.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: scale(0.85);
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.96);
}

/* 暗色模式适配 */
html.dark .uploader-floating-pill,
html.dark .uploader-panel {
  background: rgba(30, 41, 59, 0.92);
  border-color: rgba(255, 107, 139, 0.3);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
}

html.dark .panel-header {
  background: rgba(15, 23, 42, 0.5);
  border-bottom-color: rgba(51, 65, 85, 0.6);
}

html.dark .task-item {
  background: rgba(15, 23, 42, 0.7);
  border-color: rgba(51, 65, 85, 0.5);
}

html.dark .task-filename {
  color: #f1f5f9;
}

html.dark .progress-bar-wrapper {
  background: rgba(51, 65, 85, 0.8);
}

@media (max-width: 768px) {
  .uploader-panel {
    width: 95vw !important;
    max-width: 95vw !important;
    max-height: 70vh !important;
    border-radius: 16px !important;
  }
  .uploader-container {
    bottom: calc(64px + env(safe-area-inset-bottom, 0px)) !important;
    right: 8px !important;
    left: 8px !important;
    display: flex !important;
    justify-content: center !important;
  }
}

</style>
