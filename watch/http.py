# -*- coding: utf-8 -*-
"""判据层与网络之间的那层薄壳。

有它是为了**测试能离线跑**：探针只认这里的协议，测试喂一个假实现就行，不需要
起本地服务器，也不会去打真线路（真线路会抖，抖一次测试就红一次）。

壳刻意做得很薄——两个方法：

  fetch(url)    小响应（配置、清单、版本 json、一个块），整块拿进内存，有上限；
  digest(url)   大响应（热更包数百 MB），**边下边算 MD5**，不进内存。

两者都返回「拿到了什么」，而不是抛异常表达故障：HTTP 502 是探针要判的事实，
不是这层的错误。只有**连不上/超时/协议层坏掉**才抛 HttpError。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional


class HttpError(Exception):
    """连不上、超时、TLS 握手失败这类——**没拿到任何 HTTP 语义**的失败。

    消息要写成人能读的，它会直接进告警：`连接超时（15.0s）` 比
    `TimeoutError()` 有用得多。
    """


def _lower(headers: Optional[Mapping[str, str]]) -> Dict[str, str]:
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in dict(headers).items()}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    url: str = ""
    elapsed_ms: int = 0
    truncated: bool = False        # 撞到 max_bytes 被截断

    def __post_init__(self):
        # 头名一律小写化后再存：HTTP 头名不区分大小写，而调用方按小写查。
        # 不在构造时归一，就会出现「明明有 Content-Length 却查不到」这种
        # 只在某些服务器上复现的怪事。
        object.__setattr__(self, "headers", _lower(self.headers))

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    @property
    def content_length(self) -> Optional[int]:
        try:
            return int(self.header("content-length"))
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class DigestResult:
    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    size: int = 0
    md5: str = ""
    elapsed_ms: int = 0

    def __post_init__(self):
        object.__setattr__(self, "headers", _lower(self.headers))

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)


class HttpClient:
    """协议（鸭子类型即可，不强制继承）。真实现见 AiohttpClient。"""

    async def fetch(self, url: str, *, headers: Optional[Mapping[str, str]] = None,
                    max_bytes: Optional[int] = None) -> HttpResponse:
        raise NotImplementedError

    async def digest(self, url: str, *,
                     headers: Optional[Mapping[str, str]] = None) -> DigestResult:
        raise NotImplementedError


class AiohttpClient(HttpClient):
    """aiohttp 实现。**aiohttp 只在这里 import**——判据层其余部分不认识它。

    三个刻意的选择：

      · `Accept-Encoding: identity`：让服务器别压缩。压缩过的字节算出来的 MD5
        跟清单对不上是必然的，而那不是故障；
      · 不自动跟随重定向到别的主机时也照样记录——重定向本身是要看见的事实；
      · User-Agent 由配置给，且**与客户端不同**：混在一起以后就没法按 UA 把
        监控流量从访问日志里摘出去。
    """

    def __init__(self, user_agent: str, timeout_seconds: float = 30.0,
                 max_body_bytes: int = 4 * 1024 * 1024):
        try:
            import aiohttp                                    # noqa: F401
        except ImportError as e:                              # pragma: no cover
            raise HttpError(
                "缺少 aiohttp。它是 AstrBot 运行环境里本来就有的依赖；"
                "独立跑本插件时 pip install aiohttp") from e
        self._aiohttp = __import__("aiohttp")
        self._ua = user_agent
        self._timeout = timeout_seconds
        self._max_body = max_body_bytes
        self._session = None

    async def _ensure(self):
        if self._session is None or self._session.closed:
            aiohttp = self._aiohttp
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers={"User-Agent": self._ua,
                         "Accept-Encoding": "identity"},
                auto_decompress=False,
            )
        return self._session

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def fetch(self, url, *, headers=None, max_bytes=None) -> HttpResponse:
        session = await self._ensure()
        cap = max_bytes or self._max_body
        t0 = time.monotonic()
        try:
            async with session.get(url, headers=dict(headers or {})) as resp:
                buf = bytearray()
                truncated = False
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > cap:
                        truncated = True
                        break
                return HttpResponse(
                    status=resp.status, headers=_lower(resp.headers),
                    body=bytes(buf[:cap]), url=str(resp.url),
                    elapsed_ms=_ms(t0), truncated=truncated)
        except Exception as e:
            raise HttpError(_why(e, self._timeout)) from e

    async def digest(self, url, *, headers=None) -> DigestResult:
        session = await self._ensure()
        t0 = time.monotonic()
        try:
            async with session.get(url, headers=dict(headers or {})) as resp:
                md = hashlib.md5()
                size = 0
                async for chunk in resp.content.iter_chunked(1 << 20):
                    md.update(chunk)
                    size += len(chunk)
                return DigestResult(status=resp.status, headers=_lower(resp.headers),
                                    size=size, md5=md.hexdigest(), elapsed_ms=_ms(t0))
        except Exception as e:
            raise HttpError(_why(e, self._timeout)) from e


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _why(exc: Exception, timeout: float) -> str:
    """把异常翻成一句人话。告警里要出现的是这句，不是 traceback。"""
    name = type(exc).__name__
    if "Timeout" in name:
        return "连接超时（%.0fs 未完成）" % timeout
    if "ClientConnectorCertificate" in name or "SSL" in name.upper():
        return "TLS 握手失败：%s" % exc
    if "ClientConnector" in name or "Connection" in name:
        return "连不上：%s" % exc
    return "%s: %s" % (name, exc)


def kbps(byte_count: int, elapsed_ms: int) -> float:
    """把一次传输折成 kbps。与线上配置里的 min_speed_kbps 同口径（千比特/秒）。"""
    seconds = max(elapsed_ms, 1) / 1000.0
    return byte_count * 8 / 1000.0 / seconds
