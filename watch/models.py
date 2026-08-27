# -*- coding: utf-8 -*-
"""判据层的数据形状。这里只有 dataclass，没有 I/O，也没有默认地址。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence


class Severity(str, Enum):
    """级别绑定**用户影响**，不绑定技术严重性。

    判据：这个告警响了，收到的人现在要不要爬起来？
      P0  全部线路的同一环节都失败 —— 新用户装不上，得立刻处理
      P1  单条线路失败 / 内容不一致 —— 一部分人受影响，小时级
      P2  趋势类（证书快过期、速度劣化）—— 每日汇总里出现一次就够
      INFO 恢复通知、配置变更
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    INFO = "INFO"

    @property
    def emoji(self) -> str:
        return {"P0": "🔴", "P1": "🟠", "P2": "🟡", "INFO": "⚪"}[self.value]


@dataclass(frozen=True)
class ProbeResult:
    """一次探测的结论。

    `detail` 是给人读的，会**原样进告警消息**——所以它要写成「收到的人不用打开
    电脑就能判断要不要起床」的样子，而不是 `HTTPError(...)` 的 repr。

    `suppress_key` 是抑制链用的：本结果依赖谁。上游 FIRING 时，本结果不单独报
    ——`config.json` 拉不到时「各线路 manifest 都失败」是必然结果，单独报它只是
    在刷屏（CLAUDE.md 铁律 6）。

    `unknown=True` 表示**判据没跑成**（不是「探到坏」）：本机 DNS 抽风、缺可选
    依赖、线上配置没给阈值……这类一律不报警（铁律 7：探针宁可漏报）。
    """

    ok: bool
    probe: str
    target: str
    detail: str
    elapsed_ms: int = 0
    severity: Severity = Severity.P1
    suppress_key: Optional[str] = None
    unknown: bool = False
    extra: Dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """去重键：同一 `(探针, 目标)` 只报一次，直到恢复或升级。"""
        return "%s|%s" % (self.probe, self.target)

    def counts_as_failure(self) -> bool:
        return (not self.ok) and (not self.unknown)


@dataclass(frozen=True)
class Mirror:
    """线路表里的一条。字段与线上配置同名，**不在这里补默认线路**。"""

    name: str
    base: str
    weight: int = 0
    chunks: int = 0
    enabled: bool = True

    def url_for(self, file_name: str) -> str:
        base = self.base if self.base.endswith("/") else self.base + "/"
        return base + file_name.lstrip("/")


HEX32 = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class FileEntry:
    """清单里的一个文件：总长 + 块大小 + 每块的 **MD5**。

    算法不是我们选的——客户端认包用的就是 MD5（32 位十六进制），监控必须用
    **同一份判据**，否则「监控说好、客户端说坏」（CLAUDE.md 铁律 4）。
    """

    name: str
    size: int
    chunk_size: int
    chunks: Sequence[str]

    @property
    def count(self) -> int:
        return len(self.chunks)

    def range_for(self, index: int) -> tuple:
        """第 index 块的字节区间（闭区间，直接进 Range 头）。

        末块要按 size 截断：不截的话末块会向服务器要文件末尾之后的字节，
        规矩的服务器回 416，看起来就像「这条线路坏了」——那是我们自己算错。
        """
        start = index * self.chunk_size
        end = min(start + self.chunk_size, self.size) - 1
        return start, end

    def is_valid(self) -> bool:
        if self.size <= 0 or self.chunk_size <= 0 or not self.chunks:
            return False
        return all(bool(HEX32.match(h)) for h in self.chunks)


@dataclass(frozen=True)
class VersionMeta:
    """热更包的权威身份：版本号 + 整包 size + 整包 MD5。

    三者缺一，客户端那边就拒绝更新（完整性校验做不了）；监控同样按缺失判坏。
    """

    version: int
    size: int
    md5: str

    def is_valid(self) -> bool:
        return (self.version > 0 and self.size > 0
                and bool(HEX32.match((self.md5 or "").lower())))


@dataclass
class OnlineConfig:
    """线上配置的解析结果。

    **这里不放任何默认值**：拿不到就是拿不到，那本身是 P0（铁律 2）——
    绝不能拿一份旧数字接着跑，那会让监控全绿而用户装不上。
    """

    raw: dict
    mirrors: List[Mirror]

    @property
    def schema(self) -> Optional[int]:
        v = self.raw.get("schema")
        return v if isinstance(v, int) else None

    @property
    def settings(self) -> dict:
        s = self.raw.get("settings")
        return s if isinstance(s, dict) else {}

    @property
    def client(self) -> dict:
        c = self.raw.get("client")
        return c if isinstance(c, dict) else {}

    @property
    def enabled_mirrors(self) -> List[Mirror]:
        return [m for m in self.mirrors if m.enabled]

    def threshold(self, name: str) -> Optional[float]:
        """取一个阈值。**取不到返回 None，不返回兜底值。**

        调用方拿到 None 时应当把对应判据标成 unknown（不报警），而不是拿一个
        写死的数字接着算——那就是「插件里留了第二份判据」。
        """
        v = self.settings.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)
