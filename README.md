# MistRelay

MistRelay 是一个基于 Telegram Bot 的高性能 aria2 下载控制、Telegram 频道网盘中继与媒体流分发系统。系统将 HTTP/磁力/种子下载、Telegram 频道无限云存储、多机器人免加频道负载均衡集群、@BotFather 自动化扩容流水线、后台缩略图静默预热引擎、统一缓存生命周期治理中心以及现代毛玻璃 Web 管理中台整合至单个安全加固的 Docker 容器中。

---

## 核心功能与架构特性

### 1. Telegram 多机器人免加频道负载均衡集群
- **免加频道公开 Handle 自动接入**：主控机器人启动后自动探测频道的公开 Handle（用户名或关联公开讨论组），集群中的从属 Worker 机器人无需逐一人工添加到频道中，即可通过 MTProto 自动解析 Peer 并激活免加频道只读分流模式（`no_join_resolved`）。
- **严格读写分离调度**：
  - **写客户端池 (`channel_write_clients`)**：仅由 0 号主控 Bot 或具备管理员权限的机器人执行 Aria2 转存发帖与物理删帖，彻底杜绝无权限写入错误；
  - **读客户端池 (`channel_accessible_clients`)**：包含所有就绪机器人，协同承担大文件直链下载、视频在线流播与缩略图抽帧生成，成倍提升集群并发吞吐并规避单 Bot 限流。

### 2. Telegram 动态数据中心分区（DC-Aware）亲和调度与条带化负载均衡
- **DC 原生归属与热会话追踪**：自动探测 Telegram 网盘媒体所在的物理数据中心分区（DC1 美西、DC2/DC4 欧洲、DC3 美东、DC5 亚太/新加坡），并实时采集集群机器人的原生注册归属（`home_dc`）与当前活跃连接池（`warm_dcs`）。
- **三级亲和评分调度算法**：
  - **一级亲和（同区原生 `home_dc == target_dc`）**：DC 惩罚 0.0，零跨区握手延迟，最高优先级；
  - **二级亲和（热会话复用 `target_dc in warm_dcs`）**：DC 惩罚 0.8，直接复用已授权加密通道；
  - **三级溢出（跨区冷节点）**：DC 惩罚 2.0，仅在同区与热备节点高负载时平滑溢出接管，并在接管后自动晋升为二级热备节点；
- **单流多 Bot 条带化（Striping）同区优先聚合**：在线流播与大文件分块下载时，并发条带池优先聚合目标 DC 的同区与热备节点，彻底消除跨洋冷节点导出授权（`ExportAuthorization`）引发的队头阻塞与微卡顿。
- **动态分区矩阵全景看板**：Web `/bots` 页面实时呈现 DC1~DC5 网盘文件分布、各 DC 原生 Bot 数与热备就绪会话数；`/drive` 网盘列表与封面直观展示文件 DC 分区徽标。

### 2. @BotFather 自动化扩容流水线与协议号资产池
- **协议号资产池（Protocol Account Pool）**：
  - 支持多行批量粘贴（`手机号|自动接码链接` 或 Session String）与多选上传 `.session` 文件；
  - 自动识别并兼容 Pyrogram 与 Telethon 会话格式，纯内存安全解析。
- **双模铸造工作台**：
  - **多号接力模式 (Relay Mode)**：突破 Telegram 单个账号最多创建 20 个机器人的硬性物理限制（最高扩容至 200 个），当单号达到 20 个上限或遇到 FloodWait 时，自动平滑切换至下一个协议号接力创建；
  - **单号精准模式 (Single Mode)**：下拉直选资产池中指定账号，独立完成存量复用或差额创建（上限 20 个）。
- **运行期零停机热插拔**：动态接入（`hot_add_bot_client`）与下线（`hot_remove_bot_client`）Worker 节点，无需重启服务即可即刻参与集群调度。
- **性能基准与实战测速**：内置 10MB/100MB/1GB 真实样本单连接在线播放速率与多连接并发下载速率对比测速面板。

### 3. 媒体缩略图后台预生成与预热 (`TelegramThumbnailWorker`)
- **后台常驻静默预热**：服务就绪后自动启动后台扫描工作器，低速扫描未缓存媒体并预生成 WebP 缩略图；
- **增量媒体即时入队**：新文件入库后即刻入队异步生成，用户进入网盘即可享受封面秒开体验；
- **前台进度看板与一键预热**：Web 网盘页顶栏实时展现预热进度（如 `封面预热中 45/162 (28%)`），支持一键重新预热。

### 4. 存储与内存缓存治理中心 (`/cache`)
- **全维度监控**：磁盘总容量/已用/可用空间线性仪表、缩略图分类占用、下载目录残留文件与内存 LRU 缓存状态；
- **安全清理与 Dry-run 试运行**：
  - 严格防御路径越界，清理白名单目录；
  - 清理下载目录时严格保护 Aria2 活跃下载任务与数据库未完成任务，绝不误删进行中文件；
  - 支持 Dry-run 试运行模式，预先测算预计释放的文件数与空间；
- **生命周期策略动态配置**：支持可视化调整下载保留小时、清理间隔与缩略图保留天数。

### 5. Telegram 频道云盘与高级媒体交互 (`/drive`)
- **双模浏览视图**：16:10 现代网格封面卡片与紧凑列表视图，支持相册（媒体组）虚拟文件夹聚合展示；
- **自适应视口影院播放弹窗**：
  - 浅色毛玻璃卡片设计，黄金视口高度约束（彻底消除垂直撑破向下无限延伸的问题）；
  - 支持网页全屏展开与窗口模式自由切换；
  - 上一集/下一集快速切换（支持键盘快捷键 `←` / `→`）；
  - 自动连播开关（当前媒体播放完毕后平滑起播下一集）；
  - 0.5x~2.0x 播放倍速与画中画 (PiP) 模式；
  - 外部播放器联动：一键调起 PotPlayer、VLC、IINA 桌面播放器播放；
