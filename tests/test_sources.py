# -*- coding: utf-8 -*-
"""配置源：**「探哪里」从哪来**。

这一层存在的理由：监控不该绑在任何一份特定配置的形状上。老客户端那份
config.json 是某一个客户端的产物，正在开发的网页端就不用它——而监控要探的东西
（线路还活着吗、字节对不对）一个字都没变。
"""

import asyncio
import unittest

from tests.fakes import FakeClient
from watch import sources
from watch.models import Severity

URL = "https://api.example.test/path/lines.json"


def run(coro):
    return asyncio.run(coro)


class EndpointSourceTest(unittest.TestCase):
    def test_only_mirrors_is_required(self):
        """不认文档的身份，只认里面有没有线路表——所以网页端将来暴露一份最小
        JSON 也能直接用，不必长成老客户端那份配置的样子。"""
        client = FakeClient().json(URL, {"mirrors": [
            {"name": "甲", "base": "https://a.example.test/"}]})
        result, disc = run(sources.EndpointSource([URL]).discover(client))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(len(disc.enabled_mirrors), 1)
        # 没有阈值/版本闸门不是故障，只是少两样可探的东西
        self.assertIsNone(disc.threshold("min_speed_kbps"))
        self.assertIsNone(disc.client_version)

    def test_extra_fields_are_used_when_present(self):
        client = FakeClient().json(URL, {
            "mirrors": [{"name": "甲", "base": "https://a.example.test/"}],
            "settings": {"min_speed_kbps": 1200},
            "client": {"version": "1.2.3"},
            "proxy": {"base": "/stream/"},
            "watch": {"version_files": ["v.json"], "packages": {"v.json": "p.zip"}},
        })
        _, disc = run(sources.EndpointSource([URL]).discover(client))
        self.assertEqual(disc.threshold("min_speed_kbps"), 1200.0)
        self.assertEqual(disc.client_version, "1.2.3")
        self.assertEqual(disc.version_files, ["v.json"])
        self.assertEqual(disc.packages, {"v.json": "p.zip"})

    def test_content_and_transport_failures_are_told_apart(self):
        broken = FakeClient().raw(URL, b"{ half", status=200)
        result, disc = run(sources.EndpointSource([URL]).discover(broken))
        self.assertEqual(result.extra.get("reason"), "content")
        self.assertEqual(result.severity, Severity.P0)
        self.assertIsNone(disc)

        gone = FakeClient().fail(URL, "连接超时")
        result, _ = run(sources.EndpointSource([URL]).discover(gone))
        self.assertEqual(result.extra.get("reason"), "unreachable")


class MirrorListSourceTest(unittest.TestCase):
    """完全不依赖任何中心配置的模式。"""

    def _source(self):
        return sources.build({"type": "mirrors", "mirrors": [
            {"name": "甲", "base": "https://a.example.test/"},
            {"name": "乙", "base": "https://b.example.test/"}]})

    def test_no_upstream_means_no_single_point(self):
        src = self._source()
        self.assertFalse(src.has_upstream)
        result, disc = run(src.discover(FakeClient()))
        self.assertEqual(len(disc.enabled_mirrors), 2)
        # 这不是一次探测，只是把本地配置念了一遍：不该混进「全绿」的统计里
        self.assertTrue(result.unknown)

    def test_no_thresholds_means_undecided_not_a_default(self):
        """拿不到线上阈值时保持未判定——写死一个默认值当兜底也算抄第二份
        （铁律 2）。"""
        _, disc = run(self._source().discover(FakeClient()))
        self.assertIsNone(disc.threshold("min_speed_kbps"))
        self.assertIsNone(disc.threshold("stall_seconds"))


class SnapshotTest(unittest.TestCase):
    def test_roundtrip_is_source_agnostic(self):
        """快照是**归一化**的：换一种源之后，突变检测与降级探测照常工作。"""
        _, disc = run(sources.build({"type": "mirrors", "mirrors": [
            {"name": "甲", "base": "https://a.example.test/"}]}).discover(FakeClient()))
        back = sources.Discovered.from_snapshot(disc.snapshot())
        self.assertEqual([m.base for m in back.mirrors],
                         [m.base for m in disc.mirrors])

    def test_junk_snapshot_is_ignored(self):
        self.assertIsNone(sources.Discovered.from_snapshot("不是对象"))


class BuildTest(unittest.TestCase):
    def test_unknown_type_is_rejected_not_guessed(self):
        with self.assertRaises(ValueError):
            sources.build({"type": "随便什么"})
