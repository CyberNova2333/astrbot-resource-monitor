---
title: Contracts, Security Gates & Extensions
description: Security boundaries, all ten probe contracts, upstream config and manifest schemas, extension interfaces, cross-module alert/outbox behavior, and FAQ.
---

# Contracts, Security Gates & Extensions

## Capability Boundaries & Shared-Host Security

Because untrusted mirror configs and shared chat rooms can inject malicious URLs or control strings, `watch/` enforces non-overridable guardrails:

- **Public Network Pinning (`watch/http.py`)**: `validate_public_url` permits credential-free `http`/`https` URLs only and rejects `localhost`, non-canonical numeric hosts, and private/reserved/multicast literals (including embedded IPv4-in-IPv6 forms). `PublicResolver` pins `TCPConnector` strictly to already validated public IPs (`require_public_address`), while TLS cert probing (`_tls_not_after`) verifies every `getaddrinfo` IP before connecting with the original SNI `server_hostname`. Redirects are disabled (`allow_redirects=False`) and validated hop-by-hop up to `MAX_REDIRECTS = 5`, with `DummyCookieJar()` and `trust_env=False`.
- **Memory & Streaming Caps**: Buffered `HttpClient.fetch` obeys `min(MAX_BUFFER_BYTES, max_body_bytes)` where `MAX_BUFFER_BYTES = 64 MiB` cannot be inflated by remote manifests; oversized chunks emit `unknown=True`. Streaming `digest()` caps reads at `meta.size + 1 MiB` (min `1800s` stream timeout) and fails immediately on overflow.
- **Command Gate (`watch/commands.py`)**: Unlisted sessions get silent drops; `测`/`test` and `配置`/`config` share one global `"heavy"` cooldown (`60s` default); chat-triggered probes force `allow_heavy=False` so full packages are never downloaded on demand; `/线路 确认` (`ack`) unconditionally verifies admin status in `main.py`.
- **Output Sanitization (`watch/render.py`)**: `safe()` replaces ASCII control/newline characters with spaces, strips invisible Unicode formatting chars, converts platform code prefixes (`[CQ:`, `[at:`, etc.) to fullwidth `［tag：`, neutralizes `@全体成员`/`@everyone`/`@all` to `＠...`, and caps fields at `MAX_FIELD = 160` and messages at `MAX_MESSAGE = 3000`.

## Ten Probe Contracts

| Probe | Severity | Validation Contract | `unknown=True` & Edge Rules |
| --- | --- | --- | --- |
| `配置源可达性` | `P0` | Endpoint returns HTTP 200 + valid JSON + non-empty `mirrors[]` | Distinguishes transport failure vs corrupt JSON; absent in `mirrors` mode |
| `线上配置合理性` | `P0`/`P1` | Guards against `>=50%` drop in enabled mirrors (when previously `>=2`, `P0`), vanished `settings` (`P1`), non-public mirror URLs (`P1`), zero enabled mirrors (`P0`), `client.version` format & non-regression (`P0`), and `proxy.base` trailing `/` (`P1`) | Missing `client.version` -> `unknown=True`; failed checks block `last_good_snapshot` promotion |
| `清单可达性` | `P1` | Fetches `manifest.json` (`NO_CACHE`, max 4 concurrent); validates positive `size`/`chunk_size`, exact chunk count, and 32-hex MD5s | Corrupt file records are skipped and named without aborting other entries; mirror failure suppresses child checks |
| `线路一致性` | `P1` | Pure cross-mirror fingerprint comparison requiring a strict majority (`count * 2 > total_mirrors`) | 1:1 ties or lack of majority mark `unknown=True` and pause baseline chunk comparison |
| `块内容校验` | `P1` | Fetches next rotating `(mirror, file, chunk)` slice and verifies exact byte length + MD5 | Skipped chunks exceeding buffer cap mark `unknown=True` and do **not** advance 7-day coverage |
| `Range 支持` | `P1` | Chunk GET omits cache-busting headers and demands HTTP `206` with matching `Content-Range` | Returning HTTP `200` (ignoring `Range`) fails `P1` |
| `线路速率` | `P2` | Converts chunk transfer rate to kbps and compares against `settings.min_speed_kbps` | Missing threshold (or `mirrors` mode) / incomplete transfer -> `unknown=True` |
| `版本 json` | `P1` | Fetches declared `watch.version_files` (`NO_CACHE`), requiring valid `version`, positive `size`, and 32-hex `md5` | No `version_files` declared -> `unknown=True` silent skip |
| `热更包整包核对` | `P1` | Streams mapped `watch.packages` via `digest()` (`Semaphore(2)`), checking total bytes + MD5 | Re-tried on fast interval on failure/recovery; skipped on manual commands (`allow_heavy=False`) |
| `证书有效期` | `P2`/`P0` | Daily (`86400s`) TLS handshake against HTTPS `(host, port)` reading `notAfter` | `<14d` -> `P2`, `<3d` -> `P0`; connection/lookup failure -> `unknown=True` |

## Upstream JSON Contracts & Extension Interfaces

- **Endpoint JSON (`watch/discovery.py`)**: Requires `mirrors[]` (each with `base`). Optional sections `settings.min_speed_kbps`, `client.version`, `proxy.base`, and `watch: {"version_files": [...], "packages": {...}}` progressively unlock extra probes.
- **`manifest.json`**: Each file entry needs positive integers `size`, `chunk_size`, and `chunks` containing `ceil(size / chunk_size)` 32-hex MD5 strings.
- **Pluggable `Source` (`watch/sources.py`)**: Subclass `Source`, return `(ProbeResult, Discovered)` from `discover(client)`, and register its type in `sources.build()`. Probes and `AlertState` require zero changes.
- **HTTP Abstraction (`watch/http.py`)**: `Monitor` depends only on `HttpClient.fetch()` and `HttpClient.digest()`, allowing offline `FakeClient` test doubles in `tests/fakes.py`.

## Cross-Module State, Suppression & Delivery

- **Two-Tier Suppression (`watch/state.py`, `watch/probes.py`)**: Firing `KEY_ENTRY` (`配置源可达性`) suppresses config sanity, manifest reachability, and consistency alerts; firing `manifest_key(mirror)` suppresses that mirror's chunk, Range, speed, version, and hot-package alerts. TLS certificate alerts depend only on host/port.
- **Mute & Atomic Outbox (`watch/store.py`, `main.py`)**: Muting never burns un-fired initial alert eligibility and buffers recoveries into `pending_recovery_since` until unmuted. `watch-state.json` persists `AlertState`, `Rotation`, snapshot state, and `outbox`; disk-write failures pause delivery rather than dropping state. `_flush_outbox` re-checks `_discard_stale` before **each** recipient so mid-flush recoveries abort remaining sends.

## Contracts & Extension FAQ

**Q: Why are chunk GETs sent WITHOUT `Cache-Control: no-cache`, unlike endpoint and manifest requests?**
Because real users pull chunks through CDN edge caches; bypassing edge caches would hide stale/truncated cached chunks that only fail in production.

**Q: Can a slow full-package download corrupt state if config changes mid-download?**
No. Before committing ticker or failure timestamps after `probe_hot_package` or `probe_tls_expiry`, `watch/runner.py` checks `self.last_discovered.snapshot() == disc.snapshot()` and discards scheduler state updates when snapshots differ.
