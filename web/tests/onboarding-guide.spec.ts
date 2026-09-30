import { expect, test, type Page } from '@playwright/test'

async function mockCommonApis(page: Page, options: { totalFiles?: number; hasDismissedWelcome?: boolean } = {}) {
  const totalFiles = options.totalFiles ?? 0
  const dismissed = options.hasDismissedWelcome ?? true

  await page.addInitScript(({ isDismissed }) => {
    window.localStorage.setItem('token', 'mock-tenant-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'mock-tenant-refresh')
    if (isDismissed) {
      window.localStorage.setItem('mistrelay_welcome_dismissed', 'true')
    } else {
      window.localStorage.removeItem('mistrelay_welcome_dismissed')
    }
  }, { isDismissed: dismissed })

  await page.route('**/api/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ready: true,
        server_status: 'running',
        telegram_connected: true,
        version: 'v0.2.16',
      }),
    })
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: {
          id: 10,
          username: 'vip_tenant',
          role: 'user',
          dc_id: 5,
          bin_channel_id: -100200300400,
          bin_channel_username: 'vip_tenant_channel',
        },
      }),
    })
  })

  await page.route('**/api/auth/bot-info', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        bot_username: 'MistRelayOfficialBot',
        bot_name: 'MistRelay Bot',
        register_deep_link: 'https://t.me/MistRelayOfficialBot?start=help',
      }),
    })
  })

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        server_status: 'running',
        uptime: '3d',
        version: 'v0.2.16',
        loads: {},
        channel_info: {
          channel_id: -100200300400,
          channel_type: 'private',
          public_handle: 'vip_tenant_channel',
        },
      }),
    })
  })

  await page.route('**/api/downloads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { total: 0, completed: 0, failed: 0, downloading: 0, pending: 0, waiting: 0 },
      }),
    })
  })

  await page.route('**/api/uploads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { cleaned: 0 },
      }),
    })
  })

  await page.route('**/api/downloads*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [],
        items: [],
        total: 0,
        running: 0,
        waiting: 0,
        stopped: 0,
      }),
    })
  })

  await page.route('**/api/traffic*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { upload_speed: '0 B/s', download_speed: '0 B/s' },
      }),
    })
  })

  await page.route('**/api/telegram/usage*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total_size: totalFiles > 0 ? 104857600 : 0,
          total_count: totalFiles,
          videos: totalFiles > 0 ? 1 : 0,
          images: 0,
          audios: 0,
          documents: 0,
        },
      }),
    })
  })

  await page.route('**/api/telegram/browse*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        items: totalFiles > 0 ? [{
          message_id: 1,
          file_name: 'test-video.mp4',
          file_size: 104857600,
          mime_type: 'video/mp4',
          message_date: '2026-09-29T12:00:00Z',
          stream_url: 'http://127.0.0.1:8080/stream/1',
        }] : [],
        total: totalFiles,
        page: 1,
        page_size: 20,
      }),
    })
  })

  await page.route('**/api/telegram/drive*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        items: totalFiles > 0 ? [{
          message_id: 1,
          file_name: 'test-video.mp4',
          file_size: 104857600,
          mime_type: 'video/mp4',
          message_date: '2026-09-29T12:00:00Z',
          stream_url: 'http://127.0.0.1:8080/stream/1',
        }] : [],
        total: totalFiles,
        page: 1,
        page_size: 20,
      }),
    })
  })

  await page.route('**/api/edge/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        nodes: [],
        summary: {},
      }),
    })
  })

  await page.route('**/api/telegram/thumbnails/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          running: false,
          cached: 0,
          total: 0,
          percent: 100,
        },
      }),
    })
  })

  await page.route('**/api/telegram/thumbs/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        running: false,
        cached: 0,
        total: 0,
        percent: 100,
      }),
    })
  })

  await page.route('**/api/telegram/harvester/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { status: 'idle' },
      }),
    })
  })

  await page.route('**/api/telegram/botfather/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [],
      }),
    })
  })

  await page.route('**/api/harvester/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        accounts: [],
      }),
    })
  })
}

