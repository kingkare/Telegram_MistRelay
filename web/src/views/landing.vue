<template>
  <div class="landing-page">
    <!-- 背景流光装饰光晕与赛博樱花极光 Canvas -->
    <div class="landing-bg">
      <canvas ref="canvasRef" class="sakura-cosmic-canvas"></canvas>
      <div class="bg-glow bg-glow-1"></div>
      <div class="bg-glow bg-glow-2"></div>
      <div class="bg-glow bg-glow-3"></div>
      <div class="bg-grid-overlay"></div>
      <div
        class="mouse-spotlight"
        :style="{
          transform: `translate3d(${mousePos.x - 250}px, ${mousePos.y - 250}px, 0)`,
          opacity: mouseInWindow ? 1 : 0
        }"
      ></div>
    </div>

    <!-- 顶部毛玻璃导航栏 -->
    <header class="landing-header glass-card">
      <div class="header-container">
        <!-- 品牌标识 -->
        <div class="brand-group" @click="scrollToTop">
          <div class="brand-icon-wrapper">
            <el-icon :size="24" class="brand-icon"><Cpu /></el-icon>
          </div>
          <div class="brand-text-wrapper">
            <span class="brand-title">MistRelay</span>
            <span class="brand-badge">Multi-Tenant Cloud</span>
          </div>
        </div>

        <!-- 桌面端锚点导航 -->
        <nav class="nav-links">
          <a href="#features" class="nav-link">核心特性</a>
          <a href="#architecture" class="nav-link">DC亲和架构</a>
          <a href="#edge" class="nav-link">全球边缘</a>
          <a href="#quickstart" class="nav-link">快速接入</a>
        </nav>

        <!-- 系统运行状态胶囊 -->
        <div class="status-capsule" :class="{ 'is-ready': systemReady }">
          <span class="status-dot"></span>
          <span class="status-label">{{ systemStatusText }}</span>
          <span v-if="systemVersion" class="status-ver">{{ systemVersion }}</span>
        </div>

        <!-- 动作操作区 -->
        <div class="header-actions">
          <template v-if="authStore.isLoggedIn">
            <el-button
              type="primary"
              class="action-btn action-btn--primary glow-btn"
              @click="goToDashboard"
            >
              <el-icon><Monitor /></el-icon>
              <span>进入工作台</span>
            </el-button>
          </template>
          <template v-else>
            <el-button
              class="action-btn action-btn--login"
              text
              @click="goToLogin"
            >
              控制台登录
            </el-button>
            <el-button
              type="primary"
              class="action-btn action-btn--primary glow-btn"
              @click="goToRegister"
            >
              <el-icon><Promotion /></el-icon>
              <span>立即开通租户</span>
            </el-button>
          </template>

          <!-- 移动端汉堡菜单触发器 -->
          <button class="mobile-menu-btn" @click="mobileMenuOpen = !mobileMenuOpen" aria-label="Toggle Menu">
            <el-icon :size="22"><Operation /></el-icon>
          </button>
        </div>
      </div>

      <!-- 移动端下拉折叠菜单 -->
      <transition name="slide-down">
        <div v-if="mobileMenuOpen" class="mobile-nav-panel glass-card">
          <a href="#features" class="mobile-nav-link" @click="mobileMenuOpen = false">核心特性</a>
          <a href="#architecture" class="mobile-nav-link" @click="mobileMenuOpen = false">DC亲和架构</a>
          <a href="#edge" class="mobile-nav-link" @click="mobileMenuOpen = false">全球边缘</a>
          <a href="#quickstart" class="mobile-nav-link" @click="mobileMenuOpen = false">快速接入</a>
          <div class="mobile-actions">
            <el-button v-if="!authStore.isLoggedIn" class="mobile-action-btn" @click="goToLogin">控制台登录</el-button>
            <el-button type="primary" class="mobile-action-btn glow-btn" @click="authStore.isLoggedIn ? goToDashboard() : goToRegister()">
              {{ authStore.isLoggedIn ? '进入工作台' : '立即开通租户' }}
            </el-button>
          </div>
        </div>
      </transition>
    </header>

    <!-- 首屏 Hero 区域 -->
    <section class="hero-section">
      <div class="hero-content animate-fade-in">
        <div class="hero-pill">
          <span class="hero-pill-badge">v0.2 Enterprise</span>
          <span class="hero-pill-text">物理隔离专属频道 · 动态 DC 亲和 · 55+ Bot 条带化并发 · 边缘加速</span>
        </div>

        <h1 class="hero-title">
          新一代多租户 <span class="text-gradient-sakura">Telegram 频道云盘</span>
          <br />与 <span class="text-gradient-sky">全球边缘中继系统</span>
        </h1>

        <p class="hero-description">
          打破 Telegram 单机流控与存储局限。为每位租户提供独立的同 DC 物理隔离专属存储频道，依托 55+ 机器人集群动态条带化分流与私有 VPS 边缘分发，实现 4K/HDR 超高清视频秒级起播与海量资产离线转存。
        </p>

        <!-- CTA 按钮群 -->
        <div class="hero-cta-group">
          <el-button
            type="primary"
            size="large"
            class="hero-cta-btn hero-cta-btn--primary glow-btn"
            @click="authStore.isLoggedIn ? goToDashboard() : goToRegister()"
          >
            <el-icon><Promotion /></el-icon>
            <span>{{ authStore.isLoggedIn ? '进入个人工作台' : '免费开通专属租户' }}</span>
          </el-button>

          <a href="#architecture" class="hero-cta-btn hero-cta-btn--secondary">
            <el-icon><DataLine /></el-icon>
            <span>技术架构解析</span>
          </a>

          <a
            v-if="botRegisterUrl"
            :href="botRegisterUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="hero-cta-btn hero-cta-btn--tg"
          >
            <el-icon><Link /></el-icon>
            <span>私聊 @{{ botUsername || 'Bot' }} 注册</span>
          </a>
        </div>

        <!-- 关键实时指标预览看板 (Hero Mockup with 3D Tilt & Specular Glare) -->
        <div
          ref="mockupRef"
          class="hero-dashboard-mockup glass-card card-hover"
          :style="{
            transform: `perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`
          }"
          @mousemove="onMockupMouseMove"
          @mouseleave="onMockupMouseLeave"
        >
          <div
            class="mockup-glare"
            :style="{
              opacity: isHoveringMockup ? 1 : 0,
              background: `radial-gradient(circle at ${glareX}% ${glareY}%, rgba(255, 255, 255, 0.35) 0%, transparent 65%)`
            }"
          ></div>
          <div class="mockup-header">
            <div class="mockup-dots">
              <span class="dot dot-red"></span>
              <span class="dot dot-yellow"></span>
              <span class="dot dot-green"></span>
            </div>
            <div class="mockup-title">
              <el-icon><Connection /></el-icon>
              <span>MistRelay 实时集群调度与租户隔离拓扑</span>
            </div>
            <div class="mockup-badge">
              <span class="pulse-indicator"></span>
              Live Dynamic Cluster
            </div>
          </div>

          <div class="mockup-body">
            <div class="mockup-grid">
              <!-- 指标 1: 物理专属存储 -->
              <div class="mockup-stat-card">
                <div class="mockup-stat-icon icon-storage">
                  <el-icon><Folder /></el-icon>
                </div>
                <div class="mockup-stat-info">
                  <span class="mockup-stat-label">租户专属存储频道</span>
                  <span class="mockup-stat-value text-gradient-sakura">物理隔离 · 零泄漏</span>
                  <span class="mockup-stat-desc">同区原生 DC 绑定 · 私密频道转存</span>
                </div>
              </div>

              <!-- 指标 2: 条带化并发 -->
              <div class="mockup-stat-card">
                <div class="mockup-stat-icon icon-speed">
                  <el-icon><Lightning /></el-icon>
                </div>
                <div class="mockup-stat-info">
                  <span class="mockup-stat-label">Bot 阵列条带化分流</span>
                  <span class="mockup-stat-value text-gradient-sky">55+ 节点并发预取</span>
                  <span class="mockup-stat-desc">突破单机限流 · 4K/HDR 秒级起播</span>
                </div>
              </div>

              <!-- 指标 3: 全球边缘节点 -->
              <div class="mockup-stat-card">
                <div class="mockup-stat-icon icon-edge">
                  <el-icon><Share /></el-icon>
                </div>
                <div class="mockup-stat-info">
                  <span class="mockup-stat-label">全球 VPS 边缘中继</span>
                  <span class="mockup-stat-value text-gradient-sakura">就近缓存 · 智能路由</span>
                  <span class="mockup-stat-desc">私有 VPS 纳管 · 独立流量计量</span>
                </div>
              </div>
            </div>

            <!-- 动态传输带模拟 (条带化并发光纤与实时吞吐流水线) -->
            <div class="mockup-stream-bar">
              <div class="stream-info">
                <span class="stream-badge">并发流媒体管道</span>
                <span class="stream-text">Aria2 离线转存 ➜ 同区 BotStriping 读写分离 ➜ 边缘分流直链输出</span>
              </div>
              <div class="stream-pipeline-track">
                <div class="pipeline-laser"></div>
                <div class="pipeline-packet packet-1"></div>
                <div class="pipeline-packet packet-2"></div>
                <div class="pipeline-packet packet-3"></div>
              </div>
              <div class="stream-stats">
                <span class="stream-stat-item"><span class="stat-dot-pulse"></span> 4K/HDR 60fps · 86.4 MB/s</span>
                <span class="stream-stat-item">⚡ 0ms 跨区授权损耗</span>
                <span class="stream-stat-item">🛡️ 智能去广告洗白</span>
                <span class="stream-stat-item">🔒 AES-256 凭证纳管</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 核心四大支柱 Section -->
    <section id="features" class="section-container">
      <div class="section-header">
        <span class="section-subtitle-tag">CORE CAPABILITIES</span>
        <h2 class="section-title">专为高吞吐、强隔离与全球分流而生</h2>
        <p class="section-desc">从底层协议架构到前台视觉交互，每一处设计均围绕多租户安全与极致速度打磨</p>
      </div>

      <div class="features-grid">
        <!-- 特性 1 -->
        <div class="feature-card glass-card card-hover">
          <div class="feature-card-glow feature-card-glow--sakura"></div>
          <div class="feature-icon-box bg-sakura-light">
            <el-icon :size="28" class="text-pink-500"><FolderChecked /></el-icon>
          </div>
          <h3 class="feature-card-title">物理隔离专属存储频道</h3>
          <p class="feature-card-text">
            每位租户拥有独立自动纳管的 Telegram 专属频道作为对象存储后端。不同租户文件物理完全隔离，彻底避免数据泄漏与权限混杂；系统更可针对租户账号所在区域全自动匹配同 DC 存储。
          </p>
          <div class="feature-tags">
            <span class="feature-tag">物理存储隔离</span>
            <span class="feature-tag">同 DC 原生匹配</span>
            <span class="feature-tag">频道无痕转存</span>
          </div>
        </div>

        <!-- 特性 2 -->
        <div class="feature-card glass-card card-hover">
          <div class="feature-card-glow feature-card-glow--sky"></div>
          <div class="feature-icon-box bg-sky-light">
            <el-icon :size="28" class="text-sky-500"><Connection /></el-icon>
          </div>
          <h3 class="feature-card-title">多 Bot 集群条带化并发</h3>
          <p class="feature-card-text">
            首创免加频道公开探测与读写分离架构，突破 Telegram 官方单 Bot 限流及单号 20 机限制。配合动态条带化并发拉流引擎，将大文件与 4K 超清视频切片分发，在线流播真正告别缓冲。
          </p>
          <div class="feature-tags">
            <span class="feature-tag">免加频道分流</span>
            <span class="feature-tag">条带化并发预取</span>
            <span class="feature-tag">4K / HDR 秒播</span>
          </div>
        </div>

        <!-- 特性 3 -->
        <div class="feature-card glass-card card-hover">
          <div class="feature-card-glow feature-card-glow--indigo"></div>
          <div class="feature-icon-box bg-indigo-light">
            <el-icon :size="28" class="text-indigo-500"><Share /></el-icon>
          </div>
          <h3 class="feature-card-title">全球 VPS 边缘分流网络</h3>
          <p class="feature-card-text">
            租户可将自己的私有 VPS 节点通过自动化异步 SSH 一键纳管部署，将传输节点推至访客身边。系统提供双向流量脱敏计量、全自动健康巡检自愈与智能低延迟节点调度分流。
          </p>
          <div class="feature-tags">
            <span class="feature-tag">私有 VPS 纳管</span>
            <span class="feature-tag">一键 SSH 部署</span>
            <span class="feature-tag">就近边缘加速</span>
          </div>
        </div>

        <!-- 特性 4 -->
        <div class="feature-card glass-card card-hover">
          <div class="feature-card-glow feature-card-glow--amber"></div>
          <div class="feature-icon-box bg-amber-light">
            <el-icon :size="28" class="text-amber-500"><Download /></el-icon>
          </div>
          <h3 class="feature-card-title">全协议离线下载与智能洗白</h3>
          <p class="feature-card-text">
            集成工业级 Aria2 多线程下载引擎，支持 HTTP、HTTPS、磁力链接与 BT 种子全天候离线转存入库。内置智能内容净化器，自动去除第三方引流广告水印与转发来源标，专属云盘纯净无瑕。
          </p>
          <div class="feature-tags">
            <span class="feature-tag">磁力 / BT 离线</span>
            <span class="feature-tag">去广告智能清洗</span>
            <span class="feature-tag">来源标抹除</span>
          </div>
        </div>
      </div>
    </section>

    <!-- DC 亲和与调度架构 Section -->
    <section id="architecture" class="section-container bg-surface-subtle">
      <div class="section-header">
        <span class="section-subtitle-tag">DC-AWARE SCHEDULING</span>
        <h2 class="section-title">Telegram 全球 5 大数据中心亲和矩阵</h2>
        <p class="section-desc">基于原生归属与热会话追踪的三级亲和调度算法，彻底规避跨洋网络延迟</p>
      </div>

      <!-- DC 矩阵展示卡 -->
      <div class="dc-matrix-grid">
        <div class="dc-card glass-card card-hover" :class="{ 'dc-card--highlight': activeDc === 5 }" @mouseenter="activeDc = 5">
          <div v-if="activeDc === 5" class="dc-card-radar-pulse"></div>
          <div class="dc-card-badge">DC5 · Singapore</div>
          <div class="dc-card-title">亚太极速直连</div>
          <p class="dc-card-desc">针对中国大陆与亚太用户优化的低延迟数据中心，同区会话调度首选，延迟极低。</p>
          <div class="dc-card-meta">
            <span>原生亲和评分: 0.0</span>
            <span class="text-emerald-500">超低延迟推荐</span>
          </div>
        </div>

        <div class="dc-card glass-card card-hover" :class="{ 'dc-card--highlight': activeDc === 2 }" @mouseenter="activeDc = 2">
          <div class="dc-card-badge">DC2 / DC4 · Europe</div>
          <div class="dc-card-title">欧洲核心专线</div>
          <p class="dc-card-desc">位于阿姆斯特丹核心骨干网，Telegram 媒体中继高密集区，热会话复用率最高。</p>
          <div class="dc-card-meta">
            <span>热备亲和评分: 0.8</span>
            <span class="text-sky-500">高吞吐储备</span>
          </div>
        </div>

        <div class="dc-card glass-card card-hover" :class="{ 'dc-card--highlight': activeDc === 1 }" @mouseenter="activeDc = 1">
          <div class="dc-card-badge">DC1 · US West</div>
          <div class="dc-card-title">美西极速节点</div>
          <p class="dc-card-desc">美西硅谷与迈阿密分区，面向北美及跨洋边缘节点的极速转存通道。</p>
          <div class="dc-card-meta">
            <span>原生亲和评分: 0.0</span>
            <span class="text-sky-500">同区直连</span>
          </div>
        </div>

        <div class="dc-card glass-card card-hover" :class="{ 'dc-card--highlight': activeDc === 3 }" @mouseenter="activeDc = 3">
          <div class="dc-card-badge">DC3 · US East</div>
          <div class="dc-card-title">美东热备集群</div>
          <p class="dc-card-desc">美东核心算力节点，在同区高负载时平滑溢出接管，并在调用后自愈晋升热备。</p>
          <div class="dc-card-meta">
            <span>冷溢出评分: 2.0</span>
            <span class="text-amber-500">弹性自愈</span>
          </div>
        </div>
      </div>

      <!-- 数据流转全景步骤 -->
      <div class="architecture-flow-box glass-card">
        <h3 class="flow-box-title">
          <el-icon><RefreshRight /></el-icon>
          <span>多租户全链路请求分流模型</span>
        </h3>
        <div class="flow-steps">
          <div class="flow-step">
            <div class="flow-step-num">1</div>
            <div class="flow-step-content">
              <h4>访客客户端请求</h4>
              <p>播放器或下载器发起 HTTP 206 Range 范围请求</p>
            </div>
          </div>
          <div class="flow-arrow">
            <div class="flow-laser-track">
              <span class="laser-dot"></span>
            </div>
            <el-icon><ArrowRight /></el-icon>
          </div>
          <div class="flow-step">
            <div class="flow-step-num">2</div>
            <div class="flow-step-content">
              <h4>私有边缘分流</h4>
              <p>就近边缘 Worker 探测延迟并纳管缓存与会话</p>
            </div>
          </div>
          <div class="flow-arrow">
            <div class="flow-laser-track">
              <span class="laser-dot"></span>
            </div>
            <el-icon><ArrowRight /></el-icon>
          </div>
          <div class="flow-step">
            <div class="flow-step-num">3</div>
            <div class="flow-step-content">
              <h4>同区 DC 亲和聚合</h4>
              <p>优选同区 Bot 阵列，条带化并发拉取分片</p>
            </div>
          </div>
          <div class="flow-arrow">
            <div class="flow-laser-track">
              <span class="laser-dot"></span>
            </div>
            <el-icon><ArrowRight /></el-icon>
          </div>
          <div class="flow-step">
            <div class="flow-step-num">4</div>
            <div class="flow-step-content">
              <h4>专属频道物理入库</h4>
              <p>媒体物理持久化于租户专属隔离频道，资产绝对独立</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 全球边缘中继 Section -->
    <section id="edge" class="section-container">
      <div class="section-header">
        <span class="section-subtitle-tag">EDGE WORKER NODES</span>
        <h2 class="section-title">私有边缘节点纳管：算力推至离您最近的端点</h2>
        <p class="section-desc">将您的闲置云服务器一键改造为高性能流媒体边缘加速中继节点</p>
      </div>

      <div class="edge-showcase-box glass-card">
        <div class="edge-showcase-left">
          <div class="edge-pill-tag">SSH 零侵入异步纳管</div>
          <h3 class="edge-showcase-title">租户专属 VPS，一键入网加速</h3>
          <p class="edge-showcase-p">
            系统具备轻量化 Python 边缘运行时引擎，通过异步 SSH 自动为租户 VPS 检测环境、加固防火墙并拉起专用流控进程。凭据在握手完成后自毁擦除，确保零权限留存。
          </p>

          <ul class="edge-features-list">
            <li class="edge-feature-item">
              <el-icon class="text-emerald-500"><Check /></el-icon>
              <span><strong>多租户隔离计量</strong>：仅向当前租户展示其实际借用者与流量脱敏明细</span>
            </li>
            <li class="edge-feature-item">
              <el-icon class="text-emerald-500"><Check /></el-icon>
              <span><strong>秒级健康探测</strong>：动态心跳巡检与自动故障剔除，保障直链可用性 99.9%</span>
            </li>
            <li class="edge-feature-item">
              <el-icon class="text-emerald-500"><Check /></el-icon>
              <span><strong>智能测速评级</strong>：内置 10MB/100MB/1GB 多轮压测报告与 DC 延迟对齐</span>
            </li>
          </ul>

          <div class="edge-cta">
            <el-button type="primary" class="glow-btn" @click="authStore.isLoggedIn ? router.push('/edge-nodes') : goToLogin()">
              <el-icon><Share /></el-icon>
              <span>{{ authStore.isLoggedIn ? '管理我的边缘节点' : '登录后挂载边缘节点' }}</span>
            </el-button>
          </div>
        </div>

        <div class="edge-showcase-right">
          <!-- 终端模拟面板 (CRT 扫描线与闪烁光标) -->
          <div class="edge-terminal">
            <div class="terminal-scanline"></div>
            <div class="terminal-bar">
              <span class="terminal-dot red"></span>
              <span class="terminal-dot yellow"></span>
              <span class="terminal-dot green"></span>
              <span class="terminal-title">edge-deployer@mistrelay: ~</span>
              <span class="terminal-live-pill"><span class="live-dot"></span> DC5 Singapore 9.2ms [LIVE]</span>
            </div>
            <div class="terminal-body">
              <p class="terminal-line"><span class="cmd-prompt">$</span> mistrelay-edge attach --tenant-id=0 --ip=45.14.***.***</p>
              <p class="terminal-line text-emerald-400">✔ SSH 证书密钥指纹认证通过</p>
              <p class="terminal-line text-sky-400">✔ 自动化检测 Python 3.10+ & Systemd 运行时环境</p>
              <p class="terminal-line text-sky-400">✔ 配置专用流媒体分块缓存池 (Cache Size: 10GB)</p>
              <p class="terminal-line text-purple-400">✔ 联通 Telegram DC5 (Singapore RTT: 9.2ms · Rating: EXCELLENT)</p>
              <p class="terminal-line text-emerald-400">✔ 边缘工作器启动成功，加入全网租户智能分流调度池！</p>
              <p class="terminal-line text-amber-300">➜ 节点已转入安全令牌守护状态，SSH 密码已从内存安全擦除。<span class="terminal-cursor">_</span></p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 租户入驻三步指南 Section -->
    <section id="quickstart" class="section-container bg-surface-subtle">
      <div class="section-header">
        <span class="section-subtitle-tag">HOW TO GET STARTED</span>
        <h2 class="section-title">三步快速接入，开启属于您的专属云盘</h2>
        <p class="section-desc">无需复杂审核与运维流程，通过 Telegram 机器人私聊即可一键自助开通</p>
      </div>

      <div class="steps-grid">
        <!-- 步骤 1 -->
        <div class="step-card glass-card card-hover">
          <div class="step-badge">STEP 01</div>
          <div class="step-icon-wrap">
            <el-icon :size="32" class="text-pink-500"><Key /></el-icon>
          </div>
          <h3 class="step-title">私聊 Bot 获取注册码</h3>
          <p class="step-text">
            向系统主控 Telegram Bot 发送 <code>/register</code> 指令，系统将自动识别您的 Telegram 账号所属数据中心（DC1~DC5）并下发 6 位动态验证码。
          </p>
          <div class="step-action">
            <a
              v-if="botRegisterUrl"
              :href="botRegisterUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="step-bot-btn"
            >
              🚀 私聊 @{{ botUsername || 'Bot' }}
            </a>
            <span v-else class="step-bot-hint">私聊主控 Bot 发送 <code>/register</code></span>
          </div>
        </div>

        <!-- 步骤 2 -->
        <div class="step-card glass-card card-hover">
          <div class="step-badge">STEP 02</div>
          <div class="step-icon-wrap">
            <el-icon :size="32" class="text-sky-500"><Connection /></el-icon>
          </div>
          <h3 class="step-title">自动创建专属频道</h3>
          <p class="step-text">
            在 Web 注册页面输入 6 位验证码、设置用户名与密码。后台协议号将全自动为您在所属 DC 创建物理隔离专属频道，并完成读写分离集群授权。
          </p>
          <div class="step-action">
            <span class="step-tip-badge">全自动无人值守建频</span>
          </div>
        </div>

        <!-- 步骤 3 -->
        <div class="step-card glass-card card-hover">
          <div class="step-badge">STEP 03</div>
          <div class="step-icon-wrap">
            <el-icon :size="32" class="text-indigo-500"><FolderOpened /></el-icon>
          </div>
          <h3 class="step-title">登录个人云盘工作台</h3>
          <p class="step-text">
            登录专属控制台，即刻开始享受海量 Telegram 无限云盘、4K 影院播放、Aria2 离线转存、挂载边缘节点与一键导出 M3U 播放列表。
          </p>
          <div class="step-action">
            <el-button type="primary" class="glow-btn step-jump-btn" @click="goToRegister">
              <span>立即填写验证码注册</span>
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
        </div>
      </div>

      <!-- 快速开通 CTA 召集条 -->
      <div class="cta-banner glass-card">
        <div class="cta-banner-content">
          <h3 class="cta-banner-title">准备好体验极速多租户 Telegram 云盘了吗？</h3>
          <p class="cta-banner-desc">加入我们，告别限流卡顿与存储顾虑，开启超清流畅视听新纪元。</p>
        </div>
        <div class="cta-banner-actions">
          <el-button size="large" class="cta-secondary-btn" @click="goToLogin">已有账号登录</el-button>
          <el-button type="primary" size="large" class="glow-btn cta-primary-btn" @click="goToRegister">
            <el-icon><Promotion /></el-icon>
            <span>立即开通专属租户</span>
          </el-button>
        </div>
      </div>
    </section>

    <!-- 底部 Footer -->
    <footer class="landing-footer">
      <div class="footer-container">
        <div class="footer-main">
          <div class="footer-brand">
            <div class="brand-group">
              <div class="brand-icon-wrapper">
                <el-icon :size="20" class="brand-icon"><Cpu /></el-icon>
              </div>
              <span class="brand-title">MistRelay</span>
            </div>
            <p class="footer-tagline">
              新一代多租户 Telegram 频道云盘与全球边缘中继系统 · 物理隔离 · 动态 DC 亲和 · 读写分离
            </p>
          </div>

          <div class="footer-links-group">
            <div class="footer-col">
              <span class="footer-col-title">平台特性</span>
              <a href="#features" class="footer-link">专属频道隔离</a>
              <a href="#features" class="footer-link">Bot条带化并发</a>
              <a href="#edge" class="footer-link">全球边缘中继</a>
              <a href="#features" class="footer-link">Aria2离线转存</a>
            </div>

            <div class="footer-col">
              <span class="footer-col-title">架构与接入</span>
              <a href="#architecture" class="footer-link">DC1~DC5 亲和调度</a>
              <a href="#quickstart" class="footer-link">三步极速接入</a>
              <a href="#edge" class="footer-link">私有 VPS 纳管</a>
              <router-link to="/login?tab=register" class="footer-link">验证码开通</router-link>
            </div>

            <div class="footer-col">
              <span class="footer-col-title">快速入口</span>
              <router-link to="/login" class="footer-link">控制台登录</router-link>
              <router-link to="/login?tab=register" class="footer-link">注册新租户</router-link>
              <router-link to="/dashboard" class="footer-link">个人工作台</router-link>
              <a v-if="botRegisterUrl" :href="botRegisterUrl" target="_blank" class="footer-link">TG 主控机器人</a>
            </div>
          </div>
        </div>

        <div class="footer-bottom">
          <span class="copyright">
            © 2026 MistRelay Team. Released under MIT License. All rights reserved.
          </span>
          <div class="footer-meta">
            <span class="system-status-indicator">
              <span class="status-dot"></span>
              {{ systemReady ? 'All Systems Operational' : 'Systems Initializing' }}
            </span>
            <span v-if="systemVersion" class="version-tag">{{ systemVersion }}</span>
          </div>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'
