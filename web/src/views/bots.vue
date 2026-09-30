<template>
  <div class="bots-page animate-fade-in">
    <!-- 顶部品牌横幅与核心指标 -->
    <div class="bots-header-card glass-card">
      <div class="bots-header-main">
        <div class="bots-title-group">
          <div class="bots-title-row">
            <h2 class="bots-title text-gradient-sakura">机器人集群管理中心</h2>
            <span class="bots-badge">Bot Cluster &amp; Benchmark</span>
          </div>
          <p class="bots-subtitle">
            协议号全自动接码入网、@BotFather 批量铸造、全集群 MTProto 延迟与流速测速、免加频道智能分流调度。
          </p>
        </div>

        <div class="bots-header-actions">
          <el-button
            class="header-btn"
            :icon="RefreshRight"
            @click="fetchAllData"
            :loading="loading"
          >
            刷新状态
          </el-button>
          <el-button
            class="header-btn speed-test-btn"
            :icon="Lightning"
            @click="handleBenchmarkAll"
            :loading="benchmarkLoading"
          >
            一键全网健康巡检
          </el-button>
          <el-button
            class="header-btn"
            :icon="Aim"
            @click="handleReprobe"
            :loading="reprobeLoading"
          >
            重探权限
          </el-button>
          <el-button
            class="header-btn primary-glow-btn pipeline-btn"
            :icon="MagicStick"
            @click="router.push('/botfather')"
          >
            自动铸机流水线
          </el-button>
          <el-button
            class="header-btn"
            :icon="Plus"
            @click="hotAddDialogVisible = true"
          >
            挂载 Token
          </el-button>
        </div>
      </div>

      <!-- 顶部 4 大流光指标卡 -->
      <el-row :gutter="14" class="stats-row">
        <!-- 1. 集群在线节点 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-nodes">
              <el-icon :size="22"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ botDetails.length }} <span class="stat-unit">节点</span></div>
              <div class="stat-label">
                主控 1 + 从机 {{ Math.max(0, botDetails.length - 1) }} (多号集群就绪)
              </div>
              <div class="stat-progress">
                <div
                  class="stat-progress-bar"
                  :style="{ width: `${Math.min(100, (botDetails.length / Math.max(20, Math.ceil(botDetails.length / 20) * 20)) * 100)}%` }"
                ></div>
              </div>
            </div>
          </div>
        </el-col>

        <!-- 2. 免加频道分流 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-nojoin">
              <el-icon :size="22"><Lightning /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-sky">
                {{ noJoinCount }} <span class="stat-unit">免加频道</span>
              </div>
              <div class="stat-label">
                可读分流就绪 {{ accessibleCount }} / {{ botDetails.length }} 节点
              </div>
            </div>
          </div>
        </el-col>

        <!-- 3. 集群平均延迟 / 连通率 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-speed">
              <el-icon :size="22"><Odometer /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value" :class="clusterPingColorClass">
                {{ clusterBenchmark ? `${clusterBenchmark.avg_ping_ms}` : '--' }}
                <span class="stat-unit">ms</span>
              </div>
              <div class="stat-label">
                {{ clusterBenchmark ? `连通率 ${Math.round((clusterBenchmark.online_count / Math.max(1, clusterBenchmark.total_tested)) * 100)}% (${clusterBenchmark.online_count}/${clusterBenchmark.total_tested})` : '点击上方“一键全网健康巡检”' }}
              </div>
            </div>
          </div>
        </el-col>

        <!-- 4. 频道公共标识与实时负载 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-channel">
              <el-icon :size="22"><Promotion /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-pink">
                {{ channelInfo?.public_handle ? `@${channelInfo.public_handle}` : '私密频道' }}
              </div>
              <div class="stat-label">
                {{ channelInfo?.no_join_balancing_active ? '免加频道握手已激活' : '需添加管理员权限' }}
                · 负载 {{ totalWorkload }}
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 集群巡检综合报告面板 (当完成巡检后展示) -->
    <div v-if="clusterBenchmark" class="cluster-benchmark-card glass-card animate-fade-in">
      <div class="card-header-line">
        <div class="card-title-wrap">
          <span class="card-icon-dot dot-emerald"></span>
          <h3 class="card-title">全集群 Bot 连通性与 DC 健康报告</h3>
          <span class="benchmark-summary-pill">{{ clusterBenchmark.summary }}</span>
        </div>
        <div class="benchmark-header-right">
          <span class="bench-time">巡检时间: {{ clusterBenchmark.tested_at }}</span>
          <el-button
            size="small"
            class="re-bench-btn"
            :icon="Lightning"
            @click="handleBenchmarkAll"
            :loading="benchmarkLoading"
          >
            重新巡检
          </el-button>
        </div>
      </div>

      <div class="benchmark-kpi-row">
        <div class="bench-kpi-item">
          <span class="kpi-label">平均响应延迟</span>
          <span class="kpi-value text-emerald-500">{{ clusterBenchmark.avg_ping_ms }} ms</span>
          <span class="kpi-sub">MTProto get_me() 延迟</span>
        </div>
        <div class="bench-kpi-item">
          <span class="kpi-label">最优响应节点</span>
          <span class="kpi-value text-sky-500">
            #{{ clusterBenchmark.fastest_node?.index ?? '--' }}
            <span class="kpi-sub-name">@{{ cleanUsername(clusterBenchmark.fastest_node?.username) }}</span>
          </span>
          <span class="kpi-sub">{{ clusterBenchmark.fastest_node?.ping_ms }} ms</span>
        </div>
        <div class="bench-kpi-item">
          <span class="kpi-label">DC 资产分布透视</span>
          <span class="kpi-value text-pink-500 text-sm font-semibold truncate-dc-dist" :title="formatDcDistribution(clusterBenchmark.dc_distribution)">
            {{ formatDcDistribution(clusterBenchmark.dc_distribution) }}
          </span>
          <span class="kpi-sub">Telegram 官方机房分布</span>
        </div>
        <div class="bench-kpi-item">
          <span class="kpi-label">全网健康就绪率</span>
          <span class="kpi-value text-purple-500">
            {{ Math.round((clusterBenchmark.online_count / Math.max(1, clusterBenchmark.total_tested)) * 100) }}%
          </span>
          <span class="kpi-sub">{{ clusterBenchmark.online_count }} / {{ clusterBenchmark.total_tested }} 节点连通</span>
        </div>
      </div>
    </div>

    <!-- TG 数据中心（DC1~DC5）动态分区亲和矩阵 -->
    <div v-if="dcPartitionList.length > 0" class="dc-partition-card glass-card animate-fade-in">
      <div class="card-header-line">
        <div class="card-title-wrap">
          <span class="card-icon-dot dot-purple"></span>
          <h3 class="card-title">TG 数据中心（DC1~DC5）动态分区亲和矩阵</h3>
          <span class="dc-matrix-pill">DC-Aware Dynamic Routing</span>
        </div>
        <span class="dc-matrix-hint">优先调度同 DC 原生节点与已热备会话，高负载时平滑跨区溢出</span>
      </div>

      <div class="dc-matrix-grid">
        <div
          v-for="part in dcPartitionList"
          :key="part.dc_id"
          class="dc-part-item"
          :class="{
            'dc-part-active': part.files_count > 0 || part.home_bots.length > 0,
            'dc-part-idle': part.files_count === 0 && part.home_bots.length === 0 && part.warm_bots.length === 0
          }"
        >
          <div class="dc-part-top">
            <span class="dc-badge-tag" :class="`dc-tag-${part.dc_id}`">DC{{ part.dc_id }}</span>
            <span class="dc-region-name" :title="cleanDcRegion(part.label)">{{ cleanDcRegion(part.label) }}</span>
          </div>
          <div class="dc-part-metrics">
            <div class="dc-m-col">
              <span class="dc-m-val text-sky-500">{{ part.files_count }}</span>
              <span class="dc-m-lbl" title="网盘文件">网盘文件</span>
            </div>
            <div class="dc-m-col">
              <span class="dc-m-val text-pink-500">{{ part.home_bots.length }}</span>
              <span class="dc-m-lbl" title="原生Bot">原生Bot</span>
            </div>
            <div class="dc-m-col">
              <span class="dc-m-val text-emerald-500">{{ part.warm_bots.length }}</span>
              <span class="dc-m-lbl" title="热备就绪">热备就绪</span>
            </div>
          </div>
          <div class="dc-part-bots">
            <el-popover
              v-if="part.home_bots.length > 0 || part.warm_bots.length > 0"
              placement="top"
              :width="320"
              trigger="hover"
              popper-class="dc-popover-card"
            >
              <template #reference>
                <div class="dc-bot-preview-pill">
                  <template v-if="part.home_bots.length > 0">
                    <span class="dc-bot-type text-purple-600">原生:</span>
                    <span class="dc-bot-nums text-purple-600 font-medium">
                      {{ part.home_bots.slice(0, 3).map((i: number) => `#${i}`).join(', ') }}
                    </span>
                    <span v-if="part.home_bots.length > 3" class="dc-more-badge bg-purple-50 text-purple-600">
                      +{{ part.home_bots.length - 3 }}
                    </span>
                  </template>
                  <template v-else-if="part.warm_bots.length > 0">
                    <span class="dc-bot-type text-emerald-600">热备:</span>
                    <span class="dc-bot-nums text-emerald-600 font-medium">
                      {{ part.warm_bots.slice(0, 3).map((i: number) => `#${i}`).join(', ') }}
                    </span>
                    <span v-if="part.warm_bots.length > 3" class="dc-more-badge bg-emerald-50 text-emerald-600">
                      +{{ part.warm_bots.length - 3 }}
                    </span>
                  </template>
                </div>
              </template>

              <!-- 悬停 Popover 浮层内容 -->
              <div class="dc-popover-inner">
                <div class="dc-popover-header">
                  <span class="dc-badge-tag" :class="`dc-tag-${part.dc_id}`">DC{{ part.dc_id }}</span>
                  <span class="dc-popover-title">调度亲和明细 ({{ cleanDcRegion(part.label) }})</span>
                </div>

                <div v-if="part.home_bots.length > 0" class="dc-pop-section">
                  <div class="dc-pop-sec-title">
                    <span class="dc-dot-sub bg-purple-500"></span>
                    <span>原生节点 ({{ part.home_bots.length }} 个)</span>
                  </div>
                  <div class="dc-pop-chips-wrap">
                    <span
                      v-for="idx in part.home_bots"
                      :key="`h-${idx}`"
                      class="dc-pop-chip chip-purple"
                    >
                      #{{ idx }}
                    </span>
                  </div>
                </div>

                <div v-if="part.warm_bots.length > 0" class="dc-pop-section">
                  <div class="dc-pop-sec-title">
                    <span class="dc-dot-sub bg-emerald-500"></span>
                    <span>热备就绪 ({{ part.warm_bots.length }} 个)</span>
                  </div>
                  <div class="dc-pop-chips-wrap">
                    <span
                      v-for="idx in part.warm_bots"
                      :key="`w-${idx}`"
                      class="dc-pop-chip chip-emerald"
                    >
                      #{{ idx }}
                    </span>
                  </div>
                </div>
              </div>
            </el-popover>

            <span v-else class="dc-bot-pills text-slate-400">
              按需跨区拉取
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 第三部分：集群节点实时监控阵列 -->
    <div class="section-title-row">
      <div class="section-title">集群节点实时阵列 ({{ filteredBots.length }})</div>
      <div class="section-subtitle">
        支持免加频道只读分流与管理员读写分离调度，支持单卡独立测速与延迟智能排序
      </div>
    </div>

    <!-- 节点筛选与排序控制条 -->
    <div class="nodes-filter-bar glass-card">
      <div class="filter-pills">
        <button
          v-for="tab in filterTabs"
          :key="tab.key"
          type="button"
          class="filter-pill"
          :class="{ active: activeFilter === tab.key }"
          @click="activeFilter = tab.key"
        >
          <span>{{ tab.label }}</span>
          <span class="pill-count">{{ tab.count }}</span>
        </button>
      </div>

      <div class="filter-right-group">
        <!-- 视图切换: 紧凑矩阵 vs 详细卡片 -->
        <div class="view-mode-selector">
          <el-radio-group v-model="viewMode" size="small" class="view-mode-toggle">
            <el-radio-button value="compact">
              <el-icon><Grid /></el-icon>
              <span class="view-label">紧凑</span>
            </el-radio-button>
            <el-radio-button value="card">
              <el-icon><List /></el-icon>
              <span class="view-label">卡片</span>
            </el-radio-button>
          </el-radio-group>
        </div>

        <!-- 排序选择 -->
        <div class="sort-selector">
          <span class="sort-label">排序:</span>
          <el-select v-model="sortOrder" size="small" class="sort-select">
            <el-option label="默认编号 (#0~#N)" value="default" />
            <el-option label="延迟优先 (低到高)" value="ping_asc" />
            <el-option label="机房分区 (DC1~DC5)" value="dc_asc" />
          </el-select>
        </div>

        <div class="filter-search">
          <el-input
            v-model="searchQuery"
            placeholder="搜索节点 @用户名 或 #编号..."
            clearable
            :prefix-icon="Search"
            class="node-search-input"
          />
        </div>
      </div>
    </div>

    <!-- DC1 极速上传贴士 (当有 DC1 节点但无 DC1 写权限时展示) -->
    <div v-if="hasDc1Worker && !hasDc1Writer" class="dc1-tip-card glass-card mb-4">
      <div class="dc1-tip-inner">
        <div class="dc1-tip-icon-wrap">
          <el-icon :size="20"><Lightning /></el-icon>
        </div>
        <div class="dc1-tip-text">
          <div class="dc1-tip-title">⚡ 极速上传提速贴士：解锁 DC1 极速写入（25~35+ MB/s）</div>
          <div class="dc1-tip-desc">
            检测到集群拥有低时延 <strong>DC1 (美西 67ms)</strong> 节点，当前频道发帖写权限仍由主控（DC5 新加坡，物理时延约 170ms）承担。建议在 Telegram 频道管理中将任意带有 <strong>「⚡ 推荐写节点」</strong> 标识的 DC1 从机拉入频道并赋予发帖管理员权限，系统探测后将自动切换至 DC1 极速上传通道，将转存速度从 7~9 MB/s 提升至 <strong>25~35+ MB/s</strong>！
          </div>
        </div>
      </div>
    </div>

    <!-- 紧凑矩阵视图 (Compact Grid) -->
    <div v-if="viewMode === 'compact'" class="compact-nodes-grid">
      <div
        v-for="bot in paginatedBots"
        :key="bot.index"
        class="compact-node-card glass-card"
        :class="`node-mode-${bot.mode}`"
      >
        <div class="compact-top">
          <div class="compact-id-group">
            <span class="compact-idx">#{{ bot.index }}</span>
            <a
              v-if="cleanUsername(bot.username)"
              :href="`https://t.me/${cleanUsername(bot.username)}`"
              target="_blank"
              rel="noopener noreferrer"
              class="compact-uname"
              :title="`@${cleanUsername(bot.username)}`"
            >
              @{{ cleanUsername(bot.username) }}
            </a>
            <span v-else class="compact-uname text-slate-400">#{{ bot.index }}</span>
          </div>

          <div class="compact-badges">
            <span v-if="bot.home_dc" class="dc-node-pill" :class="`dc-pill-${bot.home_dc}`">
              DC{{ bot.home_dc }}
            </span>
            <span v-if="bot.home_dc === 1 && !bot.can_write" class="node-dc1-rec-badge" title="推荐拉入频道设为发帖管理员">
              ⚡DC1
            </span>
            <span v-else-if="bot.home_dc === 1 && bot.can_write" class="node-dc1-active-badge">
              🚀DC1
            </span>
            <span class="compact-mode-badge" :class="`badge-${bot.mode}`">
              {{ bot.index === 0 ? "主控" : (bot.mode === "direct_admin" ? "可写" : (bot.mode === "no_join_resolved" ? "免加" : "未活")) }}
            </span>
          </div>
        </div>

        <div class="compact-metrics">
          <div class="compact-metric-item">
            <span class="m-lbl">延迟</span>
            <span
              v-if="nodeBenchmarkMap[bot.index]"
              class="m-val"
              :class="`text-${nodeBenchmarkMap[bot.index].grade}`"
            >
              {{ nodeBenchmarkMap[bot.index].ping_ms }}ms
            </span>
            <span v-else class="m-val text-slate-400">--</span>
          </div>

          <div class="compact-metric-item">
            <span class="m-lbl">机房</span>
            <span class="m-val text-purple-500 font-bold">
              DC{{ nodeBenchmarkMap[bot.index]?.dc_id || bot.home_dc || 5 }}
            </span>
          </div>

          <div class="compact-metric-item">
            <span class="m-lbl">负载</span>
            <span class="m-val" :class="getBotWorkload(bot.index) > 0 ? 'text-sky-500 font-bold' : 'text-slate-400'">
              {{ getBotWorkload(bot.index) }}
            </span>
          </div>
        </div>

        <div class="compact-footer">
          <div class="compact-caps">
            <span class="cap-mini-dot" :class="{ active: bot.can_read }" title="流播读取">R</span>
            <span class="cap-mini-dot" :class="{ active: bot.can_write }" title="频道写入">W</span>
          </div>

          <div class="compact-actions">
            <el-button
              size="small"
              text
              class="c-act-btn"
              :loading="benchmarkingIndex === bot.index"
              @click="handleBenchmarkSingle(bot)"
            >
              探活
            </el-button>
            <el-button
              size="small"
              text
              class="c-act-btn"
              @click="copyBotUsername(bot.username)"
            >
              复制
            </el-button>
            <template v-if="bot.index !== 0">
              <el-button
                size="small"
                type="danger"
                text
                class="c-act-btn c-act-del"
                :loading="removingIndex === bot.index"
                @click="handleRemoveBot(bot)"
              >
                下线
              </el-button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 详细卡片网格视图 (Card Grid) -->
    <el-row v-else :gutter="14" class="nodes-grid-row">
      <el-col
        v-for="bot in paginatedBots"
        :key="bot.index"
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        class="node-col"
      >
        <div class="bot-node-card glass-card" :class="`node-mode-${bot.mode}`">
          <div class="node-card-top">
            <span class="node-index-badge">#{{ bot.index }}</span>
            <div class="top-badges-right">
              <!-- 测速标签 -->
              <span
                v-if="nodeBenchmarkMap[bot.index]"
                class="node-ping-badge"
                :class="`ping-${nodeBenchmarkMap[bot.index].grade}`"
                :title="`延迟: ${nodeBenchmarkMap[bot.index].ping_ms}ms, 评级: ${nodeBenchmarkMap[bot.index].grade_label}`"
              >
                {{ nodeBenchmarkMap[bot.index].ping_ms }}ms
              </span>
              <span
                v-if="nodeBenchmarkMap[bot.index]?.download_speed_mbps"
                class="node-speed-badge"
                title="实测单连接下载流速"
              >
                {{ nodeBenchmarkMap[bot.index].download_speed_mbps }}MB/s
              </span>
              <span
                v-if="nodeBenchmarkMap[bot.index]?.playback_bitrate_mbps"
                class="node-playback-badge"
                title="实测单连接播放码率"
              >
                {{ nodeBenchmarkMap[bot.index].playback_bitrate_mbps }}Mbps
              </span>
              <!-- DC1 写节点加速推荐/激活标签 -->
              <span
                v-if="bot.home_dc === 1 && !bot.can_write"
                class="node-dc1-rec-badge"
                title="DC1 美西物理时延仅 67ms，推荐将此 Bot 拉入频道设为发帖管理员以解锁 25~35+ MB/s 极速上传"
              >
                ⚡ 推荐写节点
              </span>
              <span
                v-else-if="bot.home_dc === 1 && bot.can_write"
                class="node-dc1-active-badge"
                title="已激活 DC1 极速写节点 (67ms 低时延，可达 25~35+ MB/s)"
              >
                🚀 极速写节点
              </span>
              <!-- 接入模式标签 -->
              <span class="node-mode-badge" :class="`badge-${bot.mode}`">
                {{ formatBotMode(bot.mode) }}
              </span>
            </div>
          </div>

          <div class="node-identity">
            <div class="node-avatar" :class="`avatar-${bot.mode}`">
              <el-icon :size="20"><Cpu v-if="bot.index === 0" /><Connection v-else /></el-icon>
            </div>
            <div class="node-name-wrap">
              <a
                v-if="cleanUsername(bot.username)"
                :href="`https://t.me/${cleanUsername(bot.username)}`"
                target="_blank"
                rel="noopener noreferrer"
                class="node-username"
              >
                @{{ cleanUsername(bot.username) }}
              </a>
              <span v-else class="node-username">未命名节点 #{{ bot.index }}</span>
              <span class="node-role-sub">
                {{ bot.index === 0 ? 'Primary Stream Controller' : 'Load Balance Worker' }}
              </span>
            </div>
          </div>

          <!-- 权限与负载标签 -->
          <div class="node-capabilities">
            <div class="cap-item" :class="{ enabled: bot.can_read }">
              <span class="cap-dot"></span>
              <span>流播读取: {{ bot.can_read ? '就绪' : '受限' }}</span>
            </div>
            <div class="cap-item" :class="{ enabled: bot.can_write }">
              <span class="cap-dot"></span>
              <span>频道转存: {{ bot.can_write ? '可写' : '只读分流' }}</span>
            </div>
          </div>

          <!-- DC 分区信息 -->
          <div class="node-dc-box">
            <div class="dc-info-left">
              <span class="dc-info-lbl">归属:</span>
              <span v-if="bot.home_dc" class="dc-node-pill" :class="`dc-pill-${bot.home_dc}`">
                DC{{ bot.home_dc }}
              </span>
              <span v-else class="text-slate-400 text-xs">检测中</span>
            </div>
            <div v-if="bot.warm_dcs && bot.warm_dcs.length > 0" class="dc-info-right">
              <span class="dc-info-lbl">热备:</span>
              <span class="dc-warm-tags">
                {{ bot.warm_dcs.map((d: number) => `DC${d}`).join(', ') }}
              </span>
            </div>
          </div>

          <!-- 实时负载条 -->
          <div class="node-workload-box">
            <div class="wl-header">
              <span class="wl-label">当前并发负载</span>
              <span class="wl-val">{{ getBotWorkload(bot.index) }} 活跃连接</span>
            </div>
            <div class="wl-bar-bg">
              <div
                class="wl-bar-fill"
                :style="{ width: `${Math.min(100, getBotWorkload(bot.index) * 15)}%` }"
              ></div>
            </div>
          </div>

          <!-- 底部操作栏 -->
          <div class="node-card-footer">
            <div class="footer-left-btns">
              <el-button
                size="small"
                text
                class="card-bench-btn"
                :icon="Lightning"
                :loading="benchmarkingIndex === bot.index"
                @click="handleBenchmarkSingle(bot)"
              >
                探活 / Ping
              </el-button>
              <el-button
                size="small"
                text
                :icon="CopyDocument"
                @click="copyBotUsername(bot.username)"
              >
                复制
              </el-button>
            </div>

            <template v-if="bot.index === 0">
              <span class="primary-lock-tag">核心主控保护</span>
            </template>
            <template v-else>
              <a
                v-if="bot.mode === 'unreachable' && bot.invite_url"
                :href="bot.invite_url"
                target="_blank"
                rel="noopener noreferrer"
                class="invite-link-btn"
              >
                一键加管
              </a>
              <el-button
                size="small"
                type="danger"
                text
                :icon="Delete"
                :loading="removingIndex === bot.index"
                @click="handleRemoveBot(bot)"
              >
                安全下线
              </el-button>
            </template>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 节点阵列分页导航栏 -->
    <div v-if="sortedAndFilteredBots.length > 0" class="nodes-pagination-bar glass-card">
      <div class="pagination-info">
        共 <span class="font-bold text-sky-600">{{ sortedAndFilteredBots.length }}</span> 个节点
        <template v-if="sortedAndFilteredBots.length > pageSize">
          · 当前展示第 <span class="font-bold">{{ (currentPage - 1) * pageSize + 1 }}</span> ~ <span class="font-bold">{{ Math.min(currentPage * pageSize, sortedAndFilteredBots.length) }}</span> 个
        </template>
      </div>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[12, 24, 48, 96]"
        :total="sortedAndFilteredBots.length"
        layout="sizes, prev, pager, next, jumper"
        background
        size="small"
        class="nodes-pagination"
      />
    </div>

    <!-- 快速批量添加 Token 模态框 -->
    <el-dialog
      v-model="hotAddDialogVisible"
      title="快速热挂载 Bot Token"
      width="500px"
      append-to-body
    >
      <div class="dialog-body">
        <p class="dialog-tip">
          支持一次性粘贴单个或多个由 @BotFather 签发的 Bot Token（每行一个或逗号分隔）。系统将自动完成连接验证与免加频道 Peer 解析，无需重启容器即刻生效。
        </p>
        <el-input
          v-model="hotAddTokensInput"
          type="textarea"
          :rows="6"
          placeholder="例如:&#10;8637803278:AAFTaV5R-w19GvpXagT4G7Bu38j47OsNG6k&#10;8664284654:AAHG4ArES0reOY7J06v6_qi6XUhqLuYoYoI"
        />
      </div>
      <template #footer>
        <el-button @click="hotAddDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="hotAdding"
          @click="handleHotAddSubmit"
        >
          立即热挂载入网
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue"
import { useRouter } from "vue-router"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  RefreshRight,
  Plus,
  Connection,
  Lightning,
  Promotion,
  MagicStick,
  Aim,
  Search,
  CopyDocument,
  Delete,
  Odometer,
  Grid,
  List,
  Cpu,
} from "@element-plus/icons-vue"
import {
  getStatus,
  hotAddBots,
  hotRemoveBot,
  reprobeBots,
  benchmarkBot,
  benchmarkAllBots,
  type BotBenchmarkResult,
  type BotClusterBenchmarkResponse,
} from "@/api"
import type { BotDetail, ChannelInfo, DcPartitionEntry } from "@/types/api"

