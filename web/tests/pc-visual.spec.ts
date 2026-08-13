import { expect, test, type Page } from '@playwright/test'
import { createTelegramDriveFixture } from './fixtures/telegram-drive'

const visualItems = createTelegramDriveFixture(18)
const visualViewport = { width: 1366, height: 768 }

async function mockVisualApi(page: Page) {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      user: { id: 1, username: 'mira', role: 'user' },
    }),
  }))

  await page.route('**/api/telegram/browse**', async route => {
    const url = new URL(route.request().url())
    const pageSize = Number(url.searchParams.get('page_size') || '40')
    const mediaGroupId = url.searchParams.get('media_group_id')
    const sourceItems = mediaGroupId
      ? visualItems.filter(item => item.entry_type === 'file').slice(0, 8)
      : visualItems
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        items: sourceItems.slice(0, pageSize),
        total: sourceItems.length,
        page: 1,
        page_size: pageSize,
      }),
    })
  })

  await page.route('**/api/telegram/thumbnail/**', async route => {
    const value = Array.from(new URL(route.request().url()).pathname)
      .reduce((sum, character) => sum + character.charCodeAt(0), 0)
    const palettes = [
      ['#dce6f7', '#6273cc', '#e0ad55'],
      ['#deece8', '#3d8b7a', '#6575c9'],
      ['#ece5f4', '#7a61bb', '#d29958'],
    ]
    const [background, foreground, accent] = palettes[value % palettes.length]
    await route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400"><rect width="640" height="400" fill="${background}"/><path d="M0 330 180 150l105 112 94-90 261 158v70H0Z" fill="${foreground}" opacity=".82"/><circle cx="492" cy="104" r="46" fill="${accent}"/></svg>`,
    })
  })

  await page.route('**/api/telegram/stream/**', async route => {
    if (route.request().method() === 'HEAD') {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Length': '4096', 'Accept-Ranges': 'bytes' },
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#e9eef8"/><path d="M120 620 420 280l180 210 150-150 330 280Z" fill="#6574cc"/><circle cx="900" cy="210" r="84" fill="#d5a54b"/></svg>',
    })
  })
}

async function seedAuthenticatedPc(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('token', 'visual-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'visual-refresh')
    window.localStorage.setItem('mistrelay.serverBaseUrl', 'http://127.0.0.1:5173')
    Object.assign(window, { __TAURI__: {} })
  })
}

test('renders the PC login visual baseline', async ({ page }) => {
  await page.setViewportSize(visualViewport)
  await mockVisualApi(page)
  await page.goto('/pc/login')
  await expect(page.locator('.pc-login-page')).toHaveScreenshot('pc-login-1366.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.01,
  })
})

test('keeps the login form usable at compact desktop widths', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 700 })
  await page.goto('/pc/login')

  await expect(page.locator('.pc-login-panel')).toBeVisible()
  await expect(page.locator('.pc-login-visual')).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024)
})

test('renders recent, downloads, settings, and preview baselines', async ({ page }) => {
  await page.setViewportSize(visualViewport)
  await seedAuthenticatedPc(page)
  await mockVisualApi(page)

  await page.goto('/pc/recent')
  await expect(page.locator('.pc-media-card').first()).toBeVisible()
  await expect(page.locator('.pc-shell')).toHaveScreenshot('pc-recent-server-1366.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.01,
  })

  await page.evaluate(async (items) => {
    const { usePcRecentStore } = await import('/src/stores/pcRecent.ts')
    usePcRecentStore().$patch({
      records: items.slice(1, 7).map((item, index) => ({
        id: item.entry_type === 'file' ? `file:${item.file_unique_id}` : `folder:${item.media_group_id}`,
        serverBaseUrl: 'http://127.0.0.1:5173',
        item,
        action: index % 2 === 0 ? 'preview' : 'download',
        accessedAt: `2026-07-${String(14 - index).padStart(2, '0')}T10:30:00Z`,
      })),
    })
  }, visualItems)
  await page.getByRole('tab', { name: '本机最近' }).click()
  await expect(page.locator('.pc-local-recent-row')).toHaveCount(6)
  await expect(page.locator('.pc-shell')).toHaveScreenshot('pc-recent-local-1366.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.01,
  })

  await page.getByRole('link', { name: '下载' }).click()
  const now = '2026-07-15T10:30:00Z'
  await page.evaluate(async ({ timestamp }) => {
    const { usePcDownloadsStore } = await import('/src/stores/pcDownloads.ts')
    const statuses = ['downloading', 'queued', 'completed', 'failed', 'interrupted', 'cancelled'] as const
    usePcDownloadsStore().$patch({
      tasks: statuses.map((status, index) => ({
        id: `visual-${status}`,
        sourceUrl: `http://127.0.0.1:5173/file-${index}`,
        fileName: ['产品演示_2026.mp4', '素材归档.zip', '城市夜景_01.jpg', '夜航歌单.flac', '项目资料.pdf', '角色设定稿.png'][index],
        savePath: `D:/MistRelay/Downloads/visual-${index}.bin`,
        totalBytes: 1024 * 1024 * (index + 2),
        downloadedBytes: status === 'completed' ? 1024 * 1024 * (index + 2) : status === 'downloading' ? 1024 * 1024 : 0,
        status,
        threads: 4,
        createdAt: timestamp,
        updatedAt: timestamp,
        speedBytesPerSecond: status === 'downloading' ? 8 * 1024 * 1024 : 0,
        chunks: [],
        error: status === 'failed'
          ? { taskId: `visual-${status}`, code: 'network', message: '网络连接中断', retryable: true }
          : status === 'interrupted'
            ? { taskId: `visual-${status}`, code: 'interrupted', message: '上次下载未完成，可重试', retryable: true }
            : undefined,
      })),
    })
  }, { timestamp: now })
  await expect(page.locator('.pc-download-task')).toHaveCount(6)
  await expect(page.locator('.pc-shell')).toHaveScreenshot('pc-downloads-1366.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.01,
  })

  await page.getByRole('link', { name: '设置', exact: true }).click()
  await page.getByRole('button', { name: '下载', exact: true }).click()
  await expect(page.locator('.pc-shell')).toHaveScreenshot('pc-settings-downloads-1366.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.01,
  })

  await page.getByRole('link', { name: '网盘' }).click()
  await expect(page.locator('.pc-drive-card').first()).toBeVisible()
  await page.locator('.pc-drive-card').filter({ hasText: 'mistrelay_fixture_00000' }).click()
  await expect(page.locator('.pc-preview')).toBeVisible()
  await expect(page.locator('.pc-preview')).toHaveScreenshot('pc-preview-1366.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.01,
  })
})
