<template>
  <div
    class="drive-page animate-fade-in"
    @dragenter.prevent="handleDragEnter"
    @dragover.prevent="handleDragOver"
    @dragleave.prevent="handleDragLeave"
    @drop.prevent="handleDrop"
  >
    <!-- 拖拽上传全屏半透明毛玻璃蒙层 -->
    <transition name="fade">
      <div
        v-if="isDragOver"
        class="drive-drag-overlay animate-fade-in"
      >
        <div class="drag-overlay-content glass-card">
          <el-icon class="drag-icon"><UploadFilled /></el-icon>
          <h3 class="drag-title text-gradient-sakura">松开鼠标即可极速上传至 Telegram 网盘</h3>
          <p class="drag-desc">支持任意视频、音乐、图片与文档，5MB 切片并发直传，最高支持 2GB 大文件</p>
        </div>
      </div>
    </transition>
    <!-- 头部品牌与统计区 -->
    <div class="drive-header-card glass-card">
      <div class="drive-header-main">
        <div class="drive-title-group">
          <div class="drive-title-row">
            <h2 class="drive-title text-gradient-sakura">Telegram 频道网盘</h2>
            <span class="drive-badge">Cloud Storage</span>
          </div>
          <p class="drive-subtitle">
            TG 频道媒体资源仓库，支持在线流播、原图直链与批量管理。
          </p>
        </div>

        <div class="drive-header-actions">
          <!-- 缩略图预热胶囊徽标 / 按钮 -->
          <div
            v-if="thumbStatus"
            class="thumb-warmup-pill"
            :class="{ 'is-running': thumbStatus.running }"
            :title="thumbStatus.running ? `正在后台预生成缩略图 (当前 ID: ${thumbStatus.current_message_id || '处理中'})` : '点击一键重新预热所有媒体封面'"
            @click="handleTriggerWarmup"
          >
            <el-icon class="warmup-icon" :class="{ 'is-spinning': thumbStatus.running }">
              <Loading v-if="thumbStatus.running" />
              <Picture v-else />
            </el-icon>
            <span class="warmup-text">
              <template v-if="thumbStatus.running">
                封面预热中 {{ thumbStatus.cached }}/{{ thumbStatus.total }} ({{ thumbStatus.percent }}%)
              </template>
              <template v-else-if="thumbStatus.total > 0 && thumbStatus.cached >= thumbStatus.total">
                缩略图全部就绪
              </template>
              <template v-else>
                预热缩略图 {{ thumbStatus.cached }}/{{ thumbStatus.total }}
              </template>
            </span>
          </div>

          <!-- 边缘加速选路状态胶囊 -->
          <el-dropdown
            v-if="availableEdgeNodes.length > 0"
            trigger="click"
            @command="handleEdgeNodeChange"
          >
            <div
              class="edge-status-pill"
              :class="{ 'is-direct': selectedEdgeNodeId === 'direct' }"
              :title="`当前加速模式: ${currentEdgeNodeLabel}`"
            >
              <el-icon class="edge-icon"><Lightning /></el-icon>
              <span>{{ currentEdgeNodeLabel }}</span>
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu class="edge-node-menu">
                <el-dropdown-item command="auto">
                  <div class="edge-menu-item">
                    <div class="edge-menu-title">
                      <el-icon><Compass /></el-icon>
                      <span>智能自动优选 (推荐)</span>
                    </div>
                    <span class="edge-menu-tag">{{ bestEdgeNodeInfo }}</span>
                  </div>
                </el-dropdown-item>
                <el-dropdown-item
                  v-for="node in availableEdgeNodes"
                  :key="node.id"
                  :command="String(node.id)"
                >
                  <div class="edge-menu-item">
                    <div class="edge-menu-title">
                      <span class="node-status-dot" :class="node.status" />
                      <span>{{ node.node_name }}</span>
                      <el-tag v-if="node.is_dedicated" size="small" type="success" effect="dark" style="margin-left: 4px; font-size: 10px; height: 18px; padding: 0 4px;">专属</el-tag>
                      <el-tag v-else size="small" type="info" style="margin-left: 4px; font-size: 10px; height: 18px; padding: 0 4px;">共享</el-tag>
                    </div>
                    <span class="edge-menu-latency" v-if="edgeNodeLatencies[node.id]">
                      {{ Math.round(edgeNodeLatencies[node.id]) }} ms
                    </span>
                    <span class="edge-menu-dc" v-else-if="node.fastest_dc?.name && node.fastest_dc?.avg_rtt_ms !== undefined">
                      {{ (node.fastest_dc.name || '').split(' ')[0] }} {{ Math.round(node.fastest_dc.avg_rtt_ms) }}ms
                    </span>
                  </div>
                </el-dropdown-item>
                <el-dropdown-item divided command="direct">
                  <div class="edge-menu-item">
                    <div class="edge-menu-title">
                      <el-icon><OfficeBuilding /></el-icon>
                      <span>主控直连回源 (不走分流)</span>
                    </div>
                    <span class="edge-menu-hint">Master 直出</span>
                  </div>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-button
            type="primary"
            class="header-btn upload-btn"
            :icon="UploadFilled"
            @click="triggerUpload"
          >
            上传文件
          </el-button>
          <el-button
            type="primary"
            class="header-btn harvest-btn"
            :icon="Promotion"
            @click="openHarvesterDialog"
          >
            私密/受限频道采集
          </el-button>
          <el-button
            class="header-btn refresh-btn"
            :icon="RefreshRight"
            @click="refreshAll"
            :loading="loading"
          >
            刷新
          </el-button>
          <el-button
            class="header-btn"
            :icon="Download"
            @click="handleExportMyBackup"
            :loading="exportingMyBackup"
            title="导出当前租户全部关联频道的资产元数据备份 (JSON)"
          >
            备份资产
          </el-button>
          <el-button
            type="danger"
            class="header-btn clear-all-btn"
            :icon="Delete"
            @click="handleClearAll"
            :disabled="items.length === 0 && (!usageStats || usageStats.total_count === 0)"
          >
            清空 TG 网盘
          </el-button>
        </div>
      </div>

      <!-- 现代流光指标统计卡片 -->
      <el-row :gutter="14" class="stats-row">
        <!-- 卡片 1: 文件总数 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': typeFilter === '' }"
            @click="selectTypeFilter('')"
            title="查看全部文件"
          >
            <div class="stat-icon-wrapper stat-icon-files">
              <el-icon :size="22"><Files /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ usageStats?.total_count || 0 }}</div>
              <div class="stat-label">文件总数</div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 2: 占用空间 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card stat-card-size" title="云端累计占用体积">
            <div class="stat-icon-wrapper stat-icon-storage">
              <el-icon :size="22"><Coin /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-size">{{ formatBytes(usageStats?.total_size || 0) }}</div>
              <div class="stat-label">占用空间</div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 3: 视频 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': typeFilter === 'video' }"
            @click="selectTypeFilter('video')"
            title="筛选视频文件"
          >
            <div class="stat-icon-wrapper stat-icon-video">
              <el-icon :size="22"><VideoPlay /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ usageStats?.videos || 0 }}</div>
              <div class="stat-label">视频资源</div>
            </div>
          </div>
        </el-col>

        <!-- 卡片 4: 图片 -->
        <el-col :xs="12" :sm="6">
          <div
            class="stat-card"
            :class="{ 'is-active': typeFilter === 'image' }"
            @click="selectTypeFilter('image')"
            title="筛选图片相册"
          >
            <div class="stat-icon-wrapper stat-icon-image">
              <el-icon :size="22"><Picture /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ usageStats?.images || 0 }}</div>
              <div class="stat-label">图片相册</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 主操作与媒体内容展示卡片 -->
    <div class="drive-main-card glass-card">
      <!-- 工具控制栏 -->
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索文件名或描述"
            clearable
            class="search-input"
            :prefix-icon="Search"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          />
          <el-select
            v-model="typeFilter"
            placeholder="类型"
            class="type-select"
            @change="handleSearch"
          >
            <el-option label="全部" value="" />
            <el-option label="视频" value="video" />
            <el-option label="图片" value="image" />
            <el-option label="音频" value="audio" />
            <el-option label="文档" value="document" />
          </el-select>
          <el-select
            v-model="sortOption"
            class="sort-select"
            @change="handleSearch"
          >
            <el-option label="时间 新→旧" value="message_date-desc" />
            <el-option label="时间 旧→新" value="message_date-asc" />
            <el-option label="大小 大→小" value="file_size-desc" />
            <el-option label="大小 小→大" value="file_size-asc" />
            <el-option label="名称 A→Z" value="file_name-asc" />
            <el-option label="名称 Z→A" value="file_name-desc" />
          </el-select>
        </div>

        <div class="toolbar-right">
          <el-radio-group v-model="viewMode" class="view-mode-toggle">
            <el-radio-button label="list">
              <el-icon><List /></el-icon>
            </el-radio-button>
            <el-radio-button label="grid">
              <el-icon><Grid /></el-icon>
            </el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <!-- 媒体分类快捷药丸标签 -->
      <div class="quick-filter-pills">
        <button
          v-for="pill in typePillOptions"
          :key="pill.value"
          type="button"
          class="filter-pill"
          :class="{ 'is-active': typeFilter === pill.value }"
          @click="selectTypeFilter(pill.value)"
        >
          <el-icon class="pill-icon"><component :is="pill.icon" /></el-icon>
          <span class="pill-label">{{ pill.label }}</span>
          <span v-if="pill.count !== undefined" class="pill-count">{{ pill.count }}</span>
        </button>
      </div>

      <!-- 面包屑与路径状态栏 -->
      <div class="breadcrumb-bar">
        <el-button
          v-if="isInsideGroup"
          :icon="ArrowLeft"
          class="back-root-btn"
          text
          @click="goRoot"
        >
          返回根目录
        </el-button>
        <el-breadcrumb separator="/" class="drive-breadcrumb">
          <el-breadcrumb-item>
            <span class="breadcrumb-link" @click="goRoot">
              <el-icon class="breadcrumb-home-icon"><Folder /></el-icon>
              <span>TG网盘</span>
            </span>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-if="isInsideGroup">
            <span class="breadcrumb-current-group">
              <el-icon class="mr-1 text-sm"><FolderOpened /></el-icon>
              {{ currentFolderName }}
            </span>
          </el-breadcrumb-item>
        </el-breadcrumb>
        <div v-if="total > 0" class="items-total-pill">
          共 {{ total }} 项
        </div>
      </div>

      <!-- 批量选择与操作工具栏 -->
      <div v-if="items.length" class="selection-toolbar">
        <div class="selection-left">
          <el-checkbox
            :model-value="allPageSelected"
            :indeterminate="somePageSelected"
            :disabled="loading || batchDeleting"
            @change="toggleSelectPage(Boolean($event))"
          >
            全选本页
          </el-checkbox>
          <span class="selection-count">已选 {{ selectedItems.length }} 项</span>
        </div>
        <div v-if="selectedItems.length > 0" class="selection-actions">
          <el-button
            :icon="Download"
            class="batch-btn batch-download-btn"
            :disabled="selectedFiles.length === 0 || loading || batchDeleting"
            @click="handleBatchDownload"
          >
            下载文件<span v-if="selectedFiles.length">（{{ selectedFiles.length }}）</span>
          </el-button>
          <el-button
            :icon="Link"
            class="batch-btn batch-copy-btn"
            :disabled="selectedFiles.length === 0 || loading || batchDeleting"
            @click="handleBatchCopyStreamUrls"
          >
            复制直链<span v-if="selectedFiles.length">（{{ selectedFiles.length }}）</span>
          </el-button>
          <el-button
            :icon="List"
            class="batch-btn batch-m3u-btn"
            :disabled="selectedFiles.length === 0 || loading || batchDeleting"
            @click="handleExportM3U"
          >
            导出播放列表<span v-if="selectedFiles.length">（{{ selectedFiles.length }}）</span>
          </el-button>
          <el-button
            type="danger"
            class="batch-btn batch-delete-btn"
            :icon="Delete"
            :disabled="selectedItems.length === 0 || loading"
            :loading="batchDeleting"
            @click="handleBatchDelete"
          >
            批量删除<span v-if="selectedItems.length">（{{ selectedItems.length }}）</span>
          </el-button>
          <el-button
            v-if="selectedItems.length"
            text
            class="batch-cancel-btn"
            :disabled="batchDeleting"
            @click="clearSelection"
          >
            取消选择
          </el-button>
        </div>
      </div>

      <!-- 列表模式视图 (桌面端显示宽表格) -->
      <div v-if="viewMode === 'list'" class="table-container hidden md:block">
        <el-table
          :data="items"
          v-loading="loading"
          class="drive-table"
          @row-click="handleOpen"
          :row-style="{ cursor: 'pointer' }"
        >
          <el-table-column width="48" align="center">
            <template #header>
              <el-checkbox
                :model-value="allPageSelected"
                :indeterminate="somePageSelected"
                :disabled="loading || batchDeleting"
                aria-label="全选本页"
                @click.stop
                @change="toggleSelectPage(Boolean($event))"
              />
            </template>
            <template #default="{ row }">
              <el-checkbox
                :model-value="isSelected(row)"
                :disabled="batchDeleting"
                :aria-label="`选择 ${getFileName(row)}`"
                @click.stop="handleCheckboxClick(row, $event)"
                @change="toggleItemSelection(row, Boolean($event))"
              />
            </template>
          </el-table-column>

          <el-table-column label="名称" min-width="260">
            <template #default="{ row }">
              <div class="file-name">
                <span class="file-icon-badge" :class="getFileIconClass(row)">
                  <img
                    v-if="getThumbnailUrl(row) && !failedCovers.has(getItemKey(row))"
                    :src="getThumbnailUrl(row)"
                    :alt="getFileName(row)"
                    class="file-mini-thumb"
                    loading="lazy"
                    @error="markCoverFailed(row)"
                  />
                  <el-icon v-else :size="18">
                    <Folder v-if="isFolder(row)" />
                    <Picture v-else-if="isImage(row)" />
                    <VideoPlay v-else-if="isVideo(row)" />
                    <Headset v-else-if="isAudio(row)" />
                    <Document v-else />
                  </el-icon>
                </span>
                <span class="file-title" :title="getFileName(row)">{{ getFileName(row) }}</span>
                <span v-if="row.dc_id" class="dc-tag-inline">DC{{ row.dc_id }}</span>
                <el-tag v-if="isFolder(row)" size="small" class="album-tag">
                  {{ row.item_count || 0 }} 个文件
                </el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="类型" width="130">
            <template #default="{ row }">
              <span class="type-pill" :class="getTypeBadgeClass(row)">
                {{ getTypeLabel(row) }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="大小" width="130">
            <template #default="{ row }">
              <span class="size-text">{{ formatBytes(getDisplaySize(row)) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="内容" width="120">
            <template #default="{ row }">
              <span v-if="isFolder(row)" class="content-text">{{ row.item_count || 0 }} 个文件</span>
              <span v-else class="message-id-tag">#{{ row.message_id }}</span>
            </template>
          </el-table-column>

          <el-table-column label="时间" width="180">
            <template #default="{ row }">
              <span class="time-text">{{ formatDate(row.message_date) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="220" align="center">
            <template #default="{ row }">
              <div class="table-actions" @click.stop>
                <el-button
                  v-if="isFolder(row)"
                  type="primary"
                  link
                  class="action-link-btn"
                  :icon="Folder"
                  @click.stop="enterFolder(row)"
                >
                  打开
                </el-button>
                <el-button
                  v-else
                  type="primary"
                  link
                  class="action-link-btn"
                  :icon="View"
                  @click.stop="handlePreview(row)"
                >
                  预览
                </el-button>
                <el-button
                  v-if="isFile(row)"
                  type="info"
                  link
                  class="action-link-btn action-copy-link"
                  :icon="Link"
                  title="复制文件直链"
                  @click.stop="handleCopyStreamUrl(row)"
                >
                  直链
                </el-button>
                <el-button
                  v-if="isFile(row)"
                  type="success"
                  link
                  class="action-link-btn action-download"
                  :icon="Download"
                  @click.stop="handleDownload(row)"
                >
                  下载
                </el-button>
                <el-button
                  type="danger"
                  link
                  class="action-link-btn action-delete"
                  :icon="Delete"
                  @click.stop="handleDelete(row)"
                />
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 网格模式视图 (网格模式下常驻，列表模式下移动端自适应降级为触控卡片流) -->
      <div v-if="viewMode === 'grid' || true" v-loading="loading" class="grid-view" :class="{ 'md:hidden': viewMode === 'list' }">
        <div
          v-for="item in items"
          :key="getItemKey(item)"
          class="grid-item"
          :class="{ 'is-selected': isSelected(item) }"
          @click="handleOpen(item)"
        >
          <!-- 左上角勾选框 -->
          <el-checkbox
            class="grid-item-checkbox"
            :model-value="isSelected(item)"
            :disabled="batchDeleting"
            :aria-label="`选择 ${getFileName(item)}`"
            @click.stop="handleCheckboxClick(item, $event)"
            @change="toggleItemSelection(item, Boolean($event))"
          />

          <!-- 封面缩略图区域 -->
          <div class="grid-item-preview" :class="getCoverBgClass(item)">
            <img
              v-if="getThumbnailUrl(item) && !failedCovers.has(getItemKey(item))"
              :src="getThumbnailUrl(item)"
              :alt="getFileName(item)"
              loading="lazy"
              class="grid-thumbnail"
              @error="markCoverFailed(item)"
            />
            <div v-else class="grid-placeholder">
              <div class="placeholder-icon-halo">
                <el-icon :size="40">
                  <Folder v-if="isFolder(item)" />
                  <VideoPlay v-else-if="isVideo(item)" />
                  <Picture v-else-if="isImage(item)" />
                  <Headset v-else-if="isAudio(item)" />
                  <Document v-else />
                </el-icon>
              </div>
            </div>

            <!-- 右上角类型小徽章 -->
            <span class="type-badge" :class="getTypeBadgeClass(item)">
              {{ getTypeLabel(item) }}
            </span>
            <span v-if="item.dc_id" class="grid-dc-badge">DC{{ item.dc_id }}</span>

            <!-- 相册标志 -->
            <span v-if="isFolder(item)" class="grid-album-chip">
              <el-icon class="mr-1"><Folder /></el-icon>
              {{ item.item_count || 0 }}
            </span>

            <!-- 悬浮微操作栏 -->
            <div class="grid-card-overlay" @click.stop>
              <button
                v-if="isFolder(item)"
                class="overlay-action-btn"
                title="打开相册"
                @click.stop="enterFolder(item)"
              >
                <el-icon><FolderOpened /></el-icon>
              </button>
              <button
                v-else
                class="overlay-action-btn"
                title="预览"
                @click.stop="handlePreview(item)"
              >
                <el-icon><View /></el-icon>
              </button>
              <button
                v-if="isFile(item)"
                class="overlay-action-btn overlay-link"
                title="复制直链"
                @click.stop="handleCopyStreamUrl(item)"
              >
                <el-icon><Link /></el-icon>
              </button>
              <button
                v-if="isFile(item)"
                class="overlay-action-btn overlay-download"
                title="下载"
                @click.stop="handleDownload(item)"
              >
                <el-icon><Download /></el-icon>
              </button>
              <button
                class="overlay-action-btn overlay-delete"
                title="删除"
                @click.stop="handleDelete(item)"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>

          <!-- 卡片信息与底栏操作 -->
          <div class="grid-item-body">
            <div class="grid-item-name" :title="getFileName(item)">{{ getFileName(item) }}</div>
            <div class="grid-item-footer">
              <div class="grid-item-meta">
                <span v-if="isFolder(item)">{{ item.item_count || 0 }} 个文件 · {{ formatBytes(getDisplaySize(item)) }}</span>
                <span v-else>{{ formatBytes(getDisplaySize(item)) }} · #{{ item.message_id }}</span>
              </div>
              <div class="grid-item-actions" @click.stop>
                <button
                  v-if="isFolder(item)"
                  class="card-action-btn"
                  title="打开"
                  @click.stop="enterFolder(item)"
                >
                  <el-icon><FolderOpened /></el-icon>
                </button>
                <button
                  v-else
                  class="card-action-btn"
                  title="预览"
                  @click.stop="handlePreview(item)"
                >
                  <el-icon><View /></el-icon>
                </button>
                <button
                  v-if="isFile(item)"
                  class="card-action-btn card-action-link"
                  title="复制直链"
                  @click.stop="handleCopyStreamUrl(item)"
                >
                  <el-icon><Link /></el-icon>
                </button>
                <button
                  v-if="isFile(item)"
                  class="card-action-btn"
                  title="下载"
                  @click.stop="handleDownload(item)"
                >
                  <el-icon><Download /></el-icon>
                </button>
                <button
                  class="card-action-btn card-action-delete"
                  title="删除"
                  @click.stop="handleDelete(item)"
                >
                  <el-icon><Delete /></el-icon>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && items.length === 0" class="empty-state-box">
        <!-- 场景 1: 在媒体组内 -->
        <template v-if="isInsideGroup">
          <div class="empty-icon-halo">
            <el-icon :size="54"><FolderOpened /></el-icon>
          </div>
          <div class="empty-title">此媒体组暂无文件</div>
          <p class="empty-hint">可点击上方返回根目录查看其他资源</p>
          <div class="empty-actions">
            <el-button type="primary" :icon="ArrowLeft" @click="goRoot">
              返回根目录
            </el-button>
          </div>
        </template>

        <!-- 场景 2: 搜索或类型过滤无结果 -->
        <template v-else-if="typeFilter || searchKeyword">
          <div class="empty-icon-halo">
            <el-icon :size="54"><FolderOpened /></el-icon>
          </div>
          <div class="empty-title">未找到匹配的媒体文件</div>
          <p class="empty-hint">当前筛选条件未匹配到任何资产，请尝试重置筛选</p>
          <div class="empty-actions">
            <el-button :icon="RefreshRight" @click="resetFilters">
              重置筛选条件
            </el-button>
          </div>
        </template>

        <!-- 场景 3: 初始 0 资产状态（新人起航指引态） -->
        <template v-else>
          <div class="empty-onboarding-container glass-card">
            <div class="empty-icon-halo">
              <el-icon :size="48"><FolderOpened /></el-icon>
            </div>
            <div class="empty-title text-gradient-sakura">专属云盘虚位以待 · 开启首份资产入库</div>
            <p class="empty-hint">
              MistRelay 已为您配置同区 Telegram 独立物理隔离存储空间，媒体资产永久保存。即刻通过以下方式入库：
            </p>

            <div class="empty-methods-grid">
              <!-- 方式 0: 本地文件直接上传 -->
              <div class="empty-method-card">
                <div class="method-card-top">
                  <div class="method-icon-wrap icon-wrap--sakura">
                    <el-icon><UploadFilled /></el-icon>
                  </div>
                  <span class="method-card-badge method-card-badge--sakura">Web 直传</span>
                </div>
                <h4 class="method-card-title">本地文件直接上传</h4>
                <p class="method-card-desc">
                  从电脑或手机直接拖拽或批量选择文件，5MB 分片并发直传，全自动转存入库并生成流播预览。
                </p>
                <el-button
                  size="small"
                  type="primary"
                  class="method-card-btn upload-btn"
                  :icon="UploadFilled"
                  @click="triggerUpload"
                >
                  🚀 立即上传文件
                </el-button>
              </div>

              <!-- 方式 1: 机器人私聊 -->
              <div class="empty-method-card">
                <div class="method-card-top">
                  <div class="method-icon-wrap icon-wrap--primary">
                    <el-icon><Promotion /></el-icon>
                  </div>
                  <span class="method-card-badge">极速推荐</span>
                </div>
                <h4 class="method-card-title">Telegram 私聊直投</h4>
                <p class="method-card-desc">
                  向主控 Bot 发送或转发视频、图片、音频或文档，秒级存入专属频道并生成多 Bot 串流直链。
                </p>
                <el-button
                  size="small"
                  type="primary"
                  class="method-card-btn"
                  :icon="Promotion"
                  @click="openTelegramBot"
                >
                  🚀 私聊机器人
                </el-button>
              </div>

              <!-- 方式 2: Aria2 离线 -->
              <div class="empty-method-card">
                <div class="method-card-top">
                  <div class="method-icon-wrap icon-wrap--sky">
                    <el-icon><Download /></el-icon>
                  </div>
                  <span class="method-card-badge method-card-badge--sky">全速离线</span>
                </div>
                <h4 class="method-card-title">Aria2 磁力全速转存</h4>
                <p class="method-card-desc">
                  直接将磁力链接 (magnet:) 或直链发给机器人，千兆集群全天候离线下载完成后自动打包入库。
                </p>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  class="method-card-btn"
                  :icon="CopyDocument"
                  @click="copySampleMagnet"
                >
                  📋 复制磁力格式
                </el-button>
              </div>

              <!-- 方式 3: 私密采集 -->
              <div class="empty-method-card">
                <div class="method-card-top">
                  <div class="method-icon-wrap icon-wrap--purple">
                    <el-icon><MagicStick /></el-icon>
                  </div>
                  <span class="method-card-badge method-card-badge--purple">破除限制</span>
                </div>
                <h4 class="method-card-title">受限频道破除采集</h4>
                <p class="method-card-desc">
                  针对禁止保存或转发的群组/频道，全自动调动协议号阵列无痕洗白提取并转存至此。
                </p>
                <el-button
                  size="small"
                  type="success"
                  plain
                  class="method-card-btn"
                  :icon="MagicStick"
                  @click="openHarvesterDialog"
                >
                  🎯 打开采集器
                </el-button>
              </div>
            </div>

            <div class="empty-bottom-bar">
              <span class="empty-tip-text">💡 提示：在 Telegram 投递成功后，点击右侧按钮即可刷新呈现</span>
              <div class="empty-bottom-actions">
                <el-button
                  size="small"
                  class="guide-text-btn"
                  @click="openUserGuide('upload')"
                >
                  📖 查阅完整入库教程
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :icon="RefreshRight"
                  @click="refreshAll"
                  :loading="loading"
                >
                  刷新同步
                </el-button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 分页栏 -->
      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="loadItems"
          @size-change="handlePageSizeChange"
        />
      </div>
    </div>

    <!-- 图片全屏预览 -->
    <el-image-viewer
      v-if="showPreview && previewType === 'image'"
      :url-list="previewImageUrls.length > 0 ? previewImageUrls : [previewUrl]"
      :initial-index="previewImageIndex"
      @close="closePreview"
      hide-on-click-modal
    />

    <!-- 视频弹窗播放器 -->
    <el-dialog
      v-model="showPreview"
      v-if="previewType === 'video'"
      :show-close="false"
      append-to-body
      align-center
      destroy-on-close
      @close="closePreview"
      class="video-dialog glass-video-dialog"
      :class="{ 'is-web-fullscreen': isWebFullscreen }"
    >
      <template #header="{ close }">
        <div class="video-dialog-header">
          <div class="video-header-left">
            <span class="video-badge-icon">
              <el-icon :size="16"><VideoCamera /></el-icon>
            </span>
            <span class="video-header-title" :title="getFileName(previewItem)">
              {{ getFileName(previewItem) }}
            </span>
            <span v-if="currentPlayableIndex >= 0" class="video-header-pill">
              {{ currentPlayableIndex + 1 }} / {{ playableMediaList.length }}
            </span>
          </div>
          <div class="video-header-actions">
            <el-tooltip content="上一集 (←)" placement="bottom">
              <button
                class="header-tool-btn nav-media-btn btn-prev-media"
                type="button"
                :disabled="!hasPrevMedia"
                @click="playPrevMedia"
              >
                <el-icon :size="16"><ArrowLeft /></el-icon>
              </button>
            </el-tooltip>
            <el-tooltip content="下一集 (→)" placement="bottom">
              <button
                class="header-tool-btn nav-media-btn btn-next-media"
                type="button"
                :disabled="!hasNextMedia"
                @click="playNextMedia"
              >
                <el-icon :size="16"><ArrowRight /></el-icon>
              </button>
            </el-tooltip>

            <el-tooltip :content="isWebFullscreen ? '还原窗口' : '网页宽屏'" placement="bottom">
              <button
                class="header-tool-btn btn-web-fullscreen"
                type="button"
                @click="isWebFullscreen = !isWebFullscreen"
              >
                <el-icon :size="16">
                  <component :is="isWebFullscreen ? ScaleToOriginal : FullScreen" />
                </el-icon>
              </button>
            </el-tooltip>
            <el-tooltip content="关闭预览 (Esc)" placement="bottom">
              <button class="header-tool-btn btn-close" type="button" @click="close">
                <el-icon :size="18"><Close /></el-icon>
              </button>
            </el-tooltip>
          </div>
        </div>
      </template>

      <div class="video-container" :class="{ 'fullscreen-container': isWebFullscreen }" v-loading="!previewUrl" element-loading-text="正在优选边缘链路..." element-loading-background="rgba(0, 0, 0, 0.7)">
        <VideoPlayer
          ref="videoPlayerRef"
          v-if="previewUrl"
          :src="previewUrl"
          :type="getVideoType(previewItem)"
          @ended="handleMediaEnded"
          @error="handlePlayerError"
        />
      </div>

      <template #footer>
        <div class="dialog-footer-info">
          <div class="footer-meta-tags">
            <span v-if="previewItem && previewItem.dc_id" class="dc-tag-dialog">
              DC{{ previewItem.dc_id }}
            </span>
            <span class="file-size-tag">{{ formatBytes(getDisplaySize(previewItem!)) }}</span>
            <span v-if="previewItem && previewItem.mime_type" class="file-mime-tag">
              {{ previewItem.mime_type }}
            </span>
            <!-- 播放器内边缘加速胶囊 -->
            <el-dropdown
              v-if="availableEdgeNodes.length > 0"
              trigger="click"
              @command="handleEdgeNodeChange"
            >
              <span class="edge-routing-badge" :class="{ 'is-direct': selectedEdgeNodeId === 'direct' }">
                <el-icon><Lightning /></el-icon>
                <span>{{ currentEdgeNodeLabel }}</span>
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu class="edge-node-menu">
                  <el-dropdown-item command="auto">
                    <div class="edge-menu-item">
                      <div class="edge-menu-title">
                        <el-icon><Compass /></el-icon>
                        <span>智能自动优选 (推荐)</span>
                      </div>
                      <span class="edge-menu-tag">{{ bestEdgeNodeInfo }}</span>
                    </div>
                  </el-dropdown-item>
                  <el-dropdown-item
                    v-for="node in availableEdgeNodes"
                    :key="node.id"
                    :command="String(node.id)"
                  >
                    <div class="edge-menu-item">
                      <div class="edge-menu-title">
                        <span class="node-status-dot" :class="node.status" />
                        <span>{{ node.node_name }}</span>
                        <el-tag v-if="node.is_dedicated" size="small" type="success" effect="dark" style="margin-left: 4px; font-size: 10px; height: 18px; padding: 0 4px;">专属</el-tag>
                        <el-tag v-else size="small" type="info" style="margin-left: 4px; font-size: 10px; height: 18px; padding: 0 4px;">共享</el-tag>
                      </div>
                      <span class="edge-menu-latency" v-if="edgeNodeLatencies[node.id]">
                        {{ Math.round(edgeNodeLatencies[node.id]) }} ms
                      </span>
                      <span class="edge-menu-dc" v-else-if="node.fastest_dc?.name && node.fastest_dc?.avg_rtt_ms !== undefined">
                        {{ (node.fastest_dc.name || '').split(' ')[0] }} {{ Math.round(node.fastest_dc.avg_rtt_ms) }}ms
                      </span>
                    </div>
                  </el-dropdown-item>
                  <el-dropdown-item divided command="direct">
                    <div class="edge-menu-item">
                      <div class="edge-menu-title">
                        <el-icon><OfficeBuilding /></el-icon>
                        <span>主控直连回源 (不走分流)</span>
                      </div>
                      <span class="edge-menu-hint">Master 直出</span>
                    </div>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-tooltip content="播放完毕自动起播下一个视频" placement="top">
              <el-switch
                v-model="autoplayNext"
                inline-prompt
                active-text="连播"
                inactive-text="单集"
                class="autoplay-switch"
                size="small"
              />
            </el-tooltip>
          </div>
          <div class="footer-actions">
            <el-button
              class="footer-tool-btn copy-url-btn"
              :icon="Link"
              @click="handleCopyStreamUrl(previewItem!)"
            >
              复制直链
            </el-button>

            <el-dropdown trigger="click" @command="(cmd: any) => openExternalPlayer(cmd)">
              <el-button class="footer-tool-btn external-player-btn" :icon="Promotion">
                外部播放<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu class="external-player-menu">
                  <el-dropdown-item command="potplayer">
                    <div class="player-menu-item">
                      <span class="player-menu-title">PotPlayer</span>
                      <span class="player-menu-hint">Windows 原生播放器</span>
                    </div>
                  </el-dropdown-item>
                  <el-dropdown-item command="vlc">
                    <div class="player-menu-item">
                      <span class="player-menu-title">VLC Media Player</span>
                      <span class="player-menu-hint">全平台开源播放器</span>
                    </div>
                  </el-dropdown-item>
                  <el-dropdown-item command="iina">
                    <div class="player-menu-item">
                      <span class="player-menu-title">IINA</span>
                      <span class="player-menu-hint">macOS 现代化播放器</span>
                    </div>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <el-tooltip content="独立画中画小窗播放" placement="top">
              <el-button
                class="footer-tool-btn pip-btn"
                :icon="Monitor"
                @click="triggerPlayerPiP"
              >
                画中画
              </el-button>
            </el-tooltip>

            <el-button
              class="fullscreen-toggle-btn"
              :icon="FullScreen"
              @click="triggerPlayerFullscreen"
            >
              全屏播放
            </el-button>
            <el-button
              type="primary"
              class="download-action-btn primary-glow-btn"
              :icon="Download"
              @click="handleDownload(previewItem!)"
            >
              下载原视频
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 音频试听播放器 -->
    <el-dialog
      v-model="showPreview"
      v-if="previewType === 'audio'"
      :title="getFileName(previewItem)"
      append-to-body
      align-center
      destroy-on-close
      @close="closePreview"
      center
      class="audio-dialog glass-audio-dialog"
    >
      <div class="audio-player-container">
        <div class="audio-vinyl">
          <el-icon :size="48" class="audio-vinyl-icon"><Headset /></el-icon>
        </div>
        <div class="audio-name">{{ getFileName(previewItem) }}</div>
        <div class="audio-meta">{{ formatBytes(getDisplaySize(previewItem!)) }}</div>
        <audio
          :src="previewUrl"
          controls
          autoplay
          class="audio-native-player"
          @ended="handleMediaEnded"
        ></audio>
      </div>
      <template #footer>
        <div class="dialog-footer-info">
          <div class="footer-meta-tags">
            <el-tooltip content="播放完毕自动起播下一个音频" placement="top">
              <el-switch
                v-model="autoplayNext"
                inline-prompt
                active-text="连播"
                inactive-text="单集"
                class="autoplay-switch"
                size="small"
              />
            </el-tooltip>
          </div>
          <div class="footer-actions">
            <el-button class="footer-tool-btn" :icon="Link" @click="handleCopyStreamUrl(previewItem!)">
              复制直链
            </el-button>
            <el-button type="primary" :icon="Download" @click="handleDownload(previewItem!)">
              下载音频
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
    <!-- 私密/受限频道采集与无痕转存模态框 -->
    <el-dialog
      v-model="harvesterVisible"
      title="私密/受限频道采集与无痕转存"
      width="min(760px, 94vw)"
      class="harvester-dialog custom-glass-dialog"
      append-to-body
      destroy-on-close
      :close-on-click-modal="false"
    >
      <div class="harvester-body">
        <!-- 提示横幅 -->
        <div class="harvester-intro-banner">
          <div class="intro-icon-box">
            <el-icon :size="24"><Promotion /></el-icon>
          </div>
          <div class="intro-text">
            <div class="intro-title">协议号自动化双模采集流水线</div>
            <div class="intro-desc">
              支持私密频道（<code>https://t.me/c/...</code>）与公开频道单帖或连号区间。协议号自动入群、受限内容破除、第三方引流广告清洗，并秒传/转存至网盘。
            </div>
          </div>
        </div>

        <!-- 采集配置表单 -->
        <el-form label-position="top" class="harvester-form">
          <el-form-item label="私密频道邀请链接（可选，首次采集该私密频道时提供）">
            <el-input
              v-model="harvesterInviteLink"
              placeholder="https://t.me/+AbCdEf... 或 https://t.me/joinchat/... (已在群中可留空)"
              clearable
              :disabled="harvesterStatus?.status === 'running'"
            />
          </el-form-item>

          <el-form-item label="待采集帖子链接或连号区间（支持多行批量输入）" required>
            <el-input
              v-model="harvesterLinksText"
              type="textarea"
              :rows="4"
              placeholder="每行一条，支持私密链接与连号区间，例如：&#10;https://t.me/c/1998444696/100-120&#10;https://t.me/c/1998444696/135&#10;https://t.me/public_channel/50-60"
              :disabled="harvesterStatus?.status === 'running'"
            />
          </el-form-item>

          <el-row :gutter="14">
            <el-col :xs="24" :sm="14">
              <el-form-item label="调度协议号资产">
                <el-select
                  v-model="harvesterAccountId"
                  placeholder="自动智能轮询可用协议号"
                  clearable
                  style="width: 100%"
                  :disabled="harvesterStatus?.status === 'running'"
                >
                  <el-option :value="null" label="⚡ 智能自动调度（优先活跃协议号）" />
                  <el-option
                    v-for="acc in protocolAccounts"
                    :key="acc.id"
                    :value="acc.id"
                    :label="`${acc.phone} (${acc.status === 'active' ? '正常' : acc.status}) - ${acc.bot_count || 0} Bots`"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="10">
              <el-form-item label="无痕洗白与归属替换">
                <div class="rebrand-switch-wrapper">
                  <el-switch
                    v-model="harvesterRebrandEnabled"
                    active-text="启用"
                    inactive-text="原样"
                    :disabled="harvesterStatus?.status === 'running'"
                  />
                  <span class="rebrand-switch-hint">去转发标/清广告</span>
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <!-- 任务状态与实时终端 -->
        <div v-if="harvesterStatus && harvesterStatus.status !== 'idle'" class="harvester-status-panel">
          <div class="status-panel-header">
            <div class="status-panel-title">
              <span class="status-pulse-dot" :class="harvesterStatus.status"></span>
              <span class="status-title-text">
                <template v-if="harvesterStatus.status === 'running'">流水线正在采集中...</template>
                <template v-else-if="harvesterStatus.status === 'completed'">🎉 采集已完成</template>
                <template v-else-if="harvesterStatus.status === 'cancelled'">🛑 任务已中止</template>
                <template v-else-if="harvesterStatus.status === 'failed'">❌ 任务异常终止</template>
              </span>
            </div>
            <div class="status-panel-tags">
              <span
                v-if="harvesterStatus.current_mode === 'fast_copy'"
                class="harvester-mode-pill mode-fast"
              >
                ⚡ 零流量秒传
              </span>
              <span
                v-else-if="harvesterStatus.current_mode === 'restricted_relay'"
                class="harvester-mode-pill mode-relay"
              >
                🔓 受限破除重传
              </span>
              <span v-if="harvesterStatus.speed_text" class="harvester-speed-pill">
                {{ harvesterStatus.speed_text }}
              </span>
            </div>
          </div>

          <!-- 进度条 -->
          <div class="harvester-progress-wrapper">
            <el-progress
              :percentage="harvesterProgressPercent"
              :status="harvesterProgressStatus"
              :stroke-width="10"
              striped
              :striped-flow="harvesterStatus.status === 'running'"
            />
            <div class="harvester-progress-stats">
              <span>处理进度: {{ harvesterStatus.current_index }} / {{ harvesterStatus.total_messages }}</span>
              <span>
                成功: <b class="text-success">{{ harvesterStatus.success_count }}</b>
                &nbsp;|&nbsp;
                跳过: <b class="text-warning">{{ harvesterStatus.skipped_count }}</b>
                &nbsp;|&nbsp;
                失败: <b class="text-danger">{{ harvesterStatus.failed_count }}</b>
              </span>
            </div>
          </div>

          <!-- 正在处理文件名 -->
          <div v-if="harvesterStatus.current_file" class="harvester-current-file">
            <el-icon><Document /></el-icon>
            <span class="file-text">{{ harvesterStatus.current_file }}</span>
          </div>

          <!-- 暗色磨砂实时终端日志 -->
          <div class="harvester-terminal">
            <div class="terminal-bar">
              <div class="term-dots">
                <span class="dot dot-red"></span>
                <span class="dot dot-yellow"></span>
                <span class="dot dot-green"></span>
              </div>
              <span class="term-title">harvester-execution.log</span>
            </div>
            <div ref="terminalBodyRef" class="terminal-body">
              <div v-for="(log, idx) in harvesterStatus.logs" :key="idx" class="term-line">
                {{ log }}
              </div>
              <div v-if="harvesterStatus.logs.length === 0" class="term-line text-muted">
                等待任务启动输出...
              </div>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="harvester-footer">
          <div class="footer-left">
            <el-button
              v-if="harvesterStatus?.status === 'running'"
              type="danger"
              plain
              :icon="Close"
              @click="handleCancelHarvester"
              :loading="harvesterCancelling"
            >
              中止任务
            </el-button>
          </div>
          <div class="footer-right">
            <el-button @click="harvesterVisible = false">关闭窗口</el-button>
            <el-button
              v-if="harvesterStatus?.status === 'completed'"
              type="success"
              :icon="RefreshRight"
              @click="handleFinishAndRefresh"
            >
              完成并刷新网盘
            </el-button>
            <el-button
              v-else
              type="primary"
              class="start-harvest-btn"
              :icon="Promotion"
              :loading="harvesterStarting"
              :disabled="harvesterStatus?.status === 'running'"
              @click="handleStartHarvester"
            >
              开始采集入库
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 用户本地文件分片上传管理抽屉 -->
    <DriveUploadDrawer
      ref="uploadDrawerRef"
      @upload-success="handleUploadSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Close,
  Coin,
  CopyDocument,
  Delete,
  MagicStick,
  Document,
  Download,
  Files,
  Folder,
  FolderOpened,
  FullScreen,
  Grid,
  Headset,
  Link,
  List,
  Loading,
  Monitor,
  Picture,
  Lightning,
  Compass,
  OfficeBuilding,
  Promotion,
  RefreshRight,
  ScaleToOriginal,
  Search,
  VideoCamera,
  VideoPlay,
  View,
  UploadFilled,
} from '@element-plus/icons-vue'
import DriveUploadDrawer from '@/components/DriveUploadDrawer.vue'
import {
  api,
  browseTelegramDrive,
  exportMyTenantBackup,
  clearTelegramDrive,
  deleteTelegramBatch,
  deleteTelegramGroup,
  deleteTelegramItem,
  getTelegramThumbnailStatus,
  getTelegramUsage,
  getProtocolAccounts,
  startHarvesterTask,
  getHarvesterStatus,
  cancelHarvesterTask,
  isTelegramDriveFile,
  isTelegramDriveFolder,
  warmupTelegramThumbnails,
  getAvailableEdgeNodes,
  reportClientLatency,
  resolveEdgeStreamUrl,
  type AvailableEdgeNode,
  type HarvesterTaskStatus,
  type ProtocolAccount,
  type TelegramDriveFile,
  type TelegramDriveFolder,
  type TelegramDriveItem,
  type TelegramThumbnailStatus,
  type TelegramUsageStats,
} from '@/api'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { resolveServerUrl, toAbsoluteServerUrl } from '@/utils/runtime'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const exportingMyBackup = ref(false)
async function handleExportMyBackup() {
  exportingMyBackup.value = true
  try {
    ElMessage.info("正在导出当前租户资产元数据备份...")
    const res = await exportMyTenantBackup()
    const blob = new Blob([res.data], { type: "application/json" })
    const downloadUrl = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = downloadUrl
    const tenantName = authStore.user?.username || "tenant"
    link.download = `tenant_backup_${tenantName}_${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(downloadUrl)
    ElMessage.success("资产元数据备份已成功导出")
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || "导出备份失败")
  } finally {
    exportingMyBackup.value = false
  }
}

const items = ref<TelegramDriveItem[]>([])
const usageStats = ref<TelegramUsageStats | null>(null)
const botUsername = ref('')

async function fetchBotInfo() {
  try {
    const { data } = await api.get('/auth/bot-info')
    if (data?.success) {
      botUsername.value = data.bot_username || data.data?.bot_username || ''
    }
  } catch {
    // 忽略异常
  }
}

function openTelegramBot() {
  const url = botUsername.value ? `https://t.me/${botUsername.value}` : 'https://t.me'
  window.open(url, '_blank')
}

function copySampleMagnet() {
  const sample = 'magnet:?xt=urn:btih:d6b6e4e5e7fa9b2c8a1e3f5b7c9d0e1f2a3b4c5d&dn=SampleVideo_4K'
  copyToClipboard(sample, '磁力链接示例已复制，发给机器人即可全自动离线下载')
}

function openUserGuide(tab = 'upload') {
  window.dispatchEvent(new CustomEvent('open-user-guide', { detail: { tab } }))
}
const loading = ref(false)
const searchKeyword = ref('')
const typeFilter = ref('')
const sortOption = ref(localStorage.getItem('mistrelay.drive.sortOption') || 'message_date-desc')
watch(sortOption, val => {
  localStorage.setItem('mistrelay.drive.sortOption', val)
  handleSearch()
})

const currentPage = ref(1)
const pageSize = ref(Number(localStorage.getItem('mistrelay.drive.pageSize')) || 20)
watch(pageSize, val => localStorage.setItem('mistrelay.drive.pageSize', String(val)))

const total = ref(0)
const defaultViewMode = typeof window !== 'undefined' && window.innerWidth < 768 ? 'grid' : 'list'
const viewMode = ref<'list' | 'grid'>((localStorage.getItem('mistrelay.drive.viewMode') as any) || defaultViewMode)
watch(viewMode, val => localStorage.setItem('mistrelay.drive.viewMode', val))

const lastSelectedKey = ref<string | null>(null)
const autoplayNext = ref(localStorage.getItem('mistrelay.drive.autoplayNext') !== 'false')
watch(autoplayNext, val => localStorage.setItem('mistrelay.drive.autoplayNext', String(val)))
const showPreview = ref(false)
const previewItem = ref<TelegramDriveItem | null>(null)
const previewType = ref<'image' | 'video' | 'audio' | 'unknown'>('unknown')
const previewUrl = ref('')
const currentMediaGroupId = ref('')
const currentFolderName = ref('')
const selectedKeys = ref(new Set<string>())
const batchDeleting = ref(false)
const failedCovers = ref(new Set<string>())
const thumbStatus = ref<TelegramThumbnailStatus | null>(null)
const thumbVersion = ref(0)
const pollTimer = ref<any>(null)
const isWebFullscreen = ref(false)
const videoPlayerRef = ref<any>(null)

// ---------------------------------------------------------------------------
// 边缘 VPS 智能低延迟分流调度与节点管理
// ---------------------------------------------------------------------------
const availableEdgeNodes = ref<AvailableEdgeNode[]>([])
const selectedEdgeNodeId = ref<string>(localStorage.getItem('mistrelay.drive.edgeNodePref_v2') || 'auto')
const edgeNodeLatencies = ref<Record<number, number>>({})
const isProbingEdgeNodes = ref<boolean>(false)

async function resolvePlayUrl(item: TelegramDriveItem, preferredNode?: string): Promise<string> {
  if (!isFile(item) || !item.message_id) return getStreamUrl(item)
  const nodePref = preferredNode !== undefined ? preferredNode : selectedEdgeNodeId.value
  if (nodePref === 'direct') {
    return getStreamUrl(item)
  }
  try {
    const res = await resolveEdgeStreamUrl({
      message_id: item.message_id,
      hash: item.hash,
      preferred_node: nodePref,
    })
    if (res && res.success && res.url) {
      return res.url
    }
  } catch (err) {
    console.warn('解析边缘流播直链失败，回退主控直出:', err)
  }
  return getStreamUrl(item)
}

function handlePlayerError() {
  if (previewItem.value && previewUrl.value && !previewUrl.value.includes('direct=1')) {
    console.warn('边缘节点流播异常，自动降级回源主控直出...')
    ElMessage.warning('边缘节点网络波动，已自动切换为主控直出保底')
    const masterFallback = getStreamUrl(previewItem.value)
    if (masterFallback && masterFallback !== previewUrl.value) {
      previewUrl.value = masterFallback
    }
  }
}

watch(selectedEdgeNodeId, async (val) => {
  localStorage.setItem('mistrelay.drive.edgeNodePref_v2', val)
  if (showPreview.value && previewItem.value) {
    if (val === 'direct') {
      previewUrl.value = getStreamUrl(previewItem.value)
    } else {
      const edgeUrl = await resolvePlayUrl(previewItem.value, val)
      if (showPreview.value && previewItem.value) {
        previewUrl.value = edgeUrl
      }
    }
  }
})

const bestEdgeNodeInfo = computed(() => {
  if (!availableEdgeNodes.value.length) return '暂无节点'
  let bestWithLatency: { node: AvailableEdgeNode; latency: number } | null = null
  for (const node of availableEdgeNodes.value) {
    const lat = edgeNodeLatencies.value[node.id]
    if (lat !== undefined && lat > 0) {
      if (!bestWithLatency || lat < bestWithLatency.latency) {
        bestWithLatency = { node, latency: lat }
      }
    }
  }
  if (bestWithLatency) {
    return `${bestWithLatency.node.node_name} (${Math.round(bestWithLatency.latency)}ms)`
  }
  let bestDcNode: { node: AvailableEdgeNode; rtt: number } | null = null
  for (const node of availableEdgeNodes.value) {
    if (node.fastest_dc?.avg_rtt_ms) {
      if (!bestDcNode || node.fastest_dc.avg_rtt_ms < bestDcNode.rtt) {
        bestDcNode = { node, rtt: node.fastest_dc.avg_rtt_ms }
      }
    }
  }
  if (bestDcNode) {
    return `${bestDcNode.node.node_name} (~${Math.round(bestDcNode.rtt)}ms)`
  }
  return '自动分配'
})

const currentEdgeNodeLabel = computed(() => {
  if (selectedEdgeNodeId.value === 'direct') {
    return '主控直出'
  }
  if (selectedEdgeNodeId.value === 'auto' || !selectedEdgeNodeId.value) {
    return `自动 (${bestEdgeNodeInfo.value})`
  }
  const targetId = Number(selectedEdgeNodeId.value)
  const node = availableEdgeNodes.value.find(n => n.id === targetId)
  if (node) {
    const lat = edgeNodeLatencies.value[node.id]
    if (lat !== undefined && lat > 0) {
      return `${node.node_name} · ${Math.round(lat)}ms`
    }
    return node.node_name
  }
  return `自动 (${bestEdgeNodeInfo.value})`
})

function handleEdgeNodeChange(command: string) {
  selectedEdgeNodeId.value = command
  ElMessage.success(
    command === 'direct'
      ? '已切换为主控直连回源'
      : command === 'auto'
      ? `已切换为智能自动优选: ${bestEdgeNodeInfo.value}`
      : '已切换至指定加速节点'
  )
}

async function probeSingleNode(node: AvailableEdgeNode): Promise<number | null> {
  if (!node.ping_url) return null
  // 若主站通过 HTTPS 访问且边缘节点尚未启用 SSL（http://），跳过浏览器端直连 Fetch 以免产生 Mixed Content 拦截
  if (window.location.protocol === 'https:' && (!node.use_ssl || node.ping_url.startsWith('http:'))) {
    return null
  }
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 3500)
  const start = performance.now()
  try {
    const resp = await fetch(node.ping_url, {
      method: 'GET',
      mode: 'cors',
      cache: 'no-store',
      signal: controller.signal,
    })
    clearTimeout(timeoutId)
    if (resp.ok) {
      const end = performance.now()
      return Math.round(end - start)
    }
  } catch {
    clearTimeout(timeoutId)
  }
  return null
}

async function loadAndProbeEdgeNodes() {
  try {
    const res = await getAvailableEdgeNodes()
    if (res && res.success && Array.isArray(res.nodes)) {
      availableEdgeNodes.value = res.nodes
      for (const node of res.nodes) {
        if (node.rtt_ms && node.rtt_ms > 0 && !edgeNodeLatencies.value[node.id]) {
          edgeNodeLatencies.value[node.id] = node.rtt_ms
        }
      }
      if (selectedEdgeNodeId.value !== 'auto' && selectedEdgeNodeId.value !== 'direct') {
        const exists = res.nodes.some(n => String(n.id) === selectedEdgeNodeId.value)
        if (!exists) {
          selectedEdgeNodeId.value = 'auto'
        }
      }
      if (res.nodes.length > 0 && !isProbingEdgeNodes.value) {
        isProbingEdgeNodes.value = true
        const latencyReports: Array<{ node_id: number; rtt_ms: number }> = []

        await Promise.all(
          res.nodes.map(async (node) => {
            const rtt = await probeSingleNode(node)
            if (rtt !== null && rtt > 0) {
              edgeNodeLatencies.value[node.id] = rtt
              latencyReports.push({ node_id: node.id, rtt_ms: rtt })
            }
          })
        )
        isProbingEdgeNodes.value = false

        if (latencyReports.length > 0) {
          reportClientLatency(latencyReports).catch(() => {})
        }
      }
    }
  } catch (err) {
    console.warn('加载边缘节点失败:', err)
  }
}

function triggerPlayerFullscreen() {
  if (videoPlayerRef.value && typeof videoPlayerRef.value.toggleFullscreen === 'function') {
    videoPlayerRef.value.toggleFullscreen()
  }
}

const isInsideGroup = computed(() => Boolean(currentMediaGroupId.value))
const selectedItems = computed(() => items.value.filter(item => selectedKeys.value.has(getItemKey(item))))
const selectedFiles = computed(() => selectedItems.value.filter(isFile))
const allPageSelected = computed(() => (
  items.value.length > 0 && items.value.every(item => selectedKeys.value.has(getItemKey(item)))
))
const somePageSelected = computed(() => (
  selectedItems.value.length > 0 && !allPageSelected.value
))

const sortParams = computed(() => {
  const [sortBy, order] = sortOption.value.split('-')
  return {
    sort_by: sortBy || 'message_date',
    sort_desc: order !== 'asc',
  }
})

const typePillOptions = computed(() => [
  { label: '全部', value: '', icon: Files, count: usageStats.value?.total_count },
  { label: '视频', value: 'video', icon: VideoPlay, count: usageStats.value?.videos },
  { label: '图片', value: 'image', icon: Picture, count: usageStats.value?.images },
  { label: '音频', value: 'audio', icon: Headset, count: usageStats.value?.audios },
  { label: '文档', value: 'document', icon: Document, count: usageStats.value?.documents },
])

function selectTypeFilter(value: string) {
  if (typeFilter.value === value) return
  typeFilter.value = value
  handleSearch()
}

function resetFilters() {
  typeFilter.value = ''
  searchKeyword.value = ''
  handleSearch()
}

function getFileName(item?: TelegramDriveItem | null): string {
  if (!item) return ''
  return item.file_name || `telegram_${item.message_id}`
}

function getDownloadFileName(item?: TelegramDriveItem | null): string {
  if (!item) return ''
  if (isFile(item) && item.download_file_name) return item.download_file_name

  if (item.stream_url) {
    try {
      const pathname = new URL(item.stream_url, window.location.origin).pathname
      const encodedName = pathname.split('/').filter(Boolean).pop()
      if (encodedName) {
        return decodeURIComponent(encodedName)
      }
    } catch {
      const encodedName = item.stream_url.split('?')[0]?.split('/').filter(Boolean).pop()
      if (encodedName) {
        try {
          return decodeURIComponent(encodedName)
        } catch {
          return encodedName
        }
      }
    }
  }

  return getFileName(item)
}

function getItemKey(item: TelegramDriveItem): string {
  return isFolder(item) ? `folder-${item.media_group_id}` : item.file_unique_id
}

function isSelected(item: TelegramDriveItem): boolean {
  return selectedKeys.value.has(getItemKey(item))
}

function clearSelection() {
  selectedKeys.value = new Set()
}

let isShiftPressed = false

function handleCheckboxClick(_item: TelegramDriveItem, event: MouseEvent) {
  if (event?.shiftKey) {
    isShiftPressed = true
  }
}

function toggleItemSelection(item: TelegramDriveItem, selected: boolean) {
  const key = getItemKey(item)
  const next = new Set(selectedKeys.value)

  if (isShiftPressed && lastSelectedKey.value && lastSelectedKey.value !== key) {
    const fromIdx = items.value.findIndex(it => getItemKey(it) === lastSelectedKey.value)
    const toIdx = items.value.findIndex(it => getItemKey(it) === key)
    if (fromIdx !== -1 && toIdx !== -1) {
      const start = Math.min(fromIdx, toIdx)
      const end = Math.max(fromIdx, toIdx)
      for (let i = start; i <= end; i++) {
        const k = getItemKey(items.value[i])
        if (selected) next.add(k)
        else next.delete(k)
      }
      selectedKeys.value = next
      lastSelectedKey.value = key
      isShiftPressed = false
      return
    }
  }

  isShiftPressed = false
  if (selected) next.add(key)
  else next.delete(key)
  selectedKeys.value = next
  lastSelectedKey.value = key
}

function toggleSelectPage(selected: boolean) {
  selectedKeys.value = selected
    ? new Set(items.value.map(getItemKey))
    : new Set()
}

function getStreamUrl(item: TelegramDriveItem): string {
  if (!isFile(item) || !item.stream_url) return ''
  const base = resolveServerUrl(item.stream_url)
  const urlObj = new URL(base, window.location.origin)
  if (authStore.user?.id) {
    urlObj.searchParams.set('uid', String(authStore.user.id))
  }
  if (selectedEdgeNodeId.value === 'direct') {
    urlObj.searchParams.set('direct', '1')
  } else if (selectedEdgeNodeId.value && selectedEdgeNodeId.value !== 'auto') {
    urlObj.searchParams.set('preferred_node', selectedEdgeNodeId.value)
  }
  return urlObj.toString()
}

function getDownloadUrl(item: TelegramDriveItem): string {
  const url = getStreamUrl(item)
  if (!url) return ''
  const downloadUrl = new URL(url, window.location.origin)
  downloadUrl.searchParams.set('download', '1')
  return downloadUrl.toString()
}

const coverFallbacks = ref<Record<string, string>>({})

function isFolder(item?: TelegramDriveItem | null): item is TelegramDriveFolder {
  return isTelegramDriveFolder(item)
}

function isFile(item?: TelegramDriveItem | null): item is TelegramDriveFile {
  return isTelegramDriveFile(item)
}

function isImage(item?: TelegramDriveItem | null): boolean {
  if (!item) return false
  if (isFolder(item)) return false
  if (item.mime_type?.toLowerCase().startsWith('image/')) return true
  const name = item.file_name || (item as any).download_file_name || ''
  if (/\.(jpe?g|png|gif|webp|bmp|svg|heic|avif)$/i.test(name)) return true
  const stream = item.stream_url || ''
  if (/\.(jpe?g|png|gif|webp|bmp|svg|heic|avif)(\?|$)/i.test(stream)) return true
  return false
}

function isVideo(item?: TelegramDriveItem | null): boolean {
  if (!item) return false
  if (isFolder(item)) return false
  if (item.mime_type?.toLowerCase().startsWith('video/')) return true
  const name = item.file_name || (item as any).download_file_name || ''
  if (/\.(mp4|mkv|webm|avi|mov|wmv|flv|m4v|ts)$/i.test(name)) return true
  const stream = item.stream_url || ''
  if (/\.(mp4|mkv|webm|avi|mov|wmv|flv|m4v|ts)(\?|$)/i.test(stream)) return true
  return false
}

function isAudio(item?: TelegramDriveItem | null): boolean {
  if (!item) return false
  if (isFolder(item)) return false
  if (item.mime_type?.toLowerCase().startsWith('audio/')) return true
  const name = item.file_name || (item as any).download_file_name || ''
  if (/\.(mp3|ogg|wav|flac|m4a|aac|opus)$/i.test(name)) return true
  const stream = item.stream_url || ''
  if (/\.(mp3|ogg|wav|flac|m4a|aac|opus)(\?|$)/i.test(stream)) return true
  return false
}

function isAlbumWithImages(item?: TelegramDriveItem | null): boolean {
  if (!isFolder(item)) return false
  const groupMimes = item.group_mime_types || []
  if (groupMimes.some(mime => mime.toLowerCase().startsWith('image/'))) return true
  const repMime = (item as any).representative_mime_type || ''
  if (repMime.toLowerCase().startsWith('image/')) return true
  const name = item.file_name || (item as any).representative_file_name || ''
  return /\.(jpe?g|png|gif|webp|bmp|svg|heic|avif)$/i.test(name)
}

function getThumbnailUrl(item: TelegramDriveItem): string {
  if (!item) return ''
  const key = getItemKey(item)
  if (failedCovers.value.has(key)) return ''
  if (coverFallbacks.value[key]) {
    return coverFallbacks.value[key]
  }

  // 1. 优先使用后端统一 WebP 缩略图（小体积、高并发、秒开）
  if (item.thumbnail_url) {
    const url = resolveServerUrl(item.thumbnail_url)
    if (thumbVersion.value > 0) {
      const sep = url.includes('?') ? '&' : '?'
      return `${url}${sep}_v=${thumbVersion.value}`
    }
    return url
  }

  // 2. 文件夹相册有代表项直链且为图片
  if (isFolder(item) && isAlbumWithImages(item) && item.stream_url) {
    return resolveServerUrl(item.stream_url)
  }

  // 3. 兜底非音视频直链
  if (item.stream_url && !isVideo(item) && !isAudio(item)) {
    return resolveServerUrl(item.stream_url)
  }

  return ''
}

function markCoverFailed(item: TelegramDriveItem) {
  const key = getItemKey(item)
  // 若使用直链失败且存在后端 thumbnail_url，则降级尝试 thumbnail_url
  if (!coverFallbacks.value[key] && item.thumbnail_url) {
    const fallbackThumb = resolveServerUrl(item.thumbnail_url)
    if (fallbackThumb !== getThumbnailUrl(item)) {
      coverFallbacks.value = { ...coverFallbacks.value, [key]: fallbackThumb }
      return
    }
  }
  failedCovers.value = new Set(failedCovers.value).add(key)
}

function getDisplaySize(item: TelegramDriveItem): number {
  return isFolder(item) ? item.total_size ?? 0 : item.file_size ?? 0
}

const previewImageUrls = computed(() => {
  return items.value
    .filter(i => isFile(i) && isImage(i) && i.stream_url)
    .map(i => resolveServerUrl(i.stream_url!))
})

const previewImageIndex = computed(() => {
  if (!previewItem.value || !isFile(previewItem.value)) return 0
  const currentUrl = previewUrl.value
  const idx = previewImageUrls.value.indexOf(currentUrl)
  return idx >= 0 ? idx : 0
})

function getTypeLabel(item: TelegramDriveItem): string {
  if (isFolder(item)) return '媒体组'
  if (isVideo(item)) return '视频'
  if (isImage(item)) return '图片'
  if (isAudio(item)) return '音频'
  return '文档'
}

function getTypeBadgeClass(item: TelegramDriveItem): string {
  if (isFolder(item)) return 'type-badge-album'
  if (isVideo(item)) return 'type-badge-video'
  if (isImage(item)) return 'type-badge-image'
  if (isAudio(item)) return 'type-badge-audio'
  return 'type-badge-document'
}

function getFileIconClass(item: TelegramDriveItem): string {
  if (isFolder(item)) return 'icon-badge-album'
  if (isVideo(item)) return 'icon-badge-video'
  if (isImage(item)) return 'icon-badge-image'
  if (isAudio(item)) return 'icon-badge-audio'
  return 'icon-badge-document'
}

function getCoverBgClass(item: TelegramDriveItem): string {
  if (isFolder(item)) return 'cover-album'
  if (isVideo(item)) return 'cover-video'
  if (isImage(item)) return 'cover-image'
  if (isAudio(item)) return 'cover-audio'
  return 'cover-doc'
}

function getVideoType(item?: TelegramDriveItem | null): string {
  return item?.mime_type || ''
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function formatDate(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN')
}

async function loadUsage() {
  try {
    const response = await getTelegramUsage()
    if (response.success && response.data) {
      usageStats.value = response.data
    }
  } catch (error) {
    console.error('加载 TG 网盘统计失败:', error)
  }
}

async function loadItems() {
  clearSelection()
  loading.value = true
  try {
    const response = await browseTelegramDrive({
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchKeyword.value || undefined,
      type: typeFilter.value || undefined,
      media_group_id: currentMediaGroupId.value || undefined,
      ...sortParams.value,
    })

    if (response.success) {
      items.value = response.items || []
      total.value = response.total || 0
    } else {
      items.value = []
      total.value = 0
      ElMessage.error(response.error || '加载 TG 网盘失败')
    }
  } catch (error: any) {
    console.error('加载 TG 网盘失败:', error)
    items.value = []
    total.value = 0
    ElMessage.error(error.message || '加载 TG 网盘失败')
  } finally {
    loading.value = false
  }
}

async function fetchThumbStatus() {
  try {
    const response = await getTelegramThumbnailStatus()
    if (response?.success && response.data) {
      const wasRunning = thumbStatus.value?.running
      thumbStatus.value = response.data
      if (response.data.running) {
        startThumbPolling()
      } else if (wasRunning) {
        // 预热完成，更新版本号让页面重新拉取最新生成的 WebP 缩略图
        thumbVersion.value++
        failedCovers.value = new Set()
        coverFallbacks.value = {}
        stopThumbPolling()
      }
    }
  } catch (_e) {
    // 单元测试或接口不可用时优雅降级
  }
}

let thumbPollingActive = false

function startThumbPolling() {
  thumbPollingActive = true
  if (pollTimer.value) return
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
    return
  }
  pollTimer.value = setInterval(fetchThumbStatus, 3000)
}

function stopThumbPolling() {
  thumbPollingActive = false
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

function handleVisibilityChange() {
  if (typeof document === 'undefined') return
  if (document.visibilityState === 'hidden') {
    if (pollTimer.value) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
  } else if (document.visibilityState === 'visible' && thumbPollingActive) {
    fetchThumbStatus().catch(() => {})
    if (!pollTimer.value) {
      pollTimer.value = setInterval(fetchThumbStatus, 3000)
    }
  }
}

async function handleTriggerWarmup() {
  if (thumbStatus.value?.running) {
    ElMessage.info('缩略图正在后台预热中，请稍候...')
    return
  }
  try {
    const res = await warmupTelegramThumbnails()
    if (res.success) {
      ElMessage.success(res.message || '已开始后台预生成缩略图')
      if (res.data) {
        thumbStatus.value = res.data
      }
      startThumbPolling()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '触发预热失败')
  }
}

async function refreshAll() {
  fetchThumbStatus().catch(() => {})
  loadAndProbeEdgeNodes().catch(() => {})
  await Promise.all([loadUsage(), loadItems()])
}

function handleSearch() {
  currentPage.value = 1
  loadItems()
}

function enterFolder(item: TelegramDriveItem) {
  if (!item.media_group_id) return
  currentMediaGroupId.value = item.media_group_id
  currentFolderName.value = getFileName(item)
  currentPage.value = 1
  loadItems()
}

function goRoot() {
  if (!isInsideGroup.value) return
  currentMediaGroupId.value = ''
  currentFolderName.value = ''
  currentPage.value = 1
  loadItems()
}

function handlePageSizeChange() {
  currentPage.value = 1
  loadItems()
}

function getAbsoluteStreamUrl(item?: TelegramDriveItem | null): string {
  if (!item || !isFile(item) || !item.stream_url) return ''
  const base = toAbsoluteServerUrl(item.stream_url)
  const urlObj = new URL(base)
  if (authStore.user?.id) {
    urlObj.searchParams.set('uid', String(authStore.user.id))
  }
  if (selectedEdgeNodeId.value === 'direct') {
    urlObj.searchParams.set('direct', '1')
  } else if (selectedEdgeNodeId.value && selectedEdgeNodeId.value !== 'auto') {
    urlObj.searchParams.set('preferred_node', selectedEdgeNodeId.value)
  }
  return urlObj.toString()
}

async function copyToClipboard(text: string, successMsg = '已复制到剪贴板') {
  if (!text) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    ElMessage.success(successMsg)
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

async function handleCopyStreamUrl(item: TelegramDriveItem) {
  if (isFolder(item)) {
    ElMessage.info('文件夹无法获取单文件直链')
    return
  }
  let targetUrl = ''
  let nodeTag = ''
  if (selectedEdgeNodeId.value !== 'direct') {
    try {
      const res = await resolveEdgeStreamUrl({
        message_id: item.message_id,
        hash: item.hash,
        preferred_node: selectedEdgeNodeId.value,
      })
      if (res && res.success && res.url) {
        targetUrl = res.url
        if (res.is_edge && res.node_name) {
          nodeTag = ` (${res.node_name}直连)`
        }
      }
    } catch {
      // ignore
    }
  }
  if (!targetUrl) {
    targetUrl = getAbsoluteStreamUrl(item)
  }
  if (!targetUrl) {
    ElMessage.warning('该文件暂无可用直链')
    return
  }
  copyToClipboard(targetUrl, `已复制「${getFileName(item)}」直链${nodeTag}`)
}

function handleBatchCopyStreamUrls() {
  const files = selectedFiles.value
  if (!files.length) return
  const urls = files.map(it => getAbsoluteStreamUrl(it)).filter(Boolean)
  if (!urls.length) {
    ElMessage.warning('所选文件中暂无可用直链')
    return
  }
  const text = urls.join('\n')
  copyToClipboard(text, `已成功复制 ${urls.length} 个文件直链`)
}

function handleExportM3U() {
  const files = selectedFiles.value.length > 0 ? selectedFiles.value : items.value.filter(isFile)
  const mediaFiles = files.filter(it => isVideo(it) || isAudio(it) || isFile(it))
  if (!mediaFiles.length) {
    ElMessage.warning('当前无可用媒体文件导出播放列表')
    return
  }

  let m3uContent = '#EXTM3U\n'
  for (const item of mediaFiles) {
    const url = getAbsoluteStreamUrl(item)
    if (!url) continue
    const name = getFileName(item)
    m3uContent += `#EXTINF:-1 tvg-name="${name}" group-title="TG-Drive",${name}\n${url}\n`
  }

  const blob = new Blob([m3uContent], { type: 'audio/x-mpegurl;charset=utf-8' })
  const downloadUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = downloadUrl
  const playlistName = isInsideGroup.value
    ? `${currentFolderName.value || 'album'}_playlist.m3u`
    : `tg_drive_playlist_${new Date().toISOString().slice(0, 10)}.m3u`
  link.download = playlistName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(downloadUrl)
  ElMessage.success(`已导出包含 ${mediaFiles.length} 项的 M3U 播放列表`)
}

async function openExternalPlayer(playerType: string, item?: TelegramDriveItem | null) {
  const target = item || previewItem.value
  if (!target) return
  if (isFolder(target)) return

  let absUrl = ''
  if (selectedEdgeNodeId.value !== 'direct') {
    try {
      const res = await resolveEdgeStreamUrl({
        message_id: target.message_id,
        hash: target.hash,
        preferred_node: selectedEdgeNodeId.value,
      })
      if (res && res.success && res.url) {
        absUrl = res.url
      }
    } catch {
      // ignore
    }
  }
  if (!absUrl) {
    absUrl = getAbsoluteStreamUrl(target)
  }
  if (!absUrl) {
    ElMessage.warning('该文件暂无可用直链')
    return
  }

  let protocolUrl = ''
  if (playerType === 'potplayer') {
    protocolUrl = `potplayer://${absUrl}`
  } else if (playerType === 'vlc') {
    protocolUrl = `vlc://${absUrl}`
  } else if (playerType === 'iina') {
    protocolUrl = `iina://weblink?url=${encodeURIComponent(absUrl)}`
  }

  if (protocolUrl) {
    window.location.href = protocolUrl
  }
}

function triggerPlayerPiP() {
  if (videoPlayerRef.value && typeof videoPlayerRef.value.togglePiP === 'function') {
    videoPlayerRef.value.togglePiP()
  }
}

const playableMediaList = computed(() => {
  return items.value.filter(it => isFile(it) && (isVideo(it) || (previewType.value === 'audio' && isAudio(it))))
})

const currentPlayableIndex = computed(() => {
  if (!previewItem.value) return -1
  const key = getItemKey(previewItem.value)
  return playableMediaList.value.findIndex(it => getItemKey(it) === key)
})

const hasPrevMedia = computed(() => currentPlayableIndex.value > 0)
const hasNextMedia = computed(() => currentPlayableIndex.value >= 0 && currentPlayableIndex.value < playableMediaList.value.length - 1)

function playPrevMedia() {
  if (!hasPrevMedia.value) return
  const prev = playableMediaList.value[currentPlayableIndex.value - 1]
  handlePreview(prev)
}

function playNextMedia() {
  if (!hasNextMedia.value) return
  const next = playableMediaList.value[currentPlayableIndex.value + 1]
  handlePreview(next)
}

function handleMediaEnded() {
  if (autoplayNext.value && hasNextMedia.value) {
    playNextMedia()
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Shift') {
    isShiftPressed = true
  }
  if (!showPreview.value) return
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return

  if (e.key === 'ArrowLeft') {
    if (hasPrevMedia.value) {
      e.preventDefault()
      playPrevMedia()
    }
  } else if (e.key === 'ArrowRight') {
    if (hasNextMedia.value) {
      e.preventDefault()
      playNextMedia()
    }
  }
}

async function handleDownload(item: TelegramDriveItem) {
  if (isFolder(item)) {
    ElMessage.info('请进入媒体组后下载组内文件')
    return
  }

  let url = ''
  if (selectedEdgeNodeId.value !== 'direct') {
    try {
      const res = await resolveEdgeStreamUrl({
        message_id: item.message_id,
        hash: item.hash,
        preferred_node: selectedEdgeNodeId.value,
        download: true,
      })
      if (res && res.success && res.url) {
        url = res.url
      }
    } catch {
      // ignore
    }
  }
  if (!url) {
    url = getDownloadUrl(item)
  }
  if (!url) {
    ElMessage.warning('此文件暂无可用直链')
    return
  }

  const link = document.createElement('a')
  link.href = url
  link.download = getDownloadFileName(item)
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function handleBatchDownload() {
  const files = selectedFiles.value
  if (!files.length) return

  let started = 0
  for (const item of files) {
    const url = getDownloadUrl(item)
    if (!url) continue

    const link = document.createElement('a')
    link.href = url
    link.download = getDownloadFileName(item)
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    document.body.appendChild(link)
    link.click()
    link.remove()
    started += 1
  }

  const skippedFolders = selectedItems.value.length - files.length
  if (started) {
    ElMessage.success(`已开始下载 ${started} 个文件`)
  }
  if (skippedFolders) {
    ElMessage.info(`已跳过 ${skippedFolders} 个媒体组文件夹`)
  }
}

function handleOpen(item: TelegramDriveItem) {
  if (isFolder(item)) {
    enterFolder(item)
    return
  }
  handlePreview(item)
}

async function handlePreview(item: TelegramDriveItem) {
  if (isImage(item)) {
    const url = getStreamUrl(item)
    if (!url) {
      ElMessage.warning('此文件暂无可用直链')
      return
    }
    previewType.value = 'image'
    previewItem.value = item
    previewUrl.value = url
    showPreview.value = true
    return
  }

  if (!isVideo(item) && !isAudio(item)) {
    handleDownload(item)
    return
  }

  previewType.value = isVideo(item) ? 'video' : 'audio'
  previewItem.value = item
  // 若显式锁定为主控直连，直接赋主控直链；否则先置空，待解析出边缘节点后直连拉流，主控出网流量为0
  if (selectedEdgeNodeId.value === 'direct') {
    previewUrl.value = getStreamUrl(item)
  } else {
    previewUrl.value = ''
  }
  showPreview.value = true

  // 异步快速换取 Edge 直链（若命中香港等边缘节点，无缝直连拉流）
  const directEdgeUrl = await resolvePlayUrl(item)
  if (showPreview.value && previewItem.value?.message_id === item.message_id) {
    previewUrl.value = directEdgeUrl || getStreamUrl(item)
  }
}

function closePreview() {
  showPreview.value = false
  previewItem.value = null
  previewType.value = 'unknown'
  previewUrl.value = ''
  isWebFullscreen.value = false
}

async function handleDelete(item: TelegramDriveItem) {
  const shouldDeleteGroup = isFolder(item) || (!isInsideGroup.value && Boolean(item.media_group_id))
  const targetName = shouldDeleteGroup ? `媒体组文件夹「${getFileName(item)}」` : `文件「${getFileName(item)}」`

  try {
    await ElMessageBox.confirm(`确定要删除 ${targetName} 吗？会同步删除频道消息和数据库记录。`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })

    loading.value = true
    const response = shouldDeleteGroup && item.media_group_id
      ? await deleteTelegramGroup(item.media_group_id)
      : isFile(item)
        ? await deleteTelegramItem(item.message_id)
        : { success: false, error: '无法定位要删除的文件' }

    if (response.success) {
      ElMessage.success(response.message || '删除成功')
      if (shouldDeleteGroup && isInsideGroup.value) {
        currentMediaGroupId.value = ''
        currentFolderName.value = ''
      }
      await refreshAll()
    } else {
      ElMessage.error(response.error || '删除失败')
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('删除 TG 网盘文件失败:', error)
      ElMessage.error(error.message || '删除失败')
    }
  } finally {
    loading.value = false
  }
}

async function handleBatchDelete() {
  const selection = selectedItems.value
  if (!selection.length) return

  const messageIds = selection.filter(isFile).map(item => item.message_id)
  const mediaGroupIds = selection.filter(isFolder).map(item => item.media_group_id)

  try {
    await ElMessageBox.confirm(
      `确定删除已选 ${selection.length} 项吗？媒体组文件夹会连同组内频道消息一起删除。`,
      '批量删除',
      {
        confirmButtonText: '删除所选',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )

    batchDeleting.value = true
    const response = await deleteTelegramBatch({
      message_ids: messageIds,
      media_group_ids: mediaGroupIds,
    })
    if (!response.success) throw new Error(response.error || '批量删除失败')

    clearSelection()
    ElMessage.success(response.message || `已删除 ${selection.length} 项`)
    await refreshAll()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    console.error('批量删除 TG 网盘文件失败:', error)
    ElMessage.error(error.response?.data?.error || error.message || '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

async function handleClearAll() {
  try {
    await ElMessageBox.confirm('确定要清空整个 TG 频道网盘吗？此操作会删除所有频道消息和本地记录。', '清空 TG 网盘', {
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      type: 'warning',
    })

    loading.value = true
    const response = await clearTelegramDrive()
    if (response.success) {
      ElMessage.success(response.message || 'TG 网盘已清空')
      await refreshAll()
    } else {
      ElMessage.error(response.error || '清空失败')
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('清空 TG 网盘失败:', error)
      ElMessage.error(error.message || '清空失败')
    }
  } finally {
    loading.value = false
  }
}

function handleKeyup(e: KeyboardEvent) {
  if (e.key === 'Shift') {
    isShiftPressed = false
  }
}

onMounted(() => {
  void fetchBotInfo()
  window.addEventListener('open-drive-harvester', openHarvesterDialog)
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('keyup', handleKeyup)
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }
  refreshAll()
})


// =========================================================================
// 私密/受限频道采集与无痕转存状态与控制
// =========================================================================
const uploadDrawerRef = ref<InstanceType<typeof DriveUploadDrawer> | null>(null)
const isDragOver = ref(false)
let dragCounter = 0

function triggerUpload() {
  uploadDrawerRef.value?.triggerFileInput()
}

function handleUploadSuccess() {
  refreshAll()
}

function handleDragEnter(e: DragEvent) {
  e.preventDefault()
  dragCounter++
  if (e.dataTransfer?.types?.includes("Files")) {
    isDragOver.value = true
  }
}

function handleDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = "copy"
  }
  isDragOver.value = true
}

function handleDragLeave(e: DragEvent) {
  e.preventDefault()
  dragCounter--
  if (dragCounter <= 0) {
    isDragOver.value = false
    dragCounter = 0
  }
}

function handleDrop(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
  dragCounter = 0
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    uploadDrawerRef.value?.addFiles(e.dataTransfer.files)
  }
}

const harvesterVisible = ref(false)
const harvesterInviteLink = ref('')
const harvesterLinksText = ref('')
const harvesterAccountId = ref<number | null>(null)
const harvesterRebrandEnabled = ref(true)
const harvesterStarting = ref(false)
const harvesterCancelling = ref(false)
const harvesterStatus = ref<HarvesterTaskStatus | null>(null)
const protocolAccounts = ref<ProtocolAccount[]>([])
const terminalBodyRef = ref<HTMLElement | null>(null)
let harvesterTimer: any = null

const harvesterProgressPercent = computed(() => {
  if (!harvesterStatus.value || !harvesterStatus.value.total_messages) return 0
  const pct = Math.floor((harvesterStatus.value.current_index / harvesterStatus.value.total_messages) * 100)
  return Math.min(100, Math.max(0, pct))
})

const harvesterProgressStatus = computed(() => {
  if (!harvesterStatus.value) return undefined
  if (harvesterStatus.value.status === 'completed') return 'success'
  if (harvesterStatus.value.status === 'failed') return 'exception'
  if (harvesterStatus.value.status === 'cancelled') return 'warning'
  return undefined
})

watch(
  () => harvesterStatus.value?.logs.length,
  () => {
    nextTick(() => {
      if (terminalBodyRef.value) {
        terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight
      }
    })
  }
)

async function openHarvesterDialog() {
  harvesterVisible.value = true
  try {
    const accRes = await getProtocolAccounts()
    if (accRes.success && Array.isArray(accRes.data)) {
      protocolAccounts.value = accRes.data
    }
  } catch (err) {
    console.debug('获取协议号资产列表提示:', err)
  }

  await pollHarvesterStatusOnce()
}

function stopHarvesterPolling() {
  if (harvesterTimer) {
    clearTimeout(harvesterTimer)
    harvesterTimer = null
  }
}

async function pollHarvesterStatusOnce() {
  try {
    const res = await getHarvesterStatus()
    if (res.success && res.data) {
      harvesterStatus.value = res.data
      if (res.data.status === 'running') {
        stopHarvesterPolling()
        harvesterTimer = setTimeout(pollHarvesterStatusOnce, 1500)
      }
    }
  } catch (err) {
    console.debug('轮询采集任务状态提示:', err)
  }
}

async function handleStartHarvester() {
  const text = (harvesterLinksText.value || '').trim()
  if (!text) {
    ElMessage.warning('请先输入待采集的频道帖子链接或连号区间')
    return
  }

  harvesterStarting.value = true
  try {
    const res = await startHarvesterTask({
      links_text: text,
      invite_link: harvesterInviteLink.value?.trim() || undefined,
      account_id: harvesterAccountId.value,
      rebrand_enabled: harvesterRebrandEnabled.value,
    })
    if (res.success) {
      ElMessage.success(res.message || '私密频道采集流水线已启动')
      await pollHarvesterStatusOnce()
    } else {
      ElMessage.error(res.error || '启动采集失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '启动采集失败')
  } finally {
    harvesterStarting.value = false
  }
}

async function handleCancelHarvester() {
  harvesterCancelling.value = true
  try {
    const res = await cancelHarvesterTask()
    if (res.success) {
      ElMessage.info(res.message || '中止信号已发送')
      await pollHarvesterStatusOnce()
    } else {
      ElMessage.error(res.error || '中止任务失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '中止任务失败')
  } finally {
    harvesterCancelling.value = false
  }
}

async function handleFinishAndRefresh() {
  harvesterVisible.value = false
  await refreshAll()
}

onUnmounted(() => {
  window.removeEventListener('open-drive-harvester', openHarvesterDialog)
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('keyup', handleKeyup)
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
  }
  stopThumbPolling()
  stopHarvesterPolling()
})
</script>

<style scoped>

/* 边缘加速状态胶囊与选路组件样式 */
.edge-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #0369a1;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s ease;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  user-select: none;
}

.edge-status-pill:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(56, 189, 248, 0.65);
  box-shadow: 0 4px 14px rgba(56, 189, 248, 0.2);
  transform: translateY(-1px);
}

.edge-status-pill.is-direct {
  border-color: rgba(156, 163, 175, 0.35);
  color: #6b7280;
}

.edge-icon {
  font-size: 14px;
  color: #0ea5e9;
}

.edge-routing-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 9999px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #0284c7;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.edge-routing-badge:hover {
  background: rgba(56, 189, 248, 0.22);
  border-color: rgba(56, 189, 248, 0.6);
}

.edge-routing-badge.is-direct {
  background: rgba(156, 163, 175, 0.12);
  border-color: rgba(156, 163, 175, 0.35);
  color: #4b5563;
}

.node-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  background: #9ca3af;
}

.node-status-dot.online {
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.6);
}

.edge-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  min-width: 240px;
}

.edge-menu-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
}

.edge-menu-latency {
  font-size: 12px;
  font-weight: 600;
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  padding: 1px 6px;
  border-radius: 4px;
}

.edge-menu-dc {
  font-size: 11px;
  color: #6b7280;
}

.edge-menu-tag {
  font-size: 11px;
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.1);
  padding: 1px 6px;
  border-radius: 4px;
}

.edge-menu-hint {
  font-size: 11px;
  color: #9ca3af;
}

/* 缩略图预热胶囊组件 */
.thumb-warmup-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(255, 143, 171, 0.35);
  color: #4b5563;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s ease;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  user-select: none;
}

