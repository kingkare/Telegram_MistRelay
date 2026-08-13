import { expect, test, type Page } from '@playwright/test'

declare global {
  interface Window {
    __TAURI__?: unknown
    __TAURI_INTERNALS__?: any
    __TAURI_EVENT_PLUGIN_INTERNALS__?: any
  }
}

const rootItems = [
  {
    entry_type: 'folder',
    media_group_id: 'album-summer',
    item_count: 2,
    file_name: '夏日相册',
    total_size: 4096,
    thumbnail_url: '/api/telegram/thumbnail/album-summer',
    message_date: '2026-01-01T00:00:00Z',
  },
  {
    entry_type: 'file',
    file_unique_id: 'file-beach',
    chat_id: 1000,
    message_id: 101,
    file_name: '海边照片.jpg',
    download_file_name: 'beach.jpg',
    mime_type: 'image/jpeg',
    file_size: 2048,
    thumbnail_url: '/api/telegram/thumbnail/101',
    stream_url: '/api/telegram/stream/101',
    message_date: '2026-01-01T00:01:00Z',
  },
  {
    entry_type: 'file',
    file_unique_id: 'file-delete',
    chat_id: 1000,
    message_id: 102,
    file_name: '删除取消.mp4',
    download_file_name: 'delete-cancel.mp4',
    mime_type: 'video/mp4',
    file_size: 4096,
    thumbnail_url: '/api/telegram/thumbnail/102',
    stream_url: '/api/telegram/stream/102',
    message_date: '2026-01-01T00:02:00Z',
  },
]

const albumItems = [
  {
    entry_type: 'file',
    file_unique_id: 'album-file-1',
    chat_id: 1000,
    message_id: 201,
    file_name: '相册照片 01.jpg',
    download_file_name: 'album-01.jpg',
    mime_type: 'image/jpeg',
    file_size: 1024,
    thumbnail_url: '/api/telegram/thumbnail/201',
    stream_url: '/api/telegram/stream/201',
    message_date: '2026-01-01T00:03:00Z',
  },
]

export async function installSmokeTauriHarness(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.clear()

    const callbacks = new Map<number, (event: unknown) => void>()
    const listeners = new Map<string, Map<number, number>>()
    let callbackId = 1
    let listenerId = 1

    function emit(event: string, payload: unknown) {
      listeners.get(event)?.forEach((handlerId, id) => {
        callbacks.get(handlerId)?.({ event, id, payload })
      })
    }

    Object.assign(window, {
      __TAURI__: {},
      __TAURI_EVENT_PLUGIN_INTERNALS__: {
        unregisterListener(event: string, id: number) {
          listeners.get(event)?.delete(id)
        },
      },
      __TAURI_INTERNALS__: {
        metadata: {
          currentWindow: { label: 'main' },
          currentWebview: { label: 'main' },
        },
        transformCallback(callback: (event: unknown) => void) {
          const id = callbackId++
          callbacks.set(id, callback)
          return id
        },
        unregisterCallback(id: number) {
          callbacks.delete(id)
        },
        async invoke(command: string, args: Record<string, any>) {
          if (command === 'plugin:event|listen') {
            const id = listenerId++
            const eventListeners = listeners.get(args.event) || new Map<number, number>()
            eventListeners.set(id, args.handler)
            listeners.set(args.event, eventListeners)
            return id
          }
          if (command === 'plugin:event|unlisten') {
            listeners.get(args.event)?.delete(args.eventId)
            return null
          }
          if (command === 'select_directory') {
            return '/tmp/mistrelay-smoke'
          }
          if (command === 'save_file') {
            return '/tmp/mistrelay-smoke/save-as.bin'
          }
          if (command === 'cancel_download_task') {
            emit('pc-download-cancelled', { taskId: args.taskId })
            return null
          }
          if (command === 'start_download_task') {
            const request = args.request
            const task = {
              id: request.id,
              sourceUrl: request.sourceUrl,
              fileName: request.fileName,
              savePath: request.savePath,
              totalBytes: 2048,
              downloadedBytes: 2048,
              status: 'completed',
              threads: request.threads,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            }
            emit('pc-download-progress', {
              taskId: request.id,
              status: 'completed',
              totalBytes: 2048,
              downloadedBytes: 2048,
              speedBytesPerSecond: 2048,
              chunks: [],
            })
            emit('pc-download-completed', task)
            return task
          }
          return null
        },
      },
    })
  })
}

