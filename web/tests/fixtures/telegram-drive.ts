import type { TelegramDriveFile, TelegramDriveFolder, TelegramDriveItem } from '../../src/types/api'

const MIME_TYPES = [
  'image/jpeg',
  'video/mp4',
  'audio/mpeg',
  'application/pdf',
  'application/zip',
]

function createFile(index: number): TelegramDriveFile {
  const mimeType = MIME_TYPES[index % MIME_TYPES.length]
  const fileBaseName = `mistrelay_fixture_${String(index).padStart(5, '0')}`

  return {
    entry_type: 'file',
    file_unique_id: `file-${index}`,
    chat_id: 1000,
    message_id: index,
    file_name: `${fileBaseName}.${mimeType.split('/')[1].replace('mpeg', 'mp3')}`,
    download_file_name: `${fileBaseName}.bin`,
    mime_type: mimeType,
    file_size: 1024 * (index + 1),
    message_date: new Date(Date.UTC(2026, 0, 1, 0, index % 60, 0)).toISOString(),
    supports_streaming: mimeType.startsWith('video/'),
    thumbnail_url: `/api/telegram/thumbnail/${index}`,
    stream_url: `/api/telegram/stream/${index}`,
    caption: index % 7 === 0 ? `fixture caption ${index}` : undefined,
  }
}

function createFolder(index: number): TelegramDriveFolder {
  return {
    entry_type: 'folder',
    media_group_id: `group-${index}`,
    item_count: 6,
    file_name: `媒体组 ${String(index).padStart(4, '0')}`,
    total_size: 1024 * 1024 * (index + 1),
    group_mime_types: ['image/jpeg', 'video/mp4'],
    message_date: new Date(Date.UTC(2026, 0, 1, 1, index % 60, 0)).toISOString(),
    thumbnail_url: `/api/telegram/thumbnail/group-${index}`,
  }
}

export function createTelegramDriveFixture(total = 10000): TelegramDriveItem[] {
  return Array.from({ length: total }, (_, index) => (
    index > 0 && index % 25 === 0 ? createFolder(index) : createFile(index)
  ))
}

export const pcDriveViewports = [
  { width: 1100, height: 720, columns: 5 },
  { width: 1366, height: 768, columns: 6 },
  { width: 1920, height: 1080, columns: 8 },
] as const
