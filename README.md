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
- `STREAM_ALLOWED_USERS` 只接受不可转让的数字 Telegram 用户 ID；留空时拒绝所有入库请求。

### Web 管理界面

- Vue 3 + Vite + Element Plus 前端。
- JWT 登录；首次初始化必须通过 root-only 密码文件显式提供强管理员密码，不再创建默认密码。
- 仪表盘、下载任务、上传任务、TG 网盘、系统状态、日志、配置页面。
- 生产容器不挂载 Docker socket，也不能从 Web 界面控制宿主 Docker。

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
chmod 0600 db/config.yml
```

最小配置示例：

```yaml
API_ID: your_api_id
API_HASH: your_api_hash
BOT_TOKEN: your_bot_token
ADMIN_ID: your_telegram_user_id
BIN_CHANNEL: -100xxxxxxxxxx

UP_TELEGRAM: true
SAVE_PATH: /data/downloads
DOWNLOAD_CLEANUP_ENABLED: true
DOWNLOAD_RETENTION_HOURS: 24
DOWNLOAD_CLEANUP_INTERVAL_SECONDS: 3600

RPC_SECRET: "<openssl rand -hex 32 的输出>"
RPC_URL: localhost:6800/jsonrpc

ENABLE_STREAM: true
STREAM_PORT: 8080
STREAM_BIND_ADDRESS: 0.0.0.0
STREAM_FQDN: your-domain.example
STREAM_ALLOWED_USERS: "123456789"
STREAM_AUTO_DOWNLOAD: false
SEND_STREAM_LINK: false
```

常用配置说明：

| 配置项 | 说明 |
| --- | --- |
| `UP_TELEGRAM` | 下载完成后是否上传到 Telegram 频道网盘。 |
| `BIN_CHANNEL` | TG 频道网盘存储频道，直链和上传流程都依赖它。 |
| `STREAM_FQDN` | 生成直链时使用的域名或公网 IP。 |
| `STREAM_ALLOWED_USERS` | 允许使用直链入库的数字 Telegram 用户 ID，逗号分隔；留空时拒绝所有用户。 |
| `STREAM_AUTO_DOWNLOAD` | 历史兼容开关；当前 TG 网盘媒体不会自动加入 aria2。 |
| `SEND_STREAM_LINK` | 是否把生成的直链主动回复给 Telegram 用户。 |
| `DOWNLOAD_CLEANUP_ENABLED` | 是否启用下载目录自动清理，默认启用。 |
| `DOWNLOAD_RETENTION_HOURS` | 本地下载文件保留小时数，默认 `24`。 |
| `DOWNLOAD_CLEANUP_INTERVAL_SECONDS` | 清理任务检查间隔，默认 `3600` 秒。 |
| `SKIP_SMALL_FILES` / `MIN_FILE_SIZE_MB` | 下载链路的小文件过滤配置。 |
| `MAX_CONCURRENT_MESSAGES` | Telegram 媒体消息队列的最大并发处理数。 |
| `MAX_MESSAGE_QUEUE_SIZE` | Telegram 媒体等待队列硬上限，默认 `100`，运行时限制为 `1-1000`。 |
| `MULTI_BOT_TOKENS` | 额外 Bot Token 列表，用于直链读取负载均衡。 |

### 3. Docker 部署

```bash
install -d -m 0750 db downloads cache/thumbnails
chown -R 10001:10001 db downloads cache/thumbnails
chmod 0600 db/config.yml
umask 077
openssl rand -base64 24 > db/admin-password
chown 10001:10001 db/admin-password
chmod 0600 db/admin-password
# 另用 `openssl rand -hex 32` 生成 RPC_SECRET 并写入 db/config.yml。
docker compose build
docker compose run --rm --no-deps \
  -e MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP=1 \
  mistrelay python3 bootstrap_legacy.py
