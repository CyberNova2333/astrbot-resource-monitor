#!/usr/bin/env bash
# forbid-commit.sh — PreToolUse hook for Bash，命中 `git … commit`（快速预防层）。
# 权威的 msg/作者/签名检查在 git 钩子；这里: 作者邮箱 + 命令串扫描 + 拦绕过护栏的开关。
# rev4: 放行不输出 allow; 拦 --no-verify/-n/--no-gpg-sign/-c core.hooksPath=/-c commit.gpgsign=false/--author=…noreply。
set -uo pipefail
. "$(dirname "$0")/_lib.sh"
cmd=$(get_cmd)
[ "$cmd" = "__PARSE_ERROR__" ] && warn_pass "无法解析 hook 输入"
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
check_command "$cmd" commit "$tmp"
email=$(git config user.email 2>/dev/null || echo '')
case "$(printf '%s' "$email" | tr 'A-Z' 'a-z')" in *noreply@anthropic.com|*noreply@openai.com|*noreply@deepseek.com|*noreply@moonshot.cn) deny "作者邮箱是 Agent 提供的 noreply（$email）→ 禁止 Agent 自己署名，须人类贡献者 + Co-authored-by: <Agent>";; esac
[ "$(engine_content "$cmd" "$tmp")" = "pass" ] && pass
deny "[policy] $(tr '\n' ' ' <"$tmp")"
