<template>
  <el-drawer
    v-model="visible"
    direction="rtl"
    size="min(720px, 100vw)"
    :show-close="false"
    :with-header="false"
    class="guide-drawer"
    append-to-body
    :lock-scroll="true"
    :destroy-on-close="false"
  >
    <div class="guide-container">
      <!-- 抽屉顶部流光栏 -->
      <div class="guide-header">
        <div class="guide-header-left">
          <div class="guide-icon-badge">
            <el-icon :size="22"><Reading /></el-icon>
          </div>
          <div class="guide-title-group">
            <div class="guide-title-row">
              <h3 class="guide-title text-gradient-sakura">MistRelay 新手全景使用手册</h3>
              <span class="guide-version-tag">v3.0.0 Guide</span>
            </div>
            <p class="guide-subtitle">多租户 Telegram 频道云盘与全球边缘中继系统操作指南</p>
          </div>
        </div>
        <button class="guide-close-btn" @click="visible = false" title="关闭手册">
          <el-icon :size="18"><Close /></el-icon>
        </button>
      </div>

      <!-- 选项卡导航栏 -->
      <div class="guide-tabs-nav">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="guide-tab-btn"
          :class="{ 'is-active': activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          <span class="tab-emoji">{{ tab.emoji }}</span>
          <span class="tab-label">{{ tab.label }}</span>
        </button>
      </div>

      <!-- 选项卡正文区域 -->
      <div class="guide-body">
        <!-- 1. 快速入门 -->
        <div v-if="activeTab === 'quickstart'" class="guide-section animate-fade-in">
          <div class="guide-hero-card glass-card">
            <div class="hero-card-glow"></div>
            <h4 class="section-title">
              <span class="section-badge">01</span>
              什么是 MistRelay 多租户架构？
            </h4>
            <p class="section-desc">
              MistRelay 不是传统的单机 WebDAV 或本地存储网盘，而是将
              <strong>Telegram 官方全球无限云端</strong> 作为私有对象存储后端。
              系统通过突破性的多租户架构，让每位租户拥有物理隔离的专属空间与极速流媒体中继。
            </p>

            <div class="feature-pills-grid">
              <div class="feature-pill-item">
                <div class="pill-icon-box"><el-icon><Folder /></el-icon></div>
                <div class="pill-info">
                  <span class="pill-name">物理隔离专属存储</span>
                  <span class="pill-sub">专属 Telegram 频道独立纳管，私有资产零污染</span>
                </div>
              </div>

              <div class="feature-pill-item">
                <div class="pill-icon-box"><el-icon><Compass /></el-icon></div>
                <div class="pill-info">
                  <span class="pill-name">同区 DC 亲和调度</span>
                  <span class="pill-sub">自动匹配 DC1~DC5 协议号，网络延迟直降 70%</span>
                </div>
              </div>

              <div class="feature-pill-item">
                <div class="pill-icon-box"><el-icon><Connection /></el-icon></div>
                <div class="pill-info">
                  <span class="pill-name">55+ Bot 条带化并发</span>
                  <span class="pill-sub">读写分离切片并发拉流，彻底突破单机/单号限流</span>
                </div>
              </div>

              <div class="feature-pill-item">
                <div class="pill-icon-box"><el-icon><Share /></el-icon></div>
                <div class="pill-info">
                  <span class="pill-name">全球 VPS 边缘中继</span>
                  <span class="pill-sub">一键纳管私有 VPS 就近加速，4K/HDR 瞬时秒开</span>
                </div>
              </div>
            </div>
          </div>

          <div class="guide-step-card glass-card">
            <h4 class="section-title">
              <span class="section-badge">02</span>
              3 步极速使用工作流
            </h4>
            <div class="steps-flow">
              <div class="flow-step">
                <div class="flow-step-num">1</div>
                <div class="flow-step-content">
                  <h5>私聊发送文件或磁力链接</h5>
                  <p>在 Telegram 中向您的主控 Bot 发送任意媒体文件、视频、文档，或发送磁力下载链接。</p>
                </div>
              </div>
              <div class="flow-step-arrow"><el-icon><ArrowRight /></el-icon></div>
              <div class="flow-step">
                <div class="flow-step-num">2</div>
                <div class="flow-step-content">
                  <h5>系统全自动秒存入库</h5>
                  <p>Bot 秒级转存至您的专属存储频道，自动清洗广告水印，并即刻回传高速直链与网页播放地址。</p>
                </div>
              </div>
              <div class="flow-step-arrow"><el-icon><ArrowRight /></el-icon></div>
              <div class="flow-step">
                <div class="flow-step-num">3</div>
                <div class="flow-step-content">
                  <h5>Web 观看或导出播放列表</h5>
                  <p>登录 Web 端云盘在线点播，或一键导出 M3U 导入 PotPlayer / Infuse 畅享 4K 原画。</p>
                </div>
              </div>
            </div>

            <div class="bot-cta-box">
              <div class="bot-cta-info">
                <span class="bot-status-tag">服务就绪</span>
                <span class="bot-name-label">当前主控机器人：</span>
                <code class="bot-username-code">{{ botUsername ? `@${botUsername}` : '@MistRelayOfficialBot' }}</code>
              </div>
              <el-button
                type="primary"
                class="bot-jump-btn"
                :icon="Promotion"
                @click="openTelegramBot"
              >
                🚀 私聊专属机器人
              </el-button>
            </div>
          </div>
        </div>

        <!-- 2. 文件入库 3 步法 -->
        <div v-else-if="activeTab === 'upload'" class="guide-section animate-fade-in">
          <div class="method-card glass-card">
            <div class="method-badge method-badge--primary">方式一 · 推荐</div>
            <h4 class="method-title">Telegram 机器人私聊直投 / 频道转发</h4>
            <p class="method-desc">
              最轻量、最便捷的入库方式。无需打开网页，在手机端或电脑端 Telegram 即可随心操作。
            </p>
            <div class="method-steps-list">
              <div class="method-step-row">
                <span class="step-dot">1</span>
                <span>直接向主控机器人发送视频、图片、音频、压缩包或文档（单文件支持最高 4GB）；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">2</span>
                <span>支持将其他 Telegram 群组或公开/受限频道中的消息直接<strong>转发</strong>给机器人；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">3</span>
                <span>机器人自动入库并去除来源出处标记（防引流溯源），云盘控制台实时同步展示。</span>
              </div>
            </div>
            <div class="method-footer-action">
              <el-button size="small" type="primary" plain :icon="Promotion" @click="openTelegramBot">
                打开 Telegram 私聊
              </el-button>
            </div>
          </div>

          <div class="method-card glass-card">
            <div class="method-badge method-badge--sky">方式二 · 强力离线</div>
            <h4 class="method-title">Aria2 磁力链接 / 直链 / 种子离线转存</h4>
            <p class="method-desc">
              集成工业级 Aria2 多线程离线下载引擎。服务器后台千兆满速拉取，下载完成后全自动转存入库。
            </p>
            <div class="method-steps-list">
              <div class="method-step-row">
                <span class="step-dot">1</span>
                <span>向机器人发送磁力链接（如 <code>magnet:?xt=urn:btih:...</code>）；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">2</span>
                <span>向机器人发送任意公网文件直接下载链接（<code>http://...</code> 或 <code>https://...</code>）；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">3</span>
                <span>向机器人直接发送 <code>.torrent</code> 种子文件；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">4</span>
                <span>可在 Web 端【任务中心】实时查看下载进度条、下载速度与上传转存状态。</span>
              </div>
            </div>
            <div class="code-snippet-box">
              <div class="snippet-header">
                <span>磁力链接投递示例</span>
                <button class="copy-action-btn" @click="copyText(sampleMagnet, '磁力链接示例')">
                  <el-icon><CopyDocument /></el-icon> 复制示例
                </button>
              </div>
              <pre class="snippet-code"><code>{{ sampleMagnet }}</code></pre>
            </div>
          </div>

          <div class="method-card glass-card">
            <div class="method-badge method-badge--purple">方式三 · 破除限制</div>
            <h4 class="method-title">私密 / 受限频道资源破除采集</h4>
            <p class="method-desc">
              针对开启了“禁止保存和转发（Restrict Saving Content）”的群组或频道，全自动调动集群协议号破除限制。
            </p>
            <div class="method-steps-list">
              <div class="method-step-row">
                <span class="step-dot">1</span>
                <span>前往 Web 端【TG网盘】页面，点击顶部的 <strong>[私密/受限频道采集]</strong> 按钮；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">2</span>
                <span>输入消息链接（如 <code>https://t.me/c/1234567890/100</code>）；</span>
              </div>
              <div class="method-step-row">
                <span class="step-dot">3</span>
                <span>系统自动将该消息内的视频或媒体洗白抓取并转存至您的专属存储频道。</span>
              </div>
            </div>
            <div class="method-footer-action">
              <el-button size="small" type="success" plain :icon="MagicStick" @click="goToDriveHarvest">
                前往 TG 网盘打开采集器
              </el-button>
            </div>
          </div>
        </div>

        <!-- 3. 影音播放与播放器 -->
        <div v-else-if="activeTab === 'streaming'" class="guide-section animate-fade-in">
          <div class="guide-hero-card glass-card">
            <h4 class="section-title">
              <span class="section-badge">🎬</span>
              在线播放与第三方播放器串流指南
            </h4>
            <p class="section-desc">
              MistRelay 原生支持多 Bot 读写分离条带化聚合串流，无需将数 GB 的文件下载到本地，即可享受秒开高码率观影体验。
            </p>

            <div class="player-grid">
              <div class="player-card">
                <div class="player-header">
                  <span class="player-icon">🌐</span>
                  <h5>Web 在线播放器</h5>
                </div>
                <p>在网盘列表中点击任意视频卡片，即可调起内置网页播放器，支持多音轨切换与进度随心拖拽。</p>
              </div>

              <div class="player-card">
                <div class="player-header">
                  <span class="player-icon">📺</span>
                  <h5>PotPlayer / VLC (PC)</h5>
                </div>
                <p>复制直链或导出 M3U 播放列表，直接拖入 PotPlayer / VLC，享受显卡硬件加速解码与原生 HDR 原画。</p>
              </div>

              <div class="player-card">
                <div class="player-header">
                  <span class="player-icon">🍎</span>
                  <h5>Infuse / IINA (Mac & Apple TV)</h5>
                </div>
                <p>支持将生成的 M3U 导入 Infuse 播放列表，在客厅大屏 Apple TV 或 iPad 上享受影院级杜比视界。</p>
              </div>
            </div>

            <div class="guide-tip-box">
              <el-icon class="tip-icon"><InfoFilled /></el-icon>
              <div class="tip-content">
                <strong>💡 极速串流秘诀：</strong>
                若在网盘多选了多部剧集，可直接点击底部的 <code>导出 M3U 播放列表</code>
                按钮，一键下载标准播放列表文件，双击即可在本地播放器中连续播放整季剧集！
              </div>
            </div>
          </div>
        </div>

        <!-- 4. 边缘分流 -->
        <div v-else-if="activeTab === 'edge'" class="guide-section animate-fade-in">
          <div class="guide-hero-card glass-card">
            <h4 class="section-title">
              <span class="section-badge">⚡</span>
              私有 VPS 边缘分流纳管
            </h4>
            <p class="section-desc">
              由于 Telegram 官方机房均位于欧美和新加坡，跨国直连可能受到公网 QoS 限速。
              您可以将闲置的香港、日本或任意地区私有 VPS 纳管为边缘分流节点，打造专属于您的 0ms 边缘 CDN！
            </p>

            <div class="edge-steps-list">
              <div class="edge-step-item">
                <div class="edge-step-badge">步骤 1</div>
                <div class="edge-step-detail">
                  <h6>进入边缘分流控制台</h6>
                  <p>在左侧导航栏点击【边缘分流】页面，即可查看系统当前共享节点与您的专属节点。</p>
                </div>
              </div>

              <div class="edge-step-item">
                <div class="edge-step-badge">步骤 2</div>
                <div class="edge-step-detail">
                  <h6>一键 SSH 部署 Worker</h6>
                  <p>点击“一键纳管节点”，填入 VPS 的 IP 地址与 SSH 登录凭证，系统将全自动完成 Docker 容器初始化与低延迟健康巡检。</p>
                </div>
              </div>

              <div class="edge-step-item">
                <div class="edge-step-badge">步骤 3</div>
                <div class="edge-step-detail">
                  <h6>享受专属就近加速</h6>
                  <p>纳管完成后，您在网盘中播放视频或下载文件时，系统将智能优选并调度至您的专属节点，彻底告别卡顿与加载圈。</p>
                </div>
              </div>
            </div>

            <div class="guide-tip-box">
              <el-icon class="tip-icon"><Check /></el-icon>
              <div class="tip-content">
                <strong>🔒 安全脱敏保障：</strong>
                边缘节点仅负责媒体数据块中继与本地热点缓存，不保存您的账号密码与频道凭证，安全无泄露风险。
              </div>
            </div>
          </div>
        </div>

        <!-- 5. Bot 指令与 FAQ -->
        <div v-else-if="activeTab === 'commands'" class="guide-section animate-fade-in">
          <div class="guide-hero-card glass-card">
            <h4 class="section-title">
              <span class="section-badge">🤖</span>
              Telegram 机器人指令速查表
            </h4>

            <div class="commands-table">
              <div class="command-row">
                <div class="command-syntax">
                  <code>/start</code>
                </div>
                <div class="command-desc">
                  <span>查看服务运行状态、已绑定的专属存储频道与快速功能入口</span>
                </div>
                <button class="cmd-copy-btn" @click="copyText('/start', '指令 /start')">
                  <el-icon><CopyDocument /></el-icon> 复制
                </button>
              </div>

              <div class="command-row">
                <div class="command-syntax">
                  <code>/help</code>
                </div>
                <div class="command-desc">
                  <span>调出系统全套使用说明、格式规范与离线下载说明</span>
                </div>
                <button class="cmd-copy-btn" @click="copyText('/help', '指令 /help')">
                  <el-icon><CopyDocument /></el-icon> 复制
                </button>
              </div>

              <div class="command-row">
                <div class="command-syntax">
                  <code>/register</code>
                </div>
                <div class="command-desc">
                  <span>获取注册 6 位授权码，或查看已绑定的同 DC 专属存储频道</span>
                </div>
                <button class="cmd-copy-btn" @click="copyText('/register', '指令 /register')">
                  <el-icon><CopyDocument /></el-icon> 复制
                </button>
              </div>
            </div>
          </div>

          <div class="faq-container">
            <h4 class="faq-main-title">常见问题解答 (FAQ)</h4>

            <div class="faq-item glass-card">
              <div class="faq-q">❓ 为什么在 Web 网盘里没有看到“上传文件”按钮？</div>
              <div class="faq-a">
                MistRelay 采用更现代的 Telegram 原生投递体系！您无需在浏览器中耗时挂机上传，只需要在 Telegram 手机或桌面端把文件直接发给机器人，或把磁力链接发给机器人，集群全自动在后台满速存入您的专属云盘。
              </div>
            </div>

            <div class="faq-item glass-card">
              <div class="faq-q">❓ 播放 4K 或大文件视频卡顿怎么解决？</div>
              <div class="faq-a">
                ① 在网盘顶部的【边缘加速】下拉框切换至延迟最低的边缘节点；<br />
                ② 多选文件后点击【导出 M3U 播放列表】，导入 PotPlayer 或 Infuse 启用显卡硬件加速解码；<br />
                ③ 前往【边缘分流】页面挂载一台您的专属私有 VPS 节点。
              </div>
            </div>

            <div class="faq-item glass-card">
              <div class="faq-q">❓ 遇到使用困难或直链失效如何反馈？</div>
              <div class="faq-a">
                您可以在左侧菜单进入【AI 客服】进行 24 小时实时问答，或者加入 Telegram 官方交流群获取协助。
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 抽屉底部操作栏 -->
      <div class="guide-footer">
        <el-button class="footer-btn" @click="openTelegramBot" :icon="Promotion">
          私聊专属机器人 ({{ botUsername ? `@${botUsername}` : '@MistRelay' }})
        </el-button>
        <el-button type="primary" class="footer-btn footer-btn--primary" @click="visible = false">
          明白了，开始使用
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Reading,
  Close,
  Folder,
  Compass,
  Connection,
  Share,
  ArrowRight,
  Promotion,
  CopyDocument,
  MagicStick,
  InfoFilled,
  Check
} from '@element-plus/icons-vue'
import { api } from '@/api'