docker compose up -d --no-build
docker compose logs -f --tail=100
```

旧 YAML 只允许通过上面的单次离线命令导入。命令会校验 owner-only 权限、把配置写入 SQLite 并将 `db/config.yml` 替换为空的退休占位文件。不要把 `MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP=1` 写入 Compose 或长期环境；正常启动在数据库缺失、为空或读取失败时都会拒绝回退到 YAML。

Compose 会拒绝自动创建缺失的 bind 目录，目录必须预先存在并由容器 UID/GID `10001:10001` 可写。容器使用 bridge 网络，只把 Web 端口发布到宿主回环地址；aria2 RPC 不对宿主发布：

```text
http://127.0.0.1:8080
```

首次登录用户名为 `admin`，密码是 `db/admin-password` 中的值。确认登录并改成长期密码后，可删除初始密码文件：

```bash
rm -f db/admin-password
```

### 4. 运行后的目录

默认 Docker Compose 挂载：

| 宿主机路径 | 容器路径 | 用途 |
| --- | --- | --- |
| `./db` | `/app/db` | 数据库、配置、Telegram session、日志。 |
| `./downloads` | `/data/downloads` | aria2 下载目录。 |
| `./cache/thumbnails` | `/app/cache/thumbnails` | 缩略图缓存。 |

## 使用方式

### Telegram 命令

| 命令 | 说明 |
| --- | --- |
| `/start` | 显示欢迎信息和菜单。 |
| `/help` | 查看帮助。 |
| `/menu` | 管理员菜单。 |
| `/info` | 查看 aria2 全局信息。 |

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

API 不接受 URL 查询参数中的管理员 JWT。TG 流媒体 URL 使用消息 hash，缩略图使用服务端签发的短时、单路径票据；WebSocket 使用 `Sec-WebSocket-Protocol` 传递 JWT。PC 客户端适配细节见：

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

默认 Compose 使用固定 bridge 网络、read-only rootfs、`no-new-privileges`、全部 capability drop，并且不挂载 Docker socket。Web 入口只发布到 `127.0.0.1:8080`，应由受控的 HTTPS 反向代理转发；aria2 RPC 只监听容器回环地址且不发布端口。生产代理模板见 `deploy/nginx-mistrelay.conf.example`，启用前必须替换域名和证书路径。模板会覆盖而非追加 `X-Forwarded-For`，与 Compose 中仅信任 `172.25.0.1/32` 的设置配套使用。

发生凭据泄漏后，必须先停止服务，再离线轮换。将 `docs/credential-rotation.example.yml` 复制到仓库外，填入 BotFather 新签发的 token、新 RPC secret、新管理员密码和已完成 TLS 配置的 `PUBLIC_BASE_URL`，并限制为当前用户可读。若 DNS/TLS 尚未就绪，将公开地址留空并保持 `SEND_STREAM_LINK: false`：

```bash
chmod 0600 /path/to/new-mistrelay-credentials.yml
python3 rotate_credentials.py \
  --input /path/to/new-mistrelay-credentials.yml \
  --database db/downloads.db
```

成功后立即删除输入文件。工具不会打印秘密，会在单个 SQLite 事务中更新配置、撤销现有 Web refresh session，并关闭持久化 Pyrogram 会话。不要通过命令行参数、Telegram 消息或 Web 配置接口传递秘密。

SQLite 更新会先在单一事务中提交并复核，随后再退休同目录的旧 `config.yml`。若第二步因文件权限失败，工具会明确提示数据库已经完成轮换；修复权限后用同一输入重跑，只会补做旧文件清理。轮换还会删除遗留 `FORWARD_ID`，避免旧的静默转发目标复活。

轮换后、启动前执行只读激活门禁。管理员、频道、完整 allowlist 和 HTTPS origin 必须与预期精确匹配；每个允许用户都要单独重复一次 `--expected-allowed-user`：

```bash
python3 activation_preflight.py \
  --database db/downloads.db \
  --download-root downloads \
  --cache-root cache/thumbnails \
  --rotation-input-path /path/to/new-mistrelay-credentials.yml \
  --expected-public-origin https://files.example.com \
  --expected-admin-id 123456789 \
  --expected-channel-id -1001234567890 \
  --expected-allowed-user 123456789
```

该命令不会打印秘密，也不会启动服务。它会检查数据库完整性、schema、规范化配置、管理员哈希、session 撤销、数据卷权限、镜像与工作树关键文件哈希、容器实际权限/挂载/网络和停止状态。外部凭据或域名尚未准备时，只能用 `--staged-only` 做结构检查；该模式的成功不能视为公开上线许可。

- `RPC_SECRET` 必须是 32-256 位高熵 URL-safe 随机字符串；可用 `openssl rand -hex 32` 生成。
- `API_ID` / `API_HASH`、主 Bot Token、所有额外 Bot Token 和 RPC secret 都必须与泄漏值不同；工具会拒绝复用。
- `STREAM_HASH_LENGTH` 的运行时最低值为 `32` 个十六进制字符（128 bit）。
- `STREAM_ALLOWED_USERS` 必须显式填写可信数字用户 ID，用户名和空 allowlist 均不会获得权限。
- 不要提交 `db/*.session*`、`db/sessions/`、真实 `db/config.yml`、数据库、下载或缓存目录。
- 默认 Bot 客户端只使用内存会话；如显式启用 `STREAM_USE_SESSION_FILE`，会话文件写入 `/app/db/sessions`，必须按凭证文件保护。
- 生产环境使用 HTTPS，并正确设置 `STREAM_HAS_SSL` / `STREAM_FQDN`。
- 旧 rclone/OneDrive/Google Drive 路径、remote、归档目标和上传开关会在轮换事务中删除；仍需在提供商侧撤销 OAuth grant。
- 事件恢复期间 Compose 保持 `restart: "no"`；凭据轮换、频道可访问性和 HTTPS 实链路测试全部通过后，再改为 `unless-stopped`。

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
