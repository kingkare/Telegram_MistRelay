import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import type {
  ServerStatus,
  DownloadsResponse,
  DockerStatus,
  DockerRestartResponse,
  DockerLogsResponse,
  ConfigResponse,
  ConfigUpdateResponse,
  SystemResourcesResponse,
  TelegramBrowseParams,
  TelegramBrowseResponse,
  TelegramBatchDeleteRequest,
  TelegramDeleteResponse,
  TelegramUsageResponse,
  UploadRecord
} from '@/types/api'
import {
  clearAuthTokens,
  getApiBaseUrl,
  getAuthToken,
  getRefreshToken,
  isCurrentLoginRoute,
  redirectToLogin,
  setAuthToken,
  setRefreshToken,
} from '@/utils/runtime'

export type {
  TelegramBrowseParams,
  TelegramBrowseResponse,
  TelegramBatchDeleteRequest,
  TelegramDeleteResponse,
  TelegramDriveFile,
  TelegramDriveFolder,
  TelegramDriveItem,
  TelegramUsageResponse,
  TelegramUsageStats,
} from '@/types/api'

export {
  isTelegramDriveFile,
  isTelegramDriveFolder,
} from '@/types/api'

declare module 'axios' {
  export interface AxiosRequestConfig {
    _retry?: boolean
    skipAuthRefresh?: boolean
  }

  export interface InternalAxiosRequestConfig {
    _retry?: boolean
    skipAuthRefresh?: boolean
  }
}

interface AuthRefreshResponse {
  success: boolean
  token?: string
  refresh_token?: string
  expires_in?: number
  error?: string
}

type RetryableRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean
  skipAuthRefresh?: boolean
}

let refreshPromise: Promise<string> | null = null

export const api = axios.create({
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.request.use((config) => {
  config.baseURL = getApiBaseUrl()

  const token = getAuthToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export async function refreshAuthTokens(): Promise<string> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    throw new Error('缺少 refresh token')
  }

  if (!refreshPromise) {
    refreshPromise = api.post<AuthRefreshResponse>(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { skipAuthRefresh: true },
    ).then((response) => {
      const payload = response.data
      if (!payload.success || !payload.token || !payload.refresh_token) {
        throw new Error(payload.error || '刷新登录失败')
      }

      setAuthToken(payload.token)
      setRefreshToken(payload.refresh_token)
      return payload.token
    }).finally(() => {
      refreshPromise = null
    })
  }

  return refreshPromise
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableRequestConfig | undefined

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest.skipAuthRefresh &&
      !originalRequest._retry
    ) {
      originalRequest._retry = true

      try {
        const token = await refreshAuthTokens()
        originalRequest.headers.Authorization = `Bearer ${token}`
        return api(originalRequest)
      } catch {
        clearAuthTokens()
        if (!isCurrentLoginRoute()) {
          redirectToLogin()
        }
      }
    }

    if (error.response?.status === 401) {
      clearAuthTokens()
      if (!isCurrentLoginRoute()) {
        redirectToLogin()
      }
    }
    return Promise.reject(error)
  }
)

export function getStatus(): Promise<ServerStatus> {
  return api.get<ServerStatus>('/status').then(response => response.data)
}

export function getDownloads(limit = 100, grouped = true): Promise<DownloadsResponse> {
  return api.get<DownloadsResponse>('/downloads', {
    params: { limit, grouped }
  }).then(response => response.data)
}

export function getDockerStatus(): Promise<DockerStatus> {
  return api.get<DockerStatus>('/system/docker/status').then(response => response.data)
}

export function restartDocker(): Promise<DockerRestartResponse> {
  return api.post<DockerRestartResponse>('/system/docker/restart').then(response => response.data)
}

export function getDockerLogs(lines = 100): Promise<DockerLogsResponse> {
  return api.get<DockerLogsResponse>('/system/docker/logs', {
    params: { lines }
  }).then(response => response.data)
}

export function getSystemResources(): Promise<SystemResourcesResponse> {
  return api.get<SystemResourcesResponse>('/system/resources').then(response => response.data)
}

export function getConfig(category?: string): Promise<ConfigResponse> {
  return api.get<ConfigResponse>('/config', {
    params: category ? { category } : {}
  }).then(response => response.data)
}

