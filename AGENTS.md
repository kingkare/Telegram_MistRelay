# MistRelay AI 研发与运维安全铁律规范 (AGENTS.md)

> **适用范围**：所有在此代码仓库（`/root/MistRelay-dev`）中执行代码编写、重构、测试、排查、部署、磁盘维护或文件清理的 AI Agent（包括 Codex、Claude、GPT 及各类自动化代理）和人类开发者。
> **生效级别**：**HIGHEST PRIORITY（最高优先级指令）**。本规范中的所有禁止项均为系统最高安全红线，任何任务指令（包括“清理磁盘”、“释放空间”、“优化测试”、“重置环境”）均**不得**违反本规范。

---

## 🚨 1. 绝对禁区与零容忍红线 (Zero-Tolerance Red Lines)

### 🔴 红线 1：严禁删除、覆盖、截断任何灾备文件与快照
- **禁止路径**：`/root/MistRelay-dev/db/backups/` 及其所有子目录（包括 `.immutable_baseline/`）。
- **禁止模式**：严禁执行针对 `backup_*.tar.gz`、`*.db`、`safety_*`、`downloads-before-*` 等文件的 `rm`、`os.remove`、`shutil.rmtree` 或 `delete_backup()` 操作。
- **历史警示**：`backup_mistrelay_20260928_125911.tar.gz` 是全站 272 份网盘媒体文件（105.7 GB）、31 条历史下载记录、25 名租户、24 个协议号以及 5 台边缘 VPS 节点的唯一完整历史灾备基线。**一旦被删，数据永久丢失，无法挽回！**
- **磁盘清理禁区**：在任何提示“磁盘已满”或“清理旧文件”的任务中，**绝对禁止将 `db/backups/` 目录下的任何文件视为“临时文件”或“可清理缓存”**。

### 🔴 红线 2：严禁对生产数据库直接执行破坏性 SQL
- **禁止目标**：`/root/MistRelay-dev/db/downloads.db` 以及容器内挂载的 `/app/db/downloads.db`。
- **禁止操作**：绝对禁止直接执行 `DELETE FROM tg_media`、`DELETE FROM users`、`DELETE FROM edge_nodes`、`DROP TABLE`、`TRUNCATE` 或无 `WHERE` 条件的批量 `UPDATE`。
- **外键级联风险**：SQLite 外键级联开启（`PRAGMA foreign_keys=ON;`）。`downloads` 与 `uploads` 表均外键引用 `tg_media.file_unique_id (ON DELETE CASCADE)`。**一旦在生产库误删 `tg_media`，将瞬间引发全量用户下载历史与上传记录的级联雪崩清空！**

### 🔴 红线 3：严禁在未沙箱隔离的情况下运行测试
- **测试隔离铁律**：严禁任何单元测试、功能测试、基准测试连接生产数据库。
- **未沙箱直接运行 = 重大事故**：测试中对数据库进行的增删改查必须在临时数据库文件（`tempfile.NamedTemporaryFile`）或内存库（`:memory:`）中进行，运行结束后必须自动销毁。

---

## 🛡️ 2. 自动化测试强制沙箱规范 (Test Sandboxing Contract)

编写或修改任何测试代码（`tests/test_*.py`）时，**必须严格遵循以下三层防护机制**：

### 2.1 规范编写模板（测试类级别隔离）
每个使用到数据库的测试类，必须在 `setUp` 中创建独立临时数据库，并在 `tearDown` 中恢复与清理：

```python
import os
import tempfile
import unittest
import db

class ExampleFeatureTests(unittest.TestCase):
    def setUp(self):
        # 1. 创建独立临时 SQLite 文件
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        
        # 2. 保存并重定向全局 DB_PATH
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        
        # 3. 初始化沙箱表结构
        db.init_db()

    def tearDown(self):
        # 4. 严格恢复现场，防止状态污染后续测试用例
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass
```

### 2.2 全局 Pytest 会话级兜底沙箱 (`tests/conftest.py`)
- 系统已部署 `tests/conftest.py`，在 `pytest` 会话启动时自动创建隔离的 `_pytest_sandbox.db`，并将 `MISTRELAY_DB_PATH` 重定向至临时路径。
- **测试编写者依然必须在测试用例内做好自身状态的清理**，严禁依赖其他用例留下的脏数据。

### 2.3 SQLite 引擎内核级阻断防护 (`db.py`)
- `db.py` 中内置 `_test_mode_authorizer` 钩子。
- 只要运行时检测到处于测试环境（`PYTEST_CURRENT_TEST` 或 `MISTRELAY_TEST_MODE=1`），若 `DB_PATH` 指向生产数据库，SQLite 引擎层直接阻断所有 `INSERT`、`UPDATE`、`DELETE`、`DROP_TABLE`、`ALTER_TABLE` 操作并抛出 `sqlite3.DatabaseError: not authorized`。

### 2.4 全局模块 Mock 与单例状态还原
- 测试用例若修改了 `sys.modules["WebStreamer.vars"]`、`Var.MULTI_BOT_TOKENS`、`bot_mod.multi_clients` 等全局单例，必须在 `setUp` 中备份并在 `tearDown` 中恢复。
- 严禁遗留被清空的全局 `Var.MULTI_BOT_TOKENS = []`，避免污染后续多节点调度测试。

---

## 💾 3. 灾备管理与多级防御机制 (Backup Protection Architecture)

系统已建立**三层不可变容灾防御体系**：

