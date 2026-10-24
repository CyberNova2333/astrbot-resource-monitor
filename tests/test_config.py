# -*- coding: utf-8 -*-
"""本地配置：**没有默认入口**，其余旋钮才有默认值。"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from watch.config import ConfigError, from_file, from_mapping, load

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

    def test_monitor_numeric_knobs_reject_nonfinite_and_unrepresentable_values(self):
        for value_name, value in (("nan", float("nan")), ("inf", float("inf")),
                                  ("negative_inf", -float("inf")), ("huge", 10 ** 10000)):
            for section, key in (("schedule", "interval_fast_seconds"),
                                 ("runtime", "http_timeout_seconds"),
                                 ("alert", "remind_every_hours")):
                with self.subTest(value=value_name, section=section):
                    with self.assertRaises(ConfigError):
                        from_mapping(dict(BASE, **{section: {key: value}}))

    def test_wrong_type_monitor_knobs_keep_existing_defaults(self):
        cfg = from_mapping(dict(BASE, schedule={"interval_fast_seconds": "稍后"},
                                runtime={"http_timeout_seconds": {}}))
        self.assertEqual(cfg.schedule.interval_fast_seconds, 300)
        self.assertEqual(cfg.runtime.http_timeout_seconds, 30)

    def test_url_parser_errors_are_configuration_errors(self):
        for url in ("https://[broken.example.test/", "https://a.example.test:wrong/",
                    "https://a.example.test:99999/", "https://:443/",
                    "https://a.example.test/a b"):
            with self.subTest(url=url), self.assertRaises(ConfigError):
                from_mapping({"entry_url": url})


class SourceShapeTest(unittest.TestCase):
    def test_endpoint_and_legacy_single_url_forms_remain_compatible(self):
        endpoint = from_mapping({"source": {"type": "endpoint", "urls": BASE["entry_url"]}})
        self.assertEqual(endpoint.entry_urls, [BASE["entry_url"]])
        legacy = from_mapping(dict(BASE, entry_urls="https://backup.example.test/config.json"))
        self.assertEqual(len(legacy.entry_urls), 2)
        self.assertEqual(legacy.entry_url, BASE["entry_url"])

    def test_webui_lines_and_static_numeric_strings_remain_compatible(self):
        cfg = from_mapping({"mirrors": ["甲=https://a.example.test/", "https://b.example.test/"],
                            "version_files": ["version.json"],
                            "packages": {"version.json": "package.zip"}})
        self.assertEqual(cfg.source["mirrors"][0]["name"], "甲")
        self.assertEqual(cfg.source["version_files"], ["version.json"])
        cfg = from_mapping({"source": {"type": "mirrors", "mirrors": [
            {"name": "甲", "base": "https://a.example.test/", "weight": "3",
             "chunks": "2", "enabled": False}]}})
        mirror = cfg.source["mirrors"][0]
        self.assertEqual((mirror["weight"], mirror["chunks"], mirror["enabled"]), (3, 2, False))
        self.assertEqual(cfg.source["version_files"], [])
        self.assertEqual(cfg.source["packages"], {})

    def test_invalid_source_containers_fail_explicitly(self):
        sources = [42, {"type": []}, {"type": "endpoint", "urls": 42},
                   {"type": "endpoint", "urls": [42]},
                   {"type": "mirrors", "mirrors": 42},
                   {"type": "mirrors", "mirrors": ["https://a.example.test/"]}]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ConfigError):
                from_mapping({"source": source})
        for key in ("entry_url", "entry_urls", "mirrors"):
            with self.subTest(key=key), self.assertRaises(ConfigError):
                from_mapping(dict(BASE, **{key: 42}))

    def test_invalid_mirror_field_types_fail_without_coercion(self):
        for key, value in (("enabled", "false"), ("weight", "heavy"),
                           ("chunks", []), ("weight", True), ("chunks", 1.5),
                           ("weight", float("inf")), ("chunks", -1), ("name", 42),
                           ("base", "https://[broken.example.test/")):
            mirror = {"name": "甲", "base": "https://a.example.test/"}
            mirror[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                from_mapping({"source": {"type": "mirrors", "mirrors": [mirror]}})

    def test_version_files_and_packages_are_not_reinterpreted_as_other_shapes(self):
        for key, value in (("version_files", "version.json"), ("version_files", [42]),
                           ("packages", []), ("packages", {"version.json": 42})):
            source = {"type": "mirrors", "mirrors": [{"base": "https://a.example.test/"}],
                      key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                from_mapping({"source": source})


class FallbackTest(unittest.TestCase):
    def test_malformed_webui_input_falls_back_to_local_file(self):
        invalid = [{"entry_url": "https://[broken.example.test/"},
                   {"source": {"type": "endpoint", "urls": 42}},
                   dict(BASE, runtime={"http_timeout_seconds": float("inf")}),
                   dict(BASE, schedule={"interval_fast_seconds": float("nan")}),
                   {"source": {"type": "mirrors", "mirrors": [
                       {"base": "https://a.example.test/", "enabled": "false"}]}}]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            with open(path, "w", encoding="utf-8") as output:
                json.dump(BASE, output)
            for index, data in enumerate(invalid):
                with self.subTest(case=index):
                    self.assertEqual(load(data, path).entry_url, BASE["entry_url"])

    def test_local_file_io_failure_is_a_configuration_error(self):
        for error in (PermissionError("不可读"), FileNotFoundError("不存在"), OSError("读取失败")):
            with self.subTest(error=type(error).__name__):
                with patch("builtins.open", side_effect=error), self.assertRaises(ConfigError):
                    from_file("config.json")

    def test_invalid_json_remains_a_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            with open(path, "w", encoding="utf-8") as output:
                output.write("{")
            with self.assertRaises(ConfigError):
                from_file(path)


if __name__ == "__main__":
    unittest.main()
