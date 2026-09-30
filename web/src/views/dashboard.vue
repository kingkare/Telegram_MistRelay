<template>
  <div class="dashboard-page animate-fade-in">
    <!-- 头部品牌横幅与控制区 -->
    <div class="dashboard-header-card glass-card">
      <div class="dashboard-header-main">
        <div class="dashboard-title-group">
          <div class="dashboard-title-row">
            <h2 class="dashboard-title text-gradient-sakura">
              {{ authStore.isAdmin ? '系统监控仪表板' : '个人云盘工作台' }}
            </h2>
            <span class="dashboard-badge">
              {{ authStore.isAdmin ? 'System Overview' : 'Personal Workspace' }}
            </span>
          </div>
          <p class="dashboard-subtitle">
            {{
              authStore.isAdmin
                ? '实时监测系统硬件负荷、Aria2 传输流量趋势与各 Bot 节点吞吐分流状态。'
                : '管理您的专属 Telegram 物理隔离存储频道、云盘媒体资产与个人传输任务动态。'
            }}
          </p>
        </div>

        <div class="dashboard-header-actions">
          <div class="status-indicator-pill">
            <span class="status-indicator-dot" :class="statusDotClass"></span>
            <span class="status-indicator-text">{{ serverStatusLabel }}</span>
          </div>

          <el-button
            v-if="authStore.isAdmin"
            class="header-btn auto-refresh-btn"
            :type="autoRefresh ? 'primary' : ''"
            :plain="autoRefresh"
            size="default"
            @click="toggleAutoRefresh"
            :title="autoRefresh ? '点击暂停自动轮询' : '点击开启 2 秒平滑自动采样'"
          >
            <span class="refresh-indicator" :class="{ 'is-active': autoRefresh }"></span>
            {{ autoRefresh ? '自动采样中' : '自动采样已停' }}
          </el-button>

          <el-button
            class="header-btn refresh-btn"
            :icon="RefreshRight"
            @click="handleManualRefresh"
            :loading="isRefreshing"
            size="default"
          >
            刷新数据
          </el-button>

          <el-button
            v-if="!authStore.isAdmin"
            class="header-btn jump-btn"
            :icon="Folder"
            @click="$router.push('/drive')"
            size="default"
          >
            TG网盘
          </el-button>

          <el-button
            type="primary"
            class="header-btn jump-btn"
            :icon="Download"
            @click="$router.push('/downloads')"
            size="default"
          >
            任务中心
          </el-button>
        </div>
      </div>

      <!-- 4 大流光指标卡片（管理员视图） -->
      <el-row v-if="authStore.isAdmin" :gutter="14" class="stats-row">
        <el-col :xs="12" :sm="6" v-for="stat in stats" :key="stat.key">
          <div
            class="stat-card glass-card"
            :class="`stat-card--${stat.key}`"
            @click="$router.push('/downloads')"
            title="点击跳转任务调度中心查看详情"
          >
            <div class="stat-card-glow"></div>
            <div class="stat-card-inner">
              <div class="stat-card-top">
                <span class="stat-label">{{ stat.label }}</span>
                <div class="stat-icon-wrap" :style="{ background: stat.color }">
                  <el-icon :size="18"><component :is="stat.icon" /></el-icon>
                </div>
              </div>
              <div class="stat-value-group">
                <span class="stat-value">{{ stat.value.toLocaleString() }}</span>
                <span class="stat-unit">条任务</span>
              </div>
              <div class="stat-desc">
                <span>{{ stat.desc }}</span>
                <el-icon class="stat-arrow"><ArrowRight /></el-icon>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>

      <!-- 4 大流光指标卡片（租户专属视图） -->
      <el-row v-else :gutter="14" class="stats-row">
        <el-col :xs="12" :sm="6" v-for="card in tenantStatCards" :key="card.key">
          <div
            class="stat-card glass-card"
            :class="`stat-card--${card.key}`"
            @click="$router.push(card.route)"
            :title="card.desc"
          >
            <div class="stat-card-glow"></div>
            <div class="stat-card-inner">
              <div class="stat-card-top">
                <span class="stat-label">{{ card.label }}</span>
                <div class="stat-icon-wrap" :style="{ background: card.color }">
                  <el-icon :size="18"><component :is="card.icon" /></el-icon>
                </div>
              </div>
              <div class="stat-value-group">
                <span class="stat-value">{{ card.displayValue }}</span>
                <span class="stat-unit">{{ card.unit }}</span>
              </div>
              <div class="stat-desc">
                <span>{{ card.desc }}</span>
                <el-icon class="stat-arrow"><ArrowRight /></el-icon>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 租户专属：新人快速起航向导看板 (非管理员专属) -->
    <div v-if="!authStore.isAdmin" class="tenant-onboarding-wrapper">
      <div v-if="!isOnboardingCollapsed" class="tenant-onboarding-card glass-card">
        <div class="onboarding-card-header">
          <div class="onboarding-title-wrap">
            <span class="onboarding-star-badge">🌟 新人快速起航向导</span>
            <span class="onboarding-sub">跟随 4 步任务快速掌握专属云盘、机器人极速存取与 4K 秒播</span>
          </div>
          <div class="onboarding-actions-wrap">
            <span class="onboarding-progress-badge">
              通关进度 {{ onboardingCompletedCount }}/4
            </span>
            <el-button size="small" class="onboarding-btn-guide" :icon="Reading" @click="openUserGuide('quickstart')">
              完整新手教程
            </el-button>
            <el-button size="small" class="onboarding-btn-collapse" :icon="Fold" @click="toggleOnboardingCollapse">
              收起向导
            </el-button>
          </div>
        </div>

        <div class="onboarding-progress-bar-wrap">
          <el-progress
            :percentage="Math.round((onboardingCompletedCount / 4) * 100)"
            :stroke-width="8"
            :show-text="false"
            color="linear-gradient(135deg, #ff7597 0%, #38bdf8 100%)"
          />
        </div>

        <div class="onboarding-steps-grid">
          <!-- Step 1 -->
          <div class="onboarding-step-box is-completed">
            <div class="step-box-header">
              <span class="step-num-pill">1</span>
              <span class="step-title">专属存储空间绑定</span>
              <el-tag size="small" type="success" effect="plain" class="step-status-tag">
                <el-icon><CircleCheck /></el-icon> 已就绪
              </el-tag>
            </div>
            <p class="step-desc">
              已自动分配同区 Telegram DC{{ authStore.user?.dc_id || 5 }} 物理隔离独立频道，零泄漏风险。
            </p>
            <div class="step-footer">
              <span class="step-meta">已绑定专属频道</span>
            </div>
          </div>

          <!-- Step 2 -->
          <div class="onboarding-step-box" :class="{ 'is-completed': tenantFilesCount > 0 }">
            <div class="step-box-header">
              <span class="step-num-pill">2</span>
              <span class="step-title">首份媒体资产入库</span>
              <el-tag v-if="tenantFilesCount > 0" size="small" type="success" effect="plain" class="step-status-tag">
                <el-icon><CircleCheck /></el-icon> 已存入 {{ tenantFilesCount }} 项
              </el-tag>
              <el-tag v-else size="small" type="warning" effect="plain" class="step-status-tag">
                待入库
              </el-tag>
            </div>
            <p class="step-desc">
              在手机/桌面端 TG 将视频发给机器人，或向机器人发送磁力链接 (magnet:) 自动下载。
            </p>
            <div class="step-footer">
              <el-button size="small" type="primary" plain :icon="Promotion" @click="openTelegramBot">
                私聊机器人
              </el-button>
              <el-button size="small" text @click="openUserGuide('upload')">
                查看入库方式
              </el-button>
            </div>
          </div>

          <!-- Step 3 -->
          <div class="onboarding-step-box">
            <div class="step-box-header">
              <span class="step-num-pill">3</span>
              <span class="step-title">体验云盘与 M3U 串流</span>
              <el-tag size="small" type="primary" effect="plain" class="step-status-tag">
                即点即播
              </el-tag>
            </div>
            <p class="step-desc">
              在 TG 网盘中享受 4K 在线播放，或一键导出 M3U 导入 PotPlayer / Infuse 原画硬解。
            </p>
            <div class="step-footer">
              <el-button size="small" type="primary" :icon="Folder" @click="$router.push('/drive')">
                前往 TG 网盘
              </el-button>
              <el-button size="small" text @click="openUserGuide('streaming')">
                播放器指南
              </el-button>
            </div>
          </div>

          <!-- Step 4 -->
          <div class="onboarding-step-box">
            <div class="step-box-header">
              <span class="step-num-pill">4</span>
              <span class="step-title">挂载私有 VPS 边缘分流</span>
              <el-tag size="small" type="info" effect="plain" class="step-status-tag">
                0ms 极速
              </el-tag>
            </div>
            <p class="step-desc">
              一键 SSH 部署私有 VPS 边缘中继，就近缓存加速，彻底告别 Telegram 跨国限速。
            </p>
            <div class="step-footer">
              <el-button size="small" :icon="Share" @click="$router.push('/edge-nodes')">
                探索边缘节点
              </el-button>
              <el-button size="small" text @click="openUserGuide('edge')">
                纳管教程
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 折叠态轻量展开卡片 -->
      <div v-else class="onboarding-collapsed-card glass-card" @click="toggleOnboardingCollapse">
        <div class="collapsed-left">
          <span class="collapsed-star">🌟</span>
          <span class="collapsed-title">新人快速起航向导</span>
          <span class="collapsed-progress">已完成 {{ onboardingCompletedCount }}/4 步</span>
        </div>
        <div class="collapsed-right">
          <span class="collapsed-hint">点击展开向导任务</span>
          <el-icon><Expand /></el-icon>
        </div>
      </div>
    </div>

    <!-- 管理员：实时图表与硬件资源监控 -->
    <el-row v-if="authStore.isAdmin" :gutter="16" class="charts-row">
      <!-- 实时传输图表 -->
      <el-col :xs="24" :lg="16">
        <div class="chart-card glass-card">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div class="panel-icon-pill icon-pill-primary">
                <el-icon><TrendCharts /></el-icon>
              </div>
              <div>
                <h3 class="panel-title">实时网络与传输趋势</h3>
                <p class="panel-subtitle">最近采样窗口上传速度、下载速度及 IO 吞吐监测</p>
              </div>
            </div>
            <div class="panel-tags">
              <el-tag size="small" effect="plain" class="metric-tag tag-upload">
                <span class="dot dot-upload"></span> 上传 {{ currentUploadSpeed }}
              </el-tag>
              <el-tag size="small" effect="plain" class="metric-tag tag-download">
                <span class="dot dot-download"></span> 下载 {{ currentDownloadSpeed }}
              </el-tag>
            </div>
          </div>
          <div class="chart-body">
            <div class="chart-container" ref="chartRef"></div>
          </div>
        </div>
      </el-col>

      <!-- 系统硬件负载 -->
      <el-col :xs="24" :lg="8">
        <div class="system-load-card glass-card">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div class="panel-icon-pill icon-pill-sky">
                <el-icon><Cpu /></el-icon>
              </div>
              <div>
                <h3 class="panel-title">系统核心负载</h3>
                <p class="panel-subtitle">CPU 占用、内存消耗与本地磁盘可用余量</p>
              </div>
            </div>
          </div>

          <div v-if="systemResources && systemResources.cpu && systemResources.memory && systemResources.disk" class="system-resources">
            <!-- CPU -->
            <div class="resource-item">
              <div class="resource-top">
                <div class="resource-label-group">
                  <span class="resource-icon-badge badge-cpu"><el-icon><Cpu /></el-icon></span>
                  <span class="resource-name">中央处理器 CPU</span>
                </div>
                <span class="resource-val-tag" :class="getResourceTagClass(systemResources.cpu.percent)">
                  {{ systemResources.cpu.percent.toFixed(1) }}%
                </span>
              </div>
              <div class="resource-progress-wrap">
                <el-progress
                  :percentage="Math.min(100, Math.max(0, systemResources.cpu.percent))"
                  :stroke-width="8"
                  :show-text="false"
                  :color="getResourceColor(systemResources.cpu.percent)"
                />
              </div>
            </div>

            <!-- 内存 -->
            <div class="resource-item">
              <div class="resource-top">
                <div class="resource-label-group">
                  <span class="resource-icon-badge badge-mem"><el-icon><DataBoard /></el-icon></span>
                  <span class="resource-name">运行内存 RAM</span>
                </div>
                <span class="resource-val-tag" :class="getResourceTagClass(systemResources.memory.percent)">
                  {{ systemResources.memory.percent.toFixed(1) }}%
                </span>
              </div>
              <div class="resource-progress-wrap">
                <el-progress
                  :percentage="Math.min(100, Math.max(0, systemResources.memory.percent))"
                  :stroke-width="8"
                  :show-text="false"
                  :color="getResourceColor(systemResources.memory.percent)"
                />
              </div>
              <div class="resource-detail-bar">
                <span>已用 {{ formatBytes(systemResources.memory.used) }}</span>
                <span class="text-separator">/</span>
                <span>总量 {{ formatBytes(systemResources.memory.total) }}</span>
              </div>
            </div>

            <!-- 硬盘 -->
            <div class="resource-item">
              <div class="resource-top">
                <div class="resource-label-group">
                  <span class="resource-icon-badge badge-disk"><el-icon><Files /></el-icon></span>
                  <span class="resource-name">本地存储 Disk</span>
                </div>
                <span class="resource-val-tag" :class="getResourceTagClass(systemResources.disk.percent)">
                  {{ systemResources.disk.percent.toFixed(1) }}%
                </span>
              </div>
              <div class="resource-progress-wrap">
                <el-progress
                  :percentage="Math.min(100, Math.max(0, systemResources.disk.percent))"
                  :stroke-width="8"
                  :show-text="false"
                  :color="getResourceColor(systemResources.disk.percent)"
                />
              </div>
              <div class="resource-detail-bar">
                <span>已用 {{ formatBytes(systemResources.disk.used) }}</span>
                <span class="text-separator">/</span>
                <span>总量 {{ formatBytes(systemResources.disk.total) }}</span>
              </div>
            </div>
          </div>
          <el-skeleton v-else :rows="5" animated class="p-4" />
        </div>
      </el-col>
    </el-row>

    <!-- 租户：个人云盘存储结构分析与专属空间档案 -->
    <el-row v-else :gutter="16" class="charts-row">
      <el-col :xs="24" :lg="14">
        <div class="system-load-card glass-card">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div class="panel-icon-pill icon-pill-primary">
                <el-icon><Files /></el-icon>
              </div>
              <div>
                <h3 class="panel-title">云盘存储结构分析</h3>
                <p class="panel-subtitle">专属频道内各类媒体资产数量与占比分布</p>
              </div>
            </div>
            <el-button size="small" round class="more-link-btn" @click="$router.push('/drive')">
              进入云盘 <el-icon class="ml-1"><ArrowRight /></el-icon>
            </el-button>
          </div>

          <div class="system-resources">
            <div v-for="item in tenantStorageBreakdown" :key="item.key" class="resource-item">
              <div class="resource-top">
                <div class="resource-label-group">
                  <span class="resource-icon-badge" :class="item.badgeClass">
                    <el-icon><component :is="item.icon" /></el-icon>
                  </span>
                  <span class="resource-name">{{ item.label }}</span>
                </div>
                <span class="resource-val-tag tag-normal">
                  {{ item.count }} 项 ({{ item.percent.toFixed(1) }}%)
                </span>
              </div>
              <div class="resource-progress-wrap">
                <el-progress
                  :percentage="item.percent"
                  :stroke-width="8"
                  :show-text="false"
                  :color="item.color"
                />
              </div>
            </div>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :lg="10">
        <div class="activity-card glass-card">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div class="panel-icon-pill icon-pill-sky">
                <el-icon><InfoFilled /></el-icon>
              </div>
              <div>
                <h3 class="panel-title">专属存储频道与账户档案</h3>
                <p class="panel-subtitle">物理隔离存储频道、归属 DC 与账号绑定状态</p>
              </div>
            </div>
          </div>

          <div class="system-info-body">
            <div class="info-grid">
              <div class="info-box">
                <span class="info-label">当前租户账号</span>
                <span class="info-val-text">{{ authStore.user?.username || '-' }}</span>
              </div>

              <div class="info-box">
                <span class="info-label">绑定 Telegram</span>
                <span class="info-val-text">
                  {{
                    authStore.user?.tg_username
                      ? `@${authStore.user.tg_username}`
                      : authStore.user?.tg_user_id || '未绑定'
                  }}
                </span>
              </div>

              <div class="info-box">
                <span class="info-label">归属数据中心</span>
                <span class="info-val-badge">DC{{ authStore.user?.dc_id || 5 }}</span>
              </div>

              <div class="info-box">
                <span class="info-label">服务网关状态</span>
                <div class="info-value-wrap">
                  <span class="online-pill">
                    <span class="online-dot"></span>
                    {{ status?.server_status === 'running' ? '在线运行' : '连接正常' }}
                  </span>
                </div>
              </div>

              <div class="info-box col-span-full">
                <span class="info-label">专属隔离存储频道</span>
                <span class="info-val-highlight">{{ tenantChannelDisplay }}</span>
              </div>

              <div class="info-box col-span-full">
                <span class="info-label">Telegram 服务机器人</span>
                <span class="version-tag">{{ status?.telegram_bot || '@MistRelayBot' }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 最近活动与系统环境信息 -->
    <el-row :gutter="16" class="activity-row">
      <!-- 最近下载任务 -->
      <el-col :xs="24" :lg="authStore.isAdmin ? 12 : 24">
        <div class="activity-card glass-card">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div class="panel-icon-pill icon-pill-primary">
                <el-icon><Download /></el-icon>
              </div>
              <div>
                <h3 class="panel-title">{{ authStore.isAdmin ? '最近任务动态' : '最近个人任务动态' }}</h3>
                <p class="panel-subtitle">最近 10 项下载与转存任务最新流转</p>
              </div>
            </div>
            <el-button size="small" round class="more-link-btn" @click="$router.push('/downloads')">
              查看全部 <el-icon class="ml-1"><ArrowRight /></el-icon>
            </el-button>
          </div>

          <div class="table-wrap">
            <!-- 移动端流式卡片 -->
            <div v-if="recentDownloads.length > 0" class="mobile-recent-downloads md:hidden flex flex-col gap-2">
              <div
                v-for="row in recentDownloads"
                :key="row.id || row.file_name"
                class="p-2.5 rounded-xl border border-pink-100/60 bg-white/80 shadow-sm flex items-center justify-between gap-2 cursor-pointer hover:bg-white transition-all"
                @click="$router.push('/downloads')"
              >
                <div class="flex items-center gap-2 min-w-0">
                  <el-icon class="file-type-icon shrink-0" :class="getFileIconClass(row.file_name || '')">
                    <component :is="getFileIcon(row.file_name || '')" />
                  </el-icon>
                  <div class="flex flex-col min-w-0">
                    <span class="text-xs font-semibold text-gray-800 truncate" :title="row.file_name">{{ row.file_name }}</span>
                    <span class="text-[10px] text-gray-400 font-mono">{{ formatDate(row.created_at) }}</span>
                  </div>
                </div>
                <span class="custom-status-badge shrink-0 scale-90" :class="`badge-status-${row.status}`">
                  {{ getStatusText(row.status) }}
                </span>
              </div>
            </div>
            <div v-else class="md:hidden text-center py-6 text-xs text-gray-400">
              暂无下载记录
            </div>

            <!-- 桌面端表格 -->
            <div class="hidden md:block">
              <el-table
                :data="recentDownloads"
                style="width: 100%"
                size="default"
                :show-header="recentDownloads.length > 0"
                empty-text="暂无下载记录"
                class="custom-table"
              >
                <el-table-column prop="file_name" label="文件名" min-width="160">
                  <template #default="{ row }">
                    <div class="file-name-cell">
                      <el-icon class="file-type-icon" :class="getFileIconClass(row.file_name || '')">
                        <component :is="getFileIcon(row.file_name || '')" />
                      </el-icon>
                      <span class="file-name-text" :title="row.file_name">{{ row.file_name }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="100" align="center">
                  <template #default="{ row }">
                    <span class="custom-status-badge" :class="`badge-status-${row.status}`">
                      {{ getStatusText(row.status) }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="created_at" label="时间" width="140" align="right">
                  <template #default="{ row }">
                    <span class="time-cell">{{ formatDate(row.created_at) }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </el-col>

      <!-- 系统与节点信息（仅管理员展示） -->
      <el-col v-if="authStore.isAdmin" :xs="24" :lg="12">
        <div class="activity-card glass-card">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div class="panel-icon-pill icon-pill-sky">
                <el-icon><InfoFilled /></el-icon>
              </div>
              <div>
                <h3 class="panel-title">系统与节点运行状态</h3>
                <p class="panel-subtitle">服务生命周期、TG Bot 连通度及各分流负载</p>
              </div>
            </div>
          </div>

          <div v-if="status" class="system-info-body">
            <div class="info-grid">
              <div class="info-box">
                <span class="info-label">运行状态</span>
                <div class="info-value-wrap">
                  <span class="online-pill">
                    <span class="online-dot"></span>
                    {{ status.server_status || '运行中' }}
                  </span>
                </div>
              </div>

              <div class="info-box">
                <span class="info-label">运行时长</span>
                <span class="info-val-highlight">{{ status.uptime || '-' }}</span>
              </div>

              <div class="info-box">
                <span class="info-label">Telegram Bot</span>
                <span class="info-val-text">{{ status.telegram_bot || '-' }}</span>
              </div>

              <div class="info-box">
                <span class="info-label">已连接机器人</span>
                <span class="info-val-badge">{{ status.connected_bots || 0 }} 个节点</span>
              </div>

              <div class="info-box col-span-full">
                <span class="info-label">核心版本</span>
                <span class="version-tag">{{ status.version || 'v3.0.0' }}</span>
              </div>
            </div>

            <!-- 机器人负载 -->
            <div v-if="status.loads && Object.keys(status.loads).length > 0" class="bot-loads">
              <div class="bot-loads-header">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="bot-loads-title">分流机器人节点负荷</span>
                  <span v-if="status.channel_info?.no_join_balancing_active" class="no-join-indicator" title="免加群自动负载均衡已激活">
                    ✨ 免加频道分流就绪
                  </span>
                </div>
                <div class="bot-loads-header-right">
                  <span class="bot-loads-count">
                    共 {{ totalBotLoadsCount }} 个活跃 Worker
                    <span v-if="busyBotLoadsCount > 0" class="busy-pill-hint">· {{ busyBotLoadsCount }} 忙碌</span>
                  </span>
                </div>
              </div>

              <!-- 节点较多时提供快捷筛选与检索，避免过度占用垂直高度 -->
              <div v-if="totalBotLoadsCount > 6" class="bot-loads-toolbar">
                <div class="bot-filter-pills">
                  <button
                    type="button"
                    class="filter-pill"
                    :class="{ 'is-active': botLoadFilter === 'all' }"
                    @click="botLoadFilter = 'all'"
                  >
                    全部 ({{ totalBotLoadsCount }})
                  </button>
                  <button
                    type="button"
                    class="filter-pill pill-busy"
                    :class="{ 'is-active': botLoadFilter === 'busy' }"
                    @click="botLoadFilter = 'busy'"
                  >
                    忙碌 ({{ busyBotLoadsCount }})
                  </button>
                  <button
                    type="button"
                    class="filter-pill"
                    :class="{ 'is-active': botLoadFilter === 'idle' }"
                    @click="botLoadFilter = 'idle'"
                  >
                    空闲 ({{ idleBotLoadsCount }})
                  </button>
                </div>
                <div v-if="totalBotLoadsCount > 8" class="bot-search-wrap">
                  <el-input
                    v-model="botLoadSearch"
                    size="small"
                    placeholder="过滤节点..."
                    clearable
                    class="bot-search-input"
                  >
                    <template #prefix>
                      <el-icon><Search /></el-icon>
                    </template>
                  </el-input>
                </div>
              </div>

              <div
                v-if="filteredBotLoadItems.length > 0"
                class="bot-loads-grid"
                :class="{ 'is-expanded': isBotLoadsExpanded }"
              >
                <div
                  v-for="item in filteredBotLoadItems"
                  :key="item.key"
                  class="bot-load-chip"
                  :class="{ 'is-busy': item.load > 0 }"
                >
                  <div class="bot-chip-top">
                    <span class="bot-chip-name" :title="item.displayName">{{ item.displayName }}</span>
                    <span class="bot-chip-tag" :class="getLoadChipClass(item.load)">{{ item.load }} 项</span>
                  </div>
                  <div class="bot-chip-bar">
                    <div
                      class="bot-chip-fill"
                      :style="{ width: `${getLoadPercentage(item.load)}%`, background: getLoadColor(item.load) }"
                    ></div>
                  </div>
                </div>
              </div>
              <div v-else class="bot-loads-empty">
                <el-icon class="empty-icon"><InfoFilled /></el-icon>
                <span>未找到匹配的分流节点</span>
              </div>

              <!-- 节点过多时的折叠与跳转栏 -->
              <div v-if="totalBotLoadsCount > 6" class="bot-loads-footer">
                <span class="bot-footer-summary">
                  显示 {{ filteredBotLoadItems.length }} / {{ totalBotLoadsCount }} 节点
                </span>
                <div class="bot-footer-actions">
                  <el-button
                    size="small"
                    text
                    class="bot-expand-btn"
                    @click="isBotLoadsExpanded = !isBotLoadsExpanded"
                  >
                    {{ isBotLoadsExpanded ? '收起紧凑视图' : '展开更多' }}
                    <el-icon class="ml-1">
                      <component :is="isBotLoadsExpanded ? ArrowUp : ArrowDown" />
                    </el-icon>
                  </el-button>
                  <el-button
                    size="small"
                    text
                    type="primary"
                    class="bot-jump-btn"
                    @click="$router.push('/bots')"
                  >
                    集群专页
                    <el-icon class="ml-1"><ArrowRight /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
          <el-skeleton v-else :rows="5" animated class="p-4" />
        </div>
      </el-col>
    </el-row>
    <!-- 首次登录欢迎引导弹窗 (非管理员租户) -->
    <FirstLoginWelcomeDialog v-if="!authStore.isAdmin" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/api'
import { useIntervalFn, useResizeObserver } from '@vueuse/core'
import * as echarts from 'echarts'
import {
  Check,
  Delete,
  Warning,
  Document,
  Cpu,
  DataBoard,
  Files,
  Folder,
  RefreshRight,
  Download,
  TrendCharts,
  ArrowRight,
  VideoCamera,
  Headset,
  Picture,
  Box,
  InfoFilled,
  Search,
  ArrowDown,
  ArrowUp,
  Reading,
  Promotion,
  Share,
  Fold,
  Expand,
  CircleCheck
} from '@element-plus/icons-vue'
import FirstLoginWelcomeDialog from '@/components/FirstLoginWelcomeDialog.vue'
import {
  getStatus,
  getDownloads,
  getSystemTrend,
  getDownloadStatistics,
  getUploadStatistics,
  getSystemResources,
  getTelegramUsage,
  type TrendPoint
} from '@/api'
import type { ServerStatus, DownloadRecord, SystemResources, TelegramUsageStats } from '@/types/api'
import { useAuthStore } from '@/stores/auth'
import { formatDate, getStatusText } from '@/utils/formatters'

const authStore = useAuthStore()
const status = ref<ServerStatus | null>(null)
const systemResources = ref<SystemResources | null>(null)
const usageStats = ref<TelegramUsageStats | null>(null)
const tenantTaskSummary = ref({
  total: 0,
  completed: 0,
  active: 0,
  failed: 0,
})
const recentDownloads = ref<DownloadRecord[]>([])
const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const isRefreshing = ref(false)
const autoRefresh = ref(true)
const currentUploadSpeed = ref('0 B/s')
const currentDownloadSpeed = ref('0 B/s')

const stats = ref([
  {
    key: 'completed',
    label: '传输完成',
    desc: '已成功下载并转存',
    value: 0,
    icon: Check,
    color: 'linear-gradient(135deg, #10b981 0%, #059669 100%)'
  },
  {
    key: 'cleaned',
    label: '清理归档',
    desc: '本地生命周期已释放',
    value: 0,
    icon: Delete,
    color: 'linear-gradient(135deg, #06b6d4 0%, #0284c7 100%)'
  },
  {
    key: 'failed',
    label: '失败待查',
    desc: '传输中断或鉴权异常',
    value: 0,
    icon: Warning,
    color: 'linear-gradient(135deg, #fb7185 0%, #e11d48 100%)'
  },
  {
    key: 'total',
    label: '总调度量',
    desc: '累计全量流转任务',
    value: 0,
    icon: Document,
    color: 'linear-gradient(135deg, #ff7597 0%, #38bdf8 100%)'
  }
])

const tenantChannelDisplay = computed(() => {
  const uname = authStore.user?.bin_channel_username || status.value?.channel_info?.public_handle
  const cid = authStore.user?.bin_channel_id || status.value?.channel_info?.channel_id
  if (uname && !String(uname).startsWith('channel_')) {
    return `@${uname}${cid ? ` (${cid})` : ''}`
  }
  if (cid) {
    return `私有频道 (${cid})`
  }
  return '待分配专属存储频道'
})

const isOnboardingCollapsed = ref(localStorage.getItem('mistrelay_onboarding_collapsed') === 'true')

function toggleOnboardingCollapse() {
  isOnboardingCollapsed.value = !isOnboardingCollapsed.value
  localStorage.setItem('mistrelay_onboarding_collapsed', String(isOnboardingCollapsed.value))
}

const tenantFilesCount = computed(() => usageStats.value?.total_count || 0)

const onboardingCompletedCount = computed(() => {
  let count = 1
  if (tenantFilesCount.value > 0) count += 1
  return count
})

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

function openUserGuide(tab = 'quickstart') {
  window.dispatchEvent(new CustomEvent('open-user-guide', { detail: { tab } }))
}

const tenantStatCards = computed(() => [
  {
    key: 'files',
    label: '云盘文件总数',
    displayValue: (usageStats.value?.total_count || 0).toLocaleString(),
    unit: '个文件',
    desc: '点击进入个人 TG 网盘',
    route: '/drive',
    icon: Files,
    color: 'linear-gradient(135deg, #38bdf8 0%, #0284c7 100%)',
  },
  {
    key: 'storage',
    label: '云盘累计占用',
    displayValue: formatBytes(usageStats.value?.total_size || 0),
    unit: '云端存储',
    desc: '专属隔离频道媒体总容量',
    route: '/drive',
    icon: DataBoard,
    color: 'linear-gradient(135deg, #ff7597 0%, #e11d48 100%)',
  },
  {
    key: 'completed',
    label: '传输完成任务',
    displayValue: tenantTaskSummary.value.completed.toLocaleString(),
    unit: '条任务',
    desc: '个人已成功下载并转存',
    route: '/downloads',
    icon: Check,
    color: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
  },
  {
    key: 'active_or_failed',
    label: '进行中 / 待查',
    displayValue: (tenantTaskSummary.value.active + tenantTaskSummary.value.failed).toLocaleString(),
    unit: '条任务',
    desc: `进行中 ${tenantTaskSummary.value.active} · 失败 ${tenantTaskSummary.value.failed}`,
    route: '/downloads',
    icon: Warning,
    color: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
  },
])

const tenantStorageBreakdown = computed(() => {
  const total = usageStats.value?.total_count || 0
  const calcPercent = (count: number) => (total > 0 ? Math.min(100, (count / total) * 100) : 0)
  const videos = usageStats.value?.videos || 0
  const images = usageStats.value?.images || 0
  const audios = usageStats.value?.audios || 0
  const documents = usageStats.value?.documents || 0

  return [
    {
      key: 'videos',
      label: '视频媒体 Video',
      count: videos,
      percent: calcPercent(videos),
      icon: VideoCamera,
      badgeClass: 'badge-cpu',
      color: '#38bdf8',
    },
    {
      key: 'images',
      label: '高清图片 Image',
      count: images,
      percent: calcPercent(images),
      icon: Picture,
      badgeClass: 'badge-mem',
      color: '#ff7597',
    },
    {
      key: 'audios',
      label: '音频曲目 Audio',
      count: audios,
      percent: calcPercent(audios),
      icon: Headset,
      badgeClass: 'badge-disk',
      color: '#a855f7',
    },
    {
      key: 'documents',
      label: '文档与其他 Document',
      count: documents,
      percent: calcPercent(documents),
      icon: Document,
      badgeClass: 'badge-cpu',
      color: '#10b981',
    },
  ]
})

const serverStatusLabel = computed(() => {
  if (!authStore.isAdmin) {
    const hasChannel = Boolean(authStore.user?.bin_channel_id || status.value?.channel_info?.channel_id)
    return hasChannel ? '专属频道已就绪' : '待分配专属频道'
  }
  if (!status.value) return '检测中...'
  return status.value.server_status === 'running' ? '服务运行良好' : (status.value.server_status || '在线')
})

const statusDotClass = computed(() => {
  if (!authStore.isAdmin) {
    const hasChannel = Boolean(authStore.user?.bin_channel_id || status.value?.channel_info?.channel_id)
    return hasChannel ? 'status-dot--success' : 'status-dot--warning'
  }
  if (!status.value) return 'status-dot--warning'
  return status.value.server_status === 'running' ? 'status-dot--success' : 'status-dot--warning'
})

function formatSpeed(bytesPerSec: number): string {
  if (!bytesPerSec || bytesPerSec <= 0) return '0 B/s'
  if (bytesPerSec > 1024 * 1024) {
    return (bytesPerSec / (1024 * 1024)).toFixed(2) + ' MB/s'
  } else if (bytesPerSec > 1024) {
    return (bytesPerSec / 1024).toFixed(1) + ' KB/s'
  }
  return bytesPerSec.toFixed(0) + ' B/s'
}

function initChart() {
  if (!chartRef.value) return

  chartInstance = echarts.init(chartRef.value)

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.94)',
      borderColor: 'rgba(255, 143, 171, 0.35)',
      borderWidth: 1,
      padding: [10, 14],
      textStyle: {
        color: '#1f2937',
        fontSize: 12
      },
      extraCssText: 'box-shadow: 0 10px 25px rgba(255, 117, 151, 0.15); border-radius: 12px; backdrop-filter: blur(8px);',
      formatter: function (params: any) {
        let result = `<div style="font-weight: 600; margin-bottom: 6px; color: #4b5563;">${params[0].axisValueLabel}</div>`
        params.forEach((param: any) => {
          let value = param.value
          let formattedValue = ''

          if (value > 1024 * 1024) {
            formattedValue = (value / (1024 * 1024)).toFixed(2) + ' MB/s'
          } else if (value > 1024) {
            formattedValue = (value / 1024).toFixed(2) + ' KB/s'
          } else {
            formattedValue = (value || 0) + ' B/s'
          }

          result += `<div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 3px 0;">
            <span style="display: flex; align-items: center; gap: 6px;">
              ${param.marker} <span style="color: #6b7280;">${param.seriesName}</span>
            </span>
            <span style="font-weight: 600; font-family: monospace;">${formattedValue}</span>
          </div>`
        })
        return result
      }
    },
    legend: {
      data: ['上传速度', '下载速度', 'IO占用'],
      bottom: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: {
        color: '#6b7280',
        fontSize: 12
      }
    },
    grid: {
      left: '2%',
      right: '3%',
      bottom: '12%',
      top: '6%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: [],
      axisLine: {
        lineStyle: { color: 'rgba(255, 143, 171, 0.25)' }
      },
      axisLabel: {
        color: '#9ca3af',
        fontSize: 11,
        formatter: (value: string) => {
          const timestamp = parseInt(value)
          if (isNaN(timestamp)) return value
          const date = new Date(timestamp)
          const utcHours = date.getUTCHours()
          const utcMinutes = date.getUTCMinutes()
          const utcSeconds = date.getUTCSeconds()
          const cnHours = (utcHours + 8) % 24
          return (
            cnHours.toString().padStart(2, '0') +
            ':' +
            utcMinutes.toString().padStart(2, '0') +
            ':' +
            utcSeconds.toString().padStart(2, '0')
          )
        }
      }
    },
    yAxis: {
      type: 'value',
      splitLine: {
        lineStyle: {
          color: 'rgba(229, 231, 235, 0.6)',
          type: 'dashed'
        }
      },
      axisLabel: {
        color: '#9ca3af',
        fontSize: 11,
        formatter: (value: number) => {
          if (value > 1024 * 1024) {
            return (value / (1024 * 1024)).toFixed(1) + ' M'
          } else if (value > 1024) {
            return (value / 1024).toFixed(1) + ' K'
          }
          return value.toString()
        }
      }
    },
    series: [
      {
        name: '上传速度',
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        lineStyle: {
          width: 2.5,
          color: '#ff7597'
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(255, 117, 151, 0.35)' },
            { offset: 1, color: 'rgba(255, 117, 151, 0.01)' }
          ])
        },
        data: []
      },
      {
        name: '下载速度',
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        lineStyle: {
          width: 2.5,
          color: '#38bdf8'
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(56, 189, 248, 0.35)' },
            { offset: 1, color: 'rgba(56, 189, 248, 0.01)' }
          ])
        },
        data: []
      },
      {
        name: 'IO占用',
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        lineStyle: {
          width: 2,
          color: '#fbbf24',
          type: 'dotted'
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(251, 191, 36, 0.2)' },
            { offset: 1, color: 'rgba(251, 191, 36, 0.01)' }
          ])
        },
        data: []
      }
    ],
    color: ['#ff7597', '#38bdf8', '#fbbf24']
  }

  chartInstance.setOption(option)
}