import {
  Cpu,
  Monitor,
  Promotion,
  Operation,
  Folder,
  FolderChecked,
  FolderOpened,
  Lightning,
  Share,
  Connection,
  Download,
  Key,
  Link,
  DataLine,
  RefreshRight,
  ArrowRight,
  Check
} from '@element-plus/icons-vue'

const router = useRouter()
const authStore = useAuthStore()

// 状态管理
const mobileMenuOpen = ref(false)
const activeDc = ref(5)
const systemReady = ref(true)
const systemStatusText = ref('全节点运行中')
const systemVersion = ref('')
const botUsername = ref('')
const botRegisterUrl = ref('')

// Canvas & Particle Simulation Engine
const canvasRef = ref<HTMLCanvasElement | null>(null)
let animId = 0
let ctx: CanvasRenderingContext2D | null = null
let canvasW = 0
let canvasH = 0

interface Petal {
  x: number
  y: number
  size: number
  speedX: number
  speedY: number
  roll: number
  rollSpeed: number
  pitch: number
  pitchSpeed: number
  angle: number
  angularSpeed: number
  phase: number
  opacity: number
}

interface CyberParticle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  color: string
  pulse: number
  pulseSpeed: number
}

interface BurstSpark {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  color: string
  alpha: number
  decay: number
  rotation: number
}

