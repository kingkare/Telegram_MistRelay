import { createHash } from 'node:crypto'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { expect, test, type Page } from '@playwright/test'

declare global {
  interface Window {
    __downloadTestStats: any
    __TAURI__?: unknown
    __TAURI_INTERNALS__?: any
    __TAURI_EVENT_PLUGIN_INTERNALS__?: any
  }
}

const fixtureBytes = Buffer.from(Array.from({ length: 256 * 1024 }, (_, index) => index % 251))
const fixtureHash = createHash('sha256').update(fixtureBytes).digest('hex')

let fixtureServer: Server
let fixtureServerUrl = ''

function sendFixtureResponse(request: IncomingMessage, response: ServerResponse) {
  const supportsRange = request.url?.startsWith('/range') || request.url?.startsWith('/fail-once')
  const headers: Record<string, string> = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
    'Access-Control-Allow-Headers': 'Range',
    'Access-Control-Expose-Headers': 'Accept-Ranges, Content-Length, Content-Range',
    'Content-Type': 'application/octet-stream',
    'Content-Length': String(fixtureBytes.byteLength),
    'Content-Disposition': 'attachment; filename="fixture.bin"',
  }
  if (supportsRange) {
    headers['Accept-Ranges'] = 'bytes'
  }

  if (request.method === 'OPTIONS') {
    response.writeHead(204, headers)
    response.end()
    return
  }

  if (request.method === 'HEAD') {
    response.writeHead(200, headers)
    response.end()
    return
  }

  const range = request.headers.range
  if (supportsRange && range) {
    const match = /^bytes=(\d+)-(\d+)$/.exec(range)
    const start = match ? Number(match[1]) : 0
    const end = match ? Number(match[2]) : fixtureBytes.byteLength - 1

    if (start >= fixtureBytes.byteLength || end >= fixtureBytes.byteLength || start > end) {
      response.writeHead(416, {
        'Content-Range': `bytes */${fixtureBytes.byteLength}`,
      })
      response.end()
      return
    }

    const body = fixtureBytes.subarray(start, end + 1)
    response.writeHead(206, {
      ...headers,
      'Content-Length': String(body.byteLength),
      'Content-Range': `bytes ${start}-${end}/${fixtureBytes.byteLength}`,
    })
    response.end(body)
    return
  }

  response.writeHead(200, headers)
  response.end(fixtureBytes)
}

test.beforeAll(async () => {
  fixtureServer = createServer((request, response) => {
    sendFixtureResponse(request, response)
  })
  await new Promise<void>(resolve => fixtureServer.listen(0, '127.0.0.1', resolve))
  const address = fixtureServer.address() as AddressInfo
  fixtureServerUrl = `http://127.0.0.1:${address.port}`
})

test.afterAll(async () => {
  await new Promise<void>((resolve, reject) => {
    fixtureServer.close(error => (error ? reject(error) : resolve()))
  })
})

