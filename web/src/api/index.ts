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
  UploadRecord,
  EdgeNode,
  EdgeNodesListResponse,
  EdgeNodeTokenInfo,
  EdgeBenchmarkData,
  EdgeDcResult,
  EdgeSpeedResult,
  EdgeDiagnosticsResult,
  EdgeBandwidthResult,
  TelegramUploadInitRequest,
  TelegramUploadInitResponse,
  TelegramUploadChunkResponse,
  TelegramUploadFinishResponse,
  TelegramUploadStatusResponse,
  TelegramUploadCancelResponse
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

export interface Aria2TestResponse {
  success: boolean
  data?: {
    version: string
    download_dir: string
    num_active: number
    num_waiting: number
    num_stopped: number
    download_speed: number
    max_concurrent: number
  }
  error?: string
}

export function testAria2Rpc(): Promise<Aria2TestResponse> {
  return api.post<Aria2TestResponse>('/aria2/test').then(response => response.data)
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

export function getTelegramUsage(params?: { chat_id?: number | string }): Promise<TelegramUsageResponse> {
  return api.get<TelegramUsageResponse>('/telegram/usage', { params }).then(response => response.data)
}

export function deleteTelegramItem(messageId: number, params?: { chat_id?: number | string }): Promise<TelegramDeleteResponse> {
  return api.delete<TelegramDeleteResponse>(`/telegram/item/${messageId}`, { params }).then(response => response.data)
}

export function deleteTelegramGroup(mediaGroupId: string, params?: { chat_id?: number | string }): Promise<TelegramDeleteResponse> {
  return api.delete<TelegramDeleteResponse>(`/telegram/group/${mediaGroupId}`, { params }).then(response => response.data)
}

export function deleteTelegramBatch(payload: TelegramBatchDeleteRequest, params?: { chat_id?: number | string }): Promise<TelegramDeleteResponse> {
  return api.post<TelegramDeleteResponse>('/telegram/batch/delete', payload, { params }).then(response => response.data)
}

// ==================== Telegram 用户本地文件分片上传 API ====================

export function initTelegramUpload(data: TelegramUploadInitRequest): Promise<TelegramUploadInitResponse> {
  return api.post<TelegramUploadInitResponse>('/telegram/upload/init', data).then(r => r.data)
}

export function uploadTelegramChunk(
  uploadId: string,
  chunkIndex: number,
  chunk: Blob,
  onUploadProgress?: (progressEvent: any) => void
): Promise<TelegramUploadChunkResponse> {
  const formData = new FormData()
  formData.append('upload_id', uploadId)
  formData.append('chunk_index', String(chunkIndex))
  formData.append('chunk', chunk, `chunk_${chunkIndex}`)

  return api.post<TelegramUploadChunkResponse>('/telegram/upload/chunk', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress,
    timeout: 120000,
  }).then(r => r.data)
}

export function finishTelegramUpload(uploadId: string): Promise<TelegramUploadFinishResponse> {
  return api.post<TelegramUploadFinishResponse>('/telegram/upload/finish', { upload_id: uploadId }, {
    timeout: 60000,
  }).then(r => r.data)
}

export function getTelegramUploadStatus(uploadId: string): Promise<TelegramUploadStatusResponse> {
  return api.get<TelegramUploadStatusResponse>(`/telegram/upload/status/${uploadId}`).then(r => r.data)
}

export function cancelTelegramUpload(uploadId: string): Promise<TelegramUploadCancelResponse> {
  return api.post<TelegramUploadCancelResponse>('/telegram/upload/cancel', { upload_id: uploadId }).then(r => r.data)
}

export function clearTelegramDrive(params?: { chat_id?: number | string }): Promise<TelegramDeleteResponse> {
  return api.delete<TelegramDeleteResponse>('/telegram/all', { params }).then(response => response.data)
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
  ProtocolAccountLoginCodeData,
  ProtocolAccountLoginCodeResponse,
  ProtocolAccount2FAStatusData,
  ProtocolAccount2FAStatusResponse,
} from '@/types/api'

