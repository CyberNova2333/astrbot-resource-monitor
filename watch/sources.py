# -*- coding: utf-8 -*-
"""配置源：**「探哪里」从哪来**——这一层之下，判据不认识任何一份具体配置的形状。

## 为什么要有这一层

原先的实现直接读老客户端那份 `config.json` 的结构（`mirrors[]` / `settings` /
`client.version`）。那是**某一个客户端的产物**，不是这条链路的天然形状：正在开发
的网页端就不用它。把判据绑死在它上面，等于让监控跟着某一个客户端的历史包袱走
——将来那份文件停用，整套监控一起报废，而它探的东西（线路还活着吗、字节对不对）
一个字都没变。

所以配置源被抽成一层，出去的东西统一是 `Discovered`：

    线路表 + 阈值 + 要探哪些热更文件 + （可选）客户端自己的那几个字段

现在有两种源，加第三种只需要在这里加一个类，判据层一行都不用动：

  · `endpoint` —— 从一个 URL 拉一份 JSON。**它不认「老客户端配置」这个身份**，
    只认里面有没有 `mirrors`；`settings` / `watch` / `client` / `proxy` 有就用、
    没有就当没有。所以同一个适配器既吃老客户端那份 config.json，也吃网页端
    将来暴露的任何一份含 mirrors 的 JSON；
  · `mirrors` —— **完全不依赖任何中心配置**：线路表直接由部署侧的本地配置给。
    没有上游就没有上游单点，代价是没有线上阈值（于是速率判据保持未判定，
    而不是拿一个写死的默认值凑数——那是铁律 2 禁止的）。

## 一条边界

源可以变，**判据不变**：不管线路表从哪来，块内容仍然按清单里的 MD5 逐块认。
配置源回答的是「探哪里」，永远不回答「算不算好」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import discovery
from .http import HttpClient
from .models import Mirror, OnlineConfig, ProbeResult, Severity

PROBE_SOURCE = "配置源可达性"
KEY_SOURCE = "%s|%s" % (PROBE_SOURCE, "配置源")


@dataclass
class Discovered:
    """一次自发现的产出。**判据层只认这个**，不认任何一份配置的原始形状。"""

    mirrors: List[Mirror] = field(default_factory=list)
    settings: Dict[str, float] = field(default_factory=dict)
    version_files: List[str] = field(default_factory=list)
    packages: Dict[str, str] = field(default_factory=dict)
    client_version: Optional[str] = None       # 源里没有就是 None，不代表出错
    proxy_base: Optional[str] = None
    source_name: str = ""

    @property
    def enabled_mirrors(self) -> List[Mirror]:
        return [m for m in self.mirrors if m.enabled]

    def threshold(self, name: str) -> Optional[float]:
        """取一个阈值。**取不到返回 None，不返回兜底值**（铁律 2）。

        调用方拿到 None 时应当把对应判据标成未判定，而不是拿写死的数字接着算
        ——那就是在插件里留了第二份判据。
        """
        v = self.settings.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    def snapshot(self) -> dict:
        """归一化快照：落盘、以及「这次改动是不是把自己打死了」的比对基准。

        存归一化形式而不是原始文档，是因为**比对判据不该跟着源的形状走**：
        换一种源之后，突变检测与降级探测应当照常工作。
        """
        return {
            "source": self.source_name,
            "mirrors": [{"name": m.name, "base": m.base, "weight": m.weight,
                         "chunks": m.chunks, "enabled": m.enabled}
                        for m in self.mirrors],
            "settings": dict(self.settings),
            "version_files": list(self.version_files),
            "packages": dict(self.packages),
            "client_version": self.client_version,
            "proxy_base": self.proxy_base,
        }

    @classmethod
    def from_snapshot(cls, data: Optional[dict]) -> Optional["Discovered"]:
        if not isinstance(data, dict):
            return None
        mirrors = []
        for m in data.get("mirrors") or []:
            if not isinstance(m, dict) or not m.get("base"):
                continue
            mirrors.append(Mirror(name=str(m.get("name") or m["base"]),
                                  base=str(m["base"]),
                                  weight=int(m.get("weight") or 0),
                                  chunks=int(m.get("chunks") or 0),
                                  enabled=bool(m.get("enabled", True))))
        settings = data.get("settings")
        packages = data.get("packages")
        return cls(
            mirrors=mirrors,
            settings={str(k): v for k, v in settings.items()}
            if isinstance(settings, dict) else {},
            version_files=[str(x) for x in (data.get("version_files") or [])],
            packages={str(k): str(v) for k, v in packages.items()}
            if isinstance(packages, dict) else {},
            client_version=data.get("client_version"),
            proxy_base=data.get("proxy_base"),
            source_name=str(data.get("source") or ""),
        )


class Source:
    """协议。`discover` 返回 (给状态机吃的结果, 拿到的东西)。"""

    name = "source"
    #: 这个源有没有「会挂的上游」。没有的话，降级诊断那一套都用不上。
    has_upstream = True

    async def discover(self, client: HttpClient
                       ) -> Tuple[ProbeResult, Optional[Discovered]]:
        raise NotImplementedError

    async def diagnose(self, client: HttpClient) -> List[str]:
        """源挂了时的补充线索（备用出口之类）。默认没有。"""
        return []


class EndpointSource(Source):
    """从一个 URL 拉一份含 `mirrors` 的 JSON。

    **刻意不认文档的身份**：不检查 schema、不要求任何专属字段，只要里面有
    `mirrors[]`（每条带 `base`）就能用。`settings` / `watch` / `client` /
    `proxy` 属于「有就多探两样，没有就少探两样」，不是必需品。

    第一条 URL 是主入口（客户端用的那个），其余是备用出口，只在主入口失败时试
    ——用来区分「文档内容坏了」和「这个出口挂了」，两者处置方式完全不同。
    """

    name = "endpoint"

    def __init__(self, urls: Sequence[str]):
        if not urls:
            raise ValueError("endpoint 源至少要一个 URL")
        self.urls = list(urls)

    @property
    def primary(self) -> str:
        return self.urls[0]

    @property
    def backups(self) -> List[str]:
        return self.urls[1:]

    @staticmethod
    def to_discovered(cfg: OnlineConfig) -> Discovered:
        settings = {k: v for k, v in cfg.settings.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)}
        proxy = cfg.raw.get("proxy")
        version_files = discovery.declared_version_files(cfg)
        packages = {}
        for name in version_files:
            package = discovery.declared_package_for(cfg, name)
            if package:
                packages[name] = package
        return Discovered(
            mirrors=cfg.mirrors,
            settings=settings,
            version_files=version_files,
            packages=packages,
            client_version=(str(cfg.client.get("version")).strip()
                            if cfg.client.get("version") else None),
            proxy_base=(str(proxy.get("base")) if isinstance(proxy, dict)
                        and proxy.get("base") else None),
            source_name="endpoint",
        )

    async def discover(self, client):
        import time
        t0 = time.monotonic()
        try:
            cfg, resp = await discovery.fetch_online_config(client, self.primary)
        except discovery.DiscoveryError as e:
            # 两种坏法分开记：内容坏了要回滚，拉不到要找出口那边。
            content = isinstance(e, discovery.ContentError)
            return ProbeResult(
                ok=False, probe=PROBE_SOURCE, target="配置源",
                detail=("内容坏了：%s" if content else "拉不到：%s") % e,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                severity=Severity.P0,
                extra={"reason": "content" if content else "unreachable"}), None

        disc = self.to_discovered(cfg)
        return ProbeResult(
            ok=True, probe=PROBE_SOURCE, target="配置源",
            detail="OK，%d 条线路（%d 条启用）%s"
                   % (len(disc.mirrors), len(disc.enabled_mirrors),
                      "，%d 个阈值" % len(disc.settings) if disc.settings else ""),
            elapsed_ms=resp.elapsed_ms, severity=Severity.P0,
            extra={"enabled": len(disc.enabled_mirrors)}), disc

    async def diagnose(self, client):
        lines: List[str] = []
        got = None
        for url in self.backups:
            try:
                cfg, _ = await discovery.fetch_online_config(client, url)
            except discovery.ContentError as e:
                lines.append("备用出口 %s：内容同样是坏的（%s）" % (host_of(url), e))
                continue
            except discovery.DiscoveryError as e:
                lines.append("备用出口 %s：也拉不到（%s）" % (host_of(url), e))
                continue
            got = got or cfg
            lines.append("备用出口 %s：正常，%d 条线路（%d 启用）"
                         % (host_of(url), len(cfg.mirrors), len(cfg.enabled_mirrors)))
        if got is not None:
            lines.append("→ 文档内容本身是好的，坏的是主入口那个出口")
        elif lines:
            lines.append("→ 备用出口也拿不到好文档，多半不是单个出口的问题")
        return lines


class MirrorListSource(Source):
    """线路表直接由部署侧的本地配置给，**没有任何中心配置**。

    没有上游就没有上游单点：配置源这一环不可能挂，也就不存在「入口挂了怎么办」。
    代价是拿不到线上阈值——于是速率这类判据保持未判定，而**不是**拿一个写死的
    默认值凑数（铁律 2：写死一个默认值当兜底也算抄第二份）。

    要探的热更文件同样由本地配置声明；不声明就不探。
    """

    name = "mirrors"
    has_upstream = False

    def __init__(self, mirrors: Sequence[Mirror],
                 version_files: Optional[Sequence[str]] = None,
                 packages: Optional[Dict[str, str]] = None):
        if not mirrors:
            raise ValueError("mirrors 源至少要一条线路")
        self.discovered = Discovered(
            mirrors=list(mirrors),
            version_files=list(version_files or []),
            packages=dict(packages or {}),
            source_name="mirrors")

    async def discover(self, client):
        d = self.discovered
        # 标成未判定：这不是一次探测，只是把本地配置念了一遍。让它参与状态机
        # 只会在「所有探针都绿」的统计里混进一条永远绿的假指标。
        return ProbeResult(
            ok=True, probe=PROBE_SOURCE, target="配置源",
            detail="线路表由本地配置直接给出（%d 条，无中心配置源）" % len(d.mirrors),
            unknown=True, severity=Severity.P0), d


def build(spec: dict) -> Source:
    """按配置造一个源。形状不认识就抛——**不猜**。"""
    kind = str((spec or {}).get("type") or "").strip().lower()
    if kind in ("endpoint", "url", "config", "legacy-config"):
        urls = spec.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        return EndpointSource([str(u).strip() for u in urls if str(u).strip()])
    if kind in ("mirrors", "static", "local"):
        mirrors = []
        for item in spec.get("mirrors") or []:
            if not isinstance(item, dict) or not item.get("base"):
                continue
            mirrors.append(Mirror(
                name=str(item.get("name") or item["base"]),
                base=str(item["base"]),
                weight=int(item.get("weight") or 0),
                chunks=int(item.get("chunks") or 0),
                enabled=bool(item.get("enabled", True))))
        packages = spec.get("packages")
        return MirrorListSource(
            mirrors,
            version_files=[str(x) for x in (spec.get("version_files") or [])],
            packages={str(k): str(v) for k, v in packages.items()}
            if isinstance(packages, dict) else {})
    raise ValueError("不认识的配置源类型：%r（可用：endpoint / mirrors）" % kind)


def host_of(url: str) -> str:
    """取主机名。取不到就原样返回——这个值只用来给人看。"""
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url
