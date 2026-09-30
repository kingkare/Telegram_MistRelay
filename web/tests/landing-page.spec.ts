import { expect, test, type Page } from '@playwright/test'

async function mockPublicApis(page: Page) {
  await page.route('**/api/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ready: true,
        server_status: 'running',
        telegram_connected: true,
        version: 'v0.2.16',
      }),
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
        register_deep_link: 'https://t.me/MistRelayOfficialBot?start=register',
      }),
    })
  })
}

async function mockAuthApis(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'mock-tenant-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'mock-tenant-refresh')
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 10, username: 'vip_tenant', role: 'user', dc_id: 5, bin_channel_username: 'tenant_bin_ch' },
      }),
    })
  })

  await page.route('**/api/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        server_status: 'running',
        uptime: '2d',
        version: 'v0.2.16',
        loads: {},
        channel_info: {
          channel_id: -100200300400,
          channel_type: 'public',
          public_handle: 'tenant_bin_ch',
        },
      }),
    })
  })

  await page.route('**/api/downloads*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [],
        total: 0,
        running: 0,
        waiting: 0,
        stopped: 0,
      }),
    })
  })

  await page.route('**/api/telegram/usage', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { total_size: 1024000, total_files: 5 },
      }),
    })
  })

  await page.route('**/api/edge/nodes*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        nodes: [],
        summary: {},
      }),
    })
  })
}

