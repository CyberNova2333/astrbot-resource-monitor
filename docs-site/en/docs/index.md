---
title: Getting Started & Installation
description: Scope and non-goals of AstrBot Resource Monitor, why HTTP 200 is insufficient, plugin installation under AstrBot, and chat command reference.
---

# Getting Started & Installation

**AstrBot Resource Monitor** (`astrbot_plugin_resource_watch`) is a scheduled distribution-route monitoring plugin for **AstrBot**. Rather than collecting host CPU, RAM, or disk metrics, it inspects remote configuration entrypoints, resource manifests, HTTP `Range` slices, MD5 checksums, hot-update versions/archives, and TLS certificate expiration using the same validation rules as the target client, then deduplicates and delivers actionable alerts to configured chat sessions.

## Why HTTP 200 Checks Miss Real Outages

In resource-distribution pipelines, most user-facing breakages look healthy to generic uptime pingers:

- **Silent upstream fallback**: If clients fail to fetch the remote config endpoint, they may silently fall back to built-in defaults—invisible to users, visible only to active probes.
- **Truncated or stale edge caches**: A mirror returning `HTTP 200` can still serve corrupted partial bytes whose MD5 no longer matches `manifest.json`.
- **Ignored `Range` headers**: Returning `200 OK` full bodies instead of `206 Partial Content` collapses segmented downloads into slow full-file retries.
- **Mirror drift & version regressions**: One mirror lagging behind the majority or an accidentally lowered `client.version` gate breaks installs without raising HTTP errors.

## Explicit Non-Goals

- **No long-term SLA reporting**: Tracks active failure windows and a rolling 7-day chunk coverage cursor only.
- **No upstream host management**: Does not monitor host OS utilization or manage external CDN/hosting control planes.
- **No auto-remediation**: Read-only observation never writes back to upstream configs or switches routes.
- **No business data storage**: Only alert state, rotation progress, and pending notifications live in `state_dir`.

## Installation & Quick Check

1. Copy or symlink this repository into AstrBot's plugin directory (e.g., `data/plugins/astrbot_plugin_resource_watch/`), keeping `main.py` alongside `watch/` (the plugin loads via package-relative imports).
2. Ensure Python `3.10+` and `aiohttp>=3.14.5` (`requirements.txt`; typically already bundled with AstrBot).
3. Run offline tests and the endpoint-hygiene scanner before deployment:

```sh
python3 -m unittest discover -s tests -t . -v
python3 tools/check-no-endpoints.py --verbose
```

## Chat Commands Overview

By default, `/线路` commands only respond inside `notify.sessions` and `command.allow_sessions` (both Chinese subcommands and English aliases are supported):

| Command | Alias | Purpose & Default Access |
| --- | --- | --- |
| `/线路 状态` | `/线路 status` | Show latest probe results, mute remaining time, and 7-day chunk coverage |
| `/线路 测 <mirror>` | `/线路 test <mirror>` | Probe one mirror immediately (skips heavy full-package downloads; admin + cooldown) |
| `/线路 配置` | `/线路 config` | Fetch and summarize discovered mirrors, client version gate, and thresholds (admin + cooldown) |
| `/线路 静音 [duration]` | `/线路 mute [duration]` | Pause delivery (e.g., `30m`, `2h`, `45` minutes; defaults to `30m`) while still probing and queuing recoveries |
| `/线路 取消静音` | `/线路 unmute` | End mute immediately and trigger delivery flush (admin by default) |
| `/线路 覆盖率` | `/线路 coverage` | Report percentage of `(mirror, file, chunk)` triples verified in the last 7 days |
| `/线路 通知` | `/线路 notifications` | Inspect the earliest unacknowledged alert in this session (for QQ official confirmation) |
| `/线路 确认` | `/线路 ack` | Acknowledge the notification just shown to you via `/线路 通知` (**always admin-only**) |

Next: configure `endpoint` or `mirrors` and session UMOs in [Configuration Matrix & Troubleshooting](/en/docs/configuration).
