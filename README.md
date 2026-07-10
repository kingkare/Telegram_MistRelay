# MistRelay

MistRelay 是一个基于 Telegram Bot 的 aria2 下载控制与 Telegram 频道网盘系统。它把 HTTP/磁力/种子下载、Telegram 频道归档、文件直链、任务记录和 Web 管理界面整合到一个 Docker 服务里。

当前主线能力已经从“第三方网盘 + 自动下载 Telegram 媒体”收敛为：

- HTTP/HTTPS、磁力链接、种子文件继续由 aria2 下载。
- 下载完成后可上传到 Telegram 频道网盘。
- 直接发送给 Bot 的 Telegram 媒体会保存到 `BIN_CHANNEL`，写入 TG 网盘索引，并生成直链。
- Telegram 媒体不会再自动加入 aria2 队列，也不会下载回本地。
- rclone/OneDrive/Google Drive 相关接口已废弃，仅保留历史兼容响应。

## 功能概览

### Telegram Bot

- 管理 aria2 下载任务：添加 HTTP/HTTPS 链接、磁力链接、种子文件。
- 查看正在下载、等待中、已完成/停止的任务。
- 暂停、恢复、删除任务，清空已完成任务。
- 设置默认下载路径。
- 接收 Telegram 文档、视频、音频、图片、媒体组并保存到 TG 频道网盘。

### TG 频道网盘

- 使用 Telegram 频道作为文件存储与索引来源。
- 媒体入库后记录 `chat_id`、`message_id`、文件名、大小、MIME、媒体组等元数据。
- Web 端支持浏览、搜索、预览、删除 TG 网盘文件。
- 同一 Telegram 媒体组会在 Web 端聚合为文件夹，进入后可查看组内真实文件。

### 文件直链

- 集成 TG-FileStreamBot 风格的直链服务。
- 支持完整链接和短链接。
- 支持多 Bot 客户端负载均衡，降低单 Bot 直链读取压力。
- 可通过 `STREAM_ALLOWED_USERS` 限制哪些 Telegram 用户能使用直链入库能力。

### Web 管理界面

- Vue 3 + Vite + Element Plus 前端。
- JWT 登录，默认首次初始化会创建 `admin / admin123`，上线后必须立即修改密码。
- 仪表盘、下载任务、上传任务、TG 网盘、系统状态、日志、配置页面。
- Docker 容器状态、日志查看和重启能力依赖 Docker socket 挂载。

### 数据与同步

- SQLite 持久化下载、上传、TG 媒体索引和系统配置。
- WAL 模式提升并发读写稳定性。
- WebSocket 推送任务状态和系统日志。
- 下载完成后进行基础一致性记录，上传完成后更新 TG 网盘索引。

## 快速开始

### 1. 准备 Telegram 参数

需要准备：

- `API_ID` / `API_HASH`: Telegram API 凭据。
- `BOT_TOKEN`: BotFather 创建的 Bot Token。
- `ADMIN_ID`: 管理员 Telegram 用户 ID。
- `BIN_CHANNEL`: 用作 TG 频道网盘的频道 ID，通常以 `-100` 开头。

Bot 需要加入 `BIN_CHANNEL`，并至少具备发送、读取和删除消息所需权限。

### 2. 创建配置文件

克隆项目：

```bash
git clone https://github.com/Lapis0x0/MistRelay.git
cd MistRelay
```

复制配置示例：

```bash
cp db/config.yml.example db/config.yml
```

最小配置示例：

```yaml
API_ID: your_api_id
API_HASH: your_api_hash
BOT_TOKEN: your_bot_token
ADMIN_ID: your_telegram_user_id
BIN_CHANNEL: -100xxxxxxxxxx

UP_TELEGRAM: true
SAVE_PATH: /root/downloads
DOWNLOAD_CLEANUP_ENABLED: true
DOWNLOAD_RETENTION_HOURS: 24
DOWNLOAD_CLEANUP_INTERVAL_SECONDS: 3600

RPC_SECRET: change_me_to_a_long_random_secret
RPC_URL: localhost:6800/jsonrpc

ENABLE_STREAM: true
STREAM_PORT: 8080
STREAM_BIND_ADDRESS: 0.0.0.0
STREAM_FQDN: your-domain.example
STREAM_AUTO_DOWNLOAD: false
SEND_STREAM_LINK: false
```

常用配置说明：

