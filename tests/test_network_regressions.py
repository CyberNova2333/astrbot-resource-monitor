# -*- coding: utf-8 -*-
"""网络边界与异常输入的离线回归；不向真实线路发送请求。"""

import asyncio
import hashlib
import importlib.util
import ipaddress
import json
import socket
import unittest
from unittest.mock import AsyncMock, patch

from tests.fakes import FakeClient, range_response
from watch import discovery, probes
from watch.http import (AiohttpClient, HttpError, HttpResponse, PublicResolver,
                        require_public_address, validate_public_url)
from watch.models import FileEntry, Mirror, entry_fingerprint, manifest_fingerprint
from watch.sources import Discovered, EndpointSource
from watch.state import AlertState


MIRROR = Mirror("线路甲", "https://a.example.test/")
ENTRY_URL = "https://config.example.test/lines.json"


def run(coro):
    return asyncio.run(coro)


class ParsingRegressionTest(unittest.TestCase):
    def test_invalid_mirror_container_becomes_content_failure(self):
        for value in (42, "invalid", {}):
            client = FakeClient().json(ENTRY_URL, {"mirrors": value})
            result, disc = run(EndpointSource([ENTRY_URL]).discover(client))
            self.assertFalse(result.ok)
            self.assertEqual(result.extra["reason"], "content")
            self.assertIsNone(disc)

    def test_one_bad_mirror_does_not_discard_valid_records(self):
        for value in ("high", [], float("inf"), True, 1.25):
            client = FakeClient().json(ENTRY_URL, {"mirrors": [
                {"name": "坏记录", "base": "https://bad.example.test/", "weight": value},
                {"name": MIRROR.name, "base": MIRROR.base},
            ]})
            result, disc = run(EndpointSource([ENTRY_URL]).discover(client))
            self.assertFalse(result.ok)
            self.assertEqual([m.name for m in disc.mirrors], [MIRROR.name])

    def test_bad_manifest_records_are_isolated(self):
        good = {"size": 32, "chunk_size": 16, "chunks": ["a" * 32, "b" * 32]}
        body = {"good.bin": good}
        for index, value in enumerate(("oops", {}, float("inf"), True, 1.25, 10 ** 400)):
            body["bad%d.bin" % index] = dict(good, size=value)
        entries, skipped = discovery.parse_manifest(json.dumps(body).encode())
        self.assertEqual(list(entries), ["good.bin"])
        self.assertEqual(len(skipped), 6)

    def test_chunk_count_must_cover_exactly_the_file(self):
        self.assertFalse(FileEntry("x", 32, 16, ["a" * 32]).is_valid())
        self.assertFalse(FileEntry("x", 16, 16, ["a" * 32] * 2).is_valid())
        self.assertTrue(FileEntry("x", 17, 16, ["a" * 32] * 2).is_valid())

    def test_nested_json_becomes_discovery_error(self):
        body = ("[" * 2000 + "0" + "]" * 2000).encode()
        for parser in (discovery.parse_online_config, discovery.parse_manifest,
                       discovery.parse_version_meta):
            with self.assertRaises(discovery.DiscoveryError):
                parser(body)

    def test_invalid_version_numbers_cannot_escape_probe(self):
        for value in (float("inf"), {}, True, 2.5, 10 ** 400):
            client = FakeClient().json(MIRROR.url_for("v.json"),
                                       {"version": value, "size": 16, "md5": "a" * 32})
            result, _ = run(probes.probe_version_json(client, MIRROR, "v.json"))
            self.assertFalse(result.ok)

    def test_huge_version_size_cannot_overflow_human_readable_units(self):
        client = FakeClient().json(MIRROR.url_for("v.json"),
                                   {"version": 1, "size": 10 ** 400, "md5": "a" * 32})
        result, _ = run(probes.probe_version_json(client, MIRROR, "v.json"))
        self.assertTrue(result.counts_as_failure())

    def test_snapshot_bad_fields_are_discarded(self):
        self.assertIsNone(Discovered.from_snapshot({"mirrors": 42}))
        disc = Discovered.from_snapshot({"mirrors": [
            {"base": MIRROR.base, "weight": "bad"}], "version_files": 42,
            "client_version": [], "proxy_base": {}})
        self.assertEqual(disc.mirrors, [])
        self.assertEqual(disc.version_files, [])
        self.assertIsNone(disc.client_version)
        self.assertIsNone(disc.proxy_base)

    def test_truncated_metadata_is_never_accepted(self):
        client = FakeClient()
        client.routes[MIRROR.url_for("manifest.json")] = HttpResponse(
            200, body=b'{"x":{"size":1,"chunk_size":1,"chunks":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}}',
            truncated=True)
        result, entries = run(probes.probe_manifest(client, MIRROR))
        self.assertFalse(result.ok)
        self.assertEqual(entries, {})
        client.routes[MIRROR.url_for("v.json")] = HttpResponse(
            200, body=b'{"version":1,"size":1,"md5":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}',
            truncated=True)
        result, _ = run(probes.probe_version_json(client, MIRROR, "v.json"))
        self.assertFalse(result.ok)


