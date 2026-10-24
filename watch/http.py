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
import ipaddress
import re
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional
from urllib.parse import urljoin, urlsplit

# 监控自身的资源边界，不能由远端清单里的块大小抬高。
MAX_BUFFER_BYTES = 64 * 1024 * 1024
MAX_REDIRECTS = 5
_NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}", re.I)


class HttpError(Exception):
    """连不上、超时、TLS 握手失败这类——**没拿到任何 HTTP 语义**的失败。

    消息要写成人能读的，它会直接进告警：`连接超时（15.0s）` 比
    `TimeoutError()` 有用得多。
    """


def require_public_address(host: str) -> None:
    """检查连接将实际使用的数值地址，不再另做一次存在竞态的预解析。"""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise HttpError("解析结果不是有效的数值地址") from exc
    if isinstance(address, ipaddress.IPv6Address):
        # 不依赖不同 Python 小版本对过渡地址段的分类，内嵌地址也必须可公开连接。
        for embedded in (address.ipv4_mapped, address.sixtofour, *(address.teredo or ())):
            if embedded is not None:
                require_public_address(str(embedded))
    if (not address.is_global or address.is_multicast or address.is_reserved
            or getattr(address, "scope_id", None)):
        raise HttpError("拒绝连接非公网地址")


def validate_public_url(url: str) -> str:
    """先挡住字面量内网地址；域名由连接器解析并校验实际地址。"""
    if not isinstance(url, str):
        raise HttpError("HTTP 地址必须是字符串")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise HttpError("不是有效的 HTTP 地址") from exc
    if (parsed.scheme not in ("http", "https") or not host
            or parsed.username is not None or parsed.password is not None
            or (port is not None and port <= 0)):
        raise HttpError("仅允许不含凭证的 HTTP 地址")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise HttpError("主机名不能规范化") from exc
    normalized = host.rstrip(".").lower()
    if (normalized == "localhost" or normalized.endswith(".localhost")
            or normalized == "localhost.localdomain" or "%" in host):
        raise HttpError("拒绝连接本机地址")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or _NUMERIC_HOST.fullmatch(normalized):
            # 某些连接器把整数、八进制和缩写当作 IP，直接连接而不经过 resolver。
            raise HttpError("拒绝非规范的数值地址")
    else:
        require_public_address(host)
    return host


class PublicResolver:
    """把经过检查的同一批地址交给连接器，避免检查后再次 DNS 查询。"""

    def __init__(self, resolver):
        self._resolver = resolver

    async def resolve(self, host, port=0, family=socket.AF_INET):
        addresses = await self._resolver.resolve(host, port, family=family)
        if not addresses:
            raise HttpError("DNS 没有返回可连接地址")
        for item in addresses:
            require_public_address(item["host"])
        return addresses

    async def close(self):
        await self._resolver.close()


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
    overflow: bool = False        # 撞到字节上限，提前停了

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
                     headers: Optional[Mapping[str, str]] = None,
                     max_bytes: Optional[int] = None) -> DigestResult:
        raise NotImplementedError


