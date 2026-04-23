# MistRelay 后端 API 文档

本文档基于当前仓库中的 `aiohttp` 后端实现整理，主要来源如下：

- 路由与处理逻辑：`WebStreamer/server/stream_routes.py`
- 鉴权与中间件：`WebStreamer/server/__init__.py`、`auth.py`
- 数据结构来源：`db.py`
- WebSocket 事件：`WebStreamer/server/ws_manager.py`

本文档描述的是“当前实现”，不是理想化规范。若代码与文档冲突，应以代码行为为准。

## 1. 基础信息

### 1.1 Base URL

- HTTP API 基础前缀：`/api`
- 默认部署示例：`http://your-server:8080/api`

示例环境变量：

```bash
export BASE_URL="http://localhost:8080"
export TOKEN="<jwt-token>"
```

### 1.2 鉴权规则

后端只对以 `/api/` 开头的路径启用 JWT 鉴权。以下接口免鉴权：

- `POST /api/auth/login`
- `GET /api/status`
- `GET /api/rclone/thumbnail/serve/{remote}/{filename}`

其余 `/api/*` 接口都需要 token。

传递方式：

- 普通 JSON API：推荐 `Authorization: Bearer <token>`
- 文件下载、浏览器直链、WebSocket：也可以用 `?token=<token>`

JWT 特性：

- 过期时间固定为 24 小时
- JWT 签名密钥在进程启动时随机生成
- 服务重启后，旧 token 会全部失效，需要重新登录

鉴权失败时的统一返回：

```json
{
  "success": false,
  "error": "未登录"
}
```

或：

```json
{
  "success": false,
  "error": "登录已过期，请重新登录"
}
```

状态码均为 `401`。

### 1.3 CORS

服务端对所有请求统一添加 CORS 响应头：

- `Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS`
- `Access-Control-Allow-Headers: Authorization, Content-Type, Accept, Origin, X-Requested-With`
- `Access-Control-Expose-Headers: Content-Disposition, Content-Length`

`OPTIONS` 预检请求直接返回 `204`。

### 1.4 通用响应约定

大多数 JSON 接口使用以下风格：

```json
{
  "success": true,
  "data": {}
}
```

或：

```json
{
  "success": false,
  "error": "错误描述"
}
```

注意：

- 不是所有错误都会映射成 `4xx/5xx`
- Docker/系统管理类接口里，很多运行时错误仍然返回 `200`，并通过 `success: false` 表达失败
- 文件下载、静态文件、缩略图服务、Telegram 流媒体、WebSocket 接口不使用这套 JSON 包装

### 1.5 上传大小限制

`aiohttp` 应用的 `client_max_size` 固定为 `30000000` 字节，约 28.6 MiB。超过该大小的请求体可能在进入业务逻辑前就被拒绝。

## 2. 关键数据结构

本节用于说明多个接口复用的对象结构。后续各接口章节会直接引用这些名称。

### 2.1 `User`

```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "created_at": "2026-04-20T10:00:00Z",
  "updated_at": "2026-04-20T10:00:00Z"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 用户 ID |
| `username` | string | 登录名 |
| `role` | string | 当前实现默认为 `admin` |
| `created_at` | string | ISO8601 时间 |
| `updated_at` | string | ISO8601 时间 |

### 2.2 `ServerStatus`

`GET /api/status` 返回：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `server_status` | string | 当前固定为 `running` |
| `uptime` | string | 可读格式运行时长 |
| `telegram_bot` | string | 主 bot 用户名，失败时可能是 `@unknown` 或 `限流中` |
| `connected_bots` | integer | 当前已连接 bot 数量 |
| `loads` | object | 每个 bot 的当前负载，键如 `bot1` |
| `bot_metrics` | object | 每个 bot 的运行指标 |
| `version` | string | 版本号，格式如 `v0.2.15` |

`bot_metrics[botX]` 的字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `active_requests` | integer | 正在处理的请求数 |
| `cooldown_remaining` | number | 冷却剩余时间 |
| `failure_streak` | integer | 连续失败次数 |
| `throughput_bps` | number | 吞吐速度，字节/秒 |
| `bytes_served` | integer | 已服务字节数 |

### 2.3 `DownloadRecord`

`GET /api/downloads?grouped=false` 的 `data[]` 元素。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 下载记录 ID |
| `gid` | string \| null | aria2 任务 GID |
| `source_url` | string \| null | 下载源 URL |
| `status` | string | 常见值：`pending`、`downloading`、`completed`、`failed`、`paused`、`waiting` |
| `total_length` | integer \| null | 总大小，字节 |
| `completed_length` | integer \| null | 已完成大小，字节 |
| `download_speed` | integer \| null | 下载速度，字节/秒 |
| `local_path` | string \| null | 本地路径 |
| `remote_path` | string \| null | 远端路径 |
| `upload_status` | string \| null | 旧式汇总上传状态 |
| `created_at` | string | 创建时间 |
| `started_at` | string \| null | 开始下载时间 |
| `completed_at` | string \| null | 下载完成时间 |
| `updated_at` | string | 最近更新时间 |
| `file_name` | string \| null | 源 Telegram 文件名 |
| `mime_type` | string \| null | MIME 类型 |
| `file_size` | integer \| null | Telegram 侧记录的文件大小 |
| `chat_id` | integer \| null | Telegram 聊天 ID |
| `message_id` | integer \| null | Telegram 消息 ID |
| `media_group_id` | string \| null | Telegram 媒体组 ID |
| `caption` | string \| null | 原始 caption |
| `message_date` | string \| null | Telegram 消息时间 |
| `uploads` | `UploadRecord[]` | 关联上传记录 |

### 2.4 `UploadRecord`

存在两种来源：

- 下载列表内嵌的 `uploads[]`
- `GET /api/uploads` 返回的顶层上传列表

内嵌版字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 上传记录 ID |
| `upload_target` | string | 常见值：`onedrive`、`gdrive`、`telegram` |
| `remote_path` | string \| null | 远端路径 |
| `status` | string | `pending`、`waiting_download`、`uploading`、`completed`、`failed`、`cancelled`、`paused` |
| `total_size` | integer \| null | 总大小 |
| `uploaded_size` | integer \| null | 已上传大小 |
| `upload_speed` | integer \| null | 上传速度 |
| `failure_reason` | string \| null | 失败原因分类 |
| `error_message` | string \| null | 详细错误信息 |
| `created_at` | string | 创建时间 |
| `started_at` | string \| null | 开始时间 |
| `completed_at` | string \| null | 完成时间 |
| `cleaned_at` | string \| null | 清理完成时间 |

`GET /api/uploads` 返回的顶层版还额外包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `download_id` | integer | 关联下载记录 ID |
| `error_code` | string \| null | 错误码 |
| `retry_count` | integer | 已重试次数 |
| `max_retries` | integer | 最大重试次数 |
| `updated_at` | string | 最近更新时间 |
| `local_path` | string \| null | 关联本地文件路径 |
| `download_status` | string \| null | 关联下载状态 |
| `gid` | string \| null | 关联 aria2 GID |
| `file_name` | string \| null | 文件名 |
| `file_size` | integer \| null | 文件大小 |
| `chat_id` | integer \| null | Telegram 聊天 ID |
| `message_id` | integer \| null | Telegram 消息 ID |

### 2.5 `DownloadGroup`

`GET /api/downloads?grouped=true` 的 `data[]` 元素。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `group_key` | string | 分组键，常见格式 `group_<media_group_id>` 或 `msg_<chat_id>_<message_id>` |
| `group_type` | string | 当前实现通常为 `media_group` 或 `message` |
| `chat_id` | integer \| null | Telegram 聊天 ID |
| `message_id` | integer \| null | Telegram 消息 ID |
| `media_group_id` | string \| null | 媒体组 ID |
| `caption` | string \| null | caption |
| `message_date` | string \| null | 消息时间 |
| `created_at` | string | 组内最早创建时间 |
| `stats` | object | 分组统计 |
| `downloads` | `DownloadRecord[]` | 组内下载记录 |

`stats` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total_files` | integer | 文件数 |
| `completed` | integer | 已完成数 |
| `downloading` | integer | 下载中数 |
| `failed` | integer | 失败数 |
| `pending` | integer | 待处理数 |
| `skipped` | integer | 被跳过的小文件数 |
| `total_size` | integer | 总大小 |
| `completed_size` | integer | 已完成大小 |