class ProbeRegressionTest(unittest.TestCase):
    def test_remote_chunk_size_cannot_raise_memory_budget(self):
        client = FakeClient()
        entry = FileEntry("huge.bin", 1 << 40, 1 << 40, ["a" * 32])
        results = run(probes.probe_chunk(client, MIRROR, entry, 0))
        self.assertTrue(all(r.unknown for r in results))
        self.assertEqual(client.calls, [])

    def test_complete_fingerprints_detect_later_block_changes(self):
        before = FileEntry("x", 32, 16, ["a" * 32, "b" * 32])
        after = FileEntry("x", 32, 16, ["a" * 32, "c" * 32])
        self.assertNotEqual(entry_fingerprint(before), entry_fingerprint(after))
        self.assertNotEqual(manifest_fingerprint({"x": before}),
                            manifest_fingerprint({"x": after}))
        results = probes.check_manifest_consistency(
            {"旧": {"x": before}, "新甲": {"x": after}, "新乙": {"x": after}})
        self.assertEqual([r.target for r in results if r.counts_as_failure()], ["旧#x"])

    def test_consistency_recovery_uses_same_key(self):
        before = {"x": FileEntry("x", 16, 16, ["a" * 32])}
        after = {"x": FileEntry("x", 16, 16, ["b" * 32])}
        state = AlertState(fire_after=1, window=1, recover_after=1)
        failed = probes.check_manifest_consistency({"甲": before, "乙": after, "丙": after})
        state.ingest(failed, now=1)
        recovered = probes.check_manifest_consistency({"甲": after, "乙": after, "丙": after})
        notes = state.ingest(recovered, now=2)
        self.assertEqual([(n.kind, n.result.target) for n in notes], [("recover", "甲#x")])

    def test_plurality_is_not_a_majority(self):
        entries = [{"x": FileEntry("x", 16, 16, [h * 32])} for h in "abc"]
        results = probes.check_manifest_consistency(
            {"甲": entries[0], "乙": entries[0], "丙": entries[1], "丁": entries[2]})
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.unknown for r in results))

    def test_range_recovery_is_independent_of_chunk_hash(self):
        entry = FileEntry("x", 16, 16, [hashlib.md5(b"a" * 16).hexdigest()])
        client = FakeClient().raw(MIRROR.url_for("x"), b"a" * 16)
        state = AlertState(fire_after=1, window=1, recover_after=1)
        state.ingest(run(probes.probe_chunk(client, MIRROR, entry, 0)), now=1)
        client.routes[MIRROR.url_for("x")] = range_response(b"b" * 16, 0, 15, 16)
        results = run(probes.probe_chunk(client, MIRROR, entry, 0))
        notes = state.ingest(results, now=2)
        self.assertTrue(any(n.kind == "recover" and n.result.probe == probes.PROBE_RANGE
                            for n in notes))
        self.assertTrue(any(r.counts_as_failure() and r.probe == probes.PROBE_CHUNK
                            for r in results))
        self.assertTrue(all(r.extra["mirror"] == MIRROR.name for r in results))

    def test_content_range_must_match_requested_offsets(self):
        body = b"a" * 16
        entry = FileEntry("x", 32, 16, [hashlib.md5(body).hexdigest()] * 2)
        client = FakeClient()
        client.routes[MIRROR.url_for("x")] = range_response(body, 16, 31, 32)
        results = run(probes.probe_chunk(client, MIRROR, entry, 0))
        self.assertTrue(results[0].counts_as_failure())

    def test_oversized_content_range_integer_is_a_probe_failure(self):
        body = b"a" * 16
        entry = FileEntry("x", 16, 16, [hashlib.md5(body).hexdigest()])
        client = FakeClient().raw(MIRROR.url_for("x"), body, status=206,
                                  headers={"Content-Range": "bytes 0-15/" + "9" * 5000})
        result = run(probes.probe_chunk(client, MIRROR, entry, 0))[0]
        self.assertTrue(result.counts_as_failure())


