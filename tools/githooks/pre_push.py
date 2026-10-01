# -*- coding: utf-8 -*-
"""pre-push 钩子：把 AGENTS.md §0 的分支纪律与 §1 的提交规范变成硬拦截。

装法见 tools/install-hooks.sh（多数情况用不着——见 tools/agent-guard.py）。

## 拦什么

三件事，互相独立，各有各的逃生口。

### 一、本次推送新增的提交，信息不合规（§1）

判据与 commit-msg 完全一致（共用 tools/githooks/_msgrules.py）。之所以在推送时
再查一遍：commit-msg 只管得住「提交这个动作发生在这份克隆里」。在别处提交、再作为
分支推进来的提交它看不见——而那恰恰是这类规范最常被绕开的方式。

只查**本次推送新增的**提交：已经在远端的历史一律不碰（`remote..local`，新建分支
则是 `local --not --remotes=<远端>`），另外再加一道时间闸 CUTOFF_EPOCH，早于它的
提交一律不查。所以既不翻旧账，也不会因为历史里有不合规的老提交把第一次推送卡死。
合并提交（多个父）跳过——那是 git 自己生成的信息。

逃生口：`SKIP_MSG_HOOK=1 git push ...`

### 二、新建远端分支（§0）

只有**新建**这一个动作。已存在的分支继续推、推 main、删分支，都放行。

判据见 `_branchrules.py`：远端只允许 `main` 与 `<类>/<用途>`，类只有
`hotfix` / `surgery`，且**用途段必须读得出这条分支在干什么**——`claude/x7f2a`
这种「谁开的 + 随机串」和没有纪律是一回事。名字像 CI 触发器的（`ci/*`、
`build/*`、`*-driver-*`、`*-success`、带 9 位以上 run-id）直接拦
（AGENTS.md §2：不要用分支触发 CI）。

闸门设在「往远端推一条新分支」这一刻，本地随便开不拦：留在远端的才是问题。

逃生口：`SKIP_BRANCH_HOOK=1 git push ...`

### 三、地址不入库（CLAUDE.md 铁律 1）

推送前跑一遍 tools/check-no-endpoints.py。这是本仓库唯一一条**碰了就是事故**的
规则：真实域名/URL/凭证一旦进了公开历史就擦不掉——改一行代码容易，重写历史难，
而且已经被人拉走的克隆里那份永远在。所以它必须在**推出去之前**拦，不能只在 CI 里
事后报警。

逃生口：`SKIP_ENDPOINT_HOOK=1 git push ...`（用它意味着你确认那不是真地址）

## 逃生口一览

    SKIP_MSG_HOOK=1       git push ...   跳过提交信息检查
    SKIP_BRANCH_HOOK=1    git push ...   跳过分支纪律检查
    SKIP_ENDPOINT_HOOK=1  git push ...   跳过地址守卫

用它意味着你**明确知道自己在跳过什么**，并且准备好向维护者解释。
"""

import os
import re
import subprocess
import sys
import time

HOOK_NAME = "pre-push"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import _branchrules                                       # noqa: E402
    import _msgrules                                          # noqa: E402
except ImportError:
    # 判据模块不在 → **放行**，不是拦下。缺一个文件就让整个仓库推不了，比它想
    # 强制的任何规则都糟糕：报错还只有一段 Python traceback，没人看得懂。
    # 常见成因：把钩子单独拷进 .git/hooks/ 时漏了这个不像钩子的文件。
    sys.stderr.write(
        "\n⚠ %s: 找不到同目录下的判据模块（_msgrules.py / _branchrules.py），"
        "本次跳过检查。\n"
        "  它们是钩子与体检脚本共用的判据，必须和钩子放在一起。\n"
        "  正确装法是让 core.hooksPath 指向整个目录：bash tools/install-hooks.sh\n"
        "  ——而不是把单个钩子文件拷进 .git/hooks/。\n\n" % HOOK_NAME)
    sys.exit(0)

# 提交信息检查只查这个时刻之后的提交（本仓库规范上线时刻）。
# 历史提交不翻旧账，否则谁 rebase 一下旧分支都会被一堆与自己无关的提交卡死。
CUTOFF_EPOCH = 1787788800          # 2026-08-27T00:00:00Z
MAX_COMMITS = 200                  # 单次推送最多查这么多（护栏不是审计）

# 分支判据在 _branchrules.py 里（与 tools/check-branch-hygiene.py 共用一份）：
# 远端只允许 main 与 <类>/<用途>，类只有 hotfix / surgery，且用途段必须读得出
# 这条分支在干什么。要改分支策略，改那一份 + AGENTS.md §0，别在这里另开一套。

RECENT_HOURS = 2.0

ENDPOINT_GUARD = "tools/check-no-endpoints.py"