export async function mockBackend(page: Page) {
  await page.route('**/api/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', server_status: 'running', version: 'smoke' }),
    })
  })

  await page.route('**/api/auth/login', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        token: 'smoke-token',
        refresh_token: 'smoke-refresh',
        user: { id: 1, username: 'smoke', role: 'user' },
      }),
    })
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'smoke', role: 'user' },
      }),
    })
  })

  await page.route('**/api/telegram/browse**', async route => {
    const url = new URL(route.request().url())
    const search = url.searchParams.get('search') || ''
    const mediaGroupId = url.searchParams.get('media_group_id')
    const sourceItems = mediaGroupId ? albumItems : rootItems
    const items = search
      ? sourceItems.filter(item => item.file_name.includes(search))
      : sourceItems

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        items,
        total: items.length,
        page: 1,
        page_size: 40,
      }),
    })
  })

  await page.route('**/api/telegram/thumbnail/**', async route => {
    await route.fulfill({ status: 204, body: '' })
  })

  await page.route('**/api/telegram/stream/**', async route => {
    if (route.request().method() === 'HEAD') {
      await route.fulfill({
        status: 200,
        headers: {
          'Content-Length': '2048',
          'Content-Disposition': 'attachment; filename="smoke-download.jpg"',
          'Accept-Ranges': 'bytes',
        },
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#e9eef8"/><path d="M120 620 420 280l180 210 150-150 330 280Z" fill="#6b78d8"/><circle cx="900" cy="210" r="84" fill="#d5a54b"/></svg>',
    })
  })

  await page.route('**/api/telegram/item/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'deleted' }),
    })
  })
}