function updateChart(data: TrendPoint[]) {
  if (!chartInstance || !data || data.length === 0) return

  const timestamps = data.map(p => p.timestamp)
  const uploads = data.map(p => p.upload)
  const downloads = data.map(p => p.download)
  const ios = data.map(p => p.io)

  // 更新当前速度展示
  const latest = data[data.length - 1]
  if (latest) {
    currentUploadSpeed.value = formatSpeed(latest.upload)
    currentDownloadSpeed.value = formatSpeed(latest.download)
  }

  chartInstance.setOption({
    xAxis: {
      data: timestamps
    },
    series: [
      { data: uploads },
      { data: downloads },
      { data: ios }
    ]
  })
}

function fetchTrend() {
  if (!authStore.isAdmin) return
  getSystemTrend()
    .then(response => {
      if (response.success && response.data) {
        updateChart(response.data)
      }
    })
    .catch(console.error)
}

function fetchSystemResources() {
  if (!authStore.isAdmin) return
  getSystemResources()
    .then(response => {
      if (response.success && response.data) {
        systemResources.value = response.data
      }
    })
    .catch(err => console.error('获取系统资源失败:', err))
}

function fetchTenantUsage() {
  if (authStore.isAdmin) return
  getTelegramUsage()
    .then(response => {
      if (response.success && response.data) {
        usageStats.value = response.data
      }
    })
    .catch(err => console.error('获取个人云盘容量失败:', err))
}

