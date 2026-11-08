#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守住铁律 1：**任何具体地址、凭证都不进版本库**。

用法：python3 tools/check-no-endpoints.py [--verbose] [--commits-stdin]
退出码 0 = 干净，1 = 确认违规，2 = 检查自身失败（钩子提示并放行）。

## 为什么这条要用守卫钉，而不是写在文档里

这个仓库的产物是**监控插件**，它要探的每一个地址都是线上真实地址。写代码时把
一条 URL 直接贴进源码是最省事的做法，而且当场就能跑通——没有任何即时反馈告诉你
做错了。等发现时，那条地址已经在公开历史里：

  · 改一行代码容易，**重写历史难**，而且已经被人拉走的克隆里那份永远在；
  · 地址泄露的代价不对称——写错顶多插件不工作，写对了就是把线上拓扑公开。

所以判据是「拦在推出去之前」，由 pre-push 钩子调用本脚本；CI 里再复验一次。

## 判据：会不会跟着部署走

  · 会跟着部署走的（入口地址、线路域名、会话 ID、Token）→ **一律不入库**，
    运行时从本地配置 + 线上配置现场取（README「配置来源」）；
  · 不跟着部署走的（第三方文档站、包索引、协议链接、占位符域名）→ 放行。

占位符统一用 `example.test`：RFC 6761 保留给测试用，**永远不会解析到真东西**，
所以不存在「示例配置被人照抄后打到某个真实主机上」这种事。

## 宁可漏报也不误报