interface RippleRing {
  x: number
  y: number
  radius: number
  maxRadius: number
  alpha: number
}

const petals: Petal[] = []
const particles: CyberParticle[] = []
const sparks: BurstSpark[] = []
const rings: RippleRing[] = []

const mousePos = reactive({ x: -1000, y: -1000 })
const mouseInWindow = ref(false)

// Hero Mockup 3D Tilt Card
const mockupRef = ref<HTMLElement | null>(null)
const tiltX = ref(0)
const tiltY = ref(0)
const glareX = ref(50)
const glareY = ref(50)
const isHoveringMockup = ref(false)

function onMockupMouseMove(e: MouseEvent) {
  if (!mockupRef.value || window.innerWidth <= 768) return
  const rect = mockupRef.value.getBoundingClientRect()
  const dx = (e.clientX - rect.left) / rect.width - 0.5
  const dy = (e.clientY - rect.top) / rect.height - 0.5
  tiltX.value = Math.round(-dy * 12 * 10) / 10
  tiltY.value = Math.round(dx * 12 * 10) / 10
  glareX.value = Math.round((dx + 0.5) * 100)
  glareY.value = Math.round((dy + 0.5) * 100)
  isHoveringMockup.value = true
}

function onMockupMouseLeave() {
  tiltX.value = 0
  tiltY.value = 0
  isHoveringMockup.value = false
}

