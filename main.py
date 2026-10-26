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
import math
import os
import re
import time
from typing import List, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

# 框架以 data.plugins.<插件目录>.main 加载；绝对导入会误找顶层同名模块。
from .watch import commands, render, store
from .watch.config import ConfigError, LocalConfig, load as load_config
from .watch.http import AiohttpClient
from .watch.runner import Monitor

PLUGIN_NAME = "astrbot_plugin_resource_watch"
CONFIG_FILE_ENV = "RESOURCE_WATCH_CONFIG"      # 本地配置文件路径（可选）
QQ_OFFICIAL_PLATFORMS = frozenset({"qq_official", "qq_official_webhook"})


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
        self._slow_task: Optional[asyncio.Task] = None
        self._delivery_task: Optional[asyncio.Task] = None
        self._outbox: List[dict] = []
        self._outbox_event = asyncio.Event()
        self._delivery_lock = asyncio.Lock()
        # QQ 的框架返回值只表示调用完成，不能据此丢掉告警；由查看者明确确认。
        self._shown_notifications = {}
        self._stop = asyncio.Event()
        self.gate: Optional[commands.CommandGate] = None
        # 一次只跑一轮。没有这把锁的话，群里一条命令就能和后台循环**并发**跑：
        # 两轮同时改轮转游标与状态机（重复告警、覆盖率记错），流量也翻倍。
        self._cycle_lock = asyncio.Lock()
        self._slow_lock = asyncio.Lock()

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
        self.gate = commands.build(self.cfg.notify.sessions, self.cfg.command)
        self._restore()
        self._task = asyncio.create_task(self._loop(), name="resource-watch")
        self._delivery_task = asyncio.create_task(self._delivery_loop(), name="resource-watch-notify")
        logger.info("[线路监控] 已启动，快周期 %ds / 慢周期 %ds",
                    self.cfg.schedule.interval_fast_seconds,
                    self.cfg.schedule.interval_slow_seconds)

    async def terminate(self):
        self._stop.set()
        tasks = [t for t in (self._task, self._slow_task, self._delivery_task) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
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
                async with self._cycle_lock:
                    outcome = await self.monitor.run_cycle(now=now)
                    self._queue_messages(outcome.messages)
                idle = self._slow_task is None or self._slow_task.done()
                # 坏包确认每个快周期可重试；成功后的常规检查仍走慢周期。
                if idle and outcome.config and (slow or self.monitor.hot_failures):
                    self._slow_task = asyncio.create_task(
                        self._run_slow(outcome.config), name="resource-watch-slow")
                    if slow:
                        last_slow = now
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

    async def _run_slow(self, disc):
        try:
            async with self._slow_lock:
                outcome = await self.monitor.run_slow_cycle(disc)
                self._queue_messages(outcome.messages)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[线路监控] 慢周期异常：%s", e)

    def _queue_messages(self, messages):
        """状态转换和待发通知一起落盘，手动检查与后台检查走同一出口。"""
        for message in messages:
            self._outbox.append({"text": str(message),
                                 "at_all": bool(getattr(message, "at_all", False)),
                                 "kind": getattr(message, "kind", ""),
                                 "keys": list(getattr(message, "keys", ())),
                                 "submitted": [],
                                 "remaining": list(dict.fromkeys(self.cfg.notify.sessions)),
                                 "assigned": bool(self.cfg.notify.sessions)})
        self._persist()
        self._outbox_event.set()

    async def _delivery_loop(self):
        while not self._stop.is_set():
            self._outbox_event.clear()
            try:
                await self._flush_outbox()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("[线路监控] 通知队列异常，稍后重试：%s", e)
            try:
                await asyncio.wait_for(self._outbox_event.wait(), 30.0)
            except asyncio.TimeoutError:
                pass

    async def _flush_outbox(self):
        if not self.cfg or not self.monitor or self.monitor.state.is_muted():
            return
        async with self._delivery_lock:
            # 磁盘不可写时先保留内存队列；避免状态已推进但通知没有可恢复记录。
            if not self._prepare_outbox():
                return
            failed_sessions = set()
            for item in list(self._outbox):
                if self.monitor.state.is_muted():
                    break
                # 上一条发送期间探测仍在运行；后续通知必须按最新状态再检查。
                if self._discard_stale(item):
                    if not self._persist():
                        return
                    continue
                if not item["assigned"]:
                    continue
                for session in list(item["remaining"]):
                    # 同一通知的上一个会话也可能等待很久；维护或恢复应立即阻止续发。
                    if self.monitor.state.is_muted():
                        return
                    if self._discard_stale(item):
                        if not self._persist():
                            return
                        break
                    if session in failed_sessions:
                        continue
                    try:
                        meta = self._platform_meta(session)
                        if meta is None:
                            raise RuntimeError("未找到会话对应的平台，等待适配器就绪")
                        official = getattr(meta, "name", "") in QQ_OFFICIAL_PLATFORMS
                        if official and (session in item["submitted"] or not
                                         getattr(meta, "support_proactive_message", False)):
                            continue
                        chain = MessageChain().message(
                            _qq_text(item["text"]) if official else item["text"])
                        if official:
                            _plain_chain(chain)
                        elif item["at_all"]:
                            chain.at_all()
                        result = await asyncio.wait_for(
                            self.context.send_message(session, chain), timeout=30.0)
                        if result is False:
                            raise RuntimeError("平台未确认发送成功")
                    except Exception as e:
                        failed_sessions.add(session)
                        logger.error("[线路监控] 通知发送失败，已保留重试：%s", e)
                        continue
                    if official:
                        # 不反复消耗 QQ 的推送额度；通知仍可查询，直到人工确认。
                        item["submitted"].append(session)
                    else:
                        item["remaining"].remove(session)
                    if not self._persist():
                        return
                if not item["remaining"]:
                    self._outbox.remove(item)
                    if not self._persist():
                        return

    def _platform_meta(self, session):
        """UMO 第一段是平台实例 ID，不能拿它与适配器类型直接比较。"""
        platform_id = session.split(":", 1)[0]
        getter = getattr(self.context, "get_platform_inst", None)
        if callable(getter):
            platform = getter(platform_id)
            if platform is not None:
                return platform.meta()
        # 兼容旧版用平台名称组成 UMO 的方式，仍以真实适配器元数据为准。
        manager = getattr(self.context, "platform_manager", None)
        get_insts = getattr(manager, "get_insts", None)
        if callable(get_insts):
            for platform in get_insts():
                meta = platform.meta()
                if platform_id in (getattr(meta, "id", None), meta.name):
                    return meta
        return None

    def _discard_stale(self, item):
        keys = item.get("keys", [])
        if item.get("kind") in ("fire", "remind") and keys and any(
                not self.monitor.state.is_firing(key) for key in keys):
            for key in keys:
                if self.monitor.state.is_firing(key):
                    self.monitor.state.entries[key].has_notified = False
            self._outbox.remove(item)
            return True
        return False

    def _prepare_outbox(self):
        """投递与查询共用过期清理，避免查询出已经恢复或已移除收件人的旧告警。"""
        if not self._persist():
            return False
        allowed = set(self.cfg.notify.sessions)
        for item in list(self._outbox):
            if self._discard_stale(item):
                continue
            if not item["assigned"]:
                item["remaining"] = list(dict.fromkeys(self.cfg.notify.sessions))
                item["assigned"] = bool(item["remaining"])
            item["remaining"] = [s for s in item["remaining"] if s in allowed]
            item["submitted"] = [s for s in item.get("submitted", []) if s in item["remaining"]]
            if item["assigned"] and not item["remaining"]:
                self._outbox.remove(item)
        # 不保留已过期的查看引用，以免长时间运行后累积无效通知。
        self._shown_notifications = {
            key: shown for key, shown in self._shown_notifications.items()
            if any(item is shown for item in self._outbox) and key[0] in shown["remaining"]}
        return self._persist()

    async def _pending_notification(self, event):
        async with self._delivery_lock:
            viewer = (_session_of(event), _sender_of(event))
            self._shown_notifications.pop(viewer, None)
            if self.monitor.state.is_muted():
                return "当前处于静音窗口，待处理通知暂缓展示。"
            if not self._prepare_outbox():
                return "状态暂时无法保存，请稍后再查通知。"
            pending = [item for item in self._outbox if viewer[0] in item["remaining"]]
            if not pending:
                return "本会话没有待处理通知。"
            # 只保留有确认权限的查看者，且确认绑定本人和具体对象，不按可变化的序号。
            if viewer[1] and _is_admin(event):
                self._shown_notifications[viewer] = pending[0]
            return ("待处理通知（共 %d 条，显示最早一条）：\n%s\n\n"
                    "查看不会清除通知；管理员查看后用 /线路 确认，再查下一条。"
                    % (len(pending), pending[0]["text"]))

    async def _confirm_notification(self, event):
        async with self._delivery_lock:
            viewer = (_session_of(event), _sender_of(event))
            if not viewer[1]:
                return "无法识别当前用户，不能确认通知。"
            if not self._prepare_outbox():
                return "状态暂时无法保存，通知尚未确认。"
            item = self._shown_notifications.pop(viewer, None)
            if item is None:
                return "请先用 /线路 通知 查看当前通知，再确认；重启或通知过期后需重新查看。"
            previous = list(item["remaining"])
            item["remaining"].remove(viewer[0])
            if not self._persist():
                item["remaining"] = previous
                self._shown_notifications[viewer] = item
                return "状态保存失败，通知尚未确认，请稍后重试。"
            if not item["remaining"]:
                self._outbox.remove(item)
            return "已确认本会话的这条通知。可用 /线路 通知 继续查看。"

    # ── 状态落盘 ────────────────────────────────────────────
    def _state_path(self) -> str:
        assert self.cfg
        return self.cfg.state_path

    def _persist(self):
        # 原子写只有一份实现（watch/store.py）——两份会各自长歪，而差别只在
        # 断电或磁盘满的时候现形。
        if not self.monitor:
            return False
        data = self.monitor.snapshot()
        data["outbox"] = self._outbox
        why = store.save_json(self._state_path(), data)
        if why:
            logger.warning("[线路监控] 状态写入失败，通知暂存在内存等待重试：%s", why)
        return not why

    def _restore(self):
        if not self.monitor:
            return
        data = store.load_json(self._state_path()) or {}
        self.monitor.restore(data)
        self._outbox = []
        pending = data.get("outbox") if isinstance(data, dict) else None
        if isinstance(pending, list):
            for item in pending:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    continue
                recipients = item.get("remaining")
                if not isinstance(recipients, list):
                    continue
                self._outbox.append({"text": item["text"],
                                     "at_all": item.get("at_all") is True,
                                     "kind": item.get("kind") if isinstance(item.get("kind"), str) else "",
                                     "keys": [k for k in item.get("keys", []) if isinstance(k, str)]
                                     if isinstance(item.get("keys"), list) else [],
                                     "remaining": [s for s in recipients if isinstance(s, str)],
                                     "submitted": [s for s in item.get("submitted", []) if isinstance(s, str)]
                                     if isinstance(item.get("submitted"), list) else [],
                                     "assigned": item.get("assigned") is True})

    # ── 命令 ────────────────────────────────────────────────
    @filter.command("线路")
    async def route(self, event: AstrMessageEvent):
        """线路监控：状态 / 测 <线路名> / 配置 / 静音 <时长> / 覆盖率 / 通知 / 确认"""
        if not self.monitor or not self.cfg or not self.gate:
            yield _reply(event,
                "线路监控没有启动：没有配置源（entry_url 或 mirrors 二选一），见日志。")
            return

        args = _args(event)
        sub = args[0] if args else "状态"

        # 闸门在最前面：这个插件跑在共享的聊天环境里，命令会产生真实流量。
        # 拒绝理由为空字符串 = 静默拒绝（不在允许的会话里，连回都不回）。
        refuse = self.gate.refuse_reason(sub, session=_session_of(event),
                                         is_admin=_is_admin(event))
        if refuse is not None:
            if refuse:
                yield _reply(event, refuse)
            return

        if sub in ("通知", "notifications"):
            yield _reply(event, await self._pending_notification(event))
        elif sub in ("确认", "ack"):
            # 确认会清掉待发记录，不能随静音权限配置放宽。
            if not _is_admin(event):
                yield _reply(event, "只有管理员能确认通知。")
                return
            yield _reply(event, await self._confirm_notification(event))
        elif sub in ("状态", "status"):
            yield _reply(event, render.render_status(
                self.monitor.last_results,
                muted_until=self.monitor.state.muted_until,
                coverage=self._coverage()))
        elif sub in ("测", "test"):
            name = " ".join(args[1:]).strip()
            if not name:
                yield _reply(event, "要测哪条线路？用 /线路 配置 看名字。")
                return
            if self._cycle_lock.locked():
                yield _reply(event, "正在跑一轮，等它跑完再来——同时跑两轮"
                                         "只会把流量翻倍，结论还会互相打架。")
                return
            self.gate.mark(sub)
            yield _reply(event, "在测「%s」，一轮下来要几十秒……" % render.safe(name))
            async with self._cycle_lock:
                # allow_heavy=False：命令触发的轮次不下整包（几百 MB）。
                outcome = await self.monitor.run_cycle(
                    only_mirror=name, allow_heavy=False)
                self._queue_messages(outcome.messages)
            if (outcome.config and not self._slow_lock.locked()
                    and (self._slow_task is None or self._slow_task.done())):
                async with self._slow_lock:
                    slow_out = await self.monitor.run_slow_cycle(
                        outcome.config, allow_heavy=False,
                        mirrors=[m for m in outcome.config.enabled_mirrors if m.name == name])
                    self._queue_messages(slow_out.messages)
                    outcome.results.extend(slow_out.results)
            yield _reply(event, render.render_status(outcome.results))
        elif sub in ("配置", "config"):
            if self._cycle_lock.locked():
                yield _reply(event, "正在跑一轮，稍等。")
                return
            self.gate.mark(sub)
            async with self._cycle_lock:
                outcome = await self.monitor.run_cycle(allow_heavy=False)
                self._queue_messages(outcome.messages)
            if outcome.config is None:
                yield _reply(event, "拉不到配置源：%s"
                                         % render.safe(outcome.results[0].detail, 300))
            else:
                yield _reply(event, render.render_online_config(outcome.config))
        elif sub in ("静音", "mute"):
            yield _reply(event, self._mute(event, args[1:]))
        elif sub in ("取消静音", "unmute"):
            self.monitor.state.unmute()
            self._persist()
            self._outbox_event.set()
            yield _reply(event, "已取消静音。")
        elif sub in ("覆盖率", "coverage"):
            cov = self._coverage()
            yield _reply(event, render.render_coverage(cov) if cov else
                                     "还没有拿到清单，说不出覆盖率。")
        else:
            yield _reply(event,
                "线路监控：\n"
                "  /线路 状态         当前红绿一览\n"
                "  /线路 测 <线路名>   立刻对某条线路跑一轮（管理员，有冷却）\n"
                "  /线路 配置         配置源的关键字段（管理员，有冷却）\n"
                "  /线路 静音 30m     维护窗口（管理员）\n"
                "  /线路 取消静音\n"
                "  /线路 覆盖率       抽样块校验覆盖到哪了\n"
                "  /线路 通知         查看本会话最早的待处理通知\n"
                "  /线路 确认         确认本人刚查看的通知（管理员）")

    def _mute(self, event: AstrMessageEvent, rest: List[str]) -> str:
        # 权限已由命令闸门统一判过（watch/commands.py）：静音把所有告警关掉，
        # 而关掉之后没有任何人会知道。
        assert self.cfg and self.monitor
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
        return self.monitor.rotation.coverage(
            entries, mirror_names=self.monitor.last_mirror_names) if entries else None


def _is_qq_official(event: AstrMessageEvent) -> bool:
    getter = getattr(event, "get_platform_name", None)
    if callable(getter):
        return getter() in QQ_OFFICIAL_PLATFORMS
    return getattr(getattr(event, "platform_meta", None), "name", "") in QQ_OFFICIAL_PLATFORMS


def _plain_chain(chain):
    # 新版默认 Markdown 可能需要额外权限，监控只需要文本；旧版没有这些开关。
    for name in ("use_markdown", "use_t2i"):
        setter = getattr(chain, name, None)
        if callable(setter):
            setter(False)
    return chain


def _qq_text(text: str) -> str:
    # 链接需要平台配置许可，监控回复省略链接；外部字段不能注入 QQ 控制标签。
    text = re.sub(r"https?://[^\s<>\"']+", "[链接已省略]", text, flags=re.I)
    return text.replace("<", "＜").replace(">", "＞")


def _reply(event: AstrMessageEvent, text: str):
    if _is_qq_official(event):
        return _plain_chain(event.plain_result(_qq_text(text)))
    return event.plain_result(text)


def _sender_of(event: AstrMessageEvent) -> str:
    getter = getattr(event, "get_sender_id", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:
            pass
    return ""


def _args(event: AstrMessageEvent) -> List[str]:
    """取命令后面的参数。不同版本的 message_str 有的带命令名有的不带，都兼容。"""
    text = (getattr(event, "message_str", "") or "").strip()
    parts = [p for p in text.replace("／", "/").split() if p]
    if parts and parts[0].lstrip("/") in ("线路", "route"):
        parts = parts[1:]
    return parts


def _session_of(event: AstrMessageEvent) -> str:
    """这条命令是从哪个会话来的。取不到就返回空串——**空串不匹配任何允许项**，
    于是闸门默认拒绝。取不到来源时放行是最糟的选择：那正是别人的群。"""
    for name in ("unified_msg_origin", "session_id"):
        value = getattr(event, name, None)
        if isinstance(value, str) and value:
            return value
    getter = getattr(event, "get_session_id", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:                                     # noqa: BLE001
            return ""
    return ""


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
                return _valid_duration(float(head) * mult)
            except (ValueError, OverflowError):
                return None
    try:
        return _valid_duration(float(text) * 60.0)          # 光给数字按分钟算
    except (ValueError, OverflowError):
        return None


def _valid_duration(seconds: float) -> Optional[float]:
    if not math.isfinite(seconds) or seconds < 0:
        return None
    try:
        time.localtime(time.time() + seconds)
    except (OverflowError, OSError, ValueError):
        return None
    return seconds
