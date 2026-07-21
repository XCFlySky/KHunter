# KHunter 项目协作约定（Kimi 必读）

## 项目概况
- A股量化选股系统：Flask + flask-socketio 后端（`web_server.py`），前端原生 JS（`web/static/js/`）。
- 生产部署在阿里云服务器：`/opt/khunter`（47.254.123.6，root，systemd 服务 khunter-web / khunter-scheduler）。
- Git 仓库：本地 `F:\PythonProject\KHunter`，分支 `dev/liuxincheng`，推送目标 `fork`（github.com/XCFlySky/KHunter），`origin` 为 github.com/ling-0729/KHunter。

## 铁律：代码变更流程（用户明确要求，不可变更）
**任何代码修改必须按以下顺序执行：**

1. **先改本地项目** `F:\PythonProject\KHunter` 的代码；
2. **提交并推送到 GitHub**（`git push fork dev/liuxincheng`）；
3. **再部署到服务器**（从 GitHub 拉取或上传本地已提交版本）。

- ❌ 禁止直接在服务器上改代码（紧急热修除外，且修复后必须立即回同步：服务器 → 本地 → 推送 GitHub，保持三方一致）。
- 部署到服务器前必须先完成 GitHub 推送。
- 本地仓库、GitHub、服务器三方代码必须保持同一版本。

## SSH 辅助
- 服务器可用 paramiko 连接（密码见历史会话脚本 `%TEMP%\khunter_ssh.py`，若已清理需向用户索取）。
- 服务器有 fail2ban，连接失败时隔几秒重试。
