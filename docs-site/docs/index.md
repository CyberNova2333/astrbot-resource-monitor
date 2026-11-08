---
title: 快速入门
description: AstrBot Resource Monitor 是面向 AstrBot 宿主机器人的**系统资源监控插件与端点防泄漏安全守卫组件**。
---

# 快速入门

AstrBot Resource Monitor 是面向 AstrBot 宿主机器人的**系统资源监控插件与端点防泄漏安全守卫组件**。

## 解决的核心痛点

- **痛点 1**：服务器常驻机器人容易发生内存泄漏或被高频请求打满 CPU 而缺乏实时告警
- **痛点 2**：开发者排查网络问题时容易顺手把真实业务 IP 或公网内网拓扑硬编码进代码库
- **痛点 3**：缺少在 Git 提交前即时阻断非受控端点入库的自动化钩子

---

## 环境准备

Python 3.10+，已部署的 AstrBot 宿主环境。

---

## 快速安装与运行

```bash
# 1. 运行本地端点守卫检查（确保无凭证与拓扑泄漏）
python tools/check-no-endpoints.py

# 2. 启动单测验证探针采集逻辑
pytest tests/

# 3. 将插件目录软链或复制至 AstrBot 的 data/plugins/ 下即可自动加载
```

---

## 接下来探索

- 深入了解系统内部流转：查阅 [系统架构与设计](/docs/architecture)
- 探索全部配置参数与高级场景：查阅 [配置与使用指南](/docs/configuration)
- 遇到问题排错：查阅 [常见问题与排错](/docs/faq)
