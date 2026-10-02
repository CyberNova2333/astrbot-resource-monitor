#!/usr/bin/env bash
# forbid-read-path.sh — PreToolUse hook for Read / Grep（读取文件**内容**的工具通道）。
#
# 为什么需要它：
#   forbid-read-secret.sh 只解析 Bash 的 tool_input.command，而 Claude 的 Read / Grep
#   工具走的是 tool_input.file_path / tool_input.path。于是「读凭据文件」换个工具就绕过了：
#       cat  /root/.claude/settings.json   → 被 forbid-read-secret.sh 拦
#       Read /root/.claude/settings.json   → 无人拦（rev4 的覆盖缺口，实测确认）
#
# 语义与其余四个 hook 完全一致（见 _lib.sh）：
#   * 放行 = 不表态（exit 0 且不输出）
#   * 拦截 = deny JSON + exit 2
#   * hook 输入解析失败 = 按拦截（保守）
#   * 路径先 realpath 归一化再匹配（防 ../ 与软链绕过）
#
# 覆盖 Read 与 Grep：两者都能把文件**内容**带回会话。
# Glob 只回文件名、不回内容，风险等级不同，本版不覆盖（README 已记）。
#
# 注意：本 hook 自带 JSON 解析，**不调用 _lib.sh 的 get_cmd()**——那个只认
# tool_input.command，且会消费 stdin。_lib.sh 因此无需改动（缩小影响面）。
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

raw=$(python3 -c '
import json,sys
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input") or {}
    v = ti.get("file_path") or ti.get("path") or ""
    sys.stdout.write(v if isinstance(v, str) else "")
except Exception:
    sys.stdout.write("__PARSE_ERROR__")
' 2>/dev/null) || raw="__PARSE_ERROR__"
[ "$raw" = "__PARSE_ERROR__" ] && deny "[policy] 无法解析 hook 输入，按拦截处理"
[ -z "$raw" ] && pass
# 相对路径无法可靠归一，不在这里判断（Bash 侧的命令串扫描仍覆盖那种形态）
# Windows 上工具给的是带盘符的绝对路径（C:\… 或 C:/…），同样要判断，不能当相对路径放行
case "$raw" in /*|[A-Za-z]:[\\/]*) ;; *) pass ;; esac

rp=$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$raw" 2>/dev/null) || rp="$raw"
# Windows 上 realpath 给出反斜杠路径；下面的规则都按 / 写，先统一分隔符，否则一条都匹配不上
rp=${rp//\\//}

# 白名单：公钥与非机密文件。rev4 明确反对过度拦截（README 改动 11 把裸 `.env`/裸 `token`
# 从 Bash 侧拿掉，因为会挡住日常命令）。这里逐一放行，而不是整目录封死。
case "$rp" in
  *.pub|*/authorized_keys|*/known_hosts|*/known_hosts.old|*/.ssh/config|*/gnupg/pubring.kbx) pass ;;
esac

# 1) 凭据 / 私钥 / 护栏自身配置——与 forbid-read-secret.sh 的清单对齐，并补上私钥目录
SENSITIVE='(^|/)(\.git-credentials|\.netrc|\.npmrc|\.pypirc|\.cnb-auth-token|credentials|credentials\.json|hosts\.yml|tokens?\.(env|json|txt|ya?ml))$'
SENSITIVE="$SENSITIVE"'|(^|/)\.claude/(settings\.json|\.credentials\.json)$'
SENSITIVE="$SENSITIVE"'|(^|/)\.config/gh/hosts\.yml$'
SENSITIVE="$SENSITIVE"'|(^|/)\.cnb/token$'            # cnb 命令行工具的登录令牌
SENSITIVE="$SENSITIVE"'|(^|/)\.aws/credentials$'
SENSITIVE="$SENSITIVE"'|(^|/)\.docker/config\.json$'
SENSITIVE="$SENSITIVE"'|(^|/)\.ssh/'
SENSITIVE="$SENSITIVE"'|(^|/)\.gnupg/'
SENSITIVE="$SENSITIVE"'|(^|/)/proc/[^/]+/environ$'
if printf '%s' "$rp" | grep -qE "$SENSITIVE"; then
  deny "禁止用 Read/Grep 读取凭据或私钥文件（内容会进入会话）：$rp"
fi

# 2) 环境变量文件（.env / .env.local …），模板类除外
if printf '%s' "$rp" | grep -qE '(^|/)\.env(\.[^/]+)?$' \
   && ! printf '%s' "$rp" | grep -qE '\.(example|sample|template|dist)$'; then
  deny "禁止读取环境变量文件（可能含凭据）：$rp"
fi

pass