function onWindowMouseMove(e: MouseEvent) {
  mousePos.x = e.clientX
  mousePos.y = e.clientY
  mouseInWindow.value = true
}

function onWindowMouseLeave() {
  mouseInWindow.value = false
  mousePos.x = -1000
  mousePos.y = -1000
}

function createBurst(x: number, y: number) {
  rings.push({
    x,
    y,
    radius: 6,
    maxRadius: 80,
    alpha: 0.75,
  })

  for (let i = 0; i < 12; i++) {
    const angle = (Math.PI * 2 * i) / 12 + (Math.random() - 0.5) * 0.4
    const speed = 2.2 + Math.random() * 3.8
    sparks.push({
      x,
      y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      size: 4 + Math.random() * 4,
      color: i % 2 === 0 ? 'rgba(255, 117, 151, ' : 'rgba(56, 189, 248, ',
      alpha: 0.95,
      decay: 0.022 + Math.random() * 0.015,
      rotation: Math.random() * Math.PI * 2,
    })
  }
}

function handleGlobalClick(e: MouseEvent) {
  createBurst(e.clientX, e.clientY)
}

function initCanvasElements() {
  const isMobile = window.innerWidth <= 768
  const petalCount = isMobile ? 18 : 45
  const particleCount = isMobile ? 12 : 28

  petals.length = 0
  particles.length = 0

  for (let i = 0; i < petalCount; i++) {
    petals.push({
      x: Math.random() * canvasW,
      y: Math.random() * canvasH,
      size: 10 + Math.random() * 14,
      speedX: -0.3 + Math.random() * 1.2,
      speedY: 0.8 + Math.random() * 1.5,
      roll: Math.random() * Math.PI,
      rollSpeed: 0.01 + Math.random() * 0.02,
      pitch: Math.random() * Math.PI,
      pitchSpeed: 0.01 + Math.random() * 0.02,
      angle: Math.random() * Math.PI * 2,
      angularSpeed: -0.01 + Math.random() * 0.02,
      phase: Math.random() * Math.PI * 2,
      opacity: 0.4 + Math.random() * 0.45,
    })
  }

  for (let i = 0; i < particleCount; i++) {
    const isPink = i % 2 === 0
    particles.push({
      x: Math.random() * canvasW,
      y: Math.random() * canvasH,
      vx: (-0.4 + Math.random() * 0.8) * 0.8,
      vy: (-0.4 + Math.random() * 0.8) * 0.8,
      radius: 1.5 + Math.random() * 1.5,
      color: isPink ? 'rgba(255, 117, 151, 0.7)' : 'rgba(56, 189, 248, 0.7)',
      pulse: Math.random() * Math.PI * 2,
      pulseSpeed: 0.02 + Math.random() * 0.03,
    })
  }
}

