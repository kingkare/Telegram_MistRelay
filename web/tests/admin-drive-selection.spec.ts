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