export type {
  BatchFetchProtocolAccountApiResponse,
  ProtocolAccountDetail,
  ProtocolAccountDetailResponse,
  ProtocolKeepaliveSummary,
  ProtocolKeepaliveResponse,
  KeepaliveConfig,
  KeepaliveConfigResponse,
  ProtocolAccountLoginCodeData,
  ProtocolAccountLoginCodeResponse,
  ProtocolAccount2FAStatusData,
  ProtocolAccount2FAStatusResponse,
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
  return api.get<ProtocolAccountsResponse>(`/telegram/botfather/accounts?_t=${Date.now()}`).then(r => r.data)
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
  const query = refresh ? `?refresh=1&_t=${Date.now()}` : `?_t=${Date.now()}`
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

export interface ProtocolSyncResponse {
  success: boolean
  data?: ProtocolAccount[]
  summary?: {
    total: number
    success_count: number
    failed_count: number
    avg_ping_ms?: number
  }
  error?: string
}

export function syncAllProtocolAccounts(accountIds?: number[], checkBots = true): Promise<ProtocolSyncResponse> {
  return api.post<ProtocolSyncResponse>('/telegram/botfather/accounts/sync', {
    account_ids: accountIds,
    check_bots: checkBots,
  }, {
    timeout: 300000,
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


export function fetchProtocolAccountLoginCode(accountId: number, limit = 10): Promise<ProtocolAccountLoginCodeResponse> {
  return api.get<ProtocolAccountLoginCodeResponse>(`/telegram/botfather/accounts/${accountId}/login-code?limit=${limit}&_t=${Date.now()}`, {
    timeout: 30000,
  }).then(r => r.data)
}

export function getProtocolAccount2FA(accountId: number): Promise<ProtocolAccount2FAStatusResponse> {
  return api.get<ProtocolAccount2FAStatusResponse>(`/telegram/botfather/accounts/${accountId}/2fa?_t=${Date.now()}`, {
    timeout: 30000,
  }).then(r => r.data)
}

export function updateProtocolAccount2FA(accountId: number, data: {
  new_password: string
  current_password?: string
  hint?: string
}): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>(`/telegram/botfather/accounts/${accountId}/2fa`, data, {
    timeout: 60000,
  }).then(r => r.data)
}

export function terminateProtocolAccountOtherSessions(accountId: number): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>(`/telegram/botfather/accounts/${accountId}/terminate-sessions`, {}, {
    timeout: 60000,
  }).then(r => r.data)
}

export function cancelProtocolAccountPasswordReset(accountId: number): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>(`/telegram/botfather/accounts/${accountId}/cancel-reset`, {}, {
    timeout: 30000,
  }).then(r => r.data)
}

export function bindProtocolAccountLocalOtp(accountId: number, replaceCodeUrl = true): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>(`/telegram/botfather/accounts/${accountId}/bind-local-otp`, {
    replace_code_url: replaceCodeUrl,
  }, {
    timeout: 30000,
  }).then(r => r.data)
}

export function takeoverProtocolAccount(accountId: number, data?: {
  new_password?: string
  hint?: string
}): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>(`/telegram/botfather/accounts/${accountId}/takeover`, data || {}, {
    timeout: 90000,
  }).then(r => r.data)
}

