import { expect, test, type Page } from '@playwright/test'

const MOCK_STATUS = {
  is_logged_in: true,
  user: { id: 1, username: 'admin', role: 'admin' },
  bot_details: [
    { index: 0, username: 'jiuyuetanzhen_bot', mode: 'primary_admin', home_dc: 5, warm_dcs: [4, 5], can_read: true, can_write: true },
    { index: 1, username: 'qianlong520f001_bot', mode: 'direct_admin', home_dc: 1, warm_dcs: [1, 5], can_read: true, can_write: true },
    { index: 2, username: 'jiuyue520_bot', mode: 'direct_admin', home_dc: 1, warm_dcs: [1], can_read: true, can_write: true },
    { index: 3, username: 'qianlong520_bot', mode: 'no_join_resolved', home_dc: 5, warm_dcs: [5], can_read: true, can_write: false },
    { index: 4, username: 'qianlong520f002_bot', mode: 'direct_admin', home_dc: 4, warm_dcs: [4, 5], can_read: true, can_write: true },
    { index: 5, username: 'mistrelay_node_0952e5_bot', mode: 'no_join_resolved', home_dc: 5, warm_dcs: [5], can_read: true, can_write: false },
    { index: 6, username: 'mistrelay_node_9e3dd1_bot', mode: 'no_join_resolved', home_dc: 1, warm_dcs: [1], can_read: true, can_write: false },
    { index: 7, username: 'mistrelay_node_d594d5_bot', mode: 'no_join_resolved', home_dc: 5, warm_dcs: [5], can_read: true, can_write: false },
    { index: 8, username: 'mistrelay_node_a01e15_bot', mode: 'no_join_resolved', home_dc: 1, warm_dcs: [1], can_read: true, can_write: false },
    { index: 9, username: 'mistrelay_node_dc041f_bot', mode: 'no_join_resolved', home_dc: 5, warm_dcs: [5], can_read: true, can_write: false },
  ],
  dc_partitions: {
    '1': { dc_id: 1, label: 'DC1 (美西 / 迈阿密)', home_bots: [1, 2, 6, 8], warm_bots: [1, 2, 6, 8], files_count: 12, requests_count: 45 },
    '2': { dc_id: 2, label: 'DC2 (欧洲 / 阿姆斯特丹)', home_bots: [], warm_bots: [], files_count: 0, requests_count: 0 },
    '3': { dc_id: 3, label: 'DC3 (美东 / 迈阿密)', home_bots: [], warm_bots: [], files_count: 0, requests_count: 0 },
    '4': { dc_id: 4, label: 'DC4 (欧洲 / 阿姆斯特丹)', home_bots: [4], warm_bots: [0, 4], files_count: 28, requests_count: 110 },
    '5': { dc_id: 5, label: 'DC5 (亚太 / 新加坡)', home_bots: [0, 3, 5, 7, 9], warm_bots: [0, 1, 3, 4, 5, 7, 9], files_count: 122, requests_count: 350 },
  },
  channel_info: {
    channel_id: -1001998444696,
    channel_type: 'public',
    public_handle: 'jiuyue1314520',
    no_join_balancing_active: true,
    accessible_bots: 10,
    write_bots: 4,
  },
  workloads: {
    '0': 1,
    '5': 2,
    '6': 0,
    '7': 0,
    '8': 1,
    '9': 0,
  },
  system_info: {
    service_status: 'healthy',
    active_bot: 'jiuyuetanzhen_bot',
    connected_bots: 10,
    server_time: '2026-09-26 16:00:00',
    uptime: '1h 30m',
    version: '2.2.5',
  },
}

const MOCK_TASK_STATUS = {
  success: true,
  data: {
    task_id: 'mint_123456',
    status: 'idle',
    target_count: 20,
    created_count: 5,
    reused_count: 5,
    total_active_workers: 9,
    cooldown_remaining: 0,
    cooldown_total: 0,
    current_step: '等待启动协议号自动化铸造流水线...',
    percent: 50.0,
    logs: [
      { time: '16:00:01', level: 'info', msg: '协议号会话缓存验证成功' },
      { time: '16:00:02', level: 'success', msg: '成功探测并挂载 5 个存量机器人' },
    ],
    bots: [],
    error: null,
    cached_sessions: [
      { phone: '+16813086196', cached: true },
      { phone: '+18048484620', cached: true },
    ],
  },
}