| 配置项 | 说明 |
| --- | --- |
| `UP_TELEGRAM` | 下载完成后是否上传到 Telegram 频道网盘。 |
| `BIN_CHANNEL` | TG 频道网盘存储频道，直链和上传流程都依赖它。 |
| `STREAM_FQDN` | 生成直链时使用的域名或公网 IP。 |
| `STREAM_ALLOWED_USERS` | 允许使用直链入库的 Telegram 用户 ID/用户名，逗号分隔，留空表示不限制。 |
| `STREAM_AUTO_DOWNLOAD` | 历史兼容开关；当前 TG 网盘媒体不会自动加入 aria2。 |
| `SEND_STREAM_LINK` | 是否把生成的直链主动回复给 Telegram 用户。 |
| `DOWNLOAD_CLEANUP_ENABLED` | 是否启用下载目录自动清理，默认启用。 |
| `DOWNLOAD_RETENTION_HOURS` | 本地下载文件保留小时数，默认 `24`。 |
| `DOWNLOAD_CLEANUP_INTERVAL_SECONDS` | 清理任务检查间隔，默认 `3600` 秒。 |
| `SKIP_SMALL_FILES` / `MIN_FILE_SIZE_MB` | 下载链路的小文件过滤配置。 |
| `MAX_CONCURRENT_MESSAGES` | Telegram 媒体消息队列的最大并发处理数。 |
| `MULTI_BOT_TOKENS` | 额外 Bot Token 列表，用于直链读取负载均衡。 |

### 3. Docker 部署

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

默认使用 host 网络，服务监听 `8080`：

```text
http://your-server:8080
```

首次登录：

```text
username: admin
password: admin123
```

登录后先修改密码，再继续配置服务。

### 4. 运行后的目录

默认 Docker Compose 挂载：

| 宿主机路径 | 容器路径 | 用途 |
| --- | --- | --- |
| `./db` | `/app/db` | 数据库、配置、Telegram session、日志。 |
| `./downloads` | `/root/downloads` | aria2 下载目录。 |
| `./cache/thumbnails` | `/app/cache/thumbnails` | 缩略图缓存。 |
| `/var/run/docker.sock` | `/var/run/docker.sock` | Web 系统管理模块读取/控制容器。 |

## 使用方式

### Telegram 命令

| 命令 | 说明 |
| --- | --- |
| `/start` | 显示欢迎信息和菜单。 |
| `/help` | 查看帮助。 |
| `/menu` | 管理员菜单。 |
| `/info` | 查看 aria2 全局信息。 |
| `/web` | 获取 AriaNg 在线控制地址。 |
| `/path [目录]` | 设置 aria2 默认下载目录。 |

### 下载任务

- 给 Bot 发送 HTTP/HTTPS 链接，会添加到 aria2。
- 给 Bot 发送 `magnet:` 链接，会添加到 aria2。
- 给 Bot 发送 `.torrent` 文件，会下载种子并添加到 aria2。
- 下载完成后，如果 `UP_TELEGRAM: true`，会上传到 `BIN_CHANNEL` 并写入数据库。

### TG 频道网盘

- 给 Bot 发送或转发 Telegram 媒体文件。
- 服务会把媒体转发到 `BIN_CHANNEL`。
- 服务会保存媒体元数据到 SQLite。
- Web 端的 TG 网盘页面可以浏览、预览、搜索和删除这些文件。

注意：这条链路不再创建 aria2 下载任务。`STREAM_AUTO_DOWNLOAD` 仅保留为历史配置项，当前逻辑不会因为它为 `true` 就把 TG 媒体下载回本地。

### 直链访问

直链 URL 由 `STREAM_FQDN`、`STREAM_PORT`、`STREAM_HAS_SSL`、`STREAM_NO_PORT` 和消息 hash 拼接生成。

如果播放器、下载器或客户端不能携带 `Authorization` 头，可以在部分 API/播放地址中使用 `?token=<jwt>`。PC 客户端适配细节见：

```text
docs/pc-client-tg-drive.md
```

## Web 页面

主要页面：

- `Dashboard`: 概览、任务状态和系统资源。
- `Downloads`: 下载记录、重试、删除、统计。
- `Tasks`: 队列和任务中心。
- `Drive`: TG 频道网盘浏览与预览。
- `System`: Docker 状态、资源监控、容器日志。
- `Logs`: 应用日志查看和下载。
- `Settings`: 服务配置、客户端连接、密码修改入口。

API 文档见：

```text
docs/backend-api.md
```

## 开发

### 后端

后端主要入口：

