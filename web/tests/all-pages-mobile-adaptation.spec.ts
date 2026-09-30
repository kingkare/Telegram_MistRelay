import { test, expect, type Page } from '@playwright/test'
import fs from 'fs'
import path from 'path'

const SCREENSHOT_DIR = '/root/MistRelay-dev/mobile-screenshots/all-pages'

test.beforeAll(() => {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
})

async function setupAllMobileMocks(page: Page, isLoggedIn = true) {
  await page.addInitScript((loggedIn: boolean) => {
    if (loggedIn) {
      window.localStorage.setItem('token', 'mobile-e2e-token')
      window.localStorage.setItem('mistrelay.refreshToken', 'mobile-e2e-refresh')
      window.localStorage.setItem('mistrelay.drive.viewMode', 'grid')
      window.localStorage.setItem('mistrelay_edge_view_mode', 'grid')
      window.localStorage.setItem('mistrelay_onboarding_dismissed_1', 'true')
      window.localStorage.setItem('mistrelay.welcome.dismissed.1', 'true')
    } else {
      window.localStorage.removeItem('token')
      window.localStorage.removeItem('mistrelay.refreshToken')
    }
  }, isLoggedIn)

  // 全局兜底所有 /api/ 请求
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    })
  })

  await page.route('**/api/bots/benchmark**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { nodes: [], summary: '全网节点巡检就绪' } }),
    })
  })

  // 1. Auth & Health & Status
  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: {
          id: 1,
          username: 'MistRelay Admin',
          role: 'admin',
          dc_id: 5,
          tg_user_id: 1008611,
          bin_channel_id: -100192837465,
          bin_channel_username: 'mistrelay_storage',
        },
      }),
    })
  })

  await page.route('**/api/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ready: true, server_status: 'running', telegram_connected: true, version: 'v2.2.5' }),
    })
  })

  await page.route('**/api/auth/bot-info', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        bot_username: 'MistRelayOfficialBot',
        bot_name: 'MistRelay Bot',
        register_url: 'https://t.me/MistRelayOfficialBot?start=register',
        register_deep_link: 'https://t.me/MistRelayOfficialBot?start=register',
      }),
    })
  })

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        server_status: 'running',
        uptime: '5 天 18 小时',
        telegram_bot: '@MistRelayOfficialBot',
        connected_bots: 4,
        version: 'v2.2.5',
        loads: { 'Bot-SG-1': 8, 'Bot-SG-2': 14, 'Bot-HK-1': 4, 'Bot-US-1': 6 },
        channel_info: {
          channel_id: -100192837465,
          public_handle: 'mistrelay_storage',
          accessible_bots: 4,
          write_bots: 2,
          no_join_balancing_active: true,
          dc_partition_summary: [
            { dc_id: 5, label: 'DC5 (亚太/新加坡)', files_count: 186, home_bots: [1, 2, 3], warm_bots: [4] },
            { dc_id: 1, label: 'DC1 (北美/迈阿密)', files_count: 42, home_bots: [4], warm_bots: [1, 2] },
          ],
        },
        bot_details: [
          { index: 1, name: 'Bot-SG-1', username: 'mistrelay_sg1_bot', dc_id: 5, status: 'active', ping: 18, load: 8, can_read: true, can_write: true },
          { index: 2, name: 'Bot-SG-2', username: 'mistrelay_sg2_bot', dc_id: 5, status: 'active', ping: 22, load: 14, can_read: true, can_write: true },
          { index: 3, name: 'Bot-HK-1', username: 'mistrelay_hk1_bot', dc_id: 5, status: 'active', ping: 16, load: 4, can_read: true, can_write: false },
          { index: 4, name: 'Bot-US-1', username: 'mistrelay_us1_bot', dc_id: 1, status: 'active', ping: 45, load: 6, can_read: true, can_write: false },
        ],
      }),
    })
  })

  // 2. System & Resources
  await page.route('**/api/system/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        status: 'running',
        uptime: 496800,
        memory: { total: 16384, used: 4096, free: 12288, percent: 25 },
        cpu: { percent: 18.5 },
        disk: { total: 500, used: 124, free: 376, percent: 24.8 },
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
          cpu: { percent: 18.5 },
          memory: { percent: 25.0, used: 4294967296, total: 17179869184 },
          disk: { percent: 24.8, used: 133143986176, total: 536870912000 },
          network: { rx_sec: 12400000, tx_sec: 48500000 },
        },
      }),
    })
  })

  // 3. Downloads & Uploads & Queue
  await page.route('**/api/downloads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { total: 42, completed: 38, failed: 1, active: 3 } }),
    })
  })

  await page.route('**/api/uploads/statistics', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { total: 56, cleaned: 52, active: 4 } }),
    })
  })

  await page.route('**/api/downloads**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        grouped: true,
        data: [
          {
            group_key: 'g1',
            group_type: 'single',
            caption: 'Cyberpunk 2077 Edgerunners S01 4K HDR',
            created_at: '2026-09-30T08:00:00Z',
            stats: { total_files: 2, completed: 1, downloading: 1, failed: 0, pending: 0, total_size: 28253611008, completed_size: 22451840000 },
            downloads: [
              {
                id: 101,
                gid: 'gid_101',
                file_name: 'Cyberpunk_Edgerunners_S01E01_4K.mkv',
                status: 'downloading',
                total_length: 18253611008,
                completed_length: 12451840000,
                download_speed: 45200000,
                created_at: '2026-09-30T08:00:00Z',
                updated_at: '2026-09-30T08:15:00Z',
                uploads: [],
              },
              {
                id: 102,
                gid: 'gid_102',
                file_name: 'Cyberpunk_Edgerunners_S01E02_4K.mkv',
                status: 'completed',
                total_length: 10000000000,
                completed_length: 10000000000,
                download_speed: 0,
                created_at: '2026-09-30T07:30:00Z',
                updated_at: '2026-09-30T07:50:00Z',
                uploads: [{ id: 201, status: 'completed', upload_target: 'telegram' }],
              },
            ],
          },
        ],
      }),
    })
  })

  await page.route('**/api/uploads**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          {
            id: 301,
            download_id: 102,
            file_name: 'Frieren_Beyond_Journeys_End_EP28_BD.mp4',
            upload_target: 'telegram',
            status: 'uploading',
            uploaded_size: 858993459,
            total_size: 1717986918,
            upload_speed: 28400000,
            created_at: '2026-09-30T08:10:00Z',
            updated_at: '2026-09-30T08:16:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/queue**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queue: [], queue_size: 0 }),
    })
  })

  // 4. TG Drive
  await page.route('**/api/telegram/usage**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        total_files: 228,
        total_size: 113494188032,
        by_type: { video: 168, document: 42, photo: 12, audio: 6 },
      }),
    })
  })

  await page.route('**/api/telegram/thumbnails/status**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, ready: 210, total: 228, pending: 0, running: false }),
    })
  })

  await page.route('**/api/telegram/browse**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        total: 4,
        page: 1,
        page_size: 20,
        items: [
          {
            item_type: 'file',
            file_unique_id: 'f_video_1',
            message_id: 1001,
            chat_id: -100192837465,
            file_name: 'Blade_Runner_2049_4K_DolbyVision.mp4',
            mime_type: 'video/mp4',
            media_type: 'video',
            file_size: 14829384712,
            duration: 9840,
            width: 3840,
            height: 2160,
            dc_id: 5,
            message_date: '2026-09-29T18:30:00Z',
          },
          {
            item_type: 'file',
            file_unique_id: 'f_video_2',
            message_id: 1002,
            chat_id: -100192837465,
            file_name: 'Oppenheimer_2023_IMAX_1080p.mkv',
            mime_type: 'video/x-matroska',
            media_type: 'video',
            file_size: 8429384712,
            duration: 10800,
            width: 1920,
            height: 1080,
            dc_id: 5,
            message_date: '2026-09-28T15:20:00Z',
          },
          {
            item_type: 'folder',
            media_group_id: 'mg_album_1',
            file_name: '京都秋日摄影原片合集 (RAW+JPG)',
            caption: '京都秋日摄影原片合集 (RAW+JPG)',
            file_count: 12,
            total_size: 645928192,
            media_type: 'album',
            dc_id: 5,
            message_date: '2026-09-27T11:10:00Z',
          },
          {
            item_type: 'file',
            file_unique_id: 'f_audio_1',
            message_id: 1004,
            chat_id: -100192837465,
            file_name: 'Hans_Zimmer_Interstellar_OST_FLAC.flac',
            mime_type: 'audio/flac',
            media_type: 'audio',
            file_size: 452984832,
            duration: 4200,
            dc_id: 1,
            message_date: '2026-09-26T09:00:00Z',
          },
        ],
      }),
    })
  })

  // 5. Edge Nodes
  await page.route('**/api/edge/nodes**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        summary: {
          total_nodes: 2,
          online_nodes: 2,
          deploying_nodes: 0,
          shared_pool_nodes: 2,
          active_streams: 3,
          total_tx_speed: 38500000,
          total_bytes_served: 549755813888,
          tenants: [
            {
              tenant_id: 1,
              username: 'MistRelay Admin',
              role: 'admin',
              is_owner: true,
              active_streams: 2,
              net_tx: 26500000,
              total_bytes: 389755813888,
              last_active: new Date().toISOString(),
              node_count: 2,
            },
            {
              tenant_id: 2,
              username: 'sakura_tenant',
              role: 'user',
              is_owner: false,
              active_streams: 1,
              net_tx: 12000000,
              total_bytes: 160000000000,
              last_active: new Date().toISOString(),
              node_count: 1,
            },
          ],
        },
        nodes: [
          {
            id: 1,
            node_name: '新加坡 CN2 GIA 极速节点 #1',
            ip: '45.192.108.12',
            domain: 'sg1-edge.mistrelay.io',
            ssh_port: 22,
            ssh_user: 'root',
            worker_port: 8787,
            use_ssl: true,
            status: 'online',
            allow_shared_pool: true,
            allow_bot_pool: true,
            target_dc_id: 5,
            assigned_bot_username: 'mistrelay_sg1_bot',
            tenant_username: 'MistRelay Admin',
            metrics: {
              cpu: 24.5,
              mem: 41.2,
              active_streams: 2,
              net_tx: 26500000,
              net_rx: 27100000,
              total_bytes_served: 389755813888,
              tenants: [
                {
                  tenant_id: 1,
                  username: 'MistRelay Admin',
                  is_owner: true,
                  active_streams: 2,
                  net_tx: 26500000,
                  total_bytes: 389755813888,
                  last_active: new Date().toISOString(),
                },
              ],
            },
            benchmark_data: {
              health_score: 96,
              health_grade: 'S',
              fastest_dc: { dc_id: 5, name: 'DC5 亚太(新加坡)', avg_rtt_ms: 4.2 },
              bandwidth: { down_speed_mb_s: 95.4, up_speed_mb_s: 88.2, effective_bw_mb_s: 88.2, down_speed_mbps: 763 },
              speed: { relay_speed_mb_s: 64.5, peak_speed_mb_s: 72.1, usable_bots_count: 6 },
            },
          },
          {
            id: 2,
            node_name: '美西洛杉矶 9929 节点 #2',
            ip: '142.171.88.50',
            domain: 'us1-edge.mistrelay.io',
            ssh_port: 22,
            ssh_user: 'root',
            worker_port: 8787,
            use_ssl: true,
            status: 'online',
            allow_shared_pool: true,
            allow_bot_pool: true,
            target_dc_id: 1,
            assigned_bot_username: 'mistrelay_us1_bot',
            tenant_username: 'MistRelay Admin',
            metrics: {
              cpu: 12.0,
              mem: 32.8,
              active_streams: 1,
              net_tx: 12000000,
              net_rx: 12500000,
              total_bytes_served: 160000000000,
              tenants: [],
            },
            benchmark_data: {
              health_score: 91,
              health_grade: 'A+',
              fastest_dc: { dc_id: 1, name: 'DC1 北美(迈阿密)', avg_rtt_ms: 19.8 },
              bandwidth: { down_speed_mb_s: 82.0, up_speed_mb_s: 76.5, effective_bw_mb_s: 76.5, down_speed_mbps: 656 },
              speed: { relay_speed_mb_s: 48.2, peak_speed_mb_s: 54.0, usable_bots_count: 4 },
            },
          },
        ],
      }),
    })
  })

  // 6. Users & Backups
  await page.route('**/api/users**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        summary: {
          total_users: 3,
          admin_count: 1,
          tenant_count: 2,
          bound_channel_count: 3,
          total_media_files: 272,
          total_media_bytes: 113494188032,
        },
        users: [
          {
            id: 1,
            username: 'admin',
            role: 'admin',
            tg_user_id: 1008611,
            tg_username: 'mistrelay_admin',
            tg_first_name: 'Mist Admin',
            dc_id: 5,
            bin_channel_id: -100192837465,
            bin_channel_username: 'mistrelay_storage',
            media_count: 180,
            media_bytes: 85899345920,
            active_sessions: 2,
            created_at: '2026-09-01T10:00:00Z',
          },
          {
            id: 2,
            username: 'sakura_tenant',
            role: 'user',
            tg_user_id: 2008899,
            tg_username: 'sakura_chan',
            tg_first_name: 'Sakura',
            dc_id: 5,
            bin_channel_id: -100188776655,
            bin_channel_username: 'sakura_private_bin',
            media_count: 92,
            media_bytes: 27594842112,
            active_sessions: 1,
            created_at: '2026-09-15T14:30:00Z',
          },
        ],
        recent_codes: [
          {
            code: '894216',
            tg_user_id: 3009911,
            tg_username: 'new_player',
            tg_first_name: 'Leo',
            detected_dc_id: 5,
            used: false,
            created_at: '2026-09-30T08:00:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/system/backups**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        schedule: { enabled: true, interval_hours: 24, max_keep: 15, last_run: '2026-09-30T04:00:00Z' },
        backups: [
          {
            filename: 'backup_mistrelay_20260928_125911.tar.gz',
            size: 15728640,
            size_formatted: '15.00 MB',
            created_at: '2026-09-28T12:59:11Z',
            type: 'archive',
            is_protected: true,
            is_safety_snapshot: false,
            remark: '金牌灾备基线',
            manifest: {
              db_tables: { users: 25, tg_media: 272 },
              sessions_count: 24,
            },
          },
        ],
      }),
    })
  })

  // 7. BotFather Accounts
  await page.route('**/api/telegram/botfather/accounts**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        accounts: [
          {
            id: 1,
            phone: '+65 8912 3456',
            first_name: 'SG Worker Alpha',
            username: 'sg_alpha_user',
            dc_id: 5,
            region_label: '新加坡 (DC5)',
            status: 'ready',
            bots_created: 12,
            max_bots: 20,
            updated_at: '2026-09-30T06:00:00Z',
          },
          {
            id: 2,
            phone: '+1 305 889 1024',
            first_name: 'US Worker Beta',
            username: 'us_beta_user',
            dc_id: 1,
            region_label: '美国迈阿密 (DC1)',
            status: 'ready',
            bots_created: 8,
            max_bots: 20,
            updated_at: '2026-09-30T07:00:00Z',
          },
        ],
      }),
    })
  })

  await page.route('**/api/telegram/harvester/status**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, running: false, tasks: [] }),
    })
  })

  // 8. Cache Stats & Policy
  await page.route('**/api/cache/stats**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total_bytes: 2147483648,
          max_bytes: 10737418240,
          usage_percent: 20.0,
          file_count: 642,
          hit_rate: 94.6,
          categories: {
            thumbnails: { bytes: 536870912, count: 480 },
            streams: { bytes: 1610612736, count: 162 },
          },
        },
      }),
    })
  })

  await page.route('**/api/cache/policy**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        policy: {
          max_size_gb: 10,
          ttl_hours: 72,
          auto_clean_enabled: true,
          keep_thumbnails: true,
        },
      }),
    })
  })

  // 9. Customer Service
  await page.route('**/api/telegram/customer-service/status**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        running: true,
        bot_username: 'MistRelayCSBot',
        bot_first_name: 'MistRelay 智能客服助手',
        total_Handled: 328,
        config: {
          enabled: true,
          bot_token: '7123456:AAH_mock_cs_bot_token',
          llm_api_base: 'https://api.openai.com/v1',
          llm_model: 'gpt-4o-mini',
          reply_in_groups: true,
          reply_in_private: true,
          official_website: 'https://mistrelay.example.com',
        },
      }),
    })
  })

  // 10. Settings & Config & Logs
  await page.route('**/api/config**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          telegram: { api_id: '123456', api_hash: 'mock_hash', bot_token: 'mock_token', bin_channel: '-100192837465' },
          aria2: { rpc_url: 'http://127.0.0.1:6800/jsonrpc', rpc_secret: 'mistrelay_secret' },
          server: { port: 8080, host: '0.0.0.0', base_url: 'https://mistrelay.example.com' },
        },
      }),
    })
  })

  await page.route('**/api/system/docker/status**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        running: true,
        container_name: 'mistrelay',
        uptime: '5 days',
        cpu_percent: 16.4,
        memory_usage: '4.1 GB / 16.0 GB',
      }),
    })
  })

  await page.route('**/api/logs/files**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        files: [
          { name: 'mistrelay.log', size: 1048576, modified: '2026-09-30 08:20:00' },
          { name: 'aria2.log', size: 524288, modified: '2026-09-30 08:15:00' },
        ],
      }),
    })
  })

  await page.route('**/api/logs/content**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        lines: [
          '2026-09-30 08:20:01 [INFO] MistRelay server listening on 0.0.0.0:8080',
          '2026-09-30 08:20:02 [INFO] Connected 4 Telegram worker bots (DC5/DC1)',
          '2026-09-30 08:20:05 [INFO] Edge node #1 heartbeat OK (rtt=4.2ms)',
        ],
      }),
    })
  })
}