function resizeCanvas() {
  if (!canvasRef.value) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvasW = window.innerWidth
  canvasH = window.innerHeight
  canvasRef.value.width = canvasW * dpr
  canvasRef.value.height = canvasH * dpr
  if (ctx) {
    ctx.scale(dpr, dpr)
  }
}

function renderFrame() {
  if (!ctx || !canvasRef.value) return

  ctx.clearRect(0, 0, canvasW, canvasH)

  // 1. Cyber Particles & Constellation Connections
  for (let i = 0; i < particles.length; i++) {
    const pt = particles[i]
    pt.x += pt.vx
    pt.y += pt.vy
    pt.pulse += pt.pulseSpeed
    const r = pt.radius + Math.sin(pt.pulse) * 0.7

    if (pt.x < 0 || pt.x > canvasW) pt.vx *= -1
    if (pt.y < 0 || pt.y > canvasH) pt.vy *= -1

    ctx.save()
    ctx.beginPath()
    ctx.arc(pt.x, pt.y, Math.max(0.5, r), 0, Math.PI * 2)
    ctx.fillStyle = pt.color
    ctx.shadowColor = pt.color
    ctx.shadowBlur = 6
    ctx.fill()
    ctx.restore()

    for (let j = i + 1; j < particles.length; j++) {
      const pt2 = particles[j]
      const dx = pt.x - pt2.x
      const dy = pt.y - pt2.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist < 100) {
        const alpha = (1 - dist / 100) * 0.22
        ctx.beginPath()
        ctx.moveTo(pt.x, pt.y)
        ctx.lineTo(pt2.x, pt2.y)
        ctx.strokeStyle = `rgba(186, 230, 253, ${alpha})`
        ctx.lineWidth = 0.8
        ctx.stroke()
      }
    }

    if (mouseInWindow.value) {
      const mdx = pt.x - mousePos.x
      const mdy = pt.y - mousePos.y
      const mdist = Math.sqrt(mdx * mdx + mdy * mdy)
      if (mdist < 110) {
        const alpha = (1 - mdist / 110) * 0.3
        ctx.beginPath()
        ctx.moveTo(pt.x, pt.y)
        ctx.lineTo(mousePos.x, mousePos.y)
        ctx.strokeStyle = `rgba(255, 182, 193, ${alpha})`
        ctx.lineWidth = 1
        ctx.stroke()
      }
    }
  }

  // 2. Sakura Petals
  for (let i = 0; i < petals.length; i++) {
    const p = petals[i]
    p.y += p.speedY
    p.x += p.speedX + Math.sin(p.phase) * 0.75
    p.phase += 0.02
    p.roll += p.rollSpeed
    p.pitch += p.pitchSpeed
    p.angle += p.angularSpeed

    // Mouse gentle repulsion
    if (mouseInWindow.value) {
      const dx = p.x - mousePos.x
      const dy = p.y - mousePos.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist < 130 && dist > 0) {
        const force = ((130 - dist) / 130) * 2.2
        p.x += (dx / dist) * force
        p.y += (dy / dist) * force
      }
    }

    if (p.y > canvasH + 30) {
      p.y = -30
      p.x = Math.random() * canvasW
    }
    if (p.x < -40) p.x = canvasW + 20
    if (p.x > canvasW + 40) p.x = -20

    ctx.save()
    ctx.translate(p.x, p.y)
    ctx.rotate(p.angle)
    ctx.scale(Math.cos(p.roll), Math.sin(p.pitch))

    ctx.beginPath()
    ctx.moveTo(0, -p.size)
    ctx.bezierCurveTo(
      p.size * 0.85, -p.size * 0.5,
      p.size * 0.95, p.size * 0.5,
      0, p.size
    )
    ctx.bezierCurveTo(
      -p.size * 0.95, p.size * 0.5,
      -p.size * 0.85, -p.size * 0.5,
      0, -p.size
    )
    ctx.closePath()

    const grad = ctx.createLinearGradient(0, -p.size, 0, p.size)
    grad.addColorStop(0, `rgba(255, 245, 248, ${p.opacity})`)
    grad.addColorStop(0.5, `rgba(255, 168, 192, ${p.opacity})`)
    grad.addColorStop(1, `rgba(255, 117, 151, ${p.opacity * 0.9})`)

    ctx.fillStyle = grad
    ctx.shadowColor = 'rgba(255, 117, 151, 0.4)'
    ctx.shadowBlur = 4
    ctx.fill()
    ctx.restore()
  }

  // 3. Ripple rings
  for (let i = rings.length - 1; i >= 0; i--) {
    const r = rings[i]
    r.radius += (r.maxRadius - r.radius) * 0.12 + 1.2
    r.alpha *= 0.91
    if (r.alpha < 0.02 || r.radius >= r.maxRadius) {
      rings.splice(i, 1)
      continue
    }
    ctx.save()
    ctx.beginPath()
    ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(255, 143, 171, ${r.alpha})`
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.restore()
  }

  // 4. Sparks from click bursts
  for (let i = sparks.length - 1; i >= 0; i--) {
    const s = sparks[i]
    s.x += s.vx
    s.y += s.vy
    s.vx *= 0.95
    s.vy *= 0.95
    s.alpha -= s.decay
    s.rotation += 0.06
    if (s.alpha <= 0) {
      sparks.splice(i, 1)
      continue
    }
    ctx.save()
    ctx.translate(s.x, s.y)
    ctx.rotate(s.rotation)
    ctx.beginPath()
    ctx.arc(0, 0, s.size, 0, Math.PI * 2)
    ctx.fillStyle = s.color + s.alpha + ')'
    ctx.shadowColor = s.color + '0.6)'
    ctx.shadowBlur = 6
    ctx.fill()
    ctx.restore()
  }

  animId = requestAnimationFrame(renderFrame)
}

function handleVisibilityChange() {
  if (document.hidden) {
    if (animId) cancelAnimationFrame(animId)
    animId = 0
  } else {
    if (!animId) animId = requestAnimationFrame(renderFrame)
  }
}

async function fetchSystemHealth() {
  try {
    const { data } = await api.get('/health')
    if (data) {
      systemReady.value = Boolean(data.ready)
      systemVersion.value = data.version || ''
      systemStatusText.value = data.ready ? '全节点就绪' : '服务初始化中'
    }
  } catch {
    systemReady.value = false
    systemStatusText.value = '节点连接中'
  }
}

async function fetchBotInfo() {
  try {
    const { data } = await api.get('/auth/bot-info')
    if (data?.success) {
      const uname = data.bot_username || data.data?.bot_username || ''
      botUsername.value = uname
      botRegisterUrl.value = data.register_deep_link || data.data?.register_deep_link || (uname ? `https://t.me/${uname}?start=register` : '')
    }
  } catch {
    // 忽略未就绪异常
  }
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goToLogin() {
  router.push('/login')
}

function goToRegister() {
  router.push('/login?tab=register')
}

function goToDashboard() {
  router.push('/dashboard')
}

onMounted(() => {
  void fetchSystemHealth()
  void fetchBotInfo()

  if (canvasRef.value) {
    ctx = canvasRef.value.getContext('2d')
    resizeCanvas()
    initCanvasElements()
    animId = requestAnimationFrame(renderFrame)
  }

  window.addEventListener('resize', () => {
    resizeCanvas()
    initCanvasElements()
  }, { passive: true })
  window.addEventListener('mousemove', onWindowMouseMove, { passive: true })
  window.addEventListener('mouseleave', onWindowMouseLeave, { passive: true })
  window.addEventListener('click', handleGlobalClick, { passive: true })
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  if (animId) cancelAnimationFrame(animId)
  window.removeEventListener('resize', resizeCanvas)
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseleave', onWindowMouseLeave)
  window.removeEventListener('click', handleGlobalClick)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
/* 全局页面容器 */
.landing-page {
  position: relative;
  min-height: 100vh;
  background-color: #fdf8fa;
  color: #1e293b;
  overflow-x: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
}

/* 背景流光光晕 */
.landing-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.sakura-cosmic-canvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  pointer-events: none;
  z-index: 0;
}

.mouse-spotlight {
  position: fixed;
  top: 0;
  left: 0;
  width: 500px;
  height: 500px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(255, 117, 151, 0.16) 0%,
    rgba(56, 189, 248, 0.08) 45%,
    transparent 70%
  );
  pointer-events: none;
  z-index: 0;
  transition: opacity 0.3s ease;
  will-change: transform;
}