function fetchData() {
  getStatus()
    .then(data => {
      status.value = data
    })
    .catch(err => console.error('获取状态失败:', err))

  Promise.all([
    getDownloadStatistics(),
    getUploadStatistics()
  ])
    .then(([downloadResponse, uploadResponse]) => {
      const downloadData = downloadResponse.success ? downloadResponse.data : null
      const uploadData = uploadResponse.success ? uploadResponse.data : null

      if (downloadData || uploadData) {
        const totalTasks = downloadData?.total || 0
        const activeCount = (downloadData?.downloading || 0) + (downloadData?.pending || 0) + (downloadData?.waiting || 0)
        tenantTaskSummary.value = {
          total: totalTasks,
          completed: downloadData?.completed || 0,
          active: activeCount,
          failed: downloadData?.failed || 0,
        }
        updateStats({
          completed: downloadData?.completed || 0,
          cleaned: uploadData?.cleaned || 0,
          failed: downloadData?.failed || 0,
          total: totalTasks
        })
      }
    })
    .catch(err => console.error('获取统计失败:', err))

  getDownloads(10)
    .then(response => {
      if (response.success) {
        if (response.grouped && Array.isArray(response.data)) {
          const allDownloads: DownloadRecord[] = []
          response.data.forEach((group: any) => {
            if (group.downloads && Array.isArray(group.downloads)) {
              allDownloads.push(...group.downloads)
            }
          })
          recentDownloads.value = allDownloads.slice(0, 10)
        } else {
          const data = (response.data as DownloadRecord[]) || []
          recentDownloads.value = data.slice(0, 10)
        }
      }
    })
    .catch(err => console.error('获取下载记录失败:', err))

  if (authStore.isAdmin) {
    fetchTrend()
  } else {
    fetchTenantUsage()
  }
}