.thumb-warmup-pill:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(255, 117, 151, 0.55);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.18);
  transform: translateY(-1px);
}

.thumb-warmup-pill.is-running {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.14), rgba(56, 189, 248, 0.14));
  border-color: rgba(56, 189, 248, 0.45);
  color: #0284c7;
}

.warmup-icon {
  font-size: 14px;
  color: #ff7597;
}

.thumb-warmup-pill.is-running .warmup-icon {
  color: #0284c7;
}

.warmup-icon.is-spinning {
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.drive-page {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 顶部头部毛玻璃容器 */
.drive-header-card {
  padding: 24px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 143, 171, 0.22);
  box-shadow: 0 8px 24px rgba(255, 117, 151, 0.08);
}

.drive-header-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}

.drive-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.drive-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.3px;
  line-height: 1.2;
}

.drive-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #ff7597;
  background: rgba(255, 117, 151, 0.12);
  border: 1px solid rgba(255, 117, 151, 0.25);
}

.drive-subtitle {
  margin: 8px 0 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.drive-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header-btn {
  height: 38px;
  padding: 0 16px;
  border-radius: 12px;
  font-weight: 500;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.refresh-btn {
  border: 1px solid rgba(255, 143, 171, 0.35);
  background: rgba(255, 255, 255, 0.85);
  color: #374151;
}

.refresh-btn:hover {
  background: #ffffff;
  color: #ff7597;
  border-color: #ff7597;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.2);
  transform: translateY(-1px);
}

.clear-all-btn {
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.22);
}

.clear-all-btn:hover {
  box-shadow: 0 6px 16px rgba(239, 68, 68, 0.35);
  transform: translateY(-1px);
}

/* 现代流光统计卡片 */
.stats-row {
  margin-top: 6px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(255, 143, 171, 0.18);
  box-shadow: 0 2px 10px rgba(255, 117, 151, 0.04);
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  position: relative;
  overflow: hidden;
}

.stat-card:hover {
  background: rgba(255, 255, 255, 0.98);
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 8px 20px rgba(255, 117, 151, 0.16);
  transform: translateY(-2px);
}

.stat-card.is-active {
  background: linear-gradient(135deg, rgba(255, 241, 245, 0.95), rgba(240, 249, 255, 0.9));
  border-color: #ff7597;
  box-shadow: 0 8px 22px rgba(255, 117, 151, 0.22);
}

.stat-card-size {
  cursor: default;
}

.stat-icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  transition: transform 0.25s ease;
}

