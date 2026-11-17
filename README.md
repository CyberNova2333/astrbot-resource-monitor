<h1 align="center">AstrBot Resource Monitor</h1>

<p align="center">
  <code>Python 3.10+</code> · <code>aiohttp&gt;=3.14.5</code> · <code>AstrBot Plugin (astrbot_plugin_resource_watch)</code> · <a href="LICENSE"><code>AGPL-3.0-only</code></a>
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a> · <a href="https://astrbot-resource-monitor.cbnv.me/">在线文档站</a> · <a href="repo-docs/README.md">源码与架构指南</a>
</p>

**面向 AstrBot 的定时资源分发线路探测插件**：按目标客户端一致的内容与协议口径巡检外部配置入口、资源清单、HTTP `Range` 分片、MD5 校验和、热更版本包与 HTTPS 证书到期天数，经由多轮防抖抑制与持久化队列向聊天会话推送告警；插件严格只读、仅连接已校验公网地址，不自动修改配置也不采集宿主机 CPU/内存指标。

## 核心能力与流转机制

- **配置源现场发现与安全降级**：支持远程 `endpoint`（`entry_url` + 备用 `entry_urls`）与静态 `mirrors` 两种配置源，不在代码库保留第二份线路表或阈值；主入口失联时只借未超龄快照作 `unknown=True` 辅助诊断，绝不代为判绿。
- **十项内容与协议级探针**：避免「HTTP 200 但用户装不上」的静默故障，覆盖配置突降/版本不回退、多数清单一致性、HTTP `206` 分片验证、32 位 MD5 轮转抽检（7 天覆盖度）、流式整包核对与 TLS 到期提醒（`<14d` P2 / `<3d` P0）。
- **防刷屏状态机与 QQ 官方人工确认**：`AlertState` 实施 `M-of-N` 滑动窗口、两级 `suppress_key` 抑制与静音恢复保留；投递前逐接收者复核最新状态，并在 `qq_official` / `qq_official_webhook` 平台要求管理员以 `/线路 通知` + `/线路 确认` 核销。
- **共享宿主多防线隔离**：`PublicResolver` 钉死公网解析并逐跳检查重定向（禁 Cookie、禁环境代理、单块缓冲硬上限 `64 MiB`），群指令受 `CommandGate` 冷却、白名单与禁下整包约束，外来文本经 `render.safe()` 防伪造清洗。
- **明确边界与双周期隔离**：快巡检（默认 `300s`）与慢巡检（默认 `3600s`）各自加锁互不阻塞；插件刻意不做长期 SLA 报表、不自动切流，也不缓存宿主机或业务数据库数据。

## 能做到什么程度与明确不能做什么

| 维度 | 能做到什么程度（已实现能力） | 明确不能做什么（非目标与硬限制） |
| --- | --- | --- |
| 探针与发现 | 现场发现 `endpoint` / `mirrors`，运行 10 项 `P0/P1/P2` 探针（清单、206 Range、MD5 轮转、热更包与 TLS 到期） | **绝不采集**宿主机 CPU/内存/磁盘；**不提供**长期 SLA 可用率统计或业务数据库存储 |
| 防线与告警闭环 | 公网 IP 钉死与逐跳重定向校验（64 MiB 上限）、`M-of-N` 防抖、两级抑制、`render.safe()` 与 QQ 官方确认闭环 | **不探测**内网/回环地址（禁 `trust_env`）；群手动 `/线路 测` 强迫 `allow_heavy=False` 跳过整包 |
| 自动化与可扩展 | 双异步锁隔离；`Source` 与 `HttpClient` SPI 支持纯离线单测与自定义配置源接入 | **不自动修改**线上配置或切换 CDN 路由；仓库零内置默认地址（未配 `entry_url`/`mirrors` 即报错停用） |

```mermaid
flowchart LR
    S["配置源发现 (endpoint / mirrors)"] --> G["合理性与公网 SSRF 校验"]
    G --> P["清单 / Range / MD5 / 版本 / TLS 探针"]
    P --> A["AlertState 窗口・两级抑制・静音"]
    A --> Q["持久化 watch-state.json 队列"]
    Q --> D["逐接收者复核投递 / QQ 官方人工确认"]
```

每轮编排先从配置源实时提取线路并过滤内网/突变异常，再由快、慢两条异步调度线各自产出判定结论，经滑动窗口收敛后先落盘、再按目标会话逐一复核投递。

## 快速开始

插件通过包内相对导入加载，将仓库放入 AstrBot 的 `data/plugins/` 目录即可验证离线单测并启用（插件启动必须配置 `entry_url` 或 `mirrors`，不内置默认源）：

```sh
git clone https://github.com/CyberNova2333/astrbot-resource-monitor.git data/plugins/astrbot_plugin_resource_watch
cd data/plugins/astrbot_plugin_resource_watch
pip install -r requirements.txt
python3 -m unittest discover -s tests -t . -v
```