const router = useRouter()

const loading = ref(false)
const reprobeLoading = ref(false)
const benchmarkLoading = ref(false)
const benchmarkingIndex = ref<number | null>(null)
const dcPartitions = ref<Record<string, DcPartitionEntry>>({})
const dcPartitionList = computed(() => {
  return Object.values(dcPartitions.value || {}).sort((a, b) => a.dc_id - b.dc_id)
})

function cleanDcRegion(label: string): string {
  if (!label) return ""
  return label.replace(/^DC\d\s*\(?/, "").replace(/\)?$/, "").trim()
}

function formatDcDistribution(dcDist?: Record<string, number>): string {
  if (!dcDist || Object.keys(dcDist).length === 0) return "DC5 / DC1 就绪"
  const dcLabels: Record<string, string> = {
    "1": "DC1(美东)",
    "2": "DC2(欧洲)",
    "3": "DC3(美东)",
    "4": "DC4(荷兰)",
    "5": "DC5(亚太)",
  }
  const parts: string[] = []
  for (const [dc, count] of Object.entries(dcDist)) {
    const lbl = dcLabels[dc] || `DC${dc}`
    parts.push(`${lbl} ${count}`)
  }
  return parts.join(" · ")
}

const hotAdding = ref(false)
const removingIndex = ref<number | null>(null)

