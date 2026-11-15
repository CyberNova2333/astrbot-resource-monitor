---
title: Config Matrix, Sources & FAQ
description: Three-layer configuration model, precedence between AstrBot WebUI and RESOURCE_WATCH_CONFIG, endpoint vs mirrors modes, full option matrix, and deployment FAQ.
---

# Config Matrix, Sources & FAQ

## Three-Layer Config Model & Precedence

Real endpoints, mirror URLs, session UMOs, and credentials must **never** be committed to git (`tools/check-no-endpoints.py` blocks non-allowlisted hosts, and `.gitignore` excludes root `/config.json` and `data/`):

1. **Plugin source**: Probe algorithms, window math, and safety rules only (`example.test` in docs/examples).
2. **Local config (`_raw_config` -> `RESOURCE_WATCH_CONFIG`)**: AstrBot WebUI plugin settings are evaluated first; if empty or invalid (`ConfigError`), `main.py` falls back to the JSON path in environment variable `RESOURCE_WATCH_CONFIG`. If neither yields a valid source, initialization logs an error and refuses to start rather than inventing a fake green state.
3. **Config source & mirrors**: Supply live `mirrors[]`, optional `settings`/`client`/`proxy`/`watch`, and per-mirror `manifest.json` + chunks.

## Config Source Modes (`endpoint` vs `mirrors`)

| Aspect | Mode A: `endpoint` (`entry_url`) | Mode B: `mirrors` (Static List) |
| --- | --- | --- |
| How to configure | WebUI `entry_url` (plus optional `entry_urls`), or JSON `source: {"type": "endpoint", "urls": [...]}` | WebUI `mirrors: ["MirrorA=https://a.example.test/"]` (+ `version_files`), or JSON `source: {"type": "mirrors", ...}` |
| Threshold & update discovery | Auto-discovers `settings.min_speed_kbps`, `client.version`, `proxy.base`, and `watch` | No central thresholds (`线路速率` stays `unknown=True`); add `version_files`/`packages` explicitly if needed |
| Single point of failure | Yes; when `entry_url` fails, `Monitor` probes `entry_urls` and non-expired `last_good_snapshot` for diagnostic context only | No central config dependency (`entry_url` precedence applies if both are filled) |

## Configuration Option Matrix (`_conf_schema.json` & `watch/config.py`)

