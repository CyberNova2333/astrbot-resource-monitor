# -*- coding: utf-8 -*-
"""判据层：**不依赖 AstrBot**（CLAUDE.md 铁律 3）。

进去 URL + 期望，出来 ProbeResult。所有 I/O 都通过 `watch.http.HttpClient`
这个协议走，测试里喂假响应就能离线跑——判据层的测试**不打真线路**：真线路会
抖，抖一次测试就红一次，红几次之后没人再看测试结果。

AstrBot 的 Star / Context / 命令装饰器只出现在 main.py 一层。
"""

__all__ = ["models", "config", "http", "discovery", "probes", "scheduler",
           "state", "render"]