const botDetails = ref<BotDetail[]>([])
const channelInfo = ref<ChannelInfo | null>(null)
const workloads = ref<Record<string, number>>({})

const clusterBenchmark = ref<NonNullable<BotClusterBenchmarkResponse["data"]> | null>(null)
const nodeBenchmarkMap = ref<Record<number, BotBenchmarkResult>>({})

const activeFilter = ref<"all" | "no_join" | "admin" | "unreachable">("all")
const searchQuery = ref("")
const sortOrder = ref<"default" | "ping_asc" | "dc_asc">("default")
const viewMode = ref<"compact" | "card">("card")
const currentPage = ref(1)
const pageSize = ref(24)

const hotAddDialogVisible = ref(false)
const hotAddTokensInput = ref("")

const noJoinCount = computed(() =>
  botDetails.value.filter(b => b.mode === "no_join_resolved").length
)

const accessibleCount = computed(() =>
  botDetails.value.filter(b => b.can_read).length
)

const hasDc1Writer = computed(() => botDetails.value.some((b) => b.home_dc === 1 && b.can_write))
const hasDc1Worker = computed(() => botDetails.value.some((b) => b.home_dc === 1 && b.index > 0))

const totalWorkload = computed(() =>
  Object.values(workloads.value).reduce((acc, v) => acc + (Number(v) || 0), 0)
)

