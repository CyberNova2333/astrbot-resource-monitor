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
import os
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse


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
    return int(v)


def _float(data: dict, key: str, default: float) -> float:
    v = data.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return float(v)


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
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ConfigError("entry_url 不是合法的 http(s) 地址：%r" % url)
    return url.strip()


def _mirror_from_line(item) -> dict:
    """`名称=https://…`、`https://…`、或者本来就是对象。"""
    if isinstance(item, dict):
        return item
    text = str(item).strip()
    if "=" in text and not text.split("=", 1)[0].strip().startswith("http"):
        name, _, base = text.partition("=")
        return {"name": name.strip(), "base": base.strip()}
    return {"base": text}


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
    if isinstance(spec, dict) and spec.get("type"):
        kind = str(spec["type"]).strip().lower()
        if kind in ("endpoint", "url", "config", "legacy-config"):
            urls = spec.get("urls")
            if isinstance(urls, str):
                urls = [urls]
            urls = [str(u).strip() for u in (urls or []) if str(u).strip()]
            if not urls:
                raise ConfigError("endpoint 源要给至少一个 urls")
            return {"type": "endpoint", "urls": [validate_entry_url(u) for u in urls]}
        if kind in ("mirrors", "static", "local"):
            mirrors = []
            for item in spec.get("mirrors") or []:
                if not isinstance(item, dict):
                    continue
                base = str(item.get("base") or "").strip()
                if not base.startswith(("http://", "https://")):
                    raise ConfigError("mirrors 源里的 base 必须是 http(s) 地址：%r" % base)
                mirrors.append({"name": str(item.get("name") or base), "base": base,
                                "weight": int(item.get("weight") or 0),
                                "chunks": int(item.get("chunks") or 0),
                                "enabled": bool(item.get("enabled", True))})
            if not mirrors:
                raise ConfigError("mirrors 源要给至少一条线路")
            packages = spec.get("packages")
            return {"type": "mirrors", "mirrors": mirrors,
                    "version_files": [str(x) for x in (spec.get("version_files") or [])],
                    "packages": {str(k): str(v) for k, v in packages.items()}
                    if isinstance(packages, dict) else {}}
        raise ConfigError("不认识的配置源类型：%r（可用：endpoint / mirrors）"
                          % spec.get("type"))

    # WebUI 友好的写法：一行一条线路，`名称=地址` 或光给地址。
    # AstrBot 的配置表单只能给字符串列表，表达不了对象列表——与其让人去改
    # 本地 JSON 文件，不如把这种写法直接接住。
    raw_mirrors = data.get("mirrors")
    if isinstance(raw_mirrors, list) and raw_mirrors and not data.get("entry_url"):
        return normalize_source({"source": {
            "type": "mirrors",
            "mirrors": [_mirror_from_line(x) for x in raw_mirrors],
            "version_files": data.get("version_files") or [],
            "packages": data.get("packages") or {}}})

    raw_urls = data.get("entry_urls")
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    urls = [str(u).strip() for u in (raw_urls or []) if str(u).strip()] \
        if isinstance(raw_urls, list) else []
    primary = _str(data, "entry_url")
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
    if not os.path.isfile(path):
        raise ConfigError("找不到本地配置文件：%s（样例见 config.example.json）" % path)
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ConfigError("本地配置不是合法 JSON：%s" % e)
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
