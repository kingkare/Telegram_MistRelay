import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { defineStore } from 'pinia'
import { isTauriRuntime } from '@/utils/runtime'
import { usePcPreferencesStore } from '@/stores/pcPreferences'
import { notifyPc } from '@/utils/pcNotifications'

export type DownloadTaskStatus =
  | 'queued'
  | 'downloading'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export type DownloadChunkStatus =
  | 'queued'
  | 'downloading'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface DownloadError {
  taskId: string
  code: string
  message: string
  retryable: boolean
}

export interface DownloadChunk {
  index: number
  start: number
  end: number
  downloadedBytes: number
  status: DownloadChunkStatus
  error?: string
}

export interface DownloadTask {
  id: string
  sourceUrl: string
  fileName: string
  savePath: string
  totalBytes: number
  downloadedBytes: number
  status: DownloadTaskStatus
  threads: number
  createdAt: string
  updatedAt: string
  error?: DownloadError
}

export interface PcDownloadTask extends DownloadTask {
  speedBytesPerSecond: number
  chunks: DownloadChunk[]
}

export interface DownloadProgressEvent {
  taskId: string
  status: DownloadTaskStatus
  totalBytes: number
  downloadedBytes: number
  speedBytesPerSecond: number
  chunks: DownloadChunk[]
}

export interface StartDownloadTaskRequest {
  id?: string
  sourceUrl: string
  fileName?: string
  savePath: string
  threads?: number
}

export interface EnqueueDownloadInput {
  sourceUrl: string
  fileName: string
  savePath?: string
  threads?: number
}

interface PcDownloadsState {
  tasks: PcDownloadTask[]
}

export const PC_DOWNLOAD_EVENTS = {
  progress: 'pc-download-progress',
  completed: 'pc-download-completed',
  failed: 'pc-download-failed',
  cancelled: 'pc-download-cancelled',
} as const

export const PC_DOWNLOAD_COMMANDS = {
  start: 'start_download_task',
  cancel: 'cancel_download_task',
  reveal: 'reveal_download_task',
} as const

const DOWNLOAD_TASKS_STORAGE_KEY = 'mistrelay.pc.downloadTasks'
const MAX_PERSISTED_TASKS = 200
const DEFAULT_MAX_CONCURRENT_TASKS = 2

let sequence = 0
let eventListenersReady: Promise<void> | null = null
let eventUnlisteners: UnlistenFn[] = []
let closeGuardReady: Promise<void> | null = null
let closeGuardUnlisten: UnlistenFn | null = null

function nowIso(): string {
  return new Date().toISOString()
}

function createTaskId(): string {
  sequence += 1
  return `pc-download-${Date.now()}-${sequence}`
}

function joinDownloadPath(directory: string, fileName: string): string {
  const trimmedDirectory = directory.trim()
  if (!trimmedDirectory) return fileName
  return `${trimmedDirectory.replace(/[\\/]+$/, '')}/${fileName}`
}

function normalizeError(taskId: string, error: unknown, fallback = '下载失败'): DownloadError {
  if (error && typeof error === 'object' && 'message' in error) {
    return {
      taskId,
      code: 'download_failed',
      message: String((error as { message?: unknown }).message || fallback),
      retryable: true,
    }
  }

  return {
    taskId,
    code: 'download_failed',
    message: typeof error === 'string' && error ? error : fallback,
    retryable: true,
  }
}

function createInterruptedError(taskId: string): DownloadError {
  return {
    taskId,
    code: 'interrupted',
    message: '上次下载未完成，可重试',
    retryable: true,
  }
}

function isDownloadTaskStatus(value: unknown): value is DownloadTaskStatus {
  return (
    value === 'queued' ||
    value === 'downloading' ||
    value === 'completed' ||
    value === 'failed' ||
    value === 'cancelled' ||
    value === 'interrupted'
  )
}

function isInterruptedOnRestore(status: DownloadTaskStatus): boolean {
  return status === 'queued' || status === 'downloading'
}