export function batchTakeoverProtocolAccounts(data?: {
  account_ids?: number[]
  only_unsecured?: boolean
  force_all?: boolean
}): Promise<{ success: boolean; data?: any; error?: string }> {
  return api.post<{ success: boolean; data?: any; error?: string }>('/telegram/botfather/accounts/takeover-batch', data || {}, {
    timeout: 300000,
  }).then(r => r.data)
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
  return api.get<BotFatherTaskStatusResponse>(`/telegram/botfather/task-status?_t=${Date.now()}`).then(r => r.data)
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




export function benchmarkBot(index: number, testDownload: boolean = false): Promise<BotSingleBenchmarkResponse> {
  return api.post<BotSingleBenchmarkResponse>(`/telegram/bots/${index}/benchmark`, { test_download: testDownload }).then(r => r.data)
}

export function benchmarkAllBots(testDownload: boolean = false): Promise<BotClusterBenchmarkResponse> {
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


// ==================== 多租户用户与专属频道管理 API ====================

export interface UserRecord {
  id: number
  username: string
  role: 'admin' | 'user'
  tg_user_id?: number | null
  tg_username?: string | null
  tg_first_name?: string | null
  dc_id?: number | null
  bin_channel_id?: number | null
  bin_channel_username?: string | null
  creator_account_id?: number | null
  creator_phone?: string | null
  creator_account_status?: string | null
  creator_status?: 'healthy' | 'warning' | 'untracked' | 'none'
  media_count?: number
  total_size?: number
  video_count?: number
  image_count?: number
  download_count?: number
  active_sessions?: number
  created_at?: string
  updated_at?: string
}

export interface UsersSummary {
  total_users: number
  dedicated_tenants: number
  total_files: number
  total_size: number
  pending_codes: number
  dc_distribution: Record<string, number>
}

export interface TgRegisterCodeItem {
  code: string
  tg_user_id: number
  tg_username?: string | null
  tg_first_name?: string | null
  detected_dc_id?: number | null
  created_at: string
  expires_at: string
  used: number
}

export interface UsersListResponse {
  success: boolean
  users: UserRecord[]
  summary: UsersSummary
  recent_codes: TgRegisterCodeItem[]
  error?: string
}

export function getUsersList(): Promise<UsersListResponse> {
  return api.get<UsersListResponse>('/users').then(r => r.data)
}

export function createAdminUser(payload: {
  username: string
  password?: string
  role?: string
  tg_user_id?: number | null
  tg_username?: string
  tg_first_name?: string
  target_dc_id?: number
  auto_provision_channel?: boolean
}): Promise<{ success: boolean; message?: string; user?: UserRecord; generated_password?: string; error?: string }> {
  return api.post('/users', payload).then(r => r.data)
}

export function provisionUserChannel(userId: number, targetDcId?: number): Promise<{
  success: boolean
  message?: string
  user?: UserRecord
  channel?: Record<string, any>
  error?: string
}> {
  return api.post(`/users/${userId}/provision-channel`, { target_dc_id: targetDcId }).then(r => r.data)
}

export function updateAdminUser(userId: number, payload: Partial<UserRecord>): Promise<{
  success: boolean
  message?: string
  user?: UserRecord
  error?: string
}> {
  return api.put(`/users/${userId}`, payload).then(r => r.data)
}

export function resetUserPassword(userId: number, newPassword?: string): Promise<{
  success: boolean
  message?: string
  new_password?: string
  revoked_sessions?: number
  error?: string
}> {
  return api.post(`/users/${userId}/reset-password`, { new_password: newPassword || 'auto' }).then(r => r.data)
}

export function deleteAdminUser(userId: number, cleanupRecords: boolean = false): Promise<{
  success: boolean
  message?: string
  data?: Record<string, any>
  error?: string
}> {
  return api.delete(`/users/${userId}`, { params: { cleanup_records: cleanupRecords ? 1 : 0 } }).then(r => r.data)
}

// ==================== 全量数据灾备与租户专属频道无损平移 API ====================

export interface BackupItem {
  filename: string
  size: number
  size_formatted: string
  created_at: string
  type: 'archive' | 'sqlite_raw'
  remark?: string
  is_safety_snapshot?: boolean
  is_protected?: boolean
  manifest?: {
    version?: string
    created_at?: string
    remark?: string
    db_tables?: Record<string, number>
    sessions_count?: number
    files?: Array<{ name: string; size: number; sha256: string }>
  } | null
}

export interface BackupSchedule {
  enabled: boolean
  interval_hours: number
  max_keep: number
  last_run?: string
}

export interface SystemBackupsResponse {
  success: boolean
  backups: BackupItem[]
  schedule: BackupSchedule
  backup_dir?: string
  error?: string
}

export interface ChannelMigrationLogItem {
  time: string
  level: 'info' | 'warning' | 'error' | 'success'
  msg: string
}

export interface ChannelMigrationStatus {
  task_id: string
  user_id: number
  username: string
  source_channel_id: number
  source_channel_username?: string | null
  target_channel_id?: number | null
  target_channel_username?: string | null
  target_dc_id: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_files: number
  migrated_files: number
  skipped_files: number
  failed_files: number
  progress_percent: number
  current_file_name?: string
  error_message?: string | null
  started_at: string
  finished_at?: string | null
  logs: ChannelMigrationLogItem[]
}

export function getSystemBackups(): Promise<SystemBackupsResponse> {
  return api.get<SystemBackupsResponse>('/system/backups').then(r => r.data)
}

export function createSystemBackup(remark: string = ''): Promise<{
  success: boolean
  message?: string
  data?: BackupItem
  error?: string
}> {
  return api.post('/system/backups/create', { remark }).then(r => r.data)
}

export async function downloadSystemBackup(filename: string): Promise<void> {
  const response = await api.get(`/system/backups/${encodeURIComponent(filename)}/download`, {
    responseType: 'blob',
  })
  const blob = new Blob([response.data], { type: 'application/gzip' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

export function uploadSystemBackup(file: File): Promise<{
  success: boolean
  message?: string
  data?: { filename: string; size: number; size_formatted: string }
  error?: string
}> {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/system/backups/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export function restoreSystemBackup(filename: string, mode: string = "union"): Promise<{
  success: boolean
  message?: string
  data?: Record<string, any>
  error?: string
}> {
  return api.post(`/system/backups/${encodeURIComponent(filename)}/restore`, { mode }).then(r => r.data)
}

export function exportTenantBackup(userId: number) {
  return api.get(`/system/tenants/${userId}/export`, { responseType: "blob" })
}

export function exportMyTenantBackup() {
  return api.get("/telegram/tenant/backup/export", { responseType: "blob" })
}

export function healOrphanedMedia(): Promise<{
  success: boolean
  message?: string
  data?: {
    healed: Array<{
      user_id: number
      username: string
      channel_id: number
      files_count: number
      total_size: number
    }>
    total_files_restored: number
  }
  error?: string
}> {
  return api.post("/system/tenants/heal-orphans").then(r => r.data)
}

export function deleteSystemBackup(filename: string): Promise<{
  success: boolean
  message?: string
  error?: string
}> {
  return api.delete(`/system/backups/${encodeURIComponent(filename)}`).then(r => r.data)
}

export function getBackupSchedule(): Promise<{ success: boolean; schedule: BackupSchedule; error?: string }> {
  return api.get('/system/backups/schedule').then(r => r.data)
}

export function setBackupSchedule(payload: {
  enabled: boolean
  interval_hours: number
  max_keep: number
}): Promise<{ success: boolean; message?: string; schedule: BackupSchedule; error?: string }> {
  return api.post('/system/backups/schedule', payload).then(r => r.data)
}

export function startUserChannelMigration(
  userId: number,
  payload: { target_dc_id?: number; custom_target_channel_id?: number | null }
): Promise<{
  success: boolean
  message?: string
  data?: ChannelMigrationStatus
  error?: string
}> {
  return api.post(`/users/${userId}/migrate-channel/start`, payload).then(r => r.data)
}

export function getUserChannelMigrationStatus(userId: number): Promise<{
  success: boolean
  status: string
  data?: ChannelMigrationStatus | null
  error?: string
}> {
  return api.get(`/users/${userId}/migrate-channel/status`).then(r => r.data)
}

export function cancelUserChannelMigration(userId: number): Promise<{
  success: boolean
  message?: string
  error?: string
}> {
  return api.post(`/users/${userId}/migrate-channel/cancel`).then(r => r.data)
}


// ============================================================================
// 多租户边缘推流分流节点 (Edge Streaming Worker) API
// ============================================================================

export function getEdgeNodes(tenantId?: number): Promise<EdgeNodesListResponse> {
  const params = tenantId ? { tenant_id: tenantId } : {}
  return api.get("/edge/nodes", { params }).then(r => r.data)
}

export function createEdgeNode(data: {
  node_name: string
  ip?: string
  port?: number
  ssh_host?: string
  ssh_port?: number
  ssh_user?: string
  ssh_password?: string
  domain?: string
  use_ssl?: boolean
  allow_shared_pool?: boolean
  allow_bot_pool?: boolean
  target_dc_id?: number | null
  auto_deploy?: boolean
  clear_password_on_success?: boolean
  tenant_id?: number
  master_url?: string
}): Promise<{ success: boolean; node: EdgeNode; error?: string }> {
  return api.post("/edge/nodes", data).then(r => r.data)
}

export function updateEdgeNode(
  id: number,
  data: Partial<EdgeNode> & { ssh_password?: string }
): Promise<{ success: boolean; node: EdgeNode; error?: string }> {
  return api.put(`/edge/nodes/${id}`, data).then(r => r.data)
}

export function deleteEdgeNode(id: number): Promise<{ success: boolean; message?: string; error?: string }> {
  return api.delete(`/edge/nodes/${id}`).then(r => r.data)
}

export function triggerEdgeNodeDeploy(
  id: number,
  payload?: {
    clear_password_on_success?: boolean
    master_url?: string
    ssh_host?: string
    ssh_port?: number
    ssh_user?: string
    ssh_password?: string
  }
): Promise<{ success: boolean; message?: string; node?: EdgeNode; error?: string }> {
  return api.post(`/edge/nodes/${id}/ssh-deploy`, payload || {}).then(r => r.data)
}

export function getEdgeNodeDeployLogs(id: number): Promise<{
  success: boolean
  node_id: number
  status: string
  deploy_log: string
  has_ssh_password?: boolean
  error?: string
}> {
  return api.get(`/edge/nodes/${id}/deploy-logs`).then(r => r.data)
}

export function clearEdgeNodePassword(id: number): Promise<{ success: boolean; message?: string; node?: EdgeNode; error?: string }> {
  return api.post(`/edge/nodes/${id}/clear-ssh-password`).then(r => r.data)
}

export function testEdgeNodeHealth(id: number): Promise<{
  success: boolean
  result: {
    online: boolean
    latency_ms?: number
    url?: string
    worker_data?: any
    error?: string
  }
  node?: EdgeNode
  error?: string
}> {
  return api.post(`/edge/nodes/${id}/test`).then(r => r.data)
}

export function generateEdgeNodeToken(data: {
  node_name: string
  domain?: string
  port?: number
  use_ssl?: boolean
  allow_shared_pool?: boolean
  allow_bot_pool?: boolean
  target_dc_id?: number | null
  expires_minutes?: number
  tenant_id?: number
}): Promise<{
  success: boolean
  token: string
  token_data: EdgeNodeTokenInfo
  install_url: string
  command: string
  error?: string
}> {
  return api.post("/edge/nodes/generate-token", data).then(r => r.data)
}

export function getEdgeTokenStatus(token: string): Promise<{
  success: boolean
  token_info: EdgeNodeTokenInfo
  node?: EdgeNode | null
  error?: string
}> {
  return api.get(`/edge/tokens/${encodeURIComponent(token)}/status`).then(r => r.data)
}


export function runEdgeDcsBenchmark(id: number): Promise<{
  success: boolean
  fastest_dc?: { id: number; name: string; avg_rtt_ms: number; rating: string; rating_label: string }
  home_dc?: number
  bot_username?: string
  dcs?: EdgeDcResult[]
  error?: string
}> {
  return api.post(`/edge/nodes/${id}/benchmark/dcs`).then(r => r.data)
}

export function runEdgeTgSpeedBenchmark(
  id: number,
  data?: { sample_size_mb?: number; chat_id?: number; message_id?: number }
): Promise<EdgeSpeedResult & { success: boolean; error?: string }> {
  return api.post(`/edge/nodes/${id}/benchmark/tg-speed`, data || {}).then(r => r.data)
}

export function runEdgeDiagnostics(id: number): Promise<EdgeDiagnosticsResult & { error?: string }> {
  return api.post(`/edge/nodes/${id}/diagnostics`).then(r => r.data)
}

export function runEdgeRelayStreamBenchmark(
  id: number,
  data?: { sample_size_mb?: number }
): Promise<EdgeSpeedResult & { success: boolean; error?: string }> {
  return api.post(`/edge/nodes/${id}/benchmark/relay-stream`, data || {}).then(r => r.data)
}

export function runEdgeBandwidthBenchmark(id: number): Promise<EdgeBandwidthResult & { success: boolean; error?: string }> {
  return api.post(`/edge/nodes/${id}/benchmark/bandwidth`).then(r => r.data)
}

export function runEdgeFullBenchmark(
  id: number,
  data?: { sample_size_mb?: number }
): Promise<{
  success: boolean
  benchmark_data: EdgeBenchmarkData
  node: EdgeNode
  error?: string
}> {
  return api.post(`/edge/nodes/${id}/benchmark/full`, data || {}).then(r => r.data)
}

export function upgradeEdgeNodeWorker(id: number): Promise<{
  success: boolean
  method?: "ota" | "ssh"
  message?: string
  node?: EdgeNode
  error?: string
}> {
  return api.post(`/edge/nodes/${id}/upgrade`).then(r => r.data)
}

export interface ClusterBotInfo {
  bot_index: number
  token: string
  token_mask: string
  prefix: string
  username: string
  dc_id: number
  is_main: boolean
  assigned_nodes: Array<{ id: number; name: string }>
  assigned_count: number
}

export function getEdgeBotsPool(params?: { search?: string; dc_id?: number }): Promise<{
  success: boolean
  bots: ClusterBotInfo[]
  total: number
  error?: string
}> {
  return api.get('/edge/bots-pool', { params }).then(r => r.data)
}

export function reassignEdgeNodeBot(
  id: number,
  data?: {
    mode?: 'auto' | 'manual'
    target_dc_id?: number | null
    assigned_bot_token?: string
    allow_bot_pool?: boolean
    trigger_ota?: boolean
    bot_count?: number | null
    auto_match_bandwidth?: boolean
  }
): Promise<{
  success: boolean
  message: string
  allocation?: any
  node?: EdgeNode
  ota_triggered?: boolean
  ota_result?: any
  error?: string
}> {
  return api.post(`/edge/nodes/${id}/reassign-bot`, data || {}).then(r => r.data)
}


export interface AvailableEdgeNode {
  id: number
  node_name: string
  domain: string
  ip: string
  port: number
  use_ssl: boolean
  status: string
  is_dedicated: boolean
  allow_shared_pool: boolean
  active_streams: number
  fastest_dc?: {
    id: number
    name: string
    avg_rtt_ms: number
    rating: string
    rating_label: string
  }
  dcs?: Array<{
    dc_id: number
    name: string
    avg_rtt_ms: number
    reachable: boolean
  }>
  ping_url: string
  stream_base_url: string
  rtt_ms?: number
}

export function getAvailableEdgeNodes(): Promise<{ success: boolean; nodes: AvailableEdgeNode[]; error?: string }> {
  return api.get("/edge/available-nodes").then(r => r.data)
}

export function reportClientLatency(latencies: Array<{ node_id: number; rtt_ms: number }>): Promise<{ success: boolean; recorded: number; client_ip: string }> {
  return api.post("/edge/client-latency", { latencies }).then(r => r.data)
}

export interface ResolveStreamUrlParams {
  message_id: number
  hash?: string
  preferred_node?: string | number
  download?: boolean
}

export interface ResolveStreamUrlResponse {
  success: boolean
  url: string
  node_id?: number | null
  node_name?: string
  is_edge: boolean
  error?: string
}

export function resolveEdgeStreamUrl(params: ResolveStreamUrlParams): Promise<ResolveStreamUrlResponse> {
  return api.post<ResolveStreamUrlResponse>("/edge/resolve-stream-url", params).then(r => r.data)
}

// ==========================================
// Telegram AI 客服相关接口与类型
// ==========================================

export interface CustomerServiceBotInfo {
  id?: number | null
  username?: string
  first_name?: string
  dc_id?: number | null
  is_connected?: boolean
}

export interface CustomerServiceTargetChat {
  checked: boolean
  target: string
  chat_id?: number
  chat_title?: string
  chat_username?: string
  member_status?: string
  is_admin?: boolean
  error?: string
  privileges?: Record<string, boolean>
}

export interface CustomerServiceConfig {
  enabled: boolean
  bot_token: string
  bot_username: string
  target_chat: string
  group_trigger_mode: string
  private_enabled: boolean
  api_base: string
  api_key: string
  model: string
  system_prompt: string
  temperature: number
  max_tokens: number
}

export interface CustomerServiceKnowledgeContext {
  official_website: string
  main_stream_bot: string
  cs_bot: string
  official_group: string
  official_channel: string
  admin_contact: string
  runtime_status_summary?: string
}

export interface CustomerServiceRuntimeStatus {
  overall_status: string
  streaming_engine: string
  supported_protocols: string
  edge_nodes: {
    total: number
    online: number
    health_rate_pct: number
    status_text: string
  }
  aria2_engine: {
    load_level: string
    engine_status: string
  }
  specs: {
    max_file_size: string
    supported_formats: string
    supported_offline_types: string
  }
  updated_at: number
}

export interface CustomerServiceStatusResponse {
  success: boolean
  running: boolean
  bot_info?: CustomerServiceBotInfo | null
  target_chat?: CustomerServiceTargetChat
  admin_link?: string
  config: CustomerServiceConfig
  knowledge_context?: CustomerServiceKnowledgeContext
  resolved_system_prompt?: string
  stats?: {
    active_history_chats: number
    total_history_turns: number
  }
  runtime_status?: CustomerServiceRuntimeStatus
  error?: string
}

export interface CustomerServiceActionResponse {
  success: boolean
  message: string
  running: boolean
  bot_info?: CustomerServiceBotInfo | null
  target_chat?: CustomerServiceTargetChat
  admin_link?: string
  config?: CustomerServiceConfig
  error?: string
}

export interface CustomerServiceTestChatPayload {
  query: string
  system_prompt?: string
  model?: string
  api_base?: string
  api_key?: string
  temperature?: number
  max_tokens?: number
}

export interface CustomerServiceTestChatResponse {
  success: boolean
  reply?: string
  latency_ms?: number
  model?: string
  error?: string
}

export interface CustomerServiceAutoMintPayload {
  display_name?: string
  target_chat?: string
  account_id?: number
}

export interface CustomerServiceAutoMintResponse {
  success: boolean
  bot_username?: string
  bot_token?: string
  target_chat?: string
  chat_id?: number
  chat_title?: string
  joined?: boolean
  admin_link?: string
  error?: string
}

export function getCustomerServiceStatus(): Promise<CustomerServiceStatusResponse> {
  return api.get<CustomerServiceStatusResponse>('/telegram/customer-service/status').then(r => r.data)
}

export function updateCustomerServiceConfig(config: Partial<CustomerServiceConfig>): Promise<{ success: boolean; message: string; running: boolean; error?: string }> {
  return api.post('/telegram/customer-service/config', config).then(r => r.data)
}

export function performCustomerServiceAction(action: 'start' | 'stop' | 'restart' | 'clear_history'): Promise<CustomerServiceActionResponse> {
  return api.post<CustomerServiceActionResponse>('/telegram/customer-service/actions', { action }).then(r => r.data)
}

export function testCustomerServiceChat(payload: CustomerServiceTestChatPayload): Promise<CustomerServiceTestChatResponse> {
  return api.post<CustomerServiceTestChatResponse>('/telegram/customer-service/test-chat', payload).then(r => r.data)
}

export function autoMintCustomerServiceBot(payload?: CustomerServiceAutoMintPayload): Promise<CustomerServiceAutoMintResponse> {
  return api.post<CustomerServiceAutoMintResponse>('/telegram/customer-service/auto-mint', payload || {}).then(r => r.data)
}
