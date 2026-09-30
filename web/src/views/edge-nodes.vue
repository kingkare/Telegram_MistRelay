<template>
  <div class="edge-nodes-page animate-fade-in">
    <!-- 顶部品牌横幅与控制区 (统一 Sakura Glass 风格) -->
    <div class="edge-header-card glass-card">
      <div class="edge-header-main">
        <div class="edge-title-group">
          <div class="edge-title-row">
            <h2 class="edge-title text-gradient-sakura">
              {{ authStore.isAdmin ? '全集群边缘推流分流中心' : '我的专属边缘加速节点' }}
            </h2>
            <span class="edge-badge">
              {{ authStore.isAdmin ? 'Cluster Edge Network' : 'Personal Edge CDN' }}
            </span>
          </div>
          <p class="edge-subtitle">
            {{
              authStore.isAdmin
                ? '集中监控并调度全站租户 VPS 边缘推流节点，实现大码率音视频播放直连 Telegram DC 拉流，彻底卸载主控出网流量。'
                : '挂载您的 VPS 为您的 TG 网盘与专属频道提供 302 原生直连分流加速，客户端直接与 Telegram DC 通信，享受百兆/千兆无损播放。'
            }}
          </p>
        </div>

        <div class="edge-header-actions">
          <!-- 租户端专属加速徽章 -->
          <div v-if="!authStore.isAdmin" class="tenant-status-pill">
            <span class="status-dot" :class="summary.online_nodes > 0 ? 'dot-online' : 'dot-idle'"></span>
            <span class="pill-text">
              {{ summary.online_nodes > 0 ? '专属加速已就绪生效' : '暂无在线加速节点' }}
            </span>
            <el-tag size="small" type="info" effect="plain" class="channel-pill" v-if="authStore.user?.bin_channel_username">
              @{{ authStore.user.bin_channel_username }}
            </el-tag>
          </div>

          <!-- 管理员：全网租户分流总榜 -->
          <el-button
            v-if="authStore.isAdmin"
            class="header-btn tenant-summary-btn"
            @click="openClusterTenantsDialog"
            title="查看全集群所有租户在边缘节点上的分流流量总榜与实时统计"
          >
            <span class="mr-1.5">📊</span> 全网租户分流总榜
            <span v-if="clusterTenantsList.length > 0" class="tenant-count-badge">
              {{ clusterTenantsList.length }}
            </span>
          </el-button>

          <!-- 管理员：一键全网测速按钮 -->
          <el-button
            v-if="authStore.isAdmin"
            class="header-btn batch-bench-btn"
            :icon="Compass"
            :loading="batchBenchmarking"
            @click="handleBatchBenchmark"
          >
            一键全网测速
          </el-button>

          <!-- 部署入口按钮 -->
          <el-button
            type="primary"
            class="header-btn btn-ssh-deploy"
            :icon="Monitor"
            @click="openCreateSshDialog"
          >
            SSH 自动纳管 VPS
          </el-button>

          <el-button
            class="header-btn btn-script-deploy"
            :icon="DocumentCopy"
            @click="openTokenDialog"
          >
            免密一键脚本自装
          </el-button>

          <!-- 实时推流连接状态徽标 -->
          <div class="realtime-live-badge" :class="{ 'is-live': wsConnected }" title="WebSocket 实时状态推流已就绪">
            <span class="live-pulse-dot"></span>
            <span class="live-text">{{ wsConnected ? '实时推流中' : '长连接连线中' }}</span>
          </div>

          <el-button
            class="header-btn btn-refresh"
            :icon="RefreshRight"
            :loading="manualRefreshing"
            @click="handleManualRefresh"
          >
            刷新
          </el-button>
        </div>
      </div>

      <!-- 4 大流光指标卡片 (统一 dashboard 样式) -->
      <el-row :gutter="14" class="stats-row">
        <el-col :xs="12" :sm="6" v-for="card in kpiCards" :key="card.key">
          <div class="stat-card glass-card" :class="`stat-card--${card.key}`">
            <div class="stat-card-glow"></div>
            <div class="stat-card-inner">
              <div class="stat-card-top">
                <span class="stat-label">{{ card.label }}</span>
                <div class="stat-icon-wrap" :style="{ background: card.color }">
                  <el-icon :size="18"><component :is="card.icon" /></el-icon>
                </div>
              </div>
              <div class="stat-value-group">
                <span class="stat-value">{{ card.value }}</span>
                <span class="stat-unit" v-if="card.unit">{{ card.unit }}</span>
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

    <!-- 302 智能加速链路原理提示条 (轻量化折叠设计) -->
    <div class="acceleration-status-strip glass-card">
      <div class="strip-left">
        <span class="strip-sparkle">⚡</span>
        <span class="strip-title">302 边缘直连架构：</span>
        <div class="strip-flow-wrap">
          <span class="flow-step">客户端请求</span>
          <span class="flow-arrow">➔</span>
          <span class="flow-step">主控毫秒验签 302 重定向</span>
          <span class="flow-arrow">➔</span>
          <span class="flow-step highlight-node">租户 VPS 直连 Telegram DC</span>
          <span class="flow-arrow">➔</span>
          <span class="flow-step">极速推流客户端</span>
        </div>
        <span class="strip-tag">主控出网流量 ≈ 0</span>
      </div>
      <button class="strip-toggle-btn" @click="showTopoHelp = !showTopoHelp">
        {{ showTopoHelp ? '收起说明 ▴' : '原理说明 ▾' }}
      </button>
    </div>

    <!-- 展开后的技术架构细节 -->
    <div v-if="showTopoHelp" class="topo-help-drawer glass-card animate-fade-in">
      <div class="topo-help-grid">
        <div class="topo-item">
          <div class="topo-num">1</div>
          <div class="topo-content">
            <div class="topo-heading">客户端播放与下载发起</div>
            <div class="topo-body">客户端访问 TG 网盘或直链地址时，请求首先抵达 MistRelay 主控服务器进行轻量级 Token 权限核验。</div>
          </div>
        </div>
        <div class="topo-item">
          <div class="topo-num">2</div>
          <div class="topo-content">
            <div class="topo-heading">智能签发 302 重定向 Ticket</div>
            <div class="topo-body">主控识别媒体所有权并寻找租户名下在线的边缘 VPS，为其签发带过期时间的 HMAC-SHA256 授权凭据，瞬间 302 跳转。</div>
          </div>
        </div>
        <div class="topo-item highlight">
          <div class="topo-num">3</div>
          <div class="topo-content">
            <div class="topo-heading">边缘 VPS 直连 Telegram DC</div>
            <div class="topo-body">租户 VPS (Edge Worker) 接收凭证后直连所属 Telegram DC（如 DC5 新加坡）拉取 512KB 分片，主控完全不参与数据转发。</div>
          </div>
        </div>
        <div class="topo-item">
          <div class="topo-num">4</div>
          <div class="topo-content">
            <div class="topo-heading">客户端满速原画极清推流</div>
            <div class="topo-body">支持标准 HTTP 206 Range 断点续传，充分利用 VPS 物理带宽完成秒开起播，彻底解决主控出网卡顿。</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 筛选控制与视图模式切换栏 -->
    <div class="control-filter-bar glass-card">
      <div class="filter-left">
        <!-- 标签式状态筛选器 (管理端或节点数 > 2 时展示) -->
        <div v-if="authStore.isAdmin || nodes.length > 2" class="filter-tabs">
          <button
            v-for="tab in statusTabs"
            :key="tab.value"
            :class="['filter-tab', { active: statusFilter === tab.value }]"
            @click="statusFilter = tab.value"
          >
            <span>{{ tab.label }}</span>
            <span class="tab-count">{{ tab.count }}</span>
          </button>
        </div>
        <div v-else class="tenant-node-count-badge">
          <span>专属节点列表 ({{ filteredNodes.length }})</span>
        </div>
      </div>

      <div class="filter-right">
        <!-- 快速搜索 -->
        <el-input
          v-model="searchQuery"
          placeholder="搜索节点名称、IP、域名或租户..."
          clearable
          :prefix-icon="Search"
          class="edge-search-input"
        />

        <!-- 卡片 / 表格视图切换 -->
        <div class="view-mode-toggle">
          <el-radio-group v-model="viewMode" size="default" @change="(val: any) => setViewMode(val)">
            <el-radio-button value="grid">
              <el-icon class="mr-1"><Grid /></el-icon> 卡片
            </el-radio-button>
            <el-radio-button value="table">
              <el-icon class="mr-1"><Tickets /></el-icon> 表格
            </el-radio-button>
          </el-radio-group>
        </div>
      </div>
    </div>

    <!-- 节点展示主区域 -->
    <div v-loading="loading" class="nodes-main-container">
      <!-- 空状态 -->
      <div v-if="filteredNodes.length === 0" class="empty-state glass-card">
        <div class="empty-icon-wrap">🚀</div>
        <div class="empty-title">暂无边缘推流加速节点</div>
        <div class="empty-desc">
          挂载您的 VPS（支持任意具有公网 IP 的 Linux 服务器）后，直链播放将自动由该 VPS 接管并直连 Telegram 数据中心，享受极速推流并释放主控带宽。
        </div>
        <div class="empty-btns">
          <el-button type="primary" class="header-btn btn-ssh-deploy" :icon="Monitor" @click="openCreateSshDialog">
            立即通过 SSH 纳管 VPS
          </el-button>
          <el-button class="header-btn btn-script-deploy" :icon="DocumentCopy" @click="openTokenDialog">
            生成免密一键脚本安装
          </el-button>
        </div>
      </div>

      <!-- 视图 1：自适应宽体卡片矩阵 (移动端强制以卡片流展示) -->
      <div v-else-if="viewMode === 'grid' || true" class="nodes-grid" :class="{ 'md:hidden': viewMode === 'table' }">
        <div
          v-for="node in filteredNodes"
          :key="node.id"
          :class="['node-card', 'glass-card', `status-${node.status}`]"
        >
          <!-- 卡片头部：ID、名称、租户标识与运行状态 -->
          <div class="node-card-header">
            <div class="node-title-group">
              <span class="node-id-badge">#{{ node.id }}</span>
              <span class="node-name" :title="node.node_name">{{ node.node_name }}</span>
              <el-tag
                v-if="authStore.isAdmin && node.tenant_username"
                size="small"
                type="info"
                effect="plain"
                class="tenant-tag"
              >
                👤 租户: {{ node.tenant_username }}
              </el-tag>
              <span v-if="node.benchmark_data?.diagnostics?.system?.os" class="os-mini-tag">
                {{ node.benchmark_data.diagnostics.system.os.split(' ')[0] }}
                {{ node.benchmark_data.diagnostics.system.cpu_cores ? ' · ' + node.benchmark_data.diagnostics.system.cpu_cores + '核' : '' }}
              </span>
            </div>

            <div class="node-status-pill" :class="node.status">
              <span class="status-dot"></span>
              <span>{{ formatStatusText(node.status) }}</span>
            </div>
          </div>

          <!-- 卡片主体：双栏核心信息（左网络与SSH安全 / 右测速胶囊与硬件指标） -->
          <div class="node-card-body-row">
            <!-- 左栏：网络推流地址与 SSH -->
            <div class="node-net-col">
              <div class="net-row">
                <span class="net-label">推流入口:</span>
                <div class="net-val-box">
                  <code class="ep-value">{{ formatNodeEndpoint(node) }}</code>
                  <el-button
                    link
                    size="small"
                    class="btn-copy-ep"
                    :icon="DocumentCopy"
                    @click="copyText(formatNodeEndpoint(node), '推流入口地址已复制')"
                    title="复制推流入口"
                  />
                  <el-tag v-if="node.use_ssl" size="small" type="success" effect="light" class="ssl-tag">SSL</el-tag>
                </div>
              </div>

              <div class="net-row">
                <span class="net-label">SSH 纳管:</span>
                <div class="ssh-val-box">
                  <span class="ep-sub">{{ node.ssh_user || 'root' }}@{{ node.ssh_host || node.ip || '未配置' }}:{{ node.ssh_port || 22 }}</span>
                  <span v-if="node.has_ssh_password" class="pwd-saved-badge">
                    🔑 已加密存密
                    <button class="btn-inline-wipe" @click="handleClearPassword(node)" title="从主控数据库擦除保存的 SSH 密码">
                      擦除
                    </button>
                  </span>
                  <span v-else class="pwd-wiped-badge">🔒 零密码留存</span>
                </div>
              </div>

              <div class="net-row bot-row">
                <span class="net-label">分配 Bot:</span>
                <div class="bot-val-box">
                  <div class="bot-line-main">
                    <span v-if="node.assigned_bot_username" class="bot-name" :title="'@' + node.assigned_bot_username">
                      🤖 @{{ node.assigned_bot_username }}
                    </span>
                    <span v-else class="bot-name empty-sub">智能调度</span>
                    <button
                      class="btn-inline-reassign"
                      title="手动为节点指定 Bot 或切换调度模式"
                      @click.stop="openAssignBotDialog(node)"
                    >
                      配置
                    </button>
                  </div>
                  <div class="bot-line-tags">
                    <el-tag
                      v-if="node.target_dc_id"
                      size="small"
                      :type="isNodeDcMatched(node) ? 'success' : 'warning'"
                      effect="plain"
                      class="dc-tag-pill"
                    >
                      {{ isNodeDcMatched(node) ? '⚡ DC' + node.target_dc_id + ' 原生直连' : '⚠️ DC' + node.target_dc_id + ' 跨区' }}
                    </el-tag>
                    <el-tag
                      size="small"
                      :type="node.assigned_bot_token ? 'primary' : 'info'"
                      effect="light"
                      class="dc-tag-pill"
                    >
                      {{ node.assigned_bot_token ? '手动指定' : '智能自动' }}
                    </el-tag>
                  </div>
                </div>
              </div>
            </div>

            <!-- 右栏：测速与体检指标胶囊（点击直达深度测速工作台） -->
            <div class="node-bench-col" @click="openBenchmarkModal(node)" title="点击打开全能测速与体检工作台">
              <div
                v-if="node.benchmark_data?.bandwidth?.effective_bw_mb_s || node.benchmark_data?.bandwidth?.down_speed_mb_s"
                class="bench-capsule bw-capsule"
                style="background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.3);"
              >
                <span class="capsule-icon">🌐</span>
                <span class="capsule-text">
                  <b v-if="node.benchmark_data.bandwidth.effective_bw_mb_s">
                    宽带 {{ node.benchmark_data.bandwidth.effective_bw_mb_s }} MB/s
                  </b>
                  <b v-else>
                    宽带 {{ node.benchmark_data.bandwidth.down_speed_mb_s }} MB/s
                  </b>
                  <span class="capsule-sub" v-if="node.benchmark_data.bandwidth.up_speed_mb_s">
                    (下{{ node.benchmark_data.bandwidth.down_speed_mb_s }}/上{{ node.benchmark_data.bandwidth.up_speed_mb_s }})
                  </span>
                  <span class="capsule-sub" v-else>
                    ({{ node.benchmark_data.bandwidth.matched_bots || node.target_bot_count || 4 }}Bot阵列)
                  </span>
                </span>
              </div>
              <div
                v-if="node.benchmark_data?.fastest_dc?.name && node.benchmark_data?.fastest_dc?.avg_rtt_ms !== undefined"
                class="bench-capsule dc-capsule"
              >
                <span class="capsule-icon">⚡</span>
                <span class="capsule-text">
                  <b>{{ (node.benchmark_data.fastest_dc.name || '').split(' ')[0] }}</b>
                  {{ node.benchmark_data.fastest_dc.avg_rtt_ms }}ms
                  <span class="capsule-sub">({{ node.benchmark_data.fastest_dc.rating_label || '' }})</span>
                </span>
              </div>
              <div v-else class="bench-capsule empty-capsule">
                <span class="capsule-icon">⚡</span>
                <span class="capsule-text">5大 DC 未测</span>
              </div>

              <div
                v-if="node.benchmark_data?.speed?.relay_speed_mb_s || node.benchmark_data?.speed?.peak_speed_mb_s"
                class="bench-capsule speed-capsule"
              >
                <span class="capsule-icon">🚀</span>
                <span class="capsule-text">
                  <b>体感 {{ node.benchmark_data.speed.relay_speed_mb_s || node.benchmark_data.speed.peak_speed_mb_s }} MB/s</b>
                  <span class="capsule-sub" v-if="node.benchmark_data.speed.tg_pull_speed_mb_s && node.benchmark_data.speed.tg_pull_speed_mb_s !== (node.benchmark_data.speed.relay_speed_mb_s || node.benchmark_data.speed.peak_speed_mb_s)">
                    (拉流 {{ node.benchmark_data.speed.tg_pull_speed_mb_s }} · {{ node.benchmark_data.speed.usable_bots_count || 4 }}Bot)
                  </span>
                  <span class="capsule-sub" v-else>
                    ({{ node.benchmark_data.speed.usable_bots_count || node.benchmark_data.bandwidth?.matched_bots || 4 }}Bot · {{ node.benchmark_data.speed.speed_mbps }} Mbps)
                  </span>
                </span>
              </div>
              <div v-else class="bench-capsule empty-capsule">
                <span class="capsule-icon">🚀</span>
                <span class="capsule-text">拉流未测速</span>
              </div>

              <div
                v-if="node.benchmark_data?.health_score !== undefined"
                :class="['bench-capsule', 'health-capsule', getHealthGradeClass(node.benchmark_data?.health_grade)]"
              >
                <span class="capsule-icon">🛡️</span>
                <span class="capsule-text">
                  <b>{{ node.benchmark_data.health_score }}分</b>
                  <span class="capsule-sub">({{ node.benchmark_data.health_label || '健康' }} {{ node.benchmark_data.health_grade }})</span>
                </span>
              </div>
              <div v-else class="bench-capsule empty-capsule">
                <span class="capsule-icon">🛡️</span>
                <span class="capsule-text">待系统体检</span>
              </div>
            </div>
          </div>

          <!-- 硬件实时负载与流播状态 -->
          <div class="node-metrics-grid">
            <div class="metric-item">
              <div class="metric-top">
                <span class="metric-name">CPU 负荷</span>
                <span class="metric-val">{{ (node.metrics?.cpu || 0).toFixed(1) }}%</span>
              </div>
              <el-progress
                :percentage="Math.min(100, Math.round(node.metrics?.cpu || 0))"
                :stroke-width="6"
                :show-text="false"
                :color="getProgressColor(node.metrics?.cpu || 0)"
              />
            </div>

            <div class="metric-item">
              <div class="metric-top">
                <span class="metric-name">内存占用</span>
                <span class="metric-val">{{ (node.metrics?.mem || 0).toFixed(1) }}%</span>
              </div>
              <el-progress
                :percentage="Math.min(100, Math.round(node.metrics?.mem || 0))"
                :stroke-width="6"
                :show-text="false"
                :color="getProgressColor(node.metrics?.mem || 0)"
              />
            </div>

            <div class="metric-stat-box" :class="{ 'stat-active': (node.metrics?.active_streams || 0) > 0 }">
              <div class="m-stat-label">活跃推流</div>
              <div class="m-stat-num">{{ node.metrics?.active_streams || 0 }} <small>路</small></div>
            </div>

            <div class="metric-stat-box" :class="{ 'stat-active': (node.metrics?.net_tx || 0) > 0 }">
              <div class="m-stat-label">实时出网</div>
              <div class="m-stat-num">{{ formatBytes(node.metrics?.net_tx || 0) }}/s</div>
            </div>
          </div>

          <!-- 租户分流实时监控条 (动态呼吸灯胶囊 + 流量明细入口) -->
          <div class="node-tenant-monitor-strip">
            <div class="tenant-strip-left">
              <span class="tenant-strip-tag">
                <span class="tenant-tag-icon">⚡</span>分流监控
              </span>

              <!-- 正在拉流的租户胶囊 -->
              <div v-if="getNodeActiveTenants(node).length > 0" class="tenant-capsules-group">
                <div
                  v-for="t in getNodeActiveTenants(node)"
                  :key="t.tenant_id"
                  class="tenant-streaming-capsule"
                  @click="openTenantMetricsDialog(node)"
                  :title="`租户 ${t.username} 正在拉流\n实时速率: ${formatBytes(t.net_tx)}/s\n并发路数: ${t.active_streams} 路\n累计用量: ${formatBytes(t.total_bytes)}\n点击查看完整排行`"
                >
                  <span class="streaming-dot"></span>
                  <span class="t-name">@{{ t.username.replace(/^@/, '') }}</span>
                  <span class="t-speed">{{ formatBytes(t.net_tx) }}/s</span>
                  <span class="t-streams" v-if="t.active_streams > 1">{{ t.active_streams }}路</span>
                </div>
              </div>

              <!-- 空闲胶囊 -->
              <div
                v-else
                class="tenant-idle-capsule"
                @click="openTenantMetricsDialog(node)"
                :title="`当前推流空闲 · 点击查看该节点历史 ${(node.metrics?.tenants || []).length} 位租户用量`"
              >
                <span class="idle-dot"></span>
                <span>当前推流空闲</span>
                <span v-if="(node.metrics?.tenants || []).length > 0" class="idle-history-hint">
                  (历史 {{ (node.metrics?.tenants || []).length }} 租户)
                </span>
              </div>
            </div>

            <!-- 右侧明细直达入口 -->
            <div class="tenant-strip-right">
              <el-button
                class="tenant-ranking-btn"
                size="small"
                text
                @click="openTenantMetricsDialog(node)"
              >
                <span class="rank-icon">📊</span>
                <span>租户用量明细</span>
                <span v-if="(node.metrics?.tenants || []).length > 0" class="tenant-badge">
                  {{ (node.metrics?.tenants || []).length }}
                </span>
              </el-button>
            </div>
          </div>

          <!-- 累计流量与最后心跳 -->
          <div class="node-meta-strip">
            <span>累计分流流量: <b>{{ formatBytes(node.metrics?.total_bytes_served || 0) }}</b></span>
            <span>最后上报心跳: {{ node.last_seen_at ? formatDate(node.last_seen_at) : '尚未上报' }}</span>
          </div>

          <!-- 底部控制与操作栏 (彻底解决换行与挤压) -->
          <div class="node-card-footer">
            <div class="shared-pool-toggle" title="开启后，当其他租户无节点时可借用此节点闲置带宽">
              <el-switch
                v-model="node.allow_shared_pool"
                size="small"
                @change="(val: any) => handleToggleSharedPool(node, Boolean(val))"
              />
              <span class="shared-label">
                {{ node.allow_shared_pool ? '公共共享' : '专属自用' }}
              </span>
            </div>

            <div class="node-btn-group">
              <el-button
                type="primary"
                class="btn-node-bench"
                :icon="Odometer"
                @click="openBenchmarkModal(node)"
              >
                综合测速
              </el-button>
              <el-button
                class="btn-node-act"
                :loading="testingNodeId === node.id"
                @click="handleTestNode(node)"
              >
                探测
              </el-button>
              <el-button
                class="btn-node-act"
                @click="openLogModal(node)"
              >
                日志
              </el-button>
              <el-dropdown trigger="click" @command="(cmd: string) => handleDropdownCommand(cmd, node)">
                <el-button class="btn-node-more">
                  更多 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">编辑配置</el-dropdown-item>
                    <el-dropdown-item command="assign_bot">分配 / 切换 Bot</el-dropdown-item>
                    <el-dropdown-item command="reassign_bot">重新分配最优 Bot</el-dropdown-item>
                    <el-dropdown-item command="redeploy">重新执行部署</el-dropdown-item>
                    <el-dropdown-item v-if="node.has_ssh_password" command="wipe_pwd">擦除 SSH 密码</el-dropdown-item>
                    <el-dropdown-item command="delete" divided style="color: #f43f5e;">解绑移除节点</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>
      </div>

      <!-- 视图 2：高密度紧凑表格视图 (仅桌面端显示) -->
      <div v-if="filteredNodes.length > 0 && viewMode === 'table'" class="table-container glass-card hidden md:block">
        <el-table
          :data="filteredNodes"
          row-key="id"
          style="width: 100%"
          class="edge-nodes-table"
          empty-text="暂无匹配节点"
        >
          <el-table-column label="节点名称 & 归属" min-width="190">
            <template #default="{ row }">
              <div class="table-node-name-cell">
                <div class="t-name-row">
                  <span class="node-id-badge">#{{ row.id }}</span>
                  <span class="t-node-title" :title="row.node_name">{{ row.node_name }}</span>
                </div>
                <div class="t-sub-info">
                  <span class="t-ip-sub">{{ row.ip }}:{{ row.port }}</span>
                  <el-tag v-if="authStore.isAdmin && row.tenant_username" size="small" type="info" effect="plain" class="ml-1">
                    👤 {{ row.tenant_username }}
                  </el-tag>
                </div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="推流入口" min-width="210">
            <template #default="{ row }">
              <div class="table-ep-cell">
                <code class="ep-value">{{ formatNodeEndpoint(row) }}</code>
                <el-button
                  link
                  size="small"
                  :icon="DocumentCopy"
                  @click="copyText(formatNodeEndpoint(row), '推流地址已复制')"
                />
              </div>
            </template>
          </el-table-column>

          <el-table-column label="运行状态" width="130" align="center">
            <template #default="{ row }">
              <div class="node-status-pill" :class="row.status">
                <span class="status-dot"></span>
                <span>{{ formatStatusText(row.status) }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="分配 Bot & 最优 DC" min-width="190">
            <template #default="{ row }">
              <div class="table-bot-cell">
                <div v-if="row.assigned_bot_username" class="table-bot-name">
                  🤖 @{{ row.assigned_bot_username }}
                  <el-tag size="small" :type="isNodeDcMatched(row) ? 'success' : 'warning'" effect="plain" class="table-dc-tag">
                    DC{{ row.target_dc_id || 5 }}
                  </el-tag>
                  <el-tag size="small" :type="row.assigned_bot_token ? 'primary' : 'info'" effect="light" class="table-dc-tag">
                    {{ row.assigned_bot_token ? '手动' : '自动' }}
                  </el-tag>
                </div>
                <div class="table-bot-actions-row">
                  <div v-if="row.benchmark_data?.fastest_dc?.name && row.benchmark_data?.fastest_dc?.avg_rtt_ms !== undefined" class="t-bench-pill dc-pill" @click="openBenchmarkModal(row)" style="cursor: pointer;">
                    ⚡ {{ (row.benchmark_data.fastest_dc.name || '').split(' ')[0] }}: {{ row.benchmark_data.fastest_dc.avg_rtt_ms }}ms
                  </div>
                  <el-button link type="primary" size="small" @click.stop="openAssignBotDialog(row)" class="btn-table-assign">
                    分配Bot
                  </el-button>
                </div>
                <span v-if="!row.assigned_bot_username && !row.benchmark_data?.fastest_dc?.name" class="text-slate-400 text-xs">待探测</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="中继体感流速" width="155" align="center">
            <template #default="{ row }">
              <div v-if="row.benchmark_data?.speed?.relay_speed_mb_s || row.benchmark_data?.speed?.peak_speed_mb_s">
                <div class="font-bold text-emerald-600">
                  🚀 {{ row.benchmark_data.speed.relay_speed_mb_s || row.benchmark_data.speed.peak_speed_mb_s }} MB/s
                </div>
                <div class="text-[10px] text-slate-400">
                  有效 {{ row.benchmark_data.bandwidth?.effective_bw_mb_s || row.benchmark_data.bandwidth?.down_speed_mb_s || "--" }} MB/s · {{ row.benchmark_data.speed.usable_bots_count || 4 }}Bot
                </div>
              </div>
              <span v-else class="text-slate-400 text-xs">--</span>
            </template>
          </el-table-column>

          <el-table-column label="健康评分" width="130" align="center">
            <template #default="{ row }">
              <el-tag
                v-if="row.benchmark_data?.health_score !== undefined"
                size="small"
                :type="row.benchmark_data.health_score >= 80 ? 'success' : (row.benchmark_data.health_score >= 60 ? 'warning' : 'danger')"
                effect="light"
              >
                🛡️ {{ row.benchmark_data.health_score }}分 ({{ row.benchmark_data.health_grade || 'A+' }})
              </el-tag>
              <span v-else class="text-slate-400 text-xs">--</span>
            </template>
          </el-table-column>

          <el-table-column label="CPU / 内存" width="130" align="center">
            <template #default="{ row }">
              <span class="text-xs text-slate-600 font-mono">
                {{ (row.metrics?.cpu || 0).toFixed(0) }}% / {{ (row.metrics?.mem || 0).toFixed(0) }}%
              </span>
            </template>
          </el-table-column>

          <el-table-column label="活跃/速率" width="140" align="center">
            <template #default="{ row }">
              <div class="text-xs" :class="{ 'text-sky-600 font-semibold': (row.metrics?.active_streams || 0) > 0 }">
                <b>{{ row.metrics?.active_streams || 0 }}</b> 路 ·
                <span :class="(row.metrics?.net_tx || 0) > 0 ? 'text-sky-600 font-medium' : 'text-slate-500'">{{ formatBytes(row.metrics?.net_tx || 0) }}/s</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="分流租户" min-width="180" align="center">
            <template #default="{ row }">
              <div class="table-tenant-cell">
                <template v-if="getNodeActiveTenants(row).length > 0">
                  <div
                    class="table-tenant-pill active-pill cursor-pointer"
                    @click="openTenantMetricsDialog(row)"
                    :title="`正在拉流: ${getNodeActiveTenants(row).map(t => `${t.username} (${formatBytes(t.net_tx)}/s)`).join(' · ')}`"
                  >
                    <span class="streaming-dot-sm"></span>
                    <span class="truncate max-w-[85px]">@{{ getNodeActiveTenants(row)[0].username.replace(/^@/, '') }}</span>
                    <span class="pill-extra" v-if="getNodeActiveTenants(row).length > 1">+{{ getNodeActiveTenants(row).length - 1 }}</span>
                  </div>
                </template>
                <template v-else-if="(row.metrics?.tenants || []).length > 0">
                  <span
                    class="table-tenant-pill idle-pill cursor-pointer"
                    @click="openTenantMetricsDialog(row)"
                    :title="`空闲中 · 历史共有 ${(row.metrics?.tenants || []).length} 位租户拉流`"
                  >
                    <span class="idle-dot-sm"></span>
                    <span>空闲 ({{ (row.metrics?.tenants || []).length }}租户)</span>
                  </span>
                </template>
                <template v-else>
                  <span class="text-xs text-slate-400">暂无记录</span>
                </template>

                <el-button
                  type="primary"
                  link
                  size="small"
                  class="table-rank-btn"
                  @click="openTenantMetricsDialog(row)"
                  title="查看该节点各租户分流用量明细"
                >
                  📊
                </el-button>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="共享策略" width="120" align="center">
            <template #default="{ row }">
              <el-switch
                v-model="row.allow_shared_pool"
                size="small"
                @change="(val: any) => handleToggleSharedPool(row, Boolean(val))"
                :title="row.allow_shared_pool ? '公共共享池' : '专属自用'"
              />
            </template>
          </el-table-column>

          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <div class="table-actions-cell">
                <el-button size="small" type="primary" plain :icon="Odometer" @click="openBenchmarkModal(row)">
                  测速
                </el-button>
                <el-button size="small" :loading="testingNodeId === row.id" @click="handleTestNode(row)">
                  探测
                </el-button>
                <el-dropdown trigger="click" @command="(cmd: string) => handleDropdownCommand(cmd, row)">
                  <el-button size="small">
                    更多 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="log">部署日志</el-dropdown-item>
                      <el-dropdown-item command="assign_bot">分配 / 切换 Bot</el-dropdown-item>
                      <el-dropdown-item command="edit">编辑配置</el-dropdown-item>
                      <el-dropdown-item command="reassign_bot">重新分配最优 Bot</el-dropdown-item>
                      <el-dropdown-item command="redeploy">重新部署</el-dropdown-item>
                      <el-dropdown-item v-if="row.has_ssh_password" command="wipe_pwd">擦除密码</el-dropdown-item>
                      <el-dropdown-item command="delete" divided style="color: #f43f5e;">解绑移除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>


    <!-- 弹窗 1：SSH 自动化纳管 / 编辑配置 -->
    <el-dialog
      v-model="sshDialogVisible"
      :title="isEditMode ? `编辑边缘节点 #${sshForm.id}` : 'SSH 自动纳管 VPS 边缘节点'"
      width="660px"
      :close-on-click-modal="false"
      append-to-body
      class="edge-ssh-dialog"
    >
      <div class="dialog-notice">
        <span>💡 输入您 VPS 的 <code>root</code> 账号密码，主控将通过加密 SSH 隧道自动完成环境配置、防火墙放行与边缘推流服务守护进程挂载。</span>
      </div>

      <el-form :model="sshForm" label-width="115px" class="edge-form">
        <el-form-item label="节点名称" required>
          <el-input
            v-model="sshForm.node_name"
            placeholder="例如：香港 CN2 边缘节点 #1 / 新加坡大带宽 VPS"
          />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="VPS 公网 IP" required>
              <el-input
                v-model="sshForm.ip"
                placeholder="例如：203.0.113.88"
              />
              <div v-if="getAutoEdgeDomain(sshForm.ip)" class="auto-domain-hint">
                <el-icon><Link /></el-icon>
                <span>自动绑定域名: <code>{{ getAutoEdgeDomain(sshForm.ip) }}</code> (免手动配置 DNS 解析)</span>
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="推流端口" label-width="85px" required>
              <el-input-number
                v-model="sshForm.port"
                :min="1024"
                :max="65535"
                controls-position="right"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="SSH 用户名" required>
              <el-input v-model="sshForm.ssh_user" placeholder="root" />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="SSH 端口" label-width="85px" required>
              <el-input-number
                v-model="sshForm.ssh_port"
                :min="1"
                :max="65535"
                controls-position="right"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item :label="isEditMode ? '更新 SSH 密码' : 'SSH root 密码'" :required="!isEditMode">
          <el-input
            v-model="sshForm.ssh_password"
            type="password"
            show-password
            :placeholder="isEditMode ? '留空表示沿用已保存密码或密钥' : '请输入 VPS 的 root 密码'"
          />
        </el-form-item>

        <el-form-item label="自定义域名">
          <el-input
            v-model="sshForm.domain"
            :placeholder="getAutoEdgeDomain(sshForm.ip) ? '默认自动绑定 ' + getAutoEdgeDomain(sshForm.ip) + '，留空即可' : '默认自动绑定 edge.<IP>.sslip.io，留空即可'"
          />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="启用 HTTPS/SSL">
              <el-switch v-model="sshForm.use_ssl" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="公共池共享">
              <el-switch v-model="sshForm.allow_shared_pool" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="数据中心 (DC)">
              <el-select v-model="sshForm.target_dc_id" placeholder="自动推荐 (依据测速/位置)" clearable style="width: 100%;">
                <el-option :value="null" label="🌐 自动推荐 (依据测速/位置)" />
                <el-option :value="1" label="DC1 美东/美西 (Miami/北美) · 53个Bot" />
                <el-option :value="2" label="DC2 欧洲 (Amsterdam)" />
                <el-option :value="3" label="DC3 美东 (Miami)" />
                <el-option :value="4" label="DC4 欧洲 (Holland)" />
                <el-option :value="5" label="DC5 亚太 (Singapore/新加坡) · 27个Bot" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="Bot阵列加速" label-width="95px">
              <el-switch v-model="sshForm.allow_bot_pool" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item v-if="!isEditMode" label="安全零信任">
          <div class="form-switch-line">
            <el-switch v-model="sshForm.clear_password_on_success" />
            <span class="switch-desc">部署成功后自动从主控数据库抹除 SSH 密码 (推荐)</span>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="sshDialogVisible = false">取消</el-button>
          <el-button
            v-if="isEditMode"
            type="primary"
            :loading="submitting"
            @click="handleSaveNode"
          >
            保存配置
          </el-button>
          <el-button
            type="primary"
            class="btn-ssh-deploy"
            :loading="submitting"
            @click="handleSaveAndDeploy"
          >
            {{ isEditMode ? '保存并重新执行部署' : '立即启动 SSH 自动部署' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2：免密一键脚本自装 -->
    <el-dialog
      v-model="tokenDialogVisible"
      title="免密一键脚本接入 VPS 边缘节点"
      width="680px"
      append-to-body
      class="edge-token-dialog"
      @closed="stopTokenPolling"
    >
      <div class="dialog-notice">
        <span>🔒 无需向面板提供 root 密码。生成一次性安全授权凭据后，直接在您的 VPS 终端中粘贴执行下方命令即可全自动接入。</span>
      </div>

      <el-form :model="tokenForm" label-width="115px" class="edge-form">
        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="节点名称" required>
              <el-input v-model="tokenForm.node_name" placeholder="例如：东京软银大带宽 VPS" />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="推流端口" label-width="85px" required>
              <el-input-number
                v-model="tokenForm.port"
                :min="1024"
                :max="65535"
                controls-position="right"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="自定义域名">
              <el-input v-model="tokenForm.domain" placeholder="默认自动绑定 edge.<IP>.sslip.io，留空即可" />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="公共池共享" label-width="88px">
              <el-switch v-model="tokenForm.allow_shared_pool" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="数据中心 (DC)">
              <el-select v-model="tokenForm.target_dc_id" placeholder="自动推荐 (依据测速/位置)" clearable style="width: 100%;">
                <el-option :value="null" label="🌐 自动推荐 (依据测速/位置)" />
                <el-option :value="1" label="DC1 美东/美西 (Miami/北美) · 53个Bot" />
                <el-option :value="2" label="DC2 欧洲 (Amsterdam)" />
                <el-option :value="3" label="DC3 美东 (Miami)" />
                <el-option :value="4" label="DC4 欧洲 (Holland)" />
                <el-option :value="5" label="DC5 亚太 (Singapore/新加坡) · 27个Bot" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="Bot阵列加速" label-width="95px">
              <el-switch v-model="tokenForm.allow_bot_pool" />
            </el-form-item>
          </el-col>
        </el-row>

        <div style="text-align: right; margin-bottom: 14px;">
          <el-button
            type="primary"
            class="btn-ssh-deploy"
            :loading="generatingToken"
            @click="handleGenerateToken"
          >
            生成专属一键安装脚本
          </el-button>
        </div>
      </el-form>

      <div v-if="generatedCommand" class="script-result-box">
        <div class="script-box-header">
          <span>在您的 VPS (root 权限) 终端执行以下单行命令：</span>
          <el-button size="small" type="primary" plain :icon="DocumentCopy" @click="copyInstallCommand">
            复制安装命令
          </el-button>
        </div>
        <pre class="terminal-cmd-block">{{ generatedCommand }}</pre>
        <div class="token-poll-status">
          <template v-if="pairedNode">
            <span class="poll-success">🎉 配对成功！节点 #{{ pairedNode.id }} ({{ pairedNode.ip }}:{{ pairedNode.port }}) 已在线接入！</span>
          </template>
          <template v-else>
            <span class="poll-waiting">⏳ 正在等待远程 VPS 执行脚本回连握手 (有效期 60 分钟)...</span>
          </template>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="tokenDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 3：暗黑实时部署终端日志 -->
    <el-dialog
      v-model="logModalVisible"
      :title="`节点部署终端实时日志 · ${activeLogNode?.node_name || ''}`"
      width="760px"
      append-to-body
      class="edge-log-dialog"
      @closed="stopLogPolling"
    >
      <div class="terminal-window">
        <div class="terminal-bar">
          <div class="term-dots">
            <span class="dot red"></span>
            <span class="dot yellow"></span>
            <span class="dot green"></span>
          </div>
          <div class="term-title">
            ssh {{ activeLogNode?.ssh_user || 'root' }}@{{ activeLogNode?.ssh_host || activeLogNode?.ip || 'vps' }}
          </div>
          <div class="term-status">
            <el-tag size="small" :type="getLogStatusTagType(activeLogStatus)">
              {{ formatStatusText(activeLogStatus) }}
            </el-tag>
          </div>
        </div>
        <pre ref="terminalPreRef" class="terminal-body">{{ activeDeployLog || '暂无部署输出日志...' }}</pre>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="copyDeployLogs" :icon="DocumentCopy">复制日志</el-button>
          <el-button
            v-if="activeLogNode"
            type="primary"
            class="btn-ssh-deploy"
            :loading="activeLogStatus === 'deploying'"
            @click="handleRetriggerDeployFromModal"
          >
            重新执行 SSH 部署
          </el-button>
          <el-button @click="logModalVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 4：边缘节点全能测速与体检工作台 -->
    <el-dialog
      v-model="benchmarkModalVisible"
      width="960px"
      append-to-body
      class="edge-benchmark-dialog"
    >
      <template #header>
        <div class="bench-dialog-header">
          <div class="bench-header-title-row">
            <span class="bench-header-title text-gradient-sakura">🌸 边缘节点全能测速与深度体检</span>
            <span v-if="activeBenchmarkNode" class="bench-header-node-tag">
              #{{ activeBenchmarkNode.id }} {{ activeBenchmarkNode.node_name }}
            </span>
          </div>
          <span class="bench-header-desc">四阶段自动化闭环：物理宽带双测 ➔ 木桶短板容量匹配 ➔ 全双工中继流播压测 ➔ 系统环境深度体检</span>
        </div>
      </template>
      <div v-if="activeBenchmarkNode" class="bench-dialog-body">
        <!-- 1. 吸顶常驻区：节点信息与全局动作 -->
        <div class="bench-top-banner glass-card">
          <div class="bench-node-info">
            <div class="bench-node-title">
              <span class="node-id-badge">#{{ activeBenchmarkNode.id }}</span>
              <span class="node-name-text">{{ activeBenchmarkNode.node_name }}</span>
              <span class="bench-host-tag">{{ formatNodeEndpoint(activeBenchmarkNode) }}</span>
            </div>
            <div class="bench-time-tag">
              <span>最后测速: </span>
              <b>{{ activeBenchmarkNode.benchmark_data?.last_benchmark_at ? formatDate(activeBenchmarkNode.benchmark_data.last_benchmark_at) : '尚未执行全能测速' }}</b>
            </div>
          </div>
          <div class="bench-top-actions">
            <el-button
              type="primary"
              size="default"
              class="btn-run-full"
              :icon="VideoPlay"
              :loading="benchmarking"
              @click="handleRunFullBenchmark"
            >
              {{ benchmarking ? '全套测速进行中...' : '一键全能体检与测速' }}
            </el-button>
            <el-button
              size="default"
              class="btn-upgrade-worker"
              :icon="RefreshRight"
              :loading="upgradingWorker"
              @click="handleUpgradeWorker"
              title="当 Edge Worker 守护程序有新功能时，一键热升级代码并重启"
            >
              一键升级服务
            </el-button>
          </div>
        </div>

        <!-- 测速执行中流光进度条 -->
        <div v-if="benchmarking" class="bench-progress-strip">
          <div class="progress-bar-animated"></div>
          <span class="progress-text">
            ⚡ 正在自适应闭环测速：Step 1 测 VPS 双向宽带 ➔ Step 2 木桶短板匹配 Bot 阵列 ➔ Step 3 全双工中继流播压测 ➔ Step 4 硬件体检与入库...
          </span>
        </div>

        <!-- 2. 吸顶常驻区：4 大核心 KPI 指标卡片 (有效短板 ➔ 匹配Bot ➔ 体感流速 ➔ 最优DC) -->
        <div class="bench-kpi-grid">
          <div class="bench-kpi-card kpi-bandwidth glass-card">
            <div class="b-kpi-header">
              <span class="b-kpi-title">VPS 物理宽带</span>
              <span class="b-kpi-badge badge-speed">
                {{ activeBenchmarkNode.benchmark_data?.bandwidth?.effective_bw_mb_s ? '木桶有效' : (activeBenchmarkNode.benchmark_data?.bandwidth?.source === 'anycast_cdn' ? 'Anycast' : '实测') }}
              </span>
            </div>
            <div class="b-kpi-val">
              <span class="val-num">{{ activeBenchmarkNode.benchmark_data?.bandwidth?.effective_bw_mb_s ?? activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mb_s ?? '--' }}</span>
              <span class="val-unit">MB/s</span>
            </div>
            <div class="b-kpi-sub" >
              下 {{ activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mb_s ?? '--' }} / 上 {{ activeBenchmarkNode.benchmark_data?.bandwidth?.up_speed_mb_s ?? '--' }}
              <span v-if="activeBenchmarkNode.benchmark_data?.bandwidth?.bottleneck_direction === 'egress_up'" class="text-rose-500 font-medium"> (出网上限)</span>
              <span v-else-if="activeBenchmarkNode.benchmark_data?.bandwidth?.bottleneck_direction === 'ingress_down'" class="text-amber-500 font-medium"> (入网上限)</span>
              <span v-else class="text-emerald-500 font-medium"> (对称)</span>
            </div>
          </div>

          <div class="bench-kpi-card kpi-bots glass-card">
            <div class="b-kpi-header">
              <span class="b-kpi-title">动态匹配 Bot 阵列</span>
              <span class="b-kpi-badge badge-optimal">
                {{ (activeBenchmarkNode.benchmark_data?.bandwidth?.matched_bots || activeBenchmarkNode.target_bot_count || 4) > 4 ? '已扩容' : '基础' }}
              </span>
            </div>
            <div class="b-kpi-val">
              <span class="val-num">{{ activeBenchmarkNode.benchmark_data?.bandwidth?.matched_bots || activeBenchmarkNode.target_bot_count || 4 }}</span>
              <span class="val-unit">个 Bot</span>
            </div>
            <div class="b-kpi-sub">
              额定算力: {{ activeBenchmarkNode.benchmark_data?.bandwidth?.rated_capacity_mb_s ? activeBenchmarkNode.benchmark_data.bandwidth.rated_capacity_mb_s + ' MB/s' : '--' }}
              · 按有效宽带匹配
            </div>
          </div>

          <div class="bench-kpi-card kpi-speed glass-card">
            <div class="b-kpi-header">
              <span class="b-kpi-title">体感中继流播吞吐</span>
              <span class="b-kpi-badge" :class="getHealthGradeClass(activeBenchmarkNode.benchmark_data?.speed?.grade)">
                {{ activeBenchmarkNode.benchmark_data?.speed?.grade || '极速' }}
              </span>
            </div>
            <div class="b-kpi-val">
              <span class="val-num">{{ (activeBenchmarkNode.benchmark_data?.speed?.relay_speed_mb_s || activeBenchmarkNode.benchmark_data?.speed?.peak_speed_mb_s) ?? '--' }}</span>
              <span class="val-unit">MB/s</span>
            </div>
            <div class="b-kpi-sub" :title="activeBenchmarkNode.benchmark_data?.speed?.bottleneck_diagnosis || ''">
              利用率: {{ activeBenchmarkNode.benchmark_data?.bandwidth?.saturation_percent ? activeBenchmarkNode.benchmark_data.bandwidth.saturation_percent + '%' : '--' }}
              · {{ activeBenchmarkNode.benchmark_data?.speed?.evaluation || '秒开评估' }}
            </div>
          </div>

          <div class="bench-kpi-card kpi-dc glass-card">
            <div class="b-kpi-header">
              <span class="b-kpi-title">最低延迟 DC / 评分</span>
              <span class="b-kpi-badge badge-optimal">推荐</span>
            </div>
            <div class="b-kpi-val">
              <span class="val-num text-dc">{{ activeBenchmarkNode.benchmark_data?.fastest_dc?.name ? (activeBenchmarkNode.benchmark_data.fastest_dc.name || '').split(' ')[0] : '--' }}</span>
            </div>
            <div class="b-kpi-sub">
              {{ activeBenchmarkNode.benchmark_data?.fastest_dc?.avg_rtt_ms !== undefined ? activeBenchmarkNode.benchmark_data.fastest_dc.avg_rtt_ms + 'ms' : '--' }}
              · 体检评分 {{ activeBenchmarkNode.benchmark_data?.health_score ?? 100 }}分
            </div>
          </div>
        </div>

        <!-- 3. Tab 选项卡分流体系 -->
        <el-tabs v-model="activeBenchmarkTab" class="bench-tabs-container">
          <!-- Tab 1: 全双工流播与中继压测 -->
          <el-tab-pane name="relay_stream" label="🚀 全双工流播与中继压测">
            <div class="tab-pane-inner">
              <div class="section-head" style="margin-top: 4px;">
                <div class="head-left">
                  <span class="section-title">全双工中继流播压测 (边拉取边推流)</span>
                  <span class="section-tip">Master 模拟真实视频播放器发起流播请求，边从 Telegram DC 拉取分片边向客户端推流，精确测量全链路体感流速与短板</span>
                </div>
                <div class="section-actions-row">
                  <el-radio-group v-model="speedSampleMb" size="small" class="sample-radio-group">
                    <el-radio-button :value="25">25 MB</el-radio-button>
                    <el-radio-button :value="50">50 MB (阵列达标)</el-radio-button>
                    <el-radio-button :value="100">100 MB (极限压测)</el-radio-button>
                  </el-radio-group>
                  <el-button
                    size="small"
                    type="primary"
                    :icon="VideoPlay"
                    :loading="testingSingleRelay"
                    @click="handleRunRelayOnly"
                  >
                    全双工中继压测
                  </el-button>
                  <el-button
                    size="small"
                    plain
                    :loading="testingSingleSpeed"
                    @click="handleRunSpeedOnly"
                  >
                    直连TG拉流
                  </el-button>
                </div>
              </div>

              <!-- 全双工全链路流速漏斗面板 -->
              <div class="relay-funnel-panel">
                <div class="funnel-title-bar">
                  <span class="funnel-title-text">
                    🌊 全双工中继全链路流速漏斗与瓶颈诊断
                  </span>
                  <el-tag
                    size="small"
                    :type="activeBenchmarkNode.benchmark_data?.speed?.grade === 'S+' || activeBenchmarkNode.benchmark_data?.speed?.grade === 'A+' ? 'success' : (activeBenchmarkNode.benchmark_data?.speed?.grade === 'B-' ? 'danger' : 'warning')"
                    effect="light"
                  >
                    {{ activeBenchmarkNode.benchmark_data?.speed?.bottleneck_diagnosis || '🟢 全链路无损满速中继' }}
                  </el-tag>
                </div>

                <div class="funnel-steps-grid">
                  <!-- 节点 1: Telegram DC -->
                  <div class="funnel-box">
                    <div class="funnel-box-label">Telegram 官方 DC</div>
                    <div class="funnel-box-val text-cyan">
                      {{ activeBenchmarkNode.benchmark_data?.speed?.tg_pull_speed_mb_s ? activeBenchmarkNode.benchmark_data.speed.tg_pull_speed_mb_s + ' MB/s' : (activeBenchmarkNode.benchmark_data?.speed?.peak_speed_mb_s ? activeBenchmarkNode.benchmark_data.speed.peak_speed_mb_s + ' MB/s' : '--') }}
                    </div>
                    <div class="funnel-box-sub">
                      DC{{ activeBenchmarkNode.benchmark_data?.speed?.target_dc || activeBenchmarkNode.target_dc_id || 5 }} · {{ activeBenchmarkNode.benchmark_data?.speed?.usable_bots_count || 4 }} 个 Bot 并发
                    </div>
                  </div>

                  <!-- 箭头 1 -->
                  <div class="funnel-arrow">➔</div>

                  <!-- 节点 2: VPS 边缘中继管道 -->
                  <div class="funnel-box">
                    <div class="funnel-box-label">VPS 边缘中继管道</div>
                    <div class="funnel-box-val">
                      入: <span class="text-emerald font-bold">{{ activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mb_s ?? '--' }}</span> /
                      出: <span class="text-sky-600 font-bold">{{ activeBenchmarkNode.benchmark_data?.bandwidth?.up_speed_mb_s ?? '--' }}</span>
                    </div>
                    <div class="funnel-box-sub">
                      有效短板: <b>{{ activeBenchmarkNode.benchmark_data?.bandwidth?.effective_bw_mb_s ?? activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mb_s ?? '--' }} MB/s</b>
                    </div>
                  </div>

                  <!-- 箭头 2 -->
                  <div class="funnel-arrow">➔</div>

                  <!-- 节点 3: 客户端真实体感 -->
                  <div class="funnel-box">
                    <div class="funnel-box-label">终端用户体感流速</div>
                    <div class="funnel-box-val text-emerald">
                      {{ activeBenchmarkNode.benchmark_data?.speed?.relay_speed_mb_s || activeBenchmarkNode.benchmark_data?.speed?.peak_speed_mb_s ? (activeBenchmarkNode.benchmark_data.speed.relay_speed_mb_s || activeBenchmarkNode.benchmark_data.speed.peak_speed_mb_s) + ' MB/s' : '--' }}
                    </div>
                    <div class="funnel-box-sub">
                      起播: {{ activeBenchmarkNode.benchmark_data?.speed?.buffer_ms ? activeBenchmarkNode.benchmark_data.speed.buffer_ms + 'ms' : '--' }} · TTFB {{ activeBenchmarkNode.benchmark_data?.speed?.ttfb_ms ? activeBenchmarkNode.benchmark_data.speed.ttfb_ms + 'ms' : '--' }}
                    </div>
                  </div>
                </div>
              </div>

              <!-- 4 项实测性能指标 -->
              <div class="speed-detail-panel">
                <div class="speed-stat-cell">
                  <span class="s-label">真实体感中继流速</span>
                  <span class="s-val text-emerald">
                    {{ activeBenchmarkNode.benchmark_data?.speed?.relay_speed_mb_s || activeBenchmarkNode.benchmark_data?.speed?.peak_speed_mb_s ? (activeBenchmarkNode.benchmark_data.speed.relay_speed_mb_s || activeBenchmarkNode.benchmark_data.speed.peak_speed_mb_s) + ' MB/s' : '--' }}
                  </span>
                  <span class="s-sub">等效出网: {{ (activeBenchmarkNode.benchmark_data?.speed?.relay_speed_mbps || activeBenchmarkNode.benchmark_data?.speed?.speed_mbps) ? (activeBenchmarkNode.benchmark_data.speed.relay_speed_mbps || activeBenchmarkNode.benchmark_data.speed.speed_mbps) + ' Mbps' : '--' }}</span>
                </div>

                <div class="speed-stat-cell">
                  <span class="s-label">Telegram DC 拉流速度</span>
                  <span class="s-val text-sky-600">
                    {{ activeBenchmarkNode.benchmark_data?.speed?.tg_pull_speed_mb_s ? activeBenchmarkNode.benchmark_data.speed.tg_pull_speed_mb_s + ' MB/s' : (activeBenchmarkNode.benchmark_data?.speed?.peak_speed_mb_s ? activeBenchmarkNode.benchmark_data.speed.peak_speed_mb_s + ' MB/s' : '--') }}
                  </span>
                  <span class="s-sub">{{ activeBenchmarkNode.benchmark_data?.speed?.usable_bots_count || activeBenchmarkNode.benchmark_data?.bandwidth?.matched_bots || 4 }} 个 Bot 并发拉流</span>
                </div>

                <div class="speed-stat-cell">
                  <span class="s-label">首包到达延迟 (TTFB)</span>
                  <span class="s-val text-cyan">
                    {{ activeBenchmarkNode.benchmark_data?.speed?.ttfb_ms ? activeBenchmarkNode.benchmark_data.speed.ttfb_ms + ' ms' : '--' }}
                  </span>
                  <span class="s-sub">起播缓冲: {{ activeBenchmarkNode.benchmark_data?.speed?.buffer_ms ? activeBenchmarkNode.benchmark_data.speed.buffer_ms + ' ms' : '--' }}</span>
                </div>

                <div class="speed-stat-cell">
                  <span class="s-label">流播体验评定</span>
                  <span class="s-val text-gold">
                    {{ activeBenchmarkNode.benchmark_data?.speed?.evaluation || '待测速评估' }}
                  </span>
                  <span class="s-sub">测试规格: {{ activeBenchmarkNode.benchmark_data?.speed?.sample_size_mb || speedSampleMb }} MB 样本</span>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- Tab 2: 物理宽带与 5 大 DC 矩阵 -->
          <el-tab-pane name="bandwidth_dcs" label="🌐 物理宽带与 5 大 DC 矩阵">
            <div class="tab-pane-inner">
              <!-- Part A: 物理宽带测速 -->
              <div class="bench-sub-block">
                <div class="section-head">
                  <div class="head-left">
                    <span class="section-title">VPS 宿主机物理宽带测速与 Bot 动态算力匹配</span>
                    <span class="section-tip">Anycast CDN + Master 专线流混合双测实测物理带宽，按 2MB/s/Bot 弹性扩缩 Bot 阵列</span>
                  </div>
                  <el-button
                    size="small"
                    class="btn-section-act"
                    :icon="RefreshRight"
                    :loading="testingSingleBandwidth"
                    @click="handleRunBandwidthOnly"
                  >
                    单独测宽带
                  </el-button>
                </div>

                <div class="speed-detail-panel">
                  <div class="speed-stat-cell">
                    <span class="s-label">实测物理下行 (入网)</span>
                    <span class="s-val text-emerald">
                      {{ activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mb_s ? activeBenchmarkNode.benchmark_data.bandwidth.down_speed_mb_s + ' MB/s' : '--' }}
                    </span>
                    <span class="s-sub">峰值下行: {{ activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mbps ? activeBenchmarkNode.benchmark_data.bandwidth.down_speed_mbps + ' Mbps' : '--' }}</span>
                  </div>

                  <div class="speed-stat-cell">
                    <span class="s-label">实测物理上行 (出网)</span>
                    <span class="s-val text-cyan">
                      {{ activeBenchmarkNode.benchmark_data?.bandwidth?.up_speed_mb_s ? activeBenchmarkNode.benchmark_data.bandwidth.up_speed_mb_s + ' MB/s' : '--' }}
                    </span>
                    <span class="s-sub">出网峰值: {{ activeBenchmarkNode.benchmark_data?.bandwidth?.up_speed_mbps ? activeBenchmarkNode.benchmark_data.bandwidth.up_speed_mbps + ' Mbps' : '--' }}</span>
                  </div>

                  <div class="speed-stat-cell">
                    <span class="s-label">木桶有效带宽 (短板)</span>
                    <span class="s-val text-gold">
                      {{ activeBenchmarkNode.benchmark_data?.bandwidth?.effective_bw_mb_s ? activeBenchmarkNode.benchmark_data.bandwidth.effective_bw_mb_s + ' MB/s' : (activeBenchmarkNode.benchmark_data?.bandwidth?.down_speed_mb_s ? activeBenchmarkNode.benchmark_data.bandwidth.down_speed_mb_s + ' MB/s' : '--') }}
                    </span>
                    <span class="s-sub">{{ activeBenchmarkNode.benchmark_data?.bandwidth?.bottleneck_direction === 'egress_up' ? '🔴 受限于 VPS 上行出网' : (activeBenchmarkNode.benchmark_data?.bandwidth?.bottleneck_direction === 'ingress_down' ? '🟡 受限于 VPS 下行入网' : '🟢 上下行对称') }}</span>
                  </div>

                  <div class="speed-stat-cell">
                    <span class="s-label">动态匹配 Bot 阵列</span>
                    <span class="s-val text-purple">
                      {{ activeBenchmarkNode.benchmark_data?.bandwidth?.matched_bots || activeBenchmarkNode.target_bot_count || 4 }} 个 Bot
                    </span>
                    <span class="s-sub">额定算力: {{ activeBenchmarkNode.benchmark_data?.bandwidth?.rated_capacity_mb_s ? activeBenchmarkNode.benchmark_data.bandwidth.rated_capacity_mb_s + ' MB/s' : '--' }}</span>
                  </div>
                </div>
              </div>

              <!-- Part B: 5 大 DC 延迟矩阵 -->
              <div class="bench-sub-block" style="margin-top: 14px;">
                <div class="section-head">
                  <div class="head-left">
                    <span class="section-title">Telegram 全球 5 大数据中心 (DC1 ~ DC5) 物理延迟矩阵</span>
                    <span class="section-tip">从该 VPS 边缘节点并发向 Telegram 官方骨干 DC 发起 TCP 握手探测链路质量</span>
                  </div>
                  <el-button
                    size="small"
                    class="btn-section-act"
                    :icon="RefreshRight"
                    :loading="testingSingleDc"
                    @click="handleRunDcsOnly"
                  >
                    重新探测 DC
                  </el-button>
                </div>

                <div class="dc-cards-grid">
                  <div
                    v-for="dc in (activeBenchmarkNode.benchmark_data?.dcs || defaultDcs)"
                    :key="dc.dc_id"
                    :class="['dc-item-card', { 'is-fastest': activeBenchmarkNode.benchmark_data?.fastest_dc?.id === dc.dc_id }]"
                  >
                    <div class="dc-card-top">
                      <div class="dc-name-row">
                        <span class="dc-id-pill">DC{{ dc.dc_id }}</span>
                        <span class="dc-title">{{ (dc.name || '').split(' ')[1] || dc.name || '' }}</span>
                      </div>
                      <div class="dc-badges">
                        <span v-if="activeBenchmarkNode.benchmark_data?.fastest_dc?.id === dc.dc_id" class="badge-fastest">最快</span>
                        <span v-if="activeBenchmarkNode.benchmark_data?.home_dc === dc.dc_id" class="badge-homedc">母号DC</span>
                      </div>
                    </div>
                    <div class="dc-rtt-box">
                      <span class="dc-rtt-num">{{ dc.avg_rtt_ms > 0 ? dc.avg_rtt_ms + ' ms' : '--' }}</span>
                      <span :class="['dc-quality-pill', getDcRatingClass(dc.rating)]">
                        {{ dc.rating_label || '待测' }}
                      </span>
                    </div>
                    <div class="dc-meta-foot">
                      <span>{{ dc.region }}</span>
                      <span>丢包: {{ dc.packet_loss_pct }}%</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- Tab 3: 硬件与系统体检 -->
          <el-tab-pane name="diagnostics" label="🛡️ 硬件栈与系统体检">
            <div class="tab-pane-inner">
              <div class="section-head" style="margin-top: 4px;">
                <div class="head-left">
                  <span class="section-title">VPS 宿主机硬件栈与高并发环境体检报告</span>
                  <span class="section-tip">检查 CPU/内存/磁盘、LimitNOFILE 文件句柄上限及 Telegram 微服务状态</span>
                </div>
                <el-button
                  size="small"
                  class="btn-section-act"
                  :icon="RefreshRight"
                  :loading="testingSingleDiag"
                  @click="handleRunDiagOnly"
                >
                  刷新体检
                </el-button>
              </div>

              <div v-if="activeBenchmarkNode.benchmark_data?.diagnostics?.issues?.length" class="diag-issues-banner">
                <span class="issue-tag">⚠️ 潜在性能风险:</span>
                <span v-for="(iss, i) in activeBenchmarkNode.benchmark_data.diagnostics.issues" :key="i" class="issue-item">
                  {{ iss }}
                </span>
              </div>

              <div class="diag-items-grid">
                <div class="diag-cell">
                  <div class="d-icon">💻</div>
                  <div class="d-info">
                    <span class="d-title">操作系统与内核</span>
                    <span class="d-desc">{{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.os || 'Linux' }} ({{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.arch || 'x86_64' }})</span>
                    <span class="d-sub">内核: {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.kernel || '6.x' }}</span>
                  </div>
                </div>

                <div class="diag-cell">
                  <div class="d-icon">⚡</div>
                  <div class="d-info">
                    <span class="d-title">CPU 核心与当前负荷</span>
                    <span class="d-desc">
                      {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.cpu_cores || 1 }} 核心 · 占用 {{ (activeBenchmarkNode.benchmark_data?.diagnostics?.system?.cpu_percent || 0).toFixed(1) }}%
                    </span>
                    <span class="d-sub">
                      Load Avg: {{ (activeBenchmarkNode.benchmark_data?.diagnostics?.system?.load_avg || []).join(' / ') }}
                    </span>
                  </div>
                </div>

                <div class="diag-cell">
                  <div class="d-icon">🧠</div>
                  <div class="d-info">
                    <span class="d-title">物理内存容量与占用</span>
                    <span class="d-desc">
                      {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.mem_used_mb || 0 }} MB / {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.mem_total_mb || 0 }} MB
                      ({{ (activeBenchmarkNode.benchmark_data?.diagnostics?.system?.mem_percent || 0).toFixed(1) }}%)
                    </span>
                    <span class="d-sub">空闲: {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.mem_free_mb || 0 }} MB</span>
                  </div>
                </div>

                <div class="diag-cell">
                  <div class="d-icon">💾</div>
                  <div class="d-info">
                    <span class="d-title">根磁盘分区空间</span>
                    <span class="d-desc">
                      {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.disk_used_gb || 0 }} GB / {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.disk_total_gb || 0 }} GB
                      ({{ (activeBenchmarkNode.benchmark_data?.diagnostics?.system?.disk_percent || 0).toFixed(1) }}%)
                    </span>
                    <span class="d-sub">剩余可用: {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.disk_free_gb || 0 }} GB</span>
                  </div>
                </div>

                <div class="diag-cell">
                  <div class="d-icon">🚀</div>
                  <div class="d-info">
                    <span class="d-title">最大并发文件句柄 (LimitNOFILE)</span>
                    <span class="d-desc">
                      {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.nofile_limit || 1024 }}
                      <el-tag
                        size="small"
                        :type="(activeBenchmarkNode.benchmark_data?.diagnostics?.system?.nofile_limit || 0) >= 65535 ? 'success' : 'warning'"
                        effect="light"
                        class="ml-2"
                      >
                        {{ (activeBenchmarkNode.benchmark_data?.diagnostics?.system?.nofile_limit || 0) >= 65535 ? '✅ 极高并发达标' : '建议提升' }}
                      </el-tag>
                    </span>
                    <span class="d-sub">当前活动 TCP 连接数: {{ activeBenchmarkNode.benchmark_data?.diagnostics?.system?.open_tcp_connections || 0 }}</span>
                  </div>
                </div>

                <div class="diag-cell">
                  <div class="d-icon">🤖</div>
                  <div class="d-info">
                    <span class="d-title">Telegram MTProto 推流阵列</span>
                    <span class="d-desc">
                      状态: {{ activeBenchmarkNode.benchmark_data?.diagnostics?.telegram?.connected ? '✅ MTProto 已就绪' : '未连接' }}
                      <el-tag
                        size="small"
                        :type="isNodeDcMatched(activeBenchmarkNode) ? 'success' : 'warning'"
                        effect="dark"
                        class="ml-2"
                      >
                        {{ isNodeDcMatched(activeBenchmarkNode) ? '⚡ DC' + (activeBenchmarkNode.target_dc_id || activeBenchmarkNode.benchmark_data?.diagnostics?.telegram?.home_dc || 5) + ' 原生直连' : '⚠️ 跨大洋中转中' }}
                      </el-tag>
                    </span>
                    <span class="d-sub">
                      主Bot: @{{ activeBenchmarkNode.benchmark_data?.diagnostics?.telegram?.bot_username || activeBenchmarkNode.assigned_bot_username || '未同步' }} (DC{{ activeBenchmarkNode.benchmark_data?.diagnostics?.telegram?.home_dc || 5 }})
                      <template v-if="activeBenchmarkNode.benchmark_data?.diagnostics?.telegram?.worker_bots_count">
                        · {{ activeBenchmarkNode.benchmark_data.diagnostics.telegram.worker_bots_count }} 个Bot阵列
                      </template>
                    </span>
                    <div v-if="!isNodeDcMatched(activeBenchmarkNode)" style="margin-top: 6px;">
                      <el-button
                        size="small"
                        type="warning"
                        plain
                        @click="handleReassignBot(activeBenchmarkNode)"
                      >
                        一键纠偏至实测最优 DC Bot 并热重载
                      </el-button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- Tab 4: 主从调度链路 -->
          <el-tab-pane name="master_link" label="🔗 主从调度与安全链路">
            <div class="tab-pane-inner">
              <div class="section-head" style="margin-top: 4px;">
                <div class="head-left">
                  <span class="section-title">Master 主控 ↔ 边缘 VPS 双向调度通信链路</span>
                  <span class="section-tip">评估主控向该边缘节点签发 302 重定向 Ticket 及内部管理通道通信质量</span>
                </div>
              </div>

              <div class="link-bench-grid">
                <div class="link-stat-item">
                  <span class="l-label">往返网络 RTT</span>
                  <span class="l-val text-emerald">{{ activeBenchmarkNode.benchmark_data?.link?.rtt_ms ? activeBenchmarkNode.benchmark_data.link.rtt_ms + ' ms' : '--' }}</span>
                </div>
                <div class="link-stat-item">
                  <span class="l-label">Master 专线下发吞吐</span>
                  <span class="l-val text-cyan">{{ activeBenchmarkNode.benchmark_data?.link?.down_speed_mb_s ? activeBenchmarkNode.benchmark_data.link.down_speed_mb_s + ' MB/s' : '--' }}</span>
                </div>
                <div class="link-stat-item">
                  <span class="l-label">通道防伪与安全</span>
                  <span class="l-val text-emerald">✅ HMAC-SHA256 密签防伪</span>
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="benchmarkModalVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>
    <!-- 弹窗 5：节点 Bot 调度与分配工作台 -->
    <el-dialog
      v-model="assignBotDialogVisible"
      title="节点 Bot 调度与分配工作台"
      width="780px"
      :close-on-click-modal="false"
      append-to-body
      class="edge-assign-bot-dialog"
    >
      <div v-if="activeAssignNode" class="assign-dialog-body">
        <!-- 节点当前状态概览 -->
        <div class="assign-node-summary glass-card">
          <div class="ans-left">
            <div class="ans-name-row">
              <span class="ans-id">#{{ activeAssignNode.id }}</span>
              <span class="ans-title">{{ activeAssignNode.node_name }}</span>
              <span class="ans-ip font-mono">{{ activeAssignNode.ip }}</span>
            </div>
            <div class="ans-dc-row">
              <span v-if="activeAssignNode.benchmark_data?.fastest_dc?.name" class="ans-dc-badge optimal">
                ⚡ VPS 实测最低延迟: <b>{{ activeAssignNode.benchmark_data.fastest_dc.name }} ({{ activeAssignNode.benchmark_data.fastest_dc.avg_rtt_ms }}ms)</b>
              </span>
              <span v-else class="ans-dc-badge muted">
                ⏳ 尚未执行 DC 测速 (默认分配 DC5 亚太)
              </span>
            </div>
          </div>
          <div class="ans-right">
            <div class="ans-cur-bot-box">
              <span class="ans-cur-label">当前生效主 Bot</span>
              <span class="ans-cur-val">
                🤖 @{{ activeAssignNode.assigned_bot_username || '智能调度' }}
                <small v-if="activeAssignNode.target_dc_id">(DC{{ activeAssignNode.target_dc_id }})</small>
              </span>
              <el-tag size="small" :type="activeAssignNode.assigned_bot_token ? 'primary' : 'info'" effect="light">
                {{ activeAssignNode.assigned_bot_token ? '手动指定' : '智能自动' }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 模式切换单选卡片 -->
        <div class="assign-mode-tabs">
          <div
            class="mode-card"
            :class="{ active: assignBotForm.mode === 'auto' }"
            @click="setAssignMode('auto')"
          >
            <div class="mode-card-header">
              <div class="mode-radio-dot"></div>
              <span class="mode-title">🤖 智能自动分配 (推荐)</span>
            </div>
            <p class="mode-desc">根据 VPS 物理延迟测速结果，自动优选同 DC 原生健康 Bot，链路损耗最低且无需人工挑选。</p>
          </div>

          <div
            class="mode-card"
            :class="{ active: assignBotForm.mode === 'manual' }"
            @click="setAssignMode('manual')"
          >
            <div class="mode-card-header">
              <div class="mode-radio-dot"></div>
              <span class="mode-title">🎯 手动指定特定 Bot</span>
            </div>
            <p class="mode-desc">从全集群 80 个 Bot 资产池中精准指定任意特定 Bot 作为该节点主凭据，支持按 DC 筛选及搜索。</p>
          </div>
        </div>

        <!-- 模式 A：自动分配配置 -->
        <div v-if="assignBotForm.mode === 'auto'" class="auto-mode-config glass-card">
          <!-- 物理宽带与推荐 Bot 匹配卡片 -->
          <div class="bw-recommend-box" style="margin-bottom: 16px; padding: 12px 14px; background: rgba(255, 255, 255, 0.04); border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
              <div>
                <span style="font-size: 13px; font-weight: 600;">🌐 VPS 物理实测宽带: </span>
                <b class="text-emerald font-mono" style="margin-left: 6px;">
                  {{ activeAssignNode.benchmark_data?.bandwidth?.effective_bw_mb_s ? '有效 ' + activeAssignNode.benchmark_data.bandwidth.effective_bw_mb_s + ' MB/s (下' + activeAssignNode.benchmark_data.bandwidth.down_speed_mb_s + ' / 上' + (activeAssignNode.benchmark_data.bandwidth.up_speed_mb_s || '--') + ')' : (activeAssignNode.benchmark_data?.bandwidth?.down_speed_mb_s ? activeAssignNode.benchmark_data.bandwidth.down_speed_mb_s + ' MB/s (' + activeAssignNode.benchmark_data.bandwidth.down_speed_mbps + ' Mbps)' : '尚未单独测速 (默认保底 8 MB/s)') }}
                </b>
              </div>
              <div style="display: flex; gap: 8px;">
                <el-button size="small" type="primary" plain @click="applyRecommendedBots">
                  ⚡ 智能推荐 {{ getRecommendedBots(activeAssignNode) }} 个 Bot
                </el-button>
                <el-button size="small" type="success" plain @click="applyMaxBots">
                  🚀 极速满载 (最多 100 Bot)
                </el-button>
              </div>
            </div>
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--el-text-color-secondary);">
              <div style="display: flex; align-items: center; gap: 10px;">
                <span>动态 Bot 阵列数量:</span>
                <el-input-number v-model="assignBotForm.target_bot_count" :min="2" :max="100" size="small" />
              </div>
              <span class="text-muted">
                当前延迟: <b class="font-mono">{{ activeAssignNode.benchmark_data?.fastest_dc?.avg_rtt_ms ? activeAssignNode.benchmark_data.fastest_dc.avg_rtt_ms + 'ms' : '未知' }}</b>
                · 单Bot算力: <b class="font-mono">{{ getPerBotCapacity(activeAssignNode) }} MB/s</b>
                · 阵列总算力: <b class="text-emerald font-mono">{{ (assignBotForm.target_bot_count * getPerBotCapacity(activeAssignNode)).toFixed(1) }} MB/s</b>
                ({{ (assignBotForm.target_bot_count * getPerBotCapacity(activeAssignNode) * 8).toFixed(0) }} Mbps)
              </span>
            </div>
          </div>

          <div class="config-row">
            <span class="config-label">目标数据中心 (DC):</span>
            <el-select v-model="assignBotForm.target_dc_id" placeholder="请选择目标 DC" style="width: 260px;">
              <el-option :value="0" label="自动判定 (根据 VPS 测速推荐)" />
              <el-option :value="1" label="DC1 北美/美西 (Miami · 53个Bot)" />
              <el-option :value="2" label="DC2 欧洲 (Amsterdam)" />
              <el-option :value="3" label="DC3 美东 (Miami)" />
              <el-option :value="4" label="DC4 欧洲 (Amsterdam)" />
              <el-option :value="5" label="DC5 亚太 (Singapore · 27个Bot)" />
            </el-select>
          </div>
          <div class="auto-mode-hint">
            💡 系统将从目标 DC 的原生 Bot 池中，根据节点编号哈希挑选专属原生 Bot 并配置 2~4 个同 DC 并发阵列。
          </div>
        </div>

        <!-- 模式 B：手动选择 Bot 资产池 -->
        <div v-else class="manual-mode-config glass-card">
          <!-- 搜索与 DC 过滤栏 -->
          <div class="bots-filter-bar">
            <el-input
              v-model="botsSearchQuery"
              placeholder="搜索 Bot 用户名或编号..."
              :prefix-icon="Search"
              clearable
              size="default"
              style="width: 240px;"
            />
            <div class="dc-filter-capsules">
              <button
                v-for="d in dcTabs"
                :key="d.id ?? 'all'"
                class="dc-cap-btn"
                :class="{ active: botsDcFilter === d.id }"
                @click="setBotsDcFilter(d.id)"
              >
                {{ d.label }} ({{ getDcCount(d.id) }})
              </button>
            </div>
          </div>

          <!-- 80 个 Bot 列表展示区 -->
          <div v-loading="botsPoolLoading" class="bots-grid-scroller">
            <div
              v-for="bot in filteredBotsPool"
              :key="bot.token"
              class="bot-select-item"
              :class="{ selected: assignBotForm.selected_token === bot.token }"
              @click="selectBotItem(bot)"
            >
              <div class="bs-left">
                <div class="bs-radio-indicator"></div>
                <div class="bs-info">
                  <div class="bs-name-row">
                    <span class="bs-bot-name">@{{ bot.username }}</span>
                    <el-tag
                      size="small"
                      :type="bot.dc_id === 5 ? 'success' : (bot.dc_id === 1 ? 'primary' : 'warning')"
                      effect="dark"
                      class="bs-dc-tag"
                    >
                      DC{{ bot.dc_id }}
                    </el-tag>
                    <el-tag v-if="bot.is_main" size="small" type="danger" effect="plain" class="bs-main-tag">
                      👑 主控
                    </el-tag>
                  </div>
                  <div class="bs-sub-row">
                    <span class="bs-mask font-mono">{{ bot.token_mask }}</span>
                    <span v-if="bot.assigned_count > 0" class="bs-bound-warn">
                      已绑定 {{ bot.assigned_count }} 节点 ({{ bot.assigned_nodes.map(n => n.name).join(', ') }})
                    </span>
                    <span v-else class="bs-bound-idle text-emerald-600">
                      🟢 当前空闲
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="filteredBotsPool.length === 0" class="empty-bots-hint">
              未搜索到匹配的机器人凭证
            </div>
          </div>
        </div>

        <!-- 共同高级开关 -->
        <div class="assign-advanced-options glass-card">
          <div class="adv-opt-item">
            <div class="adv-opt-info">
              <span class="adv-opt-title">开启同 DC 多 Bot 共享阵列并发加速</span>
              <span class="adv-opt-desc">分配 2~4 个同 DC 额外 Worker Bot 并行拉取分片，突破 Telegram 420 限流</span>
            </div>
            <el-switch v-model="assignBotForm.allow_bot_pool" />
          </div>

          <div class="adv-opt-item">
            <div class="adv-opt-info">
              <span class="adv-opt-title">保存后立即下发 OTA 远程热更新生效</span>
              <span class="adv-opt-desc">自动向边缘节点推送新配置并平滑重启推流微服务守护进程（零掉线）</span>
            </div>
            <el-switch v-model="assignBotForm.trigger_ota" />
          </div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="assignBotDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="assigningBot"
            @click="handleSaveAssignBot"
          >
            确认分配并应用
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 节点租户分流流量审计明细弹窗 -->
    <el-dialog
      v-model="tenantMetricsDialogVisible"
      :title="`📊 ${activeTenantMetricsNode?.node_name || '节点'} · 租户分流流量明细与审计`"
      width="840px"
      class="edge-tenant-dialog glass-card"
      destroy-on-close
    >
      <div v-if="activeTenantMetricsNode" class="tenant-dialog-body">
        <!-- 顶部 4 张核心 KPI 统计卡片 -->
        <div class="tenant-kpi-grid">
          <div class="t-kpi-card">
            <div class="t-kpi-label">当前活跃拉流租户</div>
            <div class="t-kpi-val text-emerald-500">
              {{ getNodeActiveTenants(activeTenantMetricsNode).length }} <small>位</small>
            </div>
          </div>
          <div class="t-kpi-card">
            <div class="t-kpi-label">节点实时推流总速率</div>
            <div class="t-kpi-val text-sky-500">
              {{ formatBytes(activeTenantMetricsNode.metrics?.net_tx || 0) }}/s
            </div>
          </div>
          <div class="t-kpi-card">
            <div class="t-kpi-label">该节点累计卸载流量</div>
            <div class="t-kpi-val text-purple-500">
              {{ formatBytes(activeTenantMetricsNode.metrics?.total_bytes_served || 0) }}
            </div>
          </div>
          <div class="t-kpi-card">
            <div class="t-kpi-label">历史服务租户总数</div>
            <div class="t-kpi-val text-slate-700">
              {{ (activeTenantMetricsNode.metrics?.tenants || []).length }} <small>位</small>
            </div>
          </div>
        </div>

        <!-- 租户明细列表 -->
        <div class="tenant-table-wrap">
          <!-- 移动端租户排行榜卡片流 -->
          <div class="mobile-tenant-rank-cards md:hidden flex flex-col gap-2.5">
            <div
              v-for="(row, idx) in (activeTenantMetricsNode.metrics?.tenants || [])"
              :key="row.tenant_id ?? idx"
              class="mobile-tenant-rank-card p-3 rounded-xl border border-pink-100 bg-white/90 shadow-sm flex flex-col gap-2"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span :class="['rank-badge shrink-0', idx === 0 ? 'rank-1' : idx === 1 ? 'rank-2' : idx === 2 ? 'rank-3' : 'rank-other']">
                    #{{ idx + 1 }}
                  </span>
                  <div class="t-avatar shrink-0">
                    {{ row.username.replace(/^@/, '').slice(0, 1).toUpperCase() }}
                  </div>
                  <div class="flex flex-col min-w-0">
                    <span class="text-xs font-semibold text-slate-800 truncate">@{{ row.username.replace(/^@/, '') }}</span>
                    <div class="flex items-center gap-1 mt-0.5">
                      <el-tag v-if="row.is_owner" size="small" type="warning" effect="light" class="!h-4 !px-1 !text-[10px]">👑 宿主</el-tag>
                      <el-tag v-else-if="row.tenant_id === 0" size="small" type="info" effect="light" class="!h-4 !px-1 !text-[10px]">🌐 访客</el-tag>
                      <el-tag v-else size="small" type="success" effect="light" class="!h-4 !px-1 !text-[10px]">🤝 借用</el-tag>
                    </div>
                  </div>
                </div>
                <div class="text-right shrink-0">
                  <div v-if="row.active_streams > 0 || row.net_tx > 0" class="status-streaming-badge scale-90">
                    <span class="pulse-dot"></span>
                    <span class="speed">{{ formatBytes(row.net_tx) }}/s</span>
                  </div>
                  <div v-else class="status-idle-badge scale-90">
                    <span class="idle-dot"></span>
                    <span>空闲中</span>
                  </div>
                </div>
              </div>
              <div class="pt-1.5 border-t border-slate-100 flex items-center justify-between gap-2 text-xs">
                <span class="text-slate-500">累计用量: <b class="text-slate-800 font-mono">{{ formatBytes(row.total_bytes) }}</b></span>
                <span class="text-slate-400 text-[11px]">{{ row.last_active ? formatRelativeTime(row.last_active) : '未记录' }}</span>
              </div>
              <div class="w-full">
                <el-progress
                  :percentage="calcTenantRatio(row.total_bytes, activeTenantMetricsNode.metrics?.total_bytes_served)"
                  :stroke-width="5"
                  :show-text="false"
                  color="#ec4899"
                />
              </div>
            </div>
          </div>
          <!-- 桌面端租户明细表格 -->
          <div class="hidden md:block">
            <el-table
            :data="activeTenantMetricsNode.metrics?.tenants || []"
            empty-text="暂无租户在此节点产生拉流记录"
            class="tenant-details-table"
            max-height="380"
          >
            <el-table-column label="排名" width="70" align="center">
              <template #default="{ $index }">
                <span :class="['rank-badge', $index === 0 ? 'rank-1' : $index === 1 ? 'rank-2' : $index === 2 ? 'rank-3' : 'rank-other']">
                  #{{ $index + 1 }}
                </span>
              </template>
            </el-table-column>

            <el-table-column label="租户身份" min-width="190">
              <template #default="{ row }">
                <div class="tenant-identity-cell">
                  <div class="t-avatar">
                    {{ row.username.replace(/^@/, '').slice(0, 1).toUpperCase() }}
                  </div>
                  <div class="t-info">
                    <div class="t-username flex items-center gap-1.5">
                      <span class="font-medium">@{{ row.username.replace(/^@/, '') }}</span>
                      <el-tag v-if="row.masked" size="small" type="info" effect="plain" class="scale-90">脱敏保护</el-tag>
                    </div>
                    <div class="t-role-tags">
                      <el-tag v-if="row.is_owner" size="small" type="warning" effect="light">👑 节点宿主</el-tag>
                      <el-tag v-else-if="row.tenant_id === 0" size="small" type="info" effect="light">🌐 公共访客</el-tag>
                      <el-tag v-else size="small" type="success" effect="light">🤝 共享借用</el-tag>
                    </div>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="当前状态" width="165" align="center">
              <template #default="{ row }">
                <div v-if="row.active_streams > 0 || row.net_tx > 0" class="status-streaming-badge">
                  <span class="pulse-dot"></span>
                  <div class="streaming-text">
                    <span class="speed">{{ formatBytes(row.net_tx) }}/s</span>
                    <span class="streams">{{ row.active_streams }}路并发</span>
                  </div>
                </div>
                <div v-else class="status-idle-badge">
                  <span class="idle-dot"></span>
                  <span>空闲中</span>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="累计分流用量" min-width="155" align="right">
              <template #default="{ row }">
                <div class="t-bytes-cell">
                  <span class="t-bytes-val">{{ formatBytes(row.total_bytes) }}</span>
                  <div class="t-bytes-bar">
                    <el-progress
                      :percentage="calcTenantRatio(row.total_bytes, activeTenantMetricsNode.metrics?.total_bytes_served)"
                      :stroke-width="5"
                      :show-text="false"
                      color="#ec4899"
                    />
                    <span class="t-ratio-num">
                      {{ calcTenantRatio(row.total_bytes, activeTenantMetricsNode.metrics?.total_bytes_served) }}%
                    </span>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="最近活跃" width="125" align="center">
              <template #default="{ row }">
                <span class="text-xs text-slate-500">
                  {{ row.last_active ? formatRelativeTime(row.last_active) : '未记录' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
          </div>
        </div>

        <!-- 隐私保护提示 -->
        <div class="tenant-privacy-notice">
          <span class="notice-icon">🛡️</span>
          <span>
            <b>多租户隔离规范</b>: 管理员可透视所有租户真实明细；节点主人查看借用者时，系统已自动对其他租户名称进行隐私脱敏，用量及统计百分百真实可靠。
          </span>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" @click="tenantMetricsDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 全集群租户边缘分流总榜弹窗 -->
    <el-dialog
      v-model="clusterTenantsDialogVisible"
      title="📊 全集群边缘推流租户分流总榜"
      width="840px"
      class="edge-tenant-dialog glass-card"
      destroy-on-close
    >
      <div class="tenant-dialog-body">
        <div class="tenant-kpi-grid">
          <div class="t-kpi-card">
            <div class="t-kpi-label">全网拉流租户总数</div>
            <div class="t-kpi-val text-emerald-500">
              {{ clusterTenantsList.length }} <small>位</small>
            </div>
          </div>
          <div class="t-kpi-card">
            <div class="t-kpi-label">集群活跃流播总路数</div>
            <div class="t-kpi-val text-sky-500">
              {{ summary.active_streams || 0 }} <small>路</small>
            </div>
          </div>
          <div class="t-kpi-card">
            <div class="t-kpi-label">全网聚合实时出网</div>
            <div class="t-kpi-val text-pink-500">
              {{ formatBytes(summary.total_tx_speed || 0) }}/s
            </div>
          </div>
          <div class="t-kpi-card">
            <div class="t-kpi-label">已为主控卸载总流量</div>
            <div class="t-kpi-val text-purple-500">
              {{ formatBytes(summary.total_bytes_served || totalClusterTenantBytes) }}
            </div>
          </div>
        </div>

        <div class="tenant-table-wrap">
          <!-- 移动端全集群租户总榜卡片流 -->
          <div class="mobile-tenant-rank-cards md:hidden flex flex-col gap-2.5">
            <div
              v-for="(row, idx) in clusterTenantsList"
              :key="row.tenant_id ?? idx"
              class="mobile-tenant-rank-card p-3 rounded-xl border border-pink-100 bg-white/90 shadow-sm flex flex-col gap-2"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span :class="['rank-badge shrink-0', idx === 0 ? 'rank-1' : idx === 1 ? 'rank-2' : idx === 2 ? 'rank-3' : 'rank-other']">
                    #{{ idx + 1 }}
                  </span>
                  <div class="t-avatar shrink-0">
                    {{ row.username.replace(/^@/, '').slice(0, 1).toUpperCase() }}
                  </div>
                  <div class="flex flex-col min-w-0">
                    <span class="text-xs font-semibold text-slate-800 truncate">@{{ row.username.replace(/^@/, '') }}</span>
                    <span class="text-[11px] text-slate-400">使用节点: {{ row.node_count || 1 }} 个</span>
                  </div>
                </div>
                <div class="text-right shrink-0">
                  <div v-if="row.active_streams > 0 || row.net_tx > 0" class="status-streaming-badge scale-90">
                    <span class="pulse-dot"></span>
                    <span class="speed">{{ formatBytes(row.net_tx) }}/s</span>
                  </div>
                  <div v-else class="status-idle-badge scale-90">
                    <span class="idle-dot"></span>
                    <span>空闲中</span>
                  </div>
                </div>
              </div>
              <div class="pt-1.5 border-t border-slate-100 flex items-center justify-between gap-2 text-xs">
                <span class="text-slate-500">全网流量: <b class="text-slate-800 font-mono">{{ formatBytes(row.total_bytes) }}</b></span>
                <span class="text-slate-400 text-[11px]">{{ row.last_active ? formatRelativeTime(row.last_active) : '未记录' }}</span>
              </div>
              <div class="w-full">
                <el-progress
                  :percentage="calcTenantRatio(row.total_bytes, summary.total_bytes_served)"
                  :stroke-width="5"
                  :show-text="false"
                  color="#ec4899"
                />
              </div>
            </div>
          </div>
          <!-- 桌面端全集群租户总榜表格 -->
          <div class="hidden md:block">
            <el-table
            :data="clusterTenantsList"
            empty-text="暂无租户分流数据"
            class="tenant-details-table"
            max-height="380"
          >
            <el-table-column label="排名" width="70" align="center">
              <template #default="{ $index }">
                <span :class="['rank-badge', $index === 0 ? 'rank-1' : $index === 1 ? 'rank-2' : $index === 2 ? 'rank-3' : 'rank-other']">
                  #{{ $index + 1 }}
                </span>
              </template>
            </el-table-column>

            <el-table-column label="租户身份" min-width="190">
              <template #default="{ row }">
                <div class="tenant-identity-cell">
                  <div class="t-avatar">
                    {{ row.username.replace(/^@/, '').slice(0, 1).toUpperCase() }}
                  </div>
                  <div class="t-info">
                    <div class="t-username font-medium">@{{ row.username.replace(/^@/, '') }}</div>
                    <div class="text-xs text-slate-400">使用节点: {{ row.node_count || 1 }} 个</div>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="实时状态" width="165" align="center">
              <template #default="{ row }">
                <div v-if="row.active_streams > 0 || row.net_tx > 0" class="status-streaming-badge">
                  <span class="pulse-dot"></span>
                  <div class="streaming-text">
                    <span class="speed">{{ formatBytes(row.net_tx) }}/s</span>
                    <span class="streams">{{ row.active_streams }}路并发</span>
                  </div>
                </div>
                <div v-else class="status-idle-badge">
                  <span class="idle-dot"></span>
                  <span>空闲中</span>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="全网消耗流量" min-width="160" align="right">
              <template #default="{ row }">
                <div class="t-bytes-cell">
                  <span class="t-bytes-val">{{ formatBytes(row.total_bytes) }}</span>
                  <div class="t-bytes-bar">
                    <el-progress
                      :percentage="calcTenantRatio(row.total_bytes, summary.total_bytes_served)"
                      :stroke-width="5"
                      :show-text="false"
                      color="#ec4899"
                    />
                    <span class="t-ratio-num">
                      {{ calcTenantRatio(row.total_bytes, summary.total_bytes_served || totalClusterTenantBytes) }}%
                    </span>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="最近活跃" width="125" align="center">
              <template #default="{ row }">
                <span class="text-xs text-slate-500">
                  {{ row.last_active ? formatRelativeTime(row.last_active) : '未记录' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" @click="clusterTenantsDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

  </div>
</template>


<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Monitor,
  DocumentCopy,
  RefreshRight,
  Connection,
  VideoPlay,
  Odometer,
  TrendCharts,
  Search,
  ArrowDown,
  ArrowRight,
  Grid,
  Tickets,
  Compass,
  Link,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { wsClient, type WSMessage } from '@/utils/websocket'
import {
  getEdgeNodes,
  createEdgeNode,
  updateEdgeNode,
  deleteEdgeNode,
  triggerEdgeNodeDeploy,
  getEdgeNodeDeployLogs,
  clearEdgeNodePassword,
  testEdgeNodeHealth,
  generateEdgeNodeToken,
  getEdgeTokenStatus,
  runEdgeDcsBenchmark,
  runEdgeTgSpeedBenchmark,
  runEdgeDiagnostics,
  runEdgeBandwidthBenchmark,
  runEdgeRelayStreamBenchmark,
  runEdgeFullBenchmark,
  upgradeEdgeNodeWorker,
  reassignEdgeNodeBot,
  getEdgeBotsPool,
  type ClusterBotInfo,
} from '@/api'
import type {
  EdgeNode,
  EdgeNodeSummary,
  EdgeNodeTenantMetric,
  EdgeDcResult,
} from '@/types/api'
import { formatBytes, formatDate } from '@/utils/formatters'

const authStore = useAuthStore()

const loading = ref(false)
const manualRefreshing = ref(false)
const wsConnected = ref(false)
let wsUnsubscribers: (() => void)[] = []

const tenantMetricsDialogVisible = ref(false)
const activeTenantMetricsNode = ref<EdgeNode | null>(null)
const clusterTenantsDialogVisible = ref(false)

function getNodeActiveTenants(node: EdgeNode | null | undefined): EdgeNodeTenantMetric[] {
  if (!node || !node.metrics) {
    return []
  }
  const rawTenants = node.metrics.tenants
  let list: EdgeNodeTenantMetric[] = []
  if (Array.isArray(rawTenants)) {
    list = rawTenants
  } else if (rawTenants && typeof rawTenants === "object") {
    list = Object.values(rawTenants) as any
  }
  return list.filter(t => (t.active_streams || 0) > 0 || (t.net_tx || 0) > 0)
}

function openTenantMetricsDialog(node: EdgeNode) {
  activeTenantMetricsNode.value = node
  tenantMetricsDialogVisible.value = true
}

function openClusterTenantsDialog() {
  clusterTenantsDialogVisible.value = true
}

function calcTenantRatio(bytes: number, total: number | undefined): number {
  if (!total || total <= 0 || !bytes || bytes <= 0) return 0
  const ratio = (bytes / total) * 100
  return Number(Math.min(100, Math.max(0.1, ratio)).toFixed(1))
}

function aggregateTenantsFromNodes(nodesList: EdgeNode[]): EdgeNodeTenantMetric[] {
  const map = new Map<number, EdgeNodeTenantMetric>()

  for (const n of nodesList) {
    const rawTenants = n.metrics?.tenants
    let tenantList: any[] = []
    if (Array.isArray(rawTenants)) {
      tenantList = rawTenants
    } else if (rawTenants && typeof rawTenants === "object") {
      tenantList = Object.entries(rawTenants).map(([k, v]) => ({
        tenant_id: (v as any)?.tenant_id ?? (Number(k) || 0),
        ...(typeof v === "object" ? v : {}),
      }))
    }
    if (tenantList.length === 0) continue

    for (const t of tenantList) {
      if (!t || typeof t !== "object") continue
      const tid = Number(t.tenant_id ?? 0)
      if (isNaN(tid)) continue

      const activeStreams = Number(t.active_streams || 0)
      const netTx = Number(t.net_tx || 0)
      const totalBytes = Number(t.total_bytes || 0)
      const lastActive = t.last_active ? String(t.last_active) : ""
      const username = t.username || (tid === 0 ? "公共/访客" : `租户#${tid}`)

      const existing = map.get(tid)
      if (!existing) {
        map.set(tid, {
          tenant_id: tid,
          username,
          active_streams: activeStreams,
          net_tx: netTx,
          total_bytes: totalBytes,
          node_count: 1,
          last_active: lastActive,
          is_owner: Boolean(t.is_owner),
          role: t.role || (tid === 0 ? "guest" : "user"),
          masked: Boolean(t.masked),
        })
      } else {
        existing.active_streams = (existing.active_streams || 0) + activeStreams
        existing.net_tx = (existing.net_tx || 0) + netTx
        existing.total_bytes = (existing.total_bytes || 0) + totalBytes
        existing.node_count = (existing.node_count || 1) + 1
        if (lastActive && (!existing.last_active || lastActive > existing.last_active)) {
          existing.last_active = lastActive
        }
        if (t.is_owner) existing.is_owner = true
        if (t.username && !existing.username) existing.username = t.username
      }
    }
  }

  const list = Array.from(map.values())
  list.sort((a, b) => {
    const aActive = ((a.active_streams || 0) > 0 || (a.net_tx || 0) > 0) ? 1 : 0
    const bActive = ((b.active_streams || 0) > 0 || (b.net_tx || 0) > 0) ? 1 : 0
    if (aActive !== bActive) return bActive - aActive
    if ((b.net_tx || 0) !== (a.net_tx || 0)) return (b.net_tx || 0) - (a.net_tx || 0)
    return (b.total_bytes || 0) - (a.total_bytes || 0)
  })

  return list
}

function mergeTenantsLists(base: EdgeNodeTenantMetric[], update: EdgeNodeTenantMetric[]): EdgeNodeTenantMetric[] {
  const map = new Map<number, EdgeNodeTenantMetric>()
  for (const t of base || []) {
    if (!t) continue
    const tid = Number(t.tenant_id ?? 0)
    map.set(tid, { ...t })
  }
  for (const t of update || []) {
    if (!t) continue
    const tid = Number(t.tenant_id ?? 0)
    const existing = map.get(tid)
    if (!existing) {
      map.set(tid, { ...t })
    } else {
      map.set(tid, {
        tenant_id: tid,
        username: t.username || existing.username || (tid === 0 ? "公共/访客" : `租户#${tid}`),
        role: t.role || existing.role || "user",
        is_owner: t.is_owner ?? existing.is_owner,
        active_streams: t.active_streams ?? existing.active_streams ?? 0,
        net_tx: t.net_tx ?? existing.net_tx ?? 0,
        total_bytes: Math.max(Number(existing.total_bytes || 0), Number(t.total_bytes || 0)),
        last_active: (t.last_active && String(t.last_active) > String(existing.last_active || "")) ? t.last_active : existing.last_active,
        masked: t.masked ?? existing.masked,
        node_count: Math.max(Number(existing.node_count || 1), Number(t.node_count || 1)),
      })
    }
  }
  const result = Array.from(map.values())
  result.sort((a, b) => {
    const aActive = ((a.active_streams || 0) > 0 || (a.net_tx || 0) > 0) ? 1 : 0
    const bActive = ((b.active_streams || 0) > 0 || (b.net_tx || 0) > 0) ? 1 : 0
    if (aActive !== bActive) return bActive - aActive
    if ((b.net_tx || 0) !== (a.net_tx || 0)) return (b.net_tx || 0) - (a.net_tx || 0)
    return (b.total_bytes || 0) - (a.total_bytes || 0)
  })
  return result
}

function formatRelativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '未记录'
  try {
    const ts = new Date(isoStr).getTime()
    if (isNaN(ts)) return String(isoStr)
    const diff = (Date.now() - ts) / 1000
    if (diff < 10) return '刚刚'
    if (diff < 60) return `${Math.floor(diff)}秒前`
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    return `${Math.floor(diff / 86400)}天前`
  } catch {
    return String(isoStr)
  }
}
const nodes = ref<EdgeNode[]>([])
const summary = ref<EdgeNodeSummary>({
  total_nodes: 0,
  online_nodes: 0,
  deploying_nodes: 0,
  shared_pool_nodes: 0,
  active_streams: 0,
  total_tx_speed: 0,
  total_bytes_served: 0,
})

const clusterTenantsList = computed<EdgeNodeTenantMetric[]>(() => {
  const remoteTenants = Array.isArray(summary.value?.tenants) ? summary.value.tenants : []
  const localTenants = aggregateTenantsFromNodes(nodes.value)
  return mergeTenantsLists(localTenants, remoteTenants)
})

const totalClusterTenantBytes = computed(() => {
  return clusterTenantsList.value.reduce((acc, t) => acc + (t.total_bytes || 0), 0)
})

// 视图模式与交互状态
const viewMode = ref<'grid' | 'table'>((localStorage.getItem('mistrelay_edge_view_mode') as any) || 'grid')
function setViewMode(mode: 'grid' | 'table') {
  viewMode.value = mode
  localStorage.setItem('mistrelay_edge_view_mode', mode)
}
const showTopoHelp = ref(false)
const batchBenchmarking = ref(false)

const statusFilter = ref<'all' | 'online' | 'deploying' | 'offline' | 'shared'>('all')
const searchQuery = ref('')
const testingNodeId = ref<number | null>(null)

// 4 大核心 KPI 动态计算属性 (角色感知)
const kpiCards = computed(() => {
  if (authStore.isAdmin) {
    return [
      {
        key: 'nodes',
        label: '全网边缘节点 / 在线',
        value: `${summary.value.online_nodes} / ${summary.value.total_nodes}`,
        unit: '个在线',
        desc: `公共共享池: ${summary.value.shared_pool_nodes} 个`,
        icon: Connection,
        color: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
      },
      {
        key: 'streams',
        label: '全网活跃边缘推流',
        value: `${summary.value.active_streams}`,
        unit: '路',
        desc: '全站并发 Range 分片拉流中',
        icon: VideoPlay,
        color: 'linear-gradient(135deg, #38bdf8 0%, #0284c7 100%)',
      },
      {
        key: 'speed',
        label: '集群聚合出网速率',
        value: `${formatBytes(summary.value.total_tx_speed)}`,
        unit: '/s',
        desc: '边缘 VPS 直接承载推流',
        icon: Odometer,
        color: 'linear-gradient(135deg, #ff7597 0%, #ec4899 100%)',
      },
      {
        key: 'traffic',
        label: '已为主控卸载流量',
        value: `${formatBytes(summary.value.total_bytes_served)}`,
        unit: '',
        desc: '已节省 100% 对应出网带宽',
        icon: TrendCharts,
        color: 'linear-gradient(135deg, #a855f7 0%, #7c3aed 100%)',
      },
    ]
  } else {
    return [
      {
        key: 'nodes',
        label: '我的加速节点 / 在线',
        value: `${summary.value.online_nodes} / ${summary.value.total_nodes}`,
        unit: '个在线',
        desc: summary.value.online_nodes > 0 ? '专属加速已就绪生效' : '暂无在线加速节点',
        icon: Connection,
        color: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
      },
      {
        key: 'streams',
        label: '当前个人并发流播',
        value: `${summary.value.active_streams}`,
        unit: '路',
        desc: '实时视频直推客户端',
        icon: VideoPlay,
        color: 'linear-gradient(135deg, #38bdf8 0%, #0284c7 100%)',
      },
      {
        key: 'speed',
        label: '实时个人出网速率',
        value: `${formatBytes(summary.value.total_tx_speed)}`,
        unit: '/s',
        desc: '您的 VPS 直连 TG DC',
        icon: Odometer,
        color: 'linear-gradient(135deg, #ff7597 0%, #ec4899 100%)',
      },
      {
        key: 'traffic',
        label: '已为网盘加速流量',
        value: `${formatBytes(summary.value.total_bytes_served)}`,
        unit: '',
        desc: '302 直链极速播放与下载',
        icon: TrendCharts,
        color: 'linear-gradient(135deg, #a855f7 0%, #7c3aed 100%)',
      },
    ]
  }
})

// SSH 纳管弹窗状态
const sshDialogVisible = ref(false)
const isEditMode = ref(false)
const submitting = ref(false)
const sshForm = ref({
  id: 0,
  node_name: '',
  ip: '',
  port: 8090,
  ssh_host: '',
  ssh_port: 22,
  ssh_user: 'root',
  ssh_password: '',
  domain: '',
  use_ssl: true,
  allow_shared_pool: false,
  clear_password_on_success: true,
  target_dc_id: null as number | null,
  allow_bot_pool: true,
})

// 一键脚本弹窗状态
const tokenDialogVisible = ref(false)
const generatingToken = ref(false)
const generatedToken = ref('')
const generatedCommand = ref('')
const pairedNode = ref<EdgeNode | null>(null)

// 全能测速与体检弹窗状态
const benchmarkModalVisible = ref(false)
const activeBenchmarkNode = ref<EdgeNode | null>(null)
const activeBenchmarkTab = ref('relay_stream')
const benchmarking = ref(false)
const upgradingWorker = ref(false)
const speedSampleMb = ref(50)
const testingSingleDc = ref(false)
const testingSingleSpeed = ref(false)
const testingSingleRelay = ref(false)
const testingSingleDiag = ref(false)
const testingSingleBandwidth = ref(false)

function getPerBotCapacity(node: EdgeNode | null): number {
  if (!node) return 2.0
  const rtt = node.benchmark_data?.fastest_dc?.avg_rtt_ms || 0
  if (rtt <= 0) return 2.0
  if (rtt <= 50) return 2.0
  if (rtt <= 110) return 1.2
  return 0.8
}

function getRecommendedBots(node: EdgeNode | null): number {
  if (!node) return 4
  const bw = node.benchmark_data?.bandwidth?.effective_bw_mb_s || node.benchmark_data?.bandwidth?.down_speed_mb_s || node.benchmark_data?.link?.down_speed_mb_s || 0
  if (bw <= 0) return 4
  const perBot = getPerBotCapacity(node)
  return Math.max(2, Math.min(Math.ceil(bw / perBot), 100))
}

function applyRecommendedBots() {
  if (!activeAssignNode.value) return
  assignBotForm.value.target_bot_count = getRecommendedBots(activeAssignNode.value)
  ElMessage.info(`已设定推荐数量: ${assignBotForm.value.target_bot_count} 个 Bot`)
}

function applyMaxBots() {
  assignBotForm.value.target_bot_count = Math.min(100, Math.max(24, Math.ceil((activeAssignNode.value?.benchmark_data?.bandwidth?.effective_bw_mb_s || 24) / getPerBotCapacity(activeAssignNode.value))))
  ElMessage.success(`已设定满载 ${assignBotForm.value.target_bot_count} 个 Bot (极限满速)`)
}

async function handleRunBandwidthOnly() {
  if (!activeBenchmarkNode.value) return
  const nodeId = activeBenchmarkNode.value.id
  testingSingleBandwidth.value = true
  try {
    const res = await runEdgeBandwidthBenchmark(nodeId)
    if (res.success) {
      if (!activeBenchmarkNode.value.benchmark_data) {
        activeBenchmarkNode.value.benchmark_data = {}
      }
      activeBenchmarkNode.value.benchmark_data.bandwidth = res
      ElMessage.success(`VPS 物理宽带测速完成：${res.down_speed_mb_s} MB/s (${res.down_speed_mbps} Mbps)`)
      const idx = nodes.value.findIndex(n => n.id === nodeId)
      if (idx !== -1) {
        nodes.value[idx].benchmark_data = activeBenchmarkNode.value.benchmark_data
      }
    } else {
      ElMessage.error(res.error || '宽带测速失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '测速异常')
  } finally {
    testingSingleBandwidth.value = false
  }
}

const defaultDcs: EdgeDcResult[] = [
  { dc_id: 1, name: "DC1 美西 (Miami)", region: "美西/北美", ip: "149.154.175.53", port: 443, min_rtt_ms: 0, avg_rtt_ms: 0, max_rtt_ms: 0, packet_loss_pct: 0, rating: "optimal", rating_label: "待测试", reachable: false },
  { dc_id: 2, name: "DC2 欧洲 (Amsterdam)", region: "欧洲/阿姆斯特丹", ip: "149.154.167.51", port: 443, min_rtt_ms: 0, avg_rtt_ms: 0, max_rtt_ms: 0, packet_loss_pct: 0, rating: "optimal", rating_label: "待测试", reachable: false },
  { dc_id: 3, name: "DC3 美东 (Miami)", region: "美东/迈阿密", ip: "149.154.175.100", port: 443, min_rtt_ms: 0, avg_rtt_ms: 0, max_rtt_ms: 0, packet_loss_pct: 0, rating: "optimal", rating_label: "待测试", reachable: false },
  { dc_id: 4, name: "DC4 欧洲 (Amsterdam)", region: "欧洲/荷兰", ip: "149.154.167.91", port: 443, min_rtt_ms: 0, avg_rtt_ms: 0, max_rtt_ms: 0, packet_loss_pct: 0, rating: "optimal", rating_label: "待测试", reachable: false },
  { dc_id: 5, name: "DC5 亚太 (Singapore)", region: "亚太/新加坡", ip: "91.108.56.165", port: 443, min_rtt_ms: 0, avg_rtt_ms: 0, max_rtt_ms: 0, packet_loss_pct: 0, rating: "optimal", rating_label: "待测试", reachable: false },
]
let tokenPollTimer: ReturnType<typeof setInterval> | null = null
const tokenForm = ref({
  node_name: '我的边缘分流节点',
  port: 8090,
  domain: '',
  use_ssl: true,
  allow_shared_pool: false,
  target_dc_id: null as number | null,
  allow_bot_pool: true,
})

// 实时部署终端弹窗
const logModalVisible = ref(false)
const activeLogNode = ref<EdgeNode | null>(null)
// 节点 Bot 调度与分配工作台状态
const assignBotDialogVisible = ref(false)
const assigningBot = ref(false)
const activeAssignNode = ref<EdgeNode | null>(null)
const assignBotForm = ref({
  mode: 'auto' as 'auto' | 'manual',
  selected_token: '',
  target_dc_id: 0,
  target_bot_count: 4,
  allow_bot_pool: true,
  trigger_ota: true,
})
const botsPoolList = ref<ClusterBotInfo[]>([])
const botsPoolLoading = ref(false)
const botsSearchQuery = ref('')
const botsDcFilter = ref<number | null>(null)

const dcTabs = [
  { id: null, label: '全部 DC' },
  { id: 1, label: 'DC1 美西/北美' },
  { id: 5, label: 'DC5 亚太/新加坡' },
  { id: 2, label: 'DC2 欧洲' },
  { id: 3, label: 'DC3 美东' },
  { id: 4, label: 'DC4 荷兰' },
]

const filteredBotsPool = computed(() => {
  let list = botsPoolList.value
  if (botsDcFilter.value !== null) {
    list = list.filter(b => b.dc_id === botsDcFilter.value)
  }
  if (botsSearchQuery.value.trim()) {
    const q = botsSearchQuery.value.trim().toLowerCase().replace(/^@/, '')
    list = list.filter(b =>
      b.username.toLowerCase().includes(q) ||
      b.prefix.toLowerCase().includes(q) ||
      b.token.toLowerCase().includes(q)
    )
  }
  return list
})

function getDcCount(dcId: number | null): number {
  if (dcId === null) return botsPoolList.value.length
  return botsPoolList.value.filter(b => b.dc_id === dcId).length
}

function setAssignMode(mode: 'auto' | 'manual') {
  assignBotForm.value.mode = mode
}

function setBotsDcFilter(dcId: number | null) {
  botsDcFilter.value = dcId
}

function selectBotItem(bot: ClusterBotInfo) {
  assignBotForm.value.selected_token = bot.token
}

async function fetchBotsPool() {
  botsPoolLoading.value = true
  try {
    const res = await getEdgeBotsPool()
    if (res.success && Array.isArray(res.bots)) {
      botsPoolList.value = res.bots
    }
  } catch (e) {
    console.error('获取 Bot 资产池失败', e)
  } finally {
    botsPoolLoading.value = false
  }
}

async function openAssignBotDialog(node: EdgeNode) {
  activeAssignNode.value = node
  const bwDown = node.benchmark_data?.bandwidth?.down_speed_mb_s || node.benchmark_data?.link?.down_speed_mb_s || 0
  const recommended = bwDown > 0 ? Math.max(2, Math.min(Math.ceil(bwDown / 2.0), 100)) : 4
  assignBotForm.value = {
    mode: node.assigned_bot_token ? 'manual' : 'auto',
    selected_token: node.assigned_bot_token || '',
    target_dc_id: node.target_dc_id || 0,
    target_bot_count: node.target_bot_count || recommended,
    allow_bot_pool: node.allow_bot_pool !== undefined ? Boolean(node.allow_bot_pool) : true,
    trigger_ota: node.status === 'online',
  }
  assignBotDialogVisible.value = true
  await fetchBotsPool()
}

async function handleSaveAssignBot() {
  if (!activeAssignNode.value) return
  if (assignBotForm.value.mode === 'manual' && !assignBotForm.value.selected_token) {
    ElMessage.warning('请先在下方列表中选择一个特定 Bot')
    return
  }

  assigningBot.value = true
  try {
    const payload = {
      mode: assignBotForm.value.mode,
      assigned_bot_token: assignBotForm.value.mode === 'manual' ? assignBotForm.value.selected_token : '',
      target_dc_id: assignBotForm.value.mode === 'auto' ? (assignBotForm.value.target_dc_id || undefined) : undefined,
      bot_count: assignBotForm.value.target_bot_count,
      allow_bot_pool: assignBotForm.value.allow_bot_pool,
      trigger_ota: assignBotForm.value.trigger_ota,
    }
    const res = await reassignEdgeNodeBot(activeAssignNode.value.id, payload)
    if (res.success) {
      ElMessage.success(res.message || 'Bot 分配已生效')
      if (res.node) {
        const idx = nodes.value.findIndex(n => n.id === res.node!.id)
        if (idx !== -1) {
          nodes.value[idx] = { ...nodes.value[idx], ...res.node }
        }
        if (activeBenchmarkNode.value && activeBenchmarkNode.value.id === res.node.id) {
          activeBenchmarkNode.value = { ...activeBenchmarkNode.value, ...res.node }
        }
      }
      assignBotDialogVisible.value = false
    } else {
      ElMessage.error(res.error || '分配失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '分配请求失败')
  } finally {
    assigningBot.value = false
  }
}

const activeDeployLog = ref('')
const activeLogStatus = ref('offline')
const terminalPreRef = ref<HTMLElement | null>(null)
let logPollTimer: ReturnType<typeof setInterval> | null = null

const statusTabs = computed(() => {
  const tabs: Array<{ label: string; value: 'all' | 'online' | 'deploying' | 'offline' | 'shared'; count: number }> = [
    { label: '全部节点', value: 'all', count: nodes.value.length },
    { label: '在线分流', value: 'online', count: nodes.value.filter(n => n.status === 'online').length },
    { label: '部署中', value: 'deploying', count: nodes.value.filter(n => n.status === 'deploying').length },
    { label: '离线待命', value: 'offline', count: nodes.value.filter(n => n.status === 'offline' || n.status === 'error').length },
  ]
  if (authStore.isAdmin) {
    tabs.splice(2, 0, {
      label: '公共共享池',
      value: 'shared',
      count: nodes.value.filter(n => n.allow_shared_pool).length,
    })
  }
  return tabs
})

const filteredNodes = computed(() => {
  return nodes.value
    .filter(node => {
      if (statusFilter.value === 'online' && node.status !== 'online') return false
      if (statusFilter.value === 'deploying' && node.status !== 'deploying') return false
      if (statusFilter.value === 'offline' && node.status !== 'offline' && node.status !== 'error') return false
      if (statusFilter.value === 'shared' && !node.allow_shared_pool) return false

      const q = searchQuery.value.trim().toLowerCase()
      if (!q) return true
      return (
        (node.node_name || '').toLowerCase().includes(q) ||
        (node.ip || '').toLowerCase().includes(q) ||
        (node.domain || '').toLowerCase().includes(q) ||
        (node.tenant_username || '').toLowerCase().includes(q)
      )
    })
    .sort((a, b) => b.id - a.id)
})

function formatStatusText(status: string): string {
  const map: Record<string, string> = {
    online: '在线分流中',
    deploying: 'SSH 部署中...',
    offline: '离线待命',
    error: '部署/连接异常',
  }
  return map[status] || status
}

function getLogStatusTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'online') return 'success'
  if (status === 'deploying') return 'warning'
  if (status === 'error') return 'danger'
  return 'info'
}

function getAutoEdgeDomain(ip: string): string {
  if (!ip) return ''
  const trimmed = ip.trim()
  if (/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/.test(trimmed)) {
    return `edge.${trimmed.replace(/\./g, '-')}.sslip.io`
  }
  return ''
}

function formatNodeEndpoint(node: EdgeNode): string {
  const domain = node.domain || (node.ip ? getAutoEdgeDomain(node.ip) : '')
  const useSsl = node.use_ssl || Boolean(domain)
  const scheme = useSsl ? 'https' : 'http'
  if (domain) {
    return `${scheme}://${domain}${[80, 443].includes(node.port) ? '' : ':' + node.port}`
  }
  if (node.ip) {
    return `http://${node.ip}:${node.port || 8090}`
  }
  return '待配对分配'
}

function getProgressColor(pct: number): string {
  if (pct >= 85) return '#ef4444'
  if (pct >= 65) return '#f59e0b'
  return '#10b981'
}

function recalculateSummaryFromNodes() {
  const list = nodes.value
  const localTenants = aggregateTenantsFromNodes(list)
  const existingTenants = summary.value?.tenants || []
  const finalTenants = mergeTenantsLists(existingTenants, localTenants)

  summary.value = {
    total_nodes: list.length,
    online_nodes: list.filter(n => n.status === "online").length,
    deploying_nodes: list.filter(n => n.status === "deploying").length,
    shared_pool_nodes: list.filter(n => n.status === "online" && n.allow_shared_pool).length,
    active_streams: list.filter(n => n.status === "online").reduce((acc, n) => acc + (Number(n.metrics?.active_streams) || 0), 0),
    total_tx_speed: list.filter(n => n.status === "online").reduce((acc, n) => acc + (Number(n.metrics?.net_tx) || 0), 0),
    total_bytes_served: list.reduce((acc, n) => acc + (Number(n.metrics?.total_bytes_served) || 0), 0),
    tenants: finalTenants,
  }
}

function applyNewSummary(newSummary?: EdgeNodeSummary | null, forNode?: EdgeNode | null) {
  if (!newSummary) {
    recalculateSummaryFromNodes()
    return
  }

  // 管理员端防御：如果收到租户私有节点的局部 summary，杜绝覆盖全集群全局 summary
  if (authStore.isAdmin && newSummary.total_nodes < nodes.value.length && (forNode?.tenant_id || newSummary.total_nodes > 0)) {
    recalculateSummaryFromNodes()
    return
  }

  const incomingTenants = Array.isArray(newSummary.tenants) ? newSummary.tenants : []
  const localTenants = aggregateTenantsFromNodes(nodes.value)
  const existingTenants = summary.value?.tenants || []
  const merged = mergeTenantsLists(existingTenants, mergeTenantsLists(localTenants, incomingTenants))

  summary.value = {
    ...newSummary,
    tenants: merged,
  }
}

async function fetchNodes(showLoading = false) {
  if (showLoading && nodes.value.length === 0) {
    loading.value = true
  }
  try {
    const res = await getEdgeNodes()
    if (res.success && Array.isArray(res.nodes)) {
      if (nodes.value.length === 0) {
        nodes.value = [...res.nodes]
      } else {
        for (const nn of res.nodes) {
          const idx = nodes.value.findIndex(n => n.id === nn.id)
          if (idx !== -1) {
            Object.assign(nodes.value[idx], nn)
          } else {
            nodes.value.push(nn)
          }
        }
        const validIds = new Set(res.nodes.map(n => n.id))
        const hasRemoved = nodes.value.some(n => !validIds.has(n.id))
        if (hasRemoved) {
          nodes.value = nodes.value.filter(n => validIds.has(n.id))
        }
      }
      if (res.summary) {
        applyNewSummary(res.summary)
      } else {
        recalculateSummaryFromNodes()
      }
    }
  } catch (err: any) {
    if (showLoading) {
      ElMessage.error(err?.message || '加载边缘节点列表失败')
    }
  } finally {
    loading.value = false
  }
}

async function handleManualRefresh() {
  manualRefreshing.value = true
  try {
    await fetchNodes(false)
    ElMessage.success('已刷新边缘节点最新状态')
  } finally {
    manualRefreshing.value = false
  }
}

function initWebSocket() {
  if (!wsClient.isConnected()) {
    wsClient.connect()
  } else {
    wsClient.send({ type: 'get_edge_nodes' })
  }
  wsConnected.value = wsClient.isConnected()

  // 监听 pong
  wsUnsubscribers.push(
    wsClient.on('pong', () => {
      wsConnected.value = true
    })
  )

  // 1. 单节点实时推流更新 (指标、心跳、状态变更等)
  wsUnsubscribers.push(
    wsClient.on('edge_node_update', (msg: WSMessage) => {
      wsConnected.value = true
      const { node, summary: newSummary } = msg.data || {}
      if (!node || !node.id) return

      const idx = nodes.value.findIndex(n => n.id === node.id)
      if (idx !== -1) {
        Object.assign(nodes.value[idx], node)
      } else {
        nodes.value.push(node)
      }

      applyNewSummary(newSummary, node)

      // 同步更新打开的测速或日志弹窗对象
      if (activeBenchmarkNode.value && activeBenchmarkNode.value.id === node.id) {
        Object.assign(activeBenchmarkNode.value, node)
      }
      if (activeLogNode.value && activeLogNode.value.id === node.id) {
        Object.assign(activeLogNode.value, node)
        activeLogStatus.value = node.status
      }
      if (activeTenantMetricsNode.value && activeTenantMetricsNode.value.id === node.id) {
        Object.assign(activeTenantMetricsNode.value, node)
      }
    })
  )

  // 2. 全量节点实时推流更新 (增量合并，无缝更新，不抖动)
  wsUnsubscribers.push(
    wsClient.on('edge_nodes_update', (msg: WSMessage) => {
      wsConnected.value = true
      const { nodes: newNodes, summary: newSummary } = msg.data || {}
      if (Array.isArray(newNodes)) {
        if (nodes.value.length === 0) {
          nodes.value = [...newNodes]
        } else {
          for (const nn of newNodes) {
            const idx = nodes.value.findIndex(n => n.id === nn.id)
            if (idx !== -1) {
              Object.assign(nodes.value[idx], nn)
            } else {
              nodes.value.push(nn)
            }
          }

          // 管理员端严禁在此处清除节点（节点删除由 edge_node_deleted 显式事件驱动，防止局部广播冲刷掉全集群节点）
          if (!authStore.isAdmin && newNodes.length > 0) {
            const validIds = new Set(newNodes.map(n => n.id))
            const hasRemoved = nodes.value.some(n => !validIds.has(n.id))
            if (hasRemoved) {
              nodes.value = nodes.value.filter(n => validIds.has(n.id))
            }
          }
        }
      }

      applyNewSummary(newSummary)

      if (activeTenantMetricsNode.value) {
        const found = nodes.value.find(n => n.id === activeTenantMetricsNode.value?.id)
        if (found) {
          activeTenantMetricsNode.value = found
        }
      }
    })
  )

  // 3. 节点解绑删除实时更新
  wsUnsubscribers.push(
    wsClient.on('edge_node_deleted', (msg: WSMessage) => {
      const { node_id, summary: newSummary } = msg.data || {}
      if (node_id) {
        nodes.value = nodes.value.filter(n => n.id !== node_id)
        if (newSummary) {
          applyNewSummary(newSummary)
        } else {
          recalculateSummaryFromNodes()
        }
      }
    })
  )

  // 4. SSH 部署终端实时推流日志
  wsUnsubscribers.push(
    wsClient.on('edge_deploy_log', (msg: WSMessage) => {
      const { node_id, line, deploy_log, status } = msg.data || {}
      if (activeLogNode.value && activeLogNode.value.id === node_id) {
        if (deploy_log !== undefined && deploy_log !== null) {
          activeDeployLog.value = deploy_log
        } else if (line) {
          activeDeployLog.value = (activeDeployLog.value || '') + line + "\n"
        }
        if (status) {
          activeLogStatus.value = status
        }
        nextTick(() => {
          if (terminalPreRef.value) {
            terminalPreRef.value.scrollTop = terminalPreRef.value.scrollHeight
          }
        })
      }
    })
  )

  // 5. 免密一键脚本配对成功实时推送
  wsUnsubscribers.push(
    wsClient.on('edge_token_used', (msg: WSMessage) => {
      const { token, node } = msg.data || {}
      if (generatedToken.value === token && node) {
        pairedNode.value = node
        stopTokenPolling()
        ElMessage.success(`边缘节点「${node.node_name}」已成功回连上线！`)
      }
    })
  )
}

// 复制文字工具函数
async function copyText(text: string, successMsg = '已复制到剪贴板') {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(successMsg)
  } catch {
    ElMessage.warning('请手动选中文本复制')
  }
}

// 管理员：一键全网测速
async function handleBatchBenchmark() {
  const onlineList = nodes.value.filter(n => n.status === 'online')
  if (onlineList.length === 0) {
    ElMessage.warning('当前暂无在线的边缘节点可测速')
    return
  }
  try {
    await ElMessageBox.confirm(
      `即将对全网 ${onlineList.length} 个在线边缘节点执行 Telegram 5 大 DC 延迟、MTProto 直连拉流与系统硬件深度体检，是否继续？`,
      '全网节点一键全能测速',
      { type: 'info', confirmButtonText: '开始全网测速', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  batchBenchmarking.value = true
  ElMessage.info(`已启动全网 ${onlineList.length} 个节点测速任务，请稍候...`)
  try {
    for (const node of onlineList) {
      try {
        const res = await runEdgeFullBenchmark(node.id, { sample_size_mb: 10 })
        if (res.success && res.benchmark_data) {
          node.benchmark_data = res.benchmark_data
        }
      } catch (e) {
        console.error(`节点 #${node.id} 测速失败:`, e)
      }
    }
    ElMessage.success('全网节点测速完成，最新性能指标已入库！')
  } finally {
    batchBenchmarking.value = false
  }
}

function isNodeDcMatched(node: EdgeNode | null | undefined): boolean {
  if (!node) return true
  const diagTg = node.benchmark_data?.diagnostics?.telegram
  if (diagTg && diagTg.dc_affinity_matched !== undefined) {
    return Boolean(diagTg.dc_affinity_matched)
  }
  const fastest = node.benchmark_data?.fastest_dc?.id
  const target = node.target_dc_id
  if (!target || !fastest) return true
  if (target === 1 && (fastest === 1 || fastest === 3)) return true
  if (target === 4 && (fastest === 2 || fastest === 4)) return true
  return target === fastest
}

async function handleReassignBot(node: EdgeNode, targetDcId?: number | null) {
  try {
    const res = await reassignEdgeNodeBot(node.id, {
      target_dc_id: targetDcId !== undefined ? targetDcId : node.target_dc_id,
      trigger_ota: node.status === 'online',
    })
    if (res.success) {
      ElMessage.success(res.message || '已成功重新分配原生 Bot 并热重载')
      if (res.node) {
        const idx = nodes.value.findIndex(n => n.id === res.node!.id)
        if (idx !== -1) {
          Object.assign(nodes.value[idx], res.node)
        }
        if (activeBenchmarkNode.value && activeBenchmarkNode.value.id === node.id) {
          Object.assign(activeBenchmarkNode.value, res.node)
        }
      }
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '重新分配 Bot 失败')
  }
}

// 下拉菜单操作调度
function handleDropdownCommand(cmd: string, node: EdgeNode) {
  if (cmd === 'edit') {
    openEditDialog(node)
  } else if (cmd === 'assign_bot' || cmd === 'reassign_bot') {
    openAssignBotDialog(node)
  } else if (cmd === 'log') {
    openLogModal(node)
  } else if (cmd === 'redeploy') {
    handleRetriggerDeployFromNode(node)
  } else if (cmd === 'wipe_pwd') {
    handleClearPassword(node)
  } else if (cmd === 'delete') {
    handleDeleteNode(node)
  }
}

async function handleRetriggerDeployFromNode(node: EdgeNode) {
  try {
    const res = await triggerEdgeNodeDeploy(node.id)
    if (res.success) {
      ElMessage.success('已重新启动 SSH 自动化部署')
      openLogModal(node)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '无法启动部署，请先配置 SSH 密码')
  }
}

function openCreateSshDialog() {
  isEditMode.value = false
  sshForm.value = {
    id: 0,
    node_name: '',
    ip: '',
    port: 8090,
    ssh_host: '',
    ssh_port: 22,
    ssh_user: 'root',
    ssh_password: '',
    domain: '',
    use_ssl: true,
    allow_shared_pool: false,
    clear_password_on_success: true,
    target_dc_id: null,
    allow_bot_pool: true,
  }
  sshDialogVisible.value = true
}

function openEditDialog(node: EdgeNode) {
  isEditMode.value = true
  sshForm.value = {
    id: node.id,
    node_name: node.node_name,
    ip: node.ip || '',
    port: node.port || 8090,
    ssh_host: node.ssh_host || node.ip || '',
    ssh_port: node.ssh_port || 22,
    ssh_user: node.ssh_user || 'root',
    ssh_password: '',
    domain: node.domain || '',
    use_ssl: Boolean(node.use_ssl),
    allow_shared_pool: Boolean(node.allow_shared_pool),
    clear_password_on_success: false,
    target_dc_id: node.target_dc_id ?? null,
    allow_bot_pool: node.allow_bot_pool !== false,
  }
  sshDialogVisible.value = true
}

async function handleSaveNode() {
  if (!sshForm.value.node_name.trim()) {
    ElMessage.warning('请输入节点名称')
    return
  }
  submitting.value = true
  try {
    const payload: any = {
      node_name: sshForm.value.node_name.trim(),
      ip: sshForm.value.ip.trim(),
      port: sshForm.value.port,
      ssh_host: sshForm.value.ip.trim(),
      ssh_port: sshForm.value.ssh_port,
      ssh_user: sshForm.value.ssh_user.trim() || 'root',
      domain: sshForm.value.domain.trim(),
      use_ssl: sshForm.value.use_ssl,
      allow_shared_pool: sshForm.value.allow_shared_pool,
      target_dc_id: sshForm.value.target_dc_id,
      allow_bot_pool: sshForm.value.allow_bot_pool,
    }
    if (sshForm.value.ssh_password) {
      payload.ssh_password = sshForm.value.ssh_password
    }
    const res = await updateEdgeNode(sshForm.value.id, payload)
    if (res.success) {
      ElMessage.success('节点配置已更新')
      sshDialogVisible.value = false
      if (res.node) {
        const idx = nodes.value.findIndex(n => n.id === res.node!.id)
        if (idx !== -1) {
          Object.assign(nodes.value[idx], res.node)
        }
      }
    } else {
      ElMessage.error(res.error || '保存失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function handleSaveAndDeploy() {
  if (!sshForm.value.node_name.trim()) {
    ElMessage.warning('请输入节点名称')
    return
  }
  if (!sshForm.value.ip.trim()) {
    ElMessage.warning('请输入 VPS 公网 IP 地址')
    return
  }
  if (!isEditMode.value && !sshForm.value.ssh_password) {
    ElMessage.warning('请输入远程 VPS 的 SSH 密码以执行自动部署')
    return
  }

  submitting.value = true
  try {
    if (isEditMode.value) {
      const updatePayload: any = {
        node_name: sshForm.value.node_name.trim(),
        ip: sshForm.value.ip.trim(),
        port: Number(sshForm.value.port) || 8090,
        ssh_host: sshForm.value.ip.trim(),
        ssh_port: Number(sshForm.value.ssh_port) || 22,
        ssh_user: sshForm.value.ssh_user.trim() || 'root',
        domain: sshForm.value.domain.trim(),
        use_ssl: sshForm.value.use_ssl,
        allow_shared_pool: sshForm.value.allow_shared_pool,
        target_dc_id: sshForm.value.target_dc_id,
        allow_bot_pool: sshForm.value.allow_bot_pool,
      }
      if (sshForm.value.ssh_password) {
        updatePayload.ssh_password = sshForm.value.ssh_password
      }
      await updateEdgeNode(sshForm.value.id, updatePayload)

      const res = await triggerEdgeNodeDeploy(sshForm.value.id, {
        ssh_host: sshForm.value.ip.trim(),
        ssh_port: sshForm.value.ssh_port,
        ssh_user: sshForm.value.ssh_user.trim() || 'root',
        ssh_password: sshForm.value.ssh_password || undefined,
        clear_password_on_success: sshForm.value.clear_password_on_success,
      })
      if (res.success) {
        ElMessage.success('SSH 自动部署任务已启动')
        sshDialogVisible.value = false
        if (res.node) {
          const idx = nodes.value.findIndex(n => n.id === res.node!.id)
          if (idx !== -1) {
            Object.assign(nodes.value[idx], res.node)
          }
          openLogModal(res.node)
        }
      } else {
        ElMessage.error(res.error || '启动部署失败')
      }
    } else {
      const res = await createEdgeNode({
        node_name: sshForm.value.node_name.trim(),
        ip: sshForm.value.ip.trim(),
        port: sshForm.value.port,
        ssh_host: sshForm.value.ip.trim(),
        ssh_port: sshForm.value.ssh_port,
        ssh_user: sshForm.value.ssh_user.trim() || 'root',
        ssh_password: sshForm.value.ssh_password,
        domain: sshForm.value.domain.trim(),
        use_ssl: sshForm.value.use_ssl,
        allow_shared_pool: sshForm.value.allow_shared_pool,
        target_dc_id: sshForm.value.target_dc_id,
        allow_bot_pool: sshForm.value.allow_bot_pool,
        auto_deploy: true,
        clear_password_on_success: sshForm.value.clear_password_on_success,
      })
      if (res.success && res.node) {
        ElMessage.success('节点已创建并启动 SSH 自动纳管流水线')
        sshDialogVisible.value = false
        nodes.value.unshift(res.node)
        recalculateSummaryFromNodes()
        openLogModal(res.node)
      } else {
        ElMessage.error(res.error || '创建失败')
      }
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleToggleSharedPool(node: EdgeNode, val: boolean) {
  node.allow_shared_pool = val
  recalculateSummaryFromNodes()
  try {
    const res = await updateEdgeNode(node.id, { allow_shared_pool: val })
    if (res.success) {
      ElMessage.success(val ? '已开启公共池共享分流' : '已切换为仅专属自用模式')
    }
  } catch (err: any) {
    node.allow_shared_pool = !val
    recalculateSummaryFromNodes()
    ElMessage.error(err?.response?.data?.error || '更新策略失败')
  }
}

async function handleClearPassword(node: EdgeNode) {
  try {
    await ElMessageBox.confirm(
      `确定要从主控数据库中擦除节点「${node.node_name}」保存的加密 SSH 密码吗？擦除后不影响已上线节点的正常运行。`,
      '零信任密码擦除确认',
      { type: 'warning', confirmButtonText: '确认擦除', cancelButtonText: '取消' }
    )
    const res = await clearEdgeNodePassword(node.id)
    if (res.success) {
      node.has_ssh_password = false
      ElMessage.success('已安全擦除保存的 SSH 密码')
    }
  } catch {
    // cancelled
  }
}

async function handleTestNode(node: EdgeNode) {
  testingNodeId.value = node.id
  try {
    const res = await testEdgeNodeHealth(node.id)
    if (res.success && res.result?.online) {
      node.status = 'online'
      ElMessage.success(`节点 #${node.id} 在线响应正常！实测延迟: ${res.result.latency_ms} ms`)
    } else {
      ElMessage.warning(`节点探测未就绪: ${res.result?.error || '连接超时'}`)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '探测请求失败')
  } finally {
    testingNodeId.value = null
  }
}

function openBenchmarkModal(node: EdgeNode) {
  activeBenchmarkNode.value = node
  activeBenchmarkTab.value = 'relay_stream'
  benchmarkModalVisible.value = true
}

async function handleRunFullBenchmark() {
  if (!activeBenchmarkNode.value) return
  const nodeId = activeBenchmarkNode.value.id
  benchmarking.value = true
  try {
    const res = await runEdgeFullBenchmark(nodeId, { sample_size_mb: speedSampleMb.value })
    if (res.success && res.benchmark_data) {
      if (activeBenchmarkNode.value) {
        activeBenchmarkNode.value.benchmark_data = res.benchmark_data
        activeBenchmarkNode.value.status = 'online'
      }
      const idx = nodes.value.findIndex(n => n.id === nodeId)
      if (idx !== -1) {
        nodes.value[idx].benchmark_data = res.benchmark_data
        nodes.value[idx].status = 'online'
      }
      ElMessage.success('全能综合体检与测速圆满完成，测试数据已自动持久化入库！')
    } else {
      ElMessage.error(res.error || '综合测速执行失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '综合测速异常')
  } finally {
    benchmarking.value = false
  }
}

async function handleRunDcsOnly() {
  if (!activeBenchmarkNode.value) return
  const nodeId = activeBenchmarkNode.value.id
  testingSingleDc.value = true
  try {
    const res = await runEdgeDcsBenchmark(nodeId)
    if (res.success && res.dcs) {
      if (!activeBenchmarkNode.value.benchmark_data) {
        activeBenchmarkNode.value.benchmark_data = {}
      }
      activeBenchmarkNode.value.benchmark_data.dcs = res.dcs
      activeBenchmarkNode.value.benchmark_data.fastest_dc = res.fastest_dc
      if (res.home_dc) activeBenchmarkNode.value.benchmark_data.home_dc = res.home_dc
      ElMessage.success(`Telegram 5 大 DC 延迟测速已更新！最优: ${res.fastest_dc?.name || '未知'}`)
      const idx = nodes.value.findIndex(n => n.id === nodeId)
      if (idx !== -1) {
        nodes.value[idx].benchmark_data = activeBenchmarkNode.value.benchmark_data
      }
    } else {
      ElMessage.error(res.error || 'DC 延迟测速失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '测速异常')
  } finally {
    testingSingleDc.value = false
  }
}

async function handleRunRelayOnly() {
  if (!activeBenchmarkNode.value) return
  const nodeId = activeBenchmarkNode.value.id
  testingSingleRelay.value = true
  try {
    const res = await runEdgeRelayStreamBenchmark(nodeId, { sample_size_mb: speedSampleMb.value })
    if (res.success) {
      if (!activeBenchmarkNode.value.benchmark_data) {
        activeBenchmarkNode.value.benchmark_data = {}
      }
      activeBenchmarkNode.value.benchmark_data.speed = res
      ElMessage.success(`全双工中继流播压测完成：体感 ${res.relay_speed_mb_s || res.speed_mb_s} MB/s (${res.bottleneck_diagnosis || res.evaluation || '正常'})`)
      const idx = nodes.value.findIndex(n => n.id === nodeId)
      if (idx !== -1) {
        nodes.value[idx].benchmark_data = activeBenchmarkNode.value.benchmark_data
      }
    } else {
      ElMessage.error(res.error || '中继流播压测失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '压测异常')
  } finally {
    testingSingleRelay.value = false
  }
}

async function handleRunSpeedOnly() {
  if (!activeBenchmarkNode.value) return
  const nodeId = activeBenchmarkNode.value.id
  testingSingleSpeed.value = true
  try {
    const res = await runEdgeTgSpeedBenchmark(nodeId, { sample_size_mb: speedSampleMb.value })
    if (res.success) {
      if (!activeBenchmarkNode.value.benchmark_data) {
        activeBenchmarkNode.value.benchmark_data = {}
      }
      activeBenchmarkNode.value.benchmark_data.speed = res
      ElMessage.success(`Telegram 拉流测速完成: ${res.speed_mb_s} MB/s (${res.evaluation})`)
      const idx = nodes.value.findIndex(n => n.id === nodeId)
      if (idx !== -1) {
        nodes.value[idx].benchmark_data = activeBenchmarkNode.value.benchmark_data
      }
    } else {
      ElMessage.error(res.error || '拉流测速失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '测速异常')
  } finally {
    testingSingleSpeed.value = false
  }
}

async function handleRunDiagOnly() {
  if (!activeBenchmarkNode.value) return
  const nodeId = activeBenchmarkNode.value.id
  testingSingleDiag.value = true
  try {
    const res = await runEdgeDiagnostics(nodeId)
    if (res.success) {
      if (!activeBenchmarkNode.value.benchmark_data) {
        activeBenchmarkNode.value.benchmark_data = {}
      }
      activeBenchmarkNode.value.benchmark_data.diagnostics = res
      activeBenchmarkNode.value.benchmark_data.health_score = res.health_score
      activeBenchmarkNode.value.benchmark_data.health_grade = res.health_grade
      activeBenchmarkNode.value.benchmark_data.health_label = res.health_label
      ElMessage.success(`系统深度体检完成！健康评分: ${res.health_score}分`)
      const idx = nodes.value.findIndex(n => n.id === nodeId)
      if (idx !== -1) {
        nodes.value[idx].benchmark_data = activeBenchmarkNode.value.benchmark_data
      }
    } else {
      ElMessage.error(res.error || '深度体检失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '体检异常')
  } finally {
    testingSingleDiag.value = false
  }
}

async function handleUpgradeWorker() {
  if (!activeBenchmarkNode.value) return
  upgradingWorker.value = true
  try {
    const res = await upgradeEdgeNodeWorker(activeBenchmarkNode.value.id)
    if (res.success) {
      ElMessage.success(res.message || 'Edge Worker 服务升级成功！')
      if (res.node) {
        activeBenchmarkNode.value = res.node
        const idx = nodes.value.findIndex(n => n.id === res.node!.id)
        if (idx !== -1) nodes.value[idx] = res.node
      }
    } else {
      ElMessage.warning(res.error || '升级失败')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || '升级异常')
  } finally {
    upgradingWorker.value = false
  }
}

function getHealthGradeClass(grade?: string): string {
  if (!grade) return 'grade-default'
  if (grade.startsWith('A')) return 'grade-a'
  if (grade.startsWith('B')) return 'grade-b'
  return 'grade-c'
}

function getDcRatingClass(rating?: string): string {
  switch (rating) {
    case 'optimal': return 'dc-optimal'
    case 'good': return 'dc-good'
    case 'medium': return 'dc-medium'
    case 'poor': return 'dc-poor'
    default: return 'dc-unreachable'
  }
}

async function handleDeleteNode(node: EdgeNode) {
  try {
    await ElMessageBox.confirm(
      `确定解绑并移除边缘节点「${node.node_name}」吗？移除后该租户的媒体请求将自动平滑回退至主控或公共池。`,
      '解绑边缘节点',
      { type: 'warning', confirmButtonText: '确认移除', cancelButtonText: '取消' }
    )
    const res = await deleteEdgeNode(node.id)
    if (res.success) {
      ElMessage.success('边缘节点已解绑移除')
      nodes.value = nodes.value.filter(n => n.id !== node.id)
      recalculateSummaryFromNodes()
    }
  } catch {
    // cancelled
  }
}

function openTokenDialog() {
  generatedToken.value = ''
  generatedCommand.value = ''
  pairedNode.value = null
  stopTokenPolling()
  tokenDialogVisible.value = true
}

async function handleGenerateToken() {
  if (!tokenForm.value.node_name.trim()) {
    ElMessage.warning('请输入节点名称')
    return
  }
  generatingToken.value = true
  try {
    const res = await generateEdgeNodeToken({
      node_name: tokenForm.value.node_name.trim(),
      port: tokenForm.value.port,
      domain: tokenForm.value.domain.trim(),
      use_ssl: tokenForm.value.use_ssl,
      allow_shared_pool: tokenForm.value.allow_shared_pool,
      target_dc_id: tokenForm.value.target_dc_id,
      allow_bot_pool: tokenForm.value.allow_bot_pool,
    })
    if (res.success) {
      generatedToken.value = res.token
      generatedCommand.value = res.command
      pairedNode.value = null
      startTokenPolling(res.token)
      ElMessage.success('专属一键安装指令已生成')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '生成安装 Token 失败')
  } finally {
    generatingToken.value = false
  }
}

function startTokenPolling(token: string) {
  stopTokenPolling()
  tokenPollTimer = setInterval(async () => {
    try {
      const res = await getEdgeTokenStatus(token)
      if (res.success && res.token_info?.used && res.node) {
        pairedNode.value = res.node
        stopTokenPolling()
        ElMessage.success(`边缘节点「${res.node.node_name}」已成功回连上线！`)
        const idx = nodes.value.findIndex(n => n.id === res.node!.id)
        if (idx !== -1) {
          Object.assign(nodes.value[idx], res.node)
        } else {
          nodes.value.unshift(res.node)
        }
        recalculateSummaryFromNodes()
      }
    } catch {
      // ignore poll error
    }
  }, 10000)
}

function stopTokenPolling() {
  if (tokenPollTimer) {
    clearInterval(tokenPollTimer)
    tokenPollTimer = null
  }
}

async function copyInstallCommand() {
  if (!generatedCommand.value) return
  try {
    await navigator.clipboard.writeText(generatedCommand.value)
    ElMessage.success('一键安装命令已复制到剪贴板')
  } catch {
    ElMessage.warning('请手动选中文本复制')
  }
}

function openLogModal(node: EdgeNode) {
  activeLogNode.value = node
  activeDeployLog.value = node.deploy_log || '正在加载终端部署日志...'
  activeLogStatus.value = node.status
  logModalVisible.value = true
  pollDeployLogs(node.id)
  stopLogPolling()
  // WebSocket 实时推送日志，仅保留低频 fallback 定时器
  logPollTimer = setInterval(() => {
    if (activeLogNode.value && activeLogStatus.value === 'deploying') {
      pollDeployLogs(activeLogNode.value.id)
    }
  }, 10000)
}

async function pollDeployLogs(nodeId: number) {
  try {
    const res = await getEdgeNodeDeployLogs(nodeId)
    if (res.success) {
      activeDeployLog.value = res.deploy_log || '等待输出日志...'
      activeLogStatus.value = res.status as EdgeNode['status']
      await nextTick()
      if (terminalPreRef.value) {
        terminalPreRef.value.scrollTop = terminalPreRef.value.scrollHeight
      }
      if (res.status !== 'deploying') {
        stopLogPolling()
        if (activeLogNode.value) {
          activeLogNode.value.status = res.status as EdgeNode['status']
        }
      }
    }
  } catch {
    // ignore
  }
}

function stopLogPolling() {
  if (logPollTimer) {
    clearInterval(logPollTimer)
    logPollTimer = null
  }
}

async function handleRetriggerDeployFromModal() {
  if (!activeLogNode.value) return
  try {
    const res = await triggerEdgeNodeDeploy(activeLogNode.value.id)
    if (res.success) {
      ElMessage.success('已重新启动 SSH 自动化部署')
      activeLogStatus.value = 'deploying'
      openLogModal(activeLogNode.value)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '无法启动部署，请先配置 SSH 密码')
  }
}

async function copyDeployLogs() {
  try {
    await navigator.clipboard.writeText(activeDeployLog.value || '')
    ElMessage.success('部署日志已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}

onMounted(() => {
  fetchNodes(true)
  initWebSocket()
})

onUnmounted(() => {
  stopTokenPolling()
  stopLogPolling()
  wsUnsubscribers.forEach(unsub => unsub())
  wsUnsubscribers = []
})
</script>


<style scoped>
.edge-nodes-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 28px;
  max-width: 100%;
}

/* 顶部品牌横幅与控制区 (统一 Sakura Glass 风格) */
.edge-header-card {
  padding: 24px 28px 20px;
  position: relative;
  overflow: hidden;
  border-radius: 20px;
}

.edge-header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}

.edge-title-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.edge-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.edge-title {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.5px;
  margin: 0;
  line-height: 1.2;
}

.edge-badge {
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

.edge-subtitle {
  color: #64748b;
  font-size: 13.5px;
  margin: 0;
  max-width: 780px;
  line-height: 1.5;
}

.edge-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.realtime-live-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.8);
  color: #64748b;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
  transition: all 0.3s ease;
}

.realtime-live-badge.is-live {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.35);
  color: #059669;
}

.live-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
  transition: all 0.3s ease;
}

.realtime-live-badge.is-live .live-pulse-dot {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.25), 0 0 8px #10b981;
  animation: pulse-ring 2s infinite cubic-bezier(0.45, 0, 0.2, 1);
}

@keyframes pulse-ring {
  0% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.6);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}

.tenant-status-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.3);
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.dot-online {
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2), 0 0 8px #10b981;
}

.dot-idle {
  background: #94a3b8;
}

.channel-pill {
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.header-btn:hover {
  transform: translateY(-1px);
}

.batch-bench-btn {
  background: rgba(56, 189, 248, 0.12) !important;
  color: #0284c7 !important;
  border: 1px solid rgba(56, 189, 248, 0.35) !important;
}

.btn-ssh-deploy {
  background: linear-gradient(135deg, #ff7597 0%, #ec4899 100%) !important;
  border: none !important;
  color: #ffffff !important;
  box-shadow: 0 4px 14px rgba(236, 72, 153, 0.28);
}

.btn-script-deploy {
  background: rgba(14, 165, 233, 0.1) !important;
  border: 1px solid rgba(14, 165, 233, 0.32) !important;
  color: #0284c7 !important;
}

.btn-refresh {
  border-radius: 12px !important;
}

/* 4 大统计卡片 (统一 Sakura 玻璃流光) */
.stats-row {
  margin-top: 4px;
}

.stat-card {
  position: relative;
  padding: 16px 18px;
  border-radius: 16px;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  background: rgba(255, 255, 255, 0.75) !important;
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
  font-size: 24px;
  font-weight: 800;
  color: #1e293b;
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

/* 302 智能加速链路原理提示条 */
.acceleration-status-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-radius: 14px;
  background: linear-gradient(90deg, rgba(254, 242, 242, 0.88), rgba(240, 249, 255, 0.88));
  border: 1px solid rgba(255, 143, 171, 0.28);
  font-size: 13px;
}

.strip-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.strip-sparkle {
  font-size: 15px;
}

.strip-title {
  font-weight: 700;
  color: #1e293b;
}

.strip-flow-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.flow-step {
  color: #475569;
  font-weight: 600;
}

.highlight-node {
  color: #0284c7;
  font-weight: 700;
  background: rgba(14, 165, 233, 0.1);
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

.flow-arrow {
  color: #94a3b8;
  font-weight: bold;
}

.strip-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.25);
  margin-left: 4px;
}

.strip-toggle-btn {
  background: none;
  border: none;
  font-size: 12px;
  font-weight: 600;
  color: #0284c7;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.strip-toggle-btn:hover {
  background: rgba(14, 165, 233, 0.1);
}

.topo-help-drawer {
  padding: 18px 22px;
  border-radius: 16px;
}

.topo-help-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

@media (max-width: 1024px) {
  .topo-help-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.topo-item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.8);
}

.topo-item.highlight {
  background: rgba(240, 249, 255, 0.8);
  border-color: rgba(56, 189, 248, 0.35);
}

.topo-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #ff7597;
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.topo-item.highlight .topo-num {
  background: #0284c7;
}

.topo-heading {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.topo-body {
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
}

/* 筛选控制与视图模式切换栏 */
.control-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-radius: 16px;
  gap: 16px;
  flex-wrap: wrap;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filter-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.9);
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-tab.active {
  background: rgba(255, 117, 151, 0.15);
  color: #e11d48;
  border-color: rgba(255, 117, 151, 0.4);
}

.tab-count {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
}

.tenant-node-count-badge {
  font-size: 14px;
  font-weight: 700;
  color: #334155;
}

.filter-right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.edge-search-input {
  width: 260px;
}

.view-mode-toggle {
  display: flex;
  align-items: center;
}

/* 节点网格容器 (自适应宽屏卡片，消除空旷与截断) */
.nodes-main-container {
  min-height: 280px;
}

.nodes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: 20px;
}

@media (max-width: 640px) {
  .nodes-grid {
    grid-template-columns: 1fr;
  }
  .node-card-footer {
    flex-wrap: wrap !important;
    gap: 10px;
  }
  .node-btn-group {
    flex-wrap: wrap !important;
    width: 100%;
    justify-content: flex-end;
  }
}

.node-card {
  display: flex;
  flex-direction: column;
  padding: 18px 20px;
  border-radius: 18px;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  border-left: 5px solid #cbd5e1;
  overflow: hidden;
}

.node-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
}

.node-card.status-online {
  border-left-color: #10b981;
}

.node-card.status-deploying {
  border-left-color: #0ea5e9;
}

.node-card.status-error {
  border-left-color: #ef4444;
}

/* 卡片头部 */
.node-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  min-width: 0;
}

.node-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  min-width: 0;
  flex: 1;
}

.node-id-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  flex-shrink: 0;
}

.node-name {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex-shrink: 1;
}

.tenant-tag {
  font-weight: 600;
  border-radius: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

.os-mini-tag {
  font-size: 11px;
  color: #64748b;
  background: rgba(241, 245, 249, 0.9);
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.node-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 12px;
  border-radius: 999px;
  flex-shrink: 0;
  white-space: nowrap;
}

.node-status-pill.online {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.node-status-pill.deploying {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.25);
}

.node-status-pill.offline {
  background: #f1f5f9;
  color: #64748b;
}

.node-status-pill.error {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

/* 卡片主体：双栏核心信息 */
.node-card-body-row {
  display: flex;
  gap: 16px;
  margin-bottom: 14px;
}

@media (max-width: 768px) {
  .edge-page {
    padding: 0 !important;
  }
  .edge-header-card,
  .table-container {
    padding: 14px !important;
    border-radius: 14px !important;
  }
  .edge-header-actions {
    flex-direction: column !important;
    width: 100% !important;
  }
  .edge-header-actions > * {
    width: 100% !important;
  }
  .nodes-grid {
    grid-template-columns: 1fr !important;
    gap: 12px !important;
  }
  .node-card {
    padding: 14px !important;
    border-radius: 14px !important;
  }
  .node-card-body-row {
    flex-direction: column !important;
    gap: 10px !important;
  }
  .node-card-footer {
    flex-direction: column !important;
    align-items: stretch !important;
    gap: 10px !important;
  }
  .node-card-footer .footer-actions {
    width: 100% !important;
    justify-content: space-between !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
  }
}

.node-net-col {
  flex: 1.1;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
}

.net-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.net-label {
  color: #64748b;
  font-weight: 600;
  flex-shrink: 0;
}

.net-val-box, .ssh-val-box {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.net-row.bot-row {
  align-items: flex-start;
}

.ep-value {
  color: #0284c7;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 600;
}

.btn-copy-ep {
  color: #0284c7 !important;
  padding: 0 !important;
  height: auto !important;
}

.ep-sub {
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.pwd-saved-badge {
  font-size: 11px;
  color: #d97706;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.btn-inline-wipe {
  background: rgba(225, 29, 72, 0.1);
  color: #e11d48;
  border: 1px solid rgba(225, 29, 72, 0.25);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  cursor: pointer;
}

.pwd-wiped-badge {
  font-size: 11px;
  color: #059669;
  white-space: nowrap;
}

.node-bench-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
}

.bench-capsule {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 10px;
  font-size: 12px;
  transition: all 0.2s ease;
  user-select: none;
}

.bench-capsule:hover {
  transform: translateX(2px);
  filter: brightness(1.03);
}

.capsule-icon {
  font-size: 13px;
}

.capsule-text {
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: #1e293b;
  font-weight: 600;
}

.capsule-sub {
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
}

.dc-capsule {
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(14, 165, 233, 0.25);
}

.speed-capsule {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.health-capsule.grade-a {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.health-capsule.grade-b {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.health-capsule.grade-c {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.empty-capsule {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #94a3b8;
}

/* 节点实时硬件负荷网格 */
.node-metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 0.9fr 1.1fr;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.metric-item {
  background: rgba(248, 250, 252, 0.9);
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.metric-top {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #64748b;
  margin-bottom: 4px;
}

.metric-val {
  font-weight: 700;
  color: #1e293b;
}

.metric-stat-box {
  background: rgba(248, 250, 252, 0.9);
  padding: 7px 12px;
  border-radius: 10px;
  text-align: center;
  border: 1px solid #e2e8f0;
  transition: all 0.25s ease;
}

.metric-stat-box.stat-active {
  background: rgba(2, 132, 199, 0.08);
  border-color: rgba(2, 132, 199, 0.35);
}

.metric-stat-box.stat-active .m-stat-label {
  color: #0284c7;
  font-weight: 600;
}

.metric-stat-box.stat-active .m-stat-num {
  color: #0369a1;
}

.m-stat-label {
  font-size: 11px;
  color: #64748b;
}

.m-stat-num {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
  margin-top: 2px;
}

.node-meta-strip {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: #64748b;
  padding: 0 4px;
  margin-bottom: 12px;
}

/* 底部操作与控制栏 (彻底杜绝换行与挤压) */
.node-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px dashed rgba(226, 232, 240, 0.9);
  gap: 10px;
  flex-wrap: wrap;
}

.shared-pool-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

.shared-label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

.node-btn-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-left: auto;
}

.btn-node-bench {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%) !important;
  border: none !important;
  color: #ffffff !important;
  font-weight: 600 !important;
  border-radius: 8px !important;
  height: 28px !important;
  padding: 0 9px !important;
  font-size: 11.5px !important;
  box-shadow: 0 2px 6px rgba(2, 132, 199, 0.25) !important;
  transition: all 0.2s ease !important;
}

.btn-node-bench:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(2, 132, 199, 0.35) !important;
}

.btn-node-act {
  border-radius: 8px !important;
  font-weight: 500 !important;
  height: 28px !important;
  padding: 0 8px !important;
  font-size: 11.5px !important;
}

.btn-node-more {
  border-radius: 8px !important;
  font-weight: 500 !important;
  height: 28px !important;
  padding: 0 7px !important;
  font-size: 11.5px !important;
}

/* 紧凑表格视图样式 */
.table-container {
  border-radius: 18px;
  padding: 16px 20px;
  overflow-x: auto;
}

.edge-nodes-table {
  border-radius: 12px;
  overflow: hidden;
}

.table-node-name-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.t-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.t-node-title {
  font-weight: 700;
  color: #0f172a;
}

.t-sub-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}

.t-ip-sub {
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.table-ep-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.t-bench-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
}

.table-actions-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 56px 24px;
  border-radius: 18px;
}

.empty-icon-wrap {
  font-size: 42px;
  margin-bottom: 12px;
}

.empty-title {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}

.empty-desc {
  font-size: 13.5px;
  color: #64748b;
  max-width: 520px;
  margin: 8px auto 20px;
  line-height: 1.5;
}

.empty-btns {
  display: flex;
  justify-content: center;
  gap: 14px;
}

/* 弹窗通用样式 */
.dialog-notice {
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(14, 165, 233, 0.08);
  border: 1px solid rgba(14, 165, 233, 0.22);
  color: #0369a1;
  font-size: 12.5px;
  margin-bottom: 16px;
  line-height: 1.5;
}

.script-result-box {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  margin-top: 8px;
}

.script-box-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 8px;
}

.terminal-cmd-block {
  background: #020617;
  color: #38bdf8;
  padding: 12px;
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0 0 10px;
}

.token-poll-status {
  font-size: 12.5px;
  font-weight: 600;
}

.poll-waiting {
  color: #fbbf24;
}

.poll-success {
  color: #34d399;
}

.terminal-window {
  border-radius: 12px;
  overflow: hidden;
  background: #0f172a;
  border: 1px solid #334155;
}

.terminal-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}

.term-dots {
  display: flex;
  gap: 6px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot.red { background: #ef4444; }
.dot.yellow { background: #f59e0b; }
.dot.green { background: #10b981; }

.term-title {
  font-size: 12px;
  color: #94a3b8;
  font-family: monospace;
}

.terminal-body {
  height: 360px;
  overflow-y: auto;
  padding: 14px;
  margin: 0;
  color: #10b981;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.edge-ssh-dialog .el-input-number,
.edge-token-dialog .el-input-number {
  width: 100% !important;
}

.edge-ssh-dialog .el-input-number .el-input__wrapper,
.edge-token-dialog .el-input-number .el-input__wrapper {
  padding-left: 12px !important;
  padding-right: 38px !important;
}

.edge-ssh-dialog .el-input-number .el-input__inner,
.edge-token-dialog .el-input-number .el-input__inner {
  text-align: left !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
  font-weight: 600 !important;
  font-size: 13.5px !important;
  color: #0f172a !important;
}
.auto-domain-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 12px;
  color: #0284c7;
  background: rgba(224, 242, 254, 0.65);
  border: 1px solid rgba(186, 230, 253, 0.8);
  border-radius: 6px;
  padding: 4px 10px;
}
.auto-domain-hint code {
  font-family: monospace;
  font-weight: 600;
  color: #0369a1;
}

/* ==================== 租户分流实时监控条与明细弹窗样式 ==================== */
.tenant-summary-btn {
  background: linear-gradient(135deg, rgba(236, 72, 153, 0.1), rgba(168, 85, 247, 0.12)) !important;
  border: 1px solid rgba(236, 72, 153, 0.3) !important;
  color: #db2777 !important;
  font-weight: 600 !important;
  border-radius: 10px !important;
}
.tenant-summary-btn:hover {
  background: linear-gradient(135deg, rgba(236, 72, 153, 0.2), rgba(168, 85, 247, 0.22)) !important;
  transform: translateY(-1px);
}
.tenant-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  margin-left: 6px;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #ec4899, #8b5cf6);
  border-radius: 9999px;
}

.node-tenant-monitor-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  margin-bottom: 12px;
  padding: 7px 10px;
  background: rgba(248, 250, 252, 0.7);
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 10px;
  backdrop-filter: blur(8px);
  gap: 8px;
}

.tenant-strip-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.tenant-strip-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  font-weight: 600;
  color: #64748b;
  flex-shrink: 0;
}
.tenant-tag-icon {
  font-size: 12px;
  color: #eab308;
}

.tenant-capsules-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tenant-streaming-capsule {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2.5px 8px;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(6, 182, 212, 0.12));
  border: 1px solid rgba(16, 185, 129, 0.35);
  border-radius: 9999px;
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}
.tenant-streaming-capsule:hover {
  transform: translateY(-1px);
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(6, 182, 212, 0.2));
  border-color: rgba(16, 185, 129, 0.6);
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.2);
}

.streaming-dot {
  width: 7px;
  height: 7px;
  background-color: #10b981;
  border-radius: 50%;
  box-shadow: 0 0 6px #10b981;
  animation: streamPulse 1.8s infinite;
  flex-shrink: 0;
}
@keyframes streamPulse {
  0% { transform: scale(0.9); opacity: 0.8; box-shadow: 0 0 2px #10b981; }
  50% { transform: scale(1.25); opacity: 1; box-shadow: 0 0 10px #10b981; }
  100% { transform: scale(0.9); opacity: 0.8; box-shadow: 0 0 2px #10b981; }
}

.t-name {
  font-weight: 600;
  color: #065f46;
}
.t-speed {
  font-weight: 700;
  color: #0284c7;
}
.t-streams {
  font-size: 10.5px;
  color: #64748b;
}

.tenant-idle-capsule {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2.5px 8px;
  background: rgba(241, 245, 249, 0.8);
  border: 1px dashed rgba(203, 213, 225, 0.8);
  border-radius: 9999px;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tenant-idle-capsule:hover {
  background: rgba(226, 232, 240, 0.8);
  color: #475569;
}
.idle-dot {
  width: 6px;
  height: 6px;
  background-color: #94a3b8;
  border-radius: 50%;
}
.idle-history-hint {
  font-size: 10.5px;
  color: #94a3b8;
}

.tenant-strip-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.tenant-ranking-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px !important;
  font-size: 11.5px !important;
  color: #db2777 !important;
  border-radius: 6px !important;
  transition: all 0.15s ease;
}
.tenant-ranking-btn:hover {
  background: rgba(236, 72, 153, 0.08) !important;
  color: #be185d !important;
}
.tenant-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: #ec4899;
  border-radius: 9999px;
}

/* 表格内租户分流单元格 */
.table-tenant-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.table-tenant-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 9999px;
  font-size: 11px;
}
.table-tenant-pill.active-pill {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #065f46;
  font-weight: 600;
}
.table-tenant-pill.idle-pill {
  background: rgba(241, 245, 249, 0.8);
  border: 1px dashed rgba(203, 213, 225, 0.8);
  color: #64748b;
}
.streaming-dot-sm {
  width: 6px;
  height: 6px;
  background-color: #10b981;
  border-radius: 50%;
  animation: streamPulse 1.8s infinite;
}
.idle-dot-sm {
  width: 5px;
  height: 5px;
  background-color: #94a3b8;
  border-radius: 50%;
}
.pill-extra {
  font-size: 10px;
  color: #0284c7;
  font-weight: 700;
}
.table-rank-btn {
  padding: 0 !important;
  font-size: 13px !important;
}

/* 租户审计弹窗样式 */
.edge-tenant-dialog :deep(.el-dialog__body) {
  padding: 16px 20px 20px;
}
.tenant-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tenant-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 680px) {
  .tenant-kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
.t-kpi-card {
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}
.t-kpi-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 4px;
}
.t-kpi-val {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}
.t-kpi-val small {
  font-size: 12px;
  font-weight: 500;
  color: #94a3b8;
}

.tenant-table-wrap {
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.85);
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 22px;
  font-size: 12px;
  font-weight: 700;
  border-radius: 6px;
}
.rank-badge.rank-1 {
  background: linear-gradient(135deg, #fef08a, #facc15);
  color: #854d0e;
  box-shadow: 0 2px 6px rgba(234, 179, 8, 0.3);
}
.rank-badge.rank-2 {
  background: linear-gradient(135deg, #e2e8f0, #cbd5e1);
  color: #475569;
}
.rank-badge.rank-3 {
  background: linear-gradient(135deg, #fed7aa, #fdba74);
  color: #9a3412;
}
.rank-badge.rank-other {
  color: #94a3b8;
}

.tenant-identity-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.t-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ec4899, #8b5cf6);
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(236, 72, 153, 0.25);
}
.t-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.t-username {
  font-size: 13px;
  color: #1e293b;
}
.t-role-tags {
  display: flex;
  gap: 4px;
}

.status-streaming-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 8px;
}
.streaming-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.15;
}
.streaming-text .speed {
  font-size: 12px;
  font-weight: 700;
  color: #065f46;
}
.streaming-text .streams {
  font-size: 10px;
  color: #059669;
}

.status-idle-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(241, 245, 249, 0.8);
  border: 1px dashed rgba(203, 213, 225, 0.9);
  border-radius: 8px;
  font-size: 11.5px;
  color: #64748b;
}

.t-bytes-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}
.t-bytes-val {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}
.t-bytes-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}
.t-bytes-bar :deep(.el-progress) {
  flex: 1;
}
.t-ratio-num {
  font-size: 10.5px;
  font-weight: 600;
  color: #ec4899;
  min-width: 32px;
  text-align: right;
}

.tenant-privacy-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(238, 242, 255, 0.7);
  border: 1px solid rgba(199, 210, 254, 0.7);
  border-radius: 10px;
  font-size: 12px;
  color: #4338ca;
  line-height: 1.5;
}
.notice-icon {
  font-size: 14px;
  flex-shrink: 0;
  margin-top: 1px;
}

</style>


<style>
/* 边缘节点管理弹窗通用现代精致主题（无 scoped 隔离限制，覆盖 append-to-body 与粉色主题） */
.edge-ssh-dialog.el-dialog,
.edge-token-dialog.el-dialog,
.edge-log-dialog.el-dialog {
  border-radius: 16px !important;
  border: 1px solid #cbd5e1 !important;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.25) !important;
  background: #ffffff !important;
  color: #1e293b !important;
  overflow: hidden !important;
}

.edge-ssh-dialog .el-dialog__header,
.edge-token-dialog .el-dialog__header,
.edge-log-dialog .el-dialog__header {
  padding: 16px 20px 14px !important;
  margin-right: 0 !important;
  border-bottom: 1px solid #e2e8f0 !important;
  background: #f8fafc !important;
}

.edge-ssh-dialog .el-dialog__body,
.edge-token-dialog .el-dialog__body,
.edge-log-dialog .el-dialog__body {
  padding: 18px 20px !important;
  background: #ffffff !important;
}

.edge-ssh-dialog .el-input__wrapper,
.edge-token-dialog .el-input__wrapper {
  border-radius: 8px !important;
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
  background: #ffffff !important;
}

.edge-ssh-dialog .el-input__wrapper:hover,
.edge-token-dialog .el-input__wrapper:hover {
  box-shadow: 0 0 0 1px #94a3b8 inset !important;
}

.edge-ssh-dialog .el-input__wrapper.is-focus,
.edge-token-dialog .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.4) inset !important;
}

.edge-ssh-dialog .el-button--primary:not(.is-plain):not(.is-text):not(.is-link),
.edge-token-dialog .el-button--primary:not(.is-plain):not(.is-text):not(.is-link),
.edge-log-dialog .el-button--primary:not(.is-plain):not(.is-text):not(.is-link) {
  background: #0284c7 !important;
  border: 1px solid #0284c7 !important;
  color: #ffffff !important;
  box-shadow: 0 1px 3px rgba(2, 132, 199, 0.25) !important;
}

.edge-ssh-dialog .el-switch.is-checked .el-switch__core,
.edge-token-dialog .el-switch.is-checked .el-switch__core {
  background-color: #10b981 !important;
  border-color: #10b981 !important;
}

.edge-ssh-dialog .el-input-number,
.edge-token-dialog .el-input-number {
  width: 100% !important;
}

.edge-ssh-dialog .el-input-number .el-input__wrapper,
.edge-token-dialog .el-input-number .el-input__wrapper {
  padding-left: 12px !important;
  padding-right: 38px !important;
}

.edge-ssh-dialog .el-input-number .el-input__inner,
.edge-token-dialog .el-input-number .el-input__inner {
  text-align: left !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
  font-weight: 600 !important;
  font-size: 13.5px !important;
  color: #0f172a !important;
}

.edge-ssh-dialog .el-input-number__decrease,
.edge-ssh-dialog .el-input-number__increase,
.edge-token-dialog .el-input-number__decrease,
.edge-token-dialog .el-input-number__increase {
  background: #f8fafc !important;
  border-color: #cbd5e1 !important;
  color: #475569 !important;
}

.edge-ssh-dialog .el-input-number__decrease:hover,
.edge-ssh-dialog .el-input-number__increase:hover,
.edge-token-dialog .el-input-number__decrease:hover,
.edge-token-dialog .el-input-number__increase:hover {
  background: #e2e8f0 !important;
  color: #0284c7 !important;
}

.edge-ssh-dialog .el-switch .el-switch__core,
.edge-token-dialog .el-switch .el-switch__core {
  background-color: #cbd5e1 !important;
  border-color: #cbd5e1 !important;
}

.edge-ssh-dialog .el-switch.is-checked .el-switch__core,
.edge-token-dialog .el-switch.is-checked .el-switch__core {
  background-color: #0284c7 !important;
  border-color: #0284c7 !important;
}

/* 全能测速与体检弹窗样式 (append-to-body) */
.edge-benchmark-dialog.el-dialog {
  border-radius: 20px !important;
  border: 1px solid rgba(255, 143, 171, 0.35) !important;
  box-shadow: 0 24px 60px -12px rgba(255, 117, 151, 0.2), 0 8px 24px -4px rgba(56, 189, 248, 0.12) !important;
  background: rgba(255, 255, 255, 0.96) !important;
  backdrop-filter: blur(20px) !important;
  color: #1e293b !important;
  overflow: hidden !important;
  max-width: 95vw !important;
  box-sizing: border-box !important;
}

.edge-benchmark-dialog .el-dialog__header {
  padding: 18px 24px 14px !important;
  margin-right: 0 !important;
  border-bottom: 1px solid rgba(255, 182, 193, 0.25) !important;
  background: linear-gradient(135deg, rgba(255, 240, 245, 0.85) 0%, rgba(240, 249, 255, 0.85) 100%) !important;
}

.bench-dialog-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.bench-header-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.bench-header-title {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.3px;
}

.bench-header-node-tag {
  font-size: 12px;
  font-weight: 700;
  color: #0284c7;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 2px 8px;
  border-radius: 9999px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.bench-header-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}

.edge-benchmark-dialog .el-dialog__body {
  padding: 20px 24px !important;
  background: rgba(255, 255, 255, 0.65) !important;
  max-height: 80vh !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
  box-sizing: border-box !important;
}

.edge-benchmark-dialog .el-dialog__footer {
  padding: 12px 24px 16px !important;
  border-top: 1px solid rgba(255, 182, 193, 0.25) !important;
  background: rgba(255, 245, 247, 0.65) !important;
}

.bench-dialog-body {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 顶部 Banner */
.bench-top-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 18px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(255, 182, 193, 0.35);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.06);
  box-sizing: border-box;
  width: 100%;
}

.bench-node-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1 1 300px;
}

.bench-node-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.node-id-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 6px;
  background: #0f172a;
  color: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.node-name-text {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.bench-host-tag {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  color: #0284c7;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 2px 8px;
  border-radius: 6px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-time-tag {
  font-size: 12px;
  color: #64748b;
}

.bench-top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.btn-run-full {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%) !important;
  border: none !important;
  color: #ffffff !important;
  font-weight: 700 !important;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.25);
  transition: all 0.25s ease;
}

.btn-run-full:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(255, 117, 151, 0.35);
  opacity: 0.95;
}

