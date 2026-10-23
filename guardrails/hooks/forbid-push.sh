#!/usr/bin/env bash
# forbid-push.sh — PreToolUse hook for Bash，命中 `git … push`（快速预防层）。权威 refs/签名检查在 git pre-push。
# rev4: 放行不输出 allow; 拦 --no-verify; 补上 Claude Code 实际使用的形态 `git push -u origin claude/xxx`(rev3 只认 HEAD:claude/ 形态)。
# R5 = 禁推一切 Agent 分支(前缀表来自 policy.agent_branch_prefixes)。不做 main/强推保护——那是托管平台的活(CNB 的保护分支与推送管控、GitHub 的 ruleset)。
set -uo pipefail
. "$(dirname "$0")/_lib.sh"
cmd=$(get_cmd)
[ "$cmd" = "__PARSE_ERROR__" ] && warn_pass "无法解析 hook 输入"
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
check_command "$cmd" push "$tmp"
[ "$(engine_content "$cmd" "$tmp")" = "pass" ] && pass
deny "[policy] $(tr '\n' ' ' <"$tmp")"
