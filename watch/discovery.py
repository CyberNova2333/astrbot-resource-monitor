# -*- coding: utf-8 -*-
"""自发现：**探哪里、按什么判，全部现取**（CLAUDE.md 铁律 2）。

    本地配置 → entry_url
                 └─ 线上配置 ── mirrors[]（线路表）
                                 └─ 每条线路上的 manifest（内容判据）
                                 └─ 版本 json（热更包的权威身份）

插件里不留第二份线路表、文件清单、阈值。抄一份就会漂移，而漂移的表现是
「监控全绿但用户装不上」——恰恰是这套东西存在的理由。

## 解析判据与客户端同源

清单条目按客户端的规矩认：`size` / `chunk_size` / `chunks[]`，每块一个 **32 位
十六进制 MD5**；任何一条不满足，该条目**跳过**（客户端也是跳过而不是整份作废）。
不同的是监控会把「跳过了几条」带出来——对客户端那是降级，对监控那是线索。

## 热更包探针要探什么，由被监控方声明

版本 json 的文件名不在清单里，也**不写死在插件里**。线上配置可以带一个可选的
`watch` 段来声明：

    "watch": { "version_files": ["version_a.json", "version_b.json"] }

没声明就跳过热更相关探针（标 unknown，不报警）——不知道该探什么时保持沉默，
比拿一份猜的清单去报警好（铁律 7）。
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from .http import HttpClient, HttpError, HttpResponse
from .models import MAX_METADATA_INTEGER, FileEntry, Mirror, OnlineConfig, VersionMeta

MANIFEST_NAME = "manifest.json"

# 拉配置/清单时按客户端的做法压掉中间缓存：这两份要的是**此刻线上是什么**，
# 而不是某个节点几小时前缓存的那份。
# 注意：**块内容探针不带这些头**——那边恰恰要看用户会拿到的那份缓存。
NO_CACHE = {"Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"}


class DiscoveryError(Exception):
    """拿不到/看不懂线上配置。这本身就是 P0：客户端此时会静默回退，用户无感。"""


class ContentError(DiscoveryError):
    """**拉到了，但内容是坏的**（JSON 解析不了、结构不对、一条线路都没有）。

    与「拉不到」分开，是因为处置方式完全不同：内容坏了是人改坏的，要回滚；
    拉不到是出口/托管的问题，要找那边。糊成一条 P0 的话，收到的人第一步还是
    得自己去分辨——那正是告警该替他做的事。
    """


def integer_field(value, default: int = 0) -> int:
    """兼容整数字符串，但不把布尔、分数、非有限数悄悄当成有效大小。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("应为整数")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError("应为有限整数")
    number = int(value)
    if not -MAX_METADATA_INTEGER - 1 <= number <= MAX_METADATA_INTEGER:
        raise ValueError("整数超出支持范围")
    return number


def parse_mirrors(items) -> Tuple[List[Mirror], List[str]]:
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ContentError("mirrors 必须是数组")
    mirrors: List[Mirror] = []
    skipped: List[str] = []
    seen = set()
    for index, item in enumerate(items):
        try:
            if not isinstance(item, dict):
                raise ValueError("线路条目不是对象")
            base = item.get("base")
            if not isinstance(base, str) or not base.startswith(("http://", "https://")):
                raise ValueError("缺少有效 base")
            name = item.get("name") or base
            enabled = item.get("enabled", True)
            weight = integer_field(item.get("weight"))
            chunks = integer_field(item.get("chunks"))
            if (not isinstance(name, str) or not isinstance(enabled, bool)
                    or weight < 0 or chunks < 0 or name in seen):
                raise ValueError("线路字段类型、范围或名称重复")
            mirrors.append(Mirror(name=name, base=base, weight=weight,
                                  chunks=chunks, enabled=enabled))
            seen.add(name)
        except (TypeError, ValueError, OverflowError) as exc:
            skipped.append("第 %d 条：%s" % (index + 1, exc))
    return mirrors, skipped


def parse_online_config(body: bytes) -> OnlineConfig:
    try:
        raw = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, RecursionError) as e:
        raise ContentError("线上配置不是合法 JSON：%s" % e)
    if not isinstance(raw, dict):
        raise ContentError("线上配置的顶层不是对象")

    mirrors, skipped = parse_mirrors(raw.get("mirrors"))
    return OnlineConfig(raw=raw, mirrors=mirrors, invalid_mirrors=skipped)


