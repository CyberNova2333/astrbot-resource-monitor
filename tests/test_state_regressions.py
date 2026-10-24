# -*- coding: utf-8 -*-
"""验证通知、覆盖与权限的可观察行为，避免复现过的故障重新出现。"""

import unittest
from dataclasses import replace

from watch.commands import build
from watch.models import FileEntry, ProbeResult, Severity
from watch.probes import PROBE_CHUNK, PROBE_MANIFEST
from watch import render
from watch.scheduler import Rotation, Ticker
from watch.state import AlertState, Notification


def failure(mirror="甲", probe=PROBE_MANIFEST, target=None, suppress_key=None):
    return ProbeResult(False, probe, target or mirror, "检查失败",
                       suppress_key=suppress_key, extra={"mirror": mirror})


def success(result):
    return ProbeResult(True, result.probe, result.target, "恢复正常",
                       suppress_key=result.suppress_key, extra=result.extra)


class NotificationRegressionTest(unittest.TestCase):
    def test_severity_upgrade_fires_immediately_and_only_once(self):
        state = AlertState(fire_after=1, window=1, remind_every_hours=6)
        warning = replace(failure(), severity=Severity.P2)
        urgent = replace(warning, severity=Severity.P0)
        state.ingest([warning], now=100)
        note, = state.ingest([urgent], now=101)
        self.assertEqual((note.kind, note.severity), ("fire", Severity.P0))
        self.assertEqual(state.ingest([urgent], now=102), [])

    def test_muted_upgrade_is_delivered_after_restart_and_unmute(self):
        state = AlertState(fire_after=1, window=1)
        warning = replace(failure(), severity=Severity.P2)
        urgent = replace(warning, severity=Severity.P0)
        state.ingest([warning], now=100)
        state.mute(1000, now=101)
        self.assertEqual(state.ingest([urgent], now=102), [])
        restored = AlertState(fire_after=1, window=1)
        restored.load_dict(state.to_dict())
        self.assertEqual(restored.entries[urgent.key].notified_severity, Severity.P2.value)
        restored.unmute()
        note, = restored.ingest([urgent], now=103)
        self.assertEqual((note.kind, note.severity), ("fire", Severity.P0))

    def test_suppressed_upgrade_remains_pending_until_upstream_recovers(self):
        state = AlertState(fire_after=1, window=1, recover_after=1)
        upstream = failure("上游", probe="入口")
        warning = replace(failure(suppress_key=upstream.key), severity=Severity.P2)
        urgent = replace(warning, severity=Severity.P0)
        state.ingest([warning], now=100)
        notes = state.ingest([upstream, urgent], now=101)
        self.assertEqual([n.result.key for n in notes], [upstream.key])
        notes = state.ingest([success(upstream), urgent], now=102)
        self.assertEqual([(n.kind, n.result.key) for n in notes],
                         [("recover", upstream.key), ("fire", urgent.key)])

    def test_duplicate_key_keeps_most_urgent_failure_in_round(self):
        state = AlertState(fire_after=1, window=1)
        warning = replace(failure(), severity=Severity.P2)
        urgent = replace(warning, severity=Severity.P0)
        note, = state.ingest([warning, urgent], now=100)
        self.assertEqual(note.severity, Severity.P0)

    def test_multiple_checks_in_one_round_cannot_fake_failure_or_recovery_streak(self):
        state = AlertState(fire_after=2, window=2, recover_after=2)
        bad = failure()
        self.assertEqual(state.ingest([bad, bad, success(bad)], now=100), [])
        note, = state.ingest([bad, success(bad)], now=200)
        self.assertEqual(note.kind, "fire")
        self.assertEqual(state.ingest([success(bad), success(bad)], now=300), [])
        recovery, = state.ingest([success(bad)], now=400)
        self.assertEqual(recovery.kind, "recover")

    def test_muted_reminder_does_not_advance_notification_clock(self):
        state = AlertState(fire_after=1, window=1, remind_every_hours=1)
        bad = failure()
        state.ingest([bad], now=100)
        state.mute(4000, now=200)
        self.assertEqual(state.ingest([bad], now=3800), [])
        self.assertEqual(state.entries[bad.key].last_notified_at, 100)
        notes = state.ingest([bad], now=4201)
        self.assertEqual([n.kind for n in notes], ["remind"])

    def test_muted_incident_that_recovers_does_not_emit_stale_messages(self):
        state = AlertState(fire_after=1, window=1, recover_after=1)
        bad = failure()
        state.mute(1000, now=100)
        self.assertEqual(state.ingest([bad], now=110), [])
        self.assertEqual(state.ingest([success(bad)], now=120), [])
        state.unmute()
        self.assertEqual(state.ingest([success(bad)], now=130), [])

    def test_muted_recovery_of_announced_incident_survives_restart(self):
        state = AlertState(fire_after=1, window=1, recover_after=1)
        bad = failure()
        state.ingest([bad], now=0)
        state.mute(1000, now=100)
        self.assertEqual(state.ingest([success(bad)], now=110), [])
        for now in (111, 112, 113):
            self.assertEqual(state.ingest([success(bad)], now=now), [])
        self.assertIn(bad.key, state.entries, "尚未交付恢复通知的干净条目必须保留")
        restored = AlertState(fire_after=1, window=1, recover_after=1)
        restored.load_dict(state.to_dict())
        restored.unmute()
        recovery, = restored.ingest([success(bad)], now=120)
        self.assertEqual(recovery.kind, "recover")
        self.assertEqual(recovery.duration_seconds, 110)
        self.assertEqual(restored.ingest([success(bad)], now=130), [])

    def test_relapse_cancels_pending_recovery_during_mute(self):
        state = AlertState(fire_after=1, window=1, recover_after=1)
        bad = failure()
        state.ingest([bad], now=100)
        state.mute(1000, now=200)
        state.ingest([success(bad)], now=300)
        state.ingest([bad], now=400)
        state.unmute()
        note, = state.ingest([bad], now=500)
        self.assertEqual(note.kind, "fire")

    def test_unmute_delivers_confirmed_slow_recovery_during_unrelated_fast_round(self):
        state = AlertState(fire_after=1, window=1, recover_after=1)
        slow_bad = failure(probe="慢速检查")
        state.ingest([slow_bad], now=100)
        state.mute(1000, now=200)
        state.ingest([success(slow_bad)], now=300)
        state.unmute()
        source_good = success(failure("配置", probe="入口"))
        recovery, = state.ingest([source_good], now=400)
        self.assertEqual((recovery.kind, recovery.result.key), ("recover", slow_bad.key))
        self.assertEqual(recovery.duration_seconds, 200)
        self.assertEqual(state.ingest([source_good], now=500), [])

    def test_same_round_relapse_cancels_confirmed_recovery_before_drain(self):
        state = AlertState(fire_after=1, window=1, recover_after=1)
        slow_bad = failure(probe="慢速检查")
        state.ingest([slow_bad], now=100)
        state.mute(1000, now=200)
        state.ingest([success(slow_bad)], now=300)
        state.unmute()
        source_good = success(failure("配置", probe="入口"))
        notes = state.ingest([source_good, slow_bad], now=400)
        self.assertEqual([(note.kind, note.result.key) for note in notes],
                         [("fire", slow_bad.key)])

    def test_upstream_suppresses_reminders_and_releases_unsent_first_alert(self):
        state = AlertState(fire_after=1, window=1, recover_after=1,
                           remind_every_hours=1)
        upstream = failure("配置", probe="入口")
        downstream = failure(suppress_key=upstream.key)
        self.assertEqual(len(state.ingest([upstream, downstream], now=100)), 1)
        notes = state.ingest([upstream, downstream], now=3800)
        self.assertEqual([n.result.key for n in notes], [upstream.key])
        self.assertFalse(state.entries[downstream.key].has_notified)
        notes = state.ingest([success(upstream), downstream], now=3801)
        self.assertEqual([(n.kind, n.result.key) for n in notes],
                         [("recover", upstream.key), ("fire", downstream.key)])

    def test_initial_timestamp_zero_is_a_real_failure_time(self):
        state = AlertState(fire_after=2, window=2, recover_after=1)
        bad = failure()
        state.ingest([bad], now=0)
        note, = state.ingest([bad], now=60)
        self.assertEqual(note.since, 0)
        self.assertEqual(note.duration_seconds, 60)
        recovery, = state.ingest([success(bad)], now=120)
        self.assertEqual(recovery.duration_seconds, 120)

    def test_active_results_survive_restart_and_recovery_threshold(self):
        state = AlertState(fire_after=1, window=1, recover_after=2)
        bad = failure("甲#备用")
        state.ingest([bad], now=100)
        restored = AlertState(fire_after=1, window=1, recover_after=2)
        restored.load_dict(state.to_dict())
        restored.ingest([success(bad)], now=101)
        self.assertEqual(restored.active_results(), [bad])
        restored.ingest([success(bad)], now=102)
        self.assertEqual(restored.active_results(), [])

    def test_bad_state_fields_do_not_break_startup(self):
        state = AlertState()
        state.load_dict({"muted_until": "bad", "entries": {
            "bad": {"status": "wrong", "window": 42, "severity": {},
                    "first_failed_at": "nan", "last_notified_at": [],
                    "successes": "inf", "result": {"ok": True}},
            "skip": [],
        }})
        self.assertEqual(state.muted_until, 0)
        self.assertEqual(state.entries["bad"].window, [])
        self.assertEqual(state.entries["bad"].successes, 0)
        self.assertEqual(state.active_results(), [])


