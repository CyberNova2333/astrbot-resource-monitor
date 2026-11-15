# 十项探针判据、多数共识与分块轮转

通用可用性探活只看 HTTP 200，而在资源分发场景中，客户端静默回退、CDN 缓存了半截文件、服务器忽略 `Range` 头返回整包、或部分镜像滞后于最新版，全都会返回 HTTP 200 却让用户无法正常安装或热更。插件按客户端同一套内容判据逐项核对，并用轮转抽样代替随机探测以真实度量覆盖度。

在[完整运行主流程](../walkthroughs/one-real-run.md)的检查阶段，快慢两套调度器分别并发调用这些探针，随后将结果交给告警状态机。

## 十项探针分级与触发边界

下表覆盖 [sources.py](../../watch/sources.py)、[probes.py](../../watch/probes.py) 与 [runner.py](../../watch/runner.py) 中的全部探针判据（级别遵循 `P0` 阻断全员、`P1` 影响功能或部分线路、`P2` 趋势与性能降级）：

| 探针名称 | 级别 | 检查内容与判定标准 | 触发告警与未判定（`unknown=True`）边界 |
| --- | --- | --- | --- |
| 配置源可达性 | `P0` | `endpoint` 模式拉取 `entry_url`，要求 HTTP 200、合法 JSON 与非空 `mirrors[]` | 区分拉不到与内容解析错；`mirrors` 模式不产生该单点 |
| 线上配置合理性 | `P0`/`P1` | 检查配置突变（启用线路突降 50% 以上且原至少 2 条、`settings` 消失）、非公网目标拦截、启用数大于 0、`client.version` 格式及不回退、`proxy.base` 以 `/` 结尾 | 禁用或缺少 `client.version` 时对应子项标 `unknown=True`；异常快照不更新基线 |
| 清单可达性 | `P1` | 带 `NO_CACHE` 头请求各启用线路 `manifest.json`，逐条验证文件名、正数 `size`、`chunk_size`、精确分块数与 32 位十六进制 MD5 | 单条损坏记录隔离点名而不中断整轮；拉不到整份清单时抑制后续同线路块/版本检查 |
| 线路一致性 | `P1` | 纯函数跨镜像比对文件大小、分块大小与全部块 MD5 指纹，要求严格多数一致 | 出现次数最多者未过半（`count * 2 <= len`）时全体标 `unknown=True`，暂停以清单为基准的块比较 |
| 块内容校验 | `P1` | 不带破缓存头发送 `Range: bytes=start-end` 拉取单片，核对实际字节长度与 32 位 MD5 | 块大小超过 `max_body_bytes` 上限时跳过并标 `unknown=True`，不计入覆盖率 |
| Range 支持 | `P1` | 要求块请求必须返回 HTTP 206 且 `Content-Range` 的区间与总长度精确匹配 | 服务器返回 HTTP 200 忽略 `Range` 头即判失败（会导致客户端退化成整包重下） |
| 线路速率 | `P2` | 将单块下载折算为 kbps，与线上 `settings.min_speed_kbps` 对比 | 未声明线上阈值（含 `mirrors` 模式）或 `chunk_size` 过小等未完成传输情况保持 `unknown=True` |
| 版本 json | `P1` | 带 `NO_CACHE` 头拉取 `watch.version_files` 声明文件，要求含版本字符串、正数 `size` 与 32 位十六进制 `md5` | 未在配置中声明 `version_files` 时跳过并标 `unknown=True` |
| 热更包整包核对 | `P1` | 依据 `watch.packages` 映射流式 `digest` 计算整包长度与 MD5，上限为 `size + 1 MiB` | 超出上限立即截断判失败；手动命令（`allow_heavy=False`）永不下载整包 |
| 证书有效期 | `P2`/`P0` | 对 HTTPS 线路实际主机与端口做公网解析与 TLS 握手，检查 `notAfter` 剩余天数 | 小于 14 天报 `P2`、小于 3 天升 `P0`；每 86400 秒探一次，握手或非公网校验异常标 `unknown=True` |

## 为什么选择 MD5、动态分块大小与差异化缓存头