export function updateConfig(config: Record<string, any>): Promise<ConfigUpdateResponse> {
  return api.post<ConfigUpdateResponse>('/config', config).then(response => response.data)
}

export interface QueueStatus {
  success: boolean
  current_processing: any | null
  waiting_count: number
  waiting_items: any[]
  queue_size: number
  error?: string
}

export function getQueue(): Promise<QueueStatus> {
  return api.get<QueueStatus>('/queue').then(response => response.data)
}

export interface TrendPoint {
  timestamp: number
  upload: number
  download: number
  io: number
}

export interface TrendResponse {
  success: boolean
  data: TrendPoint[]
  error?: string
}

export function getSystemTrend(): Promise<TrendResponse> {
  return api.get<TrendResponse>('/monitor/trend').then(response => response.data)
}

export interface DownloadStatistics {
  total: number
  completed: number
  downloading: number
  failed: number
  pending: number
  waiting: number
  total_size: number
  completed_size: number
}

export interface DownloadStatisticsResponse {
  success: boolean
  data: DownloadStatistics
  error?: string
}

export function getDownloadStatistics(): Promise<DownloadStatisticsResponse> {
  return api.get<DownloadStatisticsResponse>('/downloads/statistics').then(response => response.data)
}

export interface DeleteAllDownloadsResponse {
  success: boolean
  message?: string
  data?: {
    deleted_downloads: number
    deleted_media: number
  }
  error?: string
}

export function deleteAllDownloads(): Promise<DeleteAllDownloadsResponse> {
  return api.delete<DeleteAllDownloadsResponse>('/downloads/all').then(response => response.data)
}

export interface UploadStatistics {
  total: number
  uploading: number
  completed: number
  failed: number
  pending: number
  cleaned: number
}

export interface UploadStatisticsResponse {
  success: boolean
  data: UploadStatistics
  error?: string
}

export function getUploadStatistics(): Promise<UploadStatisticsResponse> {
  return api.get<UploadStatisticsResponse>('/uploads/statistics').then(response => response.data)
}

export interface UploadsResponse {
  success: boolean
  limit: number
  count: number
  data: UploadRecord[]
  error?: string
}

export function getUploads(limit = 100, status?: string, uploadTarget?: string): Promise<UploadsResponse> {
  return api.get<UploadsResponse>('/uploads', {
    params: { limit, status, upload_target: uploadTarget }
  }).then(response => response.data)
}

// ==================== 下载任务控制 API ====================

export interface TaskControlResponse {
  success: boolean
  message?: string
  new_gid?: string
  error?: string
}

export function retryDownload(gid: string): Promise<TaskControlResponse> {
  return api.post<TaskControlResponse>(`/downloads/${gid}/retry`).then(response => response.data)
}

export function deleteDownload(gid: string): Promise<TaskControlResponse> {
  return api.delete<TaskControlResponse>(`/downloads/${gid}`).then(response => response.data)
}

export interface DeleteRecordResponse {
  success: boolean
  message?: string
  data?: {
    download_deleted: boolean
    upload_count: number
    media_deleted: boolean
    file_deleted: boolean
    local_path?: string
  }
  error?: string
}

export function deleteDownloadRecord(downloadId: number, deleteFile: boolean = true): Promise<DeleteRecordResponse> {
  return api.delete<DeleteRecordResponse>(`/downloads/record/${downloadId}`, {
    params: { delete_file: deleteFile }
  }).then(response => response.data)
}

// ==================== 上传任务控制 API ====================

export function retryUpload(uploadId: number): Promise<TaskControlResponse> {
  return api.post<TaskControlResponse>(`/uploads/${uploadId}/retry`).then(response => response.data)
}

export function deleteUpload(uploadId: number): Promise<TaskControlResponse> {
  return api.delete<TaskControlResponse>(`/uploads/${uploadId}`).then(response => response.data)
}


// ==================== Telegram 频道网盘 API ====================

export function browseTelegramDrive(params: TelegramBrowseParams = {}): Promise<TelegramBrowseResponse> {
  return api.get<TelegramBrowseResponse>('/telegram/browse', { params }).then(response => response.data)
}

