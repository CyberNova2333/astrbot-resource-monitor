---
title: 配置源、参数矩阵与排错 FAQ
description: 插件配置三层架构、WebUI 与环境变量优先级、endpoint 与 mirrors 模式选择、完整参数矩阵、QQ 官方 UMO 配置及常见部署排错。
---

# 配置源、参数矩阵与排错 FAQ

## 配置分层与加载优先级

本插件严格将配置分为互不越权的三层：**绝不把任何真实入口地址、镜像域名、会话 ID 或凭据写入版本库**。

1. **插件源码**：只保留探针算法、窗口规则与格式契约（仓库内示例域名一律采用 RFC 6761 保留域名 `example.test`）。
2. **本地部署配置**：存放「配置源在哪里」、通知会话 UMO、静音与速率策略；优先级遵循 **`_raw_config`（AstrBot WebUI 面板写入且有效） -> 环境变量 `RESOURCE_WATCH_CONFIG` 指向的本地 JSON 文件**。仅当面板配置为空或未通过校验时才回退到环境变量文件；若两者均未提供合法源，插件会在日志报错并保持未启动，**不会使用内置默认地址假装健康运行**。
3. **配置源与镜像线路本身**：由本地配置指向，每轮巡检现场提供启用的 `mirrors[]`、`settings`、`watch`、各镜像 `manifest.json` 与分块 MD5。

## 两种配置源模式选择

在 WebUI 或本地 JSON 中需在下面两种互斥模式中择一配置（两者同时存在且 `entry_url` 非空时以 `entry_url` 为准）：

| 维度 | 模式 A：`endpoint`（`entry_url`） | 模式 B：`mirrors`（本地镜像列表） |
| --- | --- | --- |
| 填写方式 | WebUI 填 `entry_url`（可选 `entry_urls`），或 JSON 中写 `source: { "type": "endpoint", "urls": [...] }` | WebUI 填 `mirrors: ["线路甲=https://a.example.test/"]`（可选 `version_files`），或 JSON 写 `source: { "type": "mirrors", ... }` |
| 适用场景 | 拥有线上统一入口 JSON，且客户端也依赖该地址发现线路与阈值 | 无中心入口，或只需直接盯着几条静态镜像域名可用性与文件完整性 |
| 阈值与热更发现 | 自动读取远端 JSON 中的 `settings.min_speed_kbps`、`client.version`、`proxy.base` 与 `watch` 段 | 无法拿到线上 `settings` 阈值（速率探针保持 `未判定`）；需手动填 `version_files`/`packages` 才测热更 |
| 入口单点特征 | 有单点；但主入口失败时可附带检查 `entry_urls` 备用出口与未过期快照线索 | 无上游配置源单点，完全直连镜像检查 |

## 完整配置参数矩阵

以下键名以运行期实际读取的 `watch/config.py` 与 `_conf_schema.json` 为准（全部参数默认值可在 WebUI 面板直接调整，也可用等效嵌套 JSON 写入 `RESOURCE_WATCH_CONFIG` 指定文件）：

