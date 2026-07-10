interface PcNotificationOptions {
  key: string
  title: string
  body: string
  cooldownMs?: number
}

const lastNotificationAt = new Map<string, number>()
const DEFAULT_COOLDOWN_MS = 15000

async function requestNotificationPermission(): Promise<boolean> {
  if (!('Notification' in window)) return false
  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') return false
  return (await Notification.requestPermission()) === 'granted'
}

export async function notifyPc(options: PcNotificationOptions): Promise<void> {
  const cooldownMs = options.cooldownMs ?? DEFAULT_COOLDOWN_MS
  const now = Date.now()
  const lastShownAt = lastNotificationAt.get(options.key) || 0
  if (now - lastShownAt < cooldownMs) return

  lastNotificationAt.set(options.key, now)

  try {
    if (await requestNotificationPermission()) {
      new Notification(options.title, { body: options.body })
    }
  } catch {
    // Notification failures should never break the user action that triggered them.
  }
}