判据只认下面几类**确定**的形状。一个会拦下正常代码的检查比没有检查更糟——
被误伤过一次的人，下次就会习惯性加 SKIP_ENDPOINT_HOOK=1，那时守卫就等于没有。
"""

import io
import os
import re
import subprocess
import sys
import tokenize

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ── 允许出现的主机 ────────────────────────────────────────────────
#
# 判据是「它不跟着我们的部署走」：第三方文档站、包索引、协议/规范链接、
# 保留给示例用的域名。除此之外的主机名一律拦。
ALLOWED_HOSTS = (
    # 占位符（RFC 6761 / RFC 2606 保留域名，不解析到真实主机）
    "example.test", "example.com", "example.org", "example.net",
    "invalid", "localhost",
    # 第三方：框架与生态的文档/源码/包索引
    "astrbot.app", "docs.astrbot.app", "github.com", "github.io", "raw.githubusercontent.com",
    "pypi.org", "files.pythonhosted.org", "python.org", "docs.python.org",
    "www.python.org",
    # 文档构建的公开包索引与锁文件中的上游资助元数据，不是探测目标。
    "registry.npmjs.org", "opencollective.com", "tidelift.com",
    # 协议与规范
    "www.rfc-editor.org", "datatracker.ietf.org", "developer.mozilla.org",
    # 许可证
    "www.gnu.org", "www.fsf.org", "spdx.org", "opensource.org", "scripts.sil.org",
    # 本机回环
    "127.0.0.1", "0.0.0.0", "::1",
)

# 允许出现的邮箱域（署名 trailer 用，AGENTS.md §1 三）
ALLOWED_MAIL_DOMAINS = ("anthropic.com", "openai.com", "moonshot.cn",
                        "deepseek.com", "google.com", "users.noreply.github.com",
                        "example.test", "example.com")

# 整份豁免的文件：许可证原文、以及本脚本自己（它必须写得出这些模式）。
EXEMPT_PATHS = ("LICENSE", "LICENSE.additional-terms", "THIRD-PARTY-NOTICES.md",
                "tools/check-no-endpoints.py")


def is_exempt(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    norm = path.replace("\\", "/")
    if norm.startswith("docs-site/.vitepress/theme/vendor/") or norm.startswith("docs-site/.vitepress/theme/fonts/"):
        return True
    return False

# 只扫这些后缀（文本且我们真会往里写地址的）。二进制与资源不扫。
SCAN_SUFFIXES = (".py", ".md", ".json", ".jsonc", ".yaml", ".yml", ".toml",
                 ".sh", ".cmd", ".txt", ".cfg", ".ini", ".html", ".css", ".js",
                 ".example", ".env")

# 绝不入库的**真实**本地配置（样例是 *.example.*，不在此列）。
# 按**仓库根的完整路径**判，不按文件名：`.codex/config.toml` 是 Codex 的项目级
# 配置，必须入库——按文件名判会把它一起拦下，那正是「会误伤的检查」。
FORBIDDEN_TRACKED = ("config.toml", "config.json", "config.yaml", "config.yml",
                     ".env", "conf/config.toml", "conf/config.json")

URL = re.compile(r"\bhttps?://(\[[^\s/\"'`)}>,;]+|[^\s/\"'`)\]}>,;]+)", re.I)
# 裸主机名：至少两段 + 已知 TLD。三处刻意收紧，都是被误伤换来的：
#
#   · 后缀表只放**真会被写进来**的那些——宁可漏一个陌生 TLD，也不要把
#     `astrbot.api.star`、`config.json` 这种模块名和文件名当成主机；
#   · **区分大小写**（不加 re.I）：源码里的主机名一律小写，而 `Severity.INFO`
#     这种常量会被大小写不敏感的版本当成 `.info` 域名拦下来；
#   · 后面紧跟 `(` 的不算：那是方法调用（`logger.info(...)`），不是地址。
#     `info` 同时从后缀表里去掉了——它与 Python 里最常见的属性名撞车，
#     留着它的收益远小于误伤。
#
# 一个会拦下正常代码的检查比没有检查更糟：被误伤过一次的人，下次就会习惯性
# 加 SKIP_ENDPOINT_HOOK=1，那时守卫就等于不存在。
BARE_HOST = re.compile(
    r"(?<![\w.@/-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"(?:com|net|org|io|dev|app|top|cn|xyz|site|club|tv|test|invalid))"
    r"(?![\w-]|\()")
EMAIL = re.compile(r"[\w.+-]+@([\w.-]+\.[a-z]{2,})", re.I)
VERSION_LINE = re.compile(r"版本|version|\bver\b|\bv\d|tag", re.I)
# 裸 IPv4 字面量。公网地址同样是「会跟着部署走」的东西，而它没有 TLD，
# 上面那条主机名规则看不见它。四段都要求 ≤255、后面不接更多点号；
# 不可路由的那些在 host_allowed 里放行。
#
# 四段版本号（`1.2.3.4`）与它撞形状，所以**整行提到版本就跳过这一条**——
# 一个会拦下正常提交的守卫，用不了几天就会被人习惯性加逃生口跳过。
# 代价是漏掉「写在版本说明那一行里的真 IP」，那是可以接受的漏报。
BARE_IPV4 = re.compile(
    r"(?<![\w.:-])((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})(?![\w.-])")
# 凭证形状：这几种一眼可辨，不会误伤
SECRETS = (
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥"),
)

PLACEHOLDER_CHARS = "…<>{}\\"


def host_allowed(host):
    host = host.strip().rsplit("@", 1)[-1]
    if host.startswith("["):
        # 损坏 URL 的回归夹具也会故意缺括号；已允许的示例域名不会因此变成真地址。
        example = host.strip("[]").lower().rstrip(".")
        if ":" not in example and any(
                example == h or example.endswith("." + h) for h in ALLOWED_HOSTS):
            return True
        # 方括号是 IPv6 语法，不能当作任意地址的占位符豁免。
        bracketed = re.fullmatch(r"\[([^\[\]]+)\](?::[0-9]+)?", host)
        if not bracketed:
            return False
        literal = bracketed.group(1)
        return ":" in literal and _is_unroutable_literal(literal)
    if host.count(":") == 1:
        host, _ = host.rsplit(":", 1)
    if host == "%s":
        return True                      # 只允许完整主机占位符，不豁免含 %s 的真实域名。
    try:
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return False
    if not host or any(c in host for c in PLACEHOLDER_CHARS):
        return True                      # <主域> / {base} / … 这类占位符
    if any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        return True
    return _is_unroutable_literal(host)


def _is_unroutable_literal(host):
    """回环/私网/链路本地的**字面量 IP** 放行。

    理由：这类地址不可能是一条对外分发线路——它们不路由到公网，写下来不构成
    「把线上拓扑公开」。而 SSRF 守卫（probes.check_mirror_targets）恰恰要在
    注释与测试里把它们**指名道姓**地写出来，否则那条守卫自己没法解释、也没法测。

    残留风险是有人拿它写内网主机地址；判据只放行 IP 字面量、不放行任何域名，
    所以能漏出去的最多是一个不可路由的网段号。
    """
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # inet_aton 的旧式数字写法在各平台处理不同；自行解析，绝不请求 DNS。
        # 前 n-1 段各占一个字节，最后一段占剩余字节（如 127.1）。
        parts = host.split(".")
        if not 1 <= len(parts) <= 4:
            return False
        numbers = []
        for part in parts:
            if re.fullmatch(r"0[xX][0-9a-fA-F]+", part):
                number = int(part[2:], 16)
            elif re.fullmatch(r"[0-9]+", part):
                try:
                    number = int(part, 8 if len(part) > 1 and part.startswith("0") else 10)
                except ValueError:
                    return False
            else:
                return False
            numbers.append(number)
        if any(number > 255 for number in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(parts)):
            return False
        value = numbers[-1] + sum(number << (8 * (3 - index)) for index, number in enumerate(numbers[:-1]))
        ip = ipaddress.IPv4Address(value)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def tracked_files():
    return [f for f in git_text("ls-files", "-z").split("\0") if f]


def git_text(*args):
    result = subprocess.run(["git", *args], capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError("无法读取 Git 对象（%s）" % args[0])
    return result.stdout.decode("utf-8", "replace")


def python_text_lines(text):
    """保留字符串和注释的位置，模块名/属性表达式不是部署地址。

    不按整行豁免 import：同一行的字符串、注释仍需检查。遇到不完整源码时
    保留未能解析的部分，不能靠语法错误把后面的地址藏起来。
    """
    lines = text.splitlines(keepends=True)
    masked = [list(line) for line in lines]
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type not in (tokenize.NAME, tokenize.OP):
                continue
            (row, col), (_, end) = token.start, token.end
            if row <= len(masked):
                masked[row - 1][col:end] = " " * (end - col)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return ["".join(line) for line in masked]


def scan_line(path, lineno, line, out, *, host_line=None):
    if host_line is None:
        host_line = "".join(python_text_lines(line)) if path.endswith(".py") else line
    for m in URL.finditer(line):
        if not host_allowed(m.group(1)):
            out.append((path, lineno, "绝对地址 %s" % m.group(0)[:72],
                        "改成从配置读；文档里写 https://api.example.test/ 这类占位符"))
    for m in EMAIL.finditer(line):
        dom = m.group(1).lower()
        if not any(dom == d or dom.endswith("." + d) for d in ALLOWED_MAIL_DOMAINS):
            out.append((path, lineno, "邮箱 %s" % m.group(0),
                        "收件人走部署侧配置，不入库"))
    version_ish = VERSION_LINE.search(line) is not None
    for m in BARE_IPV4.finditer(line):
        if version_ish:
            break
        if not host_allowed(m.group(1)):
            out.append((path, lineno, "IP 地址 %s" % m.group(1),
                        "地址一律运行时取，源码与文档里不出现"))
    for m in BARE_HOST.finditer(host_line):
        host = m.group(1)
        if EMAIL.search(line) and ("@" + host) in line:
            continue                     # 已按邮箱判过
        if not host_allowed(host):
            out.append((path, lineno, "主机名 %s" % host,
                        "换成 example.test 占位符，真值由部署侧配置给"))
    for pat, what in SECRETS:
        if pat.search(line):
            # 一行里命中多条凭证规则（ghp_ 同时匹配「PAT」与更宽的那条）只报一次：
            # 同一处报两遍会让人以为有两个问题。
            out.append((path, lineno, "疑似%s" % what,
                        "凭证只走部署侧配置/CI secret，任何情况都不入库"))
            break


def scan_text(path, text, problems, label=None):
    lines = text.splitlines()
    host_lines = python_text_lines(text) if path.endswith(".py") else lines
    for number, line in enumerate(lines, 1):
        scan_line(label or path, number, line, problems, host_line=host_lines[number - 1])


def scan_path(path, problems, label=None):
    if path in FORBIDDEN_TRACKED:
        problems.append((label or path, 0, "真实配置文件被纳入版本控制",
                         "本地配置不入库；样例请命名为 *.example.*"))
    # 路径不是 Python 代码；带源码后缀也不能将其中的域名当 import 忽略。
    scan_line((label or path) + " [path]", 0, path, problems)


def scan_commits(commits, problems):
    """检查实际新增提交，而非可能与暂存区/推送分支不同的工作区。

    每个提交检查新增/修改的 blob、路径及完整消息；根提交和合并提交也覆盖。
    同一 blob 在同一路径只扫一次，已删除的旧泄露仍会在引入它的提交被发现。
    """
    seen = set()
    for sha in dict.fromkeys(commits):
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha):
            raise ValueError("提交对象编号无效")
        scan_text("commit-message", git_text("log", "-1", "--format=%B", sha),
                  problems, sha[:12] + " [message]")
        changed = set(git_text("diff-tree", "--root", "-r", "-m", "--no-commit-id",
                               "--name-only", "--diff-filter=ACMRT", "-z", sha).split("\0"))
        for record in git_text("ls-tree", "-r", "-z", "--full-tree", sha).split("\0"):
            if not record:
                continue
            meta, path = record.split("\t", 1)
            if path not in changed:
                continue
            _, kind, oid = meta.split()
            label = sha[:12] + ":" + path
            scan_path(path, problems, label)
            if kind != "blob" or is_exempt(path) or (path, oid) in seen:
                continue
            seen.add((path, oid))
            text = git_text("cat-file", "blob", oid)
            if "\0" not in text:
                scan_text(path, text, problems, label)


def main(argv):
    verbose = "--verbose" in argv
    problems = []
    if "--commits-stdin" in argv:
        commits = sys.stdin.read().split()
        scan_commits(commits, problems)
        count = "%d 个新增提交" % len(set(commits))
    else:
        files = tracked_files()
        for path in files:
            scan_path(path, problems)
            if is_exempt(path) or not path.endswith(SCAN_SUFFIXES):
                continue
            if not os.path.exists(path):
                continue  # 工作区删除的文件不在工作区自检范围，推送仍检查历史对象。
            with open(path, encoding="utf-8", errors="replace") as source:
                scan_text(path, source.read(), problems)
        count = "%d 个受版本控制的文件" % len(files)

    # 同一处可能被多条规则命中（URL 与裸主机名会重叠），去重后再报。
    seen, deduped = set(), []
    for item in problems:
        key = (item[0], item[1], item[2])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    problems = deduped

    if verbose:
        print("扫描 " + count)

    if not problems:
        print("✔ 地址守卫通过：没有发现会跟着部署走的地址或凭证")
        return 0

    print("✘ 地址守卫不通过：%d 处（CLAUDE.md 铁律 1）\n" % len(problems))
    for path, lineno, what, how in problems:
        where = "%s:%d" % (path, lineno) if lineno else path
        print("  %s\n      %s\n      → %s\n" % (where, what, how))
    print("  真值一律运行时取：本地配置给入口，线上配置给其余（README「配置来源」）。")
    print("  占位符统一用 example.test —— 它是保留域名，永远不会解析到真东西。")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:
        print("地址守卫自身失败：%s；本次检查未完成" % type(exc).__name__, file=sys.stderr)
        sys.exit(2)