const router = useRouter()

const visible = ref(false)
const activeTab = ref('quickstart')

const botUsername = ref('')
const botDeepLink = ref('')

const sampleMagnet = 'magnet:?xt=urn:btih:d6b6e4e5e7fa9b2c8a1e3f5b7c9d0e1f2a3b4c5d&dn=SampleVideo_4K'

const tabs = [
  { id: 'quickstart', emoji: '🚀', label: '快速入门' },
  { id: 'upload', emoji: '📥', label: '文件入库3步法' },
  { id: 'streaming', emoji: '🎬', label: '影音流播与串流' },
  { id: 'edge', emoji: '⚡', label: '私有VPS边缘分流' },
  { id: 'commands', emoji: '🤖', label: 'Bot指令与FAQ' }
]

async function fetchBotInfo() {
  try {
    const { data } = await api.get('/auth/bot-info')
    if (data?.success) {
      const uname = data.bot_username || data.data?.bot_username || ''
      botUsername.value = uname
      botDeepLink.value = data.register_deep_link || (uname ? `https://t.me/${uname}?start=help` : '')
    }
  } catch {
    // 优雅容错
  }
}

function openTelegramBot() {
  const url = botDeepLink.value || (botUsername.value ? `https://t.me/${botUsername.value}?start=help` : 'https://t.me')
  window.open(url, '_blank')
}

