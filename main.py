# -*- coding: utf-8 -*-
"""AstrBot 胶水层：**唯一认识 AstrBot 的一层**（CLAUDE.md 铁律 3）。

它只做三件事：

  1. 把插件配置变成 `watch.config.LocalConfig`；
  2. 按间隔叫醒 `watch.runner.Monitor`，把它吐出来的消息发到配置的会话；
  3. 挂几条命令，让人主动问。

判据一行都不在这里。**AstrBot 的 API 各版本有过变动**，所以下面凡是碰框架的
地方都写成「试几种写法，都不行就记一条日志」——插件的价值是它在跑，不是它在
某个版本上写得最漂亮。真要适配新版本，改的也只有这个文件。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import List, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

from watch import render
from watch.config import ConfigError, LocalConfig, load as load_config
from watch.http import AiohttpClient
from watch.runner import Monitor

PLUGIN_NAME = "astrbot_plugin_resource_watch"
CONFIG_FILE_ENV = "RESOURCE_WATCH_CONFIG"      # 本地配置文件路径（可选）


@register(PLUGIN_NAME, "Resource Monitor Contributors",
          "资源分发线路监控：按客户端的判据探线路，把静默故障喊出来", "0.1.0")
class ResourceWatch(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self._raw_config = dict(config) if config else {}
        self.cfg: Optional[LocalConfig] = None
        self.monitor: Optional[Monitor] = None
        self.client: Optional[AiohttpClient] = None
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ── 生命周期 ────────────────────────────────────────────
    async def initialize(self):
        try:
            self.cfg = load_config(self._raw_config, os.environ.get(CONFIG_FILE_ENV))
        except ConfigError as e:
            # 起不来就明说，别绿着骗人：没有入口地址时，一个「跑起来了」的
            # 监控比没有监控更危险。
            logger.error("[线路监控] 配置不可用，插件不会开始探测：%s", e)
            return
        self.client = AiohttpClient(
            user_agent=self.cfg.runtime.user_agent,
            timeout_seconds=self.cfg.runtime.http_timeout_seconds,
            max_body_bytes=self.cfg.runtime.max_body_bytes)
        self.monitor = Monitor(self.cfg, self.client)
        self._restore()
        self._task = asyncio.create_task(self._loop(), name="resource-watch")
        logger.info("[线路监控] 已启动，快周期 %ds / 慢周期 %ds",
                    self.cfg.schedule.interval_fast_seconds,
                    self.cfg.schedule.interval_slow_seconds)

    async def terminate(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):       # noqa: BLE001
                pass
        self._persist()
        if self.client:
            await self.client.close()

    # ── 主循环 ──────────────────────────────────────────────
    async def _loop(self):
        assert self.cfg and self.monitor
        last_slow = 0.0
        while not self._stop.is_set():
            now = time.time()
            slow = now - last_slow >= self.cfg.schedule.interval_slow_seconds
            try:
                outcome = await self.monitor.run_cycle(slow=slow, now=now)
                if slow:
                    last_slow = now
                for message in outcome.messages:
                    await self._broadcast(message)
                self._persist()
            except asyncio.CancelledError:
                raise
            except Exception as e:                            # noqa: BLE001
                # 调度器自己出错一律放行并记一条（铁律 7）：让整轮探测失败的
                # bug，不该顺带把插件也弄停。
                logger.exception("[线路监控] 本轮异常，跳过：%s", e)
            try:
                await asyncio.wait_for(self._stop.wait(),
                                       self.cfg.schedule.interval_fast_seconds)
            except asyncio.TimeoutError:
                pass

    async def _broadcast(self, message: str):
        if not self.cfg or not self.cfg.notify.sessions:
            logger.warning("[线路监控] 没有配置 notify.sessions，本条告警只进日志：\n%s",
                           message)
            return
        for session in self.cfg.notify.sessions:
            try:
                await self.context.send_message(session, MessageChain().message(message))
            except Exception as e:                            # noqa: BLE001
                logger.error("[线路监控] 发送到 %s 失败：%s", session, e)

    # ── 状态落盘 ────────────────────────────────────────────
    def _state_path(self) -> str:
        assert self.cfg
        return self.cfg.state_path

    def _persist(self):
        if not self.monitor:
            return
        path = self._state_path()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.monitor.snapshot(), f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            logger.warning("[线路监控] 状态写不进去（可丢，不影响探测）：%s", e)

    def _restore(self):
        if not self.monitor:
            return
        try:
            with open(self._state_path(), "r", encoding="utf-8") as f:
                self.monitor.restore(json.load(f))
        except (OSError, ValueError):
            pass          # 没有就是全新开始，最多重报一次

    # ── 命令 ────────────────────────────────────────────────
    @filter.command("线路")
    async def route(self, event: AstrMessageEvent):
        """线路监控：状态 / 测 <线路名> / 配置 / 静音 <时长> / 覆盖率"""
        args = _args(event)
        sub = args[0] if args else "状态"
        if not self.monitor or not self.cfg:
            yield event.plain_result(
                "线路监控没有启动：没有配置源（entry_url 或 mirrors 二选一），见日志。")
            return

        if sub in ("状态", "status"):
            yield event.plain_result(render.render_status(
                self.monitor.last_results,
                muted_until=self.monitor.state.muted_until,
                coverage=self._coverage()))
        elif sub in ("测", "test"):
            name = " ".join(args[1:]).strip()
            if not name:
                yield event.plain_result("要测哪条线路？用 /线路 配置 看名字。")
                return
            yield event.plain_result("在测「%s」，一轮下来要几十秒……" % name)
            outcome = await self.monitor.run_cycle(slow=True, only_mirror=name)
            yield event.plain_result(render.render_status(outcome.results))
        elif sub in ("配置", "config"):
            outcome = await self.monitor.run_cycle()
            if outcome.config is None:
                yield event.plain_result("拉不到线上配置：%s" % outcome.results[0].detail)
            else:
                yield event.plain_result(render.render_online_config(outcome.config))
        elif sub in ("静音", "mute"):
            yield event.plain_result(self._mute(event, args[1:]))
        elif sub in ("取消静音", "unmute"):
            self.monitor.state.unmute()
            self._persist()
            yield event.plain_result("已取消静音。")
        elif sub in ("覆盖率", "coverage"):
            cov = self._coverage()
            yield event.plain_result(render.render_coverage(cov) if cov else
                                     "还没有拿到清单，说不出覆盖率。")
        else:
            yield event.plain_result(
                "线路监控：\n"
                "  /线路 状态         当前红绿一览\n"
                "  /线路 测 <线路名>   立刻对某条线路跑一轮\n"
                "  /线路 配置         线上配置的关键字段\n"
                "  /线路 静音 30m     维护窗口（支持 30m / 2h / 90）\n"
                "  /线路 取消静音\n"
                "  /线路 覆盖率       抽样块校验覆盖到哪了")

    def _mute(self, event: AstrMessageEvent, rest: List[str]) -> str:
        assert self.cfg and self.monitor
        if self.cfg.alert.mute_command_admin_only and not _is_admin(event):
            # 静音不是可选项（自己调线路时会被自己的 bot 轰炸），但也不能人人可用
            # ——否则群友能把告警关掉，而关掉之后没有任何人会知道。
            return "只有管理员能静音。"
        seconds = _duration(" ".join(rest)) if rest else 1800.0
        if seconds is None:
            return "看不懂这个时长。写成 30m / 2h / 45（分钟）。"
        until = self.monitor.state.mute(seconds)
        self._persist()
        return "已静音 %s，到 %s 为止。期间照常探测、不发消息；结束后还坏着的会重新报。" % (
            render.human_duration(seconds), time.strftime("%H:%M", time.localtime(until)))

    def _coverage(self):
        if not self.monitor or not self.monitor.last_results:
            return None
        entries = self.monitor.last_entries
        return self.monitor.rotation.coverage(entries) if entries else None


def _args(event: AstrMessageEvent) -> List[str]:
    """取命令后面的参数。不同版本的 message_str 有的带命令名有的不带，都兼容。"""
    text = (getattr(event, "message_str", "") or "").strip()
    parts = [p for p in text.replace("／", "/").split() if p]
    if parts and parts[0].lstrip("/") in ("线路", "route"):
        parts = parts[1:]
    return parts


def _is_admin(event: AstrMessageEvent) -> bool:
    for name in ("is_admin", "is_superuser"):
        fn = getattr(event, name, None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:                                 # noqa: BLE001
                continue
    role = getattr(event, "role", "")
    return str(role).lower() in ("admin", "owner", "superuser")


def _duration(text: str) -> Optional[float]:
    """`30m` / `2h` / `90`（分钟）。看不懂返回 None，不猜。"""
    text = (text or "").strip().lower().replace(" ", "")
    if not text:
        return None
    unit = {"s": 1, "秒": 1, "m": 60, "分": 60, "分钟": 60,
            "h": 3600, "小时": 3600, "d": 86400, "天": 86400}
    for suffix, mult in sorted(unit.items(), key=lambda kv: -len(kv[0])):
        if text.endswith(suffix):
            head = text[: -len(suffix)]
            try:
                return float(head) * mult
            except ValueError:
                return None
    try:
        return float(text) * 60.0          # 光给数字按分钟算
    except ValueError:
        return None
