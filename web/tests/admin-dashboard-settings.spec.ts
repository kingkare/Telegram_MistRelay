import { expect, test, type Page } from '@playwright/test'

async function mockDashboardApis(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'admin-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'admin-refresh')
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'admin', role: 'admin' },
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
        uptime: '3 天 12 小时',
        telegram_bot: '@MistRelayBot',
        connected_bots: 3,
        version: 'v2.2.5',
        loads: {
          'Worker-Bot-1': 1,
          'Worker-Bot-2': 3,
          'Worker-Bot-3': 0,
        },
        channel_info: {
          channel_id: -1001998444696,
          channel_type: 'public',
          public_handle: 'jiuyue1314520',
          no_join_balancing_active: true,
          accessible_bots: 3,
          write_bots: 1,
        },
        bot_details: [
          {
            index: 0,
            name: 'Worker-Bot-1',
            username: '@MistRelayBot',
            mode: 'primary_admin',
            can_read: true,
            can_write: true,
            active_requests: 1,
          },
          {
            index: 1,
            name: 'Worker-Bot-2',
            username: '@WorkerBot1',
            mode: 'no_join_resolved',
            can_read: true,
            can_write: false,
            active_requests: 3,
          },
          {
            index: 2,
            name: 'Worker-Bot-3',
            username: '@WorkerBot2',
            mode: 'no_join_resolved',
            can_read: true,
            can_write: false,
            active_requests: 0,
          },
        ],
      }),
    })
  })

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        server_status: 'running',
        uptime: '3 天 12 小时',
        telegram_bot: '@MistRelayBot',
        connected_bots: 3,
        version: 'v2.2.5',
        loads: {
          'Worker-Bot-1': 1,
          'Worker-Bot-2': 3,
          'Worker-Bot-3': 0,
        },
        channel_info: {
          channel_id: -1001998444696,
          channel_type: 'public',
          public_handle: 'jiuyue1314520',
          no_join_balancing_active: true,
          accessible_bots: 3,
          write_bots: 1,
        },
        bot_details: [
          {
            index: 0,
            name: 'Worker-Bot-1',
            username: '@MistRelayBot',
            mode: 'primary_admin',
            can_read: true,
            can_write: true,
            active_requests: 1,
          },
          {
            index: 1,
            name: 'Worker-Bot-2',
            username: '@WorkerBot1',
            mode: 'no_join_resolved',
            can_read: true,
            can_write: false,
            active_requests: 3,
          },
          {
            index: 2,
            name: 'Worker-Bot-3',
            username: '@WorkerBot2',
            mode: 'no_join_resolved',
            can_read: true,
            can_write: false,
            active_requests: 0,
          },
        ],
      }),
    })
  })

  await page.route('**/api/downloads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total: 128,
          completed: 110,
          failed: 3,
        },
      }),
    })
  })

  await page.route('**/api/uploads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          cleaned: 95,
        },
      }),
    })
  })

  await page.route('**/api/downloads?**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          {
            id: 1,
            file_name: 'cyberpunk_edgerunners_ep01.mp4',
            status: 'completed',
            created_at: '2026-09-26T04:00:00Z',
          },
          {
            id: 2,
            file_name: 'soundtrack_flac.zip',
            status: 'completed',
            created_at: '2026-09-26T03:30:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/downloads', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          {
            id: 1,
            file_name: 'cyberpunk_edgerunners_ep01.mp4',
            status: 'completed',
            created_at: '2026-09-26T04:00:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/monitor/trend**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { timestamp: 1727320000000, upload: 1048576, download: 5242880, io: 2048 },
          { timestamp: 1727320002000, upload: 2097152, download: 10485760, io: 4096 },
        ],
      }),
    })
  })

  await page.route('**/api/system/trend**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { timestamp: 1727320000000, upload: 1048576, download: 5242880, io: 2048 },
          { timestamp: 1727320002000, upload: 2097152, download: 10485760, io: 4096 },
        ],
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
}

async function mockSettingsApis(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'admin-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'admin-refresh')
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'admin', role: 'admin' },
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
        uptime: '3 天 12 小时',
        telegram_bot: '@MistRelayBot',
        connected_bots: 3,
        version: 'v2.2.5',
        loads: {
          'Worker-Bot-1': 1,
          'Worker-Bot-2': 3,
          'Worker-Bot-3': 0,
        },
        channel_info: {
          channel_id: -1001998444696,
          channel_type: 'public',
          public_handle: 'jiuyue1314520',
          no_join_balancing_active: true,
          accessible_bots: 3,
          write_bots: 1,
        },
        bot_details: [
          {
            index: 0,
            name: 'Worker-Bot-1',
            username: '@MistRelayBot',
            mode: 'primary_admin',
            can_read: true,
            can_write: true,
            active_requests: 1,
          },
          {
            index: 1,
            name: 'Worker-Bot-2',
            username: '@WorkerBot1',
            mode: 'no_join_resolved',
            can_read: true,
            can_write: false,
            active_requests: 3,
          },
          {
            index: 2,
            name: 'Worker-Bot-3',
            username: '@WorkerBot2',
            mode: 'no_join_resolved',
            can_read: true,
            can_write: false,
            active_requests: 0,
          },
        ],
      }),
    })
  })

  await page.route('**/api/config**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          API_ID: 123456,
          API_HASH: 'hash123',
          BOT_TOKEN: 'token123',
          ADMIN_ID: 654321,
          UP_TELEGRAM: true,
        },
      }),
    })
  })

  await page.route('**/api/system/docker/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        in_docker: true,
        container_name: 'mistrelay',
        status: 'running',
        status_source: 'application',
        control_enabled: false,
        control_message: '宿主 Docker 控制未启用，当前状态来自应用自检',
        application_version: 'v2.2.5',
        created: '2026-08-13T10:00:00+00:00',
      }),
    })
  })

  await page.route('**/api/system/docker/logs**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, logs: 'service ready', source: 'application' }),
    })
  })
}