.stat-card:hover .stat-icon-wrapper {
  transform: scale(1.08) rotate(3deg);
}

.stat-icon-files {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
}

.stat-icon-storage {
  background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
}

.stat-icon-video {
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 100%);
}

.stat-icon-image {
  background: linear-gradient(135deg, #f472b6 0%, #ec4899 100%);
}

.stat-info {
  min-width: 0;
  flex: 1;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #1f2937;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-variant-numeric: tabular-nums;
}

.stat-value-size {
  font-size: 17px;
}

.stat-label {
  margin-top: 3px;
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

/* 主内容容器 */
.drive-main-card {
  padding: 24px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 143, 171, 0.22);
  box-shadow: 0 8px 24px rgba(255, 117, 151, 0.08);
  min-height: 520px;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(255, 245, 248, 0.8), rgba(240, 249, 255, 0.7));
  border: 1px solid rgba(255, 143, 171, 0.2);
  border-radius: 16px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  flex: 1;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  width: 270px;
}

.type-select,
.sort-select {
  width: 145px;
}

.view-mode-toggle :deep(.el-radio-button__inner) {
  padding: 8px 14px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}

/* 媒体快捷分类 Pills */
.quick-filter-pills {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 2px 4px;
  overflow-x: auto;
  scrollbar-width: none;
}