const clusterPingColorClass = computed(() => {
  if (!clusterBenchmark.value) return ""
  const p = clusterBenchmark.value.avg_ping_ms
  if (p < 100) return "text-emerald-500"
  if (p < 250) return "text-sky-500"
  if (p < 500) return "text-amber-500"
  return "text-red-500"
})

const filterTabs = computed(() => [
  { key: "all" as const, label: "全部节点", count: botDetails.value.length },
  { key: "no_join" as const, label: "免加频道就绪", count: botDetails.value.filter(b => b.mode === "no_join_resolved").length },
  { key: "admin" as const, label: "管理员节点", count: botDetails.value.filter(b => b.mode === "primary_admin" || b.mode === "direct_admin").length },
  { key: "unreachable" as const, label: "未激活", count: botDetails.value.filter(b => b.mode === "unreachable").length },
])

const filteredBots = computed(() => {
  // alias for template
  return sortedAndFilteredBots.value
})

const paginatedBots = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return sortedAndFilteredBots.value.slice(start, start + pageSize.value)
})

watch([activeFilter, searchQuery, sortOrder, pageSize], () => {
  currentPage.value = 1
})

const sortedAndFilteredBots = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return botDetails.value.filter(bot => {
    if (activeFilter.value === "no_join" && bot.mode !== "no_join_resolved") return false
    if (activeFilter.value === "admin" && bot.mode !== "primary_admin" && bot.mode !== "direct_admin") return false
    if (activeFilter.value === "unreachable" && bot.mode !== "unreachable") return false
    if (q) {
      const u = (bot.username || "").toLowerCase()
      const idxStr = String(bot.index)
      return u.includes(q) || idxStr === q
    }
    return true
  }).sort((a, b) => {
    if (sortOrder.value === "ping_asc") {
      const pA = nodeBenchmarkMap.value[a.index]?.ping_ms ?? 99999
      const pB = nodeBenchmarkMap.value[b.index]?.ping_ms ?? 99999
      return pA - pB
    }
    if (sortOrder.value === "dc_asc") {
      const dcA = a.home_dc ?? nodeBenchmarkMap.value[a.index]?.dc_id ?? 5
      const dcB = b.home_dc ?? nodeBenchmarkMap.value[b.index]?.dc_id ?? 5
      if (dcA !== dcB) return dcA - dcB
      return a.index - b.index
    }
    return a.index - b.index
  })
})

