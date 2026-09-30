import { test, expect, type Page } from '@playwright/test'

async function setupCommonMocks(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'mobile-screenshot-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'mobile-screenshot-refresh')
    window.localStorage.setItem('mistrelay.drive.viewMode', 'grid')
  })

  // 兜底所有未显式 mock 的 API，防止 401 触发全局跳转
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    })
  })

  // 用户与权限
  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: {
          id: 1,
          username: 'MistRelay Admin',
          role: 'admin',
          dc_id: 5,
          bin_channel_username: 'mistrelay_storage',
        },
      }),
    })
  })

  // 健康与服务状态
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
        uptime: '3 天 14 小时',
        telegram_bot: '@MistRelayOfficialBot',
        connected_bots: 4,
        version: 'v2.2.5',
        loads: { 'Bot-SG-1': 12, 'Bot-SG-2': 18, 'Bot-HK-1': 5, 'Bot-US-1': 8 },
        channel_info: {
          channel_id: -100192837465,
          public_handle: 'mistrelay_storage',
          accessible_bots: 4,
          write_bots: 2,
        },
        bot_details: [
          { name: 'Bot-SG-1', dc_id: 5, status: 'active', ping: 18 },
          { name: 'Bot-SG-2', dc_id: 5, status: 'active', ping: 22 },
        ],
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
        register_url: 'https://t.me/MistRelayOfficialBot?start=register',
      }),
    })
  })

  // 系统硬件资源
  await page.route('**/api/system/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        status: 'running',
        uptime: 309600,
        memory: { total: 16384, used: 4096, free: 12288, percent: 25 },
        cpu: { percent: 18.5 },
        disk: { total: 500, used: 124, free: 376, percent: 24.8 },
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
          cpu: { percent: 18.5 },
          memory: { percent: 25.0, used: 4294967296, total: 17179869184 },
          disk: { percent: 24.8, used: 133143986176, total: 536870912000 },
          network: { rx_sec: 12400000, tx_sec: 48500000 },
        },
      }),
    })
  })

  // 任务统计与列表
  await page.route('**/api/downloads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { total: 42, completed: 38, failed: 1, active: 3 } }),
    })
  })

  await page.route('**/api/uploads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { total: 56, cleaned: 52, active: 4 } }),
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
            caption: 'Cyberpunk 2077 Edgerunners S01 4K HDR',
            created_at: '2026-09-30T08:00:00Z',
            stats: { total_files: 1, completed: 0, downloading: 1, failed: 0, pending: 0, total_size: 18253611008, completed_size: 12451840000 },
            downloads: [
              {
                id: 101,
                gid: 'gid_101',
                file_name: 'Cyberpunk_Edgerunners_S01E01_4K.mkv',
                status: 'downloading',
                total_length: 18253611008,
                completed_length: 12451840000,
                download_speed: 45200000,
                created_at: '2026-09-30T08:00:00Z',
                updated_at: '2026-09-30T08:15:00Z',
                uploads: [],
              },
            ],
          },
          {
            group_key: 'g2',
            group_type: 'single',
            caption: 'Ubuntu 24.04 LTS Desktop ISO',
            created_at: '2026-09-30T08:10:00Z',
            stats: { total_files: 1, completed: 0, downloading: 1, failed: 0, pending: 0, total_size: 6144000000, completed_size: 4915200000 },
            downloads: [
              {
                id: 102,
                gid: 'gid_102',
                file_name: 'ubuntu-24.04-desktop-amd64.iso',
                status: 'downloading',
                total_length: 6144000000,
                completed_length: 4915200000,
                download_speed: 28400000,
                created_at: '2026-09-30T08:10:00Z',
                updated_at: '2026-09-30T08:16:00Z',
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
      body: JSON.stringify({
        success: true,
        data: [
          {
            id: 201,
            download_id: 101,
            file_name: 'Cyberpunk_Edgerunners_S01E01_4K.mkv',
            status: 'uploading',
            total_bytes: 18253611008,
            uploaded_bytes: 9126805504,
            upload_speed: 31500000,
            created_at: '2026-09-30T08:20:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/queue**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        queue: [],
        queue_size: 0,
        current_processing: null,
      }),
    })
  })

  // TG 网盘数据
  await page.route('**/api/telegram/usage**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total_count: 64,
          total_size: 107374182400, // 100 GB
          videos: 32,
          images: 18,
          audios: 8,
          documents: 6,
        },
      }),
    })
  })

  await page.route('**/api/telegram/thumbnails/status**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        generating: false,
        total_scanned: 64,
        queued: 0,
      }),
    })
  })

  await page.route('**/api/edge/available-nodes**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        nodes: [
          { id: 1, name: 'SG-Edge-01 (新加坡)', country_code: 'SG', ping_url: '/ping', stream_base_url: 'https://sg.edge.mistrelay.org', rtt_ms: 18 },
          { id: 2, name: 'HK-Edge-01 (香港专线)', country_code: 'HK', ping_url: '/ping', stream_base_url: 'https://hk.edge.mistrelay.org', rtt_ms: 24 },
        ],
      }),
    })
  })

  await page.route('**/api/telegram/botfather/accounts**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, accounts: [] }),
    })
  })

  await page.route('**/api/telegram/harvester/status**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, running: false, active_tasks: 0 }),
    })
  })

  await page.route('**/api/telegram/browse**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        total: 6,
        page: 1,
        page_size: 20,
        items: [
          {
            entry_type: 'file',
            file_unique_id: 'vid_01',
            file_name: 'Blade_Runner_2049_HDR.mp4',
            mime_type: 'video/mp4',
            file_size: 4294967296, // 4 GB
            chat_id: -100192837465,
            message_id: 1042,
            dc_id: 5,
            dc_label: 'DC5',
            message_date: '2026-09-30 09:20:00',
            stream_url: 'https://stream.mistrelay.org/1042',
          },
          {
            entry_type: 'file',
            file_unique_id: 'vid_02',
            file_name: 'Suzume_No_Tojimari_1080p.mkv',
            mime_type: 'video/x-matroska',
            file_size: 2847924224, // 2.65 GB
            chat_id: -100192837465,
            message_id: 1043,
            dc_id: 5,
            dc_label: 'DC5',
            message_date: '2026-09-30 08:45:00',
            stream_url: 'https://stream.mistrelay.org/1043',
          },
          {
            entry_type: 'file',
            file_unique_id: 'aud_01',
            file_name: 'RADWIMPS_Kanata_Haluka.flac',
            mime_type: 'audio/flac',
            file_size: 58720256, // 56 MB
            chat_id: -100192837465,
            message_id: 1044,
            dc_id: 5,
            dc_label: 'DC5',
            message_date: '2026-09-29 23:10:00',
            stream_url: 'https://stream.mistrelay.org/1044',
          },
          {
            entry_type: 'file',
            file_unique_id: 'img_01',
            file_name: 'Tokyo_Night_Wallpaper_8K.png',
            mime_type: 'image/png',
            file_size: 24117248, // 23 MB
            chat_id: -100192837465,
            message_id: 1045,
            dc_id: 5,
            dc_label: 'DC5',
            message_date: '2026-09-29 18:00:00',
            stream_url: 'https://stream.mistrelay.org/1045',
          },
          {
            entry_type: 'file',
            file_unique_id: 'doc_01',
            file_name: 'MistRelay_Architecture_Whitepaper.pdf',
            mime_type: 'application/pdf',
            file_size: 15728640, // 15 MB
            chat_id: -100192837465,
            message_id: 1046,
            dc_id: 5,
            dc_label: 'DC5',
            message_date: '2026-09-29 14:30:00',
            stream_url: 'https://stream.mistrelay.org/1046',
          },
          {
            entry_type: 'folder',
            media_group_id: 'group_sakura_2026',
            file_name: '2026_Sakura_Festival_Photos',
            item_count: 16,
            total_size: 157286400,
            dc_id: 5,
            message_date: '2026-09-29 10:15:00',
          },
        ],
      }),
    })
  })
}

