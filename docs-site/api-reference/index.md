---
layout: page
sidebar: false
title: API 与组件参考
description: AstrBot Resource Monitor 10 项线路内容探针、64 MiB 公网 SSRF 防线、8 条 /线路 群内指令及 Source/HttpClient 扩展接口参考。
---

<script setup lang="ts">
import { apiSpecZh } from '../.vitepress/data/api-spec'
</script>

<ApiExplorer :spec="apiSpecZh">

### 配置发现与清单一致性探针 (P0/P1) {#probes-config-manifest}

核验 `endpoint` 与 `mirrors`、启用数量骤降 / 版本不回退、`manifest.json` 32 位 MD5 及多数共识，触发 `KEY_ENTRY` 自动抑制下游误报。

### HTTP Range 分片、MD5 轮转、热更整包与 TLS 到期 (P0/P1/P2) {#probes-range-md5-tls}

沿真实 CDN 路径抽检 `206 Partial Content` 与 7 天覆盖游标，并每天校验所有公网 IP 的 TLS 证书有效期（`<14d` P2 / `<3d` P0）。

### 8 条 `/线路` 运维指令、SSRF 防线与 `Source`/`HttpClient` SPI {#commands-spi-security}

提供白名单会话 `/线路` 交互与 QQ 官方 `/线路 通知` + `/线路 确认` 闭环，拒绝内网 IP 与环境变量代理，保留 `64 MiB` 缓冲天花板。

</ApiExplorer>
