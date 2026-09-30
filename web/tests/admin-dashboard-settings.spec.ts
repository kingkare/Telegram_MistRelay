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

test('settings stream tab renders forward rebrand configuration and preview', async ({ page }) => {
  await mockSettingsApis(page)
  await page.route('**/api/telegram/rebrand/preview', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          effective_channel: '@jiuyue1314520',
          cleaned_caption: '精彩热门视频 欢迎关注 @jiuyue1314520 https://t.me/jiuyue1314520 获取更多！\n\n📢 关注官方频道: @jiuyue1314520',
          cleaned_filename: '棒棒糖 (1).mp4'
        }
      })
    })
  })

  await page.goto('/settings')
  await page.getByRole('tab', { name: /直链功能/ }).click()

  await expect(page.getByText('频道入库无痕洗白与智能归属改写')).toBeVisible()
  await expect(page.getByText('启用无痕洗白')).toBeVisible()
  await expect(page.getByText('归属目标频道')).toBeVisible()
  await expect(page.getByText('配文落款签名')).toBeVisible()
  await expect(page.getByText('净化网盘文件名', { exact: true })).toBeVisible()
  await expect(page.getByText('自定义替换/剔除规则')).toBeVisible()

  // Trigger preview
  await page.getByRole('button', { name: '测试预览' }).click()
  await expect(page.getByText('棒棒糖 (1).mp4')).toBeVisible()
  await expect(page.getByText(/📢 关注官方频道: @jiuyue1314520/)).toBeVisible()
})

test('tenant dashboard renders personal workspace without host or cluster monitoring', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'tenant-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'tenant-refresh')
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: {
          id: 9,
          username: 'alice_tenant',
          role: 'user',
          tg_user_id: 88990011,
          tg_username: 'alice_tg',
          dc_id: 5,
          bin_channel_id: -10088990011,
          bin_channel_username: 'mr_u8899_alice',
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
        uptime: '3 天 12 小时',
        telegram_bot: '@MistRelayBot',
        connected_bots: 1,
        channel_info: {
          channel_id: -10088990011,
          channel_type: 'public',
          public_handle: 'mr_u8899_alice',
          no_join_balancing_active: true,
        },
        version: 'v2.2.5',
      }),
    })
  })

  await page.route('**/api/telegram/usage**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total_count: 18,
          total_size: 1024 * 1024 * 512,
          videos: 10,
          images: 5,
          audios: 2,
          documents: 1,
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
        data: {
          total: 12,
          completed: 10,
          downloading: 1,
          pending: 0,
          waiting: 0,
          failed: 1,
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
          cleaned: 10,
        },
      }),
    })
  })

  await page.route('**/api/downloads**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        grouped: false,
        data: [
          {
            id: 101,
            file_name: 'tenant_video_01.mp4',
            status: 'completed',
            created_at: '2026-09-28T08:00:00Z',
          },
        ],
      }),
    })
  })

  await page.goto('/dashboard')

  await expect(page.getByText('个人云盘工作台')).toBeVisible()
  await expect(page.getByText('Personal Workspace')).toBeVisible()
  await expect(page.getByText('云盘文件总数')).toBeVisible()
  await expect(page.getByText('云盘存储结构分析')).toBeVisible()
  await expect(page.getByText('专属存储频道与账户档案')).toBeVisible()
  await expect(page.getByText('@mr_u8899_alice (-10088990011)')).toBeVisible()

  await expect(page.getByText('系统核心负载')).toHaveCount(0)
  await expect(page.getByText('实时网络与传输趋势')).toHaveCount(0)
  await expect(page.getByText('分流机器人节点负荷')).toHaveCount(0)
})


