# -*- coding: utf-8 -*-
"""一轮监控从头到尾：自发现 → 探 → 判 → 出消息。**仍然不认识 AstrBot。**

main.py 只做两件事：把这里的 `Monitor` 按时叫醒，把它吐出来的消息发出去。
所以这一层可以在 CI 上离线跑（喂假 HttpClient），也能在换掉 bot 框架时整个搬走。

## 一轮的顺序是有讲究的

    入口 → 合理性 → 各线路清单 → 线路一致性 → 抽样块 →（慢周期）版本 json / 热更包 / 证书

入口在最前面，因为它是抑制链的根：入口拉不到时，下面全部是必然结果。顺序反过来
的话，群里会先收到一串「线路 X 挂了」，人跑去查线路，最后才发现是配置没拉到。

## 快慢两个周期

快周期（默认 5 分钟）跑「挂了用户立刻装不上」的那几个；慢周期（默认 1 小时）
跑版本 json 与证书；热更包按版本变化触发。都由调用方按间隔叫，这里只判「该不该
在这一轮做」。
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from . import probes, render, sources
from .config import LocalConfig
from .http import HttpClient
from .models import FileEntry, Mirror, ProbeResult, manifest_fingerprint
from .scheduler import CoverageReport, HotPackagePolicy, Rotation, Ticker
from .sources import Discovered, PROBE_SOURCE, Source
from .state import AlertState

NOTE_CLIENT_VERSION = "client_version"


@dataclass
class CycleOutcome:
    results: List[ProbeResult] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    config: Optional[Discovered] = None
    entries: Dict[str, FileEntry] = field(default_factory=dict)
    coverage: Optional[CoverageReport] = None


class Monitor:
    def __init__(self, cfg: LocalConfig, client: HttpClient, *,
                 state: Optional[AlertState] = None,
                 rotation: Optional[Rotation] = None,
                 ticker: Optional[Ticker] = None,
                 source: Optional[Source] = None):
        self.cfg = cfg
        self.client = client
        # 「探哪里」全部在这一层之下（watch/sources.py）。判据不认识任何一份
        # 具体配置的形状——换源不改判据。
        self.source = source or sources.build(cfg.source)
        self.state = state or AlertState(
            fire_after=cfg.alert.fire_after_failures,
            window=cfg.alert.fire_window,
            recover_after=cfg.alert.recover_after_successes,
            remind_every_hours=cfg.alert.remind_every_hours)
        self.rotation = rotation or Rotation()
        self.ticker = ticker or Ticker()
        self.hot_policy = HotPackagePolicy(
            on_version_change=cfg.schedule.hot_package_on_version_change,
            min_interval_seconds=cfg.schedule.hot_package_min_interval_seconds)
        self.last_versions: Dict[str, int] = {}
        self.last_results: List[ProbeResult] = []
        # 上一次拉到的**好**配置。只用来在入口挂掉时继续探（降级诊断），
        # **绝不用来判绿**——拿旧数字当判据就是铁律 2 说的漂移。
        self.last_good_snapshot: Optional[dict] = None
        self.last_good_at: float = 0.0
        # 最近一次拿到的清单：`/线路 覆盖率` 要拿它当分母，没有清单就说不出
        # 覆盖率（而不是报一个 0% 或 100%，那两个数都在骗人）。
        self.last_entries: Dict[str, FileEntry] = {}
        self.last_mirror_names: List[str] = []
        self.last_discovered: Optional[Discovered] = None
        self.last_entry_result: Optional[ProbeResult] = None
        self.hot_failures: Dict[str, float] = {}
        self.all_down_probes = set()
        self.mirror_targets: Dict[str, str] = {}

    # ── 一轮 ────────────────────────────────────────────────
    async def run_cycle(self, *, slow: bool = False, only_mirror: Optional[str] = None,
                        allow_heavy: bool = True,
                        now: Optional[float] = None) -> CycleOutcome:
        """跑一轮。

        `allow_heavy=False` 时不做整包核对（几百 MB）——**命令触发的轮次一律
        用它**：群里一条命令不该能让我们去下几百 MB，哪怕发命令的人是管理员，
        也哪怕他只是手滑连发了两次。
        """
        now = now if now is not None else time.time()
        out = CycleOutcome()

        entry_result, disc = await self.source.discover(self.client)
        self.last_entry_result = entry_result
        self.last_discovered = disc
        out.results.append(entry_result)
        if disc is None:
            self.last_entries = {}
            # 入口挂了：**不是就此收工**。这时候恰恰最需要信息——是配置内容被人
            # 改坏了，还是这个出口挂了？线路那边是不是也一起挂了？所以这里不判绿，
            # 但继续用能拿到的线索探一轮，把结论附在那条 P0 后面。
            extra = await self._diagnose_entry_failure(now)
            out.results.extend(extra.results)
            out.messages = self._notify(out.results, enabled_mirrors=0, now=now,
                                        entry_result=entry_result,
                                        extra_lines=extra.lines)
            self.last_results = out.results
            return out

        mutations = probes.check_config_mutation(disc, self.last_good_snapshot)
        out.results.extend(mutations)
        out.config = disc
        sanity = probes.check_config_sanity(disc, self.state.note(NOTE_CLIENT_VERSION))
        out.results.extend(sanity)

        # 线路表来自配置源＝远端内容：先挡住指向本机/内网的地址，再拿去探。
        safe_mirrors, blocked = probes.check_mirror_targets(disc)
        out.results.extend(blocked)
        self.last_mirror_names = [m.name for m in disc.enabled_mirrors]
        self._sync_targets(disc)
        # 异常配置仍可用来诊断，但不能立刻成为下一轮的健康基准。
        if not any(r.counts_as_failure() for r in [entry_result, *mutations, *sanity, *blocked]):
            self.last_good_snapshot = disc.snapshot()
            self.last_good_at = now
            if disc.client_version:
                self.state.remember(NOTE_CLIENT_VERSION, disc.client_version)
        mirrors = [m for m in safe_mirrors
                   if only_mirror is None or m.name == only_mirror]
        if only_mirror is not None and not mirrors:
            out.results.append(ProbeResult(
                ok=True, probe="人工检查", target=only_mirror,
                detail="线上配置里没有这条启用的线路", unknown=True))
            out.messages = self._notify(out.results, enabled_mirrors=len(self.last_mirror_names),
                                        now=now, entry_result=entry_result)
            self.last_results = out.results
            return out

        per_mirror: Dict[str, Dict[str, FileEntry]] = {}
        manifest_slots = asyncio.Semaphore(4)

        async def fetch_manifest(mirror):
            async with manifest_slots:
                result, entries = await probes.probe_manifest(self.client, mirror)
                return mirror, result, entries

        for mirror, result, entries in await asyncio.gather(*(fetch_manifest(m) for m in mirrors)):
            out.results.append(result)
            if entries:
                per_mirror[mirror.name] = entries

        out.results.extend(probes.check_manifest_consistency(per_mirror))

        # 块校验用哪一份清单：多数派那份。少数派的差异已经由一致性探针报过了，
        # 拿它当基准只会让块校验跟着报一遍同一件事。
        reference = _majority_manifest(per_mirror)
        out.entries = reference
        self.last_entries = reference
        if reference:
            self.rotation.prune(reference, mirror_names=self.last_mirror_names)
            out.results.extend(await self._chunk_round(mirrors, reference, disc, now))
            out.coverage = self.rotation.coverage(
                reference, now=now, mirror_names=self.last_mirror_names)

        out.messages = self._notify(out.results, enabled_mirrors=len(disc.enabled_mirrors),
                                    now=now, entry_result=entry_result)
        self.last_results = out.results
        if slow:
            slow_out = await self.run_slow_cycle(disc, mirrors=mirrors, now=now,
                                                 allow_heavy=allow_heavy)
            out.results.extend(slow_out.results)
            out.messages.extend(slow_out.messages)
        return out

    def _sync_targets(self, disc: Discovered):
        current = {m.name: m.base for m in disc.mirrors}
        retired = {name for name, base in self.mirror_targets.items()
                   if current.get(name) != base}
        if retired:
            # 同名线路换了地址时，旧故障与旧覆盖都不能证明新目标的状态。
            for key, entry in list(self.state.entries.items()):
                result = entry.result or {}
                extra = result.get("extra", {})
                mirror = extra.get("mirror") if isinstance(extra, dict) else None
                if isinstance(mirror, str) and mirror in retired:
                    del self.state.entries[key]
            self.rotation = Rotation()
            for ledger in (self.last_versions, self.ticker.last):
                for key in list(ledger):
                    if any(key.startswith(name + "|") for name in retired):
                        ledger.pop(key, None)
        valid_packages = {"%s|%s" % (m.name, disc.packages[name])
                          for m in disc.enabled_mirrors for name in disc.version_files
                          if name in disc.packages}
        self.hot_failures = {key: value for key, value in self.hot_failures.items()
                             if key in valid_packages
                             and not any(key.startswith(name + "|") for name in retired)}
        self.mirror_targets = current

    async def run_slow_cycle(self, disc: Discovered, *, mirrors=None,
                             now: Optional[float] = None,
                             allow_heavy: bool = True) -> CycleOutcome:
        """独立慢任务；网络等待不占用快速巡检的锁。"""
        now = time.time() if now is None else now
        safe, _ = probes.check_mirror_targets(disc)
        selected = safe if mirrors is None else [m for m in mirrors if m in safe]
        results = await self._slow_round(disc, selected, now, allow_heavy)
        # 慢任务期间源可能已换配置，旧检查只能作线索，不能覆盖新配置的状态。
        if self.last_discovered is None or self.last_discovered.snapshot() != disc.snapshot():
            results = [replace(r, unknown=True, detail="旧配置任务，仅供参考：" + r.detail)
                       for r in results]
        entry = self.last_entry_result or ProbeResult(
            ok=True, probe=PROBE_SOURCE, target="配置源", detail="配置源未判定", unknown=True)
        messages = self._notify(results, enabled_mirrors=len(self.last_mirror_names),
                                now=now, entry_result=entry)
        keys = {r.key for r in results}
        self.last_results = [r for r in self.last_results if r.key not in keys] + results
        return CycleOutcome(results=results, messages=messages, config=disc)

    # ── 入口挂掉时的降级诊断 ────────────────────────────────
    async def _diagnose_entry_failure(self, now: float) -> "Degraded":
        """入口拉不到时，尽量把「坏到什么程度」说清楚。

        两条线索，都不产生告警（它们全部标成未判定）：

          1. **备用出口**——区分「配置内容坏了」（要回滚）与「这个出口挂了」
             （要找托管方）。备用能拉到并不代表用户没事：客户端只认它自己那份
             地址，所以主入口那条 P0 一个字都不减；
          2. **上一次的好线路表**——只用来问「线路是不是也一起挂了」。这决定了
             收到告警的人下一步去哪：只有入口挂 = 客户端还在靠内置线路撑着；
             连线路也挂 = 用户现在真的装不上。

        旧线路表有保质期。一天前的线路表说明不了现在，过期就不用——**说不出来
        比说错强**。
        """
        deg = Degraded()
        deg.lines.extend(await self.source.diagnose(self.client))

        if not self.cfg.degraded.probe_with_stale_config:
            return deg
        age = now - self.last_good_at if self.last_good_at else None
        if not self.last_good_snapshot or age is None:
            deg.lines.append("没有可用的旧线路表（这轮是第一次跑，或状态刚清过），"
                             "线路那边现在是什么状况说不出来")
            return deg
        if age > self.cfg.degraded.stale_config_max_age_seconds:
            deg.lines.append("旧线路表是 %s前的，太旧了不拿它探——"
                             "过期的线索会把人带偏" % render.human_duration(age))
            return deg

        stale = Discovered.from_snapshot(self.last_good_snapshot)
        mirrors, _ = probes.check_mirror_targets(stale) if stale else ([], [])
        if not mirrors:
            return deg
        alive = 0
        for mirror in mirrors:
            result, _ = await probes.probe_manifest(self.client, mirror)
            if result.ok:
                alive += 1
            # 标成未判定：用旧线路表探出来的东西只是线索，不进状态机、不触发告警。
            deg.results.append(replace(
                result, unknown=True,
                detail="（旧线路表，仅供参考）" + result.detail))
        deg.lines.append("用 %s前的旧线路表顺带探了一下：%d/%d 条线路的清单还拿得到"
                         % (render.human_duration(age), alive, len(mirrors)))
        deg.lines.append("→ " + ("线路那边看着是好的，客户端此刻靠内置线路还能撑，"
                                 "但新配置下不去" if alive == len(mirrors) else
                                 ("线路也在挂，用户现在多半真的装不上"
                                  if alive == 0 else
                                  "部分线路同时在挂，别只盯着入口")))
        return deg

    # ── 抽样块 ──────────────────────────────────────────────
    async def _chunk_round(self, mirrors: Sequence[Mirror],
                           entries: Dict[str, FileEntry], disc: Discovered,
                           now: float) -> List[ProbeResult]:
        """每轮取 N 块，逐块换一条线路。

        为什么不是「每块在每条线路上都验一遍」：那是 N × 线路数 × 块大小的流量，
        跑一天就是几个 GB。轮着来，覆盖照样滚得到，账单不炸。
        """
        out: List[ProbeResult] = []
        if not mirrors:
            return out
        by_name = {m.name: m for m in mirrors}
        picks = self.rotation.plan_for_mirrors(
            entries, list(by_name), self.cfg.schedule.chunk_probes_per_cycle)
        min_speed = disc.threshold("min_speed_kbps")
        for mirror_name, entry, index in picks:
            mirror = by_name[mirror_name]
            results = await probes.probe_chunk(self.client, mirror, entry, index,
                                               min_speed_kbps=min_speed)
            out.extend(results)
            if any(r.probe == probes.PROBE_CHUNK and r.ok and not r.unknown for r in results):
                self.rotation.mark(entry.name, index, now, mirror=mirror_name)
            else:
                # 没验成的块**不记进覆盖**，但游标照样往前走：卡在坏块上反复
                # 重试，会让其余几百块永远轮不到。
                self.rotation.advance(entry.name, index, mirror=mirror_name)
        return out

    # ── 慢周期 ──────────────────────────────────────────────
    async def _slow_round(self, disc: Discovered, mirrors: Sequence[Mirror],
                          now: float, allow_heavy: bool = True) -> List[ProbeResult]:
        out: List[ProbeResult] = []
        version_files = disc.version_files
        if not version_files:
            out.append(ProbeResult(
                ok=True, probe=probes.PROBE_VERSION, target="热更",
                detail="配置源没有声明要探哪些热更版本文件，跳过热更相关探针"
                       "（不知道该探什么时保持沉默，比拿一份猜的清单去报警好）",
                unknown=True))

        # 限制整包并发，快周期使用同一客户端但不等待这里的下载。
        semaphore = asyncio.Semaphore(2)

        async def check_version(mirror, name):
            async with semaphore:
                found = []
                result, meta = await probes.probe_version_json(self.client, mirror, name)
                found.append(result)
                if meta is None or not meta.is_valid():
                    return found
                package = disc.packages.get(name)
                if not package or not allow_heavy:
                    return found
                key = "%s|%s" % (mirror.name, package)
                last_failure = self.hot_failures.get(key)
                if last_failure is not None:
                    if now - last_failure < self.cfg.schedule.interval_fast_seconds:
                        return found
                elif not self.hot_policy.should_check(key, meta.version, self.ticker,
                                                       self.last_versions, now):
                    return found
                checked = await probes.probe_hot_package(self.client, mirror, package, meta)
                found.append(checked)
                current = self.last_discovered and self.last_discovered.snapshot() == disc.snapshot()
                if not current:
                    return found
                if checked.ok and not checked.unknown:
                    entry = self.state.entries.get(checked.key)
                    recovering = (self.state.is_firing(checked.key) and entry is not None
                                  and entry.successes + 1 < self.state.recover_after)
                    if recovering:
                        self.hot_failures[key] = now
                    else:
                        self.ticker.mark(key, now)
                        self.last_versions[key] = meta.version
                        self.hot_failures.pop(key, None)
                else:
                    # 失败确认走短间隔，不能被成功检查的六小时间隔吞掉。
                    self.hot_failures[key] = now
                return found

        async def check_tls(host, port):
            key = "tls|%s|%d" % (host, port)
            if not self.ticker.due(key, 86400.0, now):
                return []
            result = await probes.probe_tls_expiry(host, port, now=now)
            if self.last_discovered and self.last_discovered.snapshot() == disc.snapshot():
                self.ticker.mark(key, now)
            return [result]

        jobs = [check_version(m, name) for m in mirrors for name in version_files]
        tls_targets = set()
        for mirror in mirrors:
            parsed = urlsplit(mirror.base)
            if parsed.scheme == "https" and parsed.hostname:
                tls_targets.add((parsed.hostname, parsed.port or 443))
        jobs.extend(check_tls(host, port) for host, port in sorted(tls_targets))
        for found in await asyncio.gather(*jobs):
            out.extend(found)
        return out

    # ── 出消息 ──────────────────────────────────────────────
    def _notify(self, results: Sequence[ProbeResult], *, enabled_mirrors: int,
                now: float, entry_result: ProbeResult,
                extra_lines: Optional[Sequence[str]] = None) -> List[str]:
        notes = self.state.ingest(results, now=now)
        active = self.state.active_results()
        by_probe = {}
        for r in active:
            by_probe.setdefault(r.probe, []).append(r)
        current_outages = {probe for probe, group in by_probe.items()
                           if render.all_mirrors_down(group, self.last_mirror_names)}
        previous_outages = set(self.all_down_probes)
        # 未发出的静音/抑制事件不消耗首次升级提醒。
        self.all_down_probes &= current_outages
        if not notes:
            return []
        line = render.upstream_line(entry_result.ok and not entry_result.unknown,
                                    entry_result.detail, now)
        messages = []
        for group in render.group_notifications(
                notes, enabled_mirrors, active_results=active,
                mirror_names=self.last_mirror_names):
            # 入口自己那条不需要再附一行「上游正常」——它就是上游。
            is_entry = group[0].result.probe == PROBE_SOURCE
            # 入口自己那条不需要再附一行「上游正常」——它就是上游。它要附的是
            # 降级诊断：坏到什么程度、下一步该去哪。
            message = render.render_group(
                group, enabled_mirrors=enabled_mirrors,
                mirror_names=self.last_mirror_names,
                prefix=self.cfg.notify.prefix,
                at_all=self.cfg.notify.at_all_on_p0,
                upstream_line="" if is_entry else line,
                extra_lines=list(extra_lines or []) if is_entry else None)
            if group[0].result.probe in previous_outages:
                message.at_all = False
            if group[0].result.probe in current_outages:
                self.all_down_probes.add(group[0].result.probe)
            messages.append(message)
        return messages

    # ── 落盘 ────────────────────────────────────────────────
    def snapshot(self) -> dict:
        data = self.state.to_dict()
        data["rotation"] = self.rotation.to_dict()
        data["ticker"] = self.ticker.to_dict()
        data["last_versions"] = dict(self.last_versions)
        data["hot_failures"] = dict(self.hot_failures)
        data["all_down_probes"] = sorted(self.all_down_probes)
        data["mirror_targets"] = dict(self.mirror_targets)
        # 好配置也落盘：bot 重启后入口正好是挂的，没有它就连「线路是不是也挂了」
        # 都答不上来——而那是重启后第一条告警最该回答的问题。
        data["last_good_config"] = self.last_good_snapshot
        data["last_good_at"] = self.last_good_at
        return data

    def restore(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.state.load_dict(data)
        self.rotation = Rotation.from_dict(data.get("rotation"))
        self.ticker = Ticker.from_dict(data.get("ticker"))
        lv = data.get("last_versions")
        if isinstance(lv, dict):
            self.last_versions = {}
            for k, v in lv.items():
                try:
                    self.last_versions[str(k)] = int(v)
                except (ValueError, TypeError, OverflowError):
                    continue
        self.hot_failures = Ticker.from_dict(data.get("hot_failures")).last
        outages = data.get("all_down_probes")
        self.all_down_probes = {s for s in outages if isinstance(s, str)} if isinstance(outages, list) else set()
        targets = data.get("mirror_targets")
        self.mirror_targets = {k: v for k, v in targets.items()
                               if isinstance(k, str) and isinstance(v, str)} if isinstance(targets, dict) else {}
        good = data.get("last_good_config")
        if isinstance(good, dict):
            restored = Discovered.from_snapshot(good)
            self.last_good_snapshot = restored.snapshot() if restored else None
            try:
                self.last_good_at = float(data.get("last_good_at") or 0.0)
                if not math.isfinite(self.last_good_at):
                    self.last_good_at = 0.0
            except (TypeError, ValueError, OverflowError):
                self.last_good_at = 0.0


@dataclass
class Degraded:
    """降级诊断的产出：几条给人看的话 + 几条不判绿的探测结果。"""

    lines: List[str] = field(default_factory=list)
    results: List[ProbeResult] = field(default_factory=list)


def _majority_manifest(per_mirror: Dict[str, Dict[str, FileEntry]]
                       ) -> Dict[str, FileEntry]:
    """按完整内容取严格多数；没有多数时不拿任意一份给其他线路定罪。"""
    if not per_mirror:
        return {}
    buckets: Dict[str, List[Dict[str, FileEntry]]] = {}
    for entries in per_mirror.values():
        fp = manifest_fingerprint(entries)
        buckets.setdefault(fp, []).append(entries)
    best = max(buckets.values(), key=lambda group: (len(group), len(group[0])))
    return best[0] if len(best) * 2 > len(per_mirror) else {}



