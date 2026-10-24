# -*- coding: utf-8 -*-
"""故障状态机 + 去重 + 抑制链 + 静音 + 落盘。

**会喊狼来了的告警比没有告警更糟**（CLAUDE.md 铁律 6）。这个文件就是那条铁律的
实现，四件事：

  1. **连续 N 次才报**（默认三轮里坏两轮）。网络抖动是常态，一次超时就 @ 全体，
     两天之后就没人看群了；
  2. **同一 (探针, 目标) 只报一次**，直到恢复或升级；持续故障每 N 小时提醒一次
     「还在坏」，不是每轮都刷；
  3. **上游坏了抑制下游**：入口拉不到时，「各线路清单都失败」是必然结果，
     不该单独报；
  4. **恢复也要报**——不发恢复通知的监控，人会一直以为还坏着。

外加一个静音（维护窗口）。没有它，自己调线路时会被自己的 bot 轰炸，两周后人
就把整个 bot 关掉了——那等于监控不存在。

## 为什么要落盘

bot 一重启，内存里的状态全没了，所有仍在持续的故障都会被当成新故障**重报一遍**。
那是告警疲劳最常见的来源。状态是可丢的（丢了最多重报一次），所以落盘写得很糙：
一个 JSON，写坏了就当没有。
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

from . import store
from .models import ProbeResult, Severity

GREEN = "GREEN"
FIRING = "FIRING"
SEVERITY_ORDER = {Severity.P0.value: 0, Severity.P1.value: 1,
                  Severity.P2.value: 2, Severity.INFO.value: 3}


@dataclass
class Entry:
    """一个 (探针, 目标) 的状态。"""

    key: str
    status: str = GREEN
    window: List[bool] = field(default_factory=list)   # 最近几轮：True=坏
    first_failed_at: float = 0.0
    last_notified_at: float = 0.0
    successes: int = 0
    last_detail: str = ""
    severity: str = Severity.P1.value
    has_notified: bool = False
    notified_severity: Optional[str] = None
    result: Optional[dict] = None
    pending_recovery_since: Optional[float] = None
    pending_recovery_duration: float = 0.0


@dataclass
class Notification:
    """要发出去的一条通知。渲染交给 render.py，这里只决定**发不发、发什么级别**。"""

    kind: str                    # fire / remind / recover
    severity: Severity
    result: ProbeResult
    since: float = 0.0           # 首次失败时刻（fire/remind 用）
    duration_seconds: float = 0.0


class AlertState:
    def __init__(self, fire_after: int = 2, window: int = 3,
                 recover_after: int = 2, remind_every_hours: float = 6.0):
        if fire_after > window:
            raise ValueError("fire_after 不能大于 window")
        self.fire_after = fire_after
        self.window = window
        self.recover_after = recover_after
        self.remind_every = remind_every_hours * 3600.0
        self.entries: Dict[str, Entry] = {}
        self.muted_until: float = 0.0
        self.notes: Dict[str, str] = {}      # 杂项记忆（如上次看到的版本闸门）

    # ── 静音 ────────────────────────────────────────────────
    def mute(self, seconds: float, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        until = now + _number(seconds)
        self.muted_until = until if math.isfinite(until) else now
        return self.muted_until

    def unmute(self) -> None:
        self.muted_until = 0.0

    def is_muted(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return now < self.muted_until

    # ── 主流程 ──────────────────────────────────────────────
    def ingest(self, results: Sequence[ProbeResult],
               now: Optional[float] = None) -> List[Notification]:
        """吃掉一轮结果，返回**这一轮该发出去的通知**（可能是空的）。

        静音期间照常推进状态机、但不产生通知：维护窗口结束后，还在坏的东西会在
        下一轮正常报出来。窗口内发生又恢复的新故障不补发；此前已经报过的
        故障则保留恢复通知，免得维护结束后群里仍只有那条失败消息。
        """
        now = now if now is not None else time.time()
        # 这个集合要**边吃边更新**：入口和下游线路的失败通常出现在同一轮里，
        # 如果只用「进这一轮之前谁在报」，抑制链就永远慢一轮——第一轮该抑制的
        # 全都跑出去了，而那一轮恰恰是最吵的一轮（1 条入口 + N 条线路）。
        # 判据依赖 results 的顺序：调用方按依赖顺序给（见 runner 的一轮顺序）。
        firing_keys = {k for k, e in self.entries.items() if e.status == FIRING}
        out: List[Notification] = []

        # 多块抽样可能产生同一线路的多个 Range/速率结果；一轮只能记一票，
        # 否则一轮里的两个坏块就能越过「连续多轮」门槛，后续好块又会假恢复。
        round_results: Dict[str, ProbeResult] = {}
        for r in results:
            previous = round_results.get(r.key)
            if (previous is None or previous.unknown
                    or (r.counts_as_failure() and not previous.counts_as_failure())
                    or (r.counts_as_failure() and previous.counts_as_failure()
                        and SEVERITY_ORDER[r.severity.value] < SEVERITY_ORDER[previous.severity.value])):
                round_results[r.key] = r
        for r in round_results.values():
            if r.unknown:
                # 判据没跑成：既不算坏，也不算好——它不该把 FIRING 的东西
                # 「治好」，也不该把 GREEN 的东西推向告警。
                continue
            entry = self.entries.setdefault(r.key, Entry(key=r.key))
            entry.last_detail = r.detail
            entry.severity = r.severity.value
            if r.counts_as_failure() or entry.status != FIRING:
                entry.result = asdict(r)
            note = self._advance(entry, r, now, firing_keys)
            if entry.status == FIRING:
                firing_keys.add(entry.key)
            else:
                firing_keys.discard(entry.key)
            if note:
                out.append(note)

        if not self.is_muted(now):
            out.extend(self._drain_recoveries())

        # 干净的条目不留：块校验的键是 (线路, 文件, 块号)，一条线路几百块，
        # 不清理的话状态表会随时间涨到几千条，还每轮全量写盘一次。
        # 判据是「这条还有没有信息量」——见 _evict_clean。
        self._evict_clean()

        return out

    def _drain_recoveries(self) -> List[Notification]:
        """已经确认的恢复不必等慢探针再次到期；本轮复发会先撤销待发恢复。"""
        out = []
        for entry in self.entries.values():
            if entry.status != GREEN or entry.pending_recovery_since is None:
                continue
            result = _result_from_dict(entry.result)
            if result is None or not result.ok or result.unknown:
                continue
            out.append(Notification("recover", Severity.INFO, result,
                                    entry.pending_recovery_since,
                                    entry.pending_recovery_duration))
            entry.pending_recovery_since = None
            entry.pending_recovery_duration = 0.0
        return out

    def _evict_clean(self) -> int:
        """删掉**完全干净**的条目：不在报警、窗口里没有失败、且已经连续成功到
        足以恢复。

        这三条同时成立时，这个条目记住的东西与「从没见过它」完全等价——留着
        只是让状态表和状态文件无限长大。任何一条不成立都保留：窗口里有失败要
        参与「三轮里坏两轮」，FIRING 中的要等恢复，正在恢复的要数够连续成功。
        """
        gone = [k for k, e in self.entries.items()
                if e.status == GREEN and not any(e.window)
                and e.successes >= self.recover_after
                and e.pending_recovery_since is None]
        for k in gone:
            del self.entries[k]
        return len(gone)

    def _advance(self, entry: Entry, r: ProbeResult, now: float,
                 firing_keys: set) -> Optional[Notification]:
        failed = r.counts_as_failure()
        first_failure = not any(entry.window) and entry.status != FIRING
        entry.window.append(failed)
        if len(entry.window) > self.window:
            entry.window = entry.window[-self.window:]

        if failed:
            entry.successes = 0
            entry.pending_recovery_since = None
            entry.pending_recovery_duration = 0.0
            if first_failure:
                entry.first_failed_at = now
            if entry.status != FIRING and sum(entry.window) >= self.fire_after:
                entry.status = FIRING
            if entry.status != FIRING:
                return None
            # 静音与抑制只影响交付，不消耗首次通知或提醒的时间。
            if self.is_muted(now) or (r.suppress_key and r.suppress_key in firing_keys):
                return None
            # 判据最新级别和已经通知过的级别分开记：静音期间的升级不能被
            # 后续覆盖掉，也不能让紧急升级等待完整的周期提醒间隔。
            escalated = (entry.has_notified and entry.notified_severity is not None
                         and SEVERITY_ORDER[r.severity.value]
                         < SEVERITY_ORDER[entry.notified_severity])
            if (entry.has_notified and not escalated
                    and now - entry.last_notified_at < self.remind_every):
                return None
            kind = "remind" if entry.has_notified and not escalated else "fire"
            entry.has_notified = True
            entry.notified_severity = r.severity.value
            entry.last_notified_at = now
            return Notification(kind, r.severity, r, entry.first_failed_at,
                                now - entry.first_failed_at)

        entry.successes += 1
        if entry.status == FIRING and entry.successes >= self.recover_after:
            since = entry.first_failed_at
            was_notified = entry.has_notified
            entry.status = GREEN
            entry.first_failed_at = 0.0
            entry.last_notified_at = 0.0
            entry.has_notified = False
            entry.notified_severity = None
            entry.window = []
            entry.result = asdict(r)
            if self.is_muted(now):
                if was_notified:
                    entry.pending_recovery_since = since
                    entry.pending_recovery_duration = max(0.0, now - since)
                return None
            return Notification("recover", Severity.INFO, r, since,
                                max(0.0, now - since))
        return None

    # ── 查询 ────────────────────────────────────────────────
    def firing(self) -> List[Entry]:
        return [e for e in self.entries.values() if e.status == FIRING]

    def is_firing(self, key: str) -> bool:
        e = self.entries.get(key)
        return bool(e and e.status == FIRING)

    def active_results(self) -> List[ProbeResult]:
        """取仍在故障中的最近结果，供跨轮次的线路影响聚合使用。"""
        return [r for e in self.firing()
                if (r := _result_from_dict(e.result)) is not None]

    def note(self, name: str) -> Optional[str]:
        return self.notes.get(name)

    def remember(self, name: str, value: str) -> None:
        self.notes[name] = value

    # ── 落盘 ────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "version": 2,
            "muted_until": self.muted_until,
            "notes": self.notes,
            "entries": {k: asdict(e) for k, e in self.entries.items()},
        }

    def load_dict(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.muted_until = _number(data.get("muted_until"))
        notes = data.get("notes")
        self.notes = {str(k): str(v) for k, v in notes.items()} if isinstance(notes, dict) else {}
        self.entries = {}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return
        for key, raw in entries.items():
            if not isinstance(raw, dict):
                continue
            window = raw.get("window")
            window = [x for x in window if isinstance(x, bool)] if isinstance(window, list) else []
            status = FIRING if raw.get("status") == FIRING else GREEN
            notified = raw.get("has_notified")
            # 旧格式只在实际生成通知时记时间；未知旧状态保守保留去重行为。
            if not isinstance(notified, bool):
                notified = status == FIRING
            severity = raw.get("severity")
            severity = severity if isinstance(severity, str) and severity in SEVERITY_ORDER else Severity.P1.value
            notified_severity = raw.get("notified_severity")
            if not isinstance(notified_severity, str) or notified_severity not in SEVERITY_ORDER:
                notified_severity = severity if notified else None
            result = _result_from_dict(raw.get("result"))
            self.entries[str(key)] = Entry(
                key=str(key),
                status=status,
                window=window[-self.window:],
                first_failed_at=_number(raw.get("first_failed_at")),
                last_notified_at=_number(raw.get("last_notified_at")),
                successes=int(_number(raw.get("successes"))),
                last_detail=str(raw.get("last_detail") or ""),
                severity=severity,
                has_notified=notified,
                notified_severity=notified_severity,
                result=asdict(result) if result is not None and result.key == str(key) else None,
                pending_recovery_since=_optional_number(raw.get("pending_recovery_since")),
                pending_recovery_duration=_number(raw.get("pending_recovery_duration")),
            )

    def save(self, path: str) -> None:
        store.save_json(path, self.to_dict())

    def load(self, path: str) -> None:
        self.load_dict(store.load_json(path) or {})


def _number(value, default: float = 0.0) -> float:
    """落盘状态可丢弃：坏字段不该阻止整个插件启动。"""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_number(value) -> Optional[float]:
    number = _number(value, default=-1.0)
    return number if number >= 0 else None


def _result_from_dict(raw) -> Optional[ProbeResult]:
    if not isinstance(raw, dict) or not isinstance(raw.get("ok"), bool):
        return None
    if not all(isinstance(raw.get(k), str) for k in ("probe", "target", "detail")):
        return None
    try:
        severity = Severity(raw.get("severity", Severity.P1.value))
    except (TypeError, ValueError):
        return None
    return ProbeResult(raw["ok"], raw["probe"], raw["target"], raw["detail"],
                       elapsed_ms=int(_number(raw.get("elapsed_ms"))),
                       severity=severity,
                       suppress_key=raw.get("suppress_key") if isinstance(raw.get("suppress_key"), str) else None,
                       unknown=raw.get("unknown") is True,
                       extra=raw.get("extra") if isinstance(raw.get("extra"), dict) else {})