test('dashboard bot loads with many workers stays compact, scrollable, and supports filter / expand', async ({ page }) => {
  await mockDashboardApis(page)

  // Override /api/status with 24 worker bots
  const loads: Record<string, number> = {}
  const botDetails: any[] = []
  for (let i = 1; i <= 24; i++) {
    const key = `Worker-Bot-${i}`
    const loadVal = i === 5 ? 6 : i === 12 ? 3 : i === 19 ? 1 : 0
    loads[key] = loadVal
    botDetails.push({
      index: i - 1,
      name: key,
      username: `@MistNode_${String(i).padStart(2, '0')}_Bot`,
      mode: i === 1 ? 'primary_admin' : 'no_join_resolved',
      can_read: true,
      can_write: i === 1,
      active_requests: loadVal,
    })
  }

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        server_status: 'running',
        uptime: '12 天 4 小时',
        telegram_bot: '@MistNode_01_Bot',
        connected_bots: 24,
        version: 'v2.2.5',
        loads,
        channel_info: {
          channel_id: -1001998444696,
          channel_type: 'public',
          public_handle: 'jiuyue1314520',
          no_join_balancing_active: true,
          accessible_bots: 24,
          write_bots: 1,
        },
        bot_details: botDetails,
      }),
    })
  })

  await page.goto('/dashboard')

  await expect(page.getByText('分流机器人节点负荷')).toBeVisible()
  await expect(page.getByText('全部 (24)')).toBeVisible()
  await expect(page.getByText('忙碌 (3)')).toBeVisible()
  await expect(page.getByText('空闲 (21)')).toBeVisible()

  // Verify the grid is constrained in height so it does not stretch the page
  const grid = page.locator('.bot-loads-grid')
  await expect(grid).toBeVisible()
  const box = await grid.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.height).toBeLessThanOrEqual(210)

  // Verify busy bots are prioritized first
  const firstChipName = await page.locator('.bot-load-chip .bot-chip-name').first().textContent()
  expect(firstChipName?.trim()).toBe('@MistNode_05_Bot')

  // Filter by busy
  await page.getByRole('button', { name: '忙碌 (3)' }).click()
  await expect(page.locator('.bot-load-chip')).toHaveCount(3)

  // Switch back to all and test expand / collapse
  await page.getByRole('button', { name: '全部 (24)' }).click()
  await expect(page.locator('.bot-load-chip')).toHaveCount(24)

  await page.getByRole('button', { name: /展开更多/ }).click()
  await expect(grid).toHaveClass(/is-expanded/)

  await page.getByRole('button', { name: /收起紧凑视图/ }).click()
  await expect(grid).not.toHaveClass(/is-expanded/)
})

test('sidebar supports smooth collapse, centered glass capsule items, and floating tooltips', async ({ page }) => {
  await mockDashboardApis(page)
  await page.goto('/dashboard')

  const sidebar = page.locator('.sidebar')
  await expect(sidebar).toBeVisible()
  await expect(sidebar).not.toHaveClass(/is-collapsed/)

  // Toggle collapse
  const collapseBtn = page.locator('.collapse-btn')
  await collapseBtn.click()

  await expect(sidebar).toHaveClass(/is-collapsed/)
  await page.waitForTimeout(350)
  const box = await sidebar.boundingBox()
  expect(box?.width).toBeCloseTo(64, 1)

  // Verify active menu item is 44px centered capsule
  const activeItem = sidebar.locator('.el-menu-item.is-active')
  await expect(activeItem).toBeVisible()
  const activeBox = await activeItem.boundingBox()
  expect(activeBox).not.toBeNull()
  expect(activeBox!.width).toBeCloseTo(44, 2)
  expect(activeBox!.height).toBeCloseTo(44, 2)

  // Check horizontal center: activeBox.x should be approximately 10px from left (64 - 44) / 2
  expect(activeBox!.x).toBeCloseTo(10, 2)

  // Check icon inside active item is centered
  const activeIcon = activeItem.locator('.el-icon')
  const iconBox = await activeIcon.boundingBox()
  expect(iconBox).not.toBeNull()
  // icon center should be at approx 32px (64/2)
  const iconCenterX = iconBox!.x + iconBox!.width / 2
  expect(iconCenterX).toBeCloseTo(32, 3)

  // Hover over an item and verify the stylish tooltip appears
  const driveItem = sidebar.locator('.el-menu-item').nth(2)
  await driveItem.hover()
  await page.waitForTimeout(300)
  const tooltip = page.getByRole('tooltip', { name: 'TG网盘' })
  await expect(tooltip).toBeVisible()

  // Hover over the collapse button to verify its tooltip
  await collapseBtn.hover()
  await page.waitForTimeout(300)
  const collapseTooltip = page.getByRole('tooltip', { name: '展开侧边栏' })
  await expect(collapseTooltip).toBeVisible()

  // Save screenshot of collapsed sidebar for visual verification
  await page.screenshot({ path: '/tmp/sidebar-collapsed-verified.png', clip: { x: 0, y: 0, width: 300, height: 750 } })

  // Toggle back to expanded
  await collapseBtn.click()
  await expect(sidebar).not.toHaveClass(/is-collapsed/)
  await page.waitForTimeout(350)
  const expandedBox = await sidebar.boundingBox()
  expect(expandedBox?.width).toBeCloseTo(240, 1)
})