const MOCK_LOAD_TEST = {
  success: true,
  data: {
    total_bots: 10,
    accessible_bots: 10,
    total_rounds: 100,
    elapsed_ms: 1.45,
    evenness_percent: 100.0,
    distribution: { '0': 10, '1': 10, '2': 10, '3': 10, '4': 10, '5': 10, '6': 10, '7': 10, '8': 10, '9': 10 },
    nodes: [
      { index: 0, username: 'jiuyuetanzhen_bot', mode: 'primary_admin', can_read: true, can_write: true, dispatched_requests: 10, share_percent: 10.0 },
      { index: 1, username: 'qianlong520f001_bot', mode: 'direct_admin', can_read: true, can_write: true, dispatched_requests: 10, share_percent: 10.0 },
      { index: 2, username: 'jiuyue520_bot', mode: 'direct_admin', can_read: true, can_write: true, dispatched_requests: 10, share_percent: 10.0 },
      { index: 3, username: 'qianlong520_bot', mode: 'no_join_resolved', can_read: true, can_write: false, dispatched_requests: 10, share_percent: 10.0 },
      { index: 4, username: 'qianlong520f002_bot', mode: 'direct_admin', can_read: true, can_write: true, dispatched_requests: 10, share_percent: 10.0 },
      { index: 5, username: 'mistrelay_node_0952e5_bot', mode: 'no_join_resolved', can_read: true, can_write: false, dispatched_requests: 10, share_percent: 10.0 },
      { index: 6, username: 'mistrelay_node_9e3dd1_bot', mode: 'no_join_resolved', can_read: true, can_write: false, dispatched_requests: 10, share_percent: 10.0 },
      { index: 7, username: 'mistrelay_node_d594d5_bot', mode: 'no_join_resolved', can_read: true, can_write: false, dispatched_requests: 10, share_percent: 10.0 },
      { index: 8, username: 'mistrelay_node_a01e15_bot', mode: 'no_join_resolved', can_read: true, can_write: false, dispatched_requests: 10, share_percent: 10.0 },
      { index: 9, username: 'mistrelay_node_dc041f_bot', mode: 'no_join_resolved', can_read: true, can_write: false, dispatched_requests: 10, share_percent: 10.0 },
    ],
    message: '完成 100 次并发分流调度压测，10 个就绪节点均衡度 100.0% (耗时 1.45ms)',
  },
}

