"""用框架替身验证命令、后台任务与持久化发送队列，不连接聊天平台。"""

import asyncio
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from tests.astrbot_stub import load_plugin
from tests.test_runner import A, B, cfg, healthy_client
from watch import commands, render, store
from watch.runner import CycleOutcome, Monitor
from watch.sources import Discovered


glue = load_plugin()


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        platform = types.SimpleNamespace(
            meta=lambda: types.SimpleNamespace(name="aiocqhttp"))
        self.context = types.SimpleNamespace(
            send_message=AsyncMock(return_value=True),
            get_platform_inst=lambda platform_id: platform)
        self.plugin = self.make_plugin()

    def make_plugin(self):
        plugin = glue.ResourceWatch(self.context)
        plugin.cfg = cfg(runtime={"state_dir": self.temp.name})
        plugin.monitor = Monitor(plugin.cfg, healthy_client())
        plugin.gate = commands.build(plugin.cfg.notify.sessions, plugin.cfg.command)
        return plugin

    async def test_failed_session_retries_after_restart_without_resending_success(self):
        plugin = self.plugin
        plugin.cfg.notify.sessions = ["群甲", "群乙"]
        self.context.send_message.side_effect = [True, OSError("暂不可用")]
        plugin._queue_messages([render.RenderedMessage("故障", at_all=True)])
        await plugin._flush_outbox()
        self.assertEqual(plugin._outbox[0]["remaining"], ["群乙"])
        restarted = self.make_plugin()
        restarted.cfg.notify.sessions = ["群甲", "群乙"]
        restarted._restore()
        self.context.send_message.reset_mock(side_effect=True)
        self.context.send_message.return_value = True
        await restarted._flush_outbox()
        self.assertEqual(restarted._outbox, [])
        call = self.context.send_message.await_args
        self.assertEqual(call.args[0], "群乙")
        self.assertTrue(call.args[1].mention_all)

    async def test_failed_fire_cannot_be_overtaken_by_recovery(self):
        self.context.send_message.side_effect = [False, True, True]
        self.plugin._queue_messages(["故障", "恢复"])
        await self.plugin._flush_outbox()
        self.assertEqual(self.context.send_message.await_count, 1)
        self.assertEqual(len(self.plugin._outbox), 2)
        await self.plugin._flush_outbox()
        self.assertEqual([call.args[1].text for call in self.context.send_message.await_args_list],
                         ["故障", "故障", "恢复"])

    async def test_manual_config_check_does_not_consume_alert(self):
        plugin = self.plugin
        for base in (A, B):
            plugin.monitor.client.raw(base + "manifest.json", b"", status=502)
        event = types.SimpleNamespace(message_str="/线路 配置", unified_msg_origin="群甲",
                                      role="admin", plain_result=lambda text: text)
        replies = [text async for text in plugin.route(event)]
        self.assertTrue(replies)
        self.assertTrue(plugin._outbox)
        await plugin._flush_outbox()
        self.assertTrue(self.context.send_message.await_count)
        self.assertFalse(plugin._outbox)

    async def test_muting_holds_outbox_and_recovered_failure_is_not_sent(self):
        plugin = self.plugin
        for base in (A, B):
            plugin.monitor.client.raw(base + "manifest.json", b"", status=502)
        outcome = await plugin.monitor.run_cycle(now=1000)
        plugin._queue_messages(outcome.messages)
        plugin.monitor.state.mute(60)
        await plugin._flush_outbox()
        self.context.send_message.assert_not_awaited()
        plugin.monitor.client = healthy_client()
        await plugin.monitor.run_cycle()
        plugin.monitor.state.unmute()
        await plugin._flush_outbox()
        self.context.send_message.assert_not_awaited()
        plugin._queue_messages((await plugin.monitor.run_cycle()).messages)
        await plugin._flush_outbox()
        self.assertTrue(self.context.send_message.await_count)
        self.assertTrue(all("恢复" in c.args[1].text for c in self.context.send_message.await_args_list))

    async def test_storage_failure_defers_sending_without_dropping_queue(self):
        self.plugin._queue_messages(["待发"])
        with patch.object(glue.store, "save_json", return_value="磁盘不可写"):
            await self.plugin._flush_outbox()
        self.context.send_message.assert_not_awaited()
        self.assertEqual(len(self.plugin._outbox), 1)
        await self.plugin._flush_outbox()
        self.assertFalse(self.plugin._outbox)

    async def test_unassigned_notice_waits_until_recipients_are_configured(self):
        self.plugin.cfg.notify.sessions = []
        self.plugin._queue_messages(["待发"])
        await self.plugin._flush_outbox()
        self.context.send_message.assert_not_awaited()
        self.assertEqual(len(self.plugin._outbox), 1)
        self.assertFalse(self.plugin._outbox[0]["assigned"])

        self.plugin.cfg.notify.sessions = ["群甲"]
        await self.plugin._flush_outbox()
        self.context.send_message.assert_awaited_once()
        self.assertEqual(self.context.send_message.await_args.args[0], "群甲")
        self.assertEqual(self.context.send_message.await_args.args[1].text, "待发")
        self.assertFalse(self.plugin._outbox)

    async def test_recovery_during_previous_send_discards_later_failure(self):
        plugin = self.plugin
        for base in (A, B):
            plugin.monitor.client.raw(base + "manifest.json", b"", status=502)
        failed = await plugin.monitor.run_cycle(now=1000)
        self.assertTrue(failed.messages)
        plugin._queue_messages(["前置通知", *failed.messages])
        sending, resume = asyncio.Event(), asyncio.Event()

        async def send(session, chain):
            if chain.text == "前置通知":
                sending.set()
                await resume.wait()
            return True

        self.context.send_message.side_effect = send
        delivery = asyncio.create_task(plugin._flush_outbox())
        try:
            await asyncio.wait_for(sending.wait(), timeout=5)
            # 平台发送尚未返回时，另一轮探测已经确认恢复并把恢复通知入队。
            plugin.monitor.client = healthy_client()
            recovered = await plugin.monitor.run_cycle(now=1300)
            self.assertTrue(recovered.messages)
            plugin._queue_messages(recovered.messages)
        finally:
            resume.set()
            await delivery

        self.context.send_message.assert_awaited_once()
        self.assertEqual(self.context.send_message.await_args.args[1].text, "前置通知")
        self.assertTrue(plugin._outbox)
        self.assertTrue(all(item["kind"] == "recover" for item in plugin._outbox))
        await plugin._flush_outbox()
        self.assertFalse(plugin._outbox)
        self.assertTrue(all("恢复" in call.args[1].text for call in
                            self.context.send_message.await_args_list[1:]))

    async def test_mute_during_first_recipient_holds_same_notice_for_next_recipient(self):
        plugin = self.plugin
        plugin.cfg.notify.sessions = ["群甲", "群乙"]
        plugin._queue_messages(["待发通知"])
        sending, resume = asyncio.Event(), asyncio.Event()

        async def send(session, chain):
            if session == "群甲":
                sending.set()
                await resume.wait()
            return True

        self.context.send_message.side_effect = send
        delivery = asyncio.create_task(plugin._flush_outbox())
        try:
            await asyncio.wait_for(sending.wait(), timeout=5)
            plugin.monitor.state.mute(60)
        finally:
            resume.set()
            await delivery

        self.context.send_message.assert_awaited_once()
        self.assertEqual(plugin._outbox[0]["remaining"], ["群乙"])
        plugin.monitor.state.unmute()
        await plugin._flush_outbox()
        self.assertEqual([call.args[0] for call in
                          self.context.send_message.await_args_list], ["群甲", "群乙"])
        self.assertFalse(plugin._outbox)

    async def test_recovery_during_first_recipient_discards_same_failure_for_next_recipient(self):
        plugin = self.plugin
        plugin.cfg.notify.sessions = ["群甲", "群乙"]
        for base in (A, B):
            plugin.monitor.client.raw(base + "manifest.json", b"", status=502)
        failed = await plugin.monitor.run_cycle(now=1000)
        self.assertEqual(len(failed.messages), 1)
        plugin._queue_messages(failed.messages)
        sending, resume = asyncio.Event(), asyncio.Event()

        async def send(session, chain):
            if session == "群甲" and "失败" in chain.text:
                sending.set()
                await resume.wait()
            return True

        self.context.send_message.side_effect = send
        delivery = asyncio.create_task(plugin._flush_outbox())
        try:
            await asyncio.wait_for(sending.wait(), timeout=5)
            plugin.monitor.client = healthy_client()
            recovered = await plugin.monitor.run_cycle(now=1300)
            self.assertTrue(recovered.messages)
            plugin._queue_messages(recovered.messages)
        finally:
            resume.set()
            await delivery

        self.context.send_message.assert_awaited_once()
        self.assertEqual(self.context.send_message.await_args.args[0], "群甲")
        self.assertTrue(all(item["kind"] == "recover" for item in plugin._outbox))
        await plugin._flush_outbox()
        self.assertFalse(plugin._outbox)
        recovery_calls = self.context.send_message.await_args_list[1:]
        self.assertEqual([call.args[0] for call in recovery_calls], ["群甲", "群乙"])
        self.assertTrue(all("恢复" in call.args[1].text for call in recovery_calls))

    async def test_background_fast_cycles_continue_while_slow_task_waits(self):
        plugin = self.plugin
        plugin.cfg.schedule.interval_fast_seconds = 0.001
        disc = Discovered()
        calls = []
        slow_started = asyncio.Event()

        async def fast(**kwargs):
            calls.append(kwargs)
            if len(calls) == 3:
                plugin._stop.set()
            return CycleOutcome(config=disc)

        async def slow(*args, **kwargs):
            slow_started.set()
            await asyncio.Event().wait()

        with patch.object(plugin.monitor, "run_cycle", side_effect=fast), \
                patch.object(plugin.monitor, "run_slow_cycle", side_effect=slow):
            await asyncio.wait_for(plugin._loop(), timeout=1)
            self.assertTrue(slow_started.is_set())
            self.assertEqual(len(calls), 3)
            self.assertFalse(plugin._slow_task.done())
            await plugin.terminate()

    def test_malformed_outbox_does_not_break_restore(self):
        store.save_json(self.plugin.cfg.state_path,
                        {"outbox": [None, {"text": "x", "remaining": 42},
                                    {"text": "x", "remaining": [], "keys": 42}]})
        self.plugin._restore()
        self.assertEqual(len(self.plugin._outbox), 1)

    def test_invalid_duration_cannot_leave_permanent_mute(self):
        for text in ("inf", "nan", "-1h", "1e300h"):
            self.assertIsNone(glue._duration(text))
        self.assertEqual(glue._duration("30m"), 1800)