### 2.6 `TelegramMediaItem`

`GET /api/telegram/browse` 的 `items[]` 元素。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file_unique_id` | string | Telegram 文件唯一 ID |
| `chat_id` | integer | 聊天 ID |
| `message_id` | integer | 消息 ID |
| `file_name` | string \| null | 文件名 |
| `mime_type` | string \| null | MIME 类型 |
| `file_size` | integer \| null | 文件大小 |
| `duration` | integer \| null | 时长，秒 |
| `width` | integer \| null | 宽 |
| `height` | integer \| null | 高 |
| `caption` | string \| null | caption |
| `message_date` | string | ISO8601 时间 |
| `media_group_id` | string \| null | 媒体组 ID |
| `supports_streaming` | integer | 0/1 |
| `hash` | string | 用于直链校验的安全 hash |
| `stream_url` | string | 可直接访问的相对流媒体 URL |

### 2.7 `QueueStatus`

`GET /api/queue` 返回的主体字段。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `current_processing` | object \| null | 当前兼容旧逻辑的单个处理项 |
| `processing_count` | integer | 正在处理的数量 |
| `processing_items` | object[] | 处理中的详细条目 |
| `waiting_count` | integer | 等待中的数量 |
| `waiting_items` | object[] | 等待列表 |
| `queue_size` | integer | 底层异步队列大小 |
| `max_concurrent_messages` | integer | 最大并发消息数 |
| `flood_wait` | object \| null | Telegram 限流状态 |

队列条目常见字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `queue_id` | integer | 队列内部 ID |
| `title` | string | 标题 |
| `type` | string | 任务类型 |
| `media_group_total` | integer | 媒体组总数 |
| `message_id` | integer \| null | Telegram 消息 ID |
| `added_at` | number | 入队时间戳 |

`flood_wait` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `is_waiting` | boolean | 当前是否限流中 |
| `wait_seconds` | integer | 本次限流总秒数 |
| `remaining_seconds` | integer | 剩余秒数 |
| `resume_time` | number | 恢复时间戳 |

### 2.8 WebSocket 事件

#### `/api/ws/status`

- 握手成功后先发送 `initial`
- 后续广播消息由 `ws_manager` 推送
- 除 `initial` 外，广播类消息都带 `seq`

事件类型：

| `type` | 说明 |
| --- | --- |
| `initial` | 初始统计快照 |
| `download_update` | 下载状态更新 |
| `upload_update` | 上传状态更新 |
| `cleanup_update` | 清理状态更新 |
| `statistics_update` | 统计信息更新 |
| `pong` | 响应客户端 `{"type":"ping"}` |

事件结构：

```json
{
  "type": "download_update",
  "seq": 12,
  "data": {}
}
```

各 `data` 结构：

| 事件 | `data` 字段 |
| --- | --- |
| `initial` | `{ "downloads": <download statistics>, "uploads": <upload statistics> }` |
| `download_update` | `gid`, `download_id`, `status`, `completed_length`, `total_length`, `download_speed`, `uploads` |
| `upload_update` | `upload_id`, `download_id`, `status`, `uploaded_size`, `total_size`, `upload_speed`, `cleaned_at` |
| `cleanup_update` | `upload_id`, `download_id`, `cleaned_at` |
| `statistics_update` | `{ "downloads": <download statistics>, "uploads": <upload statistics> }` |

#### `/api/system/docker/logs/ws`

事件类型：

| `type` | 说明 |
| --- | --- |
| `history` | 初始历史日志，字段 `logs` |
| `stream_start` | 开始实时流，字段 `message` |
| `log` | 单行日志，字段 `line` |
| `error` | 错误事件，字段 `message` |

#### `/api/rclone/cache/monitor`

这个 WebSocket 不使用统一事件包，直接发送以下 JSON：

```json
{
  "status": "caching",
  "cached_size": 1048576,
  "total_size": 8388608,
  "percent": 12.5
}
```

错误时：

```json
{
  "error": "Missing remote or path"
}
```

## 3. 认证接口

### 3.1 `POST /api/auth/login`

登录并获取 JWT。

- 鉴权：否
- 请求体：JSON

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | string | 是 | 用户名 |
| `password` | string | 是 | 密码 |

成功响应：

```json
{
  "success": true,
  "token": "<jwt>",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin"
  }
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 用户名或密码为空 |
| `401` | 用户名或密码错误 |
| `500` | 登录流程异常 |

示例：

```bash
curl -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"secret"}'
```

### 3.2 `GET /api/auth/me`

获取当前登录用户信息。

