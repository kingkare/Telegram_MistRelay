export interface ServerStatus {
  server_status: string
  uptime: string
  telegram_bot: string
  connected_bots: number
  loads: Record<string, number>
  version: string
}

export interface UploadRecord {
  id: number
  upload_target: string
  status: 'pending' | 'waiting_download' | 'uploading' | 'completed' | 'failed' | 'cancelled' | 'paused'
  total_size?: number
  uploaded_size?: number
  upload_speed?: number
  failure_reason?: string
  error_message?: string
  created_at?: string
  started_at?: string
  completed_at?: string
  cleaned_at?: string
  updated_at?: string
  file_name?: string
  remote_path?: string
  download_id?: number
}

export interface DownloadRecord {
  id: number
  gid?: string
  source_url?: string
  status: 'pending' | 'downloading' | 'completed' | 'failed' | 'skipped' | 'paused' | 'waiting'
  total_length?: number
  completed_length?: number
  download_speed?: number
  error_message?: string
  local_path?: string
  remote_path?: string
  upload_status?: string
  updated_at?: string
  created_at: string
  started_at?: string
  completed_at?: string
  file_name?: string
  mime_type?: string
  file_size?: number
  chat_id?: number
  message_id?: number
  media_group_id?: string
  caption?: string
  message_date?: string
  uploads?: UploadRecord[]
}

export interface DownloadGroup {
  group_key: string
  group_type: 'media_group' | 'message' | 'single'
  chat_id?: number
  message_id?: number
  media_group_id?: string
  caption?: string
  message_date?: string
  created_at: string
  stats: {
    total_files: number
    completed: number
    downloading: number
    failed: number
    pending: number
    skipped?: number
    total_size: number
    completed_size: number
  }
  downloads: DownloadRecord[]
}

export interface DownloadsResponse {
  success: boolean
  limit: number
  count: number
  group_count?: number
  grouped?: boolean
  data: DownloadRecord[] | DownloadGroup[]
}

export interface DockerStatus {
  success: boolean
  in_docker?: boolean
  container_name?: string
  status?: string
  image?: string
  created?: string
  error?: string
}

export interface DockerRestartResponse {
  success: boolean
  message?: string
  container_name?: string
  error?: string
}

export interface DockerLogsResponse {
  success: boolean
  logs?: string
  lines?: number
  source?: 'docker' | 'application'
  error?: string
}

export interface ConfigResponse {
  success: boolean
  data?: Record<string, any>
  redacted_keys?: string[]
  secret_counts?: Record<string, number>
  offline_only_keys?: string[]
  error?: string
}

export interface ConfigUpdateResponse {
  success: boolean
  message?: string
  updated_count?: number
  needs_restart?: boolean
  error?: string
}

export interface SystemResources {
  cpu: {
    percent: number
  }
  memory: {
    percent: number
    total: number
    used: number
    available: number
  }
  disk: {
    percent: number
    total: number
    used: number
    free: number
  }
}

export interface SystemResourcesResponse {
  success: boolean
  data?: SystemResources
  error?: string
}

export type TelegramDriveEntryType = 'file' | 'folder'

export interface TelegramDriveBase {
  entry_type?: TelegramDriveEntryType
  file_name?: string
  mime_type?: string
  file_size?: number
  duration?: number
  width?: number
  height?: number
  caption?: string
  message_date?: string
  media_group_id?: string
  supports_streaming?: boolean
  thumbnail_url?: string
  stream_url?: string
  hash?: string
}

export interface TelegramDriveFile extends TelegramDriveBase {
  entry_type: 'file'
  file_unique_id: string
  chat_id: number
  message_id: number
  download_file_name?: string
}

export interface TelegramDriveFolder extends TelegramDriveBase {
  entry_type: 'folder'
  media_group_id: string
  file_unique_id?: string
  chat_id?: number
  message_id?: number
  item_count: number
  total_size?: number
  group_mime_types?: string[]
}

export type TelegramDriveItem = TelegramDriveFile | TelegramDriveFolder

export interface TelegramBrowseParams {
  page?: number
  page_size?: number
  search?: string
  type?: string
  sort_by?: string
  sort_desc?: boolean
  media_group_id?: string
}

export interface TelegramBrowseResponse {
  success: boolean
  items: TelegramDriveItem[]
  total: number
  page: number
  page_size: number
  error?: string
}

export interface TelegramUsageStats {
  total_count: number
  total_size: number
  videos: number
  images: number
  audios: number
  documents: number
}

export interface TelegramUsageResponse {
  success: boolean
  data?: TelegramUsageStats
  error?: string
}

export interface TelegramDeleteResponse {
  success: boolean
  message?: string
  data?: Record<string, any>
  error?: string
}

export function isTelegramDriveFile(
  item?: TelegramDriveItem | null,
): item is TelegramDriveFile {
  return item?.entry_type === 'file'
}

export function isTelegramDriveFolder(
  item?: TelegramDriveItem | null,
): item is TelegramDriveFolder {
  return item?.entry_type === 'folder'
}
