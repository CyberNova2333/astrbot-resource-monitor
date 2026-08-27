#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse 钩子（matcher: Bash）—— 让 tools/githooks/ 里的 git 钩子**自动生效**。

Claude Code 与 Codex CLI 都支持项目内的 PreToolUse 钩子，且都是「跟着仓库走、
克隆下来就加载」的。git 自己的钩子不行：`core.hooksPath` 是每份克隆的本地配置，
**没法从入库文件里设**——这是 git 有意为之的安全设计（否则 clone 一个仓库就等于
执行任意代码）。所以才有 tools/install-hooks.sh 那个手动步骤。

本脚本把那个手动步骤消掉：

    .claude/settings.json  →  PreToolUse(Bash)  ┐
                                                ├→ 本脚本
    .codex/config.toml     →  PreToolUse(Bash)  ┘

PreToolUse 在命令**执行之前**跑，所以这里把 core.hooksPath 设好之后，紧接着那条
`git commit` / `git push` 已经会走 tools/githooks/。也就是说：

  · 装了本仓库的 Claude 或 Codex 跑过**任意一条** Bash 命令 → 该克隆的 git 钩子
    从此长期生效，之后连人类手敲的 commit 也一并受管；
  · 逻辑不重复实现——真正的判定仍然只在 tools/githooks/ 里那两个 git 钩子中，
    本脚本只负责「让它们接上电」。

## 唯一在这里直接拦的事：绕过 git 钩子

git 钩子唯一挡不住的就是绕过 git 钩子本身。两条路都拦：

  · `git commit --no-verify` / `-n`、`git push --no-verify`；
  · `git -c core.hooksPath=... commit/push`（把钩子目录换掉，效果一样且更隐蔽）。

想跳过检查请用文档里写明的逃生口（提交信息里顶格独占一行的 [skip-hooks]、
或 SKIP_BRANCH_HOOK=1），那两个至少会在输出里留下痕迹。

**这不是安全边界**，是防手滑与防偷懒的护栏。真想绕总归绕得过去（环境变量、
临时脚本、直接写 .git/）。判定的目标是「常见写法一个不漏、正常提交一个不误伤」，
不是「堵死一切」。

判定改用 shlex 分词而不是在原始命令文本上跑正则——正则那版同时漏和误伤：
`git -c user.name=x commit --no-verify` 漏（`git` 与 `commit` 之间隔了全局选项）、
反斜杠续行漏（按 \n 切段切断了）、而 `git commit -m "调整 -n 参数的说明"` 却被
误拦（引号里的 -n 被当成了选项）。分词之后这三种全部正确。

## 健壮性

