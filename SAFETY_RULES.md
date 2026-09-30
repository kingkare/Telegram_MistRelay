# MistRelay 数据资产安全与灾备架构工程规范 (SAFETY_RULES.md)

本文档定义 MistRelay 流媒体网盘系统的全链路数据安全架构、高可用容灾标准、SQLite 级联保护机制与代码级铁律防御实现。

---

## 1. 架构核心与数据价值分布

MistRelay 是一个高并发 Telegram 媒体推流与私有云盘分流主从调度系统。系统核心数据包含：
1. **`tg_media`（网盘核心索引）**：
   - 记录所有由 Bot 或租户频道转发解析的音视频媒体文件元数据（`file_unique_id`、`file_id`、文件名、大小、时长、MIME 类型、Telegram 数据中心 DC 等）。
   - 数据一旦丢失，用户网盘（`/drive`）全部文件将直接显示为空，历史推流与直链全部失效。
2. **`downloads`（下载与转存记录）**：
   - 记录用户与管理员的媒体拉取、下载及外链生成历史。
   - 具有外键约束 `FOREIGN KEY (file_unique_id) REFERENCES tg_media(file_unique_id) ON DELETE CASCADE`。
3. **`users`（多租户身份与专属频道资产）**：
   - 包含普通租户与超级管理员凭据、专属私有频道 `bin_channel_id`、专属 Bot Token、分配的数据中心等。
4. **`edge_nodes`（边缘 VPS 推流分流节点池）**：
   - 包含各地已接入 VPS 的 IP、推流端口、认证 Secret、测速矩阵（Anycast CDN、上行 Egress、下行 Ingress、端到端全双工中继速率）、健康分及分配的 Bot 阵列。
5. **`sessions` 目录（Telegram MTProto 协议号凭据）**：
   - 包含全集群 80+ 个 Bot 的持久化 Pyrogram 认证 Session。

---

## 2. 灾备防御体系与分层存储架构

```
生产数据库 (/root/MistRelay-dev/db/downloads.db)
     │
     ├── 每日/手动一致性热备 (SQLite Online Backup API -> .tar.gz)
     │        │
     │        ▼
     │   工作备份目录 (/root/MistRelay-dev/db/backups/)
     │        │
     │        ├── [层级 1: 运行时快照] backup_mistrelay_YYYYMMDD_HHMMSS.tar.gz
     │        ├── [层级 2: 危险操作前镜像] safety_pre_restore_*.tar.gz
     │        └── [层级 3: 架构升级前快照] downloads-before-*.db
     │
     └── 永久金牌基线备份镜像目录 (/root/MistRelay-dev/db/backups/.immutable_baseline/)
              ├── backup_mistrelay_20260928_125911.tar.gz (chmod 444)
              └── safety_before_media_restore_1790695668.db (chmod 444)
```

### 2.1 三层不可变性机制 (Immutability Enforcement)
1. **操作系统文件权限层 (OS Permission Layer)**：
   - 金牌基线文件设置 `444`（全用户只读），防止普通进程或误执行的脚本直接重写或截断文件。
2. **微服务逻辑层 (Application Logic Layer in `backup_manager.py`)**：
   - `is_protected_backup()` 正则匹配系统基线与安全快照。
   - `delete_backup()` 强行拦截并抛出 `PermissionError`，绝不放行删除请求。
   - 自动轮转淘汰机制（Retention Policy）将所有受保护文件排除在删除候选列表外。
3. **自愈防丢机制 (Self-Healing Sync)**：
   - 系统每次读取备份列表或初始化时，自动检查 `.immutable_baseline/` 镜像目录，若工作目录中基线缺失，立刻自动复制补齐。

---

## 3. 测试隔离与运行时内核级保护

### 3.1 为什么必须沙箱隔离？
在 SQLite 数据库架构中，若测试代码未指定独立的临时数据库，`db.py` 默认会读取配置的 `downloads.db`。如果测试代码包含清理逻辑（如测试媒体去重逻辑前清空数据表），将直接清空生产活动数据库！

### 3.2 代码级双重铁律阻断
1. **Session-Level Auto-Sandbox (`tests/conftest.py`)**：
   - 在 pytest 启动时，自动生成唯一命名的临时数据库，并设置 `MISTRELAY_DB_PATH` 环境变量，自动将任何未显式隔离的测试重定向到沙箱中。
2. **SQLite Kernel Authorizer Circuit Breaker (`db.py`)**：
   - 在 `db.get_connection()` 中检测：若处于测试模式（`PYTEST_CURRENT_TEST` 或 `MISTRELAY_TEST_MODE=1`）且目标连接指向生产数据库路径：
   - 强制绑定 `conn.set_authorizer(_test_mode_authorizer)`。
   - 任何针对生产数据库的 `DELETE`、`INSERT`、`UPDATE`、`DROP_TABLE`、`ALTER_TABLE` 操作，在 SQLite 编译阶段即被直接拒绝，产生 `sqlite3.DatabaseError: not authorized` 强中断。

---

## 4. 故障响应等级与复盘标准

| 事故级别 | 定义 | 响应时间 | 处理人 | 处置标准 |
| :--- | :--- | :--- | :--- | :--- |
| **P0 致命事故** | 生产数据库被清空、灾备文件被删、关键网盘数据丢失 | 立即 (< 1 分钟) | 全员/紧急救援 | 1. 立即停止容器写入<br>2. 从基线提取数据<br>3. 采用增量并集恢复<br>4. 完整校验前端 |
| **P1 严重故障** | 边缘节点无法推流、多 Bot 阵列全部离线、验签通道阻断 | < 10 分钟 | 运维/核心开发 | 触发 OTA 远程热重载并检查 Token 状态 |
| **P2 一般异常** | 单个测试用例污染全局状态、备份轮转延迟 | 当天内修复 | 提交者 | 修复测试沙箱或配置项 |

---

## 5. 持续改进与审计

- 每月进行一次灾难恢复演练：验证从 `.immutable_baseline/` 完整还原数据至空沙箱环境的流程耗时与完整性。
- 代码审查（Code Review）中凡涉及文件删除、数据库表重构、测试套件编写的代码，必须严格对照本规范核验。