export function getTelegramUsage(): Promise<TelegramUsageResponse> {
  return api.get<TelegramUsageResponse>('/telegram/usage').then(response => response.data)
}

export function deleteTelegramItem(messageId: number): Promise<TelegramDeleteResponse> {
  return api.delete<TelegramDeleteResponse>(`/telegram/item/${messageId}`).then(response => response.data)
}

export function deleteTelegramGroup(mediaGroupId: string): Promise<TelegramDeleteResponse> {
  return api.delete<TelegramDeleteResponse>(`/telegram/group/${mediaGroupId}`).then(response => response.data)
}

export function deleteTelegramBatch(payload: TelegramBatchDeleteRequest): Promise<TelegramDeleteResponse> {
  return api.post<TelegramDeleteResponse>('/telegram/batch/delete', payload).then(response => response.data)
}

export function clearTelegramDrive(): Promise<TelegramDeleteResponse> {
  return api.delete<TelegramDeleteResponse>('/telegram/all').then(response => response.data)
}

export interface TelegramThumbnailStatus {
  running: boolean
  total: number
  cached: number
  pending: number
  percent: number
  current_message_id: number | null
}

export interface TelegramThumbnailStatusResponse {
  success: boolean
  data: TelegramThumbnailStatus
}

export interface TelegramThumbnailWarmupResponse {
  success: boolean
  message: string
  data: TelegramThumbnailStatus & {
    total_scanned?: number
    queued?: number
  }
}

export function getTelegramThumbnailStatus(): Promise<TelegramThumbnailStatusResponse> {
  return api.get<TelegramThumbnailStatusResponse>('/telegram/thumbnails/status').then(response => response.data)
}

export function warmupTelegramThumbnails(): Promise<TelegramThumbnailWarmupResponse> {
  return api.post<TelegramThumbnailWarmupResponse>('/telegram/thumbnails/warmup').then(response => response.data)
}

// ==================== 日志管理 API ====================

export interface LogFile {
  name: string
  path: string
  size: number
  modified: string
}

export interface LogFilesResponse {
  success: boolean
  files: LogFile[]
  error?: string
}

export interface LogContentResponse {
  success: boolean
  total: number
  lines: string[]
  error?: string
}

export function getLogFiles(): Promise<LogFilesResponse> {
  return api.get<LogFilesResponse>('/logs/files').then(r => r.data)
}

export function getLogContent(params: {
  file?: string
  tail?: number
  level?: string
  keyword?: string
}): Promise<LogContentResponse> {
  return api.get<LogContentResponse>('/logs', { params }).then(r => r.data)
}