class PublicNetworkBoundaryTest(unittest.TestCase):
    def test_literal_and_malformed_targets_are_blocked(self):
        for url in ("http://127.0.0.1/", "http://[::1]/", "http://localhost./",
                    "http://local.localhost/", "http://10.1.2.3/", "file:///x",
                    "https://a.example.test:invalid/", "http://[::ffff:127.0.0.1]/"):
            with self.subTest(url=url), self.assertRaises(HttpError):
                validate_public_url(url)
        self.assertEqual(validate_public_url(MIRROR.base), "a.example.test")

    def test_legacy_numeric_addresses_do_not_depend_on_connector_behavior(self):
        for host in ("127.1", "2130706433", "0177.0.0.1", "0x7f000001", "0x7f.1", "0"):
            with self.subTest(host=host), self.assertRaises(HttpError):
                validate_public_url("http://%s/" % host)
        self.assertEqual(validate_public_url("https://12.example.test/"), "12.example.test")
        self.assertEqual(validate_public_url("https://0xabc.example.test/"), "0xabc.example.test")

    def test_non_string_url_is_a_transport_error(self):
        for url in (None, b"https://a.example.test/", {}, 123):
            with self.assertRaises(HttpError):
                validate_public_url(url)

    def test_unicode_host_cannot_normalize_into_private_numeric_address(self):
        for url in ("http://１２７.０.０.１/", "http://１２７。０。０。１/",
                    "http://ⓛⓞⓒⓐⓛⓗⓞⓢⓣ/", "http://０ｘ７ｆ０００００１/"):
            with self.subTest(url=url), self.assertRaises(HttpError):
                validate_public_url(url)
        self.assertTrue(validate_public_url("https://例子.example.test/").endswith(".example.test"))

    def test_transition_addresses_validate_embedded_ipv4_on_older_python(self):
        # 模拟旧标准库把过渡段认作公网，仍不能借此包裹回环 IPv4。
        with patch.object(ipaddress.IPv6Address, "is_global", property(lambda _: True)), \
                patch.object(ipaddress.IPv6Address, "is_reserved", property(lambda _: False)):
            for host in ("2002:7f00:1::", "::ffff:127.0.0.1",
                         "2001:0:808:808:0:ffff:80ff:fffe"):
                with self.subTest(host=host), self.assertRaises(HttpError):
                    require_public_address(host)

    def test_dns_answer_is_checked_before_it_can_reach_connector(self):
        resolver = AsyncMock()
        resolver.resolve.return_value = [{"host": "127.0.0.1", "port": 443}]
        with self.assertRaises(HttpError):
            run(PublicResolver(resolver).resolve("a.example.test", 443))
        resolver.resolve.assert_awaited_once()

    def test_resolver_returns_the_same_validated_records(self):
        # 数值地址只是离线解析器的返回值，测试不会建立连接。
        records = [{"host": str(ipaddress.ip_address(0x08080808)), "port": 443}]
        resolver = AsyncMock()
        resolver.resolve.return_value = records
        self.assertIs(run(PublicResolver(resolver).resolve("a.example.test", 443)), records)
        resolver.resolve.assert_awaited_once()

    def test_tls_probe_cannot_connect_to_private_resolution(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch("socket.getaddrinfo", return_value=addresses), \
                patch("socket.socket") as connect:
            with self.assertRaises(HttpError):
                probes._tls_not_after("a.example.test", 443)
            connect.assert_not_called()

    def test_tls_custom_port_has_distinct_state_identity(self):
        async def expires(host, port):
            self.assertEqual(port, 8443)
            return 50 * 86400
        result = run(probes.probe_tls_expiry("a.example.test", 8443, now=0,
                                             fetch_not_after=expires))
        self.assertEqual(result.target, "a.example.test:8443")
        result = run(probes.probe_tls_expiry("::1", 8443, now=0, fetch_not_after=expires))
        self.assertEqual(result.target, "[::1]:8443")

    def test_tls_connection_uses_checked_address_and_original_sni(self):
        address = (str(ipaddress.ip_address(0x08080808)), 8443)
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)]
        with patch("socket.getaddrinfo", return_value=records) as lookup, \
                patch("socket.socket") as connect, \
                patch("ssl.create_default_context") as context:
            context.return_value.wrap_socket.return_value.__enter__.return_value.getpeercert.return_value = {}
            probes._tls_not_after("a.example.test", 8443)
            lookup.assert_called_once_with("a.example.test", 8443, type=socket.SOCK_STREAM)
            sock = connect.return_value.__enter__.return_value
            sock.connect.assert_called_once_with(address)
            context.return_value.wrap_socket.assert_called_once_with(sock, server_hostname="a.example.test")

    def test_tls_dns_delay_cannot_leave_a_late_connection(self):
        address = (str(ipaddress.ip_address(0x08080808)), 443)
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)]
        with patch("socket.getaddrinfo", return_value=records), \
                patch("socket.socket") as connect, \
                patch("watch.probes.time.monotonic", side_effect=[0.0, 16.0]):
            with self.assertRaises(TimeoutError):
                probes._tls_not_after("a.example.test", 443)
            connect.return_value.__enter__.return_value.connect.assert_not_called()


