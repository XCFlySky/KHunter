# KHunter 项目协作约定（Kimi 必读）

## 项目概况
- A股量化选股系统：Flask + flask-socketio 后端（`web_server.py`），前端原生 JS（`web/static/js/`）。
- 生产部署在阿里云服务器：`/opt/khunter`（47.254.123.6，root，systemd 服务 khunter-web / khunter-scheduler）。
- Git 仓库：本地 `F:\PythonProject\KHunter`，分支 `dev/liuxincheng`，推送目标 `fork`（github.com/XCFlySky/KHunter），`origin` 为 github.com/ling-0729/KHunter。

## 铁律：代码变更流程（用户明确要求，不可变更）
**任何代码修改必须按以下顺序执行：**

1. **先改本地项目** `F:\PythonProject\KHunter` 的代码；
2. **提交并推送到 GitHub**（`git push fork dev/liuxincheng`）；
3. **再部署到服务器**：在服务器 `/opt/khunter` 执行 `git pull --ff-only`（服务器仓库已跟踪 `fork/dev/liuxincheng`），然后 `systemctl restart khunter-web`。

- ❌ 禁止直接在服务器上改代码（紧急热修除外，且修复后必须立即回同步：服务器 → 本地 → 推送 GitHub，保持三方一致）。
- 部署到服务器前必须先完成 GitHub 推送。
- 本地仓库、GitHub、服务器三方代码必须保持同一版本。
- 服务器上 `data/`（运行时数据）与 `config/config.yaml`（含密钥）允许与仓库不一致，属正常，不要从这些文件反向覆盖仓库。

## 缓存架构（2026-07-21 新增）
- `utils/redis_cache.py`：查询接口响应缓存层，Redis 优先，Redis 不可用时自动降级为进程内 TTL 缓存（30s 重连节流）。
- 配置：`config/config.yaml` 的 `redis` 节（enabled/host/port/db/password/key_prefix），环境变量 `KHUNTER_REDIS_*` 可覆盖。
- 键前缀 `khunter:api:`；`cached_api('key')` 装饰器接入，TTL 分级见 `web_server.py` 的 `_API_CACHE_TTLS`；响应头 `X-Cache: HIT/MISS` 可验证。
- 主动失效 `invalidate_api_cache()`：数据更新完成、选股保存、温度重算、风控配置变更、排名生成/重算后调用。
- 诊断接口：`GET /api/cache/status`。
- 服务器 Redis：systemd `redis-server`，maxmemory 64mb + allkeys-lru；本地 Redis 跑在 WSL2（注意 WSL IP 变化需改 config.yaml 的 redis.host）。

## SSH 辅助
- 服务器可用 paramiko 连接（密码见历史会话脚本 `%TEMP%\khunter_ssh.py`，若已清理需向用户索取）。
- 服务器有 fail2ban，连接失败时隔几秒重试。
