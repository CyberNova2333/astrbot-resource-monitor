# -*- coding: utf-8 -*-
"""命令闸门。这个插件跑在共享聊天环境里：同一个 bot 上有别人的插件，群里坐着
几百个不认识的人，而我们的命令会触发**真实的网络流量**。"""

import unittest

from watch.commands import CommandGate, CommandPolicy, build


def gate(**over):
    policy = CommandPolicy(allow_sessions={"群甲"}, **over)
    return CommandGate(policy)


class WhereTest(unittest.TestCase):
    def test_other_groups_get_silence(self):
        """bot 常常同时在很多群里。别的群没理由看到线路地址与阈值，
        而回一句「你没权限」本身也是在回应陌生环境里的指令。"""
        self.assertEqual(gate().refuse_reason("状态", session="别的群", is_admin=True), "")

    def test_configured_session_passes(self):
        self.assertIsNone(gate().refuse_reason("状态", session="群甲", is_admin=False))

    def test_respond_anywhere_is_opt_in(self):
        g = gate(respond_anywhere=True)
        self.assertIsNone(g.refuse_reason("状态", session="别的群", is_admin=False))


class WhoTest(unittest.TestCase):
    def test_traffic_commands_are_admin_only(self):
        reason = gate().refuse_reason("测", session="群甲", is_admin=False)
        self.assertIn("限管理员", reason)

    def test_mute_is_admin_only(self):
        """静音把所有告警关掉，而关掉之后没有任何人会知道。"""
        self.assertIn("管理员", gate().refuse_reason("静音", session="群甲", is_admin=False))

    def test_read_only_commands_are_open(self):
        for action in ("状态", "覆盖率"):
            self.assertIsNone(gate().refuse_reason(action, session="群甲", is_admin=False))


class CooldownTest(unittest.TestCase):
    def test_repeat_is_rate_limited(self):
        """拦的不是恶意，是复读：两个人同时想起来要测一下，就会连开两轮。"""
        g = gate(cooldown_seconds=60)
        self.assertIsNone(g.refuse_reason("测", session="群甲", is_admin=True, now=0))
        g.mark("测", now=0)
        self.assertIn("秒后再来", g.refuse_reason("测", session="群甲", is_admin=True, now=10))
        self.assertIsNone(g.refuse_reason("测", session="群甲", is_admin=True, now=61))

    def test_cooldown_is_shared_across_heavy_commands(self):
        """两条不同的重命令连着来，打出去的流量是一样的。"""
        g = gate(cooldown_seconds=60)
        g.mark("测", now=0)
        self.assertIsNotNone(g.refuse_reason("配置", session="群甲", is_admin=True, now=5))

    def test_read_only_commands_have_no_cooldown(self):
        g = gate(cooldown_seconds=60)
        g.mark("测", now=0)
        self.assertIsNone(g.refuse_reason("状态", session="群甲", is_admin=True, now=1))


class BuildTest(unittest.TestCase):
    def test_defaults_are_closed(self):
        """忘了配的人也该是安全的。"""
        g = build(["群甲"])
        self.assertTrue(g.policy.heavy_admin_only)
        self.assertFalse(g.policy.respond_anywhere)
        self.assertEqual(g.policy.allow_sessions, {"群甲"})

    def test_junk_values_fall_back(self):
        g = build(["群甲"], {"cooldown_seconds": "很久"})
        self.assertEqual(g.policy.cooldown_seconds, 60.0)
