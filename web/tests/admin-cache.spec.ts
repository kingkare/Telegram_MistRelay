import { expect, test, type Page } from '@playwright/test'

const MOCK_CACHE_STATS = {
  disk: {
    total_bytes: 107374182400,
    used_bytes: 53687091200,
    free_bytes: 53687091200,
    total_gb: 100,
    used_gb: 50,
    free_gb: 50,
    percent: 50,
    path: '/data/downloads',
  },
  total_cache_bytes: 31457280,
  total_cache_size_mb: 30,
  total_cache_files: 180,
  thumbnails: {
    total_files: 150,
    total_bytes: 10485760,
    total_size_mb: 10,
    cache_dir: '/app/cache/thumbnails',
    sub_sources: {
      telegram: { total_files: 140, total_bytes: 9437184, total_size_mb: 9 },
      onedrive: { total_files: 10, total_bytes: 1048576, total_size_mb: 1 },
    },
    expired_files: 10,
    expired_bytes: 1048576,
    expired_size_mb: 1,
    retention_days: 7,
  },
  downloads: {
    root: '/data/downloads',
    total_files: 20,
    total_bytes: 15728640,
    total_size_mb: 15,
    protected_files: 5,
    cleanable_files: 15,
    cleanable_bytes: 10485760,
    cleanable_size_mb: 10,
    recent_files: 0,
    retention_hours: 24,
  },
  rclone: {
    root: '/app/cache/rclone',
    total_files: 10,
    total_bytes: 5242880,
    total_size_mb: 5,
  },
  memory: {
    thumbnail_lru: { hits: 45, misses: 10, maxsize: 100, currsize: 35 },
    stream_sessions: 2,
    config_cache_entries: 25,
  },
}

const MOCK_CACHE_POLICY = {
  DOWNLOAD_CLEANUP_ENABLED: true,
  DOWNLOAD_RETENTION_HOURS: 24,
  DOWNLOAD_CLEANUP_INTERVAL_SECONDS: 3600,
  THUMBNAIL_CACHE_MAX_AGE_DAYS: 7,
}

async function mockCachePage(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'admin-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'admin-refresh')
  })

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'admin', role: 'admin' },
      }),
    })
  })

  await page.route('**/api/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ready: true, server_status: 'running', version: 'test' }),
    })
  })

  await page.route('**/api/cache/stats', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: MOCK_CACHE_STATS,
      }),
    })
  })

  await page.route('**/api/cache/policy', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: MOCK_CACHE_POLICY,
        }),
      })
    } else if (route.request().method() === 'PUT') {
      const data = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { ...MOCK_CACHE_POLICY, ...data },
          message: '缓存策略已更新',
        }),
      })
    }
  })

  await page.route('**/api/cache/clean', async (route) => {
    const data = route.request().postDataJSON()
    if (data.dry_run) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            category: 'downloads',
            root: '/data/downloads',
            retention_hours: 24,
            scanned_files: 20,
            deleted_files: 15,
            deleted_bytes: 10485760,
            deleted_size_mb: 10,
            skipped_protected: 5,
            skipped_recent: 0,
            dry_run: true,
          },
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            category: data.category,
            deleted_files: 5,
            deleted_bytes: 5242880,
            deleted_size_mb: 5,
            dry_run: false,
          },
        }),
      })
    }
  })
}

test('cache page renders correctly with stats, cards, and policy', async ({ page }) => {
  await mockCachePage(page)
  await page.goto('/cache')

  // Header & Title
  await expect(page.getByText('缓存治理中心')).toBeVisible()
  await expect(page.getByText('Storage Governance')).toBeVisible()

  // Top stat cards
  await expect(page.getByText('50%')).toBeVisible()
  await expect(page.getByText('磁盘已用 50 / 100 GB')).toBeVisible()
  await expect(page.getByText('缓存总量 (180 文件)')).toBeVisible()

  // 4 categories
  await expect(page.getByText('媒体缩略图缓存')).toBeVisible()
  await expect(page.getByText('本地下载与临时文件')).toBeVisible()
  await expect(page.getByText('Rclone VFS 挂载缓存')).toBeVisible()
  await expect(page.getByText('运行期内存缓存')).toBeVisible()

  // Policy section
  await expect(page.getByText('自动清理与生命周期策略')).toBeVisible()
  await expect(page.getByText('自动清理下载目录')).toBeVisible()
})

test('cache dry run analysis dialog functions properly', async ({ page }) => {
  await mockCachePage(page)
  await page.goto('/cache')

  const dryRunBtn = page.getByRole('button', { name: '试运行分析 (Dry-run)' })
  await expect(dryRunBtn).toBeVisible()
  await dryRunBtn.click()

  // Modal appears
  await expect(page.getByText('下载目录试运行清理分析 (Dry-run)')).toBeVisible()
  await expect(page.getByText('预计删除文件')).toBeVisible()
  await expect(page.getByText('预计释放空间')).toBeVisible()
  await expect(page.getByText('受保护跳过')).toBeVisible()
})

test('cache page is responsive at 768px viewport without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await mockCachePage(page)
  await page.goto('/cache')

  await expect(page.getByText('缓存治理中心')).toBeVisible()

  // Check no horizontal scrollbar on body
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})
