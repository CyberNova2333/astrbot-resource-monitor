# -*- coding: utf-8 -*-
"""轮转调度：这一轮该探哪一块，以及什么该隔多久才探一次。

## 为什么是轮转，不是随机

抽样块校验要的是**覆盖**：一轮验一块，一小时十几轮，几天下来全站每个字节都被
验过一遍，而且是滚动持续验证。随机取块看起来也「均匀」，但它给不出「哪些块
还没验过」这个答案——`/线路 覆盖率` 这条命令就没法回答，而那正是这套东西凭
什么说「线上是好的」的依据。

游标记的是 `(文件名, 块序号)` 而不是下标：清单会变（加文件、改块大小），记
下标的话清单一变，游标就指到别的东西上，覆盖统计跟着全乱。

## 大件的节奏另算

热更包是数百 MB 级的整包核对。按轮跑等于把带宽烧在一件几天才变一次的事情上，
所以默认只在**版本号变了**的时候跑一次，另加一道最小间隔兜底——这类故障恰恰
只在「包刚换过」的时候出现。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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

    def __init__(self, cursor: str = "", seen: Optional[Dict[str, float]] = None):
        self.cursor = cursor
        self.seen: Dict[str, float] = dict(seen or {})

    @staticmethod
    def _pairs(entries: Dict[str, FileEntry]) -> List[Tuple[str, int]]:
        out: List[Tuple[str, int]] = []
        for name in sorted(entries):
            entry = entries[name]
            out.extend((name, i) for i in range(entry.count))
        return out

    @staticmethod
    def token(name: str, index: int) -> str:
        return "%s#%d" % (name, index)

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

    def mark(self, name: str, index: int, now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        self.seen[self.token(name, index)] = now
        self.cursor = self.token(name, index)

    def coverage(self, entries: Dict[str, FileEntry],
                 window_seconds: float = 7 * 86400.0,
                 now: Optional[float] = None) -> CoverageReport:
        """覆盖率：**窗口内**验过的块占比。

        带窗口是有意的：一个月前验过的块，说明不了这条线路现在是好的。
        没有窗口的覆盖率只会一路涨到 100% 然后永远停在那，等于没有。
        """
        now = now if now is not None else time.time()
        pairs = self._pairs(entries)
        report = CoverageReport(total=len(pairs))
        oldest = 0.0
        for name, idx in pairs:
            ts = self.seen.get(self.token(name, idx))
            # `is not None`，不是 `if ts`：时间戳 0 是合法值（epoch），
            # 按真值判会把它当成「没验过」。
            if ts is not None and now - ts <= window_seconds:
                report.verified += 1
                oldest = max(oldest, now - ts)
            elif ts is not None:
                report.stale += 1
        report.oldest_age_seconds = oldest
        return report

    def prune(self, entries: Dict[str, FileEntry]) -> int:
        """清掉清单里已经不存在的块记录。返回清掉几条。"""
        valid = {self.token(n, i) for n, i in self._pairs(entries)}
        gone = [k for k in self.seen if k not in valid]
        for k in gone:
            del self.seen[k]
        return len(gone)

    def to_dict(self) -> dict:
        return {"cursor": self.cursor, "seen": self.seen}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Rotation":
        if not isinstance(data, dict):
            return cls()
        seen = data.get("seen")
        return cls(cursor=str(data.get("cursor") or ""),
                   seen={str(k): float(v) for k, v in seen.items()}
                   if isinstance(seen, dict) else {})


class Ticker:
    """「这件事隔多久做一次」的记账本。比自己算时间戳少写一堆重复代码。"""

    def __init__(self, last: Optional[Dict[str, float]] = None):
        self.last: Dict[str, float] = dict(last or {})

    def due(self, name: str, interval_seconds: float,
            now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return now - self.last.get(name, 0.0) >= interval_seconds

    def mark(self, name: str, now: Optional[float] = None) -> None:
        self.last[name] = now if now is not None else time.time()

    def to_dict(self) -> dict:
        return dict(self.last)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Ticker":
        if not isinstance(data, dict):
            return cls()
        return cls({str(k): float(v) for k, v in data.items()})


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
