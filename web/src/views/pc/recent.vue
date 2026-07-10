<template>
  <section class="pc-recent-view">
    <section class="pc-recent-section">
      <div class="pc-recent-heading">
        <h2>最近入库</h2>
        <el-button :icon="RefreshRight" :loading="serverLoading" @click="loadServerRecent">
          刷新
        </el-button>
      </div>

      <el-alert
        v-if="serverError"
        :title="serverError"
        type="error"
        :closable="false"
        show-icon
      />

      <div v-if="serverLoading" class="pc-media-grid">
        <div v-for="index in 8" :key="index" class="pc-card pc-recent-skeleton" />
      </div>
      <DriveGrid
        v-else-if="serverItems.length"
        :items="serverItems"
        :show-delete="false"
        @open="handleOpen"
      />
      <div v-else class="pc-empty-state pc-recent-empty">
        <div class="pc-anime-asset pc-anime-empty-drive pc-recent-empty-art" aria-hidden="true"></div>
        <span>暂无最近入库</span>
      </div>
    </section>

    <section class="pc-recent-section">
      <div class="pc-recent-heading">
        <h2>本机最近</h2>
        <el-button :disabled="!recent.records.length" @click="clearLocalRecent">
          清除
        </el-button>
      </div>

      <DriveGrid
        v-if="localRecentItems.length"
        :items="localRecentItems"
        :show-delete="false"
        @open="handleOpen"
      />
      <div v-else class="pc-empty-state pc-recent-empty">
        <div class="pc-anime-asset pc-anime-empty-drive pc-recent-empty-art" aria-hidden="true"></div>
        <span>暂无本机记录</span>
      </div>
    </section>

    <MediaPreview
      v-model="previewItem"
      :items="previewItems"
      @download="handleDownload"
      @save-as="handleSaveAs"
      @delete="handleDelete"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight } from '@element-plus/icons-vue'
import DriveGrid from '@/components/pc/drive-grid.vue'
import MediaPreview from '@/components/pc/media-preview.vue'
import {
  browseTelegramDrive,
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveItem,
} from '@/api'
import { usePcRecentStore } from '@/stores/pcRecent'
import { queueTelegramDownload } from '@/utils/pcDownload'

const recent = usePcRecentStore()
const serverItems = ref<TelegramDriveItem[]>([])
const serverLoading = ref(false)
const serverError = ref('')
const previewItem = ref<TelegramDriveItem | null>(null)

const localRecentItems = computed(() => recent.records.map(record => record.item))
const previewItems = computed(() => [
  ...serverItems.value,
  ...localRecentItems.value,
].filter(isTelegramDriveFile))

onMounted(() => {
  recent.reload()
  loadServerRecent()
})

async function loadServerRecent() {
  serverLoading.value = true
  serverError.value = ''
  try {
    const response = await browseTelegramDrive({
      page: 1,
      page_size: 12,
      sort_by: 'message_date',
      sort_desc: true,
    })
    if (!response.success) {
      throw new Error(response.error || '加载最近入库失败')
    }
    serverItems.value = response.items
  } catch (error: any) {
    serverError.value = error.response?.data?.error || error.message || '加载最近入库失败'
  } finally {
    serverLoading.value = false
  }
}

function handleOpen(item: TelegramDriveItem) {
  if (isTelegramDriveFolder(item)) {
    ElMessage.info('可在网盘页打开相册')
    return
  }

  if (isTelegramDriveFile(item)) {
    recent.addRecent(item, 'preview')
    previewItem.value = item
  }
}

async function queueDownload(item: TelegramDriveItem, saveAs = false) {
  if (!isTelegramDriveFile(item)) return

  try {
    const task = await queueTelegramDownload(item, { saveAs })
    recent.addRecent(item, 'download')
    ElMessage.success(`已加入下载队列：${task.fileName}`)
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || '加入下载队列失败')
  }
}

function handleDownload(item: TelegramDriveItem) {
  return queueDownload(item)
}

function handleSaveAs(item: TelegramDriveItem) {
  return queueDownload(item, true)
}

function handleDelete() {
  ElMessage.info('删除请在网盘页操作')
}

function clearLocalRecent() {
  recent.clearCurrentServer()
}
</script>

<style scoped>
.pc-recent-view {
  display: grid;
  gap: 28px;
}

.pc-recent-section {
  display: grid;
  gap: 14px;
}

.pc-recent-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
}

.pc-recent-heading h2 {
  margin: 0;
  color: var(--pc-color-text);
  font-size: 17px;
  line-height: 1.25;
}

.pc-recent-skeleton {
  aspect-ratio: 4 / 3;
  background:
    linear-gradient(90deg, rgba(238, 247, 244, 0.72), rgba(255, 255, 255, 0.92), rgba(238, 247, 244, 0.72));
  background-size: 220% 100%;
  animation: pc-recent-skeleton 1.4s ease infinite;
}

.pc-recent-empty {
  min-height: 220px;
}

.pc-recent-empty-art {
  width: min(260px, 64vw);
}

@keyframes pc-recent-skeleton {
  from {
    background-position: 160% 0;
  }

  to {
    background-position: -60% 0;
  }
}
</style>