test('PC main user flow smoke test', async ({ page }) => {
  await installSmokeTauriHarness(page)
  await mockBackend(page)

  await page.goto('/pc/login')
  await page.getByPlaceholder('https://mistrelay.example.com').fill('http://127.0.0.1:5173')
  await page.getByPlaceholder('用户名').fill('smoke')
  await page.getByPlaceholder('密码').fill('secret')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/pc\/drive/)
  await expect(page.getByText('夏日相册')).toBeVisible()

  await page.getByPlaceholder('搜索文件名或描述').fill('海边')
  await page.getByRole('button', { name: '搜索' }).click()
  await expect(page.getByText('海边照片.jpg')).toBeVisible()

  await page.getByPlaceholder('搜索文件名或描述').fill('')
  await page.getByRole('button', { name: '搜索' }).click()
  await page.getByText('夏日相册').click()
  await expect(page.getByText('相册照片 01.jpg')).toBeVisible()

  const albumPhotoCard = page.locator('.pc-drive-card').filter({ hasText: '相册照片 01.jpg' })
  await albumPhotoCard.click()
  const preview = page.locator('.pc-preview')
  await expect(preview).toBeVisible()
  await expect(preview).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.locator('.pc-preview-toolbar button[title="关闭"]')).toBeFocused()
  await page.locator('.pc-preview-toolbar button[title="下载"]').click()
  await page.locator('.pc-preview-toolbar button[title="关闭"]').click()
  await expect(albumPhotoCard).toBeFocused()

  await page.getByRole('link', { name: '下载' }).click()
  await expect(page.getByText('smoke-download.jpg')).toBeVisible()
  await expect(page.locator('.pc-download-task').getByText('已完成')).toBeVisible()

  await page.getByRole('link', { name: '网盘' }).click()
  await page.getByRole('button', { name: '返回网盘' }).click()
  const deleteCard = page.locator('.pc-drive-card').filter({ hasText: '删除取消.mp4' })
  await deleteCard.hover()
  await deleteCard.locator('button[title="删除"]').click()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(deleteCard).toBeVisible()

  const deleteButton = deleteCard.locator('button[title="删除"]')
  await deleteButton.focus()
  await deleteButton.press('Enter')
  const keyboardDeleteDialog = page.locator('.el-message-box').last()
  await expect(keyboardDeleteDialog).toBeVisible()
  await expect(page.locator('.pc-preview')).toHaveCount(0)
  await keyboardDeleteDialog.getByRole('button', { name: '取消', exact: true }).click()

  await deleteCard.click()
  await expect(preview).toBeVisible()
  await expect(page.locator('#pc-preview-title')).toHaveText('删除取消.mp4')
  await preview.locator('video').focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('#pc-preview-title')).toHaveText('删除取消.mp4')
  await page.locator('.pc-preview-toolbar button[title="删除"]').click()
  const previewDeleteDialog = page.locator('.el-message-box').last()
  await expect(previewDeleteDialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(previewDeleteDialog).toBeHidden()
  await expect(preview).toBeVisible()
  await page.locator('.pc-preview-toolbar button[title="关闭"]').click()

  await page.getByRole('link', { name: '最近' }).click()
  await page.getByText('夏日相册').click()
  await expect(page).toHaveURL(/\/pc\/drive/)
  await expect(page.getByText('相册照片 01.jpg')).toBeVisible()

  await page.getByRole('link', { name: '最近' }).click()
  await page.getByText('海边照片.jpg').click()
  await expect(page.locator('.pc-preview')).toBeVisible()
  await expect(page.locator('.pc-preview-toolbar button[title="删除"]')).toHaveCount(0)
  await page.locator('.pc-preview-toolbar button[title="关闭"]').click()

  await page.getByRole('link', { name: '设置', exact: true }).click()
  await page.getByRole('button', { name: '下载', exact: true }).click()
  const threadInput = page.locator('.pc-settings-number').filter({ hasText: '单文件线程数' }).locator('input')
  await threadInput.fill('6')
  const concurrentInput = page.locator('.pc-settings-number').filter({ hasText: '全局并发数' }).locator('input')
  await concurrentInput.fill('3')
  await page.getByRole('button', { name: '保存下载设置' }).click()
  await expect.poll(async () => page.evaluate(() => window.localStorage.getItem('mistrelay.pc.threadsPerFile'))).toBe('6')
  await expect.poll(async () => page.evaluate(() => window.localStorage.getItem('mistrelay.pc.maxConcurrentTasks'))).toBe('3')

  await page.getByRole('button', { name: '连接与账户' }).click()
  await page.getByPlaceholder('https://example.com').fill('http://new.example.test')
  await page.getByRole('button', { name: '测试并切换' }).click()
  await page.getByRole('button', { name: '确认切换' }).click()
  await expect(page).toHaveURL(/\/pc\/login/)
  await expect.poll(async () => page.evaluate(() => window.localStorage.getItem('token'))).toBeNull()
  await expect.poll(async () => page.evaluate(() => window.localStorage.getItem('mistrelay.serverBaseUrl'))).toBe('http://new.example.test')
})

test('keeps the PC session when the initial user check has a network error', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'offline-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'offline-refresh')
    Object.assign(window, { __TAURI__: {} })
  })
  await page.route('**/api/auth/me', route => route.abort('connectionfailed'))
  await page.route('**/api/telegram/browse**', route => route.abort('connectionfailed'))

  await page.goto('/pc/drive')

  await expect(page).toHaveURL(/\/pc\/drive$/)
  await expect(page.locator('.pc-shell')).toBeVisible()
  await expect.poll(async () => page.evaluate(() => window.localStorage.getItem('token'))).toBe('offline-token')
})
