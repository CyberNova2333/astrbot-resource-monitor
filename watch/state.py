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

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .models import ProbeResult, Severity

GREEN = "GREEN"
FIRING = "FIRING"


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
        self.muted_until = now + max(0.0, seconds)
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
        下一轮正常报出来，而**期间恢复的不会补发一堆过期消息**。
        """
        now = now if now is not None else time.time()
        # 这个集合要**边吃边更新**：入口和下游线路的失败通常出现在同一轮里，
        # 如果只用「进这一轮之前谁在报」，抑制链就永远慢一轮——第一轮该抑制的
        # 全都跑出去了，而那一轮恰恰是最吵的一轮（1 条入口 + N 条线路）。
        # 判据依赖 results 的顺序：调用方按依赖顺序给（见 runner 的一轮顺序）。
        firing_keys = {k for k, e in self.entries.items() if e.status == FIRING}
        out: List[Notification] = []

        for r in results:
            if r.unknown:
                # 判据没跑成：既不算坏，也不算好——它不该把 FIRING 的东西
                # 「治好」，也不该把 GREEN 的东西推向告警。
                continue
            entry = self.entries.setdefault(r.key, Entry(key=r.key))
            entry.last_detail = r.detail
            entry.severity = r.severity.value
            note = self._advance(entry, r, now, firing_keys)
            if entry.status == FIRING:
                firing_keys.add(entry.key)
            else:
                firing_keys.discard(entry.key)
            if note:
                out.append(note)

        if self.is_muted(now):
            return []
        return out

    def _advance(self, entry: Entry, r: ProbeResult, now: float,
                 firing_keys: set) -> Optional[Notification]:
        failed = r.counts_as_failure()
        entry.window.append(failed)
        if len(entry.window) > self.window:
            entry.window = entry.window[-self.window:]

        if failed:
            entry.successes = 0
            if not entry.first_failed_at:
                entry.first_failed_at = now
            if entry.status == FIRING:
                if now - entry.last_notified_at >= self.remind_every:
                    entry.last_notified_at = now
                    return Notification("remind", r.severity, r,
                                        entry.first_failed_at,
                                        now - entry.first_failed_at)
                return None
            if sum(entry.window) >= self.fire_after:
                # 抑制链：我依赖的那个已经在报了，我这条是必然结果，不单独报。
                # 状态照样进 FIRING——否则上游恢复后，我这条会被当成新故障。
                entry.status = FIRING
                entry.last_notified_at = now
                if r.suppress_key and r.suppress_key in firing_keys:
                    return None
                return Notification("fire", r.severity, r, entry.first_failed_at,
                                    now - entry.first_failed_at)
            return None

        entry.successes += 1
        if entry.status == FIRING and entry.successes >= self.recover_after:
            since = entry.first_failed_at
            entry.status = GREEN
            entry.first_failed_at = 0.0
            entry.last_notified_at = 0.0
            entry.window = []
            return Notification("recover", Severity.INFO, r, since,
                                now - since if since else 0.0)
        return None

    # ── 查询 ────────────────────────────────────────────────
    def firing(self) -> List[Entry]:
        return [e for e in self.entries.values() if e.status == FIRING]

    def is_firing(self, key: str) -> bool:
        e = self.entries.get(key)
        return bool(e and e.status == FIRING)

    def note(self, name: str) -> Optional[str]:
        return self.notes.get(name)

    def remember(self, name: str, value: str) -> None:
        self.notes[name] = value

    # ── 落盘 ────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "muted_until": self.muted_until,
            "notes": self.notes,
            "entries": {k: asdict(e) for k, e in self.entries.items()},
        }

    def load_dict(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.muted_until = float(data.get("muted_until") or 0.0)
        notes = data.get("notes")
        self.notes = {str(k): str(v) for k, v in notes.items()} if isinstance(notes, dict) else {}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return
        for key, raw in entries.items():
            if not isinstance(raw, dict):
                continue
            self.entries[key] = Entry(
                key=str(key),
                status=str(raw.get("status") or GREEN),
                window=[bool(x) for x in (raw.get("window") or [])][-self.window:],
                first_failed_at=float(raw.get("first_failed_at") or 0.0),
                last_notified_at=float(raw.get("last_notified_at") or 0.0),
                successes=int(raw.get("successes") or 0),
                last_detail=str(raw.get("last_detail") or ""),
                severity=str(raw.get("severity") or Severity.P1.value),
            )

    def save(self, path: str) -> None:
        """尽力而为：写不进去就算了，状态是可丢的，不值得让监控本身崩掉。"""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False)
            os.replace(tmp, path)          # 原子替换，避免半截文件
        except OSError:
            pass

    def load(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.load_dict(json.load(f))
        except (OSError, ValueError):
            pass                            # 没有/坏了 = 当作全新开始
