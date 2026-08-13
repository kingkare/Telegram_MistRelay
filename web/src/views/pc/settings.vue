<template>
  <section class="pc-settings-view">
    <nav class="pc-settings-nav" aria-label="设置分类">
      <button
        v-for="category in categories"
        :key="category.id"
        class="pc-settings-nav-item"
        :class="{ active: activeCategory === category.id }"
        type="button"
        :aria-current="activeCategory === category.id ? 'page' : undefined"
        @click="activeCategory = category.id"
      >
        <el-icon :size="18"><component :is="category.icon" /></el-icon>
        <span>{{ category.label }}</span>
      </button>
    </nav>

    <section class="pc-settings-panel">
      <template v-if="activeCategory === 'connection'">
        <header class="pc-settings-heading">
          <h2>连接与账户</h2>
        </header>

        <div class="pc-settings-fields">
          <label class="pc-settings-field">
            <span>服务器地址</span>
            <div class="pc-settings-row">
              <el-input
                v-model="serverDraft"
                placeholder="https://example.com"
                clearable
                :disabled="savingServer"
                @keyup.enter="saveServer"
              />
              <el-button
                :icon="Connection"
                type="primary"
                :loading="savingServer"
                @click="saveServer"
              >
                测试并切换
              </el-button>
            </div>
          </label>

          <div class="pc-settings-account">
            <div>
              <span>当前账号</span>
              <strong>{{ auth.user?.username || '已登录' }}</strong>
            </div>
            <el-button :icon="SwitchButton" @click="logout">退出登录</el-button>
          </div>
        </div>
      </template>

      <template v-else-if="activeCategory === 'downloads'">
        <header class="pc-settings-heading">
          <h2>下载</h2>
        </header>

        <div class="pc-settings-fields">
          <label class="pc-settings-field">
            <span>默认下载目录</span>
            <div class="pc-settings-row">
              <el-input
                v-model="downloadDirectoryDraft"
                placeholder="使用系统默认目录"
                clearable
                @keyup.enter="saveDownloadSettings"
              />
              <el-button :icon="FolderOpened" @click="selectDownloadDirectory">选择目录</el-button>
            </div>
          </label>

          <div class="pc-settings-number-grid">
            <label class="pc-settings-number">
              <span>单文件线程数</span>
              <el-input-number
                v-model="threadsPerFileDraft"
                :min="1"
                :max="8"
                controls-position="right"
              />
            </label>
            <label class="pc-settings-number">
              <span>全局并发数</span>
              <el-input-number
                v-model="maxConcurrentTasksDraft"
                :min="1"
                :max="4"
                controls-position="right"
              />
            </label>
          </div>

          <div class="pc-settings-actions">
            <el-button :icon="Check" type="primary" @click="saveDownloadSettings">
              保存下载设置
            </el-button>
          </div>
        </div>
      </template>

      <template v-else>
        <header class="pc-settings-heading">
          <h2>客户端</h2>
        </header>

        <div class="pc-settings-info-grid">
          <div>
            <span>主题</span>
            <strong>浅色</strong>
          </div>
          <div>
            <span>版本</span>
            <strong>{{ appVersion }}</strong>
          </div>
          <div>
            <span>运行环境</span>
            <strong>{{ runtimeLabel }}</strong>
          </div>
          <div>
            <span>任务状态</span>
            <strong>{{ downloads.activeCount }} 下载中 / {{ downloads.totalQueued }} 排队</strong>
          </div>
        </div>

        <details class="pc-settings-advanced">
          <summary>高级诊断</summary>
          <div class="pc-settings-diagnostic-heading">
            <span>诊断信息</span>
            <el-button :icon="CopyDocument" size="small" @click="copyDiagnostics">复制</el-button>
          </div>
          <pre class="pc-settings-diagnostics">{{ diagnosticText }}</pre>
        </details>
      </template>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { invoke } from '@tauri-apps/api/core'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Check,
  Connection,
  CopyDocument,
  Download as DownloadIcon,
  FolderOpened,
  Monitor,
  SwitchButton,
} from '@element-plus/icons-vue'
import packageInfo from '../../../package.json'
import { useAuthStore } from '@/stores/auth'
import { usePcDownloadsStore } from '@/stores/pcDownloads'
import { usePcPreferencesStore } from '@/stores/pcPreferences'
import { checkServerConnection } from '@/utils/connection'
import {
  getServerBaseUrl,
  isTauriRuntime,
  isValidServerBaseUrl,
  normalizeServerBaseUrl,
  setServerBaseUrl,
} from '@/utils/runtime'

