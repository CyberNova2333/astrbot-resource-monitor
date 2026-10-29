# 代码地图

先读[一次真实操作的阶段交接](walkthroughs/one-real-run.md)，再按这里的职责定位。覆盖范围为 一轮配置发现和内容检查到 QQ 官方通知查询与确认；这不是全仓库架构清单。

| 路径 | 职责 | 关键代码 | 与主流程的关系 |
| --- | --- | --- | --- |
| 根 `main.py` | AstrBot 框架与通知接线 | [ResourceWatch](../main.py)、`_flush_outbox`、`_pending_notification`、`_confirm_notification` | 启动巡检、持久化队列、发送与人工确认 |
| `watch/` 来源与判据 | 发现当前配置并检查内容 | [runner.py](../watch/runner.py)、`sources.py`、`discovery.py`、`probes.py`、`http.py` | 读取清单、执行检查、产出结果；各探针细节未展开 |
| `watch/` 状态与展示 | 失败窗口、调度、存储及命令 | [state.py](../watch/state.py)、`scheduler.py`、`store.py`、`commands.py`、`render.py`、`models.py`、`config.py` | 推进通知状态，控制发送与命令权限 |
| `tests/` | 离线 HTTP 与框架替身 | [通知投递](../tests/test_delivery.py)、[官方平台](../tests/test_qq_official.py)、`astrbot_stub.py`、`fakes.py` | 核对保存、提交与确认边界 |
| `tools/` | 现有地址/分支守卫 | [地址检查](../tools/check-no-endpoints.py)、`check-branch-hygiene.py` | 发布前约束索引，钩子不在业务主流程内 |

## `watch/`

| 重要代码 | 功能 | 关键符号 | 调用方 / 使用方 |
| --- | --- | --- | --- |
| `runner.py` | 一轮发现、判据汇总与告警输入 | `Monitor.run_cycle` | ResourceWatch；runner/monitor 回归 |
| `state.py` / `scheduler.py` | 窗口、恢复、静音与抽样调度 | `AlertState` / `Rotation` / `Ticker` | Monitor；状态和调度回归 |
| `sources.py` / `probes.py` / `http.py` | 当前依据和内容/公网传输边界 | `Source` / `HttpClient` | Monitor；离线替身测试 |
| `store.py` / `commands.py` / `render.py` | 状态 IO、命令权限与文本输出 | 框架入口持有队列，本页不逐函数展开 | main.py；投递和官方平台回归 |

## `tests/`

| 重要代码 | 功能 | 关键符号 | 调用方 / 使用方 |
| --- | --- | --- | --- |
| `test_delivery.py` | 恢复/静音与每接收者复核 | `test_recovery_during_first_recipient_discards_same_failure_for_next_recipient` | unittest；框架替身 |
| `test_qq_official.py` / `test_plugin_loading.py` | 平台元数据、人工确认、包内导入 | `QQOfficialTests` | unittest；无真实平台连接 |

## `tools/`

| 重要代码 | 功能 | 关键符号 | 调用方 / 使用方 |
| --- | --- | --- | --- |
| `check-no-endpoints.py` | 地址与凭据不入库约束 | 独立命令入口，不是探针 | 维护者、pre-push 和 CI |
| `check-branch-hygiene.py` | 分支纪律检查 | `--can-branch` | 维护者；本轮未操作分支 |

## 修改入口与验证

配置依据改变从 `watch/sources.py`、`watch/config.py` 和 `watch/runner.py` 开始，检查来源与配置回归。告警窗口、恢复或抑制改变检查 `watch/state.py` 与状态回归。平台投递改变集中在 `main.py`，必须同时核对 delivery、QQ 官方和包加载测试，保留逐接收者状态复核。

状态落盘由 `watch/store.py` 和框架入口共同使用；不能因持久化失败就丢通知。HTTP 公网与重定向限制另从 `watch/http.py` 和连接层回归核对。

## 覆盖范围

不逐项覆盖所有探针算法、慢周期整包下载和每个平台适配器；没有真实 AstrBot/QQ 交互或云端线路验收，不提供自动修复或内网监控。

源码链接指向仓库文件。独立文档站不携带这些文件；可按表中的精确路径在克隆中查找。需要确认哪些代码已经逐段核对，查看[证据覆盖记录](references/source-evidence.md)。

证据状态：除特别标注外，本页基于当前源码已确认。
