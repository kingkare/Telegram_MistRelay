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
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/health`

其余 `/api/*` 接口都需要 token。

传递方式：

- HTTP API 和文件下载：`Authorization: Bearer <token>`
- WebSocket：子协议 `mistrelay.jwt.<token>`
- 管理员 JWT 不接受 `?token=` 查询参数，避免凭据进入访问日志和浏览器历史
- TG 缩略图使用浏览接口返回的短时、单路径 `ticket`，流媒体地址使用消息 hash

JWT 特性：

- Access token 过期时间固定为 15 分钟
- Refresh token 默认 30 天，服务端只保存哈希，并在每次刷新时轮换
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

服务端只允许同源请求和 `MISTRELAY_CORS_ORIGINS` 明确列出的 Origin：

- `Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS`
- `Access-Control-Allow-Headers: Authorization, Content-Type, Accept, Origin, X-Requested-With, Range`
- `Access-Control-Expose-Headers: Content-Disposition, Content-Length, Content-Range, Accept-Ranges, X-MistRelay-Min-Threads`

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

### 1.6 接口索引

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/auth/login` | 否 | 登录获取 JWT |
| `GET` | `/api/auth/me` | 是 | 获取当前用户 |
| `POST` | `/api/auth/password` | 是 | 修改密码 |
| `GET` | `/api/health` | 否 | 最小存活/就绪状态 |
| `GET` | `/api/status` | 是 | 详细服务与 Bot 状态 |
| `GET` | `/api/system/docker/status` | 是 | Docker 状态 |
| `POST` | `/api/system/docker/restart` | 是 | 重启 Docker 容器 |
| `GET` | `/api/system/docker/logs` | 是 | Docker 日志 |
| `GET` | `/api/system/resources` | 是 | 系统资源 |
| `GET` | `/api/system/docker/logs/ws` | 是 | Docker 日志 WebSocket |
| `GET` | `/api/config` | 是 | 获取配置 |
| `POST` | `/api/config` | 是 | 更新配置 |
| `POST` | `/api/config/reload` | 是 | 在线导入已禁用，固定返回 `403` |
| `GET` | `/api/downloads` | 是 | 下载记录 |
| `GET` | `/api/downloads/statistics` | 是 | 下载统计 |
| `DELETE` | `/api/downloads/all` | 是 | 清空下载记录 |
| `GET` | `/api/monitor/trend` | 是 | 监控趋势 |
| `GET` | `/api/uploads/statistics` | 是 | 上传统计 |
| `GET` | `/api/uploads` | 是 | 上传记录 |
| `GET` | `/api/ws/status` | 是 | 下载/上传状态 WebSocket |
| `GET` | `/api/queue` | 是 | 消息队列状态 |
| `POST` | `/api/downloads/{gid}/retry` | 是 | 重试下载 |
| `DELETE` | `/api/downloads/{gid}` | 是 | 取消/删除 aria2 任务 |
| `DELETE` | `/api/downloads/record/{download_id}` | 是 | 删除下载记录 |
| `POST` | `/api/uploads/{upload_id}/retry` | 是 | 重试上传 |
| `DELETE` | `/api/uploads/{upload_id}` | 是 | 取消/删除上传 |
| `GET` | `/api/telegram/browse` | 是 | TG 频道网盘浏览 |
| `GET` | `/api/telegram/usage` | 是 | TG 频道网盘统计 |
| `DELETE` | `/api/telegram/item/{message_id}` | 是 | 删除单个 TG 文件 |
| `DELETE` | `/api/telegram/group/{media_group_id}` | 是 | 删除媒体组文件夹 |
| `POST` | `/api/telegram/batch/delete` | 是 | 删除当前选择的 TG 文件和媒体组 |
| `DELETE` | `/api/telegram/all` | 是 | 清空 TG 频道网盘 |
| `GET` | `/api/telegram/thumbnails/status` | 是 | 缩略图后台预生成工作器状态 |
| `POST` | `/api/telegram/thumbnails/warmup` | 是 | 启动/恢复缩略图全量预热扫描 |
| `GET` | `/api/cache/stats` | 是 | 全维度存储与内存缓存统计 |
| `POST` | `/api/cache/clean` | 是 | 分类安全清理缓存（支持 Dry-run） |
| `GET` | `/api/cache/policy` | 是 | 获取自动清理生命周期策略 |
| `PUT` | `/api/cache/policy` | 是 | 动态保存自动清理生命周期策略 |
| `GET` | `/api/telegram/botfather/accounts` | 是 | 协议号资产池列表（脱敏） |
| `POST` | `/api/telegram/botfather/accounts/import` | 是 | 批量导入协议号资产（异步任务模式，避免 524 超时） |
| `GET` | `/api/telegram/botfather/accounts/import-task/{task_id}` | 是 | 查询后台协议号导入任务状态与实时进度 |
| `DELETE` | `/api/telegram/botfather/accounts/{id}` | 是 | 从资产池安全移除协议号 |
| `POST` | `/api/telegram/botfather/accounts/{id}/check` | 是 | 探测协议号存活与持有机数 |
| `POST` | `/api/telegram/botfather/tasks/start` | 是 | 启动多号接力或单号精准自动铸机流水线 |
| `GET` | `/api/telegram/botfather/task-status` | 是 | 查询创机流水线实时进度与事件日志 |
| `POST` | `/api/telegram/botfather/tasks/stop` | 是 | 停止创机流水线 |
| `POST` | `/api/telegram/bots/hot-add` | 是 | 批量热挂载 Bot Token（零停机） |
| `DELETE` | `/api/telegram/bots/{index}` | 是 | 热卸载并移除指定从机节点 |
| `POST` | `/api/telegram/bots/reprobe` | 是 | 重新探测免加频道 Handle 与分流能力 |
| `POST` | `/api/telegram/bots/test-load` | 是 | 集群节点多轮分流均匀度负载压测 |
| `POST` | `/api/telegram/bots/{index}/benchmark` | 是 | 单节点网络延迟与小块吞吐测速 |
| `POST` | `/api/telegram/bots/benchmark-all` | 是 | 全集群节点网络与小块吞吐测速 |
| `POST` | `/api/telegram/benchmark/stream-and-download` | 是 | 单连接播放 vs 多连接下载速率实战基准测试 |
| `GET` | `/api/files/list` | 是 | 本地文件列表 |
| `GET` | `/api/files/download` | 是 | 本地文件下载 |
| `POST` | `/api/files/upload` | 是 | 本地文件上传 |
| `POST` | `/api/files/mkdir` | 是 | 创建本地目录 |
| `DELETE` | `/api/files/delete` | 是 | 删除本地文件/目录 |
| `GET` | `/api/logs` | 是 | 应用日志内容 |
| `GET` | `/api/logs/files` | 是 | 应用日志文件列表 |
| `GET` | `/api/logs/download/{filename}` | 是 | 应用日志文件下载 |
| `GET/POST/DELETE` | `/api/rclone/*` | 是 | 废弃兼容占位，统一返回 `410 Gone` |
| `GET` | `/` | 否 | 前端入口或状态降级响应 |
| `GET` | `/{message_id}/{filename}?hash=...` | 是 | Telegram 流媒体/下载 |

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
| `version` | string | 版本号，格式如 `v2.2.5` |
| `channel_info` | object | TG 频道公开标识与免加频道状态 |
| `bot_details` | array | 集群中各 Bot 节点详细权限与工作模式 |
| `dc_partitions` | object | Telegram DC1~DC5 数据中心动态分区分布与热度统计 |

`channel_info` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `channel_id` | integer | 当前绑定的 Telegram 频道 ID |
| `channel_type` | string | `"public"` 或 `"private"` |
| `public_handle` | string \| null | 探测到的公开用户名或关联讨论组 Handle |
| `no_join_balancing_active` | boolean | 免加频道分流是否处于激活就绪状态 |

`bot_details[]` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `index` | integer | 机器人节点编号（0 为主控） |
| `username` | string | 机器人用户名（如 `@mr_node_1_bot`） |
| `mode` | string | `"primary_admin"` (主控) / `"direct_admin"` (频道管理) / `"no_join_resolved"` (免加频道分流就绪) / `"unreachable"` |
| `can_read` | boolean | 是否具备流播与读取权限 |
| `can_write` | boolean | 是否具备发帖转存与删帖权限 |
| `invite_url` | string \| null | 私密频道未加管时的一键加管引导链接 |
| `home_dc` | integer \| null | 机器人原生注册归属的 Telegram 数据中心编号（1~5） |
| `warm_dcs` | integer[] | 机器人当前已完成 MTProto 握手并保持活跃的热备媒体数据中心列表 |

`dc_partitions[DCx]` 字段（如 `DC1` ~ `DC5`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | string | 数据中心代码与地理分布（如 `"DC5 (新加坡/亚太)"`） |
| `files_count` | integer | 存储于该 DC 分区下的网盘媒体文件总数 |
| `home_bots` | integer | 原生归属注册在该 DC 的 Bot 节点数 |
| `warm_bots` | integer | 当前已握手就绪可零延迟拉取该 DC 媒体的活跃 Bot 数 |
| `requests` | integer | 系统累计分流至该 DC 的媒体请求计数 |

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
| `upload_target` | string | 新任务固定为 `telegram`；旧库可能保留 `onedrive`/`gdrive` 历史值 |
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

### 2.6 `TelegramDriveEntry`

`GET /api/telegram/browse` 的 `items[]` 元素。根目录可能返回媒体组文件夹或真实文件；传入 `media_group_id` 时只返回真实文件。

通用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entry_type` | string | `folder` 或 `file` |
| `file_unique_id` | string | 文件唯一 ID；文件夹条目仅作代表记录，不可作为文件夹 ID |
| `chat_id` | integer | 聊天 ID |
| `message_id` | integer | 消息 ID；删除真实文件时使用 |
| `file_name` | string \| null | 文件或文件夹显示名；历史真实文件可能为空或缺少扩展名 |
| `mime_type` | string \| null | MIME 类型；媒体组文件夹为 `application/x-mistrelay-media-group` |
| `file_size` | integer \| null | 文件大小；媒体组文件夹为组内总大小 |
| `message_date` | string | ISO8601 时间；媒体组文件夹为组内最新消息时间 |
| `media_group_id` | string \| null | 媒体组 ID；删除文件夹和进入文件夹时使用 |
| `dc_id` | integer \| null | 该媒体文件所在的 Telegram 数据中心编号（1~5） |
| `dc_label` | string \| null | 数据中心分区标签（如 `"DC5"`、`"DC4"`） |

文件夹专有字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `item_count` | integer | 组内真实文件数量 |
| `total_size` | integer | 组内真实文件总大小 |
| `group_mime_types` | string[] | 组内真实文件 MIME 类型集合 |

真实文件专有字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `duration` | integer \| null | 时长，秒 |
| `width` | integer \| null | 宽 |
| `height` | integer \| null | 高 |
| `caption` | string \| null | caption |
| `supports_streaming` | integer | 0/1 |
| `download_file_name` | string | 下载保存建议名，服务端会尽量补齐扩展名 |
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

该第三方网盘缓存监控接口已废弃，返回 `410 Gone` JSON，不再提供 WebSocket 监控。

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
| `new_password` | string | 是 | 新密码，长度 16-512 位 |

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
  -d '{"old_password":"old-password","new_password":"new-unique-password-123"}'
```

## 4. 系统与 Docker 接口

默认加固 Compose 不挂载 Docker socket。状态接口会返回应用自检结果，日志接口会读取持久化应用日志；重启接口保持关闭，页面会明确显示宿主 Docker 控制未启用。

### 4.1 `GET /api/health`

公开的最小存活/就绪检查，前端连接检测和容器健康检查使用它。启动未完成时返回 `503`，不会暴露 Bot 名称或负载。

- 鉴权：否
- 请求参数：无

示例：

```bash
curl "$BASE_URL/api/health"
```

详细状态使用 `GET /api/status`，需要 `Authorization: Bearer <token>`，成功响应见 `ServerStatus`。

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
  "created": "2026-08-13T10:00:00+00:00",
  "status_source": "application",
  "control_enabled": false,
  "control_message": "宿主 Docker 控制未启用，当前状态来自应用自检",
  "application_version": "v2.2.5"
}
```

启用 Docker 控制且 Docker API 可访问时，`status_source` 为 `docker`、`control_enabled` 为 `true`，响应还会包含镜像名称。默认加固部署中的镜像名称为空，因为应用自检不会访问宿主 Docker API。

非容器环境同样返回当前应用状态：

```json
{
  "success": true,
  "in_docker": false,
  "status": "running",
  "status_source": "application",
  "control_enabled": false
}
```

说明：

- 只读状态不依赖 Docker socket，默认使用当前应用进程的启动时间和运行状态
- 启用 Docker 控制后，接口会尝试通过 cgroup、容器名 `mistrelay`、`HOSTNAME` 等方式查找当前容器

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
wscat -s "mistrelay.jwt.$TOKEN" -c "ws://localhost:8080/api/system/docker/logs/ws?tail=100"
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
| `category` | string | 否 | 按分类过滤，如 `telegram`、`download`、`stream` |

成功响应：

```json
{
  "success": true,
  "data": {
    "API_ID": 123456,
    "BOT_TOKEN": "",
    "UP_TELEGRAM": true
  },
  "redacted_keys": ["BOT_TOKEN"],
  "offline_only_keys": ["API_ID", "BOT_TOKEN"]
}
```

说明：

- 返回的是“键值字典”，不是数组
- `API_HASH`、Bot Token、额外 Bot Token 和 `RPC_SECRET` 只返回空值与 `redacted_keys` 元数据，不返回秘密
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
  "UP_TELEGRAM": true
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

请求含任何非法或离线专用字段时，整个请求不会写入：

```json
{
  "success": false,
  "error": "部分配置更新失败: UNKNOWN_KEY: 未知的配置项",
  "updated_count": 0,
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
| `UP_TELEGRAM` | `bool` | `telegram` | 是否上传到 Telegram 频道网盘 | 否 |
| `SAVE_PATH` | `string` | `download` | 下载保存路径 | 否 |
| `PROXY_IP` | `string` | `download` | 代理 IP | 否 |
| `PROXY_PORT` | `string` | `download` | 代理端口 | 否 |
| `SKIP_SMALL_FILES` | `bool` | `download` | 是否跳过小文件 | 否 |
| `MIN_FILE_SIZE_MB` | `int` | `download` | 最小文件大小 MB | 否 |
| `DOWNLOAD_CLEANUP_ENABLED` | `bool` | `download` | 是否启用下载目录自动清理 | 否 |
| `DOWNLOAD_RETENTION_HOURS` | `int` | `download` | 下载文件保留小时数 | 否 |
| `DOWNLOAD_CLEANUP_INTERVAL_SECONDS` | `int` | `download` | 下载目录清理间隔秒数 | 否 |
| `RPC_SECRET` | `string` | `aria2` | Aria2 RPC 密钥 | 否 |
| `RPC_URL` | `string` | `aria2` | Aria2 RPC URL | 否 |
| `MAX_CONCURRENT_UPLOADS` | `int` | `upload` | 最大并发上传数 | 否 |
| `ENABLE_STREAM` | `bool` | `stream` | 是否启用直链功能 | 否 |
| `BIN_CHANNEL` | `string` | `stream` | 日志频道 ID | 是 |
| `STREAM_PORT` | `int` | `stream` | Web 端口 | 是 |
| `STREAM_BIND_ADDRESS` | `string` | `stream` | 绑定地址 | 是 |
| `STREAM_HASH_LENGTH` | `int` | `stream` | 哈希长度，运行时最小 32 | 是 |
| `STREAM_HAS_SSL` | `bool` | `stream` | 是否使用 SSL | 是 |
| `STREAM_NO_PORT` | `bool` | `stream` | 是否隐藏端口 | 是 |
| `STREAM_FQDN` | `string` | `stream` | 完全限定域名 | 是 |
| `STREAM_KEEP_ALIVE` | `bool` | `stream` | 是否保持连接活跃 | 否 |
| `STREAM_PING_INTERVAL` | `int` | `stream` | Ping 间隔秒数 | 否 |
| `STREAM_USE_SESSION_FILE` | `bool` | `stream` | 是否使用 session 文件 | 是 |
| `STREAM_ALLOWED_USERS` | `string` | `stream` | 允许使用直链的用户列表 | 否 |
| `STREAM_AUTO_DOWNLOAD` | `bool` | `stream` | 历史兼容：是否自动加入下载队列 | 否 |
| `SEND_STREAM_LINK` | `bool` | `stream` | 是否发送直链消息 | 否 |
| `MULTI_BOT_TOKENS` | `list` | `stream` | 多机器人 token 列表 | 是 |

凭据、频道、代理、RPC、文件根目录、监听地址、公开域名、哈希长度和链接发送等安全敏感字段只能在停机维护窗口用 `rotate_credentials.py` 修改；在线提交不同值会返回 `400`，且不会部分保存其他字段。

示例：

```bash
curl -X POST "$BASE_URL/api/config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"STREAM_KEEP_ALIVE":true,"STREAM_PING_INTERVAL":30}'
```

### 5.3 `POST /api/config/reload`

在线配置导入已禁用。该接口固定返回 `403`，凭据恢复必须使用 owner-only 输入文件和 `rotate_credentials.py`。

- 鉴权：是
- 请求体：无

响应状态码：

| 状态码 | 场景 |
| --- | --- |
| `403` | 在线 YAML 导入被安全策略禁止 |

示例：

```bash
curl -X POST "$BASE_URL/api/config/reload" \
  -H "Authorization: Bearer $TOKEN"
```

旧 `config.yml` 仅能在首次部署时通过显式的一次性 `bootstrap_legacy.py` 离线导入；数据库缺失或异常不会触发自动 YAML 回退。

## 6. 已废弃的第三方网盘接口

第三方网盘（rclone/OneDrive/Google Drive）已废弃。以下旧接口仅保留兼容占位，并统一返回 `410 Gone`：

- `GET /api/rclone/config`
- `POST /api/rclone/config`
- `GET /api/rclone/remotes`
- `GET /api/rclone/about`
- `GET /api/rclone/browse`
- `GET /api/rclone/thumbnail`
- `GET /api/rclone/file`
- `DELETE /api/rclone/file`
- `GET /api/rclone/cache/monitor`

响应示例：

```json
{
  "success": false,
  "error": "第三方网盘已废弃，请使用 Telegram 频道网盘",
  "deprecated": true
}
```

## 7. Telegram 频道网盘概览

TG 频道网盘是当前唯一维护的网盘能力，接口集中在第 9 节 `/api/telegram/*`。前端适配时应以 `entry_type` 区分媒体组文件夹和真实文件，不再调用第三方网盘接口。

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
      "telegram": 7,
      "onedrive": 8
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
| `upload_target` | string | 无 | 按目标过滤；新任务为 `telegram`，旧记录可能是 `onedrive`/`gdrive` |

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
      "upload_target": "telegram",
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
curl "$BASE_URL/api/uploads?limit=100&status=failed&upload_target=telegram" \
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
wscat -s "mistrelay.jwt.$TOKEN" -c "ws://localhost:8080/api/ws/status"
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
  "message": "上传任务 5 已重新提交Telegram上传"
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

- 仅 `telegram` 支持上传重试
- `onedrive` / `gdrive` 是历史第三方网盘目标，重试会返回 `410 Gone`
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

## 9. Telegram 频道网盘接口

### 9.1 `GET /api/telegram/browse`

默认按 TG 网盘根目录返回条目：同一 `media_group_id` 会聚合成一个 `entry_type = "folder"` 的媒体组文件夹；单文件返回 `entry_type = "file"`。传入 `media_group_id` 时返回该媒体组内的真实文件列表。

浏览已入库的 Telegram 频道网盘文件。

- 鉴权：是
- Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | `1` | 页码，从 1 开始 |
| `page_size` | integer | `50` | 每页数量，服务端上限 `200` |
| `search` | string | 无 | 按 `file_name` 或 `caption` 模糊搜索 |
| `type` | string | 无 | `video`、`image`、`audio`、`document` |
| `media_group_id` | string | 无 | 进入指定媒体组文件夹，返回组内真实文件 |
| `sort_by` | string | `message_date` | 允许：`message_date`、`file_size`、`file_name` |
| `sort_desc` | boolean | `true` | 只要不是显式传 `false`，都按降序处理 |

成功响应：

```json
{
  "success": true,
  "items": [
    {
      "entry_type": "folder",
      "media_group_id": "1234567890",
      "file_unique_id": "AQAD_group_rep",
      "chat_id": -1001234567890,
      "message_id": 12344,
      "file_name": "媒体组 1234567890",
      "mime_type": "application/x-mistrelay-media-group",
      "file_size": 123456789,
      "total_size": 123456789,
      "item_count": 4,
      "message_date": "2026-04-24T10:20:30"
    },
    {
      "entry_type": "file",
      "file_unique_id": "AQAD...",
      "chat_id": -1001234567890,
      "message_id": 12345,
      "file_name": "movie.mp4",
      "download_file_name": "movie.mp4",
      "mime_type": "video/mp4",
      "file_size": 104857600,
      "message_date": "2026-04-24T10:10:00",
      "hash": "a1b2c3d4",
      "stream_url": "/12345/movie.mp4?hash=a1b2c3d4"
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 50,
  "grouped": true
}
```

说明：

- 根目录 `total` 是“媒体组文件夹 + 单文件”的数量，不是底层真实媒体文件数量
- 传入 `media_group_id` 后 `grouped` 为 `false`，`items[]` 均为真实文件
- `type=document` 会排除 video/image/audio
- 非法 `sort_by` 会自动回退为 `message_date`
- `stream_url` 是相对服务端 origin 的 URL，客户端可按需追加 `token` 查询参数
- 前端下载保存名应优先使用流媒体响应头 `Content-Disposition`，拿不到响应头时使用 `download_file_name`
- 服务端会在 `download_file_name` 和 `stream_url` 路径中尽量补齐扩展名：优先使用真实文件名已有的常见扩展名；若文件名缺少扩展名，或最后的点后缀不是常见文件扩展名，则按 MIME/媒体类型补 `.mp4`、`.jpg`、`.ogg` 等后缀

示例：

```bash
curl "$BASE_URL/api/telegram/browse?page=1&page_size=50&search=movie&type=video&sort_by=message_date&sort_desc=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 9.2 `GET /api/telegram/usage`

统计 Telegram 频道网盘容量与文件类型分布。

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

删除单个 Telegram 频道网盘文件。

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

### 9.5 `POST /api/telegram/batch/delete`

批量删除选中的 Telegram 文件和媒体组。单次最多提交 200 个所选项目；媒体组会在服务端展开，和单文件一起去重后删除频道消息及关联记录。

请求体：

```json
{
  "message_ids": [12345, 12346],
  "media_group_ids": ["12345678901234567"]
}
```

成功响应中的 `matched_file_count` 是媒体组展开并去重后的频道文件数。已不存在的选择会分别出现在 `missing_message_ids` 和 `missing_media_group_ids`，只要至少匹配到一个文件，其他有效选择仍会完成删除。

```json
{
  "success": true,
  "message": "已删除 7 个频道文件",
  "data": {
    "selected_item_count": 3,
    "matched_file_count": 7,
    "deleted_message_count": 7,
    "deleted_media": 7,
    "deleted_downloads": 2,
    "deleted_uploads": 1,
    "missing_message_ids": [],
    "missing_media_group_ids": []
  }
}
```

### 9.6 `DELETE /api/telegram/all`

清空整个 Telegram 频道网盘。

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

### 9.7 `GET /api/telegram/thumbnails/status`

获取 Telegram 缩略图后台预生成工作器（`TelegramThumbnailWorker`）的实时运行状态与进度。

- 鉴权：是
- 请求参数：无
- 响应数据：

```json
{
  "success": true,
  "data": {
    "running": true,
    "total": 162,
    "cached": 45,
    "pending": 117,
    "percent": 27.8,
    "current_message_id": 5660
  }
}
```

### 9.8 `POST /api/telegram/thumbnails/warmup`

手动启动或重新触发后台全量媒体缩略图预热扫描。工作器将静默扫描历史无缓存媒体，并在后台平滑生成 WebP 缩略图，避免前台浏览时长时间等待。

- 鉴权：是（仅限管理员）
- 请求体：可选 `{ "force": false }`
- 响应数据：

```json
{
  "success": true,
  "message": "已成功启动后台缩略图预生成，共入队 117 项待处理媒体",
  "data": {
    "enqueued": 117,
    "running": true
  }
}
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
curl -L "$BASE_URL/api/files/download?path=/movie.mp4" \
  -H "Authorization: Bearer $TOKEN" \
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
curl -L "$BASE_URL/api/logs/download/mistrelay.log" \
  -H "Authorization: Bearer $TOKEN" \
  -o mistrelay.log
```

## 12. 非 `/api` 路由与流媒体行为

### 12.1 `GET /`

根路径优先尝试返回前端 `index.html`。

行为：

- 如果 `/app/web/dist/index.html` 存在，直接返回该文件
- 如果前端未构建，则退化为执行 `GET /api/health` 的逻辑并返回最小状态 JSON

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
- `Content-Disposition` 会尽量同时提供 `filename` 和 `filename*`，下载客户端应优先解析 `filename*`
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

### 12.4 下载文件名与后缀规则

客户端下载 TG 网盘文件时，保存名优先级推荐为：

1. 流媒体响应头 `Content-Disposition` 的 `filename*`
2. 流媒体响应头 `Content-Disposition` 的 `filename`
3. `/api/telegram/browse` 返回的 `download_file_name`
4. `stream_url` 路径最后一段解码后的文件名
5. `file_name`
6. `media_<message_id>.bin`

服务端生成 `download_file_name` 时会：

- 清理路径分隔符、换行和危险引号，只保留基础文件名
- 保留常见真实扩展名，例如 `.mp4`、`.jpg`、`.mkv`、`.zip`
- 对缺少扩展名的图片、视频、音频按 MIME 或媒体类型补齐扩展名
- 对类似 `movie.1080p` 这类非标准点后缀继续补真实扩展名，最终形如 `movie.1080p.mp4`
- 对未知二进制且文件名已有不明点后缀的情况不强行追加 `.bin`，避免误改用户原始文件名

示例：

| 原始文件名 | MIME/媒体类型 | 下载保存名 |
| --- | --- | --- |
| `movie` | `video/mp4` | `movie.mp4` |
| `movie.1080p` | `video/mp4` | `movie.1080p.mp4` |
| 空 | `image/jpeg` | `media_<message_id>.jpg` |
| `archive.7z` | `application/octet-stream` | `archive.7z` |

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
| `504` | 调用外部系统超时 |


## 14. 缓存与存储治理接口 (`/api/cache/*`)

提供磁盘容量概况、缩略图缓存、下载目录残留文件、Rclone VFS 挂载缓存以及运行时内存缓存的统一监控与安全清理。

### 14.1 `GET /api/cache/stats`

查询系统磁盘、分类缓存体积、文件数及运行时内存状态。

- 鉴权：是（管理员）
- 响应数据示例：

```json
{
  "success": true,
  "data": {
    "disk": {
      "total_bytes": 107374182400,
      "used_bytes": 42949672960,
      "free_bytes": 64424509440,
      "percent": 40.0
    },
    "thumbnails": {
      "total_bytes": 268435456,
      "total_files": 1280,
      "telegram_bytes": 209715200,
      "telegram_files": 1050,
      "other_bytes": 58720256,
      "other_files": 230
    },
    "downloads": {
      "path": "/data/downloads",
      "total_bytes": 5368709120,
      "total_files": 12,
      "protected_files": 2
    },
    "rclone": {
      "total_bytes": 0,
      "total_files": 0
    },
    "memory": {
      "lru_entries": 64,
      "active_sessions": 3
    }
  }
}
```

### 14.2 `POST /api/cache/clean`

分类安全清理冗余缓存。支持 `dry_run=true` 试运行模式（仅预估可释放体积与文件数，不实际删除物理文件）。下载目录清理内置活跃任务保护，绝不误删进行中的下载与上传文件。

- 鉴权：是（管理员）
- 请求体参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `category` | string | 必填 | `"thumbnails"` \| `"downloads"` \| `"rclone"` \| `"memory"` \| `"all"` |
| `retention_hours` | integer | `24` | 下载目录保留时间（小时） |
| `retention_days` | integer | `7` | 缩略图保留天数 |
| `dry_run` | boolean | `false` | 是否为仅分析不删除的试运行模式 |

- 响应示例：

```json
{
  "success": true,
  "message": "缓存清理完成",
  "data": {
    "category": "thumbnails",
    "dry_run": false,
    "deleted_files": 145,
    "freed_bytes": 45678900,
    "skipped_protected": 0,
    "duration_ms": 120
  }
}
```

### 14.3 `GET /api/cache/policy` & `PUT /api/cache/policy`

读写下载目录与缩略图的自动清理生命周期策略。

- 鉴权：是（管理员）
- 配置对象结构：

```json
{
  "success": true,
  "data": {
    "DOWNLOAD_CLEANUP_ENABLED": true,
    "DOWNLOAD_RETENTION_HOURS": 24,
    "DOWNLOAD_CLEANUP_INTERVAL_SECONDS": 3600,
    "THUMBNAIL_CACHE_MAX_AGE_DAYS": 7
  }
}
```

---

## 15. 多机器人集群与 @BotFather 自动化流水线接口

### 15.1 协议号资产池管理

- **`GET /api/telegram/botfather/accounts`**：查询纳管的 Telegram API 协议号列表（手机号、持有机数、状态、脱敏后信息）。
- **`POST /api/telegram/botfather/accounts/import`**：支持多行大文本粘贴（`+86138...|http://api...` 或 Session String）或通过 `multipart/form-data` 上传多个 `.session` 文件。默认在后台启动异步导入任务并立即返回 `task_id`，彻底避免 Cloudflare 或反向代理 100~120s 超时 (HTTP 524)。支持传 `?sync=true` 同步等待模式。
- **`GET /api/telegram/botfather/accounts/import-task/{task_id}`**：轮询后台协议号导入任务的实时状态、当前正在接码的手机号、频率保护冷却倒计时、实时日志及最终导入结果。
- **`DELETE /api/telegram/botfather/accounts/{id}`**：安全从资产池移除指定协议号。
- **`POST /api/telegram/botfather/accounts/{id}/check`**：通过 MTProto 直连 `@BotFather` `/mybots` 探测最新机器人数量并同步更新数据库。

### 15.2 @BotFather 自动化流水线

- **`POST /api/telegram/botfather/tasks/start`**：启动自动化创机流水线任务。
  - `mode`: `"relay"` (多号接力模式，突破单号 20 上限，遇上限/限流自动切号) 或 `"single"` (单号精准独立铸造)；
  - `account_ids`: 参与多号接力的账号 ID 列表；
  - `single_account_id`: 单号精准模式的目标账号 ID；
  - `count`: 目标扩容机器人总数（多号接力支持最高 200 个，单号模式上限 20 个）；
  - `name_prefix`: 机器人名称前缀（如 `MistRelay Node`）；
  - `reuse_existing`: 是否优先复用存量未挂载 Bot。
- **`GET /api/telegram/botfather/task-status`**：获取当前创机任务状态、实时百分比进度、当前运作账号、已铸造 Bot 清单及最近执行日志。
- **`POST /api/telegram/botfather/tasks/stop`**：强制取消并中止正在运行的创机流水线。

### 15.3 运行期热挂载与节点调度

- **`POST /api/telegram/bots/hot-add`**：
  - 请求体：`{ "tokens": ["123456:ABC...", "789012:DEF..."] }` 或字符串；
  - 零停机即时初始化并加入调度池，自动持久化至 `MULTI_BOT_TOKENS`。
- **`DELETE /api/telegram/bots/{index}`**：优雅断开并移除指定编号的 Worker 机器人（禁止移除 0 号主控制 Bot）。
- **`POST /api/telegram/bots/reprobe`**：重新探测频道公开 Handle，批量为未加频道的 Worker 节点激活免加频道分流模式。
- **`POST /api/telegram/bots/test-load`**：向集群发送 `rounds_per_bot * total_bots` 次分流调度请求，返回各节点分流命中次数与方差分布报告。

### 15.4 性能基准测试接口

- **`POST /api/telegram/bots/{index}/benchmark`** & **`POST /api/telegram/bots/benchmark-all`**：
  - 测试节点 API 响应延迟与 1MB 小块传输吞吐率。
- **`POST /api/telegram/benchmark/stream-and-download`**：
  - 参数：`sample_size_mb` (`10` \| `100` \| `1024`)，可选 `bot_index` 与 `message_id`；
  - 实测真实单连接在线播放吞吐速度（`Single Connection Playback Speed`）与多连接并发下载吞吐速度（`Concurrent Download Speed`），输出峰值/平均速率与链路耗时报告。