type SettingsCategory = 'connection' | 'downloads' | 'client'

const router = useRouter()
const auth = useAuthStore()
const downloads = usePcDownloadsStore()
const preferences = usePcPreferencesStore()

const appVersion = packageInfo.version
const activeCategory = ref<SettingsCategory>('connection')
const savingServer = ref(false)
const serverDraft = ref(getServerBaseUrl())
const downloadDirectoryDraft = ref(preferences.downloadDirectory)
const threadsPerFileDraft = ref(preferences.threadsPerFile)
const maxConcurrentTasksDraft = ref(preferences.maxConcurrentTasks)

const categories = [
  { id: 'connection' as const, label: '连接与账户', icon: Connection },
  { id: 'downloads' as const, label: '下载', icon: DownloadIcon },
  { id: 'client' as const, label: '客户端', icon: Monitor },
]

const runtimeLabel = computed(() => (isTauriRuntime() ? '桌面端' : '浏览器'))

const diagnosticText = computed(() => JSON.stringify({
  clientVersion: appVersion,
  runtime: runtimeLabel.value,
  serverBaseUrl: getServerBaseUrl(),
  username: auth.user?.username || null,
  downloadDirectory: preferences.downloadDirectory,
  threadsPerFile: preferences.threadsPerFile,
  maxConcurrentTasks: preferences.maxConcurrentTasks,
  tasks: {
    total: downloads.tasks.length,
    downloading: downloads.activeCount,
    queued: downloads.totalQueued,
    completed: downloads.completedTasks.length,
    failed: downloads.failedTasks.length,
    interrupted: downloads.interruptedTasks.length,
  },
}, null, 2))

async function saveServer() {
  if (savingServer.value) return

  const normalized = normalizeServerBaseUrl(serverDraft.value)
  if (!normalized) {
    ElMessage.warning('请输入服务器地址')
    return
  }
  if (!/^https?:\/\//i.test(normalized) || !isValidServerBaseUrl(normalized)) {
    ElMessage.error('服务器地址格式不正确')
    return
  }

  savingServer.value = true
  try {
    const result = await checkServerConnection(normalized)
    if (!result.ok) {
      ElMessage.error(result.message)
      return
    }

    const nextServerUrl = normalizeServerBaseUrl(result.serverBaseUrl)
    serverDraft.value = nextServerUrl
    if (nextServerUrl === getServerBaseUrl()) {
      ElMessage.success(result.message)
      return
    }

    await ElMessageBox.confirm(
      `确定切换到 ${nextServerUrl}？切换后需要重新登录。`,
      '切换服务器',
      {
        confirmButtonText: '确认切换',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )

    setServerBaseUrl(nextServerUrl)
    auth.logout()
    await router.replace('/pc/login')
  } catch (error: unknown) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '切换服务器失败')
  } finally {
    savingServer.value = false
  }
}

