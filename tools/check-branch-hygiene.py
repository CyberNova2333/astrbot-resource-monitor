#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""远端分支纪律检查器。**开任何分支之前先跑它。**

## 它回答什么

一句话：「我现在能不能开新分支」，以及「远端有没有我该收拾的垃圾」。

规则见 AGENTS.md §0，这里是它的可执行形式（判据与 pre-push 钩子共用
`tools/githooks/_branchrules.py` 那一份）：

  1. 远端只该有 `main` 与 `<类>/<用途>`，类只有 `hotfix` / `surgery`，
     **用途段必须读得出这条分支在干什么**；
  2. **2 小时内刚有过分支活动**（且那条分支还没被删），就**不许再开新分支**——
     接着用那条，或者干脆直接提 main；
  3. 同一时刻只该有**一条**例外分支。远端同时挂着两条及以上，本身就是需要
     收拾的状态；
  4. 白名单不等于永久居住证：`hotfix/*` 超 24 小时、`surgery/*` 超 72 小时
     即超期，一样点名。

## 为什么要有它

分支纪律写在文档里没人看，所以做成命令：**跑一下，它直接告诉你行还是不行。**
一次性分支的典型长相是同一条工作的递进快照（`xxx-v2`、`xxx-retry`、
`xxx-final`）——那几条本该是本地的几次 `git commit --amend`，留在远端只会变成
没人再看、也没人敢删的 ref。

## 用法

    python3 tools/check-branch-hygiene.py                # 体检：远端现在干净吗
    python3 tools/check-branch-hygiene.py --can-branch   # 我现在能开新分支吗

退出码 0 = 通过，1 = 不通过（`--can-branch` 下即「不许开」）。
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "githooks"))
try:
    import _branchrules                                       # noqa: E402
except ImportError:
    # 判据模块不在 → 说清楚而不是硬跑一套自己的。判据只该有一份。
    print("✘ 找不到 tools/githooks/_branchrules.py（分支判据）。"
          "它与 pre-push 钩子共用，必须在那个目录里。")
    sys.exit(2)

# 「刚刚才开过分支」的判定窗口
RECENT_HOURS = 2.0


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def remote_branches():
    r = sh("git", "ls-remote", "--heads", "origin")
    if r.returncode != 0:
        print("✘ 取不到远端分支列表：" + r.stderr.strip())
        sys.exit(2)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        out.append((parts[0], parts[1].replace("refs/heads/", "")))
    return out


def tip_age_hours(sha, name):
    """分支尖端提交距今多久（小时）。取不到返回 None。

    对象可能不在本地，按需取一次。**只写 FETCH_HEAD，不建 ref**——建出来的
    ref 没人清理，越攒越多，还让被删分支的对象一直可达。
    """
    if sh("git", "cat-file", "-e", sha + "^{commit}").returncode != 0:
        if sh("git", "fetch", "--quiet", "origin", name).returncode != 0:
            return None
        sha = "FETCH_HEAD"
    r = sh("git", "log", "-1", "--format=%ct", sha)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return (time.time() - int(r.stdout.strip())) / 3600.0
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--can-branch", action="store_true",
                    help="判定「现在能不能开新分支」，不能则退出码 1")
    args = ap.parse_args()

    branches = remote_branches()
    strays, overdue, fresh = [], [], []

    print("远端分支共 %d 条：" % len(branches))
    for sha, name in sorted(branches, key=lambda x: x[1]):
        probs = _branchrules.problems(name)
        tag = "允许" if not probs else "⚠ 不合规"
        age = ""
        if name != "main":
            h = tip_age_hours(sha, name)
            age = ("  （末次提交 %.1f 小时前）" % h) if h is not None else "  （时间未知）"
            limit = _branchrules.lifetime_hours(name)
            if h is not None:
                if limit is not None and h > limit:
                    tag = "⚠ 超期"
                    overdue.append((name, h, limit))
                if h < RECENT_HOURS:
                    fresh.append((name, h))
        if probs:
            strays.append((name, probs))
        print("  %-10s %s%s" % (tag, name, age))

    for name, probs in strays:
        print("\n✘ %s" % probs[0])
        for p in probs[1:]:
            print("  %s" % p)

    if strays:
        print("\n  不要直接删——有价值的先归档成 tag 再删：")
        for name, _ in strays:
            print("    git push origin origin/%s^{}:refs/tags/archive/%s"
                  " && git push origin --delete %s" % (name, name, name))

    if overdue:
        print("\n✘ 有 %d 条例外分支超期（白名单不等于永久居住证）：" % len(overdue))
        for name, h, limit in overdue:
            print("    %s —— 已存在 %.1f 小时，上限 %.0f 小时。合入 main 后删除；"
                  "舍不得删的部分打 archive/* tag。" % (name, h, limit))

    if not strays and not overdue:
        print("\n✔ 干净：只有 main 与合规、未超期的例外分支")

    if args.can_branch:
        print()
        if fresh:
            print("✘ **不许开新分支**：下面这些是 %.0f 小时内刚动过的，"
                  "接着用它（AGENTS.md §0 规则三）：" % RECENT_HOURS)
            for name, h in fresh:
                print("    %s（%.1f 小时前）" % (name, h))
            return 1
        if strays:
            print("✘ **不许开新分支**：远端已经有不合规的分支了，"
                  "先收拾干净（见上）。")
            return 1
        if overdue:
            print("✘ **不许开新分支**：有超期的例外分支没收拾（见上）。"
                  "先合入删除，或归档成 tag。")
            return 1
        print("✔ 可以开分支——但先想清楚两件事：\n"
              "    1. 本仓库默认**直接提 main**，多数改动根本不需要分支；\n"
              "    2. 真要开，名字必须是 <类>/<用途>，类只有 hotfix / surgery，\n"
              "       用途要能让别人读出这条分支在干什么（AGENTS.md §0）。")
        return 0

    return 1 if (strays or overdue) else 0


if __name__ == "__main__":
    sys.exit(main())
