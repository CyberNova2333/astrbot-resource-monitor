"""官方机器人投递与人工确认回归；只使用框架替身，不连接聊天平台。"""

import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests.astrbot_stub import Chain
from tests.test_delivery import glue
from tests.test_runner import cfg, healthy_client
from watch import commands, render
from watch.runner import Monitor


GROUP = "测试实例甲:GroupMessage:测试群甲"
FRIEND = "测试实例乙:FriendMessage:测试用户甲"
OTHER_GROUP = "测试实例甲:GroupMessage:测试群乙"
OTHER_PLATFORM = "测试实例丙:GroupMessage:测试群甲"


def event_for(session=GROUP, *, platform="qq_official", sender="测试管理员甲",
              admin=True, command="通知"):
    return types.SimpleNamespace(
        message_str="/线路 " + command,
        unified_msg_origin=session,
        role="admin" if admin else "member",
        get_platform_name=lambda: platform,
        get_sender_id=lambda: sender,
        plain_result=lambda text: Chain().message(text),
    )


class QQOfficialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.platforms = {}
        self.add_platform("测试实例甲", "qq_official")
        self.add_platform("测试实例乙", "qq_official_webhook")
        self.add_platform("测试实例丙", "aiocqhttp")
        self.context = types.SimpleNamespace(
            send_message=AsyncMock(return_value=True),
            get_platform_inst=Mock(side_effect=self.platforms.get),
        )
        self.plugin = self.make_plugin()

    def add_platform(self, platform_id, name, *, proactive=True):
        meta = types.SimpleNamespace(id=platform_id, name=name,
                                     support_proactive_message=proactive)
        self.platforms[platform_id] = types.SimpleNamespace(meta=lambda: meta)
        return meta

    def make_plugin(self, sessions=None, command=None):
        plugin = glue.ResourceWatch(self.context)
        plugin.cfg = cfg(runtime={"state_dir": self.temp.name},
                         notify={"sessions": sessions or [GROUP]},
                         command=command or {})
        plugin.monitor = Monitor(plugin.cfg, healthy_client())
        plugin.gate = commands.build(plugin.cfg.notify.sessions, plugin.cfg.command)
        return plugin

    async def replies(self, event, plugin=None):
        return [reply async for reply in (plugin or self.plugin).route(event)]

    async def test_both_adapters_use_metadata_for_custom_ids_and_plain_messages(self):
        for session, platform in ((GROUP, "qq_official"),
                                  (FRIEND, "qq_official_webhook")):
            with self.subTest(platform=platform):
                plugin = self.make_plugin([session])
                plugin._queue_messages([render.RenderedMessage(
                    '故障 https://source.example.test/path <qqbot-at-everyone />',
                    at_all=True)])
                self.context.send_message.reset_mock()
                await plugin._flush_outbox()
                self.context.send_message.assert_awaited_once()
                target, chain = self.context.send_message.await_args.args
                self.assertEqual(target, session)
                self.assertIn("故障", chain.text)
                self.assertIn("[链接已省略]", chain.text)
                self.assertNotIn("example.test", chain.text)
                self.assertNotIn("<", chain.text)
                self.assertNotIn(">", chain.text)
                self.assertFalse(chain.mention_all)
                self.assertIs(chain.use_markdown_, False)
                self.assertIs(chain.use_t2i_, False)
                self.assertEqual(plugin._outbox[0]["remaining"], [session])
                await plugin._flush_outbox()
                self.context.send_message.assert_awaited_once()

    async def test_platform_lookup_uses_instance_id_not_adapter_type(self):
        self.plugin._queue_messages(["故障"])
        await self.plugin._flush_outbox()
        self.context.get_platform_inst.assert_called_with("测试实例甲")

    async def test_missing_platform_retains_notice_until_adapter_is_available(self):
        platform = self.platforms.pop("测试实例甲")
        self.plugin._queue_messages(["平台未就绪时的通知"])
        await self.plugin._flush_outbox()
        self.context.send_message.assert_not_awaited()
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])
        self.assertEqual(self.plugin._outbox[0]["submitted"], [])
        self.assertIn("平台未就绪时的通知", (await self.replies(event_for()))[0].text)

        self.platforms["测试实例甲"] = platform
        await self.plugin._flush_outbox()
        self.context.send_message.assert_awaited_once()
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])
        self.assertEqual(self.plugin._outbox[0]["submitted"], [GROUP])
        await self.plugin._flush_outbox()
        self.context.send_message.assert_awaited_once()

    async def test_unsupported_or_undeclared_proactive_capability_retains_notice(self):
        meta = self.platforms["测试实例甲"].meta()
        for undeclared in (False, True):
            with self.subTest(undeclared=undeclared):
                if undeclared:
                    del meta.support_proactive_message
                else:
                    meta.support_proactive_message = False
                plugin = self.make_plugin()
                plugin._queue_messages(["仅查询通知"])
                await plugin._flush_outbox()
                self.context.send_message.assert_not_awaited()
                replies = await self.replies(event_for(), plugin)
                self.assertIn("仅查询通知", replies[0].text)
                self.assertEqual(plugin._outbox[0]["remaining"], [GROUP])

    async def test_false_or_exception_retries_without_overtaking_failed_notice(self):
        for failure in (False, OSError("平台暂不可用")):
            with self.subTest(failure=type(failure).__name__):
                plugin = self.make_plugin()
                plugin._queue_messages(["故障", "恢复"])
                self.context.send_message.reset_mock()
                self.context.send_message.side_effect = [failure, True, True]
                await plugin._flush_outbox()
                self.assertEqual(self.context.send_message.await_count, 1)
                self.assertEqual(len(plugin._outbox), 2)
                await plugin._flush_outbox()
                sent = [call.args[1].text for call in
                        self.context.send_message.await_args_list]
                self.assertEqual(sent, ["故障", "故障", "恢复"])
                await plugin._flush_outbox()
                self.assertEqual(self.context.send_message.await_count, 3)
                self.assertTrue(all(item["remaining"] == [GROUP]
                                    for item in plugin._outbox))

    async def test_none_return_does_not_confirm_notification(self):
        self.context.send_message.return_value = None
        self.plugin._queue_messages(["未确认通知"])
        await self.plugin._flush_outbox()
        await self.plugin._flush_outbox()
        self.context.send_message.assert_awaited_once()
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])
        self.assertIn("未确认通知", (await self.replies(event_for()))[0].text)

    async def test_restart_keeps_submitted_notice_without_repeating_push(self):
        self.plugin._queue_messages(["重启前通知"])
        await self.plugin._flush_outbox()
        restarted = self.make_plugin()
        restarted._restore()
        self.context.send_message.reset_mock()
        await restarted._flush_outbox()
        self.context.send_message.assert_not_awaited()
        replies = await self.replies(event_for(), restarted)
        self.assertIn("重启前通知", replies[0].text)
        self.assertEqual(restarted._outbox[0]["remaining"], [GROUP])

    async def test_other_platform_still_sends_mentions_and_removes_recipient(self):
        plugin = self.make_plugin([GROUP, OTHER_PLATFORM])
        plugin._queue_messages([render.RenderedMessage("故障", at_all=True)])
        await plugin._flush_outbox()
        chains = {call.args[0]: call.args[1]
                  for call in self.context.send_message.await_args_list}
        self.assertFalse(chains[GROUP].mention_all)
        self.assertTrue(chains[OTHER_PLATFORM].mention_all)
        self.assertEqual(plugin._outbox[0]["remaining"], [GROUP])

    async def test_notification_command_only_shows_oldest_notice_for_current_session(self):
        plugin = self.make_plugin([GROUP, OTHER_GROUP])
        plugin._queue_messages(["只属于群乙"])
        plugin._outbox[0]["remaining"] = [OTHER_GROUP]
        plugin._queue_messages(["群甲第一条", "群甲第二条"])
        replies = await self.replies(event_for(), plugin)
        self.assertEqual(len(replies), 1)
        self.assertIn("群甲第一条", replies[0].text)
        self.assertNotIn("只属于群乙", replies[0].text)
        self.assertNotIn("群甲第二条", replies[0].text)
        self.assertEqual(len(plugin._outbox), 3)

    async def test_query_and_confirm_obey_session_gate(self):
        self.plugin._queue_messages(["仅允许会话可见"])
        for command in ("通知", "确认"):
            replies = await self.replies(event_for(OTHER_GROUP, command=command))
            self.assertEqual(replies, [])
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])

    async def test_extra_command_session_cannot_read_another_sessions_notice(self):
        plugin = self.make_plugin(command={"allow_sessions": [OTHER_GROUP]})
        plugin._queue_messages(["收件人专属通知"])
        replies = await self.replies(event_for(OTHER_GROUP), plugin)
        self.assertNotIn("收件人专属通知", replies[0].text)
        self.assertEqual(plugin._outbox[0]["remaining"], [GROUP])

    async def test_muting_holds_delivery_and_hides_pending_notice(self):
        self.plugin._queue_messages(["静音中的通知内容"])
        self.plugin.monitor.state.mute(60)
        await self.plugin._flush_outbox()
        self.context.send_message.assert_not_awaited()
        replies = await self.replies(event_for())
        self.assertIn("静音", replies[0].text)
        self.assertNotIn("静音中的通知内容", replies[0].text)
        self.assertEqual(len(self.plugin._outbox), 1)

    async def test_confirm_requires_admin_even_when_privileged_policy_is_relaxed(self):
        plugin = self.make_plugin(command={"privileged_admin_only": False})
        plugin._queue_messages(["待确认"])
        await self.replies(event_for(), plugin)
        # 即使查看之后身份降为普通成员，也不能利用已保存的查看记录确认。
        replies = await self.replies(event_for(admin=False, command="确认"), plugin)
        self.assertIn("管理员", replies[0].text)
        self.assertEqual(plugin._outbox[0]["remaining"], [GROUP])

    async def test_confirm_is_bound_to_viewer_and_only_removes_that_recipient(self):
        plugin = self.make_plugin([GROUP, OTHER_GROUP])
        plugin._queue_messages(["共同通知"])
        await self.replies(event_for(), plugin)
        await self.replies(event_for(sender="测试管理员乙", command="确认"), plugin)
        self.assertEqual(plugin._outbox[0]["remaining"], [GROUP, OTHER_GROUP])
        await self.replies(event_for(OTHER_GROUP, command="确认"), plugin)
        self.assertEqual(plugin._outbox[0]["remaining"], [GROUP, OTHER_GROUP])
        await self.replies(event_for(command="确认"), plugin)
        self.assertEqual(plugin._outbox[0]["remaining"], [OTHER_GROUP])

    async def test_missing_sender_cannot_confirm_even_after_viewing(self):
        self.plugin._queue_messages(["待确认"])
        await self.replies(event_for(sender=""))
        await self.replies(event_for(sender="", command="确认"))
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])

    async def test_confirmation_needs_new_view_after_restart(self):
        self.plugin._queue_messages(["待确认"])
        await self.replies(event_for())
        restarted = self.make_plugin()
        restarted._restore()
        await self.replies(event_for(command="确认"), restarted)
        self.assertEqual(restarted._outbox[0]["remaining"], [GROUP])
        await self.replies(event_for(), restarted)
        await self.replies(event_for(command="确认"), restarted)
        self.assertFalse(restarted._outbox)

    async def test_expired_view_cannot_confirm_replacement_with_same_text(self):
        self.plugin._queue_messages([render.RenderedMessage(
            "同一条通知文字", kind="fire", keys=["测试探针|测试目标"])])
        with patch.object(self.plugin.monitor.state, "is_firing", return_value=True):
            await self.replies(event_for())
        self.plugin._queue_messages(["同一条通知文字"])
        await self.replies(event_for(command="确认"))
        self.assertEqual(len(self.plugin._outbox), 1)
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])
        await self.replies(event_for())
        await self.replies(event_for(command="确认"))
        self.assertFalse(self.plugin._outbox)

    async def test_confirm_save_failure_restores_recipient_and_allows_retry(self):
        self.plugin._queue_messages(["磁盘失败时不能丢失"])
        await self.replies(event_for())
        # 预处理保存均成功，仅确认变更落盘失败。
        with patch.object(self.plugin, "_persist", side_effect=[True, True, False]):
            replies = await self.replies(event_for(command="确认"))
        self.assertIn("失败", replies[0].text)
        self.assertEqual(self.plugin._outbox[0]["remaining"], [GROUP])
        restarted = self.make_plugin()
        restarted._restore()
        self.assertEqual(restarted._outbox[0]["remaining"], [GROUP])
        await self.replies(event_for(command="确认"))
        self.assertFalse(self.plugin._outbox)

    async def test_successful_confirmation_survives_restart(self):
        self.plugin._queue_messages(["已确认不应再出现", "下一条仍需处理"])
        await self.replies(event_for())
        await self.replies(event_for(command="确认"))
        restarted = self.make_plugin()
        restarted._restore()
        replies = await self.replies(event_for(), restarted)
        self.assertNotIn("已确认不应再出现", replies[0].text)
        self.assertIn("下一条仍需处理", replies[0].text)

    async def test_removing_notification_recipient_retires_old_view(self):
        self.plugin._queue_messages(["旧收件人通知"])
        await self.replies(event_for())
        self.plugin.cfg.notify.sessions = [OTHER_GROUP]
        await self.replies(event_for(command="确认"))
        self.assertFalse(self.plugin._outbox)

    async def test_passive_replies_use_same_plain_text_sanitization(self):
        for platform in ("qq_official", "qq_official_webhook"):
            with self.subTest(platform=platform):
                plugin = self.make_plugin()
                plugin._queue_messages([
                    '查看 https://source.example.test/path\n<qqbot-at-user id="测试用户" />'])
                replies = await self.replies(event_for(platform=platform), plugin)
                text = replies[0].text
                self.assertIn("[链接已省略]", text)
                self.assertIn("\n", text)
                self.assertNotIn("example.test", text)
                self.assertNotIn("<", text)
                self.assertNotIn(">", text)
                self.assertIs(replies[0].use_markdown_, False)
                self.assertIs(replies[0].use_t2i_, False)

    def test_non_qq_reply_is_not_rewritten(self):
        text = "https://source.example.test/path <保留文本>"
        reply = glue._reply(event_for(platform="aiocqhttp"), text)
        self.assertEqual(reply.text, text)
        self.assertIsNone(reply.use_markdown_)
        self.assertIsNone(reply.use_t2i_)
