import { defineStore } from 'pinia'

export type DriveViewMode = 'grid' | 'list'

const DRIVE_VIEW_MODE_KEY = 'mistrelay.pc.driveViewMode'
const DOWNLOAD_DIRECTORY_KEY = 'mistrelay.pc.downloadDirectory'
const THREADS_PER_FILE_KEY = 'mistrelay.pc.threadsPerFile'
const MAX_CONCURRENT_TASKS_KEY = 'mistrelay.pc.maxConcurrentTasks'
const DOWNLOAD_RETRY_COUNT_KEY = 'mistrelay.pc.downloadRetryCount'

const DEFAULT_THREADS_PER_FILE = 4
const DEFAULT_MAX_CONCURRENT_TASKS = 2
const DEFAULT_DOWNLOAD_RETRY_COUNT = 2

function loadDriveViewMode(): DriveViewMode {
  const stored = localStorage.getItem(DRIVE_VIEW_MODE_KEY)
  return stored === 'list' ? 'list' : 'grid'
}

function loadNumber(key: string, fallback: number, min: number, max: number): number {
  const value = Number(localStorage.getItem(key))
  return Number.isInteger(value) && value >= min && value <= max ? value : fallback
}

function assertRange(value: number, min: number, max: number, label: string) {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${label}必须在 ${min}-${max} 之间`)
  }
}

export const usePcPreferencesStore = defineStore('pcPreferences', {
  state: () => ({
    driveViewMode: loadDriveViewMode() as DriveViewMode,
    downloadDirectory: localStorage.getItem(DOWNLOAD_DIRECTORY_KEY) || '',
    threadsPerFile: loadNumber(THREADS_PER_FILE_KEY, DEFAULT_THREADS_PER_FILE, 1, 8),
    maxConcurrentTasks: loadNumber(MAX_CONCURRENT_TASKS_KEY, DEFAULT_MAX_CONCURRENT_TASKS, 1, 4),
    downloadRetryCount: loadNumber(DOWNLOAD_RETRY_COUNT_KEY, DEFAULT_DOWNLOAD_RETRY_COUNT, 0, 10),
  }),
  actions: {
    setDriveViewMode(value: DriveViewMode) {
      this.driveViewMode = value
      localStorage.setItem(DRIVE_VIEW_MODE_KEY, value)
    },

    setDownloadDirectory(value: string) {
      this.downloadDirectory = value.trim()
      if (this.downloadDirectory) {
        localStorage.setItem(DOWNLOAD_DIRECTORY_KEY, this.downloadDirectory)
      } else {
        localStorage.removeItem(DOWNLOAD_DIRECTORY_KEY)
      }
    },

    setThreadsPerFile(value: number) {
      assertRange(value, 1, 8, '单文件线程数')
      this.threadsPerFile = value
      localStorage.setItem(THREADS_PER_FILE_KEY, String(value))
    },

    setMaxConcurrentTasks(value: number) {
      assertRange(value, 1, 4, '全局并发数')
      this.maxConcurrentTasks = value
      localStorage.setItem(MAX_CONCURRENT_TASKS_KEY, String(value))
    },

    setDownloadRetryCount(value: number) {
      assertRange(value, 0, 10, '失败重试次数')
      this.downloadRetryCount = value
      localStorage.setItem(DOWNLOAD_RETRY_COUNT_KEY, String(value))
    },
  },
})