function updateStats(statistics: { completed: number; cleaned: number; failed: number; total: number }) {
  stats.value.forEach(stat => {
    switch (stat.key) {
      case 'completed':
        stat.value = statistics.completed || 0
        break
      case 'cleaned':
        stat.value = statistics.cleaned || 0
        break
      case 'failed':
        stat.value = statistics.failed || 0
        break
      case 'total':
        stat.value = statistics.total || 0
        break
      default:
        stat.value = 0
    }
  })
}

async function handleManualRefresh() {
  isRefreshing.value = true
  try {
    fetchData()
    if (authStore.isAdmin) {
      fetchSystemResources()
      fetchTrend()
    } else {
      fetchTenantUsage()
    }
  } finally {
    setTimeout(() => {
      isRefreshing.value = false
    }, 600)
  }
}

// 定时轮询（仅管理员开启 2 秒硬件与趋势采样）
const { pause: pauseTrend, resume: resumeTrend } = useIntervalFn(fetchTrend, 2000, { immediate: false })
const { pause: pauseResources, resume: resumeResources } = useIntervalFn(fetchSystemResources, 2000, { immediate: false })
const { pause: pauseData, resume: resumeData } = useIntervalFn(fetchData, 30000)

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value && authStore.isAdmin) {
    resumeTrend()
    resumeResources()
    resumeData()
  } else {
    pauseTrend()
    pauseResources()
    pauseData()
  }
}