- 鉴权：是
- 请求参数：无

成功响应：

```json
{
  "success": true,
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "created_at": "2026-04-20T10:00:00Z",
    "updated_at": "2026-04-20T10:00:00Z"
  }
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `401` | 未登录或 token 无效 |

示例：

```bash
curl "$BASE_URL/api/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

### 3.3 `POST /api/auth/password`

修改当前登录用户密码。

- 鉴权：是
- 请求体：JSON

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `old_password` | string | 是 | 旧密码 |
| `new_password` | string | 是 | 新密码，最少 6 位 |

成功响应：

```json
{
  "success": true,
  "message": "密码修改成功"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 参数缺失、长度不足、旧密码错误 |
| `401` | 未登录 |
| `500` | 修改失败 |

示例：

```bash
curl -X POST "$BASE_URL/api/auth/password" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"old_password":"old","new_password":"newpass123"}'
```

## 4. 系统与 Docker 接口

### 4.1 `GET /api/status`

公开状态检查接口，前端连接检测和登录前探活都会使用它。

- 鉴权：否
- 请求参数：无
- 成功响应：见 `ServerStatus`

示例：

```bash
curl "$BASE_URL/api/status"
```

### 4.2 `GET /api/system/docker/status`

查询当前容器状态。

- 鉴权：是
- 请求参数：无

成功响应示例：

```json
{
  "success": true,
  "in_docker": true,
  "container_name": "mistrelay",
  "status": "running",
  "image": "mistrelay:latest",
  "created": "2026-04-20T10:00:00.000000000Z"
}
```

运行时失败通常仍返回 `200`：

```json
{
  "success": false,
  "error": "不在Docker容器内运行",
  "in_docker": false
}
```

说明：

- 该接口会尝试通过 cgroup、容器名 `mistrelay`、`HOSTNAME` 等方式查找当前容器
- 如果 `docker` Python SDK 不可用，也会返回 `success: false`

示例：

```bash
curl "$BASE_URL/api/system/docker/status" \
  -H "Authorization: Bearer $TOKEN"
```

### 4.3 `POST /api/system/docker/restart`

重启当前 Docker 容器。

- 鉴权：是
- 请求体：无

成功响应：

```json
{
  "success": true,
  "message": "容器 mistrelay 重启成功",
  "container_name": "mistrelay"
}
```

失败说明：

- 大部分失败也是 `200 + success:false`
- 常见原因：不在容器内、Docker SDK 不可用、容器查找失败、Docker API 错误

示例：

```bash
curl -X POST "$BASE_URL/api/system/docker/restart" \
  -H "Authorization: Bearer $TOKEN"
```

### 4.4 `GET /api/system/docker/logs`

读取当前容器日志文本。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `lines` | integer | `100` | 返回最近日志行数，服务端会限制到 `1-1000` |

成功响应：

```json
{
  "success": true,
  "logs": "line1\nline2\nline3\n",
  "lines": 100
}
```

失败说明：

- Docker 相关错误通常仍返回 `200 + success:false`

示例：

```bash
curl "$BASE_URL/api/system/docker/logs?lines=200" \
  -H "Authorization: Bearer $TOKEN"
```

### 4.5 `GET /api/system/docker/logs/ws`

实时推送 Docker 日志。

- 鉴权：是
- 协议：WebSocket
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `tail` | integer | `100` | 初始历史日志行数，限制到 `1-1000` |

消息顺序：

1. `history`
2. `stream_start`
3. 多个 `log`
4. 失败时可能收到 `error`

示例：

```bash
wscat -c "ws://localhost:8080/api/system/docker/logs/ws?token=$TOKEN&tail=100"
```

### 4.6 `GET /api/system/resources`

获取 CPU、内存、磁盘使用情况。

- 鉴权：是
- 请求参数：无

成功响应：

```json
{
  "success": true,
  "data": {
    "cpu": {
      "percent": 15.3
    },
    "memory": {
      "percent": 48.2,
      "total": 17179869184,
      "used": 8283756544,
      "available": 8896112640
    },
    "disk": {
      "percent": 62.1,
      "total": 536870912000,
      "used": 333289553920,
      "free": 203581358080
    }
  }
}
```

失败说明：

- `psutil` 不可用时返回 `200 + success:false`

示例：

```bash
curl "$BASE_URL/api/system/resources" \
  -H "Authorization: Bearer $TOKEN"
```

## 5. 配置管理接口

### 5.1 `GET /api/config`

读取系统配置。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `category` | string | 否 | 按分类过滤，如 `telegram`、`rclone`、`download`、`stream` |

成功响应：

```json
{
  "success": true,
  "data": {
    "API_ID": 123456,
    "BOT_TOKEN": "123:abc",
    "UP_ONEDRIVE": true
  }
}
```

说明：

- 返回的是“键值字典”，不是数组
- 服务端会根据 `value_type` 自动把值转换为 `int`、`bool`、`list`、`json` 或 `string`

示例：

```bash
curl "$BASE_URL/api/config?category=telegram" \
  -H "Authorization: Bearer $TOKEN"
