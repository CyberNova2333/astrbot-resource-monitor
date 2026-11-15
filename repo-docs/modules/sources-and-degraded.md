# 配置源、分层与过期降级

配置决定探针去哪里拉取资源并按什么阈值判定，核心原则是插件仓库不保存第二份线路表与阈值，而是从线上配置或本地直连列表现场发现，并在中心入口失联时只用未过期快照做降级诊断、绝不代为判绿。

在[完整运行主流程](../walkthroughs/one-real-run.md)的起点，调度循环每次都从配置层重新取回当前线路与阈值，再交由探针并发核对内容。

## 三层分离与配置入口优先级

部署运维要面对的首要压力是配置漂移：如果插件代码里抄写了一份线路列表或默认限速，线上修改配置后就会出现「监控全绿但客户端安装失败」。为此，插件把配置严格拆成三层：

| 层级 | 承载内容 | 保存位置 | 是否随仓库提交 |
| --- | --- | --- | --- |
| 插件源码 | 探针形状、校验算法与告警窗口逻辑 | 本仓库代码目录 | 是 |
| 本地插件配置 | 配置源入口、通知会话、静音开关与运行开关 | AstrBot 面板配置或本地配置文件 | 否 |
| 线上配置与线路清单 | `mirrors`、`settings`、`watch`、各线路清单及分块 MD5 | 配置源地址与各镜像服务器 | 否 |

加载入口优先读取 AstrBot WebUI 传入的配置字典；当面板未配置有效源、或加载触发 `ConfigError` 时，插件会按环境变量 `RESOURCE_WATCH_CONFIG`（或回退路径）读取部署侧 JSON 文件（参见 [config.py](../../watch/config.py) 的 `load`）。示例配置见仓库根目录样例，其中包含占位域名 `example.test`。需特别注意字段命名迁移：当前运行时与 WebUI 模式文件 `_conf_schema.json` 使用 `alert.fire_after_failures`、`alert.fire_window` 与 `alert.recover_after_successes`，而根目录历史样例 `config.example.json` 仍写有旧示例键 `fire_after` 与 `recover_after`，运行时不会读取那两个旧示例键。

## 两种配置源模式与适配扩展

`watch/sources.py` 通过统一基类 `Source` 向编排层交付规范化的 `Discovered` 快照，使下游探针不绑定具体某一份客户端配置的字段排版。目前内置两种互斥源模式（参见 [sources.py](../../watch/sources.py) 的 `build`）：

1. **`endpoint` 模式（`EndpointSource`）**：本地配置指定 `entry_url`（可选附带备用入口 `entry_urls`）。每轮请求返回 JSON 后，只要包含非空 `mirrors[]`（每条含 `base` 字段），即可提取启用的线路列表；如果响应中还包含 `settings.min_speed_kbps`、`client.version`、`proxy.base` 或 `watch.version_files` / `watch.packages`，探针会自动追加对应检查，未声明项则保持未判定（`unknown=True`），绝不自行猜测默认阈值。
2. **`mirrors` 模式（`MirrorListSource`）**：本地直接提供 `mirrors`（支持对象数组或 WebUI 的 `线路名=https://a.example.test/` 字符串列表），可选附带 `version_files` 与 `packages`。该模式不依赖上游中心入口，因此不存在入口单点故障，但因无法获取线上 `settings`，速率比较等依赖线上阈值的项将长期处于未判定状态。

若未来需要接入第三种配置格式，只需在 [sources.py](../../watch/sources.py) 新增 `Source` 子类并产出相同结构的 `Discovered` 与条目列表，[probes.py](../../watch/probes.py) 与 [runner.py](../../watch/runner.py) 无需改动判定与调度主逻辑。

## 入口失联时的备用线索与降级边界

在 `endpoint` 模式下，`entry_url` 是整条监控链的单点。如果只报一句「主入口拉不到」，值班人无法分辨究竟是托管方出口故障、线上 JSON 被改坏，还是下游所有镜像也一并宕机。因此，当主入口失败时，`Monitor` 会按以下边界补充诊断线索，但严守两条红线：

- **备用出口验证（`entry_urls`）**：仅在主入口失败后尝试访问，用来区分「主入口链路问题」和「配置文档本身损坏」；即便备用出口成功，主入口的 `P0` 告警仍不会降级，因为真实客户端只连接主 `entry_url`。
- **上一次好配置降级探测（`degraded.probe_with_stale_config`）**：只要最近一次完整配置快照距今未超过 `stale_config_max_age_seconds`（默认 `86400` 秒），插件会借用旧配置里的启用线路去探测各镜像 `manifest.json` 存活情况。但这些降级探针结论一律标记 `unknown=True`：既**不会因旧阈值判绿**，也**不会按过期线路触发独立告警**。

## 代表性案例

- **正常与主入口降级流程**：配置 `entry_url = "https://api.example.test/lines.json"`、备用 `entry_urls = ["https://backup.example.test/lines.json"]`，且 13 分钟前曾缓存一份包含 2 条线路的好配置。当本轮主入口连接超时时，`EndpointSource` 给出 `P0`「配置源可达性」失败；随后 `Monitor` 检查备用出口发现 JSON 正常，并用 13 分钟前的缓存探测那 2 条线路均能返回清单，于是把两条线索并入 P0 告警正文，提示运维优先排查主入口出口托管方，同时下游 `unknown=True` 不计入健康统计也不触发误报。
- **边界情况（缓存超龄与异常配置不晋升）**：若上述好配置已缓存超过 86400 秒，降级探测会被直接跳过；反之若主入口虽然返回 200，但被误改导致启用线路数对比基线骤减至少一半且原线路数不少于 2 条（或原 `settings` 阈值段消失），[probes.py](../../watch/probes.py) 中的 `check_config_mutation` 会标记配置突变，[runner.py](../../watch/runner.py) 拒绝将这份异常快照晋升为 `last_good_snapshot`。

## 延伸与验证

理解上游配置如何变为可执行的检查任务后，可继续阅读[十项探针判据与分块轮转覆盖](probes-and-rotation.md)了解清单与分块校验细节，或通过[代码地图](../code-map.md)定位模块修改点。本模块行为可通过 [tests/test_config.py](../../tests/test_config.py) 与 [tests/test_sources.py](../../tests/test_sources.py) 的离线测试验证，也可在仓库根目录运行：

```sh
python3 -m unittest tests.test_config tests.test_sources tests.test_runner
```

证据状态：除特别标注外，本页基于当前源码已确认。