const MOCK_CLUSTER_BENCHMARK = {
  success: true,
  data: {
    total_tested: 10,
    online_count: 10,
    avg_ping_ms: 68.5,
    fastest_node: { index: 0, username: 'jiuyuetanzhen_bot', ping_ms: 45.2 },
    highest_speed_node: { index: 1, username: 'qianlong520f001_bot', speed_mbps: 18.5 },
    nodes: [
      {
        index: 0,
        username: 'jiuyuetanzhen_bot',
        status: 'ok',
        ping_ms: 45.2,
        channel_ping_ms: 38.1,
        download_speed_mbps: 15.2,
        playback_bitrate_mbps: 121.6,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 1,
        username: 'qianlong520f001_bot',
        status: 'ok',
        ping_ms: 55.4,
        channel_ping_ms: 48.0,
        download_speed_mbps: 18.5,
        playback_bitrate_mbps: 148.0,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 2,
        username: 'jiuyue520_bot',
        status: 'ok',
        ping_ms: 72.1,
        channel_ping_ms: 60.5,
        download_speed_mbps: 14.8,
        playback_bitrate_mbps: 118.4,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 3,
        username: 'qianlong520_bot',
        status: 'ok',
        ping_ms: 65.0,
        channel_ping_ms: 55.0,
        download_speed_mbps: 12.0,
        playback_bitrate_mbps: 96.0,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 4,
        username: 'qianlong520f002_bot',
        status: 'ok',
        ping_ms: 78.3,
        channel_ping_ms: 68.2,
        download_speed_mbps: 16.3,
        playback_bitrate_mbps: 130.4,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 5,
        username: 'mistrelay_node_0952e5_bot',
        status: 'ok',
        ping_ms: 70.2,
        channel_ping_ms: 61.4,
        download_speed_mbps: 11.5,
        playback_bitrate_mbps: 92.0,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 6,
        username: 'mistrelay_node_9e3dd1_bot',
        status: 'ok',
        ping_ms: 82.0,
        channel_ping_ms: 72.0,
        download_speed_mbps: 10.8,
        playback_bitrate_mbps: 86.4,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 7,
        username: 'mistrelay_node_d594d5_bot',
        status: 'ok',
        ping_ms: 69.4,
        channel_ping_ms: 58.3,
        download_speed_mbps: 13.2,
        playback_bitrate_mbps: 105.6,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 8,
        username: 'mistrelay_node_a01e15_bot',
        status: 'ok',
        ping_ms: 74.5,
        channel_ping_ms: 64.1,
        download_speed_mbps: 12.6,
        playback_bitrate_mbps: 100.8,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
      {
        index: 9,
        username: 'mistrelay_node_dc041f_bot',
        status: 'ok',
        ping_ms: 73.4,
        channel_ping_ms: 63.8,
        download_speed_mbps: 12.1,
        playback_bitrate_mbps: 96.8,
        bytes_transferred: 262144,
        grade: 'excellent',
        grade_label: '极佳 (<100ms)',
      },
    ],
    tested_at: '16:05:00',
    summary: '全集群 10 个节点测速完成：平均响应延迟 68.5ms，就绪率 100%',
  },
}

const MOCK_SINGLE_BENCHMARK = {
  success: true,
  data: {
    index: 0,
    username: 'jiuyuetanzhen_bot',
    status: 'ok',
    ping_ms: 42.0,
    channel_ping_ms: 35.0,
    download_speed_mbps: 16.8,
    playback_bitrate_mbps: 134.4,
    bytes_transferred: 262144,
    grade: 'excellent',
    grade_label: '极佳 (<100ms)',
  },
}

const MOCK_STREAM_BENCHMARK = {
  success: true,
  data: {
    tested_node: {
      mode: 'cluster_striped',
      mode_label: '全集群智能条带分流 (Multi-Bot Striping)',
      bot_index: 0,
      bot_username: 'jiuyuetanzhen_bot',
      active_workers_count: 6,
    },
    target_file: {
      message_id: 5948,
      file_name: 'test_sample.mp4',
      file_size: 104857600,
      file_size_formatted: '100.0 MB',
      mime_type: 'video/mp4',
    },
    playback: {
      ttfb_ms: 128.5,
      initial_buffer_ms: 420.0,
      speed_mb_s: 3.25,
      bitrate_mbps: 26.0,
      ratio_1080p: 3.25,
      ratio_4k: 1.04,
      max_supported_resolution: '4K UHD (2160p)',
      stutter_risk: 'none',
      stutter_risk_label: '无卡顿风险 (4K/1080p 秒开极流畅)',
      buffer_bytes: 1048576,
    },
    download: {
      avg_speed_mb_s: 3.85,
      peak_speed_mb_s: 4.52,
      min_speed_mb_s: 3.12,
      duration_ms: 1080.0,
      bytes_transferred: 4194304,
      stability_score: 95.8,
      grade: 'fast',
      grade_label: '高速畅享 (2~5 MB/s)',
      chunk_samples: [
        { part: 1, bot_index: 0, bot_username: 'jiuyuetanzhen_bot', size_kb: 512, elapsed_ms: 130, speed_mb_s: 3.94 },
        { part: 2, bot_index: 1, bot_username: 'qianlong520f001_bot', size_kb: 512, elapsed_ms: 125, speed_mb_s: 4.10 },
        { part: 3, bot_index: 2, bot_username: 'jiuyue520_bot', size_kb: 512, elapsed_ms: 140, speed_mb_s: 3.66 },
        { part: 4, bot_index: 3, bot_username: 'qianlong520_bot', size_kb: 512, elapsed_ms: 135, speed_mb_s: 3.79 },
      ],
    },
    tested_at: '16:30:00',
    summary: '单连接播放码率 26.0 Mbps (流速 3.25 MB/s, 首包 128.5ms)，1080p 实时倍速 3.25x；单连接平均下载速率 3.85 MB/s，稳定性 95.8%。',
  },
}

const MOCK_ACCOUNTS = {
  success: true,
  data: [
    {
      id: 1,
      phone: '+16813086196',
      session_type: 'telethon_string',
      has_code_url: true,
      masked_code_url: 'https://miha.uk/***',
      bot_count: 5,
      max_bots: 20,
      remaining_quota: 15,
      status: 'active',
      last_used_at: '2026-09-26 15:00:00',
      remark: '主力1号',
      created_at: '2026-09-26 10:00:00',
    },
    {
      id: 2,
      phone: '+18048484620',
      session_type: 'telethon_string',
      has_code_url: true,
      masked_code_url: 'https://568.5689889.uk/***',
      bot_count: 20,
      max_bots: 20,
      remaining_quota: 0,
      status: 'limit_reached',
      last_used_at: '2026-09-26 15:30:00',
      remark: '主力2号',
      created_at: '2026-09-26 11:00:00',
    },
  ],
}

async function setupBotsPageMocks(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'admin-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'admin-refresh')
  })

  await page.route('**/api/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ready: true, server_status: 'running', version: 'test' }),
    })
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

  await page.route('**/api/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_STATUS),
    })
  })

  await page.route('**/api/telegram/botfather/task-status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_TASK_STATUS),
    })
  })

  let currentAccounts = [...MOCK_ACCOUNTS.data]
  await page.route('**/api/telegram/botfather/accounts', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: currentAccounts }),
    })
  })

  await page.route(new RegExp('.*/api/telegram/botfather/accounts/\\d+.*'), async (route) => {
    if (route.request().method() === 'DELETE') {
      const match = route.request().url().match(/\/accounts\/(\d+)/)
      const id = match ? Number(match[1]) : 0
      currentAccounts = currentAccounts.filter(a => a.id !== id)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: `协议号 #${id} 已从资产池移除` }),
      })
    } else {
      await route.fallback()
    }
  })

  await page.route('**/api/telegram/botfather/accounts/import', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          async: true,
          task_id: 'import_mock_123',
          status: 'running',
          message: '已在后台启动协议号导入与接码登录任务',
        },
      }),
    })
  })

  await page.route(/.*\/api\/telegram\/botfather\/accounts\/import-task\/.*/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          task_id: 'import_mock_123',
          status: 'completed',
          progress: 100,
          progress_msg: '导入完成：成功 2 个，失败 0 个',
          current_phone: '+16813086196',
          cooldown_remaining: 0,
          imported_count: 2,
          failed_count: 0,
          imported: MOCK_ACCOUNTS.data,
          errors: [],
          logs: [
            { time: '16:00:01', msg: '已启动后台接码入库流水线' },
            { time: '16:00:02', msg: '成功解析并入库 2 个协议号' },
          ],
          pool: MOCK_ACCOUNTS.data,
        },
      }),
    })
  })

  await page.route(/.*\/api\/telegram\/botfather\/accounts\/\d+\/check$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          account: MOCK_ACCOUNTS.data[0],
          user_info: { id: 1001, first_name: 'Node', username: 'node_user' },
          bots_found: 5,
          bots: [],
        },
      }),
    })
  })

  await page.route(/.*\/api\/telegram\/botfather\/accounts\/\d+\/detail.*/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          account: {
            ...MOCK_ACCOUNTS.data[0],
            dc_id: 5,
            dc_name: 'DC5 亚太 (Singapore)',
            keepalive_ping_ms: 118,
            first_name: 'TestUser',
            username: 'test_user',
          },
          metadata: {
            dc_id: 5,
            dc_name: 'DC5 亚太 (Singapore)',
            dc_region: '亚太',
            dc_ip: '91.108.56.165',
            dc_port: 443,
            tg_user_id: 10001,
            username: 'test_user',
            first_name: 'TestUser',
            api_id: 2040,
            test_mode: false,
            is_bot: false,
            auth_key_len: 256,
            auth_key_fingerprint: 'a1b2c3d4e5f6',
            code_url: 'https://miha.uk/tgapi/xxx',
            last_keepalive_at: '2026-09-26 16:00:00',
            keepalive_ping_ms: 118,
            last_error: '',
          },
          sessions: {
            telethon_session_string: '1BVtsOK0BAAEFAAAAAAAA...',
            pyrogram_session_string: 'AQAAAAAA...',
          },
          user_info: { id: 10001, first_name: 'TestUser', username: 'test_user' },
          bots: [{ username: 'qianlong520f001_bot' }],
        },
      }),
    })
  })

  await page.route(/.*\/api\/telegram\/botfather\/accounts\/\d+\/keepalive$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          success: true,
          account_id: 1,
          phone: '+16813086196',
          ping_ms: 108,
          status: 'active',
        },
      }),
    })
  })

  await page.route('**/api/telegram/botfather/accounts/keepalive', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total: 2,
          success_count: 2,
          failed_count: 0,
          avg_ping_ms: 110,
          results: [],
          pool: MOCK_ACCOUNTS.data,
        },
      }),
    })
  })

  await page.route(/.*\/api\/telegram\/botfather\/accounts\/\d+\/fetch-api$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          api_id: 29998888,
          api_hash: '1234567890abcdef1234567890abcdef',
          region: 'US',
          proxy_used: '198.51.100.10:7150',
          detail: {
            account: {
              id: 1,
              phone: '+16813086196',
              region: 'US',
              session_type: 'pyrogram_string',
              has_code_url: true,
              masked_code_url: 'https://miha.uk/***',
              bot_count: 5,
              max_bots: 20,
              remaining_quota: 15,
              status: 'active',
              dc_id: 1,
              dc_name: 'DC1',
              api_id: 29998888,
              has_api_hash: true,
              masked_api_hash: '1234****cdef',
              last_used_at: '2026-09-26 15:00:00',
              remark: '主力1号',
              created_at: '2026-09-26 10:00:00',
            },
            metadata: {
              dc_id: 1,
              dc_name: 'DC1',
              dc_region: '北美 / 迈阿密',
              region: 'US',
              api_id: 29998888,
              api_hash: '1234567890abcdef1234567890abcdef',
              has_api_hash: true,
            },
            sessions: {
              telethon_session_string: '1BVtsOK0BAAEFAAAAAAAA...',
              pyrogram_session_string: 'AQAAAAAA...',
            },
          },
        },
      }),
    })
  })

  await page.route('**/api/telegram/botfather/proxy-config', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          proxy_api_url: 'https://proxy.example.com/api?region=US&num=1',
          default_url: 'https://proxy.example.com/api?region=US&num=1',
        },
      }),
    })
  })

  await page.route('**/api/telegram/botfather/accounts/fetch-api-batch', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          total: 2,
          succeeded: 2,
          failed: 0,
          results: [
            { account_id: 1, phone: '+16813086196', region: 'US', proxy_used: '198.51.100.10:7150', api_id: 29998888, success: true },
            { account_id: 2, phone: '+18048484620', region: 'US', proxy_used: '198.51.100.10:7150', api_id: 29998889, success: true },
          ],
        },
      }),
    })
  })

  await page.route('**/api/telegram/botfather/keepalive/config', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          running: true,
          enabled: true,
          interval_hours: 12,
          last_run_at: '2026-09-26 16:00:00',
          last_summary: {
            run_at: '2026-09-26 16:00:00',
            success_count: 2,
            failed_count: 0,
            avg_ping_ms: 110,
          },
        },
      }),
    })
  })

  await page.route('**/api/telegram/botfather/tasks/start', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_TASK_STATUS),
    })
  })

  await page.route('**/api/telegram/bots/test-load', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_LOAD_TEST),
    })
  })

  await page.route('**/api/telegram/bots/benchmark-all', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_CLUSTER_BENCHMARK),
    })
  })

  await page.route(/.*\/api\/telegram\/bots\/\d+\/benchmark$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SINGLE_BENCHMARK),
    })
  })

  await page.route('**/api/telegram/benchmark/stream-and-download', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_STREAM_BENCHMARK),
    })
  })
}