.quick-filter-pills::-webkit-scrollbar {
  display: none;
}

.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 9999px;
  border: 1px solid rgba(255, 143, 171, 0.22);
  background: rgba(255, 255, 255, 0.7);
  color: #4b5563;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
}

.filter-pill:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: #ff7597;
  color: #ff7597;
  transform: translateY(-1px);
}

.filter-pill.is-active {
  background: var(--gradient-primary);
  border-color: transparent;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.35);
}

.pill-icon {
  font-size: 14px;
}

.pill-count {
  display: inline-block;
  padding: 0 6px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.08);
  font-size: 11px;
  font-weight: 600;
}

.filter-pill.is-active .pill-count {
  background: rgba(255, 255, 255, 0.28);
  color: #ffffff;
}

/* 面包屑与路径状态栏 */
.breadcrumb-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  padding: 4px 6px;
}

.back-root-btn {
  border-radius: 10px;
  font-weight: 600;
  color: #ff7597;
  transition: all 0.2s ease;
}

.back-root-btn:hover {
  background: rgba(255, 117, 151, 0.12);
  transform: translateX(-2px);
}

.drive-breadcrumb {
  display: flex;
  align-items: center;
}

.breadcrumb-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #3b82f6;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.breadcrumb-link:hover {
  color: #ff7597;
  text-decoration: underline;
}