| 配置路径 | 默认值 | 下限 / 约束 | 作用说明 |
| --- | --- | --- | --- |
| `entry_url` / `entry_urls` | `""` / `[]` | 须为合法公网 `http(s)` URL | 配置源 A 主入口与可选备用入口；备用仅在主入口失败时用于定位故障性质，**不会降级主入口 P0** |
| `mirrors` / `version_files` / `packages` | `[]` / `[]` / `{}` | WebUI `mirrors` 支持 `"名称=URL"` 或纯 URL；JSON 下支持 `packages` 映射 | 配置源 B；`packages` 仅在本地 JSON 配置 `source` 对象时可直接映射（如 `{"version_a.json": "a.zip"}`） |
| `notify.sessions` | `[]` | 支持列表或逗号分隔字符串 | 完整 AstrBot `unified_msg_origin`（UMO），推荐用 `/线路 状态` 在目标会话确认通畅后回填 |
| `notify.at_all_on_p0` | `true` | 布尔值 | 仅在所有启用线路同类故障升级为 `P0` 时尝试 @全体；QQ 官方平台会降级为纯文本说明 |
| `notify.prefix` | `""` | 字符串 | 实例前缀（如 `境内`、`境外`），多实例部署同一群时用于区分来源 |
| `schedule.interval_fast_seconds` | `300` | `>= 30`（秒） | 快周期（配置、清单、一致性、轮转分块）巡检间隔 |
| `schedule.interval_slow_seconds` | `3600` | `>= 60`（秒） | 慢周期（版本 JSON、热更整包触发判断、TLS 证书到期检查）巡检间隔 |
| `schedule.chunk_probes_per_cycle` | `1` | `>= 0`（块） | 每轮快周期轮转校验的分块数量；置 `0` 可关闭分块抽检 |
| `schedule.hot_package_on_version_change` | `true` | 布尔值 | 当 `version_files` 版本发生变化时触发对应 `packages` 整包流式 MD5 核对 |
| `schedule.hot_package_min_interval_seconds` | `21600` | `>= 600`（秒） | 版本未变时的整包保底重核间隔（6 小时），防止长效缓存掩盖坏包 |
| `alert.fire_after_failures` | `2` | `>= 1`，且 `<= fire_window` | 判定窗口内达到多少次失败才真正触发首次告警 |
| `alert.fire_window` | `3` | `>= 1` | M-of-N 滑动窗口大小（默认即「3 轮里坏 2 轮」） |
| `alert.recover_after_successes` | `2` | `>= 1` | 进入故障状态后连续多少轮正常才产生恢复通知 |
| `alert.remind_every_hours` | `6.0` | `>= 0.5`（小时） | 持续故障重复提醒的最小间隔，防止每轮刷屏（级别升级时立即打破间隔） |
| `alert.mute_command_admin_only` | `true` | 布尔值 | Schema 展示位；**实际命令鉴权在运行期由 `command.privileged_admin_only` 执行** |
| `degraded.probe_with_stale_config` | `true` | 布尔值 | 主入口挂掉时是否借用上次好快照探一下各镜像清单存活作为附带线索 |
| `degraded.stale_config_max_age_seconds` | `86400` | `>= 0`（秒） | 上次好快照的保质期（默认 24 小时），超龄则跳过降级诊断 |
| `command.respond_anywhere` | `false` | 布尔值 | 默认只在 `notify.sessions` 与 `allow_sessions` 内响应，防止陌生群探查线路信息 |
| `command.allow_sessions` | `[]` | UMO 列表 | 额外放行命令的会话（仅允许执行查询命令，**不会为其订阅推送告警**） |
| `command.heavy_admin_only` | `true` | 布尔值 | 控制 `/线路 测` 与 `/线路 配置` 是否仅限管理员执行 |
| `command.privileged_admin_only` | `true` | 布尔值 | 控制 `/线路 静音` 与 `/线路 取消静音` 是否仅限管理员执行（注：`/线路 确认` 始终仅限管理员） |
| `command.cooldown_seconds` | `60` | `>= 0`（秒） | 重命令全局共享冷却时间，防止连续切换重命令放大镜像流量 |
| `runtime.user_agent` | `"resource-watch/1.0"` | 非空字符串 | 故意区别于真实客户端 UA，避免在 CDN 访问日志里污染客户端安装量统计 |
| `runtime.state_dir` | `"data"` | 目录路径 | 保存 `<state_dir>/watch-state.json`（故障窗口、覆盖游标与未发队列） |
| `runtime.http_timeout_seconds` | `30.0` | `>= 5.0`（秒） | 常规配置/清单/分块请求与重定向总时限（流式整包上限另有 1800s 保护） |
| `runtime.max_body_bytes` | `4194304` | `>= 65536`（字节，硬上限 `64 MiB`） | 单次缓冲响应上限（默认 4 MiB），任何清单都无法抬高 64 MiB 硬上限 |