.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.65;
}

.bg-glow-1 {
  width: 680px;
  height: 680px;
  background: radial-gradient(circle, rgba(255, 117, 151, 0.28) 0%, transparent 70%);
  top: -120px;
  left: -100px;
  animation: float 14s ease-in-out infinite;
}

.bg-glow-2 {
  width: 720px;
  height: 720px;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.25) 0%, transparent 70%);
  top: 25%;
  right: -150px;
  animation: float 16s ease-in-out infinite reverse;
}

.bg-glow-3 {
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(255, 182, 193, 0.22) 0%, transparent 70%);
  bottom: 10%;
  left: 20%;
  animation: float 18s ease-in-out infinite;
}

.bg-grid-overlay {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(rgba(255, 143, 171, 0.15) 1px, transparent 1px);
  background-size: 32px 32px;
  opacity: 0.5;
}

/* 顶部毛玻璃导航栏 */
.landing-header {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: calc(100% - 48px);
  max-width: 1240px;
  height: 64px;
  z-index: 100;
  background: rgba(255, 255, 255, 0.82) !important;
  backdrop-filter: blur(20px) !important;
  -webkit-backdrop-filter: blur(20px) !important;
  border: 1px solid rgba(255, 143, 171, 0.28) !important;
  border-radius: 20px !important;
  box-shadow: 0 10px 30px -10px rgba(255, 117, 151, 0.15) !important;
  padding: 0 20px;
}

.header-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
}

.brand-group {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}

.brand-icon-wrapper {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: var(--gradient-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(255, 117, 151, 0.35);
  transition: transform 0.25s ease;
}

.brand-group:hover .brand-icon-wrapper {
  transform: rotate(6deg) scale(1.05);
}

.brand-text-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-title {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.brand-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 117, 151, 0.12);
  color: #ff7597;
  border: 1px solid rgba(255, 117, 151, 0.25);
}

/* 导航链接 */
.nav-links {
  display: flex;
  align-items: center;
  gap: 28px;
}

.nav-link {
  color: #475569;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: color 0.2s ease;
}

.nav-link:hover {
  color: #ff7597;
}

/* 状态胶囊 */
.status-capsule {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.22);
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f59e0b;
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);
}

.status-capsule.is-ready .status-dot {
  background: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.6);
}

.status-ver {
  font-size: 11px;
  color: #94a3b8;
  border-left: 1px solid #cbd5e1;
  padding-left: 6px;
}

/* 右侧动作 */
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.action-btn {
  border-radius: 12px;
  font-weight: 600;
  font-size: 14px;
}

.action-btn--login {
  color: #475569;
}

.action-btn--login:hover {
  color: #ff7597;
  background: rgba(255, 117, 151, 0.08);
}

.glow-btn {
  position: relative;
  background: var(--gradient-primary) !important;
  border: none !important;
  box-shadow: 0 4px 18px rgba(255, 117, 151, 0.4), 0 2px 10px rgba(56, 189, 248, 0.25) !important;
  transition: all 0.25s cubic-bezier(0.2, 0.8, 0.2, 1) !important;
  animation: cosmicButtonGlow 4s ease-in-out infinite;
}

.glow-btn:hover {
  transform: translateY(-2px) scale(1.025) !important;
  box-shadow: 0 8px 28px rgba(255, 117, 151, 0.58), 0 4px 16px rgba(56, 189, 248, 0.42) !important;
}

@keyframes cosmicButtonGlow {
  0%, 100% {
    box-shadow: 0 4px 18px rgba(255, 117, 151, 0.4), 0 2px 10px rgba(56, 189, 248, 0.25);
  }
  50% {
    box-shadow: 0 6px 24px rgba(56, 189, 248, 0.5), 0 2px 14px rgba(255, 117, 151, 0.35);
  }
}

.mobile-menu-btn {
  display: none;
  background: transparent;
  border: none;
  color: #475569;
  cursor: pointer;
  padding: 4px;
}

/* 移动端菜单面板 */
.mobile-nav-panel {
  position: absolute;
  top: 72px;
  left: 0;
  right: 0;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: rgba(255, 255, 255, 0.96) !important;
  box-shadow: 0 16px 32px rgba(255, 117, 151, 0.18) !important;
}

.mobile-nav-link {
  font-size: 15px;
  font-weight: 600;
  color: #334155;
  text-decoration: none;
  padding: 8px 12px;
  border-radius: 8px;
}

.mobile-nav-link:hover {
  background: rgba(255, 117, 151, 0.1);
  color: #ff7597;
}

.mobile-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 143, 171, 0.2);
}

.mobile-action-btn {
  width: 100%;
}

/* 首屏 Hero */
.hero-section {
  position: relative;
  z-index: 1;
  padding: 140px 24px 70px;
  max-width: 1240px;
  margin: 0 auto;
}

.hero-content {
  text-align: center;
  max-width: 960px;
  margin: 0 auto;
}

.hero-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(255, 143, 171, 0.35);
  box-shadow: 0 4px 16px rgba(255, 117, 151, 0.12);
  margin-bottom: 24px;
}

.hero-pill-badge {
  background: linear-gradient(135deg, #ff7597 0%, #38bdf8 100%);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
}

.hero-pill-text {
  font-size: 13px;
  color: #475569;
  font-weight: 600;
}

.hero-title {
  font-size: 48px;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: -1px;
  color: #0f172a;
  margin-bottom: 20px;
}

.hero-description {
  font-size: 17px;
  line-height: 1.65;
  color: #475569;
  max-width: 820px;
  margin: 0 auto 36px;
}

.hero-cta-group {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 48px;
}

.hero-cta-btn {
  height: 48px;
  padding: 0 26px;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  transition: all 0.25s ease;
}

.hero-cta-btn--primary {
  font-size: 16px;
}

.hero-cta-btn--secondary {
  background: rgba(255, 255, 255, 0.88);
  color: #334155;
  border: 1px solid rgba(255, 143, 171, 0.3);
  box-shadow: 0 4px 14px rgba(255, 117, 151, 0.08);
}

.hero-cta-btn--secondary:hover {
  background: #ffffff;
  color: #ff7597;
  border-color: #ff7597;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(255, 117, 151, 0.16);
}

.hero-cta-btn--tg {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.12), rgba(14, 165, 233, 0.08));
  color: #0284c7;
  border: 1px solid rgba(56, 189, 248, 0.35);
}

.hero-cta-btn--tg:hover {
  background: linear-gradient(135deg, #0ea5e9 0%, #38bdf8 100%);
  color: #fff;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.3);
}

/* 核心指标可视化模拟卡片 (Hero Mockup) */
.hero-dashboard-mockup {
  max-width: 980px;
  margin: 0 auto;
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid rgba(255, 143, 171, 0.32) !important;
  box-shadow: 0 24px 60px -12px rgba(255, 117, 151, 0.22), 0 12px 28px -8px rgba(56, 189, 248, 0.18) !important;
}

.mockup-header {
  height: 48px;
  background: rgba(248, 250, 252, 0.9);
  border-bottom: 1px solid rgba(255, 143, 171, 0.2);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
}

.mockup-dots {
  display: flex;
  gap: 6px;
}

.mockup-dots .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-red { background: #ff5f56; }
.dot-yellow { background: #ffbd2e; }
.dot-green { background: #27c93f; }

.mockup-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}

.mockup-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  padding: 2px 8px;
  border-radius: 999px;
}

.pulse-indicator {
  position: relative;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0ea5e9;
}

.pulse-indicator::before,
.pulse-indicator::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1.5px solid #38bdf8;
  animation: pingRadar 2s cubic-bezier(0, 0.2, 0.8, 1) infinite;
}

.pulse-indicator::after {
  animation-delay: 1s;
}

@keyframes pingRadar {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(2.6); opacity: 0; }
}

.mockup-body {
  padding: 24px;
  background: rgba(255, 255, 255, 0.95);
}

.mockup-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.mockup-stat-card {
  padding: 16px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(255, 143, 171, 0.18);
  display: flex;
  align-items: flex-start;
  gap: 12px;
  text-align: left;
}

