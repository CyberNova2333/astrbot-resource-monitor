# -*- coding: utf-8 -*-
"""探针：纯函数，进去 URL + 期望，出来 ProbeResult。**不认识 AstrBot。**

## 判据的总原则（CLAUDE.md 铁律 4）

**内容按 hash 认，不按状态码认。** 这条链路上绝大多数真实故障是「HTTP 200，
但字节是坏的」——回源缓存了半截文件、某条线路不支持 Range、上游配置拉不到而
客户端静默回退。探活返回 200 就算绿的探针，在这些故障面前**全是绿的**。

## 抽样块校验：一发验三件事

清单里存的正是每一块的 MD5，所以取一块回来比一次，同时得到：

  · **可达**——连得上、这条线路上真有这个文件；
  · **Range 支持**——不支持的线路第一步就露馅（返回 200 = 把整个文件给了我们，
    客户端的分片下载会因此退化，表现是「下载特别慢」而不是「失败」，极难归因）；
  · **字节正确**——回源缓存了旧版本或半截文件时，只有这一步能发现。

外加一个免费的副产品：这一块的耗时就是一次真实测速样本。

轮转而不是随机取块：要保证覆盖。一天几百块滚下来，全站每个字节都会被验到，
而且是持续滚动验证，不是一次性。

## 不确定时不报警

判据跑不成（本机 DNS 抽风、线上配置没给阈值、可选依赖缺失）一律返回
`unknown=True` 的结果——它不计入连续失败，也不会触发告警（铁律 7）。
一个会误报的监控，用不了几天就没人看了。
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Dict, List, Optional, Tuple

from . import discovery
from .http import (MAX_BUFFER_BYTES, DigestResult, HttpClient, HttpError, elapsed_ms,
                   kbps, require_public_address, validate_public_url)
from .models import FileEntry, Mirror, ProbeResult, Severity, VersionMeta, entry_fingerprint
from .sources import Discovered, KEY_SOURCE

PROBE_SANITY = "线上配置合理性"
PROBE_MANIFEST = "清单可达性"
PROBE_CHUNK = "块内容校验"
PROBE_RANGE = "Range 支持"
PROBE_VERSION = "版本 json"
PROBE_HOTPKG = "热更包整包核对"
PROBE_CONSISTENCY = "线路一致性"
PROBE_SPEED = "线路速率"
PROBE_TLS = "证书有效期"

# 抑制链的根：配置源坏了，下面全部是必然结果，不单独报（铁律 6）
KEY_ENTRY = KEY_SOURCE

CONTENT_RANGE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+)$", re.I)


def manifest_key(mirror: Mirror) -> str:
    """某条线路的清单探针键。线路上的其余探针都挂在它下面。"""
    return "%s|%s" % (PROBE_MANIFEST, mirror.name)


def _mirror_result(mirror: Mirror, **kwargs) -> ProbeResult:
    extra = dict(kwargs.pop("extra", {}))
    extra["mirror"] = mirror.name
    return ProbeResult(extra=extra, **kwargs)


# ────────────────────────────────────────────────────────────────
# 一、配置源自身的合理性（拉到了，但内容合不合理）
#
# 「探哪里」由 watch/sources.py 回答，那一层之下判据不认识任何一份配置的形状。
# 这里只吃 Discovered——所以换一种源（网页端将来暴露什么都行），下面一行不用改。
# ────────────────────────────────────────────────────────────────

def check_config_mutation(disc: Discovered, last_snapshot: Optional[dict]
                          ) -> List[ProbeResult]:
    """与上一次的好配置比：**这次改动是不是把自己打死了**。

    判据只挑「一眼可辨、且后果是全体用户」的那几种突变；小改动一律放行。
    会误报的配置守卫比没有守卫更糟——被误伤一次，人就再也不信这条告警了。
    """
    out: List[ProbeResult] = []
    prev = Discovered.from_snapshot(last_snapshot)
    if prev is None:
        return out

    now_count, prev_count = len(disc.enabled_mirrors), len(prev.enabled_mirrors)
    if prev_count >= 2 and now_count * 2 <= prev_count:
        out.append(ProbeResult(
            ok=False, probe=PROBE_SANITY, target="线路表突变",
            detail="启用的线路从 %d 条掉到 %d 条——改配置时手滑关掉一批，"
                   "剩下的会被瞬间打满" % (prev_count, now_count),
            severity=Severity.P0, suppress_key=KEY_ENTRY))
    else:
        out.append(ProbeResult(
            ok=True, probe=PROBE_SANITY, target="线路表突变",
            detail="启用线路数没有异常减少", severity=Severity.P0,
            suppress_key=KEY_ENTRY))

    if prev.settings and not disc.settings:
        out.append(ProbeResult(
            ok=False, probe=PROBE_SANITY, target="阈值段消失",
            detail="settings 段没了——客户端会退回内置默认值，实际行为与你以为的"
                   "不一样，而且监控这边的速率判据也跟着失效",
            severity=Severity.P1, suppress_key=KEY_ENTRY))
    else:
        out.append(ProbeResult(
            ok=True, probe=PROBE_SANITY, target="阈值段消失",
            detail="阈值段没有异常消失", severity=Severity.P1,
            suppress_key=KEY_ENTRY))
    return out


def check_mirror_targets(disc: Discovered) -> Tuple[List[Mirror], List[ProbeResult]]:
    """挡住指向**本机/内网**的线路地址，返回 (可以探的线路, 要报的结果)。

    线路表来自配置源，而配置源是**远端内容**：它被改坏或被劫持时，可以把线路
    指到 `http://127.0.0.1:8080/` 或 `http://10.0.0.5/` 上，让监控替它去敲部署
    机自己的内网——这是拿监控当跳板的经典形状（SSRF）。监控没有凭证，能捞到的
    有限，但「替远端内容访问内网」这件事本身就不该发生。

    这里先筛字面量和 URL 结构；DNS 与重定向在 HTTP 连接层检查，使用检查过的
    同一批地址建立连接，避免预解析后重查带来的竞态。
    """
    ok_mirrors: List[Mirror] = []
    out: List[ProbeResult] = []
    for m in disc.enabled_mirrors:
        host = _host_of(m.base)
        try:
            validate_public_url(m.base)
        except HttpError:
            out.append(ProbeResult(
                ok=False, probe=PROBE_SANITY, target=m.name,
                detail="线路指向本机/内网地址（%s），已拒绝探测——配置源是远端"
                       "内容，不该能指挥监控去敲部署机自己的内网" % host,
                severity=Severity.P1, suppress_key=KEY_ENTRY,
                extra={"mirror": m.name}))
            continue
        ok_mirrors.append(m)
    return ok_mirrors, out


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def check_config_sanity(disc: Discovered,
                        last_client_version: Optional[str] = None) -> List[ProbeResult]:
    """线上配置的**合理性**——防「改配置把自己打死」。

    这里刻意不去跟任何外部清单核对版本号（那需要认识别处的东西，本仓库不写
    具体出处）。判据只用两样：配置自身的结构，以及**上一次看到的值**——
    版本闸门只该往前走，回退多半是手滑，而它的后果是全体用户被推去装一个
    不存在的版本。
    """
    out: List[ProbeResult] = []
    enabled = disc.enabled_mirrors
    out.append(ProbeResult(
        ok=bool(enabled), probe=PROBE_SANITY, target="启用的线路数",
        detail=("%d 条线路启用" % len(enabled)) if enabled
               else "一条启用的线路都没有——用户会全部退回内置默认线路",
        severity=Severity.P0, suppress_key=KEY_ENTRY))

    ver = (disc.client_version or "").strip()
    if not ver:
        # 源里没有版本闸门这个概念（比如线路表直接由本地配置给），不是故障——
        # 少一样可探的东西而已。
        out.append(ProbeResult(
            ok=True, probe=PROBE_SANITY, target="版本闸门",
            detail="这个配置源没有版本闸门字段，跳过",
            severity=Severity.P1, unknown=True, suppress_key=KEY_ENTRY))
    else:
        shape_ok = bool(re.match(r"^\d+(\.\d+)*$", ver))
        moved_back = False
        if shape_ok and last_client_version:
            moved_back = _version_tuple(ver) < _version_tuple(last_client_version)
        if not shape_ok:
            detail = "版本闸门形状可疑：%r" % ver
        elif moved_back:
            detail = ("版本闸门回退了：%s → %s。往回改会把已经装上新版的人挡在"
                      "外面，或者把所有人推去装一个不存在的版本"
                      % (last_client_version, ver))
        else:
            detail = "版本闸门 %s" % ver
        out.append(ProbeResult(
            ok=shape_ok and not moved_back, probe=PROBE_SANITY, target="版本闸门",
            detail=detail, severity=Severity.P0, suppress_key=KEY_ENTRY,
            extra={"version": ver}))

    if disc.proxy_base:
        ok = disc.proxy_base.endswith("/")
        out.append(ProbeResult(
            ok=ok, probe=PROBE_SANITY, target="代理前缀",
            detail="代理前缀正常" if ok else
                   "代理前缀没有以 / 结尾，拼出来的地址会少一层路径",
            severity=Severity.P1, suppress_key=KEY_ENTRY))
    return out


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


# ────────────────────────────────────────────────────────────────
# 二、线路：清单
# ────────────────────────────────────────────────────────────────

async def probe_manifest(client: HttpClient, mirror: Mirror
                         ) -> Tuple[ProbeResult, Dict[str, FileEntry]]:
    """某条线路的清单。清单缺条目时客户端会换线；**全部线路都缺 = 谁都装不上**。"""
    t0 = time.monotonic()
    try:
        entries, skipped, resp = await discovery.fetch_manifest(client, mirror)
    except discovery.DiscoveryError as e:
        return _mirror_result(mirror,
            ok=False, probe=PROBE_MANIFEST, target=mirror.name,
            detail=str(e), elapsed_ms=elapsed_ms(t0), severity=Severity.P1,
            suppress_key=KEY_ENTRY), {}

    if not entries:
        return _mirror_result(mirror,
            ok=False, probe=PROBE_MANIFEST, target=mirror.name,
            detail="清单里没有一条可用条目（%d 条被判为坏条目）" % len(skipped),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=KEY_ENTRY), {}

    detail = "OK，%d 个文件" % len(entries)
    if skipped:
        detail += "；%d 条坏条目被跳过：%s" % (len(skipped), "、".join(skipped[:3]))
    return _mirror_result(mirror,
        ok=not skipped, probe=PROBE_MANIFEST, target=mirror.name,
        detail=detail, elapsed_ms=resp.elapsed_ms,
        severity=Severity.P1 if skipped else Severity.P1,
        suppress_key=KEY_ENTRY,
        extra={"files": len(entries), "skipped": len(skipped)}), entries


# ────────────────────────────────────────────────────────────────
# 三、内容：抽样块校验（一发验三件事）
# ────────────────────────────────────────────────────────────────

async def probe_chunk(client: HttpClient, mirror: Mirror, entry: FileEntry,
                      index: int, min_speed_kbps: Optional[float] = None
                      ) -> List[ProbeResult]:
    """取一块回来，比 MD5，分别给出内容、Range 与速率结果。

    **刻意不带 no-cache 头**：这一探要看的正是「用户现在会拿到什么」，包括
    这条线路的缓存里躺着的那份。压掉缓存等于把最想抓的故障绕过去了。
    """
    target = "%s#%s[%d]" % (mirror.name, entry.name, index)
    if not entry.is_valid() or index < 0 or index >= entry.count:
        return [_mirror_result(mirror, ok=True, probe=PROBE_CHUNK, target=target,
                            detail="清单条目或块序号无效，跳过", unknown=True,
                            suppress_key=manifest_key(mirror))]

    start, end = entry.range_for(index)
    want = entry.chunks[index]
    expect_len = end - start + 1
    if expect_len > MAX_BUFFER_BYTES:
        return [_mirror_result(
            mirror, ok=True, probe=PROBE_CHUNK, target=target,
            detail="清单块大小超过本地内存安全上限，本轮不下载该块", unknown=True,
            suppress_key=manifest_key(mirror))]
    url = mirror.url_for(entry.name)
    t0 = time.monotonic()
    try:
        resp = await client.fetch(url, headers={"Range": "bytes=%d-%d" % (start, end)},
                                  max_bytes=expect_len + 1024)
    except HttpError as e:
        return [_mirror_result(mirror, ok=False, probe=PROBE_CHUNK, target=target,
                            detail="连接失败：%s" % e, elapsed_ms=elapsed_ms(t0),
                            severity=Severity.P1, suppress_key=manifest_key(mirror))]

    if resp.status == 200:
        # 服务器忽略了 Range，把整个文件给了我们。这本身就是故障：客户端的分片
        # 下载会退化成整包重下，表现是「网特别慢」而不是「失败」。
        return [_mirror_result(mirror,
            ok=False, probe=PROBE_RANGE, target=mirror.name,
            detail="不支持 Range（返回 200，期望 206）——分片下载会退化成整包重下，"
                   "用户看到的是『下载特别慢』",
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror))]

    if resp.status != 206:
        return [_mirror_result(mirror,
            ok=False, probe=PROBE_CHUNK, target=target,
            detail="HTTP %d（期望 206）" % resp.status, elapsed_ms=resp.elapsed_ms,
            severity=Severity.P1, suppress_key=manifest_key(mirror))]

    cr = CONTENT_RANGE.match(resp.header("content-range").strip())
    try:
        bounds = tuple(int(value) for value in cr.groups()) if cr else None
    except ValueError:
        bounds = None
    if bounds is None or bounds[:2] != (start, end):
        return [_mirror_result(
            mirror, ok=False, probe=PROBE_CHUNK, target=target,
            detail="Content-Range 缺失或与请求的块区间不符",
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror))]
    range_ok = _mirror_result(
        mirror, ok=True, probe=PROBE_RANGE, target=mirror.name,
        detail="Range 响应正常", elapsed_ms=resp.elapsed_ms,
        severity=Severity.P1, suppress_key=manifest_key(mirror))
    if bounds[2] != entry.size:
        return [_mirror_result(mirror,
            ok=False, probe=PROBE_CHUNK, target=target,
            detail="文件总长与清单不符：清单 %d，这条线路 %s"
                   "（多半是这条线路上还是旧版本）" % (entry.size, cr.group(3)),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror)), range_ok]

    got = resp.body
    if resp.truncated or len(got) != expect_len:
        return [_mirror_result(mirror,
            ok=False, probe=PROBE_CHUNK, target=target,
            detail="收到 %d 字节，期望 %d 字节" % (len(got), expect_len),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror)), range_ok]

    digest = hashlib.md5(got).hexdigest()
    if digest != want:
        return [_mirror_result(mirror,
            ok=False, probe=PROBE_CHUNK, target=target,
            detail="内容不符：清单 %s… 实得 %s…（这条线路多半缓存了旧版本或"
                   "半截文件）" % (want[:12], digest[:12]),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror)), range_ok]

    speed = kbps(len(got), resp.elapsed_ms)
    out = [_mirror_result(mirror,
        ok=True, probe=PROBE_CHUNK, target=target,
        detail="OK，%.1f MiB，%.0f kbps" % (len(got) / 1048576.0, speed),
        elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
        suppress_key=manifest_key(mirror),
        extra={"kbps": speed, "bytes": len(got)})]
    out.append(range_ok)

    # 速率判据的阈值**来自线上配置**（min_speed_kbps）。线上没给就不判——
    # 在这里写一个默认值，就是在插件里留第二份判据（铁律 2）。
    if min_speed_kbps is None:
        out.append(_mirror_result(mirror,
            ok=True, probe=PROBE_SPEED, target=mirror.name,
            detail="线上配置未给 min_speed_kbps，本轮不判速率", unknown=True,
            suppress_key=manifest_key(mirror)))
    else:
        slow = speed < min_speed_kbps
        out.append(_mirror_result(mirror,
            ok=not slow, probe=PROBE_SPEED, target=mirror.name,
            detail="%.0f kbps（线上阈值 %.0f kbps）%s"
                   % (speed, min_speed_kbps,
                      "——低于客户端会判停滞换线的速度" if slow else ""),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P2,
            suppress_key=manifest_key(mirror), extra={"kbps": speed}))
    return out


# ────────────────────────────────────────────────────────────────
# 四、热更包
# ────────────────────────────────────────────────────────────────

async def probe_version_json(client: HttpClient, mirror: Mirror, name: str
                             ) -> Tuple[ProbeResult, Optional[VersionMeta]]:
    """版本 json：热更包的权威身份（version + size + md5）。

    三者缺一，客户端那边就拒绝更新——它宁可不更也不装一个校验不了的包。
    所以「字段缺失」在这里等价于「热更停摆」，按坏判。
    """
    url = mirror.url_for(name)
    t0 = time.monotonic()
    try:
        resp = await client.fetch(url, headers=discovery.NO_CACHE)
    except HttpError as e:
        return _mirror_result(mirror, ok=False, probe=PROBE_VERSION, target="%s#%s" % (mirror.name, name),
                           detail="连接失败：%s" % e, elapsed_ms=elapsed_ms(t0),
                           severity=Severity.P1, suppress_key=manifest_key(mirror)), None
    if resp.status != 200:
        return _mirror_result(mirror, ok=False, probe=PROBE_VERSION, target="%s#%s" % (mirror.name, name),
                           detail="HTTP %d（期望 200）" % resp.status,
                           elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
                           suppress_key=manifest_key(mirror)), None
    try:
        if resp.truncated:
            raise discovery.ContentError("版本响应超过本地读取上限，内容不完整")
        meta = discovery.parse_version_meta(resp.body)
    except discovery.DiscoveryError as e:
        return _mirror_result(mirror, ok=False, probe=PROBE_VERSION, target="%s#%s" % (mirror.name, name),
                           detail=str(e), elapsed_ms=resp.elapsed_ms,
                           severity=Severity.P1, suppress_key=manifest_key(mirror)), None

    if not meta.is_valid():
        return _mirror_result(mirror,
            ok=False, probe=PROBE_VERSION, target="%s#%s" % (mirror.name, name),
            detail="缺 version/size/md5（version=%s size=%s md5=%s）——客户端会因此"
                   "拒绝更新，热更静默停摆" % (meta.version, meta.size, meta.md5 or "空"),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror)), meta
    return _mirror_result(mirror,
        ok=True, probe=PROBE_VERSION, target="%s#%s" % (mirror.name, name),
        detail="OK，v%d，%.1f MiB" % (meta.version, meta.size / 1048576.0),
        elapsed_ms=resp.elapsed_ms, severity=Severity.P1,
        suppress_key=manifest_key(mirror),
        extra={"version": meta.version, "size": meta.size}), meta


async def probe_hot_package(client: HttpClient, mirror: Mirror, package: str,
                            meta: VersionMeta) -> ProbeResult:
    """整包核对：size + 整包 MD5，与客户端的验收判据同源。

    包不小（数百 MB 量级），所以调度上**默认只在版本号变化时**跑一次，外加一道
    最小间隔兜底（见 scheduler）。按轮跑会把带宽烧在一件几天才变一次的事情上，
    而这类故障恰恰只在「包刚换过」的时候出现。
    """
    url = mirror.url_for(package)
    target = "%s#%s" % (mirror.name, package)
    t0 = time.monotonic()
    try:
        # 上限 = 声称的大小 + 1 MiB 余量。超了就不必再下：内容已经与它声称的
        # 身份不符，而继续下只是替一条坏线路烧我们自己的带宽。
        res: DigestResult = await client.digest(url, max_bytes=meta.size + (1 << 20))
    except HttpError as e:
        return _mirror_result(mirror, ok=False, probe=PROBE_HOTPKG, target=target,
                           detail="连接失败：%s" % e, elapsed_ms=elapsed_ms(t0),
                           severity=Severity.P1, suppress_key=manifest_key(mirror))
    if res.status != 200:
        return _mirror_result(mirror, ok=False, probe=PROBE_HOTPKG, target=target,
                           detail="HTTP %d（期望 200）" % res.status,
                           elapsed_ms=res.elapsed_ms, severity=Severity.P1,
                           suppress_key=manifest_key(mirror))
    if res.overflow:
        return _mirror_result(mirror,
            ok=False, probe=PROBE_HOTPKG, target=target,
            detail="包比版本文件声称的大：说好 %d 字节，下到 %d 还没完，已中断"
                   % (meta.size, res.size),
            elapsed_ms=res.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror))
    if res.size != meta.size:
        return _mirror_result(mirror,
            ok=False, probe=PROBE_HOTPKG, target=target,
            detail="长度不符：版本 json 说 %d，实得 %d" % (meta.size, res.size),
            elapsed_ms=res.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror))
    if res.md5 != meta.md5:
        return _mirror_result(mirror,
            ok=False, probe=PROBE_HOTPKG, target=target,
            detail="整包 MD5 不符：期望 %s… 实得 %s…（长度对得上而内容不对，"
                   "多半是这条线路缓存了同名旧包）" % (meta.md5[:12], res.md5[:12]),
            elapsed_ms=res.elapsed_ms, severity=Severity.P1,
            suppress_key=manifest_key(mirror))
    speed = kbps(res.size, res.elapsed_ms)
    return _mirror_result(mirror,
        ok=True, probe=PROBE_HOTPKG, target=target,
        detail="OK，v%d，%.1f MiB，%.0f kbps"
               % (meta.version, res.size / 1048576.0, speed),
        elapsed_ms=res.elapsed_ms, severity=Severity.P1,
        suppress_key=manifest_key(mirror), extra={"kbps": speed})


# ────────────────────────────────────────────────────────────────
# 五、线路一致性（纯函数，不联网）
# ────────────────────────────────────────────────────────────────

def check_manifest_consistency(per_mirror: Dict[str, Dict[str, FileEntry]]
                               ) -> List[ProbeResult]:
    """同一文件在各条线路上的清单必须一致，不一致说明某条线路落后了。

    判据用**多数派**：以出现次数最多的那份为准，少数的那条报出来。只有两条
    线路且互相矛盾时不指认谁对（unknown）——那时候监控说不清，硬指一个反而
    会把人引到错的方向。
    """
    out: List[ProbeResult] = []
    if len(per_mirror) < 2:
        return out

    names = set()
    for entries in per_mirror.values():
        names.update(entries.keys())

    for name in sorted(names):
        fingerprints: Dict[str, List[str]] = {}
        for mirror_name, entries in per_mirror.items():
            e = entries.get(name)
            fp = "缺失" if e is None else entry_fingerprint(e)
            fingerprints.setdefault(fp, []).append(mirror_name)
        ranked = sorted(fingerprints.items(), key=lambda kv: -len(kv[1]))
        top = ranked[0]
        ambiguous = len(top[1]) * 2 <= len(per_mirror)
        for fp, mirrors in ranked:
            for mirror_name in mirrors:
                matches = fp == top[0]
                detail = ("与多数线路一致" if matches else
                          "与多数线路不一致（%d 条线路是 %s，这条是 %s）"
                          % (len(top[1]), _fp_human(top[0]), _fp_human(fp)))
                out.append(ProbeResult(
                    ok=matches and not ambiguous, probe=PROBE_CONSISTENCY,
                    target="%s#%s" % (mirror_name, name),
                    detail="各线路清单没有明确多数，无法确认内容基准"
                           if ambiguous else detail,
                    severity=Severity.P1, unknown=ambiguous,
                    suppress_key=KEY_ENTRY, extra={"mirror": mirror_name}))
    return out


def _fp_human(fp: str) -> str:
    if fp == "缺失":
        return "没有这个文件"
    size, _, rest = fp.partition("/")
    return "%.1f MiB" % (int(size) / 1048576.0) if size.isdigit() else fp


# ────────────────────────────────────────────────────────────────
# 六、证书有效期（P2，趋势类）
# ────────────────────────────────────────────────────────────────

def check_cert_days(host: str, days_left: Optional[float]) -> ProbeResult:
    """把「还剩几天」翻成结论。取不到天数就是 unknown——不报警。

    分两档是因为它们要人做的事不一样：14 天是「排进这周」，3 天是「今天就得
    弄」。一个级别的告警说不清这个差别。
    """
    if days_left is None:
        return ProbeResult(ok=True, probe=PROBE_TLS, target=host,
                           detail="取不到证书信息，本轮跳过", unknown=True)
    if days_left < 3:
        return ProbeResult(ok=False, probe=PROBE_TLS, target=host,
                           detail="证书 %.1f 天后过期——过期即全部线路不可用"
                                  % days_left, severity=Severity.P0)
    if days_left < 14:
        return ProbeResult(ok=False, probe=PROBE_TLS, target=host,
                           detail="证书还剩 %.0f 天" % days_left, severity=Severity.P2)
    return ProbeResult(ok=True, probe=PROBE_TLS, target=host,
                       detail="证书还剩 %.0f 天" % days_left, severity=Severity.P2)


async def probe_tls_expiry(host: str, port: int = 443, *,
                           now: Optional[float] = None,
                           fetch_not_after=None) -> ProbeResult:
    """证书剩余天数。`fetch_not_after` 可注入，测试用它避免联网。"""
    now = now if now is not None else time.time()
    target = host if port == 443 else "%s:%d" % (
        "[%s]" % host if ":" in host else host, port)
    getter = fetch_not_after or _default_not_after
    try:
        not_after = await getter(host, port)
    except Exception as e:                                    # noqa: BLE001
        return ProbeResult(ok=True, probe=PROBE_TLS, target=target,
                           detail="取证书失败（%s），本轮跳过" % e, unknown=True)
    if not not_after:
        return check_cert_days(target, None)
    return check_cert_days(target, (not_after - now) / 86400.0)


async def _default_not_after(host: str, port: int) -> Optional[float]:
    """真实现：握手拿证书。放在线程里跑——ssl 那套是阻塞 API。"""
    import asyncio
    return await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(None, _tls_not_after, host, port),
        timeout=15.0)


def _tls_not_after(host: str, port: int) -> Optional[float]:
    import socket
    import ssl

    deadline = time.monotonic() + 15.0

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("TLS 解析和握手超过总时限")
        return seconds

    ctx = ssl.create_default_context()
    # TLS 探针也必须使用同一批经过校验的 DNS 结果，不能另走未防护的连接。
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for _, _, _, _, address in addresses:
        require_public_address(address[0])
    last_error = None
    cert = None
    for family, kind, protocol, _, address in addresses:
        try:
            with socket.socket(family, kind, protocol) as sock:
                sock.settimeout(remaining())
                sock.connect(address)
                sock.settimeout(remaining())
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    cert = tls.getpeercert()
            break
        except OSError as exc:
            last_error = exc
    if cert is None and last_error is not None:
        raise last_error
    raw = cert.get("notAfter") if cert else None
    # cert_time_to_seconds 认的就是 notAfter 那个格式，避免手工解析时区缩写。
    return float(ssl.cert_time_to_seconds(raw)) if raw else None