.breadcrumb-current-group {
  display: inline-flex;
  align-items: center;
  color: #1f2937;
  font-weight: 600;
}

.items-total-pill {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
}

/* 批量操作浮动栏 */
.selection-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 48px;
  margin-top: 14px;
  padding: 8px 16px;
  border: 1px solid rgba(255, 143, 171, 0.28);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 241, 245, 0.95), rgba(240, 249, 255, 0.95));
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.08);
  box-sizing: border-box;
  max-width: 100%;
}

.selection-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.selection-count {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 9999px;
  background: rgba(255, 117, 151, 0.14);
  color: #ff7597;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.selection-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  flex-wrap: wrap;
}

.batch-btn {
  border-radius: 10px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.batch-download-btn {
  border-color: rgba(56, 189, 248, 0.4);
  background: rgba(255, 255, 255, 0.9);
  color: #0284c7;
}

.batch-download-btn:hover:not(:disabled) {
  background: #38bdf8;
  color: #ffffff;
  border-color: #38bdf8;
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.35);
  transform: translateY(-1px);
}

.batch-delete-btn {
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
}

.batch-delete-btn:hover:not(:disabled) {
  box-shadow: 0 6px 16px rgba(239, 68, 68, 0.35);
  transform: translateY(-1px);
}

.batch-cancel-btn {
  color: #64748b;
  font-weight: 500;
}

