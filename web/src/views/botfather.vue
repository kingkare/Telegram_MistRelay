<template>
  <div class="botfather-page animate-fade-in">
    <!-- 顶部品牌横幅与核心指标 -->
    <div class="botfather-header-card glass-card">
      <div class="bots-header-main">
        <div class="bots-title-group">
          <div class="bots-title-row">
            <h2 class="bots-title text-gradient-sakura">@BotFather 自动化铸造与扩容流水线</h2>
            <span class="bots-badge">BotFather Auto-Minting Pipeline</span>
          </div>
          <p class="bots-subtitle">
            协议号资产池纳管、存量机器人一键探测复用、多号跨账号自动接力铸造与免加频道热插拔挂载，实现集群无缝全自动扩容。
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
            class="header-btn primary-glow-btn open-batch-import-btn"
            :icon="Plus"
            @click="openBatchImportModal"
          >
            批量导入协议号
          </el-button>
          <el-button
            class="header-btn"
            :icon="Promotion"
            @click="hotAddDialogVisible = true"
          >
            挂载 Token
          </el-button>
          <el-button
            class="header-btn cluster-nav-btn"
            :icon="Connection"
            @click="router.push('/bots')"
          >
            集群管理中心
          </el-button>
        </div>
      </div>

      <!-- 顶部 4 大流光指标卡 -->
      <el-row :gutter="14" class="stats-row">
        <!-- 1. 纳管协议号总数 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-accounts">
              <el-icon :size="22"><Iphone /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ protocolAccounts.length }} <span class="stat-unit">个账号</span></div>
              <div class="stat-label">
                有效就绪 {{ protocolAccounts.filter(a => a.status === 'active').length }} / 总纳管 {{ protocolAccounts.length }}
              </div>
            </div>
          </div>
        </el-col>

        <!-- 2. 协议号已持机与配额 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-quota">
              <el-icon :size="22"><MagicStick /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-sky">
                {{ totalBotCountInPool }} <span class="stat-unit">/ {{ Math.max(20, protocolAccounts.length * 20) }}</span>
              </div>
              <div class="stat-label">
                已用配额 · 剩余可建 {{ totalRemainingQuota }} 个
              </div>
              <div class="stat-progress">
                <div
                  class="stat-progress-bar"
                  :style="{ width: `${Math.min(100, (totalBotCountInPool / Math.max(1, protocolAccounts.length * 20)) * 100)}%` }"
                ></div>
              </div>
            </div>
          </div>
        </el-col>

        <!-- 3. 流水线任务状态 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-pipeline">
              <el-icon :size="22"><Timer /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value" :class="taskStatus.status === 'running' ? 'text-sky-500' : 'text-emerald-500'">
                {{ taskStatusLabel }}
              </div>
              <div class="stat-label">
                {{ taskStatus.status === 'running' ? `进度 ${taskStatus.percent}% · 已造 ${taskStatus.created_count}` : `当前集群共 ${botDetails.length} 个节点` }}
              </div>
            </div>
          </div>
        </el-col>

        <!-- 4. 集群当前活跃从机 -->
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-cluster">
              <el-icon :size="22"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-pink">
                {{ botDetails.length }} <span class="stat-unit">节点</span>
              </div>
              <div class="stat-label">
                免加频道就绪 {{ botDetails.filter(b => b.mode === 'no_join_resolved').length }} · 读写就绪 {{ botDetails.filter(b => b.can_read).length }}
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 协议号资产池管理面板 -->
    <div class="account-pool-card glass-card animate-fade-in">
      <div class="card-header-line">
        <div class="card-title-wrap">
          <span class="card-icon-dot dot-pink"></span>
          <h3 class="card-title">Telegram 协议号资产池</h3>
          <span class="pool-quota-badge">
            纳管 {{ protocolAccounts.length }} 个账号 · 已接管 {{ takenOverAccountsCount }}/{{ protocolAccounts.length }} · 已持机 {{ totalBotCountInPool }}/{{ Math.max(20, protocolAccounts.length * 20) }} · 剩余配额 {{ totalRemainingQuota }}
          </span>
        </div>
        <div class="pool-actions">
          <el-button
            size="small"
            class="header-btn sync-pool-btn"
            :icon="RefreshRight"
            :loading="syncingAllAccounts"
            @click="handleSyncAllAccounts"
            title="一键错峰握手探测 @BotFather，全量同步真实持机数、官方档案、DC 与关联租户专属频道"
          >
            ⚡ 全池数据同步
          </el-button>
          <el-button
            size="small"
            class="header-btn"
            :icon="Lock"
            :loading="batchTakingOver"
            @click="handleBatchTakeoverAll"
            :title="pendingTakeoverAccounts.length > 0 ? `当前有 ${pendingTakeoverAccounts.length} 个协议号尚未接管（已接管 ${takenOverAccountsCount} 个将自动跳过）` : `全池 ${protocolAccounts.length} 个协议号均已完成安全接管`"
          >
            🛡️ {{ pendingTakeoverAccounts.length > 0 ? `一键接管 (${pendingTakeoverAccounts.length})` : `全池已接管 (${takenOverAccountsCount})` }}
          </el-button>
          <el-button
            size="small"
            class="header-btn"
            :icon="Cpu"
            :loading="keepaliveAllLoading"
            @click="handleKeepaliveAll"
            title="对所有协议号执行错峰 MTProto 轻量保活"
          >
            一键全量保活
          </el-button>
          <el-button
            size="small"
            class="header-btn"
            :icon="Connection"
            :loading="batchFetchingApi"
            @click="openBatchFetchApiModal"
            title="为所有未配置 API 的协议号按地区匹配家宽代理批量提取凭证"
          >
            批量提取 API
          </el-button>
          <el-button
            size="small"
            class="header-btn"
            :icon="Download"
            @click="openBatchExportTelethonModal"
            title="生成并批量导出全部 Telethon StringSession 凭证"
          >
            导出 Telethon
          </el-button>
          <el-button
            size="small"
            class="header-btn"
            :icon="Setting"
            @click="openKeepaliveConfigModal"
            title="配置协议号后台定时自动保活"
          >
            保活配置
          </el-button>
          <el-button
            size="small"
            class="header-btn open-batch-import-btn primary-glow-btn"
            :icon="Plus"
            @click="openBatchImportModal"
          >
            批量导入协议号
          </el-button>
          <el-button
            size="small"
            class="header-btn"
            :icon="RefreshRight"
            :loading="accountsLoading"
            @click="fetchAccounts"
          >
            刷新资产池
          </el-button>
        </div>
      </div>

      <!-- 搜索、筛选与排序工具栏 -->
      <div v-if="protocolAccounts.length > 0" class="pool-filter-toolbar glass-card">
        <div class="filter-controls-left">
          <el-input
            v-model="accountSearchQuery"
            placeholder="搜索手机号 / 用户名 / UID / 备注 / 地区..."
            :prefix-icon="Search"
            clearable
            size="small"
            class="filter-search-input"
          />

          <el-select
            v-model="accountStatusFilter"
            size="small"
            class="filter-select status-select"
            placeholder="全部状态"
          >
            <el-option label="全部状态" value="all" />
            <el-option label="🟢 正常活跃" value="active" />
            <el-option label="🟠 单号满额 (20/20)" value="limit_reached" />
            <el-option label="🟡 频率冷却中" value="cooling_down" />
            <el-option label="🔴 凭证失效/受限" value="invalid" />
          </el-select>

          <el-select
            v-model="account2faFilter"
            size="small"
            class="filter-select twofa-select"
            placeholder="2FA 状态"
          >
            <el-option label="全部 2FA" value="all" />
            <el-option label="🛡️ 已安全接管" value="taken_over" />
            <el-option label="⚠️ 待接管 / 初始2FA" value="pending" />
          </el-select>

          <el-select
            v-model="accountDcFilter"
            size="small"
            class="filter-select dc-select"
            placeholder="全部 DC"
          >
            <el-option label="全部 DC 区域" value="all" />
            <el-option label="🌐 DC1 (Miami)" value="1" />
            <el-option label="🌐 DC2 (Amsterdam)" value="2" />
            <el-option label="🌐 DC3 (Miami)" value="3" />
            <el-option label="🌐 DC4 (Amsterdam)" value="4" />
            <el-option label="🌐 DC5 (Singapore)" value="5" />
          </el-select>

          <el-select
            v-model="accountChannelFilter"
            size="small"
            class="filter-select channel-select"
            placeholder="租户频道"
          >
            <el-option label="全部频道状态" value="all" />
            <el-option label="🏠 有托管频道" value="has_channels" />
            <el-option label="⚪ 无托管频道 (空闲)" value="no_channels" />
          </el-select>
        </div>

        <div class="filter-controls-right">
          <el-select
            v-model="accountSortOrder"
            size="small"
            class="filter-select sort-select"
            placeholder="排序方式"
          >
            <el-option label="默认排序 (ID)" value="default" />
            <el-option label="租户频道数 ↓ (从多到少)" value="channels_desc" />
            <el-option label="租户频道数 ↑ (从少到多)" value="channels_asc" />
            <el-option label="持机数 ↓ (从多到少)" value="bot_count_desc" />
            <el-option label="持机数 ↑ (从少到多)" value="bot_count_asc" />
            <el-option label="保活延迟优先 (Ping 升序)" value="ping_asc" />
            <el-option label="最近保活时间 (最新优先)" value="keepalive_desc" />
          </el-select>

          <el-button
            size="small"
            class="filter-reset-btn"
            @click="resetAccountFilters"
            :disabled="!hasActiveAccountFilters"
          >
            重置
          </el-button>
        </div>
      </div>

      <!-- 资产池账号列表卡片网格 -->
      <div v-if="paginatedAccounts.length > 0" class="account-pool-grid">
        <div
          v-for="acc in paginatedAccounts"
          :key="acc.id || acc.phone"
          class="account-item-card"
          :class="{
            'active-selected': (mintStrategy === 'single' && selectedSingleAccountId === acc.id) || (mintStrategy === 'relay' && selectedRelayAccountIds.includes(acc.id)),
            'status-limit': acc.status === 'limit_reached',
            'status-cooling': acc.status === 'cooling_down',
            'status-invalid': acc.status === 'invalid'
          }"
        >
          <div class="account-card-top">
            <button
              type="button"
              class="cached-phone-pill"
              :class="{ active: mintForm.sessionString.startsWith(acc.phone) }"
              @click="selectCachedPhone(acc.phone)"
              title="点击快速选中并填入输入框"
            >
              <el-icon><Iphone /></el-icon>
              <span>{{ acc.phone }}</span>
            </button>
            <div class="acc-top-badges">
              <span v-if="acc.dc_id" class="acc-dc-badge" :class="'dc-' + acc.dc_id" :title="`数据中心: ${acc.dc_name || ('DC' + acc.dc_id)}`">
                DC{{ acc.dc_id }}
              </span>
              <span v-if="acc.keepalive_ping_ms" class="acc-ping-badge" :class="acc.keepalive_ping_ms < 250 ? 'ping-fast' : 'ping-slow'" :title="`最近一次保活握手延迟: ${acc.keepalive_ping_ms}ms`">
                {{ acc.keepalive_ping_ms }}ms
              </span>
              <span class="acc-status-tag" :class="`acc-status-${acc.status}`">
                {{ formatAccountStatus(acc.status) }}
              </span>
            </div>
          </div>

          <!-- 用户档案信息与最近保活 -->
          <div class="acc-meta-strip">
            <span v-if="acc.first_name || acc.username" class="acc-user-display" :title="`Telegram 用户: ${acc.first_name || ''} (@${acc.username || ''})`">
              <span v-if="acc.first_name" class="font-medium text-slate-700">{{ acc.first_name }}</span>
              <span v-if="acc.username" class="text-sky-600 ml-1">@{{ acc.username }}</span>
            </span>
            <span v-else-if="acc.tg_user_id" class="acc-user-display text-xs text-slate-500 font-mono">
              UID: {{ acc.tg_user_id }}
            </span>
            <span v-else class="acc-user-display text-xs text-slate-400">
              未同步档案
            </span>
            <span v-if="acc.last_keepalive_at" class="acc-keepalive-time" :title="`最近保活时间: ${acc.last_keepalive_at}`">
              保活: {{ formatRelativeTime(acc.last_keepalive_at) }}
            </span>
            <span v-else class="acc-keepalive-time text-slate-400">
              未保活
            </span>
          </div>

          <!-- 配额进度条 -->
          <div class="acc-quota-block">
            <div class="acc-quota-row">
              <span class="acc-quota-label">持有机数: <strong>{{ acc.bot_count }}</strong>/20</span>
              <span class="acc-quota-rem" :class="{ 'text-amber-500': acc.remaining_quota === 0 }">
                {{ acc.remaining_quota > 0 ? `余 ${acc.remaining_quota}` : '满额' }}
              </span>
            </div>
            <div class="acc-progress-bar-bg">
              <div
                class="acc-progress-bar-fill"
                :style="{ width: `${Math.min(100, (acc.bot_count / 20) * 100)}%` }"
                :class="{ 'fill-limit': acc.bot_count >= 20 }"
              ></div>
            </div>
          </div>

          <!-- 跨模块全维度联动呈现 (租户专属频道配额 + 集群在线活跃节点) -->
          <div class="acc-cross-module-row">
            <el-tooltip
              placement="top"
              :content="acc.tenant_usernames && acc.tenant_usernames.length > 0
                ? `已为租户创建专属存储频道 (${acc.tenant_usernames.length}个): @${acc.tenant_usernames.join(', @')}`
                : '尚未为租户创建专属频道 (Telegram 单号公开频道/超级群上限 10 个)'"
            >
              <div
                class="cross-module-item channel-item"
                :class="{ 'has-channels': (acc.created_channels_count || 0) > 0 }"
                @click="handleOpenAccountDetail(acc)"
                title="点击查看该母号托管的租户专属频道明细与配额"
              >
                <span class="cross-icon">🏠</span>
                <span class="cross-label">租户频道</span>
                <strong class="cross-val">{{ acc.created_channels_count || 0 }}/10</strong>
              </div>
            </el-tooltip>

            <el-tooltip
              placement="top"
              :content="`此母号名下共有 ${acc.bot_count || 0} 个 Bot，其中 ${acc.cluster_active_bots_count || 0} 个已挂载并在当前多 Bot 集群中在线处理流量`"
            >
              <div class="cross-module-item bot-item" :class="{ 'has-active': (acc.cluster_active_bots_count || 0) > 0 }">
                <span class="cross-icon">🤖</span>
                <span class="cross-label">集群在线</span>
                <strong class="cross-val">{{ acc.cluster_active_bots_count || 0 }} 节点</strong>
              </div>
            </el-tooltip>
          </div>

          <!-- 属性标签行 (Session类型 + API状态 + 备注) -->
          <div class="acc-tags-row">
            <div class="acc-tags-left">
              <span
                v-if="acc.region"
                class="acc-region-chip"
                :title="`账号手机号归属地区: ${acc.region} (自动匹配该地区家宽住宅代理)`"
              >
                🌐 {{ acc.region }}
              </span>
              <span class="acc-type-chip">
                {{ acc.session_type === 'telethon_string' ? 'Telethon' : acc.session_type === 'session_file' ? '.session' : 'Pyrogram' }}
              </span>
              <span
                v-if="acc.is_taken_over"
                class="acc-2fa-chip ready"
                @click="handleOpenAccountDetail(acc)"
                title="已完成安全接管：独立 15 位 2FA 强密码 + 本机自主接码链接"
              >
                <el-icon><Lock /></el-icon>
                <span>已安全接管</span>
              </span>
              <span
                v-else-if="acc.has_two_fa"
                class="acc-2fa-chip pending"
                @click="handleOpenAccountDetail(acc)"
                title="当前为号商初始 2FA 密码/外部接码，点击前往一键安全接管"
              >
                <el-icon><Unlock /></el-icon>
                <span>待接管(初始2FA)</span>
              </span>
              <span
                v-else
                class="acc-2fa-chip pending"
                @click="handleOpenAccountDetail(acc)"
                title="尚未设置 2FA 云密码，点击前往一键安全接管"
              >
                <el-icon><Unlock /></el-icon>
                <span>2FA 待加锁</span>
              </span>
              <span
                v-if="acc.api_id && acc.has_api_hash"
                class="acc-api-chip ready"
                @click="handleOpenAccountDetail(acc)"
                title="开发者 API 凭证 (api_id/api_hash) 已就绪，点击查看详情"
              >
                <el-icon><Check /></el-icon>
                <span>API 就绪</span>
              </span>
              <span
                v-else
                class="acc-api-chip pending"
                @click="handleOpenAccountDetail(acc)"
                title="未配置专属开发者 API 凭证，点击前往 my.telegram.org 自动提取"
              >
                <el-icon><Connection /></el-icon>
                <span>API 待提取</span>
              </span>
            </div>
            <div v-if="acc.remark" class="acc-remark-text" :title="acc.remark">
              {{ acc.remark }}
            </div>
          </div>

          <!-- API 凭证持久化落库回显条 (高对比度双模展示，彻底消除刷新后消失感) -->
          <div
            v-if="acc.api_id && acc.has_api_hash"
            class="acc-api-banner ready"
            @click="handleOpenAccountDetail(acc)"
            title="Telegram 开发者 API 凭证已持久化落库，点击查看详情"
          >
            <div class="acc-api-banner-left">
              <span class="acc-api-banner-badge">
                <el-icon><Check /></el-icon>
                <span>已落库</span>
              </span>
              <span class="acc-api-banner-id">ID: <strong>{{ acc.api_id }}</strong></span>
              <span class="acc-api-banner-hash font-mono">{{ acc.masked_api_hash }}</span>
            </div>
            <button
              type="button"
              class="acc-api-banner-copy-btn"
              @click.stop="copyToClipboard(`${acc.api_id}:${acc.masked_api_hash}`, 'API 凭证')"
              title="一键复制已落库的 API 凭证组合"
            >
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
          <div
            v-else
            class="acc-api-banner pending"
            @click="handleOpenAccountDetail(acc)"
            title="未配置专属开发者 API 凭证，点击前往 my.telegram.org 自动提取"
          >
            <div class="acc-api-banner-left">
              <span class="acc-api-banner-badge pending">
                <el-icon><Connection /></el-icon>
                <span>未提取</span>
              </span>
              <span class="acc-api-banner-prompt">点击前往自动提取 API 凭证 →</span>
            </div>
          </div>

          <!-- 底部操作按钮栏 (全宽等比分配，零溢出) -->
          <div class="acc-card-actions">
            <el-button
              size="small"
              class="acc-btn-action otp-account-btn"
              :icon="ChatDotRound"
              @click="handleQuickViewOtp(acc)"
              title="实时截获 777000 登录验证码与自主接码"
            >
              接码
            </el-button>
            <el-button
              size="small"
              class="acc-btn-action detail-account-btn"
              :icon="View"
              @click="handleOpenAccountDetail(acc)"
              title="查看底层参数与凭证中心"
            >
              详情
            </el-button>
            <el-button
              size="small"
              class="acc-btn-action keepalive-account-btn"
              :icon="Cpu"
              :loading="singleKeepaliveLoading === acc.id"
              @click="handleSingleKeepalive(acc)"
              title="发起轻量 MTProto 保活握手"
            >
              保活
            </el-button>
            <el-button
              size="small"
              class="acc-btn-action single-mint-quick-btn"
              :icon="MagicStick"
              @click="handleQuickSingleMint(acc)"
              title="切换为此号单号精准独立铸造"
            >
              单号
            </el-button>
            <el-button
              size="small"
              class="acc-btn-action check-account-btn"
              :icon="RefreshRight"
              :loading="checkAccountLoading === acc.id"
              @click="handleCheckAccount(acc)"
              title="在线检测账号健康度并刷新 Bot 数量"
            >
              检测
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              class="acc-btn-action delete-account-btn"
              :icon="Delete"
              @click="handleDeleteAccount(acc)"
              title="从资产池安全移除"
            />
          </div>
        </div>
      </div>
      <!-- 搜索筛选空状态提示 -->
      <div v-else-if="protocolAccounts.length > 0" class="pool-empty-box glass-card">
        <el-empty description="未找到符合筛选条件的 Telegram 协议号" :image-size="80">
          <el-button size="small" type="primary" plain @click="resetAccountFilters">
            重置筛选条件
          </el-button>
        </el-empty>
      </div>

      <div v-else class="account-pool-empty">
        <el-icon :size="24"><Warning /></el-icon>
        <span>资产池暂未纳管协议号，点击右上角「批量导入协议号」或在下方输入即可开始</span>
      </div>

      <!-- 底部分页控制栏 -->
      <div v-if="sortedAndFilteredAccounts.length > 0" class="pool-pagination-bar glass-card">
        <div class="pagination-info text-xs text-slate-500">
          <span>共 <strong class="text-slate-800 font-semibold">{{ sortedAndFilteredAccounts.length }}</strong> 个账号</span>
          <span class="mx-1.5 opacity-40">|</span>
          <span>当前展示第 <strong class="text-sky-600 font-semibold">{{ (accountCurrentPage - 1) * accountPageSize + 1 }} ~ {{ Math.min(accountCurrentPage * accountPageSize, sortedAndFilteredAccounts.length) }}</strong> 个</span>
        </div>
        <el-pagination
          v-model:current-page="accountCurrentPage"
          v-model:page-size="accountPageSize"
          :page-sizes="[8, 12, 16, 24, 48]"
          :total="sortedAndFilteredAccounts.length"
          layout="sizes, prev, pager, next, jumper"
          size="small"
          background
          class="account-pool-pagination"
        />
      </div>
    </div>

    <el-row :gutter="16" class="mint-console-row">
      <!-- 左侧：协议号输入与参数配置 -->
      <el-col :xs="24" :lg="11" class="mint-col">
        <div class="mint-config-card glass-card">
          <div class="card-header-line">
            <div class="card-title-wrap">
              <span class="card-icon-dot dot-pink"></span>
              <h3 class="card-title">自动化铸造配置</h3>
            </div>
            <span class="card-pill">Dual-Mode Minting</span>
          </div>

          <!-- 双模切换 Segmented 选项卡 -->
          <div class="mint-strategy-tabs">
            <button
              type="button"
              class="strategy-tab-btn strategy-tab-relay"
              :class="{ active: mintStrategy === 'relay' }"
              @click="switchMintStrategy('relay')"
            >
              <el-icon><Lightning /></el-icon>
              <span>多号接力扩容 (Relay)</span>
              <span class="strategy-badge">突破单号20上限</span>
            </button>
            <button
              type="button"
              class="strategy-tab-btn strategy-tab-single"
              :class="{ active: mintStrategy === 'single' }"
              @click="switchMintStrategy('single')"
            >
              <el-icon><Aim /></el-icon>
              <span>单号精准铸造 (Single)</span>
              <span class="strategy-badge">独立单号控量</span>
            </button>
          </div>

          <!-- 多号接力模式专有说明与账号选择 -->
          <div v-if="mintStrategy === 'relay'" class="strategy-setting-box">
            <div class="strategy-desc-banner">
              <el-icon><Lightning /></el-icon>
              <span>
                <strong>多号跨账号接力策略：</strong>支持设定突破单号 20 上限的大额目标，系统按序调度各协议号。当单号达到 20 个机器人上限或触发频率限流时，<strong>自动无缝切换至下一协议号继续铸造</strong>，直至集群目标达成。
              </span>
            </div>

            <!-- 接力账号多选勾选 -->
            <div v-if="protocolAccounts.length > 0" class="relay-select-wrap">
              <div class="relay-select-header">
                <span class="relay-select-label">参与接力的协议号 ({{ selectedRelayAccountIds.length }}/{{ protocolAccounts.length }})：</span>
                <el-button size="small" text @click="toggleSelectAllRelayAccounts">
                  {{ selectedRelayAccountIds.length === protocolAccounts.length ? '取消全选' : '一键全选' }}
                </el-button>
              </div>
              <div class="relay-checkbox-group">
                <label
                  v-for="acc in protocolAccounts"
                  :key="acc.id"
                  class="relay-checkbox-item"
                  :class="{ selected: selectedRelayAccountIds.includes(acc.id), disabled: acc.status === 'invalid' }"
                >
                  <input
                    type="checkbox"
                    :value="acc.id"
                    v-model="selectedRelayAccountIds"
                    :disabled="acc.status === 'invalid'"
                  />
                  <span class="acc-phone-text">{{ acc.phone }}</span>
                  <span class="acc-bot-count">({{ acc.bot_count }}/20)</span>
                </label>
              </div>
            </div>
          </div>

          <!-- 单号精准模式专有配置 -->
          <div v-else class="strategy-setting-box">
            <div class="strategy-desc-banner single-banner">
              <el-icon><Aim /></el-icon>
              <span>
                <strong>单号精准独立铸造：</strong>仅由选定的单个协议号独立执行存量提取或新建，受 Telegram 官方规则限制，目标数量上限锁定为 20。
              </span>
            </div>

            <el-form-item label="指定目标协议号" class="single-account-picker-item">
              <el-select
                v-model="selectedSingleAccountId"
                placeholder="请选择要操作的协议号"
                class="single-account-select w-full"
                filterable
              >
                <el-option
                  v-for="acc in protocolAccounts"
                  :key="acc.id"
                  :value="acc.id"
                  :label="`${acc.phone} (已建 ${acc.bot_count}/20 · 剩余配额 ${acc.remaining_quota})`"
                />
              </el-select>
            </el-form-item>
          </div>

          <!-- 补充临时协议号输入模式切换 -->
          <div class="supplement-input-toggle">
            <span class="supplement-label">
              {{ mintStrategy === 'relay' ? '补充外部协议号 (可选，与资产池一同调度)：' : '或手动输入临时协议号：' }}
            </span>
            <div class="input-mode-tabs">
              <button
                type="button"
                class="mode-tab-btn"
                :class="{ active: inputMode === 'phone_url' }"
                @click="inputMode = 'phone_url'"
              >
                手机号 | 接码链接
              </button>
              <button
                type="button"
                class="mode-tab-btn"
                :class="{ active: inputMode === 'session_str' }"
                @click="inputMode = 'session_str'"
              >
                Session 文本
              </button>
              <button
                type="button"
                class="mode-tab-btn"
                :class="{ active: inputMode === 'session_file' }"
                @click="inputMode = 'session_file'"
              >
                .session 文件
              </button>
            </div>
          </div>

          <el-form label-position="top" class="mint-form">
            <el-form-item v-if="inputMode === 'phone_url'" :label="mintStrategy === 'relay' ? '手机号与接码 API 链接 (多号接力支持多行粘贴)' : '手机号与发卡网接码 API 链接 (或已缓存手机号)'">
              <el-input
                v-model="mintForm.sessionString"
                type="textarea"
                :rows="mintStrategy === 'relay' ? 3 : 2"
                :placeholder="phoneInputPlaceholder"
                clearable
              />
            </el-form-item>

            <el-form-item v-else-if="inputMode === 'session_str'" label="Pyrogram / Telethon Session String">
              <el-input
                v-model="mintForm.sessionString"
                type="textarea"
                :rows="3"
                placeholder="粘贴 Pyrogram 或 Telethon 导出的长字符串 Session String (多号可换行粘贴)..."
                clearable
              />
            </el-form-item>

            <el-form-item v-else label="上传协议号 .session 文件">
              <div class="session-upload-box" @click="triggerFileSelect">
                <input
                  ref="fileInputRef"
                  type="file"
                  accept=".session"
                  class="hidden-file-input"
                  @change="handleFileChange"
                />
                <el-icon :size="28" class="upload-icon"><UploadFilled /></el-icon>
                <div class="upload-text">
                  {{ selectedFile ? `已选择: ${selectedFile.name}` : '点击选择 Pyrogram / Telethon 的 .session 文件' }}
                </div>
              </div>
            </el-form-item>

            <el-row :gutter="12">
              <el-col :xs="24" :sm="13">
                <el-form-item :label="`目标扩容节点数 (${mintStrategy === 'relay' ? `多号上限 ${relayMaxCount}` : '单号上限 20'})`">
                  <div class="slider-with-num">
                    <el-slider
                      v-model="mintForm.count"
                      :min="1"
                      :max="mintStrategy === 'relay' ? relayMaxCount : 20"
                      :step="1"
                      class="flex-1"
                    />
                    <el-input-number
                      v-model="mintForm.count"
                      :min="1"
                      :max="mintStrategy === 'relay' ? relayMaxCount : 20"
                      size="small"
                    />
                  </div>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="11">
                <el-form-item label="机器人显示名称前缀">
                  <el-input v-model="mintForm.namePrefix" placeholder="MistRelay Node" />
                </el-form-item>
              </el-col>
            </el-row>

            <div class="reuse-switch-row">
              <div class="reuse-copy">
                <span class="reuse-title">优先探测并复用存量 Bot</span>
                <span class="reuse-desc">自动通过 /token 提取该账号下已有机器人，不足部分再新建</span>
              </div>
              <el-switch v-model="mintForm.reuseExisting" />
            </div>

            <div class="mint-actions-row">
              <el-button
                type="primary"
                class="primary-glow-btn flex-1"
                :icon="VideoPlay"
                :loading="startingTask"
                :disabled="isTaskActive"
                @click="handleStartBackgroundMint"
              >
                {{ isTaskActive ? '后台流水线运行中...' : '启动后台自动铸造' }}
              </el-button>
              <el-button
                class="sync-mint-btn"
                :icon="MagicStick"
                :loading="syncMintLoading"
                :disabled="isTaskActive"
                @click="handleSyncAutoCreate"
              >
                立即同步提取/创建
              </el-button>
              <el-button
                v-if="isTaskActive"
                type="danger"
                plain
                :icon="VideoPause"
                @click="handleStopTask"
              >
                停止
              </el-button>
            </div>
          </el-form>
        </div>
      </el-col>

      <!-- 右侧：实时流水线进度与终端日志 -->
      <el-col :xs="24" :lg="13" class="mint-col">
        <div class="mint-monitor-card glass-card">
          <div class="card-header-line">
            <div class="card-title-wrap">
              <span class="card-icon-dot" :class="taskStatusDotClass"></span>
              <h3 class="card-title">流水线执行监控与实时日志</h3>
            </div>
            <span class="task-status-badge" :class="`status-${taskStatus.status}`">
              {{ taskStatusLabel }}
            </span>
          </div>

          <!-- 当前正在运行的协议号与跨号接力提示 -->
          <div v-if="taskStatus.current_account_phone || (isTaskActive && taskStatus.account_index)" class="current-account-banner">
            <span class="pulse-dot dot-sky"></span>
            <span class="curr-acc-label">正在调度协议号:</span>
            <span class="curr-acc-phone">{{ taskStatus.current_account_phone || '调度中' }}</span>
            <span v-if="taskStatus.total_accounts && taskStatus.total_accounts > 1" class="curr-acc-index">
              (账号 {{ taskStatus.account_index }}/{{ taskStatus.total_accounts }})
            </span>
            <span class="curr-acc-mode">{{ taskStatus.mode === 'single' ? '单号模式' : '多号接力' }}</span>
          </div>

          <!-- 账号流转历史胶囊 -->
          <div v-if="taskStatus.account_history && taskStatus.account_history.length > 0" class="account-history-bar">
            <span class="hist-label">接力流转:</span>
            <div class="hist-tags">
              <span
                v-for="(h, hIdx) in taskStatus.account_history"
                :key="hIdx"
                class="hist-tag"
                :class="`hist-${h.status}`"
              >
                {{ h.phone }}: 复用{{ h.reused }}/新建{{ h.created }} ({{ formatAccountHistoryStatus(h.status) }})
              </span>
            </div>
          </div>

          <!-- 进度指标概览 -->
          <div class="mint-progress-box">
            <div class="progress-step-row">
              <span class="step-text">{{ taskStatus.current_step || '等待启动协议号自动化铸造流水线...' }}</span>
              <span class="step-pct">{{ taskStatus.percent }}%</span>
            </div>
            <el-progress
              :percentage="taskStatus.percent"
              :stroke-width="10"
              :show-text="false"
              :status="taskStatus.status === 'failed' ? 'exception' : taskStatus.status === 'completed' ? 'success' : ''"
              class="sakura-progress"
            />
            <div class="mint-metrics-mini">
              <div class="mini-item">
                <span class="mini-label">已复用存量</span>
                <span class="mini-val text-sky-500">{{ taskStatus.reused_count }}</span>
              </div>
              <div class="mini-item">
                <span class="mini-label">新铸造节点</span>
                <span class="mini-val text-pink-500">{{ taskStatus.created_count }}</span>
              </div>
              <div class="mini-item">
                <span class="mini-label">目标数量</span>
                <span class="mini-val">{{ taskStatus.target_count || mintForm.count }}</span>
              </div>
              <div class="mini-item">
                <span class="mini-label">集群活跃从机</span>
                <span class="mini-val text-emerald-500">{{ Math.max(0, botDetails.length - 1) }}</span>
              </div>
            </div>
          </div>

          <!-- 冷却或限流提醒横幅 -->
          <div v-if="taskStatus.status === 'cooling_down' || cooldownNotice" class="cooldown-banner">
            <el-icon class="cd-icon"><Timer /></el-icon>
            <div class="cd-copy">
              <div class="cd-title">
                @BotFather 频率保护提示
                <span v-if="taskStatus.cooldown_remaining > 0" class="cd-timer">
                  剩余 {{ formatCooldown(taskStatus.cooldown_remaining) }}
                </span>
              </div>
              <div class="cd-desc">
                {{ cooldownNotice }}
              </div>
            </div>
          </div>

          <!-- 实时终端日志 -->
          <div class="mint-terminal">
            <div class="terminal-header">
              <div class="terminal-dots">
                <span class="t-dot red"></span>
                <span class="t-dot yellow"></span>
                <span class="t-dot green"></span>
              </div>
              <span class="terminal-title">botfather-pipeline.log</span>
              <span class="terminal-count">{{ taskStatus.logs.length }} 条记录</span>
            </div>
            <div ref="terminalBodyRef" class="terminal-body">
              <div v-if="taskStatus.logs.length === 0" class="terminal-empty">
                [READY] 协议号流水线已就绪，选择左侧已缓存手机号或输入接码链接即可开始自动扩容...
              </div>
              <div
                v-for="(log, idx) in taskStatus.logs"
                :key="idx"
                class="terminal-line"
                :class="`log-${log.level}`"
              >
                <span class="log-time">[{{ log.time }}]</span>
                <span class="log-level">[{{ log.level.toUpperCase() }}]</span>
                <span class="log-msg">{{ log.msg }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
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
    <!-- 批量导入协议号模态框 -->
    <el-dialog
      v-model="batchImportDialogVisible"
      title="批量导入 Telegram 协议号"
      width="640px"
      append-to-body
      class="glass-dialog"
    >
      <div class="dialog-body">
        <p class="dialog-tip">
          支持批量导入号商交付的 <strong>[手机号|接码链接]</strong>（每行一个）、<strong>Session String</strong> 长文本，或同时拖拽上传多个 <strong>.session</strong> 文件。系统将自动解析、建库并纳入资产池调度。
        </p>

        <el-form label-position="top">
          <el-form-item label="多行协议号文本 (每行一个)">
            <el-input
              v-model="batchImportForm.textContent"
              type="textarea"
              :rows="5"
              class="batch-import-textarea"
              placeholder="+16813086196|https://miha.uk/tgapi/92980827-e8db-4dea-b664-f4a7979b0632/GetHTML&#10;+18048484620|https://568.5689889.uk/@ming888/b0c57ee6-cea1-4ffa-ad82-d20d65cae9aa/GetHTML&#10;或长 Session String..."
            />
          </el-form-item>

          <el-form-item label="或批量上传 .session / .json 档案文件 (支持多选与配对)">
            <div class="batch-upload-dropzone" @click="triggerBatchFileInput">
              <input
                ref="batchFileInputRef"
                type="file"
                accept=".session,.json"
                multiple
                class="hidden-file-input"
                @change="handleBatchFilesSelect"
              />
              <el-icon :size="28" class="upload-icon"><UploadFilled /></el-icon>
              <div class="upload-text">
                {{ batchImportFiles.length > 0 ? `已选择 ${batchImportFiles.length} 个文件 (.session / .json)` : '点击选择或拖拽多个 .session / .json 档案文件' }}
              </div>
            </div>
            <div v-if="batchImportFiles.length > 0" class="file-list-preview">
              <span v-for="(f, i) in batchImportFiles" :key="i" class="file-chip">
                {{ f.name }}
              </span>
            </div>
          </el-form-item>

          <el-form-item label="备注说明 (可选)">
            <el-input
              v-model="batchImportForm.remark"
              class="batch-import-remark"
              placeholder="例如: 号商采购批次 / 2026-09"
            />
          </el-form-item>
        </el-form>

        <!-- 异步导入实时任务状态指示器 -->
        <div v-if="batchImportLoading" class="import-task-banner mb-4">
          <div class="task-banner-top flex items-center justify-between">
            <div class="flex items-center gap-2">
              <el-icon class="is-loading text-sky-500"><Loading /></el-icon>
              <span class="font-bold text-sm text-slate-800">协议号接码入网流水线进行中</span>
            </div>
            <span v-if="importTaskCooldown > 0" class="cooldown-pill">
              接码频率冷却: {{ importTaskCooldown }}s
            </span>
          </div>

          <div class="task-banner-msg mt-2 text-xs text-slate-600">
            {{ importTaskProgressMsg || "正在连接 Telegram 并等待接码平台返回验证码..." }}
          </div>

          <div v-if="importTaskCurrentPhone" class="task-banner-phone mt-1 text-xs text-sky-600 font-medium">
            当前调度手机号: <code class="phone-code">{{ importTaskCurrentPhone }}</code>
          </div>

          <div v-if="importTaskLogs && importTaskLogs.length > 0" class="task-banner-logs mt-2">
            <div v-for="(log, lIdx) in importTaskLogs.slice(-4)" :key="lIdx" class="task-mini-log">
              <span class="log-time">{{ log.time }}</span>
              <span class="log-msg">{{ log.msg }}</span>
            </div>
          </div>
        </div>

        <div v-if="batchImportResult" class="import-result-box">
          <div class="result-summary">
            <span class="text-emerald-500 font-bold">成功导入 {{ batchImportResult.imported_count }} 个</span>
            <span v-if="batchImportResult.failed_count > 0" class="text-red-500 font-bold ml-2">
              失败 {{ batchImportResult.failed_count }} 个
            </span>
          </div>
          <div v-if="batchImportResult.errors && batchImportResult.errors.length > 0" class="result-errors">
            <div v-for="(err, eIdx) in batchImportResult.errors" :key="eIdx" class="err-line">
              {{ err }}
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="batchImportLoading" @click="batchImportDialogVisible = false">在后台继续运行</el-button>
        <el-button v-else @click="batchImportDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          class="primary-glow-btn confirm-batch-import-btn"
          :loading="batchImportLoading"
          @click="handleConfirmBatchImport"
        >
          {{ batchImportLoading ? "正在解析入网..." : "立即解析并入库" }}
        </el-button>
      </template>
    </el-dialog>


    <!-- 协议号详细参数与 Session 凭证中心模态框 (自适应限高 + 3大Tab分类收纳) -->
    <el-dialog
      v-model="accountDetailDialogVisible"
      title="协议号详细参数与 Session 凭证中心"
      width="min(860px, 94vw)"
      top="5vh"
      append-to-body
      class="glass-dialog detail-dialog compact-detail-dialog"
    >
      <div v-loading="detailLoading" class="dialog-body compact-dialog-body">
        <div v-if="accountDetail" class="detail-content space-y-3">
          <!-- 账号顶部核心档案横幅 (固定置顶) -->
          <div class="detail-header-card">
            <div class="flex items-center justify-between flex-wrap gap-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="detail-phone font-mono font-bold text-lg text-slate-800">{{ accountDetail.account.phone }}</span>
                <span v-if="accountDetail.metadata.first_name || accountDetail.metadata.username" class="detail-user-pill">
                  {{ accountDetail.metadata.first_name }}
                  <span v-if="accountDetail.metadata.username" class="text-sky-600">(@{{ accountDetail.metadata.username }})</span>
                </span>
                <span class="acc-status-tag" :class="`acc-status-${accountDetail.account.status}`">
                  {{ formatAccountStatus(accountDetail.account.status) }}
                </span>
                <span v-if="accountDetail.metadata.dc_id" class="acc-dc-badge" :class="'dc-' + accountDetail.metadata.dc_id">
                  {{ accountDetail.metadata.dc_name }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <el-button
                  size="small"
                  :icon="RefreshRight"
                  :loading="detailOnlineRefreshing"
                  @click="handleRefreshAccountDetailOnline"
                >
                  在线刷新档案与Bot
                </el-button>
              </div>
            </div>

            <!-- 核心 MTProto 参数指标网格 (紧凑高密度指示栏) -->
            <div class="detail-metrics-compact-row mt-2.5">
              <div class="compact-metric-item">
                <span class="compact-metric-label">Telegram UID</span>
                <span class="font-mono font-bold text-slate-800 text-xs">{{ accountDetail.metadata.tg_user_id || '未获取' }}</span>
              </div>
              <div class="compact-metric-item">
                <span class="compact-metric-label">数据中心 / 节点</span>
                <span class="font-mono font-bold text-sky-600 text-xs truncate">{{ accountDetail.metadata.dc_ip || 'N/A' }}:{{ accountDetail.metadata.dc_port }}</span>
              </div>
              <div class="compact-metric-item">
                <span class="compact-metric-label">密钥指纹 (SHA256)</span>
                <span class="font-mono font-bold text-emerald-600 text-xs truncate" :title="accountDetail.metadata.auth_key_fingerprint">{{ accountDetail.metadata.auth_key_fingerprint ? accountDetail.metadata.auth_key_fingerprint.slice(0, 10) + '...' : '256-bit' }}</span>
              </div>
              <div class="compact-metric-item">
                <span class="compact-metric-label">保活延迟 / 时间</span>
                <span class="font-mono font-bold text-xs" :class="accountDetail.metadata.keepalive_ping_ms ? 'text-emerald-600' : 'text-slate-400'">
                  {{ accountDetail.metadata.keepalive_ping_ms ? accountDetail.metadata.keepalive_ping_ms + 'ms' : '未检测' }}
                </span>
              </div>
            </div>
          </div>

          <!-- 现代毛玻璃三维分类标签页 -->
          <el-tabs v-model="detailActiveTab" class="detail-modern-tabs">
            <!-- Tab 1: 安全加固与自主接码 -->
            <el-tab-pane name="security" label="🔐 安全加固与接码">
              <div class="tab-pane-content space-y-3 pt-1">
                <!-- 2FA 云密码自主管理与防收回专区 -->
                <div class="twofa-section p-3 rounded-lg border border-indigo-200 bg-indigo-50/40">
                  <div class="flex items-center justify-between flex-wrap gap-2 mb-2">
                    <div class="flex items-center gap-2">
                      <span class="font-semibold text-slate-800 text-sm flex items-center gap-1.5">
                        <span class="text-indigo-600 font-bold">🔐</span> 2FA 云密码管理与安全加固
                      </span>
                      <span
                        v-if="accountDetail.two_fa?.has_two_fa || twoFaStatusData?.has_password"
                        class="text-xs px-2 py-0.5 rounded font-medium bg-emerald-50 text-emerald-600 border border-emerald-200"
                      >
                        ✓ 2FA 已加锁
                      </span>
                      <span
                        v-else
                        class="text-xs px-2 py-0.5 rounded font-medium bg-amber-50 text-amber-600 border border-amber-200"
                      >
                        ⚠️ 未开启 2FA (有被收回风险)
                      </span>
                    </div>
                    <div class="flex items-center gap-2 flex-wrap">
                      <el-button
                        size="small"
                        type="success"
                        :loading="takingOverSingle"
                        @click="handleSingleTakeover"
                        title="自动生成新 2FA 强密码 + 切换本机接码链接 + 踢除号商所有外部设备"
                      >
                        ⚡ 一键全自动接管
                      </el-button>
                      <el-button
                        size="small"
                        type="primary"
                        :icon="Lock"
                        @click="openEdit2faModal"
                      >
                        {{ accountDetail.two_fa?.has_two_fa ? '修改 2FA 云密码' : '设置 2FA 云密码加锁' }}
                      </el-button>
                      <el-button
                        size="small"
                        type="danger"
                        plain
                        :loading="terminatingSessions"
                        @click="handleTerminateOtherSessions"
                        title="注销除 MistRelay 之外号商的所有其他已登录设备"
                      >
                        一键踢除号商其他设备
                      </el-button>
                    </div>
                  </div>

                  <!-- 恶意重置警告横幅 (若检测到重置倒计时) -->
                  <div
                    v-if="twoFaStatusData?.has_pending_reset"
                    class="mb-2 p-2.5 rounded bg-rose-100 border border-rose-300 flex items-center justify-between text-xs text-rose-800"
                  >
                    <div class="flex items-center gap-2">
                      <el-icon :size="16" class="text-rose-600"><Warning /></el-icon>
                      <span><strong>严重警报：</strong>检测到有外部设备正在对该账号发起 2FA 密码重置申请！</span>
                    </div>
                    <el-button
                      size="small"
                      type="danger"
                      :loading="cancellingReset"
                      @click="handleCancelPasswordReset"
                    >
                      立即撤销重置申请
                    </el-button>
                  </div>

                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div class="bg-white p-2.5 rounded border border-slate-200">
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-slate-500 font-medium">当前 2FA 云密码 (已持久化):</span>
                        <div class="flex items-center gap-1">
                          <el-button
                            v-if="accountDetail.two_fa?.two_fa_password"
                            size="small"
                            text
                            @click="showTwoFaPassword = !showTwoFaPassword"
                          >
                            {{ showTwoFaPassword ? '隐藏' : '显示' }}
                          </el-button>
                          <el-button
                            v-if="accountDetail.two_fa?.two_fa_password"
                            size="small"
                            text
                            :icon="CopyDocument"
                            @click="copyToClipboard(accountDetail.two_fa.two_fa_password, '2FA 密码')"
                          >
                            复制
                          </el-button>
                        </div>
                      </div>
                      <div class="font-mono text-sm font-bold truncate" :class="accountDetail.two_fa?.two_fa_password ? 'text-indigo-950' : 'text-slate-400 italic'">
                        {{ accountDetail.two_fa?.two_fa_password ? (showTwoFaPassword ? accountDetail.two_fa.two_fa_password : '••••••••') : '尚未记录 (点击右上角设置)' }}
                      </div>
                    </div>

                    <div class="bg-white p-2.5 rounded border border-slate-200">
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-slate-500 font-medium">密码提示 (Hint):</span>
                        <span class="text-[11px] text-slate-400">登入时展示</span>
                      </div>
                      <div class="text-sm font-medium text-slate-700 truncate">
                        {{ accountDetail.two_fa?.two_fa_hint || twoFaStatusData?.hint || '无提示' }}
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 自主在线接码中心 (777000 官方通知) -->
                <div class="otp-center-section p-3 rounded-lg border border-sky-200 bg-sky-50/50">
                  <div class="flex items-center justify-between flex-wrap gap-2 mb-2">
                    <div class="flex items-center gap-2">
                      <span class="font-semibold text-slate-800 text-sm flex items-center gap-1.5">
                        <span class="text-sky-600 font-bold">⚡</span> 自主实时接码 (777000 官方通知)
                      </span>
                      <span
                        v-if="otpData?.is_recent"
                        class="text-xs px-2 py-0.5 rounded font-medium bg-emerald-100 text-emerald-700 border border-emerald-300"
                      >
                        🟢 最新有效
                      </span>
                      <span
                        v-else
                        class="text-xs px-2 py-0.5 rounded font-medium bg-amber-100 text-amber-700 border border-amber-300"
                      >
                        {{ otpData?.latest_code ? '⚠️ 可能已过期' : '🟡 等待新验证码' }}
                      </span>
                    </div>
                    <div class="flex items-center gap-2">
                      <el-checkbox v-model="otpAutoPoll" size="small" @change="accountDetail && toggleOtpAutoPoll(accountDetail.account.id)">
                        5秒自动监听
                      </el-checkbox>
                      <el-button
                        size="small"
                        :icon="RefreshRight"
                        :loading="otpLoading"
                        @click="accountDetail && loadAccountOtp(accountDetail.account.id)"
                      >
                        刷新验证码
                      </el-button>
                      <a
                        v-if="accountDetail.account.local_otp_token"
                        :href="`/api/telegram/botfather/otp/${accountDetail.account.local_otp_token}`"
                        target="_blank"
                        class="text-xs text-sky-600 hover:underline flex items-center gap-0.5"
                      >
                        独立接码页 ↗
                      </a>
                    </div>
                  </div>

                  <!-- 紧凑型验证码展示卡 -->
                  <div
                    class="otp-code-highlight-card text-center py-2 px-3 rounded-lg border border-sky-300 bg-white cursor-pointer hover:border-sky-500 transition"
                    @click="otpData?.latest_code && copyToClipboard(otpData.latest_code, '验证码')"
                  >
                    <div class="text-[11px] text-slate-500">Telegram 5位登录验证码</div>
                    <div class="font-mono font-extrabold text-2xl tracking-widest text-sky-600 my-0.5">
                      {{ otpData?.latest_code || '------' }}
                    </div>
                    <div class="text-[11px] text-slate-400">
                      {{ otpData?.latest_code ? '点击直接一键复制' : '新客户端输入手机号后，在此实时读取 777000' }}
                    </div>
                  </div>

                  <!-- 上下文数据指标 -->
                  <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs mt-2">
                    <div class="bg-white p-1.5 rounded border border-slate-200">
                      <span class="text-slate-400 block text-[11px]">接收时间</span>
                      <span class="font-mono text-slate-700 truncate block">{{ otpData?.code_time || '暂无' }}</span>
                    </div>
                    <div class="bg-white p-1.5 rounded border border-slate-200">
                      <span class="text-slate-400 block text-[11px]">有效状态</span>
                      <span class="font-medium truncate block" :class="otpData?.is_recent ? 'text-emerald-600' : 'text-slate-500'">{{ otpData?.relative_time || '未检测' }}</span>
                    </div>
                    <div class="bg-white p-1.5 rounded border border-slate-200">
                      <span class="text-slate-400 block text-[11px]">尝试设备</span>
                      <span class="font-mono text-slate-700 truncate block">{{ otpData?.device || '未知' }}</span>
                    </div>
                    <div class="bg-white p-1.5 rounded border border-slate-200">
                      <span class="text-slate-400 block text-[11px]">登录 IP / 地点</span>
                      <span class="font-mono text-slate-700 truncate block">{{ otpData?.ip || '未知' }}</span>
                    </div>
                  </div>

                  <!-- 自主接码链接与替换操作 -->
                  <div class="mt-2 pt-2 border-t border-sky-200/80 flex items-center justify-between flex-wrap gap-2 text-xs">
                    <div class="flex items-center gap-1.5 text-slate-600">
                      <span class="text-slate-500">专属自主接码链接:</span>
                      <span class="font-mono text-sky-700 truncate max-w-xs">{{ accountDetail.account.local_otp_token ? `/api/telegram/botfather/otp/${accountDetail.account.local_otp_token}` : '未生成' }}</span>
                    </div>
                    <div class="flex items-center gap-1">
                      <el-button
                        v-if="accountDetail.account.local_otp_token"
                        size="small"
                        text
                        :icon="CopyDocument"
                        @click="copyToClipboard(getFullOtpUrl(accountDetail.account.local_otp_token), '自主接码链接')"
                      >
                        复制链接
                      </el-button>
                      <el-button
                        size="small"
                        type="primary"
                        plain
                        @click="handleBindLocalOtp(accountDetail.account.id)"
                        title="生成并永久将该号的外部号商接码链接替换为本系统自主接码链接"
                      >
                        设为默认接码链接
                      </el-button>
                    </div>
                  </div>
                </div>

                <!-- 附加信息（接码链接、备注、错误） -->
                <div v-if="accountDetail.metadata.code_url || accountDetail.account.remark || accountDetail.metadata.last_error" class="detail-extra-box text-xs space-y-1 p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                  <div v-if="accountDetail.metadata.code_url" class="flex items-center justify-between">
                    <span class="text-slate-500">当前绑定接码链接:</span>
                    <span class="font-mono text-sky-700 truncate max-w-md ml-2">{{ accountDetail.metadata.code_url }}</span>
                    <el-button size="small" text :icon="CopyDocument" @click="copyToClipboard(accountDetail.metadata.code_url, '接码链接')">复制</el-button>
                  </div>
                  <div v-if="accountDetail.account.remark" class="flex items-center gap-2">
                    <span class="text-slate-500">账号备注:</span>
                    <span class="text-slate-700">{{ accountDetail.account.remark }}</span>
                  </div>
                  <div v-if="accountDetail.metadata.last_error" class="flex items-center gap-2 text-rose-600">
                    <span>最近异常:</span>
                    <span>{{ accountDetail.metadata.last_error }}</span>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <!-- Tab 2: 租户存储与机器集群 -->
            <el-tab-pane name="channels" label="🏠 租户存储与节点">
              <div class="tab-pane-content space-y-3 pt-1">
                <!-- 租户专属存储频道托管中心 (X/10) -->
                <div class="tenant-channels-section p-3 rounded-lg border border-sky-200 bg-sky-50/40">
                  <div class="flex items-center justify-between flex-wrap gap-2 mb-2">
                    <div class="flex items-center gap-2">
                      <span class="font-semibold text-slate-800 text-sm flex items-center gap-1.5">
                        <span class="text-sky-600 font-bold">🏠</span> 租户专属存储频道托管中心
                      </span>
                      <span
                        class="text-xs px-2 py-0.5 rounded font-bold"
                        :class="(accountDetail.account.created_channels_count || 0) > 0 ? 'bg-sky-100 text-sky-700 border border-sky-300' : 'bg-slate-100 text-slate-600 border border-slate-200'"
                      >
                        已托管 {{ accountDetail.account.created_channels_count || 0 }} / 10 频道
                      </span>
                    </div>
                    <div class="flex items-center gap-2">
                      <el-button
                        size="small"
                        type="primary"
                        plain
                        @click="router.push('/users')"
                        title="前往用户管理页面查看或分配租户"
                      >
                        用户管理 ↗
                      </el-button>
                    </div>
                  </div>

                  <!-- 频道明细列表 (带内滚保护) -->
                  <div v-if="accountDetail.tenant_channels && accountDetail.tenant_channels.length > 0" class="tenant-channel-cards space-y-2 mt-2">
                    <div
                      v-for="tc in accountDetail.tenant_channels"
                      :key="tc.user_id || tc.bin_channel_id"
                      class="p-2.5 rounded bg-white border border-slate-200 flex items-center justify-between flex-wrap gap-2 text-xs hover:border-sky-300 transition"
                    >
                      <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-bold text-slate-800 flex items-center gap-1">
                          <span class="text-slate-400">租户:</span>
                          <span class="text-sky-600 font-mono">@{{ tc.username }}</span>
                        </span>
                        <span class="text-slate-400">|</span>
                        <span class="text-slate-600">
                          频道: <strong class="font-mono text-slate-800">@{{ tc.bin_channel_username || '私密频道' }}</strong>
                        </span>
                        <span class="acc-dc-badge" :class="'dc-' + (tc.dc_id || 5)">
                          DC{{ tc.dc_id || 5 }}
                        </span>
                        <span class="font-mono text-slate-400 text-[11px]">
                          ID: {{ tc.bin_channel_id }}
                        </span>
                      </div>
                      <div class="flex items-center gap-1">
                        <el-button
                          v-if="tc.bin_channel_username"
                          size="small"
                          text
                          :icon="CopyDocument"
                          @click="copyToClipboard(`@${tc.bin_channel_username}`, '频道公开Handle')"
                        >
                          复制Handle
                        </el-button>
                        <el-button
                          size="small"
                          text
                          :icon="CopyDocument"
                          @click="copyToClipboard(String(tc.bin_channel_id), '频道 ID')"
                        >
                          复制ID
                        </el-button>
                      </div>
                    </div>
                  </div>

                  <div v-else class="text-xs text-slate-500 py-3 text-center bg-white/70 rounded border border-dashed border-slate-300">
                    <span>当前协议号尚未为租户创建专属存储频道 (Telegram 普通号上限 10 个)。在「用户管理」中创建新租户时，系统将优先按同 DC 调度此号自动开通频道。</span>
                  </div>
                </div>

                <!-- 名下已创建的 Bot 列表 -->
                <div v-if="accountDetail.bots && accountDetail.bots.length > 0" class="bots-list-section p-3 rounded-lg border border-slate-200 bg-white">
                  <div class="font-semibold text-slate-800 text-xs mb-2">名下 @BotFather 机器人 (共 {{ accountDetail.bots.length }} 个):</div>
                  <div class="flex flex-wrap gap-2">
                    <span v-for="b in accountDetail.bots" :key="b.username" class="bot-chip">
                      @{{ b.username }}
                    </span>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <!-- Tab 3: Session 凭证与开发者 API -->
            <el-tab-pane name="credentials" label="🔑 Session 凭证与 API">
              <div class="tab-pane-content space-y-3 pt-1">
                <!-- Telegram 开发者 API 凭证 (api_id / api_hash) 专区 -->
                <div class="api-credentials-section p-3 rounded-lg border border-slate-200 bg-slate-50/80">
                  <div class="flex items-center justify-between flex-wrap gap-2 mb-2">
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="font-semibold text-slate-800 text-sm">Telegram 开发者 API 凭证</span>
                      <span v-if="accountDetail.metadata.api_id && accountDetail.metadata.api_hash" class="text-xs text-emerald-600 font-medium bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                        ✓ 已持久化落库
                      </span>
                      <span v-else class="text-xs text-amber-600 font-medium bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                        未配置专属凭证
                      </span>
                      <span class="text-xs text-sky-700 bg-sky-50 px-2 py-0.5 rounded border border-sky-200 font-medium">
                        🌐 归属地区: {{ accountDetail.metadata.region || accountDetail.account.region || 'US' }}
                      </span>
                    </div>
                    <div class="flex items-center gap-2">
                      <el-button
                        size="small"
                        type="primary"
                        plain
                        :icon="Connection"
                        :loading="fetchingApiCredentials"
                        @click="handleFetchApiFromMyTelegram"
                        title="通过协议号会话与同地区家宽住宅代理连接 my.telegram.org 自动提取或创建应用"
                      >
                        {{ fetchingApiCredentials ? '正在通过家宽代理提取...' : '从 my.telegram.org 自动提取' }}
                      </el-button>
                      <el-button
                        size="small"
                        :icon="Edit"
                        @click="openEditCredentialsModal"
                      >
                        编辑凭证
                      </el-button>
                    </div>
                  </div>

                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div class="bg-white p-2.5 rounded border border-slate-200">
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-slate-500 font-medium">App api_id:</span>
                        <el-button
                          v-if="accountDetail.metadata.api_id"
                          size="small"
                          text
                          :icon="CopyDocument"
                          @click="copyToClipboard(String(accountDetail.metadata.api_id), 'api_id')"
                        >
                          复制
                        </el-button>
                      </div>
                      <div class="font-mono text-sm font-bold" :class="accountDetail.metadata.api_id ? 'text-slate-800' : 'text-slate-400 italic'">
                        {{ accountDetail.metadata.api_id || '未配置' }}
                      </div>
                    </div>

                    <div class="bg-white p-2.5 rounded border border-slate-200">
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-slate-500 font-medium">App api_hash:</span>
                        <div class="flex items-center gap-1">
                          <el-button
                            v-if="accountDetail.metadata.api_hash"
                            size="small"
                            text
                            @click="showApiHash = !showApiHash"
                          >
                            {{ showApiHash ? '隐藏' : '显示' }}
                          </el-button>
                          <el-button
                            v-if="accountDetail.metadata.api_hash"
                            size="small"
                            text
                            :icon="CopyDocument"
                            @click="copyToClipboard(accountDetail.metadata.api_hash, 'api_hash')"
                          >
                            复制
                          </el-button>
                        </div>
                      </div>
                      <div class="font-mono text-sm font-bold truncate" :class="accountDetail.metadata.api_hash ? 'text-slate-800' : 'text-slate-400 italic'">
                        {{ accountDetail.metadata.api_hash ? (showApiHash ? accountDetail.metadata.api_hash : maskApiHash(accountDetail.metadata.api_hash)) : '未配置' }}
                      </div>
                    </div>
                  </div>

                  <div v-if="accountDetail.metadata.api_id && accountDetail.metadata.api_hash" class="mt-2 flex justify-end">
                    <el-button
                      size="small"
                      text
                      class="text-sky-600"
                      :icon="CopyDocument"
                      @click="copyToClipboard(`${accountDetail.metadata.api_id}:${accountDetail.metadata.api_hash}`, 'api_id:api_hash 组合')"
                    >
                      一键复制 api_id:api_hash 组合
                    </el-button>
                  </div>

                  <!-- 家宽代理策略与提示 -->
                  <div class="mt-2.5 pt-2 border-t border-slate-200/80 text-xs">
                    <div class="flex items-center justify-between flex-wrap gap-2">
                      <div class="flex items-center gap-1.5 text-slate-600">
                        <span class="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        <span>
                          家宽住宅代理: 系统将动态按 <strong>{{ accountDetail.metadata.region || accountDetail.account.region || 'US' }}</strong> 地区获取 10分钟粘性住宅 IP 穿透风控
                        </span>
                      </div>
                      <el-button
                        size="small"
                        text
                        class="text-sky-600 p-0 h-auto font-normal"
                        @click="showCustomProxyInput = !showCustomProxyInput"
                      >
                        {{ showCustomProxyInput ? '收起代理配置' : '自定义家宽代理' }}
                      </el-button>
                    </div>

                    <div v-if="showCustomProxyInput" class="mt-2 p-2.5 rounded bg-white border border-slate-200">
                      <div class="text-slate-600 mb-1 font-medium flex items-center justify-between">
                        <span>家宽住宅代理提取 URL (支持 <code>{region}</code> 或 <code>region=US</code> 占位符):</span>
                        <el-button size="small" text class="text-xs p-0 text-slate-400 hover:text-slate-600" @click="resetCustomProxyUrl">
                          恢复默认
                        </el-button>
                      </div>
                      <el-input
                        v-model="customProxyApiUrl"
                        size="small"
                        placeholder="https://proxy-api.example.com/api?region=US&num=1&time=10&format=1&type=txt"
                        clearable
                      />
                      <div class="text-[11px] text-slate-400 mt-1">
                        提取时系统将自动将 URL 中的 region 替换为该协议号对应的国家代码 (如 region={{ accountDetail.metadata.region || accountDetail.account.region || 'US' }})。
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Telethon 1.x StringSession 生成与导出 -->
                <div class="session-section">
                  <div class="session-section-header">
                    <div class="flex items-center gap-2">
                      <span class="font-semibold text-slate-800 text-sm">Telethon 1.x StringSession</span>
                      <span class="text-xs text-sky-600 font-mono bg-sky-50 px-2 py-0.5 rounded border border-sky-200">以 "1" 开头 · 标准格式</span>
                    </div>
                    <div class="flex items-center gap-2">
                      <el-button size="small" text @click="showTelethonSession = !showTelethonSession">
                        {{ showTelethonSession ? '隐藏密文' : '显示明文' }}
                      </el-button>
                      <el-button size="small" type="primary" :icon="CopyDocument" @click="copyToClipboard(accountDetail.sessions.telethon_session_string, 'Telethon Session')">
                        一键复制 Telethon Session
                      </el-button>
                    </div>
                  </div>
                  <el-input
                    :model-value="showTelethonSession ? accountDetail.sessions.telethon_session_string : maskSessionString(accountDetail.sessions.telethon_session_string)"
                    type="textarea"
                    :rows="3"
                    readonly
                    class="font-mono text-xs session-textarea"
                  />
                </div>

                <!-- Pyrogram 2.x Session String 导出 -->
                <div class="session-section">
                  <div class="session-section-header">
                    <div class="flex items-center gap-2">
                      <span class="font-semibold text-slate-800 text-sm">Pyrogram 2.x Session String</span>
                      <span class="text-xs text-purple-600 font-mono bg-purple-50 px-2 py-0.5 rounded border border-purple-200">Pyrogram 兼容格式</span>
                    </div>
                    <div class="flex items-center gap-2">
                      <el-button size="small" text @click="showPyrogramSession = !showPyrogramSession">
                        {{ showPyrogramSession ? '隐藏密文' : '显示明文' }}
                      </el-button>
                      <el-button size="small" type="primary" :icon="CopyDocument" @click="copyToClipboard(accountDetail.sessions.pyrogram_session_string, 'Pyrogram Session')">
                        一键复制 Pyrogram Session
                      </el-button>
                    </div>
                  </div>
                  <el-input
                    :model-value="showPyrogramSession ? accountDetail.sessions.pyrogram_session_string : maskSessionString(accountDetail.sessions.pyrogram_session_string)"
                    type="textarea"
                    :rows="3"
                    readonly
                    class="font-mono text-xs session-textarea"
                  />
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
      <template #footer>
        <el-button @click="accountDetailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 手动编辑 API 凭证模态框 -->
    <el-dialog
      v-model="editCredentialsDialogVisible"
      title="配置/编辑 Telegram API 开发者凭证"
      width="480px"
      append-to-body
      class="glass-dialog"
    >
      <el-form label-position="top">
        <el-form-item label="App api_id (纯数字)">
          <el-input
            v-model="editCredentialsForm.api_id"
            placeholder="例如: 21234567"
            clearable
          />
        </el-form-item>
        <el-form-item label="App api_hash (32位十六进制字符串)">
          <el-input
            v-model="editCredentialsForm.api_hash"
            placeholder="例如: b18441a1ff607e10a989891a5462e627"
            clearable
          />
        </el-form-item>
        <el-form-item label="备注说明 (可选)">
          <el-input
            v-model="editCredentialsForm.remark"
            placeholder="账号备注说明"
            clearable
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editCredentialsDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          class="primary-glow-btn"
          :loading="savingCredentials"
          @click="handleSaveCredentials"
        >
          保存凭证
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量导出 Telethon Session 模态框 -->
    <el-dialog
      v-model="batchExportDialogVisible"
      title="批量导出 Telethon 1.x StringSession 凭证"
      width="680px"
      append-to-body
      class="glass-dialog"
    >
      <div v-loading="batchExportLoading" class="dialog-body">
        <p class="dialog-tip">
          已将纳管协议号统一转换为 Telethon 标准 StringSession 格式（以 <code>1</code> 开头，每行一个），可用于第三方 Telethon 脚本、客户端或跨环境迁移。
        </p>
        <div class="flex items-center justify-between mb-3 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
          <span class="text-xs text-slate-700 font-medium">导出凭证格式:</span>
          <el-radio-group v-model="batchExportFormat" size="small" @change="updateBatchExportText">
            <el-radio-button label="session">纯 Session (手机号 | Session)</el-radio-button>
            <el-radio-button label="full">完整凭证 (手机号 | api_id | api_hash | Session)</el-radio-button>
          </el-radio-group>
        </div>
        <el-input
          v-model="batchExportText"
          type="textarea"
          :rows="12"
          readonly
          class="font-mono text-xs"
        />
      </div>
      <template #footer>
        <el-button @click="batchExportDialogVisible = false">关闭</el-button>
        <el-button :icon="Download" @click="downloadExportTextFile">保存为 .txt 文件</el-button>
        <el-button type="primary" :icon="CopyDocument" @click="copyToClipboard(batchExportText, '全部 Telethon Session')">一键复制全部</el-button>
      </template>
    </el-dialog>

    <!-- 自动保活配置模态框 -->
    <el-dialog
      v-model="keepaliveConfigDialogVisible"
      title="Telegram 协议号后台定时自动保活设置"
      width="520px"
      append-to-body
      class="glass-dialog"
    >
      <div v-loading="keepaliveConfigLoading" class="dialog-body space-y-4">
        <p class="dialog-tip">
          协议号长期静默未与 Telegram 服务器通信可能导致会话被注销或账号休眠。启用后后台 Worker 将定时执行轻量 MTProto 握手保持活跃，并在遇到断线时自动根据接码链接续登。
        </p>
        <el-form label-position="left" label-width="140px">
          <el-form-item label="定时自动保活开关">
            <el-switch v-model="keepaliveConfigForm.enabled" active-text="开启守护" inactive-text="关闭" />
          </el-form-item>
          <el-form-item label="保活巡检周期">
            <el-select v-model="keepaliveConfigForm.interval_hours" style="width: 100%">
              <el-option :value="6" label="每 6 小时巡检一次 (推荐)" />
              <el-option :value="12" label="每 12 小时巡检一次 (默认)" />
              <el-option :value="24" label="每 24 小时巡检一次" />
              <el-option :value="48" label="每 48 小时巡检一次" />
            </el-select>
          </el-form-item>
          <el-form-item label="保存时立即触发">
            <el-checkbox v-model="keepaliveConfigForm.trigger_now">保存后立即触发一次全量保活</el-checkbox>
          </el-form-item>
        </el-form>

        <div v-if="keepaliveConfigForm.last_summary" class="text-xs p-3 rounded bg-slate-50 border border-slate-200">
          <div class="font-semibold text-slate-700 mb-1">最近一次巡检汇总:</div>
          <div class="text-slate-600">时间: {{ keepaliveConfigForm.last_summary.run_at }}</div>
          <div class="text-slate-600">
            成功: <span class="text-emerald-600 font-bold">{{ keepaliveConfigForm.last_summary.success_count }}</span> ·
            失败: <span class="text-rose-600 font-bold">{{ keepaliveConfigForm.last_summary.failed_count }}</span> ·
            平均延迟: <span class="text-sky-600 font-bold">{{ keepaliveConfigForm.last_summary.avg_ping_ms }}ms</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="keepaliveConfigDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingKeepaliveConfig" @click="handleSaveKeepaliveConfig">保存设置</el-button>
      </template>
    </el-dialog>


    <!-- 快速查看 Telegram 登录验证码与 2FA 模态框 -->
    <el-dialog
      v-model="quickOtpDialogVisible"
      :title="`⚡ 实时登录验证码 (777000) - ${currentQuickOtpAccount?.phone || ''}`"
      width="520px"
      append-to-body
      class="glass-dialog"
    >
      <div v-loading="quickOtpLoading" class="dialog-body space-y-4">
        <div class="flex items-center justify-between p-2 rounded bg-slate-50 border border-slate-200 text-xs">
          <span class="text-slate-600">当前账号: <strong class="font-mono text-slate-800">{{ currentQuickOtpAccount?.phone }}</strong></span>
          <div class="flex items-center gap-2">
            <span
              v-if="quickOtpData?.is_recent"
              class="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200"
            >
              🟢 最新有效
            </span>
            <span
              v-else
              class="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-600 border border-amber-200"
            >
              {{ quickOtpData?.latest_code ? '⚠️ 可能已过期' : '🟡 等待发码' }}
            </span>
            <el-button
              size="small"
              :icon="RefreshRight"
              :loading="quickOtpLoading"
              @click="currentQuickOtpAccount && handleQuickViewOtp(currentQuickOtpAccount)"
            >
              刷新
            </el-button>
          </div>
        </div>

        <div
          class="otp-display-box text-center p-5 rounded-xl border-2 border-dashed border-sky-400/60 bg-sky-50/50 cursor-pointer hover:bg-sky-50 transition"
          @click="quickOtpData?.latest_code && copyToClipboard(quickOtpData.latest_code, '验证码')"
        >
          <div class="text-xs text-slate-500 mb-1">Telegram 5位登录验证码</div>
          <div class="font-mono font-extrabold text-3xl tracking-widest text-sky-600 my-1">
            {{ quickOtpData?.latest_code || '------' }}
          </div>
          <div class="text-[11px] text-slate-400">
            {{ quickOtpData?.latest_code ? '点击一键复制验证码' : '请在新客户端输入手机号触发验证码，系统将自动读取 777000' }}
          </div>
        </div>

        <div class="grid grid-cols-2 gap-2 text-xs">
          <div class="p-2 rounded bg-slate-50 border border-slate-200">
            <span class="text-slate-400 block mb-0.5">接收时间:</span>
            <span class="font-mono font-medium text-slate-700">{{ quickOtpData?.code_time || '暂无' }} ({{ quickOtpData?.relative_time }})</span>
          </div>
          <div class="p-2 rounded bg-slate-50 border border-slate-200">
            <span class="text-slate-400 block mb-0.5">尝试设备:</span>
            <span class="font-mono font-medium text-slate-700 truncate block">{{ quickOtpData?.device || '未知' }}</span>
          </div>
          <div class="p-2 rounded bg-slate-50 border border-slate-200">
            <span class="text-slate-400 block mb-0.5">登录 IP:</span>
            <span class="font-mono font-medium text-slate-700">{{ quickOtpData?.ip || '未知' }}</span>
          </div>
          <div class="p-2 rounded bg-slate-50 border border-slate-200">
            <span class="text-slate-400 block mb-0.5">地理位置:</span>
            <span class="font-medium text-slate-700">{{ quickOtpData?.location || '未知' }}</span>
          </div>
        </div>

        <div
          v-if="quickOtpData?.pass2fa"
          class="p-2.5 rounded bg-indigo-50 border border-indigo-200 flex items-center justify-between text-xs cursor-pointer"
          @click="copyToClipboard(quickOtpData.pass2fa, '2FA 密码')"
        >
          <div>
            <div class="text-indigo-600 font-semibold text-[11px]">2FA 二步验证云密码 (已加锁):</div>
            <div class="font-mono font-bold text-indigo-950 text-sm">{{ quickOtpData.pass2fa }}</div>
          </div>
          <el-button size="small" type="primary" plain :icon="CopyDocument">复制密码</el-button>
        </div>

        <div v-if="currentQuickOtpAccount?.local_otp_token" class="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
          <span class="text-slate-500">专属免密接码链接:</span>
          <div class="flex items-center gap-1">
            <el-button
              size="small"
              text
              :icon="CopyDocument"
              @click="copyToClipboard(getFullOtpUrl(currentQuickOtpAccount.local_otp_token), '专属接码链接')"
            >
              复制网页链接
            </el-button>
            <a
              :href="`/api/telegram/botfather/otp/${currentQuickOtpAccount.local_otp_token}`"
              target="_blank"
              class="text-xs text-sky-600 hover:underline inline-flex items-center gap-0.5 ml-1"
            >
              新窗口打开 ↗
            </a>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="quickOtpDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 开启 / 修改 2FA 云密码模态框 -->
    <el-dialog
      v-model="edit2faDialogVisible"
      :title="`设置 / 修改 2FA 云密码 - ${accountDetail?.account.phone || ''}`"
      width="480px"
      append-to-body
      class="glass-dialog"
    >
      <el-form label-position="top">
        <p class="dialog-tip mb-3 text-xs text-slate-500">
          设置 2FA 云密码后，任何新设备或号商尝试登录该账号，必须输入此密码才能通过校验。密码将加密落库并展示在后台，彻底杜绝号商收回风险！
        </p>

        <el-form-item label="当前 2FA 密码 (若当前已有密码必填，未设密码可留空)">
          <el-input
            v-model="edit2faForm.current_password"
            type="password"
            show-password
            placeholder="账号当前生效的原密码（系统将自动填入已记录的密码）"
            clearable
          />
        </el-form-item>

        <el-form-item label="新的 2FA 云密码 (必填，已为您自动生成强密码)">
          <div class="flex items-center gap-2 w-full">
            <el-input
              v-model="edit2faForm.new_password"
              type="text"
              placeholder="自定义强密码 (如 Mr-8kP4xV9mQ2wL)"
              clearable
              class="flex-1 font-mono"
            />
            <el-button @click="generateRandom2faPassword">
              🎲 随机生成
            </el-button>
            <el-button :icon="CopyDocument" @click="copyToClipboard(edit2faForm.new_password, '新 2FA 密码')">
              复制
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="密码提示 (Hint, 可选)">
          <el-input
            v-model="edit2faForm.hint"
            placeholder="提示信息 (留空则不设置提示)"
            clearable
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit2faDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="saving2fa"
          @click="handleSave2fa"
        >
          保存并立即锁定
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量提取 Telegram 开发者 API 模态框 -->
    <el-dialog
      v-model="batchFetchApiDialogVisible"
      title="批量提取 Telegram 开发者 API 凭证 (地区匹配家宽代理)"
      width="680px"
      append-to-body
      class="glass-dialog"
    >
      <div class="dialog-body space-y-4">
        <p class="dialog-tip">
          <code>my.telegram.org</code> 对机房 IP 与异地 IP 存在严格风控限制。系统将根据每个协议号的国际电话区号自动识别所属国家地区（如 <code>+1</code> ➔ <code>US</code>、<code>+95</code> ➔ <code>MM</code>、<code>+44</code> ➔ <code>GB</code>），并向家宽代理接口动态获取对应地区的 10 分钟粘性住宅 IP，全程穿透官网风控。
        </p>

        <el-form label-position="top">
          <el-form-item label="家宽住宅代理提取 API 链接:">
            <el-input
              v-model="batchFetchApiProxyUrl"
              placeholder="https://proxy-api.example.com/api?region=US&num=1&time=10&format=1&type=txt"
              clearable
            >
              <template #append>
                <el-button @click="resetBatchFetchApiProxyUrl">
                  恢复默认
                </el-button>
              </template>
            </el-input>
            <div class="text-xs text-slate-400 mt-1">
              无论配置固定 <code>region=US</code> 还是含 <code>{region}</code> 占位符，系统提取时均会自动替换为每个账号真实的地区代码。
            </div>
          </el-form-item>

          <el-form-item label="提取执行范围:">
            <el-radio-group v-model="batchFetchApiScope">
              <el-radio label="missing">
                仅提取尚未配置专属 API 的协议号 (推荐，共 {{ missingApiAccountCount }} 个)
              </el-radio>
              <el-radio label="all">
                提取全部有效协议号 (重新提取并覆盖，共 {{ activeAccountCount }} 个)
              </el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>

        <div v-if="batchFetchApiResults && batchFetchApiResults.length > 0" class="border border-slate-200 rounded-lg p-3 bg-slate-50/80 max-h-60 overflow-y-auto">
          <div class="text-xs font-semibold text-slate-700 mb-2 flex items-center justify-between">
            <span>提取执行结果明细:</span>
            <span>
              成功: <strong class="text-emerald-600">{{ batchFetchApiSummary.succeeded }}</strong> ·
              失败: <strong class="text-rose-600">{{ batchFetchApiSummary.failed }}</strong>
            </span>
          </div>
          <div class="space-y-1.5 text-xs">
            <div
              v-for="r in batchFetchApiResults"
              :key="r.account_id"
              class="flex items-center justify-between p-2 rounded bg-white border border-slate-200"
            >
              <div class="flex items-center gap-2">
                <span class="font-mono font-medium">{{ r.phone }}</span>
                <span v-if="r.region" class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-sky-50 text-sky-700 border border-sky-200">
                  {{ r.region }}
                </span>
                <span v-if="r.proxy_used" class="text-[11px] text-slate-400 font-mono">
                  [{{ r.proxy_used }}]
                </span>
              </div>
              <div>
                <span v-if="r.success" class="text-emerald-600 font-medium">
                  ✅ 成功 (api_id: {{ r.api_id }})
                </span>
                <span v-else class="text-rose-600" :title="r.error">
                  ❌ {{ r.error || '提取失败' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="batchFetchApiDialogVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :icon="Connection"
          :loading="batchFetchingApi"
          @click="handleStartBatchFetchApi"
        >
          {{ batchFetchingApi ? '正在按地区调度家宽代理批量提取...' : '开始批量提取' }}
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from "vue"
import { useRouter } from "vue-router"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  RefreshRight,
  Plus,
  Connection,
  Promotion,
  Iphone,
  UploadFilled,
  VideoPlay,
  VideoPause,
  MagicStick,
  Timer,
  Delete,
  Warning,
  Loading,
  View,
  Cpu,
  Download,
  Setting,
  CopyDocument,
  Edit,
  Check,
  Lock,
  Unlock,
  ChatDotRound,
  Search,
} from "@element-plus/icons-vue"
import {
  getStatus,
  getBotFatherTaskStatus,
  startBotFatherTask,
  stopBotFatherTask,
  botfatherAutoCreate,
  hotAddBots,
  getProtocolAccounts,
  importProtocolAccounts,
  getImportAccountTaskStatus,
  deleteProtocolAccount,
  checkProtocolAccount,
  getProtocolAccountDetail,
  keepaliveSingleProtocolAccount,
  keepaliveAllProtocolAccounts,
  getKeepaliveConfig,
  updateKeepaliveConfig,
  getApiProxyConfig,
  fetchProtocolAccountApi,
  batchFetchProtocolAccountApi,
  updateProtocolAccountCredentials,
  fetchProtocolAccountLoginCode,
  getProtocolAccount2FA,
  updateProtocolAccount2FA,
  terminateProtocolAccountOtherSessions,
  cancelProtocolAccountPasswordReset,
  bindProtocolAccountLocalOtp,
  takeoverProtocolAccount,
  batchTakeoverProtocolAccounts,
  syncAllProtocolAccounts,
  type ProtocolAccountLoginCodeData,
  type ProtocolAccount2FAStatusData,
  type BotFatherTaskStatus,
  type ProtocolAccount,
  type ProtocolAccountDetail,
  type BatchImportAccountsResult,
} from "@/api"
import type { BotDetail, ChannelInfo } from "@/types/api"

const router = useRouter()

const loading = ref(false)
const startingTask = ref(false)
const syncMintLoading = ref(false)
const hotAdding = ref(false)

const botDetails = ref<BotDetail[]>([])
const channelInfo = ref<ChannelInfo | null>(null)
const workloads = ref<Record<string, number>>({})

const inputMode = ref<"phone_url" | "session_str" | "session_file">("phone_url")
const selectedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const terminalBodyRef = ref<HTMLElement | null>(null)

const mintForm = ref({
  sessionString: "+16813086196",
  count: 20,
  namePrefix: "MistRelay Node",
  reuseExisting: true,
})

const taskStatus = ref<BotFatherTaskStatus>({
  task_id: null,
  status: "idle",
  target_count: 20,
  created_count: 0,
  reused_count: 0,
  total_active_workers: 0,
  cooldown_remaining: 0,
  cooldown_total: 0,
  current_step: "",
  percent: 0,
  logs: [],
  bots: [],
  error: null,
  cached_sessions: [],
})

const hotAddDialogVisible = ref(false)
const hotAddTokensInput = ref("")

// ==================== 协议号资产池与双模铸造状态 ====================
const accountsList = ref<ProtocolAccount[]>([])
const accountsLoading = ref(false)
const mintStrategy = ref<"relay" | "single">("relay")
const selectedRelayAccountIds = ref<number[]>([])
const selectedSingleAccountId = ref<number | null>(null)
const batchImportDialogVisible = ref(false)
const batchImportForm = ref({ textContent: "", remark: "" })
const batchImportFiles = ref<File[]>([])
const batchFileInputRef = ref<HTMLInputElement | null>(null)
const batchImportLoading = ref(false)
const batchImportResult = ref<BatchImportAccountsResult | null>(null)
const checkAccountLoading = ref<number | null>(null)

const hasFetchedAccounts = ref(false)

const protocolAccounts = computed<ProtocolAccount[]>(() => {
  if (hasFetchedAccounts.value) return accountsList.value
  if (accountsList.value.length > 0) return accountsList.value
  if (taskStatus.value.accounts && taskStatus.value.accounts.length > 0) return taskStatus.value.accounts
  return []
})

// 协议号资产池搜索、多维筛选与分页状态
const accountSearchQuery = ref("")
const accountStatusFilter = ref<string>("all")
const account2faFilter = ref<string>("all")
const accountDcFilter = ref<string>("all")
const accountChannelFilter = ref<string>("all")
const accountSortOrder = ref<string>("default")
const accountCurrentPage = ref(1)
const accountPageSize = ref(12)
const syncingAllAccounts = ref(false)

const hasActiveAccountFilters = computed(() => {
  return (
    accountSearchQuery.value.trim() !== "" ||
    accountStatusFilter.value !== "all" ||
    account2faFilter.value !== "all" ||
    accountDcFilter.value !== "all" ||
    accountChannelFilter.value !== "all" ||
    accountSortOrder.value !== "default"
  )
})

function resetAccountFilters() {
  accountSearchQuery.value = ""
  accountStatusFilter.value = "all"
  account2faFilter.value = "all"
  accountDcFilter.value = "all"
  accountChannelFilter.value = "all"
  accountSortOrder.value = "default"
  accountCurrentPage.value = 1
}

watch(
  [accountSearchQuery, accountStatusFilter, account2faFilter, accountDcFilter, accountChannelFilter, accountSortOrder, accountPageSize],
  () => {
    accountCurrentPage.value = 1
  }
)

const sortedAndFilteredAccounts = computed<ProtocolAccount[]>(() => {
  let list = [...protocolAccounts.value]

  // 1. 关键词搜索 (模糊匹配手机号、用户名、TG UID、备注、归属地)
  const q = accountSearchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((acc) => {
      const phone = (acc.phone || "").toLowerCase()
      const uname = (acc.username || "").toLowerCase()
      const fname = (acc.first_name || "").toLowerCase()
      const uid = String(acc.tg_user_id || "")
      const remark = (acc.remark || "").toLowerCase()
      const region = (acc.region || "").toLowerCase()
      const dc = `dc${acc.dc_id || ""}`.toLowerCase()
      return (
        phone.includes(q) ||
        uname.includes(q) ||
        fname.includes(q) ||
        uid.includes(q) ||
        remark.includes(q) ||
        region.includes(q) ||
        dc.includes(q)
      )
    })
  }

  // 2. 状态筛选
  if (accountStatusFilter.value !== "all") {
    list = list.filter((acc) => acc.status === accountStatusFilter.value)
  }

  // 3. 2FA 安全接管筛选
  if (account2faFilter.value === "taken_over") {
    list = list.filter((acc) => Boolean(acc.is_taken_over))
  } else if (account2faFilter.value === "pending") {
    list = list.filter((acc) => !acc.is_taken_over)
  }

  // 4. DC 区域筛选
  if (accountDcFilter.value !== "all") {
    list = list.filter((acc) => String(acc.dc_id || "") === accountDcFilter.value)
  }

  // 5. 租户频道托管状态筛选
  if (accountChannelFilter.value === "has_channels") {
    list = list.filter((acc) => (acc.created_channels_count || 0) > 0)
  } else if (accountChannelFilter.value === "no_channels") {
    list = list.filter((acc) => (acc.created_channels_count || 0) === 0)
  }

  // 6. 排序规则
  const order = accountSortOrder.value
  if (order === "channels_desc") {
    list.sort((a, b) => (b.created_channels_count || 0) - (a.created_channels_count || 0))
  } else if (order === "channels_asc") {
    list.sort((a, b) => (a.created_channels_count || 0) - (b.created_channels_count || 0))
  } else if (order === "bot_count_desc") {
    list.sort((a, b) => (b.bot_count || 0) - (a.bot_count || 0))
  } else if (order === "bot_count_asc") {
    list.sort((a, b) => (a.bot_count || 0) - (b.bot_count || 0))
  } else if (order === "ping_asc") {
    list.sort((a, b) => {
      const pa = a.keepalive_ping_ms ?? 999999
      const pb = b.keepalive_ping_ms ?? 999999
      return pa - pb
    })
  } else if (order === "keepalive_desc") {
    list.sort((a, b) => {
      const ta = a.last_keepalive_at ? new Date(a.last_keepalive_at).getTime() : 0
      const tb = b.last_keepalive_at ? new Date(b.last_keepalive_at).getTime() : 0
      return tb - ta
    })
  }

  return list
})

watch(sortedAndFilteredAccounts, (newVal) => {
  const maxPage = Math.max(1, Math.ceil(newVal.length / accountPageSize.value))
  if (accountCurrentPage.value > maxPage) {
    accountCurrentPage.value = maxPage
  }
})

const paginatedAccounts = computed<ProtocolAccount[]>(() => {
  const start = (accountCurrentPage.value - 1) * accountPageSize.value
  return sortedAndFilteredAccounts.value.slice(start, start + accountPageSize.value)
})

async function handleSyncAllAccounts() {
  syncingAllAccounts.value = true
  try {
    const res = await syncAllProtocolAccounts(undefined, true)
    if (res.success && res.data) {
      accountsList.value = res.data
      const total = res.summary?.total || res.data.length
      const successCount = res.summary?.success_count || 0
      ElMessage.success(
        `全池数据同步完成！共探测 ${total} 个协议号，成功同步 ${successCount} 个账号的真实持机数、TG 官方档案与租户专属频道`
      )
      await fetchClusterStatus()
    } else {
      ElMessage.error(res.error || "全池数据同步失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "全池数据同步请求异常")
  } finally {
    syncingAllAccounts.value = false
  }
}

const totalRemainingQuota = computed(() =>
  protocolAccounts.value.reduce((acc, a) => acc + (a.remaining_quota ?? Math.max(0, 20 - a.bot_count)), 0)
)

const totalBotCountInPool = computed(() =>
  protocolAccounts.value.reduce((acc, a) => acc + (a.bot_count || 0), 0)
)

const phoneInputPlaceholder = computed(() => {
  if (mintStrategy.value === "relay") {
    return "支持多行粘贴，例如:\n+16813086196|https://miha.uk/tgapi/xxx/GetHTML\n+18048484620|https://568.5689889.uk/xxx/GetHTML"
  }
  return "例如: +16813086196|https://miha.uk/tgapi/xxx/GetHTML 或直接输入已缓存手机号 +16813086196"
})

const relayMaxCount = computed(() => {
  const countAccs = Math.max(1, selectedRelayAccountIds.value.length || protocolAccounts.value.length)
  return Math.max(40, Math.min(200, countAccs * 20))
})

let pollTimer: number | null = null

// @ts-ignore
const _cachedPhones = computed(() => {
  if (taskStatus.value.cached_sessions && taskStatus.value.cached_sessions.length > 0) {
    return taskStatus.value.cached_sessions
  }
  return protocolAccounts.value.map(a => ({ phone: a.phone, cached: true }))
})

const isTaskActive = computed(() =>
  taskStatus.value.status === "running" || taskStatus.value.status === "cooling_down"
)

const taskStatusLabel = computed(() => {
  const map: Record<string, string> = {
    idle: "空闲待命",
    running: "正在自动铸造",
    cooling_down: "BotFather 频率冷却中",
    completed: "任务已完成",
    stopped: "已手动停止",
    failed: "执行受限/停止",
  }
  return map[taskStatus.value.status] || "待命"
})

const taskStatusDotClass = computed(() => {
  if (taskStatus.value.status === "running") return "dot-sky pulse"
  if (taskStatus.value.status === "cooling_down") return "dot-amber pulse"
  if (taskStatus.value.status === "completed") return "dot-emerald"
  if (taskStatus.value.status === "failed") return "dot-red"
  return "dot-slate"
})

const cooldownNotice = computed(() => {
  if (taskStatus.value.status === "cooling_down" && taskStatus.value.cooldown_remaining > 0) {
    return "Telegram 官方对连续创建机器人设有频率间隔保护，后台任务正在静默等待倒计时结束并将自动继续创建。"
  }
  const errText = taskStatus.value.error || ""
  const lastErrLog = [...taskStatus.value.logs].reverse().find(l => l.level === "error")?.msg || ""
  const combined = `${errText} ${lastErrLog}`
  if (combined.includes("seconds")) {
    const m = combined.match(/(\d+)\s*seconds/i)
    const sec = m ? Number(m[1]) : 0
    if (sec > 3600) {
      const hours = (sec / 3600).toFixed(1)
      return `当前协议号已触发 Telegram 官方单账号每日新建 Bot 额度上限 (需冷却约 ${hours} 小时)。该账号已创建的存量机器人已全部热挂载入网！您可切换其他协议号或直接粘贴已有 Token 继续扩容。`
    }
    if (sec > 0) {
      return `@BotFather 要求冷却等待 ${sec} 秒，请稍候重试或使用后台自动等待流水线。`
    }
  }
  return ""
})

function switchMintStrategy(strategy: "relay" | "single") {
  mintStrategy.value = strategy
  if (strategy === "single") {
    if (mintForm.value.count > 20) {
      mintForm.value.count = 20
    }
    if (selectedSingleAccountId.value === null && protocolAccounts.value.length > 0) {
      selectedSingleAccountId.value = protocolAccounts.value[0].id
    }
  }
}

function toggleSelectAllRelayAccounts() {
  if (selectedRelayAccountIds.value.length === protocolAccounts.value.length) {
    selectedRelayAccountIds.value = []
  } else {
    selectedRelayAccountIds.value = protocolAccounts.value.filter(a => a.status !== "invalid").map(a => a.id)
  }
}

function handleQuickSingleMint(acc: ProtocolAccount) {
  mintStrategy.value = "single"
  selectedSingleAccountId.value = acc.id
  mintForm.value.sessionString = acc.phone
  mintForm.value.count = Math.min(mintForm.value.count, 20)
  ElMessage.success(`已切换为此号精准铸造：${acc.phone} (剩余配额: ${acc.remaining_quota})`)
}

async function handleCheckAccount(acc: ProtocolAccount) {
  checkAccountLoading.value = acc.id
  try {
    const res = await checkProtocolAccount(acc.id)
    if (res.success && res.data) {
      ElMessage.success(`协议号 ${acc.phone} 状态健康！持有 ${res.data.bots_found} 个机器人`)
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "检测失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "检测协议号异常")
  } finally {
    checkAccountLoading.value = null
  }
}

async function handleDeleteAccount(acc: ProtocolAccount) {
  try {
    await ElMessageBox.confirm(
      `确定要将协议号 ${acc.phone} 从资产池中移除吗？已挂载运行的机器人节点不受影响。`,
      "移除协议号确认",
      {
        confirmButtonText: "确认移除",
        cancelButtonText: "取消",
        type: "warning",
      }
    )
  } catch {
    return
  }

  try {
    const res = await deleteProtocolAccount(acc.id, acc.phone)
    if (res.success) {
      ElMessage.success(`已移除协议号 ${acc.phone}`)
      accountsList.value = accountsList.value.filter(a => a.id !== acc.id && a.phone !== acc.phone)
      selectedRelayAccountIds.value = selectedRelayAccountIds.value.filter(id => id !== acc.id)
      if (selectedSingleAccountId.value === acc.id) {
        selectedSingleAccountId.value = accountsList.value.length > 0 ? accountsList.value[0].id : null
      }
      if (taskStatus.value.accounts) {
        taskStatus.value.accounts = taskStatus.value.accounts.filter((a: any) => a.id !== acc.id && a.phone !== acc.phone)
      }
      if (taskStatus.value.cached_sessions) {
        taskStatus.value.cached_sessions = taskStatus.value.cached_sessions.filter((a: any) => a.phone !== acc.phone)
      }
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "移除失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "移除协议号失败")
  }
}

const importTaskId = ref<string | null>(null)
const importTaskStatus = ref<string>("idle")
const importTaskProgressMsg = ref<string>("")
const importTaskCurrentPhone = ref<string>("")
const importTaskCooldown = ref<number>(0)
const importTaskLogs = ref<Array<{ time: string; msg: string }>>([])
let importPollTimer: any = null

function openBatchImportModal() {
  batchImportForm.value = { textContent: "", remark: "" }
  batchImportFiles.value = []
  batchImportResult.value = null
  importTaskId.value = null
  importTaskStatus.value = "idle"
  importTaskProgressMsg.value = ""
  importTaskCurrentPhone.value = ""
  importTaskCooldown.value = 0
  importTaskLogs.value = []
  batchImportDialogVisible.value = true
}

function triggerBatchFileInput() {
  batchFileInputRef.value?.click()
}

function handleBatchFilesSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files) {
    batchImportFiles.value = Array.from(target.files)
  }
}

async function handleConfirmBatchImport() {
  const text = batchImportForm.value.textContent.trim()
  if (!text && batchImportFiles.value.length === 0) {
    ElMessage.warning("请输入协议号文本或选择 .session 文件")
    return
  }

  batchImportLoading.value = true
  batchImportResult.value = null
  importTaskProgressMsg.value = "正在提交协议号导入任务..."
  importTaskCurrentPhone.value = ""
  importTaskCooldown.value = 0
  importTaskLogs.value = []

  try {
    let res: any
    if (batchImportFiles.value.length > 0) {
      const fd = new FormData()
      for (const f of batchImportFiles.value) {
        fd.append("session_files", f)
      }
      if (text) {
        fd.append("content", text)
      }
      if (batchImportForm.value.remark.trim()) {
        fd.append("remark", batchImportForm.value.remark.trim())
      }
      res = await importProtocolAccounts(fd)
    } else {
      res = await importProtocolAccounts({
        content: text,
        remark: batchImportForm.value.remark.trim() || undefined,
      })
    }

    if (!res.success) {
      ElMessage.error(res.error || "批量导入失败")
      batchImportLoading.value = false
      return
    }

    if (res.data?.async && res.data?.task_id) {
      importTaskId.value = res.data.task_id
      importTaskStatus.value = "running"
      importTaskProgressMsg.value = res.data.message || "后台任务已启动，正在连接 Telegram 并监听验证码..."
      startImportTaskPolling(res.data.task_id)
    } else if (res.data && res.data.imported_count !== undefined) {
      batchImportResult.value = res.data
      batchImportLoading.value = false
      ElMessage.success(`成功解析并导入 ${res.data.imported_count} 个协议号！`)
      await fetchAccounts()
      if (res.data.failed_count === 0) {
        setTimeout(() => {
          batchImportDialogVisible.value = false
        }, 1200)
      }
    } else {
      ElMessage.error(res.error || "未能获取导入结果")
      batchImportLoading.value = false
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "批量导入异常")
    batchImportLoading.value = false
  }
}

function startImportTaskPolling(taskId: string) {
  if (importPollTimer) {
    clearInterval(importPollTimer)
  }

  const poll = async () => {
    try {
      const res = await getImportAccountTaskStatus(taskId)
      if (!res.success || !res.data) return

      const data = res.data
      importTaskStatus.value = data.status
      importTaskProgressMsg.value = data.progress_msg || ""
      importTaskCurrentPhone.value = data.current_phone || ""
      importTaskCooldown.value = data.cooldown_remaining || 0
      importTaskLogs.value = data.logs || []

      if (data.status === "completed") {
        if (importPollTimer) {
          clearInterval(importPollTimer)
          importPollTimer = null
        }
        batchImportLoading.value = false
        batchImportResult.value = {
          imported_count: data.imported_count,
          failed_count: data.failed_count,
          imported: data.imported,
          errors: data.errors,
          pool: data.pool || [],
        }
        if (data.imported_count > 0) {
          ElMessage.success(`导入完成！成功解析入库 ${data.imported_count} 个协议号`)
        } else {
          ElMessage.warning(`导入完成：未能成功入库协议号 (失败 ${data.failed_count} 个)`)
        }
        await fetchAccounts()
        if (data.failed_count === 0) {
          setTimeout(() => {
            batchImportDialogVisible.value = false
          }, 1500)
        }
      } else if (data.status === "failed") {
        if (importPollTimer) {
          clearInterval(importPollTimer)
          importPollTimer = null
        }
        batchImportLoading.value = false
        ElMessage.error(data.error || "导入任务异常终止")
      }
    } catch (e: any) {
      console.warn("轮询导入任务状态异常:", e)
    }
  }

  poll()
  importPollTimer = setInterval(poll, 1500)
}

function formatAccountStatus(status?: string): string {
  const map: Record<string, string> = {
    active: "正常可用",
    limit_reached: "达20个上限",
    cooling_down: "频率冷却中",
    restricted: "SpamBot受限",
    invalid: "已失效",
  }
  return map[status || ""] || status || "正常"
}

function formatAccountHistoryStatus(status?: string): string {
  const map: Record<string, string> = {
    ok: "完成",
    completed: "目标达成",
    limit_reached: "单号达20切号",
    cooling_down: "频率冷却切号",
    restricted: "受限跳过",
    error: "异常跳过",
  }
  return map[status || ""] || status || "就绪"
}

async function fetchAccounts() {
  accountsLoading.value = true
  try {
    const res = await getProtocolAccounts()
    hasFetchedAccounts.value = true
    if (res.success && res.data) {
      accountsList.value = res.data
      if (selectedRelayAccountIds.value.length === 0) {
        selectedRelayAccountIds.value = res.data.filter(a => a.status !== "invalid").map(a => a.id)
      }
      if (selectedSingleAccountId.value === null && res.data.length > 0) {
        selectedSingleAccountId.value = res.data[0].id
      }
    }
  } catch (err) {
    // ignore
  } finally {
    accountsLoading.value = false
  }
}

function selectCachedPhone(phone: string) {
  inputMode.value = "phone_url"
  mintForm.value.sessionString = phone
  ElMessage.success(`已选择缓存协议号 ${phone}，可直接启动铸造或提取存量节点`)
}

function triggerFileSelect() {
  fileInputRef.value?.click()
}

function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) {
    selectedFile.value = file
  }
}

async function fetchClusterStatus() {
  try {
    const statusRes = await getStatus()
    botDetails.value = statusRes.bot_details || []
    channelInfo.value = statusRes.channel_info || null
    workloads.value = statusRes.workloads || {}
  } catch (err) {
    // ignore
  }
}

async function fetchTaskStatus() {
  try {
    const res = await getBotFatherTaskStatus()
    if (res.success && res.data) {
      const prevCount = taskStatus.value.bots?.length || 0
      taskStatus.value = res.data
      const newCount = res.data.bots?.length || 0
      if (newCount > prevCount || res.data.status === "completed") {
        await Promise.all([fetchClusterStatus(), fetchAccounts()])
      }
      await nextTick()
      if (terminalBodyRef.value) {
        terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight
      }
    }
  } catch (err) {
    // ignore transient poll errors
  }
}

async function fetchAllData() {
  loading.value = true
  try {
    await Promise.all([fetchClusterStatus(), fetchTaskStatus(), fetchAccounts(), loadProxyConfig()])
  } finally {
    loading.value = false
  }
}

async function handleStartBackgroundMint() {
  startingTask.value = true
  try {
    let res
    if (mintStrategy.value === "single") {
      if (selectedSingleAccountId.value !== null) {
        res = await startBotFatherTask({
          mode: "single",
          single_account_id: selectedSingleAccountId.value,
          count: Math.min(mintForm.value.count, 20),
          name_prefix: mintForm.value.namePrefix || "MistRelay Node",
          reuse_existing: mintForm.value.reuseExisting,
        })
      } else {
        res = await startBotFatherTask({
          mode: "single",
          session_string: mintForm.value.sessionString.trim(),
          count: Math.min(mintForm.value.count, 20),
          name_prefix: mintForm.value.namePrefix || "MistRelay Node",
          reuse_existing: mintForm.value.reuseExisting,
        })
      }
    } else {
      res = await startBotFatherTask({
        mode: "relay",
        account_ids: selectedRelayAccountIds.value.length > 0 ? selectedRelayAccountIds.value : undefined,
        count: mintForm.value.count,
        name_prefix: mintForm.value.namePrefix || "MistRelay Node",
        reuse_existing: mintForm.value.reuseExisting,
      })
    }

    if (res.success && res.data) {
      taskStatus.value = res.data
      ElMessage.success("流水线已启动！可在右侧终端实时观察造机与挂载进度")
      startPolling()
    } else {
      ElMessage.error(res.error || "启动任务失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "启动任务异常")
  } finally {
    startingTask.value = false
  }
}

async function handleStopTask() {
  try {
    const res = await stopBotFatherTask()
    if (res.success && res.data) {
      taskStatus.value = res.data
      ElMessage.warning("已停止后台自动铸造任务")
    }
  } catch (err: any) {
    ElMessage.error(err?.message || "停止任务失败")
  }
}

async function handleSyncAutoCreate() {
  syncMintLoading.value = true
  try {
    let res
    if (inputMode.value === "session_file") {
      if (!selectedFile.value) {
        ElMessage.warning("请先选择 .session 文件")
        return
      }
      const fd = new FormData()
      fd.append("session_file", selectedFile.value)
      fd.append("count", String(mintForm.value.count))
      fd.append("name_prefix", mintForm.value.namePrefix || "MistRelay Node")
      fd.append("reuse_existing", String(mintForm.value.reuseExisting))
      res = await botfatherAutoCreate(fd)
    } else {
      if (!mintForm.value.sessionString.trim()) {
        ElMessage.warning("请输入协议号信息")
        return
      }
      res = await botfatherAutoCreate({
        session_string: mintForm.value.sessionString.trim(),
        count: mintForm.value.count,
        name_prefix: mintForm.value.namePrefix || "MistRelay Node",
        reuse_existing: mintForm.value.reuseExisting,
      })
    }

    if (res.success && res.data) {
      const d = res.data
      ElMessage.success(
        `同步执行完成：复用 ${d.reused_count} 个，新建 ${d.created_count} 个，当前共 ${d.total_active_workers} 个从节点`
      )
      await fetchAllData()
    } else {
      ElMessage.error(res.error || "执行失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "同步执行失败")
  } finally {
    syncMintLoading.value = false
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
      await Promise.all([fetchClusterStatus(), fetchAccounts()])
    } else {
      ElMessage.error(res.error || "挂载失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "热挂载失败")
  } finally {
    hotAdding.value = false
  }
}

function formatCooldown(sec: number): string {
  if (sec >= 3600) {
    return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
  }
  if (sec >= 60) {
    return `${Math.floor(sec / 60)}m ${sec % 60}s`
  }
  return `${sec}s`
}

function startPolling() {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(() => {
    void fetchTaskStatus()
  }, 2500)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  if (otpPollTimer !== null) {
    window.clearInterval(otpPollTimer)
    otpPollTimer = null
  }
  if (importPollTimer) {
    clearInterval(importPollTimer)
    importPollTimer = null
  }
}


// ================= 协议号详情、Session 生成与保活状态 =================
const accountDetailDialogVisible = ref(false)
const detailActiveTab = ref<'security' | 'channels' | 'credentials'>('security')
const detailLoading = ref(false)
const detailOnlineRefreshing = ref(false)
const accountDetail = ref<ProtocolAccountDetail | null>(null)
const showTelethonSession = ref(false)
const showPyrogramSession = ref(false)
const showApiHash = ref(false)
const fetchingApiCredentials = ref(false)
const editCredentialsDialogVisible = ref(false)
const savingCredentials = ref(false)
const editCredentialsForm = ref({
  api_id: '',
  api_hash: '',
  remark: '',
})
const batchExportFormat = ref<'session' | 'full'>('session')
const batchExportCachedDetails = ref<Record<number, any>>({})

function maskApiHash(hash: string): string {
  if (!hash) return ''
  if (hash.length >= 8) return `${hash.slice(0, 4)}****${hash.slice(-4)}`
  return '***'
}

const defaultProxyApiUrl = ref("")
const customProxyApiUrl = ref("")
const showCustomProxyInput = ref(false)
const batchFetchApiDialogVisible = ref(false)
const batchFetchingApi = ref(false)
const batchFetchApiProxyUrl = ref("")
const batchFetchApiScope = ref<'missing' | 'all'>('missing')
const batchFetchApiResults = ref<any[] | null>(null)

const missingApiAccountCount = computed(() =>
  protocolAccounts.value.filter(a => !(a.api_id && a.has_api_hash) && a.status !== 'invalid').length
)
const activeAccountCount = computed(() =>
  protocolAccounts.value.filter(a => a.status !== 'invalid').length
)
const pendingTakeoverAccounts = computed(() =>
  protocolAccounts.value.filter(a => !a.is_taken_over && a.status !== 'invalid')
)
const takenOverAccountsCount = computed(() =>
  protocolAccounts.value.filter(a => Boolean(a.is_taken_over)).length
)
const batchFetchApiSummary = computed(() => {
  if (!batchFetchApiResults.value) return { succeeded: 0, failed: 0 }
  return {
    succeeded: batchFetchApiResults.value.filter(r => r.success).length,
    failed: batchFetchApiResults.value.filter(r => !r.success).length,
  }
})

async function loadProxyConfig() {
  try {
    const res = await getApiProxyConfig()
    if (res.success && res.data) {
      defaultProxyApiUrl.value = res.data.proxy_api_url || res.data.default_url || ""
      if (!customProxyApiUrl.value && defaultProxyApiUrl.value) {
        customProxyApiUrl.value = defaultProxyApiUrl.value
      }
      if (!batchFetchApiProxyUrl.value && defaultProxyApiUrl.value) {
        batchFetchApiProxyUrl.value = defaultProxyApiUrl.value
      }
    }
  } catch (e) {
    // ignore
  }
}

function resetCustomProxyUrl() {
  customProxyApiUrl.value = defaultProxyApiUrl.value
}

function resetBatchFetchApiProxyUrl() {
  batchFetchApiProxyUrl.value = defaultProxyApiUrl.value || customProxyApiUrl.value
}

function openBatchFetchApiModal() {
  batchFetchApiDialogVisible.value = true
  batchFetchApiResults.value = null
  batchFetchApiProxyUrl.value = customProxyApiUrl.value || defaultProxyApiUrl.value || ""
}

async function handleStartBatchFetchApi() {
  batchFetchingApi.value = true
  try {
    ElMessage.info("开始按协议号地区匹配家宽代理批量提取 API 凭证...")
    const res = await batchFetchProtocolAccountApi({
      only_missing: batchFetchApiScope.value === 'missing',
      proxy_api_url: batchFetchApiProxyUrl.value.trim() || undefined,
    })
    if (res.success && res.data) {
      batchFetchApiResults.value = res.data.results
      if (res.data.accounts) {
        accountsList.value = res.data.accounts
      }
      batchExportCachedDetails.value = {}
      ElMessage.success(`批量提取并持久化落库完成！成功: ${res.data.succeeded} 个，失败: ${res.data.failed} 个`)
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "批量提取执行失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "批量提取异常")
  } finally {
    batchFetchingApi.value = false
  }
}

async function handleFetchApiFromMyTelegram() {
  if (!accountDetail.value) return
  const accId = accountDetail.value.account.id
  const targetRegion = accountDetail.value.metadata.region || accountDetail.value.account.region || 'US'
  fetchingApiCredentials.value = true
  try {
    ElMessage.info(`正在通过 ${targetRegion} 地区匹配家宽住宅代理连接 my.telegram.org 并拦截 777000 官方验证码...`)
    const res = await fetchProtocolAccountApi(accId, customProxyApiUrl.value.trim() || undefined)
    if (res.success && res.data) {
      accountDetail.value = res.data.detail
      if ((res.data as any).pool) {
        accountsList.value = (res.data as any).pool
      }
      batchExportCachedDetails.value = {}
      const usedProxy = res.data.proxy_used ? ` (代理: ${res.data.proxy_used})` : ''
      ElMessage.success(`成功提取并已持久化落库！api_id: ${res.data.api_id}${usedProxy}`)
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "从官网提取凭证失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "提取 API 凭证异常")
  } finally {
    fetchingApiCredentials.value = false
  }
}

function openEditCredentialsModal() {
  if (!accountDetail.value) return
  editCredentialsForm.value = {
    api_id: accountDetail.value.metadata.api_id ? String(accountDetail.value.metadata.api_id) : '',
    api_hash: accountDetail.value.metadata.api_hash || '',
    remark: accountDetail.value.account.remark || '',
  }
  editCredentialsDialogVisible.value = true
}

async function handleSaveCredentials() {
  if (!accountDetail.value) return
  const accId = accountDetail.value.account.id
  savingCredentials.value = true
  try {
    const rawId = editCredentialsForm.value.api_id.trim()
    const apiIdVal = rawId ? parseInt(rawId, 10) : null
    const res = await updateProtocolAccountCredentials(accId, {
      api_id: apiIdVal,
      api_hash: editCredentialsForm.value.api_hash.trim() || null,
      remark: editCredentialsForm.value.remark.trim() || undefined,
    })
    if (res.success && res.data) {
      accountDetail.value = res.data
      if ((res.data as any).pool) {
        accountsList.value = (res.data as any).pool
      }
      batchExportCachedDetails.value = {}
      editCredentialsDialogVisible.value = false
      ElMessage.success("开发者 API 凭证保存并已持久化落库！")
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "保存凭证失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "保存凭证异常")
  } finally {
    savingCredentials.value = false
  }
}

const singleKeepaliveLoading = ref<number | null>(null)
const keepaliveAllLoading = ref(false)

const batchExportDialogVisible = ref(false)
const batchExportLoading = ref(false)
const batchExportText = ref("")

const keepaliveConfigDialogVisible = ref(false)
const keepaliveConfigLoading = ref(false)
const savingKeepaliveConfig = ref(false)
const keepaliveConfigForm = ref({
  enabled: true,
  interval_hours: 12,
  trigger_now: false,
  last_summary: null as any,
})


// ================= 自主接码 (OTP) 与 2FA 云密码管理状态 =================
const otpLoading = ref(false)
const otpData = ref<ProtocolAccountLoginCodeData | null>(null)
const otpAutoPoll = ref(false)
let otpPollTimer: any = null

const quickOtpDialogVisible = ref(false)
const quickOtpLoading = ref(false)
const quickOtpData = ref<ProtocolAccountLoginCodeData | null>(null)
const currentQuickOtpAccount = ref<ProtocolAccount | null>(null)

const twoFaStatusLoading = ref(false)
const twoFaStatusData = ref<ProtocolAccount2FAStatusData | null>(null)
const showTwoFaPassword = ref(false)
const edit2faDialogVisible = ref(false)
const saving2fa = ref(false)
const edit2faForm = ref({
  current_password: '',
  new_password: '',
  hint: '',
})
const terminatingSessions = ref(false)
const cancellingReset = ref(false)
const takingOverSingle = ref(false)
const batchTakingOver = ref(false)

function generateStrong2faString(): string {
  const chars = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
  let res = "Mr-"
  for (let i = 0; i < 12; i++) {
    res += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return res
}

function generateRandom2faPassword() {
  edit2faForm.value.new_password = generateStrong2faString()
}

function getFullOtpUrl(token?: string): string {
  if (!token) return ""
  const origin = typeof window !== "undefined" ? window.location.origin : ""
  return `${origin}/api/telegram/botfather/otp/${token}`
}

async function loadAccountOtp(accountId: number) {
  otpLoading.value = true
  try {
    const res = await fetchProtocolAccountLoginCode(accountId, 10)
    if (res.success && res.data) {
      otpData.value = res.data
    } else {
      ElMessage.warning(res.error || "获取验证码失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "获取验证码异常")
  } finally {
    otpLoading.value = false
  }
}

function toggleOtpAutoPoll(accountId: number) {
  if (otpAutoPoll.value) {
    if (otpPollTimer) clearInterval(otpPollTimer)
    otpPollTimer = setInterval(() => {
      void loadAccountOtp(accountId)
    }, 5000)
    ElMessage.info("已开启 5 秒实时接码监听")
  } else {
    if (otpPollTimer) {
      clearInterval(otpPollTimer)
      otpPollTimer = null
    }
    ElMessage.info("已停止实时接码监听")
  }
}

async function handleBindLocalOtp(accountId: number) {
  try {
    const res = await bindProtocolAccountLocalOtp(accountId, true)
    if (res.success && res.data) {
      ElMessage.success("已成功生成自主接码地址，并替换号商接码链接！")
      if (accountDetail.value && res.data.detail) {
        accountDetail.value = res.data.detail
      }
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "生成自主接码链接失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "操作失败")
  }
}

async function handleQuickViewOtp(acc: ProtocolAccount) {
  currentQuickOtpAccount.value = acc
  quickOtpDialogVisible.value = true
  quickOtpLoading.value = true
  quickOtpData.value = null
  try {
    const res = await fetchProtocolAccountLoginCode(acc.id, 10)
    if (res.success && res.data) {
      quickOtpData.value = res.data
    } else {
      ElMessage.warning(res.error || "获取验证码失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "获取验证码异常")
  } finally {
    quickOtpLoading.value = false
  }
}

async function loadAccount2FAStatus(accountId: number) {
  twoFaStatusLoading.value = true
  try {
    const res = await getProtocolAccount2FA(accountId)
    if (res.success && res.data) {
      twoFaStatusData.value = res.data
    }
  } catch (e) {
    // ignore
  } finally {
    twoFaStatusLoading.value = false
  }
}

function openEdit2faModal() {
  if (!accountDetail.value) return
  edit2faForm.value = {
    current_password: accountDetail.value.two_fa?.two_fa_password || '',
    new_password: generateStrong2faString(),
    hint: accountDetail.value.two_fa?.two_fa_hint || 'MistRelay-2026',
  }
  edit2faDialogVisible.value = true
}

async function handleSingleTakeover() {
  if (!accountDetail.value) return
  const acc = accountDetail.value.account
  const autoPass = generateStrong2faString()
  try {
    await ElMessageBox.confirm(
      `即将对协议号 ${acc.phone} 执行全自动安全接管：

1. 自动匹配原密码并修改为新强密码：${autoPass}
2. 将接码地址切换为本机自主接码链接
3. 一键踢除号商其他所有已登录设备

确认立即执行吗？`,
      "⚡ 一键全自动安全接管",
      {
        confirmButtonText: "立即接管并锁定",
        cancelButtonText: "取消",
        type: "warning",
      }
    )
  } catch {
    return
  }

  takingOverSingle.value = true
  try {
    const res = await takeoverProtocolAccount(acc.id, {
      new_password: autoPass,
      hint: "MistRelay-2026",
    })
    if (res.success && res.data) {
      ElMessage.success(res.data.message || "协议号安全接管成功！")
      if (res.data.detail) {
        accountDetail.value = res.data.detail
      }
      showTwoFaPassword.value = true
      await loadAccount2FAStatus(acc.id)
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "安全接管失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "安全接管异常")
  } finally {
    takingOverSingle.value = false
  }
}

async function handleBatchTakeoverAll() {
  if (protocolAccounts.value.length === 0) {
    ElMessage.warning("当前资产池中没有协议号")
    return
  }

  const pendingList = pendingTakeoverAccounts.value
  const pendingCount = pendingList.length
  const securedCount = takenOverAccountsCount.value
  const totalPoolCount = protocolAccounts.value.length

  let forceAll = false
  if (pendingCount === 0) {
    try {
      await ElMessageBox.confirm(
        `当前资产池共 ${totalPoolCount} 个协议号，全部均已完成安全接管（已配置独立 2FA 强密码与本机自主接码）！

若仍需对全池 ${totalPoolCount} 个协议号重新生成新密码并再次执行接管，请点击「强制重新接管」。`,
        "🛡️ 全池协议号已全部安全接管",
        {
          confirmButtonText: "强制重新接管",
          cancelButtonText: "无需操作",
          type: "info",
        }
      )
      forceAll = true
    } catch {
      return
    }
  } else {
    try {
      const skipNote = securedCount > 0 ? `\n（已安全接管的 ${securedCount} 个协议号已自动排除，不重复操作）` : ""
      await ElMessageBox.confirm(
        `即将对资产池中剩余未接管的 ${pendingCount} 个协议号执行一键安全接管：${skipNote}

• 为每个未接管号生成独立 15 位高强度 2FA 云密码并同步至 Telegram
• 自动将号商外部接码链接切换为本机自主接码链接
• 自动踢除号商后台残留的外部设备会话

执行后所有新密码均自动加密保存在后台详情中，确认开始吗？`,
        `🛡️ 协议号一键安全接管 (待接管 ${pendingCount} / 共 ${totalPoolCount})`,
        {
          confirmButtonText: `开始接管 (${pendingCount} 个)`,
          cancelButtonText: "取消",
          type: "warning",
        }
      )
    } catch {
      return
    }
  }

  batchTakingOver.value = true
  try {
    const res = await batchTakeoverProtocolAccounts(
      forceAll
        ? { force_all: true, only_unsecured: false }
        : { account_ids: pendingList.map(a => a.id), only_unsecured: true }
    )
    if (res.success && res.data) {
      const d = res.data
      const skippedLine = d.skipped_count ? `\n• 已接管跳过：${d.skipped_count} 个` : ""
      ElMessageBox.alert(
        `批量安全接管已完成！

• 本次待接管：${d.total} 个${skippedLine}
• 接管成功：${d.success_count} 个
• 失败数量：${d.failed_count} 个

您可在各协议号的「详情 / Session」中查看并复制新生成的专属 2FA 密码。`,
        "🎉 安全接管完成",
        { type: d.failed_count === 0 ? "success" : "warning" }
      )
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "批量安全接管失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "批量安全接管异常")
  } finally {
    batchTakingOver.value = false
  }
}

async function handleSave2fa() {
  if (!accountDetail.value) return
  if (!edit2faForm.value.new_password.trim()) {
    ElMessage.warning("请输入新的 2FA 云密码")
    return
  }
  const accId = accountDetail.value.account.id
  saving2fa.value = true
  try {
    const res = await updateProtocolAccount2FA(accId, {
      new_password: edit2faForm.value.new_password.trim(),
      current_password: edit2faForm.value.current_password.trim() || undefined,
      hint: edit2faForm.value.hint.trim() || undefined,
    })
    if (res.success && res.data) {
      ElMessage.success("2FA 云密码已成功设置并持久化落库！")
      if (res.data.detail) {
        accountDetail.value = res.data.detail
      }
      edit2faDialogVisible.value = false
      await loadAccount2FAStatus(accId)
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "设置 2FA 密码失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "设置 2FA 密码异常")
  } finally {
    saving2fa.value = false
  }
}

async function handleTerminateOtherSessions() {
  if (!accountDetail.value) return
  const acc = accountDetail.value.account
  try {
    await ElMessageBox.confirm(
      `确定要一键踢除协议号 ${acc.phone} 的所有其他已登录设备/会话吗？\n\n执行后号商持有的所有电脑、手机与第三方客户端将立即失效掉线，仅保留 MistRelay 本地会话！`,
      "一键踢除号商外部会话",
      {
        confirmButtonText: "确认踢除",
        cancelButtonText: "取消",
        type: "warning",
      }
    )
  } catch {
    return
  }

  terminatingSessions.value = true
  try {
    const res = await terminateProtocolAccountOtherSessions(acc.id)
    if (res.success && res.data) {
      if (res.data.restricted) {
        ElMessageBox.alert(res.data.message, "Telegram 安全风控提示", { type: "info" })
      } else {
        ElMessage.success(res.data.message || "成功踢除号商所有其他会话！")
      }
    } else {
      ElMessage.error(res.error || "踢除会话失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "踢除会话异常")
  } finally {
    terminatingSessions.value = false
  }
}

async function handleCancelPasswordReset() {
  if (!accountDetail.value) return
  const acc = accountDetail.value.account
  cancellingReset.value = true
  try {
    const res = await cancelProtocolAccountPasswordReset(acc.id)
    if (res.success) {
      ElMessage.success("已成功撤销 Telegram 密码重置申请，阻断外部收回！")
      await loadAccount2FAStatus(acc.id)
    } else {
      ElMessage.error(res.error || "撤销重置失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "撤销重置异常")
  } finally {
    cancellingReset.value = false
  }
}

async function handleOpenAccountDetail(acc: ProtocolAccount) {
  accountDetailDialogVisible.value = true
  detailActiveTab.value = 'security'
  detailLoading.value = true
  showTelethonSession.value = false
  showPyrogramSession.value = false
  showTwoFaPassword.value = false
  otpData.value = null
  twoFaStatusData.value = null
  if (otpPollTimer) {
    clearInterval(otpPollTimer)
    otpPollTimer = null
  }
  otpAutoPoll.value = false
  void loadAccountOtp(acc.id)
  void loadAccount2FAStatus(acc.id)
  try {
    const res = await getProtocolAccountDetail(acc.id, false)
    if (res.success && res.data) {
      accountDetail.value = res.data
      if (res.data.metadata.proxy_api_url) {
        customProxyApiUrl.value = res.data.metadata.proxy_api_url
      }
    } else {
      ElMessage.error(res.error || "获取协议号详情失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "获取协议号详情异常")
  } finally {
    detailLoading.value = false
  }
}

async function handleRefreshAccountDetailOnline() {
  if (!accountDetail.value) return
  detailOnlineRefreshing.value = true
  try {
    const res = await getProtocolAccountDetail(accountDetail.value.account.id, true)
    if (res.success && res.data) {
      accountDetail.value = res.data
      ElMessage.success("账号在线档案与名下 Bot 列表刷新成功！")
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "在线刷新失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "在线刷新异常")
  } finally {
    detailOnlineRefreshing.value = false
  }
}

async function handleSingleKeepalive(acc: ProtocolAccount) {
  singleKeepaliveLoading.value = acc.id
  try {
    const res = await keepaliveSingleProtocolAccount(acc.id, false)
    if (res.success && res.data?.success) {
      ElMessage.success(`协议号 ${acc.phone} 保活成功！延迟: ${res.data.ping_ms}ms`)
      await fetchAccounts()
      if (accountDetailDialogVisible.value && accountDetail.value?.account.id === acc.id) {
        await handleOpenAccountDetail(acc)
      }
    } else {
      ElMessage.error(res.data?.error || res.error || "保活握手未成功")
      await fetchAccounts()
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "保活请求异常")
  } finally {
    singleKeepaliveLoading.value = null
  }
}

async function handleKeepaliveAll() {
  keepaliveAllLoading.value = true
  try {
    ElMessage.info("已启动协议号资产池全量保活巡检，正在错峰向 Telegram 握手...")
    const res = await keepaliveAllProtocolAccounts(undefined, false)
    if (res.success && res.data) {
      const d = res.data
      ElMessage.success(
        `全量保活完成！成功: ${d.success_count} 个，失败: ${d.failed_count} 个，平均延迟: ${d.avg_ping_ms}ms`
      )
      await fetchAccounts()
    } else {
      ElMessage.error(res.error || "全量保活执行失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || err?.message || "全量保活请求异常")
  } finally {
    keepaliveAllLoading.value = false
  }
}

function updateBatchExportText() {
  const lines: string[] = []
  for (const acc of protocolAccounts.value) {
    const detail = batchExportCachedDetails.value[acc.id]
    if (detail?.sessions?.telethon_session_string) {
      if (batchExportFormat.value === 'full') {
        const aId = detail.metadata.api_id || ''
        const aHash = detail.metadata.api_hash || ''
        lines.push(`${acc.phone} | ${aId} | ${aHash} | ${detail.sessions.telethon_session_string}`)
      } else {
        lines.push(`${acc.phone} | ${detail.sessions.telethon_session_string}`)
      }
    }
  }
  batchExportText.value = lines.join("\n")
}

async function openBatchExportTelethonModal() {
  batchExportDialogVisible.value = true
  batchExportLoading.value = true
  batchExportText.value = ""
  try {
    for (const acc of protocolAccounts.value) {
      if (!batchExportCachedDetails.value[acc.id]) {
        try {
          const detail = await getProtocolAccountDetail(acc.id, false)
          if (detail.success && detail.data) {
            batchExportCachedDetails.value[acc.id] = detail.data
          }
        } catch (e) {
          // ignore single account detail fail
        }
      }
    }
    updateBatchExportText()
  } finally {
    batchExportLoading.value = false
  }
}

function downloadExportTextFile() {
  if (!batchExportText.value) return
  const blob = new Blob([batchExportText.value], { type: "text/plain;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `mistrelay_telethon_sessions_${new Date().toISOString().slice(0, 10)}.txt`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success("已导出为 .txt 文件")
}

async function openKeepaliveConfigModal() {
  keepaliveConfigDialogVisible.value = true
  keepaliveConfigLoading.value = true
  try {
    const res = await getKeepaliveConfig()
    if (res.success && res.data) {
      keepaliveConfigForm.value.enabled = res.data.enabled
      keepaliveConfigForm.value.interval_hours = res.data.interval_hours || 12
      keepaliveConfigForm.value.trigger_now = false
      keepaliveConfigForm.value.last_summary = res.data.last_summary
    }
  } catch (err: any) {
    ElMessage.error(err?.message || "读取保活配置失败")
  } finally {
    keepaliveConfigLoading.value = false
  }
}

async function handleSaveKeepaliveConfig() {
  savingKeepaliveConfig.value = true
  try {
    const res = await updateKeepaliveConfig({
      enabled: keepaliveConfigForm.value.enabled,
      interval_hours: keepaliveConfigForm.value.interval_hours,
      trigger_now: keepaliveConfigForm.value.trigger_now,
    })
    if (res.success) {
      ElMessage.success("保活配置已成功保存！")
      keepaliveConfigDialogVisible.value = false
    } else {
      ElMessage.error(res.error || "保存保活配置失败")
    }
  } catch (err: any) {
    ElMessage.error(err?.message || "保存保活配置异常")
  } finally {
    savingKeepaliveConfig.value = false
  }
}

function maskSessionString(str?: string): string {
  if (!str) return ""
  if (str.length <= 24) return "***"
  return `${str.slice(0, 8)}...${str.slice(-8)} (长度 ${str.length} 字符)`
}

function formatRelativeTime(isoStr?: string | null): string {
  if (!isoStr) return "从未"
  try {
    const target = new Date(isoStr).getTime()
    const now = Date.now()
    const diff = Math.max(0, Math.floor((now - target) / 1000))
    if (diff < 60) return `${diff}秒前`
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    return `${Math.floor(diff / 86400)}天前`
  } catch {
    return isoStr
  }
}

function copyToClipboard(text: string, label: string) {
  if (!text) {
    ElMessage.warning("内容为空，无法复制")
    return
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      ElMessage.success(`${label}已复制到剪贴板！`)
    }).catch(() => {
      fallbackCopy(text, label)
    })
  } else {
    fallbackCopy(text, label)
  }
}

function fallbackCopy(text: string, label: string) {
  const ta = document.createElement("textarea")
  ta.value = text
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand("copy")
    ElMessage.success(`${label}已复制到剪贴板！`)
  } catch {
    ElMessage.error("复制失败，请手动选取文本复制")
  }
  document.body.removeChild(ta)
}

onMounted(async () => {
  await fetchAllData()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>

.botfather-page {
  @apply space-y-6 pb-12;
}

.botfather-header-card {
  padding: 24px 28px;
  border-radius: 20px;
}

.bots-header-main {
  @apply flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5;
  border-bottom: 1px solid rgba(255, 143, 171, 0.16);
}

.bots-title-group {
  @apply space-y-2;
}

.bots-title-row {
  @apply flex items-center gap-3 flex-wrap;
}

.bots-title {
  @apply text-2xl font-bold tracking-tight;
  margin: 0;
}

.bots-badge {
  @apply text-xs font-semibold px-3 py-1 rounded-full;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.18), rgba(56, 189, 248, 0.15));
  color: #ff7597;
  border: 1px solid rgba(255, 143, 171, 0.35);
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.12);
}

.bots-subtitle {
  @apply text-sm text-gray-500 max-w-3xl leading-relaxed;
  margin: 0;
}

.bots-header-actions {
  @apply flex items-center gap-2.5 flex-wrap shrink-0;
}

.header-btn {
  border-radius: 12px;
  font-weight: 500;
  transition: all 0.25s ease;
  backdrop-filter: blur(8px);
}

.cluster-nav-btn {
  border-color: rgba(56, 189, 248, 0.4);
  color: #0284c7;
}

.cluster-nav-btn:hover {
  background: rgba(56, 189, 248, 0.12);
  border-color: #38bdf8;
  color: #0284c7;
  transform: translateY(-2px);
}

.primary-glow-btn {
  background: linear-gradient(135deg, #ff7597 0%, #ff8fab 100%) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.35);
}

.primary-glow-btn:hover {
  box-shadow: 0 6px 18px rgba(255, 117, 151, 0.5);
  transform: translateY(-2px);
}

.stats-row {
  margin-top: 18px;
}

.stat-card {
  @apply flex items-center gap-3.5 p-3.5 rounded-2xl;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(255, 143, 171, 0.2);
  transition: all 0.25s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(255, 117, 151, 0.12);
  border-color: rgba(255, 117, 151, 0.4);
}

.stat-icon-wrapper {
  @apply w-12 h-12 rounded-xl flex items-center justify-center shrink-0 text-white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.stat-icon-accounts {
  background: linear-gradient(135deg, #a855f7 0%, #ec4899 100%);
}

.stat-icon-quota {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
}

.stat-icon-pipeline {
  background: linear-gradient(135deg, #38bdf8 0%, #6366f1 100%);
}

.stat-icon-cluster {
  background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
}

.stat-info {
  @apply flex-1 min-w-0;
}

.stat-value {
  @apply text-xl font-bold tracking-tight text-gray-800;
  line-height: 1.2;
}

.stat-unit {
  @apply text-xs font-normal text-gray-500 ml-1;
}

.stat-value-sky {
  color: #0284c7;
}

.stat-value-pink {
  color: #ff7597;
}

.stat-label {
  @apply text-xs text-gray-500 truncate mt-1;
}

.stat-progress {
  @apply w-full h-1.5 bg-gray-100 rounded-full mt-2 overflow-hidden;
}

.stat-progress-bar {
  @apply h-full rounded-full transition-all duration-500;
  background: linear-gradient(90deg, #ff7597 0%, #38bdf8 100%);
}

.import-waiting-alert {
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #0369a1;
}


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

/* 并发压测卡片 */
.load-test-card {
  padding: 18px 20px;
  border-radius: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.load-summary-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.load-test-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rounds-label {
  font-size: 12px;
  color: #64748b;
}

.load-distribution-grid {
  row-gap: 10px;
}

.dist-node-item {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(56, 189, 248, 0.22);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dist-node-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 700;
}

.dist-idx {
  color: #ff7597;
}

.dist-uname {
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dist-bar-wrap {
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #38bdf8, #ff7597);
}

.dist-node-bottom {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #64748b;
}

.dist-share {
  font-weight: 700;
  color: #0284c7;
}

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


.stream-benchmark-card {
  padding: 20px 22px;
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stream-bench-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.stream-bench-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.bench-ctrl-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ctrl-label {
  font-size: 13px;
  font-weight: 500;
  color: #475569;
  white-space: nowrap;
}

.bench-bot-select {
  width: 230px;
}

.start-stream-bench-btn {
  border-radius: 10px;
  font-weight: 600;
}

.stream-bench-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.bench-dual-row {
  margin-bottom: 0;
}

.bench-dual-col {
  margin-bottom: 12px;
}

.bench-subcard {
  padding: 16px 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.85);
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  box-sizing: border-box;
}

.subcard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subcard-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.subcard-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-playback {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.2), rgba(14, 165, 233, 0.1));
  color: #0284c7;
}

.icon-download {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.2), rgba(244, 63, 94, 0.1));
  color: #e11d48;
}

.subcard-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
}

.subcard-sub {
  font-size: 11px;
  color: #64748b;
}

.stutter-risk-tag, .dl-grade-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
}

.risk-none {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.risk-low {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.3);
}

.risk-moderate {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.risk-high {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.grade-ultra {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.15), rgba(56, 189, 248, 0.15));
  color: #ec4899;
  border: 1px solid rgba(255, 117, 151, 0.35);
}

.grade-fast {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.grade-normal {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.3);
}

.grade-slow {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.subcard-main-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed rgba(226, 232, 240, 0.9);
}

.main-stat-val {
  font-size: 30px;
  font-weight: 800;
  line-height: 1;
}

.main-stat-val .unit {
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
  margin-left: 2px;
}

.main-stat-badge {
  font-size: 12px;
  color: #475569;
  background: rgba(241, 245, 249, 0.9);
  padding: 4px 10px;
  border-radius: 8px;
}

.playback-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.pb-grid-item {
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(241, 245, 249, 0.9);
  border-radius: 10px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pb-label {
  font-size: 11px;
  color: #64748b;
}

.pb-val {
  font-size: 14px;
  font-weight: 700;
}

.pb-hint {
  font-size: 10px;
  color: #94a3b8;
}

.ratio-progress {
  height: 4px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.8);
  overflow: hidden;
  margin-top: 3px;
}

.ratio-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #38bdf8, #ff7597);
}

.truncate-filename {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.chunk-samples-bar {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.samples-title {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.samples-row {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.chunk-sample-item {
  flex: 1;
  min-width: 105px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.9);
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.02);
}

.sample-part {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
}

.sample-bot {
  font-size: 10px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-speed {
  font-size: 14px;
  font-weight: 800;
}

.sample-speed .sub {
  font-size: 10px;
  font-weight: 500;
  color: #64748b;
}

.sample-time {
  font-size: 10px;
  color: #94a3b8;
}

.bench-diagnosis-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.08), rgba(56, 189, 248, 0.08));
  border: 1px solid rgba(255, 117, 151, 0.2);
}

.diag-icon {
  color: #ff7597;
  flex-shrink: 0;
}

.diag-text {
  font-size: 12px;
  color: #334155;
  line-height: 1.4;
}

.bench-empty-guide {
  padding: 32px 20px;
  text-align: center;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.6);
  border: 1px dashed rgba(203, 213, 225, 0.8);
}

.empty-guide-content {
  max-width: 440px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.empty-icon {
  animation: pulse 2.5s infinite;
}

.empty-guide-title {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.empty-guide-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  margin: 0;
}

.empty-start-btn {
  border-radius: 10px;
  font-weight: 600;
  margin-top: 4px;
}

.node-playback-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(168, 85, 247, 0.12);
  color: #9333ea;
  border: 1px solid rgba(168, 85, 247, 0.3);
}

.card-stream-bench-btn {
  color: #0284c7;
  padding: 0 4px;
  font-size: 12px;
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
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 16px;
  margin-top: 14px;
}

.account-item-card {
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(226, 232, 240, 0.95);
  transition: all 0.25s ease;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  box-sizing: border-box;
  min-width: 0;
}

.account-item-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -6px rgba(56, 189, 248, 0.18);
  border-color: rgba(56, 189, 248, 0.45);
}

.account-item-card.active-selected {
  border-color: rgba(255, 117, 151, 0.55);
  background: linear-gradient(145deg, rgba(255, 245, 247, 0.85), rgba(240, 249, 255, 0.9));
}

.account-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
  flex-wrap: nowrap;
}

.account-card-top .cached-phone-pill {
  padding: 3px 9px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  flex-shrink: 0;
  border-radius: 6px;
}

.acc-top-badges {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  white-space: nowrap;
}

.acc-dc-badge,
.acc-ping-badge,
.acc-status-tag {
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0 !important;
}

.acc-dc-badge {
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1.2;
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.25);
  display: inline-flex;
  align-items: center;
}

.acc-dc-badge.dc-1 { background: rgba(59, 130, 246, 0.12); color: #2563eb; border-color: rgba(59, 130, 246, 0.25); }
.acc-dc-badge.dc-2, .acc-dc-badge.dc-4 { background: rgba(16, 185, 129, 0.12); color: #059669; border-color: rgba(16, 185, 129, 0.25); }
.acc-dc-badge.dc-3 { background: rgba(168, 85, 247, 0.12); color: #9333ea; border-color: rgba(168, 85, 247, 0.25); }
.acc-dc-badge.dc-5 { background: rgba(245, 158, 11, 0.12); color: #d97706; border-color: rgba(245, 158, 11, 0.25); }

.acc-ping-badge {
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1.2;
  display: inline-flex;
  align-items: center;
}

.acc-ping-badge.ping-fast {
  background: rgba(34, 197, 94, 0.12);
  color: #16a34a;
  border: 1px solid rgba(34, 197, 94, 0.25);
}

.acc-ping-badge.ping-slow {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.acc-status-tag {
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  line-height: 1.2;
  display: inline-flex;
  align-items: center;
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

.acc-meta-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  padding: 4px 9px;
  border-radius: 8px;
  background: rgba(241, 245, 249, 0.7);
  color: #64748b;
  min-height: 26px;
}

.acc-user-display {
  display: inline-flex;
  align-items: center;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.acc-keepalive-time {
  font-size: 10.5px;
  color: #64748b;
  white-space: nowrap;
  flex-shrink: 0;
}

.acc-quota-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.acc-quota-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: #475569;
}

.acc-quota-rem {
  font-weight: 600;
  font-size: 11px;
  color: #0284c7;
}

.acc-progress-bar-bg {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.85);
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

.acc-tags-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 22px;
}

.acc-tags-left {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}

.acc-type-chip {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1.5px 6px;
  border-radius: 4px;
  background: rgba(241, 245, 249, 0.95);
  color: #64748b;
  border: 1px solid rgba(203, 213, 225, 0.8);
  white-space: nowrap;
}

.acc-region-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1.5px 7px;
  border-radius: 9999px;
  font-size: 10.5px;
  font-weight: 600;
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.25);
  white-space: nowrap;
}


.acc-2fa-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1.5px 7px;
  border-radius: 9999px;
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.acc-2fa-chip.ready {
  background: rgba(99, 102, 241, 0.12);
  color: #4f46e5;
  border: 1px solid rgba(99, 102, 241, 0.3);
}

.acc-2fa-chip.ready:hover {
  background: rgba(99, 102, 241, 0.2);
}

.acc-2fa-chip.pending {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.acc-2fa-chip.pending:hover {
  background: rgba(245, 158, 11, 0.22);
  transform: scale(1.02);
}

.otp-account-btn {
  background: rgba(14, 165, 233, 0.08) !important;
  border-color: rgba(14, 165, 233, 0.35) !important;
  color: #0284c7 !important;
}

.otp-account-btn:hover {
  background: rgba(14, 165, 233, 0.18) !important;
  border-color: #0284c7 !important;
  color: #0369a1 !important;
}

.acc-api-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1.5px 7px;
  border-radius: 9999px;
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.acc-api-chip.ready {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.acc-api-chip.ready:hover {
  background: rgba(16, 185, 129, 0.2);
}

.acc-api-chip.pending {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.acc-api-chip.pending:hover {
  background: rgba(245, 158, 11, 0.22);
  transform: scale(1.02);
}

.acc-remark-text {
  font-size: 11px;
  color: #94a3b8;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.acc-api-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px;
  border-radius: 6px;
  font-size: 11px;
  margin-top: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  box-sizing: border-box;
  width: 100%;
}

.acc-api-banner.ready {
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #065f46;
}

.acc-api-banner.ready:hover {
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.4);
}

.acc-api-banner.pending {
  background: rgba(248, 250, 252, 0.95);
  border: 1px dashed rgba(203, 213, 225, 0.9);
  color: #64748b;
}

.acc-api-banner.pending:hover {
  background: rgba(254, 243, 199, 0.6);
  border-color: rgba(245, 158, 11, 0.5);
  color: #b45309;
}

.acc-api-banner-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.acc-api-banner-badge {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  background: rgba(16, 185, 129, 0.2);
  color: #047857;
  white-space: nowrap;
}

.acc-api-banner-badge.pending {
  background: rgba(226, 232, 240, 0.8);
  color: #64748b;
}

.acc-api-banner-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
}

.acc-api-banner-hash {
  color: #475569;
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 110px;
}

.acc-api-banner-prompt {
  font-size: 10.5px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.acc-api-banner-copy-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #059669;
  padding: 2px 4px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.acc-api-banner-copy-btn:hover {
  background: rgba(16, 185, 129, 0.2);
  color: #047857;
}

.acc-card-actions {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  padding-top: 8px;
  border-top: 1px dashed rgba(226, 232, 240, 0.9);
  box-sizing: border-box;
}

.acc-card-actions :deep(.el-button),
.acc-card-actions .el-button {
  margin-left: 0 !important;
  margin-right: 0 !important;
  height: 26px !important;
  font-size: 11px !important;
  border-radius: 6px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 2px !important;
  padding: 0 4px !important;
  box-sizing: border-box !important;
  border: 1px solid rgba(226, 232, 240, 0.85) !important;
  background: rgba(255, 255, 255, 0.95) !important;
  color: #475569 !important;
  transition: all 0.2s ease !important;
}

.acc-card-actions :deep(.acc-btn-action) {
  flex: 1 1 0% !important;
  min-width: 0 !important;
}

.acc-card-actions :deep(.delete-account-btn) {
  flex: 0 0 28px !important;
  width: 28px !important;
  padding: 0 !important;
  color: #ef4444 !important;
  border-color: rgba(239, 68, 68, 0.25) !important;
}

.acc-card-actions :deep(.delete-account-btn:hover) {
  background: rgba(254, 242, 242, 0.95) !important;
  border-color: rgba(239, 68, 68, 0.45) !important;
  color: #dc2626 !important;
}

.acc-card-actions :deep(.detail-account-btn) {
  color: #0284c7 !important;
  border-color: rgba(56, 189, 248, 0.3) !important;
}
.acc-card-actions :deep(.detail-account-btn:hover) {
  background: rgba(240, 249, 255, 0.95) !important;
  border-color: rgba(56, 189, 248, 0.55) !important;
}

.acc-card-actions :deep(.keepalive-account-btn) {
  color: #059669 !important;
  border-color: rgba(16, 185, 129, 0.3) !important;
}
.acc-card-actions :deep(.keepalive-account-btn:hover) {
  background: rgba(236, 253, 245, 0.95) !important;
  border-color: rgba(16, 185, 129, 0.5) !important;
}

.acc-card-actions :deep(.single-mint-quick-btn) {
  color: #db2777 !important;
  border-color: rgba(255, 117, 151, 0.3) !important;
  font-weight: 600;
}
.acc-card-actions :deep(.single-mint-quick-btn:hover) {
  background: rgba(255, 241, 242, 0.95) !important;
  border-color: rgba(255, 117, 151, 0.5) !important;
}

.acc-card-actions :deep(.check-account-btn) {
  color: #7c3aed !important;
  border-color: rgba(168, 85, 247, 0.3) !important;
}
.acc-card-actions :deep(.check-account-btn:hover) {
  background: rgba(245, 243, 255, 0.95) !important;
  border-color: rgba(168, 85, 247, 0.5) !important;
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

  .bots-header-card {
    padding: 16px;
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

  .botfather-page {
    padding: 0 !important;
  }

  .header-card {
    padding: 14px !important;
    border-radius: 14px !important;
  }

  .header-actions {
    flex-direction: column !important;
    width: 100% !important;
  }

  .header-actions > * {
    width: 100% !important;
  }
}


.import-task-banner {
  background: rgba(240, 249, 255, 0.85);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 12px;
  padding: 12px 14px;
}

.cooldown-pill {
  background: rgba(245, 158, 11, 0.15);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.35);
  padding: 2px 10px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.phone-code {
  background: rgba(56, 189, 248, 0.15);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.task-banner-logs {
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 8px;
  padding: 6px 10px;
  max-height: 90px;
  overflow-y: auto;
}

.task-mini-log {
  display: flex;
  gap: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: #475569;
}

.task-mini-log .log-time {
  color: #94a3b8;
  font-family: monospace;
  flex-shrink: 0;
}

.task-mini-log .log-msg {
  word-break: break-all;
}

.detail-header-card {
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(240, 249, 255, 0.8), rgba(254, 242, 242, 0.8));
  border-radius: 12px;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.detail-user-pill {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(203, 213, 225, 0.8);
}

.detail-metric-card {
  padding: 10px;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.85);
}

.session-section {
  padding: 12px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.session-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 6px;
}

.session-textarea {
  font-family: monospace;
}

.bot-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
  font-family: monospace;
}


/* 协议号资产池搜索与筛选工具栏 */
.pool-filter-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.75);
  border: 1px solid rgba(226, 232, 240, 0.8);
  margin-top: 14px;
}

.filter-controls-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex: 1;
  min-width: 280px;
}

.filter-search-input {
  width: 240px;
}

.filter-select {
  width: 140px;
}

.filter-select.dc-select {
  width: 130px;
}

.filter-select.status-select {
  width: 145px;
}

.filter-select.twofa-select {
  width: 135px;
}

.filter-controls-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-select.sort-select {
  width: 175px;
}

.filter-reset-btn {
  padding: 0 12px;
}

/* 跨模块联动呈现条 */
.acc-cross-module-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(241, 245, 249, 0.65);
  border: 1px solid rgba(226, 232, 240, 0.7);
}

.cross-module-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.2s ease;
  overflow: hidden;
  white-space: nowrap;
}

.cross-module-item:hover {
  background: rgba(255, 255, 255, 0.85);
}

.cross-module-item .cross-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.cross-module-item .cross-label {
  color: #64748b;
  flex-shrink: 0;
}

.cross-module-item .cross-val {
  margin-left: auto;
  font-weight: 600;
  color: #334155;
}

.filter-select.channel-select {
  width: 140px;
}

.cross-module-item.channel-item.has-channels {
  background: rgba(14, 165, 233, 0.12);
  border: 1px solid rgba(14, 165, 233, 0.35);
}

.cross-module-item.channel-item.has-channels:hover {
  background: rgba(14, 165, 233, 0.22);
}

.cross-module-item.channel-item.has-channels .cross-val {
  color: #0284c7;
  font-weight: 700;
}

.cross-module-item.bot-item.has-active .cross-val {
  color: #10b981;
}

/* 底部分页与空状态栏 */
.pool-empty-box {
  padding: 36px 20px;
  margin-top: 14px;
  border-radius: 14px;
  text-align: center;
}

.pool-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 12px;
  margin-top: 14px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.sync-pool-btn {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.12), rgba(129, 140, 248, 0.15)) !important;
  color: #0284c7 !important;
  border-color: rgba(56, 189, 248, 0.35) !important;
  font-weight: 600 !important;
}

.sync-pool-btn:hover {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.22), rgba(129, 140, 248, 0.25)) !important;
  border-color: #0284c7 !important;
  color: #0369a1 !important;
}


/* ================= 紧凑化协议号详情弹窗 ================= */
.compact-detail-dialog :deep(.el-dialog__header) {
  padding: 16px 22px 12px !important;
  margin-right: 0 !important;
  border-bottom: 1px solid rgba(255, 143, 171, 0.18) !important;
  background: linear-gradient(135deg, rgba(255, 245, 247, 0.9) 0%, rgba(240, 249, 255, 0.9) 100%) !important;
}

.compact-detail-dialog :deep(.el-dialog__body) {
  padding: 14px 20px !important;
  max-height: calc(85vh - 120px) !important;
  overflow-y: auto !important;
}

.compact-detail-dialog :deep(.el-dialog__footer) {
  padding: 12px 20px !important;
  border-top: 1px solid rgba(255, 143, 171, 0.18) !important;
  background: rgba(255, 255, 255, 0.92) !important;
}

/* 自定义细长平滑滚动条 */
.compact-dialog-body::-webkit-scrollbar,
.compact-detail-dialog :deep(.el-dialog__body)::-webkit-scrollbar,
.tenant-channel-cards::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

.compact-dialog-body::-webkit-scrollbar-thumb,
.compact-detail-dialog :deep(.el-dialog__body)::-webkit-scrollbar-thumb,
.tenant-channel-cards::-webkit-scrollbar-thumb {
  background: rgba(255, 143, 171, 0.35);
  border-radius: 999px;
}

.compact-dialog-body::-webkit-scrollbar-thumb:hover,
.compact-detail-dialog :deep(.el-dialog__body)::-webkit-scrollbar-thumb:hover,
.tenant-channel-cards::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 117, 151, 0.6);
}

/* 顶部紧凑指标平铺条 */
.detail-metrics-compact-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 8px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(226, 232, 240, 0.8);
}

@media (min-width: 640px) {
  .detail-metrics-compact-row {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

.compact-metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.compact-metric-label {
  color: #64748b;
  font-size: 11px;
  line-height: 1.2;
}

/* 现代毛玻璃 Tab 导航 */
.detail-modern-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
  border-bottom: 1px solid rgba(255, 143, 171, 0.2);
}

.detail-modern-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: rgba(255, 143, 171, 0.2);
}

.detail-modern-tabs :deep(.el-tabs__active-bar) {
  background: linear-gradient(90deg, #ff7597, #38bdf8);
  height: 3px;
  border-radius: 999px;
}

.detail-modern-tabs :deep(.el-tabs__item) {
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  padding: 0 16px;
  height: 38px;
  line-height: 38px;
  transition: all 0.2s ease;
}

.detail-modern-tabs :deep(.el-tabs__item:hover) {
  color: #ff7597;
}

.detail-modern-tabs :deep(.el-tabs__item.is-active) {
  color: #ff7597;
  font-weight: 600;
}

/* 频道列表卡片容器内滚 */
.tenant-channel-cards {
  max-height: 260px;
  overflow-y: auto;
  padding-right: 4px;
}

</style>
