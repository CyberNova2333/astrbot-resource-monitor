---
title: 原理与源码导览（含决策迁移）
description: 端到端单轮运行机制、交互式架构拓扑、模块代码地图、离线验证矩阵，以及关键架构决策记录（ADR）与版本迁移指南。
---

# 原理与源码导览（含决策迁移）

## 一次真实运行是怎样走通的

每当快周期（默认 300s）或慢周期（默认 3600s）到达，或管理员执行指定命令时，请求按以下五步穿过核心模块（源码级逐步骤推导见仓库根目录 `repo-docs/walkthroughs/one-real-run.md`）：

1. **取回当前配置依据（`watch/config.py` -> `watch/sources.py`）**：在插件初始化阶段将 AstrBot WebUI 字典或 `RESOURCE_WATCH_CONFIG` JSON 规范化为 `LocalConfig`；每轮启动时由 `Source.discover` 提取 `Discovered` 快照。若主入口失败，编排器再调用 `entry_urls` 备用出口与保质期内的 `last_good_snapshot` 补充 `unknown=True` 排查线索，但绝不用旧配置判绿。
2. **安全过滤与基准确认（`watch/probes.py`）**：拦截启用数骤降一半以上、阈值段消失或版本回退的异常配置并阻止更新基准；对所有镜像地址执行公网合法性预检后，以 `Semaphore(4)` 并发拉取 `manifest.json`，并经由 `check_manifest_consistency` 确立严格多数有效条目。
3. **快慢探针分流执行（`watch/runner.py`、`watch/scheduler.py`）**：
   - 快轮次沿 `Rotation` 确定的 `(线路, 文件, 分块)` 三元组抽样拉取分块，核对 206 `Range` 与 MD5，合格即推进 7 天覆盖统计。
   - 慢轮次在独立异步锁与 `Semaphore(2)` 下核对 `version_files`、按版本变动或间隔保底执行整包流式 MD5（手动命令传入 `allow_heavy=False` 强制禁用整包），以及每天一次对 HTTPS 主机校验 TLS 余期；若下载耗时期间配置已发生变化，旧任务结果不写回新配置调度状态。
4. **告警收敛与持久化存储（`watch/state.py`、`watch/store.py`）**：将带两级 `suppress_key` 与 `unknown` 标志的结果送入 `AlertState` 滑动窗口，生成去重或恢复通知，并将窗口状态、覆盖游标与待发 `outbox` 一并原子保存至 `<state_dir>/watch-state.json`。
5. **逐接收者复核与平台确认（`main.py`）**：投递循环 `_flush_outbox` 在向每个目标群发送前都重新调用 `_discard_stale` 核验当前是否静音或故障已恢复。对于 `qq_official` / `qq_official_webhook`，调用成功后仅记为 `submitted` 并改写为纯文本，必须由管理员在对应会话先后执行 `/线路 通知`（绑定查看者与条目 ID）和 `/线路 确认` 正式消警。

## 架构交互全景图

<DiagramFrame
  src="/diagrams/monitor-architecture.html"
  title="宿主集成、SSRF 守卫与出站投递全景（支持拖拽与缩放）"
  aspect="900 / 408"
  new-tab-label="在新窗口全屏打开"
/>

> **读图对照提示**：上图反映 AstrBot 宿主、插件核心、安全护卫层与多通道告警模块之间的结构职责；实际巡检实现（`watch/probes.py` 等）核对的是分发配置、清单、分片、整包散列与 TLS 证书，而非图中早期概览标签所写的宿主 CPU/内存占用。

## 源码地图与离线验证工作流

更多符号级索引与修改指南请结合阅读仓库根目录的 `repo-docs/code-map.md` 与 `repo-docs/modules/*.md`：

