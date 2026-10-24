# -*- coding: utf-8 -*-
"""告警状态机：连报、去重、抑制链、恢复、静音、落盘。

这些判据的目的只有一个——**别让人把 bot 关掉**。
"""

import unittest

from watch.models import ProbeResult, Severity
from watch.state import AlertState

BAD = ProbeResult(False, "清单可达性", "线路甲", "HTTP 502", severity=Severity.P1)
GOOD = ProbeResult(True, "清单可达性", "线路甲", "OK")


def kinds(notes):
    return [n.kind for n in notes]


class FireAndRecoverTest(unittest.TestCase):
    def setUp(self):
        self.s = AlertState(fire_after=2, window=3, recover_after=2,
                            remind_every_hours=6)

    def test_single_failure_does_not_alert(self):
        self.assertEqual(kinds(self.s.ingest([BAD], now=0)), [])

    def test_two_of_three_fires_once(self):
        self.s.ingest([BAD], now=0)
        self.assertEqual(kinds(self.s.ingest([BAD], now=60)), ["fire"])
        self.assertEqual(kinds(self.s.ingest([BAD], now=120)), [])

    def test_reminder_after_interval(self):
        self.s.ingest([BAD], now=0)
        self.s.ingest([BAD], now=60)
        self.assertEqual(kinds(self.s.ingest([BAD], now=60 + 6 * 3600)), ["remind"])

    def test_recovery_is_reported(self):
        self.s.ingest([BAD], now=0)
        self.s.ingest([BAD], now=60)
        self.assertEqual(kinds(self.s.ingest([GOOD], now=120)), [])
        notes = self.s.ingest([GOOD], now=180)
        self.assertEqual(kinds(notes), ["recover"])
        self.assertEqual(notes[0].severity, Severity.INFO)

    def test_unknown_neither_breaks_nor_heals(self):
        unknown = ProbeResult(True, "清单可达性", "线路甲", "判据没跑成", unknown=True)
        self.s.ingest([BAD], now=0)
        self.s.ingest([BAD], now=60)              # FIRING
        self.assertEqual(kinds(self.s.ingest([unknown], now=120)), [])
        self.assertTrue(self.s.is_firing(BAD.key))


class SuppressionTest(unittest.TestCase):
    def test_downstream_is_suppressed_while_upstream_fires(self):
        s = AlertState(fire_after=1, window=1, recover_after=1)
        up = ProbeResult(False, "线上配置可达性", "线上配置", "入口不可达",
                         severity=Severity.P0)
        down = ProbeResult(False, "清单可达性", "线路甲", "HTTP 502",
                           suppress_key=up.key)
        first = s.ingest([up, down], now=0)
        self.assertEqual(kinds(first), ["fire"])          # 只报上游那条
        self.assertTrue(s.is_firing(down.key))            # 下游状态照样进 FIRING

    def test_downstream_recovers_normally_afterwards(self):
        """下游被抑制过，也要能正常发恢复——否则人会一直以为还坏着。"""
        s = AlertState(fire_after=1, window=1, recover_after=1)
        up = ProbeResult(False, "线上配置可达性", "线上配置", "入口不可达")
        down = ProbeResult(False, "清单可达性", "线路甲", "HTTP 502",
                           suppress_key=up.key)
        s.ingest([up, down], now=0)
        notes = s.ingest([ProbeResult(True, "线上配置可达性", "线上配置", "OK"),
                          ProbeResult(True, "清单可达性", "线路甲", "OK")], now=60)
        self.assertEqual(kinds(notes), ["recover", "recover"])


class MuteTest(unittest.TestCase):
    def test_muted_swallows_notifications_but_keeps_state(self):
        s = AlertState(fire_after=1, window=1)
        s.mute(1800, now=0)
        self.assertEqual(kinds(s.ingest([BAD], now=10)), [])
        self.assertTrue(s.is_firing(BAD.key))
        # 静音期间从未交付的故障，解除静音后的下一轮应发首次通知。
        s.unmute()
        self.assertEqual(kinds(s.ingest([BAD], now=11)), ["fire"])


class PersistenceTest(unittest.TestCase):
    def test_roundtrip_keeps_firing_state(self):
        """bot 重启后不该把仍在持续的故障当成新故障重报一遍。"""
        s = AlertState(fire_after=1, window=1)
        s.ingest([BAD], now=0)
        s.remember("client_version", "1.0.170")
        blob = s.to_dict()

        s2 = AlertState(fire_after=1, window=1)
        s2.load_dict(blob)
        self.assertTrue(s2.is_firing(BAD.key))
        self.assertEqual(s2.note("client_version"), "1.0.170")
        self.assertEqual(kinds(s2.ingest([BAD], now=60)), [])

    def test_broken_state_file_is_ignored(self):
        s = AlertState()
        s.load_dict({"entries": "这不是对象"})     # 不该抛
        self.assertEqual(s.entries, {})


if __name__ == "__main__":
    unittest.main()
