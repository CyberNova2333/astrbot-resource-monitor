# -*- coding: utf-8 -*-
"""状态落盘。原子写 + 坏了就当没有——只有这一份实现，别处不要再写一遍。

原先 `AlertState.save` 与 main.py 各写了一遍「建目录 → 写 .tmp → os.replace」。
两份实现会各自长歪：一份加了原子替换、另一份没有，而这类差别只在断电或磁盘满
的时候才现形，那时候没人会想到去比对两个函数。
"""

from __future__ import annotations

import json
import os
from typing import Optional


def save_json(path: str, data: dict) -> Optional[str]:
    """尽力而为地写。成功返回 None，失败返回一句给日志看的话。

    **写不进去不是致命错误**：这里存的是故障状态机，可丢，丢了最多重报一次。
    为它让整个监控崩掉是本末倒置（铁律 7）。
    """
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)      # 原子替换：中途挂掉也不会留半截文件
        return None
    except (OSError, TypeError, ValueError) as e:
        return str(e)


def load_json(path: str) -> Optional[dict]:
    """读回来。没有、读不动、或者不是个对象，一律返回 None（当作全新开始）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