export async function downloadLogFile(filename: string): Promise<void> {
  const response = await api.get<Blob>(`/logs/download/${encodeURIComponent(filename)}`, {
    responseType: 'blob',
  })
  const objectUrl = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

// ==================== 用户认证 API ====================

export interface ChangePasswordResponse {
  success: boolean
  message?: string
  error?: string
}

export function changePassword(oldPassword: string, newPassword: string): Promise<ChangePasswordResponse> {
  return api.post<ChangePasswordResponse>('/auth/password', {
    old_password: oldPassword,
    new_password: newPassword,
  }).then(r => r.data)
}

// ==================== 缓存治理与管理 API ====================

import type {
  CacheStatsData,
  CacheStatsResponse,
  CacheCleanRequest,
  CacheCleanResult,
  CacheCleanResponse,
  CachePolicy,
  CachePolicyResponse,
} from '@/types/api'

export type {
  CacheStatsData,
  CacheStatsResponse,
  CacheCleanRequest,
  CacheCleanResult,
  CacheCleanResponse,
  CachePolicy,
  CachePolicyResponse,
}

export function getCacheStats(): Promise<CacheStatsResponse> {
  return api.get<CacheStatsResponse>('/cache/stats').then(r => r.data)
}

export function cleanCache(payload: CacheCleanRequest): Promise<CacheCleanResponse> {
  return api.post<CacheCleanResponse>('/cache/clean', payload).then(r => r.data)
}

export function getCachePolicy(): Promise<CachePolicyResponse> {
  return api.get<CachePolicyResponse>('/cache/policy').then(r => r.data)
}

export function updateCachePolicy(policy: Partial<CachePolicy>): Promise<CachePolicyResponse> {
  return api.put<CachePolicyResponse>('/cache/policy', policy).then(r => r.data)
}

// ==================== Telegram 多 Bot 热插拔与 BotFather 自动创机 API ====================

import type {
  HotAddBotResult,
  HotAddBotsResponse,
  HotRemoveBotResponse,
  BotFatherAutoCreateRequest,
  BotFatherAutoCreateResponse,
  ProtocolAccount,
  ProtocolAccountsResponse,
  BatchImportAccountsRequest,
  BatchImportAccountsResult,
  BatchImportAccountsResponse,
  CheckProtocolAccountResponse,
  ImportTaskStatus,
  ImportTaskStatusResponse,
  ProtocolAccountDetail,
  ProtocolAccountDetailResponse,
  FetchProtocolAccountApiResponse,
  BatchFetchProtocolAccountApiResponse,
  UpdateProtocolAccountCredentialsRequest,
  ProtocolKeepaliveSummary,
  ProtocolKeepaliveResponse,
  KeepaliveConfig,
  KeepaliveConfigResponse,
} from '@/types/api'

export type {
  BatchFetchProtocolAccountApiResponse,
  ProtocolAccountDetail,
  ProtocolAccountDetailResponse,
  ProtocolKeepaliveSummary,
  ProtocolKeepaliveResponse,
  KeepaliveConfig,
  KeepaliveConfigResponse,
  HotAddBotResult,
  HotAddBotsResponse,
  HotRemoveBotResponse,
  BotFatherAutoCreateRequest,
  BotFatherAutoCreateResponse,
  ProtocolAccount,
  ProtocolAccountsResponse,
  BatchImportAccountsRequest,
  BatchImportAccountsResult,
  BatchImportAccountsResponse,
  CheckProtocolAccountResponse,
  ImportTaskStatus,
  ImportTaskStatusResponse,
}

export function getProtocolAccounts(): Promise<ProtocolAccountsResponse> {
  return api.get<ProtocolAccountsResponse>('/telegram/botfather/accounts').then(r => r.data)
}

export function importProtocolAccounts(
  data: FormData | BatchImportAccountsRequest
): Promise<BatchImportAccountsResponse> {
  if (data instanceof FormData) {
    return api.post<BatchImportAccountsResponse>('/telegram/botfather/accounts/import', data, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }).then(r => r.data)
  }
  return api.post<BatchImportAccountsResponse>('/telegram/botfather/accounts/import', data, {
    timeout: 300000,
  }).then(r => r.data)
}

export function getImportAccountTaskStatus(taskId: string): Promise<ImportTaskStatusResponse> {
  return api.get<ImportTaskStatusResponse>(`/telegram/botfather/accounts/import-task/${taskId}`).then(r => r.data)
}

export function deleteProtocolAccount(accountId: number | string, phone?: string): Promise<{ success: boolean; message?: string; error?: string }> {
  const query = phone ? `?phone=${encodeURIComponent(phone)}` : ""
  return api.delete<{ success: boolean; message?: string; error?: string }>(`/telegram/botfather/accounts/${accountId}${query}`).then(r => r.data)
}

export function checkProtocolAccount(accountId: number): Promise<CheckProtocolAccountResponse> {
  return api.post<CheckProtocolAccountResponse>(`/telegram/botfather/accounts/${accountId}/check`, {}, {
    timeout: 300000,
  }).then(r => r.data)
}

export function getProtocolAccountDetail(accountId: number, refresh = false): Promise<ProtocolAccountDetailResponse> {
  const query = refresh ? '?refresh=1' : ''
  return api.get<ProtocolAccountDetailResponse>(`/telegram/botfather/accounts/${accountId}/detail${query}`, {
    timeout: 120000,
  }).then(r => r.data)
}

export function fetchProtocolAccountApi(accountId: number, proxyApiUrl?: string): Promise<FetchProtocolAccountApiResponse> {
  return api.post<FetchProtocolAccountApiResponse>(`/telegram/botfather/accounts/${accountId}/fetch-api`, {
    proxy_api_url: proxyApiUrl,
  }, {
    timeout: 180000,
  }).then(r => r.data)
}