async function assertNoHorizontalOverflow(page: Page, routeLabel: string) {
  const overflowInfo = await page.evaluate(() => {
    const docEl = document.documentElement
    const body = document.body
    return {
      docScrollWidth: docEl.scrollWidth,
      docClientWidth: docEl.clientWidth,
      bodyScrollWidth: body.scrollWidth,
      bodyClientWidth: body.clientWidth,
      viewportWidth: window.innerWidth,
    }
  })
  expect(
    overflowInfo.docScrollWidth - overflowInfo.docClientWidth,
    `[${routeLabel}] documentElement 存在横向溢出: ${JSON.stringify(overflowInfo)}`
  ).toBeLessThanOrEqual(1)
}

test.describe('MistRelay 全页面移动端深度适配与全功能触控巡检 (iPhone 14/15 - 390x844)', () => {
  test.use({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  })

  test('1. 官网展示首页 (/) 与登录页 (/login) 移动端适配与截图', async ({ page }) => {
    await setupAllMobileMocks(page, false)

    // 1.1 访问官网首页
    await page.goto('/?preview=1')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.landing-header')).toBeVisible()
    await assertNoHorizontalOverflow(page, 'Landing (/)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01-landing.png'), fullPage: false })

    // 1.2 访问登录页 (模拟 TMA 宿主环境)
    await page.route('https://telegram.org/js/telegram-web-app.js', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: `
          window.Telegram = {
            WebApp: {
              initData: 'query_id=AAHdF6IQAAAAAN0XohD9&user=%7B%22id%22%3A1008611%2C%22first_name%22%3A%22Alex%22%7D&auth_date=1720000000&hash=mock_hash',
              initDataUnsafe: { user: { id: 1008611, first_name: 'Alex' } },
              ready: function() {},
              expand: function() {},
              BackButton: { isVisible: false, onClick: function() {}, offClick: function() {}, show: function() {}, hide: function() {} }
            }
          };
        `,
      })
    })
    await page.route('**/api/auth/tma', async route => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ success: false, error: 'TMA 预览模式' }),
      })
    })

    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.tma-quick-box')).toBeVisible()
    await assertNoHorizontalOverflow(page, 'Login (/login)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02-login.png'), fullPage: false })
  })

  test('2. 仪表盘 (/dashboard)、任务中心 (/downloads) 与 TG 网盘 (/drive) 双模卡片与截图', async ({ page }) => {
    await setupAllMobileMocks(page, true)

    // 2.1 仪表盘
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.sidebar')).toHaveCount(0)
    await expect(page.locator('.app-bottom-nav')).toBeVisible()
    await expect(page.locator('.mobile-recent-downloads')).toBeVisible()
    await assertNoHorizontalOverflow(page, 'Dashboard (/dashboard)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03-dashboard.png'), fullPage: false })

    // 2.2 任务中心 (下载中 + 历史记录分组卡片)
    await page.goto('/downloads')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.mobile-task-cards-list').first()).toBeVisible()
    await assertNoHorizontalOverflow(page, 'Downloads (/downloads)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04-downloads-active.png'), fullPage: false })

    // 切换到历史记录标签页并展开分组验证移动端历史卡片流
    await page.getByRole('tab', { name: /历史记录/ }).click()
    await page.waitForTimeout(250)
    await assertNoHorizontalOverflow(page, 'Downloads History (/downloads)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05-downloads-history.png'), fullPage: false })

    // 2.3 TG 网盘
    await page.goto('/drive')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.grid-view')).toBeVisible()
    await expect(page.getByText('Blade_Runner_2049_4K_DolbyVision.mp4')).toBeVisible()
    await assertNoHorizontalOverflow(page, 'Drive (/drive)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06-drive.png'), fullPage: false })
  })

  test('3. 边缘分流中心 (/edge-nodes) 与租户排行榜弹窗双模卡片检验', async ({ page }) => {
    await setupAllMobileMocks(page, true)

    await page.goto('/edge-nodes')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.nodes-grid')).toBeVisible()
    await expect(page.getByText('新加坡 CN2 GIA 极速节点 #1')).toBeVisible()
    await assertNoHorizontalOverflow(page, 'EdgeNodes (/edge-nodes)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07-edge-nodes.png'), fullPage: false })

    // 点击打开全网租户分流总榜弹窗，验证弹窗宽度 <= 95vw 且显示移动端卡片流
    const rankBtn = page.locator('.tenant-summary-btn')
    if (await rankBtn.isVisible()) {
      await rankBtn.click()
      const dialog = page.locator('.edge-tenant-dialog')
      await expect(dialog).toBeVisible()
      await expect(dialog.locator('.mobile-tenant-rank-card').first()).toBeVisible()
      const box = await dialog.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.width).toBeLessThanOrEqual(390 * 0.96)
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08-edge-tenant-ranking-dialog.png'), fullPage: false })
      await page.keyboard.press('Escape')
    }
  })

  test('4. 用户与租户管理中枢 (/users) 及灾备归档弹窗双模卡片检验', async ({ page }) => {
    await setupAllMobileMocks(page, true)

    await page.goto('/users')
    await page.waitForLoadState('networkidle')
    // 移动端用户卡片可见，桌面宽表格隐藏
    await expect(page.locator('.mobile-user-cards-list')).toBeVisible()
    await expect(page.locator('.mobile-user-card').first()).toBeVisible()
    await assertNoHorizontalOverflow(page, 'Users (/users)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '09-users.png'), fullPage: false })

    // 打开灾备管理弹窗，验证移动端灾备卡片流与弹窗宽度自适应
    const backupBtn = page.locator('.backup-entry-btn')
    if (await backupBtn.isVisible()) {
      await backupBtn.click()
      const backupDialog = page.locator('.disaster-backup-dialog')
      await expect(backupDialog).toBeVisible()
      await expect(backupDialog.locator('.mobile-backup-cards')).toBeVisible()
      const box = await backupDialog.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.width).toBeLessThanOrEqual(390 * 0.96)
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, '10-users-backup-dialog.png'), fullPage: false })
      await page.keyboard.press('Escape')
    }
  })

  test('5. 集群管理 (/bots)、自动铸机 (/botfather)、缓存 (/cache)、客服 (/customer-service) 与设置 (/settings) 巡检', async ({ page }) => {
    await setupAllMobileMocks(page, true)

    // 5.1 集群管理 (/bots)
    await page.goto('/bots')
    await page.waitForLoadState('networkidle')
    await assertNoHorizontalOverflow(page, 'Bots (/bots)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '11-bots.png'), fullPage: false })

    // 5.2 自动铸机 (/botfather)
    await page.goto('/botfather')
    await page.waitForLoadState('networkidle')
    await assertNoHorizontalOverflow(page, 'BotFather (/botfather)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '12-botfather.png'), fullPage: false })

    // 5.3 缓存管理 (/cache)
    await page.goto('/cache')
    await page.waitForLoadState('networkidle')
    await assertNoHorizontalOverflow(page, 'Cache (/cache)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '13-cache.png'), fullPage: false })

    // 5.4 AI 客服中枢 (/customer-service)
    await page.goto('/customer-service')
    await page.waitForLoadState('networkidle')
    await assertNoHorizontalOverflow(page, 'CustomerService (/customer-service)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '14-customer-service.png'), fullPage: false })

    // 5.5 系统设置 (/settings)
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')
    await assertNoHorizontalOverflow(page, 'Settings (/settings)')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '15-settings.png'), fullPage: false })

    // 5.6 全局移动端导航抽屉 (AppMobileDrawer)
    const hamburgerBtn = page.locator('.mobile-hamburger-btn')
    await expect(hamburgerBtn).toBeVisible()
    await hamburgerBtn.click()
    const drawer = page.locator('.mobile-nav-drawer')
    await expect(drawer).toBeVisible()
    await page.waitForTimeout(300)
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '16-mobile-drawer.png'), fullPage: false })
  })
})

test.describe('小屏紧凑设备极限防溢出校验 (iPhone SE - 375x667)', () => {
  test.use({
    viewport: { width: 375, height: 667 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  })

  test('在 375px 窄屏下核心高频页零横向溢出', async ({ page }) => {
    await setupAllMobileMocks(page, true)
    for (const route of ['/dashboard', '/downloads', '/drive', '/edge-nodes', '/users', '/settings']) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      await assertNoHorizontalOverflow(page, `iPhoneSE ${route}`)
    }
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '17-iphone-se-compact.png'), fullPage: false })
  })
})
