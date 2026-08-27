# -*- coding: utf-8 -*-
"""端到端跑一轮：自发现 → 探 → 判 → 出消息。全程离线，喂假响应。

这几条测试盯的是**整套东西合在一起时的行为**，而不是某个函数的返回值：
一轮下来群里会收到几条消息、是不是该抑制的都抑制了、覆盖率有没有往前走。
"""

import asyncio
import hashlib
import unittest

from tests.fakes import FakeClient, manifest_for, range_response
from watch.config import from_mapping
from watch.runner import Monitor

ENTRY_URL = "https://api.example.test/path/config.json"
A = "https://a.example.test/"
B = "https://b.example.test/"
CHUNK = b"a" * 16
MANIFEST = manifest_for("pack.zip", [CHUNK])

ONLINE_CONFIG = {
    "schema": 1,
    "settings": {"min_speed_kbps": 1},
    "client": {"version": "1.0.170"},
    "mirrors": [
        {"name": "线路甲", "base": A, "enabled": True},
        {"name": "线路乙", "base": B, "enabled": True},
    ],
}


def cfg(**over):
    data = {"entry_url": ENTRY_URL,
            "notify": {"sessions": ["群甲"]},
            "alert": {"fire_after_failures": 1, "fire_window": 1,
                      "recover_after_successes": 1}}
    data.update(over)
    return from_mapping(data)


def healthy_client() -> FakeClient:
    client = FakeClient().json(ENTRY_URL, ONLINE_CONFIG)
    for base in (A, B):
        client.json(base + "manifest.json", MANIFEST)
        client.routes[base + "pack.zip"] = range_response(CHUNK, 0, 15, 16)
    return client


def run(coro):
    return asyncio.run(coro)


class HealthyTest(unittest.TestCase):
    def test_quiet_when_everything_is_fine(self):
        m = Monitor(cfg(), healthy_client())
        out = run(m.run_cycle(now=1000))
        self.assertEqual(out.messages, [], "全绿的一轮不该发任何消息")
        self.assertTrue(all(r.ok for r in out.results), [r.detail for r in out.results])

    def test_chunk_coverage_advances(self):
        m = Monitor(cfg(), healthy_client())
        out = run(m.run_cycle(now=1000))
        self.assertEqual(out.coverage.verified, 1)
        self.assertAlmostEqual(out.coverage.percent, 100.0)

    def test_mirrors_take_turns(self):
        """每轮换一条线路验块：N 条线路 × 每块全验一遍的流量账单会炸。"""
        client = healthy_client()
        m = Monitor(cfg(), client)
        run(m.run_cycle(now=1000))
        run(m.run_cycle(now=2000))
        chunk_calls = [url for kind, url, _ in client.calls if url.endswith("pack.zip")]
        self.assertEqual(chunk_calls, [A + "pack.zip", B + "pack.zip"])


class EntryDownTest(unittest.TestCase):
    def test_entry_failure_stops_the_cycle_and_reports_p0(self):
        client = FakeClient().fail(ENTRY_URL, "连接超时（30s 未完成）")
        m = Monitor(cfg(), client)
        out = run(m.run_cycle(now=1000))
        self.assertEqual(len(out.messages), 1)
        self.assertIn("🔴 P0", out.messages[0])
        self.assertEqual(len(out.results), 1, "入口挂了就别再探下游了")

    def test_downstream_is_not_reported_separately(self):
        """入口拉不到时，各线路失败是必然结果——单独报它只是在刷屏。"""
        client = FakeClient().fail(ENTRY_URL)
        m = Monitor(cfg(), client)
        run(m.run_cycle(now=1000))
        # 入口恢复、但线路仍然坏着：这时候线路那条才该自己报
        client = healthy_client()
        client.routes[A + "manifest.json"] = FakeClient().raw(
            A + "manifest.json", b"", status=502).routes[A + "manifest.json"]
        m.client = client
        out = run(m.run_cycle(now=2000))
        joined = "\n".join(out.messages)
        self.assertIn("清单可达性", joined)


