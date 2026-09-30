<template>
  <div class="settings-page animate-fade-in">
    <!-- 顶部品牌横幅与连接状态 -->
    <div class="settings-header-card glass-card">
      <div class="settings-header-main">
        <div class="settings-title-group">
          <div class="settings-title-row">
            <h2 class="settings-title text-gradient-sakura">系统设置与运维中心</h2>
            <span class="settings-badge">Config & DevOps</span>
          </div>
          <p class="settings-subtitle">
            核心服务参数动态配置、Aria2 RPC 调优、直链管理与 Docker 容器全生命周期治理。
          </p>
        </div>

        <div class="settings-header-actions">
          <div class="connection-pill-card">
            <span class="connection-dot" :class="connectionStatusDotClass"></span>
            <div class="connection-pill-info">
              <span class="connection-pill-label">后端连接状态</span>
              <span class="connection-pill-val">{{ connectionStatusLabel }} ({{ effectiveServerUrlLabel }})</span>
            </div>
          </div>

          <el-button
            class="header-btn"
            :icon="Refresh"
            @click="reloadCurrentTab"
            size="default"
          >
            重新载入
          </el-button>
        </div>
      </div>
    </div>

    <!-- 核心配置变更需重启提示横幅 -->
    <div v-if="pendingRestartWarning" class="cluster-banner banner-warning mb-4 flex items-center justify-between flex-wrap gap-3">
      <div class="flex items-center gap-2">
        <span class="banner-icon">⚠️</span>
        <span class="banner-text">
          <strong>核心配置变更已落库：</strong>{{ pendingRestartMessage || "部分核心参数需要重启容器以全面生效。" }}
        </span>
      </div>
      <div class="flex items-center gap-2">
        <el-button size="small" type="warning" :icon="RefreshRight" :loading="restarting" @click="handleRestart">
          ⚡ 一键重启容器（热重载）
        </el-button>
        <el-button size="small" text @click="pendingRestartWarning = false">
          稍后处理
        </el-button>
      </div>
    </div>

    <!-- 现代 Segmented 毛玻璃设置标签页 -->
    <div class="settings-tabs-wrapper">
      <el-tabs v-model="activeTab" class="modern-settings-tabs" type="border-card">
        <!-- 1. 客户端连接 -->
        <el-tab-pane name="client" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><Link /></el-icon>
              <span>客户端连接</span>
            </span>
          </template>

          <div v-if="activeTab === 'client'" class="tab-pane-content">
            <div class="pane-header-row">
              <div class="pane-title-group">
                <h3 class="pane-title">客户端连接配置</h3>
                <p class="pane-desc">管理 Web 前端与 MistRelay 后端服务的通信端点及同源/远程策略</p>
              </div>
              <div class="pane-actions">
                <el-button @click="testConnection" :loading="testingConnection">
                  测试连接
                </el-button>
                <el-button type="primary" @click="saveClientConnection" :loading="savingClientConnection">
                  保存并应用
                </el-button>
              </div>
            </div>

            <el-alert
              title="浏览器端可选择同源访问，也可以指定远程服务器。"
              type="info"
              :closable="false"
              class="modern-alert mb-6"
            />

            <el-form label-width="180px" class="modern-form">
              <el-form-item label="客户端类型">
                <el-tag type="info" class="font-medium">浏览器客户端</el-tag>
              </el-form-item>
              <el-form-item label="服务器地址">
                <el-input
                  v-model="clientServerUrl"
                  placeholder="127.0.0.1:8080 或 https://mistrelay.example.com"
                  clearable
                />
                <div class="el-form-item__help">
                  留空时继续使用当前同源服务。
                </div>
              </el-form-item>
              <el-form-item label="当前生效地址">
                <el-input :model-value="effectiveServerUrlLabel" readonly class="readonly-input" />
              </el-form-item>
              <el-form-item label="连接状态">
                <div class="connection-status">
                  <el-tag :type="connectionStatusTagType" effect="light">
                    {{ connectionStatusLabel }}
                  </el-tag>
                  <span v-if="connectionStatusText" class="connection-status-text">
                    {{ connectionStatusText }}
                  </span>
                </div>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- 2. Telegram配置 -->
        <el-tab-pane name="telegram" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><Promotion /></el-icon>
              <span>Telegram配置</span>
            </span>
          </template>

          <div v-if="activeTab === 'telegram'" class="tab-pane-content">
            <div class="pane-header-row">
              <div class="pane-title-group">
                <h3 class="pane-title">Telegram Bot 配置</h3>
                <p class="pane-desc">配置 Telegram 认证凭证与频道自动转存参数</p>
              </div>
              <div class="pane-actions">
                <el-button type="primary" @click="saveConfig('telegram')" :loading="saving">
                  保存配置
                </el-button>
              </div>
            </div>

            <el-alert
              type="warning"
              :closable="false"
              class="modern-alert mb-6"
            >
              <template #title>
                <div style="font-size: 13px; line-height: 1.6;">
                  <strong>注意：</strong>修改 API ID、API Hash、Bot Token 或管理员ID 后需要重启服务才能生效。
                  <br />其他配置（如上传到 Telegram）保存后会在下次使用时自动从数据库读取最新配置。
                </div>
              </template>
            </el-alert>

            <el-form :model="configs.telegram" label-width="180px" :rules="rules" class="modern-form">
              <el-form-item label="API ID" prop="API_ID">
                <el-input-number
                  v-model="configs.telegram.API_ID"
                  :min="0"
                  style="width: 100%"
                  :disabled="isOfflineOnly('API_ID')"
                />
              </el-form-item>
              <el-form-item label="API Hash" prop="API_HASH">
                <el-input
                  v-model="configs.telegram.API_HASH"
                  type="password"
                  show-password
                  :disabled="isOfflineOnly('API_HASH')"
                  :placeholder="secretStatus('API_HASH')"
                />
              </el-form-item>
              <el-form-item label="Bot Token" prop="BOT_TOKEN">
                <el-input
                  v-model="configs.telegram.BOT_TOKEN"
                  type="password"
                  show-password
                  :disabled="isOfflineOnly('BOT_TOKEN')"
                  :placeholder="secretStatus('BOT_TOKEN')"
                />
              </el-form-item>
              <el-form-item label="管理员ID" prop="ADMIN_ID">
                <el-input-number
                  v-model="configs.telegram.ADMIN_ID"
                  :min="0"
                  style="width: 100%"
                  :disabled="isOfflineOnly('ADMIN_ID')"
                />
              </el-form-item>
              <el-form-item label="上传到Telegram">
                <el-switch v-model="configs.telegram.UP_TELEGRAM" />
              </el-form-item>
            </el-form>

            <!-- 多租户云盘与自助注册策略卡片 -->
            <div class="bot-cluster-card mt-6">
              <div class="cluster-card-header">
                <div class="flex items-center gap-2">
                  <div class="cluster-icon-pill">
                    <el-icon><Promotion /></el-icon>
                  </div>
                  <div>
                    <h4 class="cluster-title">多租户云盘与自助注册策略</h4>
                    <p class="cluster-desc">
                      管控用户通过 Telegram 私聊 /register 自助获取验证码注册、默认 DC 数据中心分配与专属存储频道 Handle 规则
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <el-button size="small" plain @click="router.push('/users')">
                    前往用户管理 (/users)
                  </el-button>
                  <el-button size="small" type="primary" @click="saveConfig('telegram')" :loading="saving">
                    保存多租户策略
                  </el-button>
                </div>
              </div>

              <el-form :model="configs.telegram" label-width="180px" class="modern-form mt-4">
                <el-form-item label="开放自助注册">
                  <el-switch
                    v-model="configs.telegram.ALLOW_USER_REGISTRATION"
                    active-text="允许用户私聊 /register 获取验证码自助注册"
                    inactive-text="仅限管理员在后台手动开户"
                  />
                </el-form-item>
                <el-form-item label="默认建频数据中心">
                  <el-select v-model="configs.telegram.DEFAULT_TENANT_DC_ID" style="width: 100%">
                    <el-option :value="1" label="DC1 - 美国/迈阿密 (低延迟欧美)" />
                    <el-option :value="2" label="DC2 - 欧洲/阿姆斯特丹" />
                    <el-option :value="3" label="DC3 - 美国/迈阿密" />
                    <el-option :value="4" label="DC4 - 欧洲/阿姆斯特丹" />
                    <el-option :value="5" label="DC5 - 亚太/新加坡 (推荐默认)" />
                  </el-select>
                  <div class="el-form-item__help">
                    当注册用户未设置 Telegram 头像且无法通过语言判定时，默认调配该区域的协议号创建专属频道。
                  </div>
                </el-form-item>
                <el-form-item label="专属频道 Handle 前缀">
                  <el-input
                    v-model="configs.telegram.TENANT_CHANNEL_PREFIX"
                    placeholder="mr_u"
                  />
                  <div class="el-form-item__help">
                    自动生成形如 @{{ configs.telegram.TENANT_CHANNEL_PREFIX || 'mr_u' }}9001_xxxx 的公开频道用户名，供 55+ Bot 集群免加群极速分流。
                  </div>
                </el-form-item>
              </el-form>
            </div>

            <!-- 协议号资产池保活与家宽代理配置卡片 -->
            <div class="bot-cluster-card mt-6">
              <div class="cluster-card-header">
                <div class="flex items-center gap-2">
                  <div class="cluster-icon-pill">
                    <el-icon><Cpu /></el-icon>
                  </div>
                  <div>
                    <h4 class="cluster-title">协议号保活与家宽代理配置</h4>
                    <p class="cluster-desc">
                      配置协议号资产池后台定时自动保活巡检与 my.telegram.org 开发者凭证提取家宽代理接口
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <el-button size="small" plain @click="router.push('/botfather')">
                    前往自动铸机 (/botfather)
                  </el-button>
                  <el-button size="small" type="primary" @click="saveConfig('telegram')" :loading="saving">
                    保存保活与代理配置
                  </el-button>
                </div>
              </div>

              <el-form :model="configs.telegram" label-width="180px" class="modern-form mt-4">
                <el-form-item label="定时自动保活">
                  <el-switch
                    v-model="configs.telegram.PROTOCOL_KEEPALIVE_ENABLED"
                    active-text="启用后台定时 MTProto 握手保活与失效自动重登"
                  />
                </el-form-item>
                <el-form-item label="保活巡检周期" v-if="configs.telegram.PROTOCOL_KEEPALIVE_ENABLED">
                  <el-select v-model="configs.telegram.PROTOCOL_KEEPALIVE_INTERVAL_HOURS" style="width: 100%">
                    <el-option :value="6" label="每 6 小时巡检一次" />
                    <el-option :value="12" label="每 12 小时巡检一次 (推荐)" />
                    <el-option :value="24" label="每 24 小时巡检一次" />
                    <el-option :value="48" label="每 48 小时巡检一次" />
                  </el-select>
                </el-form-item>
                <el-form-item label="家宽代理 API 模板">
                  <el-input
                    v-model="configs.telegram.TELEGRAM_API_PROXY_URL"
                    placeholder="https://white.novproxy.com/white/api?region=US&num=1&time=10&format=1&type=txt"
                    clearable
                  />
                  <div class="el-form-item__help">
                    提取协议号 api_id / api_hash 时，系统会自动根据手机号国际区号将 region=XX 动态替换为对应国家代码。
                  </div>
                </el-form-item>
              </el-form>
            </div>
          </div>
        </el-tab-pane>

        <!-- 3. 下载配置 -->
        <el-tab-pane name="download" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><Download /></el-icon>
              <span>下载配置</span>
            </span>
          </template>

          <div v-if="activeTab === 'download'" class="tab-pane-content">
            <div class="pane-header-row">
              <div class="pane-title-group">
                <h3 class="pane-title">本地存储与下载策略</h3>
                <p class="pane-desc">配置下载保存路径、网络代理及文件生命周期清理策略</p>
              </div>
              <div class="pane-actions">
                <el-button type="primary" @click="saveConfig('download')" :loading="saving">
                  保存配置
                </el-button>
              </div>
            </div>

            <el-alert
              type="info"
              :closable="false"
              class="modern-alert mb-6"
            >
              <template #title>
                <div style="font-size: 13px">
                  <strong>提示：</strong>下载配置保存后会立即生效，下次下载时会自动从数据库读取最新配置，无需重启服务。
                </div>
              </template>
            </el-alert>

            <el-form :model="configs.download" label-width="200px" class="modern-form">
              <el-form-item label="保存路径">
                <el-input v-model="configs.download.SAVE_PATH" />
              </el-form-item>
              <el-form-item label="自动清理下载文件">
                <el-switch v-model="configs.download.DOWNLOAD_CLEANUP_ENABLED" />
                <div class="el-form-item__help">
                  启用后，后台会定期清理保存路径中超过保留时间的本地文件，并自动跳过正在下载或上传的文件
                </div>
              </el-form-item>
              <el-form-item
                label="下载文件保留时间（小时）"
                v-if="configs.download.DOWNLOAD_CLEANUP_ENABLED"
              >
                <el-input-number
                  v-model="configs.download.DOWNLOAD_RETENTION_HOURS"
                  :min="1"
                  :max="8760"
                  style="width: 100%"
                />
                <div class="el-form-item__help">
                  默认保留 24 小时；清理任务每小时检查一次
                </div>
              </el-form-item>
              <el-form-item label="代理IP">
                <el-input
                  v-model="configs.download.PROXY_IP"
                  placeholder="留空则不使用代理"
                  :disabled="isOfflineOnly('PROXY_IP')"
                />
              </el-form-item>
              <el-form-item label="代理端口">
                <el-input
                  v-model="configs.download.PROXY_PORT"
                  placeholder="留空则不使用代理"
                  :disabled="isOfflineOnly('PROXY_PORT')"
                />
              </el-form-item>
              <el-form-item label="最大并发上传数">
                <el-input-number
                  v-model="configs.download.MAX_CONCURRENT_UPLOADS"
                  :min="1"
                  :max="32"
                  style="width: 100%"
                />
                <div class="el-form-item__help">
                  本地文件并发上传至 Telegram 频道的最大任务数（默认：10）
                </div>
              </el-form-item>
              <el-form-item label="缩略图缓存保留天数">
                <el-input-number
                  v-model="configs.download.THUMBNAIL_CACHE_MAX_AGE_DAYS"
                  :min="1"
                  :max="365"
                  style="width: 100%"
                />
              </el-form-item>
              <el-divider />
              <el-form-item label="跳过小文件">
                <el-switch v-model="configs.download.SKIP_SMALL_FILES" />
                <div class="el-form-item__help">
                  启用后，小于指定大小的媒体文件将不会被下载
                </div>
              </el-form-item>
              <el-form-item
                label="最小文件大小（MB）"
                v-if="configs.download.SKIP_SMALL_FILES"
              >
                <el-input-number
                  v-model="configs.download.MIN_FILE_SIZE_MB"
                  :min="1"
                  :max="10000"
                  style="width: 100%"
                />
                <div class="el-form-item__help">
                  小于此大小的文件将被跳过下载（默认：100MB）
                </div>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- 4. Aria2配置 -->
        <el-tab-pane name="aria2" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><Cpu /></el-icon>
              <span>Aria2配置</span>
            </span>
          </template>

          <div v-if="activeTab === 'aria2'" class="tab-pane-content">
            <div class="pane-header-row">
              <div class="pane-title-group">
                <h3 class="pane-title">Aria2 RPC 引擎配置</h3>
                <p class="pane-desc">配置 Aria2 RPC 秘钥与端点连接地址，并支持一键连通性诊断</p>
              </div>
              <div class="pane-actions">
                <el-button type="success" plain @click="handleTestAria2" :loading="testingAria2">
                  🔌 测试 Aria2 连通性
                </el-button>
                <el-button type="primary" @click="saveConfig('aria2')" :loading="saving">
                  保存配置
                </el-button>
              </div>
            </div>

            <div v-if="aria2TestResult" class="cluster-banner mb-4" :class="aria2TestResult.success ? 'banner-success' : 'banner-warning'">
              <span class="banner-icon">{{ aria2TestResult.success ? '✅' : '❌' }}</span>
              <span v-if="aria2TestResult.success && aria2TestResult.data" class="banner-text">
                <strong>Aria2 RPC 握手成功：</strong>版本 <code>v{{ aria2TestResult.data.version }}</code> ·
                下载目录 <code>{{ aria2TestResult.data.download_dir }}</code> ·
                活跃任务 <strong>{{ aria2TestResult.data.num_active }}</strong> ·
                等待中 <strong>{{ aria2TestResult.data.num_waiting }}</strong> ·
                已停止/完成 <strong>{{ aria2TestResult.data.num_stopped }}</strong>
              </span>
              <span v-else class="banner-text">
                <strong>连接失败：</strong>{{ aria2TestResult.error }}
              </span>
            </div>

            <el-alert
              type="info"
              :closable="false"
              class="modern-alert mb-6"
            >
              <template #title>
                <div style="font-size: 13px">
                  <strong>提示：</strong>Aria2配置保存后会立即生效，下次连接时会自动从数据库读取最新配置，无需重启服务。
                </div>
              </template>
            </el-alert>

            <el-form :model="configs.aria2" label-width="180px" class="modern-form">
              <el-form-item label="RPC密钥">
                <el-input
                  v-model="configs.aria2.RPC_SECRET"
                  type="password"
                  show-password
                  :disabled="isOfflineOnly('RPC_SECRET')"
                  :placeholder="secretStatus('RPC_SECRET')"
                />
              </el-form-item>
              <el-form-item label="RPC URL">
                <el-input v-model="configs.aria2.RPC_URL" :disabled="isOfflineOnly('RPC_URL')" />
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- 5. 直链功能 -->
        <el-tab-pane name="stream" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><VideoPlay /></el-icon>
              <span>直链功能</span>
            </span>
          </template>

          <div v-if="activeTab === 'stream'" class="tab-pane-content">
            <div class="pane-header-row">
              <div class="pane-title-group">
                <h3 class="pane-title">媒体直链与 WebStreamer 服务</h3>
                <p class="pane-desc">配置 Telegram 媒体流媒体代理、SSL 端口与多机器人分流池</p>
              </div>
              <div class="pane-actions">
                <el-button type="primary" @click="saveConfig('stream')" :loading="saving">
                  保存配置
                </el-button>
              </div>
            </div>

            <el-form :model="configs.stream" label-width="180px" class="modern-form">
              <el-form-item label="启用直链功能">
                <el-switch v-model="configs.stream.ENABLE_STREAM" />
              </el-form-item>
              <el-form-item label="日志频道ID">
                <el-input v-model="configs.stream.BIN_CHANNEL" :disabled="isOfflineOnly('BIN_CHANNEL')" />
              </el-form-item>
              <el-form-item label="Web服务器端口">
                <el-input-number v-model="configs.stream.STREAM_PORT" :min="1" :max="65535" style="width: 100%" />
              </el-form-item>
              <el-form-item label="绑定地址">
                <el-input v-model="configs.stream.STREAM_BIND_ADDRESS" />
              </el-form-item>
              <el-form-item label="哈希长度">
                <el-input-number v-model="configs.stream.STREAM_HASH_LENGTH" :min="5" :max="64" style="width: 100%" />
              </el-form-item>
              <el-form-item label="使用SSL">
                <el-switch v-model="configs.stream.STREAM_HAS_SSL" />
              </el-form-item>
              <el-form-item label="隐藏端口">
                <el-switch v-model="configs.stream.STREAM_NO_PORT" />
              </el-form-item>
              <el-form-item label="完全限定域名">
                <el-input v-model="configs.stream.STREAM_FQDN" />
              </el-form-item>
              <el-form-item label="保持连接活跃">
                <el-switch v-model="configs.stream.STREAM_KEEP_ALIVE" />
              </el-form-item>
              <el-form-item label="Ping间隔（秒）">
                <el-input-number v-model="configs.stream.STREAM_PING_INTERVAL" :min="60" style="width: 100%" />
              </el-form-item>
              <el-form-item label="使用会话文件">
                <el-switch v-model="configs.stream.STREAM_USE_SESSION_FILE" :disabled="isOfflineOnly('STREAM_USE_SESSION_FILE')" />
              </el-form-item>
              <el-form-item label="允许使用直链的用户">
                <el-input
                  v-model="configs.stream.STREAM_ALLOWED_USERS"
                  placeholder="数字用户 ID，逗号分隔；留空则拒绝所有人"
                  :disabled="isOfflineOnly('STREAM_ALLOWED_USERS')"
                />
              </el-form-item>
              <el-form-item label="自动下载兼容开关">
                <el-switch v-model="configs.stream.STREAM_AUTO_DOWNLOAD" />
                <div class="el-form-item__help">
                  TG网盘媒体不会本地下载；此开关仅保留给旧直链流程。
                </div>
              </el-form-item>
              <el-form-item label="发送直链信息给用户">
                <el-switch v-model="configs.stream.SEND_STREAM_LINK" />
              </el-form-item>
              <el-form-item label="消息最大并发处理数">
                <el-input-number v-model="configs.stream.MAX_CONCURRENT_MESSAGES" :min="1" :max="100" style="width: 100%" />
              </el-form-item>
              <el-form-item label="消息等待队列上限">
                <el-input-number v-model="configs.stream.MAX_MESSAGE_QUEUE_SIZE" :min="10" :max="5000" style="width: 100%" />
              </el-form-item>
              <el-form-item label="多机器人Token列表">
                <el-input
                  v-model="multiBotTokensText"
                  type="textarea"
                  :rows="4"
                  placeholder="新增 Token，每行一个或逗号分隔"
                />
                <div class="el-form-item__help">
                  {{ secretStatus('MULTI_BOT_TOKENS') }}
                </div>
              </el-form-item>
            </el-form>

            <!-- 频道入库无痕洗白与智能归属改写面板 -->
            <div class="bot-cluster-card rebrand-config-card mt-6">
              <div class="cluster-card-header">
                <div class="flex items-center gap-2">
                  <div class="cluster-icon-pill">
                    <el-icon><Brush /></el-icon>
                  </div>
                  <div>
                    <h4 class="cluster-title">频道入库无痕洗白与智能归属改写</h4>
                    <p class="cluster-desc">
                      抹除用户转发的外部来源标，自动清洗第三方引流广告、替换为本频道落款与净化网盘文件名
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <el-button size="small" type="primary" @click="saveConfig('stream')" :loading="saving">
                    保存洗白策略
                  </el-button>
                </div>
              </div>

              <el-form :model="configs.stream" label-width="180px" class="modern-form mt-4">
                <el-form-item label="启用无痕洗白">
                  <el-switch v-model="configs.stream.FORWARD_REBRAND_ENABLED" />
                  <div class="el-form-item__help">
                    开启后使用 Telegram 无痕 Copy 发布，彻底抹除顶部的“转发自 XXX”来源标，并清洗配文。
                  </div>
                </el-form-item>

                <el-form-item label="归属目标频道">
                  <el-input
                    v-model="configs.stream.FORWARD_TARGET_CHANNEL"
                    placeholder="例如: @jiuyue1314520 （留空则自动使用主控嗅探到的公开频道标识）"
                  />
                  <div class="el-form-item__help">
                    所有第三方 @username 与 t.me 链接将自动替换为该频道标识。
                  </div>
                </el-form-item>

                <el-form-item label="配文落款签名">
                  <el-input
                    v-model="configs.stream.FORWARD_CHANNEL_SIGNATURE"
                    placeholder="例如: 📢 关注官方频道: {channel}"
                  />
                  <div class="el-form-item__help">
                    自动追加在频道消息配文末尾（支持 {channel} 与 {url} 占位符，自动防重复追加）。
                  </div>
                </el-form-item>

                <el-form-item label="净化网盘文件名">
                  <el-switch v-model="configs.stream.FORWARD_CLEAN_FILENAMES" />
                  <div class="el-form-item__help">
                    入库时自动剔除文件名中的第三方引流后缀（如 电报TG@xxx、tg搜@xxx），严格保留原始格式与集数编号。
                  </div>
                </el-form-item>

                <el-form-item label="自定义替换/剔除规则">
                  <el-input
                    v-model="configs.stream.FORWARD_CUSTOM_REPLACE_RULES"
                    type="textarea"
                    :rows="3"
                    placeholder="每行一条，支持 原词=>新词 或直接填写需剔除的广告词"
                  />
                  <div class="el-form-item__help">
                    支持“原词=>替换词”定向改写，或直接填写词条整词剔除。
                  </div>
                </el-form-item>
              </el-form>

              <!-- 实时洗白效果交互预览框 -->
              <div class="rebrand-preview-box mt-4">
                <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
                  <div class="flex items-center gap-1.5 font-semibold text-sm text-slate-700">
                    <el-icon><View /></el-icon>
                    <span>实时清洗效果交互预览</span>
                  </div>
                  <el-button size="small" type="primary" plain @click="runRebrandPreview" :loading="previewLoading">
                    测试预览
                  </el-button>
                </div>
                <div class="rebrand-preview-grid">
                  <div class="preview-col">
                    <div class="preview-col-label">测试输入（原始配文 &amp; 文件名）</div>
                    <el-input
                      v-model="previewInput.caption"
                      type="textarea"
                      :rows="2"
                      placeholder="测试配文，例如：精彩热门视频 电报TG@yijiqwq 关注 @other_bot https://t.me/other"
                    />
                    <el-input
                      v-model="previewInput.filename"
                      size="small"
                      class="mt-2"
                      placeholder="测试文件名，例如：电报TG@yijiqwq 棒棒糖 (1).mp4"
                    />
                  </div>
                  <div class="preview-col">
                    <div class="preview-col-label">清洗输出预览（洗白后结果）</div>
                    <div class="preview-output-caption">
                      {{ previewOutput.caption || '（点击右上方【测试预览】查看配文洗白与落款效果）' }}
                    </div>
                    <div class="preview-output-filename mt-2">
                      📁 {{ previewOutput.filename || '（净化后文件名）' }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 多 Bot 负载均衡与免加频道状态诊断卡片 -->
            <div class="bot-cluster-card mt-6">
              <div class="cluster-card-header">
                <div class="flex items-center gap-2">
                  <div class="cluster-icon-pill">
                    <el-icon><Cpu /></el-icon>
                  </div>
                  <div>
                    <h4 class="cluster-title">多 Bot 集群与免加频道状态诊断</h4>
                    <p class="cluster-desc">
                      共 {{ serverStatus?.bot_details?.length || 1 }} 个节点 ·
                      流播分流就绪 {{ serverStatus?.channel_info?.accessible_bots || 1 }} 个 ·
                      上传写权限 {{ serverStatus?.channel_info?.write_bots || 1 }} 个
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <el-button size="small" type="primary" plain @click="openHotAddDialog">
                    + 快速热添加 Token
                  </el-button>
                  <el-button size="small" type="success" @click="openBotFatherDialog">
                    ⚡ API协议号自动创机
                  </el-button>
                  <el-button size="small" :icon="Refresh" circle @click="fetchServerStatus" :loading="loadingServerStatus" title="刷新状态" />
                </div>
              </div>

              <!-- 提示横幅 -->
              <div v-if="serverStatus?.channel_info?.no_join_balancing_active" class="cluster-banner banner-success">
                <span class="banner-icon">🎉</span>
                <span class="banner-text">
                  频道已检测到公开标识符（<strong>@{{ serverStatus.channel_info.public_handle }}</strong>），所有 Worker 机器人无需人工加入频道，已自动激活免加频道负载均衡与多 DC 满速分流！
                </span>
              </div>
              <div v-else-if="serverStatus?.channel_info?.channel_type === 'private' && hasUnreachableBots" class="cluster-banner banner-warning">
                <span class="banner-icon">💡</span>
                <span class="banner-text">
                  检测到私密频道存在未激活从节点。建议在 Telegram 频道设置中配置一个公开用户名（如 @xxx）或绑定公开讨论组，所有从机器人将全自动免加频道就绪；亦可点击下方【一键加管】快速授权。
                </span>
              </div>

              <!-- 节点网格 -->
              <div v-if="serverStatus?.bot_details && serverStatus.bot_details.length > 0" class="bot-node-grid">
                <div v-for="bot in displayedSettingsBots" :key="bot.index" class="bot-node-card">
                  <div class="node-card-top">
                    <div class="flex items-center gap-2 overflow-hidden">
                      <span class="node-name font-mono font-semibold">{{ bot.name }}</span>
                      <span class="node-username text-xs text-slate-500 truncate" :title="bot.username">{{ bot.username }}</span>
                    </div>
                    <div class="flex items-center gap-1.5">
                      <span :class="['node-badge', getBotModeBadge(bot).cls]">
                        {{ getBotModeBadge(bot).label }}
                      </span>
                      <el-button
                        v-if="bot.index !== 0"
                        size="small"
                        type="danger"
                        link
                        :icon="Delete"
                        title="下线并移除该节点"
                        @click="handleRemoveBot(bot)"
                      />
                    </div>
                  </div>

                  <div class="node-caps-row">
                    <span class="cap-tag" :class="bot.can_read ? 'cap-ok' : 'cap-no'">
                      {{ bot.can_read ? '✓ 流播分流' : '✗ 无法分流' }}
                    </span>
                    <span class="cap-tag" :class="bot.can_write ? 'cap-ok' : 'cap-readonly'">
                      {{ bot.can_write ? '✓ 上传/删帖' : '只读分流' }}
                    </span>
                    <span class="cap-load text-xs text-slate-500 ml-auto">
                      负载: {{ bot.active_requests }}
                    </span>
                  </div>

                  <div v-if="!bot.can_read && bot.invite_url" class="node-action-row mt-2">
                    <el-button
                      size="small"
                      type="warning"
                      plain
                      class="w-full"
                      tag="a"
                      :href="bot.invite_url"
                      target="_blank"
                    >
                      一键加管授权
                    </el-button>
                  </div>
                </div>
              </div>
              <div v-if="(serverStatus?.bot_details?.length || 0) > 12" class="flex items-center justify-between flex-wrap gap-2 mt-4 pt-3 border-t border-slate-200/60 text-xs text-slate-500">
                <span>
                  当前展示 {{ displayedSettingsBots.length }} / {{ serverStatus?.bot_details?.length }} 个集群节点
                </span>
                <div class="flex items-center gap-2">
                  <el-button size="small" text type="primary" @click="showAllBotsInSettings = !showAllBotsInSettings">
                    {{ showAllBotsInSettings ? '收起折叠节点' : `展开全部 ${serverStatus?.bot_details?.length} 个节点` }}
                  </el-button>
                  <el-button size="small" plain @click="router.push('/bots')">
                    前往 Bot 集群监控专页 (/bots)
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- 6. 容器管理 (兼容 admin-container-status.spec.ts) -->
        <el-tab-pane name="container" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><Box /></el-icon>
              <span>容器管理</span>
            </span>
          </template>

          <div v-if="activeTab === 'container'" class="tab-pane-content">
            <el-row :gutter="20">
              <!-- 左侧: 容器状态 -->
              <el-col :xs="24" :lg="12">
                <el-card shadow="hover" class="container-info-card mb-6">
                  <template #header>
                    <div class="card-header">
                      <div class="flex items-center gap-2">
                        <el-icon class="text-primary"><Box /></el-icon>
                        <span class="font-bold">Docker容器状态</span>
                      </div>
                      <el-button
                        :icon="Refresh"
                        circle
                        size="small"
                        @click="fetchDockerStatus"
                        :loading="loadingStatus"
                        title="刷新容器状态"
                      />
                    </div>
                  </template>

                  <el-skeleton v-if="loadingStatus" :rows="6" animated />

                  <div v-else-if="dockerStatus" class="container-status-details">
                    <el-descriptions :column="1" border size="small" class="modern-descriptions">
                      <el-descriptions-item label="运行环境">
                        <el-tag :type="dockerStatus.in_docker ? 'success' : 'info'" size="small">
                          {{ dockerStatus.in_docker ? 'Docker容器内' : '非Docker环境' }}
                        </el-tag>
                      </el-descriptions-item>
                      <el-descriptions-item label="容器名称">
                        <span class="font-mono font-semibold text-slate-800">{{ dockerStatus.container_name || '-' }}</span>
                      </el-descriptions-item>
                      <el-descriptions-item label="运行状态">
                        <el-tag :type="getStatusType(dockerStatus.status)" size="small">
                          {{ dockerStatus.status || '-' }}
                        </el-tag>
                      </el-descriptions-item>
                      <el-descriptions-item label="镜像名称">
                        <span class="font-mono text-xs text-slate-600">{{ dockerStatus.image || '-' }}</span>
                      </el-descriptions-item>
                      <el-descriptions-item label="状态来源">
                        <span class="badge-source">{{ dockerStatus.status_source === 'docker' ? 'Docker API' : '应用自检' }}</span>
                      </el-descriptions-item>
                      <el-descriptions-item label="应用版本">
                        <span class="font-mono font-bold text-primary">{{ dockerStatus.application_version || '-' }}</span>
                      </el-descriptions-item>
                      <el-descriptions-item label="创建时间">
                        <span class="text-slate-500 font-mono text-xs">{{ formatDate(dockerStatus.created) }}</span>
                      </el-descriptions-item>
                    </el-descriptions>

                    <div v-if="dockerStatus.error" class="mt-4">
                      <el-alert
                        :title="dockerStatus.error"
                        type="warning"
                        :closable="false"
                      />
                    </div>
                  </div>

                  <el-empty v-else description="无法获取容器状态" />
                </el-card>
              </el-col>

              <!-- 右侧: 容器控制 -->
              <el-col :xs="24" :lg="12">
                <el-card shadow="hover" class="container-ctrl-card mb-6">
                  <template #header>
                    <div class="flex items-center gap-2">
                      <el-icon class="text-primary"><RefreshRight /></el-icon>
                      <span class="font-bold">容器控制</span>
                    </div>
                  </template>

                  <div class="control-actions">
                    <p class="text-sm text-slate-500 mb-4">
                      重载 MistRelay 宿主容器。当检测到外部 Docker Socket 挂载时支持优雅热重启。
                    </p>

                    <el-button
                      type="primary"
                      :icon="RefreshRight"
                      @click="handleRestart"
                      :loading="restarting"
                      :disabled="!dockerStatus?.control_enabled"
                      block
                      size="large"
                      class="restart-container-btn"
                    >
                      重启容器（热重载）
                    </el-button>

                    <el-alert
                      v-if="dockerStatus && !dockerStatus.control_enabled"
                      :title="dockerStatus.control_message || '宿主 Docker 控制未启用'"
                      type="info"
                      :closable="false"
                      class="mt-4 modern-alert"
                    />

                    <div v-if="restartMessage" class="mt-4">
                      <el-alert
                        :title="restartMessage"
                        :type="restartSuccess ? 'success' : 'error'"
                        :closable="true"
                        @close="restartMessage = ''"
                      />
                    </div>
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <!-- 容器日志 -->
            <el-card shadow="hover" class="container-logs-card">
              <template #header>
                <div class="flex justify-between items-center flex-wrap gap-2">
                  <div class="flex items-center gap-2">
                    <el-icon class="text-primary"><Document /></el-icon>
                    <span class="font-bold">容器日志</span>
                    <span v-if="wsConnected" class="stream-live-pill">
                      <span class="stream-dot"></span> LIVE 流式传输中
                    </span>
                  </div>
                  <div class="flex gap-2 items-center flex-wrap">
                    <el-select
                      v-model="dockerLogLines"
                      @change="handleDockerLogLinesChange"
                      style="width: 110px"
                      size="small"
                      :disabled="wsConnected"
                    >
                      <el-option label="50 行" :value="50" />
                      <el-option label="100 行" :value="100" />
                      <el-option label="200 行" :value="200" />
                      <el-option label="500 行" :value="500" />
                    </el-select>
                    <el-button
                      v-if="!wsConnected"
                      :icon="VideoPlay"
                      circle
                      size="small"
                      @click="startLogStream"
                      :loading="connecting"
                      title="开始实时日志"
                    />
                    <el-button
                      v-else
                      :icon="VideoPause"
                      circle
                      size="small"
                      type="danger"
                      @click="stopLogStream"
                      title="停止实时日志"
                    />
                    <el-button
                      :icon="Refresh"
                      circle
                      size="small"
                      @click="fetchDockerLogs"
                      :loading="loadingDockerLogs"
                      :disabled="wsConnected"
                      title="刷新日志"
                    />
                    <el-button
                      :icon="Delete"
                      circle
                      size="small"
                      @click="clearDockerLogs"
                      title="清空日志"
                    />
                  </div>
                </div>
              </template>

              <el-skeleton v-if="loadingDockerLogs && !wsConnected" :rows="10" animated />

              <div v-else class="logs-container" ref="dockerLogsContainerRef">
                <pre class="logs-content">{{ dockerLogs }}</pre>
              </div>

              <el-empty v-if="!dockerLogs && !wsConnected" description="无法获取容器日志" />
            </el-card>
          </div>
        </el-tab-pane>

        <!-- 7. 系统日志 -->
        <el-tab-pane name="app-logs" lazy>
          <template #label>
            <span class="tab-label-item">
              <el-icon><Document /></el-icon>
              <span>系统日志</span>
            </span>
          </template>

          <div v-if="activeTab === 'app-logs'" class="tab-pane-content">
            <!-- 工具栏卡片 -->
            <el-card shadow="hover" class="mb-4 app-logs-toolbar-card">
              <div class="toolbar">
                <div class="toolbar-left">
                  <el-select
                    v-model="selectedFile"
                    placeholder="当前日志"
                    clearable
                    style="width: 200px"
                    size="default"
                    @change="fetchAppLogs"
                  >
                    <el-option
                      v-for="f in logFiles"
                      :key="f.name"
                      :label="`${f.name} (${formatSize(f.size)})`"
                      :value="f.name"
                    />
                  </el-select>

                  <el-select
                    v-model="levelFilter"
                    placeholder="全部级别"
                    clearable
                    style="width: 120px"
                    size="default"
                    @change="fetchAppLogs"
                  >
                    <el-option label="ERROR" value="ERROR" />
                    <el-option label="WARNING" value="WARNING" />
                    <el-option label="INFO" value="INFO" />
                    <el-option label="DEBUG" value="DEBUG" />
                  </el-select>

                  <el-input
                    v-model="keyword"
                    placeholder="关键词搜索"
                    clearable
                    style="width: 180px"
                    size="default"
                    @keyup.enter="fetchAppLogs"
                    @clear="fetchAppLogs"
                  >
                    <template #prefix>
                      <el-icon><Search /></el-icon>
                    </template>
                  </el-input>

                  <el-select
                    v-model="tailCount"
                    style="width: 130px"
                    size="default"
                    @change="fetchAppLogs"
                  >
                    <el-option label="最新 100 行" :value="100" />
                    <el-option label="最新 200 行" :value="200" />
                    <el-option label="最新 500 行" :value="500" />
                    <el-option label="最新 1000 行" :value="1000" />
                  </el-select>
                </div>

                <div class="toolbar-right">
                  <el-button
                    :icon="Refresh"
                    circle
                    size="default"
                    @click="fetchAppLogs"
                    :loading="loadingAppLogs"
                    title="刷新"
                  />
                  <el-button
                    :icon="Download"
                    circle
                    size="default"
                    @click="handleDownload"
                    :disabled="!currentFileName"
                    title="下载日志文件"
                  />
                  <el-button
                    :icon="Delete"
                    circle
                    size="default"
                    @click="clearAppLogDisplay"
                    title="清空显示"
                  />
                </div>
              </div>
            </el-card>

            <!-- 日志文件折叠卡片 -->
            <el-card shadow="hover" class="mb-4" v-if="logFiles.length > 0">
              <template #header>
                <div class="flex justify-between items-center">
                  <span class="font-semibold text-slate-700">磁盘日志文件档案 ({{ logFiles.length }})</span>
                  <el-button text size="small" @click="showFileList = !showFileList">
                    {{ showFileList ? '收起' : '展开' }}
                  </el-button>
                </div>
              </template>
              <div v-if="showFileList">
                <!-- 移动端日志文件卡片流 -->
                <div class="mobile-log-files md:hidden flex flex-col gap-2">
                  <div
                    v-for="file in logFiles"
                    :key="file.name"
                    class="p-2.5 rounded-xl border border-pink-100/70 bg-white/80 shadow-sm flex items-center justify-between gap-2"
                  >
                    <div class="flex flex-col min-w-0">
                      <span class="text-xs font-mono font-medium text-slate-800 truncate" :title="file.name">{{ file.name }}</span>
                      <span class="text-[11px] text-slate-400 font-mono">{{ formatSize(file.size) }} · {{ file.modified }}</span>
                    </div>
                    <el-button text size="small" type="primary" class="shrink-0" @click="viewFile(file.name)">查看</el-button>
                  </div>
                </div>

                <!-- 桌面端日志文件表格 -->
                <div class="hidden md:block">
                  <el-table :data="logFiles" size="small" stripe class="custom-log-files-table">
                    <el-table-column prop="name" label="文件名" />
                    <el-table-column label="大小" width="120">
                      <template #default="{ row }">{{ formatSize(row.size) }}</template>
                    </el-table-column>
                    <el-table-column prop="modified" label="最后修改" width="180" />
                    <el-table-column label="操作" width="100">
                      <template #default="{ row }">
                        <el-button text size="small" type="primary" @click="viewFile(row.name)">查看</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </div>
            </el-card>

            <!-- 终端日志内容 -->
            <el-card shadow="hover" class="app-logs-viewer-card">
              <template #header>
                <div class="flex justify-between items-center">
                  <span class="font-bold flex items-center gap-2">
                    <span>运行日志输出</span>
                    <el-tag size="small" type="info" class="ml-2 font-mono" v-if="appLogLines.length">
                      {{ appLogLines.length }} 行
                    </el-tag>
                  </span>
                  <el-switch v-model="autoScroll" active-text="自动贴底滚动" inactive-text="" size="small" />
                </div>
              </template>

              <el-skeleton v-if="loadingAppLogs" :rows="12" animated />

              <div
                v-else-if="appLogLines.length > 0"
                class="logs-container app-logs-container"
                ref="appLogsContainerRef"
              >
                <div v-for="(line, idx) in appLogLines" :key="idx" :class="['log-line', getLineClass(line)]">
                  <span class="line-no">{{ idx + 1 }}</span>
                  <span class="line-content">{{ line }}</span>
                </div>
              </div>

              <el-empty v-else description="暂无日志数据" />
            </el-card>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 快速热添加 Bot Token 弹窗 -->
    <el-dialog
      v-model="showHotAddDialog"
      destroy-on-close
      title="快速热添加负载机器人 Token"
      width="520px"
      append-to-body
    >
      <div class="space-y-4">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="零停机热插拔：提交后立即在运行期初始化连接、完成免加频道 Peer 解析并纳入负载均衡池，无需重启容器。"
        />
        <el-input
          v-model="hotAddTokensText"
          type="textarea"
          :rows="5"
          placeholder="每行粘贴一个 Bot Token（或用逗号分隔），例如：&#10;1234567890:AAHxyz...&#10;9876543210:BBGabc..."
        />
      </div>
      <template #footer>
        <el-button @click="showHotAddDialog = false">取消</el-button>
        <el-button type="primary" :loading="submittingHotAdd" @click="handleHotAddSubmit">
          立即热挂载入网
        </el-button>
      </template>
    </el-dialog>

    <!-- API 协议号一键自动创机与入网向导弹窗 -->
    <el-dialog
      v-model="showBotFatherDialog"
      destroy-on-close
      title="API 协议号一键批量创机与入网 (@BotFather 流水线)"
      width="600px"
      append-to-body
    >
      <div class="space-y-4">
        <el-alert
          type="success"
          :closable="false"
          show-icon
          title="全生态协议号支持：兼容 Pyrogram 与 Telethon 的 Session String 及 .session 文件。仅在内存临时连接 @BotFather，任务完成后自动销毁会话。"
        />

        <el-radio-group v-model="botFatherInputMode" size="default" class="w-full">
          <el-radio-button value="string">粘贴 Session String 文本</el-radio-button>
          <el-radio-button value="file">上传 .session 协议号文件</el-radio-button>
        </el-radio-group>

        <div v-if="botFatherInputMode === 'string'">
          <el-input
            v-model="botFatherSessionString"
            type="textarea"
            :rows="3"
            placeholder="请粘贴 Pyrogram 或 Telethon 导出的 Session String 文本..."
          />
        </div>
        <div v-else class="session-upload-box">
          <input
            type="file"
            accept=".session"
            @change="onSessionFileChange"
            class="block w-full text-sm text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-sky-50 file:text-sky-700 hover:file:bg-sky-100"
          />
          <p v-if="botFatherSelectedFile" class="text-xs text-emerald-600 mt-2 font-medium">
            已选择协议号文件: {{ botFatherSelectedFile.name }} ({{ (botFatherSelectedFile.size / 1024).toFixed(1) }} KB)
          </p>
        </div>

        <el-form label-width="140px" size="default" class="mt-2">
          <el-form-item label="目标扩容节点数">
            <el-slider v-model="botFatherCount" :min="1" :max="20" show-input class="w-full" />
          </el-form-item>
          <el-form-item label="机器人名称前缀">
            <el-input v-model="botFatherPrefix" placeholder="MistRelay Node" />
          </el-form-item>
          <el-form-item label="存量机器人复用">
            <el-switch
              v-model="botFatherReuse"
              active-text="优先探测并直接提取该协议号下已有的 Bot Token（省时高效）"
            />
          </el-form-item>
        </el-form>

        <!-- 运行进度或结果反馈 -->
        <div v-if="submittingBotFather" class="p-3 rounded-xl bg-sky-50 border border-sky-200 text-sky-800 text-xs space-y-1">
          <div class="font-semibold">🚀 正在执行自动化创机流水线，请稍候（每个新机器人约需 2~3 秒）...</div>
          <div>① 解析协议号内存会话 ➔ ② 对话 @BotFather 探测/创建 ➔ ③ 提取 Token 并激活免加频道分流</div>
        </div>

        <div v-if="botFatherResult" class="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs space-y-1.5">
          <div class="font-bold text-sm">
            ✅ 流水线执行完毕：复用存量 {{ botFatherResult.reused_count }} 个 · 新建签发 {{ botFatherResult.created_count }} 个 · 当前活跃从节点 {{ botFatherResult.total_active_workers }} 个
          </div>
          <div v-if="botFatherResult.bots?.length" class="flex flex-wrap gap-1.5 pt-1">
            <span
              v-for="b in botFatherResult.bots"
              :key="b.index"
              class="px-2 py-0.5 rounded bg-white border border-emerald-300 font-mono text-xs"
            >
              Bot {{ b.index }} (@{{ b.username }})
            </span>
          </div>
          <div v-if="botFatherResult.errors?.length" class="text-amber-700 pt-1">
            <div v-for="(err, idx) in botFatherResult.errors" :key="idx">⚠️ {{ err }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showBotFatherDialog = false">关闭</el-button>
        <el-button type="success" :loading="submittingBotFather" @click="handleBotFatherSubmit">
          启动全自动创机并入网
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  downloadLogFile,
  getConfig,
  updateConfig,
  getStatus,
  getDockerStatus,
  restartDocker,
  getDockerLogs,
  getLogFiles,
  getLogContent,
  hotAddBots,
  hotRemoveBot,
  botfatherAutoCreate,
  previewRebrand,
  testAria2Rpc,
  type Aria2TestResponse,
  type LogFile
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import { checkServerConnection } from '@/utils/connection'
import { getServerBaseUrl, isValidServerBaseUrl, setServerBaseUrl } from '@/utils/runtime'
import {
  Refresh,
  RefreshRight,
  VideoPlay,
  VideoPause,
  Delete,
  Download,
  Search,
  Link,
  Promotion,
  Cpu,
  Box,
  Document,
  Brush,
  View
} from '@element-plus/icons-vue'
import type { DockerStatus, ServerStatus } from '@/types/api'
import { formatDate } from '@/utils/formatters'
import { buildWsProtocols, buildWsUrl } from '@/utils/websocket'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

type SettingsTab = 'client' | 'telegram' | 'download' | 'aria2' | 'stream' | 'container' | 'app-logs'
const validTabs: SettingsTab[] = ['client', 'telegram', 'download', 'aria2', 'stream', 'container', 'app-logs']
const initialTab =
  typeof route.query.tab === 'string' && validTabs.includes(route.query.tab as SettingsTab)
    ? (route.query.tab as SettingsTab)
    : 'client'
const activeTab = ref<SettingsTab>(initialTab)
const serverStatus = shallowRef<ServerStatus | null>(null)
const loadingServerStatus = ref(false)

async function fetchServerStatus() {
  loadingServerStatus.value = true
  try {
    serverStatus.value = await getStatus()
  } catch (e) {
    console.error('获取系统状态与Bot集群信息失败', e)
  } finally {
    loadingServerStatus.value = false
  }
}

const hasUnreachableBots = computed(() => {
  return serverStatus.value?.bot_details?.some(b => !b.can_read) ?? false
})

// 多 Bot 热插拔与 @BotFather 自动化流水线状态
const showHotAddDialog = ref(false)
const hotAddTokensText = ref('')
const submittingHotAdd = ref(false)

const showBotFatherDialog = ref(false)
const botFatherInputMode = ref<'string' | 'file'>('string')
const botFatherSessionString = ref('')
const botFatherSelectedFile = ref<File | null>(null)
const botFatherCount = ref(3)
const botFatherPrefix = ref('MistRelay Node')
const botFatherReuse = ref(true)
const submittingBotFather = ref(false)
const botFatherResult = ref<any>(null)

function openHotAddDialog() {
  hotAddTokensText.value = ''
  showHotAddDialog.value = true
}

function openBotFatherDialog() {
  botFatherResult.value = null
  showBotFatherDialog.value = true
}

function onSessionFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    botFatherSelectedFile.value = input.files[0]
  } else {
    botFatherSelectedFile.value = null
  }
}

