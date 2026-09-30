<template>
  <div class="tasks-center-page animate-fade-in">
    <!-- 头部品牌与统计控制区 -->
    <div class="tasks-header-card glass-card">
      <div class="tasks-header-main">
        <div class="tasks-title-group">
          <div class="tasks-title-row">
            <h2 class="tasks-title text-gradient-sakura">任务调度中心</h2>
            <span class="tasks-badge">Task Engine</span>
          </div>
          <p class="tasks-subtitle">
            Aria2 传输调度、Telegram 频道上传队列与转存历史统筹管理。
          </p>
        </div>

        <div class="tasks-header-actions">
          <el-select
            v-model="limit"
            class="tasks-limit-select"
            @change="handleLimitChange"
            size="default"
          >
            <el-option label="显示 50 条" :value="50" />
            <el-option label="显示 100 条" :value="100" />
            <el-option label="显示 200 条" :value="200" />
            <el-option label="显示 500 条" :value="500" />
          </el-select>

          <el-button
            class="header-btn auto-refresh-btn"
            :type="queueAutoRefresh ? 'primary' : ''"
            :plain="queueAutoRefresh"
            size="default"
            @click="toggleQueueAutoRefresh"
            :title="queueAutoRefresh ? '点击暂停自动轮询' : '点击开启 3 秒平滑自动轮询'"
          >
            <span class="refresh-indicator" :class="{ 'is-active': queueAutoRefresh }"></span>
            {{ queueAutoRefresh ? '自动轮询中' : '自动刷新已停' }}
          </el-button>

          <el-button
            class="header-btn refresh-btn"
            :icon="RefreshRight"
            @click="handleRefresh"
            :loading="isLoading || queueLoading"
            size="default"
          >
            刷新
          </el-button>

          <el-button
            v-if="failedDownloadsCount > 0"
            type="warning"
            class="header-btn retry-all-btn"
            :icon="RefreshRight"
            @click="handleRetryAllFailed"
            :loading="operationLoading"
            size="default"
          >
            重试失败 ({{ failedDownloadsCount }})
          </el-button>

          <el-button
            type="danger"
            class="header-btn delete-all-btn"
            :icon="Delete"
            @click="handleDeleteAll"
            :disabled="groups.length === 0 && uploads.length === 0"
            size="default"
          >
            清空历史记录
          </el-button>
        </div>
      </div>

      <!-- 4 大流光指标卡片 -->
      <el-row :gutter="14" class="stats-row">
        <!-- 卡片 1: 正在下载 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': activeTab === 'download' }"
            @click="activeTab = 'download'"
            title="查看正在下载列表"
          >
            <div class="stat-icon-wrapper stat-icon-download">
              <el-icon :size="22"><Download /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value text-sky-500">
                {{ activeDownloads.length }}
                <span class="stat-unit" v-if="totalDownloadSpeed > 0">· {{ formatSpeed(totalDownloadSpeed) }}</span>
              </div>
              <div class="stat-label">正在下载</div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 2: 正在上传 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': activeTab === 'upload' }"
            @click="activeTab = 'upload'"
            title="查看正在上传列表"
          >
            <div class="stat-icon-wrapper stat-icon-upload">
              <el-icon :size="22"><Upload /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value text-pink-500">
                {{ activeUploads.length }}
                <span class="stat-unit" v-if="totalUploadSpeed > 0">· {{ formatSpeed(totalUploadSpeed) }}</span>
              </div>
              <div class="stat-label">正在上传</div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 3: 排队等待 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': activeTab === 'queue', 'is-warning': queueData?.flood_wait?.is_waiting }"
            @click="activeTab = 'queue'"
            title="查看处理与等待队列"
          >
            <div class="stat-icon-wrapper stat-icon-queue">
              <el-icon :size="22"><List /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value text-purple-500">
                {{ queueSize }}
                <span class="stat-unit" v-if="queueData?.flood_wait?.is_waiting">· 限流中</span>
              </div>
              <div class="stat-label">排队等待中</div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 4: 任务记录组 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': activeTab === 'records' }"
            @click="activeTab = 'records'"
            title="查看历史任务记录"
          >
            <div class="stat-icon-wrapper stat-icon-records">
              <el-icon :size="22"><Files /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-records">
                {{ groups.length }}
                <span class="stat-unit" v-if="failedDownloadsCount > 0">({{ failedDownloadsCount }} 失败)</span>
              </div>
              <div class="stat-label">历史任务记录</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 主体任务内容卡片 -->
    <div class="tasks-content-card glass-card">
      <el-skeleton v-if="isLoading" :rows="10" animated class="p-6" />

      <el-alert
        v-else-if="error"
        :title="`加载失败: ${error}`"
        type="error"
        :closable="false"
        class="m-6"
      >
        <template #default>
          <el-button @click="handleRefresh" type="primary" size="small" class="mt-2">重试</el-button>
        </template>
      </el-alert>

      <div v-else class="tasks-tabs-container">
        <el-tabs v-model="activeTab" class="tasks-modern-tabs">
          <!-- 下载标签页 -->
          <el-tab-pane name="download">
            <template #label>
              <span class="tab-label-inner">
                <el-icon><Download /></el-icon>
                <span>正在下载</span>
                <el-tag v-if="activeDownloads.length > 0" size="small" type="primary" round effect="dark" class="tab-badge">
                  {{ activeDownloads.length }}
                </el-tag>
              </span>
            </template>

            <el-empty
              v-if="activeDownloads.length === 0"
              description="当前没有正在下载或等待的 Aria2 任务"
              :image-size="100"
              class="my-8"
            />
            <div v-else class="tasks-table-wrapper">
              <!-- 移动端下载任务卡片流 (桌面端隐藏) -->
              <div class="mobile-task-cards-list md:hidden flex flex-col gap-2.5">
                <div
                  v-for="row in activeDownloads"
                  :key="row.id"
                  class="mobile-task-card glass-card p-3 rounded-xl cursor-pointer"
                  @click="openGroupForActiveRow(row)"
                >
                  <div class="flex items-start justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0 flex-1">
                      <div class="file-type-icon text-lg flex-shrink-0" :style="{ color: getFileIcon(row.file_name).color }">
                        <component :is="getFileIcon(row.file_name).icon" />
                      </div>
                      <div class="flex flex-col min-w-0 flex-1">
                        <span class="text-sm font-semibold text-gray-800 truncate">{{ row.file_name || row.source_url?.substring(0, 40) || '未知文件' }}</span>
                        <span class="text-xs text-gray-500 truncate" v-if="row.group_title">{{ row.group_title }}</span>
                      </div>
                    </div>
                    <el-tag :type="getStatusTagTypeWithSkip(row.status, row.error_message)" size="small" round>
                      {{ getStatusTextWithSkip(row.status, row.error_message) }}
                    </el-tag>
                  </div>

                  <div class="mt-2.5">
                    <el-progress
                      :percentage="getProgress(row.total_length, row.completed_length, row.status)"
                      :status="getProgressStatus(row.status)"
                      :stroke-width="6"
                      class="modern-progress"
                    />
                    <div class="flex items-center justify-between text-xs text-gray-500 mt-1 font-mono">
                      <span>{{ formatSize(row.completed_length || 0) }} / {{ formatSize(row.total_length || 0) }}</span>
                      <span v-if="row.status === 'downloading'" class="text-sky-500 font-bold">
                        ⚡ {{ formatSpeed(row.download_speed) }}
                      </span>
                    </div>
                  </div>

                  <div class="flex items-center justify-between mt-2.5 pt-2 border-t border-pink-100/60" @click.stop>
                    <span class="text-xs text-gray-400 font-mono">{{ formatDate(row.updated_at || row.created_at) }}</span>
                    <div class="flex items-center gap-2">
                      <el-button
                        size="small"
                        circle
                        :icon="RefreshRight"
                        :loading="operationLoading"
                        :disabled="!row.gid && !row.source_url"
                        @click.stop="handleRetry(row)"
                        title="重试任务"
                      />
                      <el-button
                        size="small"
                        circle
                        type="danger"
                        :icon="Delete"
                        :loading="operationLoading"
                        @click.stop="handleDelete(row, false)"
                        title="删除下载任务"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 桌面端表格 (移动端隐藏) -->
              <div class="hidden md:block">
              <el-table
                :data="activeDownloads"
                size="default"
                style="width: 100%"
                row-key="id"
                @row-click="openGroupForActiveRow"
                class="modern-task-table cursor-pointer"
              >
                <el-table-column prop="group_title" label="来源" min-width="200" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="font-medium text-gray-700">{{ row.group_title }}</span>
                  </template>
                </el-table-column>

                <el-table-column prop="file_name" label="文件名" min-width="260" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="file-name-cell">
                      <div class="file-type-icon" :style="{ color: getFileIcon(row.file_name).color }">
                        <component :is="getFileIcon(row.file_name).icon" />
                      </div>
                      <span class="file-name-text">{{ row.file_name || row.source_url?.substring(0, 40) || '未知文件' }}</span>
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="状态" width="120">
                  <template #default="{ row }">
                    <el-tag :type="getStatusTagTypeWithSkip(row.status, row.error_message)" size="small" round>
                      {{ getStatusTextWithSkip(row.status, row.error_message) }}
                    </el-tag>
                  </template>
                </el-table-column>

                <el-table-column label="进度" width="190">
                  <template #default="{ row }">
                    <div class="progress-cell">
                      <el-progress
                        :percentage="getProgress(row.total_length, row.completed_length, row.status)"
                        :status="getProgressStatus(row.status)"
                        :stroke-width="8"
                        class="modern-progress"
                      />
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="下载速度" width="130">
                  <template #default="{ row }">
                    <span v-if="row.status === 'downloading'" class="speed-badge font-mono">
                      {{ formatSpeed(row.download_speed) }}
                    </span>
                    <span v-else class="text-gray-400">-</span>
                  </template>
                </el-table-column>

                <el-table-column label="更新时间" width="160">
                  <template #default="{ row }">
                    <span class="text-xs text-gray-500 font-mono">{{ formatDate(row.updated_at || row.created_at) }}</span>
                  </template>
                </el-table-column>

                <el-table-column label="操作" width="120" fixed="right">
                  <template #default="{ row }">
                    <div class="action-btn-group" @click.stop>
                      <el-button
                        size="small"
                        circle
                        :icon="RefreshRight"
                        :loading="operationLoading"
                        :disabled="!row.gid && !row.source_url"
                        @click.stop="handleRetry(row)"
                        title="重试任务"
                      />
                      <el-button
                        size="small"
                        circle
                        type="danger"
                        :icon="Delete"
                        :loading="operationLoading"
                        @click.stop="handleDelete(row, false)"
                        title="删除下载任务"
                      />
                    </div>
                  </template>
                </el-table-column>
              </el-table>
              </div>
              <div class="table-tip-bar">
                <el-icon class="mr-1 text-sky-500"><InfoFilled /></el-icon>
                <span>点击任意行可自动切换至“任务记录”并展开对应消息媒体组</span>
              </div>
            </div>
          </el-tab-pane>

          <!-- 上传标签页 -->
          <el-tab-pane name="upload">
            <template #label>
              <span class="tab-label-inner">
                <el-icon><Upload /></el-icon>
                <span>正在上传</span>
                <el-tag v-if="activeUploads.length > 0" size="small" type="success" round effect="dark" class="tab-badge">
                  {{ activeUploads.length }}
                </el-tag>
              </span>
            </template>

            <el-empty
              v-if="activeUploads.length === 0"
              description="当前没有正在上传的 Telegram 任务"
              :image-size="100"
              class="my-8"
            />
            <div v-else class="tasks-table-wrapper">
              <!-- 移动端上传任务卡片流 (桌面端隐藏) -->
              <div class="mobile-task-cards-list md:hidden flex flex-col gap-2.5">
                <div
                  v-for="row in activeUploads"
                  :key="row.id"
                  class="mobile-task-card glass-card p-3 rounded-xl"
                >
                  <div class="flex items-start justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0 flex-1">
                      <div class="file-type-icon text-lg flex-shrink-0" :style="{ color: getFileIcon(row.file_name).color }">
                        <component :is="getFileIcon(row.file_name).icon" />
                      </div>
                      <div class="flex flex-col min-w-0 flex-1">
                        <span class="text-sm font-semibold text-gray-800 truncate">{{ row.file_name || '未知文件' }}</span>
                        <div class="flex items-center gap-1.5 mt-0.5">
                          <el-tag size="small" :type="getUploadTargetTagType(row.upload_target)" round style="font-size: 10px; height: 18px; padding: 0 4px;">
                            {{ getUploadTargetLabel(row.upload_target) }}
                          </el-tag>
                          <span class="text-xs text-gray-400 font-mono">{{ formatSize(row.total_size) }}</span>
                        </div>
                      </div>
                    </div>
                    <el-tag :type="getUploadStatusTagType(row.status)" size="small" round>
                      {{ getUploadStatusText(row.status, row.upload_target) }}
                    </el-tag>
                  </div>

                  <div class="mt-2.5">
                    <el-progress
                      :percentage="getUploadProgress(row.total_size, row.uploaded_size)"
                      :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : 'warning'"
                      :stroke-width="6"
                      class="modern-progress"
                    />
                    <div class="flex items-center justify-between text-xs text-gray-500 mt-1 font-mono">
                      <span>{{ formatSize(row.uploaded_size || 0) }} / {{ formatSize(row.total_size || 0) }}</span>
                      <span v-if="row.status === 'uploading' && row.upload_speed && row.upload_speed > 0" class="text-pink-500 font-bold">
                        🚀 {{ formatSpeed(row.upload_speed) }}
                      </span>
                    </div>
                  </div>

                  <div class="flex items-center justify-between mt-2.5 pt-2 border-t border-pink-100/60" @click.stop>
                    <span class="text-xs text-gray-400 font-mono">{{ formatDate(row.updated_at || row.created_at) }}</span>
                    <div class="flex items-center gap-2">
                      <el-button
                        size="small"
                        circle
                        :icon="RefreshRight"
                        :loading="operationLoading"
                        :disabled="isDeprecatedUploadTarget(row.upload_target)"
                        @click.stop="handleRetryUpload(row)"
                        :title="isDeprecatedUploadTarget(row.upload_target) ? '历史第三方网盘已废弃' : '重试'"
                      />
                      <el-button
                        size="small"
                        circle
                        type="danger"
                        :icon="Delete"
                        :loading="operationLoading"
                        :disabled="row.status === 'completed' || (row.status as string) === 'cleaned'"
                        @click.stop="handleDeleteUpload(row)"
                        title="删除上传任务"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 桌面端表格 (移动端隐藏) -->
              <div class="hidden md:block">
              <el-table :data="activeUploads" size="default" style="width: 100%" row-key="id" class="modern-task-table">
                <el-table-column prop="file_name" label="文件名" min-width="250" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="file-name-cell">
                      <div class="file-type-icon" :style="{ color: getFileIcon(row.file_name).color }">
                        <component :is="getFileIcon(row.file_name).icon" />
                      </div>
                      <span class="file-name-text">{{ row.file_name || '未知文件' }}</span>
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="上传目标" width="130">
                  <template #default="{ row }">
                    <el-tag size="small" :type="getUploadTargetTagType(row.upload_target)" round>
                      {{ getUploadTargetLabel(row.upload_target) }}
                    </el-tag>
                  </template>
                </el-table-column>

                <el-table-column label="状态" width="120">
                  <template #default="{ row }">
                    <el-tag :type="getUploadStatusTagType(row.status)" size="small" round>
                      {{ getUploadStatusText(row.status, row.upload_target) }}
                    </el-tag>
                  </template>
                </el-table-column>

                <el-table-column label="进度" width="190">
                  <template #default="{ row }">
                    <div class="progress-cell">
                      <el-progress
                        :percentage="getUploadProgress(row.total_size, row.uploaded_size)"
                        :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : 'warning'"
                        :stroke-width="8"
                        class="modern-progress"
                      />
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="上传速度" width="130">
                  <template #default="{ row }">
                    <span v-if="row.status === 'uploading' && row.upload_speed && row.upload_speed > 0" class="speed-badge font-mono">
                      {{ formatSpeed(row.upload_speed) }}
                    </span>
                    <span v-else-if="row.status === 'uploading'" class="text-xs text-amber-500">计算中...</span>
                    <span v-else class="text-gray-400">-</span>
                  </template>
                </el-table-column>

                <el-table-column label="文件大小" width="120">
                  <template #default="{ row }">
                    <span class="text-xs font-mono font-medium text-gray-700">{{ formatSize(row.total_size) }}</span>
                  </template>
                </el-table-column>

                <el-table-column label="更新时间" width="160">
                  <template #default="{ row }">
                    <span class="text-xs text-gray-500 font-mono">{{ formatDate(row.updated_at || row.created_at) }}</span>
                  </template>
                </el-table-column>

                <el-table-column label="操作" width="120" fixed="right">
                  <template #default="{ row }">
                    <div class="action-btn-group" @click.stop>
                      <el-button
                        size="small"
                        circle
                        :icon="RefreshRight"
                        :loading="operationLoading"
                        :disabled="isDeprecatedUploadTarget(row.upload_target)"
                        @click.stop="handleRetryUpload(row)"
                        :title="isDeprecatedUploadTarget(row.upload_target) ? '历史第三方网盘已废弃' : '重试'"
                      />
                      <el-button
                        size="small"
                        circle
                        type="danger"
                        :icon="Delete"
                        :loading="operationLoading"
                        :disabled="row.status === 'completed' || row.status === 'cleaned'"
                        @click.stop="handleDeleteUpload(row)"
                        title="删除上传任务"
                      />
                    </div>
                  </template>
                </el-table-column>
              </el-table>
              </div>
            </div>
          </el-tab-pane>

          <!-- 队列标签页 -->
          <el-tab-pane name="queue">
            <template #label>
              <span class="tab-label-inner">
                <el-icon><List /></el-icon>
                <span>等待队列</span>
                <el-tag v-if="queueSize > 0" size="small" type="warning" round effect="dark" class="tab-badge">
                  {{ queueSize }}
                </el-tag>
              </span>
            </template>

            <div class="queue-tab-content">
              <!-- 限流告警卡片 -->
              <div v-if="queueData?.flood_wait?.is_waiting" class="flood-wait-card">
                <div class="flood-wait-header">
                  <div class="flood-badge">
                    <el-icon :size="20"><Warning /></el-icon>
                    <span>Telegram 接口限流保护中</span>
                  </div>
                  <span class="flood-timer font-mono">剩余 {{ queueData.flood_wait.remaining_seconds }} 秒</span>
                </div>
                <div class="flood-wait-body">
                  <p>Bot 触发了 Telegram FloodWait 限制（总时长 {{ queueData.flood_wait.wait_seconds }} 秒）。所有待处理消息已安全暂存于内存等待队列中，限流倒计时结束后将按顺序自动恢复处理。</p>
                </div>
              </div>

              <!-- 队列正在处理 -->
              <div class="queue-section">
                <div class="queue-section-title">
                  <span>当前正在处理</span>
                  <span v-if="currentProcessing" class="active-pulse"></span>
                </div>

                <el-empty v-if="!currentProcessing" description="当前没有正在处理的队列项" :image-size="80" />
                <div v-else class="current-task-box">
                  <div class="current-task-badge">
                    <el-icon class="is-spinning"><Loading /></el-icon>
                    <span>处理中</span>
                  </div>
                  <div class="current-task-info">
                    <div class="current-task-title">{{ currentProcessing.title }}</div>
                    <div class="current-task-tags">
                      <el-tag size="small" type="primary" round>
                        {{ currentProcessing.type === 'media_group' ? '媒体组相册' : '单文件' }}
                      </el-tag>
                      <el-tag v-if="currentProcessing.media_group_total" size="small" type="info" round>
                        包含 {{ currentProcessing.media_group_total }} 个媒体
                      </el-tag>
                      <el-tag v-if="currentProcessing.task_gids && currentProcessing.task_gids.length" size="small" type="success" round>
                        {{ currentProcessing.task_gids.length }} 个 Aria2 任务
                      </el-tag>
                    </div>
                  </div>
                </div>
              </div>

              <el-divider class="my-6" />

              <!-- 排队列表 -->
              <div class="queue-section">
                <div class="queue-section-title">
                  <span>排队等待队列 ({{ waitingItems.length }})</span>
                  <el-button size="small" text :icon="RefreshRight" @click="fetchQueue" :loading="queueLoading">
                    刷新队列
                  </el-button>
                </div>

                <el-empty v-if="waitingItems.length === 0" description="等待队列为空，调度空闲" :image-size="80" />
                <div v-else class="waiting-list">
                  <div
                    v-for="(item, index) in waitingItems"
                    :key="item.queue_id || index"
                    class="waiting-item-card"
                  >
                    <div class="waiting-order-badge font-mono">#{{ Number(index) + 1 }}</div>
                    <div class="waiting-item-main">
                      <div class="waiting-item-title">{{ item.title }}</div>
                      <div class="waiting-item-meta">
                        <el-tag size="small" :type="item.type === 'media_group' ? 'warning' : 'info'" round>
                          {{ item.type === 'media_group' ? '媒体组' : '单文件' }}
                        </el-tag>
                        <span v-if="item.media_group_total" class="text-xs text-gray-500">
                          共 {{ item.media_group_total }} 个文件
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 记录标签页 -->
          <el-tab-pane name="records">
            <template #label>
              <span class="tab-label-inner">
                <el-icon><Files /></el-icon>
                <span>历史记录组</span>
                <el-tag size="small" type="info" round class="tab-badge">{{ filteredGroups.length }}</el-tag>
              </span>
            </template>

            <!-- 记录页专用筛选工具栏 -->
            <div class="records-filter-toolbar">
              <el-input
                v-model="recordSearch"
                placeholder="搜索文件名、消息说明或 Message ID..."
                :prefix-icon="Search"
                clearable
                class="record-search-input"
              />

              <div class="record-filter-pills">
                <button
                  type="button"
                  class="filter-pill"
                  :class="{ 'is-active': recordStatusFilter === '' }"
                  @click="recordStatusFilter = ''"
                >
                  全部 ({{ groups.length }})
                </button>
                <button
                  type="button"
                  class="filter-pill"
                  :class="{ 'is-active': recordStatusFilter === 'active' }"
                  @click="recordStatusFilter = 'active'"
                >
                  进行中
                </button>
                <button
                  type="button"
                  class="filter-pill"
                  :class="{ 'is-active': recordStatusFilter === 'completed' }"
                  @click="recordStatusFilter = 'completed'"
                >
                  已完成
                </button>
                <button
                  type="button"
                  class="filter-pill pill-danger"
                  :class="{ 'is-active': recordStatusFilter === 'failed' }"
                  @click="recordStatusFilter = 'failed'"
                >
                  含失败
                </button>
              </div>
            </div>

            <el-empty
              v-if="filteredGroups.length === 0"
              :description="recordSearch || recordStatusFilter ? '没有符合筛选条件的任务记录' : '暂无任务记录'"
              :image-size="100"
              class="my-8"
            />

            <el-collapse v-else v-model="activeGroups" class="modern-collapse">
              <el-collapse-item
                v-for="group in filteredGroups"
                :key="group.group_key"
                :name="group.group_key"
                class="download-group-item"
              >
                <template #title>
                  <div class="group-header">
                    <div class="group-info">
                      <div class="group-icon-wrapper">
                        <el-icon :size="18"><Files /></el-icon>
                      </div>
                      <div class="group-details">
                        <div class="group-title">
                          <span v-if="group.caption" class="caption">{{ truncateText(group.caption, 50) }}</span>
                          <span v-else class="group-type">
                            {{ group.group_type === 'media_group' ? '媒体组相册' : '频道消息' }}
                            <span v-if="group.message_id" class="font-mono text-pink-500">#{{ group.message_id }}</span>
                          </span>
                        </div>
                        <div class="group-meta">
                          <el-tag size="small" type="info" round>{{ group.stats.total_files }} 文件</el-tag>
                          <el-tag size="small" type="success" round>{{ group.stats.completed }} 完成</el-tag>
                          <el-tag v-if="group.stats.downloading > 0" size="small" type="warning" round>
                            {{ group.stats.downloading }} 下载中
                          </el-tag>
                          <el-tag v-if="(group.stats.skipped || 0) > 0" size="small" type="info" round>
                            {{ group.stats.skipped }} 跳过
                          </el-tag>
                          <el-tag v-if="group.stats.failed > 0" size="small" type="danger" round>
                            {{ group.stats.failed }} 失败
                          </el-tag>
                          <span class="group-date font-mono">{{ formatDate(group.created_at || group.message_date) }}</span>
                        </div>
                      </div>
                    </div>
                    <div class="group-progress-side">
                      <el-progress
                        :percentage="getGroupProgress(group.stats)"
                        :status="getGroupStatus(group.stats)"
                        :stroke-width="8"
                        style="width: 110px"
                        class="modern-progress"
                      />
                      <span class="group-size font-mono">{{ formatSize(group.stats.total_size) }}</span>
                    </div>
                  </div>
                </template>

                <div class="group-downloads-inner">
                  <!-- 移动端任务卡片列表 -->
                  <div class="mobile-history-cards md:hidden flex flex-col gap-2 p-2">
                    <div
                      v-for="row in group.downloads"
                      :key="row.id"
                      class="p-2.5 rounded-xl border border-pink-100/70 bg-white/90 shadow-sm flex flex-col gap-1.5 cursor-pointer"
                      @click="handleRowClick(row)"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <div class="flex items-center gap-2 min-w-0">
                          <div class="file-type-icon shrink-0" :style="{ color: getFileIcon(row.file_name).color }">
                            <component :is="getFileIcon(row.file_name).icon" />
                          </div>
                          <span class="text-xs font-semibold text-gray-800 truncate" :title="row.file_name">
                            {{ row.file_name || row.source_url?.substring(0, 40) || "未知文件" }}
                          </span>
                        </div>
                        <el-tag :type="getRecordStatusTagType(row)" size="small" round class="shrink-0 scale-90">
                          {{ getRecordStatusText(row) }}
                        </el-tag>
                      </div>
                      <div class="flex items-center justify-between text-[11px] text-gray-500 pt-1 border-t border-pink-50">
                        <span class="font-mono">{{ formatSize(row.total_length || row.file_size) }}</span>
                        <span class="font-mono text-gray-400">{{ formatDate(row.created_at) }}</span>
                      </div>
                      <div class="flex items-center justify-end gap-2 pt-1" @click.stop>
                        <el-button
                          size="small"
                          circle
                          :icon="RefreshRight"
                          :loading="operationLoading"
                          :disabled="!row.gid && !row.source_url"
                          @click.stop="handleRetry(row)"
                          title="重试任务"
                        />
                        <el-button
                          size="small"
                          circle
                          type="danger"
                          :icon="Delete"
                          :loading="operationLoading"
                          @click.stop="handleDelete(row, true)"
                          title="删除记录与本地文件"
                        />
                      </div>
                    </div>
                  </div>

                  <!-- 桌面端表格 -->
                  <div class="hidden md:block">
                    <el-table
                      :data="group.downloads"
                      size="default"
                      style="width: 100%"
                      row-key="id"
                      @row-click="handleRowClick"
                      class="modern-task-table cursor-pointer"
                    >
                      <el-table-column prop="file_name" label="文件名" min-width="250" show-overflow-tooltip>
                        <template #default="{ row }">
                          <div class="file-name-cell">
                            <div class="file-type-icon" :style="{ color: getFileIcon(row.file_name).color }">
                              <component :is="getFileIcon(row.file_name).icon" />
                            </div>
                            <span class="file-name-text">{{ row.file_name || row.source_url?.substring(0, 40) || '未知文件' }}</span>
                          </div>
                        </template>
                      </el-table-column>
  
                      <el-table-column label="大小" width="120">
                        <template #default="{ row }">
                          <span class="font-mono text-xs font-medium text-gray-700">
                            {{ formatSize(row.total_length || row.file_size) }}
                          </span>
                        </template>
                      </el-table-column>
  
                      <el-table-column label="综合状态" width="130">
                        <template #default="{ row }">
                          <el-tag :type="getRecordStatusTagType(row)" size="small" round>
                            {{ getRecordStatusText(row) }}
                          </el-tag>
                          <el-tooltip
                            v-if="row.status === 'failed' && row.error_message"
                            :content="row.error_message"
                            placement="top"
                          >
                            <el-icon class="ml-1 cursor-pointer text-gray-400 hover:text-red-500">
                              <InfoFilled />
                            </el-icon>
                          </el-tooltip>
                        </template>
                      </el-table-column>
  
                      <el-table-column label="创建时间" width="160">
                        <template #default="{ row }">
                          <span class="text-xs text-gray-500 font-mono">{{ formatDate(row.created_at) }}</span>
                        </template>
                      </el-table-column>
  
                      <el-table-column label="操作" width="130" fixed="right">
                        <template #default="{ row }">
                          <div class="action-btn-group" @click.stop>
                            <el-button
                              size="small"
                              circle
                              :icon="RefreshRight"
                              :loading="operationLoading"
                              :disabled="!row.gid && !row.source_url"
                              @click.stop="handleRetry(row)"
                              title="重试任务"
                            />
                            <el-button
                              size="small"
                              circle
                              type="danger"
                              :icon="Delete"
                              :loading="operationLoading"
                              @click.stop="handleDelete(row, true)"
                              title="删除记录与本地文件"
                            />
                          </div>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>

    <!-- 文件详情对话框 -->
    <el-dialog
      v-model="detailDialogVisible"
      title="文件转存与上传详情"
      width="800px"
      :close-on-click-modal="true"
      :close-on-press-escape="true"
      class="file-detail-dialog"
      align-center
      destroy-on-close
    >
      <div v-if="selectedRecord" class="file-detail-content">
        <el-descriptions :column="1" border class="detail-descriptions">
          <el-descriptions-item label="文件名">
            <div class="flex items-center gap-2">
              <div class="file-type-icon" :style="{ color: getFileIcon(selectedRecord.file_name).color }">
                <component :is="getFileIcon(selectedRecord.file_name).icon" />
              </div>
              <span class="font-semibold text-gray-800 break-all">
                {{ selectedRecord.file_name || selectedRecord.source_url || '未知文件' }}
              </span>
            </div>
          </el-descriptions-item>

          <el-descriptions-item label="文件大小">
            <span class="font-mono">{{ formatSize(selectedRecord.total_length || selectedRecord.file_size) }}</span>
          </el-descriptions-item>

          <el-descriptions-item label="文件类型">
            <span v-if="selectedRecord.mime_type" class="font-mono text-xs">{{ selectedRecord.mime_type }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>

          <el-descriptions-item label="下载状态">
            <div class="flex items-center gap-2">
              <el-tag :type="getRecordStatusTagType(selectedRecord)" size="small" round>
                {{ getRecordStatusText(selectedRecord) }}
              </el-tag>
              <el-tooltip
                v-if="selectedRecord.status === 'failed' && selectedRecord.error_message"
                :content="selectedRecord.error_message"
                placement="top"
              >
                <el-icon class="cursor-pointer text-gray-400 hover:text-red-500"><InfoFilled /></el-icon>
              </el-tooltip>
            </div>
          </el-descriptions-item>

          <el-descriptions-item label="本地存储路径">
            <span v-if="selectedRecord.local_path" class="font-mono text-xs text-sky-700 break-all">{{ selectedRecord.local_path }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>

          <el-descriptions-item label="Telegram 上传">
            <div v-if="selectedRecord.uploads && selectedRecord.uploads.length > 0" class="space-y-2">
              <div v-for="upload in selectedRecord.uploads" :key="upload.id" class="p-2.5 rounded-xl bg-gray-50 border border-gray-100 space-y-1">
                <div class="flex items-center gap-2">
                  <el-tag size="small" :type="getUploadTargetTagType(upload.upload_target)" round>
                    {{ getUploadTargetLabel(upload.upload_target) }}
                  </el-tag>
                  <el-tag :type="getUploadStatusTagType(upload.status)" size="small" round>
                    {{ getUploadStatusText(upload.status, upload.upload_target) }}
                  </el-tag>
                  <span v-if="upload.completed_at" class="text-xs text-gray-500 font-mono">
                    完成: {{ formatDate(upload.completed_at) }}
                  </span>
                </div>
                <div v-if="upload.error_message" class="text-xs text-red-500">
                  失败原因: {{ upload.error_message }}
                </div>
              </div>
            </div>
            <span v-else class="text-gray-400">无关联上传记录</span>
          </el-descriptions-item>

          <el-descriptions-item label="源 TG 消息">
            <div v-if="selectedRecord.chat_id && selectedRecord.message_id" class="flex items-center gap-2">
              <a
                :href="getTelegramUrl(selectedRecord.chat_id, selectedRecord.message_id)"
                target="_blank"
                rel="noopener noreferrer"
                class="text-sky-600 hover:text-sky-800 break-all text-xs font-mono flex items-center gap-1 transition-colors"
              >
                {{ getTelegramUrl(selectedRecord.chat_id, selectedRecord.message_id) }}
                <el-icon class="text-xs"><Link /></el-icon>
              </a>
            </div>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>

          <el-descriptions-item label="说明文本 (Caption)">
            <span v-if="selectedRecord.caption" class="text-sm text-gray-700 whitespace-pre-wrap">{{ selectedRecord.caption }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>

          <el-descriptions-item label="时间记录">
            <div class="text-xs space-y-1 text-gray-600 font-mono">
              <div>创建: {{ formatDate(selectedRecord.created_at) }}</div>
              <div v-if="selectedRecord.completed_at">完成: {{ formatDate(selectedRecord.completed_at) }}</div>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <template #footer>
        <div class="dialog-footer-actions">
          <el-button
            type="primary"
            plain
            :icon="Folder"
            @click="jumpToDrive(selectedRecord?.file_name)"
            title="在 TG 网盘中定位此文件"
          >
            在 TG 网盘中定位
          </el-button>
          <el-button @click="detailDialogVisible = false" type="primary">
            关闭
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete,
  Document,
  Download,
  Files,
  Folder,
  Headset,
  InfoFilled,
  Link,
  List,
  Loading,
  Picture,
  RefreshRight,
  Search,
  Upload,
  VideoPlay,
  Warning,
} from '@element-plus/icons-vue'
import { useIntervalFn } from '@vueuse/core'
import {
  deleteAllDownloads,
  deleteDownload,
  deleteDownloadRecord,
  deleteUpload,
  getDownloads,
  getQueue,
  getUploads,
  retryDownload,
  retryUpload,
} from '@/api'
import type { DownloadGroup, DownloadRecord, UploadRecord } from '@/types/api'
import { wsClient } from '@/utils/websocket'
import {
  formatDate,
  formatSize,
  getProgress,
  getStatusTagType,
  getStatusText,
} from '@/utils/formatters'

const route = useRoute()
const router = useRouter()

type TaskCenterTab = 'download' | 'upload' | 'queue' | 'records'
const validTabs: TaskCenterTab[] = ['download', 'upload', 'queue', 'records']
const initialTab = typeof route.query.tab === 'string' && validTabs.includes(route.query.tab as TaskCenterTab)
  ? route.query.tab as TaskCenterTab
  : 'download'
const activeTab = ref<TaskCenterTab>(initialTab)

const groups = ref<DownloadGroup[]>([])
const uploads = ref<UploadRecord[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)
const limit = ref(100)
const activeGroups = ref<string[]>([])
const detailDialogVisible = ref(false)
const selectedRecord = ref<DownloadRecord | null>(null)
const autoDeleteAfterUpload = ref<boolean>(true)
const operationLoading = ref(false)
const queueData = ref<any>(null)
const queueLoading = ref(false)
const queueAutoRefresh = ref(true)

// 记录页专用快筛
const recordSearch = ref('')
const recordStatusFilter = ref<'' | 'active' | 'completed' | 'failed'>('')

watch(() => route.query.tab, (tab) => {
  if (typeof tab === 'string' && validTabs.includes(tab as TaskCenterTab)) {
    activeTab.value = tab as TaskCenterTab
  }
})

// 文件图标与主题色计算
function getFileIcon(fileName?: string): { icon: any; color: string } {
  const name = (fileName || '').toLowerCase()
  if (name.match(/\.(mp4|mkv|avi|mov|wmv|flv|webm|m4v|mpg|mpeg)$/)) {
    return { icon: VideoPlay, color: '#0284c7' }
  }
  if (name.match(/\.(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/)) {
    return { icon: Picture, color: '#ec4899' }
  }
  if (name.match(/\.(mp3|flac|wav|m4a|aac|ogg|opus)$/)) {
    return { icon: Headset, color: '#8b5cf6' }
  }
  if (name.match(/\.(zip|rar|7z|tar|gz|bz2|xz)$/)) {
    return { icon: Folder, color: '#f59e0b' }
  }
  return { icon: Document, color: '#64748b' }
}

// 扩展状态文本和标签类型函数
function getStatusTextWithSkip(status?: string, errorMessage?: string): string {
  if (status === 'failed' && errorMessage && errorMessage.includes('跳过')) {
    return '已跳过'
  }
  return getStatusText(status)
}

function getStatusTagTypeWithSkip(status?: string, errorMessage?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'failed' && errorMessage && errorMessage.includes('跳过')) {
    return 'info'
  }
  return getStatusTagType(status)
}

function getRecordStatusText(record: DownloadRecord): string {
  if (record.status === 'failed') {
    if (record.error_message && record.error_message.includes('跳过')) {
      return '已跳过'
    }
    return '失败'
  }

  if (record.status === 'downloading' || record.status === 'pending') {
    return '下载中'
  }

  if (record.status === 'completed') {
    if (record.uploads && record.uploads.length > 0) {
      const hasUploading = record.uploads.some(u =>
        u.status === 'uploading' || u.status === 'pending' || u.status === 'waiting_download'
      )
      if (hasUploading) return '上传中'

      const hasFailed = record.uploads.some(u => u.status === 'failed')
      if (hasFailed) {
        const hasCompleted = record.uploads.some(u => u.status === 'completed')
        return hasCompleted ? '部分失败' : '失败'
      }

      const allCompleted = record.uploads.every(u =>
        u.status === 'completed' || u.status === 'failed'
      )

      if (allCompleted) {
        if (autoDeleteAfterUpload.value) {
          const hasUncleaned = record.uploads.some(u =>
            u.status === 'completed' && !u.cleaned_at
          )
          if (hasUncleaned) return '清理中'
        }
        return '已完成'
      }
      return '上传中'
    }
    return '已完成'
  }

  return getStatusText(record.status)
}

function getRecordStatusTagType(record: DownloadRecord): 'success' | 'warning' | 'danger' | 'info' {
  if (record.status === 'failed') {
    if (record.error_message && record.error_message.includes('跳过')) return 'info'
    return 'danger'
  }
  if (record.status === 'downloading' || record.status === 'pending') return 'warning'

  if (record.status === 'completed') {
    if (record.uploads && record.uploads.length > 0) {
      const hasUploading = record.uploads.some(u =>
        u.status === 'uploading' || u.status === 'pending' || u.status === 'waiting_download'
      )
      if (hasUploading) return 'warning'

      const hasFailed = record.uploads.some(u => u.status === 'failed')
      if (hasFailed) return 'danger'

      const allCompleted = record.uploads.every(u =>
        u.status === 'completed' || u.status === 'failed'
      )
      if (allCompleted) {
        if (autoDeleteAfterUpload.value) {
          const hasUncleaned = record.uploads.some(u =>
            u.status === 'completed' && !u.cleaned_at
          )
          if (hasUncleaned) return 'warning'
        }
        return 'success'
      }
      return 'warning'
    }
    return 'success'
  }
  return getStatusTagType(record.status)
}

type ActiveDownloadRow = DownloadRecord & {
  group_key: string
  group_title: string
}

function getGroupTitle(group: DownloadGroup): string {
  if (group.caption) return truncateText(group.caption, 50)
  const typeText = group.group_type === 'media_group' ? '媒体组相册' : '频道消息'
  const msg = group.message_id ? ` #${group.message_id}` : ''
  return `${typeText}${msg}`
}

function stableSortDownloads(a: ActiveDownloadRow, b: ActiveDownloadRow): number {
  const aTime = new Date(a.created_at || 0).getTime()
  const bTime = new Date(b.created_at || 0).getTime()
  if (aTime !== bTime) {
    return aTime - bTime
  }
  return (a.id || 0) - (b.id || 0)
}

const activeDownloads = computed<ActiveDownloadRow[]>(() => {
  const rows: ActiveDownloadRow[] = []
  for (const group of groups.value) {
    for (const d of group.downloads || []) {
      if (d.status === 'downloading' || d.status === 'pending') {
        rows.push({
          ...d,
          group_key: group.group_key,
          group_title: getGroupTitle(group)
        })
      }
    }
  }
  const sorted = [...rows]
  sorted.sort(stableSortDownloads)
  return sorted
})

const totalDownloadSpeed = computed(() => {
  return activeDownloads.value.reduce((acc, row) => acc + (row.download_speed || 0), 0)
})

function openGroupForActiveRow(row: ActiveDownloadRow) {
  activeTab.value = 'records'
  activeGroups.value = [row.group_key]
}

function stableSortUploads(a: UploadRecord, b: UploadRecord): number {
  const aTime = new Date(a.created_at || 0).getTime()
  const bTime = new Date(b.created_at || 0).getTime()
  if (aTime !== bTime) {
    return aTime - bTime
  }
  return (a.id || 0) - (b.id || 0)
}

const activeUploads = computed<UploadRecord[]>(() => {
  const filtered = uploads.value.filter(u => u.status === 'uploading' || u.status === 'pending' || u.status === 'waiting_download')
  const sorted = [...filtered]
  sorted.sort(stableSortUploads)
  return sorted
})

const totalUploadSpeed = computed(() => {
  return activeUploads.value.reduce((acc, row) => acc + (row.upload_speed || 0), 0)
})

const currentProcessing = computed(() => queueData.value?.current_processing || null)
const waitingItems = computed(() => queueData.value?.waiting_items || [])
const queueSize = computed(() => queueData.value?.queue_size || waitingItems.value.length || 0)

const failedDownloadsCount = computed(() => {
  let count = 0
  for (const group of groups.value) {
    count += (group.stats?.failed || 0)
  }
  return count
})

// 过滤后的记录列表
const filteredGroups = computed(() => {
  let list = groups.value
  const kw = recordSearch.value.trim().toLowerCase()

  if (recordStatusFilter.value === 'active') {
    list = list.filter(g => (g.stats.downloading || 0) > 0 || (g.stats.pending || 0) > 0)
  } else if (recordStatusFilter.value === 'completed') {
    list = list.filter(g => {
      const realFailed = (g.stats.failed || 0) - (g.stats.skipped || 0)
      return realFailed === 0 && (g.stats.downloading || 0) === 0 && (g.stats.pending || 0) === 0 && (g.stats.completed || 0) > 0
    })
  } else if (recordStatusFilter.value === 'failed') {
    list = list.filter(g => {
      const realFailed = (g.stats.failed || 0) - (g.stats.skipped || 0)
      return realFailed > 0
    })
  }

  if (kw) {
    list = list.filter(g => {
      if (g.caption && g.caption.toLowerCase().includes(kw)) return true
      if (String(g.message_id || '').includes(kw)) return true
      if (g.group_key && g.group_key.toLowerCase().includes(kw)) return true
      if (g.downloads && g.downloads.some(d => (d.file_name || '').toLowerCase().includes(kw))) return true
      return false
    })
  }

  return list
})

function fetchQueue() {
  queueLoading.value = true
  getQueue()
    .then(data => {
      if (data.success) {
        queueData.value = data
      }
    })
    .catch(err => console.error('获取队列状态失败:', err))
    .finally(() => {
      queueLoading.value = false
    })
}

function toggleQueueAutoRefresh() {
  queueAutoRefresh.value = !queueAutoRefresh.value
  if (queueAutoRefresh.value) {
    resumeQueueRefresh()
    fetchQueue()
  } else {
    pauseQueueRefresh()
  }
}

function fetchUploads() {
  getUploads(limit.value)
    .then(response => {
      if (response.success) {
        uploads.value = response.data || []
      }
    })
    .catch(err => {
      console.error('获取上传记录失败:', err)
    })
}

function fetchDownloads() {
  isLoading.value = true
  error.value = null
  getDownloads(limit.value, true)
    .then(response => {
      if (response.success && response.grouped) {
        groups.value = (response.data as DownloadGroup[]) || []
        if (groups.value.length > 0 && activeGroups.value.length === 0) {
          activeGroups.value = [groups.value[0].group_key]
        }
      } else {
        error.value = '获取数据失败'
      }
    })
    .catch(err => {
      error.value = err.message || '未知错误'
      console.error('获取下载记录失败:', err)
    })
    .finally(() => {
      isLoading.value = false
    })
}

function handleRefresh() {
  fetchDownloads()
  fetchUploads()
  fetchQueue()
}

function handleLimitChange() {
  handleRefresh()
}

function getGroupProgress(stats: DownloadGroup['stats']): number {
  if (stats.total_size === 0) return 0
  return Math.round((stats.completed_size / stats.total_size) * 100)
}

function getGroupStatus(stats: DownloadGroup['stats']): 'success' | 'exception' | 'warning' {
  const realFailed = (stats.failed || 0) - (stats.skipped || 0)
  if (realFailed > 0) return 'exception'
  if (stats.downloading > 0 || stats.pending > 0) return 'warning'
  return 'success'
}

function truncateText(text: string, maxLength: number): string {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

function formatSpeed(speed?: number): string {
  if (!speed || speed === 0) return '-'
  return formatSize(speed) + '/s'
}

function getProgressStatus(status?: string): 'success' | 'exception' | 'warning' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return 'warning'
}

function isDeprecatedUploadTarget(target?: string): boolean {
  return target === 'onedrive' || target === 'gdrive'
}

function getUploadTargetLabel(target?: string): string {
  if (target === 'telegram') return 'Telegram'
  if (isDeprecatedUploadTarget(target)) return '历史第三方网盘'
  return target || '未知'
}

function getUploadTargetTagType(target?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (target === 'telegram') return 'success'
  if (isDeprecatedUploadTarget(target)) return 'info'
  return 'warning'
}

function getUploadStatusText(status?: string, target?: string): string {
  if (!status) return '未知'
  const statusMap: Record<string, string> = {
    pending: '等待中',
    waiting_download: '等待下载',
    uploading: '上传中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    paused: '已暂停',
  }
  const statusText = statusMap[status] || status
  if (target && status === 'uploading') {
    const targetMap: Record<string, string> = {
      onedrive: '历史第三方网盘',
      gdrive: '历史第三方网盘',
      telegram: 'Telegram',
    }
    return `${statusText} (${targetMap[target] || target})`
  }
  return statusText
}

function getUploadStatusTagType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (!status) return 'info'
  if (status === 'completed') return 'success'
  if (status === 'uploading') return 'warning'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  return 'info'
}

function getUploadProgress(totalSize?: number, uploadedSize?: number): number {
  if (!totalSize || totalSize === 0 || !uploadedSize) return 0
  return Math.round((uploadedSize / totalSize) * 100)
}

function getTelegramUrl(chatId?: number, messageId?: number): string {
  if (!chatId || !messageId) return ''
  let urlChatId = chatId.toString()
  if (urlChatId.startsWith('-100')) {
    urlChatId = urlChatId.substring(4)
  }
  return `https://t.me/c/${urlChatId}/${messageId}`
}

function handleRowClick(row: DownloadRecord) {
  selectedRecord.value = row
  detailDialogVisible.value = true
}

function jumpToDrive(fileName?: string) {
  detailDialogVisible.value = false
  router.push({
    path: '/drive',
    query: fileName ? { search: fileName } : {},
  })
}

async function handleRetry(task: DownloadRecord) {
  if (!task.gid && !task.source_url) {
    ElMessage.warning('任务 GID 和源 URL 都不存在，无法重试')
    return
  }

  try {
    operationLoading.value = true
    if (task.gid) {
      const result = await retryDownload(task.gid)
      if (result.success) {
        ElMessage.success(result.message || '任务已重新提交到 Aria2')
        fetchDownloads()
      } else {
        ElMessage.error(result.error || '重试失败')
      }
    } else if (task.source_url) {
      ElMessage.warning('该任务没有 GID，无法直接重试')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '重试失败')
  } finally {
    operationLoading.value = false
  }
}

async function handleRetryAllFailed() {
  const failedTasks: DownloadRecord[] = []
  for (const group of groups.value) {
    for (const d of group.downloads || []) {
      if (d.status === 'failed' && d.gid) {
        failedTasks.push(d)
      }
    }
  }

  if (failedTasks.length === 0) {
    ElMessage.info('当前没有可重试的失败任务')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要批量重试全部 ${failedTasks.length} 个失败任务吗？`,
      '批量重试确认',
      { confirmButtonText: '确定重试', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  operationLoading.value = true
  let successCount = 0
  for (const task of failedTasks) {
    try {
      if (task.gid) {
        const res = await retryDownload(task.gid)
        if (res.success) successCount++
      }
    } catch {
      // continue
    }
  }
  operationLoading.value = false
  ElMessage.success(`已重新提交 ${successCount}/${failedTasks.length} 个任务`)
  fetchDownloads()
}

async function handleDelete(task: DownloadRecord, isRecordTab: boolean = false) {
  if (isRecordTab) {
    if (!task.id) {
      ElMessage.warning('下载记录 ID 不存在')
      return
    }

    ElMessageBox.confirm(
      `确定要删除记录 "${task.file_name || '未知文件'}" 吗？\n\n这将删除：\n• 数据库记录\n• 关联的上传记录\n• 本地文件（如果存在）`,
      '确认删除记录',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    ).then(async () => {
      try {
        operationLoading.value = true
        const result = await deleteDownloadRecord(task.id!, true)
        if (result.success) {
          ElMessage.success('记录已成功删除')
          fetchDownloads()
        } else {
          ElMessage.error(result.error || '删除失败')
        }
      } catch (error: any) {
        ElMessage.error(error.message || '删除失败')
      } finally {
        operationLoading.value = false
      }
    }).catch(() => {})
    return
  }

  if (!task.gid) {
    ElMessage.warning('任务 GID 不存在')
    return
  }

  ElMessageBox.confirm(
    `确定要删除下载任务 "${task.file_name || '未知文件'}" 吗？`,
    '确认删除',
    { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
  ).then(async () => {
    try {
      operationLoading.value = true
      const result = await deleteDownload(task.gid!)
      if (result.success) {
        ElMessage.success(result.message || '任务已删除')
        fetchDownloads()
      } else {
        ElMessage.error(result.error || '删除失败')
      }
    } catch (error: any) {
      ElMessage.error(error.message || '删除失败')
    } finally {
      operationLoading.value = false
    }
  }).catch(() => {})
}

async function handleRetryUpload(upload: UploadRecord) {
  if (!upload.id) {
    ElMessage.warning('上传任务 ID 不存在')
    return
  }

  try {
    operationLoading.value = true
    if (isDeprecatedUploadTarget(upload.upload_target)) {
      ElMessage.warning('历史第三方网盘上传目标已废弃，不能重试历史任务')
      return
    }

    const result = await retryUpload(upload.id)
    if (result.success) {
      ElMessage.success(result.message || '上传任务已重新提交 Telegram 上传')
      fetchUploads()
    } else {
      ElMessage.error(result.error || '重试失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '重试失败')
  } finally {
    operationLoading.value = false
  }
}

async function handleDeleteUpload(upload: UploadRecord) {
  if (!upload.id) {
    ElMessage.warning('上传任务 ID 不存在')
    return
  }

  ElMessageBox.confirm(
    '确定要删除上传任务吗？',
    '确认删除',
    { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
  ).then(async () => {
    try {
      operationLoading.value = true
      const result = await deleteUpload(upload.id!)
      if (result.success) {
        ElMessage.success(result.message || '上传任务已删除')
        fetchUploads()
      } else {
        ElMessage.error(result.error || '删除失败')
      }
    } catch (error: any) {
      ElMessage.error(error.message || '删除失败')
    } finally {
      operationLoading.value = false
    }
  }).catch(() => {})
}

function handleDeleteAll() {
  ElMessageBox.confirm(
    '确定要删除所有记录吗？\n\n这将清空全部下载、上传与转存记录。此操作不可恢复！',
    '确认清空记录',
    { confirmButtonText: '确定清空', cancelButtonText: '取消', type: 'warning' }
  ).then(() => {
    deleteAllDownloads()
      .then(response => {
        if (response.success) {
          ElMessage.success(response.message || '已清空所有记录')
          fetchDownloads()
          fetchUploads()
        } else {
          ElMessage.error(response.error || '删除失败')
        }
      })
      .catch(err => {
        console.error('删除所有记录失败:', err)
        ElMessage.error('删除失败: ' + (err.message || '未知错误'))
      })
  }).catch(() => {})
}

// WebSocket 实时更新
let wsUnsubscribers: (() => void)[] = []

const { pause, resume } = useIntervalFn(() => {
  fetchDownloads()
  fetchUploads()
}, 30000, { immediate: false })

const { pause: pauseQueueRefresh, resume: resumeQueueRefresh } = useIntervalFn(fetchQueue, 3000, { immediate: false })

function checkConnectionAndPoll() {
  if (!wsClient.isConnected()) {
    resume()
  } else {
    pause()
  }
}

onUnmounted(() => {
  pause()
  pauseQueueRefresh()
  wsUnsubscribers.forEach(unsub => unsub())
  wsUnsubscribers = []
})

onMounted(() => {
  autoDeleteAfterUpload.value = true

  fetchDownloads()
  fetchUploads()
  fetchQueue()
  if (queueAutoRefresh.value) {
    resumeQueueRefresh()
  }

  wsClient.connect()

  const unsubDownload = wsClient.on('download_update', (message) => {
    if (message.data) {
      updateDownloadFromWS(message.data)
    }
  })
  wsUnsubscribers.push(unsubDownload)

  const unsubUpload = wsClient.on('upload_update', (message) => {
    if (message.data) {
      updateUploadFromWS(message.data)
    }
  })
  wsUnsubscribers.push(unsubUpload)

  const unsubCleanup = wsClient.on('cleanup_update', (message) => {
    if (message.data && message.data.upload_id) {
      updateUploadFromWS({
        upload_id: message.data.upload_id,
        download_id: message.data.download_id,
        cleaned_at: message.data.cleaned_at,
      })
    }
  })
  wsUnsubscribers.push(unsubCleanup)

  const unsubInitial = wsClient.on('initial', (message) => {
    if (message.data) {
      fetchDownloads()
      fetchUploads()
    }
  })
  wsUnsubscribers.push(unsubInitial)

  const unsubConnect = wsClient.on('pong', () => {
    checkConnectionAndPoll()
  })
  wsUnsubscribers.push(unsubConnect)

  setTimeout(() => {
    checkConnectionAndPoll()
  }, 1000)
})

function updateDownloadFromWS(data: any) {
  const { gid, download_id, status, completed_length, total_length, download_speed, uploads: uploads_data } = data
  if (!gid && !download_id) return

  let found = false
  for (let groupIndex = 0; groupIndex < groups.value.length; groupIndex++) {
    const group = groups.value[groupIndex]
    if (!group.downloads) continue

    for (let downloadIndex = 0; downloadIndex < group.downloads.length; downloadIndex++) {
      const download = group.downloads[downloadIndex]
      const matches = (gid && download.gid === gid) || (!gid && download_id && download.id === download_id)

      if (matches) {
        const updates: Partial<DownloadRecord> = {}
        if (status !== undefined) updates.status = status
        if (completed_length !== undefined) updates.completed_length = completed_length
        if (total_length !== undefined) updates.total_length = total_length
        if (download_speed !== undefined) updates.download_speed = download_speed

        if (uploads_data && Array.isArray(uploads_data)) {
          if (!download.uploads) download.uploads = []
          for (const uploadUpdate of uploads_data) {
            const existingUploadIndex = download.uploads.findIndex((u: UploadRecord) => u.id === uploadUpdate.id)
            if (existingUploadIndex !== -1) {
              Object.assign(download.uploads[existingUploadIndex], uploadUpdate)
            } else {
              download.uploads.push(uploadUpdate as UploadRecord)
            }
          }
          download.uploads = download.uploads.filter((u: UploadRecord) =>
            uploads_data.some((ud: any) => ud.id === u.id)
          )
        }

        Object.assign(download, updates)
        updateGroupStats(group)
        found = true
        break
      }
    }
    if (found) break
  }

  if (!found && (gid || download_id)) {
    fetchDownloads()
  }
}

function updateUploadFromWS(data: any) {
  const { upload_id, download_id, status, uploaded_size, total_size, upload_speed, cleaned_at } = data
  if (!upload_id) return

  let found = false
  const uploadIndex = uploads.value.findIndex(u => u.id === upload_id)
  if (uploadIndex !== -1) {
    const upload = uploads.value[uploadIndex]
    const updates: Partial<UploadRecord> = {}
    if (status !== undefined) updates.status = status
    if (uploaded_size !== undefined) updates.uploaded_size = uploaded_size
    if (total_size !== undefined) updates.total_size = total_size
    if (upload_speed !== undefined) updates.upload_speed = upload_speed
    if (cleaned_at !== undefined) updates.cleaned_at = cleaned_at

    Object.assign(upload, updates)
    found = true
  }

  for (let groupIndex = 0; groupIndex < groups.value.length; groupIndex++) {
    const group = groups.value[groupIndex]
    if (!group.downloads) continue

    for (let downloadIndex = 0; downloadIndex < group.downloads.length; downloadIndex++) {
      const download = group.downloads[downloadIndex]

      if (download.id === download_id && download.uploads) {
        for (let uploadIndex = 0; uploadIndex < download.uploads.length; uploadIndex++) {
          const upload = download.uploads[uploadIndex]
          if (upload.id === upload_id) {
            const updates: Partial<UploadRecord> = {}
            if (status !== undefined) updates.status = status
            if (uploaded_size !== undefined) updates.uploaded_size = uploaded_size
            if (total_size !== undefined) updates.total_size = total_size
            if (upload_speed !== undefined) updates.upload_speed = upload_speed
            if (cleaned_at !== undefined) updates.cleaned_at = cleaned_at

            Object.assign(upload, updates)
            updateGroupStats(group)
            found = true
            break
          }
        }
        if (found) break
      }
    }
    if (found) break
  }

  if (!found && upload_id) {
    fetchUploads()
  }
}

function updateGroupStats(group: DownloadGroup) {
  if (!group.downloads || group.downloads.length === 0) return

  let total_files = 0
  let completed = 0
  let downloading = 0
  let failed = 0
  let pending = 0
  let skipped = 0
  let total_size = 0
  let completed_size = 0

  for (const download of group.downloads) {
    total_files++
    const downloadStatus = download.status || 'pending'
    const itemUploads = download.uploads || []

    const hasUploadActive = itemUploads.some(upload => upload.status === 'uploading')
    const hasUploadPending = itemUploads.some(upload => ['pending', 'waiting_download'].includes(upload.status || ''))
    const hasUploadFailed = itemUploads.some(upload => ['failed', 'cancelled'].includes(upload.status || ''))
    const hasUploadCleanupPending = itemUploads.some(upload => upload.status === 'completed' && !upload.cleaned_at)

    const isTrulyCompleted = () => {
      if (downloadStatus !== 'completed') return false
      if (itemUploads.length === 0) return true
      for (const upload of itemUploads) {
        if (upload.status !== 'completed' || !upload.cleaned_at) return false
      }
      return true
    }

    if (isTrulyCompleted()) {
      completed++
    } else if (downloadStatus === 'downloading' || hasUploadActive) {
      downloading++
    } else if (downloadStatus === 'failed' || hasUploadFailed) {
      failed++
    } else if (downloadStatus === 'pending' || hasUploadPending || hasUploadCleanupPending) {
      pending++
    } else if (downloadStatus === 'skipped' || (download.error_message && download.error_message.includes('跳过'))) {
      skipped++
    }

    const fileSize = download.total_length || download.file_size || 0
    total_size += fileSize

    if (isTrulyCompleted()) {
      completed_size += fileSize
    }
  }

  group.stats = {
    total_files,
    completed,
    downloading,
    failed,
    pending,
    skipped,
    total_size,
    completed_size,
  }
}
</script>

<style scoped>
.tasks-center-page {
  @apply space-y-6;
  max-width: 1400px;
  margin: 0 auto;
}

/* 头部卡片 */
.tasks-header-card {
  padding: 24px;
  border-radius: 20px;
}

.tasks-header-main {
  @apply flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6;
}

.tasks-title-row {
  @apply flex items-center gap-3 mb-1;
}

.tasks-title {
  @apply text-2xl md:text-3xl font-extrabold tracking-tight;
}

.tasks-badge {
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

.tasks-subtitle {
  @apply text-sm text-gray-500 max-w-2xl;
}

.tasks-header-actions {
  @apply flex items-center gap-2.5 flex-wrap;
}

.tasks-limit-select {
  width: 135px;
}

.tasks-limit-select :deep(.el-input__wrapper) {
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 0 0 1px rgba(255, 143, 171, 0.25) inset;
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.25s ease;
}

.auto-refresh-btn {
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: #0284c7;
}

.refresh-indicator {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: #cbd5e1;
  margin-right: 6px;
  transition: all 0.3s ease;
}

.refresh-indicator.is-active {
  background: #10b981;
  box-shadow: 0 0 8px #10b981;
}

.refresh-btn {
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.25);
  color: #4b5563;
}

.refresh-btn:hover {
  color: #ff7597;
  border-color: rgba(255, 117, 151, 0.5);
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.15);
}

.retry-all-btn {
  border-radius: 12px;
  font-weight: 600;
}

.delete-all-btn {
  border-radius: 12px;
  font-weight: 600;
}

/* 顶部流光指标卡片 */
.stats-row {
  margin-top: 10px;
}

.stat-card {
  @apply flex items-center gap-3.5 p-3.5 rounded-2xl cursor-pointer;
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
  border-color: rgba(255, 117, 151, 0.3);
}

.stat-card.is-active {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(255, 117, 151, 0.5);
  box-shadow: 0 8px 22px rgba(255, 117, 151, 0.18);
}

.stat-card.is-warning {
  border-color: #f59e0b;
  animation: pulseWarning 2s infinite;
}

@keyframes pulseWarning {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0); }
}

.stat-icon-wrapper {
  @apply w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 text-white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.stat-icon-download {
  background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%);
}

.stat-icon-upload {
  background: linear-gradient(135deg, #ec4899 0%, #ff7597 100%);
}

.stat-icon-queue {
  background: linear-gradient(135deg, #8b5cf6 0%, #a855f7 100%);
}

.stat-icon-records {
  background: linear-gradient(135deg, #10b981 0%, #14b8a6 100%);
}

.stat-info {
  @apply flex-1 min-w-0;
}

.stat-value {
  @apply text-lg font-bold leading-tight truncate;
}

.stat-value-records {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.stat-unit {
  font-size: 11px;
  font-weight: 500;
  color: #6b7280;
  margin-left: 2px;
}

.stat-label {
  @apply text-xs text-gray-500 mt-0.5 truncate font-medium;
}

/* 主内容卡片 */
.tasks-content-card {
  padding: 16px;
  border-radius: 20px;
}

/* 标签页现代 Segmented 胶囊设计 */
.tasks-modern-tabs :deep(.el-tabs__header) {
  margin: 0 0 16px 0;
  border-bottom: 1px solid rgba(255, 143, 171, 0.15);
}

.tasks-modern-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.tasks-modern-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 9999px;
  background: var(--gradient-primary);
}

.tasks-modern-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 600;
  color: #6b7280;
  padding: 0 20px;
  height: 44px;
  line-height: 44px;
  transition: all 0.25s ease;
}

.tasks-modern-tabs :deep(.el-tabs__item.is-active) {
  color: #ff7597;
}

.tab-label-inner {
  @apply flex items-center gap-2;
}

.tab-badge {
  font-size: 11px;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
}

/* 表格包装器与微质感 */
.tasks-table-wrapper {
  @apply overflow-hidden rounded-xl border border-gray-100;
  background: rgba(255, 255, 255, 0.5);
}

.modern-task-table {
  background: transparent !important;
}

.modern-task-table :deep(th.el-table__cell) {
  background: rgba(248, 250, 252, 0.8) !important;
  font-weight: 600;
  color: #475569;
  font-size: 12.5px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
}

.modern-task-table :deep(td.el-table__cell) {
  border-bottom: 1px solid rgba(241, 245, 249, 0.9);
  padding: 12px 0;
}

.modern-task-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: rgba(255, 117, 151, 0.04) !important;
}

.file-name-cell {
  @apply flex items-center gap-2.5;
}

.file-type-icon {
  @apply w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 text-base;
  background: rgba(0, 0, 0, 0.03);
}

.file-name-text {
  @apply font-medium text-gray-800 truncate;
}

.progress-cell {
  @apply pr-2;
}

.modern-progress :deep(.el-progress-bar__inner) {
  background: linear-gradient(90deg, #38bdf8 0%, #ff7597 100%) !important;
  border-radius: 9999px;
}

.speed-badge {
  @apply text-xs font-semibold px-2 py-0.5 rounded-md bg-sky-50 text-sky-600 border border-sky-200 inline-block;
}

.action-btn-group {
  @apply flex items-center gap-1.5;
}

.table-tip-bar {
  @apply flex items-center p-3 text-xs text-gray-500 bg-gray-50/70 border-t border-gray-100;
}

/* 队列样式 */
.queue-tab-content {
  @apply p-2 space-y-6;
}

.flood-wait-card {
  @apply p-4 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.1);
}

.flood-wait-header {
  @apply flex items-center justify-between pb-2 border-b border-amber-200/60 mb-2;
}

.flood-badge {
  @apply flex items-center gap-2 font-bold text-amber-800 text-sm;
}

.flood-timer {
  @apply text-xs font-bold px-2 py-1 rounded bg-amber-200 text-amber-900;
}

.flood-wait-body p {
  @apply text-xs text-amber-700 leading-relaxed;
}

.queue-section-title {
  @apply flex items-center justify-between font-bold text-gray-800 text-base mb-3;
}

.active-pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 9999px;
  background: #10b981;
  box-shadow: 0 0 10px #10b981;
}

.current-task-box {
  @apply flex items-start gap-4 p-4 rounded-2xl bg-white border border-sky-100;
  box-shadow: 0 4px 16px rgba(56, 189, 248, 0.08);
}

.current-task-badge {
  @apply flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-bold text-sky-700 bg-sky-100/70 border border-sky-200 flex-shrink-0;
}

.current-task-info {
  @apply flex-1 min-w-0;
}

.current-task-title {
  @apply font-bold text-gray-800 text-base mb-2 break-all;
}

.current-task-tags {
  @apply flex items-center gap-2 flex-wrap;
}

.waiting-list {
  @apply grid grid-cols-1 md:grid-cols-2 gap-3;
}

.waiting-item-card {
  @apply flex items-center gap-3 p-3.5 rounded-xl bg-white border border-gray-100;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
}

.waiting-item-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.05);
  border-color: rgba(255, 143, 171, 0.3);
}

.waiting-order-badge {
  @apply w-9 h-9 rounded-xl flex items-center justify-center font-bold text-sm bg-purple-50 text-purple-600 border border-purple-200 flex-shrink-0;
}

.waiting-item-main {
  @apply flex-1 min-w-0;
}

.waiting-item-title {
  @apply text-sm font-semibold text-gray-800 truncate mb-1;
}

.waiting-item-meta {
  @apply flex items-center gap-2 flex-wrap;
}

/* 记录筛选工具栏 */
.records-filter-toolbar {
  @apply flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 p-2;
}

.record-search-input {
  max-width: 380px;
}

.record-search-input :deep(.el-input__wrapper) {
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 0 0 1px rgba(255, 143, 171, 0.25) inset;
}

.record-filter-pills {
  @apply flex items-center gap-1.5 flex-wrap;
}

.filter-pill {
  @apply px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all;
  background: rgba(255, 255, 255, 0.7);
  border-color: rgba(226, 232, 240, 0.9);
  color: #64748b;
  cursor: pointer;
}

.filter-pill:hover {
  color: #ff7597;
  border-color: rgba(255, 117, 151, 0.4);
}

.filter-pill.is-active {
  background: var(--gradient-primary);
  border-color: transparent;
  color: white;
  box-shadow: 0 2px 10px rgba(255, 117, 151, 0.3);
}

.filter-pill.pill-danger.is-active {
  background: #ef4444;
  box-shadow: 0 2px 10px rgba(239, 68, 68, 0.3);
}

/* 记录折叠面板 */
.modern-collapse {
  border: none;
  --el-collapse-header-bg-color: transparent;
}

.modern-collapse :deep(.el-collapse-item) {
  margin-bottom: 12px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02);
  overflow: hidden;
  transition: all 0.25s ease;
}

.modern-collapse :deep(.el-collapse-item:hover) {
  border-color: rgba(255, 117, 151, 0.3);
  box-shadow: 0 6px 18px rgba(255, 117, 151, 0.08);
}

.modern-collapse :deep(.el-collapse-item__header) {
  padding: 14px 18px;
  height: auto;
  border-bottom: 1px solid rgba(241, 245, 249, 0.8);
}

.modern-collapse :deep(.el-collapse-item__content) {
  padding: 0;
}

.group-header {
  @apply flex flex-col md:flex-row md:items-center justify-between gap-3 w-full pr-3;
}

.group-info {
  @apply flex items-center gap-3 min-w-0;
}

.group-icon-wrapper {
  @apply w-10 h-10 rounded-xl flex items-center justify-center text-white flex-shrink-0;
  background: var(--gradient-primary);
  box-shadow: 0 3px 10px rgba(255, 117, 151, 0.25);
}

.group-details {
  @apply min-w-0;
}

.group-title {
  @apply font-bold text-gray-800 text-sm truncate mb-1;
}

.group-meta {
  @apply flex items-center gap-1.5 flex-wrap text-xs text-gray-500;
}

.group-date {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 4px;
}

.group-progress-side {
  @apply flex items-center gap-3 flex-shrink-0;
}

.group-size {
  @apply text-xs font-semibold text-gray-700 min-w-[70px] text-right;
}

.group-downloads-inner {
  @apply p-2 bg-white/40;
}

/* 详情弹窗 */
.file-detail-content {
  @apply py-2;
}

.detail-descriptions :deep(.el-descriptions__label) {
  width: 140px;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
}

.dialog-footer-actions {
  @apply flex items-center justify-between w-full;
}

/* ========== 移动端响应式布局优化 ========== */
@media (max-width: 768px) {
  .tasks-center-page {
    padding: 0;
  }

  .tasks-header-card {
    padding: 14px;
    border-radius: 16px;
  }

  .tasks-header-main {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .tasks-header-actions {
    flex-wrap: wrap;
    width: 100%;
    gap: 8px;
  }

  .tasks-header-actions > * {
    flex: 1 1 calc(50% - 4px);
    margin-left: 0 !important;
  }

  .tasks-limit-select {
    width: 100%;
  }

  .stats-row {
    margin-top: 10px;
    margin-bottom: 12px;
  }

  .stat-card {
    padding: 10px 12px;
    gap: 10px;
  }

  .stat-icon-wrapper {
    width: 38px;
    height: 38px;
  }

  .stat-value {
    font-size: 16px;
  }

  .mobile-task-card {
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid rgba(255, 143, 171, 0.22);
    box-shadow: 0 4px 14px rgba(255, 117, 151, 0.08);
  }
}
</style>
