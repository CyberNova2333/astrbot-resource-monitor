---
layout: page
sidebar: false
title: API & Component Reference
description: Interactive reference for AstrBot Resource Monitor's 10 distribution probes, SSRF/64 MiB guardrails, 8 chat commands, and Source/HttpClient SPIs.
---

<script setup lang="ts">
import { apiSpecEn } from '../../.vitepress/data/api-spec'
</script>

<ApiExplorer :spec="apiSpecEn">

### Endpoint Discovery, Config Sanity, Manifest, Consensus & Version Probes {#probes-config-manifest}

Detects corrupt endpoints, >=50% mirror drops, version regressions, 32-hex manifest MD5 mismatches, and majority splits with two-tier alert suppression.

### HTTP Range, MD5 Chunk Rotation, Hot Packages & TLS Expiry {#probes-range-md5-tls}

Validates real CDN HTTP `206` chunks, 7-day rotating MD5 cursor, streaming package digests under `64 MiB` fetch limits, and daily TLS `notAfter` monitoring.

### 8 Chat Commands (`/线路`), Output Guard & Pluggable SPIs {#commands-spi-security}

Session-allowlisted chat subcommands, QQ Official admin acknowledgment, `render.safe()` mention neutralization, and offline `Source`/`HttpClient` SPIs.

</ApiExplorer>
