import { expect, test, type Page } from '@playwright/test'

async function mockContainerPage(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('token', 'admin-container-token')
    window.localStorage.setItem('mistrelay.refreshToken', 'admin-container-refresh')
  })

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: { id: 1, username: 'admin', role: 'admin' },
      }),
    })
  })

  await page.route('**/api/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ready: true, server_status: 'running', version: 'test' }),
    })
  })

  await page.route('**/api/config**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    })
  })

  await page.route('**/api/system/docker/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        in_docker: true,
        container_name: 'mistrelay',
        status: 'running',
        status_source: 'application',
        control_enabled: false,
        control_message: '宿主 Docker 控制未启用，当前状态来自应用自检',
        application_version: 'v2.2.5',
        created: '2026-08-13T10:00:00+00:00',
      }),
    })
  })

  await page.route('**/api/system/docker/logs**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, logs: 'service ready', source: 'application' }),
    })
  })
}

test('container page renders self-check status when Docker control is disabled', async ({ page }) => {
  await mockContainerPage(page)
  await page.goto('/settings?tab=container')

  await expect(page.getByText('Docker容器状态')).toBeVisible()
  await expect(page.getByText('mistrelay', { exact: true })).toBeVisible()
  await expect(page.getByText('running', { exact: true })).toBeVisible()
  await expect(page.getByText('应用自检', { exact: true })).toBeVisible()
  await expect(page.getByText('v2.2.5', { exact: true })).toBeVisible()
  await expect(page.getByText('宿主 Docker 控制未启用，当前状态来自应用自检')).toBeVisible()
  await expect(page.getByRole('button', { name: '重启容器（热重载）' })).toBeDisabled()
  await expect(page.getByText('无法获取容器状态')).toHaveCount(0)
})