async function copyText(text: string, label: string) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success(`已复制 ${label}`)
  } catch {
    ElMessage.error('复制失败，请手动选中复制')
  }
}

function goToDriveHarvest() {
  visible.value = false
  router.push('/drive')
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent('open-drive-harvester'))
  }, 300)
}

function open(tab = 'quickstart') {
  activeTab.value = tab
  visible.value = true
}

function handleOpenGuideEvent(e: Event) {
  const customEvent = e as CustomEvent<{ tab?: string }>
  open(customEvent.detail?.tab || 'quickstart')
}

onMounted(() => {
  void fetchBotInfo()
  window.addEventListener('open-user-guide', handleOpenGuideEvent)
})

onUnmounted(() => {
  window.removeEventListener('open-user-guide', handleOpenGuideEvent)
})

defineExpose({
  open,
  close: () => { visible.value = false }
})
</script>


<style>
/* 全局抽屉挂载样式 (append-to-body 穿透与层级置顶) */
.guide-drawer.el-drawer {
  background: #ffffff !important;
  backdrop-filter: blur(28px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(28px) saturate(180%) !important;
  border-left: 1px solid rgba(255, 143, 171, 0.35) !important;
  box-shadow: -16px 0 48px rgba(255, 117, 151, 0.22), -4px 0 16px rgba(56, 189, 248, 0.15) !important;
  overflow: hidden !important;
}

.guide-drawer .el-drawer__body {
  padding: 0 !important;
  overflow: hidden !important;
  height: 100% !important;
  display: flex !important;
  flex-direction: column !important;
}

.el-overlay.is-drawer:has(.guide-drawer) {
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  background-color: rgba(15, 23, 42, 0.4) !important;
}
</style>

<style scoped>
:deep(.el-drawer) {
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(24px);
  border-left: 1px solid rgba(255, 143, 171, 0.28);
  box-shadow: -8px 0 36px rgba(255, 117, 151, 0.15);
}

.guide-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  color: #1f2937;
}