客户端分发包与热更清单原本采用每块 32 位十六进制 MD5，且分块尺寸由 `manifest.json` 的 `chunk_size` 字段动态给出而非写死在客户端里。监控必须沿用完全一致的算法与尺寸口径，否则就会出现监控按 SHA-256 或固定 16 MiB 判绿、客户端却校验拒收的「假绿」现象。

此外，插件刻意区分缓存头策略：拉取 `entry_url`、`manifest.json` 和 `version_files` 时携带 `NO_CACHE`（`Cache-Control: no-cache, no-store, max-age=0` 与 `Pragma: no-cache`）以立刻捕捉配置滞后；而请求分块文件字节时**故意不加破缓存请求头**，以便真实命中边缘节点与 CDN 缓存（正是半截坏块、回源过期等真实故障的所在位置）。

## 轮转调度、快慢隔离与覆盖率计数

块抽样采用确定性轮转（`Rotation`）而非随机抽签，位于 [scheduler.py](../../watch/scheduler.py)。插件把当前清单中所有可用条目展开为 `(线路, 文件, 块序号)` 三元组队列并持久保存游标，每轮快巡检抽取 `chunk_probes_per_cycle` 个三元组；仅当请求成功收到 206 数据且内容与 MD5 核对完成时，才记录该三元组已覆盖，默认覆盖窗口为 7 天（`604800` 秒），用于支撑 `/线路 覆盖率` 的实际覆盖比例说明。网络失败、超时、`Range` 不匹配、或者因单块过大被跳过的 `unknown=True` 结果**全部不计入覆盖率**。

在并发隔离方面，[runner.py](../../watch/runner.py) 的快轮次（默认每 300 秒）与慢轮次（默认每 3600 秒）分别持有独立异步锁：

- **清单并发上限为 4**：防止线路数较多时瞬时打满目标带宽；
- **慢周期并发上限为 2**：版本检查、整包流式核对和 TLS 证书探针（每 86400 秒）互不阻塞快巡检；
- **热更整包触发条件与快重试**：当检测到版本变化、距上次成功整包核对超过 `hot_package_min_interval_seconds`（默认 21600 秒），或上一轮整包核对失败/尚在连续恢复确认期（`hot_failures` 按 `interval_fast_seconds` 快重试）时触发；若整包慢下载或 TLS 探针耗时较长期间 `last_discovered.snapshot()` 相对本轮启动时的 `disc.snapshot()` 发生变更，旧任务结果只作为当前轮次记录返回，**绝不写入新配置的 `ticker`、`last_versions` 或失败调度表**。

## 代表性案例

- **正常与 Range 降级案例**：某线路清单声明文件 `patch.bin` 的 `chunk_size = 4194304`（4 MiB）。当轮转抽到分块 0 时，探针发送 `Range: bytes=0-4194303`：若镜像返回 `206 Partial Content`、`Content-Range: bytes 0-4194303/8388608` 且 4 MiB 字节 MD5 与清单一致，则「块内容校验」与「Range 支持」均记绿并推进 7 天覆盖记录；若镜像忽略请求头直接返回 `200 OK` 并吐出完整文件，「Range 支持」立即判 `P1` 失败，提示分片能力已退化。
- **边界案例（无严格多数与未知结果）**：当只有两条启用镜像且某文件清单哈希彼此冲突（1 比 1，不满足 `count * 2 > 2`）时，`check_manifest_consistency` 将所有线路的该文件一致性判为 `unknown=True`，同时暂停以此不可信清单作为后续分块对比基线，避免随机挑一条错误线路把正确线路误报成故障。

## 延伸与验证

理解探针如何产出带抑制键和未判定标记的 `ProbeResult` 后，可前往[告警抑制窗口、持久化队列与人工确认](alert-state-and-delivery.md)了解消息如何去重及送达，或阅读[目标校验、响应上限与命令闸门](security-and-gates.md)了解所有请求共用的 SSRF 防护。探针、解析与轮转契约可通过下列测试集验证：

```sh
python3 -m unittest tests.test_discovery tests.test_probes tests.test_scheduler tests.test_runner tests.test_monitor_regressions
```

证据状态：除特别标注外，本页基于当前源码已确认。
