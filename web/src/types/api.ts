export interface BotDetail {
  index: number
  name: string
  username: string
  mode: 'primary_admin' | 'direct_admin' | 'no_join_resolved' | 'unreachable' | string
  home_dc?: number | null
  warm_dcs?: number[]
  can_read: boolean
  can_write: boolean
  active_requests: number
  invite_url?: string
}

export interface DcPartitionEntry {
  dc_id: number
  label: string
  home_bots: number[]
  warm_bots: number[]
  files_count: number
  requests_count: number
}

export interface ChannelInfo {
  channel_id: number | null
  channel_type: 'public' | 'private'
  public_handle: string
  no_join_balancing_active: boolean
  accessible_bots: number
  write_bots: number
}

export interface ServerStatus {
  server_status: string
  uptime: string
  telegram_bot: string
  connected_bots: number
  loads: Record<string, number>
  workloads?: Record<string, number>
  bot_metrics?: Record<string, any>
  bot_details?: BotDetail[]
  channel_info?: ChannelInfo
  dc_partitions?: Record<string, DcPartitionEntry>
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
  status_source?: 'docker' | 'application'
  control_enabled?: boolean
  control_message?: string
  application_version?: string
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
  dc_id?: number | null
  dc_label?: string | null
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

export interface TelegramBatchDeleteRequest {
  message_ids: number[]
  media_group_ids: string[]
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

// ==================== 缓存治理与管理 API 类型 ====================

export interface DiskStats {
  total_bytes: number
  used_bytes: number
  free_bytes: number
  total_gb: number
  used_gb: number
  free_gb: number
  percent: number
  path: string
}

export interface ThumbnailSubSource {
  total_files: number
  total_bytes: number
  total_size_mb: number
}

export interface ThumbnailStats {
  total_files: number
  total_bytes: number
  total_size_mb: number
  cache_dir: string
  sub_sources: Record<string, ThumbnailSubSource>
  expired_files: number
  expired_bytes: number
  expired_size_mb: number
  retention_days: number
}

export interface DownloadsStats {
  root: string
  total_files: number
  total_bytes: number
  total_size_mb: number
  protected_files: number
  cleanable_files: number
  cleanable_bytes: number
  cleanable_size_mb: number
  recent_files: number
  retention_hours: number
}

export interface RcloneStats {
  root: string
  total_files: number
  total_bytes: number
  total_size_mb: number
}

export interface MemoryStats {
  thumbnail_lru: {
    hits?: number
    misses?: number
    maxsize?: number
    currsize?: number
  }
  stream_sessions: number
  config_cache_entries: number
}

export interface CacheStatsData {
  disk: DiskStats
  total_cache_bytes: number
  total_cache_size_mb: number
  total_cache_files: number
  thumbnails: ThumbnailStats
  downloads: DownloadsStats
  rclone: RcloneStats
  memory: MemoryStats
}

export interface CacheStatsResponse {
  success: boolean
  data: CacheStatsData
  error?: string
}

export interface CacheCleanRequest {
  category: 'thumbnails' | 'downloads' | 'rclone' | 'memory' | 'all'
  retention_hours?: number
  retention_days?: number
  purge_all?: boolean
  dry_run?: boolean
  sub_source?: string
}

export interface CacheCleanResult {
  category: string
  deleted_files?: number
  deleted_bytes?: number
  deleted_size_mb?: number
  scanned_files?: number
  dry_run?: boolean
  skipped_protected?: number
  skipped_recent?: number
  status?: string
  sessions_cleared?: number
  details?: Record<string, any>
}

export interface CacheCleanResponse {
  success: boolean
  data: CacheCleanResult
  error?: string
}

export interface CachePolicy {
  DOWNLOAD_CLEANUP_ENABLED: boolean
  DOWNLOAD_RETENTION_HOURS: number
  DOWNLOAD_CLEANUP_INTERVAL_SECONDS: number
  THUMBNAIL_CACHE_MAX_AGE_DAYS: number
}

export interface CachePolicyResponse {
  success: boolean
  data: CachePolicy
  message?: string
  error?: string
}

// ==================== Telegram 多 Bot 热插拔与 BotFather 自动创机类型 ====================

export interface HotAddBotResult {
  index: number
  username: string
  mode: string
  can_read: boolean
  can_write: boolean
  already_exists?: boolean
}

export interface HotAddBotsResponse {
  success: boolean
  data?: {
    added: HotAddBotResult[]
    errors: string[]
    total_added: number
  }
  error?: string
}

export interface HotRemoveBotResponse {
  success: boolean
  data?: {
    removed_index: number
    username: string
    remaining_workers: number
  }
  error?: string
}

export interface ProtocolAccount {
  id: number
  phone: string
  session_type: string
  has_code_url: boolean
  masked_code_url: string
  bot_count: number
  max_bots: number
  remaining_quota: number
  status: 'active' | 'limit_reached' | 'cooling_down' | 'restricted' | 'invalid'
  last_used_at: string | null
  remark: string
  created_at: string
}

export interface ProtocolAccountsResponse {
  success: boolean
  data: ProtocolAccount[]
  error?: string
}

export interface BatchImportAccountsRequest {
  lines?: string[]
  content?: string
  session_string?: string
  remark?: string
}

export interface BatchImportAccountsResult {
  async?: boolean
  task_id?: string
  status?: string
  message?: string
  imported_count: number
  failed_count: number
  imported: ProtocolAccount[]
  errors: string[]
  pool: ProtocolAccount[]
}

export interface BatchImportAccountsResponse {
  success: boolean
  data?: BatchImportAccountsResult
  error?: string
}

export interface ImportTaskStatus {
  task_id: string
  status: 'running' | 'completed' | 'failed'
  progress: number
  progress_msg: string
  current_phone: string
  cooldown_remaining: number
  imported_count: number
  failed_count: number
  imported: ProtocolAccount[]
  errors: string[]
  logs: Array<{ time: string; msg: string }>
  pool?: ProtocolAccount[]
  error?: string
}

export interface ImportTaskStatusResponse {
  success: boolean
  data?: ImportTaskStatus
  error?: string
}

export interface CheckProtocolAccountResponse {
  success: boolean
  data?: {
    account: ProtocolAccount
    user_info: { id: number; first_name: string; username: string }
    bots_found: number
    bots: Array<{ username: string }>
  }
  error?: string
}

export interface BotFatherAutoCreateRequest {
  session_string?: string
  session?: string
  count?: number
  name_prefix?: string
  reuse_existing?: boolean
  mode?: 'relay' | 'single'
  account_ids?: number[]
  single_account_id?: number | null
}

export interface BotFatherAutoCreateResponse {
  success: boolean
  data?: {
    reused_count: number
    created_count: number
    total_active_workers: number
    bots: HotAddBotResult[]
    errors: string[]
    accounts_used?: number
  }
  error?: string
}


export interface BotFatherTaskStatus {
  task_id: string | null
  mode?: 'relay' | 'single'
  status: 'idle' | 'running' | 'cooling_down' | 'completed' | 'stopped' | 'failed'
  target_count: number
  created_count: number
  reused_count: number
  total_active_workers: number
  cooldown_remaining: number
  cooldown_total: number
  current_step: string
  current_account_phone?: string
  account_index?: number
  total_accounts?: number
  account_history?: Array<{
    phone: string
    reused: number
    created: number
    status: string
    error?: string
  }>
  percent: number
  logs: Array<{ time: string; level: 'info' | 'warn' | 'error' | 'success'; msg: string }>
  bots: HotAddBotResult[]
  error: string | null
  cached_sessions: Array<{ phone: string; cached: boolean }>
  accounts?: ProtocolAccount[]
}

export interface BotFatherTaskStatusResponse {
  success: boolean
  data: BotFatherTaskStatus
  error?: string
}

export interface BotClusterLoadTestNode {
  index: number
  username: string
  mode: string
  can_read: boolean
  can_write: boolean
  dispatched_requests: number
  share_percent: number
}

export interface BotClusterLoadTestResponse {
  success: boolean
  data?: {
    total_bots: number
    accessible_bots: number
    total_rounds: number
    elapsed_ms: number
    evenness_percent: number
    distribution: Record<string, number>
    nodes: BotClusterLoadTestNode[]
    message: string
  }
  error?: string
}

export interface BotReprobeResponse {
  success: boolean
  data?: {
    probed_count: number
    accessible_bots: number
    write_bots: number
    bots: Array<{
      index: number
      username: string
      mode: string
      can_read: boolean
      can_write: boolean
    }>
  }
  error?: string
}


export interface BotBenchmarkResult {
  index: number
  username: string
  mode: string
  can_read: boolean
  can_write: boolean
  ping_ms: number
  channel_ping_ms?: number | null
  stream_ttfb_ms?: number | null
  download_speed_mbps?: number | null
  playback_bitrate_mbps?: number | null
  bytes_transferred?: number
  grade: 'excellent' | 'good' | 'moderate' | 'slow' | 'error'
  grade_label: string
  status: 'ok' | 'error'
  error?: string | null
  tested_at: string
}

export interface BotClusterBenchmarkResponse {
  success: boolean
  data?: {
    total_tested: number
    online_count: number
    avg_ping_ms: number
    fastest_node?: { index: number; username: string; ping_ms: number } | null
    highest_speed_node?: { index: number; username: string; speed_mbps: number } | null
    nodes: BotBenchmarkResult[]
    tested_at: string
    summary: string
  }
  error?: string
}

export interface BotSingleBenchmarkResponse {
  success: boolean
  data?: BotBenchmarkResult
  error?: string
}

export interface StreamChunkSample {
  part: number
  bot_index: number
  bot_username: string
  size_kb: number
  elapsed_ms: number
  speed_mb_s: number
}

export interface StreamAndDownloadBenchmarkResult {
  tested_node: {
    mode: string
    mode_label: string
    bot_index: number
    bot_username: string
    active_workers_count: number
  }
  target_file: {
    message_id: number
    file_name: string
    file_size: number
    file_size_formatted: string
    mime_type: string
  }
  playback: {
    ttfb_ms: number
    initial_buffer_ms: number
    speed_mb_s: number
    bitrate_mbps: number
    ratio_1080p: number
    ratio_4k: number
    max_supported_resolution: string
    stutter_risk: 'none' | 'low' | 'moderate' | 'high'
    stutter_risk_label: string
    buffer_bytes: number
  }
  download: {
    avg_speed_mb_s: number
    peak_speed_mb_s: number
    min_speed_mb_s: number
    duration_ms: number
    bytes_transferred: number
    stability_score: number
    grade: 'ultra' | 'fast' | 'normal' | 'slow'
    grade_label: string
    total_chunks_tested?: number
    sample_mb_requested?: number
    sample_mb_transferred?: number
    is_sampled_timeline?: boolean
    chunk_samples: StreamChunkSample[]
  }
  tested_at: string
  summary: string
}

export interface StreamAndDownloadBenchmarkResponse {
  success: boolean
  data?: StreamAndDownloadBenchmarkResult
  error?: string
}
