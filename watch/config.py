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
class RuntimeConfig:
    # 刻意与客户端不同：混在一起的话，日志里监控流量与用户流量就分不开了。
    user_agent: str = "resource-watch/1.0"
    state_dir: str = "data"
    http_timeout_seconds: float = 30.0
    max_body_bytes: int = 4 * 1024 * 1024      # 配置/清单类响应的上限


@dataclass
class LocalConfig:
    entry_url: str
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    alert: AlertConfig = field(default_factory=AlertConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

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
            "缺少 entry_url：线上配置的入口地址。它不入库，必须由部署侧给"
            "（AstrBot 插件配置或本地 config.json）。形如 "
            "https://api.example.test/path/to/config.json")
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ConfigError("entry_url 不是合法的 http(s) 地址：%r" % url)
    return url.strip()


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

    cfg = LocalConfig(
        entry_url=validate_entry_url(_str(data, "entry_url")),
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