.batch-cancel-btn:hover {
  color: #ff7597;
}

/* 列表模式表格美化 */
.table-container {
  margin-top: 16px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid rgba(255, 143, 171, 0.18);
}

.drive-table {
  width: 100%;
}

.file-name {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-icon-badge {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.2s ease;
  overflow: hidden;
}

.file-mini-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 10px;
}

.file-name:hover .file-icon-badge {
  transform: scale(1.08);
}

.icon-badge-album {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.icon-badge-video {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.icon-badge-image {
  background: rgba(244, 63, 94, 0.12);
  color: #f43f5e;
}

.icon-badge-audio {
  background: rgba(168, 85, 247, 0.12);
  color: #a855f7;
}

.icon-badge-document {
  background: rgba(100, 116, 139, 0.12);
  color: #64748b;
}

.file-title {
  font-weight: 500;
  color: #1f2937;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.album-tag {
  border-radius: 6px;
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: none;
  font-weight: 600;
}

.type-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.type-badge-album {
  background: rgba(245, 158, 11, 0.1);
  color: #b45309;
}

.type-badge-video {
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
}

.type-badge-image {
  background: rgba(244, 63, 94, 0.1);
  color: #e11d48;
}

.type-badge-audio {
  background: rgba(168, 85, 247, 0.1);
  color: #9333ea;
}

.type-badge-document {
  background: rgba(100, 116, 139, 0.1);
  color: #475569;
}

.size-text {
  font-weight: 500;
  color: #374151;
  font-variant-numeric: tabular-nums;
}

.content-text {
  color: #64748b;
  font-size: 13px;
}

.message-id-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.05);
  color: #64748b;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.time-text {
  color: #64748b;
  font-size: 13px;
}