class AggregationRegressionTest(unittest.TestCase):
    def test_distinct_blocks_on_same_mirror_do_not_escalate(self):
        notes = [Notification("fire", Severity.P1,
                              failure(probe=PROBE_CHUNK, target="甲#包[%d]" % i))
                 for i in range(2)]
        self.assertEqual(render.escalated_severity(notes, 2), Severity.P1)
        message = render.render_group(notes, enabled_mirrors=2, at_all=True)
        self.assertNotIn("全部", message)
        self.assertFalse(message.at_all)

    def test_staggered_failures_escalate_using_active_state(self):
        state = AlertState(fire_after=1, window=1)
        state.ingest([failure("甲")], now=100)
        notes = state.ingest([failure("乙")], now=200)
        groups = render.group_notifications(notes, 2,
                                             active_results=state.active_results(),
                                             mirror_names=["甲", "乙"])
        message = render.render_group(groups[0], enabled_mirrors=2,
                                      mirror_names=["甲", "乙"], at_all=True)
        self.assertIn("P0", message)
        self.assertIn("全部 2 条线路", message)
        self.assertTrue(message.at_all)
        self.assertNotIn("@全体成员", message)
        self.assertEqual(set(message.keys), {failure("甲").key, failure("乙").key})
        self.assertEqual(message.kind, "fire")
        self.assertTrue(render.all_mirrors_down(state.active_results(), ["甲", "乙"]))

    def test_retired_mirror_does_not_count_toward_current_outage(self):
        notes = [Notification("fire", Severity.P1, failure("甲")),
                 Notification("fire", Severity.P1, failure("已退役"))]
        self.assertEqual(render.escalated_severity(notes, 2,
                                                  mirror_names=["甲", "乙"]), Severity.P1)

    def test_reminder_and_recovery_never_ping_everyone(self):
        for kind in ("remind", "recover"):
            notes = [Notification(kind, Severity.P0, failure())]
            self.assertFalse(render.render_group(notes, at_all=True).at_all)