async function installTauriDownloadHarness(page: Page, maxConcurrentTasks: number) {
  await page.addInitScript(({ maxConcurrentTasks: concurrentLimit }) => {
    window.localStorage.setItem('token', 'download-test-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'download-test-refresh')
    window.localStorage.setItem('mistrelay.pc.maxConcurrentTasks', String(concurrentLimit))
    window.localStorage.setItem('mistrelay.pc.threadsPerFile', '4')
    window.localStorage.removeItem('mistrelay.pc.downloadTasks')

    const callbacks = new Map<number, (event: unknown) => void>()
    const listeners = new Map<string, Map<number, number>>()
    const cancelledTasks = new Set<string>()
    const attempts = new Map<string, number>()
    let callbackId = 1
    let listenerId = 1

    const stats = {
      activeTasks: 0,
      maxActiveTasks: 0,
      maxActiveRangeRequests: 0,
      completed: [] as string[],
      failed: [] as Array<{ taskId: string; code: string }>,
      cancelled: [] as string[],
      hashes: {} as Record<string, string>,
      threadCounts: [] as number[],
      fallbackCount: 0,
    }

    Object.defineProperty(window, '__downloadTestStats', {
      value: stats,
      configurable: true,
    })

    function emit(event: string, payload: unknown) {
      const eventListeners = listeners.get(event)
      if (!eventListeners) return
      eventListeners.forEach((handlerId, id) => {
        callbacks.get(handlerId)?.({ event, id, payload })
      })
    }

    function splitRanges(totalBytes: number, threads: number) {
      const count = Math.max(1, Math.min(threads, totalBytes))
      const chunkSize = Math.ceil(totalBytes / count)
      return Array.from({ length: count }, (_, index) => {
        const start = index * chunkSize
        return [start, Math.min(totalBytes - 1, start + chunkSize - 1)] as const
      }).filter(([start]) => start < totalBytes)
    }

    async function hashBytes(bytes: Uint8Array) {
      const digest = await crypto.subtle.digest('SHA-256', bytes)
      return Array.from(new Uint8Array(digest))
        .map(byte => byte.toString(16).padStart(2, '0'))
        .join('')
    }

    async function readResponseBytes(response: Response) {
      return new Uint8Array(await response.arrayBuffer())
    }

    async function downloadBytes(request: { id: string; sourceUrl: string; threads?: number }) {
      if (request.sourceUrl.includes('/disk-full')) {
        throw { taskId: request.id, code: 'disk_full', message: '磁盘空间不足', retryable: false }
      }

      if (request.sourceUrl.includes('/fail-once')) {
        const count = attempts.get(request.sourceUrl) || 0
        attempts.set(request.sourceUrl, count + 1)
        if (count === 0) {
          throw { taskId: request.id, code: 'network_interrupted', message: '网络中断', retryable: true }
        }
      }

      const threads = Math.max(1, Math.min(8, Number(request.threads || 1)))
      stats.threadCounts.push(threads)
      const head = await fetch(request.sourceUrl, { method: 'HEAD' })
      const totalBytes = Number(head.headers.get('content-length') || '0')
      const supportsRange = head.headers.get('accept-ranges')?.includes('bytes') && totalBytes > 0

      if (!supportsRange || threads === 1) {
        stats.fallbackCount += supportsRange ? 0 : 1
        const response = await fetch(request.sourceUrl)
        return readResponseBytes(response)
      }

      let activeRangeRequests = 0
      const chunks = await Promise.all(splitRanges(totalBytes, threads).map(async ([start, end]) => {
        if (cancelledTasks.has(request.id)) {
          throw { taskId: request.id, code: 'cancelled', message: '下载已取消', retryable: false }
        }

        activeRangeRequests += 1
        stats.maxActiveRangeRequests = Math.max(stats.maxActiveRangeRequests, activeRangeRequests)
        try {
          await new Promise(resolve => window.setTimeout(resolve, 25))
          const response = await fetch(request.sourceUrl, {
            headers: { Range: `bytes=${start}-${end}` },
          })
          if (response.status !== 206) {
            stats.fallbackCount += 1
            return readResponseBytes(await fetch(request.sourceUrl))
          }
          return readResponseBytes(response)
        } finally {
          activeRangeRequests -= 1
        }
      }))

      const merged = new Uint8Array(chunks.reduce((total, chunk) => total + chunk.byteLength, 0))
      let offset = 0
      chunks.forEach(chunk => {
        merged.set(chunk, offset)
        offset += chunk.byteLength
      })
      return merged
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
          if (command === 'cancel_download_task') {
            cancelledTasks.add(args.taskId)
            emit('pc-download-cancelled', { taskId: args.taskId })
            return null
          }
          if (command !== 'start_download_task') {
            return null
          }

          const request = args.request
          stats.activeTasks += 1
          stats.maxActiveTasks = Math.max(stats.maxActiveTasks, stats.activeTasks)
          emit('pc-download-progress', {
            taskId: request.id,
            status: 'downloading',
            totalBytes: 0,
            downloadedBytes: 0,
            speedBytesPerSecond: 0,
            chunks: [],
          })

          try {
            const bytes = await downloadBytes(request)
            if (cancelledTasks.has(request.id)) {
              throw { taskId: request.id, code: 'cancelled', message: '下载已取消', retryable: false }
            }
            const hash = await hashBytes(bytes)
            stats.hashes[request.id] = hash
            stats.completed.push(request.id)
            const task = {
              id: request.id,
              sourceUrl: request.sourceUrl,
              fileName: request.fileName,
              savePath: request.savePath,
              totalBytes: bytes.byteLength,
              downloadedBytes: bytes.byteLength,
              status: 'completed',
              threads: request.threads,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            }
            emit('pc-download-completed', task)
            return task
          } catch (error: any) {
            if (error?.code === 'cancelled') {
              stats.cancelled.push(request.id)
              emit('pc-download-cancelled', { taskId: request.id })
            } else {
              const payload = {
                taskId: request.id,
                code: error?.code || 'download_failed',
                message: error?.message || '下载失败',
                retryable: error?.retryable !== false,
              }
              stats.failed.push({ taskId: request.id, code: payload.code })
              emit('pc-download-failed', payload)
            }
            throw error
          } finally {
            stats.activeTasks -= 1
          }
        },
      },
    })
  }, { maxConcurrentTasks })
}

async function openDownloads(page: Page, maxConcurrentTasks = 2) {
  await installTauriDownloadHarness(page, maxConcurrentTasks)
  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'download-test', role: 'user' },
      }),
    })
  })
  await page.goto('/pc/downloads')
  await expect(page).toHaveURL(/\/pc\/downloads$/)
  await expect(page.locator('.pc-downloads-view')).toBeVisible()
}

async function enqueueDownloads(page: Page, tasks: Array<{ sourceUrl: string; fileName: string; savePath: string; threads: number }>) {
  await page.evaluate(async (tasksToQueue) => {
    const { usePcDownloadsStore } = await import('/src/stores/pcDownloads.ts')
    const store = usePcDownloadsStore()
    tasksToQueue.forEach(task => store.enqueueDownload(task))
  }, tasks)
}

