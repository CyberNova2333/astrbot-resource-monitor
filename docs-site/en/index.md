---
layout: home

hero:
  name: AstrBot Resource Monitor
  text: Distribution Route Probe Plugin
  tagline: Scheduled resource-distribution monitor for AstrBot that verifies remote config endpoints, manifests, HTTP Range chunks, MD5 checksums, hot-update packages, and TLS expiry with debounced alerting and QQ official acknowledgment.
  actions:
    - theme: brand
      text: 1. Quick Start & Config
      link: /en/docs/
    - theme: alt
      text: 2. Contracts & Extensions
      link: /en/docs/contracts
    - theme: alt
      text: 3. Architecture & Decisions
      link: /en/docs/architecture

features:
  - title: Live Config Source Discovery
    details: Never duplicates mirror lists or thresholds inside plugin source. Supports remote endpoint discovery or static local mirror lists, plus strictly non-authoritative degraded diagnostics.
  - title: Ten Content & Protocol Probes
    details: Goes beyond HTTP 200 to catch silent config corruption, missing HTTP 206 Range headers, stale mirror manifests, MD5 chunk drift, oversized hot packages, and expiring TLS certs.
  - title: Shared-Host Safety & Delivery
    details: Public IP resolution pinning, per-hop redirect checks, 64 MiB buffer cap, CommandGate rate limiting, output sanitization, persistent outbox, and QQ official viewer-bound ack.
---

## Quick Entry by Role / Goal

| Role / Goal | Start Here | What You Get |
| --- | --- | --- |
| Deploy plugin & wire chat alerts | [1. Overview & Installation](/en/docs/) & [Configuration Matrix](/en/docs/configuration) | Install under AstrBot `data/plugins/`, configure `endpoint` or `mirrors`, set session UMOs, and troubleshoot setup issues |
| Integrate sources or verify probe rules | [2. Probe Contracts & Extension Points](/en/docs/contracts) | Inspect all 10 probes, `unknown=True` rules, JSON schemas, `Source`/`HttpClient` extension points, and SSRF boundaries |
| Trace source code, tests & migrations | [3. Execution Flow, Topology & Decisions](/en/docs/architecture) | Walk through a full check-to-ack run, explore the interactive architecture view, and check schema migrations & ADRs |

## Interactive Topology Overview

<div class="archify-diagram-card" style="margin: 1.5rem 0; border: 1px solid var(--vp-c-border); border-radius: 12px; overflow: hidden; background: var(--vp-c-bg-soft); box-shadow: 0 4px 16px rgba(0,0,0,0.06);">
  <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 18px; background: var(--vp-c-bg-elv); border-bottom: 1px solid var(--vp-c-border); font-size: 13px;">
    <span style="font-weight: 600; color: var(--vp-c-text-1); display: flex; align-items: center; gap: 8px;">
      <span>Host, Plugin, SSRF Guard & Alert Delivery Topology (Pan / Zoom)</span>
    </span>
    <a href="/diagrams/monitor-architecture.html" target="_blank" rel="noreferrer" style="font-size: 12px; color: var(--vp-c-brand-1); text-decoration: none; font-weight: 500;">
      Open Fullscreen
    </a>
  </div>
  <iframe src="/diagrams/monitor-architecture.html" width="100%" height="520px" frameborder="0" style="display: block; border: none;" allowfullscreen loading="lazy"></iframe>
</div>

> **Implementation alignment note**: The embedded diagram depicts high-level topology between AstrBot, the plugin core, SSRF/output guards, and delivery channels. Actual probes implemented in `watch/` inspect **external distribution configs, manifests, HTTP Range chunks, MD5 hashes, hot-update archives, and TLS expiry** — never host CPU or memory telemetry.

## Quick Local Verification

```sh
# 1. Run offline unit tests (252 total; 5 aiohttp boundary tests skip if aiohttp is absent)
python3 -m unittest discover -s tests -t . -v

# 2. Verify no real endpoints or credentials are committed
python3 tools/check-no-endpoints.py --verbose
```

For contributor-oriented deep dives and source evidence logs, inspect `repo-docs/README.md` in the repository root.
