# -*- coding: utf-8 -*-
"""本地配置：**没有默认入口**，其余旋钮才有默认值。"""

import unittest

from watch.config import ConfigError, from_mapping

BASE = {"entry_url": "https://api.example.test/path/config.json"}


class LocalConfigTest(unittest.TestCase):
    def test_entry_url_is_required(self):
        """不设默认入口是有意的：默认值会让插件在没配好的机器上「跑起来」，
        群里一片绿而其实什么都没探。"""
        with self.assertRaises(ConfigError):
            from_mapping({})
        with self.assertRaises(ConfigError):
            from_mapping({"entry_url": "不是地址"})

    def test_sessions_accept_a_comma_separated_string(self):
        cfg = from_mapping(dict(BASE, notify={"sessions": "甲, 乙，丙"}))
        self.assertEqual(cfg.notify.sessions, ["甲", "乙", "丙"])

    def test_impossible_alert_window_is_rejected(self):
        with self.assertRaises(ConfigError):
            from_mapping(dict(BASE, alert={"fire_after_failures": 5, "fire_window": 3}))

    def test_defaults_are_monitor_owned_knobs_only(self):
        cfg = from_mapping(BASE)
        self.assertEqual(cfg.schedule.interval_fast_seconds, 300)
        self.assertEqual(cfg.alert.fire_after_failures, 2)
        self.assertTrue(cfg.alert.mute_command_admin_only)
        # 被监控方的阈值一个都不该在这里出现
        self.assertFalse(hasattr(cfg, "min_speed_kbps"))

    def test_comment_fields_in_the_example_are_harmless(self):
        cfg = from_mapping(dict(BASE, comment="样例里的说明字段"))
        self.assertTrue(cfg.entry_url)


if __name__ == "__main__":
    unittest.main()