.btn-upgrade-worker {
  background: rgba(255, 255, 255, 0.9) !important;
  border: 1px solid rgba(255, 182, 193, 0.4) !important;
  color: #334155 !important;
  font-weight: 600 !important;
  transition: all 0.2s ease;
}

.btn-upgrade-worker:hover {
  border-color: #38bdf8 !important;
  color: #0284c7 !important;
  background: rgba(240, 249, 255, 0.9) !important;
}

/* 测速进行中进度条 */
.bench-progress-strip {
  position: relative;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  color: #38bdf8;
  padding: 10px 14px;
  border-radius: 10px;
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
  width: 100%;
  box-sizing: border-box;
}

.progress-bar-animated {
  position: absolute;
  top: 0;
  left: -100%;
  width: 50%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), transparent);
  animation: benchGlow 1.8s infinite linear;
}

@keyframes benchGlow {
  0% { left: -50%; }
  100% { left: 100%; }
}

.progress-text {
  position: relative;
  z-index: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}

/* 4 大核心 KPI 卡片 */
.bench-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
}

@media (max-width: 860px) {
  .bench-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.bench-kpi-card {
  min-width: 0;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 182, 193, 0.35);
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.05);
  box-sizing: border-box;
  overflow: hidden;
  transition: all 0.25s ease;
}