function normalizePersistedTask(rawTask: unknown): PcDownloadTask | null {
  if (!rawTask || typeof rawTask !== 'object') return null

  const task = rawTask as Partial<PcDownloadTask>
  if (!task.id || !task.sourceUrl || !task.fileName || !task.savePath) return null

  const restoredStatus = isDownloadTaskStatus(task.status) ? task.status : 'interrupted'
  const status = isInterruptedOnRestore(restoredStatus) ? 'interrupted' : restoredStatus
  const now = nowIso()
  const taskId = String(task.id)

  return {
    id: taskId,
    sourceUrl: String(task.sourceUrl),
    fileName: String(task.fileName),
    savePath: String(task.savePath),
    totalBytes: Number.isFinite(task.totalBytes) ? Number(task.totalBytes) : 0,
    downloadedBytes: Number.isFinite(task.downloadedBytes) ? Number(task.downloadedBytes) : 0,
    status,
    threads: Number.isInteger(task.threads) ? Number(task.threads) : 4,
    createdAt: task.createdAt || now,
    updatedAt: now,
    error: status === 'interrupted' ? createInterruptedError(taskId) : task.error,
    speedBytesPerSecond: 0,
    chunks: Array.isArray(task.chunks) && status !== 'interrupted' ? task.chunks : [],
  }
}

