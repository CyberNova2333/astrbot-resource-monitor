---
title: 接口与扩展契约
description: 十项探针判据规范、安全与资源上限假设、配置与清单数据契约、配置源/HTTP 扩展接口及状态队列跨模块交互。
---

# 接口与扩展契约

本页定义监控引擎对被测分发体系的输入预期、十项探针判定契约、共享宿主运行时的安全防线，以及自定义配置源和状态队列的交互规范。

## 能力边界与安全假设

由于插件运行在共享 AstrBot 宿主环境且所有探测输入均来自外部配置与第三方镜像服务器，代码在接入层设置了四道不可被远程配置绕过的防线：

1. **公网连接钉死（`watch/http.py`）**：
   - `validate_public_url` 仅接受不含用户名密码的 `http://` 与 `https://` URL，拒绝 `localhost`、字面量内网/保留/组播 IP 及畸形数字/十六进制缩写主机。
   - `PublicResolver` 与底层 `TCPConnector` 直接复用校验通过的公网 IP 列表，TLS 证书校验 `_tls_not_after` 也对 `socket.getaddrinfo` 全部结果执行 `require_public_address` 后再携带原始 `server_hostname` SNI 直连，防止 DNS 重绑定（TOCTOU）。
   - 关闭框架自动跳转（`allow_redirects=False`），对最多 `MAX_REDIRECTS = 5` 次重定向逐跳重新执行公网合法性检验；全程采用 `DummyCookieJar()` 与 `trust_env=False`，不保存服务端 Cookie 也不走环境代理。
2. **内存与流式带宽上限（`watch/http.py`、`watch/probes.py`）**：
   - 缓冲读取方法 `HttpClient.fetch` 受硬编码 `MAX_BUFFER_BYTES = 64 MiB` 约束，即使远端清单将 `chunk_size` 写得极大，单块超过上限也会直接跳过并记 `unknown=True`。
   - 热更包校验采用流式边下边算 `HttpClient.digest`，受配置下发的正数上限 `meta.size + 1 MiB` 约束（超时最低 `max(http_timeout_seconds, 1800.0)`），一旦溢出立刻截断并判整包校验失败。
3. **命令放大器防护（`watch/commands.py`、`main.py`）**：
   - 非白名单会话默认静默拒绝；所有主动打流量的重命令（`测`、`配置`）共享一个全局 `"heavy"` 冷却计时器（默认 60 秒）并默认限管理员；聊天指令触发的所有检测均强制设置 `allow_heavy=False`，绝不允许一条群消息引发整包下载。
4. **出群文本净化（`watch/render.py`）**：
   - 外部来源的线路名、文件名及错误细节在 `safe()` 中清洗 ASCII 控制符与零宽字符、转义 `[CQ:`/`[at:`/`[mirai:`/`[face:`/`[json:`/`[xml:` 前缀为全角 `［tag：`，改写 `@全体成员`/`@everyone`/`@all` 为 `＠...`，并将单字段与整条消息分别截断至 `MAX_FIELD = 160` 与 `MAX_MESSAGE = 3000` 字符。

## 十项探针契约与分级

| 探针名称 | 级别 | 触发输入与校验契约 | `unknown=True` / 特殊边界 |
| --- | --- | --- | --- |
| `配置源可达性` | `P0` | 请求 `entry_url` 要求 HTTP 200、有效 JSON 且含非空 `mirrors[]` | 明确区分 `拉不到`（网络/状态码）与 `内容坏了`（解析失败） |
| `线上配置合理性` | `P0`/`P1` | 检测启用数突减 >=50%（原 >=2 条，`P0`）、`settings` 消失（`P1`）、非公网镜像目标（`P1`）、无启用线路（`P0`）、`client.version` 格式及不回退（`P0`）、`proxy.base` 以 `/` 结尾（`P1`） | 缺少 `client.version` 标 `unknown=True`；任何失败均阻止当前快照成为健康基准 |
| `清单可达性` | `P1` | 带 `NO_CACHE` 并发（最多 4 路）拉取 `manifest.json`，逐条验证字段类型、正整数 `size`/`chunk_size`、严格匹配分块数与 32 位十六进制 MD5 | 损坏文件条目会被隔离点名但不中断其余条目；请求失败触发同镜像后续检查抑制 |
| `线路一致性` | `P1` | 纯函数按各镜像有效清单指纹统计严格多数（`count * 2 > total_mirrors`），点名少数落后镜像 | 仅有 2 条镜像且互相矛盾（1:1）或无多数时标 `unknown=True`，并暂停以此清单基准抽块 |
| `块内容校验` | `P1` | 按 `(线路, 文件, 分块)` 轮转游标发起分片下载，验证实际返回字节长度与清单该块 MD5 一致 | 单块大小超出上限时跳过标 `unknown=True`，网络失败或 `unknown` 不计入 7 天覆盖率 |
| `Range 支持` | `P1` | 分块 GET **故意不带破缓存请求头**、只带 `Range: bytes=start-end`，要求响应 `206 Partial Content` 且 `Content-Range` 与总大小严格吻合 | 镜像返回 `200` 忽略分片请求即判 `P1` 失败 |
| `线路速率` | `P2` | 将单块下载耗时折算为 kbps，与线上 `settings.min_speed_kbps` 对比 | 未声明 `settings.min_speed_kbps`（含 `mirrors` 模式）或未完成传块时标 `unknown=True` |
| `版本 json` | `P1` | 带 `NO_CACHE` 拉取 `watch.version_files` 列表文件，要求含有效 `version`、正整数 `size` 与 32 位十六进制 `md5` | 配置未声明 `version_files` 时标 `unknown=True` 并沉默跳过 |
| `热更包整包核对` | `P1` | 按 `watch.packages` 映射对对应安装/升级包做流式 `digest`，核对总字节与整包 MD5，最多 2 并发（慢锁独立） | 失败或恢复确认期进入快间隔重查；慢任务期间配置变动则结果不污染新调度 |
| `证书有效期` | `P2`/`P0` | 对全部 HTTPS 启用线路的 `(host, port)` 每 86400s 握手一次读取 `notAfter` | `< 14` 天报 `P2`、`< 3` 天立即升 `P0`；连不上或取不到天数标 `unknown=True` |

