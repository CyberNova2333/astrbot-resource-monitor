#!/usr/bin/env bash
# 安装本仓库的 git 钩子。
#
# **多数情况用不上这个脚本**：.claude/settings.json 与 .codex/config.toml 各注册了
# 一个 PreToolUse(Bash) 钩子指向 tools/agent-guard.py，它会在第一条 Bash 命令执行前
# 自动做完下面这件事。只有「Claude 与 Codex 都没碰过这份克隆」（比如人类直接
# git clone 下来手敲）时才需要手动跑一次。
#
# 钩子放在 tools/githooks/（受版本控制），靠 core.hooksPath 指过去——
# 这样它们跟着仓库走，而不是躺在每个人各自的 .git/hooks 里自生自灭。
#
#   tools/githooks/commit-msg    提交信息规范（中文 / Co-authored-by / 文档:）
#   tools/githooks/pre-push      推送时的提交信息复查（§1）+ 分支纪律（§0）
#
# 这两个是 POSIX sh 的启动层，只负责找一个能用的 Python 3；真正的实现分别在
# commit_msg.py / pre_push.py，判据在两者共用的 _msgrules.py。分层是为了
# Windows：那边 python3 常常不在 PATH，而钩子跑不起来会让**合规的提交也提不了**。
#
# Windows 用户不想开 Git Bash 的话，跑 tools\install-hooks.cmd，等价。
#
# 跳过单次检查：
#   提交信息里顶格独占一行写 [skip-hooks]  跳过 commit-msg
#   SKIP_MSG_HOOK=1    git push ...  跳过 pre-push 的提交信息检查
#   SKIP_BRANCH_HOOK=1 git push ...  跳过 pre-push 的分支纪律检查
#
# 卸载：git config --unset core.hooksPath

set -euo pipefail
cd "$(dirname "$0")/.."

# 只给真正的钩子加执行位。下划线开头的是共用模块（_msgrules.py），
# git 不会去执行它，也就没必要标成可执行。
# 用 || true 兜住：set -e 之下少一个钩子文件会让脚本在设 hooksPath 之前就退出，
# 反而什么都没装上。
chmod +x tools/githooks/commit-msg tools/githooks/pre-push 2>/dev/null || true
git config core.hooksPath tools/githooks

echo "✔ 已把 core.hooksPath 指向 tools/githooks"
echo
echo "  生效的钩子："
printf "    %-12s %s\n" "commit-msg" "提交信息规范（中文 / Co-authored-by / 文档:）"
printf "    %-12s %s\n" "pre-push"   "推送时复查提交信息 + 分支纪律"
echo
echo "  自检： git config --get core.hooksPath"
