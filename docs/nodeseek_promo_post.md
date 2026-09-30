# 【重大开源】MistRelay v3.0 发布：多租户 TG 频道云盘 + 全球 VPS 边缘推流网络，彻底解放主控带宽！

各位 NodeSeek 的大佬、鸡友、自建党们大家好！

今天非常荣幸向大家带来 **MistRelay v3.0.0** 重大版本的开源发布！🎉

很多 MJJ 手里都有不少 Telegram 频道用来存电影、动漫、大文件，或者用各种 TG Bot 做中继流媒体播放。但大家在实际折腾过程中，是不是经常遇到这几个要命的痛点：
1. **主控小鸡带宽跑满**：好不容易在低配小鸡上搭了个 TG 直链中继，在线播放几部 4K/1080P 视频，主控小鸡的几百兆带宽瞬间被干爆，月流量直接见底；
2. **单 Bot 限流严重**：只要并发稍微高一点，或者拖动几次进度条，Telegram 官方直接甩一脸 `FloodWait`，全员卡死；
3. **跨洋 DC 握手极慢，播放频繁微卡顿**：Telegram 官方数据中心分布在美西(DC1)、欧洲(DC2/DC4)、美东(DC3)和新加坡(DC5)。如果你的媒体在 DC5，Bot 却跑在欧美小鸡上，跨洋重授权与拉流延迟高到怀疑人生；
4. **受限频道无法保存**：好不容易找到一个私密或者开了“禁止转发/保存”的宝藏频道，想备份却发现根本存不下来；
5. **大文件网页上传限制**：浏览器上传大文件动辄被 Nginx / Cloudflare 的请求体大小限制掐断。

为了彻底解决这些痛点，经过数个月的高强度重构，我们把 MistRelay 从早期的单机脚本，彻底打造成了一个 **企业级多租户 Telegram 频道云盘 + 全球 VPS 边缘推流分发网络 + Aria2 离线下载中台**！

手头有吃灰廉价小鸡（RackNerd、Cloudcone、Hetzner、甲骨文、BuyVM 等）的鸡友，现在可以让它们全部上岗作为**边缘推流节点**了！

---

## 🌟 v3.0 核心黑科技亮点

### 1. 🌐 全球 VPS 边缘推流网络（Edge Worker 集群）：主控流量近乎为 0！
- **去中心化推流架构**：自研独立边缘推流微服务（`edge_worker/worker_server.py`），部署在你吃灰的各大 VPS 节点上。
- **302 智能调度与防篡改 Ticket**：主控服务器仅负责向客户端签发携带 HMAC 签名的有时效防伪 Ticket，客户端通过 302 自动重定向到就近的边缘节点。
- **流量彻底旁路**：边缘节点直接向 Telegram DC 拉取分片并向播放器输出 HTTP Range 流，**主控服务器零流量中继负担**，百兆小鸡也能轻松扛起数百人并发看片！
- **SSH 异步一键自动化纳管**：后台输入 VPS IP 与 SSH 密码，全自动完成环境初始化、systemd 守护进程与防火墙配置，部署日志实时回传。
- **全方位网络测速诊断**：内置全球 5 大 DC 延迟矩阵、MTProto 真实拉流测速、Anycast CDN 诊断与全双工中继速率测试。

### 2. ⚡ Telegram DC 原生亲和打分（DC-Aware）与免加频道只读集群
- **三级亲和调度算法**：主控自动探测媒体所在的物理数据中心（DC1~DC5），按照 `一级同区原生 (0.0 惩罚) -> 二级热会话复用 (0.8) -> 三级跨区溢出 (2.0)` 算法智能分流，高清秒起播。
- **单流多 Bot 条带化并发预取**：同一条视频并发切片拉取时，优先聚合目标 DC 的同区 Bot 条带池，彻底消除跨洋冷节点 `ExportAuthorization` 握手引发的队头阻塞与微卡顿。
- **从机 Worker 免加频道**：集群中的几十个 Worker 机器人无需逐一人工添加到频道中！只要主控连接公开 Handle，从机通过 MTProto 自动解析 Peer 激活免加只读分流模式（`no_join_resolved`）。
- **Pyrogram 64 位 Channel ID 深度热补丁**：内置 `pyrogram_patch.py`，彻底解决 TG 新型 64 位超大频道 ID 导致的 `Peer id invalid` 崩溃及新版 API Layer 构造器兼容问题。

