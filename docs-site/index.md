---
layout: home
repoGuideSource: "repo-docs/README.md"

hero:
  name: AstrBot Resource Monitor
  text: 资源线路监控与安全准入守卫
  tagline: 实时核验资源线路内容与哈希摘要，防止未授权配置回退与恶意流量重定向。
  actions:
    - theme: brand
      text: 开启文档阅读
      link: /walkthroughs/one-real-run
    - theme: alt
      text: 架构代码地图
      link: /code-map
    - theme: alt
      text: GitHub 仓库
      link: https://github.com/CyberNova2333/astrbot-resource-monitor

features:
  - title: 线路安全准入核验
    details: 在分发与解析资源前，严格核对线上配置指纹与文件哈希，拒绝任何格式异常或未签名的外部线路。
  - title: 进程级指标监控
    details: 实时追踪资源拉取延迟、失败率与网络吞吐指标，自动触发熔断降级与报警上报。
  - title: AstrBot 插件无缝嵌入
    details: 遵循标准插件上下文生命周期，与 Bot 核心消息流和调度系统安全隔离。
---

## 这是什么

**AstrBot Resource Monitor** 是专为 AstrBot 机器人生态打造的高可用资源监控与线路守卫插件。

在分布式资源获取与媒体解析场景下，外部下载源可能遭遇劫持、下线或重定向篡改。本插件在资源被传递给主进程前，执行严格的内容合规校验、哈希指纹匹配以及链路状态监控，保障服务运行环境绝对安全可控。

## 怎么用 / 快速上手

### 1. 插件集成与环境检查

Python 3.10+ 环境下安装并运行检查：

```bash
# 运行单元测试验证守卫断言
python scripts/test.py
```

### 2. 配置与启用

将插件放入 AstrBot 的 `data/plugins/` 目录，在配置文件中填入监控线路：

```yaml
resource_monitor:
  check_interval: 60
  allowed_endpoints:
    - "https://assets.example.com"
  enforce_sha256: true
```

## 分层阅读与快速跳转

::: tip 按读者角色快速检索
- **初次接触 / 快速理解**：从[一条真实主流程](/walkthroughs/one-real-run)开始，追踪一次资源下载请求从 URL 触发到安全准入守卫拦截验证的完整过程。
- **架构设计 / 模块定位**：从[代码地图](/code-map)进入，查阅探针（Prober）、指标采集器与规则引擎代码分布。
- **审计复核 / 核心贡献**：从[源码证据](/references/source-evidence)核对安全规则断言，查阅[阅读质量审计](/references/quality-review)了解未覆盖风险。
:::

---

## 完整项目指南概览

<!--@include: ../repo-docs/README.md-->