test('dashboard renders modernized header, cards, and panels', async ({ page }) => {
  await mockDashboardApis(page)
  await page.goto('/dashboard')

  // Header & branding
  await expect(page.getByText('系统监控仪表板')).toBeVisible()
  await expect(page.getByText('System Overview')).toBeVisible()
  await expect(page.getByRole('button', { name: '刷新数据' })).toBeVisible()

  // 4 Stat Cards
  await expect(page.getByText('传输完成')).toBeVisible()
  await expect(page.getByText('清理归档')).toBeVisible()
  await expect(page.getByText('失败待查')).toBeVisible()
  await expect(page.getByText('总调度量')).toBeVisible()

  // Chart & Resources
  await expect(page.getByText('实时网络与传输趋势')).toBeVisible()
  await expect(page.getByText('系统核心负载')).toBeVisible()
  await expect(page.getByText('中央处理器 CPU')).toBeVisible()
  await expect(page.getByText('运行内存 RAM')).toBeVisible()
  await expect(page.getByText('本地存储 Disk')).toBeVisible()

  // Activity & System status
  await expect(page.getByText('最近任务动态')).toBeVisible()
  await expect(page.getByText('cyberpunk_edgerunners_ep01.mp4')).toBeVisible()
  await expect(page.getByText('系统与节点运行状态')).toBeVisible()
  await expect(page.getByText('@MistRelayBot').first()).toBeVisible()
})

test('dashboard is responsive at 768px viewport without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await mockDashboardApis(page)
  await page.goto('/dashboard')

  await expect(page.getByText('系统监控仪表板')).toBeVisible()

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('settings renders modern header, tabs, and content', async ({ page }) => {
  await mockSettingsApis(page)
  await page.goto('/settings')

  // Header
  await expect(page.getByText('系统设置与运维中心')).toBeVisible()
  await expect(page.getByText('Config & DevOps')).toBeVisible()

  // Tabs
  await expect(page.getByRole('tab', { name: /客户端连接/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /Telegram配置/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /下载配置/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /Aria2配置/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /直链功能/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /容器管理/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /系统日志/ })).toBeVisible()

  // Switch to stream tab and verify multi-bot cluster diagnostic card
  await page.getByRole('tab', { name: /直链功能/ }).click()
  await expect(page.getByText('多 Bot 集群与免加频道状态诊断')).toBeVisible()
  await expect(page.getByText('免加频道负载均衡与多 DC 满速分流')).toBeVisible()
  await expect(page.getByText('免加频道就绪').first()).toBeVisible()

  // Switch to container tab
  await page.getByRole('tab', { name: /容器管理/ }).click()
  await expect(page.getByText('Docker容器状态')).toBeVisible()
  await expect(page.getByText('mistrelay', { exact: true })).toBeVisible()
})

test('settings is responsive at 768px viewport without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await mockSettingsApis(page)
  await page.goto('/settings')

  await expect(page.getByText('系统设置与运维中心')).toBeVisible()

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('settings multi-bot cluster supports hot-add dialog and botfather auto-create dialog', async ({ page }) => {
  await mockSettingsApis(page)
  await page.goto('/settings')

  // Switch to stream tab
  await page.getByRole('tab', { name: /直链功能/ }).click()
  await expect(page.getByText('多 Bot 集群与免加频道状态诊断')).toBeVisible()

  // Test opening Hot-Add Dialog
  const hotAddBtn = page.getByRole('button', { name: /快速热添加 Token/ })
  await expect(hotAddBtn).toBeVisible()
  await hotAddBtn.click()
  await expect(page.getByText('快速热添加负载机器人 Token')).toBeVisible()
  await expect(page.getByText('零停机热插拔')).toBeVisible()
  await page.getByRole('button', { name: '取消' }).click()

  // Test opening BotFather Pipeline Dialog
  const botFatherBtn = page.getByRole('button', { name: /API协议号自动创机/ })
  await expect(botFatherBtn).toBeVisible()
  await botFatherBtn.click()
  await expect(page.getByText('API 协议号一键批量创机与入网 (@BotFather 流水线)')).toBeVisible()
  await expect(page.getByText('全生态协议号支持')).toBeVisible()
  await expect(page.getByText('目标扩容节点数')).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
})