| 模块位置 | 核心职责 | 关联回归测试文件 |
| --- | --- | --- |
| `main.py` | AstrBot `Star` 生命周期、`@filter.command("线路")`、队列持久化与 QQ 官方逐会话确认 | `tests/test_plugin_loading.py`、`tests/test_delivery.py`、`tests/test_qq_official.py` |
| `watch/config.py` / `sources.py` / `discovery.py` | 配置优先级与校验、`endpoint`/`mirrors` 源抽象、JSON 清单与版本解析 | `tests/test_config.py`、`tests/test_sources.py`、`tests/test_discovery.py` |
| `watch/http.py` / `probes.py` / `models.py` | `PublicResolver` 与重定向防 SSRF、64 MiB/流式 MD5、10 项探针及 TLS 检查 | `tests/test_probes.py`、`tests/test_network_regressions.py` |
| `watch/runner.py` / `scheduler.py` | 快慢巡检编排、入口失联降级诊断、Cartesian 分块轮转与 7 天覆盖统计 | `tests/test_runner.py`、`tests/test_scheduler.py`、`tests/test_monitor_regressions.py` |
| `watch/state.py` / `store.py` | `AlertState` 窗口、两级抑制、静音留存与 `watch-state.json` 原子存储 | `tests/test_state.py`、`tests/test_state_regressions.py`、`tests/test_store.py` |
| `watch/commands.py` / `render.py` | `CommandGate` 三道防放大闸门、影响描述渲染与 `safe()` 文本净化 | `tests/test_commands.py`、`tests/test_render.py` |
| `tools/check-no-endpoints.py` | 静态扫描禁止真实域名、内部镜像名与凭证写入仓库与文档 | `tests/test_guardrail_endpoints.py`、`tests/test_guardrail_regressions.py` |

开发与验证命令（基于标准库 `unittest` 驱动离线替身，不访问外部生产镜像；系统未安装 `aiohttp` 时会跳过 `test_network_regressions.py` 中 5 项 `AiohttpBoundaryTest`）：

```sh
python3 -m unittest discover -s tests -t . -v
python3 tools/check-no-endpoints.py --verbose
python3 -m compileall -q tools watch main.py
```

## 关键架构决策（ADR）与版本迁移指南

### ADR-1：采用每块 MD5 与清单动态 `chunk_size`，而不是 SHA-256 或固定分块

- **背景与决策**：被测分发客户端按资源清单自报的 `chunk_size` 与每块 32 位十六进制 MD5 校验证书与安装包内容。如果监控端改用 SHA-256 或写死固定 16 MiB 块大小，监控就会和客户端验证逻辑彻底脱节，出现「监控全绿、用户报损」的假阳性绿色信号。

### ADR-2：使用确定性三元组轮转（`Rotation`）代替随机抽样

- **背景与决策**：全站多线路全部逐块校验会产生 `N × 线路数 × 全包体积` 的巨额下行流量。采用 `(线路, 文件, 分块)` 持久游标顺序推进，并在成功收到 206 校验通过后计入 7 天窗口覆盖率，既将每轮带宽锁在常数级别，又能让 `/线路 覆盖率` 有据可查地回答「哪些分块在过去一周已实际检验」。

### ADR-3：取消任何内置 `entry_url` 默认值并隔离运行 `User-Agent`

- **背景与决策**：绝不内置任何兜底入口地址——当机器未配置合法配置源时宁可明确在初始化报错停机，防止误报虚假绿灯；同时默认 `User-Agent` 设为 `resource-watch/1.0`，避免在 CDN 访问日志里将机器人定时探测流量混入真实终端用户装机量统计。

### 历史配置结构迁移对照

如果你曾参考过较早版本的本地 JSON 写法或仓库根目录样例文件，请按下列对照检查并完成迁移：

| 历史写法 / 样例残留 | 现行契约写法 | 迁移说明 |
| --- | --- | --- |
| 顶层平铺 `entry_url` / `entry_urls` | 仍兼容；新写法推荐 `source: { "type": "endpoint", "urls": [...] }` | 若同时存在 `entry_url` 与 `mirrors`，运行时会优先消费 `entry_url` |
| `alert.fire_after: [2, 3]`、`alert.recover_after: 2`（见于 `config.example.json`） | `alert.fire_after_failures: 2`、`alert.fire_window: 3`、`alert.recover_after_successes: 2` | 运行期与 `_conf_schema.json` 只读取后三个分拆整型键；务必把样例里的数组形式改写成现行键名 |
| `command` 白名单缺省配置 | 显式确认 `notify.sessions` / `command.allow_sessions` 完整 UMO | `allow_sessions` 仅开放查询权限而不触发告警订阅；QQ 官方管理员必须填写用户 OpenID |