```

### 5.2 `POST /api/config`

更新系统配置。

- 鉴权：是
- 请求体：JSON 对象，键必须是允许的配置项

请求示例：

```json
{
  "UP_ONEDRIVE": true,
  "RCLONE_REMOTE": "onedrive",
  "RCLONE_PATH": "/Downloads"
}
```

成功响应：

```json
{
  "success": true,
  "message": "成功更新 3 个配置项，下次使用时将从数据库读取最新配置",
  "updated_count": 3,
  "needs_restart": false
}
```

部分失败时：

```json
{
  "success": false,
  "error": "部分配置更新失败: UNKNOWN_KEY: 未知的配置项",
  "updated_count": 1,
  "needs_restart": false
}
```

失败状态码：

| 状态码 | 场景 |
| --- | --- |
| `400` | 请求体不是对象，或含未知配置项，或部分配置保存失败 |
| `500` | 后端异常 |

当前允许的配置项：

| Key | 类型 | 分类 | 说明 | 需要重启 |
| --- | --- | --- | --- | --- |
| `API_ID` | `int` | `telegram` | Telegram API ID | 是 |
| `API_HASH` | `string` | `telegram` | Telegram API Hash | 是 |
| `BOT_TOKEN` | `string` | `telegram` | Telegram Bot Token | 是 |
| `ADMIN_ID` | `int` | `telegram` | Telegram 管理员 ID | 是 |
| `FORWARD_ID` | `string` | `telegram` | 转发 ID | 否 |
| `UP_TELEGRAM` | `bool` | `telegram` | 是否上传到 Telegram | 否 |
| `UP_ONEDRIVE` | `bool` | `rclone` | 是否启用 rclone 上传到 OneDrive | 否 |
| `RCLONE_REMOTE` | `string` | `rclone` | rclone remote 名称 | 否 |
| `RCLONE_PATH` | `string` | `rclone` | OneDrive 目标路径 | 否 |
| `UP_GOOGLE_DRIVE` | `bool` | `rclone` | 是否上传到 Google Drive | 否 |
| `GOOGLE_DRIVE_REMOTE` | `string` | `rclone` | Google Drive remote 名称 | 否 |
| `GOOGLE_DRIVE_PATH` | `string` | `rclone` | Google Drive 上传路径 | 否 |
| `AUTO_DELETE_AFTER_UPLOAD` | `bool` | `rclone` | 上传后自动删除本地文件 | 否 |
| `SAVE_PATH` | `string` | `download` | 下载保存路径 | 否 |
| `PROXY_IP` | `string` | `download` | 代理 IP | 否 |
| `PROXY_PORT` | `string` | `download` | 代理端口 | 否 |
| `SKIP_SMALL_FILES` | `bool` | `download` | 是否跳过小文件 | 否 |
| `MIN_FILE_SIZE_MB` | `int` | `download` | 最小文件大小 MB | 否 |
| `RPC_SECRET` | `string` | `aria2` | Aria2 RPC 密钥 | 否 |
| `RPC_URL` | `string` | `aria2` | Aria2 RPC URL | 否 |
| `MAX_CONCURRENT_UPLOADS` | `int` | `upload` | 最大并发上传数 | 否 |
| `ENABLE_STREAM` | `bool` | `stream` | 是否启用直链功能 | 否 |
| `BIN_CHANNEL` | `string` | `stream` | 日志频道 ID | 是 |
| `STREAM_PORT` | `int` | `stream` | Web 端口 | 是 |
| `STREAM_BIND_ADDRESS` | `string` | `stream` | 绑定地址 | 是 |
| `STREAM_HASH_LENGTH` | `int` | `stream` | 哈希长度 | 是 |
| `STREAM_HAS_SSL` | `bool` | `stream` | 是否使用 SSL | 是 |
| `STREAM_NO_PORT` | `bool` | `stream` | 是否隐藏端口 | 是 |
| `STREAM_FQDN` | `string` | `stream` | 完全限定域名 | 是 |
| `STREAM_KEEP_ALIVE` | `bool` | `stream` | 是否保持连接活跃 | 否 |
| `STREAM_PING_INTERVAL` | `int` | `stream` | Ping 间隔秒数 | 否 |
| `STREAM_USE_SESSION_FILE` | `bool` | `stream` | 是否使用 session 文件 | 是 |
| `STREAM_ALLOWED_USERS` | `string` | `stream` | 允许使用直链的用户列表 | 否 |
| `STREAM_AUTO_DOWNLOAD` | `bool` | `stream` | 是否自动加入下载队列 | 否 |
| `SEND_STREAM_LINK` | `bool` | `stream` | 是否发送直链消息 | 否 |
| `MULTI_BOT_TOKENS` | `list` | `stream` | 多机器人 token 列表 | 是 |

示例：

```bash
curl -X POST "$BASE_URL/api/config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"STREAM_KEEP_ALIVE":true,"STREAM_PING_INTERVAL":30}'
```

### 5.3 `POST /api/config/reload`

从 `config.yml` 重新导入配置到数据库。

- 鉴权：是
- 请求体：无

成功响应：

```json
{
  "success": true,
  "message": "配置已从config.yml重新导入到数据库，下次使用时将从数据库读取最新配置",
  "imported": true
}
```

失败状态码：

| 状态码 | 场景 |
| --- | --- |
| `500` | 重新导入失败 |

示例：

```bash
curl -X POST "$BASE_URL/api/config/reload" \
  -H "Authorization: Bearer $TOKEN"
```

## 6. Rclone 配置与云盘信息接口

### 6.1 `GET /api/rclone/config`

读取容器内的 rclone 配置文件内容。

- 鉴权：是
- 请求参数：无

文件路径固定为 `/root/.config/rclone/rclone.conf`。

成功响应示例：

```json
{
  "success": true,
  "content": "[onedrive]\ntype = onedrive\n...",
  "file_path": "/root/.config/rclone/rclone.conf",
  "exists": true
}
```

如果文件不存在：

```json
{
  "success": true,
  "content": "",
  "file_path": "/root/.config/rclone/rclone.conf",
  "exists": false,
  "message": "配置文件不存在,请先创建配置"
}
```

示例：

```bash
curl "$BASE_URL/api/rclone/config" \
  -H "Authorization: Bearer $TOKEN"
```

### 6.2 `POST /api/rclone/config`

保存 rclone 配置文件内容。

- 鉴权：是
- 请求体：JSON

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `content` | string | 是 | 完整的 `rclone.conf` 文本 |

成功响应：

```json
{
  "success": true,
  "message": "配置已保存,修改将在下次上传时生效",
  "file_path": "/root/.config/rclone/rclone.conf",
  "backup_path": "/root/.config/rclone/rclone.conf.bak"
}
```

说明：

- 若原文件存在，服务端会尽量生成 `.bak` 备份
- 若内容非空但看起来不像 INI 配置，服务端只记录警告，不阻止保存

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 请求体格式错误或缺少 `content` |
| `500` | 文件写入失败 |

示例：

```bash
curl -X POST "$BASE_URL/api/rclone/config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"[onedrive]\ntype = onedrive\n"}'
```

### 6.3 `GET /api/rclone/remotes`

解析 `rclone.conf` 中的全部 remote。

- 鉴权：是
- 请求参数：无

成功响应：

```json
{
  "success": true,
  "remotes": [
    {
      "name": "onedrive",
      "type": "onedrive"
    },
    {
      "name": "gdrive",
      "type": "drive"
    }
  ]
}
```

如果配置文件不存在，返回空数组而不是错误。

示例：

```bash
curl "$BASE_URL/api/rclone/remotes" \
  -H "Authorization: Bearer $TOKEN"
```

### 6.4 `GET /api/rclone/about`

查询 remote 容量信息。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remote` | string | 是 | remote 名称，如 `onedrive` |

成功响应：

