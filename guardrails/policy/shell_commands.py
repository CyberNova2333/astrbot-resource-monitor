"""Shell 命令解析共用层：引号与选项值不能被当作命令或开关。"""
import re
import shlex


def without_heredoc_bodies(command):
    """Here-doc 是输入数据；终止符之后才重新开始解释命令。

    只认引号外的 << / <<-，保留头部的真实命令。未终止的 here-doc 也不
    将正文重新解释成命令，避免文档/脚本内容中的示例被误拦。
    """
    pending, output, quote = [], [], None
    for line in command.splitlines(keepends=True):
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.rstrip("\r\n")
            if (candidate.lstrip("\t") if strip_tabs else candidate) == delimiter:
                pending.pop(0)
            output.append("\n" if line.endswith("\n") else "")
            continue
        output.append(line)
        escaped, index = False, 0
        while index < len(line):
            char = line[index]
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == "#" and (index == 0 or line[index - 1].isspace()):
                break
            elif line.startswith("<<<", index):
                index += 2  # here-string 没有随后待消费的正文。
            elif line.startswith("<<", index):
                start = index + 2
                strip_tabs = line[start:start + 1] == "-"
                if strip_tabs:
                    start += 1
                lexer = shlex.shlex(line[start:], posix=True, punctuation_chars=";&|<>()")
                lexer.whitespace_split = True
                try:
                    delimiter = next(lexer)
                except (ValueError, StopIteration):
                    delimiter = None
                if delimiter is not None:
                    pending.append((delimiter, strip_tabs))
                index = start - 1
            index += 1
    return "".join(output)


def split_segments(cmd):
    """只在引号外分段；引号里的示例和分号都是参数，不是新命令。"""
    cmd = cmd.replace("\\\n", "")
    cmd = without_heredoc_bodies(cmd)
    parts, current, quote, escaped, comment = [], [], None, False, False
    for char in cmd:
        if comment:
            if char == "\n":
                parts.append("".join(current))
                current, comment = [], False
            else:
                current.append(char)
        elif escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            current.append(char)
            escaped = True
        elif quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == "#" and (not current or current[-1].isspace()):
            comment = True
            current.append(char)
        elif char in ";|&\n":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    for seg in parts:
        try:
            yield shlex.split(seg, comments=True)
        except ValueError:
            # 不完整的 shell 不能靠丢掉引号来猜测，否则会把消息正文当命令。
            continue


def command_args(tokens):
    """定位实际命令，允许常见环境赋值/包装器，不搜索任意参数中的 git。"""
    tokens = list(tokens)
    while tokens and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])
                      or tokens[0] in ("command", "exec", "env", "!", "then", "do", "if")):
        tokens.pop(0)
    if tokens and tokens[0] == "--":
        tokens.pop(0)
    if not tokens or tokens[0].replace("\\", "/").rsplit("/", 1)[-1] not in ("git", "git.exe"):
        return []
    return tokens[1:]


def noverify_option(args, sub):
    """跳过消息、路径等选项值；只识别真正传给 commit/push 的开关。"""
    takes_value = {"--message", "--file", "--reuse-message", "--reedit-message",
                   "--fixup", "--squash", "--author", "--date", "--template",
                   "--cleanup", "--trailer", "--pathspec-from-file", "--repo",
                   "--receive-pack", "--exec", "--push-option"}
    short_values = "mFCct" if sub == "commit" else "o"
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            break
        if token == "--no-verify":
            return token
        if token in takes_value:
            i += 2
            continue
        if token.startswith("-") and not token.startswith("--"):
            for pos, flag in enumerate(token[1:], 1):
                if sub == "commit" and flag == "n":
                    return token + "（commit 的 -n 就是 --no-verify）"
                if flag in short_values:
                    if pos == len(token) - 1:
                        i += 1
                    break
        i += 1
    return None


