"""监控编排的行为回归；所有线路与证书响应均在本地构造。"""

import asyncio
import copy
import hashlib
import json
import unittest
from unittest.mock import AsyncMock, patch

from tests.test_runner import A, B, ENTRY_URL, ONLINE_CONFIG, cfg, healthy_client
from tests.fakes import FakeClient, manifest_for
from watch.discovery import parse_manifest
from watch.models import ProbeResult
from watch.runner import Monitor, _majority_manifest
from watch.sources import Discovered, PROBE_SOURCE


class MonitorRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tls = patch("watch.probes.probe_tls_expiry", new=AsyncMock(
            return_value=ProbeResult(True, "证书有效期", "测试证书", "正常")))
        tls.start()
        self.addCleanup(tls.stop)

    async def test_bad_config_is_not_promoted_before_confirmation(self):
        monitor = Monitor(cfg(alert={"fire_after_failures": 2, "fire_window": 3,
                                     "recover_after_successes": 1}), healthy_client())
        await monitor.run_cycle(now=1000)
        accepted = copy.deepcopy(monitor.last_good_snapshot)
        changed = copy.deepcopy(ONLINE_CONFIG)
        changed["mirrors"][1]["enabled"] = False
        changed.pop("settings")
        changed["client"]["version"] = "1.0.1"
        monitor.client.json(ENTRY_URL, changed)
        self.assertEqual((await monitor.run_cycle(now=1300)).messages, [])
        outcome = await monitor.run_cycle(now=1600)
        text = "\n".join(outcome.messages)
        self.assertIn("线路表突变", text)
        self.assertIn("阈值段消失", text)
        self.assertEqual(monitor.last_good_snapshot, accepted)
        monitor.client.json(ENTRY_URL, ONLINE_CONFIG)
        self.assertIn("恢复", "\n".join((await monitor.run_cycle(now=1900)).messages))

    async def test_stale_private_targets_are_filtered_again(self):
        monitor = Monitor(cfg(), FakeClient().fail(ENTRY_URL))
        monitor.last_good_at = 1000
        monitor.last_good_snapshot = {"mirrors": [{"name": "旧线路", "base": "http://127.0.0.1/"}]}
        await monitor.run_cycle(now=1300)
        self.assertEqual([url for kind, url, _ in monitor.client.calls], [ENTRY_URL])

    async def test_fast_state_advances_before_slow_download_completes(self):
        monitor = Monitor(cfg(), healthy_client())
        monitor.client.raw(A + "manifest.json", b"", status=502)
        started, finish = asyncio.Event(), asyncio.Event()

        async def slow(*args):
            started.set()
            await finish.wait()
            return []

        with patch.object(monitor, "_slow_round", side_effect=slow):
            task = asyncio.create_task(monitor.run_cycle(slow=True, now=1000))
            await started.wait()
            self.assertTrue(monitor.state.firing())
            finish.set()
            await task

    async def test_tls_does_not_depend_on_version_files(self):
        monitor = Monitor(cfg(), healthy_client())
        good = ProbeResult(True, "证书有效期", "线路", "正常")
        with patch("watch.probes.probe_tls_expiry", new=AsyncMock(return_value=good)) as tls:
            await monitor.run_cycle(slow=True, now=100000)
            self.assertEqual(tls.await_count, 2)

    async def test_tls_uses_configured_https_port_and_skips_plain_http(self):
        monitor = Monitor(cfg(), healthy_client())
        disc = Discovered.from_snapshot({"mirrors": [
            {"name": "甲", "base": "https://a.example.test:8443/"},
            {"name": "乙", "base": "http://b.example.test/"}]})
        monitor.last_discovered = disc
        with patch("watch.probes.probe_tls_expiry", new=AsyncMock(
                return_value=ProbeResult(True, "证书有效期", "测试证书", "正常"))) as tls:
            await monitor.run_slow_cycle(disc, now=1000)
            tls.assert_awaited_once_with("a.example.test", 8443, now=1000)

    async def test_unknown_chunk_is_not_recorded_as_verified(self):
        monitor = Monitor(cfg(), healthy_client())
        with patch("watch.probes.probe_chunk", new=AsyncMock(return_value=[
                ProbeResult(True, "块内容校验", "甲", "超过本地上限", unknown=True)])):
            out = await monitor.run_cycle(now=1000)
        self.assertEqual(out.coverage.verified, 0)

    async def test_failed_package_confirms_on_fast_interval(self):
        monitor = Monitor(cfg(alert={"fire_after_failures": 2, "fire_window": 3}), healthy_client())
        data = copy.deepcopy(ONLINE_CONFIG)
        data["watch"] = {"version_files": ["version_a.json"],
                         "packages": {"version_a.json": "hot.zip"}}
        monitor.client.json(ENTRY_URL, data)
        for base in (A, B):
            monitor.client.json(base + "version_a.json", {"version": 7, "size": 16, "md5": "a" * 32})
            monitor.client.digest_result(base + "hot.zip", b"bad")
        first = await monitor.run_cycle(slow=True, now=1000)
        self.assertFalse(first.messages)
        self.assertTrue(monitor.hot_failures)
        second = await monitor.run_cycle(slow=True, now=1300)
        self.assertTrue(second.messages)
        self.assertEqual(len([c for c in monitor.client.calls if c[0] == "digest"]), 4)

    async def test_package_recovery_confirms_before_six_hour_interval(self):
        monitor = Monitor(cfg(alert={"fire_after_failures": 2, "fire_window": 3,
                                     "recover_after_successes": 2}), healthy_client())
        data = copy.deepcopy(ONLINE_CONFIG)
        data["watch"] = {"version_files": ["version_a.json"],
                         "packages": {"version_a.json": "hot.zip"}}
        monitor.client.json(ENTRY_URL, data)
        body = b"a" * 16
        for base in (A, B):
            monitor.client.json(base + "version_a.json",
                                {"version": 7, "size": len(body),
                                 "md5": hashlib.md5(body).hexdigest()})
            monitor.client.digest_result(base + "hot.zip", b"bad")
        await monitor.run_cycle(slow=True, now=1000)
        await monitor.run_cycle(slow=True, now=1300)
        for base in (A, B):
            monitor.client.digest_result(base + "hot.zip", body)
        first_good = await monitor.run_cycle(slow=True, now=1600)
        self.assertFalse(first_good.messages)
        self.assertTrue(monitor.hot_failures)
        second_good = await monitor.run_cycle(slow=True, now=1900)
        self.assertIn("恢复", "\n".join(second_good.messages))
        self.assertFalse(monitor.hot_failures)
        self.assertEqual(len([c for c in monitor.client.calls if c[0] == "digest"]), 8)

    async def test_malformed_persisted_fields_do_not_prevent_cycle(self):
        monitor = Monitor(cfg(), healthy_client())
        monitor.restore({"muted_until": "bad", "rotation": {"seen": {"x": []}},
                         "ticker": {"x": {}}, "last_good_config": {"mirrors": 42},
                         "last_good_at": "nan", "last_versions": {"x": "9" * 5000},
                         "hot_failures": {"x": "bad"}})
        self.assertEqual((await monitor.run_cycle(now=1000)).messages, [])

    def test_majority_uses_all_hashes_and_ties_have_no_reference(self):
        old, _ = parse_manifest(json.dumps(manifest_for("part.bin", [b"a", b"b"])).encode())
        new, _ = parse_manifest(json.dumps(manifest_for("part.bin", [b"a", b"c"])).encode())
        self.assertEqual(_majority_manifest({"甲": old, "乙": new, "丙": new}), new)
        self.assertEqual(_majority_manifest({"甲": old, "乙": new}), {})

    def test_all_down_ping_occurs_only_on_transition(self):
        monitor = Monitor(cfg(), healthy_client())
        monitor.last_mirror_names = ["甲", "乙"]
        source = ProbeResult(True, PROBE_SOURCE, "配置源", "正常")

        def bad(mirror, block):
            return ProbeResult(False, "块内容校验", "%s#part[%d]" % (mirror, block),
                               "错误", extra={"mirror": mirror})

        first = monitor._notify([bad("甲", 0), bad("乙", 0)], enabled_mirrors=2,
                                now=1000, entry_result=source)
        self.assertTrue(first[0].at_all)
        second = monitor._notify([bad("甲", 1)], enabled_mirrors=2,
                                 now=1300, entry_result=source)
        self.assertIn("P0", second[0])
        self.assertFalse(second[0].at_all)
        saved = monitor.snapshot()
        restarted = Monitor(cfg(), healthy_client())
        restarted.restore(saved)
        restarted.last_mirror_names = ["甲", "乙"]
        third = restarted._notify([bad("乙", 1)], enabled_mirrors=2,
                                   now=1600, entry_result=source)
        self.assertFalse(third[0].at_all)

    async def test_changing_target_retires_old_fault_and_coverage(self):
        monitor = Monitor(cfg(), healthy_client())
        monitor.client.raw(A + "manifest.json", b"", status=502)
        await monitor.run_cycle(now=1000)
        self.assertTrue(monitor.state.firing())
        changed = copy.deepcopy(ONLINE_CONFIG)
        changed["mirrors"][0]["base"] = "https://replacement.example.test/"
        monitor._sync_targets(Discovered.from_snapshot(changed))
        self.assertFalse([e for e in monitor.state.firing()
                          if (e.result or {}).get("extra", {}).get("mirror") == "线路甲"])
        self.assertEqual(monitor.rotation.seen, {})
