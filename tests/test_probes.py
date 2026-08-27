# -*- coding: utf-8 -*-
"""探针判据。每个测试对应一种**真实发生过或必然会发生**的故障形态。"""

import asyncio
import hashlib
import unittest

from tests.fakes import FakeClient, manifest_for, range_response
from watch import probes
from watch.models import FileEntry, Mirror, OnlineConfig, Severity

MIRROR = Mirror(name="线路甲", base="https://a.example.test/")
CHUNKS = [b"a" * 16, b"b" * 16, b"c" * 8]
ENTRY = FileEntry(name="pack.zip", size=40, chunk_size=16,
                  chunks=[hashlib.md5(c).hexdigest() for c in CHUNKS])


def run(coro):
    return asyncio.run(coro)


class ChunkProbeTest(unittest.TestCase):
    def test_ok(self):
        client = FakeClient()
        client.routes[MIRROR.url_for("pack.zip")] = range_response(CHUNKS[0], 0, 15, 40)
        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        self.assertTrue(results[0].ok, results[0].detail)
        self.assertEqual(results[0].probe, probes.PROBE_CHUNK)

    def test_last_chunk_range_is_clamped(self):
        """末块要按文件总长截断，否则规矩的服务器回 416，看起来像线路坏了。"""
        self.assertEqual(ENTRY.range_for(2), (32, 39))

    def test_content_mismatch_is_a_failure(self):
        """200 且长度正确、但字节是坏的——这条链路上最常见的真实故障。"""
        client = FakeClient()
        client.routes[MIRROR.url_for("pack.zip")] = range_response(b"x" * 16, 0, 15, 40)
        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        self.assertFalse(results[0].ok)
        self.assertIn("内容不符", results[0].detail)

    def test_status_200_means_range_unsupported(self):
        """服务器忽略 Range 把整包给我们：客户端会退化成整包重下，是故障。"""
        client = FakeClient()
        client.raw(MIRROR.url_for("pack.zip"), b"a" * 40, status=200)
        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        self.assertFalse(results[0].ok)
        self.assertEqual(results[0].probe, probes.PROBE_RANGE)

    def test_total_length_mismatch_means_stale_mirror(self):
        client = FakeClient()
        client.routes[MIRROR.url_for("pack.zip")] = range_response(CHUNKS[0], 0, 15, 999)
        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        self.assertFalse(results[0].ok)
        self.assertIn("旧版本", results[0].detail)

    def test_short_body(self):
        client = FakeClient()
        client.routes[MIRROR.url_for("pack.zip")] = range_response(b"a" * 8, 0, 15, 40)
        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        self.assertFalse(results[0].ok)
        self.assertIn("期望", results[0].detail)

    def test_speed_threshold_comes_from_online_config(self):
        """线上没给 min_speed_kbps 就不判速率——插件里不留第二份阈值。"""
        client = FakeClient()
        client.routes[MIRROR.url_for("pack.zip")] = range_response(CHUNKS[0], 0, 15, 40)
        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        speed = [r for r in results if r.probe == probes.PROBE_SPEED]
        self.assertTrue(speed[0].unknown)

        results = run(probes.probe_chunk(client, MIRROR, ENTRY, 0,
                                         min_speed_kbps=10 ** 9))
        speed = [r for r in results if r.probe == probes.PROBE_SPEED]
        self.assertFalse(speed[0].ok)
        self.assertEqual(speed[0].severity, Severity.P2)

    def test_no_cache_busting_on_chunk(self):
        """块校验要看用户会拿到的那份缓存，所以**不能**带 no-cache。"""
        client = FakeClient()
        client.routes[MIRROR.url_for("pack.zip")] = range_response(CHUNKS[0], 0, 15, 40)
        run(probes.probe_chunk(client, MIRROR, ENTRY, 0))
        _, _, headers = client.calls[0]
        self.assertNotIn("cache-control", {k.lower() for k in headers})


