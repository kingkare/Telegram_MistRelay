<template>
  <div class="cache-page animate-fade-in">
    <!-- 头部品牌与操作区 -->
    <div class="cache-header-card glass-card">
      <div class="cache-header-main">
        <div class="cache-title-group">
          <div class="cache-title-row">
            <h2 class="cache-title text-gradient-sakura">缓存治理中心</h2>
            <span class="cache-badge">Storage Governance</span>
          </div>
          <p class="cache-subtitle">
            系统磁盘与各级缓存生命周期统筹治理，支持容量分析、分类安全清理与自动保留策略配置。
          </p>
        </div>

        <div class="cache-header-actions">
          <el-button
            class="header-btn refresh-btn"
            :icon="RefreshRight"
            @click="fetchData"
            :loading="loading"
          >
            刷新状态
          </el-button>
          <el-button
            type="primary"
            class="header-btn safe-clean-btn"
            :icon="Brush"
            @click="handleSafeCleanAll"
            :loading="actionLoading"
          >
            一键安全清理
          </el-button>
        </div>
      </div>

      <!-- 顶部 4 大流光指标卡片 -->
      <el-row :gutter="14" class="stats-row">
        <!-- 卡片 1: 磁盘利用率 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card stat-card-disk" title="服务器存储分区占用">
            <div class="stat-icon-wrapper stat-icon-disk">
              <el-icon :size="22"><Odometer /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">
                {{ stats?.disk.percent ?? 0 }}%
              </div>
              <div class="stat-label">
                磁盘已用 {{ stats?.disk.used_gb ?? 0 }} / {{ stats?.disk.total_gb ?? 0 }} GB
              </div>
              <div class="stat-progress">
                <div
                  class="stat-progress-bar"
                  :style="{ width: `${Math.min(stats?.disk.percent || 0, 100)}%` }"
                ></div>
              </div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 2: 缓存总占用 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card" title="缩略图 + 下载临时 + Rclone 汇总占用">
            <div class="stat-icon-wrapper stat-icon-total">
              <el-icon :size="22"><Box /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-total">
                {{ formatBytes(stats?.total_cache_bytes || 0) }}
              </div>
              <div class="stat-label">
                缓存总量 ({{ stats?.total_cache_files || 0 }} 文件)
              </div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 3: 缩略图缓存 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card" title="WebP 媒体封面缓存">
            <div class="stat-icon-wrapper stat-icon-thumb">
              <el-icon :size="22"><Picture /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">
                {{ formatBytes(stats?.thumbnails.total_bytes || 0) }}
              </div>
              <div class="stat-label">
                缩略图 ({{ stats?.thumbnails.total_files || 0 }} 项)
              </div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 4: 下载与临时目录 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card" title="本地临时文件占用">
            <div class="stat-icon-wrapper stat-icon-down">
              <el-icon :size="22"><Download /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">
                {{ formatBytes(stats?.downloads.total_bytes || 0) }}
              </div>
              <div class="stat-label">
                下载临时 (可清 {{ stats?.downloads.cleanable_files || 0 }} 项)
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 分类缓存管理面板 -->
    <div class="section-title-row">
      <div class="section-title">分类缓存治理</div>
      <div class="section-subtitle">按数据类别精细化查看、试运行分析与按需释放</div>
    </div>

    <el-row :gutter="16" class="categories-row">
      <!-- 类别 1: 媒体缩略图缓存 -->
      <el-col :xs="24" :lg="12">
        <div class="category-card glass-card">
          <div class="card-head">
            <div class="card-head-left">
              <div class="cat-icon-badge cat-thumb">
                <el-icon :size="20"><Picture /></el-icon>
              </div>
              <div>
                <div class="cat-title">媒体缩略图缓存</div>
                <div class="cat-path">{{ stats?.thumbnails.cache_dir || 'cache/thumbnails' }}</div>
              </div>
            </div>
            <el-tag size="small" type="info" effect="light" class="cat-tag">WebP 格式</el-tag>
          </div>

          <div class="card-body">
            <div class="metric-grid">
              <div class="metric-item">
                <div class="metric-label">当前总占用</div>
                <div class="metric-num text-gradient-sakura">
                  {{ formatBytes(stats?.thumbnails.total_bytes || 0) }}
                </div>
                <div class="metric-sub">{{ stats?.thumbnails.total_files || 0 }} 个封面文件</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">已过期缓存</div>
                <div class="metric-num text-amber-500">
                  {{ formatBytes(stats?.thumbnails.expired_bytes || 0) }}
                </div>
                <div class="metric-sub">> {{ stats?.thumbnails.retention_days || 7 }} 天 ({{ stats?.thumbnails.expired_files || 0 }} 个)</div>
              </div>
            </div>

            <!-- 子来源细分 -->
            <div class="sub-sources-container" v-if="stats?.thumbnails.sub_sources && Object.keys(stats.thumbnails.sub_sources).length > 0">
              <div class="sub-sources-title">来源细分：</div>
              <div class="sub-sources-list">
                <div
                  v-for="(sub, key) in stats.thumbnails.sub_sources"
                  :key="key"
                  class="sub-source-pill"
                >
                  <span class="sub-name">{{ formatSubSourceName(String(key)) }}</span>
                  <span class="sub-detail">{{ sub.total_files }} 项 · {{ sub.total_size_mb }} MB</span>
                  <el-button
                    v-if="['onedrive', 'gdrive'].includes(String(key)) && sub.total_files > 0"
                    size="small"
                    text
                    type="danger"
                    class="sub-clean-btn"
                    @click="handleCleanSubSource(String(key))"
                    title="清理历史残留网盘缩略图"
                  >
                    清理
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <div class="card-footer">
            <el-button
              size="default"
              :icon="Brush"
              @click="handleCleanThumbnails(false)"
              :loading="actionLoading"
              :disabled="!stats || stats.thumbnails.expired_files === 0"
            >
              清理过期封面
            </el-button>
            <el-button
              size="default"
              type="primary"
              plain
              :icon="Loading"
              @click="handleTriggerWarmup"
            >
              一键预热封面
            </el-button>
            <el-button
              size="default"
              type="danger"
              plain
              :icon="Delete"
              @click="handleCleanThumbnails(true)"
              :loading="actionLoading"
              :disabled="!stats || stats.thumbnails.total_files === 0"
            >
              清空全部封面
            </el-button>
          </div>
        </div>
      </el-col>

      <!-- 类别 2: 下载与临时文件缓存 -->
      <el-col :xs="24" :lg="12">
        <div class="category-card glass-card">
          <div class="card-head">
            <div class="card-head-left">
              <div class="cat-icon-badge cat-down">
                <el-icon :size="20"><Download /></el-icon>
              </div>
              <div>
                <div class="cat-title">本地下载与临时文件</div>
                <div class="cat-path">{{ stats?.downloads.root || 'downloads' }}</div>
              </div>
            </div>
            <el-tag size="small" type="success" effect="light" class="cat-tag">任务受保护</el-tag>
          </div>

          <div class="card-body">
            <div class="metric-grid">
              <div class="metric-item">
                <div class="metric-label">临时目录占用</div>
                <div class="metric-num text-sky-500">
                  {{ formatBytes(stats?.downloads.total_bytes || 0) }}
                </div>
                <div class="metric-sub">{{ stats?.downloads.total_files || 0 }} 个本地文件</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">可安全清理</div>
                <div class="metric-num text-rose-500">
                  {{ formatBytes(stats?.downloads.cleanable_bytes || 0) }}
                </div>
                <div class="metric-sub">> {{ stats?.downloads.retention_hours || 24 }} 小时 ({{ stats?.downloads.cleanable_files || 0 }} 个)</div>
              </div>
            </div>

            <div class="safe-notice-box">
              <el-icon class="notice-icon"><Lock /></el-icon>
              <span>正在下载/上传中的活跃任务文件由安全机制保护，绝不会被误删（当前保护 {{ stats?.downloads.protected_files || 0 }} 项）。</span>
            </div>
          </div>

          <div class="card-footer">
            <el-button
              size="default"
              :icon="Search"
              @click="handleDryRunDownloads"
              :loading="actionLoading"
            >
              试运行分析 (Dry-run)
            </el-button>
            <el-button
              size="default"
              type="danger"
              :icon="Delete"
              @click="handleCleanDownloads"
              :loading="actionLoading"
              :disabled="!stats || stats.downloads.cleanable_files === 0"
            >
              清理过期临时文件
            </el-button>
          </div>
        </div>
      </el-col>

      <!-- 类别 3: Rclone VFS 挂载缓存 -->
      <el-col :xs="24" :lg="12">
        <div class="category-card glass-card">
          <div class="card-head">
            <div class="card-head-left">
              <div class="cat-icon-badge cat-rclone">
                <el-icon :size="20"><Folder /></el-icon>
              </div>
              <div>
                <div class="cat-title">Rclone VFS 挂载缓存</div>
                <div class="cat-path">{{ stats?.rclone.root || 'cache/rclone' }}</div>
              </div>
            </div>
            <el-tag size="small" type="info" effect="light" class="cat-tag">VFS 块缓存</el-tag>
          </div>

          <div class="card-body">
            <div class="metric-grid">
              <div class="metric-item">
                <div class="metric-label">缓存占用</div>
                <div class="metric-num text-purple-500">
                  {{ formatBytes(stats?.rclone.total_bytes || 0) }}
                </div>
                <div class="metric-sub">{{ stats?.rclone.total_files || 0 }} 个缓存分片</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">建议处理</div>
                <div class="metric-num text-gray-600">
                  {{ (stats?.rclone.total_files || 0) > 0 ? '可随时安全清空' : '已完全就绪' }}
                </div>
                <div class="metric-sub">释放挂载点本地临时预读缓存</div>
              </div>
            </div>
          </div>

          <div class="card-footer">
            <el-button
              size="default"
              type="danger"
              plain
              :icon="Delete"
              @click="handleCleanRclone"
              :loading="actionLoading"
              :disabled="!stats || stats.rclone.total_files === 0"
            >
              清空 Rclone 挂载缓存
            </el-button>
          </div>
        </div>
      </el-col>

      <!-- 类别 4: 运行期内存缓存 -->
      <el-col :xs="24" :lg="12">
        <div class="category-card glass-card">
          <div class="card-head">
            <div class="card-head-left">
              <div class="cat-icon-badge cat-mem">
                <el-icon :size="20"><Cpu /></el-icon>
              </div>
              <div>
                <div class="cat-title">运行期内存缓存</div>
                <div class="cat-path">In-Memory Runtime Caches</div>
              </div>
            </div>
            <el-tag size="small" type="success" effect="light" class="cat-tag">内存驻留</el-tag>
          </div>

          <div class="card-body">
            <div class="metric-grid">
              <div class="metric-item">
                <div class="metric-label">封面 LRU 驻留</div>
                <div class="metric-num text-emerald-500">
                  {{ stats?.memory.thumbnail_lru.currsize || 0 }}
                </div>
                <div class="metric-sub">命中: {{ stats?.memory.thumbnail_lru.hits || 0 }} · 未中: {{ stats?.memory.thumbnail_lru.misses || 0 }}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">流媒体客户端</div>
                <div class="metric-num text-sky-500">
                  {{ stats?.memory.stream_sessions || 0 }}
                </div>
                <div class="metric-sub">活跃 ByteStreamer 实例缓存</div>
              </div>
            </div>
          </div>

          <div class="card-footer">
            <el-button
              size="default"
              :icon="RefreshRight"
              @click="handleCleanMemory"
              :loading="actionLoading"
            >
              刷新内存运行态缓存
            </el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 自动清理与生命周期策略卡片 -->
    <div class="policy-card glass-card">
      <div class="policy-header">
        <div class="policy-title-left">
          <div class="policy-icon-wrapper">
            <el-icon :size="22"><Setting /></el-icon>
          </div>
          <div>
            <div class="policy-title">自动清理与生命周期策略</div>
            <div class="policy-subtitle">守护磁盘安全，定时自动执行后台平滑清理，无需人工频繁干预</div>
          </div>
        </div>
        <el-button
          type="primary"
          class="save-policy-btn"
          @click="handleSavePolicy"
          :loading="savingPolicy"
        >
          保存策略配置
        </el-button>
      </div>

      <el-form :model="policyForm" label-width="220px" class="policy-form" v-if="policyForm">
        <el-form-item label="自动清理下载目录">
          <el-switch v-model="policyForm.DOWNLOAD_CLEANUP_ENABLED" />
          <div class="form-item-tip">
            开启后，后台每隔设定时间自动扫描并清理超出保留时长的已完成/残留文件。
          </div>
        </el-form-item>

        <el-form-item label="下载文件保留时长 (小时)">
          <el-input-number
            v-model="policyForm.DOWNLOAD_RETENTION_HOURS"
            :min="1"
            :max="8760"
            :step="1"
            class="policy-input-num"
          />
          <div class="form-item-tip">超过此保留时长的文件将被后台清理任务自动删除（默认 24 小时）。</div>
        </el-form-item>

        <el-form-item label="清理检查间隔 (秒)">
          <el-input-number
            v-model="policyForm.DOWNLOAD_CLEANUP_INTERVAL_SECONDS"
            :min="60"
            :max="86400"
            :step="300"
            class="policy-input-num"
          />
          <div class="form-item-tip">后台清理轮询检查的周期（推荐 3600 秒，即每小时检查一次）。</div>
        </el-form-item>

        <el-divider class="policy-divider" />

        <el-form-item label="缩略图缓存有效期 (天)">
          <el-input-number
            v-model="policyForm.THUMBNAIL_CACHE_MAX_AGE_DAYS"
            :min="1"
            :max="365"
            :step="1"
            class="policy-input-num"
          />
          <div class="form-item-tip">超过此天数的媒体缩略图 WebP 缓存会被标记为过期（默认 7 天）。</div>
        </el-form-item>
      </el-form>
    </div>

    <!-- 试运行分析 (Dry-run) 结果弹窗 -->
    <el-dialog
      v-model="showDryRunModal"
      title="下载目录试运行清理分析 (Dry-run)"
      width="560px"
      destroy-on-close
      center
      class="dry-run-dialog"
    >
      <div v-if="dryRunResult" class="dry-run-content">
        <div class="dry-run-summary-box">
          <div class="dry-run-metric">
            <span class="dry-num text-rose-500">{{ dryRunResult.deleted_files || 0 }}</span>
            <span class="dry-label">预计删除文件</span>
          </div>
          <div class="dry-run-metric">
            <span class="dry-num text-emerald-500">{{ formatBytes(dryRunResult.deleted_bytes || 0) }}</span>
            <span class="dry-label">预计释放空间</span>
          </div>
          <div class="dry-run-metric">
            <span class="dry-num text-sky-500">{{ dryRunResult.skipped_protected || 0 }}</span>
            <span class="dry-label">受保护跳过</span>
          </div>
        </div>

        <div class="dry-run-details">
          <div class="detail-row">
            <span class="detail-k">扫描根目录：</span>
            <span class="detail-v">{{ dryRunResult.root }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-k">保留策略时长：</span>
            <span class="detail-v">{{ dryRunResult.retention_hours }} 小时</span>
          </div>
          <div class="detail-row">
            <span class="detail-k">扫描文件总数：</span>
            <span class="detail-v">{{ dryRunResult.scanned_files }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-k">未超期文件：</span>
            <span class="detail-v">{{ dryRunResult.skipped_recent || 0 }} 个</span>
          </div>
        </div>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="当前为试运行预演，未做任何真实删除操作。点击下方按钮即可立即执行实际清理。"
          class="dry-run-alert"
        />
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="showDryRunModal = false">关闭</el-button>
          <el-button
            type="danger"
            @click="executeCleanDownloadsFromDryRun"
            :loading="actionLoading"
            :disabled="!dryRunResult || dryRunResult.deleted_files === 0"
          >
            立即执行清理 (释放 {{ formatBytes(dryRunResult?.deleted_bytes || 0) }})
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Box,
  Brush,
  Cpu,
  Delete,
  Download,
  Folder,
  Loading,
  Lock,
  Odometer,
  Picture,
  RefreshRight,
  Search,
  Setting,
} from '@element-plus/icons-vue'
import {
  cleanCache,
  getCachePolicy,
  getCacheStats,
  updateCachePolicy,
  warmupTelegramThumbnails,
  type CachePolicy,
  type CacheStatsData,
} from '@/api'

const stats = ref<CacheStatsData | null>(null)
const loading = ref(false)
const actionLoading = ref(false)
const savingPolicy = ref(false)

const policyForm = ref<CachePolicy>({
  DOWNLOAD_CLEANUP_ENABLED: true,
  DOWNLOAD_RETENTION_HOURS: 24,
  DOWNLOAD_CLEANUP_INTERVAL_SECONDS: 3600,
  THUMBNAIL_CACHE_MAX_AGE_DAYS: 7,
})

const showDryRunModal = ref(false)
const dryRunResult = ref<any>(null)

function formatBytes(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

function formatSubSourceName(key: string): string {
  if (key === 'telegram') return 'Telegram 封面'
  if (key === 'onedrive') return 'OneDrive 历史'
  if (key === 'gdrive') return 'GDrive 历史'
  return key
}

async function fetchData() {
  loading.value = true
  try {
    const [statsRes, policyRes] = await Promise.all([
      getCacheStats(),
      getCachePolicy(),
    ])
    if (statsRes.success) {
      stats.value = statsRes.data
    }
    if (policyRes.success) {
      policyForm.value = { ...policyRes.data }
    }
  } catch (err: any) {
    ElMessage.error(err.message || '获取缓存状态失败')
  } finally {
    loading.value = false
  }
}

async function handleSafeCleanAll() {
  try {
    await ElMessageBox.confirm(
      '一键安全清理将清除过期缩略图（>7天）、过期下载临时文件（保留活跃任务）、Rclone缓存以及重置内存LRU缓存。是否继续？',
      '一键安全清理确认',
      {
        confirmButtonText: '确定清理',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  actionLoading.value = true
  try {
    const res = await cleanCache({ category: 'all' })
    if (res.success) {
      ElMessage.success(`安全清理完成，共删除 ${res.data.deleted_files || 0} 个文件，释放 ${formatBytes(res.data.deleted_bytes || 0)} 空间`)
      await fetchData()
    } else {
      ElMessage.error(res.error || '清理失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '清理操作失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleCleanThumbnails(purgeAll: boolean) {
  if (purgeAll) {
    try {
      await ElMessageBox.confirm(
        '清空所有缩略图将删除全部媒体 WebP 缓存，之后浏览时需重新生成或预热。是否确认清空？',
        '清空缩略图警告',
        {
          confirmButtonText: '确定清空',
          cancelButtonText: '取消',
          type: 'error',
        }
      )
    } catch {
      return
    }
  }

  actionLoading.value = true
  try {
    const res = await cleanCache({
      category: 'thumbnails',
      purge_all: purgeAll,
    })
    if (res.success) {
      ElMessage.success(
        purgeAll
          ? `已清空缩略图，删除了 ${res.data.deleted_files || 0} 个文件 (${formatBytes(res.data.deleted_bytes || 0)})`
          : `已清理过期缩略图，删除了 ${res.data.deleted_files || 0} 个文件 (${formatBytes(res.data.deleted_bytes || 0)})`
      )
      await fetchData()
    } else {
      ElMessage.error(res.error || '清理缩略图失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '清理缩略图失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleCleanSubSource(subSource: string) {
  try {
    await ElMessageBox.confirm(
      `确定清理 ${formatSubSourceName(subSource)} 的历史残留缩略图吗？`,
      '清理确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  actionLoading.value = true
  try {
    const res = await cleanCache({
      category: 'thumbnails',
      purge_all: true,
      sub_source: subSource,
    })
    if (res.success) {
      ElMessage.success(`已清理 ${subSource} 缩略图，删除 ${res.data.deleted_files || 0} 个文件`)
      await fetchData()
    } else {
      ElMessage.error(res.error || '清理失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '清理失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleTriggerWarmup() {
  try {
    const res = await warmupTelegramThumbnails()
    if (res.success) {
      ElMessage.success(res.message || '已触发后台全量缩略图预热扫描')
      await fetchData()
    }
  } catch (err: any) {
    ElMessage.error(err.message || '预热触发失败')
  }
}

async function handleDryRunDownloads() {
  actionLoading.value = true
  try {
    const res = await cleanCache({
      category: 'downloads',
      dry_run: true,
    })
    if (res.success) {
      dryRunResult.value = res.data
      showDryRunModal.value = true
    } else {
      ElMessage.error(res.error || '分析失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '分析失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleCleanDownloads() {
  try {
    await ElMessageBox.confirm(
      '确定清理下载目录中超过保留时间的临时文件吗？正在进行中的任务不会受到影响。',
      '清理确认',
      { confirmButtonText: '确定清理', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  actionLoading.value = true
  try {
    const res = await cleanCache({
      category: 'downloads',
      dry_run: false,
    })
    if (res.success) {
      ElMessage.success(`清理完成，删除了 ${res.data.deleted_files || 0} 个文件，释放 ${formatBytes(res.data.deleted_bytes || 0)} 空间`)
      await fetchData()
    } else {
      ElMessage.error(res.error || '清理下载目录失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '清理下载目录失败')
  } finally {
    actionLoading.value = false
  }
}

async function executeCleanDownloadsFromDryRun() {
  showDryRunModal.value = false
  await handleCleanDownloads()
}

async function handleCleanRclone() {
  try {
    await ElMessageBox.confirm(
      '确定清空 Rclone 挂载缓存目录吗？',
      '清空确认',
      { confirmButtonText: '确定清空', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  actionLoading.value = true
  try {
    const res = await cleanCache({ category: 'rclone' })
    if (res.success) {
      ElMessage.success(`已清空 Rclone 缓存，删除了 ${res.data.deleted_files || 0} 个文件`)
      await fetchData()
    } else {
      ElMessage.error(res.error || '清空 Rclone 缓存失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '清空 Rclone 缓存失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleCleanMemory() {
  actionLoading.value = true
  try {
    const res = await cleanCache({ category: 'memory' })
    if (res.success) {
      ElMessage.success('运行期内存与 LRU 缓存已成功刷新重置')
      await fetchData()
    } else {
      ElMessage.error(res.error || '刷新失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '刷新失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleSavePolicy() {
  savingPolicy.value = true
  try {
    const res = await updateCachePolicy(policyForm.value)
    if (res.success) {
      ElMessage.success(res.message || '缓存自动清理策略配置已成功保存并生效')
      policyForm.value = { ...res.data }
      await fetchData()
    } else {
      ElMessage.error(res.error || '保存策略失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '保存策略失败')
  } finally {
    savingPolicy.value = false
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.cache-page {
  @apply space-y-6;
  max-width: 1400px;
  margin: 0 auto;
}

/* 头部卡片 */
.cache-header-card {
  padding: 24px;
  border-radius: 20px;
}

.cache-header-main {
  @apply flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6;
}

.cache-title-row {
  @apply flex items-center gap-3 mb-1;
}

.cache-title {
  @apply text-2xl md:text-3xl font-extrabold tracking-tight;
}

.cache-badge {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 3px 10px;
  border-radius: 9999px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.15) 0%, rgba(56, 189, 248, 0.15) 100%);
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.3);
}

.cache-subtitle {
  @apply text-sm text-gray-500 max-w-2xl;
}

.cache-header-actions {
  @apply flex items-center gap-3 flex-wrap;
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.25s ease;
}

.refresh-btn {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 143, 171, 0.25);
  color: #4b5563;
}

.refresh-btn:hover {
  color: #ff7597;
  border-color: rgba(255, 117, 151, 0.5);
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.15);
}

.safe-clean-btn {
  background: var(--gradient-primary);
  border: none;
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.35);
}

.safe-clean-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(255, 117, 151, 0.45);
}

/* 顶部指标卡片 */
.stats-row {
  margin-top: 10px;
}

.stat-card {
  @apply flex items-center gap-3.5 p-3.5 rounded-2xl;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03);
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
}

.stat-card:hover {
  background: rgba(255, 255, 255, 0.95);
  transform: translateY(-2px);
  box-shadow: 0 8px 22px rgba(255, 117, 151, 0.12);
  border-color: rgba(255, 117, 151, 0.25);
}

.stat-icon-wrapper {
  @apply w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 text-white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.stat-icon-disk {
  background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%);
}

.stat-icon-total {
  background: linear-gradient(135deg, #ec4899 0%, #f43f5e 100%);
}

.stat-icon-thumb {
  background: linear-gradient(135deg, #8b5cf6 0%, #a855f7 100%);
}

.stat-icon-down {
  background: linear-gradient(135deg, #06b6d4 0%, #14b8a6 100%);
}

.stat-info {
  @apply flex-1 min-w-0;
}

.stat-value {
  @apply text-lg font-bold text-gray-800 leading-tight truncate;
}

.stat-value-total {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.stat-label {
  @apply text-xs text-gray-500 mt-0.5 truncate font-medium;
}

.stat-progress {
  width: 100%;
  height: 4px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 9999px;
  margin-top: 6px;
  overflow: hidden;
}

.stat-progress-bar {
  height: 100%;
  border-radius: 9999px;
  background: linear-gradient(90deg, #38bdf8 0%, #ff7597 100%);
  transition: width 0.4s ease;
}

/* 分类标题 */
.section-title-row {
  @apply flex flex-col sm:flex-row sm:items-center justify-between gap-1 pt-2 pb-1;
}

.section-title {
  @apply text-xl font-bold text-gray-800;
}

.section-subtitle {
  @apply text-xs text-gray-500;
}

/* 分类卡片 */
.categories-row {
  row-gap: 16px;
}

.category-card {
  padding: 20px;
  border-radius: 18px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: all 0.25s ease;
}

.category-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(255, 117, 151, 0.12);
  border-color: rgba(255, 117, 151, 0.3);
}

.card-head {
  @apply flex items-center justify-between pb-4 border-b border-gray-100;
}

.card-head-left {
  @apply flex items-center gap-3;
}

.cat-icon-badge {
  @apply w-10 h-10 rounded-xl flex items-center justify-center text-white;
}

.cat-thumb {
  background: linear-gradient(135deg, #a855f7 0%, #ec4899 100%);
}

.cat-down {
  background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%);
}

.cat-rclone {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
}

.cat-mem {
  background: linear-gradient(135deg, #10b981 0%, #14b8a6 100%);
}

.cat-title {
  @apply text-base font-bold text-gray-800;
}

.cat-path {
  @apply text-xs text-gray-400 font-mono mt-0.5 truncate max-w-xs;
}

.cat-tag {
  border-radius: 8px;
}

.card-body {
  @apply py-4 flex-1;
}

.metric-grid {
  @apply grid grid-cols-2 gap-3 mb-3;
}

.metric-item {
  @apply p-3 rounded-xl bg-white/60 border border-white/80;
}

.metric-label {
  @apply text-xs text-gray-500 font-medium;
}

.metric-num {
  @apply text-lg font-extrabold mt-1;
}

.metric-sub {
  @apply text-xs text-gray-400 mt-0.5 font-normal truncate;
}

/* 子来源细分 */
.sub-sources-container {
  @apply mt-3 pt-3 border-t border-gray-100;
}

.sub-sources-title {
  @apply text-xs font-semibold text-gray-500 mb-2;
}

.sub-sources-list {
  @apply flex flex-wrap gap-2;
}

.sub-source-pill {
  @apply flex items-center gap-2 px-2.5 py-1 rounded-lg bg-gray-50 border border-gray-200 text-xs;
}

.sub-name {
  @apply font-medium text-gray-700;
}

.sub-detail {
  @apply text-gray-400;
}

.sub-clean-btn {
  padding: 0 4px;
  font-size: 11px;
}

.safe-notice-box {
  @apply flex items-center gap-2 p-2.5 rounded-xl text-xs text-sky-700 bg-sky-50/70 border border-sky-200 mt-2;
}

.notice-icon {
  @apply flex-shrink-0 text-sky-600;
}

.card-footer {
  @apply pt-3 border-t border-gray-100 flex items-center gap-2 flex-wrap;
}

/* 策略卡片 */
.policy-card {
  padding: 24px;
  border-radius: 20px;
}

.policy-header {
  @apply flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-gray-100 mb-4;
}

.policy-title-left {
  @apply flex items-center gap-3;
}

.policy-icon-wrapper {
  @apply w-10 h-10 rounded-xl flex items-center justify-center text-white;
  background: var(--gradient-primary);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.35);
}

.policy-title {
  @apply text-lg font-bold text-gray-800;
}

.policy-subtitle {
  @apply text-xs text-gray-500 mt-0.5;
}

.save-policy-btn {
  border-radius: 12px;
  font-weight: 600;
  background: var(--gradient-primary);
  border: none;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.25);
}

.policy-form {
  @apply max-w-2xl py-2;
}

.policy-input-num {
  width: 220px;
}

.form-item-tip {
  @apply text-xs text-gray-400 mt-1;
}

.policy-divider {
  margin: 16px 0;
  border-color: rgba(0, 0, 0, 0.04);
}

/* Dry-run 对话框 */
.dry-run-summary-box {
  @apply grid grid-cols-3 gap-3 p-4 rounded-2xl bg-gray-50 border border-gray-200 mb-4 text-center;
}

.dry-run-metric {
  @apply flex flex-col items-center;
}

.dry-num {
  @apply text-xl font-extrabold;
}

.dry-label {
  @apply text-xs text-gray-500 mt-1 font-medium;
}

.dry-run-details {
  @apply space-y-2 mb-4 p-3 bg-white rounded-xl border border-gray-100 text-xs;
}

.detail-row {
  @apply flex justify-between items-center;
}

.detail-k {
  @apply text-gray-500;
}

.detail-v {
  @apply font-medium text-gray-800;
}

.dry-run-alert {
  margin-top: 10px;
  border-radius: 10px;
}

/* ========== 移动端响应式覆盖 ========== */
@media (max-width: 768px) {
  .cache-page {
    padding: 0 !important;
  }

  .cache-header-card,
  .category-card,
  .policy-card {
    padding: 14px !important;
    border-radius: 14px !important;
  }

  .cache-header-actions {
    flex-direction: column !important;
    width: 100% !important;
    gap: 8px !important;
  }

  .cache-header-actions > * {
    width: 100% !important;
  }

  .card-actions {
    flex-direction: column !important;
    width: 100% !important;
    gap: 6px !important;
  }

  .card-actions > * {
    width: 100% !important;
  }

  .policy-input-num {
    width: 100% !important;
  }

  .dry-run-summary-box {
    grid-template-columns: 1fr !important;
    gap: 8px !important;
  }
}

</style>