## 外部配置与清单格式契约

### 1. 配置源 JSON 最小与完整形状（`endpoint` 返回体）

`watch/discovery.py` 的 `parse_config` 只强制要求顶层包含至少一条合法 `mirrors[]` 项（含非空 `base`）；其余字段全部按「有就多探一项、没有就优雅降级或标 `unknown`」处理：

```json
{
  "mirrors": [
    { "name": "线路甲", "base": "https://a.example.test/", "enabled": true, "weight": 100 }
  ],
  "settings": { "min_speed_kbps": 512 },
  "client": { "version": "1.2.3" },
  "proxy": { "base": "https://proxy.example.test/mirror/" },
  "watch": {
    "version_files": ["version_a.json"],
    "packages": { "version_a.json": "hotpatch_a.zip" }
  }
}
```

### 2. 线路 `manifest.json` 与热更版本 JSON

- **清单 `manifest.json`**：顶层对象或 `files` 映射表中的每个文件条目均须提供正整数 `size`、`chunk_size`，以及 `chunks`（长度恰好等于 `ceil(size / chunk_size)` 的 32 位十六进制 MD5 数组）。
- **版本 JSON（由 `watch.version_files` 声明路径）**：须包含字符串或数值 `version`、正整数 `size` 以及 32 位十六进制 `md5`。

## 扩展接口（新增配置源 / 传输层替身）

1. **新增配置源适配（`watch/sources.py`）**：继承 `Source` 基类并实现 `discover(client) -> (ProbeResult, Optional[Discovered])` 与可选 `diagnose(client)`，在 `sources.build(spec)` 注册新 `type` 名称即可。所有下游探针、轮转调度器与告警状态机无需任何改动。
2. **扩展或替换传输客户端（`watch/http.py`、`tests/fakes.py`）**：探针与编排层仅依赖 `HttpClient` 协议提供的两个异步方法：`fetch(url, *, headers=None, max_bytes=None) -> HttpResponse` 与 `digest(url, *, headers=None, max_bytes=None) -> DigestResult`。编写离线测试或切换传输层时，只需按 `tests/fakes.py` 中的 `FakeClient` 实现这两个方法。

## 跨模块交互与状态流转

1. **两级抑制链（`watch/state.py`、`watch/probes.py`）**：`配置源可达性` 失败产生的 `KEY_ENTRY` 正在报警时，会抑制配置合理性、清单可达性、线路一致性这三类连带结果通知；某条线路 `清单可达性` 正在报警产生的 `manifest_key(mirror)` 则会抑制该线路名下的分块内容、`Range`、速率、版本及整包故障通知；`证书有效期` 仅依附域名与端口独立触发。
2. **静音留存与持久化队列（`watch/state.py`、`watch/store.py`、`main.py`）**：
   - 在静音窗口内新积攒触发的故障不会消耗首次 `fire` 资格；已触发过的故障若在静音期恢复，会留存 `pending_recovery_since` 至解除静音后通过 `flush_pending_recoveries` 补发恢复通知。
   - 状态与出站队列统一原子落盘到 `<state_dir>/watch-state.json`；写盘失败则延迟尝试发送。
   - `_flush_outbox` 在发向每一个目标会话前都会调用 `_discard_stale` 实时检查是否已静音或故障已恢复；若为 `qq_official` / `qq_official_webhook`，则走纯文本并写入 `submitted`，交由 `/线路 通知` 绑定查看者与 `/线路 确认` 正式完结。

## 契约与扩展 FAQ

**Q1：为什么不能把单轮偶然一次分块超时立刻作为故障通知发送？**
`AlertState` 默认实施 3 轮窗口内 2 次失败（`fire_after_failures=2` / `fire_window=3`）与连续 2 轮成功恢复。这可以在公网偶发丢包时避免狼来了式的刷屏告警，同时通过级别升级打破 `remind_every_hours`（例如证书从小于 14 天掉到小于 3 天会立即发 `P0`）。

**Q2：为什么分块请求故意不带 `NO_CACHE` 请求头，而配置和清单必须带？**
配置入口与清单变化需要第一时间生效以便快速捕捉配置错误或回退；而普通用户下载分块一定会经过 CDN 边缘节点，不破缓存才能真实暴露 CDN 缓存坏块或回源残缺的问题。

**Q3：遇到两个镜像清单互相不一致时，插件会按哪一个判对？**
遵循严格多数原则（`count * 2 > len(per_mirror)`）。只有出现次数过半的那份清单指纹才会被采信为基准；如果是 2 个镜像互不相让（1 比 1），两者都记为 `unknown=True` 并暂停以此清单做后续块比对，杜绝随机冤枉好节点。

**Q4：新增一个配置源类型需要改动探针或状态机吗？**
不需要。只要你在 `watch/sources.py` 产出的 `Discovered` 包含启用 `Mirror` 列表，并按需填充阈值或 `version_files`/`packages`，所有现有 10 项探针、轮转器和状态机都会直接复用。
