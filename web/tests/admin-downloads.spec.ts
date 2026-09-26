import { expect, test, type Page } from '@playwright/test'

const MOCK_DOWNLOADS = {
  success: true,
  grouped: true,
  data: [
    {
      group_key: 'group_1',
      group_type: 'media_group',
      message_id: 1001,
      caption: '樱花动漫合集 2026',
      created_at: '2026-09-26T04:00:00Z',
      stats: {
        total_files: 2,
        completed: 1,
        downloading: 1,
        failed: 0,
        pending: 0,
        skipped: 0,
        total_size: 209715200,
        completed_size: 104857600,
      },
      downloads: [
        {
          id: 101,
          gid: 'gid_101',
          file_name: 'episode_01.mp4',
          status: 'downloading',
          total_length: 104857600,
          completed_length: 52428800,
          download_speed: 5242880,
          created_at: '2026-09-26T04:00:00Z',
          uploads: [],
        },
        {
          id: 102,
          gid: 'gid_102',
          file_name: 'cover_art.jpg',
          status: 'completed',
          total_length: 104857600,
          completed_length: 104857600,
          download_speed: 0,
          created_at: '2026-09-26T04:00:00Z',
          uploads: [
            {
              id: 201,
              download_id: 102,
              upload_target: 'telegram',
              status: 'completed',
              cleaned_at: '2026-09-26T04:05:00Z',
              completed_at: '2026-09-26T04:05:00Z',
            },
          ],
        },
      ],
    },
    {
      group_key: 'group_2',
      group_type: 'single',
      message_id: 1002,
      caption: '失败测试文件组',
      created_at: '2026-09-26T03:00:00Z',
      stats: {
        total_files: 1,
        completed: 0,
        downloading: 0,
        failed: 1,
        pending: 0,
        skipped: 0,
        total_size: 10485760,
        completed_size: 0,
      },
      downloads: [
        {
          id: 103,
          gid: 'gid_103',
          file_name: 'broken_video.mkv',
          status: 'failed',
          error_message: '连接超时',
          total_length: 10485760,
          completed_length: 0,
          download_speed: 0,
          created_at: '2026-09-26T03:00:00Z',
          uploads: [],
        },
      ],
    },
  ],
}

async function mockDownloadsPage(page: Page) {
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

  await page.route('**/api/downloads**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_DOWNLOADS),
    })
  })

  await page.route('**/api/uploads**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          {
            id: 301,
            file_name: 'uploading_music.flac',
            upload_target: 'telegram',
            status: 'uploading',
            total_size: 52428800,
            uploaded_size: 26214400,
            upload_speed: 2097152,
            created_at: '2026-09-26T04:10:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/queue**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        queue_size: 1,
        current_processing: {
          title: '正在转存的高清PV.mp4',
          type: 'single',
          task_gids: ['gid_101'],
        },
        waiting_items: [
          {
            queue_id: 'q1',
            title: '排队等待相册 #2',
            type: 'media_group',
            media_group_total: 4,
          },
        ],
      }),
    })
  })
}

test('downloads task center renders modern header, stats, and tabs', async ({ page }) => {
  await mockDownloadsPage(page)
  await page.goto('/downloads')

  await expect(page.getByText('任务调度中心')).toBeVisible()
  await expect(page.getByText('Task Engine')).toBeVisible()
  await expect(page.getByRole('button', { name: /重试失败/ })).toBeVisible()

  // Active download row in downloading tab
  await expect(page.locator('#pane-download').getByText('episode_01.mp4')).toBeVisible()

  // Switch to Records tab and test search & filter
  await page.getByRole('tab', { name: /历史记录组/ }).click()
  await expect(page.locator('#pane-records').getByText('樱花动漫合集 2026')).toBeVisible()
  await expect(page.locator('#pane-records').getByText('失败测试文件组')).toBeVisible()

  // Filter by failed only
  await page.getByRole('button', { name: '含失败' }).click()
  await expect(page.locator('#pane-records').getByText('失败测试文件组')).toBeVisible()
  await expect(page.locator('#pane-records').getByText('樱花动漫合集 2026')).toHaveCount(0)

  // Reset filter & test search
  await page.getByRole('button', { name: /全部/ }).click()
  const searchInput = page.getByPlaceholder('搜索文件名、消息说明或 Message ID...')
  await searchInput.fill('cover_art')
  await expect(page.locator('#pane-records').getByText('樱花动漫合集 2026')).toBeVisible()
  await expect(page.locator('#pane-records').getByText('失败测试文件组')).toHaveCount(0)
})

test('downloads page is responsive at 768px without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await mockDownloadsPage(page)
  await page.goto('/downloads')

  await expect(page.getByText('任务调度中心')).toBeVisible()

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})
