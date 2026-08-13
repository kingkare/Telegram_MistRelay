# PC 客户端 TG 频道网盘适配指南

本文面向 PC 客户端开发者，目标是让客户端正确实现 MistRelay 的 TG 频道网盘页面，尤其是“媒体组作为文件夹显示”的行为。

## 1. 总览

TG 频道网盘是当前唯一维护的网盘能力：

- 下载完成后，服务端会把文件上传到 Telegram 频道网盘。
- PC 客户端通过 `/api/telegram/*` 接口浏览、预览、下载、删除频道文件。
- 同一个 `media_group_id` 的多条 Telegram 媒体在根目录必须显示为一个“媒体组文件夹”。
- 进入媒体组文件夹后，才显示组内真实文件。

不要再实现或调用第三方网盘能力：

- 不要调用 `/api/rclone/*`。
- 不要实现 OneDrive / Google Drive / rclone 配置页面；这些旧接口只会返回废弃提示。
- 历史上传记录里的 `onedrive` / `gdrive` 只能作为历史状态展示，不能重试。

## 2. 鉴权与基础 URL

所有 `/api/telegram/*` 接口都需要登录态。

请求头：

```http
Authorization: Bearer <jwt-token>
Content-Type: application/json
```

推荐客户端维护两个基础地址：

```ts
const serverOrigin = 'http://127.0.0.1:8080'
const apiBaseUrl = `${serverOrigin}/api`
```

接口返回的 `stream_url` 是服务端相对路径，例如：

```json
"/12345/movie.mp4?hash=a1b2c3d4"
```

PC 客户端用于预览/下载时应拼接为绝对 URL：

```ts
function resolveServerUrl(path: string): string {
  return new URL(path, serverOrigin).toString()
}
```

流媒体 URL 已包含消息 hash，不要向 URL 追加管理员 JWT：

```ts
function buildStreamUrl(entry: TelegramDriveFile): string {
  return new URL(entry.stream_url!, serverOrigin).toString()
}
```

## 3. 核心数据类型

### 3.1 浏览响应

`GET /api/telegram/browse` 返回：

```ts
type TelegramBrowseResponse = {
  success: boolean
  items: TelegramDriveEntry[]
  total: number
  page: number
  page_size: number
  grouped?: boolean
  media_group_id?: string
  error?: string
}
```

### 3.2 条目联合类型

客户端必须根据 `entry_type` 分支处理。

```ts
type TelegramDriveEntry = TelegramDriveFolder | TelegramDriveFile
```

### 3.3 媒体组文件夹

根目录中，同一 `media_group_id` 只返回一个 `folder` 条目：