export function batchFetchProtocolAccountApi(data?: {
  account_ids?: number[]
  proxy_api_url?: string
  only_missing?: boolean
}): Promise<BatchFetchProtocolAccountApiResponse> {
  return api.post<BatchFetchProtocolAccountApiResponse>('/telegram/botfather/accounts/fetch-api-batch', data || {}, {
    timeout: 600000,
  }).then(r => r.data)
}

export function getApiProxyConfig(): Promise<{ success: boolean; data?: { proxy_api_url: string; default_url: string }; error?: string }> {
  return api.get('/telegram/botfather/proxy-config').then(r => r.data)
}

export function setApiProxyConfig(proxyApiUrl: string): Promise<{ success: boolean; data?: { proxy_api_url: string }; error?: string }> {
  return api.post('/telegram/botfather/proxy-config', { proxy_api_url: proxyApiUrl }).then(r => r.data)
}

export function updateProtocolAccountCredentials(accountId: number, data: UpdateProtocolAccountCredentialsRequest): Promise<ProtocolAccountDetailResponse> {
  return api.post<ProtocolAccountDetailResponse>(`/telegram/botfather/accounts/${accountId}/credentials`, data, {
    timeout: 30000,
  }).then(r => r.data)
}

export function keepaliveSingleProtocolAccount(accountId: number, checkBots = false): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>(`/telegram/botfather/accounts/${accountId}/keepalive`, {
    check_bots: checkBots,
  }, {
    timeout: 120000,
  }).then(r => r.data)
}

export function keepaliveAllProtocolAccounts(accountIds?: number[], checkBots = false): Promise<ProtocolKeepaliveResponse> {
  return api.post<ProtocolKeepaliveResponse>('/telegram/botfather/accounts/keepalive', {
    account_ids: accountIds,
    check_bots: checkBots,
  }, {
    timeout: 300000,
  }).then(r => r.data)
}

export function getKeepaliveConfig(): Promise<KeepaliveConfigResponse> {
  return api.get<KeepaliveConfigResponse>('/telegram/botfather/keepalive/config').then(r => r.data)
}

export function updateKeepaliveConfig(data: { enabled?: boolean; interval_hours?: number; trigger_now?: boolean }): Promise<KeepaliveConfigResponse> {
  return api.post<KeepaliveConfigResponse>('/telegram/botfather/keepalive/config', data).then(r => r.data)
}

export function hotAddBots(tokens: string[] | string): Promise<HotAddBotsResponse> {
  return api.post<HotAddBotsResponse>('/telegram/bots/hot-add', { tokens }, {
    timeout: 180000,
  }).then(r => r.data)
}

export function hotRemoveBot(index: number): Promise<HotRemoveBotResponse> {
  return api.delete<HotRemoveBotResponse>(`/telegram/bots/${index}`).then(r => r.data)
}

export function botfatherAutoCreate(formDataOrJson: FormData | BotFatherAutoCreateRequest): Promise<BotFatherAutoCreateResponse> {
  if (formDataOrJson instanceof FormData) {
    return api.post<BotFatherAutoCreateResponse>('/telegram/botfather/auto-create', formDataOrJson, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }).then(r => r.data)
  }
  return api.post<BotFatherAutoCreateResponse>('/telegram/botfather/auto-create', formDataOrJson, {
    timeout: 300000,
  }).then(r => r.data)
}


import type {
  BotFatherTaskStatus,
  BotFatherTaskStatusResponse,
  BotClusterLoadTestNode,
  BotClusterLoadTestResponse,
  BotReprobeResponse,
  BotBenchmarkResult,
  BotClusterBenchmarkResponse,
  BotSingleBenchmarkResponse,
  StreamAndDownloadBenchmarkResponse,
} from '@/types/api'

export type {
  BotFatherTaskStatus,
  BotFatherTaskStatusResponse,
  BotClusterLoadTestNode,
  BotClusterLoadTestResponse,
  BotReprobeResponse,
  BotBenchmarkResult,
  BotClusterBenchmarkResponse,
  BotSingleBenchmarkResponse,
  StreamAndDownloadBenchmarkResponse,
}

export function getBotFatherTaskStatus(): Promise<BotFatherTaskStatusResponse> {
  return api.get<BotFatherTaskStatusResponse>('/telegram/botfather/task-status').then(r => r.data)
}