/* 顶部栏 */
.guide-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid rgba(255, 143, 171, 0.2);
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.08) 0%, rgba(56, 189, 248, 0.05) 100%);
}

.guide-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.guide-icon-badge {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.35);
  flex-shrink: 0;
}

.guide-title-group {
  display: flex;
  flex-direction: column;
}

.guide-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.guide-title {
  font-size: 1.15rem;
  font-weight: 800;
  margin: 0;
  letter-spacing: -0.3px;
}

.guide-version-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 117, 151, 0.12);
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.3);
}

.guide-subtitle {
  font-size: 12px;
  color: #6b7280;
  margin: 2px 0 0 0;
}

.guide-close-btn {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  border: 1px solid rgba(255, 143, 171, 0.2);
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  cursor: pointer;
  transition: all 0.2s ease;
}

.guide-close-btn:hover {
  background: rgba(255, 117, 151, 0.15);
  color: #ff7597;
  transform: rotate(90deg);
}

/* 导航 Tabs */
.guide-tabs-nav {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  background: rgba(255, 255, 255, 0.9);
  border-bottom: 1px solid rgba(255, 143, 171, 0.18);
  overflow-x: auto;
  scrollbar-width: none;
  flex-shrink: 0;
}

.guide-tabs-nav::-webkit-scrollbar {
  display: none;
}