function cleanUsername(uname?: string): string {
  if (!uname) return ""
  return uname.replace(/^@/, "")
}

function formatBotMode(mode?: string): string {
  const map: Record<string, string> = {
    primary_admin: "主控 (管理员)",
    direct_admin: "分流+转存就绪",
    no_join_resolved: "免加频道分流就绪",
    unreachable: "未激活 (私密频道)",
  }
  return map[mode || ""] || mode || "未知"
}

function getBotWorkload(index: number): number {
  return Number(workloads.value[String(index)] || 0)
}

async function fetchClusterStatus() {
  const statusRes = await getStatus()
  botDetails.value = statusRes.bot_details || []
  channelInfo.value = statusRes.channel_info || null
  workloads.value = statusRes.workloads || {}
  if (statusRes.dc_partitions) {
    dcPartitions.value = statusRes.dc_partitions
  }
}

async function fetchAllData() {
  loading.value = true
  try {
    await fetchClusterStatus()
  } finally {
    loading.value = false
  }
}

async function handleBenchmarkAll() {
  benchmarkLoading.value = true
  try {
    const res = await benchmarkAllBots(false)
    if (res.success && res.data) {
      clusterBenchmark.value = res.data
      for (const node of (res.data?.nodes || [])) {
        nodeBenchmarkMap.value[node.index] = node
      }
      ElMessage.success(res.data.summary)
    } else {
      ElMessage.error(res.error || "全网健康巡检失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "全网健康巡检异常")
  } finally {
    benchmarkLoading.value = false
  }
}

async function handleBenchmarkSingle(bot: BotDetail) {
  benchmarkingIndex.value = bot.index
  try {
    const res = await benchmarkBot(bot.index, false)
    if (res.success && res.data) {
      nodeBenchmarkMap.value[bot.index] = res.data
      ElMessage.success(`节点 #${bot.index} 探活完成：延迟 ${res.data.ping_ms}ms (${res.data.grade_label}) · DC${res.data.dc_id || bot.home_dc || 5}`)
    } else {
      ElMessage.error(res.error || `节点 #${bot.index} 探活失败`)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || `节点 #${bot.index} 探活异常`)
  } finally {
    benchmarkingIndex.value = null
  }
}

async function handleReprobe() {
  reprobeLoading.value = true
  try {
    const res = await reprobeBots()
    if (res.success && res.data) {
      ElMessage.success(`已完成 ${res.data.probed_count} 个从节点权限重探，可读分流节点: ${res.data.accessible_bots}`)
      await fetchClusterStatus()
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "重探失败")
  } finally {
    reprobeLoading.value = false
  }
}

async function handleHotAddSubmit() {
  const raw = hotAddTokensInput.value.trim()
  if (!raw) {
    ElMessage.warning("请粘贴至少一个有效的 Bot Token")
    return
  }
  hotAdding.value = true
  try {
    const res = await hotAddBots(raw)
    if (res.success && res.data) {
      ElMessage.success(`成功挂载 ${res.data.total_added} 个机器人节点`)
      hotAddDialogVisible.value = false
      hotAddTokensInput.value = ""
      await fetchClusterStatus()
    } else {
      ElMessage.error(res.error || "挂载失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "热挂载失败")
  } finally {
    hotAdding.value = false
  }
}

async function handleRemoveBot(bot: BotDetail) {
  try {
    await ElMessageBox.confirm(
      `确定要将节点 #${bot.index} (@${cleanUsername(bot.username)}) 从负载均衡集群中安全下线并移除吗？`,
      "节点下线确认",
      {
        confirmButtonText: "确认下线",
        cancelButtonText: "取消",
        type: "warning",
      }
    )
  } catch {
    return
  }

  removingIndex.value = bot.index
  try {
    const res = await hotRemoveBot(bot.index)
    if (res.success) {
      ElMessage.success(`节点 #${bot.index} 已安全下线`)
      await fetchClusterStatus()
    } else {
      ElMessage.error(res.error || "下线失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "下线失败")
  } finally {
    removingIndex.value = null
  }
}

function copyBotUsername(uname?: string) {
  const clean = cleanUsername(uname)
  if (!clean) return
  navigator.clipboard?.writeText(`@${clean}`)
  ElMessage.success(`已复制 @${clean}`)
}

onMounted(async () => {
  await fetchAllData()
  void handleBenchmarkAll()
})
</script>

<style scoped>
.bots-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-bottom: 28px;
  max-width: 100%;
  overflow-x: hidden;
}

.bots-header-card {
  padding: 22px 24px;
  border-radius: 20px;
}

.bots-header-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.bots-title-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bots-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.bots-title {
  font-size: 24px;
  font-weight: 800;
  margin: 0;
  letter-spacing: -0.3px;
}

.bots-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.14), rgba(56, 189, 248, 0.14));
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.28);
}

.bots-subtitle {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}

.bots-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
}

.speed-test-btn {
  border-color: rgba(16, 185, 129, 0.35);
  color: #059669;
  background: rgba(16, 185, 129, 0.08);
}

.speed-test-btn:hover {
  background: rgba(16, 185, 129, 0.16);
  border-color: #10b981;
}

.test-btn {
  border-color: rgba(56, 189, 248, 0.35);
  color: #0284c7;
  background: rgba(56, 189, 248, 0.08);
}

.primary-glow-btn {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  border: none;
  box-shadow: 0 6px 16px rgba(255, 117, 151, 0.28);
}

/* 顶部统计卡片 */
.stats-row {
  row-gap: 12px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(255, 143, 171, 0.18);
  transition: all 0.25s ease;
  height: 100%;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 22px rgba(255, 117, 151, 0.12);
}