> **样例文件字段对齐提示**：仓库根目录 `config.example.json` 的 `alert` 段写有历史示例键 `fire_after: [2, 3]` 与 `recover_after: 2`，**运行时 `watch/config.py` 与 `_conf_schema.json` 实际读取的是 `fire_after_failures`、`fire_window` 与 `recover_after_successes`**。直接复用 JSON 样例作为本地配置时请改写为那三个现行键名。

## QQ 官方适配器（`qq_official` / `qq_official_webhook`）接线要点

1. **填完整 UMO 与 OpenID**：`notify.sessions` 和 `command.allow_sessions` 必须复制 AstrBot 里实际的完整 `unified_msg_origin`（首位是平台实例 ID，而非固定适配器类型）。QQ 官方会使用 OpenID 标识，**不能填写日常 QQ 号或 QQ 群号**；同样地，AstrBot 的管理员列表也需配置为对应用户的 OpenID。
2. **新会话或重启先发一条消息**：插件初始化后如果官方适配器实例尚未缓存上下文，先在目标会话与机器人发一条指令（例如 `/线路 状态`）建立交互路径。
3. **理解 `submitted` 与 `/线路 通知` / `/线路 确认`**：QQ 官方主动推送受到框架能力与平台配额约束。只要主动发送接口调用不报错，插件即在该目标记录 `submitted`、阻止每轮自动重发，但条目保留在待发队列；随后需由管理员在会话发 `/线路 通知` 查看、再发 `/线路 确认` 核销。

## 部署与配置排错 FAQ

**Q1：插件安装后后台没有任何定时巡检日志，也不报具体线路错？**
检查启动日志中是否打印 `[线路监控] 配置不可用，插件不会开始探测`。当 WebUI 面板未填 `entry_url` / `mirrors` 且 `RESOURCE_WATCH_CONFIG` 也未指向合法 JSON 文件时，插件刻意拒绝启动，避免在未配置状态下给出假绿；另外若配置校验报错 `fire_after_failures 不能大于 fire_window` 同样会中止启动。

**Q2：群里发送 `/线路 状态` 或 `/线路 测` 机器人完全没有反应？**
`command.respond_anywhere` 默认关闭，在未列入 `notify.sessions` 或 `command.allow_sessions` 的会话发指令时插件会静默忽略（返回空字符串），请确认群聊 UMO 字符串完整无误（注意首个分隔段是你的机器人实例 ID）。如果指令是管理员命令（如 `/线路 测`、`/线路 静音`、`/线路 确认`），则需检查发信者在 AstrBot 中的管理员配置是否使用了该平台对应的真实用户 ID / OpenID。

**Q3：为什么填写了 `mirrors` 配置源后，`线路速率` 一直显示未判定？**
这是预期契约行为。`mirrors` 模式不依赖中心入口 JSON，因此拿不到线上 `settings.min_speed_kbps` 阈值；遵循「宁可未判定也不用写死默认值判绿或误报」的原则，速率检查保持 `unknown=True`，而清单解析、`Range` 206、分块 MD5 与 HTTPS 证书探针仍正常告警。

**Q4：修改了磁盘 `config.json` 但没有生效，或者旧故障一直重复上报？**
请两步核查：第一，当 WebUI 面板写入了有效源时，`watch/config.py` 会优先消费 WebUI 配置，只有面板源无效或为空时才回退 `RESOURCE_WATCH_CONFIG` 环境变量；第二，检查 `runtime.state_dir` 是否挂载在可写且重启保留的目录，若 `watch-state.json` 每次重启被清空，插件无法记住 `AlertState` 历史与已覆盖分块游标。

**Q5：为什么 `mirrors` 模式无法在 WebUI 表单里直接配 `packages` 映射？**
AstrBot WebUI 的列表组件只能录入字符串列表，因此 WebUI 提供了 `mirrors`（支持 `名称=https://a.example.test/`）与 `version_files`；如需在无中心入口下同时对整包做流式 MD5 核对，请通过 `RESOURCE_WATCH_CONFIG` 指向本地 JSON 文件并使用 `source: { "type": "mirrors", "mirrors": [...], "version_files": [...], "packages": {...} }`。
