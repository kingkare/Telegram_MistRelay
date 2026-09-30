# Changelog

All notable changes to **MistRelay** are documented in this file.

---

## [v3.0.0] - 2026-09-30 (Major Open-Source Milestone)

**MistRelay v3.0.0** 是系统自诞生以来最重大的架构跃迁版本。系统从单实例管理员网盘全面升级为 **企业级多租户 Telegram 云盘、全球 VPS 边缘推流分流网络、TMA 移动端无缝生态与智能自动化运维中台**。

### 🌟 核心架构新增 (Major New Subsystems)

1. **多租户架构与专属存储频道物理隔离 (Multi-Tenant Cloud Drive & Channel Isolation)**
   - 支持用户通过 Telegram 私聊 `/register` 获取一次性验证码自助开通专属云盘，或由管理员在 `/users` 后台统一开户；
   - 基于协议号资产池与租户所选数据中心（DC1~DC5），全自动开通物理隔离的 Telegram 专属存储频道（`@mr_u<id>_...`）并完成主控与从属 Bot 权限编排；
   - 实现严格的 RBAC 权限隔离中间件：普通租户仅能访问自有频道媒体、自有下载队列与自有边缘节点，杜绝跨租户越权访问。

2. **全球 VPS 边缘推流节点集群与 302 动态 Ticket 智能路由 (`/edge-nodes`)**
   - 新增独立边缘推流微服务 `edge_worker/worker_server.py`，支持通过 HMAC 防篡改 Ticket 直接从 Telegram DC 拉取分片并向客户端提供 HTTP Range 流式传输，彻底释放主控服务器带宽；
   - 新增异步 SSH 自动化部署引擎 (`vps_deployer.py`)：填入 VPS IP 与 SSH 凭据即可一键完成环境初始化、systemd 守护进程配置、TLS/防火墙放行与实时部署终端日志回传；
   - 支持多维度深度测速与诊断：全球 5 大 Telegram DC 延迟矩阵探测、真实 MTProto 拉流测速、Anycast CDN 探测、上行/下行带宽基准测试及客户端就近低延迟智能匹配。

3. **Telegram Mini App (TMA) 免密鉴权与全页面移动端 PWA 适配**
   - 新增 `POST /api/auth/tma` 端点与前端 `tma.ts` SDK 桥接，在 Telegram 客户端内打开小程序即可基于 `initData` HMAC-SHA256 签名完成零操作自动免密登录；
   - 全站 11 个核心视图完成移动端流光毛玻璃响应式重构，配备底部灵动导航栏 (`AppBottomNav.vue`)、移动端抽屉菜单 (`AppMobileDrawer.vue`) 与标准 Web App Manifest (`manifest.webmanifest`)。

4. **在线一致性热备、三级不可变容灾防御与专属频道无损平移**
   - 新增 `backup_manager.py`：基于 SQLite Online Backup API 实现零停机热备，将数据库、Telegram Session 凭据、JWT 密钥与配置文件统一归档为 `.tar.gz`；
   - 建立三级容灾保护机制（`.immutable_baseline` 只读基线保护、还原前自动创建 `safety_pre_restore_*` 快照、支持 `union` 非破坏性增量并集合并与孤儿媒体自愈）；
   - 新增租户专属频道无损平移引擎 (`channel_migrator.py`)：当原协议号受限或需切换 DC 时，一键开通新频道并通过服务端 `copy_message` 极速克隆全部历史媒体，直链与缩略图无缝平滑切换。

5. **Web 端 2GB 大文件分片断点续传直传引擎 (`telegram_user_uploader.py`)**
   - 新增浏览器端本地大文件分片上传抽屉 (`DriveUploadDrawer.vue`)，默认 5MB 分片并发流式汇聚，突破网关请求体限制，直达 Telegram 2GB 单文件上限；
   - 上传完成后自动按媒体类型投递至租户专属存储频道，即时入库并触发缩略图预热。

6. **Telegram 群专属 AI 智能客服与出站隐私安全护栏 (`/customer-service`)**
   - 新增 `ai_customer_service.py`：支持在指定官方交流群内通过 `@机器人` 或引用回复触发 AI 客服解答，内置滑动窗口多轮上下文记忆；
   - 实时注入脱敏后的系统运行态指标（在线 Bot 数、边缘节点健康度、网盘统计），并配备严格的出站正则护栏（自动拦截并抹除任何 IP、Bot Token、API Key 与私钥格式）。

7. **协议号资产池安全接管与家宽代理 API 凭据自动提取 (`botfather_creator.py`)**
   - 支持一键批量安全接管协议号：自动剔除其他可疑登录设备会话、设置/轮换两步验证（2FA）云密码、取消账号重置请求并绑定本地接码；
   - 支持按协议号所属国家/地区自动匹配住宅代理（Residential Proxy）访问 `my.telegram.org` 提取开发者 `api_id` 与 `api_hash`。

8. **Pyrogram 64 位新型频道 ID 与新版 TL 构造器热补丁 (`pyrogram_patch.py`)**
   - 彻底解决 Telegram 新版超过 32 位上限的 64 位频道 ID（如 `-10040567...`）导致的 `Peer id invalid` 崩溃；
   - 修复新版 Telegram API Layer `UserFull` 未知构造器异常，提供轻量级高并发 `get_me()` 实现。

9. **全新宇宙樱花流光门户 (`/`) 与新用户交互式引导体验**
   - 新增公开产品门户页 (`landing.vue`)：集成动态樱花星云 Canvas、3D 视差倾斜仪表盘预览、实时节点健康胶囊与激光流播管线动效；
   - 新增首次登录欢迎向导 (`FirstLoginWelcomeDialog.vue`) 与全功能交互式使用指南抽屉 (`UserGuideDrawer.vue`)。

10. **三层自动化测试沙箱与研发安全铁律体系**
    - 建立 `tests/conftest.py` 会话级自动沙箱与 `db.py` SQLite 内核级 `_test_mode_authorizer` 钩子，从引擎底层杜绝测试代码误触生产数据库；
    - 全量 353 项后端单元与集成测试、Playwright 端到端测试 100% 验证通过。

---

## [v2.2.5] - 2026-04-20

- 新增 Telegram 私密/受限频道自动化采集与无痕洗白转存引擎 (`private_channel_harvester.py`)；
- 新增 Telegram 动态数据中心分区（DC1~DC5）三级亲和评分调度与单流多 Bot 条带化负载均衡；
- 新增 @BotFather 双模自动化铸机流水线与运行期零停机热插拔；
- 新增 `TelegramThumbnailWorker` 后台静默缩略图预热与 `/cache` 统一存储治理中心。