class CoverageRegressionTest(unittest.TestCase):
    def setUp(self):
        self.entries = {"包": FileEntry("包", 32, 16, ["0" * 32, "1" * 32])}

    def test_cartesian_schedule_covers_all_pairs_even_with_common_factors(self):
        rotation = Rotation()
        visited = []
        for _ in range(4):
            mirror, entry, index = rotation.plan_for_mirrors(self.entries, ["甲", "乙"], 1)[0]
            visited.append((mirror, index))
            rotation.mark(entry.name, index, now=100, mirror=mirror)
        self.assertEqual(set(visited), {("甲", 0), ("甲", 1), ("乙", 0), ("乙", 1)})
        report = rotation.coverage(self.entries, now=100, mirror_names=["甲", "乙"])
        self.assertEqual((report.verified, report.total), (4, 4))

    def test_failed_pair_advances_without_claiming_coverage(self):
        rotation = Rotation()
        mirror, entry, index = rotation.plan_for_mirrors(self.entries, ["甲", "乙"], 1)[0]
        rotation.advance(entry.name, index, mirror=mirror)
        self.assertEqual(rotation.coverage(self.entries, now=100,
                                           mirror_names=["甲", "乙"]).verified, 0)
        next_mirror, _, _ = rotation.plan_for_mirrors(self.entries, ["甲", "乙"], 1)[0]
        self.assertNotEqual(next_mirror, mirror)

    def test_new_bytes_invalidate_previous_coverage_after_restart(self):
        rotation = Rotation()
        mirror, entry, index = rotation.plan_for_mirrors(self.entries, ["甲"], 1)[0]
        rotation.mark(entry.name, index, now=100, mirror=mirror)
        rotation = Rotation.from_dict(rotation.to_dict())
        changed = {"包": FileEntry("包", 32, 16, ["2" * 32, "1" * 32])}
        self.assertEqual(rotation.coverage(changed, now=101, mirror_names=["甲"]).verified, 0)

    def test_bad_scheduler_state_is_discarded_per_field(self):
        rotation = Rotation.from_dict({"seen": {"bad": "bad", "infinity": "inf", "valid": 100}})
        self.assertEqual(rotation.seen, {"valid": 100})
        ticker = Ticker.from_dict({"bad": [], "nan": "nan", "valid": 100})
        self.assertEqual(ticker.last, {"valid": 100})
        self.assertTrue(ticker.due("new", 86400, now=0))

    def test_malformed_saved_coverage_identity_does_not_crash(self):
        rotation = Rotation.from_dict({"seen": {'["甲",[],0]': 100}})
        rotation.prune(self.entries, mirror_names=["甲"])
        self.assertEqual(rotation.seen, {})


class ClosedCommandsRegressionTest(unittest.TestCase):
    def test_empty_whitelist_denies_by_default(self):
        self.assertEqual(build([]).refuse_reason("状态", session="陌生群", is_admin=True), "")
        self.assertIsNone(build([], {"respond_anywhere": True}).refuse_reason(
            "状态", session="陌生群", is_admin=False))

    def test_mistyped_flags_and_cooldown_preserve_closed_defaults(self):
        gate = build([], {"respond_anywhere": "false", "heavy_admin_only": [],
                          "cooldown_seconds": float("inf")})
        self.assertFalse(gate.policy.respond_anywhere)
        self.assertTrue(gate.policy.heavy_admin_only)
        self.assertEqual(gate.policy.cooldown_seconds, 60)
        state = AlertState()
        self.assertEqual(state.mute(float("inf"), now=100), 100)


if __name__ == "__main__":
    unittest.main()
