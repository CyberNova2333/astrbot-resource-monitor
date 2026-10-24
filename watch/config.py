# -*- coding: utf-8 -*-
"""本地配置：**只给一个入口**，其余一律运行时从线上取（CLAUDE.md 铁律 1/2）。

这一层允许有默认值，但只限**监控自己的**旋钮（探针间隔、连报几次才告警）。
被监控方那边已经有一份的东西（线路表、超时、最低速率、换线判据）在这里一个
都不放——放了就是第二份判据，会漂移。

配置可以来自两处，形状一样：

  · AstrBot 插件配置（WebUI 表单，见 _conf_schema.json）；
  · 本地 JSON 文件（config.json，已被 .gitignore 挡住；样例见 config.example.json）。

示例地址一律 `https://api.example.test/…`——保留域名，永远不会解析到真东西。
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

from .discovery import ContentError, parse_mirrors


class ConfigError(ValueError):
    """配置不可用。**不给兜底值**——没有入口就没得探，这一条要让人看见。"""


@dataclass
class NotifyConfig:
    sessions: List[str] = field(default_factory=list)
    at_all_on_p0: bool = True
    prefix: str = ""


@dataclass
class ScheduleConfig:
    interval_fast_seconds: int = 300      # P0 探针
    interval_slow_seconds: int = 3600     # P1 探针
    chunk_probes_per_cycle: int = 1       # 每轮验几个块
    # 热更包整包核对：包不小（数百 MB 量级），所以默认**只在版本号变化时**做，
    # 另加一道最小间隔兜底。按轮跑会把带宽烧在一件几天才变一次的事情上。
    hot_package_min_interval_seconds: int = 21600   # 6 小时
    hot_package_on_version_change: bool = True


@dataclass
class AlertConfig:
    # 「三轮里坏两轮」才报。网络抖动是常态，一次超时就 @ 全体，两天之后
    # 就没人看群了（CLAUDE.md 铁律 6）。
    fire_after_failures: int = 2
    fire_window: int = 3
    recover_after_successes: int = 2
    remind_every_hours: float = 6.0
    mute_command_admin_only: bool = True


@dataclass
class DegradedConfig:
    """入口挂了以后怎么办。

    入口是整条链的单点：它一挂，监控既不知道有哪几条线路，也不知道按什么判。
    但**「不知道」不等于「什么都别做」**——那恰恰是最需要信息的时刻。所以：

      · 备用入口（同一份配置的另一个出口）用来区分两种完全不同的故障：
        「配置内容被人改坏了」和「这个出口/域名挂了」，处置方式一个是回滚、
        一个是找托管方；
      · 上一次拉到的好配置留一份**只用来继续探**，不用来判绿——用旧线路表
        探出来的结论一律标成「仅供参考」，永远不触发告警。拿旧数字当判据
        就是铁律 2 说的那种漂移；拿旧线路表当**线索**不是。

    旧配置有保质期：超过 max_age 就不用了。一天前的线路表说明不了现在。
    """

    stale_config_max_age_seconds: float = 86400.0
    probe_with_stale_config: bool = True


@dataclass
class RuntimeConfig:
    # 刻意与客户端不同：混在一起的话，日志里监控流量与用户流量就分不开了。
    user_agent: str = "resource-watch/1.0"
    state_dir: str = "data"
    http_timeout_seconds: float = 30.0
    max_body_bytes: int = 4 * 1024 * 1024      # 配置/清单类响应的上限


@dataclass
class LocalConfig:
    # 配置源规格（见 watch/sources.py）。两种：
    #
    #   {"type": "endpoint", "urls": [...]}   从 URL 拉一份含 mirrors 的 JSON；
    #                                          第一条是主入口，其余是备用出口
    #   {"type": "mirrors",  "mirrors": [...]} 线路表直接由本地配置给，无中心配置
    #
    # 监控**不绑定任何一份特定配置的形状**：源可以换，判据不变。
    source: dict = field(default_factory=dict)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    alert: AlertConfig = field(default_factory=AlertConfig)
    degraded: DegradedConfig = field(default_factory=DegradedConfig)
    # 命令闸门的原始配置，判据在 watch/commands.py（那边是纯函数，可单测）
    command: dict = field(default_factory=dict)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    @property
    def entry_urls(self) -> List[str]:
        """endpoint 源的 URL 列表；别的源返回空。"""
        urls = self.source.get("urls") or []
        return [str(u) for u in urls]

    @property
    def entry_url(self) -> str:
        urls = self.entry_urls
        return urls[0] if urls else ""

    @property
    def state_path(self) -> str:
        return os.path.join(self.runtime.state_dir, "watch-state.json")


def _section(data: dict, name: str) -> dict:
    v = data.get(name)
    return v if isinstance(v, dict) else {}


def _int(data: dict, key: str, default: int) -> int:
    v = data.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    try:
        number = int(v)
    except (ValueError, OverflowError) as exc:
        raise ConfigError("%s 必须是有限数值" % key) from exc
    if abs(number) > sys.maxsize:
        raise ConfigError("%s 数值超出支持范围" % key)
    return number


def _float(data: dict, key: str, default: float) -> float:
    v = data.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    try:
        number = float(v)
    except (ValueError, OverflowError) as exc:
        raise ConfigError("%s 必须是有限数值" % key) from exc
    if not math.isfinite(number) or abs(number) > sys.maxsize:
        raise ConfigError("%s 必须是支持范围内的有限数值" % key)
    return number


def _bool(data: dict, key: str, default: bool) -> bool:
    v = data.get(key, default)
    return bool(v) if isinstance(v, bool) else default


def _str(data: dict, key: str, default: str = "") -> str:
    v = data.get(key, default)
    return v if isinstance(v, str) else default


def validate_entry_url(url: str) -> str:
    """入口地址必须是完整的 http(s) URL。**没有默认值。**

    不设默认入口是有意的：默认值在这件事上只会造成一种结果——插件在一台没配好
    的机器上「跑起来了」，探的却是别人的地址，或者干脆什么都没探而群里一片
    绿。宁可起不来，也不要绿着骗人。
    """
    if not url or not isinstance(url, str):
        raise ConfigError(
            "没有配置源：监控不知道该探哪里。二选一，都由部署侧给（不入库）——\n"
            "  1. 有一个能拉到线路表的地址："
            "entry_url = https://api.example.test/path/to/lines.json\n"
            "     （那份 JSON 只要有 mirrors[]，其余字段有就多探两样）\n"
            "  2. 没有中心配置：source = {\"type\": \"mirrors\", "
            "\"mirrors\": [{\"name\": \"甲\", \"base\": \"https://a.example.test/\"}]}")
    normalized = url.strip()
    try:
        p = urlparse(normalized)
        # hostname/port 的格式错误会在访问属性时才抛出，必须一并转换。
        valid = (p.scheme in ("http", "https") and bool(p.hostname)
                 and (p.port is None or p.port > 0)
                 and not any(char.isspace() for char in normalized))
    except ValueError as exc:
        raise ConfigError("entry_url 不是合法的 http(s) 地址：%r" % url) from exc
    if not valid:
        raise ConfigError("entry_url 不是合法的 http(s) 地址：%r" % url)
    return normalized


def _mirror_from_line(item) -> dict:
    """`名称=https://…`、`https://…`、或者本来就是对象。"""
    if isinstance(item, dict):
        return item
    if not isinstance(item, str):
        raise ConfigError("mirrors 的线路条目必须是对象或地址字符串")
    text = item.strip()
    if "=" in text and not text.split("=", 1)[0].strip().startswith("http"):
        name, _, base = text.partition("=")
        return {"name": name.strip(), "base": base.strip()}
    return {"base": text}


def _strings(value, label: str, *, allow_single: bool = False) -> List[str]:
    if value is None:
        return []
    if allow_single and isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError("%s 必须是字符串数组" % label)
    return [item.strip() for item in value if item.strip()]


def normalize_source(data: dict) -> dict:
    """把配置里的「探哪里」归一成一份源规格。

    三种写法，前两种是同一件事的新旧说法：

        {"source": {"type": "endpoint", "urls": [...]}}      ← 推荐
        {"entry_url": "...", "entry_urls": [...]}            ← 旧写法，等价
        {"source": {"type": "mirrors", "mirrors": [...]}}    ← 不依赖任何中心配置

    **不给默认源**：没配就报错，不是悄悄用一个内置的。默认值在这件事上只会让
    插件在一台没配好的机器上「跑起来」，群里一片绿而其实什么都没探。
    """
    spec = data.get("source")
    if spec is not None and not isinstance(spec, dict):
        raise ConfigError("source 必须是对象")
    if isinstance(spec, dict) and spec:
        if not isinstance(spec.get("type"), str) or not spec["type"].strip():
            raise ConfigError("source.type 必须是配置源类型字符串")
        kind = spec["type"].strip().lower()
        if kind in ("endpoint", "url", "config", "legacy-config"):
            urls = _strings(spec.get("urls"), "endpoint.urls", allow_single=True)
            if not urls:
                raise ConfigError("endpoint 源要给至少一个 urls")
            return {"type": "endpoint", "urls": [validate_entry_url(u) for u in urls]}
        if kind in ("mirrors", "static", "local"):
            raw_mirrors = spec.get("mirrors")
            if not isinstance(raw_mirrors, list):
                raise ConfigError("mirrors 源的 mirrors 必须是对象数组")
            normalized = []
            for item in raw_mirrors:
                if not isinstance(item, dict):
                    raise ConfigError("mirrors 源的线路条目必须是对象")
                if item.get("name") is not None and not isinstance(item["name"], str):
                    raise ConfigError("mirrors 源的 name 必须是字符串")
                normalized.append(dict(item, base=validate_entry_url(item.get("base"))))
            try:
                parsed, skipped = parse_mirrors(normalized)
            except ContentError as exc:
                raise ConfigError(str(exc)) from exc
            if skipped:
                raise ConfigError("mirrors 源的线路字段无效：%s" % "；".join(skipped[:3]))
            mirrors = [{"name": m.name, "base": m.base, "weight": m.weight,
                        "chunks": m.chunks, "enabled": m.enabled} for m in parsed]
            if not mirrors:
                raise ConfigError("mirrors 源要给至少一条线路")
            packages = spec.get("packages")
            if packages is None:
                packages = {}
            if not isinstance(packages, dict) or any(
                    not isinstance(k, str) or not isinstance(v, str) for k, v in packages.items()):
                raise ConfigError("mirrors 源的 packages 必须是字符串映射")
            return {"type": "mirrors", "mirrors": mirrors,
                    "version_files": _strings(spec.get("version_files"), "version_files"),
                    "packages": dict(packages)}
        raise ConfigError("不认识的配置源类型：%r（可用：endpoint / mirrors）"
                          % spec.get("type"))

    # WebUI 友好的写法：一行一条线路，`名称=地址` 或光给地址。
    # AstrBot 的配置表单只能给字符串列表，表达不了对象列表——与其让人去改
    # 本地 JSON 文件，不如把这种写法直接接住。
    raw_mirrors = data.get("mirrors")
    if raw_mirrors is not None and not isinstance(raw_mirrors, list):
        raise ConfigError("mirrors 必须是线路数组")
    if isinstance(raw_mirrors, list) and raw_mirrors and not data.get("entry_url"):
        return normalize_source({"source": {
            "type": "mirrors",
            "mirrors": [_mirror_from_line(x) for x in raw_mirrors],
            "version_files": data.get("version_files"),
            "packages": data.get("packages")}})

    urls = _strings(data.get("entry_urls"), "entry_urls", allow_single=True)
    primary = data.get("entry_url")
    if primary is not None and not isinstance(primary, str):
        raise ConfigError("entry_url 必须是地址字符串")
    primary = primary.strip() if primary else ""
    if primary:
        urls = [primary] + [u for u in urls if u != primary]
    if not urls:
        validate_entry_url("")                    # 抛出那条写得清楚的 ConfigError
    return {"type": "endpoint", "urls": [validate_entry_url(u) for u in urls]}


def from_mapping(data: dict) -> LocalConfig:
    """从一个 dict 造 LocalConfig（AstrBot 插件配置直接喂进来即可）。"""
    if not isinstance(data, dict):
        raise ConfigError("配置必须是一个对象")

    notify_raw = _section(data, "notify")
    sessions = notify_raw.get("sessions")
    if isinstance(sessions, str):
        # WebUI 里手填成一行逗号分隔是常见写法，接住它——比让人对着一条
        # "sessions 必须是列表" 的报错发呆强。
        sessions = [s.strip() for s in sessions.replace("，", ",").split(",")]
    if not isinstance(sessions, list):
        sessions = []
    sessions = [s for s in (str(x).strip() for x in sessions) if s]

    sched_raw = _section(data, "schedule")
    alert_raw = _section(data, "alert")
    rt_raw = _section(data, "runtime")

    degraded_raw = _section(data, "degraded")

    cfg = LocalConfig(
        source=normalize_source(data),
        notify=NotifyConfig(
            sessions=sessions,
            at_all_on_p0=_bool(notify_raw, "at_all_on_p0", True),
            prefix=_str(notify_raw, "prefix"),
        ),
        schedule=ScheduleConfig(
            interval_fast_seconds=max(30, _int(sched_raw, "interval_fast_seconds", 300)),
            interval_slow_seconds=max(60, _int(sched_raw, "interval_slow_seconds", 3600)),
            chunk_probes_per_cycle=max(0, _int(sched_raw, "chunk_probes_per_cycle", 1)),
            hot_package_min_interval_seconds=max(
                600, _int(sched_raw, "hot_package_min_interval_seconds", 21600)),
            hot_package_on_version_change=_bool(
                sched_raw, "hot_package_on_version_change", True),
        ),
        alert=AlertConfig(
            fire_after_failures=max(1, _int(alert_raw, "fire_after_failures", 2)),
            fire_window=max(1, _int(alert_raw, "fire_window", 3)),
            recover_after_successes=max(1, _int(alert_raw, "recover_after_successes", 2)),
            remind_every_hours=max(0.5, _float(alert_raw, "remind_every_hours", 6.0)),
            mute_command_admin_only=_bool(alert_raw, "mute_command_admin_only", True),
        ),
        command=_section(data, "command"),
        degraded=DegradedConfig(
            stale_config_max_age_seconds=max(
                0.0, _float(degraded_raw, "stale_config_max_age_seconds", 86400.0)),
            probe_with_stale_config=_bool(degraded_raw, "probe_with_stale_config", True),
        ),
        runtime=RuntimeConfig(
            user_agent=_str(rt_raw, "user_agent", "resource-watch/1.0") or "resource-watch/1.0",
            state_dir=_str(rt_raw, "state_dir", "data") or "data",
            http_timeout_seconds=max(5.0, _float(rt_raw, "http_timeout_seconds", 30.0)),
            max_body_bytes=max(64 * 1024, _int(rt_raw, "max_body_bytes", 4 * 1024 * 1024)),
        ),
    )
    if cfg.alert.fire_after_failures > cfg.alert.fire_window:
        raise ConfigError("alert.fire_after_failures 不能大于 fire_window"
                          "（「%d 轮里坏 %d 轮」不成立）"
                          % (cfg.alert.fire_window, cfg.alert.fire_after_failures))
    return cfg


def from_file(path: str) -> LocalConfig:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        raise ConfigError("无法读取本地配置文件：%s（样例见 config.example.json）" % path) from exc
    except (ValueError, RecursionError) as exc:
        raise ConfigError("本地配置不是合法 JSON：%s" % exc) from exc
    # 样例里的注释字段（"comment"）无害，直接忽略
    return from_mapping(data)


def load(data: Optional[dict] = None, path: Optional[str] = None) -> LocalConfig:
    """优先用传进来的 dict（AstrBot 插件配置），否则读本地文件。"""
    if data:
        try:
            return from_mapping(data)
        except ConfigError:
            if not path:
                raise
    if path:
        return from_file(path)
    raise ConfigError("没有可用的配置来源")