- **直链生态与播表导出**：单项直链一键复制、多项换行批量导出所选直链、一键导出标准 UTF-8 `#EXTM3U` 播放列表；
- **高级交互**：Shift 键区间连选、视图偏好与每页条数持久化保存。

### 6. Aria2 下载控制与全能中继
- 支持 HTTP/HTTPS、磁力链接（Magnet）与 BitTorrent 种子文件；
- 异步 WebSocket 实时双向通信，实时捕获下载进度；
- 下载完成后自动转存至 Telegram 存储频道，记录索引并生成永久访问直链；
- 本地下载文件自动定时清理，保障宿主磁盘健康。

---

## 快速开始

### 1. 准备 Telegram 参数
- `API_ID` / `API_HASH`: Telegram API 凭据。
- `BOT_TOKEN`: BotFather 创建的主 Bot Token。
- `ADMIN_ID`: 管理员 Telegram 数字用户 ID。
- `BIN_CHANNEL`: 用作 TG 频道网盘的频道 ID（通常为 `-100` 开头的数字）。

主 Bot 需要加入 `BIN_CHANNEL` 并赋予发帖、删帖等管理员权限。建议为频道设置公开用户名（如 `@your_channel`）或绑定公开讨论组，从属 Worker 机器人即可实现完全免加频道自动负载均衡。

### 2. 创建配置文件

```bash
git clone https://github.com/Lapis0x0/MistRelay.git
cd MistRelay
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
| `MAX_MESSAGE_QUEUE_SIZE` | Telegram 媒体等待队列硬上限，默认 `100`。 |
| `MULTI_BOT_TOKENS` | 额外 Bot Token 列表，用于直链读取负载均衡（可在 Web 端动态管理）。 |

### 3. Docker 部署

```bash
install -d -m 0750 db downloads cache/thumbnails
chown -R 10001:10001 db downloads cache/thumbnails
chmod 0600 db/config.yml

# 初始化管理员密码文件（首次必须通过只读文件显式提供强密码）
umask 077
openssl rand -base64 24 | tr -d '\r\n' > db/initial_admin_password
chmod 0400 db/initial_admin_password
chown 10001:10001 db/initial_admin_password

# 构建并启动服务
docker compose up -d --build
```

服务就绪后，通过浏览器访问 `http://127.0.0.1:8080`，使用管理员账号 `admin` 与 `db/initial_admin_password` 中的密码完成登录。登录后密码文件将被自动安全擦除。

---

## Web 管理端页面导航

- **`/dashboard` 系统监控仪表板**：概览指标、实时传输趋势图（ECharts）、系统负载、各 Bot 节点分流与最近动态。
- **`/downloads` 下载与任务中心**：实时下载/上传队列、历史记录、添加 HTTP/磁力/种子下载与任务控制。
- **`/drive` TG 频道云盘**：双模浏览视图、封面秒开预热指示、自适应视口影院播放弹窗、直链生态与 M3U 播放列表导出。
- **`/bots` 机器人集群管理中心**：多 Bot 负载均衡池监控、MTProto 响应延迟、全集群质量测速、单连接流播/满速下载测速（10MB/100MB/1GB）及免加频道分流治理。\n- **`/botfather` 自动铸机与扩容流水线**：协议号资产池纳管、存量机器人一键探测复用、多号跨账号自动接力突破单号 20 上限、单号精准独立铸造与运行期零停机热插拔挂载。
- **`/cache` 缓存与存储治理中心**：磁盘容量概览、各类缓存细分监控、安全清理与 Dry-run 试运行、自动清理策略配置。
- **`/settings` 系统设置与运维中心**：全模块配置表单、Docker 容器自检面板与系统日志暗色终端。

后端 REST API 完整规范详见：[`docs/backend-api.md`](docs/backend-api.md)。

---

## 部署与安全规范

- **非 root 用户运行**：默认 Compose 容器使用非特权 UID/GID `10001:10001` 运行。
- **加固容器安全**：Compose 默认启用 `read_only: true`、`no-new-privileges: true`、drop 全部 Linux capability，且严禁挂载宿主 Docker Socket。
- **反向代理模板**：生产环境建议通过 Nginx 进行 TLS 终结与反向代理，参考配置见 `deploy/nginx-mistrelay.conf.example`。
- **离线安全凭据轮换**：若发生凭据泄漏，停止服务后使用离线工具安全轮换：
  ```bash
  python3 rotate_credentials.py \
    --input /path/to/new-mistrelay-credentials.yml \
    --database db/downloads.db
  ```
- **只读激活门禁**：凭据轮换后使用 `activation_preflight.py` 验证环境一致性后再启动生产服务。

---

## 开发与测试

### Python 后端检查与单测
```bash
# 语法静态编译检查
python3 -m compileall -q app.py auth.py configer.py db.py util.py log_config.py monitor.py async_aria2_client.py thumbnail_generator.py thumbnail_worker.py botfather_creator.py session_adapter.py cache_manager.py aria2_client WebStreamer

# 执行全量单元测试
python3 -m unittest discover -s tests -p "test_*.py" -t .
```

### Vue 3 前端构建与 E2E 测试
```bash
cd web
npm install
npm run type-check
npm run build
npx playwright test
```

---

## 致谢与参考

- [TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot)
- [HouCoder/tele-aria2](https://github.com/HouCoder/tele-aria2)
- [jw-star/aria2bot](https://github.com/jw-star/aria2bot)
