<template>
  <el-dialog
    v-model="visible"
    width="min(560px, 92vw)"
    :show-close="false"
    :close-on-click-modal="false"
    class="welcome-dialog"
    append-to-body
  >
    <div class="welcome-container">
      <!-- 顶部樱花光晕横幅 -->
      <div class="welcome-header">
        <div class="welcome-badge">🎉 欢迎启航 · Tenant Onboarding</div>
        <h3 class="welcome-title text-gradient-sakura">欢迎加入 MistRelay 云盘空间！</h3>
        <p class="welcome-subtitle">
          您的多租户 Telegram 物理隔离专属存储频道与 DC 亲和路由已自动配置就绪。
        </p>
      </div>

      <!-- 租户当前绑定信息卡片 -->
      <div class="welcome-info-card glass-card">
        <div class="info-row">
          <span class="info-icon">📡</span>
          <span class="info-text">
            <strong>专属存储环境：</strong>
            同区 Telegram DC{{ userDc }} 物理隔离独立频道
          </span>
        </div>
        <div class="info-row">
          <span class="info-icon">🤖</span>
          <span class="info-text">
            <strong>主控服务机器人：</strong>
            <code class="bot-code">{{ botUsername ? `@${botUsername}` : '@MistRelayOfficialBot' }}</code>
          </span>
        </div>
      </div>

      <!-- 3 步极速使用要诀 -->
      <div class="welcome-tips-list">
        <div class="tip-item">
          <div class="tip-num">1</div>
          <div class="tip-detail">
            <strong>私聊机器人秒存入库：</strong>
            无需在网页上传，直接在 Telegram 中将视频、音频或文件发送给主控 Bot，秒级归档并生成直链。
          </div>
        </div>

        <div class="tip-item">
          <div class="tip-num">2</div>
          <div class="tip-detail">
            <strong>4K 秒播与 M3U 导出：</strong>
            进入【TG 网盘】在线点播，或一键导出 M3U 播放列表导入 PotPlayer、VLC、Infuse 等专业播放器。
          </div>
        </div>

        <div class="tip-item">
          <div class="tip-num">3</div>
          <div class="tip-detail">
            <strong>Aria2 磁力全速离线转存：</strong>
            直接把磁力链接（<code>magnet:?xt=...</code>）或种子发给机器人，集群后台满速下载完成后自动打包入库。
          </div>
        </div>
      </div>

      <!-- 底部控制栏 -->
      <div class="welcome-footer">
        <el-checkbox v-model="dontShowAgain" class="dont-show-checkbox">
          不再自动弹出（可随时在顶栏【新手教程】重新查阅）
        </el-checkbox>

        <div class="footer-btns-group">
          <el-button class="guide-btn" @click="handleOpenGuide">
            📖 查阅详细教程
          </el-button>
          <el-button type="primary" class="start-btn" @click="handleConfirm">
            🚀 开始探索工作台
          </el-button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'

const authStore = useAuthStore()

const visible = ref(false)
const dontShowAgain = ref(true)
const botUsername = ref('')

const userDc = computed(() => authStore.user?.dc_id || 5)

async function fetchBotInfo() {
  try {
    const { data } = await api.get('/auth/bot-info')
    if (data?.success) {
      botUsername.value = data.bot_username || data.data?.bot_username || ''
    }
  } catch {
    // 优雅容错
  }
}

function handleConfirm() {
  if (dontShowAgain.value) {
    localStorage.setItem('mistrelay_welcome_dismissed', 'true')
  }
  visible.value = false
}

function handleOpenGuide() {
  if (dontShowAgain.value) {
    localStorage.setItem('mistrelay_welcome_dismissed', 'true')
  }
  visible.value = false
  window.dispatchEvent(new CustomEvent('open-user-guide', { detail: { tab: 'quickstart' } }))
}

function checkAndShow() {
  const dismissed = localStorage.getItem('mistrelay_welcome_dismissed')
  if (!dismissed) {
    visible.value = true
  }
}

watch(
  () => authStore.user,
  (newUser) => {
    if (newUser && newUser.role !== 'admin') {
      checkAndShow()
    }
  },
  { immediate: true }
)

onMounted(() => {
  void fetchBotInfo()
  if (authStore.user && authStore.user.role !== 'admin') {
    checkAndShow()
  }
})

defineExpose({
  show: () => { visible.value = true },
  close: () => { visible.value = false }
})
</script>

<style scoped>
:deep(.el-dialog) {
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 143, 171, 0.3);
  box-shadow: 0 16px 48px rgba(255, 117, 151, 0.18);
  padding: 0;
  overflow: hidden;
}

:deep(.el-dialog__body) {
  padding: 0;
}

.welcome-container {
  padding: 24px 28px;
}

.welcome-header {
  text-align: center;
  margin-bottom: 20px;
}

.welcome-badge {
  display: inline-block;
  font-size: 11.5px;
  font-weight: 700;
  padding: 3px 12px;
  border-radius: 999px;
  background: rgba(255, 117, 151, 0.12);
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.25);
  margin-bottom: 8px;
}

.welcome-title {
  font-size: 1.3rem;
  font-weight: 800;
  margin: 0 0 6px 0;
  letter-spacing: -0.3px;
}

.welcome-subtitle {
  font-size: 13px;
  color: #6b7280;
  margin: 0;
  line-height: 1.5;
}

.welcome-info-card {
  padding: 12px 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.08) 0%, rgba(56, 189, 248, 0.08) 100%);
  border: 1px solid rgba(255, 143, 171, 0.25);
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 18px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: #374151;
}

.info-icon {
  font-size: 15px;
}

.bot-code {
  color: #ff7597;
  font-weight: 700;
  background: rgba(255, 255, 255, 0.9);
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255, 143, 171, 0.2);
}

.welcome-tips-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 22px;
}

.tip-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 143, 171, 0.18);
}

.tip-num {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: white;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.tip-detail {
  font-size: 12.5px;
  color: #4b5563;
  line-height: 1.5;
}

.tip-detail strong {
  color: #111827;
}

.welcome-footer {
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-top: 1px solid rgba(255, 143, 171, 0.2);
  padding-top: 16px;
}

.dont-show-checkbox {
  font-size: 12px;
  color: #6b7280;
}

.footer-btns-group {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.guide-btn {
  border-radius: 10px;
  font-weight: 600;
  border: 1px solid rgba(255, 143, 171, 0.3);
  color: #ff7597;
}

.guide-btn:hover {
  background: rgba(255, 117, 151, 0.08);
  border-color: #ff7597;
}

.start-btn {
  border-radius: 10px;
  font-weight: 700;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  border: none;
}

@media (max-width: 640px) {
  .welcome-container {
    padding: 18px;
  }
  .footer-btns-group {
    flex-direction: column;
    width: 100%;
  }
  .footer-btns-group .el-button {
    width: 100%;
  }
}
</style>