test.describe('Admin Bots Cluster Management View', () => {
  test('renders header, stat cards, pipeline entry button, and 10 bot nodes correctly', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/bots')

    // 验证页面主标题与药丸徽标
    await expect(page.locator('.bots-title')).toHaveText('机器人集群管理中心')
    await expect(page.locator('.bots-badge')).toHaveText('Bot Cluster & Benchmark')

    // 验证顶部 4 大指标卡
    await expect(page.locator('.stat-card').first()).toContainText('10 节点')
    await expect(page.locator('.stat-card').nth(1)).toContainText('6 免加频道')
    await expect(page.locator('.stat-card').nth(2)).toContainText('68.5')
    await expect(page.locator('.stat-card').nth(3)).toContainText('@jiuyue1314520')

    // 验证指向独立流水线页面的自动铸机按钮
    const pipelineBtn = page.locator('.pipeline-btn')
    await expect(pipelineBtn).toBeVisible()
    await expect(pipelineBtn).toContainText('自动铸机流水线')

    // 验证 DC 动态分区亲和矩阵
    await expect(page.locator('.dc-partition-card')).toBeVisible()
    await expect(page.locator('.dc-matrix-grid .dc-part-item')).toHaveCount(5)

    // 验证全部 10 个机器人节点卡片渲染
    await expect(page.locator('.bot-node-card')).toHaveCount(10)
    await expect(page.locator('.bot-node-card').first()).toContainText('@jiuyuetanzhen_bot')
    await expect(page.locator('.bot-node-card').first()).toContainText('核心主控保护')

    // 验证免加频道节点徽标
    const noJoinCards = page.locator('.badge-no_join_resolved')
    await expect(noJoinCards.first()).toHaveText('免加频道分流就绪')
  })

  test('filters nodes by capability pill and search query', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/bots')

    // 点击“免加频道就绪”筛选胶囊
    await page.locator('.filter-pill', { hasText: '免加频道就绪' }).click()
    await expect(page.locator('.bot-node-card')).toHaveCount(6)

    // 点击“管理员节点”筛选胶囊
    await page.locator('.filter-pill', { hasText: '管理员节点' }).click()
    await expect(page.locator('.bot-node-card')).toHaveCount(4)

    // 点击“全部节点”并搜索
    await page.locator('.filter-pill', { hasText: '全部节点' }).click()
    await page.locator('.node-search-input input').fill('0952e5')
    await expect(page.locator('.bot-node-card')).toHaveCount(1)
    await expect(page.locator('.bot-node-card')).toContainText('mistrelay_node_0952e5_bot')
  })

  test('runs load test and displays distribution report', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/bots')

    // 验证并发压测报告卡片已渲染
    const reportCard = page.locator('.load-test-card')
    await expect(reportCard).toBeVisible()
    await expect(reportCard).toContainText('100 次并发分流调度压测')
    await expect(reportCard).toContainText('均衡度 100.0%')

    // 验证 10 个节点分流占比柱
    await expect(page.locator('.dist-node-item')).toHaveCount(10)
  })

  test('executes benchmark and displays cluster speed report and node speed tags', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/bots')

    // 验证全集群测速与质量报告卡片渲染
    const benchmarkCard = page.locator('.cluster-benchmark-card')
    await expect(benchmarkCard).toBeVisible()
    await expect(benchmarkCard).toContainText('全集群测速与质量报告')
    await expect(benchmarkCard).toContainText('平均响应延迟 68.5ms')

    // 验证 4 大 KPI 标牌
    await expect(benchmarkCard.locator('.bench-kpi-item').nth(0)).toContainText('68.5 ms')
    await expect(benchmarkCard.locator('.bench-kpi-item').nth(1)).toContainText('jiuyuetanzhen_bot')
    await expect(benchmarkCard.locator('.bench-kpi-item').nth(2)).toContainText('18.5 MB/s')
    await expect(benchmarkCard.locator('.bench-kpi-item').nth(3)).toContainText('100%')

    // 验证每个节点卡片上的延迟和流速徽标
    const firstNodeCard = page.locator('.bot-node-card').first()
    await expect(firstNodeCard.locator('.node-ping-badge')).toHaveText('45.2ms')
    await expect(firstNodeCard.locator('.node-speed-badge')).toContainText('MB/s')

    // 验证单节点独立测速按钮
    const benchBtn = firstNodeCard.locator('.card-bench-btn')
    await expect(benchBtn).toBeVisible()
    await benchBtn.click()

    // 验证测速后依然呈现延迟标签
    await expect(firstNodeCard.locator('.node-ping-badge')).toBeVisible()
  })

  test('executes single-connection playback and download benchmark and displays dual dashboard', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/bots')

    // 验证单连接测速工作台已渲染
    const streamCard = page.locator('.stream-benchmark-card')
    await expect(streamCard).toBeVisible()
    await expect(streamCard).toContainText('单连接流播播放与下载测速')
    await expect(streamCard).toContainText('Single-Stream Benchmark')

    // 验证左侧单连接流播播放卡片
    const playbackCard = page.locator('.playback-subcard')
    await expect(playbackCard).toBeVisible()
    await expect(playbackCard).toContainText('单连接流播播放体验')
    await expect(playbackCard).toContainText('3.25')
    await expect(playbackCard).toContainText('26')
    await expect(playbackCard).toContainText('128.5 ms')
    await expect(playbackCard).toContainText('3.25x 实时')
    await expect(playbackCard).toContainText('无卡顿风险')

    // 验证右侧单连接满速下载卡片
    const downloadCard = page.locator('.download-subcard')
    await expect(downloadCard).toBeVisible()
    await expect(downloadCard).toContainText('单连接满速下载表现')
    await expect(downloadCard).toContainText('3.85')
    await expect(downloadCard).toContainText('4.52')
    await expect(downloadCard).toContainText('95.8%')
    await expect(downloadCard).toContainText('高速畅享')

    // 验证分片时序条带
    await expect(page.locator('.chunk-sample-item')).toHaveCount(4)
    await expect(page.locator('.chunk-sample-item').first()).toContainText('分片 #1')

    // 验证综合诊断横幅
    await expect(page.locator('.bench-diagnosis-bar')).toContainText('单连接播放码率 26.0 Mbps')

    // 验证样本大小选项包含 10 MB, 100 MB, 1 GB
    const sampleGroup = page.locator('.sample-size-group')
    await expect(sampleGroup).toBeVisible()
    await expect(sampleGroup).toContainText('10 MB')
    await expect(sampleGroup).toContainText('100 MB')
    await expect(sampleGroup).toContainText('1 GB')

    // 切换至 100 MB 并重新测试
    await sampleGroup.locator('.el-radio-button', { hasText: '100 MB' }).click()
    const startStreamBtn = page.locator('.start-stream-bench-btn')
    await startStreamBtn.click()
    await expect(playbackCard).toBeVisible()

    // 切换至 1 GB 并启动测速
    await sampleGroup.locator('.el-radio-button', { hasText: '1 GB' }).click()
    await startStreamBtn.click()
    await expect(playbackCard).toBeVisible()

    // 点击“单流”独立节点测速按钮
    const firstNodeStreamBtn = page.locator('.bot-node-card').first().locator('.card-stream-bench-btn')
    await expect(firstNodeStreamBtn).toBeVisible()
    await firstNodeStreamBtn.click()
    await expect(playbackCard).toBeVisible()
  })

  test('supports botfather dedicated page with protocol account pool, relay vs single mode, and batch import modal', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/botfather')

    // 验证独立流水线页面标题与徽标
    await expect(page.locator('.bots-title')).toHaveText('@BotFather 自动化铸造与扩容流水线')
    await expect(page.locator('.bots-badge')).toHaveText('BotFather Auto-Minting Pipeline')

    // 验证顶部指标卡
    await expect(page.locator('.stat-card').first()).toContainText('2 个账号')
    await expect(page.locator('.stat-card').nth(3)).toContainText('10 节点')

    // 1. 验证协议号资产池卡片展示
    const poolCard = page.locator('.account-pool-card')
    await expect(poolCard).toBeVisible()
    await expect(poolCard).toContainText('Telegram 协议号资产池')
    await expect(poolCard).toContainText('纳管 2 个账号')
    await expect(page.locator('.account-item-card')).toHaveCount(2)
    await expect(page.locator('.account-item-card').first()).toContainText('5/20')
    await expect(page.locator('.account-item-card').nth(1)).toContainText('达20个上限')

    // 2. 验证双模切换选项卡 (多号接力 vs 单号精准)
    const relayTab = page.locator('.strategy-tab-relay')
    const singleTab = page.locator('.strategy-tab-single')
    await expect(relayTab).toHaveClass(/active/)
    await expect(page.locator('.strategy-desc-banner')).toContainText('多号跨账号接力策略')

    // 切换到单号精准模式
    await singleTab.click()
    await expect(singleTab).toHaveClass(/active/)
    await expect(page.locator('.strategy-desc-banner')).toContainText('单号精准独立铸造')
    await expect(page.locator('.single-account-select')).toBeVisible()

    // 切回多号接力，再通过资产池卡片上的“单号铸造”按钮一键切入单号模式
    await relayTab.click()
    await expect(relayTab).toHaveClass(/active/)
    await page.locator('.single-mint-quick-btn').first().click()
    await expect(singleTab).toHaveClass(/active/)

    // 3. 验证批量导入协议号弹窗
    await page.locator('.open-batch-import-btn').first().click()
    const importDialog = page.locator('.el-dialog').filter({ hasText: '批量导入 Telegram 协议号' })
    await expect(importDialog).toBeVisible()

    const textarea = importDialog.locator('.batch-import-textarea textarea')
    await textarea.fill('+16813086196|https://miha.uk/tgapi/111/GetHTML\n+18048484620|https://568.5689889.uk/222/GetHTML')
    await importDialog.locator('.confirm-batch-import-btn').click()
    await expect(importDialog.locator('.import-result-box')).toContainText('成功导入 2 个')

    // 4. 验证从资产池中移除协议号（确认删除后卡片彻底消失）
    await page.keyboard.press('Escape')
    const secondCard = page.locator('.account-item-card').nth(1)
    await expect(secondCard).toContainText('+18048484620')
    await secondCard.locator('.delete-account-btn').click()
    const confirmBtn = page.locator('.el-message-box__btns .el-button--primary')
    await confirmBtn.click()
    await expect(page.locator('.account-item-card')).toHaveCount(1)
    await expect(page.locator('.account-item-card').first()).toContainText('+16813086196')
  })

  test('adapts seamlessly to 768px mobile viewport without horizontal overflow', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.goto('/bots')

    await expect(page.locator('.bots-title')).toBeVisible()

    // 验证页面无横向溢出
    const hasHorizontalScroll = await page.evaluate(() => {
      return document.documentElement.scrollWidth > window.innerWidth
    })
    expect(hasHorizontalScroll).toBe(false)

    // 验证独立流水线页面 /botfather 在 768px 移动端视口无横向溢出
    await page.goto('/botfather')
    await expect(page.locator('.bots-title')).toBeVisible()
    const hasBfHorizontalScroll = await page.evaluate(() => {
      return document.documentElement.scrollWidth > window.innerWidth
    })
    expect(hasBfHorizontalScroll).toBe(false)
  })

  test('handles 50+ bots cluster gracefully without layout distortion, showing balanced equal widths and popover chips', async ({ page }) => {
    // 构造包含 55 个节点与高密度亲和分区的极限模拟状态
    const fiftyFiveBots = Array.from({ length: 55 }, (_, i) => ({
      index: i,
      username: `mistrelay_node_${i}_bot`,
      mode: i === 0 ? 'primary_admin' : 'no_join_resolved',
      home_dc: i === 0 ? 5 : (i === 10 ? 4 : 1),
      warm_dcs: [1, 4, 5],
      can_read: true,
      can_write: i === 0,
    }))
    const mockDcPartitions = {
      '1': {
        dc_id: 1,
        label: 'DC1 (美西 / 迈阿密)',
        home_bots: Array.from({ length: 49 }, (_, i) => i + 1), // 49 个原生节点
        warm_bots: Array.from({ length: 55 }, (_, i) => i),     // 55 个热备会话
        files_count: 4,
        requests_count: 50,
      },
      '2': {
        dc_id: 2,
        label: 'DC2 (欧洲 / 阿姆斯特丹)',
        home_bots: [],
        warm_bots: [],
        files_count: 0,
        requests_count: 0,
      },
      '3': {
        dc_id: 3,
        label: 'DC3 (美东 / 迈阿密)',
        home_bots: [],
        warm_bots: [],
        files_count: 0,
        requests_count: 0,
      },
      '4': {
        dc_id: 4,
        label: 'DC4 (欧洲 / 阿姆斯特丹)',
        home_bots: [],
        warm_bots: Array.from({ length: 55 }, (_, i) => i), // 55 个热备会话
        files_count: 3,
        requests_count: 30,
      },
      '5': {
        dc_id: 5,
        label: 'DC5 (亚太 / 新加坡)',
        home_bots: [0],
        warm_bots: Array.from({ length: 55 }, (_, i) => i),
        files_count: 10,
        requests_count: 100,
      },
    }

    await setupBotsPageMocks(page)
    await page.route('**/api/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK_STATUS,
          bot_details: fiftyFiveBots,
          dc_partitions: mockDcPartitions,
        }),
      })
    })

    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/bots')

    // 验证矩阵卡片与 5 个 DC 分区卡片正常渲染
    const matrixGrid = page.locator('.dc-matrix-grid')
    await expect(matrixGrid).toBeVisible()
    const partItems = matrixGrid.locator('.dc-part-item')
    await expect(partItems).toHaveCount(5)

    // 验证 DC1 ~ DC5 每一项卡片均在可视范围内，且宽度完全均分（误差 <= 2px）
    const itemWidths: number[] = []
    for (let i = 0; i < 5; i++) {
      const box = await partItems.nth(i).boundingBox()
      expect(box).not.toBeNull()
      if (box) {
        expect(box.width).toBeGreaterThan(150)
        itemWidths.push(box.width)
      }
    }
    const maxWidth = Math.max(...itemWidths)
    const minWidth = Math.min(...itemWidths)
    expect(maxWidth - minWidth).toBeLessThanOrEqual(2)

    // 验证各指标标签正常显示且未折行
    await expect(partItems.nth(0).locator('.dc-m-lbl').first()).toHaveText('网盘文件')
    await expect(partItems.nth(0).locator('.dc-m-lbl').nth(1)).toHaveText('原生Bot')
    await expect(partItems.nth(0).locator('.dc-m-lbl').nth(2)).toHaveText('热备就绪')

    // 验证 DC1 预览胶囊显示前 3 个编号与 +46 更多徽标
    const dc1Preview = partItems.nth(0).locator('.dc-bot-preview-pill')
    await expect(dc1Preview).toBeVisible()
    await expect(dc1Preview).toContainText('原生:')
    await expect(dc1Preview).toContainText('#1, #2, #3')
    await expect(dc1Preview.locator('.dc-more-badge')).toHaveText('+46')

    // 验证 DC4（无原生但有 55 个热备）显示前 3 个热备编号与 +52 更多徽标
    const dc4Preview = partItems.nth(3).locator('.dc-bot-preview-pill')
    await expect(dc4Preview).toBeVisible()
    await expect(dc4Preview).toContainText('热备:')
    await expect(dc4Preview).toContainText('#0, #1, #2')
    await expect(dc4Preview.locator('.dc-more-badge')).toHaveText('+52')

    // 验证 DC2（完全空闲）显示按需跨区拉取
    await expect(partItems.nth(1).locator('.dc-part-bots')).toContainText('按需跨区拉取')

    // 悬停 DC1 预览胶囊，验证 Popover 浮层弹出且同时包含原生与热备节点
    await dc1Preview.hover()
    const popover = page.locator('.dc-popover-card:visible')
    await expect(popover).toBeVisible()
    await expect(popover).toContainText('调度亲和明细')
    await expect(popover).toContainText('原生节点 (49 个)')
    await expect(popover).toContainText('热备就绪 (55 个)')
    await expect(popover.locator('.chip-purple')).toHaveCount(49)
    await expect(popover.locator('.chip-emerald')).toHaveCount(55)

    // 验证 1440px 视口无横向溢出
    const hasHorizontalScroll = await page.evaluate(() => {
      return document.documentElement.scrollWidth > window.innerWidth
    })
    expect(hasHorizontalScroll).toBe(false)
  })

  test('supports protocol account detail modal, telethon session export, and keepalive inspection', async ({ page }) => {
    await setupBotsPageMocks(page)
    await page.goto('/botfather')

    // 验证“一键全量保活”按钮
    const keepaliveAllBtn = page.locator('.header-btn', { hasText: '一键全量保活' })
    await expect(keepaliveAllBtn).toBeVisible()
    await keepaliveAllBtn.click()

    // 验证“导出 Telethon”按钮与弹窗
    const exportBtn = page.locator('.header-btn', { hasText: '导出 Telethon' })
    await expect(exportBtn).toBeVisible()
    await exportBtn.click()
    const exportDialog = page.locator('.el-dialog:visible', { hasText: '批量导出 Telethon' })
    await expect(exportDialog).toBeVisible()
    await exportDialog.locator('.el-button', { hasText: '关闭' }).click()

    // 验证协议号卡片上的“详情”按钮打开详情与 Session 凭证中心
    const firstAccCard = page.locator('.account-item-card').first()
    const detailBtn = firstAccCard.locator('.detail-account-btn')
    await expect(detailBtn).toBeVisible()
    await detailBtn.click()

    const detailDialog = page.locator('.detail-dialog:visible')
    await expect(detailDialog).toBeVisible()
    await expect(detailDialog).toContainText('Telethon 1.x StringSession')
    await expect(detailDialog).toContainText('Pyrogram 2.x Session String')
    await expect(detailDialog).toContainText('一键复制 Telethon Session')
    await expect(detailDialog).toContainText('一键复制 Pyrogram Session')
    await expect(detailDialog).toContainText('数据中心 / 节点')
    await expect(detailDialog).toContainText('密钥指纹')
    await expect(detailDialog).toContainText('Telegram 开发者 API 凭证')
    await expect(detailDialog).toContainText('App api_id')
    await expect(detailDialog).toContainText('App api_hash')
    await expect(detailDialog).toContainText('从 my.telegram.org 自动提取')

    // 关闭详情弹窗
    await detailDialog.locator('.el-button', { hasText: '关闭' }).click()

    // 验证“批量提取 API”按钮与模态框
    const batchFetchApiBtn = page.locator('.header-btn', { hasText: '批量提取 API' })
    await expect(batchFetchApiBtn).toBeVisible()
    await batchFetchApiBtn.click()

    const batchApiDialog = page.locator('.el-dialog:visible', { hasText: '批量提取 Telegram 开发者 API' })
    await expect(batchApiDialog).toBeVisible()
    await expect(batchApiDialog).toContainText('家宽住宅代理提取 API 链接')
    await expect(batchApiDialog.locator('input').first()).toHaveValue(/proxy/)
    await batchApiDialog.locator('.el-button--primary', { hasText: '开始批量提取' }).click()
    await expect(batchApiDialog).toContainText('提取执行结果明细')
    await batchApiDialog.locator('.el-button', { hasText: '关闭' }).click()

    // 验证单个协议号“保活”按钮
    const singleKeepaliveBtn = firstAccCard.locator('.keepalive-account-btn')
    await expect(singleKeepaliveBtn).toBeVisible()
    await singleKeepaliveBtn.click()

    // 验证协议号卡片布局严谨无横向溢出
    const cardBox = await firstAccCard.boundingBox()
    expect(cardBox).not.toBeNull()
    if (cardBox) {
      expect(cardBox.width).toBeGreaterThanOrEqual(300)
      const btnGroup = firstAccCard.locator('.acc-card-actions')
      const btnGroupBox = await btnGroup.boundingBox()
      expect(btnGroupBox).not.toBeNull()
      if (btnGroupBox) {
        expect(btnGroupBox.x + btnGroupBox.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 1)
      }
      const deleteBtn = firstAccCard.locator('.delete-account-btn')
      const deleteBtnBox = await deleteBtn.boundingBox()
      expect(deleteBtnBox).not.toBeNull()
      if (deleteBtnBox) {
        expect(deleteBtnBox.x + deleteBtnBox.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 1)
      }
    }
  })
})