function loadPersistedTasks(): PcDownloadTask[] {
  if (typeof localStorage === 'undefined') return []

  try {
    const parsed = JSON.parse(localStorage.getItem(DOWNLOAD_TASKS_STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .map(normalizePersistedTask)
      .filter((task): task is PcDownloadTask => Boolean(task))
      .slice(0, MAX_PERSISTED_TASKS)
  } catch {
    return []
  }
}

function persistTasks(tasks: PcDownloadTask[]) {
  if (typeof localStorage === 'undefined') return

  const persistedTasks = tasks.slice(0, MAX_PERSISTED_TASKS).map(task => ({
    ...task,
    speedBytesPerSecond: task.status === 'downloading' ? task.speedBytesPerSecond : 0,
  }))
  localStorage.setItem(DOWNLOAD_TASKS_STORAGE_KEY, JSON.stringify(persistedTasks))
}

function createLocalTask(input: EnqueueDownloadInput, preferences: ReturnType<typeof usePcPreferencesStore>): PcDownloadTask {
  const createdAt = nowIso()
  const threads = input.threads ?? preferences.threadsPerFile
  const savePath = input.savePath || joinDownloadPath(preferences.downloadDirectory, input.fileName)

  return {
    id: createTaskId(),
    sourceUrl: input.sourceUrl,
    fileName: input.fileName,
    savePath,
    totalBytes: 0,
    downloadedBytes: 0,
    status: 'queued',
    threads,
    createdAt,
    updatedAt: createdAt,
    speedBytesPerSecond: 0,
    chunks: [],
  }
}

function getCancelledTaskId(payload: unknown): string {
  if (typeof payload === 'string') return payload
  if (payload && typeof payload === 'object' && 'taskId' in payload) {
    return String((payload as { taskId?: unknown }).taskId || '')
  }
  return ''
}

export const usePcDownloadsStore = defineStore('pcDownloads', {
  state: (): PcDownloadsState => ({
    tasks: loadPersistedTasks(),
  }),

  getters: {
    queuedTasks: (state): PcDownloadTask[] => state.tasks.filter(task => task.status === 'queued'),
    downloadingTasks: (state): PcDownloadTask[] => state.tasks.filter(task => task.status === 'downloading'),
    completedTasks: (state): PcDownloadTask[] => state.tasks.filter(task => task.status === 'completed'),
    failedTasks: (state): PcDownloadTask[] => state.tasks.filter(task => task.status === 'failed'),
    cancelledTasks: (state): PcDownloadTask[] => state.tasks.filter(task => task.status === 'cancelled'),
    interruptedTasks: (state): PcDownloadTask[] => state.tasks.filter(task => task.status === 'interrupted'),
    finishedTasks: (state): PcDownloadTask[] => state.tasks.filter(task => (
      task.status === 'completed' ||
      task.status === 'failed' ||
      task.status === 'cancelled'
    )),
    activeCount(): number {
      return this.downloadingTasks.length
    },
    totalQueued(): number {
      return this.queuedTasks.length
    },
  },

  actions: {
    async ensureEventListeners() {
      if (!isTauriRuntime()) return
      void this.ensureWindowCloseGuard()
      if (eventListenersReady) {
        await eventListenersReady
        return
      }

      eventListenersReady = Promise.all([
        listen<DownloadProgressEvent>(PC_DOWNLOAD_EVENTS.progress, event => {
          this.applyProgress(event.payload)
        }),
        listen<DownloadTask>(PC_DOWNLOAD_EVENTS.completed, event => {
          this.applyCompleted(event.payload)
        }),
        listen<DownloadError>(PC_DOWNLOAD_EVENTS.failed, event => {
          this.applyFailure(event.payload)
        }),
        listen<unknown>(PC_DOWNLOAD_EVENTS.cancelled, event => {
          this.applyCancelled(getCancelledTaskId(event.payload))
        }),
      ]).then(unlisteners => {
        eventUnlisteners = unlisteners
      })

      await eventListenersReady
    },

    disposeEventListeners() {
      eventUnlisteners.forEach(unlisten => unlisten())
      eventUnlisteners = []
      eventListenersReady = null
      closeGuardUnlisten?.()
      closeGuardUnlisten = null
      closeGuardReady = null
    },

    async ensureWindowCloseGuard() {
      if (!isTauriRuntime()) return
      if (closeGuardReady) {
        await closeGuardReady
        return
      }

      closeGuardReady = getCurrentWindow().onCloseRequested(event => {
        if (this.downloadingTasks.length === 0) return
        const shouldClose = window.confirm(`仍有 ${this.downloadingTasks.length} 个下载任务运行中，确定关闭？`)
        if (!shouldClose) {
          event.preventDefault()
        }
      }).then(unlisten => {
        closeGuardUnlisten = unlisten
      })

      await closeGuardReady
    },

    enqueueDownload(input: EnqueueDownloadInput): PcDownloadTask {
      const preferences = usePcPreferencesStore()
      const task = createLocalTask(input, preferences)
      this.tasks.unshift(task)
      this.persist()
      void this.ensureEventListeners()
      void this.ensureWindowCloseGuard()
      this.drainQueue()
      return task
    },

    enqueueDownloads(inputs: EnqueueDownloadInput[]): PcDownloadTask[] {
      const tasks = inputs.map(input => this.enqueueDownload(input))
      this.drainQueue()
      return tasks
    },

    drainQueue() {
      const preferences = usePcPreferencesStore()
      const maxConcurrentTasks = Math.max(
        1,
        Math.min(4, preferences.maxConcurrentTasks || DEFAULT_MAX_CONCURRENT_TASKS),
      )
      const availableSlots = Math.max(0, maxConcurrentTasks - this.downloadingTasks.length)
      if (availableSlots === 0) return

      const nextTasks = this.queuedTasks
        .slice()
        .reverse()
        .slice(0, availableSlots)

      nextTasks.forEach(task => {
        void this.runTask(task.id)
      })
    },

    async runTask(taskId: string) {
      const task = this.tasks.find(item => item.id === taskId)
      if (!task || task.status !== 'queued') return

      if (!isTauriRuntime()) {
        this.applyFailure({
          taskId,
          code: 'tauri_unavailable',
          message: '桌面端下载能力不可用',
          retryable: false,
        })
        return
      }

      this.patchTask(taskId, {
        status: 'downloading',
        error: undefined,
        speedBytesPerSecond: 0,
      })

      try {
        await this.ensureEventListeners()
        const request: StartDownloadTaskRequest = {
          id: task.id,
          sourceUrl: task.sourceUrl,
          fileName: task.fileName,
          savePath: task.savePath,
          threads: task.threads,
        }
        const completedTask = await invoke<DownloadTask>(PC_DOWNLOAD_COMMANDS.start, { request })
        this.applyCompleted(completedTask)
      } catch (error) {
        const current = this.tasks.find(item => item.id === taskId)
        if (current && current.status === 'downloading') {
          this.applyFailure(normalizeError(taskId, error))
        }
      } finally {
        this.drainQueue()
      }
    },

    patchTask(taskId: string, patch: Partial<PcDownloadTask>) {
      const index = this.tasks.findIndex(task => task.id === taskId)
      if (index === -1) return
      this.tasks[index] = {
        ...this.tasks[index],
        ...patch,
        updatedAt: patch.updatedAt || nowIso(),
      }
      this.persist()
    },

    applyProgress(progress: DownloadProgressEvent) {
      this.patchTask(progress.taskId, {
        status: progress.status,
        totalBytes: progress.totalBytes,
        downloadedBytes: progress.downloadedBytes,
        speedBytesPerSecond: progress.speedBytesPerSecond,
        chunks: progress.chunks,
      })
    },

    applyCompleted(task: DownloadTask) {
      const existing = this.tasks.find(item => item.id === task.id)
      const previousStatus = existing?.status
      const completedTask: PcDownloadTask = {
        ...task,
        status: 'completed',
        speedBytesPerSecond: 0,
        chunks: existing?.chunks || [],
        updatedAt: task.updatedAt || nowIso(),
      }

      if (existing) {
        this.patchTask(task.id, completedTask)
      } else {
        this.tasks.unshift(completedTask)
        this.persist()
      }

      if (previousStatus !== 'completed') {
        void notifyPc({
          key: `download-completed:${task.id}`,
          title: '下载完成',
          body: task.fileName,
          cooldownMs: 60000,
        })
      }

      this.drainQueue()
    },

    applyFailure(error: DownloadError) {
      const task = this.tasks.find(item => item.id === error.taskId)
      const previousStatus = task?.status
      this.patchTask(error.taskId, {
        status: 'failed',
        error,
        speedBytesPerSecond: 0,
      })
      if (previousStatus !== 'failed') {
        void notifyPc({
          key: `download-failed:${error.taskId}`,
          title: '下载失败',
          body: task?.fileName ? `${task.fileName}：${error.message}` : error.message,
          cooldownMs: 60000,
        })
      }
      this.drainQueue()
    },

    applyCancelled(taskId: string) {
      if (!taskId) return
      this.patchTask(taskId, {
        status: 'cancelled',
        speedBytesPerSecond: 0,
      })
      this.drainQueue()
    },

    async cancelTask(taskId: string) {
      const task = this.tasks.find(item => item.id === taskId)
      if (!task || task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') return

      if (task.status !== 'downloading') {
        this.applyCancelled(taskId)
        return
      }

      await invoke(PC_DOWNLOAD_COMMANDS.cancel, { taskId })
      this.applyCancelled(taskId)
    },

    retryTask(taskId: string) {
      const task = this.tasks.find(item => item.id === taskId)
      if (!task || task.status === 'queued' || task.status === 'downloading') return

      this.patchTask(taskId, {
        status: 'queued',
        totalBytes: 0,
        downloadedBytes: 0,
        speedBytesPerSecond: 0,
        chunks: [],
        error: undefined,
      })
      this.drainQueue()
    },

    removeTask(taskId: string) {
      this.tasks = this.tasks.filter(task => task.id !== taskId)
      this.persist()
    },

    clearCompleted() {
      this.tasks = this.tasks.filter(task => task.status !== 'completed')
      this.persist()
    },

    clearFinished() {
      this.tasks = this.tasks.filter(task => (
        task.status !== 'completed' &&
        task.status !== 'failed' &&
        task.status !== 'cancelled'
      ))
      this.persist()
    },

    async openTaskFile(taskId: string) {
      const task = this.tasks.find(item => item.id === taskId)
      if (!task) return
      await invoke('open_file', { path: task.savePath })
    },

    async openTaskFolder(taskId: string) {
      const task = this.tasks.find(item => item.id === taskId)
      if (!task) return
      await invoke('open_folder', { path: task.savePath })
    },

    persist() {
      persistTasks(this.tasks)
    },
  },
})
