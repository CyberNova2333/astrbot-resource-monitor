# -*- coding: utf-8 -*-
"""把结论渲染成群里那条消息。

**坏消息要能让人不打开电脑就判断要不要起床。** 所以每条告警都带三样：

  · 影响——这个探针挂了，用户那边会发生什么；
  · 已持续多久——刚坏和坏了两小时是两件事；
  · **已经排除了什么**——只报「都挂了」的告警，收到的人第一件事还是得自己爬
    起来查上游，等于没省事。

多条线路同时挂同一个环节时合并成一条 P0：级别绑定的是**用户影响**，不是技术
严重性。一条线路挂了用户还能装（会换线），全部挂了就谁都装不上。
"""

from __future__ import annotations

import time
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence

from .models import ProbeResult, Severity
from .probes import (PROBE_CHUNK, PROBE_CONSISTENCY, PROBE_HOTPKG, PROBE_MANIFEST,
                     PROBE_RANGE, PROBE_SANITY, PROBE_SPEED, PROBE_TLS,
                     PROBE_VERSION)
from .sources import PROBE_SOURCE
from .scheduler import CoverageReport
from .state import Notification

# 「这个探针挂了，用户会怎样」。写在这里是因为它是**监控自己的知识**，
# 不是被监控方的配置——不属于「不许留第二份」的那类东西。
IMPACT = {
    PROBE_SOURCE: "拿不到线路表，客户端会静默回退到它内置的那条；用户无感，只有监控看得见",
    PROBE_SANITY: "配置本身会误伤用户（版本闸门/线路开关写错，影响面是全体）",
    PROBE_MANIFEST: "新用户装不了资源包，老用户的热更也会停",
    PROBE_CHUNK: "这条线路上的文件字节是坏的——用户能下完，但装不上",
    PROBE_RANGE: "分片下载退化成整包重下，表现是『下载特别慢』而不是失败",
    PROBE_VERSION: "客户端拒绝更新，热更静默停摆",
    PROBE_HOTPKG: "热更包内容与版本 json 不符，客户端下完会拒收",
    PROBE_CONSISTENCY: "某条线路落后了：同一文件在不同线路上不是同一份",
    PROBE_SPEED: "低于客户端判停滞的速度，用户会不停换线",
    PROBE_TLS: "证书过期后这条线路直接不可用",
}


