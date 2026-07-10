import { invoke } from '@tauri-apps/api/core'
import {
  isTelegramDriveFile,
  refreshAuthTokens,
  type TelegramDriveItem,
} from '@/api'
import {
  usePcDownloadsStore,
  type PcDownloadTask,
} from '@/stores/pcDownloads'
import { usePcPreferencesStore } from '@/stores/pcPreferences'
import { buildAuthorizedStreamUrl, isTauriRuntime } from '@/utils/runtime'

interface QueueTelegramDownloadOptions {
  saveAs?: boolean
}

interface PreparedStream {
  sourceUrl: string
  fileName: string
}

function fallbackFileName(item: TelegramDriveItem): string {
  if (!isTelegramDriveFile(item)) return 'download.bin'
  return item.file_name || item.download_file_name || `telegram_${item.message_id}`
}

function decodeHeaderFileName(value: string): string {
  const trimmed = value.trim().replace(/^"|"$/g, '')
  try {
    return decodeURIComponent(trimmed)
  } catch {
    return trimmed
  }
}

function parseContentDispositionFileName(value: string | null): string {
  if (!value) return ''

  for (const part of value.split(';').map(item => item.trim())) {
    if (part.toLowerCase().startsWith('filename*=')) {
      const rawName = part.slice('filename*='.length)
      const encodedName = rawName.includes("''")
        ? rawName.split("''").slice(1).join("''")
        : rawName
      const fileName = decodeHeaderFileName(encodedName)
      if (fileName) return fileName
    }

    if (part.toLowerCase().startsWith('filename=')) {
      const fileName = decodeHeaderFileName(part.slice('filename='.length))
      if (fileName) return fileName
    }
  }

  return ''
}

function cleanFileName(fileName: string): string {
  const cleaned = fileName.replace(/[\\/:*?"<>|]/g, '_').trim()
  return cleaned || 'download.bin'
}

function splitFileName(fileName: string): { base: string; extension: string } {
  const dotIndex = fileName.lastIndexOf('.')
  if (dotIndex <= 0 || dotIndex === fileName.length - 1) {
    return { base: fileName, extension: '' }
  }
  return {
    base: fileName.slice(0, dotIndex),
    extension: fileName.slice(dotIndex),
  }
}

function getPathDirectory(path: string): string {
  const separatorIndex = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return separatorIndex >= 0 ? path.slice(0, separatorIndex) : ''
}

function getPathBaseName(path: string): string {
  const separatorIndex = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return separatorIndex >= 0 ? path.slice(separatorIndex + 1) : path
}

function joinPath(directory: string, fileName: string): string {
  const trimmedDirectory = directory.trim()
  if (!trimmedDirectory) return fileName
  return `${trimmedDirectory.replace(/[\\/]+$/, '')}/${fileName}`
}

function createUniqueFileName(fileName: string, directory: string, tasks: PcDownloadTask[]): string {
  const { base, extension } = splitFileName(fileName)
  const existingNames = new Set(
    tasks
      .filter(task => getPathDirectory(task.savePath) === directory)
      .map(task => getPathBaseName(task.savePath).toLowerCase()),
  )

  let index = 0
  let candidate = fileName
  while (existingNames.has(candidate.toLowerCase())) {
    index += 1
    candidate = `${base} (${index})${extension}`
  }
  return candidate
}

async function fetchStreamHead(sourceUrl: string): Promise<Response | null> {
  const response = await fetch(sourceUrl, { method: 'HEAD' })
  return response.status === 405 ? null : response
}

async function prepareStream(item: TelegramDriveItem): Promise<PreparedStream> {
  if (!isTelegramDriveFile(item) || !item.stream_url) {
    throw new Error('此条目不可下载')
  }

  let sourceUrl = buildAuthorizedStreamUrl(item.stream_url)
  let response = await fetchStreamHead(sourceUrl)

  if (response?.status === 401) {
    await refreshAuthTokens()
    sourceUrl = buildAuthorizedStreamUrl(item.stream_url)
    response = await fetchStreamHead(sourceUrl)
  }

  if (response && !response.ok) {
    throw new Error(response.status === 401 ? '登录已过期' : `下载预检失败：HTTP ${response.status}`)
  }

  const headerFileName = parseContentDispositionFileName(
    response?.headers.get('content-disposition') || null,
  )

  return {
    sourceUrl,
    fileName: cleanFileName(headerFileName || fallbackFileName(item)),
  }
}

async function chooseSavePath(fileName: string): Promise<string> {
  if (!isTauriRuntime()) {
    throw new Error('另存为仅在桌面端可用')
  }
  return invoke<string>('save_file', { options: { defaultName: fileName } })
}

export async function queueTelegramDownload(
  item: TelegramDriveItem,
  options: QueueTelegramDownloadOptions = {},
): Promise<PcDownloadTask> {
  const downloads = usePcDownloadsStore()
  const preferences = usePcPreferencesStore()
  const prepared = await prepareStream(item)

  if (options.saveAs) {
    const savePath = await chooseSavePath(prepared.fileName)
    const directory = getPathDirectory(savePath)
    const fileName = cleanFileName(getPathBaseName(savePath) || prepared.fileName)
    const uniqueFileName = createUniqueFileName(fileName, directory, downloads.tasks)
    const uniqueSavePath = joinPath(directory, uniqueFileName)

    return downloads.enqueueDownload({
      sourceUrl: prepared.sourceUrl,
      fileName: uniqueFileName,
      savePath: uniqueSavePath,
      threads: preferences.threadsPerFile,
    })
  }

  const directory = preferences.downloadDirectory
  const uniqueFileName = createUniqueFileName(prepared.fileName, directory, downloads.tasks)
  const savePath = joinPath(directory, uniqueFileName)

  return downloads.enqueueDownload({
    sourceUrl: prepared.sourceUrl,
    fileName: uniqueFileName,
    savePath,
    threads: preferences.threadsPerFile,
  })
}
