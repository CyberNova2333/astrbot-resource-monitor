# -*- coding: utf-8 -*-
"""commit-msg 钩子：把 CLAUDE.md / AGENTS.md 的提交规范变成硬拦截。

装法见 tools/install-hooks.sh。拦下的三条都是文档里写死的：

  1. 标题必须是「type(scope): 中文描述」（AGENTS.md §1 一，
     Conventional 前缀为强制，没有中间地带）；
  2. 必须有 Co-authored-by trailer（CLAUDE.md 提交约定 / AGENTS.md §1 三）；
  3. 必须交代文档（AGENTS.md §1 四）——写「文档: 不影响任何文档描述」也算。

## 为什么要拦而不是提醒

同项目另一个仓库把这几条写在文档里，然后一口气进来十几个英文标题、
作者是 CI bot、没有任何 Co-authored-by 的提交。
**文档挡不住不读文档的人，钩子可以。**

## 逃生口

确实需要跳过（修 typo、纯格式调整）时，**顶格独占一行**写 [skip-hooks]。
用它意味着你**明确知道自己在跳过什么**——不要养成习惯。

要求「顶格独占一行」不是讲究格式，是两次被咬出来的：

  · 早先在全文里搜这个字符串，于是第一个**介绍这个钩子**的提交（信息里引用了
    标记本身）把自己给跳过了——凡是提到它的提交信息都会中招；
  · 改成整行匹配（允许缩进）之后仍然漏：`git commit -v` 会把 diff 附在剪刀线
    之后一并写进这个文件，而 diff 的上下文行带一个前导空格。AGENTS.md 里恰好
    有一行顶格的 [skip-hooks]（逃生口说明），于是**任何用 -v 提交且改到
    AGENTS.md 的人都会被静默放行**。

所以现在两道都做：先按剪刀线截断（-v 的 diff 与注释一律不参与判定），再要求
标记顶格独占一行。
"""

import os
import sys

HOOK_NAME = "commit-msg"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import _msgrules                                          # noqa: E402
except ImportError:
    # 判据模块不在 → **放行**，不是拦下。缺一个文件就让整个仓库提交不了/推不了，
    # 比它想强制的任何规则都糟糕：报错还只有一段 Python traceback，没人看得懂。
    # 常见成因：把钩子单独拷进 .git/hooks/ 时漏了这个不像钩子的文件。
    sys.stderr.write(
        "\n⚠ %s: 找不到同目录下的 _msgrules.py（提交信息判据），本次跳过检查。\n"
        "  它是两个钩子共用的判据模块，必须和它们放在一起。\n"
        "  正确装法是让 core.hooksPath 指向整个目录：bash tools/install-hooks.sh\n"
        "  ——而不是把单个钩子文件拷进 .git/hooks/。\n\n" % HOOK_NAME)
    sys.exit(0)


def main():
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # 判据在 _msgrules 里，与 pre-push 共用一份——两个钩子查的是同一件事，
    # 只是时刻不同（提交时 / 推送时），不该各写一遍然后慢慢长歪。
    problems = _msgrules.problems(raw, drop_comments=True)
    if not problems:
        return 0

    sys.stderr.write("\n✘ 提交被 commit-msg 钩子拦下（%d 项）：\n\n" % len(problems))
    for i, p in enumerate(problems, 1):
        sys.stderr.write("  %d. %s\n\n" % (i, p))
    sys.stderr.write("  规则出处: CLAUDE.md「提交约定」/ AGENTS.md §1\n")
    sys.stderr.write("  确需跳过: 在提交信息里**顶格独占一行**写 %s\n\n"
                     % _msgrules.SKIP)
    return 1


if __name__ == "__main__":
    # 顶层 fail-open：检查自身出了任何意外，都**放行**并把 traceback 打出来。
    # 不这么做的话，一个 FileNotFoundError 或 IndexError 会以退出码 1 冒出去，
    # git 当成「检查没过」——于是钩子自己的 bug 就把整个仓库锁死了，
    # 而屏幕上只有一段谁也看不懂的 Python traceback。
    # （SystemExit 继承自 BaseException，不会被 except Exception 吞掉，
    #   所以 main() 正常返回的 0/1 照常生效。）
    try:
        sys.exit(main())
    except Exception:
        import traceback
        sys.stderr.write(
            "\n\u26a0 " + HOOK_NAME + ": 检查自身出错，本次放行。"
            "请把下面这段贴给维护者：\n")
        traceback.print_exc()
        sys.exit(0)