def git_commands(cmd):
    """返回实际执行的 Git 子命令、参数和逐项配置覆盖。"""
    for toks in split_segments(cmd):
        rest = command_args(toks)
        if not rest:
            continue
        sub, configs = None, {}
        j = 0
        while j < len(rest):                 # 跳过 git 自己的全局选项
            t = rest[j]
            if t == "-c" and j + 1 < len(rest):
                key, _, value = rest[j + 1].partition("=")
                configs[key.strip().lower()] = value
                j += 2
                continue
            if t in ("-C", "--git-dir", "--work-tree", "--namespace", "--config-env"):
                if t == "--config-env" and j + 1 < len(rest):
                    configs[rest[j + 1].split("=", 1)[0].lower()] = None
                j += 2
                continue
            if t.startswith("-"):
                if t.startswith("-c"):
                    key, _, value = t[2:].partition("=")
                    configs[key.lower()] = value
                if t.startswith("--config-env="):
                    configs[t.split("=", 2)[1].lower()] = None
                j += 1
                continue
            sub = t
            rest = rest[j + 1:]
            break
        if sub:
            yield sub, rest, configs


def offending(cmd):
    """返回被拦下的理由（字符串），没问题则返回 None。"""
    for sub, rest, configs in git_commands(cmd):
        if sub not in ("commit", "push"):
            continue
        if "core.hookspath" in configs:
            return "-c core.hooksPath=…（把钩子目录换掉）"
        why = noverify_option(rest, sub)
        if why:
            return why
    return None


def options(args, sub):
    """只暴露选项本身与其值，消息/路径内容不会被重新分词。"""
    takes_value = {"--message", "--file", "--reuse-message", "--reedit-message",
                   "--fixup", "--squash", "--author", "--date", "--template",
                   "--cleanup", "--trailer", "--pathspec-from-file", "--repo",
                   "--receive-pack", "--exec", "--push-option"}
    short_values = "mFCct" if sub == "commit" else "o"
    i, positional = 0, False
    while i < len(args):
        token = args[i]
        if token == "--" and not positional:
            positional = True
        elif token.startswith("--") and not positional:
            key, separator, value = token.partition("=")
            if not separator and key in takes_value:
                i += 1
                value = args[i] if i < len(args) else ""
            yield key, value
        elif token.startswith("-") and not positional:
            for index, flag in enumerate(token[1:], 1):
                value = ""
                if flag in short_values:
                    value = token[index + 1:]
                    if not value:
                        i += 1
                        value = args[i] if i < len(args) else ""
                    yield "-" + flag, value
                    break
                yield "-" + flag, value
        else:
            yield "", token
        i += 1


def inspect_command(command, target, policy):
    """随包快速钩子只判实际选项；签名、作者与内容仍由正式 Git 钩子复验。"""
    matched = False
    for sub, args, configs in git_commands(command):
        if sub != target:
            continue
        matched = True
        if "core.hookspath" in configs or noverify_option(args, sub):
            return "violation", "禁止绕过 Git 钩子"
        if sub == "commit":
            for key, value in configs.items():
                if key == "commit.gpgsign" and (value is None or value.lower() in ("false", "no", "off", "0")):
                    return "violation", "禁止关闭提交签名"
                if key == "gpg.format" and value != "ssh":
                    return "violation", "提交要求 SSH 签名"
                if key == "user.email" and value and any(p.casefold() in value.casefold() for p in policy['agent_provider_emails']):
                    return "violation", "作者必须使用人类贡献者身份"
            for key, value in options(args, sub):
                if key == "--no-gpg-sign":
                    return "violation", "禁止关闭提交签名"
                if key == "--author" and any(p.casefold() in value.casefold() for p in policy['agent_provider_emails']):
                    return "violation", "作者必须使用人类贡献者身份"
        elif sub == "push":
            positionals = [value for key, value in options(args, sub) if not key]
            prefixes = tuple(p.casefold() for p in policy['agent_branch_prefixes'])
            for refspec in positionals[1:]:  # 第一个位置参数是远端。
                destination = refspec.lstrip('+').rsplit(':', 1)[-1].removeprefix('refs/heads/')
                if destination.casefold().startswith(prefixes):
                    return "violation", "禁止推送到 Agent 命名分支"
    return ("match", "") if matched else ("pass", "")


def main():
    import json
    import sys
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        with open(sys.argv[2], encoding="utf-8") as source:
            policy = json.load(source)
        status, reason = inspect_command(sys.stdin.read(), sys.argv[1], policy)
    except Exception as exc:
        status, reason = "error", "命令检查未完成：" + type(exc).__name__
    print(status)
    if reason:
        print(reason, file=sys.stderr)


if __name__ == '__main__':
    main()
