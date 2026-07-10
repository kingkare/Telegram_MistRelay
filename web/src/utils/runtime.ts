const SERVER_BASE_URL_KEY = 'mistrelay.serverBaseUrl'
const TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'mistrelay.refreshToken'

declare global {
  interface Window {
    __TAURI__?: unknown
    __TAURI_INTERNALS__?: unknown
  }
}

function getHostnameForProtocolDefault(value: string): string {
  try {
    return new URL(`http://${value}`).hostname.toLowerCase()
  } catch {
    return ''
  }
}

function shouldDefaultToHttp(value: string): boolean {
  const hostname = getHostnameForProtocolDefault(value)
  if (!hostname) return false

  if (
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname === '0.0.0.0' ||
    hostname === '::1' ||
    hostname === 'host.docker.internal' ||
    hostname.endsWith('.local')
  ) {
    return true
  }

  const octets = hostname.split('.').map(part => Number(part))
  if (octets.length !== 4 || octets.some(part => !Number.isInteger(part) || part < 0 || part > 255)) {
    return false
  }

  const [first, second] = octets
  return (
    first === 10 ||
    first === 127 ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168) ||
    (first === 169 && second === 254)
  )
}

export function normalizeServerBaseUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''

  const withProtocol = /^https?:\/\//i.test(trimmed) || trimmed.startsWith('/')
    ? trimmed
    : `${shouldDefaultToHttp(trimmed) ? 'http' : 'https'}://${trimmed}`

  return withProtocol.replace(/\/+$/, '')
}

export function shouldUseHashHistory(): boolean {
  return import.meta.env.VITE_USE_HASH_ROUTER === 'true'
}

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && (
    Boolean(window.__TAURI_INTERNALS__) ||
    Boolean(window.__TAURI__)
  )
}

export function getDefaultRoutePath(): string {
  return isTauriRuntime() ? '/pc/drive' : '/dashboard'
}

function getAppBasePath(): string {
  const base = (import.meta.env.BASE_URL || '/').trim()
  if (!base || base === '/') return ''
  return `/${base.replace(/^\/+|\/+$/g, '')}`
}

function normalizePathname(pathname: string): string {
  const normalized = pathname.replace(/\/+$/, '')
  return normalized || '/'
}

export function getDefaultServerBaseUrl(): string {
  return normalizeServerBaseUrl(import.meta.env.VITE_SERVER_BASE_URL || '')
}

export function getServerBaseUrl(): string {
  const stored = localStorage.getItem(SERVER_BASE_URL_KEY)
  return normalizeServerBaseUrl(stored || getDefaultServerBaseUrl())
}

export function setServerBaseUrl(value: string): string {
  const normalized = normalizeServerBaseUrl(value)

  if (normalized) {
    localStorage.setItem(SERVER_BASE_URL_KEY, normalized)
  } else {
    localStorage.removeItem(SERVER_BASE_URL_KEY)
  }

  return normalized
}

export function isValidServerBaseUrl(value: string): boolean {
  const normalized = normalizeServerBaseUrl(value)

  if (!normalized) {
    return true
  }

  try {
    new URL(normalized, window.location.origin)
    return true
  } catch {
    return false
  }
}

export function getApiBaseUrl(): string {
  const serverBaseUrl = getServerBaseUrl()
  return serverBaseUrl ? `${serverBaseUrl}/api` : '/api'
}

export function resolveServerUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const serverBaseUrl = getServerBaseUrl()
  return serverBaseUrl ? `${serverBaseUrl}${normalizedPath}` : normalizedPath
}

export function toAbsoluteServerUrl(path: string): string {
  return new URL(resolveServerUrl(path), window.location.origin).toString()
}

export function getAuthToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAuthToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    clearAuthToken()
  }
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_TOKEN_KEY) || ''
}

export function setRefreshToken(token: string): void {
  if (token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, token)
  } else {
    clearRefreshToken()
  }
}

export function clearRefreshToken(): void {
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function clearAuthTokens(): void {
  clearAuthToken()
  clearRefreshToken()
}

export function buildAuthorizedApiUrl(
  path: string,
  params: Record<string, string | number | boolean | null | undefined> = {},
): string {
  const url = new URL(toAbsoluteServerUrl(path))
  const token = getAuthToken()

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    url.searchParams.set(key, String(value))
  })

  if (token) {
    url.searchParams.set('token', token)
  }

  return url.toString()
}

export function buildAuthorizedStreamUrl(streamUrl: string): string {
  if (!streamUrl) return ''

  const absoluteUrl = /^https?:\/\//i.test(streamUrl)
    ? streamUrl
    : toAbsoluteServerUrl(streamUrl)
  const url = new URL(absoluteUrl, window.location.origin)
  const token = getAuthToken()

  if (token) {
    url.searchParams.set('token', token)
  }

  return url.toString()
}

export function getLoginRouteUrl(): string {
  const basePath = getAppBasePath()
  const loginPath = isTauriRuntime() ? '/pc/login' : '/login'
  if (shouldUseHashHistory()) {
    return `${basePath}/#${loginPath}`
  }
  return `${basePath}${loginPath}`
}

export function isCurrentLoginRoute(): boolean {
  if (
    window.location.hash.startsWith('#/login') ||
    window.location.hash.startsWith('#/pc/login')
  ) {
    return true
  }

  const basePath = getAppBasePath()
  const pathname = normalizePathname(window.location.pathname)
  return (
    pathname === normalizePathname(`${basePath}/login`) ||
    pathname === normalizePathname(`${basePath}/pc/login`)
  )
}

export function redirectToLogin(): void {
  window.location.replace(getLoginRouteUrl())
}
