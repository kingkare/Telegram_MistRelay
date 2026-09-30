import { expect, test, type Page } from '@playwright/test'

const rootItems = [
  {
    entry_type: 'folder',
    media_group_id: 'album-summer',
    item_count: 2,
    file_name: '夏日相册',
    total_size: 4096,
    message_date: '2026-01-01T00:00:00Z',
  },
  {
    entry_type: 'file',
    file_unique_id: 'file-photo',
    chat_id: 1000,
    message_id: 101,
    file_name: '海边照片.jpg',
    download_file_name: 'beach.jpg',
    mime_type: 'image/jpeg',
    file_size: 2048,
    stream_url: '/101/beach.jpg?hash=test',
    message_date: '2026-01-01T00:01:00Z',
  },
  {
    entry_type: 'file',
    file_unique_id: 'file-video',
    chat_id: 1000,
    message_id: 102,
    file_name: '海边视频.mp4',
    download_file_name: 'beach.mp4',
    mime_type: 'video/mp4',
    file_size: 4096,
    stream_url: '/102/beach.mp4?hash=test',
    message_date: '2026-01-01T00:02:00Z',
  },
]

async function mockAdminDrive(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'admin-drive-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'admin-drive-refresh')
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
      body: JSON.stringify({ ready: true, server_status: 'running', version: 'test' }),
    })
  })

  await page.route('**/api/telegram/usage', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { total_count: 3, total_size: 6144, videos: 1, images: 1, audios: 0, documents: 0 },
      }),
    })
  })

  await page.route('**/api/telegram/thumbnails/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { running: false, total: 3, cached: 3, pending: 0, percent: 100, current_message_id: null },
      }),
    })
  })

  await page.route('**/api/telegram/browse**', async route => {
    const url = new URL(route.request().url())
    const pageNumber = Number(url.searchParams.get('page') || '1')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        items: pageNumber === 1 ? rootItems : [rootItems[1]],
        total: 21,
        page: pageNumber,
        page_size: 20,
      }),
    })
  })
}

test('Telegram admin drive supports current-page multi-select and batch delete', async ({ page }) => {
  await mockAdminDrive(page)

  let batchPayload: unknown
  await page.route('**/api/telegram/batch/delete', async route => {
    batchPayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: '已删除 3 个频道文件' }),
    })
  })

  await page.goto('/drive')
  await expect(page.getByRole('heading', { name: 'Telegram 频道网盘' })).toBeVisible()
  await expect(page.getByText('已选 0 项')).toBeVisible()

  await page.getByRole('row', { name: /夏日相册/ }).locator('.el-checkbox').click()
  await page.getByRole('row', { name: /海边照片\.jpg/ }).locator('.el-checkbox').click()
  await expect(page.getByText('已选 2 项')).toBeVisible()
  await expect(page.getByRole('button', { name: /下载文件\s*（1）/ })).toBeEnabled()

  await page.getByRole('button', { name: /批量删除\s*（2）/ }).click()
  await expect(page.getByRole('dialog', { name: '批量删除' })).toBeVisible()
  await page.getByRole('button', { name: '删除所选' }).click()

  await expect.poll(() => batchPayload).toEqual({
    message_ids: [101],
    media_group_ids: ['album-summer'],
  })
  await expect(page.getByText('已选 0 项')).toBeVisible()
})

test('selection works in grid mode and resets when the page changes', async ({ page }) => {
  await mockAdminDrive(page)
  await page.goto('/drive')

  await page.getByText('全选本页', { exact: true }).click()
  await expect(page.getByText('已选 3 项')).toBeVisible()

  await page.locator('.el-radio-button').filter({ has: page.locator('.el-icon') }).nth(1).click()
  await expect(page.locator('.grid-item.is-selected')).toHaveCount(3)

  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByText('已选 0 项')).toBeVisible()
  await expect(page.locator('.grid-item.is-selected')).toHaveCount(0)
})

test('multi-select controls remain usable at compact widths', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 })
  await mockAdminDrive(page)
  await page.goto('/drive')

  await page.getByText('全选本页', { exact: true }).click()
  await expect(page.getByText('已选 3 项')).toBeVisible()
  await expect(page.getByRole('button', { name: /下载文件\s*（2）/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /批量删除\s*（3）/ })).toBeVisible()

  const overflow = await page.locator('.selection-toolbar').evaluate(element => ({
    horizontal: element.scrollWidth > element.clientWidth + 1,
    viewport: document.documentElement.scrollWidth > window.innerWidth + 1,
  }))
  expect(overflow).toEqual({ horizontal: false, viewport: false })
})