.table-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.table-actions :deep(.el-button.is-link) {
  background: transparent !important;
  box-shadow: none !important;
  padding: 4px 8px !important;
  border-radius: 6px !important;
  font-weight: 500;
  height: 28px !important;
}

.table-actions :deep(.el-button--primary.is-link) {
  color: #ff7597 !important;
}

.table-actions :deep(.el-button--primary.is-link:hover) {
  background: rgba(255, 117, 151, 0.12) !important;
  color: #f43f6e !important;
}

.table-actions :deep(.el-button--success.is-link) {
  color: #0284c7 !important;
}

.table-actions :deep(.el-button--success.is-link:hover) {
  background: rgba(56, 189, 248, 0.12) !important;
  color: #0369a1 !important;
}

.table-actions :deep(.el-button--danger.is-link) {
  color: #ef4444 !important;
}

.table-actions :deep(.el-button--danger.is-link:hover) {
  background: rgba(239, 68, 68, 0.12) !important;
  color: #dc2626 !important;
}

/* 网格模式卡片设计 */
.grid-view {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 18px;
  margin-top: 18px;
  min-height: 200px;
}

.grid-item {
  position: relative;
  border-radius: 16px;
  border: 1px solid rgba(255, 143, 171, 0.2);
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.06);
  cursor: pointer;
  overflow: hidden;
  transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
  display: flex;
  flex-direction: column;
}

.grid-item:hover {
  border-color: #ff7597;
  box-shadow: 0 12px 28px rgba(255, 117, 151, 0.2), 0 4px 12px rgba(56, 189, 248, 0.12);
  transform: translateY(-4px);
}

.grid-item.is-selected {
  border-color: #ff7597;
  background: rgba(255, 241, 245, 0.95);
  box-shadow: 0 0 0 2px #ff7597, 0 8px 24px rgba(255, 117, 151, 0.2);
}

.grid-item-checkbox {
  position: absolute;
  z-index: 4;
  top: 10px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  border: 1px solid rgba(255, 143, 171, 0.25);
  transition: all 0.2s ease;
}

.grid-item:hover .grid-item-checkbox {
  border-color: #ff7597;
}

