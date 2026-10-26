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
        self.context = types.SimpleNamespace(send_message=AsyncMock(return_value=True))
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