### 3. 🏢 物理隔离多租户架构与 Telegram `/register` 验证码开户
- **私聊极速开户**：普通用户私聊主控 Bot 发送 `/register` 即可获取 6 位动态验证码，在 Web 登录页直接自助开通独立云盘，并自选存储数据中心（DC1~DC5）。
- **专属存储频道全自动编排**：系统从协议号资产池调配对应 DC 的健康母号，全自动创建 `@mr_u<id>_...` 专属物理隔离频道并配置集群权限。
- **严格 RBAC 权限隔离**：租户只能看到和操作自己的文件、任务与自建边缘小鸡，物理级数据隔离。

### 4. 📤 浏览器 2GB 大文件 5MB 分片流式断点直传
- 前端自研分片上传抽屉（`DriveUploadDrawer.vue`），支持本地拖拽、批量并发上传与断点续传。
- 采用 5MB 流式分片汇聚，轻松穿透任何反向代理与 CDN 限制，直接吃满 Telegram 官方 2GB 单文件上传上限，并自动入库预生成 WebP 缩略图封面。

### 5. 📱 Telegram Mini App (TMA) 免密鉴权与全端毛玻璃 PWA
- **TMA 零操作秒登**：在 Telegram 客户端内点击应用菜单，基于官方 `initData` 的 HMAC-SHA256 签名算法自动完成免密登录与开户。
- **移动端流光毛玻璃体验**：全站 11 个管理视图移动端自适应重构，配备灵动底栏、手势抽屉与标准 PWA 清单，添加到手机主屏幕就是独立 App。

### 6. 🕵️ 私密/受限频道无痕洗白与转存引擎
- 支持解析私密频道区间链接（`t.me/c/<id>/100-200`）与邀请链接。
- **双模自动降级**：未受限消息执行 `fast_copy` 零流量服务端秒传；禁止转发受限频道自动调用底层流式下载破除限制并重新上传。
- **广告无痕净化**：自动抹除“转发自”来源头，自动净化原配文与文件名中的第三方引流广告、`@username` 与外部链接，自动追加本频道落款。

### 7. 🛡️ 在线一致性热备、三级容灾防御与频道无损平移
- 基于 SQLite Online Backup API 实现不停机在线热备（打包数据库、Session 凭据、JWT 密钥与配置），配合 Level 1 只读金牌基线（`chmod 444`），误删自愈恢复。
- **专属频道无损平移（Channel Migrator）**：母号遇到风控或想换机房？一键调配新号开通新频道，通过服务端 `copy_message` 极速镜像全部历史文件并原子切换指针，前台直链零感知！

### 8. 🤖 Telegram 群专属 AI 智能客服中台
- 支持在交流群内通过 `@机器人` 或引用回复唤醒 AI 客服，带滑动窗口多轮上下文记忆。
- 实时接入系统运行态指标（在线 Bot 数、边缘节点健康度），内置出站敏感信息正则拦截护栏，自动阻断并脱敏任何服务器 IP、Bot Token 与私钥。

---

## 📸 界面高清图赏

