<template>
  <section class="pc-settings-view">
    <section class="pc-card pc-settings-section">
      <div class="pc-settings-section-heading">
        <h2>服务器</h2>
      </div>
      <div class="pc-settings-row">
        <el-input
          v-model="serverDraft"
          placeholder="https://example.com"
          clearable
          @keyup.enter="saveServer"
        />
        <el-button :icon="Check" type="primary" @click="saveServer">保存</el-button>
      </div>
      <div class="pc-settings-account">
        <div>
          <span>当前账号</span>
          <strong>{{ auth.user?.username || '已登录' }}</strong>
        </div>
        <el-button :icon="SwitchButton" @click="logout">退出登录</el-button>
      </div>
    </section>

    <section class="pc-card pc-settings-section">
      <div class="pc-settings-section-heading">
        <h2>下载</h2>
      </div>
      <div class="pc-settings-row">
        <el-input
          v-model="downloadDirectoryDraft"
          placeholder="默认下载目录"
          clearable
          @blur="saveDownloadDirectory"
          @keyup.enter="saveDownloadDirectory"
        />
        <el-button :icon="FolderOpened" @click="selectDownloadDirectory">选择</el-button>
        <el-button :icon="Check" @click="saveDownloadDirectory">保存</el-button>
      </div>

      <div class="pc-settings-number-grid">
        <label class="pc-settings-number">
          <span>单文件线程数</span>
          <el-input-number v-model="threadsPerFile" :min="1" :max="8" controls-position="right" />
        </label>
        <label class="pc-settings-number">
          <span>全局并发数</span>
          <el-input-number v-model="maxConcurrentTasks" :min="1" :max="4" controls-position="right" />
        </label>
      </div>
    </section>

    <section class="pc-card pc-settings-section">
      <div class="pc-settings-section-heading">
        <h2>客户端</h2>
      </div>
      <div class="pc-settings-info-grid">
        <div>
          <span>主题</span>
          <strong>清爽浅色</strong>
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
    </section>

    <section class="pc-card pc-settings-section">
      <div class="pc-settings-section-heading">
        <h2>诊断</h2>
        <el-button :icon="CopyDocument" @click="copyDiagnostics">复制</el-button>
      </div>
      <pre class="pc-settings-diagnostics">{{ diagnosticText }}</pre>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { invoke } from '@tauri-apps/api/core'
import { ElMessage } from 'element-plus'
import { Check, CopyDocument, FolderOpened, SwitchButton } from '@element-plus/icons-vue'
import packageInfo from '../../../package.json'
import { useAuthStore } from '@/stores/auth'
import { usePcDownloadsStore } from '@/stores/pcDownloads'
import { usePcPreferencesStore } from '@/stores/pcPreferences'
import {
  getServerBaseUrl,
  isTauriRuntime,
  setServerBaseUrl,
} from '@/utils/runtime'

const router = useRouter()
const auth = useAuthStore()
const downloads = usePcDownloadsStore()
const preferences = usePcPreferencesStore()

const appVersion = packageInfo.version
const serverDraft = ref(getServerBaseUrl())
const downloadDirectoryDraft = ref(preferences.downloadDirectory)

const threadsPerFile = computed({
  get: () => preferences.threadsPerFile,
  set: (value: number) => preferences.setThreadsPerFile(value),
})

const maxConcurrentTasks = computed({
  get: () => preferences.maxConcurrentTasks,
  set: (value: number) => {
    preferences.setMaxConcurrentTasks(value)
    downloads.drainQueue()
  },
})

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

function saveServer() {
  const normalized = setServerBaseUrl(serverDraft.value)
  serverDraft.value = normalized
  ElMessage.success('服务器已保存')
}

function saveDownloadDirectory() {
  preferences.setDownloadDirectory(downloadDirectoryDraft.value)
  downloadDirectoryDraft.value = preferences.downloadDirectory
  ElMessage.success('下载目录已保存')
}

async function selectDownloadDirectory() {
  try {
    const path = await invoke<string>('select_directory')
    if (!path) return
    downloadDirectoryDraft.value = path
    saveDownloadDirectory()
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
  router.push('/pc/login')
}
</script>

<style scoped>
.pc-settings-view {
  display: grid;
  gap: 14px;
}

.pc-settings-section {
  display: grid;
  gap: 14px;
  padding: 16px;
}

.pc-settings-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pc-settings-section-heading h2 {
  margin: 0;
  font-size: 16px;
  line-height: 1.25;
}

.pc-settings-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: center;
}

.pc-settings-account {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--pc-color-border);
}

.pc-settings-account div,
.pc-settings-info-grid div,
.pc-settings-number {
  display: grid;
  gap: 4px;
}

.pc-settings-account span,
.pc-settings-info-grid span,
.pc-settings-number span {
  color: var(--pc-color-text-muted);
  font-size: 12px;
}

.pc-settings-account strong,
.pc-settings-info-grid strong {
  color: var(--pc-color-text);
  font-size: 14px;
}

.pc-settings-number-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 220px));
  gap: 14px;
}

.pc-settings-info-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.pc-settings-diagnostics {
  max-height: 280px;
  margin: 0;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--pc-color-border);
  border-radius: var(--pc-radius-md);
  background: #f3f8f6;
  color: var(--pc-color-text);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

@media (max-width: 900px) {
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