def sh(*a, **kw):
    return subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, **kw)


def parse_stdin():
    """stdin: <local ref> <local sha> <remote ref> <remote sha>，逐行。

    返回 [(local_sha, branch, remote_sha)]，只含 refs/heads/ 且非删除的条目。
    全零 OID = 「不存在」；长度随仓库哈希算法变（SHA-1 40 / SHA-256 64），
    所以按「全是 0」判，别写死 40。
    """
    out = []
    for line in sys.stdin.read().split("\n"):
        parts = line.split()
        if len(parts) != 4:
            continue
        _, local_sha, remote_ref, remote_sha = parts
        if not remote_ref.startswith("refs/heads/"):
            continue
        if set(local_sha) == {"0"}:                  # 删除分支，放行
            continue
        out.append((local_sha, remote_ref[len("refs/heads/"):], remote_sha))
    return out


def remote_name():
    """git 把远端名作为第一个参数传给 pre-push。取不到就退回 origin。"""
    return sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "origin"


def new_commits(local_sha, remote_sha):
    """本次推送**新增**的提交 SHA 列表（不含合并提交）。

    已存在的分支用 remote..local，精确且不需要任何远端信息；新建分支用
    local --not --remotes=<远端>，把已经在那个远端的历史全部排除掉。远端名取
    git 传进来的参数、不写死 origin——推到第二个远端时写死会拿错排除集。
    """
    if set(remote_sha) != {"0"}:
        rng = ["%s..%s" % (remote_sha, local_sha)]
    else:
        rng = [local_sha, "--not", "--remotes=%s" % remote_name()]
    r = sh("git", "rev-list", "--no-merges",
           "--max-count=%d" % MAX_COMMITS, *rng)
    if r.returncode != 0:
        return []                                    # 算不出来就不查（fail-open）
    return [x for x in r.stdout.split() if x]


def check_messages(refs):
    """检查本次推送新增提交的信息。返回给用户看的问题列表。"""
    bad, seen = [], set()
    for local_sha, branch, remote_sha in refs:
        for sha in new_commits(local_sha, remote_sha):
            if sha in seen:          # 同一提交出现在两条被推的分支上，只报一次
                continue
            seen.add(sha)
            r = sh("git", "log", "-1", "--format=%ct%x1f%B", sha)
            if r.returncode != 0:
                continue
            ts, _, raw = r.stdout.partition("\x1f")
            try:
                if int(ts.strip()) < CUTOFF_EPOCH:   # 历史提交不翻旧账
                    continue
            except ValueError:
                continue
            probs = _msgrules.problems(raw)
            if probs:
                subj = (raw.strip().split("\n") or [""])[0][:60]
                bad.append((sha[:8], branch, subj, probs))
    return bad


def report_messages(bad):
    sys.stderr.write("\n✘ push 被 pre-push 钩子拦下：%d 个提交的信息不合规\n\n"
                     % len(bad))
    for sha, branch, subj, probs in bad:
        sys.stderr.write("  %s (%s)  %s\n" % (sha, branch, subj))
        for p in probs:
            sys.stderr.write("      · %s\n" % p.replace("\n      ", "\n        "))
        sys.stderr.write("\n")
    sys.stderr.write("  这一道查的是**本次推送新增的**提交——commit-msg 只管得住在\n"
                     "  这份克隆里做的提交，在别处提交再推进来的它看不见。\n\n")
    sys.stderr.write("  改法: git rebase -i --exec 'git commit --amend' 或重写这几条的信息\n")
    sys.stderr.write("  规则出处: CLAUDE.md「提交约定」/ AGENTS.md §1\n")
    sys.stderr.write("  确需跳过: SKIP_MSG_HOOK=1 git push ...\n\n")


def repo_root():
    r = sh("git", "rev-parse", "--show-toplevel")
    return r.stdout.strip() if r.returncode == 0 else None


def check_endpoints():
    """跑地址守卫。返回它的输出（有问题时），没问题或跑不起来返回 None。"""
    root = repo_root()
    if not root:
        return None
    guard = os.path.join(root, ENDPOINT_GUARD)
    if not os.path.isfile(guard):
        return None                                  # 守卫不在也放行
    r = sh(sys.executable, guard, cwd=root)
    if r.returncode == 0:
        return None
    return (r.stdout or "") + (r.stderr or "")


def report_endpoints(out):
    sys.stderr.write("\n✘ push 被 pre-push 钩子拦下：地址守卫不通过\n\n")
    for line in out.rstrip().split("\n"):
        sys.stderr.write("  %s\n" % line)
    sys.stderr.write("\n  规则出处: CLAUDE.md 铁律 1（任何具体地址/凭证都不入库）\n"
                     "  这一条拦在推送前而不是 CI 里，是因为进了公开历史就擦不掉。\n"
                     "  确需跳过: SKIP_ENDPOINT_HOOK=1 git push ...\n\n")


