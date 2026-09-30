import { expect, test, type Page } from '@playwright/test'

async function setupMobileMocks(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'mobile-test-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'mobile-test-refresh')
  })

  // 兜底所有未显式 mock 的 API，防止 401 触发全局跳转
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    })
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: {
          id: 1,
          username: 'admin',
          role: 'admin',
          dc_id: 5,
          bin_channel_username: 'mistrelay_channel',
        },
      }),
    })
  })

  await page.route('**/api/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ready: true, server_status: 'running', version: 'v2.2.5' }),
    })
  })

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        server_status: 'running',
        uptime: '1 天 2 小时',
        telegram_bot: '@MistRelayBot',
        connected_bots: 2,
        version: 'v2.2.5',
        loads: { 'Bot-1': 0 },
        channel_info: { channel_id: -1001234, public_handle: 'test', accessible_bots: 2, write_bots: 1 },
        bot_details: [],
      }),
    })
  })

  await page.route('**/api/system/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        status: 'running',
        uptime: 3600,
        memory: { total: 1024, used: 256, free: 768, percent: 25 },
        cpu: { percent: 12 },
        disk: { total: 100, used: 20, free: 80, percent: 20 },
      }),
    })
  })

  await page.route('**/api/system/resources**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          cpu: { percent: 24.5 },
          memory: { percent: 45.2, used: 3865470566, total: 8552099840 },
          disk: { percent: 61.8, used: 64424509440, total: 107374182400 },
        },
      }),
    })
  })

  await page.route('**/api/downloads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { total: 10, completed: 8, failed: 1 } }),
    })
  })

  await page.route('**/api/uploads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { cleaned: 8 } }),
    })
  })

  await page.route('**/api/downloads**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        grouped: true,
        data: [
          {
            group_key: 'g1',
            group_type: 'single',
            caption: '测试下载任务',
            created_at: '2026-09-30T00:00:00Z',
            stats: { total_files: 1, completed: 0, downloading: 1, failed: 0, pending: 0, total_size: 50000000, completed_size: 25000000 },
            downloads: [
              {
                id: 101,
                gid: 'gid_101',
                file_name: 'mobile_sample_video.mp4',
                status: 'downloading',
                total_length: 50000000,
                completed_length: 25000000,
                download_speed: 2500000,
                created_at: '2026-09-30T00:00:00Z',
                updated_at: '2026-09-30T00:01:00Z',
                uploads: [],
              },
            ],
          },
        ],
      }),
    })
  })

  await page.route('**/api/uploads**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: [] }),
    })
  })

  await page.route('**/api/queue**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queue: [], queue_size: 0 }),
    })
  })
}

test.describe('移动平台响应式与导航适配测试', () => {
  test.use({
    viewport: { width: 375, height: 667 }, // 典型移动手机视口 (iPhone SE / 8)
  })

  test('在 375px 移动端下侧边栏隐藏且底部导航栏正常渲染与切换', async ({ page }) => {
    await setupMobileMocks(page)
    await page.goto('/dashboard')

    // 1. 验证桌面侧边栏在手机视口下彻底隐藏
    const desktopSidebar = page.locator('.sidebar')
    await expect(desktopSidebar).toHaveCount(0)

    // 2. 验证主容器启用移动端流式布局类
    const mainContainer = page.locator('.main-container')
    await expect(mainContainer).toHaveClass(/is-mobile-layout/)

    // 3. 验证底部导航栏渲染并包含 4 大入口和更多
    const bottomNav = page.locator('.app-bottom-nav')
    await expect(bottomNav).toBeVisible()
    await expect(bottomNav.getByText('仪表板')).toBeVisible()
    await expect(bottomNav.getByText('任务')).toBeVisible()
    await expect(bottomNav.getByText('TG网盘')).toBeVisible()
    await expect(bottomNav.getByText('分流')).toBeVisible()
    await expect(bottomNav.getByText('更多')).toBeVisible()

    // 4. 验证顶栏汉堡包按钮展开移动端抽屉
    const hamburgerBtn = page.locator('.mobile-hamburger-btn')
    await expect(hamburgerBtn).toBeVisible()
    await hamburgerBtn.click()

    const drawer = page.locator('.mobile-nav-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText('核心导航')).toBeVisible()
    await expect(drawer.getByText('集群管理中台')).toBeVisible()

    // 5. 点击抽屉内的任务中心进行导航并自动关闭抽屉
    await drawer.getByText('任务中心').click()
    await expect(page).toHaveURL(/.*\/downloads/)
    await expect(drawer).toBeHidden()

    // 6. 在任务中心点击底部导航栏切换到 TG网盘
    await bottomNav.getByText('TG网盘').click()
    await expect(page).toHaveURL(/.*\/drive/)
  })

  test('移动端任务中心渲染触控卡片流替代宽幅表格', async ({ page }) => {
    await setupMobileMocks(page)
    await page.goto('/downloads')

    // 验证移动端任务卡片列表可见
    const mobileCards = page.locator('.mobile-task-cards-list')
    await expect(mobileCards).toBeVisible()
    await expect(mobileCards.getByText('mobile_sample_video.mp4')).toBeVisible()
    await expect(mobileCards.getByText('下载中')).toBeVisible()
  })
})