function getFileIcon(fileName: string) {
  const ext = fileName?.split('.').pop()?.toLowerCase() || ''
  if (['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'ts'].includes(ext)) return VideoCamera
  if (['mp3', 'flac', 'wav', 'aac', 'ogg', 'm4a'].includes(ext)) return Headset
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return Picture
  if (['zip', 'rar', '7z', 'tar', 'gz', 'iso'].includes(ext)) return Box
  return Document
}

function getFileIconClass(fileName: string) {
  const ext = fileName?.split('.').pop()?.toLowerCase() || ''
  if (['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'ts'].includes(ext)) return 'icon-video'
  if (['mp3', 'flac', 'wav', 'aac', 'ogg', 'm4a'].includes(ext)) return 'icon-audio'
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return 'icon-image'
  if (['zip', 'rar', '7z', 'tar', 'gz', 'iso'].includes(ext)) return 'icon-archive'
  return 'icon-doc'
}

function getResourceTagClass(percent: number): string {
  if (percent < 50) return 'tag-normal'
  if (percent < 80) return 'tag-medium'
  return 'tag-high'
}

function getResourceColor(percent: number): string {
  if (percent < 50) return '#38bdf8'
  if (percent < 80) return '#f59e0b'
  return '#ff7597'
}

function getLoadPercentage(load: number): number {
  return Math.min((load / 10) * 100, 100)
}

function getLoadColor(load: number): string {
  if (load <= 2) return '#38bdf8'
  if (load <= 5) return '#f59e0b'
  return '#ff7597'
}

function getBotDisplayName(botKey: string): string {
  if (status.value?.bot_details) {
    const detail = status.value.bot_details.find(b => b.name === botKey)
    if (detail && detail.username) {
      return detail.username
    }
  }
  return botKey
}

function getLoadChipClass(load: number): string {
  if (load <= 2) return 'chip-green'
  if (load <= 5) return 'chip-yellow'
  return 'chip-red'
}

const botLoadFilter = ref<'all' | 'busy' | 'idle'>('all')
const botLoadSearch = ref('')
const isBotLoadsExpanded = ref(false)

interface BotLoadItem {
  key: string
  displayName: string
  load: number
}

const allBotLoadItems = computed<BotLoadItem[]>(() => {
  const loads = status.value?.loads
  if (!loads) return []
  return Object.entries(loads)
    .map(([bot, load]) => ({
      key: bot,
      displayName: getBotDisplayName(bot),
      load: Number(load) || 0,
    }))
    .sort((a, b) => {
      // 忙碌/有负载节点优先排在最前，保证管理员一眼能看到执行中的Worker
      if (b.load !== a.load) return b.load - a.load
      return a.key.localeCompare(b.key, undefined, { numeric: true })
    })
})

const totalBotLoadsCount = computed(() => allBotLoadItems.value.length)
const busyBotLoadsCount = computed(() => allBotLoadItems.value.filter(item => item.load > 0).length)
const idleBotLoadsCount = computed(() => totalBotLoadsCount.value - busyBotLoadsCount.value)

const filteredBotLoadItems = computed<BotLoadItem[]>(() => {
  let list = allBotLoadItems.value
  if (botLoadFilter.value === 'busy') {
    list = list.filter(item => item.load > 0)
  } else if (botLoadFilter.value === 'idle') {
    list = list.filter(item => item.load === 0)
  }
  const kw = botLoadSearch.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      item =>
        item.displayName.toLowerCase().includes(kw) ||
        item.key.toLowerCase().includes(kw)
    )
  }
  return list
})

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

onMounted(() => {
  void fetchBotInfo()
  fetchData()
  if (authStore.isAdmin) {
    fetchSystemResources()
    resumeTrend()
    resumeResources()
    nextTick(() => {
      initChart()
      fetchTrend()
    })
  } else {
    pauseTrend()
    pauseResources()
  }

  useResizeObserver(document.body, () => {
    chartInstance?.resize()
  })
})

onUnmounted(() => {
  pauseTrend()
  pauseResources()
  pauseData()
  chartInstance?.dispose()
})
</script>

<style scoped>
.dashboard-page {
  @apply space-y-6;
  max-width: 100%;
  overflow-x: hidden;
}

/* 头部品牌横幅 */
.tenant-onboarding-wrapper {
  margin-bottom: 16px;
}

.tenant-onboarding-card {
  padding: 20px 24px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.28);
  box-shadow: 0 8px 30px rgba(255, 117, 151, 0.08);
}

.onboarding-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 10px;
}