```
/root/MistRelay-dev/db/
├── downloads.db              <-- 生产活动数据库 (WAL 模式，高频读写)
└── backups/
    ├── .immutable_baseline/  <-- [Level 1] 只读金牌灾备基线 (chmod 444，永不可删)
    │   ├── backup_mistrelay_20260928_125911.tar.gz
    │   └── safety_before_media_restore_1790695668.db
    ├── backup_mistrelay_*.tar.gz <-- [Level 2] 生产全量归档 (受保护基线拒绝删除)
    ├── safety_pre_restore_*.tar.gz <-- [Level 3] 还原/大更新前自动安全快照
    └── downloads-before-*.db  <-- 结构迁移前快照
```

### 3.1 核心代码防护策略 (`backup_manager.py`)
1. **基线保护判断**：`is_protected_backup(filename)` 会自动识别核心基线和前缀为 `safety_`、`downloads-before-` 的快照。
2. **强制拒绝删除**：`delete_backup(filename)` 针对受保护文件直接抛出 `PermissionError`，拦截任何物理删除操作。
3. **轮转策略豁免**：定时任务执行 `_enforce_retention_policy()` 时，自动将所有受保护基线和安全快照从淘汰候选列表中剔除，永不老化清理。
4. **缺失自愈机制**：`ensure_baseline_backups()` 会在列表查询时自愈检测，若工作备份目录中核心基线被意外移动，自动从 `.immutable_baseline/` 镜像还原。

---

## 🛠️ 4. 生产环境数据库变更规范 (Database Migration Protocol)

任何数据库表结构变更必须遵守非破坏性原则：
1. **仅允许向前兼容的增量变更**：
   - 允许：`ALTER TABLE {table} ADD COLUMN {col} {type} DEFAULT ...;`
   - 禁止：`DROP TABLE` 重建、`ALTER TABLE DROP COLUMN`、破坏性重命名。
2. **变更前强制安全快照**：
   在执行任何涉及生产表结构的脚本前，必须通过 `backup_manager.create_backup(prefix="safety_pre_migration")` 创建热备快照。
3. **多租户数据合并一致性**：
   新增加字段必须使用 `init_db()` 内的 `PRAGMA table_info` 幂等检测添加，确保多实例重启不会重复报错。

---

## 🧹 5. 磁盘清理与文件维护安全边界 (Safe Filesystem Maintenance)

当执行环境清理或维护时，严格遵循以下白名单与黑名单：

### ✅ 安全可清理文件（白名单）
- 虚拟环境构建缓存：`/root/.cache/pip/`、`/root/MistRelay-dev/web/node_modules/.vite/`
- Python 字节码缓存：`__pycache__/`、`*.pyc`
- 测试临时缓存：`.pytest_cache/`
- 前端打包临时目录：`/root/MistRelay-dev/web/dist_tmp/`

### ❌ 绝对禁止清理/移动路径（黑名单）
- `/root/MistRelay-dev/db/downloads.db`（生产数据库）
- `/root/MistRelay-dev/db/backups/`（全量灾备归档）
- `/root/MistRelay-dev/db/sessions/`（Telegram 协议号与 Bot MTProto Session 凭据）
- `/root/MistRelay-dev/db/jwt_signing.key`（用户身份鉴权密钥）
- `/root/MistRelay-dev/db/config.yml` 与 `config.example.yml`

---

## 🚑 6. 突发事故应急恢复标准作业程序 (SOP / Runbook)

如果遭遇人为操作失误或异常导致生产数据受损，**必须严格按以下步骤处理**：

### 步骤 1：立即冻结现场
```bash
# 停止容器以防脏数据写入
docker stop mistrelay
```

### 步骤 2：创建现场保护快照
```bash
# 无论现场多么损坏，首先对当前状态留存事故现场镜像
cp -p /root/MistRelay-dev/db/downloads.db /root/MistRelay-dev/db/backups/incident_snapshot_$(date +%s).db
```

### 步骤 3：从受保护基线提取历史数据
```bash
mkdir -p /tmp/mistrelay_restore_staging
tar -xzf /root/MistRelay-dev/db/backups/.immutable_baseline/backup_mistrelay_20260928_125911.tar.gz -C /tmp/mistrelay_restore_staging/
```

### 步骤 4：以并集增量方式恢复（绝不直接覆盖，防止丢失新注册租户与节点）
使用 Python 脚本执行基于 SQLite `INSERT OR IGNORE` 的并集迁移：
```python
import sqlite3

backup_conn = sqlite3.connect('/tmp/mistrelay_restore_staging/downloads.db')
target_conn = sqlite3.connect('/root/MistRelay-dev/db/downloads.db')

for table in ['tg_media', 'downloads', 'uploads']:
    rows = backup_conn.execute(f"SELECT * FROM {table}").fetchall()
    cols = [desc[0] for desc in backup_conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
    placeholders = ",".join(["?"] * len(cols))
    target_conn.executemany(
        f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        rows
    )
target_conn.commit()
```

### 步骤 5：重启容器与全功能健康校验
```bash
docker start mistrelay
# 校验网盘与流播数据
curl -s http://127.0.0.1:8080/api/telegram/usage
```

---

## 📌 总结：每个 AI Agent 执行操作前的自我核查清单 (Checklist)
1. [ ] 我的命令是否包含 `rm`、`delete`、`drop` 等关键词？如果有，目标路径是否避开了 `db/` 和 `db/backups/`？
2. [ ] 我的测试代码是否在 `tempfile` 沙箱中运行？是否在 `setUp` 中重定向并在 `tearDown` 中还原了全局变量？
3. [ ] 我的数据库修改是否是增量非破坏性的？是否已验证在旧数据上能平滑兼容？
4. [ ] 我是否绝对不会尝试删除或修改任何 `.tar.gz` 灾备归档？

**铁律如山，防患未然。**
