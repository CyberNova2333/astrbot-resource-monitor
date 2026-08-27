# -*- coding: utf-8 -*-
"""命令闸门：谁能用、在哪能用、多久能用一次。**纯函数，可离线单测。**

## 为什么监控插件需要这一层

这个插件跑在一个**共享的聊天环境**里：同一个 bot 上装着别人的插件，群里坐着
几百个不认识的人，而我们的命令能触发**真实的网络流量**——`/线路 测` 会拉清单、
取块、核对热更包。没有闸门的话，一条 `/线路 测 甲` 复读机就是一台放大器：
每条消息都让我们去打一遍线上线路，账单和封禁都算在我们头上。

三道闸，各管一件事：

  1. **在哪能用**——默认只在配置好的通知会话里响应。别的群里 @ 出来的命令
     不回：那些群没理由看到线路地址与阈值，而 bot 常常同时在很多群里；
  2. **谁能用**——会产生流量的命令限管理员（与静音同一条判据）。查看类不限，
     它们只读内存里已经有的东西；
  3. **多久一次**——最小间隔。它拦的不是恶意，而是复读：群里两个人同时想起来
     要测一下，就会连开两轮。

三道都**默认打开**。安全默认值的意义就在于：忘了配的人也是安全的。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Set

# 会打真实网络的命令。查看类不在此列——它们只读内存里已经跑出来的结果。
HEAVY = frozenset({"测", "test", "配置", "config"})
# 会改变告警行为的命令：静音把所有告警关掉，且关掉之后没有任何人会知道。
PRIVILEGED = frozenset({"静音", "mute", "取消静音", "unmute"})


@dataclass
class CommandPolicy:
    allow_sessions: Set[str] = field(default_factory=set)
    respond_anywhere: bool = False
    heavy_admin_only: bool = True
    privileged_admin_only: bool = True
    cooldown_seconds: float = 60.0


class CommandGate:
    def __init__(self, policy: CommandPolicy):
        self.policy = policy
        self._last: Dict[str, float] = {}

    def refuse_reason(self, action: str, *, session: str, is_admin: bool,
                      now: Optional[float] = None) -> Optional[str]:
        """放行返回 None，否则返回一句**给发命令的人看**的拒绝理由。

        拒绝也要说清楚为什么：一条沉默的命令会让人以为 bot 挂了，然后再发五遍。
        """
        now = now if now is not None else time.time()
        p = self.policy

        if not p.respond_anywhere and p.allow_sessions and session not in p.allow_sessions:
            # 在别的群里干脆不回（返回空字符串 = 静默拒绝）：那些群没理由看到
            # 线路地址，而回一句「你没权限」本身也是在回应陌生环境里的指令。
            return ""

        if action in PRIVILEGED and p.privileged_admin_only and not is_admin:
            return "只有管理员能用这条命令。"
        if action in HEAVY:
            if p.heavy_admin_only and not is_admin:
                return "这条命令会真的去打线上线路，限管理员使用。"
            left = self._cooldown_left(action, now)
            if left > 0:
                return "刚跑过一轮，%d 秒后再来——每条命令都会产生真实流量。" % int(left + 0.5)
        return None

    def _cooldown_left(self, action: str, now: float) -> float:
        # 冷却按「重活」整体算，不按具体子命令：两条不同的重命令连着来，
        # 打出去的流量是一样的。
        #
        # 「从没跑过」用 None 判，不用 0.0 当哨兵：0 是合法时间戳（epoch），
        # 拿它当「没有」会让第一条命令在冷却里出不去。
        last = self._last.get("heavy")
        if last is None:
            return 0.0
        return max(0.0, self.policy.cooldown_seconds - (now - last))

    def mark(self, action: str, now: Optional[float] = None) -> None:
        if action in HEAVY:
            self._last["heavy"] = now if now is not None else time.time()


def build(sessions: Sequence[str], raw: Optional[dict] = None) -> CommandGate:
    raw = raw if isinstance(raw, dict) else {}
    extra = raw.get("allow_sessions")
    allow = {str(s).strip() for s in sessions if str(s).strip()}
    if isinstance(extra, list):
        allow |= {str(s).strip() for s in extra if str(s).strip()}
    cooldown = raw.get("cooldown_seconds", 60)
    return CommandGate(CommandPolicy(
        allow_sessions=allow,
        respond_anywhere=bool(raw.get("respond_anywhere", False)),
        heavy_admin_only=bool(raw.get("heavy_admin_only", True)),
        privileged_admin_only=bool(raw.get("privileged_admin_only", True)),
        cooldown_seconds=float(cooldown) if isinstance(cooldown, (int, float))
        and not isinstance(cooldown, bool) else 60.0,
    ))
