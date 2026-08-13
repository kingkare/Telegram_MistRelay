import { expect, test } from '@playwright/test'
import { createTelegramDriveFixture, pcDriveViewports } from './fixtures/telegram-drive'

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

  await page.route('**/api/health', async route => {
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
  for (const viewport of pcDriveViewports) {
    test(`renders the complete shell at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await mockPcDriveApi(page)

      const startedAt = Date.now()
      await page.goto('/pc/drive')
      await expect(page.locator('.pc-media-card').first()).toBeVisible()
      expect(Date.now() - startedAt).toBeLessThan(8000)

      await expect(page.locator('.pc-media-card')).toHaveCount(40)
      await expect(page.locator('.pc-drive-pagination')).toContainText('10000')
      await expect(page.locator('.pc-sidebar-account')).toContainText('pc-user')

      const shellGeometry = await page.locator('.pc-shell').evaluate((shell) => {
        const sidebar = shell.querySelector<HTMLElement>('.pc-sidebar')!
        const toolbar = shell.querySelector<HTMLElement>('.pc-toolbar')!
        const content = shell.querySelector<HTMLElement>('.pc-content')!
        const grid = shell.querySelector<HTMLElement>('.pc-media-grid')!
        const contentStyle = getComputedStyle(content)
        return {
          sidebarWidth: Math.round(sidebar.getBoundingClientRect().width),
          toolbarHeight: Math.round(toolbar.getBoundingClientRect().height),
          contentPadding: Number.parseFloat(contentStyle.paddingLeft),
          columns: getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length,
          contentOverflowsHorizontally: content.scrollWidth > content.clientWidth + 1,
          pageOverflowsHorizontally: document.documentElement.scrollWidth > window.innerWidth + 1,
        }
      })

      expect(shellGeometry).toEqual({
        sidebarWidth: 184,
        toolbarHeight: 56,
        contentPadding: 18,
        columns: viewport.columns,
        contentOverflowsHorizontally: false,
        pageOverflowsHorizontally: false,
      })
      await expect(page.locator('.pc-content')).toBeInViewport()
      expect(await countOverflowingCards(page)).toBe(0)
      await expect(page.locator('.pc-shell')).toHaveScreenshot(`pc-drive-${viewport.width}.png`, {
        animations: 'disabled',
        maxDiffPixelRatio: 0.01,
      })
    })
  }
})