class EntryProbeTest(unittest.TestCase):
    def test_unreachable_entry_is_p0(self):
        client = FakeClient().fail("https://api.example.test/config.json")
        result, cfg = run(probes.probe_entry(client, "https://api.example.test/config.json"))
        self.assertFalse(result.ok)
        self.assertIsNone(cfg)
        self.assertEqual(result.severity, Severity.P0)

    def test_ok(self):
        client = FakeClient().json("https://api.example.test/config.json", {
            "schema": 1,
            "mirrors": [{"name": "甲", "base": "https://a.example.test/", "enabled": True}],
        })
        result, cfg = run(probes.probe_entry(client, "https://api.example.test/config.json"))
        self.assertTrue(result.ok)
        self.assertEqual(len(cfg.enabled_mirrors), 1)


class SanityTest(unittest.TestCase):
    def _cfg(self, raw):
        from watch.discovery import parse_online_config
        import json as _json
        return parse_online_config(_json.dumps(raw).encode())

    def test_no_enabled_mirror_is_p0(self):
        cfg = self._cfg({"mirrors": [{"name": "甲", "base": "https://a.example.test/",
                                      "enabled": False}]})
        results = probes.check_config_sanity(cfg)
        bad = [r for r in results if not r.ok]
        self.assertTrue(bad)
        self.assertEqual(bad[0].severity, Severity.P0)

    def test_version_rollback_is_flagged(self):
        cfg = self._cfg({"client": {"version": "1.0.150"},
                         "mirrors": [{"name": "甲", "base": "https://a.example.test/"}]})
        results = probes.check_config_sanity(cfg, last_client_version="1.0.170")
        rollback = [r for r in results if r.target == "版本闸门"]
        self.assertFalse(rollback[0].ok)
        self.assertIn("回退", rollback[0].detail)

    def test_version_forward_is_fine(self):
        cfg = self._cfg({"client": {"version": "1.0.171"},
                         "mirrors": [{"name": "甲", "base": "https://a.example.test/"}]})
        results = probes.check_config_sanity(cfg, last_client_version="1.0.170")
        self.assertTrue([r for r in results if r.target == "版本闸门"][0].ok)


class VersionAndPackageTest(unittest.TestCase):
    def test_missing_md5_means_hot_update_stalls(self):
        client = FakeClient().json(MIRROR.url_for("version_a.json"),
                                   {"version": 12, "size": 100})
        result, meta = run(probes.probe_version_json(client, MIRROR, "version_a.json"))
        self.assertFalse(result.ok)
        self.assertIn("拒绝更新", result.detail)

    def test_package_md5_mismatch(self):
        from watch.models import VersionMeta
        body = b"z" * 100
        meta = VersionMeta(version=3, size=100, md5="0" * 32)
        client = FakeClient().digest_result(MIRROR.url_for("a.zip"), body)
        result = run(probes.probe_hot_package(client, MIRROR, "a.zip", meta))
        self.assertFalse(result.ok)
        self.assertIn("MD5 不符", result.detail)


class ConsistencyTest(unittest.TestCase):
    def test_minority_mirror_is_named(self):
        good = {"p.zip": FileEntry("p.zip", 40, 16, ["0" * 32] * 3)}
        stale = {"p.zip": FileEntry("p.zip", 20, 16, ["1" * 32] * 2)}
        results = probes.check_manifest_consistency(
            {"甲": good, "乙": dict(good), "丙": stale})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].target, "丙#p.zip")

    def test_two_mirrors_disagreeing_is_unknown(self):
        """只有两条线路且互相矛盾时，监控说不清谁对——说不清就不报警。"""
        a = {"p.zip": FileEntry("p.zip", 40, 16, ["0" * 32] * 3)}
        b = {"p.zip": FileEntry("p.zip", 20, 16, ["1" * 32] * 2)}
        results = probes.check_manifest_consistency({"甲": a, "乙": b})
        self.assertTrue(results and all(r.unknown for r in results))


class CertTest(unittest.TestCase):
    def test_grades(self):
        self.assertEqual(probes.check_cert_days("h.example.test", 40).severity, Severity.P2)
        self.assertTrue(probes.check_cert_days("h.example.test", 40).ok)
        self.assertFalse(probes.check_cert_days("h.example.test", 10).ok)
        self.assertEqual(probes.check_cert_days("h.example.test", 1).severity, Severity.P0)
        self.assertTrue(probes.check_cert_days("h.example.test", None).unknown)


if __name__ == "__main__":
    unittest.main()