test.describe('MistRelay 移动端真实视觉与功能截图测试 (390x844)', () => {
  test.use({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  })

  test('截图 1: 移动端仪表板 (/dashboard)', async ({ page }) => {
    await setupCommonMocks(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    // 确保主容器是移动端布局
    await expect(page.locator('.main-container')).toHaveClass(/is-mobile-layout/)
    // 确保底部导航栏可见
    await expect(page.locator('.app-bottom-nav')).toBeVisible()

    // 截图保存
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-dashboard.png',
      fullPage: false,
    })
  })

  test('截图 2: 移动端任务中心 (/downloads)', async ({ page }) => {
    await setupCommonMocks(page)
    await page.goto('/downloads')
    await page.waitForLoadState('networkidle')

    // 验证移动端下载卡片已渲染 (使用 first 确保下载列表卡片)
    const mobileCards = page.locator('.mobile-task-cards-list').first()
    await expect(mobileCards).toBeVisible()
    await expect(mobileCards.getByText('Cyberpunk_Edgerunners_S01E01_4K.mkv')).toBeVisible()

    // 截图保存下载中标签页
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-downloads.png',
      fullPage: false,
    })

    // 切换到上传标签页并截取上传卡片
    await page.getByRole('tab', { name: /正在上传/ }).click()
    const uploadCards = page.locator('.mobile-task-cards-list').nth(1)
    await expect(uploadCards).toBeVisible()
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-downloads-upload.png',
      fullPage: false,
    })
  })

  test('截图 3: 移动端 TG 网盘 2 列网格卡片 (/drive)', async ({ page }) => {
    await setupCommonMocks(page)
    await page.goto('/drive')
    await page.waitForLoadState('networkidle')

    // 确保网盘卡片已加载渲染
    await expect(page.locator('.grid-view')).toBeVisible()
    await expect(page.getByText('Blade_Runner_2049_HDR.mp4')).toBeVisible()

    // 截图 1: 网盘顶栏与指标概览
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-drive-overview.png',
      fullPage: false,
    })

    // 滚动至 2 列网格卡片流核心视图
    await page.evaluate(() => window.scrollTo({ top: 350, behavior: 'instant' }))
    await page.waitForTimeout(300)

    // 截图 2: 2 列触控卡片流核心视图 (未勾选状态，清爽浏览)
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-drive.png',
      fullPage: false,
    })

    // 勾选第一项，展示移动端批量操作栏激活状态
    await page.locator('.grid-item-checkbox').first().click()
    await page.waitForTimeout(200)

    // 截图 3: 移动端选中状态与 2x2 批量管理操作栏
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-drive-selected.png',
      fullPage: false,
    })
  })

  test('截图 4: 移动端全局侧滑抽屉展开态 (AppMobileDrawer)', async ({ page }) => {
    await setupCommonMocks(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    // 点击顶栏汉堡包展开抽屉
    const hamburgerBtn = page.locator('.mobile-hamburger-btn')
    await expect(hamburgerBtn).toBeVisible()
    await hamburgerBtn.click()

    // 抽屉可见
    const drawer = page.locator('.mobile-nav-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText('核心导航')).toBeVisible()
    await expect(drawer.getByText('集群管理中台')).toBeVisible()
    await page.waitForTimeout(300) // 等待展开动画完全就绪

    // 截图保存
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-drawer.png',
      fullPage: false,
    })
  })

  test('截图 5: 移动端 Telegram 免密与登录页 (/login)', async ({ page }) => {
    // 拦截 telegram-web-app.js，注入模拟 Telegram 客户端环境
    await page.route('https://telegram.org/js/telegram-web-app.js', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: `
          window.Telegram = {
            WebApp: {
              initData: 'query_id=AAHdF6IQAAAAAN0XohD9...&user=%7B%22id%22%3A123456789%2C%22first_name%22%3A%22Alex%22%7D&auth_date=1720000000&hash=mocked_hash',
              initDataUnsafe: { user: { id: 123456789, first_name: 'Alex' } },
              ready: function() {},
              expand: function() {},
              BackButton: { isVisible: false, onClick: function() {}, offClick: function() {}, show: function() {}, hide: function() {} }
            }
          };
        `,
      })
    })

    await page.addInitScript(() => {
      window.localStorage.removeItem('token')
      window.localStorage.removeItem('mistrelay.refreshToken')
    })

    // 拦截 TMA 自动登录网络请求，防止其跳转，以展示登录卡片与 TMA 入口
    await page.route('**/api/auth/tma', async route => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ success: false, error: 'Telegram 免密环境已就绪' }),
      })
    })

    await page.route('**/api/auth/bot-info', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          bot_username: 'MistRelayOfficialBot',
          register_url: 'https://t.me/MistRelayOfficialBot?start=register',
        }),
      })
    })

    await page.goto('/login')
    await page.waitForLoadState('networkidle')

    // 验证 TMA 免密登录提示卡片渲染
    await expect(page.locator('.tma-quick-box')).toBeVisible()
    await expect(page.getByText('Telegram 客户端一键免密登录')).toBeVisible()

    // 截图保存
    await page.screenshot({
      path: '/root/MistRelay-dev/mobile-screenshots/mobile-login.png',
      fullPage: false,
    })
  })
})
