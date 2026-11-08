---
layout: home

hero:
  name: AstrBot 监控插件
  text: 现代技术基础设施
  tagline: AstrBot Resource Monitor 是面向 AstrBot 宿主机器人的**系统资源监控插件与端点防泄漏安全守卫组件**。
  actions:
    - theme: brand
      text: 快速开始阅读
      link: /docs/
    - theme: alt
      text: 交互式架构全景
      link: /docs/architecture
    - theme: alt
      text: GitHub 仓库
      link: https://github.com/CyberNova2333/astrbot-resource-monitor

features:
  - title: 极简快速上手
    details: 通俗易懂的文档组织结构，分钟级完成环境搭建与快速启动。
  - title: 严密安全防护
    details: 零凭据泄漏防护、受控沙箱隔离与细粒度白名单权限控制。
  - title: 现代化视觉呈现
    details: 质感模式与简约模式双向自适应，内建 Archify 交互架构图表。
---

## 架构全景

<div class="archify-diagram-card" style="margin: 1.5rem 0; border: 1px solid var(--vp-c-border); border-radius: 12px; overflow: hidden; background: var(--vp-c-bg-soft); box-shadow: 0 4px 16px rgba(0,0,0,0.06);">
  <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 18px; background: var(--vp-c-bg-elv); border-bottom: 1px solid var(--vp-c-border); font-size: 13px;">
    <span style="font-weight: 600; color: var(--vp-c-text-1); display: flex; align-items: center; gap: 8px;">
      <span style="font-size: 16px;">📐</span> 监控插件与安全守卫拓扑（基于 Archify 的高保真交互图表，支持平移/缩放/探查）
    </span>
    <a href="/diagrams/monitor-architecture.html" target="_blank" rel="noreferrer" style="font-size: 12px; color: var(--vp-c-brand-1); text-decoration: none; font-weight: 500;">
      在新窗口全屏打开 ↗
    </a>
  </div>
  <iframe src="/diagrams/monitor-architecture.html" width="100%" height="520px" frameborder="0" style="display: block; border: none;" allowfullscreen loading="lazy"></iframe>
</div>

## 快速上手演示

```bash
# 1. 运行本地端点守卫检查（确保无凭证与拓扑泄漏）
python tools/check-no-endpoints.py

# 2. 启动单测验证探针采集逻辑
pytest tests/

# 3. 将插件目录软链或复制至 AstrBot 的 data/plugins/ 下即可自动加载
```

## 文档分层导航

::: tip 按照读者需求快速跳转
- **初次上手**：直接阅读 [快速入门与实战](/docs/)，走通环境配置与首次执行流程；
- **架构探查**：查阅 [系统架构与设计](/docs/architecture)，全屏体验交互式拓扑图表；
- **详细配置**：查阅 [配置与使用指南](/docs/configuration)，查阅所有环境变量与参数；
- **排查解惑**：查阅 [常见问题与排错](/docs/faq)，快速定位解决使用疑难。
:::