.mockup-stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.icon-storage {
  background: rgba(255, 117, 151, 0.15);
  color: #ff7597;
}

.icon-speed {
  background: rgba(56, 189, 248, 0.15);
  color: #0ea5e9;
}

.icon-edge {
  background: rgba(129, 140, 248, 0.15);
  color: #6366f1;
}

.mockup-stat-info {
  display: flex;
  flex-direction: column;
}

.mockup-stat-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 2px;
}

.mockup-stat-value {
  font-size: 16px;
  font-weight: 800;
  margin-bottom: 2px;
}

.mockup-stat-desc {
  font-size: 11px;
  color: #94a3b8;
}

.mockup-stream-bar {
  padding: 14px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.08) 0%, rgba(56, 189, 248, 0.08) 100%);
  border: 1px solid rgba(255, 143, 171, 0.25);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stream-pipeline-track {
  position: relative;
  width: 100%;
  height: 6px;
  background: rgba(241, 245, 249, 0.85);
  border-radius: 999px;
  overflow: hidden;
  margin: 4px 0 2px;
  border: 1px solid rgba(255, 143, 171, 0.2);
}

.pipeline-laser {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, rgba(255, 117, 151, 0.25), rgba(56, 189, 248, 0.45));
}

.pipeline-packet {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #ff7597, #38bdf8);
  box-shadow: 0 0 8px #ff7597, 0 0 12px #38bdf8;
}

.packet-1 {
  width: 45px;
  animation: packetSlide 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.packet-2 {
  width: 65px;
  animation: packetSlide 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite 0.8s;
}

.packet-3 {
  width: 35px;
  animation: packetSlide 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite 1.6s;
}

@keyframes packetSlide {
  0% { left: -25%; opacity: 0; }
  15% { opacity: 1; }
  85% { opacity: 1; }
  100% { left: 105%; opacity: 0; }
}

.stat-dot-pulse {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 8px #10b981;
  margin-right: 4px;
  animation: dotPulse 1.5s infinite;
}

@keyframes dotPulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: 0.6; }
}