.bench-kpi-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 117, 151, 0.5);
  box-shadow: 0 8px 24px rgba(255, 117, 151, 0.12);
}

.b-kpi-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  gap: 4px;
}

.b-kpi-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.b-kpi-badge {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
  white-space: nowrap;
  flex-shrink: 0;
}

.b-kpi-badge.grade-a { background: #d1fae5; color: #065f46; }
.b-kpi-badge.grade-b { background: #fef3c7; color: #92400e; }
.b-kpi-badge.grade-c { background: #fee2e2; color: #991b1b; }
.badge-speed { background: #dbeafe; color: #1e40af; }
.badge-neutral { background: #f1f5f9; color: #475569; }
.badge-optimal { background: #dcfce7; color: #166534; }

.b-kpi-val {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 4px;
  min-width: 0;
}

.val-num {
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.val-unit {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.text-dc {
  font-size: 19px;
  color: #0284c7;
}

.b-kpi-sub {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
  display: block;
}

/* Tab 选项卡分流容器 */
.bench-tabs-container {
  width: 100%;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 182, 193, 0.35);
  border-radius: 16px;
  padding: 16px 18px;
  box-shadow: 0 4px 20px rgba(255, 117, 151, 0.06);
}

.bench-tabs-container :deep(.el-tabs__header) {
  margin: 0 0 16px 0;
  border-bottom: 1px solid rgba(255, 182, 193, 0.25);
}

.bench-tabs-container :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: rgba(255, 182, 193, 0.25);
}

.bench-tabs-container :deep(.el-tabs__item) {
  font-size: 13.5px;
  font-weight: 600;
  color: #64748b;
  padding: 0 18px 10px;
  transition: all 0.2s ease;
}

.bench-tabs-container :deep(.el-tabs__item:hover) {
  color: #ff7597;
}

.bench-tabs-container :deep(.el-tabs__item.is-active) {
  color: #ff7597;
  font-weight: 700;
}

.bench-tabs-container :deep(.el-tabs__active-bar) {
  background: linear-gradient(90deg, #ff7597 0%, #38bdf8 100%);
  height: 3px;
  border-radius: 3px;
}

.tab-pane-inner {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 模块容器与头部 */
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
  width: 100%;
  box-sizing: border-box;
}

.head-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1 1 280px;
}

.section-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #1e293b;
}

.section-tip {
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.4;
}

.section-actions-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.sample-radio-group {
  flex-shrink: 0;
}

.sample-radio-group :deep(.el-radio-button__inner) {
  padding: 6px 10px;
  font-size: 11.5px;
}

.btn-section-act {
  background: rgba(255, 255, 255, 0.9) !important;
  border-color: rgba(255, 182, 193, 0.4) !important;
  color: #334155 !important;
  font-weight: 600 !important;
}

.btn-section-act:hover {
  border-color: #38bdf8 !important;
  color: #0284c7 !important;
  background: rgba(240, 249, 255, 0.9) !important;
}

/* 全双工流速漏斗面板 */
.relay-funnel-panel {
  background: rgba(255, 245, 247, 0.7);
  border: 1px solid rgba(255, 182, 193, 0.35);
  border-radius: 12px;
  padding: 14px 16px;
  box-sizing: border-box;
  width: 100%;
}

.funnel-title-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.funnel-title-text {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}

.funnel-steps-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1.25fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
}

@media (max-width: 680px) {
  .funnel-steps-grid {
    grid-template-columns: 1fr;
  }
  .funnel-arrow {
    transform: rotate(90deg);
    margin: 4px auto;
  }
}

.funnel-box {
  min-width: 0;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(255, 182, 193, 0.3);
  border-radius: 10px;
  padding: 10px 12px;
  text-align: center;
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.05);
  box-sizing: border-box;
  transition: all 0.2s ease;
}

.funnel-box:hover {
  border-color: rgba(255, 117, 151, 0.5);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.1);
}

.funnel-box-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.funnel-box-val {
  font-size: 15px;
  font-weight: 800;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.funnel-box-sub {
  font-size: 10.5px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.funnel-arrow {
  color: #ff8fab;
  font-size: 18px;
  font-weight: 800;
  flex-shrink: 0;
  user-select: none;
  padding: 0 4px;
}

/* 性能与统计面板 */
.speed-detail-panel {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 182, 193, 0.3);
  border-radius: 12px;
  padding: 12px 14px;
  box-sizing: border-box;
  width: 100%;
}

@media (max-width: 768px) {
  .speed-detail-panel {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.speed-stat-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.s-label {
  font-size: 11.5px;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.s-val {
  font-size: 17px;
  font-weight: 800;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.text-emerald { color: #059669; }
.text-cyan { color: #0284c7; }
.text-purple { color: #7c3aed; }
.text-gold { color: #d97706; }

.s-sub {
  font-size: 10.5px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 子块容器 */
.bench-sub-block {
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 182, 193, 0.28);
  border-radius: 12px;
  padding: 14px 16px;
  box-sizing: border-box;
  width: 100%;
}

/* DC 延迟卡片网格 */
.dc-cards-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
}

@media (max-width: 820px) {
  .dc-cards-grid {
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  }
}

.dc-item-card {
  min-width: 0;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 10px;
  padding: 10px 12px;
  transition: all 0.2s ease;
  position: relative;
  box-sizing: border-box;
}

.dc-item-card:hover {
  transform: translateY(-2px);
  border-color: rgba(56, 189, 248, 0.6);
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.12);
}

.dc-item-card.is-fastest {
  border-color: #10b981 !important;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.25) !important;
  background: rgba(240, 253, 244, 0.95) !important;
}

.dc-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 6px;
  gap: 4px;
}

.dc-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.dc-id-pill {
  font-size: 11px;
  font-weight: 800;
  padding: 1px 5px;
  border-radius: 4px;
  background: #0f172a;
  color: #ffffff;
  flex-shrink: 0;
}

.dc-title {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dc-badges {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex-shrink: 0;
}

.badge-fastest {
  font-size: 9.5px;
  font-weight: 700;
  background: #10b981;
  color: #ffffff;
  padding: 1px 4px;
  border-radius: 3px;
}

.badge-homedc {
  font-size: 9.5px;
  font-weight: 700;
  background: #0284c7;
  color: #ffffff;
  padding: 1px 4px;
  border-radius: 3px;
}

.dc-rtt-box {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 6px;
  gap: 4px;
}

.dc-rtt-num {
  font-size: 16px;
  font-weight: 800;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #0f172a;
  white-space: nowrap;
}

.dc-quality-pill {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.dc-optimal { color: #059669; background: #d1fae5; }
.dc-good { color: #0284c7; background: #e0f2fe; }
.dc-medium { color: #d97706; background: #fef3c7; }
.dc-poor { color: #dc2626; background: #fee2e2; }
.dc-unreachable { color: #64748b; background: #f1f5f9; }

.dc-meta-foot {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #94a3b8;
  gap: 4px;
}

.dc-meta-foot span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 系统体检网格 */
.diag-issues-banner {
  background: rgba(254, 243, 199, 0.9);
  border: 1px solid #fde68a;
  color: #b45309;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  box-sizing: border-box;
}

.issue-tag { font-weight: 700; }
.issue-item {
  background: #fef3c7;
  padding: 2px 6px;
  border-radius: 4px;
}

.diag-items-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
}

@media (max-width: 768px) {
  .diag-items-grid {
    grid-template-columns: 1fr;
  }
}

.diag-cell {
  display: flex;
  gap: 10px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(255, 182, 193, 0.3);
  border-radius: 10px;
  padding: 10px 12px;
  box-sizing: border-box;
  min-width: 0;
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.04);
}

.d-icon {
  font-size: 20px;
  line-height: 1;
  flex-shrink: 0;
}

.d-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  min-width: 0;
}

.d-title {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
}

.d-desc {
  font-size: 12px;
  color: #334155;
  font-weight: 600;
  word-break: break-all;
}

.d-sub {
  font-size: 10.5px;
  color: #64748b;
  word-break: break-all;
}

/* 链路测速网格 */
.link-bench-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 182, 193, 0.3);
  border-radius: 10px;
  padding: 12px 14px;
  box-sizing: border-box;
  width: 100%;
}

@media (max-width: 768px) {
  .link-bench-grid {
    grid-template-columns: 1fr;
  }
}

.link-stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  min-width: 0;
}

.l-label {
  color: #64748b;
  font-weight: 600;
}

.l-val {
  font-size: 14.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #0f172a;
  font-weight: 700;
}
</style>

<style scoped>
.bot-val-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.bot-line-main {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.bot-name {
  color: #0f172a;
  font-weight: 600;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  max-width: 175px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bot-name.empty-sub {
  color: #64748b;
  font-weight: normal;
}

.bot-line-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.dc-tag-pill {
  font-size: 11px;
  font-weight: 600;
  border-radius: 9999px;
  padding: 0 6px;
  height: 20px;
  line-height: 18px;
  white-space: nowrap;
}

.btn-inline-reassign {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}

.btn-inline-reassign:hover {
  background: #f59e0b;
  color: #fff;
}

.table-bot-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.table-bot-name {
  font-weight: 600;
  font-size: 12px;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 4px;
}

.table-dc-tag {
  font-size: 10px;
  padding: 0 4px;
  height: 18px;
  line-height: 16px;
}

/* 弹窗 5：节点 Bot 调度与分配工作台样式 */
.edge-assign-bot-dialog :deep(.el-dialog__body) {
  padding: 16px 24px 20px;
}

.assign-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.assign-node-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(226, 232, 240, 0.8);
}

.ans-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.ans-id {
  font-size: 13px;
  font-weight: 700;
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
  padding: 2px 6px;
  border-radius: 6px;
}

.ans-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.ans-ip {
  font-size: 13px;
  color: #64748b;
}

.ans-dc-badge {
  font-size: 12px;
}

.ans-dc-badge.optimal {
  color: #059669;
}

.ans-dc-badge.muted {
  color: #94a3b8;
}

.ans-cur-bot-box {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.ans-cur-label {
  font-size: 11px;
  color: #94a3b8;
}

.ans-cur-val {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.assign-mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.mode-card {
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  border: 2px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s ease;
}

.mode-card:hover {
  border-color: #cbd5e1;
  background: #ffffff;
}

.mode-card.active {
  border-color: #3b82f6;
  background: rgba(239, 246, 255, 0.85);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.12);
}

.mode-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.mode-radio-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid #cbd5e1;
  position: relative;
  transition: all 0.2s ease;
}

.mode-card.active .mode-radio-dot {
  border-color: #3b82f6;
  background: #3b82f6;
  box-shadow: inset 0 0 0 2px #ffffff;
}

.mode-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.mode-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  margin: 0;
}

.auto-mode-config,
.manual-mode-config {
  padding: 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(226, 232, 240, 0.8);
}

.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}

.auto-mode-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.bots-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.dc-filter-capsules {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.dc-cap-btn {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.dc-cap-btn:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.dc-cap-btn.active {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #ffffff;
  font-weight: 500;
}

.bots-grid-scroller {
  max-height: 280px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.bot-select-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 10px;
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.15s ease;
}

.bot-select-item:hover {
  border-color: #93c5fd;
  background: #f8fafc;
}

.bot-select-item.selected {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
}

.bs-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bs-radio-indicator {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid #cbd5e1;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.bot-select-item.selected .bs-radio-indicator {
  border-color: #3b82f6;
  background: #3b82f6;
  box-shadow: inset 0 0 0 3px #ffffff;
}

.bs-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.bs-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bs-bot-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.bs-dc-tag, .bs-main-tag {
  font-size: 11px;
}

.bs-sub-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}

.bs-mask {
  color: #64748b;
}

.bs-bound-warn {
  color: #d97706;
}

.bs-bound-idle {
  color: #059669;
}

.empty-bots-hint {
  text-align: center;
  padding: 30px;
  color: #94a3b8;
  font-size: 13px;
}

.assign-advanced-options {
  padding: 14px 18px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.adv-opt-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.adv-opt-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.adv-opt-title {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
}

.adv-opt-desc {
  font-size: 11px;
  color: #64748b;
}

.btn-table-assign {
  font-size: 12px;
  padding: 0;
  height: auto;
}

.table-bot-actions-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
</style>
