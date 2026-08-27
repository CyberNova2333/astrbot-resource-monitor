# -*- coding: utf-8 -*-
"""测试用的假 HttpClient。

判据层的测试**不联网**（AGENTS.md §3）：真线路会抖，抖一次测试就红一次，
红几次之后没人再看测试结果。所有响应在这里现造。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from watch.http import DigestResult, HttpClient, HttpError, HttpResponse


class FakeClient(HttpClient):
    def __init__(self):
        self.routes: Dict[str, object] = {}
        self.calls: List[tuple] = []

    # ── 布置响应 ────────────────────────────────────────────
    def json(self, url: str, payload, status: int = 200, headers=None):
        self.routes[url] = HttpResponse(
            status=status, headers=headers or {},
            body=json.dumps(payload).encode("utf-8"), url=url, elapsed_ms=10)
        return self

    def raw(self, url: str, body: bytes, status: int = 200, headers=None,
            elapsed_ms: int = 10):
        self.routes[url] = HttpResponse(status=status, headers=headers or {},
                                        body=body, url=url, elapsed_ms=elapsed_ms)
        return self

    def fail(self, url: str, why: str = "连不上：模拟故障"):
        self.routes[url] = HttpError(why)
        return self

    def digest_result(self, url: str, body: bytes, status: int = 200):
        self.routes["digest:" + url] = DigestResult(
            status=status, size=len(body), md5=hashlib.md5(body).hexdigest(),
            elapsed_ms=10)
        return self

    # ── HttpClient 协议 ─────────────────────────────────────
    async def fetch(self, url, *, headers=None, max_bytes=None) -> HttpResponse:
        self.calls.append(("fetch", url, dict(headers or {})))
        route = self.routes.get(url)
        if route is None:
            raise HttpError("连不上：测试里没布置 %s" % url)
        if isinstance(route, HttpError):
            raise route
        if isinstance(route, HttpResponse) and route.status == 206:
            return route
        return route

    async def digest(self, url, *, headers=None) -> DigestResult:
        self.calls.append(("digest", url, dict(headers or {})))
        route = self.routes.get("digest:" + url)
        if route is None:
            raise HttpError("连不上：测试里没布置 digest %s" % url)
        if isinstance(route, HttpError):
            raise route
        return route


def range_response(body: bytes, start: int, end: int, total: int,
                   elapsed_ms: int = 10) -> HttpResponse:
    return HttpResponse(status=206, body=body, elapsed_ms=elapsed_ms,
                        headers={"Content-Range": "bytes %d-%d/%d" % (start, end, total),
                                 "Content-Length": str(len(body))})


def manifest_for(name: str, chunk_bodies: List[bytes]) -> dict:
    size = sum(len(b) for b in chunk_bodies)
    return {name: {"size": size, "chunk_size": len(chunk_bodies[0]),
                   "chunks": [hashlib.md5(b).hexdigest() for b in chunk_bodies]}}
