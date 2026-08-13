<template>
  <div class="settings-page">
    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="客户端连接" name="client">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>客户端连接配置</span>
              <div class="card-actions">
                <el-button @click="testConnection" :loading="testingConnection">
                  测试连接
                </el-button>
                <el-button type="primary" @click="saveClientConnection" :loading="savingClientConnection">
                  保存并应用
                </el-button>
              </div>
            </div>
          </template>

          <el-alert
            title="浏览器端可选择同源访问，也可以指定远程服务器。"
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          />

          <el-form label-width="180px">
            <el-form-item label="客户端类型">
              <el-tag type="info">浏览器客户端</el-tag>
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
              <el-input :model-value="effectiveServerUrlLabel" readonly />
            </el-form-item>
            <el-form-item label="连接状态">
              <div class="connection-status">
                <el-tag :type="connectionStatusTagType">
                  {{ connectionStatusLabel }}
                </el-tag>
                <span v-if="connectionStatusText" class="connection-status-text">
                  {{ connectionStatusText }}
                </span>
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Telegram配置 -->
      <el-tab-pane label="Telegram配置" name="telegram">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>Telegram Bot配置</span>
              <el-button type="primary" @click="saveConfig('telegram')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="warning"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>注意：</strong>修改 API ID、API Hash、Bot Token 或管理员ID 后需要重启服务才能生效。
                <br />其他配置（如上传到Telegram）保存后会在下次使用时自动从数据库读取最新配置。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.telegram" label-width="180px" :rules="rules">
            <el-form-item label="API ID" prop="API_ID">
              <el-input-number v-model="configs.telegram.API_ID" :min="0" style="width: 100%" :disabled="isOfflineOnly('API_ID')" />
            </el-form-item>
            <el-form-item label="API Hash" prop="API_HASH">
              <el-input v-model="configs.telegram.API_HASH" type="password" show-password :disabled="isOfflineOnly('API_HASH')" :placeholder="secretStatus('API_HASH')" />
            </el-form-item>
            <el-form-item label="Bot Token" prop="BOT_TOKEN">
              <el-input v-model="configs.telegram.BOT_TOKEN" type="password" show-password :disabled="isOfflineOnly('BOT_TOKEN')" :placeholder="secretStatus('BOT_TOKEN')" />
            </el-form-item>
            <el-form-item label="管理员ID" prop="ADMIN_ID">
              <el-input-number v-model="configs.telegram.ADMIN_ID" :min="0" style="width: 100%" :disabled="isOfflineOnly('ADMIN_ID')" />
            </el-form-item>
            <el-form-item label="上传到Telegram">
              <el-switch v-model="configs.telegram.UP_TELEGRAM" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 下载配置 -->
      <el-tab-pane label="下载配置" name="download">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>下载设置</span>
              <el-button type="primary" @click="saveConfig('download')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>提示：</strong>下载配置保存后会立即生效，下次下载时会自动从数据库读取最新配置，无需重启服务。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.download" label-width="180px">
            <el-form-item label="保存路径">
              <el-input v-model="configs.download.SAVE_PATH" />
            </el-form-item>
            <el-form-item label="自动清理下载文件">
              <el-switch v-model="configs.download.DOWNLOAD_CLEANUP_ENABLED" />
              <div class="el-form-item__help">
                启用后，后台会定期清理保存路径中超过保留时间的本地文件，并跳过正在下载或上传的文件
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
              <el-input v-model="configs.download.PROXY_IP" placeholder="留空则不使用代理" :disabled="isOfflineOnly('PROXY_IP')" />
            </el-form-item>
            <el-form-item label="代理端口">
              <el-input v-model="configs.download.PROXY_PORT" placeholder="留空则不使用代理" :disabled="isOfflineOnly('PROXY_PORT')" />
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
        </el-card>
      </el-tab-pane>

      <!-- Aria2配置 -->
      <el-tab-pane label="Aria2配置" name="aria2">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>Aria2 RPC配置</span>
              <el-button type="primary" @click="saveConfig('aria2')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>提示：</strong>Aria2配置保存后会立即生效，下次连接时会自动从数据库读取最新配置，无需重启服务。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.aria2" label-width="180px">
            <el-form-item label="RPC密钥">
              <el-input v-model="configs.aria2.RPC_SECRET" type="password" show-password :disabled="isOfflineOnly('RPC_SECRET')" :placeholder="secretStatus('RPC_SECRET')" />
            </el-form-item>
            <el-form-item label="RPC URL">
              <el-input v-model="configs.aria2.RPC_URL" :disabled="isOfflineOnly('RPC_URL')" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 直链功能配置 -->
      <el-tab-pane label="直链功能" name="stream">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>直链功能配置</span>
              <el-button type="primary" @click="saveConfig('stream')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-form :model="configs.stream" label-width="180px">
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
              <el-input v-model="configs.stream.STREAM_ALLOWED_USERS" placeholder="数字用户 ID，逗号分隔；留空则拒绝所有人" :disabled="isOfflineOnly('STREAM_ALLOWED_USERS')" />
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
        </el-card>
      </el-tab-pane>


      <el-tab-pane label="容器管理" name="container">
        <el-row :gutter="20">
          <el-col :xs="24" :lg="12">
            <el-card shadow="hover" class="mb-6">
              <template #header>
                <div class="flex justify-between items-center">
                  <span>Docker容器状态</span>
                  <el-button
                    :icon="Refresh"
                    circle
                    size="small"
                    @click="fetchDockerStatus"
                    :loading="loadingStatus"
                  />
                </div>
              </template>

              <el-skeleton v-if="loadingStatus" :rows="5" animated />

              <div v-else-if="dockerStatus">
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="运行环境">
                    <el-tag :type="dockerStatus.in_docker ? 'success' : 'info'" size="small">
                      {{ dockerStatus.in_docker ? 'Docker容器内' : '非Docker环境' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="容器名称">
                    {{ dockerStatus.container_name || '-' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="运行状态">
                    <el-tag
                      :type="getStatusType(dockerStatus.status)"
                      size="small"
                    >
                      {{ dockerStatus.status || '-' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="镜像名称">
                    {{ dockerStatus.image || '-' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="创建时间">
                    {{ formatDate(dockerStatus.created) }}
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

          <el-col :xs="24" :lg="12">
            <el-card shadow="hover" class="mb-6">
              <template #header>
                <span>容器控制</span>
              </template>

              <div class="control-actions">
                <el-button
                  type="primary"
                  :icon="RefreshRight"
                  @click="handleRestart"
                  :loading="restarting"
                  :disabled="!dockerStatus?.in_docker"
                  block
                  size="large"
                >
                  重启容器（热重载）
                </el-button>

                <el-alert
                  v-if="!dockerStatus?.in_docker"
                  title="当前不在Docker容器内运行，无法执行容器操作"
                  type="info"
                  :closable="false"
                  class="mt-4"
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

        <el-card shadow="hover">
          <template #header>
            <div class="flex justify-between items-center">
              <span>容器日志</span>
              <div class="flex gap-2">
                <el-select
                  v-model="dockerLogLines"
                  @change="handleDockerLogLinesChange"
                  style="width: 120px"
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
      </el-tab-pane>

      <el-tab-pane label="系统日志" name="app-logs">
        <el-card shadow="hover" class="mb-4">
          <div class="toolbar">
            <div class="toolbar-left">
              <el-select v-model="selectedFile" placeholder="当前日志" clearable style="width: 220px" size="default" @change="fetchAppLogs">
                <el-option v-for="f in logFiles" :key="f.name" :label="`${f.name} (${formatSize(f.size)})`" :value="f.name" />
              </el-select>

              <el-select v-model="levelFilter" placeholder="全部级别" clearable style="width: 130px" size="default" @change="fetchAppLogs">
                <el-option label="ERROR" value="ERROR" />
                <el-option label="WARNING" value="WARNING" />
                <el-option label="INFO" value="INFO" />
                <el-option label="DEBUG" value="DEBUG" />
              </el-select>

              <el-input v-model="keyword" placeholder="关键词搜索" clearable style="width: 200px" size="default" @keyup.enter="fetchAppLogs" @clear="fetchAppLogs">
                <template #prefix>
                  <el-icon><Search /></el-icon>
                </template>
              </el-input>

              <el-select v-model="tailCount" style="width: 120px" size="default" @change="fetchAppLogs">
                <el-option label="最新 100 行" :value="100" />
                <el-option label="最新 200 行" :value="200" />
                <el-option label="最新 500 行" :value="500" />
                <el-option label="最新 1000 行" :value="1000" />
              </el-select>
            </div>

            <div class="toolbar-right">
              <el-button :icon="Refresh" circle size="default" @click="fetchAppLogs" :loading="loadingAppLogs" title="刷新" />
              <el-button :icon="Download" circle size="default" @click="handleDownload" :disabled="!currentFileName" title="下载日志文件" />
              <el-button :icon="Delete" circle size="default" @click="clearAppLogDisplay" title="清空显示" />
            </div>
          </div>
        </el-card>

        <el-card shadow="hover" class="mb-4" v-if="logFiles.length > 0">
          <template #header>
            <div class="flex justify-between items-center">
              <span>日志文件 ({{ logFiles.length }})</span>
              <el-button text size="small" @click="showFileList = !showFileList">
                {{ showFileList ? '收起' : '展开' }}
              </el-button>
            </div>
          </template>
          <div v-if="showFileList">
            <el-table :data="logFiles" size="small" stripe>
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
        </el-card>

        <el-card shadow="hover">
          <template #header>
            <div class="flex justify-between items-center">
              <span>
                日志内容
                <el-tag size="small" type="info" class="ml-2" v-if="appLogLines.length">{{ appLogLines.length }} 行</el-tag>
              </span>
              <el-switch v-model="autoScroll" active-text="自动滚动" inactive-text="" size="small" />
            </div>
          </template>

          <el-skeleton v-if="loadingAppLogs" :rows="12" animated />

          <div v-else-if="appLogLines.length > 0" class="logs-container app-logs-container" ref="appLogsContainerRef">
            <div v-for="(line, idx) in appLogLines" :key="idx" :class="['log-line', getLineClass(line)]">
              <span class="line-no">{{ idx + 1 }}</span>
              <span class="line-content">{{ line }}</span>
            </div>
          </div>

          <el-empty v-else description="暂无日志数据" />
        </el-card>
      </el-tab-pane>

    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { downloadLogFile, getConfig, updateConfig, getDockerStatus, restartDocker, getDockerLogs, getLogFiles, getLogContent, type LogFile } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { checkServerConnection } from '@/utils/connection'
import { getServerBaseUrl, isValidServerBaseUrl, setServerBaseUrl } from '@/utils/runtime'
import { Refresh, RefreshRight, VideoPlay, VideoPause, Delete, Download, Search } from '@element-plus/icons-vue'
import type { DockerStatus } from '@/types/api'
import { formatDate } from '@/utils/formatters'
import { buildWsProtocols, buildWsUrl } from '@/utils/websocket'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

type SettingsTab = 'client' | 'telegram' | 'download' | 'aria2' | 'stream' | 'container' | 'app-logs'
const validTabs: SettingsTab[] = ['client', 'telegram', 'download', 'aria2', 'stream', 'container', 'app-logs']
const initialTab = typeof route.query.tab === 'string' && validTabs.includes(route.query.tab as SettingsTab)
  ? route.query.tab as SettingsTab
  : 'client'
const activeTab = ref<SettingsTab>(initialTab)
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
// 配置数据
const configs = ref({
  telegram: {
    API_ID: 0,
    API_HASH: '',
    BOT_TOKEN: '',
    ADMIN_ID: 0,
    UP_TELEGRAM: true
  },
  download: {
    SAVE_PATH: '/data/downloads',
    PROXY_IP: '',
    PROXY_PORT: '',
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
    STREAM_FQDN: '23.94.9.54',
    STREAM_KEEP_ALIVE: false,
    STREAM_PING_INTERVAL: 1200,
    STREAM_USE_SESSION_FILE: false,
    STREAM_ALLOWED_USERS: '',
    STREAM_AUTO_DOWNLOAD: false,
    SEND_STREAM_LINK: false,
    MULTI_BOT_TOKENS: [] as string[]
  }
})

// 多机器人Token文本（用于显示和编辑）
const multiBotTokensText = computed({
  get: () => {
    const tokens = configs.value.stream.MULTI_BOT_TOKENS || []
    return tokens.join('\n')
  },
  set: (val: string) => {
    updateMultiBotTokens(val)
  }
})

function updateMultiBotTokens(text: string) {
  if (!text.trim()) {
    configs.value.stream.MULTI_BOT_TOKENS = []
    return
  }
  // 支持换行和逗号分隔
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
    for (const category of configCategories) {
      const response = await getConfig(category)
      if (response.success && response.data) {
        redactedKeys.value = new Set([...redactedKeys.value, ...(response.redacted_keys || [])])
        offlineOnlyKeys.value = new Set([...offlineOnlyKeys.value, ...(response.offline_only_keys || [])])
        secretCounts.value = { ...secretCounts.value, ...(response.secret_counts || {}) }
        // 合并配置，保留默认值
        ;(configs.value as Record<ConfigCategory, Record<string, any>>)[category] = {
          ...(configs.value[category] as Record<string, any>),
          ...response.data
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
        ElMessage.warning({
          message: response.message || '配置已保存，但需要重启服务才能生效',
          duration: 5000
        })
      } else {
        ElMessage.success(response.message || '配置已保存，下次使用时将从数据库读取最新配置')
      }
      // 重新获取配置以确保同步
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

const dockerStatus = ref<DockerStatus | null>(null)
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

const logFiles = ref<LogFile[]>([])
const appLogLines = ref<string[]>([])
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
      // 清空现有日志，准备接收流式日志
      dockerLogs.value = ''
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'history') {
          dockerLogs.value = data.logs || ''
        } else if (data.type === 'log' || data.type === 'line') { // line passed from backend is 'line', but let's handle 'log' too just in case
          // Append new log line
          dockerLogs.value += (dockerLogs.value ? '\n' : '') + (data.line || '')
          // Auto scroll to bottom
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
    // 如果正在流式传输，重新连接以应用新的行数设置
    startLogStream()
  } else {
    // 否则只是获取静态日志
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
  if (!dockerStatus.value?.in_docker) {
    ElMessage.warning('当前不在Docker容器内运行')
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
          // 延迟刷新状态
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
  if (typeof route.query.tab === 'string' && validTabs.includes(route.query.tab as SettingsTab)) {
    activeTab.value = route.query.tab as SettingsTab
  } else if (!route.query.tab) {
    activeTab.value = 'client'
  }
}

function updateSettingsTabQuery(tab: SettingsTab) {
  const nextQuery = { ...route.query }
  if (tab === 'client') {
    delete nextQuery.tab
  } else {
    nextQuery.tab = tab
  }
  router.replace({ path: '/settings', query: nextQuery })
}

function loadSystemTabData(tab: SettingsTab) {
  if (tab === 'container') {
    fetchDockerStatus()
    fetchDockerLogs()
  }
  if (tab === 'app-logs' && logFiles.value.length === 0 && !loadingAppLogs.value) {
    fetchFileList().then(() => fetchAppLogs())
  }
}

watch(() => route.query.tab, syncSettingsTabFromRoute)
watch(activeTab, (tab) => {
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
}

.page-header {
  @apply mb-6 flex items-center justify-between;
}

.page-title {
  @apply text-3xl font-bold text-gray-800 mb-2;
}

.page-subtitle {
  @apply text-gray-600;
}

.card-header {
  @apply flex items-center justify-between;
}

.card-actions {
  @apply flex items-center gap-3;
}

.connection-status {
  @apply flex items-center gap-3;
}

.connection-status-text {
  @apply text-sm text-gray-500;
}

.quick-actions {
  @apply space-y-3;
}

.el-form-item__help {
  @apply text-xs text-gray-500 mt-1;
}

.control-actions {
  @apply space-y-4;
}

.settings-page .system-tabs {
  @apply rounded-xl bg-white p-4;
}

.settings-page .system-tabs:deep(.el-tabs__header) {
  margin-bottom: 20px;
}

.settings-page .system-tabs:deep(.el-tabs__nav-wrap::after) {
  background-color: rgba(226, 232, 240, 0.9);
}

.toolbar {
  @apply flex flex-wrap justify-between items-center gap-3;
}

.toolbar-left {
  @apply flex flex-wrap items-center gap-2;
}

.toolbar-right {
  @apply flex items-center gap-1;
}

.logs-container {
  @apply bg-gray-900 rounded-lg p-4 overflow-auto;
  max-height: 600px;
  font-family: 'Courier New', monospace;
  position: relative;
}

.app-logs-container {
  @apply p-0;
  max-height: 65vh;
  font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.6;
}

.logs-content {
  @apply text-gray-100 text-sm whitespace-pre-wrap;
  margin: 0;
  line-height: 1.5;
  word-break: break-all;
}

.log-line {
  @apply flex px-3 py-0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  transition: background-color 0.15s;
}

.log-line:hover {
  background-color: rgba(255, 255, 255, 0.05);
}

.log-error {
  background-color: rgba(239, 68, 68, 0.12);
}

.log-warn {
  background-color: rgba(245, 158, 11, 0.10);
}

.log-debug {
  @apply text-gray-500;
}

.line-no {
  @apply text-gray-600 select-none pr-3 text-right flex-shrink-0;
  min-width: 40px;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  margin-right: 12px;
}

.line-content {
  @apply text-gray-200 whitespace-pre-wrap break-all;
}

.log-error .line-content {
  @apply text-red-400;
}

.log-warn .line-content {
  @apply text-yellow-400;
}

.logs-container::-webkit-scrollbar {
  width: 8px;
}

.logs-container::-webkit-scrollbar-track {
  @apply bg-gray-800 rounded;
}

.logs-container::-webkit-scrollbar-thumb {
  @apply bg-gray-600 rounded;
}

.logs-container::-webkit-scrollbar-thumb:hover {
  @apply bg-gray-500;
}

:deep(.el-descriptions__label) {
  @apply font-medium;
}

</style>