```json
{
  "success": true,
  "supported": true,
  "remote": "onedrive",
  "data": {
    "total": 107374182400,
    "used": 21474836480,
    "free": 85899345920,
    "trashed": 0,
    "other": 0,
    "objects": 1234
  }
}
```

如果当前网盘不支持容量统计：

```json
{
  "success": true,
  "supported": false,
  "remote": "some-remote",
  "error": "当前网盘暂不支持容量统计"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `remote` 为空 |
| `500` | rclone 执行失败或输出解析失败 |
| `504` | rclone 超时 |

示例：

```bash
curl "$BASE_URL/api/rclone/about?remote=onedrive" \
  -H "Authorization: Bearer $TOKEN"
```

## 7. Rclone 浏览、缩略图与文件接口

### 7.1 `GET /api/rclone/browse`

列出指定 remote/path 下的文件与目录。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `remote` | string | `onedrive` | remote 名称 |
| `path` | string | `/` | 远端路径 |

成功响应：

```json
{
  "success": true,
  "remote": "onedrive",
  "path": "/Movies",
  "items": [
    {
      "name": "movie.mp4",
      "path": "Movies/movie.mp4",
      "size": 123456789,
      "mimeType": "video/mp4",
      "modTime": "2026-04-22T10:00:00Z",
      "isDir": false,
      "id": "0123456789ABCDEF"
    }
  ]
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `remote` 为空 |
| `500` | rclone 执行或 JSON 解析失败 |
| `504` | rclone 超时 |

示例：

```bash
curl "$BASE_URL/api/rclone/browse?remote=onedrive&path=/Movies" \
  -H "Authorization: Bearer $TOKEN"
```

### 7.2 `GET /api/rclone/thumbnail`

为远端文件生成或获取缩略图地址。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remote` | string | 是 | remote 名称 |
| `path` | string | 是 | 文件路径 |
| `dir` | string | 否 | 当前目录，兼容旧前端时用于补全相对路径 |

说明：

- 如果传入的是相对路径，且 `dir` 不为 `/`，服务端会尝试拼接成完整路径
- 接口成功时不会直接返回图片二进制，而是返回相对 URL

成功响应：

```json
{
  "success": true,
  "thumbnail_url": "/api/rclone/thumbnail/serve/onedrive/4c6f0d9f9b5f.webp"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `remote` 或 `path` 缺失 |
| `500` | 挂载失败、文件路径获取失败、缩略图生成失败 |

示例：

```bash
curl "$BASE_URL/api/rclone/thumbnail?remote=onedrive&path=Movies/movie.mp4&dir=/Movies" \
  -H "Authorization: Bearer $TOKEN"
```

### 7.3 `GET /api/rclone/thumbnail/serve/{remote}/{filename}`

直接返回缩略图文件。

- 鉴权：否
- Path 参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `remote` | string | remote 名称 |
| `filename` | string | 缩略图文件名，通常是 hash 后的 `.webp` |

成功响应：

- `Content-Type: image/webp`
- `Cache-Control: public, max-age=86400`

失败：

| 状态码 | 场景 |
| --- | --- |
| `404` | 缩略图不存在 |
| `500` | 服务内部错误 |

示例：

```bash
curl -O "$BASE_URL/api/rclone/thumbnail/serve/onedrive/4c6f0d9f9b5f.webp"
```

### 7.4 `GET /api/rclone/file`

读取远端文件。成功时返回文件流，不是 JSON。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remote` | string | 是 | remote 名称 |
| `path` | string | 是 | 文件路径 |
| `download` | boolean | 否 | 为 `true` 时添加 `Content-Disposition: attachment` |

说明：

- 服务端会先确保 remote 已挂载
- 成功时由 `aiohttp.web.FileResponse` 直接返回本地挂载文件
- 浏览器直接下载场景建议使用 `?token=` 方式

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少 `remote` 或 `path` |
| `404` | 文件不存在或不可访问 |
| `500` | 挂载或内部处理失败，返回纯文本响应 |

示例：

```bash
curl -L "$BASE_URL/api/rclone/file?remote=onedrive&path=Movies/movie.mp4&download=true&token=$TOKEN" \
  -o movie.mp4
```

### 7.5 `DELETE /api/rclone/file`

删除远端文件或目录。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remote` | string | 是 | remote 名称 |
| `path` | string | 是 | 文件或目录路径 |
| `is_dir` | boolean | 否 | `true` 时删除目录并清空内容；默认删除单个文件 |

成功响应：

```json
{
  "success": true,
  "message": "删除成功"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少 `remote` 或 `path` |
| `500` | rclone 删除失败 |
| `504` | 删除超时 |

示例：

```bash
curl -X DELETE "$BASE_URL/api/rclone/file?remote=onedrive&path=Movies/movie.mp4&is_dir=false" \
  -H "Authorization: Bearer $TOKEN"
```

### 7.6 `GET /api/rclone/cache/monitor`

监控 VFS 缓存进度。

- 鉴权：是
- 协议：WebSocket
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remote` | string | 是 | remote 名称 |
| `path` | string | 是 | 文件路径 |

成功消息：

```json
{
  "status": "caching",
  "cached_size": 1048576,
  "total_size": 8388608,
  "percent": 12.5
}
```

`status` 可能值：

- `waiting`
- `caching`
- `fully_cached`

错误时直接发送：

```json
{
  "error": "File not found on mount"
}
```

示例：

```bash
wscat -c "ws://localhost:8080/api/rclone/cache/monitor?token=$TOKEN&remote=onedrive&path=Movies/movie.mp4"
```

## 8. 下载、上传、队列与统计接口

### 8.1 `GET /api/downloads`

查询下载记录列表。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | integer | `100` | 最大记录数，服务端限制到 `1-500` |
| `grouped` | boolean | `true` | `true` 时按 Telegram 消息/媒体组聚合 |

成功响应：

- `grouped=true` 时：`data` 为 `DownloadGroup[]`
- `grouped=false` 时：`data` 为 `DownloadRecord[]`

示例 1：

```bash
curl "$BASE_URL/api/downloads?limit=50&grouped=true" \
  -H "Authorization: Bearer $TOKEN"
```

示例 2：

```bash
curl "$BASE_URL/api/downloads?limit=50&grouped=false" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.2 `GET /api/downloads/statistics`

获取下载统计信息。统计维度是“消息组”，不是单个文件行。

- 鉴权：是

成功响应：

```json
{
  "success": true,
  "data": {
    "total": 20,
    "completed": 10,
    "downloading": 3,
    "failed": 2,
    "pending": 5,
    "waiting": 5,
    "total_size": 1234567890,
    "completed_size": 987654321
  }
}
```

失败状态码：

| 状态码 | 场景 |
| --- | --- |
| `500` | 统计失败 |

示例：

```bash
curl "$BASE_URL/api/downloads/statistics" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.3 `DELETE /api/downloads/all`

删除全部下载记录、上传记录和 Telegram 媒体记录。

- 鉴权：是

成功响应：

```json
{
  "success": true,
  "message": "已删除 10 条下载记录、12 条上传记录和 10 条媒体记录",
  "data": {
    "deleted_downloads": 10,
    "deleted_uploads": 12,
    "deleted_media": 10
  }
}
```

示例：

```bash
curl -X DELETE "$BASE_URL/api/downloads/all" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.4 `GET /api/monitor/trend`

读取系统监控历史趋势。

- 鉴权：是

成功响应：

```json
{
  "success": true,
  "data": [
    {
      "timestamp": 1713800000,
      "upload": 12345,
      "download": 67890,
      "io": 80123
    }
  ]
}
```

说明：

- `data` 的具体点结构由 `monitor.get_history()` 决定
- 前端当前按 `timestamp/upload/download/io` 读取

示例：

```bash
curl "$BASE_URL/api/monitor/trend" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.5 `GET /api/uploads/statistics`

获取上传统计信息。

- 鉴权：是

成功响应：

```json
{
  "success": true,
  "data": {
    "total": 15,
    "uploading": 2,
    "completed": 8,
    "failed": 3,
    "pending": 2,
    "cleaned": 5,
    "total_size": 1234567890,
    "uploaded_size": 987654321,
    "by_target": {
      "onedrive": 8,
      "telegram": 7
    },
    "by_failure_reason": {
      "network_error": 1,
      "code_error": 2
    }
  }
}
```

说明：

- `pending` 已经把 `waiting_download` 合并计算进去了

示例：

```bash
curl "$BASE_URL/api/uploads/statistics" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.6 `GET /api/uploads`

查询上传记录列表。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | integer | `100` | 最大返回条数，限制到 `1-500` |
| `status` | string | 无 | 按上传状态过滤 |
| `upload_target` | string | 无 | 按目标过滤，如 `onedrive`、`telegram`、`gdrive` |

成功响应：

```json
{
  "success": true,
  "limit": 100,
  "count": 2,
  "data": [
    {
      "id": 1,
      "download_id": 10,
      "upload_target": "onedrive",
      "status": "uploading",
      "uploaded_size": 123456,
      "total_size": 999999,
      "file_name": "movie.mp4"
    }
  ]
}
```

示例：

```bash
curl "$BASE_URL/api/uploads?limit=100&status=failed&upload_target=onedrive" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.7 `GET /api/ws/status`

实时订阅下载、上传与统计更新。

- 鉴权：是
- 协议：WebSocket

客户端可以发送：

```json
{
  "type": "ping"
}
```

服务端会回复：

```json
{
  "type": "pong"
}
```

连接建立后会先收到 `initial`，随后收到各类广播事件。详见上文“2.8 WebSocket 事件”。

示例：

```bash
wscat -c "ws://localhost:8080/api/ws/status?token=$TOKEN"
```

### 8.8 `GET /api/queue`

获取 Telegram 消息处理队列状态。

- 鉴权：是
- 成功响应：见 `QueueStatus`

说明：

- 如果直链模块未启用，接口仍然返回 `success:true`，但队列为空

示例：

```bash
curl "$BASE_URL/api/queue" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.9 `POST /api/downloads/{gid}/retry`

重试某个 aria2 下载任务。

- 鉴权：是
- Path 参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `gid` | string | 旧下载任务 GID |

成功响应：

```json
{
  "success": true,
  "message": "任务已重新提交到aria2，新GID: 2089b05ecca3d829",
  "new_gid": "2089b05ecca3d829"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 无下载源 URL，无法重试 |
| `404` | 找不到下载记录 |
| `500` | aria2 提交失败或其他异常 |
| `503` | aria2 客户端未初始化 |

说明：

- 服务端会尝试移除旧 GID
- 即使旧 GID 在 aria2 中不存在，也会继续尝试重新提交

示例：

```bash
curl -X POST "$BASE_URL/api/downloads/2089b05ecca3d829/retry" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.10 `DELETE /api/downloads/{gid}`

删除某个下载任务。

- 鉴权：是
- Path 参数：`gid`

成功响应示例：

```json
{
  "success": true,
  "message": "任务 2089b05ecca3d829 已删除（Aria2任务和数据库记录已删除）",
  "data": {
    "success": true,
    "download_deleted": true,
    "upload_count": 1,
    "media_deleted": true,
    "file_deleted": false,
    "local_path": null
  }
}
```

说明：

- 如果 aria2 里已经没有该任务，但数据库里还有记录，也会继续清理数据库
- 如果数据库和 aria2 都没有该任务，接口仍可能返回 `success:true`

示例：

```bash
curl -X DELETE "$BASE_URL/api/downloads/2089b05ecca3d829" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.11 `DELETE /api/downloads/record/{download_id}`

删除下载记录，并可选择删除本地文件。

- 鉴权：是
- Path 参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `download_id` | integer | 下载记录 ID |

- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `delete_file` | boolean | `true` | 是否删除本地文件 |

成功响应：

```json
{
  "success": true,
  "message": "下载记录 10 已删除",
  "data": {
    "success": true,
    "download_deleted": true,
    "upload_count": 1,
    "media_deleted": true,
    "file_deleted": true,
    "local_path": "/downloads/movie.mp4"
  }
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `download_id` 非法，或记录删除失败 |
| `500` | 内部错误 |

说明：

- 该接口不会主动删除 aria2 任务
- 如果关联的 aria2 任务早已不存在，服务端会尽量忽略这类历史遗留错误并继续删除记录

示例：

```bash
curl -X DELETE "$BASE_URL/api/downloads/record/10?delete_file=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.12 `POST /api/uploads/{upload_id}/retry`

重试上传任务。

- 鉴权：是
- Path 参数：`upload_id`

成功响应示例：

```json
{
  "success": true,
  "message": "上传任务 5 已重新提交rclone上传"
}
```

或：

```json
{
  "success": true,
  "message": "上传任务 5 已重新提交Telegram上传"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `upload_id` 非法，或上传目标不支持 |
| `404` | 上传记录、关联下载记录或本地文件不存在 |
| `500` | 提交重试失败 |

说明：

- `onedrive` / `gdrive` 走 rclone 上传重试
- `telegram` 走 Telegram 上传重试
- 重试前会把上传状态重置为 `pending`

示例：

```bash
curl -X POST "$BASE_URL/api/uploads/5/retry" \
  -H "Authorization: Bearer $TOKEN"
```

### 8.13 `DELETE /api/uploads/{upload_id}`

取消或删除上传任务。

- 鉴权：是
- Path 参数：`upload_id`

成功响应：

```json
{
  "success": true,
  "message": "上传任务 5 已取消"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `upload_id` 非法 |
| `404` | 上传记录不存在 |
| `500` | 取消失败 |

说明：

- 若上传状态是 `uploading`，服务端会尝试终止对应进程
- 最终状态会被写成 `cancelled`

示例：

```bash
curl -X DELETE "$BASE_URL/api/uploads/5" \
  -H "Authorization: Bearer $TOKEN"
```

## 9. Telegram 媒体库接口

### 9.1 `GET /api/telegram/browse`

浏览已入库的 Telegram 媒体文件。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | `1` | 页码，从 1 开始 |
| `page_size` | integer | `50` | 每页数量，服务端上限 `200` |
| `search` | string | 无 | 按 `file_name` 或 `caption` 模糊搜索 |
| `type` | string | 无 | `video`、`image`、`audio`、`document` |
| `sort_by` | string | `message_date` | 允许：`message_date`、`file_size`、`file_name` |
| `sort_desc` | boolean | `true` | 只要不是显式传 `false`，都按降序处理 |

成功响应：

```json
{
  "success": true,
  "items": [
    {
      "file_unique_id": "AQAD...",
      "message_id": 12345,
      "file_name": "movie.mp4",
      "hash": "a1b2c3d4",
      "stream_url": "/12345/movie.mp4?hash=a1b2c3d4"
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 50
}
```

说明：

- `type=document` 会排除 video/image/audio
- 非法 `sort_by` 会自动回退为 `message_date`

示例：

```bash
curl "$BASE_URL/api/telegram/browse?page=1&page_size=50&search=movie&type=video&sort_by=message_date&sort_desc=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 9.2 `GET /api/telegram/usage`

统计 Telegram 媒体库容量与文件类型分布。

- 鉴权：是

成功响应：

```json
{
  "success": true,
  "data": {
    "total_count": 100,
    "total_size": 1234567890,
    "videos": 30,
    "images": 40,
    "audios": 10,
    "documents": 20
  }
}
```

示例：

```bash
curl "$BASE_URL/api/telegram/usage" \
  -H "Authorization: Bearer $TOKEN"
```

### 9.3 `DELETE /api/telegram/item/{message_id}`

删除单个 Telegram 媒体项。

- 鉴权：是
- Path 参数：`message_id`

成功响应：

```json
{
  "success": true,
  "message": "频道消息已删除并清理记录",
  "data": {
    "deleted_media": 1,
    "deleted_downloads": 1,
    "deleted_uploads": 1,
    "deleted_message_count": 1,
    "cleanup_only": false,
    "client_index": 0,
    "message_id": 12345
  }
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `message_id` 非法 |
| `404` | 媒体记录不存在 |
| `500` | 删除失败 |

说明：

- 如果频道消息已经不存在，但数据库记录存在，接口仍可能成功，并把 `cleanup_only` 标记为 `true`

示例：

```bash
curl -X DELETE "$BASE_URL/api/telegram/item/12345" \
  -H "Authorization: Bearer $TOKEN"
```

### 9.4 `DELETE /api/telegram/group/{media_group_id}`

删除整个 Telegram 媒体组。

- 鉴权：是
- Path 参数：`media_group_id`

成功响应：

```json
{
  "success": true,
  "message": "媒体组已删除并清理记录",
  "data": {
    "deleted_media": 5,
    "deleted_downloads": 5,
    "deleted_uploads": 5,
    "deleted_message_count": 5,
    "cleanup_only": false,
    "client_index": 1,
    "media_group_id": "12345678901234567",
    "message_count": 5
  }
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | `media_group_id` 为空 |
| `404` | 媒体组不存在 |
| `500` | 删除失败 |

示例：

```bash
curl -X DELETE "$BASE_URL/api/telegram/group/12345678901234567" \
  -H "Authorization: Bearer $TOKEN"
```

### 9.5 `DELETE /api/telegram/all`

清空整个 Telegram 媒体库。

- 鉴权：是

成功响应示例：

```json
{
  "success": true,
  "message": "tg 网盘已清空",
  "data": {
    "deleted_media": 10,
    "deleted_downloads": 10,
    "deleted_uploads": 10,
    "deleted_message_count": 10,
    "cleanup_only": false,
    "client_index": 0,
    "message_count": 10
  }
}
```

如果本来就是空的：

```json
{
  "success": true,
  "message": "tg 网盘已为空",
  "data": {
    "deleted_media": 0,
    "deleted_downloads": 0,
    "deleted_uploads": 0,
    "deleted_message_count": 0,
    "cleanup_only": false,
    "client_index": null
  }
}
```

示例：

```bash
curl -X DELETE "$BASE_URL/api/telegram/all" \
  -H "Authorization: Bearer $TOKEN"
```

## 10. 文件管理接口

> 注意：这组接口当前直接以容器根目录 `/` 为基准进行读写，不是受限的业务目录。文档必须按现状理解，生产环境使用前应自行评估安全风险。

### 10.1 `GET /api/files/list`

列出指定目录下的文件与文件夹。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `path` | string | `/` | 要列出的目录 |

成功响应：

```json
{
  "success": true,
  "path": "/downloads",
  "files": [
    {
      "name": "movie.mp4",
      "path": "/downloads/movie.mp4",
      "is_dir": false,
      "size": 123456789,
      "modified_time": "2026-04-22 11:30:00"
    }
  ]
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 指定路径不是目录 |
| `403` | 无权访问目录 |
| `404` | 路径不存在 |
| `500` | 其他异常 |

示例：

```bash
curl "$BASE_URL/api/files/list?path=/downloads" \
  -H "Authorization: Bearer $TOKEN"
```

### 10.2 `GET /api/files/download`

下载本地文件。成功时直接返回文件流。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `path` | string | 是 | 本地文件路径 |

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少 `path`，或目标是目录 |
| `404` | 文件不存在 |
| `500` | 读取失败 |

示例：

```bash
curl -L "$BASE_URL/api/files/download?path=/downloads/movie.mp4&token=$TOKEN" \
  -o movie.mp4
```

### 10.3 `POST /api/files/upload`

上传本地文件到容器文件系统。

- 鉴权：是
- 请求体：`multipart/form-data`

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `path` | string | 否 | 目标目录，默认 `/` |
| `file` | file | 是 | 文件内容 |

成功响应：

```json
{
  "success": true,
  "message": "上传成功",
  "file": {
    "name": "movie.mp4",
    "path": "/downloads/movie.mp4",
    "size": 123456789
  }
}
```

说明：

- 若目标目录不存在，服务端会自动创建
- 受全局 `client_max_size` 限制

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少文件字段，或文件名为空 |
| `500` | 写入失败 |

示例：

```bash
curl -X POST "$BASE_URL/api/files/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "path=/downloads" \
  -F "file=@./movie.mp4"
```

### 10.4 `POST /api/files/mkdir`

创建本地目录。

- 鉴权：是
- 请求体：JSON

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `path` | string | 是 | 要创建的目录路径 |

成功响应：

```json
{
  "success": true,
  "message": "目录 /downloads/new-folder 创建成功"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少 `path` 或目录已存在 |
| `500` | 创建失败 |

示例：

```bash
curl -X POST "$BASE_URL/api/files/mkdir" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"path":"/downloads/new-folder"}'
```

### 10.5 `DELETE /api/files/delete`

删除本地文件或目录。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `path` | string | 是 | 要删除的路径 |

成功响应：

```json
{
  "success": true,
  "message": "已删除 /downloads/movie.mp4"
}
```

失败：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少 `path` |
| `403` | 试图删除根目录 `/` |
| `404` | 文件或目录不存在 |
| `500` | 删除失败 |

示例：

```bash
curl -X DELETE "$BASE_URL/api/files/delete?path=/downloads/movie.mp4" \
  -H "Authorization: Bearer $TOKEN"
```

## 11. 日志管理接口

### 11.1 `GET /api/logs`

读取日志内容。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 当前日志文件 | 指定日志文件名 |
| `tail` | integer | `200` | 返回最后 N 行 |
| `level` | string | 无 | 级别过滤，如 `ERROR`、`WARNING`、`INFO` |
| `keyword` | string | 无 | 关键词搜索 |

成功响应：

```json
{
  "success": true,
  "total": 2,
  "lines": [
    "2026-04-22 10:00:00 | INFO    | routes | started",
    "2026-04-22 10:00:01 | ERROR   | routes | something failed"
  ]
}
```

说明：

- 如果指定文件不存在，当前实现返回 `success:true` 且 `lines` 为空数组

示例：

```bash
curl "$BASE_URL/api/logs?file=mistrelay.log&tail=100&level=ERROR&keyword=timeout" \
  -H "Authorization: Bearer $TOKEN"
```

### 11.2 `GET /api/logs/files`

列出所有日志文件。

- 鉴权：是

成功响应：

```json
{
  "success": true,
  "files": [
    {
      "name": "mistrelay.log",
      "path": "/app/db/logs/mistrelay.log",
      "size": 123456,
      "modified": "2026-04-22 11:00:00"
    }
  ]
}
```

说明：

- 只会列出文件名以 `mistrelay` 开头的日志文件
- 按 `modified` 降序排序

示例：

```bash
curl "$BASE_URL/api/logs/files" \
  -H "Authorization: Bearer $TOKEN"
```

### 11.3 `GET /api/logs/download/{filename}`

下载指定日志文件。

- 鉴权：是
- Path 参数：`filename`

成功响应：

- 直接返回文件流
- Header 含 `Content-Disposition: attachment; filename="<safe_name>"`

失败：

| 状态码 | 场景 |
| --- | --- |
| `404` | 文件不存在 |
| `500` | 下载失败 |

说明：

- 服务端会对 `filename` 做 `basename` 处理，避免直接使用路径穿越值

示例：

```bash
curl -L "$BASE_URL/api/logs/download/mistrelay.log?token=$TOKEN" \
  -o mistrelay.log
```

## 12. 非 `/api` 路由与流媒体行为

### 12.1 `GET /`

根路径优先尝试返回前端 `index.html`。

行为：

- 如果 `/app/web/dist/index.html` 存在，直接返回该文件
- 如果前端未构建，则退化为执行 `GET /api/status` 的逻辑并返回状态 JSON

### 12.2 `GET /{path:.+}`

这是一个 catch-all 路由，优先级低于所有已声明的 `/api/*` 路由。

处理顺序如下：

1. 如果路径以 `api/` 开头，直接返回 `404 API endpoint not found`
2. 如果路径以 `assets/` 开头，按前端静态资源返回，并设置长期缓存
3. 如果路径是 `favicon.ico` 或 `robots.txt`，尝试返回静态文件
4. 否则尝试按 Telegram 流媒体路径处理
5. 如果不是合法流媒体路径，则回退到 SPA 的 `index.html`

### 12.3 Telegram 流媒体路径

当前支持两种 URL 形式：

1. `/{hash}{message_id}`
2. `/{message_id}/{filename}?hash={hash}`

其中：

- `hash` 长度取决于当前 `Var.HASH_LENGTH`
- `message_id` 是频道消息 ID

成功时返回：

- `200` 或 `206`
- `Accept-Ranges: bytes`
- `Content-Range`
- `Content-Length`
- `Content-Disposition`
- `X-MistRelay-Min-Threads`

说明：

- 支持 Range 请求
- 对视频、音频、HTML 会用 `inline`；其他类型默认 `attachment`
- `hash` 不匹配时返回 `403`
- 文件不存在时返回 `404`

示例：

```bash
curl -L "$BASE_URL/12345/movie.mp4?hash=a1b2c3d4"
```

## 13. 常见错误码速查

| 状态码 | 常见来源 |
| --- | --- |
| `200` | 成功；或 Docker/系统类接口的运行时失败但使用 `success:false` 表达 |
| `204` | CORS 预检 `OPTIONS` |
| `400` | 参数缺失、参数格式错误、业务前置条件不满足 |
| `401` | 未登录、token 失效 |
| `403` | 无权限、流媒体 hash 不合法、禁止删除根目录 |
| `404` | 资源不存在、文件不存在、下载记录不存在 |
| `500` | 后端异常、子进程失败、数据库/IO 错误 |
| `503` | 依赖服务未初始化，例如 aria2 客户端缺失 |
| `504` | 调用 rclone 或外部系统超时 |
