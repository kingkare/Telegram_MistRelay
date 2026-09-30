<template>
  <div class="users-page animate-fade-in">
    <!-- 顶部品牌横幅与核心指标 -->
    <div class="users-header-card glass-card">
      <div class="users-header-main">
        <div class="users-title-group">
          <div class="users-title-row">
            <h2 class="users-title text-gradient-sakura">多租户用户与专属频道管理中心</h2>
            <span class="users-badge">Multi-Tenant Cloud Isolation</span>
          </div>
          <p class="users-subtitle">
            管理全站用户账号、同 DC 协议号自动创建物理隔离专属存储频道、租户频道无损容灾平移与全量数据热备。
          </p>
        </div>

        <div class="users-header-actions">
          <el-button
            class="header-btn"
            :icon="RefreshRight"
            :loading="loading"
            @click="fetchUsersData"
          >
            刷新列表
          </el-button>
          <el-button
            class="header-btn backup-entry-btn"
            :icon="FolderChecked"
            @click="openBackupDialog"
          >
            全量数据灾备
          </el-button>
          <el-button
            class="header-btn"
            :icon="MagicStick"
            :loading="healingOrphans"
            @click="handleHealOrphans"
          >
            自愈孤儿资产
          </el-button>
          <el-button
            class="header-btn"
            :icon="Key"
            @click="codesDialogVisible = true"
          >
            近期 TG 注册码
            <el-badge
              v-if="summary.pending_codes > 0"
              :value="summary.pending_codes"
              type="primary"
              style="margin-left: 6px;"
            />
          </el-button>
          <el-button
            type="primary"
            class="header-btn primary-glow-btn"
            :icon="Plus"
            @click="openCreateDialog"
          >
            新增租户 (自动建频)
          </el-button>
        </div>
      </div>

      <!-- 顶部 4 张核心统计卡 -->
      <el-row :gutter="14" class="stats-row">
        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-users">
              <el-icon :size="22"><User /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">
                {{ summary.total_users }} <span class="stat-unit">位用户</span>
              </div>
              <div class="stat-label">
                管理员 {{ adminCount }} · 普通租户 {{ Math.max(0, summary.total_users - adminCount) }}
              </div>
            </div>
          </div>
        </el-col>

        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-channels">
              <el-icon :size="22"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-emerald">
                {{ summary.dedicated_tenants }} <span class="stat-unit">个专属频道</span>
              </div>
              <div class="stat-label">
                {{ dcDistributionText }}
              </div>
            </div>
          </div>
        </el-col>

        <el-col :xs="12" :sm="6">
          <div class="stat-card">
            <div class="stat-icon-wrapper stat-icon-storage">
              <el-icon :size="22"><FolderOpened /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-sky">
                {{ formatBytes(summary.total_size) }}
              </div>
              <div class="stat-label">
                全站累计入库 {{ summary.total_files }} 个媒体文件
              </div>
            </div>
          </div>
        </el-col>

        <el-col :xs="12" :sm="6">
          <div class="stat-card" style="cursor: pointer;" @click="codesDialogVisible = true">
            <div class="stat-icon-wrapper stat-icon-codes">
              <el-icon :size="22"><Key /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value stat-value-amber">
                {{ summary.pending_codes }} <span class="stat-unit">个待核销码</span>
              </div>
              <div class="stat-label">
                累计下发 {{ recentCodes.length }} 条 TG 注册验证码
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 搜索与筛选工具栏 -->
    <div class="filter-bar glass-card">
      <div class="filter-left">
        <el-input
          v-model="searchQuery"
          placeholder="搜索用户名 / TG ID / @TG用户名 / 专属频道 Handle..."
          clearable
          :prefix-icon="Search"
          class="search-input"
        />
        <el-select v-model="roleFilter" placeholder="角色筛选" style="width: 140px;">
          <el-option value="all" label="全部角色" />
          <el-option value="admin" label="系统管理员" />
          <el-option value="user" label="普通租户" />
        </el-select>
        <el-select v-model="dcFilter" placeholder="数据中心筛选" style="width: 160px;">
          <el-option value="all" label="全部数据中心" />
          <el-option value="5" label="DC5 (亚太/新加坡)" />
          <el-option value="1" label="DC1 (美洲/迈阿密)" />
          <el-option value="2" label="DC2 (欧洲/阿姆斯特丹)" />
          <el-option value="unbound" label="未绑定专属频道" />
        </el-select>
      </div>
      <div class="filter-right">
        <span class="filter-count">共筛选出 <b>{{ filteredUsers.length }}</b> 位用户</span>
      </div>
    </div>

    <!-- 用户列表主表格 (限高 + 分页防止把页面拉高) -->
    <div class="table-card glass-card">
      <!-- 移动端专属租户卡片流 (桌面端隐藏) -->
      <div class="mobile-user-cards-list md:hidden flex flex-col gap-3 mb-3">
        <div
          v-for="row in paginatedUsers"
          :key="row.id"
          class="mobile-user-card p-3.5 rounded-xl border border-pink-200/50 bg-white/90 shadow-sm"
        >
          <!-- 顶部：头像、用户名、角色与状态 -->
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-2.5 min-w-0">
              <div class="user-avatar" :class="row.role === 'admin' ? 'avatar-admin' : 'avatar-user'">
                {{ (row.username || 'U').slice(0, 1).toUpperCase() }}
              </div>
              <div class="flex flex-col min-w-0">
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span class="font-bold text-gray-900 text-sm truncate">{{ row.username }}</span>
                  <el-tag
                    size="small"
                    :type="row.role === 'admin' ? 'danger' : 'primary'"
                    effect="light"
                    class="!h-5 !px-1.5 !text-[11px]"
                  >
                    {{ row.role === 'admin' ? '管理员' : '租户' }}
                  </el-tag>
                </div>
                <span class="text-xs text-gray-500 font-mono">#{{ row.id }} · {{ formatDate(row.created_at) }}</span>
              </div>
            </div>
            <span v-if="row.active_sessions" class="text-[11px] text-emerald-600 font-medium whitespace-nowrap">
              🟢 {{ row.active_sessions }} 在线
            </span>
          </div>

          <!-- 中部：TG 身份与频道绑定 -->
          <div class="mt-2.5 pt-2 border-t border-pink-100/60 flex flex-col gap-1.5 text-xs">
            <div class="flex items-center justify-between gap-2">
              <span class="text-gray-500">Telegram 绑定:</span>
              <div v-if="row.tg_user_id || row.tg_username" class="font-medium text-sky-600 truncate">
                {{ row.tg_first_name || 'TG 用户' }}
                <span v-if="row.tg_username">(@{{ row.tg_username }})</span>
              </div>
              <span v-else class="text-gray-400">未绑定</span>
            </div>

            <div class="flex items-center justify-between gap-2">
              <span class="text-gray-500">专属频道:</span>
              <div v-if="row.bin_channel_id" class="flex items-center gap-1 min-w-0">
                <el-tag size="small" type="success" effect="dark" class="!h-4 !px-1 !text-[10px]">
                  DC{{ row.dc_id || 5 }}
                </el-tag>
                <span class="truncate text-gray-800 font-medium">{{ row.bin_channel_username || '私有频道' }}</span>
              </div>
              <span v-else-if="row.role === 'admin'" class="text-gray-500">全局默认 (BIN)</span>
              <span v-else class="text-amber-500">⚠️ 未分配</span>
            </div>

            <div class="flex items-center justify-between gap-2">
              <span class="text-gray-500">网盘用量:</span>
              <span class="font-bold text-gray-800 font-mono">
                {{ formatBytes(row.total_size || 0) }} · {{ row.media_count || 0 }} 文件
              </span>
            </div>
          </div>

          <!-- 底部操作按钮 -->
          <div class="mt-3 pt-2.5 border-t border-pink-100/60 flex items-center justify-between gap-1.5 flex-wrap">
            <div class="flex items-center gap-1.5">
              <el-button
                size="small"
                type="primary"
                plain
                :icon="FolderOpened"
                @click="inspectUserDrive(row)"
              >
                网盘
              </el-button>
              <el-button
                v-if="row.bin_channel_id"
                size="small"
                :type="row.creator_status === 'warning' ? 'danger' : 'success'"
                plain
                :icon="Connection"
                @click="openMigrationDialog(row)"
              >
                平移
              </el-button>
              <el-button
                v-else
                size="small"
                type="success"
                plain
                :icon="Connection"
                @click="openProvisionDialog(row)"
              >
                开通
              </el-button>
              <el-button
                size="small"
                type="warning"
                plain
                :icon="Key"
                @click="openResetPwdDialog(row)"
              >
                重置
              </el-button>
            </div>
            <div class="flex items-center gap-1">
              <el-button
                size="small"
                circle
                :icon="Download"
                @click="handleExportTenantBackup(row)"
                title="导出备份"
              />
              <el-button
                size="small"
                circle
                :icon="Edit"
                @click="openEditDialog(row)"
                title="编辑"
              />
              <el-button
                size="small"
                circle
                type="danger"
                :icon="Delete"
                :disabled="row.id === authStore.user?.id"
                @click="confirmDeleteUser(row)"
                title="删除用户"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 桌面端表格 (移动端隐藏) -->
      <div class="hidden md:block">
        <el-table
        :data="paginatedUsers"
        v-loading="loading"
        stripe
        max-height="580px"
        style="width: 100%"
        empty-text="暂无匹配的用户记录"
      >
        <el-table-column label="用户账号" min-width="175">
          <template #default="{ row }">
            <div class="user-cell">
              <div class="user-avatar" :class="row.role === 'admin' ? 'avatar-admin' : 'avatar-user'">
                {{ (row.username || 'U').slice(0, 1).toUpperCase() }}
              </div>
              <div class="user-meta">
                <div class="user-name-line">
                  <span class="user-name">{{ row.username }}</span>
                  <el-tag
                    size="small"
                    :type="row.role === 'admin' ? 'danger' : 'primary'"
                    effect="light"
                  >
                    {{ row.role === 'admin' ? '管理员' : '租户' }}
                  </el-tag>
                </div>
                <div class="user-sub-line">
                  <span>ID: #{{ row.id }}</span>
                  <span v-if="row.active_sessions" class="online-dot">
                    🟢 {{ row.active_sessions }} 在线会话
                  </span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Telegram 绑定身份" min-width="185">
          <template #default="{ row }">
            <div v-if="row.tg_user_id || row.tg_username" class="tg-identity-cell">
              <div class="tg-name-row">
                <span class="tg-fname">{{ row.tg_first_name || 'TG 用户' }}</span>
                <a
                  v-if="row.tg_username"
                  :href="`https://t.me/${row.tg_username}`"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="tg-uname-link"
                >
                  @{{ row.tg_username }}
                </a>
              </div>
              <div v-if="row.tg_user_id" class="tg-uid-row">
                TG ID: <code>{{ row.tg_user_id }}</code>
              </div>
            </div>
            <span v-else class="text-muted">未绑定 Telegram</span>
          </template>
        </el-table-column>

        <el-table-column label="专属物理隔离频道 (DC & Handle)" min-width="260">
          <template #default="{ row }">
            <div v-if="row.bin_channel_id" class="channel-cell">
              <div class="channel-top-row">
                <el-tag size="small" type="success" effect="dark" class="dc-badge">
                  DC{{ row.dc_id || 5 }}
                </el-tag>
                <a
                  v-if="row.bin_channel_username && !String(row.bin_channel_username).startsWith('channel_')"
                  :href="`https://t.me/${row.bin_channel_username}`"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="channel-handle-link"
                >
                  @{{ row.bin_channel_username }}
                </a>
                <span v-else class="channel-handle-text">
                  {{ row.bin_channel_username || '私有频道' }}
                </span>
                <el-tooltip
                  v-if="row.creator_status === 'warning'"
                  content="建频母号状态异常或已失效，建议点击右侧「无损平移」将频道媒体克隆至新健康协议号创建的频道"
                  placement="top"
                >
                  <span class="creator-warning-badge">⚠️ 母号异常</span>
                </el-tooltip>
              </div>
              <div class="channel-sub-row">
                <span>频道 ID: <code>{{ row.bin_channel_id }}</code></span>
                <span
                  v-if="row.creator_phone"
                  class="creator-tag"
                  :class="row.creator_status === 'warning' ? 'creator-tag-warn' : 'creator-tag-ok'"
                >
                  {{ row.creator_status === 'warning' ? '⚠️' : '🟢' }} 母号: {{ row.creator_phone }}
                </span>
              </div>
            </div>
            <div v-else-if="row.role === 'admin'" class="channel-fallback">
              <el-tag size="small" type="info" effect="plain">全局默认频道 (BIN_CHANNEL)</el-tag>
            </div>
            <div v-else class="channel-unbound">
              <el-tag size="small" type="warning" effect="light">⚠️ 尚未分配专属频道</el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="独立网盘用量" min-width="185">
          <template #default="{ row }">
            <div class="storage-cell">
              <div class="storage-size-row">
                <span class="storage-bytes">{{ formatBytes(row.total_size || 0) }}</span>
                <span class="storage-count">{{ row.media_count || 0 }} 个文件</span>
              </div>
              <div class="storage-breakdown">
                <span>🎬 视频 {{ row.video_count || 0 }}</span>
                <span>🖼️ 图片 {{ row.image_count || 0 }}</span>
                <span>⬇️ 任务 {{ row.download_count || 0 }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="注册时间" width="160">
          <template #default="{ row }">
            <span class="time-text">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="管理操作" width="340" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-button
                size="small"
                type="primary"
                plain
                :icon="FolderOpened"
                @click="inspectUserDrive(row)"
              >
                查看网盘
              </el-button>
              <el-button
                v-if="row.bin_channel_id"
                size="small"
                :type="row.creator_status === 'warning' ? 'danger' : 'success'"
                :plain="row.creator_status !== 'warning'"
                :icon="Connection"
                @click="openMigrationDialog(row)"
              >
                无损平移
              </el-button>
              <el-button
                v-else
                size="small"
                type="success"
                plain
                :icon="Connection"
                @click="openProvisionDialog(row)"
              >
                开通频道
              </el-button>
              <el-button
                size="small"
                type="warning"
                plain
                :icon="Key"
                @click="openResetPwdDialog(row)"
              >
                重置密码
              </el-button>
              <el-button
                size="small"
                plain
                :icon="Download"
                title="导出该租户的独立媒体与任务备份"
                @click="handleExportTenantBackup(row)"
              >
                导出
              </el-button>
              <el-button
                size="small"
                plain
                :icon="Edit"
                @click="openEditDialog(row)"
              />
              <el-button
                size="small"
                type="danger"
                plain
                :icon="Delete"
                :disabled="row.id === authStore.user?.id"
                @click="confirmDeleteUser(row)"
              />
            </div>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <!-- 用户分页控制栏 -->
      <div v-if="filteredUsers.length > 0" class="pagination-bar">
        <div class="pagination-info">
          共 <span class="font-bold text-sky-600">{{ filteredUsers.length }}</span> 位用户
          <template v-if="filteredUsers.length > userPageSize">
            · 当前显示第 <span class="font-bold">{{ (userCurrentPage - 1) * userPageSize + 1 }}</span> ~ <span class="font-bold">{{ Math.min(userCurrentPage * userPageSize, filteredUsers.length) }}</span> 位
          </template>
        </div>
        <el-pagination
          v-model:current-page="userCurrentPage"
          v-model:page-size="userPageSize"
          :page-sizes="[10, 15, 25, 50, 100]"
          :total="filteredUsers.length"
          layout="sizes, prev, pager, next, jumper"
          background
          size="small"
          class="users-pagination"
        />
      </div>
    </div>

    <!-- 1. 新增租户弹窗 -->
    <el-dialog
      v-model="createDialogVisible"
      title="➕ 新增租户账号 & 自动开通同 DC 专属频道"
      width="520px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form :model="createForm" label-position="top">
        <el-form-item label="登录用户名 (必填，3~32位字符)" required>
          <el-input v-model="createForm.username" placeholder="例如: alice_vip" />
        </el-form-item>

        <el-form-item label="初始登录密码 (至少8位，支持一键随机生成)" required>
          <div style="display: flex; gap: 8px; width: 100%;">
            <el-input v-model="createForm.password" placeholder="输入密码或点击右侧随机生成" />
            <el-button @click="generateCreatePassword">🎲 随机生成</el-button>
            <el-button type="primary" plain @click="copyText(createForm.password, '密码已复制')">复制</el-button>
          </div>
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="账号角色">
              <el-select v-model="createForm.role" style="width: 100%;">
                <el-option value="user" label="普通租户 (物理隔离)" />
                <el-option value="admin" label="系统管理员 (全局权限)" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="绑定 Telegram User ID (可选)">
              <el-input v-model="createForm.tg_user_id" placeholder="如: 6581234567" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="自动调度协议号创建专属存储频道">
          <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
            <el-switch
              v-model="createForm.auto_provision_channel"
              active-text="立即自动调配协议号建频并提权 Bot"
            />
          </div>
        </el-form-item>

        <el-form-item v-if="createForm.auto_provision_channel" label="目标数据中心 (优先选用同 DC 协议号创建频道)">
          <el-select v-model="createForm.target_dc_id" style="width: 100%;">
            <el-option :value="5" label="🇸🇬 DC5 亚太/新加坡 (推荐中文/亚太用户)" />
            <el-option :value="1" label="🇺🇸 DC1 美洲/迈阿密 (推荐 +1 北美用户)" />
            <el-option :value="2" label="🇳🇱 DC2 欧洲/阿姆斯特丹 (推荐欧洲用户)" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" @click="submitCreateUser">
          {{ createSubmitting ? '正在调度协议号建频开户...' : '确认创建租户' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 2. 补建 / 更换专属存储频道弹窗 -->
    <el-dialog
      v-model="provisionDialogVisible"
      :title="`📡 为用户 ${provisionTarget?.username || ''} 分配全新专属存储频道`"
      width="480px"
      :close-on-click-modal="false"
      append-to-body
    >
      <div class="dialog-tip-box">
        系统将从协议号资产池中优选指定 DC 区域的协议号，自动创建全新公开存储频道（<code>@mr_u...</code>），并将主控 Bot 与工作节点提权为频道管理员。
      </div>
      <el-form label-position="top" style="margin-top: 14px;">
        <el-form-item label="当前绑定状态">
          <div v-if="provisionTarget?.bin_channel_id" style="font-size: 13px; color: #334155;">
            已绑定频道: <b>@{{ provisionTarget.bin_channel_username }}</b> (<code>{{ provisionTarget.bin_channel_id }}</code> · DC{{ provisionTarget.dc_id || 5 }})
          </div>
          <div v-else style="font-size: 13px; color: #d97706;">
            当前尚未绑定专属频道
          </div>
        </el-form-item>
        <el-form-item label="选择新专属频道所属数据中心 (DC)">
          <el-select v-model="provisionDcId" style="width: 100%;">
            <el-option :value="5" label="🇸🇬 DC5 亚太/新加坡" />
            <el-option :value="1" label="🇺🇸 DC1 美洲/迈阿密" />
            <el-option :value="2" label="🇳🇱 DC2 欧洲/阿姆斯特丹" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="provisionDialogVisible = false">取消</el-button>
        <el-button type="success" :loading="provisionSubmitting" @click="submitProvisionChannel">
          {{ provisionSubmitting ? '正在通过协议号创建频道...' : '立即创建并绑定专属频道' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 3. 编辑用户弹窗 -->
    <el-dialog
      v-model="editDialogVisible"
      :title="`✏️ 编辑用户信息 - ${editForm.username}`"
      width="500px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form :model="editForm" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="登录用户名">
              <el-input v-model="editForm.username" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="账号角色">
              <el-select v-model="editForm.role" style="width: 100%;">
                <el-option value="user" label="普通租户 (user)" />
                <el-option value="admin" label="系统管理员 (admin)" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="Telegram User ID">
              <el-input v-model="editForm.tg_user_id" placeholder="数字 ID，可留空" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Telegram 用户名 (@username)">
              <el-input v-model="editForm.tg_username" placeholder="不含 @" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="所属 DC">
              <el-select v-model="editForm.dc_id" style="width: 100%;">
                <el-option :value="5" label="DC5" />
                <el-option :value="1" label="DC1" />
                <el-option :value="2" label="DC2" />
                <el-option :value="4" label="DC4" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="专属存储频道 ID (-100xxxxxxxxxx)">
              <el-input v-model="editForm.bin_channel_id" placeholder="如 -1002345678901" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="专属存储频道公开 Handle (@username)">
          <el-input v-model="editForm.bin_channel_username" placeholder="如 mr_u1234_a1b2c3d4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEditUser">保存修改</el-button>
      </template>
    </el-dialog>

    <!-- 4. 重置密码弹窗 -->
    <el-dialog
      v-model="resetPwdDialogVisible"
      :title="`🔑 重置用户密码 - ${resetPwdTarget?.username || ''}`"
      width="460px"
      :close-on-click-modal="false"
      append-to-body
    >
      <div class="dialog-tip-box">
        重置密码后，该用户当前所有已登录设备会话将被立即强制下线。
      </div>
      <el-form label-position="top" style="margin-top: 14px;">
        <el-form-item label="新登录密码 (至少 8 位)">
          <div style="display: flex; gap: 8px; width: 100%;">
            <el-input v-model="resetPwdValue" placeholder="输入新密码" />
            <el-button @click="resetPwdValue = generateRandomPassword()">🎲 随机生成</el-button>
            <el-button
              type="primary"
              plain
              @click="copyText(`账号: ${resetPwdTarget?.username}\n密码: ${resetPwdValue}`, '账号与新密码已复制')"
            >
              复制账密
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetPwdDialogVisible = false">取消</el-button>
        <el-button type="warning" :loading="resetPwdSubmitting" @click="submitResetPassword">
          确认重置并强制下线旧会话
        </el-button>
      </template>
    </el-dialog>

    <!-- 5. 近期 Telegram 注册验证码弹窗 (带搜索与分页) -->
    <el-dialog
      v-model="codesDialogVisible"
      title="🔑 近期 Telegram 私聊 /register 验证码记录"
      width="740px"
      append-to-body
      top="7vh"
    >
      <!-- 搜索与状态过滤 -->
      <div class="dialog-filter-bar">
        <el-input
          v-model="codeSearch"
          placeholder="搜索验证码 / TG 用户名 / TG ID..."
          clearable
          size="small"
          :prefix-icon="Search"
          style="max-width: 280px;"
        />
        <el-radio-group v-model="codeStatusFilter" size="small">
          <el-radio-button value="all">全部 ({{ recentCodes.length }})</el-radio-button>
          <el-radio-button value="pending">待使用 ({{ pendingCodesCount }})</el-radio-button>
          <el-radio-button value="used">已核销 ({{ usedCodesCount }})</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 移动端验证码卡片流 -->
      <div class="md:hidden mobile-code-cards flex flex-col gap-2 mb-3">
        <div
          v-for="row in paginatedCodes"
          :key="row.code"
          class="p-3 rounded-xl border border-pink-100 bg-white shadow-sm flex flex-col gap-1.5 text-xs"
        >
          <div class="flex items-center justify-between">
            <code
              class="text-base font-bold text-rose-600 font-mono tracking-wider cursor-pointer"
              @click="copyText(row.code, '验证码已复制')"
            >
              {{ row.code }}
            </code>
            <el-tag size="small" :type="row.used ? 'success' : 'warning'">
              {{ row.used ? '已核销' : '待使用' }}
            </el-tag>
          </div>
          <div class="flex items-center justify-between text-gray-500">
            <span>TG: {{ row.tg_first_name || 'User' }} <b v-if="row.tg_username" class="text-sky-600">@{{ row.tg_username }}</b> ({{ row.tg_user_id }})</span>
            <el-tag size="small" type="info">DC{{ row.detected_dc_id || 5 }}</el-tag>
          </div>
          <div class="text-gray-400 font-mono text-[11px]">{{ formatDate(row.created_at) }}</div>
        </div>
      </div>

      <!-- 桌面端验证码表格 -->
      <div class="hidden md:block">
        <el-table
          :data="paginatedCodes"
          stripe
          size="small"
          max-height="420px"
          empty-text="暂无注册验证码记录"
        >
        <el-table-column label="6位验证码" width="120">
          <template #default="{ row }">
            <code
              style="font-size: 14px; font-weight: 700; color: #e11d48; cursor: pointer;"
              @click="copyText(row.code, '验证码已复制')"
            >
              {{ row.code }}
            </code>
          </template>
        </el-table-column>
        <el-table-column label="Telegram 用户" min-width="160">
          <template #default="{ row }">
            <div>{{ row.tg_first_name || 'User' }} <span v-if="row.tg_username" style="color: #0284c7;">@{{ row.tg_username }}</span></div>
            <div style="font-size: 11px; color: #64748b;">ID: {{ row.tg_user_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="识别区域" width="95">
          <template #default="{ row }">
            <el-tag size="small" type="info">DC{{ row.detected_dc_id || 5 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="95">
          <template #default="{ row }">
            <el-tag size="small" :type="row.used ? 'success' : 'warning'">
              {{ row.used ? '已核销' : '待使用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="生成时间" width="160">
          <template #default="{ row }">
            <span style="font-size: 12px; color: #64748b;">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <!-- 验证码分页导航 -->
      <div v-if="filteredCodes.length > 0" class="dialog-pagination-bar">
        <span class="dialog-pagination-info">
          共 {{ filteredCodes.length }} 条记录
          <template v-if="filteredCodes.length > codePageSize">
            · 第 {{ (codeCurrentPage - 1) * codePageSize + 1 }} ~ {{ Math.min(codeCurrentPage * codePageSize, filteredCodes.length) }} 条
          </template>
        </span>
        <el-pagination
          v-model:current-page="codeCurrentPage"
          v-model:page-size="codePageSize"
          :page-sizes="[10, 20, 50]"
          :total="filteredCodes.length"
          layout="sizes, prev, pager, next"
          background
          size="small"
        />
      </div>
    </el-dialog>

    <!-- 6. 全量数据灾备与一键恢复中心弹窗 -->
    <el-dialog
      v-model="backupDialogVisible"
      width="960px"
      :close-on-click-modal="false"
      append-to-body
      top="5vh"
      class="disaster-backup-dialog"
    >
      <template #header>
        <div class="disaster-dialog-header">
          <div class="disaster-header-left">
            <div class="disaster-icon-box">🛡️</div>
            <div>
              <div class="disaster-title">全量数据灾备与一键恢复中心</div>
              <div class="disaster-desc">SQLite 在线无锁事务热备 · 协议号 Session 凭据 · JWT/Config 深度归档</div>
            </div>
          </div>
          <div class="disaster-header-right">
            <el-tag size="small" type="success" effect="light" class="header-tag-pill">
              {{ backupsList.length }} 份归档 · 累计 {{ formatBytes(totalBackupSizeBytes) }}
            </el-tag>
          </div>
        </div>
      </template>

      <!-- 顶部功能卡片：左侧机制说明，右侧自动策略配置 -->
      <div class="backup-top-grid">
        <div class="backup-info-card">
          <div class="backup-info-title">
            <el-icon :size="16"><FolderChecked /></el-icon>
            <span>在线热备机制与安全回滚</span>
          </div>
          <p class="backup-info-text">
            基于 Python 官方 <code>sqlite3.backup()</code> 强一致性热备，服务零中断打包数据库、<code>sessions/</code> 会话凭据及核心配置。
          </p>
          <div class="backup-safety-notice">
            <span>🛡️ 每次还原前自动生成 <code>safety_pre_restore_*</code> 兜底快照，支持随时无损回滚。</span>
          </div>
        </div>

        <div class="backup-sched-card">
          <div class="backup-sched-header">
            <div class="backup-sched-title">
              <el-icon :size="16"><Setting /></el-icon>
              <span>定时自动热备策略</span>
            </div>
            <el-switch
              v-model="scheduleForm.enabled"
              size="small"
              active-text="启用"
            />
          </div>
          <div class="backup-sched-controls">
            <div class="sched-inline-item">
              <span class="sched-label">每</span>
              <el-input-number
                v-model="scheduleForm.interval_hours"
                :min="1"
                :max="168"
                size="small"
                controls-position="right"
                style="width: 80px;"
              />
              <span class="sched-unit">小时</span>
            </div>
            <div class="sched-inline-item">
              <span class="sched-label">保留</span>
              <el-input-number
                v-model="scheduleForm.max_keep"
                :min="3"
                :max="100"
                size="small"
                controls-position="right"
                style="width: 80px;"
              />
              <span class="sched-unit">份</span>
            </div>
            <el-button
              size="small"
              class="sched-save-btn"
              :loading="scheduleSaving"
              @click="handleSaveBackupSchedule"
            >
              保存策略
            </el-button>
          </div>
          <div class="backup-sched-foot">
            <span v-if="scheduleForm.last_run">上次自动备份: {{ formatDate(scheduleForm.last_run) }}</span>
            <span v-else>尚未执行自动计划</span>
          </div>
        </div>
      </div>

      <!-- 操作栏：立即创建备份 + 上传 + 刷新 -->
      <div class="backup-action-bar">
        <div class="backup-create-group">
          <el-input
            v-model="backupRemark"
            placeholder="输入备份备注（如：更新前快照 / 每日归档）..."
            clearable
            :prefix-icon="Edit"
            style="width: 320px;"
          />
          <el-button
            type="primary"
            class="btn-create-backup"
            :icon="FolderChecked"
            :loading="backupCreating"
            @click="handleCreateBackup"
          >
            {{ backupCreating ? '正在热备打包...' : '立即创建全量备份' }}
          </el-button>
        </div>

        <div class="backup-upload-group">
          <input
            ref="backupFileInputRef"
            type="file"
            accept=".tar.gz,.tgz,.db"
            style="display: none;"
            @change="handleBackupFileSelected"
          />
          <el-button
            class="btn-neutral"
            :icon="Upload"
            :loading="backupUploading"
            @click="triggerBackupUpload"
          >
            上传备份包
          </el-button>
          <el-button
            class="btn-neutral"
            :icon="RefreshRight"
            :loading="backupLoading"
            @click="fetchBackupsList"
          >
            刷新
          </el-button>
        </div>
      </div>

      <!-- 备份归档列表 (无 fixed="right"，彻底消除阴影遮挡与换行) -->
      <div class="backup-table-wrapper">
        <!-- 移动端灾备归档卡片流 -->
        <div class="mobile-backup-cards md:hidden flex flex-col gap-2.5 my-2">
          <div
            v-for="row in paginatedBackups"
            :key="row.filename"
            class="p-3 rounded-xl border border-pink-100/80 bg-white/95 shadow-sm flex flex-col gap-2"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="flex items-center gap-1.5 min-w-0">
                <span class="text-base shrink-0">{{ row.type === 'archive' ? '📦' : '🗄️' }}</span>
                <span class="text-xs font-semibold text-gray-800 truncate" :title="row.filename">{{ row.filename }}</span>
              </div>
              <span class="text-xs font-mono font-bold text-gray-700 shrink-0">{{ row.size_formatted }}</span>
            </div>
            <div class="flex items-center gap-1.5 flex-wrap">
              <el-tag
                v-if="row.is_safety_snapshot"
                size="small"
                type="warning"
                effect="light"
                class="!h-5 !px-1.5 !text-[10px]"
              >
                安全兜底快照
              </el-tag>
              <el-tag
                v-else
                size="small"
                :type="row.type === 'archive' ? 'success' : 'info'"
                effect="plain"
                class="!h-5 !px-1.5 !text-[10px]"
              >
                {{ row.type === 'archive' ? '全量归档' : '单库快照' }}
              </el-tag>
              <span v-if="row.manifest" class="text-[11px] text-gray-500 font-mono">
                👤{{ row.manifest.db_tables?.users ?? 0 }} · 🎬{{ row.manifest.db_tables?.tg_media ?? 0 }} · 📱{{ row.manifest.sessions_count ?? 0 }}
              </span>
              <span class="text-[10px] text-gray-400 ml-auto font-mono">{{ formatDate(row.created_at) }}</span>
            </div>
            <div class="flex items-center gap-2 pt-1.5 border-t border-pink-50">
              <el-button size="small" class="flex-1" :icon="Download" @click="handleDownloadBackup(row)">下载</el-button>
              <el-button size="small" type="primary" class="flex-1" :icon="RefreshLeft" :loading="backupRestoring === row.filename" @click="handleRestoreBackup(row)">还原</el-button>
              <el-button v-if="!row.is_protected" size="small" type="danger" text :icon="Delete" @click="handleDeleteBackup(row)" />
              <el-tag v-else size="small" type="danger" effect="light" class="!h-6 !text-[10px]">🔒 保护基线</el-tag>
            </div>
          </div>
        </div>
        <!-- 桌面端灾备归档表格 -->
        <div class="hidden md:block">
          <el-table
          :data="paginatedBackups"
          v-loading="backupLoading"
          stripe
          size="small"
          max-height="380px"
          style="width: 100%"
          empty-text="暂无备份归档，请点击上方「立即创建全量备份」生成第一份灾备快照"
        >
          <el-table-column label="备份归档文件" min-width="290">
            <template #default="{ row }">
              <div class="backup-file-entry">
                <div class="backup-fname-row">
                  <span class="backup-file-icon">{{ row.type === 'archive' ? '📦' : '🗄️' }}</span>
                  <span class="backup-fname" :title="row.filename">{{ row.filename }}</span>
                </div>
                <div class="backup-meta-row">
                  <el-tag
                    v-if="row.is_safety_snapshot"
                    size="small"
                    type="warning"
                    effect="light"
                    class="tag-compact"
                  >
                    安全兜底快照
                  </el-tag>
                  <el-tag
                    v-else
                    size="small"
                    :type="row.type === 'archive' ? 'success' : 'info'"
                    effect="plain"
                    class="tag-compact"
                  >
                    {{ row.type === 'archive' ? '全量归档 (.tar.gz)' : '数据库快照 (.db)' }}
                  </el-tag>
                  <span v-if="row.remark" class="backup-remark-tag">
                    📝 {{ row.remark }}
                  </span>
                </div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="包含数据明细" min-width="210">
            <template #default="{ row }">
              <div v-if="row.manifest" class="manifest-pill-group">
                <span class="meta-pill pill-user">
                  👤 用户 {{ row.manifest.stats?.users ?? row.manifest.db_tables?.users ?? 0 }}
                </span>
                <span class="meta-pill pill-media">
                  🎬 媒体 {{ row.manifest.stats?.media ?? row.manifest.db_tables?.tg_media ?? 0 }}
                </span>
                <span class="meta-pill pill-sess">
                  📱 协议号 {{ row.manifest.sessions_count ?? 0 }}
                </span>
              </div>
              <span v-else class="text-muted">SQLite 单库快照</span>
            </template>
          </el-table-column>

          <el-table-column label="体积" width="105" align="right">
            <template #default="{ row }">
              <span class="backup-size-text">{{ row.size_formatted }}</span>
            </template>
          </el-table-column>

          <el-table-column label="创建时间" width="165" align="center">
            <template #default="{ row }">
              <span class="time-text">{{ formatDate(row.created_at) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="灾备操作" width="205" align="center">
            <template #default="{ row }">
              <div class="backup-action-row">
                <el-button
                  size="small"
                  class="btn-act-download"
                  :icon="Download"
                  @click="handleDownloadBackup(row)"
                >
                  下载
                </el-button>
                <el-button
                  size="small"
                  class="btn-act-restore"
                  :icon="RefreshLeft"
                  :loading="backupRestoring === row.filename"
                  @click="handleRestoreBackup(row)"
                >
                  还原
                </el-button>
                <el-button
                  v-if="!row.is_protected"
                  size="small"
                  class="btn-act-delete"
                  :icon="Delete"
                  title="删除备份"
                  @click="handleDeleteBackup(row)"
                />
                <el-tag
                  v-else
                  size="small"
                  type="danger"
                  effect="light"
                  style="border-radius: 6px; font-weight: 600; cursor: not-allowed;"
                  title="系统核心灾备基线，强制受保护，禁止删除"
                >
                  🔒 受保护基线
                </el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </div>

      <!-- 备份列表分页 -->
      <div v-if="backupsList.length > 0" class="dialog-pagination-bar">
        <span class="dialog-pagination-info">
          共 <b>{{ backupsList.length }}</b> 份灾备归档 · 累计 <b>{{ formatBytes(totalBackupSizeBytes) }}</b>
        </span>
        <el-pagination
          v-model:current-page="backupCurrentPage"
          v-model:page-size="backupPageSize"
          :page-sizes="[6, 12, 24]"
          :total="backupsList.length"
          layout="sizes, prev, pager, next"
          background
          size="small"
        />
      </div>
    </el-dialog>

    <!-- 7. 租户专属存储频道无损平移工作台弹窗 -->
    <el-dialog
      v-model="migrationDialogVisible"
      :title="`🚀 租户专属频道无损平移工作台 - ${migrationTarget?.username || ''}`"
      width="700px"
      :close-on-click-modal="false"
      append-to-body
      top="6vh"
      class="migration-dialog"
      @closed="stopMigrationPolling"
    >
      <!-- 源频道概况卡片 -->
      <div v-if="migrationTarget" class="mig-source-card">
        <div class="mig-source-header">
          <span class="mig-source-title">当前源存储频道档案</span>
          <el-tag
            size="small"
            :type="migrationTarget.creator_status === 'warning' ? 'danger' : 'success'"
          >
            {{ migrationTarget.creator_status === 'warning' ? '⚠️ 建频母号异常 (强烈建议平移)' : '🟢 频道运行正常' }}
          </el-tag>
        </div>
        <div class="mig-source-grid">
          <div class="mig-kv">
            <span class="mig-k">源频道 Handle：</span>
            <span class="mig-v">@{{ migrationTarget.bin_channel_username || '私有频道' }} (<code>{{ migrationTarget.bin_channel_id }}</code>)</span>
          </div>
          <div class="mig-kv">
            <span class="mig-k">归属数据中心：</span>
            <span class="mig-v">DC{{ migrationTarget.dc_id || 5 }} · 母号 {{ migrationTarget.creator_phone || '未记录' }}</span>
          </div>
          <div class="mig-kv">
            <span class="mig-k">待平移媒体数：</span>
            <span class="mig-v"><b>{{ migrationTarget.media_count || 0 }}</b> 个文件 ({{ formatBytes(migrationTarget.total_size || 0) }})</span>
          </div>
        </div>
      </div>

      <!-- 零损安全说明 -->
      <div class="dialog-tip-box" style="margin-top: 12px;">
        ⚡ <b>Telegram 服务端零流量极速克隆：</b>通过主控 Bot 执行原生 <code>copy_message</code> 将源频道历史媒体毫秒级无损镜像至新频道，并原子更新数据库 <code>tg_media</code> 与缩略图缓存指针；<b>原旧频道历史消息 100% 完整保留不删除</b>，前台直链与网盘零感知平滑过渡。
      </div>

      <!-- 目标频道配置表单 -->
      <el-form label-position="top" style="margin-top: 14px;" :disabled="isMigrationRunning">
        <el-form-item label="目标存储频道分配方式">
          <el-radio-group v-model="migrationForm.mode">
            <el-radio value="auto">自动调度健康协议号新建公开频道并提权集群 (推荐)</el-radio>
            <el-radio value="custom">平移至指定已有频道 ID</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="migrationForm.mode === 'auto'" label="选择新频道目标数据中心 (DC)">
          <el-select v-model="migrationForm.target_dc_id" style="width: 100%;">
            <el-option :value="5" label="🇸🇬 DC5 亚太/新加坡 (推荐)" />
            <el-option :value="1" label="🇺🇸 DC1 美洲/迈阿密" />
            <el-option :value="2" label="🇳🇱 DC2 欧洲/阿姆斯特丹" />
            <el-option :value="4" label="🇪🇺 DC4 欧洲节点" />
          </el-select>
        </el-form-item>

        <el-form-item v-else label="已有目标频道 ID (格式: -100xxxxxxxxxx，需已将主控与工作 Bot 设为管理员)">
          <el-input v-model="migrationForm.custom_target_channel_id" placeholder="例如: -1002345678901" />
        </el-form-item>
      </el-form>

      <!-- 实时平移进度与终端日志面板 -->
      <div v-if="migrationStatus" class="mig-progress-panel">
        <div class="mig-progress-header">
          <div class="mig-status-left">
            <el-tag
              size="small"
              :type="
                migrationStatus.status === 'completed'
                  ? 'success'
                  : migrationStatus.status === 'failed'
                  ? 'danger'
                  : migrationStatus.status === 'cancelled'
                  ? 'warning'
                  : 'primary'
              "
            >
              {{
                migrationStatus.status === 'running'
                  ? '🔄 正在无损克隆平移中...'
                  : migrationStatus.status === 'completed'
                  ? '✅ 平移圆满完成'
                  : migrationStatus.status === 'failed'
                  ? '❌ 平移异常中断'
                  : migrationStatus.status === 'cancelled'
                  ? '⏹️ 已手动中止'
                  : '⏳ 准备中'
              }}
            </el-tag>
            <span v-if="migrationStatus.target_channel_username" class="mig-target-tag">
              新频道: <b>@{{ migrationStatus.target_channel_username }}</b> (<code>{{ migrationStatus.target_channel_id }}</code>)
            </span>
          </div>
          <div class="mig-counters">
            <span>总计: <b>{{ migrationStatus.total_files }}</b></span>
            <span style="color: #059669;">已克隆: <b>{{ migrationStatus.migrated_files }}</b></span>
            <span v-if="migrationStatus.skipped_files > 0" style="color: #d97706;">
              跳过: <b>{{ migrationStatus.skipped_files }}</b>
            </span>
          </div>
        </div>

        <el-progress
          :percentage="Math.min(100, Math.max(0, Number(migrationStatus.progress_percent || 0)))"
          :status="
            migrationStatus.status === 'completed'
              ? 'success'
              : migrationStatus.status === 'failed'
              ? 'exception'
              : undefined
          "
          :stroke-width="14"
          striped
          :striped-flow="isMigrationRunning"
          style="margin: 10px 0;"
        />

        <!-- 暗黑实时终端日志框 -->
        <div ref="migrationLogBoxRef" class="mig-terminal-box">
          <div
            v-for="(log, idx) in migrationStatus.logs || []"
            :key="idx"
            class="mig-log-line"
            :class="`mig-log-${log.level || 'info'}`"
          >
            <span class="mig-log-time">[{{ log.time }}]</span>
            <span class="mig-log-msg">{{ log.msg }}</span>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="mig-dialog-footer">
          <el-button
            v-if="migrationTarget && !isMigrationRunning"
            size="small"
            text
            type="info"
            @click="switchToBlankProvision"
          >
            仅重置为空白新频道 (不迁移历史文件)
          </el-button>
          <div class="mig-footer-right">
            <el-button @click="migrationDialogVisible = false">关闭窗口</el-button>
            <el-button
              v-if="isMigrationRunning"
              type="danger"
              :loading="migrationCancelling"
              @click="handleCancelMigration"
            >
              安全中止平移
            </el-button>
            <el-button
              v-else
              type="primary"
              :icon="Connection"
              :loading="migrationStarting"
              @click="handleStartMigration"
            >
              {{ migrationStatus?.status === 'completed' ? '重新执行无损平移' : '🚀 立即启动无损平移' }}
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  User,
  Connection,
  FolderOpened,
  FolderChecked,
  Key,
  Plus,
  RefreshRight,
  RefreshLeft,
  Search,
  Edit,
  Delete,
  Upload,
  Download,
  Setting,
  MagicStick,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  getUsersList,
  createAdminUser,
  provisionUserChannel,
  updateAdminUser,
  resetUserPassword,
  deleteAdminUser,
  getSystemBackups,
  createSystemBackup,
  downloadSystemBackup,
  uploadSystemBackup,
  restoreSystemBackup,
  exportTenantBackup,
  healOrphanedMedia,
  deleteSystemBackup,
  setBackupSchedule,
  startUserChannelMigration,
  getUserChannelMigrationStatus,
  cancelUserChannelMigration,
  type UserRecord,
  type UsersSummary,
  type TgRegisterCodeItem,
  type BackupItem,
  type ChannelMigrationStatus,
} from '@/api'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const users = ref<UserRecord[]>([])
const recentCodes = ref<TgRegisterCodeItem[]>([])
const summary = reactive<UsersSummary>({
  total_users: 0,
  dedicated_tenants: 0,
  total_files: 0,
  total_size: 0,
  pending_codes: 0,
  dc_distribution: {},
})

const searchQuery = ref('')
const roleFilter = ref('all')
const dcFilter = ref('all')

const adminCount = computed(() => users.value.filter(u => u.role === 'admin').length)

const dcDistributionText = computed(() => {
  const entries = Object.entries(summary.dc_distribution || {})
  if (!entries.length) return '支持 DC1 / DC2 / DC5 自动就近建频'
  return entries.map(([k, v]) => `${k}: ${v}人`).join(' · ')
})

const filteredUsers = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return users.value.filter(u => {
    if (roleFilter.value !== 'all' && u.role !== roleFilter.value) return false
    if (dcFilter.value === 'unbound') {
      if (u.bin_channel_id) return false
    } else if (dcFilter.value !== 'all') {
      if (String(u.dc_id || '') !== dcFilter.value) return false
    }
    if (!q) return true
    return (
      (u.username || '').toLowerCase().includes(q) ||
      (u.tg_username || '').toLowerCase().includes(q) ||
      (u.tg_first_name || '').toLowerCase().includes(q) ||
      String(u.tg_user_id || '').includes(q) ||
      (u.bin_channel_username || '').toLowerCase().includes(q) ||
      String(u.bin_channel_id || '').includes(q)
    )
  })
})

// 用户主表格分页 (默认每页 10 条，避免拉高页面)
const userCurrentPage = ref(1)
const userPageSize = ref(10)

const paginatedUsers = computed(() => {
  const start = (userCurrentPage.value - 1) * userPageSize.value
  return filteredUsers.value.slice(start, start + userPageSize.value)
})

watch([searchQuery, roleFilter, dcFilter, userPageSize], () => {
  userCurrentPage.value = 1
})

// 近期注册验证码弹窗搜索、过滤与分页
const codeSearch = ref('')
const codeStatusFilter = ref<'all' | 'pending' | 'used'>('all')
const codeCurrentPage = ref(1)
const codePageSize = ref(10)

const pendingCodesCount = computed(() => recentCodes.value.filter(c => !c.used).length)
const usedCodesCount = computed(() => recentCodes.value.filter(c => c.used).length)

const filteredCodes = computed(() => {
  const q = codeSearch.value.trim().toLowerCase()
  return recentCodes.value.filter(item => {
    if (codeStatusFilter.value === 'pending' && item.used) return false
    if (codeStatusFilter.value === 'used' && !item.used) return false
    if (!q) return true
    return (
      (item.code || '').toLowerCase().includes(q) ||
      (item.tg_username || '').toLowerCase().includes(q) ||
      (item.tg_first_name || '').toLowerCase().includes(q) ||
      String(item.tg_user_id || '').includes(q)
    )
  })
})

const paginatedCodes = computed(() => {
  const start = (codeCurrentPage.value - 1) * codePageSize.value
  return filteredCodes.value.slice(start, start + codePageSize.value)
})

watch([codeSearch, codeStatusFilter, codePageSize], () => {
  codeCurrentPage.value = 1
})

function generateRandomPassword(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  let out = 'Mr-'
  for (let i = 0; i < 10; i++) {
    out += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return out
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 2 : 0)} ${units[i]}`
}

function formatDate(iso?: string): string {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

async function copyText(text: string, msg = '已复制到剪贴板') {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(msg)
  } catch {
    ElMessage.info(text)
  }
}

async function fetchUsersData() {
  loading.value = true
  try {
    const res = await getUsersList()
    if (res.success) {
      users.value = res.users || []
      recentCodes.value = res.recent_codes || []
      if (res.summary) {
        Object.assign(summary, res.summary)
      }
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function inspectUserDrive(row: UserRecord) {
  if (row.bin_channel_id) {
    router.push({
      path: '/drive',
      query: {
        chat_id: String(row.bin_channel_id),
        username: row.username,
      },
    })
  } else {
    router.push('/drive')
  }
}

// ==================== 1. 新增租户 ====================
const createDialogVisible = ref(false)
const createSubmitting = ref(false)
const createForm = reactive({
  username: '',
  password: '',
  role: 'user',
  tg_user_id: '',
  auto_provision_channel: true,
  target_dc_id: 5,
})

function generateCreatePassword() {
  createForm.password = generateRandomPassword()
}

function openCreateDialog() {
  createForm.username = ''
  createForm.password = generateRandomPassword()
  createForm.role = 'user'
  createForm.tg_user_id = ''
  createForm.auto_provision_channel = true
  createForm.target_dc_id = 5
  createDialogVisible.value = true
}

async function submitCreateUser() {
  if (!createForm.username.trim()) {
    ElMessage.warning('请输入登录用户名')
    return
  }
  createSubmitting.value = true
  try {
    const res = await createAdminUser({
      username: createForm.username.trim(),
      password: createForm.password.trim() || 'auto',
      role: createForm.role,
      tg_user_id: createForm.tg_user_id ? Number(createForm.tg_user_id) : null,
      auto_provision_channel: createForm.auto_provision_channel,
      target_dc_id: createForm.target_dc_id,
    })
    if (res.success) {
      ElMessage.success(res.message || '租户创建成功')
      createDialogVisible.value = false
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '创建失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '创建租户失败')
  } finally {
    createSubmitting.value = false
  }
}

// ==================== 2. 补建/换绑专属频道 ====================
const provisionDialogVisible = ref(false)
const provisionSubmitting = ref(false)
const provisionTarget = ref<UserRecord | null>(null)
const provisionDcId = ref(5)

function openProvisionDialog(row: UserRecord) {
  provisionTarget.value = row
  provisionDcId.value = row.dc_id || 5
  provisionDialogVisible.value = true
}

async function submitProvisionChannel() {
  if (!provisionTarget.value) return
  provisionSubmitting.value = true
  try {
    const res = await provisionUserChannel(provisionTarget.value.id, provisionDcId.value)
    if (res.success) {
      ElMessage.success(res.message || '专属频道分配成功')
      provisionDialogVisible.value = false
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '分配失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '分配专属频道失败')
  } finally {
    provisionSubmitting.value = false
  }
}

// ==================== 3. 编辑用户 ====================
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({
  id: 0,
  username: '',
  role: 'user' as 'admin' | 'user',
  tg_user_id: '' as string | number,
  tg_username: '',
  dc_id: 5,
  bin_channel_id: '' as string | number,
  bin_channel_username: '',
})

function openEditDialog(row: UserRecord) {
  editForm.id = row.id
  editForm.username = row.username
  editForm.role = row.role
  editForm.tg_user_id = row.tg_user_id || ''
  editForm.tg_username = row.tg_username || ''
  editForm.dc_id = row.dc_id || 5
  editForm.bin_channel_id = row.bin_channel_id || ''
  editForm.bin_channel_username = row.bin_channel_username || ''
  editDialogVisible.value = true
}

async function submitEditUser() {
  editSubmitting.value = true
  try {
    const res = await updateAdminUser(editForm.id, {
      username: editForm.username.trim(),
      role: editForm.role,
      tg_user_id: editForm.tg_user_id ? Number(editForm.tg_user_id) : null,
      tg_username: editForm.tg_username.trim() || null,
      dc_id: editForm.dc_id,
      bin_channel_id: editForm.bin_channel_id ? Number(editForm.bin_channel_id) : null,
      bin_channel_username: editForm.bin_channel_username.trim() || null,
    })
    if (res.success) {
      ElMessage.success(res.message || '更新成功')
      editDialogVisible.value = false
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '更新失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '更新失败')
  } finally {
    editSubmitting.value = false
  }
}

// ==================== 4. 重置密码 ====================
const resetPwdDialogVisible = ref(false)
const resetPwdSubmitting = ref(false)
const resetPwdTarget = ref<UserRecord | null>(null)
const resetPwdValue = ref('')

function openResetPwdDialog(row: UserRecord) {
  resetPwdTarget.value = row
  resetPwdValue.value = generateRandomPassword()
  resetPwdDialogVisible.value = true
}

async function submitResetPassword() {
  if (!resetPwdTarget.value) return
  resetPwdSubmitting.value = true
  try {
    const res = await resetUserPassword(resetPwdTarget.value.id, resetPwdValue.value.trim())
    if (res.success) {
      resetPwdValue.value = res.new_password || resetPwdValue.value
      ElMessage.success(res.message || '密码已重置')
      await copyText(
        `账号: ${resetPwdTarget.value.username}\n新密码: ${resetPwdValue.value}`,
        '重置成功！账号与新密码已复制到剪贴板',
      )
      resetPwdDialogVisible.value = false
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '重置失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '重置密码失败')
  } finally {
    resetPwdSubmitting.value = false
  }
}

// ==================== 5. 删除用户 & 注册码弹窗 ====================
const codesDialogVisible = ref(false)

async function confirmDeleteUser(row: UserRecord) {
  try {
    await ElMessageBox.confirm(
      `确定要删除租户账号「${row.username}」吗？删除后该用户的登录权限将被立即吊销（远端 Telegram 频道不会被销毁）。`,
      '删除租户确认',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    const res = await deleteAdminUser(row.id, false)
    if (res.success) {
      ElMessage.success(res.message || '用户已删除')
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '删除失败')
    }
  } catch {
    // cancelled
  }
}

// ==================== 6. 全量数据灾备与恢复中心 ====================
const backupDialogVisible = ref(false)
const backupLoading = ref(false)
const backupCreating = ref(false)
const backupUploading = ref(false)
const backupRestoring = ref<string | null>(null)
const backupRemark = ref('')
const backupsList = ref<BackupItem[]>([])
const backupCurrentPage = ref(1)
const backupPageSize = ref(6)
const backupFileInputRef = ref<HTMLInputElement | null>(null)

const scheduleSaving = ref(false)
const scheduleForm = reactive({
  enabled: false,
  interval_hours: 24,
  max_keep: 15,
  last_run: '',
})

const totalBackupSizeBytes = computed(() => {
  return backupsList.value.reduce((sum, b) => sum + (b.size || 0), 0)
})

const paginatedBackups = computed(() => {
  const start = (backupCurrentPage.value - 1) * backupPageSize.value
  return backupsList.value.slice(start, start + backupPageSize.value)
})

function openBackupDialog() {
  backupDialogVisible.value = true
  void fetchBackupsList()
}

async function fetchBackupsList() {
  backupLoading.value = true
  try {
    const res = await getSystemBackups()
    if (res.success) {
      backupsList.value = res.backups || []
      if (res.schedule) {
        scheduleForm.enabled = Boolean(res.schedule.enabled)
        scheduleForm.interval_hours = Number(res.schedule.interval_hours || 24)
        scheduleForm.max_keep = Number(res.schedule.max_keep || 15)
        scheduleForm.last_run = res.schedule.last_run || ''
      }
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '获取备份列表失败')
  } finally {
    backupLoading.value = false
  }
}

async function handleCreateBackup() {
  backupCreating.value = true
  try {
    const res = await createSystemBackup(backupRemark.value.trim())
    if (res.success) {
      ElMessage.success(res.message || '全量备份创建成功')
      backupRemark.value = ''
      await fetchBackupsList()
    } else {
      ElMessage.error(res.error || '创建备份失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '创建备份失败')
  } finally {
    backupCreating.value = false
  }
}

async function handleDownloadBackup(item: BackupItem) {
  try {
    ElMessage.info(`正在准备下载备份包: ${item.filename}`)
    await downloadSystemBackup(item.filename)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '下载备份包失败')
  }
}

function triggerBackupUpload() {
  if (backupFileInputRef.value) {
    backupFileInputRef.value.value = ''
    backupFileInputRef.value.click()
  }
}

async function handleBackupFileSelected(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  backupUploading.value = true
  try {
    const res = await uploadSystemBackup(file)
    if (res.success) {
      ElMessage.success(res.message || '备份包上传成功')
      await fetchBackupsList()
    } else {
      ElMessage.error(res.error || '上传失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '上传备份包失败')
  } finally {
    backupUploading.value = false
  }
}

async function handleRestoreBackup(item: BackupItem) {
  try {
    await ElMessageBox.confirm(
      `确定要从备份归档「${item.filename}」恢复全站数据吗？\n\n• 恢复前系统将自动生成一份 safety_pre_restore_* 安全兜底快照\n• 数据库与协议号 Session 凭据将被完整还原至该备份时间点`,
      '⚠️ 全量灾备还原确认',
      {
        confirmButtonText: '确认立即恢复',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    backupRestoring.value = item.filename
    const res = await restoreSystemBackup(item.filename)
    if (res.success) {
      ElMessage.success(res.message || '数据恢复成功')
      await fetchBackupsList()
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '数据恢复失败')
    }
  } catch (e: any) {
    if (e !== 'cancel' && e?.message) {
      ElMessage.error(e.response?.data?.error || e.message || '恢复失败')
    }
  } finally {
    backupRestoring.value = null
  }
}

async function handleDeleteBackup(item: BackupItem) {
  if (item.is_protected) {
    ElMessage.warning('该备份属于系统核心灾备基线或安全快照，严禁删除')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要永久删除备份文件「${item.filename}」吗？`,
      '删除备份确认',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    const res = await deleteSystemBackup(item.filename)
    if (res.success) {
      ElMessage.success(res.message || '备份已删除')
      await fetchBackupsList()
    } else {
      ElMessage.error(res.error || '删除失败')
    }
  } catch {
    // cancelled
  }
}

async function handleSaveBackupSchedule() {
  scheduleSaving.value = true
  try {
    const res = await setBackupSchedule({
      enabled: scheduleForm.enabled,
      interval_hours: scheduleForm.interval_hours,
      max_keep: scheduleForm.max_keep,
    })
    if (res.success) {
      ElMessage.success(res.message || '自动备份策略已保存')
    } else {
      ElMessage.error(res.error || '保存策略失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '保存策略失败')
  } finally {
    scheduleSaving.value = false
  }
}

// ==================== 6.1 租户资产导出与孤儿资产自愈 ====================
const healingOrphans = ref(false)

async function handleHealOrphans() {
  healingOrphans.value = true
  try {
    const res = await healOrphanedMedia()
    if (res.success) {
      const restored = res.data?.total_files_restored ?? 0
      ElMessage.success(res.message || `孤儿资产自愈完成，共恢复 ${restored} 个文件的关联`)
      await fetchUsersData()
    } else {
      ElMessage.error(res.error || '自愈处理失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '自愈处理失败')
  } finally {
    healingOrphans.value = false
  }
}

async function handleExportTenantBackup(row: UserRecord) {
  try {
    ElMessage.info(`正在导出租户「${row.username}」的专属数据资产...`)
    const res = await exportTenantBackup(row.id)
    const blob = new Blob([res.data], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `tenant_backup_${row.username}_${row.id}.json`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success(`租户「${row.username}」数据导出成功`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '导出租户数据失败')
  }
}

// ==================== 7. 租户专属频道无损平移工作台 ====================
const migrationDialogVisible = ref(false)
const migrationTarget = ref<UserRecord | null>(null)
const migrationStarting = ref(false)
const migrationCancelling = ref(false)
const migrationStatus = ref<ChannelMigrationStatus | null>(null)
const migrationLogBoxRef = ref<HTMLElement | null>(null)
let migrationPollTimer: ReturnType<typeof setInterval> | null = null

const migrationForm = reactive({
  mode: 'auto' as 'auto' | 'custom',
  target_dc_id: 5,
  custom_target_channel_id: '',
})

const isMigrationRunning = computed(() => {
  return migrationStatus.value?.status === 'pending' || migrationStatus.value?.status === 'running'
})

function scrollMigrationLogsToBottom() {
  nextTick(() => {
    if (migrationLogBoxRef.value) {
      migrationLogBoxRef.value.scrollTop = migrationLogBoxRef.value.scrollHeight
    }
  })
}

function stopMigrationPolling() {
  if (migrationPollTimer) {
    clearInterval(migrationPollTimer)
    migrationPollTimer = null
  }
}

function startMigrationPolling(userId: number) {
  stopMigrationPolling()
  migrationPollTimer = setInterval(async () => {
    try {
      const res = await getUserChannelMigrationStatus(userId)
      if (res.success && res.data) {
        migrationStatus.value = res.data
        scrollMigrationLogsToBottom()
        if (!['pending', 'running'].includes(res.data.status)) {
          stopMigrationPolling()
          if (res.data.status === 'completed') {
            ElMessage.success('🎉 租户专属频道无损平移已全部完成！')
            await fetchUsersData()
          }
        }
      }
    } catch {
      // ignore transient poll errors
    }
  }, 1200)
}

async function openMigrationDialog(row: UserRecord) {
  migrationTarget.value = row
  migrationForm.mode = 'auto'
  migrationForm.target_dc_id = row.dc_id || 5
  migrationForm.custom_target_channel_id = ''
  migrationStatus.value = null
  migrationDialogVisible.value = true

  try {
    const res = await getUserChannelMigrationStatus(row.id)
    if (res.success && res.data) {
      migrationStatus.value = res.data
      scrollMigrationLogsToBottom()
      if (['pending', 'running'].includes(res.data.status)) {
        startMigrationPolling(row.id)
      }
    }
  } catch {
    // ignore
  }
}

async function handleStartMigration() {
  if (!migrationTarget.value) return
  if (migrationForm.mode === 'custom' && !migrationForm.custom_target_channel_id.trim()) {
    ElMessage.warning('请输入已有目标存储频道的 ID（如 -100xxxxxxxxxx）')
    return
  }
  migrationStarting.value = true
  try {
    const payload =
      migrationForm.mode === 'auto'
        ? { target_dc_id: migrationForm.target_dc_id, custom_target_channel_id: null }
        : {
            target_dc_id: migrationForm.target_dc_id,
            custom_target_channel_id: Number(migrationForm.custom_target_channel_id.trim()),
          }
    const res = await startUserChannelMigration(migrationTarget.value.id, payload)
    if (res.success && res.data) {
      migrationStatus.value = res.data
      ElMessage.success(res.message || '无损平移任务已启动')
      scrollMigrationLogsToBottom()
      startMigrationPolling(migrationTarget.value.id)
    } else {
      ElMessage.error(res.error || '启动平移任务失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '启动平移任务失败')
  } finally {
    migrationStarting.value = false
  }
}

async function handleCancelMigration() {
  if (!migrationTarget.value) return
  migrationCancelling.value = true
  try {
    const res = await cancelUserChannelMigration(migrationTarget.value.id)
    if (res.success) {
      ElMessage.warning(res.message || '已发送安全中止指令')
    } else {
      ElMessage.error(res.error || '中止失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || e.message || '中止失败')
  } finally {
    migrationCancelling.value = false
  }
}

function switchToBlankProvision() {
  if (!migrationTarget.value) return
  const target = migrationTarget.value
  migrationDialogVisible.value = false
  openProvisionDialog(target)
}

onMounted(() => {
  void fetchUsersData()
})

onUnmounted(() => {
  stopMigrationPolling()
})
</script>

<style scoped>
.users-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-bottom: 28px;
}

.users-header-card {
  padding: 22px 24px;
  border-radius: 20px;
}

.users-header-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.users-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.users-title {
  font-size: 22px;
  font-weight: 800;
  margin: 0;
}

.users-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.14), rgba(56, 189, 248, 0.14));
  color: #e11d48;
  border: 1px solid rgba(255, 117, 151, 0.28);
}

.users-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
}

.users-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
}

.backup-entry-btn {
  border-color: rgba(16, 185, 129, 0.4);
  color: #059669;
  background: rgba(16, 185, 129, 0.06);
}

.backup-entry-btn:hover {
  background: rgba(16, 185, 129, 0.14);
  border-color: #10b981;
  color: #047857;
}

.primary-glow-btn {
  background: var(--gradient-primary);
  border: none;
  box-shadow: 0 6px 18px rgba(255, 117, 151, 0.32);
}

.stats-row {
  margin-top: 4px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 15px 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(255, 143, 171, 0.2);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.03);
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

.stat-icon-users {
  background: linear-gradient(135deg, #ff7597, #fb7185);
}

.stat-icon-channels {
  background: linear-gradient(135deg, #10b981, #34d399);
}

.stat-icon-storage {
  background: linear-gradient(135deg, #0ea5e9, #38bdf8);
}

.stat-icon-codes {
  background: linear-gradient(135deg, #f59e0b, #fbbf24);
}

.stat-info {
  min-width: 0;
  flex: 1;
}

.stat-value {
  font-size: 20px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1.2;
}

.stat-value-emerald {
  color: #059669;
}

.stat-value-sky {
  color: #0284c7;
}

.stat-value-amber {
  color: #d97706;
}

.stat-unit {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-radius: 16px;
  flex-wrap: wrap;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}

.search-input {
  max-width: 340px;
}

.filter-count {
  font-size: 13px;
  color: #64748b;
}

.table-card {
  padding: 16px;
  border-radius: 18px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 15px;
  color: #fff;
  flex-shrink: 0;
}

.avatar-admin {
  background: linear-gradient(135deg, #f43f5e, #fb7185);
}

.avatar-user {
  background: linear-gradient(135deg, #0ea5e9, #38bdf8);
}

.user-name-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-name {
  font-weight: 700;
  color: #1e293b;
  font-size: 14px;
}

.user-sub-line {
  font-size: 12px;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.online-dot {
  color: #10b981;
  font-weight: 600;
}

.tg-identity-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tg-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.tg-uname-link {
  color: #0284c7;
  text-decoration: none;
}

.tg-uname-link:hover {
  text-decoration: underline;
}

.tg-uid-row {
  font-size: 12px;
  color: #64748b;
}

.channel-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.channel-top-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.channel-handle-link {
  font-weight: 700;
  color: #059669;
  text-decoration: none;
  font-size: 13px;
}

.channel-handle-link:hover {
  text-decoration: underline;
}

.creator-warning-badge {
  font-size: 11px;
  font-weight: 700;
  color: #dc2626;
  background: rgba(254, 226, 226, 0.9);
  border: 1px solid rgba(248, 113, 113, 0.5);
  padding: 1px 6px;
  border-radius: 999px;
  cursor: help;
}

.channel-sub-row {
  font-size: 11px;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.creator-tag {
  background: rgba(241, 245, 249, 0.9);
  padding: 1px 6px;
  border-radius: 4px;
  color: #475569;
}

.creator-tag-warn {
  background: rgba(254, 243, 199, 0.9);
  color: #b45309;
  font-weight: 600;
}

.creator-tag-ok {
  background: rgba(236, 253, 245, 0.9);
  color: #047857;
}

.storage-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.storage-size-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.storage-bytes {
  font-weight: 700;
  color: #0284c7;
  font-size: 14px;
}

.storage-count {
  font-size: 12px;
  color: #475569;
}

.storage-breakdown {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #64748b;
}

.time-text {
  font-size: 12px;
  color: #64748b;
}

.text-muted {
  font-size: 12px;
  color: #94a3b8;
}

.action-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.dialog-tip-box {
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 12px;
  color: #334155;
  line-height: 1.5;
}

.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 6px 4px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  margin-top: 10px;
}

.pagination-info {
  font-size: 13px;
  color: #64748b;
}

.users-pagination {
  margin-left: auto;
}

.dialog-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.dialog-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  flex-wrap: wrap;
}

.dialog-pagination-info {
  font-size: 12px;
  color: #64748b;
}

/* 灾备中心弹窗专用精美样式 */
.disaster-backup-dialog {
  border-radius: 20px !important;
}

.disaster-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 32px;
}

.disaster-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.disaster-icon-box {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(14, 165, 233, 0.12));
  border: 1px solid rgba(16, 185, 129, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.disaster-title {
  font-size: 16px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1.3;
}

.disaster-desc {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

.header-tag-pill {
  font-size: 12px;
  font-weight: 600;
  border-radius: 999px;
  padding: 4px 10px;
}

.backup-top-grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

@media (max-width: 768px) {
  .backup-top-grid {
    grid-template-columns: 1fr;
  }
}

.backup-info-card,
.backup-sched-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.backup-info-title,
.backup-sched-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}

.backup-info-text {
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
  margin: 6px 0;
}

.backup-info-text code,
.backup-safety-notice code {
  background: rgba(226, 232, 240, 0.8);
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 11px;
  color: #0f172a;
}

.backup-safety-notice {
  font-size: 11px;
  color: #047857;
  background: rgba(236, 253, 245, 0.9);
  border: 1px solid rgba(167, 243, 208, 0.9);
  padding: 4px 8px;
  border-radius: 6px;
}

.backup-sched-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.backup-sched-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  flex-wrap: wrap;
}

.sched-inline-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #475569;
}

.sched-label,
.sched-unit {
  font-size: 12px;
  color: #64748b;
}

.sched-save-btn {
  background: #0284c7 !important;
  color: #ffffff !important;
  border: none !important;
  font-weight: 600 !important;
  border-radius: 8px !important;
  padding: 0 10px !important;
  height: 28px !important;
}

.sched-save-btn:hover {
  background: #0369a1 !important;
}

.backup-sched-foot {
  font-size: 11px;
  color: #94a3b8;
}

.backup-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.backup-create-group,
.backup-upload-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.btn-create-backup {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
  color: #ffffff !important;
  border: none !important;
  font-weight: 600 !important;
  border-radius: 10px !important;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.28) !important;
}

.btn-create-backup:hover {
  background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
}

.btn-neutral {
  border-radius: 10px !important;
  border: 1px solid #cbd5e1 !important;
  color: #334155 !important;
  background: #ffffff !important;
  font-weight: 500 !important;
}

.btn-neutral:hover {
  border-color: #94a3b8 !important;
  color: #0f172a !important;
  background: #f8fafc !important;
}

.backup-table-wrapper {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}

.backup-file-entry {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.backup-fname-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.backup-file-icon {
  font-size: 14px;
}

.backup-fname {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 250px;
}

.backup-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tag-compact {
  font-size: 11px !important;
  padding: 0 6px !important;
  height: 20px !important;
  line-height: 20px !important;
}

.backup-remark-tag {
  font-size: 11px;
  color: #475569;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 1px 6px;
  border-radius: 4px;
}

.manifest-pill-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.meta-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
}

.pill-user {
  background: rgba(244, 63, 94, 0.08);
  color: #e11d48;
  border: 1px solid rgba(244, 63, 94, 0.2);
}

.pill-media {
  background: rgba(14, 165, 233, 0.08);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

.pill-sess {
  background: rgba(16, 185, 129, 0.08);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.backup-size-text {
  font-weight: 700;
  color: #0284c7;
  font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.backup-action-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.btn-act-download {
  color: #0284c7 !important;
  background: rgba(2, 132, 199, 0.08) !important;
  border: 1px solid rgba(2, 132, 199, 0.3) !important;
  font-weight: 600 !important;
  border-radius: 8px !important;
}

.btn-act-download:hover {
  background: #0284c7 !important;
  color: #ffffff !important;
}

.btn-act-restore {
  color: #d97706 !important;
  background: rgba(217, 119, 6, 0.08) !important;
  border: 1px solid rgba(217, 119, 6, 0.3) !important;
  font-weight: 600 !important;
  border-radius: 8px !important;
}

.btn-act-restore:hover {
  background: #d97706 !important;
  color: #ffffff !important;
}

.btn-act-delete {
  color: #e11d48 !important;
  background: rgba(225, 29, 72, 0.08) !important;
  border: 1px solid rgba(225, 29, 72, 0.25) !important;
  border-radius: 8px !important;
}

.btn-act-delete:hover {
  background: #e11d48 !important;
  color: #ffffff !important;
}

/* 无损平移工作台样式 */
.mig-source-card {
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(203, 213, 225, 0.75);
  border-radius: 12px;
  padding: 12px 14px;
}

.mig-source-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.mig-source-title {
  font-weight: 700;
  font-size: 13px;
  color: #1e293b;
}

.mig-source-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}

.mig-kv {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mig-k {
  color: #64748b;
  min-width: 105px;
}

.mig-v {
  color: #1e293b;
}

.mig-progress-panel {
  margin-top: 12px;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  padding: 12px;
}

.mig-progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.mig-status-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mig-target-tag {
  font-size: 12px;
  color: #059669;
}

.mig-counters {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #475569;
}

.mig-terminal-box {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 200px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
}

.mig-log-line {
  display: flex;
  gap: 8px;
  word-break: break-all;
}

.mig-log-time {
  color: #64748b;
  flex-shrink: 0;
}

.mig-log-info .mig-log-msg {
  color: #e2e8f0;
}

.mig-log-success .mig-log-msg {
  color: #34d399;
  font-weight: 600;
}

.mig-log-warning .mig-log-msg {
  color: #fbbf24;
}

.mig-log-error .mig-log-msg {
  color: #f87171;
}

.mig-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  flex-wrap: wrap;
  gap: 8px;
}

.mig-footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
</style>

<style>
/* 全量灾备与一键恢复中心 - 现代企业级精致主题（覆盖 append-to-body 与全局粉色变量） */
.disaster-backup-dialog.el-dialog {
  border-radius: 16px !important;
  border: 1px solid #cbd5e1 !important;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.25) !important;
  background: #ffffff !important;
  color: #1e293b !important;
  overflow: hidden !important;
}

.disaster-backup-dialog .el-dialog__header {
  padding: 16px 20px 14px !important;
  margin-right: 0 !important;
  border-bottom: 1px solid #e2e8f0 !important;
  background: #f8fafc !important;
}

.disaster-backup-dialog .el-dialog__body {
  padding: 18px 20px !important;
  background: #ffffff !important;
}

.disaster-backup-dialog .disaster-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 28px;
}

.disaster-backup-dialog .disaster-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.disaster-backup-dialog .disaster-icon-box {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: #eff6ff !important;
  border: 1px solid #bfdbfe !important;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #2563eb;
}

.disaster-backup-dialog .disaster-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.3;
}

.disaster-backup-dialog .disaster-desc {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

.disaster-backup-dialog .header-tag-pill {
  font-size: 12px;
  font-weight: 600;
  border-radius: 999px;
  padding: 4px 10px;
  background: #ecfdf5 !important;
  color: #059669 !important;
  border: 1px solid #a7f3d0 !important;
}

.disaster-backup-dialog .backup-top-grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

@media (max-width: 768px) {
  .disaster-backup-dialog.el-dialog {
    width: 94vw !important;
    margin: 12px auto !important;
  }

  .disaster-backup-dialog .disaster-dialog-header {
    flex-direction: column !important;
    align-items: flex-start !important;
    gap: 8px !important;
    padding-right: 24px !important;
  }

  .disaster-backup-dialog .disaster-header-left {
    width: 100% !important;
  }

  .disaster-backup-dialog .disaster-title {
    font-size: 15px !important;
    white-space: normal !important;
  }

  .disaster-backup-dialog .backup-top-grid {
    grid-template-columns: 1fr !important;
  }

  .disaster-backup-dialog .backup-action-bar,
  .disaster-backup-dialog .backup-create-group,
  .disaster-backup-dialog .backup-upload-group {
    flex-direction: column !important;
    align-items: stretch !important;
    width: 100% !important;
    gap: 8px !important;
  }

  .disaster-backup-dialog .backup-create-group .el-input {
    width: 100% !important;
  }

  .disaster-backup-dialog .btn-create-backup {
    width: 100% !important;
  }

  .disaster-backup-dialog .sched-form-row {
    flex-wrap: wrap !important;
    gap: 8px !important;
  }
}

.disaster-backup-dialog .backup-info-card,
.disaster-backup-dialog .backup-sched-card {
  background: #f8fafc !important;
  border: 1px solid #e2e8f0 !important;
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.disaster-backup-dialog .backup-info-title,
.disaster-backup-dialog .backup-sched-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.disaster-backup-dialog .backup-info-text {
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
  margin: 6px 0;
}

.disaster-backup-dialog .backup-info-text code,
.disaster-backup-dialog .backup-safety-notice code {
  background: #e2e8f0 !important;
  padding: 2px 5px !important;
  border-radius: 4px !important;
  font-size: 11px !important;
  color: #0f172a !important;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.disaster-backup-dialog .backup-safety-notice {
  font-size: 11px;
  color: #047857;
  background: #ecfdf5 !important;
  border: 1px solid #a7f3d0 !important;
  padding: 4px 8px;
  border-radius: 6px;
}

.disaster-backup-dialog .backup-sched-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.disaster-backup-dialog .backup-sched-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  flex-wrap: wrap;
}

.disaster-backup-dialog .sched-inline-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #475569;
}

.disaster-backup-dialog .sched-label,
.disaster-backup-dialog .sched-unit {
  font-size: 12px;
  color: #64748b;
}

.disaster-backup-dialog .sched-save-btn {
  background: #0284c7 !important;
  color: #ffffff !important;
  border: none !important;
  font-weight: 600 !important;
  border-radius: 6px !important;
  padding: 0 10px !important;
  height: 28px !important;
  box-shadow: none !important;
}

.disaster-backup-dialog .sched-save-btn:hover {
  background: #0369a1 !important;
}

.disaster-backup-dialog .backup-sched-foot {
  font-size: 11px;
  color: #94a3b8;
}

.disaster-backup-dialog .backup-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.disaster-backup-dialog .backup-create-group,
.disaster-backup-dialog .backup-upload-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.disaster-backup-dialog .el-input__wrapper {
  border-radius: 8px !important;
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
  background: #ffffff !important;
}

.disaster-backup-dialog .el-input__wrapper:hover {
  box-shadow: 0 0 0 1px #94a3b8 inset !important;
}

.disaster-backup-dialog .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.4) inset !important;
}

.disaster-backup-dialog .btn-create-backup {
  background: #059669 !important;
  border: 1px solid #059669 !important;
  color: #ffffff !important;
  font-weight: 600 !important;
  border-radius: 8px !important;
  box-shadow: 0 1px 3px rgba(5, 150, 105, 0.25) !important;
}

.disaster-backup-dialog .btn-create-backup:hover {
  background: #047857 !important;
  border-color: #047857 !important;
}

.disaster-backup-dialog .btn-neutral {
  border-radius: 8px !important;
  border: 1px solid #cbd5e1 !important;
  color: #334155 !important;
  background: #ffffff !important;
  font-weight: 500 !important;
  box-shadow: none !important;
}

.disaster-backup-dialog .btn-neutral:hover {
  border-color: #94a3b8 !important;
  background: #f8fafc !important;
  color: #0f172a !important;
}

.disaster-backup-dialog .backup-table-wrapper {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.disaster-backup-dialog .el-table th.el-table__cell {
  background: #f8fafc !important;
  color: #475569 !important;
  font-weight: 600 !important;
  border-bottom: 1px solid #e2e8f0 !important;
}

.disaster-backup-dialog .el-table td.el-table__cell {
  border-bottom: 1px solid #f1f5f9 !important;
}

.disaster-backup-dialog .el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background: #f8fafc !important;
}

.disaster-backup-dialog .backup-file-entry {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.disaster-backup-dialog .backup-fname-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.disaster-backup-dialog .backup-file-icon {
  font-size: 14px;
}

.disaster-backup-dialog .backup-fname {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 250px;
}

.disaster-backup-dialog .backup-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.disaster-backup-dialog .tag-compact {
  font-size: 11px !important;
  padding: 0 6px !important;
  height: 20px !important;
  line-height: 20px !important;
}

.disaster-backup-dialog .backup-remark-tag {
  font-size: 11px;
  color: #475569;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 1px 6px;
  border-radius: 4px;
}

.disaster-backup-dialog .manifest-pill-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.disaster-backup-dialog .meta-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
}

.disaster-backup-dialog .pill-user {
  background: rgba(244, 63, 94, 0.08);
  color: #e11d48;
  border: 1px solid rgba(244, 63, 94, 0.2);
}

.disaster-backup-dialog .pill-media {
  background: rgba(14, 165, 233, 0.08);
  color: #0284c7;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

.disaster-backup-dialog .pill-sess {
  background: rgba(16, 185, 129, 0.08);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.disaster-backup-dialog .backup-size-text {
  font-weight: 700;
  color: #0284c7;
  font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.disaster-backup-dialog .backup-action-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.disaster-backup-dialog .btn-act-download {
  color: #0284c7 !important;
  background: #eff6ff !important;
  border: 1px solid #bfdbfe !important;
  font-weight: 600 !important;
  border-radius: 6px !important;
  box-shadow: none !important;
}

.disaster-backup-dialog .btn-act-download:hover {
  background: #0284c7 !important;
  color: #ffffff !important;
}

.disaster-backup-dialog .btn-act-restore {
  color: #d97706 !important;
  background: #fffbeb !important;
  border: 1px solid #fde68a !important;
  font-weight: 600 !important;
  border-radius: 6px !important;
  box-shadow: none !important;
}

.disaster-backup-dialog .btn-act-restore:hover {
  background: #d97706 !important;
  color: #ffffff !important;
}

.disaster-backup-dialog .btn-act-delete {
  color: #e11d48 !important;
  background: #fff1f2 !important;
  border: 1px solid #fecdd3 !important;
  font-weight: 600 !important;
  border-radius: 6px !important;
  box-shadow: none !important;
}

.disaster-backup-dialog .btn-act-delete:hover {
  background: #e11d48 !important;
  color: #ffffff !important;
}

.disaster-backup-dialog .el-switch.is-checked .el-switch__core {
  background-color: #10b981 !important;
  border-color: #10b981 !important;
}

.disaster-backup-dialog .el-pagination.is-background .el-pager li.is-active {
  background-color: #0284c7 !important;
  color: #ffffff !important;
}

/* 租户专属频道无损平移工作台弹窗 */
.migration-dialog.el-dialog {
  border-radius: 16px !important;
  border: 1px solid #cbd5e1 !important;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.25) !important;
  background: #ffffff !important;
  color: #1e293b !important;
  overflow: hidden !important;
}

.migration-dialog .el-dialog__header {
  padding: 16px 20px 14px !important;
  margin-right: 0 !important;
  border-bottom: 1px solid #e2e8f0 !important;
  background: #f8fafc !important;
}

.migration-dialog .el-dialog__body {
  padding: 18px 20px !important;
  background: #ffffff !important;
}

.migration-dialog .el-input__wrapper {
  border-radius: 8px !important;
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
  background: #ffffff !important;
}

.migration-dialog .el-button--primary:not(.is-plain):not(.is-text):not(.is-link) {
  background: #0284c7 !important;
  border: 1px solid #0284c7 !important;
  color: #ffffff !important;
  box-shadow: 0 1px 3px rgba(2, 132, 199, 0.3) !important;
}
</style>

/* ========== 移动端响应式覆盖 ========== */
@media (max-width: 768px) {
  .users-page {
    padding: 0 !important;
  }

  .header-card,
  .table-card,
  .filter-bar {
    padding: 14px !important;
    border-radius: 14px !important;
  }

  .filter-bar {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  .filter-left {
    flex-direction: column !important;
    align-items: stretch !important;
    width: 100% !important;
  }

  .filter-left > * {
    width: 100% !important;
    max-width: 100% !important;
  }

  .filter-right {
    margin-top: 4px;
    text-align: right;
  }

  .pagination-bar {
    flex-direction: column !important;
    align-items: stretch !important;
    gap: 8px !important;
  }

  .users-pagination {
    overflow-x: auto !important;
    max-width: 100% !important;
  }

  .mobile-user-card {
    background: rgba(255, 255, 255, 0.95);
    border: 1px solid rgba(255, 143, 171, 0.22);
    box-shadow: 0 4px 14px rgba(255, 117, 151, 0.06);
  }

  .disaster-backup-dialog .backup-top-grid {
    grid-template-columns: 1fr !important;
  }

  .disaster-backup-dialog .disaster-dialog-header {
    flex-direction: column !important;
    align-items: flex-start !important;
    gap: 8px !important;
    padding-right: 28px !important;
  }

  .disaster-backup-dialog .disaster-title {
    font-size: 15px !important;
  }

  .disaster-backup-dialog .backup-action-bar,
  .disaster-backup-dialog .backup-create-group,
  .disaster-backup-dialog .backup-upload-group {
    flex-direction: column !important;
    align-items: stretch !important;
    width: 100% !important;
    gap: 8px !important;
  }

  .disaster-backup-dialog .backup-create-group .el-input {
    width: 100% !important;
  }

  .disaster-backup-dialog .btn-create-backup {
    width: 100% !important;
  }

  .disaster-backup-dialog .sched-form-row {
    flex-wrap: wrap !important;
    gap: 8px !important;
  }
}