class AiohttpClient(HttpClient):
    """aiohttp 实现。**aiohttp 只在这里 import**——判据层其余部分不认识它。

    三个刻意的选择：

      · `Accept-Encoding: identity`：让服务器别压缩。压缩过的字节算出来的 MD5
        跟清单对不上是必然的，而那不是故障；
      · 每次重定向重新检查地址，DNS 结果直接用于连接，不允许转进内网；
      · User-Agent 由配置给，且**与客户端不同**：混在一起以后就没法按 UA 把
        监控流量从访问日志里摘出去。
    """

    def __init__(self, user_agent: str, timeout_seconds: float = 30.0,
                 max_body_bytes: int = 4 * 1024 * 1024,
                 stream_timeout_seconds: float = 1800.0):
        try:
            import aiohttp                                    # noqa: F401
        except ImportError as e:                              # pragma: no cover
            raise HttpError(
                "缺少 aiohttp。它是 AstrBot 运行环境里本来就有的依赖；"
                "独立跑本插件时 pip install aiohttp") from e
        self._aiohttp = __import__("aiohttp")
        from yarl import URL
        self._url_type = URL
        self._ua = user_agent
        self._timeout = timeout_seconds
        # 整包核对是几百 MB，用小响应那个超时必然拉不完——那会把「包很大」
        # 误报成「线路坏了」，而误报的监控没几天就没人看了。
        self._stream_timeout = max(timeout_seconds, stream_timeout_seconds)
        self._max_body = min(MAX_BUFFER_BYTES, max(1, int(max_body_bytes)))
        self._session = None
        self._resolver = None

    async def _ensure(self):
        if self._session is None or self._session.closed:
            aiohttp = self._aiohttp
            self._resolver = PublicResolver(aiohttp.resolver.DefaultResolver())
            self._session = aiohttp.ClientSession(
                # 会话级只设连接与首字节超时；整体时长按请求给（小响应 30s、
                # 整包核对半小时），否则两者只能二选一。
                timeout=aiohttp.ClientTimeout(total=None,
                                              connect=self._timeout,
                                              sock_read=self._timeout),
                headers={"User-Agent": self._ua,
                         "Accept-Encoding": "identity"},
                auto_decompress=False,
                connector=aiohttp.TCPConnector(resolver=self._resolver),
                # 探针不需要服务端会话，禁用 Cookie 避免跨请求状态和额外解析面。
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
            )
        return self._session

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        if self._resolver is not None:
            await self._resolver.close()
            self._resolver = None

    @asynccontextmanager
    async def _get(self, url, *, headers, timeout):
        session = await self._ensure()
        deadline = time.monotonic() + timeout
        for hop in range(MAX_REDIRECTS + 1):
            validate_public_url(url)
            # 校验真正传给连接器的规范化地址；Unicode 域名可能归一成数值 IP。
            url = self._url_type(url)
            validate_public_url(str(url))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HttpError("请求及重定向超过总时限")
            async with session.get(
                    url, headers=dict(headers or {}), allow_redirects=False,
                    timeout=self._aiohttp.ClientTimeout(
                        total=remaining, connect=self._timeout,
                        sock_read=self._timeout)) as resp:
                if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    if hop == MAX_REDIRECTS:
                        raise HttpError("重定向次数超过本地上限")
                    url = urljoin(str(resp.url), resp.headers["Location"])
                    continue
                yield resp
                return

    async def fetch(self, url, *, headers=None, max_bytes=None) -> HttpResponse:
        cap = min(MAX_BUFFER_BYTES, max(1, int(max_bytes))) if max_bytes is not None else self._max_body
        t0 = time.monotonic()
        try:
            async with self._get(url, headers=headers, timeout=self._timeout) as resp:
                buf = bytearray()
                truncated = False
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    remaining = cap - len(buf)
                    buf.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                        break
                return HttpResponse(
                    status=resp.status, headers=_lower(resp.headers),
                    body=bytes(buf[:cap]), url=str(resp.url),
                    elapsed_ms=_ms(t0), truncated=truncated)
        except Exception as e:
            raise HttpError(_why(e, self._timeout)) from e

    async def digest(self, url, *, headers=None, max_bytes=None) -> DigestResult:
        """边下边算 MD5，不进内存。

        **一定要有字节上限。** 没有上限的话，一条被劫持或坏掉的线路可以一直
        往我们这边灌数据：内存不涨（是流式的），但带宽和时间无上限——监控自己
        变成了那条线路的长期负载。上限由调用方按「版本文件声明的大小」给，
        超了直接判失败：本来就说明这个包不是它声称的那个。
        """
        if max_bytes is None or max_bytes <= 0:
            raise HttpError("流式读取必须指定正数字节上限")
        cap = max_bytes
        t0 = time.monotonic()
        try:
            async with self._get(url, headers=headers, timeout=self._stream_timeout) as resp:
                md = hashlib.md5()
                size = 0
                overflow = False
                async for chunk in resp.content.iter_chunked(1 << 20):
                    md.update(chunk)
                    size += len(chunk)
                    if cap is not None and size > cap:
                        overflow = True
                        break
                return DigestResult(status=resp.status, headers=_lower(resp.headers),
                                    size=size, md5=md.hexdigest(), elapsed_ms=_ms(t0),
                                    overflow=overflow)
        except Exception as e:
            raise HttpError(_why(e, self._stream_timeout)) from e


def elapsed_ms(t0: float) -> int:
    """`time.monotonic()` 起点到现在的毫秒数。计时只有这一份实现。"""
    return int((time.monotonic() - t0) * 1000)


_ms = elapsed_ms          # 模块内部沿用短名


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