### 宇宙樱花流光门户首屏与架构全景
![Landing Preview](https://raw.githubusercontent.com/qianlong520/Telegram_MistRelay/main/docs/assets/landing-preview.png)

![Landing Features](https://raw.githubusercontent.com/qianlong520/Telegram_MistRelay/main/docs/assets/landing-preview-features.png)

### 移动端与 Telegram Mini App (TMA) 响应式
| 移动端仪表盘 | 移动端 TG 云盘 | 移动端任务中心 | 移动端抽屉菜单 |
| :---: | :---: | :---: | :---: |
| ![Mobile Dashboard](https://raw.githubusercontent.com/qianlong520/Telegram_MistRelay/main/docs/assets/mobile/mobile-dashboard.png) | ![Mobile Drive](https://raw.githubusercontent.com/qianlong520/Telegram_MistRelay/main/docs/assets/mobile/mobile-drive.png) | ![Mobile Downloads](https://raw.githubusercontent.com/qianlong520/Telegram_MistRelay/main/docs/assets/mobile/mobile-downloads.png) | ![Mobile Drawer](https://raw.githubusercontent.com/qianlong520/Telegram_MistRelay/main/docs/assets/mobile/mobile-drawer.png) |

---

## ⚡ 3 分钟 Docker Compose 极速搭建

系统已完全容器化封装，默认使用非特权用户（UID 10001）运行，drop 全部 Linux capability，安全加固。

### 1. 克隆代码与初始化环境
```bash
git clone https://github.com/qianlong520/Telegram_MistRelay.git
cd Telegram_MistRelay

# 创建持久化目录并赋权
install -d -m 0750 db db/backups db/sessions downloads cache/thumbnails
chown -R 10001:10001 db downloads cache/thumbnails

# 复制配置文件模板
cp db/config.yml.example db/config.yml
chmod 0600 db/config.yml
```

### 2. 填写核心参数 (`db/config.yml`)
打开 `db/config.yml`，填入必填项：
```yaml
API_ID: 12345678                   # my.telegram.org 申请的 API ID
API_HASH: your_api_hash_here       # my.telegram.org 申请的 API Hash
BOT_TOKEN: 123456:ABC-DEF1234ghI   # @BotFather 申请的主 Bot Token
ADMIN_ID: 123456789                # 管理员的 Telegram 数字用户 ID
BIN_CHANNEL: -100xxxxxxxxxx        # 存储频道 ID (主 Bot 需加入并给管理员权限)

UP_TELEGRAM: true
SAVE_PATH: /data/downloads
RPC_SECRET: replace-with-openssl-rand-hex-32-output
RPC_URL: localhost:6800/jsonrpc

ENABLE_STREAM: true
STREAM_PORT: 8080
STREAM_BIND_ADDRESS: 0.0.0.0
STREAM_FQDN: your-domain.com       # 你的主控公网域名或服务器 IP
STREAM_ALLOWED_USERS: "123456789"
```

### 3. 生成初始管理员强密码并启动
```bash
# 生成首次随机强密码文件（首次登录成功后系统会自动安全擦除该文件）
umask 077
openssl rand -base64 24 | tr -d '\r\n' > db/admin-password
chmod 0400 db/admin-password
chown 10001:10001 db/admin-password

# 启动容器
docker compose up -d --build
```

容器启动后，浏览器直接访问 `http://你的IP:8080`：
- 查看 `db/admin-password` 中的密码，使用账号 `admin` 登录；
- 进入 `/edge-nodes` 页面，直接输入你其他吃灰 VPS 的 IP 和 SSH 凭据，一键部署边缘分流微服务；
- 进入 `/botfather` 页面，导入存量 Telegram 账号即可一键自动批量铸造集群 Worker 机器人。

---

## 🔗 开源地址与交流反馈

- 📦 **GitHub 仓库**：[https://github.com/qianlong520/Telegram_MistRelay](https://github.com/qianlong520/Telegram_MistRelay)
- 🏷️ **当前最新版本**：`v3.0.0`
- 🌐 **在线演示体验站**：`[点击体验演示站 / 待填入]`
- 💬 **Telegram 官方交流群**：`[点击加入 TG 交流群 / 待填入]`

如果这个项目对你的吃灰小鸡或者 Telegram 云盘折腾有所帮助，欢迎大家去 GitHub 点个 ⭐️ **Star** 支持一下开源作者！

各位 MJJ 在部署过程中遇到任何网络、DC 调度或边缘推流问题，欢迎在楼下留言讨论，有问必答！也欢迎大家贴出自己的各地区 VPS 拉流测速成绩单！🍻