export function startBotFatherTask(data: FormData | BotFatherAutoCreateRequest): Promise<BotFatherTaskStatusResponse> {
  if (data instanceof FormData) {
    return api.post<BotFatherTaskStatusResponse>('/telegram/botfather/tasks/start', data, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }).then(r => r.data)
  }
  return api.post<BotFatherTaskStatusResponse>('/telegram/botfather/tasks/start', data, {
    timeout: 300000,
  }).then(r => r.data)
}

export function stopBotFatherTask(): Promise<BotFatherTaskStatusResponse> {
  return api.post<BotFatherTaskStatusResponse>('/telegram/botfather/tasks/stop').then(r => r.data)
}

export function testBotClusterLoad(roundsPerBot: number = 10): Promise<BotClusterLoadTestResponse> {
  return api.post<BotClusterLoadTestResponse>('/telegram/bots/test-load', { rounds_per_bot: roundsPerBot }).then(r => r.data)
}

export function reprobeBots(): Promise<BotReprobeResponse> {
  return api.post<BotReprobeResponse>('/telegram/bots/reprobe').then(r => r.data)
}




export function benchmarkBot(index: number, testDownload: boolean = true): Promise<BotSingleBenchmarkResponse> {
  return api.post<BotSingleBenchmarkResponse>(`/telegram/bots/${index}/benchmark`, { test_download: testDownload }).then(r => r.data)
}

export function benchmarkAllBots(testDownload: boolean = true): Promise<BotClusterBenchmarkResponse> {
  return api.post<BotClusterBenchmarkResponse>('/telegram/bots/benchmark-all', { test_download: testDownload }).then(r => r.data)
}

export function benchmarkStreamAndDownload(params: {
  bot_index?: number | null
  sample_size_mb?: number
  message_id?: number | null
} = {}): Promise<StreamAndDownloadBenchmarkResponse> {
  return api.post<StreamAndDownloadBenchmarkResponse>('/telegram/benchmark/stream-and-download', params, {
    timeout: 300000,
  }).then(r => r.data)
}

export interface RebrandPreviewRequest {
  caption?: string
  filename?: string
  target_channel?: string
  signature?: string
  clean_filenames?: boolean
  custom_rules?: string
}

export interface RebrandPreviewResponse {
  success: boolean
  data?: {
    effective_channel: string
    cleaned_caption: string
    cleaned_filename: string
  }
  error?: string
}

export function previewRebrand(data: RebrandPreviewRequest): Promise<RebrandPreviewResponse> {
  return api.post<RebrandPreviewResponse>('/telegram/rebrand/preview', data).then(response => response.data)
}


export interface HarvesterStartRequest {
  links_text: string
  invite_link?: string
  account_id?: number | null
  rebrand_enabled?: boolean
}

export interface HarvesterTaskStatus {
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  task_id: string
  total_messages: number
  current_index: number
  success_count: number
  failed_count: number
  skipped_count: number
  current_mode: 'idle' | 'fast_copy' | 'restricted_relay'
  current_file: string
  speed_text: string
  logs: string[]
  results: Array<{
    name: string
    full_link: string
    short_link: string
    msg_id: number
  }>
  account_phone: string | null
  error: string | null
}

export interface HarvesterStartResponse {
  success: boolean
  message?: string
  task_id?: string
  total_messages?: number
  error?: string
}

export interface HarvesterStatusResponse {
  success: boolean
  data?: HarvesterTaskStatus
  error?: string
}

export interface HarvesterCancelResponse {
  success: boolean
  message?: string
  error?: string
}

export function startHarvesterTask(data: HarvesterStartRequest): Promise<HarvesterStartResponse> {
  return api.post<HarvesterStartResponse>('/telegram/harvester/start', data).then(r => r.data)
}

export function getHarvesterStatus(): Promise<HarvesterStatusResponse> {
  return api.get<HarvesterStatusResponse>('/telegram/harvester/status').then(r => r.data)
}

export function cancelHarvesterTask(): Promise<HarvesterCancelResponse> {
  return api.post<HarvesterCancelResponse>('/telegram/harvester/cancel').then(r => r.data)
}