test('video preview dialog adapts to viewport and does not overflow screen', async ({ page }) => {
  await mockAdminDrive(page)
  // Test standard desktop viewport
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/drive')

  const videoRow = page.getByRole('row', { name: /海边视频\.mp4/ })
  await videoRow.getByRole('button', { name: '预览' }).click()

  const dialog = page.locator('.glass-video-dialog')
  await expect(dialog).toBeVisible()

  await expect(page.locator('.video-header-title')).toContainText('海边视频.mp4')

  let box = await dialog.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.height).toBeLessThanOrEqual(800)
  expect(box!.y + box!.height).toBeLessThanOrEqual(800)

  await expect(page.getByRole('button', { name: '全屏播放' })).toBeVisible()
  await expect(page.getByRole('button', { name: '下载原视频' })).toBeVisible()

  // Test web fullscreen mode
  await page.locator('.video-header-actions .btn-web-fullscreen').click()
  await expect(dialog).toHaveClass(/is-web-fullscreen/)

  // Test ultrawide/high-res viewport (3840x1920)
  await page.setViewportSize({ width: 3840, height: 1920 })
  box = await dialog.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.height).toBeLessThanOrEqual(1920)
  expect(box!.y + box!.height).toBeLessThanOrEqual(1920)

  // Test mobile/tablet viewport (768x1024)
  await page.setViewportSize({ width: 768, height: 1024 })
  box = await dialog.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.height).toBeLessThanOrEqual(1024)
  expect(box!.y + box!.height).toBeLessThanOrEqual(1024)

  // Close dialog via close button
  await page.locator('.video-header-actions .btn-close').click()
  await expect(dialog).not.toBeVisible()
})


test('supports stream link copy, M3U export, shift selection, and view preference persistence', async ({ page }) => {
  await mockAdminDrive(page)
  await page.goto('/drive')

  // Test Shift range selection: click row 1 checkbox, then Shift+click row 3 checkbox
  const rows = page.locator('.drive-table .el-table__body-wrapper tbody tr')
  await expect(rows).toHaveCount(3)

  await rows.nth(0).locator('.el-checkbox').click()
  await expect(page.getByText('已选 1 项')).toBeVisible()

  await rows.nth(2).locator('.el-checkbox').click({ modifiers: ['Shift'] })
  await expect(page.getByText('已选 3 项')).toBeVisible()

  // Verify batch copy & M3U export buttons are enabled
  await expect(page.getByRole('button', { name: /复制直链\s*（2）/ })).toBeEnabled()
  await expect(page.getByRole('button', { name: /导出播放列表\s*（2）/ })).toBeEnabled()

  // Trigger M3U playlist export
  await page.getByRole('button', { name: /导出播放列表\s*（2）/ }).click()
  await expect(page.getByText(/已导出包含 2 项的 M3U 播放列表/)).toBeVisible()

  // Switch to grid mode and verify persistence across reload
  await page.locator('.el-radio-button').filter({ has: page.locator('.el-icon') }).nth(1).click()
  await expect(page.locator('.grid-view')).toBeVisible()

  await page.reload()
  await expect(page.locator('.grid-view')).toBeVisible()
})

test('private and restricted channel harvester modal and workflow', async ({ page }) => {
  await mockAdminDrive(page)

  await page.route('**/api/telegram/botfather/accounts**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { id: 1, phone: '+18048484620', status: 'active', bot_count: 5 },
          { id: 2, phone: '+16813086196', status: 'limit_reached', bot_count: 20 },
        ],
      }),
    })
  })

  let startPayload: any = null
  await page.route('**/api/telegram/harvester/start', async route => {
    startPayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        task_id: 'harvest_test_001',
        total_messages: 5,
        message: '私密/受限频道采集流水线已启动',
      }),
    })
  })

  let statusCallCount = 0
  await page.route('**/api/telegram/harvester/status', async route => {
    statusCallCount++
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          status: statusCallCount <= 1 ? 'idle' : 'running',
          task_id: 'harvest_test_001',
          total_messages: 5,
          current_index: 2,
          success_count: 2,
          failed_count: 0,
          skipped_count: 0,
          current_mode: 'restricted_relay',
          current_file: 'sample_video.mp4',
          speed_text: '12.5 MB/s (40%)',
          logs: ['[12:00:00] 启动频道采集任务', '[12:00:02] 已解密受限消息 #101 并上传成功'],
          results: [],
          account_phone: '+18048484620',
          error: null,
        },
      }),
    })
  })

  let cancelCalled = false
  await page.route('**/api/telegram/harvester/cancel', async route => {
    cancelCalled = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: '已发送中止信号' }),
    })
  })

  await page.goto('/drive')
  await page.getByRole('button', { name: '私密/受限频道采集' }).click()

  const dialog = page.locator('.harvester-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('协议号自动化双模采集流水线')).toBeVisible()

  // Fill in links
  await dialog.locator('textarea').fill('https://t.me/c/1998444696/100-104')
  await dialog.getByRole('button', { name: '开始采集入库' }).click()

  expect(startPayload).not.toBeNull()
  expect(startPayload.links_text).toContain('https://t.me/c/1998444696/100-104')
  expect(startPayload.rebrand_enabled).toBe(true)

  // Verify status panel elements
  await expect(dialog.locator('.harvester-status-panel')).toBeVisible()
  await expect(dialog.locator('.mode-relay')).toContainText('受限破除重传')
  await expect(dialog.locator('.term-line').first()).toBeVisible()

  // Cancel task
  await dialog.getByRole('button', { name: '中止任务' }).click()
  expect(cancelCalled).toBe(true)
})
