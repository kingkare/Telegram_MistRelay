import { expect, test } from '@playwright/test'
import { createTelegramDriveFixture, pcDriveViewportWidths } from './fixtures/telegram-drive'

const driveItems = createTelegramDriveFixture(10000)

async function mockPcDriveApi(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'pc-drive-layout-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'pc-drive-layout-refresh')
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'pc-user', role: 'user' },
      }),
    })
  })

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        server_status: 'running',
        version: 'test',
      }),
    })
  })

  await page.route('**/api/telegram/thumbnail/**', async route => {
    await route.fulfill({
      status: 204,
      body: '',
    })
  })

  await page.route('**/api/telegram/browse**', async route => {
    const url = new URL(route.request().url())
    const pageNumber = Number(url.searchParams.get('page') || '1')
    const pageSize = Number(url.searchParams.get('page_size') || '40')
    const mediaGroupId = url.searchParams.get('media_group_id')
    const sourceItems = mediaGroupId
      ? driveItems.filter(item => item.entry_type === 'file').slice(0, 6)
      : driveItems
    const start = (pageNumber - 1) * pageSize
    const items = sourceItems.slice(start, start + pageSize)

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        items,
        total: sourceItems.length,
        page: pageNumber,
        page_size: pageSize,
      }),
    })
  })
}

async function countOverflowingCards(page: import('@playwright/test').Page): Promise<number> {
  return page.locator('.pc-media-card').evaluateAll(cards => (
    cards.filter(card => {
      const cardRect = card.getBoundingClientRect()
      const title = card.querySelector('.pc-media-title')
      const meta = card.querySelector('.pc-media-meta')
      const titleRect = title?.getBoundingClientRect()
      const metaRect = meta?.getBoundingClientRect()

      return [titleRect, metaRect]
        .filter(Boolean)
        .some(rect => (
          rect!.left < cardRect.left - 1 ||
          rect!.right > cardRect.right + 1 ||
          rect!.top < cardRect.top - 1 ||
          rect!.bottom > cardRect.bottom + 1
        ))
    }).length
  ))
}

test.describe('PC drive layout with large Telegram drive data', () => {
  for (const width of pcDriveViewportWidths) {
    test(`renders without obvious layout overflow at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 820 })
      await mockPcDriveApi(page)

      const startedAt = Date.now()
      await page.goto('/pc/drive')
      await expect(page.locator('.pc-media-card').first()).toBeVisible()
      expect(Date.now() - startedAt).toBeLessThan(8000)

      await expect(page.locator('.pc-media-card')).toHaveCount(40)
      await expect(page.locator('.pc-drive-pagination')).toContainText('10000')

      const screenshot = await page.locator('.pc-content').screenshot({
        path: testInfo.outputPath(`pc-drive-${width}.png`),
        animations: 'disabled',
      })
      expect(screenshot.byteLength).toBeGreaterThan(12000)
      await expect(page.locator('.pc-content')).toBeInViewport()
      expect(await countOverflowingCards(page)).toBe(0)
    })
  }
})