.stream-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stream-badge {
  background: var(--gradient-primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}

.stream-text {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.stream-stats {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stream-stat-item {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

/* 通用分区容器 */
.section-container {
  position: relative;
  z-index: 1;
  padding: 80px 24px;
  max-width: 1240px;
  margin: 0 auto;
}

.bg-surface-subtle {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.6) 0%, rgba(253, 247, 249, 0.9) 100%);
  border-radius: 36px;
}

.section-header {
  text-align: center;
  max-width: 780px;
  margin: 0 auto 56px;
}

.section-subtitle-tag {
  display: inline-block;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 1.5px;
  color: #ff7597;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.section-title {
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.5px;
  color: #0f172a;
  margin-bottom: 14px;
}

.section-desc {
  font-size: 16px;
  color: #64748b;
  line-height: 1.6;
}

/* 特性卡片网格 */
.features-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.feature-card {
  position: relative;
  padding: 32px;
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
  background: rgba(255, 255, 255, 0.88) !important;
  transition: transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.35s ease !important;
  z-index: 1;
}

.feature-card::before {
  content: '';
  position: absolute;
  inset: -120%;
  background: conic-gradient(
    from 0deg at 50% 50%,
    transparent 0deg,
    rgba(255, 117, 151, 0) 50deg,
    rgba(255, 117, 151, 0.85) 110deg,
    rgba(56, 189, 248, 0.95) 170deg,
    rgba(255, 117, 151, 0) 230deg,
    transparent 360deg
  );
  animation: borderBeamRotate 6s linear infinite;
  opacity: 0.35;
  transition: opacity 0.3s ease;
  pointer-events: none;
  z-index: 0;
}

.feature-card::after {
  content: '';
  position: absolute;
  inset: 1.5px;
  border-radius: inherit;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  z-index: 0;
  pointer-events: none;
}

.feature-card:hover {
  transform: translateY(-8px) scale(1.015);
  box-shadow: 0 20px 48px rgba(255, 117, 151, 0.22), 0 8px 24px rgba(56, 189, 248, 0.18) !important;
}

.feature-card:hover::before {
  opacity: 1;
  animation-duration: 3s;
}

.feature-card > * {
  position: relative;
  z-index: 1;
}

@keyframes borderBeamRotate {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.feature-card-glow {
  position: absolute;
  top: -40px;
  right: -40px;
  width: 160px;
  height: 160px;
  border-radius: 50%;
  filter: blur(40px);
  pointer-events: none;
  opacity: 0.35;
}

.feature-card-glow--sakura { background: #ff7597; }
.feature-card-glow--sky { background: #38bdf8; }
.feature-card-glow--indigo { background: #818cf8; }
.feature-card-glow--amber { background: #f59e0b; }

.feature-icon-box {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
  animation: iconFloat 4s ease-in-out infinite;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.feature-card:hover .feature-icon-box {
  transform: scale(1.15) rotate(6deg);
  box-shadow: 0 0 24px rgba(255, 117, 151, 0.45);
}

@keyframes iconFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

.bg-sakura-light { background: rgba(255, 117, 151, 0.15); }
.bg-sky-light { background: rgba(56, 189, 248, 0.15); }
.bg-indigo-light { background: rgba(129, 140, 248, 0.15); }
.bg-amber-light { background: rgba(245, 158, 11, 0.15); }

.feature-card-title {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 12px;
}

.feature-card-text {
  font-size: 14px;
  color: #64748b;
  line-height: 1.7;
  margin-bottom: 20px;
}

.feature-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.feature-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 8px;
  background: rgba(241, 245, 249, 0.9);
  color: #475569;
  border: 1px solid rgba(203, 213, 225, 0.6);
}

/* DC 矩阵卡片 */
.dc-matrix-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
  margin-bottom: 40px;
}

.dc-card {
  position: relative;
  overflow: hidden;
  padding: 24px;
  border-radius: 20px;
  border: 1px solid rgba(255, 143, 171, 0.22) !important;
  background: rgba(255, 255, 255, 0.9) !important;
  cursor: pointer;
  transition: all 0.3s ease;
}

.dc-card--highlight {
  border-color: #ff7597 !important;
  box-shadow: 0 14px 34px rgba(255, 117, 151, 0.25), 0 0 20px rgba(56, 189, 248, 0.2) !important;
  transform: translateY(-4px);
}

.dc-card-radar-pulse {
  position: absolute;
  top: -60px;
  right: -60px;
  width: 160px;
  height: 160px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 117, 151, 0.28) 0%, rgba(56, 189, 248, 0.1) 50%, transparent 70%);
  animation: dcRadarGlow 2.5s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes dcRadarGlow {
  0% { transform: scale(0.9); opacity: 0.4; }
  100% { transform: scale(1.3); opacity: 0.9; }
}

.ping-live-text {
  animation: pingTextBlink 2s ease-in-out infinite;
}

@keyframes pingTextBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.dc-card-badge {
  font-size: 12px;
  font-weight: 700;
  color: #ff7597;
  margin-bottom: 8px;
}

.dc-card-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 10px;
}

.dc-card-desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
  margin-bottom: 16px;
  min-height: 58px;
}

.dc-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  border-top: 1px solid rgba(241, 245, 249, 0.9);
  padding-top: 12px;
}

/* 调度流程步骤框 */
.architecture-flow-box {
  padding: 32px;
  border-radius: 24px;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
}

.flow-box-title {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 24px;
}

.flow-steps {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.flow-step {
  flex: 1;
  background: rgba(248, 250, 252, 0.9);
  padding: 18px;
  border-radius: 16px;
  border: 1px solid rgba(255, 143, 171, 0.18);
  display: flex;
  gap: 12px;
}

.flow-step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--gradient-primary);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.flow-step-content h4 {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.flow-step-content p {
  font-size: 12px;
  color: #64748b;
  margin: 0;
  line-height: 1.4;
}

.flow-arrow {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  color: #ff7597;
  font-size: 20px;
  flex-shrink: 0;
}

.flow-laser-track {
  position: absolute;
  top: 50%;
  left: -8px;
  right: -8px;
  height: 2px;
  background: linear-gradient(90deg, rgba(255, 117, 151, 0.25), rgba(56, 189, 248, 0.45));
  transform: translateY(-50%);
  overflow: hidden;
  border-radius: 999px;
  pointer-events: none;
}

.laser-dot {
  position: absolute;
  top: -1px;
  width: 16px;
  height: 4px;
  border-radius: 999px;
  background: #38bdf8;
  box-shadow: 0 0 8px #38bdf8, 0 0 14px #ff7597;
  animation: laserTravel 1.8s ease-in-out infinite;
}

@keyframes laserTravel {
  0% { left: -25%; opacity: 0; }
  25% { opacity: 1; }
  75% { opacity: 1; }
  100% { left: 120%; opacity: 0; }
}

/* 边缘节点 Showcase */
.edge-showcase-box {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 36px;
  padding: 36px;
  border-radius: 28px;
  border: 1px solid rgba(255, 143, 171, 0.3) !important;
}

.edge-pill-tag {
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
  color: #0284c7;
  background: rgba(56, 189, 248, 0.12);
  padding: 4px 12px;
  border-radius: 999px;
  margin-bottom: 12px;
}

.edge-showcase-title {
  font-size: 26px;
  font-weight: 800;
  color: #0f172a;
  margin-bottom: 14px;
}

.edge-showcase-p {
  font-size: 15px;
  color: #475569;
  line-height: 1.7;
  margin-bottom: 20px;
}

.edge-features-list {
  list-style: none;
  padding: 0;
  margin: 0 0 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.edge-feature-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #334155;
}

/* 终端模拟 */
.edge-terminal {
  position: relative;
  overflow: hidden;
  border-radius: 18px;
  background: #0f172a;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.35);
  border: 1px solid rgba(255, 143, 171, 0.3);
  height: 100%;
  display: flex;
  flex-direction: column;
}

.terminal-scanline {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.5), transparent);
  animation: scanlineMove 4s linear infinite;
  pointer-events: none;
  z-index: 2;
}

@keyframes scanlineMove {
  0% { top: 0%; opacity: 0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { top: 100%; opacity: 0; }
}

.terminal-cursor {
  display: inline-block;
  font-weight: 700;
  color: #38bdf8;
  animation: cursorBlink 1s infinite;
}

@keyframes cursorBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.terminal-live-pill {
  margin-left: auto;
  font-size: 11px;
  font-family: monospace;
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(16, 185, 129, 0.3);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
  animation: dotPulse 1.2s infinite;
}

.terminal-bar {
  height: 36px;
  background: #1e293b;
  display: flex;
  align-items: center;
  padding: 0 14px;
  gap: 6px;
}

.terminal-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.terminal-dot.red { background: #ef4444; }
.terminal-dot.yellow { background: #f59e0b; }
.terminal-dot.green { background: #10b981; }

.terminal-title {
  margin-left: 10px;
  font-size: 12px;
  color: #94a3b8;
  font-family: monospace;
}

.terminal-body {
  padding: 18px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  flex: 1;
}

.terminal-line {
  margin: 0 0 6px;
  color: #cbd5e1;
}

.cmd-prompt {
  color: #ff7597;
  margin-right: 6px;
  font-weight: 700;
}

/* 三步接入 Steps 网格 */
.steps-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 48px;
}

.step-card {
  padding: 32px 24px;
  border-radius: 24px;
  border: 1px solid rgba(255, 143, 171, 0.25) !important;
  background: rgba(255, 255, 255, 0.95) !important;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  position: relative;
}

.step-badge {
  position: absolute;
  top: 18px;
  right: 18px;
  font-size: 11px;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 1px;
}

.step-icon-wrap {
  width: 64px;
  height: 64px;
  border-radius: 20px;
  background: rgba(248, 250, 252, 0.9);
  border: 1px solid rgba(255, 143, 171, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.step-title {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 12px;
}

.step-text {
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
  margin: 0 0 20px;
  flex: 1;
}

.step-text code {
  background: rgba(255, 117, 151, 0.1);
  color: #e11d48;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
}

.step-action {
  width: 100%;
}

.step-bot-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 10px 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, #0ea5e9 0%, #38bdf8 100%);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.25);
  transition: all 0.2s ease;
}

.step-bot-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.4);
}

.step-bot-hint {
  font-size: 12px;
  color: #0284c7;
  font-weight: 600;
}

.step-bot-hint code {
  background: rgba(56, 189, 248, 0.1);
  padding: 1px 4px;
  border-radius: 4px;
}

.step-tip-badge {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  padding: 6px 12px;
  border-radius: 8px;
}

.step-jump-btn {
  width: 100%;
}

/* 快速开通 CTA 召集条 */
.cta-banner {
  padding: 40px;
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(255, 117, 151, 0.12) 0%, rgba(56, 189, 248, 0.12) 100%), #ffffff !important;
  border: 1px solid rgba(255, 143, 171, 0.35) !important;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 24px;
  box-shadow: 0 20px 40px rgba(255, 117, 151, 0.15) !important;
}

.cta-banner-title {
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
  margin-bottom: 6px;
}

.cta-banner-desc {
  font-size: 15px;
  color: #64748b;
  margin: 0;
}

.cta-banner-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.cta-primary-btn {
  height: 46px;
  padding: 0 24px;
  border-radius: 12px;
  font-size: 15px;
}

.cta-secondary-btn {
  height: 46px;
  padding: 0 20px;
  border-radius: 12px;
  font-size: 14px;
  color: #475569;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 143, 171, 0.3);
}

.cta-secondary-btn:hover {
  color: #ff7597;
  border-color: #ff7597;
}

/* 底部 Footer */
.landing-footer {
  position: relative;
  z-index: 1;
  background: rgba(255, 255, 255, 0.92);
  border-top: 1px solid rgba(255, 143, 171, 0.22);
  padding: 60px 24px 32px;
  margin-top: 60px;
}

.footer-container {
  max-width: 1240px;
  margin: 0 auto;
}

.footer-main {
  display: flex;
  justify-content: space-between;
  gap: 48px;
  margin-bottom: 48px;
  flex-wrap: wrap;
}

.footer-brand {
  max-width: 380px;
}

.footer-tagline {
  font-size: 13px;
  color: #64748b;
  line-height: 1.7;
  margin-top: 12px;
}

.footer-links-group {
  display: flex;
  gap: 60px;
  flex-wrap: wrap;
}

.footer-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.footer-col-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.footer-link {
  font-size: 13px;
  color: #64748b;
  text-decoration: none;
  transition: color 0.2s ease;
}

.footer-link:hover {
  color: #ff7597;
}

.footer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 24px;
  border-top: 1px solid rgba(255, 143, 171, 0.15);
  font-size: 12px;
  color: #94a3b8;
  flex-wrap: wrap;
  gap: 12px;
}

.footer-meta {
  display: flex;
  align-items: center;
  gap: 14px;
}

.system-status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #10b981;
  font-weight: 600;
}

.version-tag {
  background: rgba(241, 245, 249, 0.9);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #cbd5e1;
}

/* 响应式样式适配 */
@media (max-width: 1024px) {
  .hero-title {
    font-size: 38px;
  }

  .dc-matrix-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .edge-showcase-box {
    grid-template-columns: 1fr;
  }

  .steps-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .landing-header {
    width: calc(100% - 24px);
    padding: 0 14px;
  }

  .nav-links,
  .status-capsule,
  .action-btn--login,
  .action-btn--primary,
  .brand-badge {
    display: none !important;
  }

  .action-btn--register {
    padding: 6px 12px !important;
    font-size: 13px !important;
  }

  .mobile-menu-btn {
    display: flex;
  }

  .hero-section {
    padding: 110px 16px 40px;
  }

  .hero-title {
    font-size: 28px;
  }

  .hero-description {
    font-size: 14px;
  }

  .mockup-grid {
    grid-template-columns: 1fr;
  }

  .features-grid {
    grid-template-columns: 1fr;
  }

  .flow-steps {
    flex-direction: column;
  }

  .flow-arrow {
    transform: rotate(90deg);
  }

  .cta-banner {
    padding: 24px;
    flex-direction: column;
    text-align: center;
  }

  .cta-banner-actions {
    width: 100%;
    flex-direction: column;
  }

  .cta-banner-actions .el-button {
    width: 100%;
  }

  .footer-links-group {
    gap: 32px;
  }

  .footer-bottom {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
