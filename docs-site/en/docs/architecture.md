---
title: Architecture, Code Map & Decisions
description: End-to-end execution walkthrough, interactive architecture diagram, module/test code map, verification commands, ADRs, and schema migration guide.
---

# Architecture, Code Map & Decisions

## One Real Run Walkthrough

Every scheduled tick or manual command follows five verifiable stages (for the full line-by-line engineering walkthrough, inspect `repo-docs/walkthroughs/one-real-run.md`):

1. **Config Normalization & Discovery (`watch/config.py`, `watch/sources.py`)**: `load()` resolves WebUI settings or `RESOURCE_WATCH_CONFIG`; `Source.discover()` returns a normalized `Discovered` snapshot. If the primary endpoint fails, `Monitor._diagnose_entry_failure` checks `entry_urls` and a non-expired `last_good_snapshot` for non-authoritative `unknown=True` context.
2. **Sanity Gates & Consensus (`watch/probes.py`)**: Mutation, version non-regression, trailing slash, and SSRF checks run before `Semaphore(4)` fetches `manifest.json`. `check_manifest_consistency` requires a strict majority before approving baseline entries for chunk checks.
3. **Separated Fast & Slow Cycles (`watch/runner.py`, `watch/scheduler.py`)**: Fast cycles (`300s`) step deterministically through `Rotation` triples and record 7-day coverage only for verified 206 MD5 chunks. Slow cycles (`3600s`) use `Semaphore(2)` under an independent lock to validate `version_files`, eligible hot packages (disabled when `allow_heavy=False`), and daily TLS expiry.
4. **Alert Convergence & Atomic State (`watch/state.py`, `watch/store.py`)**: Results carry suppression keys into `AlertState`'s `M-of-N` window; pending notifications persist alongside coverage state in `<state_dir>/watch-state.json`.
5. **Per-Recipient Recheck & Official Ack (`main.py`)**: `_flush_outbox` checks `_discard_stale` before each session send. On `qq_official` / `qq_official_webhook`, successful submission records `submitted` and awaits an admin's `/线路 通知` followed by `/线路 确认` in that exact session.

## Interactive Architecture Diagram

<DiagramFrame
  src="/diagrams/monitor-architecture.html"
  title="Host Integration, SSRF Guard & Delivery Topology (Pan / Zoom)"
  aspect="900 / 408"
  new-tab-label="Open Fullscreen"
/>

> **Diagram note**: The interactive topology summarizes host integration, SSRF/command guards, and alert channels; actual `watch/` probes inspect distribution configs, manifests, HTTP Range slices, MD5 digests, and TLS certs rather than host CPU or memory.

## Code Map & Verification Workflow

| Area | Responsibility | Associated Tests |
| --- | --- | --- |
| `main.py` | AstrBot `Star` lifecycle, `/线路` routing, persistent outbox, QQ official ack | `tests/test_plugin_loading.py`, `tests/test_delivery.py`, `tests/test_qq_official.py` |
| `watch/config.py`, `sources.py`, `discovery.py` | Config precedence/clamping, `endpoint`/`mirrors` sources, JSON parsers | `tests/test_config.py`, `tests/test_sources.py`, `tests/test_discovery.py` |
| `watch/http.py`, `probes.py`, `models.py` | Public IP resolution, redirect pinning, streaming digest, 10 probes | `tests/test_probes.py`, `tests/test_network_regressions.py` |
| `watch/runner.py`, `scheduler.py` | Fast/slow orchestration, degraded fallback, 7-day `Rotation` & `Ticker` | `tests/test_runner.py`, `tests/test_scheduler.py`, `tests/test_monitor_regressions.py` |
| `watch/state.py`, `store.py` | `AlertState` windows, suppression tree, mute retention, JSON store | `tests/test_state.py`, `tests/test_state_regressions.py`, `tests/test_store.py` |
| `watch/commands.py`, `render.py` | `CommandGate`, impact rendering, `safe()` & `clamp()` sanitization | `tests/test_commands.py`, `tests/test_render.py` |
| `tools/check-no-endpoints.py` | Static endpoint, mirror, and credential leak guardrail | `tests/test_guardrail_endpoints.py`, `tests/test_guardrail_regressions.py` |

Run offline verification (`252` unit tests total; `5` `AiohttpBoundaryTest` cases skip when system `python3` lacks `aiohttp`):

```sh
python3 -m unittest discover -s tests -t . -v
python3 tools/check-no-endpoints.py --verbose
python3 -m compileall -q tools watch main.py
```

## Key Architectural Decisions (ADRs) & Migration

- **ADR-1 (MD5 + Manifest `chunk_size`)**: Uses each manifest's declared `chunk_size` and 32-hex chunk MD5s instead of SHA-256 or a hardcoded 16 MiB slice so probe verdicts stay identical to the distribution client's own validation.
- **ADR-2 (Deterministic Rotation vs Random Sampling)**: Persistent `(mirror, file, chunk)` cursor rotation keeps traffic bounded per cycle while giving `/线路 覆盖率` an auditable 7-day byte coverage metric.
- **ADR-3 (No Default `entry_url` & Separate `User-Agent`)**: Refusing to fall back to a baked-in entrypoint prevents false green monitoring on unconfigured deployments; `resource-watch/1.0` keeps CDN logs separable from real user downloads.

### Configuration Migration Summary

| Legacy / Example Syntax | Current Runtime Contract | Action Needed |
| --- | --- | --- |
| `alert.fire_after: [2, 3]`, `alert.recover_after: 2` (`config.example.json`) | `alert.fire_after_failures: 2`, `alert.fire_window: 3`, `alert.recover_after_successes: 2` | Replace legacy array/shorthand keys when adapting `config.example.json` |
| Top-level `entry_url` + `mirrors` set together | `entry_url` wins whenever non-empty | Clear `entry_url` if switching to static `mirrors` mode |