class AllMirrorsDownTest(unittest.TestCase):
    def test_one_grouped_p0_message(self):
        client = healthy_client()
        for base in (A, B):
            client.raw(base + "manifest.json", b"", status=502)
        m = Monitor(cfg(), client)
        out = run(m.run_cycle(now=1000))
        self.assertEqual(len(out.messages), 1, "两条线路同一个环节，应当合成一条")
        msg = out.messages[0]
        self.assertIn("🔴 P0", msg)
        self.assertIn("全部 2 条线路", msg)
        self.assertIn("线路甲", msg)
        self.assertIn("线路乙", msg)
        # 告警自己要把「已经排除了什么」说出来
        self.assertIn("上游线上配置：正常", msg)

    def test_recovery_is_announced(self):
        client = healthy_client()
        for base in (A, B):
            client.raw(base + "manifest.json", b"", status=502)
        m = Monitor(cfg(), client)
        run(m.run_cycle(now=1000))
        m.client = healthy_client()
        out = run(m.run_cycle(now=2000))
        self.assertTrue(out.messages)
        self.assertIn("恢复", out.messages[0])


class CorruptedMirrorTest(unittest.TestCase):
    def test_bad_bytes_on_one_mirror_are_reported(self):
        client = healthy_client()
        client.routes[A + "pack.zip"] = range_response(b"x" * 16, 0, 15, 16)
        m = Monitor(cfg(), client)
        out = run(m.run_cycle(now=1000))
        joined = "\n".join(out.messages)
        self.assertIn("块内容校验", joined)
        self.assertIn("内容不符", joined)
        self.assertEqual(out.coverage.verified, 0, "没验成的块不该计进覆盖率")


class HotUpdateTest(unittest.TestCase):
    def test_skipped_when_not_declared(self):
        """线上没声明版本 json 清单 → 跳过，不猜文件名，也不报警。"""
        m = Monitor(cfg(), healthy_client())
        out = run(m.run_cycle(slow=True, now=1000))
        self.assertEqual(out.messages, [])
        skipped = [r for r in out.results if r.unknown and "watch.version_files" in r.detail]
        self.assertTrue(skipped)

    def test_full_package_check_on_version_change(self):
        online = dict(ONLINE_CONFIG)
        online["watch"] = {"version_files": ["version_a.json"],
                           "packages": {"version_a.json": "hot.zip"}}
        body = b"z" * 64
        client = healthy_client().json(ENTRY_URL, online)
        for base in (A, B):
            client.json(base + "version_a.json",
                        {"version": 7, "size": len(body),
                         "md5": hashlib.md5(body).hexdigest()})
            client.digest_result(base + "hot.zip", body)
        m = Monitor(cfg(), client)
        out = run(m.run_cycle(slow=True, now=1000))
        self.assertEqual(out.messages, [])
        digests = [url for kind, url, _ in client.calls if kind == "digest"]
        self.assertEqual(len(digests), 2, "版本第一次见到，两条线路各核对一次整包")

        # 版本没变、也没到最小间隔 → 不再整包下（几百 MB 的东西不该按轮跑）
        client.calls.clear()
        run(m.run_cycle(slow=True, now=1000 + 60))
        self.assertEqual([url for kind, url, _ in client.calls if kind == "digest"], [])


class PersistenceTest(unittest.TestCase):
    def test_restart_does_not_re_report(self):
        client = healthy_client()
        for base in (A, B):
            client.raw(base + "manifest.json", b"", status=502)
        m = Monitor(cfg(), client)
        run(m.run_cycle(now=1000))
        blob = m.snapshot()

        m2 = Monitor(cfg(), client)
        m2.restore(blob)
        out = run(m2.run_cycle(now=2000))
        self.assertEqual(out.messages, [], "重启后仍在坏的故障不该被当成新故障重报")


if __name__ == "__main__":
    unittest.main()