随后在 AstrBot WebUI 插件配置中填写 `entry_url`（或 `mirrors`）与 `notify.sessions` 完整会话 UMO，重启插件并在授权会话执行 `/线路 状态` 确认就绪（若直接复用根目录样例，请将其中的旧例键改写为现行 `fire_after_failures`、`fire_window` 与 `recover_after_successes`）。其他接入模式与交互命令如下：

| 使用场景 / 运行模式 | 入口说明 | 详细文档 |
| --- | --- | --- |
| 独立 JSON 配置文件 | 通过环境变量 `RESOURCE_WATCH_CONFIG` 指定本地 JSON（有效 WebUI 配置优先） | [配置源与参数矩阵](docs-site/docs/configuration.md) |
| 静态直连 `mirrors` 模式 | 填写 `["线路甲=https://a.example.test/"]`，速率无线上阈值保持未判定 | [两种配置源对比](docs-site/docs/configuration.md#两种配置源模式选择) |
| 群内 `/线路` 运维交互 | 支持 `状态`、`测`、`配置`、`静音`、`取消静音`、`覆盖率`、`通知`、`确认` | [安装与指令速览](docs-site/docs/index.md#常用指令速览) |
| QQ 官方机器人适配 | 填 OpenID 完整 UMO，主动发送后记 `submitted` 并待管理员查看确认 | [QQ 官方接线要点](docs-site/docs/configuration.md#qq-官方适配器qq_official--qq_official_webhook接线要点) |
| 离线校验与地址守卫 | 提交前运行 `unittest`、`compileall` 与 `check-no-endpoints.py` | [源码导览与验证](docs-site/docs/architecture.md) |

## 选型与边界 FAQ

- **这个插件会监控 AstrBot 所在主机的 CPU、内存或磁盘吗？**
  不会。所有探针均面向外部 HTTP/HTTPS 资源分发线路（配置入口、清单、`Range` 分片、热更包与 TLS 证书），不采集宿主机性能指标。

- **发现镜像损坏或入口不可达时，会自动切换线路或修改配置吗？**
  不能。插件严格分离观测权限与写权限，仅产出告警与排查线索，也不承担长期可用率 SLA 统计平台角色。

- **能否用于监控内网镜像站，或者通过宿主机环境变量代理出网？**
  不支持。`PublicResolver` 与 TLS 证书检查强制拒绝内网、回环和保留 IP，并禁用 `trust_env` 环境代理。

- **在群里手动运行 `/线路 测 <线路名>` 会一次性下载数百 MB 热更包吗？**
  不会。聊天命令触发的检查固定传入 `allow_heavy=False` 并受共享冷却限制，避免群聊复读放大镜像站带宽压力。

- **未在 AstrBot WebUI 配置 `entry_url` 或 `mirrors` 时，插件会使用内置测试地址吗？**
  不会。仓库不携带真实地址也没有内置默认源，未配合法来源时会在初始化日志明确报错停用，杜绝虚假绿灯。

## 文档与源码导航

| 读者目标 | 用户文档站（`docs-site/`） | 源码与机制指南（`repo-docs/`） |
| --- | --- | --- |
| 插件安装、完整参数矩阵与部署排错 | [起步与配置部署](docs-site/docs/index.md) · [参数与 FAQ](docs-site/docs/configuration.md) | [配置源、分层与过期降级](repo-docs/modules/sources-and-degraded.md) |
| 核对 10 项探针契约、安全护栏与扩展 | [接口与扩展契约](docs-site/docs/contracts.md) · [API 与组件参考](docs-site/api-reference/index.md) | [探针与轮转](repo-docs/modules/probes-and-rotation.md) · [安全边界与闸门](repo-docs/modules/security-and-gates.md) |
| 追踪运行主路径、告警队列与架构决策 | [原理与源码导览（含决策迁移）](docs-site/docs/architecture.md) | [一次巡检与确认流程](repo-docs/walkthroughs/one-real-run.md) · [代码地图](repo-docs/code-map.md) |
| 查阅源码证据覆盖、术语与审计风险 | — | [术语表](repo-docs/glossary.md) · [源码证据](repo-docs/references/source-evidence.md) · [质量审计](repo-docs/references/quality-review.md) |
| 了解协作成规、提交钩子与安全报告 | — | [贡献规范](CONTRIBUTING.md) · [安全声明](SECURITY.md) · [护栏说明](guardrails/README.md) |

## 许可与安全规范

- **开源协议与归属**：本项目源码依据 [GNU Affero General Public License v3.0](LICENSE)（`AGPL-3.0-only`）授权分发，作为 [AstrBot](https://astrbot.app/) 生态只读运维插件使用；请长期保留 `runtime.state_dir` 以避免重启后丢失待发通知和静音状态。
- **零端点防泄漏原则**：仓库不随源码分发任何真实入口、线路域名、会话 ID 或访问令牌，文档与样例统一使用 RFC 6761 保留域名 `example.test`。
- **提交与安全披露**：所有代码与文档变更提交前必须通过 `python3 tools/check-no-endpoints.py --verbose`，协作流程与安全上报通道见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。