.onboarding-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}

.onboarding-star-badge {
  font-size: 15px;
  font-weight: 800;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 6px;
}

.onboarding-sub {
  font-size: 12.5px;
  color: #6b7280;
}

.onboarding-actions-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.onboarding-progress-badge {
  font-size: 12px;
  font-weight: 700;
  color: #ff7597;
  background: rgba(255, 117, 151, 0.12);
  border: 1px solid rgba(255, 117, 151, 0.3);
  padding: 3px 10px;
  border-radius: 999px;
}

.onboarding-btn-guide {
  border-radius: 10px;
  border-color: rgba(255, 143, 171, 0.35);
  color: #ff7597;
}

.onboarding-btn-collapse {
  border-radius: 10px;
  color: #6b7280;
}

.onboarding-progress-bar-wrap {
  margin-bottom: 18px;
}

.onboarding-steps-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.onboarding-step-box {
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(255, 143, 171, 0.2);
  border-radius: 14px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: all 0.25s ease;
}

.onboarding-step-box:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 6px 20px rgba(255, 117, 151, 0.12);
}

.onboarding-step-box.is-completed {
  border-color: rgba(16, 185, 129, 0.3);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.6) 0%, rgba(255, 255, 255, 0.8) 100%);
}

.step-box-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.step-num-pill {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: white;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #111827;
  flex: 1;
  margin-left: 8px;
}