.guide-tab-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: #4b5563;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.guide-tab-btn:hover {
  background: rgba(255, 117, 151, 0.08);
  color: #ff7597;
}

.guide-tab-btn.is-active {
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.15) 0%, rgba(56, 189, 248, 0.12) 100%);
  border-color: rgba(255, 117, 151, 0.35);
  color: #ff7597;
  box-shadow: 0 2px 8px rgba(255, 117, 151, 0.15);
}

.tab-emoji {
  font-size: 14px;
}

/* 内容正文 */
.guide-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background: #fcf8fa;
}

.guide-body::-webkit-scrollbar {
  width: 5px;
}

.guide-body::-webkit-scrollbar-thumb {
  background: rgba(255, 117, 151, 0.25);
  border-radius: 999px;
}

/* 卡片样式 */
.guide-hero-card,
.guide-step-card,
.method-card {
  padding: 20px;
  border-radius: 16px;
  position: relative;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid rgba(255, 143, 171, 0.28);
  box-shadow: 0 4px 18px rgba(255, 117, 151, 0.08);
  margin-bottom: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 10px 0;
}

.section-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 6px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: white;
}

.section-desc {
  font-size: 13.5px;
  color: #4b5563;
  line-height: 1.6;
  margin: 0 0 16px 0;
}