async function handleHotAddSubmit() {
  const raw = hotAddTokensText.value.trim()
  if (!raw) {
    ElMessage.warning('请至少输入一个有效的 Bot Token')
    return
  }
  submittingHotAdd.value = true
  try {
    const res = await hotAddBots(raw)
    if (res.success && res.data) {
      const addedCount = res.data.total_added || 0
      const errCount = res.data.errors?.length || 0
      if (addedCount > 0) {
        ElMessage.success(`成功热挂载 ${addedCount} 个机器人节点` + (errCount > 0 ? `（${errCount} 个失败）` : ''))
        showHotAddDialog.value = false
        await fetchServerStatus()
        await fetchConfigs()
      } else if (errCount > 0) {
        ElMessage.error(`挂载失败: ${res.data.errors[0]}`)
      }
    } else {
      ElMessage.error(res.error || '热挂载失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '请求失败')
  } finally {
    submittingHotAdd.value = false
  }
}

async function handleRemoveBot(bot: any) {
  if (!bot || bot.index === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要将节点 ${bot.name} (${bot.username}) 下线并从负载均衡池移除吗？`,
      '移除负载节点',
      { type: 'warning', confirmButtonText: '确认移除', cancelButtonText: '取消' }
    )
    const res = await hotRemoveBot(bot.index)
    if (res.success) {
      ElMessage.success(`节点 ${bot.name} 已安全下线并移除`)
      await fetchServerStatus()
      await fetchConfigs()
    } else {
      ElMessage.error(res.error || '移除失败')
    }
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || e?.message || '移除失败')
    }
  }
}

async function handleBotFatherSubmit() {
  if (botFatherInputMode.value === 'string' && !botFatherSessionString.value.trim()) {
    ElMessage.warning('请粘贴有效的 Session String 文本')
    return
  }
  if (botFatherInputMode.value === 'file' && !botFatherSelectedFile.value) {
    ElMessage.warning('请选择要上传的 .session 协议号文件')
    return
  }

  submittingBotFather.value = true
  botFatherResult.value = null
  try {
    let res
    if (botFatherInputMode.value === 'file' && botFatherSelectedFile.value) {
      const fd = new FormData()
      fd.append('session_file', botFatherSelectedFile.value)
      fd.append('count', String(botFatherCount.value))
      fd.append('name_prefix', botFatherPrefix.value || 'MistRelay Node')
      fd.append('reuse_existing', String(botFatherReuse.value))
      res = await botfatherAutoCreate(fd)
    } else {
      res = await botfatherAutoCreate({
        session_string: botFatherSessionString.value.trim(),
        count: botFatherCount.value,
        name_prefix: botFatherPrefix.value || 'MistRelay Node',
        reuse_existing: botFatherReuse.value,
      })
    }

    if (res.success && res.data) {
      botFatherResult.value = res.data
      const totalGot = (res.data.reused_count || 0) + (res.data.created_count || 0)
      if (totalGot > 0) {
        ElMessage.success(`自动创机流水线成功！共接入 ${totalGot} 个负载机器人`)
        await fetchServerStatus()
        await fetchConfigs()
      } else {
        ElMessage.warning('流水线执行完成，但未新增可用机器人，请查看详情提示')
      }
    } else {
      ElMessage.error(res.error || '自动创机流水线执行失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '自动创机请求失败')
  } finally {
    submittingBotFather.value = false
  }
}

function getBotModeBadge(bot: any) {
  if (!bot) return { label: '就绪', cls: 'badge-ready' }
  switch (bot.mode) {
    case 'primary_admin':
      return { label: '主控 (管理员)', cls: 'badge-primary' }
    case 'direct_admin':
      return { label: '频道管理员', cls: 'badge-admin' }
    case 'no_join_resolved':
      return { label: '免加频道就绪', cls: 'badge-nojoin' }
    case 'unreachable':
      return { label: '未激活 (私密)', cls: 'badge-unreachable' }
    default:
      return { label: '就绪', cls: 'badge-ready' }
  }
}

const saving = ref(false)
const clientServerUrl = ref(getServerBaseUrl())
const testingConnection = ref(false)
const savingClientConnection = ref(false)
const connectionState = ref<'idle' | 'success' | 'error'>('idle')
const connectionStatusText = ref('')
const configCategories = ['telegram', 'download', 'aria2', 'stream'] as const
type ConfigCategory = typeof configCategories[number]
const redactedKeys = ref(new Set<string>())
const offlineOnlyKeys = ref(new Set<string>())
const secretCounts = ref<Record<string, number>>({})

function isOfflineOnly(key: string): boolean {
  return offlineOnlyKeys.value.has(key)
}

function secretStatus(key: string): string {
  if (key === 'MULTI_BOT_TOKENS' && secretCounts.value[key]) {
    return `已配置 ${secretCounts.value[key]} 个`
  }
  return redactedKeys.value.has(key) ? '已配置' : '未配置'
}

const effectiveServerUrlLabel = computed(() => clientServerUrl.value || '同源 /api')
const connectionStatusLabel = computed(() => {
  if (connectionState.value === 'success') return '已连接'
  if (connectionState.value === 'error') return '不可用'
  return '未检测'
})
const connectionStatusTagType = computed(() => {
  if (connectionState.value === 'success') return 'success'
  if (connectionState.value === 'error') return 'danger'
  return 'info'
})
const connectionStatusDotClass = computed(() => {
  if (connectionState.value === 'success') return 'connection-dot--success'
  if (connectionState.value === 'error') return 'connection-dot--error'
  return 'connection-dot--idle'
})

const pendingRestartWarning = ref(false)
const pendingRestartMessage = ref('')
const showAllBotsInSettings = ref(false)
const testingAria2 = ref(false)
const aria2TestResult = ref<Aria2TestResponse | null>(null)

const displayedSettingsBots = computed(() => {
  const list = serverStatus.value?.bot_details || []
  if (showAllBotsInSettings.value || list.length <= 12) {
    return list
  }
  return list.slice(0, 12)
})

async function handleTestAria2() {
  testingAria2.value = true
  try {
    const res = await testAria2Rpc()
    aria2TestResult.value = res
    if (res.success && res.data) {
      ElMessage.success(`Aria2 RPC 连接正常 (v${res.data.version})`)
    } else {
      ElMessage.error(res.error || 'Aria2 RPC 连通测试失败')
    }
  } catch (e: any) {
    const errMsg = e?.response?.data?.error || e?.message || 'Aria2 RPC 连接失败'
    aria2TestResult.value = { success: false, error: errMsg }
    ElMessage.error(errMsg)
  } finally {
    testingAria2.value = false
  }
}

// 配置数据
const configs = ref({
  telegram: {
    API_ID: 0,
    API_HASH: '',
    BOT_TOKEN: '',
    ADMIN_ID: 0,
    UP_TELEGRAM: true,
    ALLOW_USER_REGISTRATION: true,
    DEFAULT_TENANT_DC_ID: 5,
    TENANT_CHANNEL_PREFIX: 'mr_u',
    PROTOCOL_KEEPALIVE_ENABLED: true,
    PROTOCOL_KEEPALIVE_INTERVAL_HOURS: 12,
    TELEGRAM_API_PROXY_URL: ''
  },
  download: {
    SAVE_PATH: '/data/downloads',
    PROXY_IP: '',
    PROXY_PORT: '',
    MAX_CONCURRENT_UPLOADS: 10,
    THUMBNAIL_CACHE_MAX_AGE_DAYS: 30,
    SKIP_SMALL_FILES: false,
    MIN_FILE_SIZE_MB: 100,
    DOWNLOAD_CLEANUP_ENABLED: true,
    DOWNLOAD_RETENTION_HOURS: 24,
    DOWNLOAD_CLEANUP_INTERVAL_SECONDS: 3600
  },
  aria2: {
    RPC_SECRET: '',
    RPC_URL: 'localhost:6800/jsonrpc'
  },
  stream: {
    ENABLE_STREAM: true,
    BIN_CHANNEL: '',
    STREAM_PORT: 8080,
    STREAM_BIND_ADDRESS: '0.0.0.0',
    STREAM_HASH_LENGTH: 6,
    STREAM_HAS_SSL: false,
    STREAM_NO_PORT: false,
    STREAM_FQDN: '127.0.0.1',
    STREAM_KEEP_ALIVE: false,
    STREAM_PING_INTERVAL: 1200,
    STREAM_USE_SESSION_FILE: false,
    STREAM_ALLOWED_USERS: '',
    STREAM_AUTO_DOWNLOAD: false,
    SEND_STREAM_LINK: false,
    MAX_CONCURRENT_MESSAGES: 5,
    MAX_MESSAGE_QUEUE_SIZE: 100,
    MULTI_BOT_TOKENS: [] as string[],
    FORWARD_REBRAND_ENABLED: true,
    FORWARD_TARGET_CHANNEL: '',
    FORWARD_CHANNEL_SIGNATURE: '',
    FORWARD_CLEAN_FILENAMES: true,
    FORWARD_CUSTOM_REPLACE_RULES: ''
  }
})

// 多机器人Token文本
const multiBotTokensText = computed({
  get: () => {
    const tokens = configs.value.stream.MULTI_BOT_TOKENS || []
    return tokens.join('\n')
  },
  set: (val: string) => {
    updateMultiBotTokens(val)
  }
})

const previewInput = ref({
  caption: '精彩热门视频 电报TG@yijiqwq 欢迎关注 @other_bot https://t.me/other 获取更多！',
  filename: '电报TG@yijiqwq 棒棒糖 (1).mp4'
})
const previewOutput = ref({
  caption: '',
  filename: ''
})
const previewLoading = ref(false)

async function runRebrandPreview() {
  previewLoading.value = true
  try {
    const res = await previewRebrand({
      caption: previewInput.value.caption,
      filename: previewInput.value.filename,
      target_channel: configs.value.stream.FORWARD_TARGET_CHANNEL,
      signature: configs.value.stream.FORWARD_CHANNEL_SIGNATURE,
      clean_filenames: configs.value.stream.FORWARD_CLEAN_FILENAMES,
      custom_rules: configs.value.stream.FORWARD_CUSTOM_REPLACE_RULES
    })
    if (res.success && res.data) {
      previewOutput.value.caption = res.data.cleaned_caption
      previewOutput.value.filename = res.data.cleaned_filename
      ElMessage.success('已完成试运行清洗预览')
    } else {
      ElMessage.error(res.error || '预览失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '预览请求失败')
  } finally {
    previewLoading.value = false
  }
}

function updateMultiBotTokens(text: string) {
  if (!text.trim()) {
    configs.value.stream.MULTI_BOT_TOKENS = []
    return
  }
  const tokens = text
    .split(/[,\n]/)
    .map(t => t.trim())
    .filter(t => t.length > 0)
  configs.value.stream.MULTI_BOT_TOKENS = tokens
}

// 表单验证规则
const rules = {
  API_ID: [{ required: true, message: '请输入API ID', trigger: 'blur' }],
  API_HASH: [{ required: true, message: '请输入API Hash', trigger: 'blur' }],
  BOT_TOKEN: [{ required: true, message: '请输入Bot Token', trigger: 'blur' }],
  ADMIN_ID: [{ required: true, message: '请输入管理员ID', trigger: 'blur' }]
}

async function testConnection(showMessage = true) {
  if (!isValidServerBaseUrl(clientServerUrl.value)) {
    connectionState.value = 'error'
    connectionStatusText.value = '服务器地址格式不正确'
    if (showMessage) {
      ElMessage.error(connectionStatusText.value)
    }
    return false
  }

  testingConnection.value = true
  try {
    const result = await checkServerConnection(clientServerUrl.value)
    connectionState.value = result.ok ? 'success' : 'error'
    connectionStatusText.value = result.message

    if (showMessage) {
      if (result.ok) {
        ElMessage.success(result.message)
      } else {
        ElMessage.error(result.message)
      }
    }

    return result.ok
  } finally {
    testingConnection.value = false
  }
}

async function saveClientConnection() {
  if (!isValidServerBaseUrl(clientServerUrl.value)) {
    ElMessage.error('服务器地址格式不正确')
    return
  }

  savingClientConnection.value = true
  try {
    const ok = await testConnection(false)
    if (!ok) {
      ElMessage.error(connectionStatusText.value || '服务器连接失败，未保存')
      return
    }

    const previousServerUrl = getServerBaseUrl()
    const nextServerUrl = setServerBaseUrl(clientServerUrl.value)

    if (nextServerUrl !== previousServerUrl) {
      authStore.logout()
      ElMessage.success('客户端连接已更新，请重新登录')
      router.push('/login')
      return
    }

    ElMessage.success('客户端连接已保存')
  } finally {
    savingClientConnection.value = false
  }
}

async function fetchConfigs() {
  try {
    const response = await getConfig()
    if (response.success && response.data) {
      redactedKeys.value = new Set(response.redacted_keys || [])
      offlineOnlyKeys.value = new Set(response.offline_only_keys || [])
      secretCounts.value = { ...(response.secret_counts || {}) }
      const data = response.data
      for (const category of configCategories) {
        const target = configs.value[category] as Record<string, any>
        for (const key of Object.keys(target)) {
          if (key in data) {
            target[key] = data[key]
          }
        }
      }
    }
  } catch (err) {
    console.error('获取配置失败:', err)
    ElMessage.error('获取配置失败')
  }
}

async function saveConfig(category: ConfigCategory) {
  saving.value = true
  try {
    const categoryConfig = configs.value[category]
    const response = await updateConfig(categoryConfig)

    if (response.success) {
      if (response.needs_restart) {
        pendingRestartWarning.value = true
        pendingRestartMessage.value = response.message || '配置已保存，需要重启容器后生效'
        ElMessage.warning({
          message: response.message || '配置已保存，但需要重启服务才能生效',
          duration: 5000
        })
      } else {
        ElMessage.success(response.message || '配置已保存，下次使用时将从数据库读取最新配置')
      }
      await fetchConfigs()
    } else {
      ElMessage.error(response.error || '配置保存失败')
    }
  } catch (err: any) {
    console.error('保存配置失败:', err)
    ElMessage.error(err.response?.data?.error || err.message || '配置保存失败')
  } finally {
    saving.value = false
  }
}

function reloadCurrentTab() {
  if (activeTab.value === 'container') {
    fetchDockerStatus()
    fetchDockerLogs()
  } else if (activeTab.value === 'app-logs') {
    fetchFileList().then(() => fetchAppLogs())
  } else {
    fetchConfigs()
    testConnection(false)
  }
  ElMessage.success('已刷新当前页面数据')
}

const dockerStatus = shallowRef<DockerStatus | null>(null)
const dockerLogs = ref<string>('')
const loadingStatus = ref(false)
const loadingDockerLogs = ref(false)
const restarting = ref(false)
const restartMessage = ref('')
const restartSuccess = ref(false)
const dockerLogLines = ref(100)
const wsConnected = ref(false)
const connecting = ref(false)
const ws = ref<WebSocket | null>(null)
const dockerLogsContainerRef = ref<HTMLElement | null>(null)

const logFiles = shallowRef<LogFile[]>([])
const appLogLines = shallowRef<string[]>([])
const loadingAppLogs = ref(false)
const showFileList = ref(false)
const autoScroll = ref(true)
const appLogsContainerRef = ref<HTMLElement | null>(null)
const selectedFile = ref<string>('')
const levelFilter = ref<string>('')
const keyword = ref<string>('')
const tailCount = ref<number>(200)
const currentFileName = ref<string>('')

function fetchDockerStatus() {
  loadingStatus.value = true
  getDockerStatus()
    .then(data => {
      dockerStatus.value = data
    })
    .catch(err => {
      console.error('获取Docker状态失败:', err)
      ElMessage.error('获取Docker状态失败')
    })
    .finally(() => {
      loadingStatus.value = false
    })
}

function stopLogStream() {
  if (ws.value) {
    ws.value.close()
    ws.value = null
  }
  wsConnected.value = false
  connecting.value = false
}

function startLogStream() {
  if (ws.value) {
    stopLogStream()
  }

  connecting.value = true
  const url = buildWsUrl('/api/system/docker/logs/ws', { tail: String(dockerLogLines.value) })

  try {
    ws.value = new WebSocket(url, buildWsProtocols())

    ws.value.onopen = () => {
      wsConnected.value = true
      connecting.value = false
      dockerLogs.value = ''
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'history') {
          dockerLogs.value = data.logs || ''
        } else if (data.type === 'log' || data.type === 'line') {
          dockerLogs.value += (dockerLogs.value ? '\n' : '') + (data.line || '')
          nextTick(() => {
            if (dockerLogsContainerRef.value) {
              dockerLogsContainerRef.value.scrollTop = dockerLogsContainerRef.value.scrollHeight
            }
          })
        } else if (data.type === 'error') {
          ElMessage.error(data.message || '日志流错误')
        }
      } catch (e) {
        console.error('解析WebSocket消息失败:', e)
      }
    }

    ws.value.onerror = (error) => {
      console.error('WebSocket错误:', error)
      ElMessage.error('日志流连接错误')
      connecting.value = false
      wsConnected.value = false
    }

    ws.value.onclose = () => {
      wsConnected.value = false
      connecting.value = false
    }
  } catch (e) {
    console.error('建立WebSocket连接失败:', e)
    ElMessage.error('无法建立日志流连接')
    connecting.value = false
  }
}

function handleDockerLogLinesChange() {
  if (wsConnected.value) {
    startLogStream()
  } else {
    fetchDockerLogs()
  }
}

function fetchDockerLogs() {
  loadingDockerLogs.value = true
  getDockerLogs(dockerLogLines.value)
    .then(data => {
      if (data.success) {
        dockerLogs.value = data.logs || ''
      } else {
        dockerLogs.value = ''
        ElMessage.warning(data.error || '无法获取日志')
      }
    })
    .catch(err => {
      console.error('获取Docker日志失败:', err)
      ElMessage.error('获取Docker日志失败')
      dockerLogs.value = ''
    })
    .finally(() => {
      loadingDockerLogs.value = false
    })
}

function clearDockerLogs() {
  dockerLogs.value = ''
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
}

function getLineClass(line: string): string {
  if (line.includes('| ERROR')) return 'log-error'
  if (line.includes('| WARNING')) return 'log-warn'
  if (line.includes('| DEBUG')) return 'log-debug'
  return ''
}

function scrollAppLogsToBottom() {
  if (!autoScroll.value) return
  nextTick(() => {
    if (appLogsContainerRef.value) {
      appLogsContainerRef.value.scrollTop = appLogsContainerRef.value.scrollHeight
    }
  })
}

async function fetchFileList() {
  try {
    const res = await getLogFiles()
    if (res.success) {
      logFiles.value = res.files
      if (res.files.length > 0 && !currentFileName.value) {
        currentFileName.value = res.files[0].name
      }
    }
  } catch (e: any) {
    console.error('获取日志文件列表失败:', e)
  }
}

async function fetchAppLogs() {
  loadingAppLogs.value = true
  try {
    const res = await getLogContent({
      file: selectedFile.value || undefined,
      tail: tailCount.value,
      level: levelFilter.value || undefined,
      keyword: keyword.value || undefined,
    })
    if (res.success) {
      appLogLines.value = res.lines
      currentFileName.value = selectedFile.value || (logFiles.value.length > 0 ? logFiles.value[0].name : '')
    } else {
      ElMessage.error(res.error || '获取日志失败')
    }
  } catch (e: any) {
    console.error('获取日志内容失败:', e)
    ElMessage.error('获取日志内容失败')
  } finally {
    loadingAppLogs.value = false
  }
}

function viewFile(name: string) {
  selectedFile.value = name
  fetchAppLogs()
}

async function handleDownload() {
  if (!currentFileName.value) return
  try {
    await downloadLogFile(currentFileName.value)
  } catch {
    ElMessage.error('下载日志失败')
  }
}

function clearAppLogDisplay() {
  appLogLines.value = []
}

function handleRestart() {
  if (!dockerStatus.value?.control_enabled) {
    ElMessage.warning(dockerStatus.value?.control_message || '宿主 Docker 控制未启用')
    return
  }

  ElMessageBox.confirm(
    '确定要重启Docker容器吗？重启后服务会短暂中断。',
    '确认重启',
    {
      confirmButtonText: '确定重启',
      cancelButtonText: '取消',
      type: 'warning',
      dangerouslyUseHTMLString: false
    }
  ).then(() => {
    restarting.value = true
    restartMessage.value = ''

    restartDocker()
      .then(data => {
        if (data.success) {
          restartSuccess.value = true
          restartMessage.value = data.message || '容器重启成功'
          ElMessage.success(restartMessage.value)
          setTimeout(() => {
            fetchDockerStatus()
            fetchDockerLogs()
          }, 2000)
        } else {
          restartSuccess.value = false
          restartMessage.value = data.error || '重启失败'
          ElMessage.error(restartMessage.value)
        }
      })
      .catch(err => {
        restartSuccess.value = false
        restartMessage.value = err.message || '重启操作失败'
        ElMessage.error(restartMessage.value)
        console.error('重启Docker容器失败:', err)
      })
      .finally(() => {
        restarting.value = false
      })
  }).catch(() => {
    // 用户取消
  })
}

function getStatusType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (!status) return 'info'
  const lowerStatus = status.toLowerCase()
  if (lowerStatus.includes('running') || lowerStatus.includes('up')) {
    return 'success'
  }
  if (lowerStatus.includes('restarting') || lowerStatus.includes('paused')) {
    return 'warning'
  }
  if (lowerStatus.includes('stopped') || lowerStatus.includes('exited')) {
    return 'danger'
  }
  return 'info'
}

function syncSettingsTabFromRoute() {
  const tabFromQuery = route.query.tab
  if (typeof tabFromQuery === 'string' && validTabs.includes(tabFromQuery as SettingsTab)) {
    if (activeTab.value !== tabFromQuery) {
      activeTab.value = tabFromQuery as SettingsTab
    }
  } else if (!tabFromQuery && activeTab.value !== 'client') {
    activeTab.value = 'client'
  }
}

function updateSettingsTabQuery(tab: SettingsTab) {
  const currentTabInQuery = route.query.tab
  const targetTabInQuery = tab === 'client' ? undefined : tab
  if (currentTabInQuery === targetTabInQuery) {
    return
  }
  const nextQuery = { ...route.query }
  if (tab === 'client') {
    delete nextQuery.tab
  } else {
    nextQuery.tab = tab
  }
  router.replace({ path: '/settings', query: nextQuery })
}

function loadSystemTabData(tab: SettingsTab) {
  if (tab === 'stream' && !loadingServerStatus.value && !serverStatus.value) {
    fetchServerStatus()
  }
  if (tab === 'container' && !loadingStatus.value && !dockerStatus.value) {
    fetchDockerStatus()
    fetchDockerLogs()
  }
  if (tab === 'app-logs' && logFiles.value.length === 0 && !loadingAppLogs.value) {
    fetchFileList().then(() => fetchAppLogs())
  }
}

watch(() => route.query.tab, syncSettingsTabFromRoute)
watch(activeTab, (tab) => {
  if (tab !== 'container' && ws.value) {
    stopLogStream()
  }
  updateSettingsTabQuery(tab)
  loadSystemTabData(tab)
})
watch(appLogLines, () => {
  scrollAppLogsToBottom()
})

onMounted(() => {
  fetchConfigs()
  void testConnection(false)
  loadSystemTabData(activeTab.value)
})

onUnmounted(() => {
  stopLogStream()
})
</script>

<style scoped>
.settings-page {
  @apply space-y-6;
  max-width: 100%;
  overflow-x: hidden;
}

/* 顶部品牌横幅 */
.settings-header-card {
  padding: 24px 28px 20px;
  position: relative;
  overflow: hidden;
  border-radius: 20px;
}

.settings-header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.settings-title-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.settings-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.settings-title {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.5px;
  margin: 0;
  line-height: 1.2;
}

.settings-badge {
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

.settings-subtitle {
  color: #64748b;
  font-size: 13.5px;
  margin: 0;
}

.settings-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.connection-pill-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 143, 171, 0.25);
}

.connection-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  flex-shrink: 0;
}

.connection-dot--success {
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2), 0 0 8px #10b981;
}

.connection-dot--error {
  background: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.2);
}

.connection-dot--idle {
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
}

.connection-pill-info {
  display: flex;
  flex-direction: column;
}

.connection-pill-label {
  font-size: 10.5px;
  color: #94a3b8;
  font-weight: 600;
}

.connection-pill-val {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  font-family: monospace;
}

.header-btn {
  border-radius: 12px;
  font-weight: 600;
}

/* 现代毛玻璃标签容器 */
.settings-tabs-wrapper {
  border-radius: 20px;
  overflow: hidden;
  padding: 12px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(255, 143, 171, 0.25);
  box-shadow: 0 10px 30px 0 rgba(255, 117, 151, 0.08);
}

.modern-settings-tabs {
  border: none !important;
  background: transparent !important;
}

.modern-settings-tabs :deep(.el-tabs__header) {
  background: rgba(248, 250, 252, 0.8) !important;
  border: 1px solid rgba(255, 143, 171, 0.2) !important;
  border-radius: 14px !important;
  padding: 6px !important;
  margin-bottom: 20px !important;
  display: flex;
  overflow-x: auto;
}

.modern-settings-tabs :deep(.el-tabs__header)::-webkit-scrollbar {
  height: 4px;
}

.modern-settings-tabs :deep(.el-tabs__nav) {
  border: none !important;
  display: flex;
  gap: 4px;
}

.modern-settings-tabs :deep(.el-tabs__item) {
  border: none !important;
  border-radius: 10px !important;
  padding: 0 16px !important;
  height: 38px !important;
  line-height: 38px !important;
  font-size: 13.5px !important;
  font-weight: 600 !important;
  color: #64748b !important;
  transition: background-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease !important;
}

.modern-settings-tabs :deep(.el-tabs__item:hover) {
  color: #ff7597 !important;
  background: rgba(255, 117, 151, 0.08) !important;
}

.modern-settings-tabs :deep(.el-tabs__item.is-active) {
  background: var(--gradient-primary) !important;
  color: #ffffff !important;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.35) !important;
}

.tab-label-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tab-pane-content {
  padding: 16px 20px;
}

/* 标签面板头部 */
.pane-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px dashed rgba(226, 232, 240, 0.9);
}

.pane-title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pane-title {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.pane-desc {
  font-size: 13px;
  color: #64748b;
  margin: 0;
}

.pane-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 现代表单定制 */
.modern-form {
  max-width: 800px;
}

.modern-alert {
  border-radius: 12px !important;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
  background: rgba(255, 255, 255, 0.85) !important;
}

.readonly-input :deep(.el-input__wrapper) {
  background-color: rgba(241, 245, 249, 0.8) !important;
}

.connection-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.connection-status-text {
  font-size: 13px;
  color: #64748b;
}

.el-form-item__help {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  line-height: 1.5;
}

/* 容器管理专属样式 */
.container-info-card,
.container-ctrl-card,
.container-logs-card {
  border-radius: 16px;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
  background: rgba(255, 255, 255, 0.85) !important;
}

.badge-source {
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.12);
  color: #0284c7;
}

.restart-container-btn {
  border-radius: 12px;
  height: 44px;
  font-weight: 700;
}

.stream-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  font-size: 11.5px;
  font-weight: 700;
  margin-left: 10px;
}

.stream-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.35);
  animation: pulse 1.8s infinite;
}

/* 终端日志视窗 */
.logs-container {
  background: #0f172a;
  border-radius: 12px;
  padding: 14px 16px;
  overflow-y: auto;
  max-height: 520px;
  border: 1px solid rgba(51, 65, 85, 0.6);
  box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.35);
}

.logs-content {
  color: #e2e8f0;
  font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

/* 系统日志应用专属样式 */
.app-logs-toolbar-card {
  border-radius: 14px;
  border: 1px solid rgba(255, 143, 171, 0.22) !important;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.app-logs-viewer-card {
  border-radius: 16px;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
}

.app-logs-container {
  padding: 10px 0;
  max-height: 65vh;
  font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.log-line {
  display: flex;
  padding: 2px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  transition: background-color 0.15s ease;
  content-visibility: auto;
  contain-intrinsic-size: 24px;
}

.log-line:hover {
  background-color: rgba(255, 255, 255, 0.06);
}

.log-error {
  background-color: rgba(244, 63, 94, 0.15);
}

.log-warn {
  background-color: rgba(245, 158, 11, 0.12);
}

.log-debug {
  color: #94a3b8;
}

.line-no {
  color: #64748b;
  user-select: none;
  padding-right: 12px;
  text-align: right;
  flex-shrink: 0;
  min-width: 44px;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  margin-right: 12px;
  font-size: 11px;
}

.line-content {
  color: #f1f5f9;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-error .line-content {
  color: #fda4af;
  font-weight: 500;
}

.log-warn .line-content {
  color: #fde047;
  font-weight: 500;
}

.custom-log-files-table {
  background: transparent !important;
}

.custom-log-files-table :deep(tr) {
  background: transparent !important;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .settings-header-card {
    padding: 16px;
  }

  .settings-title {
    font-size: 20px;
  }

  .settings-page {
    padding: 0 !important;
  }

  .settings-header-actions {
    flex-direction: column !important;
    width: 100% !important;
    gap: 8px !important;
  }

  .settings-header-actions > * {
    width: 100% !important;
    justify-content: center !important;
  }

  .tab-pane-content {
    padding: 10px 4px;
  }

  .pane-header-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .modern-form {
    max-width: 100%;
  }

  .toolbar-left {
    width: 100%;
  }

  .toolbar-left :deep(.el-input),
  .toolbar-left :deep(.el-select) {
    width: 100% !important;
  }
}

/* 多 Bot 集群卡片 */
.bot-cluster-card {
  margin-top: 24px;
  padding: 20px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.85);
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.06);
}

.cluster-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.cluster-icon-pill {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
  font-size: 18px;
}

.cluster-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.cluster-desc {
  margin: 2px 0 0;
  font-size: 12px;
  color: #64748b;
}

.cluster-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 12.5px;
  line-height: 1.5;
  margin-bottom: 16px;
}

.banner-success {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #065f46;
}

.banner-warning {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.25);
  color: #92400e;
}

.bot-node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.bot-node-card {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.node-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.node-badge {
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  white-space: nowrap;
}

.badge-primary {
  background: rgba(168, 85, 247, 0.15);
  color: #7e22ce;
  border: 1px solid rgba(168, 85, 247, 0.3);
}

.badge-admin {
  background: rgba(16, 185, 129, 0.15);
  color: #047857;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-nojoin {
  background: rgba(56, 189, 248, 0.15);
  color: #0369a1;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.badge-unreachable {
  background: rgba(245, 158, 11, 0.15);
  color: #b45309;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.node-caps-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.cap-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}

.cap-ok {
  background: rgba(16, 185, 129, 0.12);
  color: #047857;
}

.cap-no {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}

.cap-readonly {
  background: rgba(148, 163, 184, 0.15);
  color: #475569;
}

.rebrand-preview-box {
  padding: 16px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px dashed rgba(255, 117, 151, 0.35);
}

.rebrand-preview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 768px) {
  .rebrand-preview-grid {
    grid-template-columns: 1fr;
  }
}

.preview-col-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
}

.preview-output-caption {
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: #1e293b;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 8px;
  min-height: 54px;
  white-space: pre-wrap;
  word-break: break-word;
}

.preview-output-filename {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #0369a1;
  background: rgba(240, 249, 255, 0.9);
  border: 1px solid rgba(186, 230, 253, 0.9);
  border-radius: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>