test.describe('Onboarding & User Guide Center', () => {
  test('header renders guide pill and opens comprehensive user guide drawer', async ({ page }) => {
    await mockCommonApis(page, { totalFiles: 0, hasDismissedWelcome: true })
    await page.goto('/dashboard')

    // 验证顶栏中的【新手教程】流光胶囊
    const guidePill = page.locator('.guide-pill')
    await expect(guidePill).toBeVisible()
    await expect(guidePill).toContainText('新手教程')

    // 点击打开教程抽屉
    await guidePill.click()
    const drawer = page.locator('.guide-drawer')
    await expect(drawer).toBeVisible()
    await expect(page.locator('.guide-title')).toContainText('MistRelay 新手全景使用手册')

    // 严密验证抽屉已 append-to-body 且具有全屏高视口（杜绝陷入 64px 顶栏高度陷阱）
    const drawerBox = await drawer.boundingBox()
    expect(drawerBox).not.toBeNull()
    expect(drawerBox!.height).toBeGreaterThan(500)
    const overlayParentTag = await page.evaluate(() => {
      return document.querySelector('.el-overlay.is-drawer')?.parentElement?.tagName
    })
    expect(overlayParentTag).toBe('BODY')

    // 验证 5 大选项卡
    const tabBtns = page.locator('.guide-tab-btn')
    await expect(tabBtns).toHaveCount(5)
    await expect(tabBtns.nth(0)).toContainText('快速入门')
    await expect(tabBtns.nth(1)).toContainText('文件入库3步法')
    await expect(tabBtns.nth(2)).toContainText('影音流播与串流')
    await expect(tabBtns.nth(3)).toContainText('私有VPS边缘分流')
    await expect(tabBtns.nth(4)).toContainText('Bot指令与FAQ')

    // 切换至【文件入库3步法】
    await tabBtns.nth(1).click()
    await expect(page.locator('.method-title').first()).toContainText('Telegram 机器人私聊直投')
    await expect(page.locator('.code-snippet-box')).toBeVisible()

    // 切换至【Bot指令与FAQ】
    await tabBtns.nth(4).click()
    await expect(page.locator('.commands-table')).toBeVisible()
    await expect(page.locator('.command-row')).toHaveCount(3)
    await expect(page.locator('.faq-container')).toBeVisible()

    // 关闭抽屉
    await page.locator('.guide-close-btn').click()
    await expect(drawer).not.toBeVisible()
  })

  test('tenant dashboard renders onboarding roadmap card and allows collapsing', async ({ page }) => {
    await mockCommonApis(page, { totalFiles: 0, hasDismissedWelcome: true })
    await page.goto('/dashboard')

    // 验证向导卡片渲染
    const onboardingCard = page.locator('.tenant-onboarding-card')
    await expect(onboardingCard).toBeVisible()
    await expect(page.locator('.onboarding-star-badge')).toContainText('新人快速起航向导')

    // 验证 4 个步骤项
    const stepBoxes = page.locator('.onboarding-step-box')
    await expect(stepBoxes).toHaveCount(4)
    await expect(stepBoxes.nth(0)).toContainText('专属存储空间绑定')
    await expect(stepBoxes.nth(1)).toContainText('首份媒体资产入库')
    await expect(stepBoxes.nth(2)).toContainText('体验云盘与 M3U 串流')
    await expect(stepBoxes.nth(3)).toContainText('挂载私有 VPS 边缘分流')

    // 验证折叠功能
    await page.locator('.onboarding-btn-collapse').click()
    await expect(onboardingCard).not.toBeVisible()

    // 验证出现折叠胶囊
    const collapsedCard = page.locator('.onboarding-collapsed-card')
    await expect(collapsedCard).toBeVisible()
    await expect(collapsedCard).toContainText('新人快速起航向导')

    // 再次点击展开
    await collapsedCard.click()
    await expect(onboardingCard).toBeVisible()
  })

  test('first-time tenant login pops up welcome dialog with dismissal persistence', async ({ page }) => {
    await mockCommonApis(page, { totalFiles: 0, hasDismissedWelcome: false })
    await page.goto('/dashboard')

    // 验证弹出首次登录欢迎弹窗
    const welcomeDialog = page.locator('.welcome-dialog')
    await expect(welcomeDialog).toBeVisible()
    await expect(page.locator('.welcome-title')).toContainText('欢迎加入 MistRelay 云盘空间！')
    await expect(page.locator('.welcome-info-card')).toContainText('DC5')

    // 点击“开始探索工作台”
    await page.locator('.start-btn').click()
    await expect(welcomeDialog).not.toBeVisible()

    // 验证 localStorage 已记录不再提示
    const isDismissed = await page.evaluate(() => window.localStorage.getItem('mistrelay_welcome_dismissed'))
    expect(isDismissed).toBe('true')

    // 刷新页面，验证弹窗不再弹出
    await page.reload()
    await expect(page.locator('.welcome-dialog')).not.toBeVisible()
  })

  test('TG drive renders 3-card rich onboarding guide on empty state', async ({ page }) => {
    await mockCommonApis(page, { totalFiles: 0, hasDismissedWelcome: true })
    await page.goto('/drive')

    // 验证空状态富媒体引导容器
    const emptyContainer = page.locator('.empty-onboarding-container')
    await expect(emptyContainer).toBeVisible()
    await expect(page.locator('.empty-title')).toContainText('专属云盘虚位以待 · 开启首份资产入库')

    // 验证 3 大方式卡片
    const methodCards = page.locator('.empty-method-card')
    await expect(methodCards).toHaveCount(3)
    await expect(methodCards.nth(0)).toContainText('Telegram 私聊直投')
    await expect(methodCards.nth(1)).toContainText('Aria2 磁力全速转存')
    await expect(methodCards.nth(2)).toContainText('受限频道破除采集')

    // 点击“打开采集器”按钮，验证触发采集弹窗
    await page.locator('.method-card-btn', { hasText: '打开采集器' }).click()
    const harvesterDialog = page.locator('.harvester-dialog')
    await expect(harvesterDialog).toBeVisible()
    // 关闭采集弹窗
    await page.locator('.harvester-dialog button', { hasText: '关闭窗口' }).click()
    await expect(harvesterDialog).not.toBeVisible()

    // 点击底部的“查阅完整入库教程”，验证调起教程抽屉
    await page.locator('.guide-text-btn', { hasText: '查阅完整入库教程' }).click()
    const drawer = page.locator('.guide-drawer')
    await expect(drawer).toBeVisible()
    await expect(page.locator('.guide-tab-btn.is-active')).toContainText('文件入库3步法')
  })

  test('onboarding guide adapts smoothly on 375px mobile viewport without horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await mockCommonApis(page, { totalFiles: 0, hasDismissedWelcome: true })
    await page.goto('/dashboard')

    // 验证无横向滚动条
    const hasHorizontalScroll = await page.evaluate(() => {
      return document.documentElement.scrollWidth > window.innerWidth
    })
    expect(hasHorizontalScroll).toBe(false)

    // 验证向导卡片在手机端正常展示
    const onboardingCard = page.locator('.tenant-onboarding-card')
    await expect(onboardingCard).toBeVisible()

    // 验证顶栏教程胶囊自适应紧凑图标
    const guidePill = page.locator('.guide-pill')
    await expect(guidePill).toBeVisible()
    await guidePill.click()

    // 验证抽屉全屏展开且无横向滚动溢出
    const drawer = page.locator('.guide-drawer')
    await expect(drawer).toBeVisible()
  })
})
