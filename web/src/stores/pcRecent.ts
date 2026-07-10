import { defineStore } from 'pinia'
import type { TelegramDriveItem } from '@/api'
import { getServerBaseUrl } from '@/utils/runtime'

export type PcRecentAction = 'preview' | 'download'

export interface PcRecentRecord {
  id: string
  serverBaseUrl: string
  item: TelegramDriveItem
  action: PcRecentAction
  accessedAt: string
}

interface PcRecentState {
  records: PcRecentRecord[]
}

const RECENT_STORAGE_KEY = 'mistrelay.pc.recentByServer'
const MAX_RECENT_RECORDS = 50

function getCurrentServerKey(): string {
  return getServerBaseUrl() || window.location.origin
}

function getItemKey(item: TelegramDriveItem): string {
  return item.entry_type === 'folder'
    ? `folder:${item.media_group_id}`
    : `file:${item.file_unique_id}`
}

function loadAllRecent(): Record<string, PcRecentRecord[]> {
  try {
    return JSON.parse(localStorage.getItem(RECENT_STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}

function saveAllRecent(value: Record<string, PcRecentRecord[]>) {
  localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(value))
}

function loadCurrentRecent(): PcRecentRecord[] {
  const allRecent = loadAllRecent()
  return allRecent[getCurrentServerKey()] || []
}

export const usePcRecentStore = defineStore('pcRecent', {
  state: (): PcRecentState => ({
    records: loadCurrentRecent(),
  }),
  actions: {
    reload() {
      this.records = loadCurrentRecent()
    },

    addRecent(item: TelegramDriveItem, action: PcRecentAction) {
      const serverBaseUrl = getCurrentServerKey()
      const allRecent = loadAllRecent()
      const id = getItemKey(item)
      const existing = allRecent[serverBaseUrl] || []
      const nextRecord: PcRecentRecord = {
        id,
        serverBaseUrl,
        item,
        action,
        accessedAt: new Date().toISOString(),
      }
      const nextRecords = [
        nextRecord,
        ...existing.filter(record => record.id !== id),
      ].slice(0, MAX_RECENT_RECORDS)

      allRecent[serverBaseUrl] = nextRecords
      saveAllRecent(allRecent)
      this.records = nextRecords
    },

    clearCurrentServer() {
      const serverBaseUrl = getCurrentServerKey()
      const allRecent = loadAllRecent()
      delete allRecent[serverBaseUrl]
      saveAllRecent(allRecent)
      this.records = []
    },
  },
})