.step-desc {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.45;
  margin: 0 0 14px 0;
  flex: 1;
}

.step-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-meta {
  font-size: 11px;
  color: #10b981;
  font-weight: 600;
}

/* 折叠卡片 */
.onboarding-collapsed-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.28);
  cursor: pointer;
  transition: all 0.2s ease;
}

.onboarding-collapsed-card:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.12);
  transform: translateY(-1px);
}

.collapsed-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.collapsed-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #111827;
}

.collapsed-progress {
  font-size: 11.5px;
  font-weight: 600;
  color: #ff7597;
  background: rgba(255, 117, 151, 0.1);
  padding: 2px 8px;
  border-radius: 999px;
}

.collapsed-right {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}

@media (max-width: 992px) {
  .onboarding-steps-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .onboarding-steps-grid {
    grid-template-columns: 1fr;
  }
  .onboarding-card-header {
    flex-direction: column;
    align-items: flex-start;
  }
}

.dashboard-header-card {
  padding: 24px 28px 20px;
  position: relative;
  overflow: hidden;
  border-radius: 20px;
}

.dashboard-header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

.dashboard-title-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dashboard-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dashboard-title {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.5px;
  margin: 0;
  line-height: 1.2;
}

.dashboard-badge {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  padding: 3px 10px;
  border-radius: 9999px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.15) 0%, rgba(56, 189, 248, 0.15) 100%);
  color: #ff7597;
  border: 1px solid rgba(255, 143, 171, 0.35);
}

.dashboard-subtitle {
  color: #64748b;
  font-size: 13.5px;
  margin: 0;
}

.dashboard-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.status-indicator-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 143, 171, 0.25);
  font-size: 12.5px;
  font-weight: 600;
  color: #374151;
}

.status-indicator-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
}

.status-dot--success {
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2), 0 0 8px #10b981;
}

.status-dot--warning {
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.header-btn:hover {
  transform: translateY(-1px);
}

.auto-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.refresh-indicator {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #cbd5e1;
  display: inline-block;
}

.refresh-indicator.is-active {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.35);
  animation: pulse 1.8s infinite;
}

/* 4 大统计卡片 */
.stats-row {
  margin-top: 4px;
}

.stat-card {
  position: relative;
  padding: 16px 18px;
  border-radius: 16px;
  cursor: pointer;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  background: rgba(255, 255, 255, 0.72) !important;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
}

.stat-card:hover {
  transform: translateY(-3px);
  background: rgba(255, 255, 255, 0.95) !important;
  box-shadow: 0 12px 28px rgba(255, 117, 151, 0.18), 0 6px 16px rgba(56, 189, 248, 0.12) !important;
}

.stat-card-inner {
  position: relative;
  z-index: 1;
}

.stat-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.stat-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.12);
  transition: transform 0.3s ease;
}

.stat-card:hover .stat-icon-wrap {
  transform: scale(1.08) rotate(4deg);
}

.stat-value-group {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 6px;
}

.stat-value {
  font-size: 26px;
  font-weight: 800;
  color: #1e293b;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  letter-spacing: -0.5px;
}

.stat-unit {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
}

.stat-desc {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: #94a3b8;
  padding-top: 8px;
  border-top: 1px dashed rgba(226, 232, 240, 0.8);
}

.stat-arrow {
  font-size: 12px;
  color: #cbd5e1;
  transition: transform 0.25s ease, color 0.25s ease;
}

.stat-card:hover .stat-arrow {
  color: #ff7597;
  transform: translateX(3px);
}

/* 图表与负载容器 */
.charts-row,
.activity-row {
  display: flex;
  align-items: stretch;
}

.chart-card,
.system-load-card,
.activity-card {
  padding: 20px 22px;
  border-radius: 18px;
  display: flex;
  flex-direction: column;
  height: 100%;
  border: 1px solid rgba(255, 143, 171, 0.22) !important;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.panel-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-icon-pill {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: #ffffff;
  flex-shrink: 0;
}

.icon-pill-primary {
  background: var(--gradient-primary);
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.35);
}

.icon-pill-sky {
  background: var(--gradient-sky);
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.35);
}

.panel-title {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 2px;
}

.panel-subtitle {
  font-size: 12px;
  color: #64748b;
  margin: 0;
}

.panel-tags {
  display: flex;
  gap: 8px;
}

.metric-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 8px;
  font-family: monospace;
  font-weight: 600;
  font-size: 12px;
  padding: 4px 10px;
}

.tag-upload {
  border-color: rgba(255, 117, 151, 0.35) !important;
  color: #ff7597 !important;
  background: rgba(255, 117, 151, 0.08) !important;
}

.tag-download {
  border-color: rgba(56, 189, 248, 0.35) !important;
  color: #0284c7 !important;
  background: rgba(56, 189, 248, 0.08) !important;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  display: inline-block;
}

.dot-upload {
  background: #ff7597;
}

.dot-download {
  background: #38bdf8;
}

.chart-body {
  flex: 1;
  min-height: 270px;
  display: flex;
  flex-direction: column;
}

.chart-container {
  width: 100%;
  flex: 1;
  min-height: 270px;
}

/* 硬件资源面板 */
.system-resources {
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex: 1;
  justify-content: center;
}

.resource-item {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.65);
  border: 1px solid rgba(226, 232, 240, 0.8);
  transition: all 0.25s ease;
}

.resource-item:hover {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(255, 143, 171, 0.35);
  transform: translateX(2px);
}

.resource-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.resource-label-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.resource-icon-badge {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: #fff;
}

