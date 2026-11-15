# 代码地图

先读[沿一次真实巡检与确认走到底](walkthroughs/one-real-run.md)建立端到端心智模型，再按本页职责表定位代码、配置模式与离线回归测试。

| 路径 | 职责 | 关键代码 | 与主流程的关系 |
| --- | --- | --- | --- |
| `main.py` 根插件入口 | AstrBot 生命周期、命令入口、持久化出站与插件元数据 | [main.py](../main.py)、[_conf_schema.json](../_conf_schema.json)、[metadata.yaml](../metadata.yaml) | 托管后台快慢调度循环、管理员交互、队列落盘与 QQ 官方逐会话确认 |
| `watch/` | 配置源、十项探针、轮转调度、状态收敛与安全净化 | [runner.py](../watch/runner.py)、[probes.py](../watch/probes.py)、[state.py](../watch/state.py)、[http.py](../watch/http.py) | 执行配置发现、内容与 TLS 检查、抑制窗口与出群过滤 |
| `tests/` | 离线单元测试与框架/网络假实现 | [fakes.py](../tests/fakes.py)、[astrbot_stub.py](../tests/astrbot_stub.py)、[test_runner.py](../tests/test_runner.py) | 脱离真实机器人宿主和公网镜像验证配置、探针、状态机、投递与守卫边界 |
| `tools/` | 地址与凭证防泄漏扫描、提交与分支钩子 | [check-no-endpoints.py](../tools/check-no-endpoints.py)、[commit_msg.py](../tools/githooks/commit_msg.py) | 在本地钩子和 CI 阶段阻断真实域名、令牌及敏感历史意外提交 |

## `watch/`

| 重要代码 | 功能 | 关键符号 | 调用方 / 使用方 |
| --- | --- | --- | --- |
| `config.py` / `sources.py` / `discovery.py` | 本地配置兜底、配置源抽象与清单解析 | `load`、`build`、`EndpointSource`、`MirrorListSource`、`parse_manifest` | `main.py`、`Monitor`；见[配置源与降级说明](modules/sources-and-degraded.md) |
| `probes.py` / `scheduler.py` / `runner.py` | 十项探针、7 天覆盖轮转与快慢任务调度 | `Monitor.run_cycle`、`Rotation`、`Ticker`、`HotPackagePolicy` | `main.py` 后台循环；见[探针判据与轮转](modules/probes-and-rotation.md) |
| `state.py` / `store.py` | 窗口触发、两级抑制、静音留存与原子存储 | `AlertState`、`Notification`、`load_json`、`save_json` | `Monitor._notify`、`main.py`；见[告警状态与投递](modules/alert-state-and-delivery.md) |
| `http.py` / `commands.py` / `render.py` | 公网连接绑定、重命令冷却与防伪造输出 | `validate_public_url`、`PublicResolver`、`CommandGate`、`safe`、`clamp` | 探针层与命令入口；见[安全边界与命令闸门](modules/security-and-gates.md) |

## `tests/`

| 重要代码 | 功能 | 关键符号 | 调用方 / 使用方 |
| --- | --- | --- | --- |
| `test_config.py` / `test_sources.py` / `test_discovery.py` | 参数归一化、源模式切换、清单与版本字段校验 | `LocalConfigTest`、`SourceShapeTest`、`ManifestParseTest` | `unittest` 离线运行，不访问真实配置入口 |
| `test_probes.py` / `test_scheduler.py` / `test_runner.py` / `test_monitor_regressions.py` | 十项探针、轮转覆盖、入口失联降级与配置突变保护 | `ChunkProbeTest`、`RotationTest`、`EntryDownDiagnosisTest`、`MonitorRegressions` | `unittest` 配合 `FakeClient`，不消耗实际带宽 |
| `test_state.py` / `test_state_regressions.py` / `test_delivery.py` / `test_qq_official.py` | 窗口收敛、静音恢复、逐接收者复核与 QQ 官方确认 | `FireAndRecoverTest`、`DeliveryTests`、`QQOfficialTests` | `unittest` 配合 `astrbot_stub`，不连真实官方接口 |
| `test_commands.py` / `test_render.py` / `test_network_regressions.py` / `test_plugin_loading.py` | 权限冷却、文本防注入、SSRF/重定向防护与相对导入 | `InjectionTest`、`PublicNetworkBoundaryTest`、`PluginLoadingTests` | 其中 5 项 `AiohttpBoundaryTest` 需安装 `aiohttp` 后执行 |
| `test_guardrail_endpoints.py` / `test_guardrail_regressions.py` | 示例域名守卫、敏感路径与提交作用域检查 | `GuardrailEndpointTests`、`EndpointSyntaxTests` | CI 与维护者核验 `tools/` 及 `guardrails/` |

## `tools/`

| 重要代码 | 功能 | 关键符号 | 调用方 / 使用方 |
| --- | --- | --- | --- |
| `check-no-endpoints.py` | 扫描仓库文本，拦截非白名单域名、凭据与禁止后缀 | 命令行入口，非运行时探针 | pre-push 钩子、CI 与文档发布前自检 |
| `tools/githooks/commit_msg.py` / `check-branch-hygiene.py` | 强制中文提交前缀、分支规范与维护策略 | `_msgrules`、`_branchrules` | 本地 Git 钩子与分支卫生自检 |

## 修改入口与验证

调整配置字段或来源格式时，需同步核对 `watch/config.py`、`_conf_schema.json`、`watch/sources.py` 与 `tests/test_config.py`、`tests/test_sources.py`；修改探针判据、多数基准或轮转策略时，从 `watch/probes.py`、`watch/scheduler.py` 与 `watch/runner.py` 入手并运行对应回归。涉及通知收敛、状态持久化与平台适配时，重点核查 `watch/state.py`、`watch/store.py` 与 `main.py` 中的 `_flush_outbox`、`_discard_stale`、`_pending_notification` 及 `_confirm_notification`，并重跑投递、QQ 官方和包加载测试。修改任何外链、命令权限或出群渲染时，必须同时覆盖 `watch/http.py`、`watch/commands.py`、`watch/render.py` 以及端点扫描脚本 `tools/check-no-endpoints.py`。

## 覆盖范围

本指南覆盖 `main.py` 宿主接线、`watch/` 核心十项探针与状态投递全链路，以及 `tests/`、`tools/` 的离线验证体系。明确排除且由插件刻意不做的内容包括：长期可用率 SLA 统计报表、外部上游或托管方主动控制、自动切换或改写线上配置的自愈操作，以及未经部署侧真机校验的 QQ 官方或公网镜像送达担保。

需要核对每项源码结论的遍历证据与测试情况，可查看[源码证据与验证覆盖](references/source-evidence.md)。

证据状态：除特别标注外，本页基于当前源码已确认。