async def fetch_online_config(client: HttpClient, entry_url: str) -> Tuple[OnlineConfig, HttpResponse]:
    """拉线上配置。拿不到就抛 DiscoveryError——**不返回上一次的那份**。

    这里不做「用缓存顶一下」是有意的：监控的价值就在于说出「现在拿不到」。
    拿旧的接着跑，探针会全绿，而用户那边正在静默回退到内置线路。
    """
    try:
        resp = await client.fetch(entry_url, headers=NO_CACHE)
    except HttpError as e:
        # 不在这里加「入口不可达」前缀：调用方已经按「拉不到 / 内容坏了」
        # 分好类了，两层前缀叠起来是「拉不到：入口不可达：连接超时」。
        raise DiscoveryError(str(e))
    if resp.status != 200:
        raise DiscoveryError("入口返回 HTTP %d（期望 200）" % resp.status)
    if resp.truncated:
        raise ContentError("入口响应超过上限，没读完——这不像是一份配置")
    cfg = parse_online_config(resp.body)
    if not cfg.mirrors:
        raise ContentError("线上配置里没有任何可用的 mirrors 条目")
    return cfg, resp


def parse_manifest(body: bytes) -> Tuple[Dict[str, FileEntry], List[str]]:
    """返回 (可用条目, 被跳过的条目名)。

    跳过而不是整份作废，与客户端一致；但把跳过的名字带出来——清单里出现坏条目
    时客户端只会换线，用户看到的是「换了条线继续下」，只有监控能说出为什么。
    """
    try:
        raw = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, RecursionError) as e:
        raise DiscoveryError("清单不是合法 JSON：%s" % e)
    if not isinstance(raw, dict):
        raise DiscoveryError("清单的顶层不是对象")

    entries: Dict[str, FileEntry] = {}
    skipped: List[str] = []
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            skipped.append(str(name))
            continue
        chunks = meta.get("chunks")
        try:
            entry = FileEntry(
                name=str(name),
                size=integer_field(meta.get("size"), -1),
                chunk_size=integer_field(meta.get("chunk_size")),
                chunks=[h.strip().lower() for h in chunks]
                if isinstance(chunks, list) and all(isinstance(h, str) for h in chunks) else [],
            )
        except (TypeError, ValueError, OverflowError):
            skipped.append(str(name))
            continue
        if entry.is_valid():
            entries[entry.name] = entry
        else:
            skipped.append(entry.name)
    return entries, skipped


async def fetch_manifest(client: HttpClient, mirror: Mirror
                         ) -> Tuple[Dict[str, FileEntry], List[str], HttpResponse]:
    url = mirror.url_for(MANIFEST_NAME)
    try:
        resp = await client.fetch(url, headers=NO_CACHE)
    except HttpError as e:
        raise DiscoveryError("清单不可达：%s" % e)
    if resp.status != 200:
        raise DiscoveryError("清单返回 HTTP %d（期望 200）" % resp.status)
    if resp.truncated:
        raise ContentError("清单响应超过本地读取上限，内容不完整")
    entries, skipped = parse_manifest(resp.body)
    return entries, skipped, resp


def parse_version_meta(body: bytes) -> VersionMeta:
    try:
        raw = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, RecursionError) as e:
        raise DiscoveryError("版本 json 不是合法 JSON：%s" % e)
    if not isinstance(raw, dict):
        raise DiscoveryError("版本 json 的顶层不是对象")
    try:
        version = integer_field(raw.get("version"))
        size = integer_field(raw.get("size"))
    except (TypeError, ValueError, OverflowError):
        version, size = 0, 0
    md5 = str(raw.get("md5") or "").strip().lower()
    return VersionMeta(version=version, size=size, md5=md5)


def declared_version_files(cfg: OnlineConfig) -> List[str]:
    """线上配置声明的版本 json 清单；没声明返回空列表（对应探针跳过）。"""
    watch = cfg.raw.get("watch")
    if not isinstance(watch, dict):
        return []
    names = watch.get("version_files")
    if not isinstance(names, list):
        return []
    return [n.strip() for n in names if isinstance(n, str) and n.strip()]


def declared_package_for(cfg: OnlineConfig, version_file: str) -> Optional[str]:
    """某份版本 json 对应的包名（可选声明）。没有就返回 None，整包核对跳过。"""
    watch = cfg.raw.get("watch")
    if not isinstance(watch, dict):
        return None
    mapping = watch.get("packages")
    if not isinstance(mapping, dict):
        return None
    name = mapping.get(version_file)
    return name if isinstance(name, str) and name else None