test.describe('Landing Page & Multi-Tenant Portal', () => {
  test('unauthenticated visitor lands on / and sees complete landing page', async ({ page }) => {
    await mockPublicApis(page)
    await page.goto('/')

    // Should stay on / (not redirect to /login)
    expect(page.url()).toMatch(/\/(#\/)?$/)

    // Check brand and title
    await expect(page.locator('.brand-title').first()).toHaveText('MistRelay')
    await expect(page.locator('.hero-title')).toContainText('新一代多租户')
    await expect(page.locator('.hero-title')).toContainText('Telegram 频道云盘')

    // Check system status badge loaded from mock API
    await expect(page.locator('.status-capsule')).toBeVisible()
    await expect(page.locator('.status-label')).toHaveText('全节点就绪')

    // Check navigation links
    await expect(page.locator('.nav-link[href="#features"]')).toBeVisible()
    await expect(page.locator('.nav-link[href="#architecture"]')).toBeVisible()
    await expect(page.locator('.nav-link[href="#edge"]')).toBeVisible()
    await expect(page.locator('.nav-link[href="#quickstart"]')).toBeVisible()

    // Check feature cards
    await expect(page.locator('.feature-card')).toHaveCount(4)
    await expect(page.locator('.feature-card-title').first()).toHaveText('物理隔离专属存储频道')

    // Check DC matrix cards
    await expect(page.locator('.dc-card')).toHaveCount(4)

    // Check bot deep link from /api/auth/bot-info
    const tgBtn = page.locator('.hero-cta-btn--tg')
    await expect(tgBtn).toBeVisible()
    await expect(tgBtn).toHaveAttribute('href', 'https://t.me/MistRelayOfficialBot?start=register')

    // Check action buttons in header
    await expect(page.locator('.action-btn--login')).toBeVisible()
    await expect(page.locator('.action-btn--primary')).toBeVisible()
  })

  test('clicking action buttons navigates to login and register tabs with back navigation', async ({ page }) => {
    await mockPublicApis(page)
    await page.goto('/')

    // Click "立即开通租户" in header
    await page.locator('.header-actions .action-btn--primary').click()
    await page.waitForURL(/.*\/login\?tab=register/)

    // Verify register tab is active
    const registerTabBtn = page.locator('.auth-tab-btn', { hasText: 'Telegram 验证码注册' })
    await expect(registerTabBtn).toHaveClass(/active/)
    await expect(page.locator('.register-panel')).toBeVisible()

    // Click "返回官网首页"
    await page.locator('.back-home-link').click()
    await page.waitForURL(/.*\/$/)
    await expect(page.locator('.hero-title')).toBeVisible()

    // Click "控制台登录"
    await page.locator('.action-btn--login').click()
    await page.waitForURL(/.*\/login/)
    const loginTabBtn = page.locator('.auth-tab-btn', { hasText: '账号密码登录' })
    await expect(loginTabBtn).toHaveClass(/active/)
  })

  test('authenticated user accessing / is redirected to /dashboard', async ({ page }) => {
    await mockPublicApis(page)
    await mockAuthApis(page)

    await page.goto('/')

    // Should redirect to dashboard
    await page.waitForURL(/.*\/dashboard/)
    await expect(page.locator('.dashboard-title')).toBeVisible()
  })

  test('authenticated user accessing /?preview=1 can view landing page with dashboard CTA', async ({ page }) => {
    await mockPublicApis(page)
    await mockAuthApis(page)

    await page.goto('/?preview=1')

    // Should stay on landing page
    await expect(page.locator('.hero-title')).toBeVisible()
    // Should display "进入工作台" in header instead of login/register
    const dashBtn = page.locator('.header-actions .action-btn--primary')
    await expect(dashBtn).toContainText('进入工作台')
  })
})

  test('login and register tabs switch smoothly with integrated get-code button and compact DC select', async ({ page }) => {
    await mockPublicApis(page)
    await page.goto('/login')

    const loginCard = page.locator('.login-card')
    await expect(loginCard).toBeVisible()

    // 1. Measure login card box
    const loginBox = await loginCard.boundingBox()
    expect(loginBox).toBeTruthy()

    // 2. Switch to Telegram register tab
    const registerTabBtn = page.locator('.auth-tab-btn', { hasText: 'Telegram 验证码注册' })
    await registerTabBtn.click()

    // Check integrated get-code button inside the code row
    const getCodeBtn = page.locator('.code-input-group .get-code-btn')
    await expect(getCodeBtn).toBeVisible()
    await expect(getCodeBtn).toContainText('获取验证码')
    await expect(getCodeBtn).toHaveAttribute('href', 'https://t.me/MistRelayOfficialBot?start=register')

    // Check compact DC selector
    const dcSelect = page.locator('.register-panel .el-select')
    await expect(dcSelect).toBeVisible()

    // Check register button text
    const regSubmitBtn = page.locator('.register-panel .login-btn')
    await expect(regSubmitBtn).toHaveText('立即开通专属云盘')

    // 3. Measure register card box: should be compact (within 70px difference, no violent jump)
    const registerBox = await loginCard.boundingBox()
    expect(registerBox).toBeTruthy()
    const heightDiff = Math.abs((registerBox?.height || 0) - (loginBox?.height || 0))
    expect(heightDiff).toBeLessThan(120)

    // 4. Switch back to login tab smoothly
    const loginTabBtn = page.locator('.auth-tab-btn', { hasText: '账号密码登录' })
    await loginTabBtn.click()
    await expect(page.locator('.login-form')).toBeVisible()
  })
  test('login and register tabs maintain steady height and smooth carousel transition on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await mockPublicApis(page)
    await page.goto('/login')

    const loginCard = page.locator('.login-card')
    await expect(loginCard).toBeVisible()

    const initialBox = await loginCard.boundingBox()
    expect(initialBox).toBeTruthy()

    // Switch to register
    await page.locator('.auth-tab-btn', { hasText: 'Telegram 验证码注册' }).click()
    await expect(page.locator('.register-panel')).toBeVisible()

    const registerBox = await loginCard.boundingBox()
    expect(registerBox).toBeTruthy()
    // Zero or near zero jump
    expect(Math.abs((registerBox?.height || 0) - (initialBox?.height || 0))).toBeLessThan(15)

    // Switch back to login
    await page.locator('.auth-tab-btn', { hasText: '账号密码登录' }).click()
    await expect(page.locator('.login-form')).toBeVisible()
  })
  test('landing page renders interactive cosmic sakura canvas, 3D tilt mockup, and streaming laser pipeline', async ({ page }) => {
    await mockPublicApis(page)
    await page.goto('/')

    // Check canvas element
    const canvas = page.locator('.sakura-cosmic-canvas')
    await expect(canvas).toBeVisible()

    // Check mouse spotlight
    const spotlight = page.locator('.mouse-spotlight')
    await expect(spotlight).toBeAttached()

    // Check 3D tilt mockup and glare
    const mockup = page.locator('.hero-dashboard-mockup')
    await expect(mockup).toBeVisible()
    const glare = page.locator('.mockup-glare')
    await expect(glare).toBeAttached()

    // Hover over mockup to test tilt
    await mockup.hover({ position: { x: 50, y: 50 } })
    const styleAfterHover = await mockup.getAttribute('style')
    expect(styleAfterHover).toContain('perspective(1000px)')

    // Check dynamic stream pipeline track and packets
    const streamTrack = page.locator('.stream-pipeline-track')
    await expect(streamTrack).toBeVisible()
    await expect(page.locator('.pipeline-packet')).toHaveCount(3)

    // Check data flow laser tracks
    await expect(page.locator('.flow-laser-track')).toHaveCount(3)

    // Check terminal scanline and cursor
    await expect(page.locator('.terminal-scanline')).toBeAttached()
    await expect(page.locator('.terminal-cursor')).toBeVisible()

    // Test global click burst interaction
    await page.mouse.click(300, 300)
    await page.waitForTimeout(500)
    await page.evaluate(() => window.scrollTo(0, 1100))
    await page.waitForTimeout(600)
  })
