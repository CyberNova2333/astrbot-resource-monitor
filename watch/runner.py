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

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import discovery, probes, render
from .config import LocalConfig
from .http import HttpClient
from .models import FileEntry, Mirror, OnlineConfig, ProbeResult, Severity
from .scheduler import CoverageReport, HotPackagePolicy, Rotation, Ticker
from .state import AlertState

NOTE_CLIENT_VERSION = "client_version"
NOTE_MIRROR_CURSOR = "mirror_cursor"


@dataclass
class CycleOutcome:
    results: List[ProbeResult] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    config: Optional[OnlineConfig] = None
    entries: Dict[str, FileEntry] = field(default_factory=dict)
    coverage: Optional[CoverageReport] = None


class Monitor:
    def __init__(self, cfg: LocalConfig, client: HttpClient, *,
                 state: Optional[AlertState] = None,
                 rotation: Optional[Rotation] = None,
                 ticker: Optional[Ticker] = None):
        self.cfg = cfg
        self.client = client
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
        # 最近一次拿到的清单：`/线路 覆盖率` 要拿它当分母，没有清单就说不出
        # 覆盖率（而不是报一个 0% 或 100%，那两个数都在骗人）。
        self.last_entries: Dict[str, FileEntry] = {}

    # ── 一轮 ────────────────────────────────────────────────
    async def run_cycle(self, *, slow: bool = False, only_mirror: Optional[str] = None,
                        now: Optional[float] = None) -> CycleOutcome:
        now = now if now is not None else time.time()
        out = CycleOutcome()

        entry_result, cfg = await probes.probe_entry(self.client, self.cfg.entry_url)
        out.results.append(entry_result)
        if cfg is None:
            # 入口挂了就到此为止：下游探针此刻探什么都没有意义（探哪里都不知道），
            # 硬探一轮只会在群里刷一堆必然失败。
            out.messages = self._notify(out.results, enabled_mirrors=0, now=now,
                                        entry_result=entry_result)
            self.last_results = out.results
            return out

        out.config = cfg
        out.results.extend(probes.check_config_sanity(
            cfg, self.state.note(NOTE_CLIENT_VERSION)))
        ver = str(cfg.client.get("version") or "").strip()
        if ver:
            self.state.remember(NOTE_CLIENT_VERSION, ver)

        mirrors = [m for m in cfg.enabled_mirrors
                   if only_mirror is None or m.name == only_mirror]
        if only_mirror is not None and not mirrors:
            out.results.append(ProbeResult(
                ok=True, probe="人工检查", target=only_mirror,
                detail="线上配置里没有这条启用的线路", unknown=True))
            self.last_results = out.results
            return out

        per_mirror: Dict[str, Dict[str, FileEntry]] = {}
        for mirror in mirrors:
            result, entries = await probes.probe_manifest(self.client, mirror)
            out.results.append(result)
            if entries:
                per_mirror[mirror.name] = entries

        out.results.extend(probes.check_manifest_consistency(per_mirror))

        # 块校验用哪一份清单：多数派那份。少数派的差异已经由一致性探针报过了，
        # 拿它当基准只会让块校验跟着报一遍同一件事。
        reference = _majority_manifest(per_mirror)
        out.entries = reference
        if reference:
            self.last_entries = reference
        if reference:
            self.rotation.prune(reference)
            out.results.extend(await self._chunk_round(mirrors, reference, cfg, now))
            out.coverage = self.rotation.coverage(reference, now=now)

        if slow:
            out.results.extend(await self._slow_round(cfg, mirrors, now))

        out.messages = self._notify(out.results, enabled_mirrors=len(cfg.enabled_mirrors),
                                    now=now, entry_result=entry_result)
        self.last_results = out.results
        return out

    # ── 抽样块 ──────────────────────────────────────────────
    async def _chunk_round(self, mirrors: Sequence[Mirror],
                           entries: Dict[str, FileEntry], cfg: OnlineConfig,
                           now: float) -> List[ProbeResult]:
        """每轮取 N 块，逐块换一条线路。

        为什么不是「每块在每条线路上都验一遍」：那是 N × 线路数 × 块大小的流量，
        跑一天就是几个 GB。轮着来，覆盖照样滚得到，账单不炸。
        """
        out: List[ProbeResult] = []
        if not mirrors:
            return out
        picks = self.rotation.plan(entries, self.cfg.schedule.chunk_probes_per_cycle)
        cursor = int(self.state.note(NOTE_MIRROR_CURSOR) or 0)
        min_speed = cfg.threshold("min_speed_kbps")
        for entry, index in picks:
            mirror = mirrors[cursor % len(mirrors)]
            cursor += 1
            results = await probes.probe_chunk(self.client, mirror, entry, index,
                                               min_speed_kbps=min_speed)
            out.extend(results)
            if all(r.ok for r in results):
                self.rotation.mark(entry.name, index, now)
            else:
                # 没验成的块**不记进覆盖**，但游标照样往前走：卡在坏块上反复
                # 重试，会让其余几百块永远轮不到。
                self.rotation.cursor = self.rotation.token(entry.name, index)
        self.state.remember(NOTE_MIRROR_CURSOR, str(cursor % max(len(mirrors), 1)))
        return out

    # ── 慢周期 ──────────────────────────────────────────────
    async def _slow_round(self, cfg: OnlineConfig, mirrors: Sequence[Mirror],
                          now: float) -> List[ProbeResult]:
        out: List[ProbeResult] = []
        version_files = discovery.declared_version_files(cfg)
        if not version_files:
            out.append(ProbeResult(
                ok=True, probe=probes.PROBE_VERSION, target="热更",
                detail="线上配置没有声明 watch.version_files，跳过热更相关探针"
                       "（不知道该探什么时保持沉默，比拿一份猜的清单去报警好）",
                unknown=True))
            return out

        for mirror in mirrors:
            for name in version_files:
                result, meta = await probes.probe_version_json(self.client, mirror, name)
                out.append(result)
                if meta is None or not meta.is_valid():
                    continue
                package = discovery.declared_package_for(cfg, name)
                if not package:
                    continue
                key = "%s|%s" % (mirror.name, package)
                if not self.hot_policy.should_check(key, meta.version, self.ticker,
                                                    self.last_versions, now):
                    continue
                out.append(await probes.probe_hot_package(self.client, mirror,
                                                          package, meta))
                self.ticker.mark(key, now)
                self.last_versions[key] = meta.version

        for host in sorted({_host(m.base) for m in mirrors if _host(m.base)}):
            if self.ticker.due("tls|%s" % host, 86400.0, now):
                out.append(await probes.probe_tls_expiry(host, now=now))
                self.ticker.mark("tls|%s" % host, now)
        return out

    # ── 出消息 ──────────────────────────────────────────────
    def _notify(self, results: Sequence[ProbeResult], *, enabled_mirrors: int,
                now: float, entry_result: ProbeResult) -> List[str]:
        notes = self.state.ingest(results, now=now)
        if not notes:
            return []
        line = render.upstream_line(entry_result.ok and not entry_result.unknown,
                                    entry_result.detail, now)
        messages = []
        for group in render.group_notifications(notes, enabled_mirrors):
            # 入口自己那条不需要再附一行「上游正常」——它就是上游。
            attach = "" if group[0].result.probe == probes.PROBE_ENTRY else line
            messages.append(render.render_group(
                group, enabled_mirrors=enabled_mirrors,
                prefix=self.cfg.notify.prefix,
                at_all=self.cfg.notify.at_all_on_p0,
                upstream_line=attach))
        return messages

    # ── 落盘 ────────────────────────────────────────────────
    def snapshot(self) -> dict:
        data = self.state.to_dict()
        data["rotation"] = self.rotation.to_dict()
        data["ticker"] = self.ticker.to_dict()
        data["last_versions"] = dict(self.last_versions)
        return data

    def restore(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.state.load_dict(data)
        self.rotation = Rotation.from_dict(data.get("rotation"))
        self.ticker = Ticker.from_dict(data.get("ticker"))
        lv = data.get("last_versions")
        if isinstance(lv, dict):
            self.last_versions = {str(k): int(v) for k, v in lv.items()
                                  if str(v).lstrip("-").isdigit()}


def _majority_manifest(per_mirror: Dict[str, Dict[str, FileEntry]]
                       ) -> Dict[str, FileEntry]:
    """取出现次数最多的那份清单。平票时取文件数最多的一份（能验的更多）。"""
    if not per_mirror:
        return {}
    buckets: Dict[str, List[Dict[str, FileEntry]]] = {}
    for entries in per_mirror.values():
        fp = "|".join("%s:%d:%d" % (n, e.size, e.chunk_size)
                      for n, e in sorted(entries.items()))
        buckets.setdefault(fp, []).append(entries)
    best = max(buckets.values(), key=lambda group: (len(group), len(group[0])))
    return best[0]


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""
