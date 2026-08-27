# -*- coding: utf-8 -*-
"""自发现的解析判据，与客户端同源。"""

import json
import unittest

from watch.discovery import (DiscoveryError, declared_version_files, parse_manifest,
                             parse_online_config, parse_version_meta)


class ManifestParseTest(unittest.TestCase):
    def test_md5_shaped_hashes_only(self):
        """清单里的块哈希是 32 位十六进制 MD5——客户端认包用的就是它。"""
        body = json.dumps({
            "good.zip": {"size": 100, "chunk_size": 50, "chunks": ["a" * 32, "b" * 32]},
            "sha256.zip": {"size": 100, "chunk_size": 50, "chunks": ["c" * 64]},
            "empty.zip": {"size": 100, "chunk_size": 50, "chunks": []},
            "junk.zip": "这不是对象",
        }).encode()
        entries, skipped = parse_manifest(body)
        self.assertEqual(list(entries), ["good.zip"])
        self.assertEqual(sorted(skipped), ["empty.zip", "junk.zip", "sha256.zip"])

    def test_broken_json_is_an_error_not_an_empty_manifest(self):
        with self.assertRaises(DiscoveryError):
            parse_manifest("{ 半截".encode("utf-8"))


class ConfigParseTest(unittest.TestCase):
    def test_mirrors_without_usable_base_are_dropped(self):
        cfg = parse_online_config(json.dumps({"mirrors": [
            {"name": "甲", "base": "https://a.example.test/", "enabled": True},
            {"name": "坏的", "base": "ftp://nope.example.test/"},
            {"name": "缺 base"},
        ]}).encode())
        self.assertEqual([m.name for m in cfg.mirrors], ["甲"])

    def test_thresholds_return_none_when_absent(self):
        """线上没给就是没给——**不返回兜底值**（铁律 2）。"""
        cfg = parse_online_config(json.dumps({"mirrors": [], "settings": {}}).encode())
        self.assertIsNone(cfg.threshold("min_speed_kbps"))
        cfg = parse_online_config(json.dumps(
            {"mirrors": [], "settings": {"min_speed_kbps": 1200}}).encode())
        self.assertEqual(cfg.threshold("min_speed_kbps"), 1200.0)

    def test_watch_declaration_is_optional(self):
        """被监控方没声明要探什么，就不探——不知道时保持沉默。"""
        cfg = parse_online_config(json.dumps({"mirrors": []}).encode())
        self.assertEqual(declared_version_files(cfg), [])
        cfg = parse_online_config(json.dumps(
            {"mirrors": [], "watch": {"version_files": ["version_a.json"]}}).encode())
        self.assertEqual(declared_version_files(cfg), ["version_a.json"])


class VersionMetaTest(unittest.TestCase):
    def test_all_three_fields_required(self):
        self.assertTrue(parse_version_meta(
            json.dumps({"version": 3, "size": 10, "md5": "a" * 32}).encode()).is_valid())
        self.assertFalse(parse_version_meta(
            json.dumps({"version": 3, "size": 10}).encode()).is_valid())


if __name__ == "__main__":
    unittest.main()
