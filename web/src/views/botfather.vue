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
            纳管 {{ protocolAccounts.length }} 个账号 · 已持机 {{ totalBotCountInPool }} / {{ Math.max(20, protocolAccounts.length * 20) }} · 剩余可建配额 {{ totalRemainingQuota }}
          </span>
        </div>
        <div class="pool-actions">
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

      <!-- 资产池账号列表卡片网格 -->
      <div v-if="protocolAccounts.length > 0" class="account-pool-grid">
        <div
          v-for="acc in protocolAccounts"
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
            <span class="acc-status-tag" :class="`acc-status-${acc.status}`">
              {{ formatAccountStatus(acc.status) }}
            </span>
          </div>

          <!-- 配额进度条 -->
          <div class="acc-quota-row">
            <span class="acc-quota-label">持有机数: {{ acc.bot_count }}/20</span>
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

          <div class="account-card-bottom">
            <span class="acc-type-text">
              {{ acc.session_type === 'telethon_string' ? 'Telethon' : acc.session_type === 'session_file' ? '.session' : 'Pyrogram' }}
              {{ acc.remark ? `· ${acc.remark}` : '' }}
            </span>
            <div class="acc-btn-group">
              <el-button
                size="small"
                text
                class="single-mint-quick-btn"
                :icon="MagicStick"
                @click="handleQuickSingleMint(acc)"
                title="切换为此号单号精准独立铸造"
              >
                单号铸造
              </el-button>
              <el-button
                size="small"
                text
                class="check-account-btn"
                :loading="checkAccountLoading === acc.id"
                @click="handleCheckAccount(acc)"
                title="在线检测账号健康度并刷新 Bot 数量"
              >
                检测
              </el-button>
              <el-button
                size="small"
                text
                type="danger"
                class="delete-account-btn"
                :icon="Delete"
                @click="handleDeleteAccount(acc)"
                title="从资产池安全移除"
              >
              </el-button>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="account-pool-empty">
        <el-icon :size="24"><Warning /></el-icon>
        <span>资产池暂未纳管协议号，点击右上角「批量导入协议号」或在下方输入即可开始</span>
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

          <el-form-item label="或批量上传 .session 文件 (支持多选)">
            <div class="batch-upload-dropzone" @click="triggerBatchFileInput">
              <input
                ref="batchFileInputRef"
                type="file"
                accept=".session"
                multiple
                class="hidden-file-input"
                @change="handleBatchFilesSelect"
              />
              <el-icon :size="28" class="upload-icon"><UploadFilled /></el-icon>
              <div class="upload-text">
                {{ batchImportFiles.length > 0 ? `已选择 ${batchImportFiles.length} 个 .session 文件` : '点击选择或拖拽多个 .session 文件' }}
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

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue"
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
  type BotFatherTaskStatus,
  type ProtocolAccount,
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

const protocolAccounts = computed<ProtocolAccount[]>(() => {
  if (accountsList.value.length > 0) return accountsList.value
  if (taskStatus.value.accounts && taskStatus.value.accounts.length > 0) return taskStatus.value.accounts
  if (taskStatus.value.cached_sessions && taskStatus.value.cached_sessions.length > 0) {
    return taskStatus.value.cached_sessions.map((item: any, idx: number) => ({
      id: idx + 1,
      phone: item.phone,
      session_type: "pyrogram_string",
      has_code_url: false,
      masked_code_url: "",
      bot_count: 5,
      max_bots: 20,
      remaining_quota: 15,
      status: "active" as const,
      last_used_at: null,
      remark: "已缓存协议号",
      created_at: "",
    }))
  }
  return []
})

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
    const res = await deleteProtocolAccount(acc.id)
    if (res.success) {
      ElMessage.success(`已移除协议号 ${acc.phone}`)
      accountsList.value = accountsList.value.filter(a => a.id !== acc.id && a.phone !== acc.phone)
      selectedRelayAccountIds.value = selectedRelayAccountIds.value.filter(id => id !== acc.id)
      if (selectedSingleAccountId.value === acc.id) {
        selectedSingleAccountId.value = accountsList.value.length > 0 ? accountsList.value[0].id : null
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
      if (newCount > prevCount) {
        await fetchClusterStatus()
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
    await Promise.all([fetchClusterStatus(), fetchTaskStatus(), fetchAccounts()])
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
  if (importPollTimer) {
    clearInterval(importPollTimer)
    importPollTimer = null
  }
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

</style>