async function getStoreTasks(page: Page) {
  return page.evaluate(async () => {
    const { usePcDownloadsStore } = await import('/src/stores/pcDownloads.ts')
    return usePcDownloadsStore().tasks.map(task => ({
      id: task.id,
      status: task.status,
      errorCode: task.error?.code || '',
    }))
  })
}

test.describe('PC download concurrency', () => {
  test('downloads 1/4/8 thread files with matching hashes', async ({ page }) => {
    await openDownloads(page, 3)
    await enqueueDownloads(page, [1, 4, 8].map(threads => ({
      sourceUrl: `${fixtureServerUrl}/range/thread-${threads}`,
      fileName: `thread-${threads}.bin`,
      savePath: `/tmp/thread-${threads}.bin`,
      threads,
    })))

    await expect.poll(async () => page.evaluate(() => window.__downloadTestStats.completed.length)).toBe(3)
    const stats = await page.evaluate(() => window.__downloadTestStats)
    expect(stats.threadCounts.sort((a: number, b: number) => a - b)).toEqual([1, 4, 8])
    expect(Object.values(stats.hashes).sort()).toEqual([fixtureHash, fixtureHash, fixtureHash].sort())
    expect(stats.maxActiveRangeRequests).toBeGreaterThanOrEqual(4)
  })

  for (const maxConcurrentTasks of [1, 2, 4]) {
    test(`respects global concurrency ${maxConcurrentTasks}`, async ({ page }) => {
      await openDownloads(page, maxConcurrentTasks)
      await enqueueDownloads(page, Array.from({ length: 6 }, (_, index) => ({
        sourceUrl: `${fixtureServerUrl}/range/concurrency-${maxConcurrentTasks}-${index}`,
        fileName: `concurrency-${index}.bin`,
        savePath: `/tmp/concurrency-${index}.bin`,
        threads: 2,
      })))

      await expect.poll(async () => page.evaluate(() => window.__downloadTestStats.completed.length)).toBe(6)
      const stats = await page.evaluate(() => window.__downloadTestStats)
      expect(stats.maxActiveTasks).toBeLessThanOrEqual(maxConcurrentTasks)
    })
  }

  test('uses no-Range fallback and keeps the hash correct', async ({ page }) => {
    await openDownloads(page, 1)
    await enqueueDownloads(page, [{
      sourceUrl: `${fixtureServerUrl}/no-range/fallback`,
      fileName: 'fallback.bin',
      savePath: '/tmp/fallback.bin',
      threads: 8,
    }])

    await expect.poll(async () => page.evaluate(() => window.__downloadTestStats.completed.length)).toBe(1)
    const stats = await page.evaluate(() => window.__downloadTestStats)
    expect(stats.fallbackCount).toBeGreaterThanOrEqual(1)
    expect(Object.values(stats.hashes)).toContain(fixtureHash)
  })

  test('handles cancel, retry, and disk full states', async ({ page }) => {
    await openDownloads(page, 1)
    await enqueueDownloads(page, [{
      sourceUrl: `${fixtureServerUrl}/range/cancel`,
      fileName: 'cancel.bin',
      savePath: '/tmp/cancel.bin',
      threads: 8,
    }])

    await expect.poll(async () => page.evaluate(() => window.__downloadTestStats.activeTasks)).toBe(1)
    await page.evaluate(async () => {
      const { usePcDownloadsStore } = await import('/src/stores/pcDownloads.ts')
      const store = usePcDownloadsStore()
      await store.cancelTask(store.tasks[0].id)
    })
    await expect.poll(async () => (await getStoreTasks(page))[0]?.status).toBe('cancelled')
    await expect.poll(async () => page.evaluate(() => window.__downloadTestStats.activeTasks)).toBe(0)

    await enqueueDownloads(page, [{
      sourceUrl: `${fixtureServerUrl}/fail-once/retry`,
      fileName: 'retry.bin',
      savePath: '/tmp/retry.bin',
      threads: 4,
    }])
    await expect.poll(async () => (await getStoreTasks(page)).find(task => task.status === 'failed')?.errorCode).toBe('network_interrupted')
    await page.evaluate(async () => {
      const { usePcDownloadsStore } = await import('/src/stores/pcDownloads.ts')
      const store = usePcDownloadsStore()
      const failedTask = store.tasks.find(task => task.status === 'failed')
      if (failedTask) store.retryTask(failedTask.id)
    })
    await expect.poll(async () => page.evaluate(() => window.__downloadTestStats.completed.length)).toBe(1)

    await enqueueDownloads(page, [{
      sourceUrl: `${fixtureServerUrl}/disk-full/full`,
      fileName: 'disk-full.bin',
      savePath: '/tmp/disk-full.bin',
      threads: 4,
    }])
    await expect.poll(async () => (await getStoreTasks(page)).find(task => task.errorCode === 'disk_full')?.status).toBe('failed')
  })
})
