# -*- coding: utf-8 -*-
"""消息渲染：坏消息要能让人**不打开电脑**就判断要不要起床。"""

import unittest

from watch import render
from watch.models import ProbeResult, Severity
from watch.state import Notification


def fire(target, detail, probe="清单可达性", severity=Severity.P1):
    return Notification("fire", severity,
                        ProbeResult(False, probe, target, detail, severity=severity),
                        since=1000, duration_seconds=480)


class GroupTest(unittest.TestCase):
    def test_all_mirrors_escalates_to_p0(self):
        group = [fire("甲", "连接超时"), fire("乙", "HTTP 502")]
        self.assertEqual(render.escalated_severity(group, 2), Severity.P0)

    def test_one_of_many_stays_p1(self):
        self.assertEqual(render.escalated_severity([fire("甲", "HTTP 502")], 3),
                         Severity.P1)

    def test_message_says_impact_duration_and_what_was_ruled_out(self):
        msg = render.render_group(
            [fire("甲", "连接超时"), fire("乙", "HTTP 502")], enabled_mirrors=2,
            upstream_line=render.upstream_line(True, "2 条线路均 enabled", 1500))
        self.assertIn("影响：", msg)
        self.assertIn("已持续：8 分钟", msg)
        self.assertIn("排除配置问题", msg)

    def test_upstream_failure_points_at_the_entry(self):
        line = render.upstream_line(False, "入口不可达")
        self.assertIn("先看它", line)

    def test_at_all_only_on_p0(self):
        p0 = render.render_group([fire("甲", "x"), fire("乙", "y")],
                                 enabled_mirrors=2, at_all=True)
        p1 = render.render_group([fire("甲", "x")], enabled_mirrors=3, at_all=True)
        self.assertIn("@全体成员", p0)
        self.assertNotIn("@全体成员", p1)

    def test_columns_line_up_with_cjk_names(self):
        """中日韩字符占两格。按 len() 对齐的表格在手机上会歪，而告警最常见的
        阅读场景就是手机。"""
        msg = render.render_group([fire("多吉云", "HTTP 502"),
                                   fire("EdgeOne加速", "连接超时")], enabled_mirrors=3)
        rows = [(l, d) for l in msg.split("\n")
                for d in ("HTTP 502", "连接超时") if l.endswith(d)]
        # 详情列的起始显示宽度必须一致（按显示宽度量，不是按字符数）
        starts = {render._width(line[:line.rindex(detail)]) for line, detail in rows}
        self.assertEqual(len(starts), 1, rows)

    def test_prefix_marks_which_instance_reported(self):
        msg = render.render_group([fire("甲", "x")], enabled_mirrors=3, prefix="境内")
        self.assertIn("【境内】", msg)


class DurationTest(unittest.TestCase):
    def test_reads_like_a_human_wrote_it(self):
        self.assertEqual(render.human_duration(45), "45 秒")
        self.assertEqual(render.human_duration(480), "8 分钟")
        self.assertEqual(render.human_duration(7200), "2.0 小时")


if __name__ == "__main__":
    unittest.main()


class InjectionTest(unittest.TestCase):
    """告警里大量字符串**不是我们写的**：线路名与阈值来自配置源，文件名来自
    线路上的清单，错误文本来自对面的服务器。任何一处被改坏或被劫持，我们就会
    原样把它念进群里。"""

    def test_forged_alert_block_is_flattened(self):
        """最危险的一种：一个带换行的线路名，在群里看起来就是我们发的另一条 P0。"""
        msg = render.render_group(
            [fire("线路甲 正常\n\n🔴 P0 · 全部线路失败", "x")], enabled_mirrors=3)
        # 判据不是「不许出现这几个字」——那拦不住，也没必要。判据是**它永远
        # 起不了一行**：伪造之所以像真的，全靠自己独占一行顶在最上面。
        forged = [l for l in msg.split("\n")[1:] if l.lstrip().startswith("🔴")]
        self.assertEqual(forged, [], "伪造的告警不该独占一行：%r" % msg)

    def test_platform_control_codes_are_defanged(self):
        """QQ 的 CQ 码写在纯文本里也可能被适配器解析——等于让一条线路的名字
        替我们 @ 全体。"""
        out = render.safe("[CQ:at,qq=all]")
        self.assertNotIn("[CQ:", out)

    def test_at_all_text_is_neutralized(self):
        self.assertNotIn("@全体成员", render.safe("@全体成员 快跑"))

    def test_invisible_characters_are_stripped(self):
        self.assertEqual(render.safe("线​路‮甲"), "线路甲")

    def test_long_field_and_long_message_are_capped(self):
        self.assertLessEqual(len(render.safe("字" * 500)), render.MAX_FIELD + 1)
        self.assertLessEqual(len(render.clamp("字" * 9000)), render.MAX_MESSAGE + 24)

    def test_at_all_only_on_first_fire_not_on_reminders(self):
        """持续故障每 6 小时提醒一次，那几条再 @ 全体，人只会把 bot 屏蔽掉。"""
        remind = Notification("remind", Severity.P1,
                              ProbeResult(False, "清单可达性", "甲", "还在坏"),
                              since=1000, duration_seconds=6 * 3600)
        msg = render.render_group([remind, remind], enabled_mirrors=2, at_all=True)
        self.assertNotIn("@全体成员", msg)