.badge-cpu {
  background: linear-gradient(135deg, #ff7597, #f43f5e);
}

.badge-mem {
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
}

.badge-disk {
  background: linear-gradient(135deg, #a855f7, #6366f1);
}

.resource-name {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.resource-val-tag {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}

.tag-normal {
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
}

.tag-medium {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.tag-high {
  background: rgba(255, 117, 151, 0.15);
  color: #e11d48;
}

.resource-progress-wrap {
  margin-bottom: 4px;
}

.resource-detail-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  font-size: 11.5px;
  color: #64748b;
  margin-top: 6px;
}

.text-separator {
  color: #cbd5e1;
}

/* 最近下载表格 */
.more-link-btn {
  border-radius: 999px;
  color: #ff7597;
  border-color: rgba(255, 143, 171, 0.3);
  font-weight: 600;
}

.more-link-btn:hover {
  background: rgba(255, 117, 151, 0.08);
  border-color: #ff7597;
}

.table-wrap {
  flex: 1;
  overflow: hidden;
}

.custom-table {
  background: transparent !important;
}

.custom-table :deep(tr) {
  background: transparent !important;
}

.custom-table :deep(.el-table__row:hover > td) {
  background: linear-gradient(90deg, rgba(255, 117, 151, 0.08), rgba(56, 189, 248, 0.04)) !important;
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-type-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.icon-video {
  color: #38bdf8;
}

.icon-audio {
  color: #a855f7;
}

.icon-image {
  color: #ff7597;
}

.icon-archive {
  color: #f59e0b;
}

.icon-doc {
  color: #94a3b8;
}

.file-name-text {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.custom-status-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 600;
}

.badge-status-completed,
.badge-status-success {
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
}

.badge-status-downloading,
.badge-status-running {
  background: rgba(255, 117, 151, 0.12);
  color: #e11d48;
}

.badge-status-failed,
.badge-status-error {
  background: rgba(244, 63, 94, 0.12);
  color: #e11d48;
}

.badge-status-waiting,
.badge-status-paused {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.time-cell {
  font-size: 11.5px;
  color: #94a3b8;
  font-family: monospace;
}

/* 系统运行信息卡片 */
.system-info-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex: 1;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.info-box {
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.65);
  border: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-box.col-span-full {
  grid-column: span 2;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.info-label {
  font-size: 11.5px;
  color: #64748b;
  font-weight: 500;
}

.info-value-wrap {
  display: flex;
  align-items: center;
}

.online-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #059669;
}

.online-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
}

.info-val-highlight {
  font-size: 13.5px;
  font-weight: 700;
  color: #0284c7;
  font-family: monospace;
}

.info-val-text {
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.info-val-badge {
  font-size: 12px;
  font-weight: 700;
  color: #ff7597;
}

.version-tag {
  font-size: 12px;
  font-family: monospace;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 8px;
  background: var(--gradient-primary);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.35);
}

/* 机器人负载 */
.bot-loads {
  padding-top: 14px;
  border-top: 1px dashed rgba(226, 232, 240, 0.9);
  display: flex;
  flex-direction: column;
}

.bot-loads-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  flex-wrap: wrap;
  gap: 8px;
}

.bot-loads-title {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.no-join-indicator {
  font-size: 11px;
  font-weight: 600;
  color: #0284c7;
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 1px 8px;
  border-radius: 999px;
}

.bot-loads-count {
  font-size: 11.5px;
  color: #94a3b8;
}

.busy-pill-hint {
  color: #ff7597;
  font-weight: 600;
}

.bot-loads-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.bot-filter-pills {
  display: flex;
  align-items: center;
  gap: 4px;
}

.filter-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(248, 250, 252, 0.7);
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
  line-height: 18px;
}

.filter-pill:hover {
  color: #0f172a;
  background: #ffffff;
  border-color: #cbd5e1;
}

.filter-pill.is-active {
  background: #38bdf8;
  border-color: #38bdf8;
  color: #ffffff;
  box-shadow: 0 1px 4px rgba(56, 189, 248, 0.35);
}

.filter-pill.pill-busy.is-active {
  background: #ff7597;
  border-color: #ff7597;
  box-shadow: 0 1px 4px rgba(255, 117, 151, 0.35);
}

.bot-search-wrap {
  width: 120px;
}

.bot-search-input :deep(.el-input__wrapper) {
  border-radius: 8px;
  font-size: 11px;
  padding: 0 8px;
  height: 24px;
}

.bot-loads-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
  max-height: 196px;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 4px;
  padding-bottom: 2px;
  scrollbar-width: thin;
  scrollbar-color: rgba(203, 213, 225, 0.8) transparent;
  transition: max-height 0.25s ease-in-out;
}

.bot-loads-grid.is-expanded {
  max-height: 380px;
}

.bot-loads-grid::-webkit-scrollbar {
  width: 4px;
}

.bot-loads-grid::-webkit-scrollbar-track {
  background: rgba(241, 245, 249, 0.6);
  border-radius: 999px;
}

.bot-loads-grid::-webkit-scrollbar-thumb {
  background: rgba(203, 213, 225, 0.9);
  border-radius: 999px;
}

.bot-loads-grid::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.9);
}

.bot-load-chip {
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.8);
  transition: all 0.2s ease;
}

.bot-load-chip.is-busy {
  background: rgba(255, 241, 242, 0.7);
  border-color: rgba(255, 117, 151, 0.4);
  box-shadow: 0 1px 4px rgba(255, 117, 151, 0.1);
}

.bot-chip-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 6px;
}

.bot-chip-name {
  font-size: 11.5px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bot-chip-tag {
  font-size: 10.5px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}

.chip-green {
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
}

.chip-yellow {
  background: rgba(245, 158, 11, 0.15);
  color: #d97706;
}

.chip-red {
  background: rgba(255, 117, 151, 0.15);
  color: #e11d48;
}

.bot-chip-bar {
  width: 100%;
  height: 4px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.8);
  overflow: hidden;
}

.bot-chip-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}

.bot-loads-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 24px 0;
  color: #94a3b8;
  font-size: 12px;
}

.bot-loads-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed rgba(226, 232, 240, 0.7);
  font-size: 11px;
  color: #94a3b8;
}

.bot-footer-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.bot-expand-btn,
.bot-jump-btn {
  font-size: 11px !important;
  padding: 2px 4px !important;
  height: auto !important;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .tenant-onboarding-wrapper {
  margin-bottom: 16px;
}

.tenant-onboarding-card {
  padding: 20px 24px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.28);
  box-shadow: 0 8px 30px rgba(255, 117, 151, 0.08);
}

.onboarding-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 10px;
}

.onboarding-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}

.onboarding-star-badge {
  font-size: 15px;
  font-weight: 800;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 6px;
}

.onboarding-sub {
  font-size: 12.5px;
  color: #6b7280;
}

.onboarding-actions-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.onboarding-progress-badge {
  font-size: 12px;
  font-weight: 700;
  color: #ff7597;
  background: rgba(255, 117, 151, 0.12);
  border: 1px solid rgba(255, 117, 151, 0.3);
  padding: 3px 10px;
  border-radius: 999px;
}

.onboarding-btn-guide {
  border-radius: 10px;
  border-color: rgba(255, 143, 171, 0.35);
  color: #ff7597;
}

.onboarding-btn-collapse {
  border-radius: 10px;
  color: #6b7280;
}

.onboarding-progress-bar-wrap {
  margin-bottom: 18px;
}

.onboarding-steps-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.onboarding-step-box {
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(255, 143, 171, 0.2);
  border-radius: 14px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: all 0.25s ease;
}

.onboarding-step-box:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 6px 20px rgba(255, 117, 151, 0.12);
}

.onboarding-step-box.is-completed {
  border-color: rgba(16, 185, 129, 0.3);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.6) 0%, rgba(255, 255, 255, 0.8) 100%);
}

.step-box-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.step-num-pill {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: white;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #111827;
  flex: 1;
  margin-left: 8px;
}

.step-desc {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.45;
  margin: 0 0 14px 0;
  flex: 1;
}

.step-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-meta {
  font-size: 11px;
  color: #10b981;
  font-weight: 600;
}

/* 折叠卡片 */
.onboarding-collapsed-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.28);
  cursor: pointer;
  transition: all 0.2s ease;
}

.onboarding-collapsed-card:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(255, 117, 151, 0.45);
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.12);
  transform: translateY(-1px);
}

.collapsed-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.collapsed-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #111827;
}

.collapsed-progress {
  font-size: 11.5px;
  font-weight: 600;
  color: #ff7597;
  background: rgba(255, 117, 151, 0.1);
  padding: 2px 8px;
  border-radius: 999px;
}

.collapsed-right {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}

@media (max-width: 992px) {
  .onboarding-steps-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .onboarding-steps-grid {
    grid-template-columns: 1fr;
  }
  .onboarding-card-header {
    flex-direction: column;
    align-items: flex-start;
  }
}

.dashboard-header-card {
    padding: 16px;
  }

  .dashboard-title {
    font-size: 20px;
  }

  .dashboard-header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .stats-row :deep(.el-col) {
    margin-bottom: 10px;
  }

  .chart-card,
  .system-load-card,
  .activity-card {
    padding: 16px;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .info-box.col-span-full {
    grid-column: span 1;
  }
}
</style>