.feature-pills-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.feature-pill-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff8f9;
  border: 1px solid rgba(255, 143, 171, 0.22);
}

.pill-icon-box {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(255, 117, 151, 0.12);
  color: #ff7597;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.pill-info {
  display: flex;
  flex-direction: column;
}

.pill-name {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.pill-sub {
  font-size: 11px;
  color: #6b7280;
  line-height: 1.3;
  margin-top: 2px;
}

/* 流程图 */
.steps-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
}

.flow-step {
  flex: 1;
  background: #fff8f9;
  border: 1px solid rgba(255, 143, 171, 0.22);
  border-radius: 12px;
  padding: 14px;
  position: relative;
}

.flow-step-num {
  position: absolute;
  top: -8px;
  left: 10px;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  background: #ff7597;
  color: white;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(255, 117, 151, 0.4);
}

.flow-step-content h5 {
  font-size: 12.5px;
  font-weight: 700;
  color: #111827;
  margin: 4px 0 4px 0;
}

.flow-step-content p {
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
  margin: 0;
}

.flow-step-arrow {
  color: #ff7597;
  display: flex;
  align-items: center;
  font-size: 14px;
}

.bot-cta-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.12) 0%, rgba(56, 189, 248, 0.08) 100%);
  border: 1px solid rgba(255, 117, 151, 0.3);
}

.bot-cta-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.bot-status-tag {
  font-size: 11px;
  font-weight: 700;
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 2px 6px;
  border-radius: 6px;
}

.bot-name-label {
  font-size: 12px;
  color: #4b5563;
}

.bot-username-code {
  font-size: 12px;
  font-weight: 700;
  color: #ff7597;
  background: rgba(255, 255, 255, 0.8);
  padding: 2px 6px;
  border-radius: 6px;
}

.bot-jump-btn {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  border: none;
  font-weight: 700;
  border-radius: 10px;
}

/* 方式卡片 */
.method-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 999px;
  margin-bottom: 8px;
}

.method-badge--primary {
  background: rgba(255, 117, 151, 0.15);
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.3);
}

.method-badge--sky {
  background: rgba(56, 189, 248, 0.15);
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.method-badge--purple {
  background: rgba(168, 85, 247, 0.15);
  color: #9333ea;
  border: 1px solid rgba(168, 85, 247, 0.3);
}

.method-title {
  font-size: 15px;
  font-weight: 800;
  color: #111827;
  margin: 0 0 6px 0;
}

.method-desc {
  font-size: 13px;
  color: #4b5563;
  margin: 0 0 12px 0;
  line-height: 1.5;
}

.method-steps-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.method-step-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
  color: #374151;
  line-height: 1.5;
}