.grid-item-preview {
  position: relative;
  aspect-ratio: 16 / 10;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #f8fafc;
}

.cover-album {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
}

.cover-video {
  background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
}

.cover-image {
  background: linear-gradient(135deg, #ffe4e6 0%, #fbcfe8 100%);
}

.cover-audio {
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
}

.cover-doc {
  background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
}

.grid-thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.35s ease;
}

.grid-item:hover .grid-thumbnail {
  transform: scale(1.05);
}

.grid-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.placeholder-icon-halo {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  color: #64748b;
  transition: transform 0.25s ease;
}

.grid-item:hover .placeholder-icon-halo {
  transform: scale(1.1);
}

.type-badge {
  position: absolute;
  right: 8px;
  top: 8px;
  z-index: 3;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  backdrop-filter: blur(8px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

.grid-album-chip {
  position: absolute;
  left: 8px;
  bottom: 8px;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.72);
  color: #ffffff;
  backdrop-filter: blur(6px);
}

/* 卡片悬浮快捷动作底栏 */
.grid-card-overlay {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  opacity: 0;
  pointer-events: none;
  transition: all 0.25s ease;
}

.grid-item:hover .grid-card-overlay {
  opacity: 1;
  pointer-events: auto;
}

.overlay-action-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.95);
  color: #1f2937;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.overlay-action-btn:hover {
  transform: scale(1.15);
  color: #ff7597;
  background: #ffffff;
}

.overlay-action-btn.overlay-download:hover {
  color: #0284c7;
}

.overlay-action-btn.overlay-delete:hover {
  color: #ef4444;
}

.grid-item-body {
  padding: 12px 14px 12px;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.grid-item-name {
  font-weight: 600;
  color: #1f2937;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grid-item-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  gap: 8px;
}

.grid-item-meta {
  color: #64748b;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.grid-item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.card-action-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: rgba(0, 0, 0, 0.04);
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 13px;
}

.card-action-btn:hover {
  background: rgba(255, 117, 151, 0.14);
  color: #ff7597;
  transform: translateY(-1px);
}

.card-action-btn.card-action-delete:hover {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

/* 空状态卡片 */
.empty-onboarding-container {
  width: 100%;
  max-width: 860px;
  padding: 32px 28px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.3);
  box-shadow: 0 10px 36px rgba(255, 117, 151, 0.1);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-methods-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  width: 100%;
  margin: 20px 0;
}

.empty-method-card {
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(255, 143, 171, 0.22);
  border-radius: 14px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  text-align: left;
  transition: all 0.25s ease;
}

.empty-method-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 6px 20px rgba(255, 117, 151, 0.12);
}

.method-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.method-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.icon-wrap--primary {
  background: rgba(255, 117, 151, 0.15);
  color: #ff7597;
}

.icon-wrap--sky {
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
}

.icon-wrap--purple {
  background: rgba(168, 85, 247, 0.15);
  color: #9333ea;
}

.method-card-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(255, 117, 151, 0.12);
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.25);
}

.method-card-badge--sky {
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
  border-color: rgba(56, 189, 248, 0.25);
}

.method-card-badge--purple {
  background: rgba(168, 85, 247, 0.12);
  color: #9333ea;
  border-color: rgba(168, 85, 247, 0.25);
}

.method-card-title {
  font-size: 14px;
  font-weight: 800;
  color: #111827;
  margin: 0 0 6px 0;
}

.method-card-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
  margin: 0 0 14px 0;
  flex: 1;
}

.method-card-btn {
  width: 100%;
  border-radius: 8px;
  font-weight: 600;
}

.empty-bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 143, 171, 0.2);
  flex-wrap: wrap;
  gap: 10px;
}

.empty-tip-text {
  font-size: 12px;
  color: #64748b;
}

.empty-bottom-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.guide-text-btn {
  border-radius: 8px;
  border-color: rgba(255, 143, 171, 0.35);
  color: #ff7597;
}

@media (max-width: 768px) {
  .empty-methods-grid {
    grid-template-columns: 1fr;
  }
  .empty-bottom-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .empty-bottom-actions {
    justify-content: flex-end;
  }
}

.empty-state-box {
  padding: 60px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-icon-halo {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.14), rgba(56, 189, 248, 0.14));
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ff7597;
  margin-bottom: 16px;
  box-shadow: 0 8px 24px rgba(255, 117, 151, 0.15);
  animation: float 4s ease-in-out infinite;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.empty-hint {
  margin: 6px 0 20px;
  font-size: 13px;
  color: #64748b;
  max-width: 360px;
}

.empty-actions {
  display: flex;
  gap: 12px;
}

/* 分页 */
.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: 24px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 143, 171, 0.15);
}

/* 视频预览弹窗头部 */
.video-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.video-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.video-badge-icon {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.2) 0%, rgba(56, 189, 248, 0.2) 100%);
  color: #ff7597;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.video-header-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.video-header-pill {
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
  flex-shrink: 0;
}

.video-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: 12px;
}

.header-tool-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  background: rgba(255, 255, 255, 0.85);
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.header-tool-btn:hover {
  background: #ffffff;
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.4);
  transform: translateY(-1px);
}

.header-tool-btn.btn-close:hover {
  color: #ff7597;
  border-color: rgba(255, 117, 151, 0.4);
}

/* 视频容器 */
.video-container {
  width: 100%;
  height: clamp(320px, 60vh, 680px);
  max-height: calc(88vh - 120px);
  background: #000000;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.video-container.fullscreen-container {
  height: calc(95vh - 120px) !important;
  max-height: calc(95vh - 120px) !important;
}

.video-container :deep(.video-js) {
  width: 100% !important;
  height: 100% !important;
}

/* 弹窗底部操作区 */
.dialog-footer-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.footer-meta-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-size-tag {
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  background: rgba(241, 245, 249, 0.9);
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.file-mime-tag {
  color: #64748b;
  font-size: 12px;
  background: rgba(248, 250, 252, 0.85);
  padding: 4px 8px;
  border-radius: 8px;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fullscreen-toggle-btn {
  border-radius: 10px;
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: #0284c7;
  background: rgba(240, 249, 255, 0.85);
  font-weight: 500;
  transition: all 0.2s ease;
}

.fullscreen-toggle-btn:hover {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38bdf8;
  color: #0369a1;
}

.download-action-btn {
  border-radius: 10px;
  font-weight: 500;
}

/* 音频试听弹窗 */
.audio-player-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0;
  text-align: center;
}

.audio-vinyl {
  width: 110px;
  height: 110px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
  border: 4px solid #ff7597;
  box-shadow: 0 10px 28px rgba(255, 117, 151, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  margin-bottom: 18px;
}

.audio-name {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audio-meta {
  font-size: 13px;
  color: #64748b;
  margin: 4px 0 18px;
}

.audio-native-player {
  width: 100%;
  border-radius: 12px;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .stats-row {
    margin-top: 8px;
    margin-bottom: 10px;
  }

  .stat-card {
    padding: 10px 12px !important;
    gap: 8px !important;
    border-radius: 12px !important;
  }

  .stat-icon-wrapper {
    width: 36px !important;
    height: 36px !important;
    border-radius: 10px !important;
  }

  .stat-value {
    font-size: 16px !important;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .toolbar-left .type-select {
    display: none !important;
  }

  .grid-view {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 10px !important;
    margin-top: 12px !important;
  }

  .grid-item {
    border-radius: 12px !important;
  }

  .grid-item-title {
    font-size: 12px !important;
    line-height: 1.3 !important;
  }

  .grid-item-info {
    padding: 8px 10px !important;
  }

  .quick-filter-pills {
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
    padding-bottom: 6px !important;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .quick-filter-pills::-webkit-scrollbar {
    display: none;
  }

  .drive-page {
    padding: 0;
  }

  .drive-header-card,
  .drive-main-card {
    padding: 16px;
    border-radius: 16px;
  }

  .drive-header-actions {
    flex-wrap: wrap;
    gap: 8px;
    width: 100%;
  }

  .thumb-warmup-pill {
    width: 100%;
    justify-content: center;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-left {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-left > * {
    width: 100% !important;
  }

  .toolbar-right {
    justify-content: flex-end;
  }

  .selection-toolbar {
    flex-direction: column;
    align-items: stretch;
    padding: 10px;
    gap: 10px;
    max-width: 100%;
    overflow-x: hidden;
  }

  .selection-left {
    justify-content: space-between;
    width: 100%;
  }

  .selection-actions {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
    margin-left: 0;
    gap: 8px;
  }

  .selection-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0 !important;
  }

  .pagination-container {
    justify-content: flex-start;
    overflow-x: auto;
  }

  .video-container {
    height: clamp(240px, 50vh, 420px);
  }
}

.footer-tool-btn {
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  color: #475569;
  background: rgba(248, 250, 252, 0.9);
  font-weight: 500;
  transition: all 0.2s ease;
}

.footer-tool-btn:hover {
  background: #ffffff;
  border-color: rgba(56, 189, 248, 0.4);
  color: #0284c7;
}

.nav-media-btn:disabled {
  opacity: 0.35 !important;
  cursor: not-allowed !important;
  pointer-events: none;
}

.autoplay-switch {
  margin-left: 8px;
}

.player-menu-item {
  display: flex;
  flex-direction: column;
  padding: 3px 6px;
}

.player-menu-title {
  font-weight: 600;
  color: #1e293b;
  font-size: 13px;
}

.player-menu-hint {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.action-copy-link {
  color: #0284c7 !important;
}

.action-copy-link:hover {
  color: #38bdf8 !important;
}

.overlay-link {
  background: rgba(255, 255, 255, 0.85);
  color: #0284c7;
}

.overlay-link:hover {
  background: #38bdf8;
  color: #ffffff;
}

.card-action-link:hover {
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
}


.dc-tag-inline {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.2);
  margin-left: 6px;
  flex-shrink: 0;
}

.grid-dc-badge {
  position: absolute;
  top: 8px;
  left: 36px;
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(8px);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
  z-index: 2;
}

.dc-tag-dialog {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(255, 117, 151, 0.15));
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.25);
}

/* 私密/受限频道采集模态框与组件样式 */
.harvest-btn {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%) !important;
  border: none !important;
  color: #ffffff !important;
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.25);
  transition: all 0.25s ease;
}

.harvest-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(56, 189, 248, 0.35);
  opacity: 0.95;
}

.harvester-intro-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.08), rgba(56, 189, 248, 0.08));
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 12px;
  margin-bottom: 18px;
}

.intro-icon-box {
  color: #ff7597;
  padding-top: 2px;
  flex-shrink: 0;
}

.intro-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.intro-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}

.intro-desc code {
  background: rgba(255, 255, 255, 0.7);
  padding: 1px 4px;
  border-radius: 4px;
  color: #0284c7;
  font-size: 11px;
}

.rebrand-switch-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 32px;
}

.rebrand-switch-hint {
  font-size: 12px;
  color: #64748b;
}

.harvester-status-panel {
  margin-top: 16px;
  padding: 14px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
}

.status-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}

.status-panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.status-pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}

.status-pulse-dot.running {
  background: #38bdf8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.3);
  animation: pulse-ring 1.5s infinite;
}

.status-pulse-dot.completed {
  background: #10b981;
}

.status-pulse-dot.cancelled {
  background: #f59e0b;
}

.status-pulse-dot.failed {
  background: #ef4444;
}

@keyframes pulse-ring {
  0% { transform: scale(0.95); opacity: 0.8; }
  50% { transform: scale(1.15); opacity: 1; }
  100% { transform: scale(0.95); opacity: 0.8; }
}

.status-panel-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.harvester-mode-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}

.mode-fast {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.mode-relay {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.harvester-speed-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.harvester-progress-stats {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}

.text-success { color: #10b981; }
.text-warning { color: #f59e0b; }
.text-danger { color: #ef4444; }

.harvester-current-file {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 12px;
  color: #475569;
  background: #ffffff;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.harvester-current-file .file-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
}

.harvester-terminal {
  margin-top: 12px;
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.terminal-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: #1e293b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.term-dots {
  display: flex;
  gap: 5px;
}

.term-dots .dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.dot-red { background: #ef4444; }
.dot-yellow { background: #f59e0b; }
.dot-green { background: #10b981; }

.term-title {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
}

.terminal-body {
  height: 140px;
  overflow-y: auto;
  padding: 8px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  color: #e2e8f0;
}

.term-line {
  word-break: break-all;
}

.text-muted {
  color: #64748b;
}

.harvester-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.start-harvest-btn {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%) !important;
  border: none !important;
  font-weight: 600;
}
.upload-btn {
  background: linear-gradient(135deg, #ff4081 0%, #7c4dff 100%) !important;
  border: none !important;
  color: #ffffff !important;
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(255, 64, 129, 0.3);
  transition: all 0.25s ease;
}

.upload-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(124, 77, 255, 0.4);
  opacity: 0.95;
}

.drive-drag-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.drag-overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 48px 64px;
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.92);
  border: 2px dashed #ff4081;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.25), 0 0 30px rgba(255, 64, 129, 0.3);
}

html.dark .drag-overlay-content {
  background: rgba(30, 41, 59, 0.95);
  border-color: #ff4081;
}

.drag-icon {
  font-size: 56px;
  color: #ff4081;
  animation: bounce-icon 1s infinite alternate ease-in-out;
}

.drag-title {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
}

.drag-desc {
  margin: 0;
  font-size: 14px;
  color: #64748b;
}

@keyframes bounce-icon {
  from { transform: translateY(0); }
  to { transform: translateY(-8px); }
}

.icon-wrap--sakura {
  background: linear-gradient(135deg, rgba(255, 64, 129, 0.15), rgba(124, 77, 255, 0.15)) !important;
  color: #ff4081 !important;
}

.method-card-badge--sakura {
  background: rgba(255, 64, 129, 0.12) !important;
  color: #ff4081 !important;
}
</style>