function saveDownloadSettings() {
  const threads = Number(threadsPerFileDraft.value)
  const concurrentTasks = Number(maxConcurrentTasksDraft.value)
  if (!Number.isInteger(threads) || threads < 1 || threads > 8) {
    ElMessage.warning('单文件线程数必须在 1-8 之间')
    return
  }
  if (!Number.isInteger(concurrentTasks) || concurrentTasks < 1 || concurrentTasks > 4) {
    ElMessage.warning('全局并发数必须在 1-4 之间')
    return
  }

  preferences.setDownloadDirectory(downloadDirectoryDraft.value)
  preferences.setThreadsPerFile(threads)
  preferences.setMaxConcurrentTasks(concurrentTasks)

  downloadDirectoryDraft.value = preferences.downloadDirectory
  threadsPerFileDraft.value = preferences.threadsPerFile
  maxConcurrentTasksDraft.value = preferences.maxConcurrentTasks
  downloads.drainQueue()
  ElMessage.success('下载设置已保存')
}

async function selectDownloadDirectory() {
  try {
    const path = await invoke<string>('select_directory')
    if (path) downloadDirectoryDraft.value = path
  } catch (error: any) {
    ElMessage.error(error.message || error || '选择目录失败')
  }
}

async function copyDiagnostics() {
  try {
    await navigator.clipboard.writeText(diagnosticText.value)
    ElMessage.success('诊断信息已复制')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = diagnosticText.value
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('诊断信息已复制')
  }
}

function logout() {
  auth.logout()
  router.replace('/pc/login')
}
</script>

<style scoped>
.pc-settings-view {
  display: grid;
  grid-template-columns: 184px minmax(0, 1fr);
  align-items: start;
  gap: 18px;
  min-width: 0;
}

.pc-settings-nav {
  display: grid;
  gap: 4px;
}

.pc-settings-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 0;
  border-radius: var(--pc-radius-md);
  background: transparent;
  color: var(--pc-color-text-muted);
  font: inherit;
  font-size: 14px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
}

.pc-settings-nav-item:hover {
  background: var(--pc-color-surface-soft);
  color: var(--pc-color-text);
}

.pc-settings-nav-item.active {
  background: var(--pc-color-primary-soft);
  color: var(--pc-color-primary-strong);
  font-weight: 600;
}

.pc-settings-nav-item:focus-visible {
  outline: 3px solid var(--pc-color-focus);
  outline-offset: 1px;
}

.pc-settings-panel {
  min-width: 0;
  min-height: 430px;
  padding: 20px 22px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface);
}

.pc-settings-heading {
  margin-bottom: 22px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--pc-color-border);
}

.pc-settings-heading h2 {
  margin: 0;
  color: var(--pc-color-text);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.25;
}

.pc-settings-fields {
  display: grid;
  gap: 22px;
}

.pc-settings-field,
.pc-settings-number {
  display: grid;
  gap: 8px;
}

.pc-settings-field > span,
.pc-settings-number > span,
.pc-settings-account span,
.pc-settings-info-grid span {
  color: var(--pc-color-text-muted);
  font-size: 12px;
  line-height: 16px;
}

.pc-settings-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.pc-settings-account {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid var(--pc-color-border);
}

.pc-settings-account div,
.pc-settings-info-grid div {
  display: grid;
  gap: 4px;
}

.pc-settings-account strong,
.pc-settings-info-grid strong {
  color: var(--pc-color-text);
  font-size: 14px;
  font-weight: 600;
}

.pc-settings-number-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 220px));
  gap: 18px;
}

.pc-settings-number :deep(.el-input-number) {
  width: 100%;
}

.pc-settings-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 18px;
  border-top: 1px solid var(--pc-color-border);
}

.pc-settings-info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px 28px;
}

.pc-settings-advanced {
  margin-top: 28px;
  border-top: 1px solid var(--pc-color-border);
}

.pc-settings-advanced summary {
  padding: 16px 0;
  color: var(--pc-color-text);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.pc-settings-diagnostic-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-settings-diagnostics {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-bg);
  color: var(--pc-color-text);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

@media (max-width: 820px) {
  .pc-settings-view {
    grid-template-columns: 1fr;
  }

  .pc-settings-nav {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .pc-settings-nav-item {
    justify-content: center;
  }

  .pc-settings-row,
  .pc-settings-info-grid,
  .pc-settings-number-grid {
    grid-template-columns: 1fr;
  }

  .pc-settings-account {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
