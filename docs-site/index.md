---
layout: home

hero:
  name: AstrBot Resource Monitor
  text: 资源分发线路巡检与告警插件
  tagline: 基于客户端同一份校验口径，定时核查配置源、清单一致性、HTTP Range 分片、MD5 散列、热更包与 TLS 证书到期，经由多轮防抖与 QQ 官方人工确认闭环投递。
  actions:
    - theme: brand
      text: 起步与配置部署
      link: /docs/
    - theme: alt
      text: API 与探针参考
      link: /api-reference/
    - theme: alt
      text: 探针契约与扩展
      link: /docs/contracts
    - theme: alt
      text: 原理与交互拓扑
      link: /docs/architecture

features:
  - title: 从配置源现场自发现
    details: 拒绝在插件仓库硬编码第二份线路表或限速阈值。支持 endpoint 动态发现与 mirrors 本地列表两种源模式，并在主入口异常时用未超龄快照作仅参考的降级线索。
  - title: 十项内容与协议级探针
    details: 覆盖线上配置合理性、清单解析、多数共识、HTTP 206 Range 支持、32 位 MD5 分块轮转校验、热更包流式校验及 TLS 证书余期提醒。
  - title: 共享环境安全护栏与精确投递
    details: 公网 DNS 绑定、逐跳重定向校验、64 MiB 缓存硬上限、命令闸门与出群文本净化，配合 M-of-N 防抖、静音留存与 QQ 官方查看确认闭环。
---

## 能力定位与明确边界

::: info 能做到什么程度（已实现能力）
- **10 项客户端一致性深度探针**：不仅看 HTTP 200，更校验配置突降/版本回退、多数共识、HTTP `206` Range、32 位 MD5 分块轮转（7 天覆盖度）、热更包流式整包校验与 `<14d`/`<3d` TLS 证书到期。
- **公网 SSRF 钉死与共享防线**：`PublicResolver` 禁止内网/保留 IP（含 IPv4 映射 IPv6）与 `trust_env` 代理，锁定 `64 MiB` 缓冲天花板，配合 `M-of-N` 防抖、两级抑制、`render.safe()` 防注入与 QQ 官方 `/线路 通知` + `/线路 确认` 闭环。
- **快慢双锁隔离与可插拔 SPI**：`300s` 快线与 `3600s` 慢线独立加锁不相互阻塞；`Source` 与 `HttpClient` 支持离线 `FakeClient` 无网全测。
:::

::: warning 明确不能做什么（非目标与硬限制）
- **严格只读观察，不查宿主机也不自动切流**：绝不采集 AstrBot 宿主机 CPU/内存，绝不回改上游配置或切换 CDN，也不提供长期 SLA 可用率历史报表。
- **禁内网与群聊重放保护**：强制拦截回环与私网目标且禁用环境代理；聊天指令强制 `allow_heavy=False` 跳过百 MB 整包，`/线路 确认` 始终只限管理员；仓库零内置默认源（必须手动配 `entry_url` 或 `mirrors`）。
:::

## 架构拓扑概览

<DiagramFrame
  src="/diagrams/monitor-architecture.html"
  title="插件宿主、守卫与告警投递交互拓扑（支持平移与缩放）"
  aspect="900 / 408"
  new-tab-label="在新窗口全屏打开 ↗"
/>

> **图表与源码实现对齐说明**：上方拓扑图展示 AstrBot 宿主、插件核心、SSRF 守卫与告警通道之间的宏观交互关系（图中「资源统计与日志」节点标签为早期总览命名）；当前 `watch/` 代码实际执行的是**外部资源分发线路的配置文件、清单、HTTP Range 分片 MD5、热更包与 TLS 证书巡检**，并不采集宿主机 CPU 或内存占用。

## 本地快速检验

```sh
# 1. 在仓库根目录运行离线单元测试（共 252 项；系统 Python 未装 aiohttp 时跳过 5 项连接边界测试）
python3 -m unittest discover -s tests -t . -v

# 2. 运行地址与凭证防泄漏扫描
python3 tools/check-no-endpoints.py --verbose
```

## 文档分层导航

::: tip 按照读者需求快速跳转
- **初次安装与接通群告警**：阅读 [概览、边界与插件安装](/docs/) 与 [配置源、参数矩阵与排错 FAQ](/docs/configuration)，在 AstrBot 安装插件、配通 `endpoint` / `mirrors`、会话 UMO 与 `/线路` 命令；
- **对接自定义配置源或扩展探针**：查阅 [探针契约、安全护栏与扩展点](/docs/contracts)，查清 10 项探针分级、`unknown=True` 判定边界、JSON 清单格式、`Source`/`HttpClient` 接口及安全假设；
- **研读源码流程、变更迁移与测试**：查阅 [运行原理、交互拓扑与架构决策](/docs/architecture) 与仓库根目录 `repo-docs/README.md`，串联一轮完整巡检到确认流程。
:::
