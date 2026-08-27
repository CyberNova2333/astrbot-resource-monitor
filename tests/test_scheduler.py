# -*- coding: utf-8 -*-
"""轮转与节奏。"""

import unittest

from watch.models import FileEntry
from watch.scheduler import HotPackagePolicy, Rotation, Ticker

ENTRIES = {
    "a.zip": FileEntry("a.zip", 100, 50, ["0" * 32] * 2),
    "b.zip": FileEntry("b.zip", 60, 30, ["1" * 32] * 2),
}


class RotationTest(unittest.TestCase):
    def test_covers_everything_in_order(self):
        r = Rotation()
        seen = []
        for _ in range(4):
            (entry, idx), = r.plan(ENTRIES, 1)
            seen.append((entry.name, idx))
            r.mark(entry.name, idx, now=100)
        self.assertEqual(seen, [("a.zip", 0), ("a.zip", 1), ("b.zip", 0), ("b.zip", 1)])

    def test_wraps_around(self):
        r = Rotation()
        for _ in range(4):
            (entry, idx), = r.plan(ENTRIES, 1)
            r.mark(entry.name, idx, now=100)
        (entry, idx), = r.plan(ENTRIES, 1)
        self.assertEqual((entry.name, idx), ("a.zip", 0))

    def test_cursor_survives_manifest_change(self):
        """清单变了不该让轮转乱掉——记的是 (文件, 块号)，不是下标。"""
        r = Rotation(cursor="zz.zip#7")
        picked = r.plan(ENTRIES, 1)
        self.assertEqual((picked[0][0].name, picked[0][1]), ("a.zip", 0))

    def test_coverage_has_a_window(self):
        """一个月前验过的块说明不了现在。没有窗口的覆盖率会永远停在 100%。"""
        r = Rotation()
        r.mark("a.zip", 0, now=0)
        self.assertAlmostEqual(r.coverage(ENTRIES, now=0).percent, 25.0)
        later = r.coverage(ENTRIES, window_seconds=7 * 86400, now=8 * 86400)
        self.assertEqual(later.verified, 0)
        self.assertEqual(later.stale, 1)

    def test_prune_drops_vanished_files(self):
        r = Rotation()
        r.mark("gone.zip", 0, now=0)
        r.mark("a.zip", 0, now=0)
        self.assertEqual(r.prune(ENTRIES), 1)
        self.assertNotIn("gone.zip#0", r.seen)


class HotPolicyTest(unittest.TestCase):
    def test_version_change_triggers(self):
        p = HotPackagePolicy(on_version_change=True, min_interval_seconds=10 ** 6)
        t = Ticker()
        self.assertTrue(p.should_check("甲|a.zip", 5, t, {}, now=0))
        t.mark("甲|a.zip", 0)
        self.assertFalse(p.should_check("甲|a.zip", 5, t, {"甲|a.zip": 5}, now=1))
        self.assertTrue(p.should_check("甲|a.zip", 6, t, {"甲|a.zip": 5}, now=2))

    def test_min_interval_is_a_backstop(self):
        """版本一直没变也要兜一次底——「没变」也可能是缓存把新包挡住了。"""
        p = HotPackagePolicy(on_version_change=True, min_interval_seconds=100)
        t = Ticker({"甲|a.zip": 0})
        self.assertFalse(p.should_check("甲|a.zip", 5, t, {"甲|a.zip": 5}, now=50))
        self.assertTrue(p.should_check("甲|a.zip", 5, t, {"甲|a.zip": 5}, now=200))


if __name__ == "__main__":
    unittest.main()
