# -*- coding: utf-8 -*-
"""轮转调度：这一轮该探哪一块，以及什么该隔多久才探一次。

## 为什么是轮转，不是随机

抽样块校验要的是**覆盖**：一轮验一块，一小时十几轮，几天下来全站每个字节都被
验过一遍，而且是滚动持续验证。随机取块看起来也「均匀」，但它给不出「哪些块
还没验过」这个答案——`/线路 覆盖率` 这条命令就没法回答，而那正是这套东西凭
什么说「线上是好的」的依据。

游标记的是 `(线路名, 文件名, 块序号)` 而不是下标：清单会变（加文件、改块大小），记
下标的话清单一变，游标就指到别的东西上，覆盖统计跟着全乱。

## 大件的节奏另算

热更包是数百 MB 级的整包核对。按轮跑等于把带宽烧在一件几天才变一次的事情上，
所以默认只在**版本号变了**的时候跑一次，另加一道最小间隔兜底——这类故障恰恰
只在「包刚换过」的时候出现。
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .models import FileEntry


@dataclass
class CoverageReport:
    total: int = 0
    verified: int = 0
    stale: int = 0
    oldest_age_seconds: float = 0.0

    @property
    def percent(self) -> float:
        return 100.0 * self.verified / self.total if self.total else 0.0


class Rotation:
    """块轮转游标 + 覆盖记录。"""

    def __init__(self, cursor: str = "", seen: Optional[Dict[str, float]] = None,
                 signatures: Optional[Dict[str, str]] = None):
        self.cursor = cursor
        self.seen: Dict[str, float] = dict(seen or {})
        self.signatures: Dict[str, str] = dict(signatures or {})

    @staticmethod
    def _pairs(entries: Dict[str, FileEntry]) -> List[Tuple[str, int]]:
        out: List[Tuple[str, int]] = []
        for name in sorted(entries):
            entry = entries[name]
            out.extend((name, i) for i in range(entry.count))
        return out

    @staticmethod
    def token(name: str, index: int, *, mirror: Optional[str] = None) -> str:
        if mirror is not None:
            return json.dumps([mirror, name, index], ensure_ascii=False, separators=(",", ":"))
        return "%s#%d" % (name, index)

    def plan_for_mirrors(self, entries: Dict[str, FileEntry],
                         mirror_names: Sequence[str], count: int
                         ) -> List[Tuple[str, FileEntry, int]]:
        """对线路与分块的笛卡尔积轮转，避免两个独立游标永远锁在同一对。"""
        self._sync_signatures(entries)
        pairs = self._pairs(entries)
        mirrors = list(dict.fromkeys(mirror_names))
        if not pairs or not mirrors or count <= 0:
            return []
        start = 0
        try:
            mirror, name, index = json.loads(self.cursor)
            start = pairs.index((name, index)) * len(mirrors) + mirrors.index(mirror) + 1
        except (ValueError, TypeError, IndexError):
            pass
        total = len(pairs) * len(mirrors)
        picks = []
        for offset in range(min(count, total)):
            position = (start + offset) % total
            name, index = pairs[position // len(mirrors)]
            picks.append((mirrors[position % len(mirrors)], entries[name], index))
        return picks

    def advance(self, name: str, index: int, *, mirror: Optional[str] = None) -> None:
        """失败也推进游标，但不能把失败记成成功覆盖。"""
        self.cursor = self.token(name, index, mirror=mirror)

    def _sync_signatures(self, entries: Dict[str, FileEntry]) -> None:
        current = {name: hashlib.sha256(json.dumps(
            [e.size, e.chunk_size, list(e.chunks)], separators=(",", ":")
        ).encode("utf-8")).hexdigest() for name, e in entries.items()}
        changed = {name for name, signature in current.items()
                   if self.signatures.get(name) != signature}
        for token in list(self.seen):
            try:
                identity = json.loads(token)
            except (ValueError, TypeError):
                continue
            if (isinstance(identity, list) and len(identity) == 3
                    and isinstance(identity[1], str) and identity[1] in changed):
                del self.seen[token]
        self.signatures = current

    def plan(self, entries: Dict[str, FileEntry], count: int
             ) -> List[Tuple[FileEntry, int]]:
        """接着上次的位置往下取 count 块（绕回开头）。清单为空时返回空。"""
        pairs = self._pairs(entries)
        if not pairs or count <= 0:
            return []
        start = 0
        if self.cursor:
            try:
                name, _, idx = self.cursor.rpartition("#")
                start = pairs.index((name, int(idx))) + 1
            except (ValueError, IndexError):
                start = 0                       # 清单变了，从头接着滚
        picked: List[Tuple[FileEntry, int]] = []
        n = len(pairs)
        for k in range(min(count, n)):
            name, idx = pairs[(start + k) % n]
            picked.append((entries[name], idx))
        return picked

    def mark(self, name: str, index: int, now: Optional[float] = None,
             *, mirror: Optional[str] = None) -> None:
        now = now if now is not None else time.time()
        self.seen[self.token(name, index, mirror=mirror)] = now
        self.advance(name, index, mirror=mirror)

    def coverage(self, entries: Dict[str, FileEntry],
                 window_seconds: float = 7 * 86400.0,
                 now: Optional[float] = None, *,
                 mirror_names: Optional[Sequence[str]] = None) -> CoverageReport:
        """覆盖率：**窗口内**验过的块占比。

        带窗口是有意的：一个月前验过的块，说明不了这条线路现在是好的。
        没有窗口的覆盖率只会一路涨到 100% 然后永远停在那，等于没有。
        """
        now = now if now is not None else time.time()
        pairs = self._pairs(entries)
        if mirror_names is not None:
            self._sync_signatures(entries)
        mirrors = list(dict.fromkeys(mirror_names)) if mirror_names is not None else [None]
        tokens = [self.token(name, idx, mirror=mirror) for name, idx in pairs for mirror in mirrors]
        report = CoverageReport(total=len(tokens))
        oldest = 0.0
        for token in tokens:
            ts = self.seen.get(token)
            # `is not None`，不是 `if ts`：时间戳 0 是合法值（epoch），
            # 按真值判会把它当成「没验过」。
            if ts is not None and 0 <= now - ts <= window_seconds:
                report.verified += 1
                oldest = max(oldest, now - ts)
            elif ts is not None:
                report.stale += 1
        report.oldest_age_seconds = oldest
        return report

    def prune(self, entries: Dict[str, FileEntry], *,
              mirror_names: Optional[Sequence[str]] = None) -> int:
        """清掉清单里已经不存在的块记录。返回清掉几条。"""
        before = len(self.seen)
        if mirror_names is not None:
            self._sync_signatures(entries)
        mirrors = list(dict.fromkeys(mirror_names)) if mirror_names is not None else [None]
        valid = {self.token(n, i, mirror=m) for n, i in self._pairs(entries) for m in mirrors}
        gone = [k for k in self.seen if k not in valid]
        for k in gone:
            del self.seen[k]
        return before - len(self.seen)

    def to_dict(self) -> dict:
        return {"cursor": self.cursor, "seen": self.seen, "signatures": self.signatures}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Rotation":
        if not isinstance(data, dict):
            return cls()
        signatures = data.get("signatures")
        return cls(cursor=str(data.get("cursor") or ""),
                   seen=_timestamps(data.get("seen")),
                   signatures={k: v for k, v in signatures.items()
                               if isinstance(k, str) and isinstance(v, str)}
                   if isinstance(signatures, dict) else {})


class Ticker:
    """「这件事隔多久做一次」的记账本。比自己算时间戳少写一堆重复代码。"""

    def __init__(self, last: Optional[Dict[str, float]] = None):
        self.last: Dict[str, float] = dict(last or {})

    def due(self, name: str, interval_seconds: float,
            now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return name not in self.last or now - self.last[name] >= interval_seconds

    def mark(self, name: str, now: Optional[float] = None) -> None:
        self.last[name] = now if now is not None else time.time()

    def to_dict(self) -> dict:
        return dict(self.last)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Ticker":
        if not isinstance(data, dict):
            return cls()
        return cls(_timestamps(data))


def _timestamps(data) -> Dict[str, float]:
    if not isinstance(data, dict):
        return {}
    valid = {}
    for key, value in data.items():
        if isinstance(value, bool):
            continue
        try:
            timestamp = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(timestamp) and timestamp >= 0:
            valid[str(key)] = timestamp
    return valid


@dataclass
class HotPackagePolicy:
    """热更包整包核对的节奏。

    版本变了就查（那是唯一会引入坏包的时刻），否则按最小间隔兜一次底——
    「一直没变」也可能是这条线路的缓存把新包挡住了，那也是故障。
    """

    on_version_change: bool = True
    min_interval_seconds: float = 21600.0

    def should_check(self, key: str, version: int, ticker: Ticker,
                     last_versions: Dict[str, int],
                     now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        changed = last_versions.get(key) != version
        if self.on_version_change and changed:
            return True
        return ticker.due(key, self.min_interval_seconds, now)