.stat-icon-wrapper {
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-icon-nodes {
  background: linear-gradient(135deg, #ff7597, #fb7185);
}

.stat-icon-nojoin {
  background: linear-gradient(135deg, #38bdf8, #0284c7);
}

.stat-icon-speed {
  background: linear-gradient(135deg, #10b981, #059669);
}

.stat-icon-channel {
  background: linear-gradient(135deg, #f472b6, #38bdf8);
}

.stat-info {
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: 20px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-unit {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.stat-value-sky {
  color: #0284c7;
}

.stat-value-pink {
  color: #db2777;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-progress {
  margin-top: 6px;
  height: 5px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.8);
  overflow: hidden;
}

.stat-progress-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #ff7597, #38bdf8);
}

/* 测速综合报告面板 */
.cluster-benchmark-card {
  padding: 18px 20px;
  border-radius: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.benchmark-summary-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.benchmark-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bench-time {
  font-size: 12px;
  color: #64748b;
}

.re-bench-btn {
  border-radius: 8px;
  font-size: 12px;
}

.benchmark-kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.bench-kpi-item {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.kpi-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
}

.kpi-value {
  font-size: 18px;
  font-weight: 800;
  line-height: 1.3;
}

.kpi-sub-name {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.kpi-sub {
  font-size: 11px;
  color: #94a3b8;
}

/* 分区标题 */
.section-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 0 4px;
}

.section-title {
  font-size: 17px;
  font-weight: 800;
  color: #1e293b;
}

.section-subtitle {
  font-size: 12px;
  color: #64748b;
}

/* 铸造控制台 */
.mint-console-row {
  row-gap: 16px;
}

.mint-config-card,
.mint-monitor-card {
  padding: 20px;
  border-radius: 18px;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.card-header-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.card-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-pink { background: #ff7597; }
.dot-sky { background: #38bdf8; }
.dot-amber { background: #f59e0b; }
.dot-emerald { background: #10b981; }
.dot-red { background: #ef4444; }
.dot-slate { background: #94a3b8; }

.card-title {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.card-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
}

.cached-sessions-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 241, 245, 0.75);
  border: 1px dashed rgba(255, 117, 151, 0.35);
}

.cached-label {
  font-size: 12px;
  font-weight: 600;
  color: #be185d;
}

.cached-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cached-phone-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #fff;
  color: #334155;
  border: 1px solid rgba(255, 117, 151, 0.3);
  cursor: pointer;
  transition: all 0.2s ease;
}

.cached-phone-pill:hover,
.cached-phone-pill.active {
  background: linear-gradient(135deg, #ff7597, #38bdf8);
  color: #fff;
  border-color: transparent;
}

.input-mode-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  background: rgba(241, 245, 249, 0.85);
  padding: 4px;
  border-radius: 12px;
}

.mode-tab-btn {
  padding: 7px 8px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.mode-tab-btn.active {
  background: #fff;
  color: #ff7597;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.session-upload-box {
  width: 100%;
  padding: 18px;
  border-radius: 12px;
  border: 2px dashed rgba(56, 189, 248, 0.4);
  background: rgba(240, 249, 255, 0.5);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.hidden-file-input {
  display: none;
}

.upload-icon {
  color: #38bdf8;
}

.upload-text {
  font-size: 12px;
  color: #475569;
}

.slider-with-num {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.reuse-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.9);
  margin-bottom: 12px;
}

.reuse-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.reuse-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.reuse-desc {
  font-size: 11px;
  color: #64748b;
}

.mint-actions-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* 右侧监控面板 */
.task-status-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
}

.status-idle { background: #f1f5f9; color: #64748b; }
.status-running { background: rgba(56, 189, 248, 0.15); color: #0284c7; }
.status-cooling_down { background: rgba(245, 158, 11, 0.16); color: #d97706; }
.status-completed { background: rgba(16, 185, 129, 0.15); color: #059669; }
.status-stopped { background: rgba(148, 163, 184, 0.2); color: #475569; }
.status-failed { background: rgba(239, 68, 68, 0.14); color: #dc2626; }

.mint-progress-box {
  padding: 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 143, 171, 0.18);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-step-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.step-pct {
  color: #ff7597;
  font-weight: 800;
}

.mint-metrics-mini {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
}

.mini-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.mini-label {
  font-size: 11px;
  color: #64748b;
}

.mini-val {
  font-size: 16px;
  font-weight: 800;
  color: #1e293b;
}

.cooldown-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(254, 243, 199, 0.8);
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: #92400e;
}

.cd-icon {
  font-size: 18px;
  margin-top: 2px;
  color: #d97706;
}

.cd-title {
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}

.cd-timer {
  padding: 1px 8px;
  border-radius: 999px;
  background: #d97706;
  color: #fff;
  font-size: 11px;
}

.cd-desc {
  font-size: 12px;
  margin-top: 2px;
  line-height: 1.4;
}

/* 终端日志 */
.mint-terminal {
  flex: 1;
  min-height: 210px;
  max-height: 270px;
  border-radius: 14px;
  background: #0f172a;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.terminal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #1e293b;
  font-size: 12px;
  color: #94a3b8;
}

.terminal-dots {
  display: flex;
  gap: 6px;
}

.t-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.t-dot.red { background: #ef4444; }
.t-dot.yellow { background: #f59e0b; }
.t-dot.green { background: #10b981; }

.terminal-body {
  flex: 1;
  padding: 12px 14px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.terminal-empty {
  color: #64748b;
}

.terminal-line {
  display: flex;
  gap: 8px;
  word-break: break-all;
}

.log-time { color: #64748b; flex-shrink: 0; }
.log-level { font-weight: 700; flex-shrink: 0; }
.log-info .log-level { color: #38bdf8; }
.log-success .log-level, .log-success .log-msg { color: #34d399; }
.log-warn .log-level, .log-warn .log-msg { color: #fbbf24; }
.log-error .log-level, .log-error .log-msg { color: #f87171; }

/* 节点筛选与排序栏 */
.nodes-filter-bar {
  padding: 12px 16px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-pills {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  background: rgba(241, 245, 249, 0.85);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-pill.active {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.16), rgba(56, 189, 248, 0.16));
  color: #ff7597;
  border-color: rgba(255, 117, 151, 0.35);
}

.pill-count {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.85);
}

.filter-right-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.sort-selector {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sort-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.sort-select {
  width: 150px;
}

.filter-search {
  width: 220px;
  max-width: 100%;
}

/* 节点网格卡片 */
.nodes-grid-row {
  row-gap: 14px;
}

.bot-node-card {
  padding: 16px;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  transition: all 0.25s ease;
}

.bot-node-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 24px rgba(255, 117, 151, 0.14);
}

.node-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.top-badges-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.node-index-badge {
  font-size: 12px;
  font-weight: 800;
  padding: 2px 9px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
}

/* 测速徽标 */
.node-ping-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  letter-spacing: -0.2px;
}

.ping-excellent {
  background: rgba(16, 185, 129, 0.15);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.ping-good {
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.ping-moderate {
  background: rgba(245, 158, 11, 0.16);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.ping-slow, .ping-error {
  background: rgba(239, 68, 68, 0.14);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.node-speed-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(244, 114, 182, 0.14);
  color: #db2777;
  border: 1px solid rgba(244, 114, 182, 0.28);
}

.node-mode-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 999px;
}

.badge-primary_admin {
  background: rgba(139, 92, 246, 0.14);
  color: #7c3aed;
}

.badge-direct_admin {
  background: rgba(16, 185, 129, 0.14);
  color: #059669;
}

.badge-no_join_resolved {
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
}

.badge-unreachable {
  background: rgba(245, 158, 11, 0.16);
  color: #d97706;
}

.node-identity {
  display: flex;
  align-items: center;
  gap: 12px;
}

.node-avatar {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  background: linear-gradient(135deg, #38bdf8, #0284c7);
}

.avatar-primary_admin {
  background: linear-gradient(135deg, #8b5cf6, #ec4899);
}

.avatar-direct_admin {
  background: linear-gradient(135deg, #10b981, #059669);
}

.node-name-wrap {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.node-username {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-username:hover {
  color: #ff7597;
}

.node-role-sub {
  font-size: 11px;
  color: #64748b;
}

.node-capabilities {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.85);
}

.cap-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #94a3b8;
}

.cap-item.enabled {
  color: #334155;
  font-weight: 600;
}

.cap-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.cap-item.enabled .cap-dot {
  background: #10b981;
}

.node-workload-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.wl-header {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #64748b;
}

.wl-val {
  font-weight: 700;
  color: #0284c7;
}

.wl-bar-bg {
  height: 5px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.wl-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #38bdf8, #ff7597);
}

.node-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
}

.footer-left-btns {
  display: flex;
  align-items: center;
  gap: 4px;
}

.card-bench-btn {
  color: #059669;
}

.card-bench-btn:hover {
  background: rgba(16, 185, 129, 0.1);
  color: #047857;
}

.primary-lock-tag {
  font-size: 11px;
  font-weight: 600;
  color: #8b5cf6;
  background: rgba(139, 92, 246, 0.1);
  padding: 2px 8px;
  border-radius: 6px;
}

.invite-link-btn {
  font-size: 12px;
  font-weight: 600;
  color: #d97706;
  text-decoration: none;
}

.dialog-tip {
  font-size: 13px;
  color: #475569;
  margin-top: 0;
  margin-bottom: 12px;
  line-height: 1.5;
}


/* ==================== 协议号资产池与双模铸造样式 ==================== */
.account-pool-card {
  padding: 18px 20px;
  border-radius: 18px;
}

.pool-quota-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.12), rgba(56, 189, 248, 0.14));
  color: #db2777;
  border: 1px solid rgba(255, 117, 151, 0.3);
}

.pool-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.account-pool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.account-item-card {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(226, 232, 240, 0.9);
  transition: all 0.25s ease;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.account-item-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -6px rgba(56, 189, 248, 0.18);
  border-color: rgba(56, 189, 248, 0.45);
}

.account-item-card.active-selected {
  border-color: rgba(255, 117, 151, 0.55);
  background: linear-gradient(145deg, rgba(255, 245, 247, 0.75), rgba(240, 249, 255, 0.8));
}

.account-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.acc-status-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}

.acc-status-active {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.acc-status-limit_reached {
  background: rgba(245, 158, 11, 0.14);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.acc-status-cooling_down {
  background: rgba(56, 189, 248, 0.14);
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.35);
}

.acc-status-restricted,
.acc-status-invalid {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.acc-quota-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #475569;
}

.acc-quota-rem {
  font-weight: 600;
  color: #0284c7;
}

.acc-progress-bar-bg {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.8);
  overflow: hidden;
}

.acc-progress-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #ff7597, #38bdf8);
  transition: width 0.3s ease;
}

.acc-progress-bar-fill.fill-limit {
  background: linear-gradient(90deg, #f59e0b, #ef4444);
}

.account-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 4px;
  border-top: 1px dashed rgba(226, 232, 240, 0.8);
}

.acc-type-text {
  font-size: 11px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}

.acc-btn-group {
  display: flex;
  align-items: center;
  gap: 2px;
}

.single-mint-quick-btn {
  color: #db2777 !important;
  font-weight: 600;
  padding: 0 4px;
}

.check-account-btn {
  color: #0284c7 !important;
  padding: 0 4px;
}

.delete-account-btn {
  padding: 0 4px;
}

.account-pool-empty {
  margin-top: 12px;
  padding: 18px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.7);
  border: 1px dashed rgba(203, 213, 225, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
}

/* 双模切换 Segmented 选项卡 */
.mint-strategy-tabs {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  padding: 5px;
  border-radius: 14px;
  background: rgba(241, 245, 249, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.9);
  margin-bottom: 14px;
}

.strategy-tab-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-wrap: wrap;
}

.strategy-tab-btn.active {
  background: #ffffff;
  color: #db2777;
  border-color: rgba(255, 117, 151, 0.4);
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.14);
}

.strategy-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 117, 151, 0.12);
  color: #db2777;
}

.strategy-setting-box {
  margin-bottom: 14px;
  padding: 12px;
  border-radius: 12px;
  background: rgba(240, 249, 255, 0.55);
  border: 1px solid rgba(186, 230, 253, 0.7);
}

.strategy-desc-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  color: #0369a1;
  line-height: 1.5;
}

.strategy-desc-banner.single-banner {
  color: #be185d;
}

.relay-select-wrap {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed rgba(186, 230, 253, 0.8);
}

.relay-select-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.relay-select-label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.relay-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.relay-checkbox-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(203, 213, 225, 0.8);
  cursor: pointer;
  user-select: none;
}

.relay-checkbox-item.selected {
  border-color: #38bdf8;
  background: rgba(224, 242, 254, 0.65);
  color: #0369a1;
  font-weight: 600;
}

.relay-checkbox-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.acc-bot-count {
  font-size: 11px;
  color: #64748b;
}

.single-account-picker-item {
  margin-top: 10px;
  margin-bottom: 0;
}

.supplement-input-toggle {
  margin-bottom: 10px;
}

.supplement-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}

.current-account-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border-radius: 10px;
  background: linear-gradient(90deg, rgba(56, 189, 248, 0.12), rgba(255, 117, 151, 0.12));
  border: 1px solid rgba(56, 189, 248, 0.35);
  margin-bottom: 10px;
  font-size: 12px;
}

.curr-acc-label {
  color: #475569;
  font-weight: 600;
}

.curr-acc-phone {
  color: #0284c7;
  font-weight: 700;
  font-family: monospace;
}

.curr-acc-index {
  color: #db2777;
  font-weight: 600;
}

.curr-acc-mode {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  color: #db2777;
  font-weight: 600;
}

.account-history-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 12px;
}

.hist-label {
  font-weight: 600;
  color: #64748b;
}

.hist-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hist-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  color: #334155;
  border: 1px solid rgba(203, 213, 225, 0.8);
}

.hist-limit_reached {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.35);
}

.batch-upload-dropzone {
  width: 100%;
  padding: 18px;
  border-radius: 12px;
  border: 2px dashed rgba(56, 189, 248, 0.45);
  background: rgba(240, 249, 255, 0.45);
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.batch-upload-dropzone:hover {
  border-color: #ff7597;
  background: rgba(255, 241, 242, 0.45);
}

.file-list-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.file-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
}

.import-result-box {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.9);
  font-size: 12px;
}

.result-errors {
  margin-top: 6px;
  max-height: 100px;
  overflow-y: auto;
  color: #dc2626;
}

@media (max-width: 768px) {
  .mint-strategy-tabs {
    grid-template-columns: 1fr;
  }

  .account-pool-grid {
    grid-template-columns: 1fr;
  }

  .pool-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .stream-bench-controls {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }

  .bench-ctrl-item {
    width: 100%;
    justify-content: space-between;
  }

  .bench-bot-select {
    flex: 1;
  }

  .start-stream-bench-btn {
    width: 100%;
  }

  .subcard-main-stat {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }

  .bots-page {
    padding: 0 !important;
  }

  .bots-header-card {
    padding: 14px !important;
    border-radius: 14px !important;
  }

  .bots-header-actions {
    flex-direction: column !important;
    width: 100% !important;
  }

  .bots-header-actions > * {
    width: 100% !important;
    justify-content: center !important;
  }

  .compact-nodes-grid {
    grid-template-columns: 1fr !important;
  }

  .bots-title {
    font-size: 20px;
  }

  .benchmark-kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }

  .mint-metrics-mini {
    grid-template-columns: repeat(2, 1fr);
  }

  .filter-right-group {
    width: 100%;
  }

  .sort-selector {
    width: 100%;
    justify-content: space-between;
  }

  .sort-select {
    flex: 1;
  }

  .filter-search {
    width: 100%;
  }
}

/* DC 动态分区亲和矩阵 */
.dc-partition-card {
  padding: 18px 22px;
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dc-matrix-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(168, 85, 247, 0.12);
  color: #9333ea;
  border: 1px solid rgba(168, 85, 247, 0.25);
}

.dc-matrix-hint {
  font-size: 12px;
  color: #64748b;
}

.dc-matrix-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 1100px) {
  .dc-matrix-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .dc-matrix-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 480px) {
  .dc-matrix-grid {
    grid-template-columns: 1fr;
  }
}

.dc-part-item {
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 14px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.2s ease;
  min-width: 0;
  overflow: hidden;
}

.dc-part-item.dc-part-active {
  background: rgba(255, 255, 255, 0.85);
  border-color: rgba(192, 132, 252, 0.35);
  box-shadow: 0 4px 14px rgba(168, 85, 247, 0.06);
}

.dc-part-item.dc-part-idle {
  opacity: 0.72;
}

.dc-part-item:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(56, 189, 248, 0.5);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(56, 189, 248, 0.12);
}

.dc-part-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}

.dc-badge-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 6px;
  flex-shrink: 0;
}

.dc-tag-1 { background: rgba(59, 130, 246, 0.12); color: #2563eb; border: 1px solid rgba(59, 130, 246, 0.25); }
.dc-tag-2 { background: rgba(16, 185, 129, 0.12); color: #059669; border: 1px solid rgba(16, 185, 129, 0.25); }
.dc-tag-3 { background: rgba(245, 158, 11, 0.12); color: #d97706; border: 1px solid rgba(245, 158, 11, 0.25); }
.dc-tag-4 { background: rgba(99, 102, 241, 0.12); color: #4f46e5; border: 1px solid rgba(99, 102, 241, 0.25); }
.dc-tag-5 { background: rgba(236, 72, 153, 0.12); color: #db2777; border: 1px solid rgba(236, 72, 153, 0.25); }

.dc-region-name {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.dc-part-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  padding: 7px 0;
  border-top: 1px solid rgba(241, 245, 249, 0.9);
  border-bottom: 1px solid rgba(241, 245, 249, 0.9);
}

.dc-m-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}

.dc-m-val {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.2;
}

.dc-m-lbl {
  font-size: 10.5px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.dc-part-bots {
  font-size: 11px;
  min-width: 0;
  overflow: hidden;
  display: flex;
  align-items: center;
}

.dc-bot-preview-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  cursor: pointer;
  padding: 1px 4px;
  border-radius: 6px;
  transition: background 0.15s ease;
  min-width: 0;
}

.dc-bot-preview-pill:hover {
  background: rgba(241, 245, 249, 0.8);
}

.dc-bot-type {
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.dc-bot-nums {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.dc-more-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 0 5px;
  border-radius: 999px;
  flex-shrink: 0;
  line-height: 16px;
}

.dc-bot-pills {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* DC Popover 浮层样式 */
.dc-popover-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px;
}

.dc-popover-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
}

.dc-popover-title {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
}

.dc-pop-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dc-pop-sec-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
}

.dc-dot-sub {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.dc-pop-chips-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 120px;
  overflow-y: auto;
  padding: 2px 0;
}

.dc-pop-chips-wrap::-webkit-scrollbar {
  width: 4px;
}

.dc-pop-chips-wrap::-webkit-scrollbar-thumb {
  background: rgba(203, 213, 225, 0.8);
  border-radius: 4px;
}

.dc-pop-chip {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  line-height: 15px;
}

.chip-purple {
  background: rgba(168, 85, 247, 0.12);
  color: #9333ea;
  border: 1px solid rgba(168, 85, 247, 0.2);
}

.chip-emerald {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

/* 卡片内的 DC 信息条 */
.node-dc-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: rgba(248, 250, 252, 0.85);
  border-radius: 8px;
  font-size: 11px;
  gap: 6px;
}

.dc-info-left, .dc-info-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.dc-info-lbl {
  color: #94a3b8;
  font-size: 10px;
}

.dc-node-pill {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.dc-pill-1 { background: rgba(59, 130, 246, 0.15); color: #2563eb; }
.dc-pill-2 { background: rgba(16, 185, 129, 0.15); color: #059669; }
.dc-pill-3 { background: rgba(245, 158, 11, 0.15); color: #d97706; }
.dc-pill-4 { background: rgba(99, 102, 241, 0.15); color: #4f46e5; }
.dc-pill-5 { background: rgba(236, 72, 153, 0.15); color: #db2777; }

.dc-warm-tags {
  color: #059669;
  font-weight: 600;
  font-size: 10px;
}

/* DC1 极速提示卡片 */
.dc1-tip-card {
  padding: 14px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(254, 240, 138, 0.25), rgba(56, 189, 248, 0.15));
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.dc1-tip-inner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.dc1-tip-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.dc1-tip-title {
  font-size: 13px;
  font-weight: 700;
  color: #b45309;
  margin-bottom: 4px;
}

.dc1-tip-desc {
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}

.node-dc1-rec-badge {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(239, 68, 68, 0.15));
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.35);
  animation: pulse-border 2.5s infinite;
}

.node-dc1-active-badge {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(56, 189, 248, 0.15));
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.35);
}

@keyframes pulse-border {
  0%, 100% { border-color: rgba(245, 158, 11, 0.35); }
  50% { border-color: rgba(239, 68, 68, 0.7); box-shadow: 0 0 8px rgba(245, 158, 11, 0.25); }
}


/* 紧凑节点矩阵视图 */
.view-mode-selector {
  display: flex;
  align-items: center;
}

.view-label {
  margin-left: 4px;
  font-size: 12px;
}

.compact-nodes-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 1360px) {
  .compact-nodes-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .compact-nodes-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .load-kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .compact-nodes-grid {
    grid-template-columns: 1fr;
  }
}

.compact-node-card {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(226, 232, 240, 0.85);
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.2s ease;
  min-width: 0;
}

.compact-node-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 18px rgba(56, 189, 248, 0.12);
  border-color: rgba(56, 189, 248, 0.4);
}

.compact-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}

.compact-id-group {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}

.compact-idx {
  font-size: 11px;
  font-weight: 800;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
  flex-shrink: 0;
}

.compact-uname {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.compact-uname:hover {
  color: #ff7597;
}

.compact-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.compact-mode-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
}

.compact-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  background: rgba(248, 250, 252, 0.85);
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px solid rgba(241, 245, 249, 0.9);
}

.compact-metric-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}

.compact-metric-item .m-lbl {
  font-size: 10px;
  color: #94a3b8;
}

.compact-metric-item .m-val {
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.compact-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding-top: 4px;
  border-top: 1px solid rgba(241, 245, 249, 0.9);
}

.compact-caps {
  display: flex;
  align-items: center;
  gap: 3px;
}

.cap-mini-dot {
  font-size: 9px;
  font-weight: 800;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: #f1f5f9;
  color: #94a3b8;
}

.cap-mini-dot.active {
  background: rgba(16, 185, 129, 0.15);
  color: #059669;
}

.compact-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.c-act-btn {
  font-size: 11px;
  padding: 0 4px;
  height: 22px;
  color: #059669;
}

.c-act-btn.c-act-stream {
  color: #0284c7;
}

.c-act-btn.c-act-del {
  color: #dc2626;
}

.nodes-pagination-bar {
  padding: 12px 18px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pagination-info {
  font-size: 12px;
  color: #64748b;
}

.nodes-pagination {
  margin-left: auto;
}

.text-excellent { color: #059669; }
.text-good { color: #0284c7; }
.text-moderate { color: #d97706; }
.text-slow, .text-error { color: #dc2626; }
</style>

.truncate-dc-dist {
  font-size: 13px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
  display: inline-block;
}