.step-dot {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: rgba(255, 117, 151, 0.15);
  color: #ff7597;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.code-snippet-box {
  background: #1e293b;
  border-radius: 12px;
  padding: 10px 14px;
  color: #e2e8f0;
  margin-top: 8px;
}

.snippet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: #94a3b8;
  margin-bottom: 6px;
}

.copy-action-btn {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #f1f5f9;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s ease;
}

.copy-action-btn:hover {
  background: #ff7597;
  border-color: #ff7597;
}

.snippet-code {
  margin: 0;
  font-family: monospace;
  font-size: 11.5px;
  word-break: break-all;
  white-space: pre-wrap;
  color: #38bdf8;
}

/* 播放器卡片 */
.player-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}

.player-card {
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.2);
  border-radius: 12px;
  padding: 12px;
}

.player-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.player-icon {
  font-size: 16px;
}

.player-header h5 {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
  margin: 0;
}

.player-card p {
  font-size: 11.5px;
  color: #6b7280;
  line-height: 1.4;
  margin: 0;
}

.guide-tip-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.25);
  font-size: 12.5px;
  color: #0369a1;
  line-height: 1.5;
}

.tip-icon {
  font-size: 16px;
  color: #0284c7;
  flex-shrink: 0;
  margin-top: 2px;
}

/* 边缘节点步骤 */
.edge-steps-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.edge-step-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff8f9;
  border: 1px solid rgba(255, 143, 171, 0.22);
}

.edge-step-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 6px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: white;
  flex-shrink: 0;
}

.edge-step-detail h6 {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 4px 0;
}

.edge-step-detail p {
  font-size: 12px;
  color: #6b7280;
  margin: 0;
  line-height: 1.4;
}

/* Bot 指令表 */
.commands-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.command-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-radius: 12px;
  background: #fff8f9;
  border: 1px solid rgba(255, 143, 171, 0.22);
  gap: 12px;
}

.command-syntax code {
  font-family: monospace;
  font-size: 13px;
  font-weight: 800;
  color: #ff7597;
  background: rgba(255, 117, 151, 0.12);
  padding: 3px 8px;
  border-radius: 6px;
}

.command-desc {
  flex: 1;
  font-size: 12.5px;
  color: #4b5563;
}

.cmd-copy-btn {
  background: rgba(255, 117, 151, 0.1);
  border: 1px solid rgba(255, 117, 151, 0.25);
  color: #ff7597;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s ease;
}

.cmd-copy-btn:hover {
  background: #ff7597;
  color: white;
}

/* FAQ */
.faq-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.faq-main-title {
  font-size: 14px;
  font-weight: 800;
  color: #111827;
  margin: 4px 0 2px 0;
}

.faq-item {
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff8f9;
  border: 1px solid rgba(255, 143, 171, 0.22);
}

.faq-q {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 4px;
}

.faq-a {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}

/* 底部操作区 */
.guide-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 14px 24px;
  border-top: 1px solid rgba(255, 143, 171, 0.2);
  background: rgba(255, 255, 255, 0.8);
}

.footer-btn {
  border-radius: 10px;
  font-weight: 600;
}

.footer-btn--primary {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  border: none;
}

@media (max-width: 768px) {
  .guide-header {
    padding: 12px 14px;
    gap: 8px;
  }
  .guide-icon-badge {
    width: 34px;
    height: 34px;
    border-radius: 10px;
  }
  .guide-title {
    font-size: 0.95rem;
  }
  .guide-version-tag {
    display: none;
  }
  .guide-subtitle {
    font-size: 11px;
  }
  .guide-body {
    padding: 16px;
  }
  .feature-pills-grid,
  .player-grid {
    grid-template-columns: 1fr;
  }
  .steps-flow {
    flex-direction: column;
  }
  .flow-step-arrow {
    transform: rotate(90deg);
    margin: 4px 0;
  }
  .guide-footer {
    flex-direction: column;
    padding: 12px 16px;
  }
  .footer-btn {
    width: 100%;
  }
}
</style>