| Key Path | Default | Minimum / Constraint | Purpose |
| --- | --- | --- | --- |
| `entry_url` / `entry_urls` | `""` / `[]` | Public `http(s)` URL(s) | Primary endpoint & optional backups (backups help classify primary outage; never downgrade primary P0) |
| `mirrors` / `version_files` / `packages` | `[]` / `[]` / `{}` | WebUI supports `"Name=URL"` strings | Static mirrors mode; full `packages` map requires JSON `source` object via `RESOURCE_WATCH_CONFIG` |
| `notify.sessions` | `[]` | List or comma-separated string | Full AstrBot `unified_msg_origin` (UMO) targets; QQ official uses OpenID UMOs, never raw QQ numbers |
| `notify.at_all_on_p0` | `true` | Boolean | Mention all only on P0 all-mirror outage (degrades to plain text on QQ official) |
| `notify.prefix` | `""` | String | Instance label (e.g., region tag) when multiple deployments post into one group |
| `schedule.interval_fast_seconds` | `300` | `>= 30` sec | Fast cycle interval (endpoint, sanity, manifests, consistency, rotating chunks) |
| `schedule.interval_slow_seconds` | `3600` | `>= 60` sec | Slow cycle interval (version JSON, hot package check eligibility, daily TLS check) |
| `schedule.chunk_probes_per_cycle` | `1` | `>= 0` | Number of `(mirror, file, chunk)` triples checked per fast cycle (`0` disables chunk rotation) |
| `schedule.hot_package_on_version_change` | `true` | Boolean | Trigger streaming full-package MD5 digest when `version_files` version changes |
| `schedule.hot_package_min_interval_seconds` | `21600` | `>= 600` sec | Fallback interval (6h) to re-verify full hot packages even without version bump |
| `alert.fire_after_failures` | `2` | `>= 1`, `<= fire_window` | Failures required inside sliding window before firing (`GREEN` -> `FIRING`) |
| `alert.fire_window` | `3` | `>= 1` | Sliding failure window length ("M failures out of N cycles") |
| `alert.recover_after_successes` | `2` | `>= 1` | Consecutive passing cycles required to emit `recover` notification |
| `alert.remind_every_hours` | `6.0` | `>= 0.5` hr | Minimum interval between repeat `remind` notifications (bypassed on severity escalation) |
| `alert.mute_command_admin_only` | `true` | Boolean | Schema placeholder; **runtime enforcement reads `command.privileged_admin_only`** |
| `degraded.probe_with_stale_config` | `true` | Boolean | Probe mirrors with cached snapshot when `entry_url` fails (marked `unknown=True`, never alerts or marks healthy) |
| `degraded.stale_config_max_age_seconds` | `86400` | `>= 0` sec | Maximum age (24h) before stale snapshot is ignored completely |
| `command.respond_anywhere` | `false` | Boolean | When false, silently ignores `/线路` outside `notify.sessions` and `allow_sessions` |
| `command.allow_sessions` | `[]` | List of UMOs | Extra sessions allowed to run `/线路` queries (does **not** subscribe them to alerts) |
| `command.heavy_admin_only` | `true` | Boolean | Restrict `/线路 测` & `/线路 配置` to admins |
| `command.privileged_admin_only` | `true` | Boolean | Restrict `/线路 静音` & `/线路 取消静音` to admins (`/线路 确认` is always admin-only) |
| `command.cooldown_seconds` | `60` | `>= 0` sec | Shared cooldown across heavy network commands (`"heavy"` lock key) |
| `runtime.user_agent` | `"resource-watch/1.0"` | Non-empty string | Intentionally distinct from client UA so CDN logs exclude monitor traffic from install stats |
| `runtime.state_dir` | `"data"` | Directory path | Stores `<state_dir>/watch-state.json` (alert state, 7-day coverage, outbox) |
| `runtime.http_timeout_seconds` | `30.0` | `>= 5.0` sec | Request + redirect total timeout for small payloads (streaming digest uses min `1800s`) |
| `runtime.max_body_bytes` | `4194304` | `>= 65536` bytes (cap `64 MiB`) | Buffered `fetch()` limit (4 MiB default; 64 MiB hard cap cannot be raised remotely) |

> **Example file notice**: `config.example.json` uses legacy example keys `alert.fire_after` and `alert.recover_after`, whereas `watch/config.py` and `_conf_schema.json` actively read `fire_after_failures`, `fire_window`, and `recover_after_successes`. Update those three keys if copying `config.example.json` as a local `RESOURCE_WATCH_CONFIG` file.

## QQ Official Adapter Notes

- Use full AstrBot UMOs containing the QQ official OpenID (do **not** use everyday QQ numbers or group numbers), and configure AstrBot admins with OpenIDs as well.
- When `qq_official` / `qq_official_webhook` sends succeed without raising an exception, the target entry transitions to `submitted` (preventing repeat spam) while remaining in the outbox until an admin runs `/线路 通知` and then `/线路 确认` in that session.

## Deployment FAQ

**Q: The plugin loads in AstrBot, but no probes run and no alerts arrive.**
Check AstrBot logs for `[线路监控] 配置不可用，插件不会开始探测`. When neither WebUI nor `RESOURCE_WATCH_CONFIG` yields a valid source—or when `fire_after_failures > fire_window`—the plugin intentionally aborts startup instead of faking green health.

**Q: `/线路 状态` produces zero response in a group chat.**
By default `command.respond_anywhere` is `false`, so unapproved chats are silently ignored (`""`). Verify the full UMO string (first segment is the AstrBot platform instance ID, not necessarily the adapter name).

**Q: Why is download speed (`线路速率`) permanently unknown in `mirrors` mode?**
Without a central config endpoint, `settings.min_speed_kbps` is unavailable. Rather than hardcoding a guess that drifts from client behavior, speed checks emit `unknown=True` while manifest, Range 206, chunk MD5, and TLS probes continue normally.
