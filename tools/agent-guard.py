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
import subprocess
import sys

# 中文 Windows 下 Python 默认按 GBK 读写标准流，而 Claude Code 收发的都是 UTF-8：
# 不统一的话，命令里一有中文就解析失败、落进下面的放行分支。
for _s in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HOOKS_DIR = "tools/githooks"


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "guardrails", "policy"))
try:
    from shell_commands import offending  # 共用解析器，随包钩子与仓库钩子保持一致。
except Exception:
    sys.stderr.write("agent-guard: 命令解析器不可用，本次跳过命令检查\n")

    def offending(cmd):
        return None


def git(*args, **kw):
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
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
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        sys.stderr.write("agent-guard: 无法解析输入，本次放行\n")
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
        note = "无法检查钩子配置，本次放行"

    try:
        why = offending(cmd)
    except Exception:
        sys.stderr.write("agent-guard: 命令检查自身失败，本次放行\n")
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
        sys.stderr.write("agent-guard: 检查自身失败，本次放行\n")
        sys.exit(0)