```ts
type TelegramDriveFolder = {
  entry_type: 'folder'
  media_group_id: string
  file_unique_id: string
  chat_id: number
  message_id: number
  file_name: string
  mime_type: 'application/x-mistrelay-media-group'
  file_size: number
  total_size: number
  item_count: number
  message_date?: string
  group_mime_types?: string[]
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `entry_type` | 固定为 `folder` |
| `media_group_id` | 文件夹 ID，进入文件夹和删除整个媒体组都使用它 |
| `file_name` | 文件夹显示名，服务端已去掉代表文件的最后一个后缀 |
| `item_count` | 组内文件数量 |
| `total_size` / `file_size` | 组内文件总大小，优先显示 `total_size` |
| `message_date` | 组内最新消息时间，可用于排序/展示 |
| `group_mime_types` | 组内真实文件 MIME 类型集合，仅用于辅助展示 |

重要规则：

- PC 客户端不要再对 `folder.file_name` 做去后缀处理。
- PC 客户端不要用 `file_unique_id` 当文件夹 ID。
- 文件夹的稳定 key 建议使用 `folder:${media_group_id}`。

### 3.4 真实文件

单文件和媒体组内文件都返回 `file` 条目：

```ts
type TelegramDriveFile = {
  entry_type: 'file'
  file_unique_id: string
  chat_id: number
  message_id: number
  file_name?: string
  download_file_name?: string
  mime_type?: string
  file_size?: number
  duration?: number
  width?: number
  height?: number
  caption?: string
  message_date?: string
  media_group_id?: string
  supports_streaming?: boolean
  hash?: string
  stream_url?: string
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `entry_type` | 固定为 `file` |
| `file_unique_id` | 文件唯一 ID，适合作为文件 key |
| `message_id` | 频道消息 ID，删除单文件时使用 |
| `media_group_id` | 如果文件属于媒体组，则会存在；组内删除单文件仍使用 `message_id` |
| `file_name` | 显示用文件名；历史照片/语音等记录可能为空或缺少扩展名 |
| `download_file_name` | 下载保存建议名，服务端会尽量补齐扩展名 |
| `mime_type` | 用于判断图片/视频/音频/文档 |
| `stream_url` | 预览/下载 URL，相对服务端 origin |

## 4. 浏览接口

### 4.1 根目录浏览

请求：

```http
GET /api/telegram/browse?page=1&page_size=50&sort_by=message_date&sort_desc=true
```

不要传 `media_group_id`。

响应示例：

```json
{
  "success": true,
  "items": [
    {
      "entry_type": "folder",
      "media_group_id": "13887700123456",
      "file_unique_id": "AgAD_group_rep",
      "chat_id": -1001234567890,
      "message_id": 456,
      "file_name": "夏日相册",
      "mime_type": "application/x-mistrelay-media-group",
      "file_size": 73400320,
      "total_size": 73400320,
      "item_count": 6,
      "message_date": "2026-04-24T10:20:30"
    },
    {
      "entry_type": "file",
      "file_unique_id": "AgAD_file_1",
      "chat_id": -1001234567890,
      "message_id": 457,
      "file_name": "movie.mp4",
      "download_file_name": "movie.mp4",
      "mime_type": "video/mp4",
      "file_size": 104857600,
      "message_date": "2026-04-24T10:10:00",
      "hash": "a1b2c3",
      "stream_url": "/457/movie.mp4?hash=a1b2c3"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 50,
  "grouped": true
}
```

根目录渲染规则：

- `entry_type = folder`：显示为文件夹，不显示下载按钮，点击进入文件夹。
- `entry_type = file`：显示为普通文件，点击预览/下载。
- `total` 是“文件夹 + 单文件”的数量，不是数据库真实媒体条数。

### 4.2 进入媒体组文件夹

请求：

```http
GET /api/telegram/browse?media_group_id=13887700123456&page=1&page_size=50&sort_by=message_date&sort_desc=true
```

响应示例：

```json
{
  "success": true,
  "items": [
    {
      "entry_type": "file",
      "file_unique_id": "AgAD_group_file_1",
      "chat_id": -1001234567890,
      "message_id": 456,
      "file_name": "夏日相册-01.jpg",
      "download_file_name": "夏日相册-01.jpg",
      "mime_type": "image/jpeg",
      "file_size": 5242880,
      "media_group_id": "13887700123456",
      "message_date": "2026-04-24T10:20:30",
      "hash": "b2c3d4",
      "stream_url": "/456/%E5%A4%8F%E6%97%A5%E7%9B%B8%E5%86%8C-01.jpg?hash=b2c3d4"
    }
  ],
  "total": 6,
  "page": 1,
  "page_size": 50,
  "grouped": false,
  "media_group_id": "13887700123456"
}
```

组内渲染规则：

- 所有条目都当真实文件处理。
- 文件名保留后缀。
- 删除按钮删除单个文件，不删除整个媒体组。
- 返回根目录时，清空客户端状态里的 `media_group_id`。

## 5. 查询参数

`GET /api/telegram/browse` 支持：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `page` | number | `1` | 页码，从 1 开始 |
| `page_size` | number | `50` | 每页数量，服务端最大 `200` |
| `search` | string | 空 | 搜索 `file_name` 或 `caption` |
| `type` | string | 空 | `video` / `image` / `audio` / `document` |
| `sort_by` | string | `message_date` | `message_date` / `file_size` / `file_name` |
| `sort_desc` | boolean | `true` | 除显式 `false` 外均按降序 |
| `media_group_id` | string | 空 | 进入指定媒体组文件夹 |

搜索和筛选规则：

- 根目录搜索时，如果媒体组内任一文件命中，根目录显示该媒体组文件夹。
- 根目录类型筛选时，如果媒体组内任一文件符合类型，根目录显示该媒体组文件夹。
- 进入媒体组后，搜索/筛选只作用于该组内文件。

排序规则：

- `message_date`：媒体组文件夹使用组内最新消息时间。
- `file_size`：媒体组文件夹使用组内总大小。
- `file_name`：媒体组文件夹使用后端返回的文件夹名。

## 6. UI 状态机

PC 客户端建议维护以下状态：

```ts
type DriveState = {
  currentMediaGroupId: string | null
  currentFolderName: string | null
  page: number
  pageSize: number
  search: string
  type: '' | 'video' | 'image' | 'audio' | 'document'
  sortBy: 'message_date' | 'file_size' | 'file_name'
  sortDesc: boolean
}
```

根目录：

```ts
state.currentMediaGroupId = null
state.currentFolderName = null
```

进入文件夹：

```ts
function enterFolder(folder: TelegramDriveFolder) {
  state.currentMediaGroupId = folder.media_group_id
  state.currentFolderName = folder.file_name
  state.page = 1
  loadDriveEntries()
}
```

返回根目录：

```ts
function goRoot() {
  state.currentMediaGroupId = null
  state.currentFolderName = null
  state.page = 1
  loadDriveEntries()
}
```

加载列表：

```ts
async function loadDriveEntries() {
  const params = {
    page: state.page,
    page_size: state.pageSize,
    search: state.search || undefined,
    type: state.type || undefined,
    sort_by: state.sortBy,
    sort_desc: state.sortDesc,
    media_group_id: state.currentMediaGroupId || undefined,
  }

  const res = await api.get<TelegramBrowseResponse>('/telegram/browse', { params })
  if (!res.data.success) throw new Error(res.data.error || '加载 TG 网盘失败')
  return res.data
}
```

## 7. 类型守卫与显示逻辑

```ts
function isFolder(entry: TelegramDriveEntry): entry is TelegramDriveFolder {
  return entry.entry_type === 'folder'
}

function isFile(entry: TelegramDriveEntry): entry is TelegramDriveFile {
  return entry.entry_type === 'file'
}

function getEntryKey(entry: TelegramDriveEntry): string {
  return isFolder(entry)
    ? `folder:${entry.media_group_id}`
    : `file:${entry.file_unique_id}`
}

function getDisplayName(entry: TelegramDriveEntry): string {
  if (isFolder(entry)) return entry.file_name
  return entry.file_name || `telegram_${entry.message_id}`
}

function getDownloadName(entry: TelegramDriveFile): string {
  return entry.download_file_name
    || getNameFromStreamUrl(entry.stream_url)
    || entry.file_name
    || `media_${entry.message_id}.bin`
}

function getNameFromStreamUrl(streamUrl?: string): string {
  if (!streamUrl) return ''
  try {
    const pathname = new URL(streamUrl, serverOrigin).pathname
    const encodedName = pathname.split('/').filter(Boolean).pop()
    return encodedName ? decodeURIComponent(encodedName) : ''
  } catch {
    const encodedName = streamUrl.split('?')[0]?.split('/').filter(Boolean).pop()
    if (!encodedName) return ''
    try {
      return decodeURIComponent(encodedName)
    } catch {
      return encodedName
    }
  }
}

function getDisplaySize(entry: TelegramDriveEntry): number {
  return isFolder(entry)
    ? entry.total_size || entry.file_size || 0
    : entry.file_size || 0
}
```

图标建议：

```ts
function getIcon(entry: TelegramDriveEntry) {
  if (isFolder(entry)) return 'folder'
  if (entry.mime_type?.startsWith('image/')) return 'image'
  if (entry.mime_type?.startsWith('video/')) return 'video'
  if (entry.mime_type?.startsWith('audio/')) return 'audio'
  return 'document'
}
```

## 8. 预览与下载

文件夹：

- 点击：进入文件夹。
- 不显示下载按钮。
- 不使用 `stream_url`。

文件：

- 图片：可以用 `stream_url` 做图片预览。
- 视频：可以用 `stream_url` 给播放器播放。
- 其他文件：可以打开 `stream_url` 下载或交给系统处理。
- 下载保存名优先使用响应头 `Content-Disposition` 的 `filename*` / `filename`；如果下载库拿不到响应头，再使用 `download_file_name`。
- 服务端会尽量在 `download_file_name`、`stream_url` 路径和 `Content-Disposition` 中补齐扩展名；客户端不要再删除最后一个点后缀。

```ts
function openEntry(entry: TelegramDriveEntry) {
  if (isFolder(entry)) {
    enterFolder(entry)
    return
  }

  if (!entry.stream_url) {
    showToast('此文件暂无可用直链')
    return
  }

  const url = resolveServerUrl(entry.stream_url)
  if (entry.mime_type?.startsWith('image/')) openImagePreview(url)
  else if (entry.mime_type?.startsWith('video/')) openVideoPreview(url)
  else openExternal(url)
}
```

保存名优先级：

```ts
function getSaveName(entry: TelegramDriveFile, contentDisposition?: string): string {
  return parseFilenameFromContentDisposition(contentDisposition)
    || entry.download_file_name
    || getNameFromStreamUrl(entry.stream_url)
    || entry.file_name
    || `media_${entry.message_id}.bin`
}
```

`Content-Disposition` 解析要求：

- 优先解析 RFC 5987 形式的 `filename*=UTF-8''...`
- 再解析普通 `filename="..."`
- 解析失败时再走 `download_file_name` 回退
- 不要使用媒体组文件夹的 `file_name` 作为文件保存名

参考实现：

```ts
function parseFilenameFromContentDisposition(value?: string): string {
  if (!value) return ''

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim())
    } catch {
      return utf8Match[1].trim()
    }
  }

  const asciiMatch = value.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1]?.trim() || ''
}
```

后缀规则：

| 场景 | 服务端保存名行为 | 客户端行为 |
| --- | --- | --- |
| `file_name = movie`，MIME 为 `video/mp4` | 返回 `movie.mp4` | 直接使用 |
| `file_name = movie.1080p`，MIME 为 `video/mp4` | 返回 `movie.1080p.mp4` | 不裁剪 |
| `file_name` 为空，MIME 为 `image/jpeg` | 返回 `media_<message_id>.jpg` | 直接使用 |
| 只有 `stream_url` 可用 | 路径最后一段已带扩展名 | 解码路径文件名 |

## 9. 删除规则

### 9.1 删除单个文件

接口：

```http
DELETE /api/telegram/item/{message_id}
```

使用场景：

- 根目录中的 `entry_type = file`。
- 媒体组文件夹内的真实文件。

示例：

```ts
await api.delete(`/telegram/item/${file.message_id}`)
```

### 9.2 删除整个媒体组文件夹

接口：

```http
DELETE /api/telegram/group/{media_group_id}
```

使用场景：

- 根目录中的 `entry_type = folder`。

示例：

```ts
await api.delete(`/telegram/group/${folder.media_group_id}`)
```

### 9.3 清空 TG 网盘

接口：

```http
DELETE /api/telegram/all
```

使用场景：

- 用户明确点击“清空 TG 网盘”。
- 必须二次确认。

### 9.4 删除后刷新

建议：

```ts
async function deleteEntry(entry: TelegramDriveEntry) {
  if (isFolder(entry)) {
    await api.delete(`/telegram/group/${entry.media_group_id}`)
    await loadDriveEntries()
    return
  }

  await api.delete(`/telegram/item/${entry.message_id}`)
  await loadDriveEntries()
}
```

如果当前位于某个媒体组内，且组内最后一个文件被删除，服务端会返回空列表。客户端可以显示“此媒体组暂无文件”，也可以自动返回根目录。Web 端当前选择显示空状态并保留当前位置。

## 10. 容量统计

接口：

```http
GET /api/telegram/usage
```

响应：

```ts
type TelegramUsageResponse = {
  success: boolean
  data?: {
    total_count: number
    total_size: number
    videos: number
    images: number
    audios: number
    documents: number
  }
  error?: string
}
```

说明：

- `total_count` 是真实媒体文件数量，不是根目录“文件夹 + 单文件”的数量。
- `total_size` 是所有真实媒体文件总大小。
- 类型统计也是按真实媒体文件计算。

## 11. 错误处理

常见错误：

| 状态码 | 场景 | 客户端处理 |
| --- | --- | --- |
| `401` | token 缺失或过期 | 清理登录态，跳转登录 |
| `404` | 删除的文件/媒体组不存在 | 提示不存在并刷新列表 |
| `410` | 误调用 `/api/rclone/*` 旧接口 | 停止调用旧接口，切换到 `/api/telegram/*` |
| `500` | 服务端异常 | 显示错误消息，保留当前页面 |

删除接口可能出现频道消息已不存在但数据库记录仍存在的情况。服务端会尽量清理数据库，并在响应中返回 `cleanup_only` 等字段。客户端只需要按 `success` 判断是否刷新列表。

## 12. 禁止事项与常见坑

必须避免：

- 不要把同一 `media_group_id` 的所有文件平铺在根目录。
- 不要点击媒体组文件夹时直接预览代表文件。
- 不要用 `file_unique_id` 作为文件夹 ID；文件夹 ID 是 `media_group_id`。
- 不要对媒体组文件夹名再次去后缀；后端已经处理。
- 不要在组内删除文件时调用 `DELETE /api/telegram/group/{media_group_id}`。
- 不要调用 `/api/rclone/*` 实现网盘浏览、缩略图、下载或删除。
- 不要实现第三方网盘配置入口。

推荐行为：

- 根目录文件夹 key：`folder:${media_group_id}`。
- 文件 key：`file:${file_unique_id}`。
- 文件夹显示大小：`total_size`。
- 文件夹显示数量：`item_count`。
- 进入文件夹后保留搜索/筛选条件或清空条件都可以，但必须保证请求带 `media_group_id`。

## 13. 最小实现清单

PC 客户端实现 TG 网盘至少需要：

- 登录后保存 JWT token。
- 调用 `GET /api/telegram/usage` 显示统计。
- 调用 `GET /api/telegram/browse` 显示根目录。
- 根据 `entry_type` 区分文件夹和文件。
- 点击文件夹时用 `media_group_id` 重新请求列表。
- 点击文件时使用 `stream_url` 预览或下载。
- 删除文件夹调用 `DELETE /api/telegram/group/{media_group_id}`。
- 删除文件调用 `DELETE /api/telegram/item/{message_id}`。
- 清空网盘调用 `DELETE /api/telegram/all` 并做二次确认。