任何内部异常一律放行（exit 0，fail-open）。钩子自身绝不能挡住正常工作——
这条比它想强制的任何规则都优先。
"""

import json
import os
import re
import shlex
import subprocess
import sys

HOOKS_DIR = "tools/githooks"
# commit 的 -n 是 --no-verify，可以并进组合短选项（-an）。
# push 的 -n 是 --dry-run，无害，所以只在 commit 上认 -n。
COMMIT_SHORT_NOVERIFY = re.compile(r"^-[A-Za-z]*n[A-Za-z]*$")


def split_segments(cmd):
    """按 shell 分隔符切段并分词。分不了词的段退回朴素 split（fail-open）。"""
    cmd = re.sub(r"\\\n", " ", cmd)          # 先接上反斜杠续行，否则切段会切断它
    for seg in re.split(r"&&|\|\||[;|\n]", cmd):
        try:
            yield shlex.split(seg)
        except ValueError:                   # 引号不配对等
            yield seg.split()


def offending(cmd):
    """返回被拦下的理由（字符串），没问题则返回 None。"""
    for toks in split_segments(cmd):
        try:
            i = next(k for k, t in enumerate(toks)
                     if t == "git" or t.endswith("/git"))
        except StopIteration:
            continue
        rest, sub, hooks_off = toks[i + 1:], None, False
        j = 0
        while j < len(rest):                 # 跳过 git 自己的全局选项
            t = rest[j]
            if t == "-c" and j + 1 < len(rest):
                if rest[j + 1].split("=", 1)[0].strip().lower() == "core.hookspath":
                    hooks_off = True
                j += 2
                continue
            if t.startswith("-"):
                if t.lower().startswith("-ccore.hookspath"):
                    hooks_off = True
                j += 1
                continue
            sub = t
            rest = rest[j + 1:]
            break
        if sub not in ("commit", "push"):
            continue
        if hooks_off:
            return "-c core.hooksPath=…（把钩子目录换掉）"
        for t in rest:
            if t == "--no-verify":
                return "--no-verify"
            if sub == "commit" and COMMIT_SHORT_NOVERIFY.match(t):
                return t + "（commit 的 -n 就是 --no-verify）"
    return None


def git(*args, **kw):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          timeout=10, **kw)


def ensure_hooks_path(cwd):
    """把 core.hooksPath 指向 tools/githooks。返回给用户看的一行说明，或 None。

    cwd 用钩子输入里的那个，不是本进程的——命令可能在别的仓库/子目录里跑，
    按本进程的 cwd 判会认错仓库。
    """
    top = git("rev-parse", "--show-toplevel", cwd=cwd)
    if top.returncode != 0:
        return None                                   # 不在 git 仓库里
    root = top.stdout.strip()
    if not os.path.isdir(os.path.join(root, HOOKS_DIR)):
        return None                                   # 不是本仓库

    cur = git("config", "--get", "core.hooksPath", cwd=root).stdout.strip()
    if cur == HOOKS_DIR:
        return None                                   # 已生效，安静通过
    if cur:
        # 别人自己配了别的钩子目录——不覆盖，只提醒。强制不该踩掉别人的设置。
        return ("提醒：core.hooksPath 当前是 %r，不是本仓库的 %s。"
                "本仓库的提交/分支检查不会生效；"
                "确认无误可跑 bash tools/install-hooks.sh。" % (cur, HOOKS_DIR))

    for h in ("commit-msg", "pre-push"):
        p = os.path.join(root, HOOKS_DIR, h)
        if os.path.exists(p):
            try:
                os.chmod(p, os.stat(p).st_mode | 0o111)
            except OSError:
                pass
    if git("config", "core.hooksPath", HOOKS_DIR, cwd=root).returncode != 0:
        return None
    return ("已把本克隆的 core.hooksPath 指向 %s —— "
            "提交信息规范与分支纪律（CLAUDE.md / AGENTS.md）从现在起会真的拦人。"
            % HOOKS_DIR)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    cmd = ((data.get("tool_input") or {}).get("command") or "")
    if "git" not in cmd:
        return 0
    cwd = data.get("cwd") or None
    if cwd and not os.path.isdir(cwd):
        cwd = None

    try:
        note = ensure_hooks_path(cwd)
    except Exception:
        note = None                                   # fail-open

    try:
        why = offending(cmd)
    except Exception:
        why = None                                    # fail-open
    if why:
        sys.stderr.write(
            "\n✘ 不要绕过 git 钩子（检出：%s）。\n\n"
            "  那两个钩子（tools/githooks/）执行的是 CLAUDE.md「提交约定」与\n"
            "  AGENTS.md §0/§1 的硬规则，绕过它们等于绕过规则本身，而且不留痕迹。\n\n"
            "  确实需要跳过时用文档写明的逃生口——它们会在输出里留下记录：\n"
            "    提交信息里**顶格独占一行**写 [skip-hooks]   跳过提交信息检查\n"
            "    SKIP_BRANCH_HOOK=1 git push ...             跳过分支纪律检查\n\n"
            % why)
        return 2                                      # exit 2 = 拒绝，理由回喂给模型

    if note:
        sys.stderr.write("agent-guard: %s\n" % note)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