- `app.py`: Telegram Bot、aria2 client、WebStreamer 启动入口。
- `WebStreamer/server/stream_routes.py`: aiohttp API 和前端静态文件路由。
- `db.py`: SQLite schema、迁移和数据访问。
- `aria2_client/`: aria2 RPC、下载事件、上传事件处理。
- `WebStreamer/bot/plugins/stream_modules/`: Telegram 媒体入库、队列、限流和直链辅助逻辑。

Python 语法检查：

```bash
python3 -m compileall -q app.py auth.py configer.py db.py util.py log_config.py monitor.py async_aria2_client.py thumbnail_generator.py aria2_client WebStreamer
```

### 前端

```bash
cd web
npm install
npm run dev
npm run type-check
npm run build
```

前端开发服务器默认：

```text
http://localhost:5173
```

Vite 会把 `/api` 和直链路径代理到 `http://localhost:8080`。

### 开发脚本

`dev-scripts/` 下保留了开发辅助脚本：

- `dev-scripts/start-dev.sh`
- `dev-scripts/watch-backend.sh`
- `dev-scripts/build-frontend.sh`

具体用法见 `dev-scripts/README.md`。

## 部署与安全注意事项

当前默认 Docker Compose 偏向“单机自用、快速部署”：

- `network_mode: host` 会让容器直接使用宿主机网络。
- `privileged: true` 会扩大容器权限。
- 挂载 `/var/run/docker.sock` 后，Web 系统管理模块具备控制 Docker 的能力。
- aria2 RPC 默认由启动脚本生成配置，务必设置强 `RPC_SECRET`。

建议：

- 只把 Web 入口暴露给可信网络，或放在反向代理后面。
- 上线后立即修改默认管理员密码。
- 不要把 `db/*.session`、`db/*.session.bak-*`、真实 `db/config.yml` 提交到仓库。
- 如果不需要 Web 控制 Docker，移除 Docker socket 挂载并关闭相关页面入口。
- 生产环境建议使用 HTTPS，并正确设置 `STREAM_HAS_SSL` / `STREAM_FQDN`。

## 数据一致性

MistRelay 的核心数据表：

- `tg_media`: Telegram 媒体索引。
- `downloads`: aria2 下载记录。
- `uploads`: 上传任务记录。
- `config_settings`: Web 可编辑配置。
- `users`: Web 登录用户。

一致性机制：

- SQLite WAL 模式。
- 事务封装数据库写入。
- aria2 事件和轮询同步下载状态。
- 上传完成后写入 TG 媒体索引。
- WebSocket 推送任务和日志状态。

更多背景资料：

```text
DATABASE_SYNC_REPORT.md
DATA_CONSISTENCY_CHECK.md
```

## 常见问题

### TG 网盘页面没有文件

检查：

- `BIN_CHANNEL` 是否配置正确。
- Bot 是否是频道管理员。
- 发送给 Bot 的媒体是否成功转发到频道。
- 后端日志里是否有 `记录频道媒体到数据库失败`。

### 直链打不开

检查：

- `STREAM_FQDN` 是否是浏览器可访问的域名或公网 IP。
- `STREAM_PORT` 是否开放。
- `STREAM_HAS_SSL` / `STREAM_NO_PORT` 是否和实际反向代理一致。
- Bot 是否仍能访问 `BIN_CHANNEL` 中的原始消息。

### Web 配置保存后没有立即生效

部分配置在模块导入或客户端初始化时读取，需要重启服务才会完全生效，例如 Telegram 凭据、频道、端口、FQDN、多 Bot Token 等。保存配置后如果页面提示需要重启，请通过 Docker 或系统页面重启容器。

### 第三方网盘还能用吗

不再维护。`/api/rclone/*` 接口会返回废弃提示。新上传和新索引都走 Telegram 频道网盘。

## 路线图

- [ ] 收紧文件管理 API 的可访问根目录。
- [ ] 为默认管理员增加首次登录强制改密流程。
- [ ] 优化 TG 网盘搜索、重命名和批量操作。
- [ ] 优化移动端 Web 体验。
- [ ] 增加后端自动化测试覆盖。

## 致谢

本项目参考和整合了以下项目的思路或能力：

- [TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot)
- [MistRelay](https://github.com/Lapis0x0/MistRelay)
- [HouCoder/tele-aria2](https://github.com/HouCoder/tele-aria2)
- [jw-star/aria2bot](https://github.com/jw-star/aria2bot)
