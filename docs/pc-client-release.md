# MistRelay PC 客户端发布说明

本文面向开发和发布人员，说明 PC 客户端 P0 版本的构建、测试和打包流程。

## 1. 前置条件

Windows 打包机需要准备：

- Node.js 20+ 和 npm。
- Rust stable、Cargo、rustup。
- Tauri v2 所需 Windows 构建工具。
- 可选：`zip` 或 PowerShell `Compress-Archive`，用于生成便携包。

Linux 环境只能做前端检查；若要运行 Tauri build，需要安装 Rust/Cargo 以及 Tauri Linux 依赖，例如 WebKitGTK 和 librsvg。

## 2. 检查命令

在 `web/` 目录运行：

```bash
npm run type-check
npm run build
npm run check
```

PC 完整构建检查：

```bash
npm run check:pc
```

`check:pc` 会依次执行类型检查、Vite build 和 Tauri build。当前容器若没有 Cargo，会在 `tauri build` 阶段失败，错误通常是无法运行 `cargo metadata`。

## 3. E2E 测试

测试脚本：

```bash
npm run test:e2e:pc-drive -- --list
npm run test:e2e:downloads -- --list
npm run test:e2e:pc-smoke -- --list
npm run test:e2e -- --list
```

实际运行截图和浏览器测试前，需要安装 Playwright 浏览器：

```bash
npx playwright install chromium
```

测试覆盖：

- 万级网盘数据和 `1100`、`1366`、`1920` 宽度布局截图检查。
- 1/4/8 线程下载、1/2/4 全局并发、Range fallback、取消、重试、磁盘不足模拟。
- 登录、浏览、搜索、相册、预览、下载、删除取消、设置线程和并发的主流程冒烟测试。

## 4. Windows 打包

PowerShell：

```powershell
.\dev-scripts\build-pc-client.ps1
```

Bash / Git Bash：

```bash
./dev-scripts/build-pc-client.sh
```

跳过前端检查：

```powershell
.\dev-scripts\build-pc-client.ps1 -SkipChecks
```

```bash
./dev-scripts/build-pc-client.sh --skip-checks
```

脚本流程：

1. 读取 `web/package.json` 版本。
2. 执行 `npm run check`。
3. 执行 `npm run tauri:build`。
4. 使用 Tauri NSIS bundle 输出安装包。
5. 将 release exe 打成 zip 便携包。

产物路径：

- 安装包：`web/src-tauri/target/release/bundle/nsis/`
- 便携包：`web/src-tauri/target/release/bundle/portable/MistRelay-PC-Client-<version>-windows-x64-portable.zip`

## 5. 发布前清单

- `npm run check` 通过。
- `npm run tauri:build` 在 Windows 打包机通过。
- PC smoke、网盘布局、下载并发测试可运行或已在 CI 通过。
- 安装版可启动、登录、浏览、下载。
- 便携版解压后可启动。
- 设置页不出现后台管理配置。
- 文档中的已知限制与当前实现一致。

## 6. P0 已知限制

- 暂停、续传和自动更新延后到 P1。
- 目录选择、另存为、打开文件/文件夹需要目标平台桌面命令完整可用。
- 系统通知基于 Web Notification 权限，可能被系统或 WebView 拦截。
- 当前 PC 客户端隐藏管理入口，但服务端普通用户权限模型仍是后续工作。