class _Content:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, size):
        yield self.body


class _Response:
    def __init__(self, url, body=b"", status=200, headers=None):
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.content = _Content(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Session:
    closed = False

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)

    async def close(self):
        self.closed = True


@unittest.skipUnless(importlib.util.find_spec("aiohttp"), "独立离线环境未安装 aiohttp")
class AiohttpBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_unicode_numeric_host_is_rejected_before_request(self):
        for method in ("fetch", "digest"):
            client = AiohttpClient("offline-test")
            client._session = _Session()
            try:
                with self.assertRaises(HttpError):
                    await getattr(client, method)("http://１２７。０。０。１/", max_bytes=100)
                self.assertEqual(client._session.calls, [])
            finally:
                await client.close()

    async def test_fetch_and_digest_reject_private_redirects(self):
        for method in ("fetch", "digest"):
            client = AiohttpClient("offline-test")
            session = _Session(_Response(MIRROR.base, status=302,
                                        headers={"Location": "http://127.0.0.1/private"}))
            client._session = session
            try:
                with self.assertRaises(HttpError):
                    await getattr(client, method)(MIRROR.base, max_bytes=100)
                self.assertEqual(len(session.calls), 1)
                self.assertFalse(session.calls[0][1]["allow_redirects"])
            finally:
                await client.close()

    async def test_public_redirect_and_relative_location_remain_supported(self):
        client = AiohttpClient("offline-test")
        session = _Session(_Response(MIRROR.base, status=302, headers={"Location": "/new"}),
                           _Response(MIRROR.url_for("new"), body=b"ok"))
        client._session = session
        try:
            result = await client.fetch(MIRROR.base)
            self.assertEqual(result.body, b"ok")
            self.assertEqual(str(session.calls[1][0]), MIRROR.url_for("new"))
        finally:
            await client.close()

    async def test_caller_cannot_override_hard_buffer_limit(self):
        client = AiohttpClient("offline-test")
        client._session = _Session(_Response(MIRROR.base, body=b"a" * 16))
        try:
            with patch("watch.http.MAX_BUFFER_BYTES", 8):
                result = await client.fetch(MIRROR.base, max_bytes=1 << 40)
            self.assertEqual(len(result.body), 8)
            self.assertTrue(result.truncated)
        finally:
            await client.close()

    async def test_real_connector_rejects_private_dns_before_socket_creation(self):
        client = AiohttpClient("offline-test")
        try:
            await client._ensure()
            resolver = AsyncMock()
            resolver.resolve.return_value = [{"hostname": "a.example.test", "host": "127.0.0.1",
                                              "port": 443, "family": socket.AF_INET,
                                              "proto": socket.IPPROTO_TCP, "flags": 0}]
            client._resolver._resolver = resolver
            with patch.object(client._session.connector, "_wrap_create_connection",
                              new_callable=AsyncMock) as connect:
                with self.assertRaises(HttpError):
                    await client.fetch(MIRROR.base)
                connect.assert_not_awaited()
        finally:
            await client.close()