def _width(text: str) -> int:
    """显示宽度：中日韩字符占两格。

    直接用 len() 对齐会歪——「多吉云」是 3 个字符、6 格宽，而
    「EdgeOne加速」是 11 个字符、13 格宽。歪掉的表格在手机上尤其难读，
    而告警最常见的阅读场景就是手机。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "%d 秒" % int(seconds)
    if seconds < 5400:
        return "%d 分钟" % int(seconds / 60)
    if seconds < 172800:
        return "%.1f 小时" % (seconds / 3600.0)
    return "%.1f 天" % (seconds / 86400.0)


def _clock(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "未知"


def group_notifications(notes: Sequence[Notification], enabled_mirrors: int
                        ) -> List[List[Notification]]:
    """把同一探针的多条告警并成一组，顺序保持稳定（便于测试与阅读）。"""
    groups: Dict[str, List[Notification]] = {}
    order: List[str] = []
    for n in notes:
        key = "%s|%s" % (n.kind, n.result.probe)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(n)
    return [groups[k] for k in order]


def escalated_severity(group: Sequence[Notification], enabled_mirrors: int) -> Severity:
    """全部线路都挂同一个环节 → P0。级别跟着用户影响走，不跟技术严重性走。"""
    if not group:
        return Severity.INFO
    base = group[0].severity
    if group[0].kind == "recover":
        return Severity.INFO
    if enabled_mirrors >= 2 and len(group) >= enabled_mirrors and base != Severity.P0:
        return Severity.P0
    return base


def render_group(group: Sequence[Notification], *, enabled_mirrors: int = 0,
                 prefix: str = "", at_all: bool = False,
                 upstream_line: str = "",
                 extra_lines: Optional[Sequence[str]] = None) -> str:
    """渲染一组同类通知。"""
    if not group:
        return ""
    head = group[0]
    sev = escalated_severity(group, enabled_mirrors)
    probe = head.result.probe
    tag = ("【%s】" % prefix) if prefix else ""

    if head.kind == "recover":
        lines = ["%s %s · %s%s 恢复" % (Severity.INFO.emoji, Severity.INFO.value, tag, probe)]
        for n in group:
            lines.append("  %s  %s" % (n.result.target, n.result.detail))
            if n.duration_seconds:
                lines.append("  故障持续了 %s（%s 起）"
                             % (human_duration(n.duration_seconds), _clock(n.since)))
        return "\n".join(lines)

    title_scope = ("全部 %d 条线路" % enabled_mirrors
                   if enabled_mirrors and len(group) >= enabled_mirrors > 1
                   else ("%d 个目标" % len(group) if len(group) > 1 else group[0].result.target))
    verb = "仍在失败" if head.kind == "remind" else "失败"
    # 目标名已经包含在探针名里时不要重复（「线上配置 线上配置可达性 失败」）。
    if title_scope and title_scope in probe:
        title_scope = ""
    lines = ["%s %s · %s%s%s %s" % (sev.emoji, sev.value, tag, title_scope,
                                    (" " if title_scope else "") + probe, verb)]
    lines.append("")
    lines.append("  探针：%s" % probe)
    if IMPACT.get(probe):
        lines.append("  影响：%s" % IMPACT[probe])
    if head.since:
        # 刚坏就报的时候写「已持续 0 秒」是句废话，还会让人以为监控在抽风。
        lines.append("  已持续：本轮首次失败（%s）" % _clock(head.since)
                     if head.duration_seconds < 60 else
                     "  已持续：%s（首次失败 %s）"
                     % (human_duration(head.duration_seconds), _clock(head.since)))
    lines.append("")
    width = max((_width(n.result.target) for n in group), default=0)
    for n in group:
        lines.append("  %s  %s" % (_pad(n.result.target, width), n.result.detail))
    if upstream_line:
        lines.append("")
        lines.append("  %s" % upstream_line)
    # 降级诊断：入口挂了的时候，这几行回答的是「坏到什么程度、下一步去哪」。
    # 没有它，收到 P0 的人第一件事还是得自己爬起来挨个试。
    if extra_lines:
        lines.append("")
        for extra in extra_lines:
            lines.append("  %s" % extra)
    if at_all and sev == Severity.P0:
        lines.append("")
        lines.append("@全体成员")
    return "\n".join(lines)


def upstream_line(entry_ok: bool, entry_detail: str, entry_at: float = 0.0) -> str:
    """告警自己要把「已经排除了什么」说出来。

    只报「都挂了」的告警，收到的人第一件事还是得自己爬起来查上游——那等于
    没省事。这一行就是替他先查了那一步。
    """
    if entry_ok:
        return ("上游线上配置：正常（%s 拉取成功，%s）\n  → 排除配置问题，"
                "像是回源侧故障" % (_clock(entry_at) if entry_at else "本轮", entry_detail))
    return ("上游线上配置：**同样失败**（%s）\n  → 先看入口，下游这些多半是"
            "它的连带结果" % entry_detail)


def render_status(results: Sequence[ProbeResult], *, muted_until: float = 0.0,
                  coverage: Optional[CoverageReport] = None,
                  now: Optional[float] = None) -> str:
    """`/线路 状态`：当前所有探针的红绿一览。"""
    now = now if now is not None else time.time()
    lines = ["线路监控 · 状态一览"]
    if muted_until > now:
        lines.append("🔇 静音中，还剩 %s" % human_duration(muted_until - now))
    if not results:
        lines.append("（还没有跑过一轮）")
        return "\n".join(lines)

    bad = [r for r in results if r.counts_as_failure()]
    unknown = [r for r in results if r.unknown]
    lines.append("%d 项检查：%d 正常，%d 失败，%d 未判定"
                 % (len(results), len(results) - len(bad) - len(unknown),
                    len(bad), len(unknown)))
    lines.append("")
    for r in results:
        mark = "✅" if r.ok and not r.unknown else ("⚪" if r.unknown else "❌")
        lines.append("%s %s · %s" % (mark, r.probe, r.target))
        lines.append("    %s" % r.detail)
    if coverage is not None and coverage.total:
        lines.append("")
        lines.append("块校验覆盖率：%.1f%%（%d/%d 块，7 天窗口）"
                     % (coverage.percent, coverage.verified, coverage.total))
    return "\n".join(lines)


def render_coverage(coverage: CoverageReport, window_days: float = 7.0) -> str:
    """`/线路 覆盖率`。"""
    if not coverage.total:
        return "还没有拿到清单，说不出覆盖率——先看 /线路 状态 里的入口探针。"
    lines = ["抽样块校验覆盖率（%.0f 天窗口）" % window_days,
             "  %.1f%%：%d/%d 块在窗口内验过"
             % (coverage.percent, coverage.verified, coverage.total)]
    if coverage.stale:
        lines.append("  %d 块验过但已经超出窗口（旧结论说明不了现在）" % coverage.stale)
    if coverage.verified and coverage.oldest_age_seconds:
        lines.append("  窗口内最久的一块是 %s 前验的"
                     % human_duration(coverage.oldest_age_seconds))
    return "\n".join(lines)


def render_online_config(disc, extra_lines: Optional[Iterable[str]] = None) -> str:
    """`/线路 配置`：打印这一轮自发现到的东西。

    打印的是运行期取来的值，给运维看没问题；**入库的源码里一个地址都不许有**
    是另一回事（CLAUDE.md 铁律 1）。

    参数是 `Discovered`，不是某一份配置的原始形状——换配置源这段不用改。
    """
    lines = ["配置源 · 这一轮拿到了什么",
             "  源类型：%s" % (disc.source_name or "未知")]
    if disc.client_version:
        lines.append("  版本闸门：%s" % disc.client_version)
    lines.append("  线路：%d 条，%d 条启用" % (len(disc.mirrors), len(disc.enabled_mirrors)))
    for m in disc.mirrors:
        lines.append("    %s %s（weight=%s chunks=%s）"
                     % ("✅" if m.enabled else "⛔", m.name, m.weight, m.chunks))
    known = [("换线失败阈值", "switch_after_failures"), ("停滞秒数", "stall_seconds"),
             ("最低速率 kbps", "min_speed_kbps"), ("冷却毫秒", "cooldown_ms")]
    shown = [(label, disc.threshold(key)) for label, key in known]
    shown = [(label, v) for label, v in shown if v is not None]
    if shown:
        lines.append("  判据阈值（监控与客户端同源，用的就是这几个数）：")
        for label, v in shown:
            lines.append("    %s：%g" % (label, v))
    else:
        lines.append("  这个源没给阈值——速率一类的判据保持未判定"
                     "（不拿写死的默认值凑数）")
    if disc.version_files:
        lines.append("  热更探针：%s" % "、".join(disc.version_files))
    for extra in extra_lines or []:
        lines.append("  %s" % extra)
    return "\n".join(lines)