def main():
    refs = parse_stdin()
    if not refs:
        return 0

    rc = 0

    # ── 一、提交信息（§1）────────────────────────────────────
    if os.environ.get("SKIP_MSG_HOOK"):
        sys.stderr.write("pre-push: SKIP_MSG_HOOK=1，跳过提交信息检查\n")
    else:
        try:
            bad = check_messages(refs)
        except Exception:
            bad = []                                 # fail-open
        if bad:
            report_messages(bad)
            rc = 1

    # ── 三、地址不入库（铁律 1）──────────────────────────────
    if os.environ.get("SKIP_ENDPOINT_HOOK"):
        sys.stderr.write("pre-push: SKIP_ENDPOINT_HOOK=1，跳过地址守卫\n")
    else:
        try:
            ep = check_endpoints()
        except Exception:
            ep = None                                # fail-open
        if ep:
            report_endpoints(ep)
            rc = 1

    # ── 二、分支纪律（§0）────────────────────────────────────
    if os.environ.get("SKIP_BRANCH_HOOK"):
        sys.stderr.write("pre-push: SKIP_BRANCH_HOOK=1，跳过分支纪律检查\n")
        return rc

    new_branches = [b for local_sha, b, remote_sha in refs
                    if set(remote_sha) == {"0"}]
    if not new_branches:
        return rc

    problems = []
    for name in new_branches:
        problems.extend(_branchrules.problems(name))

    if not problems:
        return rc

    # 远端现状：有没有可接续的 / 2 小时内动过的
    r = sh("git", "ls-remote", "--heads", remote_name())
    existing = []
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            p = line.split()
            if len(p) == 2:
                n = p[1].replace("refs/heads/", "")
                if n != "main":
                    existing.append((p[0], n))   # 例外分支：可接续的候选

    fresh = []
    for sha, n in existing:
        t = sh("git", "log", "-1", "--format=%ct", sha)
        if t.returncode != 0:
            # 本地没有这个对象，取回来再问一次。**只写 FETCH_HEAD，不建 ref**——
            # 建出来的 ref 没人清理，越攒越多，还让被删分支的对象一直可达。
            if sh("git", "fetch", "--quiet", remote_name(), n).returncode != 0:
                continue
            t = sh("git", "log", "-1", "--format=%ct", "FETCH_HEAD")
        if t.returncode == 0 and t.stdout.strip():
            try:
                h = (time.time() - int(t.stdout.strip())) / 3600.0
                if h < RECENT_HOURS:
                    fresh.append((n, h))
            except ValueError:
                pass

    sys.stderr.write("\n✘ push 被 pre-push 钩子拦下：正在新建分支\n\n")
    for i, p in enumerate(problems, 1):
        sys.stderr.write("  %d. %s\n\n" % (i, p))

    if fresh:
        sys.stderr.write("  远端有 %.0f 小时内刚动过的分支——"
                         "AGENTS.md §0 规则三：接着用它，不许再开：\n" % RECENT_HOURS)
        for n, h in fresh:
            sys.stderr.write("      %s（%.1f 小时前）\n" % (n, h))
        sys.stderr.write("\n")
    elif existing:
        sys.stderr.write("  远端已有例外分支——AGENTS.md §0 规则二："
                         "同一时刻只该有一条：\n")
        for _, n in existing:
            sys.stderr.write("      %s\n" % n)
        sys.stderr.write("\n")
    else:
        sys.stderr.write("  本仓库默认**直接提 main**（AGENTS.md §0 规则一）：\n"
                         "      git push -u origin main\n\n")

    sys.stderr.write("  详情: python3 tools/check-branch-hygiene.py --can-branch\n")
    sys.stderr.write("  确需跳过: SKIP_BRANCH_HOOK=1 git push ...\n\n")
    return 1


if __name__ == "__main__":
    # 顶层 fail-open：检查自身出了任何意外，都**放行**并把 traceback 打出来。
    # 不这么做的话，一个 FileNotFoundError 会以退出码 1 冒出去，git 当成
    # 「检查没过」——钩子自己的 bug 就把整个仓库锁死了，而屏幕上只有一段
    # 谁也看不懂的 Python traceback。
    # （SystemExit 继承自 BaseException，不会被 except Exception 吞掉，
    #   所以 main() 正常返回的 0/1 照常生效。）
    try:
        sys.exit(main())
    except Exception:
        import traceback
        sys.stderr.write(
            "\n⚠ " + HOOK_NAME + ": 检查自身出错，本次放行。"
            "请把下面这段贴给维护者：\n")
        traceback.print_exc()
        sys.exit(0)
