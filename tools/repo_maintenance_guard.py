#!/usr/bin/env python3
"""提交与推送的离线安全检查；只读取 Git 对象，不读取未暂存文件。"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

VERSION = 2
MAX_BLOB = 8 * 1024 * 1024
TYPES = r'feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert|data'
SUBJECT = re.compile(r'^(?:' + TYPES + r')(?:\([A-Za-z0-9_./-]+\))?!?: \S.*$')
AUTO = ('Merge ', 'Revert ', 'fixup! ', 'squash! ')
PATTERNS = [
    ('private-key', re.compile(rb'-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')),
    ('github-token', re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')),
    ('aws-access-key', re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('slack-token', re.compile(rb'\bxox[baprs]-[A-Za-z0-9-]{20,}\b')),
    ('stripe-live-key', re.compile(rb'\bsk_live_[A-Za-z0-9]{20,}\b')),
    ('google-api-key', re.compile(rb'\bAIza[A-Za-z0-9_-]{35}\b')),
]
BEGIN = '# repo-maintenance-guard: begin'
END = '# repo-maintenance-guard: end'


def git(*args: str, data: bytes | None = None, check: bool = True) -> bytes:
    result = subprocess.run(['git', *args], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError('Git 检查失败：' + ' '.join(args[:3]))
    return result.stdout


def repo_root() -> Path:
    return Path(os.fsdecode(git('rev-parse', '--show-toplevel').strip())).resolve()


def config(name: str) -> str:
    return git('config', '--get', name, check=False).decode('utf-8', 'replace').strip()


def message_problems(raw: str) -> list[str]:
    lines = raw.lstrip('\ufeff').splitlines()
    lines = [line for line in lines if not line.startswith('#')]
    subject = next((line.strip() for line in lines if line.strip()), '')
    errors = []
    if not subject:
        errors.append('提交标题为空')
    elif not subject.startswith(AUTO):
        if not SUBJECT.fullmatch(subject):
            errors.append('标题须为 Conventional Commits：type(scope): 描述')
        if len(subject) > 100:
            errors.append('提交标题超过 100 个字符，请把细节移到正文')
    for rule, pattern in PATTERNS:
        if pattern.search(raw.encode('utf-8')):
            errors.append('提交信息包含疑似凭证：' + rule)
    return errors


def blocked_path(path: str) -> bool:
    parts = path.replace('\\', '/').split('/')
    name = parts[-1].lower()
    example = re.search(r'(?:^|[._-])(?:example|sample|template|test|testing|defaults?)(?:[._-]|$)', name)
    if (name == '.env' or name.startswith('.env.')) and not example:
        return True
    if name in ('id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'credentials.json', 'service-account.json'):
        return True
    if any(part.lower() in ('secrets', '.secrets') for part in parts[:-1]) and not example:
        return True
    return '设计文稿' in name or 'design-manuscript' in name


class ObjectBatch:
    """复用 Git 对象管道，避免历史扫描为每个对象反复启动进程。"""
    def __init__(self):
        self.check = subprocess.Popen(['git', 'cat-file', '--batch-check'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.reader = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.metadata = {}
        self.cache = OrderedDict()
        self.cache_bytes = 0

    def info(self, query):
        if query not in self.metadata:
            self.check.stdin.write(query.encode('utf-8') + b'\n')
            self.check.stdin.flush()
            fields = self.check.stdout.readline().split()
            if len(fields) == 2 and fields[1] == b'missing':
                self.metadata[query] = None
            elif len(fields) == 3:
                self.metadata[query] = (fields[0].decode('ascii'), fields[1], int(fields[2]))
            else:
                raise ValueError('Git 对象批量查询返回无效结果')
        return self.metadata[query]

    def read(self, query):
        info = self.info(query)
        if info is None:
            return None
        oid, _, size = info
        if size > MAX_BLOB:
            raise ValueError('拒绝把超出扫描预算的对象载入内存')
        if oid in self.cache:
            self.cache.move_to_end(oid)
            return self.cache[oid]
        self.reader.stdin.write(oid.encode('ascii') + b'\n')
        self.reader.stdin.flush()
        header = self.reader.stdout.readline().split()
        if len(header) != 3 or header[0].decode('ascii') != oid or int(header[2]) != size:
            raise ValueError('Git 对象批量读取返回无效结果')
        data = self.reader.stdout.read(size)
        if len(data) != size or self.reader.stdout.read(1) != b'\n':
            raise ValueError('Git 对象批量读取未完整结束')
        self.cache[oid] = data
        self.cache_bytes += size
        while self.cache_bytes > 32 * 1024 * 1024:
            _, old = self.cache.popitem(last=False)
            self.cache_bytes -= len(old)
        return data

    def close(self):
        for process in (self.check, self.reader):
            process.stdin.close()
            process.stdout.close()
            process.wait(timeout=10)


def allowlist(root: Path, revision: str = '', reader=None) -> dict:
    # 例外来自即将提交的 index 或待推送的提交；未暂存工作区不能放宽检查。
    raw = reader.read(revision + ':.repo-security-allowlist.json') if reader else git('show', revision + ':.repo-security-allowlist.json', check=False)
    if not raw:
        return {}
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('安全例外清单必须是以仓库相对路径为键的对象')
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError('安全例外清单格式无效')
        if not re.fullmatch(r'[0-9a-f]{64}', str(value.get('sha256', ''))) or not value.get('reason'):
            raise ValueError('安全例外须包含精确 sha256 与 reason；不支持通配符')
    return data


def scan_blob(path: str, oid: str, exceptions: dict, seen: set[tuple[str, str]], reader=None) -> list[str]:
    key = (path, oid)
    if key in seen:
        return []
    seen.add(key)
    info = reader.info(oid) if reader else None
    kind = info[1] if reader and info else git('cat-file', '-t', oid).strip()
    if kind != b'blob':
        return []  # Gitlink 不是此仓库可审计的文件内容。
    size = info[2] if info else int(git('cat-file', '-s', oid))
    errors = []
    if size > MAX_BLOB:
        # 体积上限透明报告；原有 LFS/资产检查继续负责大型二进制。
        print('安全检查提示：大型对象未作内容扫描：' + path, file=sys.stderr)
        if blocked_path(path):
            errors.append(path + ': sensitive-path')
        return errors
    blob = reader.read(oid) if reader else git('cat-file', 'blob', oid)
    entry = exceptions.get(path)
    if entry and hashlib.sha256(blob).hexdigest() == entry['sha256']:
        return []
    if blocked_path(path):
        errors.append(path + ': sensitive-path')
    for rule, pattern in PATTERNS:
        match = pattern.search(blob)
        if match:
            line = blob.count(b'\n', 0, match.start()) + 1
            errors.append(f'{path}:{line}: {rule}')
    return errors


def staged(exceptions: dict) -> list[str]:
    names = git('diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z').split(b'\0')
    errors, seen = [], set()
    for raw in filter(None, names):
        path = os.fsdecode(raw)
        entries = git('ls-files', '--stage', '-z', '--', path).split(b'\0')
        for entry in filter(None, entries):
            info, _ = entry.split(b'\t', 1)
            mode, oid, stage = info.split()
            if stage != b'0':
                errors.append(path + ': 请先解决暂存区冲突')
            elif mode not in (b'120000', b'160000'):
                errors.extend(scan_blob(path, oid.decode('ascii'), exceptions, seen))
    return errors


def pushed(lines: bytes, exceptions: dict) -> list[str]:
    commits = set()
    for line in lines.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise ValueError('pre-push 输入不是 Git 的四列引用协议')
        _, local, _, remote = fields
        if set(local) == {ord('0')}:
            continue
        for oid in (local, remote):
            if not re.fullmatch(rb'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', oid):
                raise ValueError('pre-push 输入含无效对象编号')
        local_commit = git('rev-parse', '--verify', local.decode() + '^{commit}', check=False).strip()
        if not local_commit:
            continue  # 直接指向 blob/tree 的标签不含提交历史。
        args = ['rev-list', local_commit.decode()]
        if set(remote) != {ord('0')}:
            exists = subprocess.run(['git', 'cat-file', '-e', remote.decode() + '^{commit}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if exists.returncode:
                raise ValueError('本机缺少远端顶点对象，无法确定待推送范围；先 fetch 对应远端再推送')
            args += ['^' + remote.decode() + '^{commit}']
        commits.update(git(*args).decode().splitlines())
    errors, checked = [], {}
    reader = ObjectBatch()
    root = repo_root()
    try:
        for commit in sorted(commits):
            commit_exceptions = allowlist(root, commit, reader)
            raw_commit = reader.read(commit)
            if raw_commit is None:
                raise ValueError('待推送提交对象缺失')
            header, _, body = raw_commit.partition(b'\n\n')
            errors.extend(commit[:12] + ': ' + error for error in message_problems(body.decode('utf-8', 'replace')))
            parents = [line[7:].decode('ascii') for line in header.splitlines() if line.startswith(b'parent ')]
            args = ['diff-tree', '--root', '--no-commit-id', '-r', '--raw', '--no-renames', '--diff-filter=ACMRT', '-z']
            args += [parents[0], commit] if parents else [commit]
            entries = git(*args).split(b'\0')
            for index in range(0, len(entries) - 1, 2):
                fields = entries[index].split()
                if len(fields) != 5 or not fields[0].startswith(b':'):
                    raise ValueError('Git 文件差异返回无效结果')
                _, mode, _, oid, _ = fields
                path = os.fsdecode(entries[index + 1])
                if mode in (b'120000', b'160000'):
                    continue
                # 缓存包含本提交对该路径的精确例外，撤销例外后必须重新检查。
                key = (path, oid, json.dumps(commit_exceptions.get(path), sort_keys=True))
                if key not in checked:
                    checked[key] = scan_blob(path, oid.decode('ascii'), commit_exceptions, set(), reader)
                    errors.extend(checked[key])
    finally:
        reader.close()
    return errors


def launcher(event: str) -> str:
    capture = ''
    suffix = ''
    if event == 'pre-push':
        # 两次独立打开文件产生独立偏移，旧钩子能收到完整 stdin；随后立刻取消文件名。
        capture = '''repo_guard_input=$(mktemp) || exit 1
cat > "$repo_guard_input" || { rm -f -- "$repo_guard_input"; exit 1; }
exec 3<"$repo_guard_input" 4<"$repo_guard_input"
rm -f -- "$repo_guard_input"
'''
        suffix = ' <&3'
    text = f'''{BEGIN}
{capture}repo_guard_root=$(git rev-parse --show-toplevel) || exit 1
repo_guard_found=0
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
for repo_guard_python in python3 python "py -3"; do
    if $repo_guard_python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        repo_guard_found=1
        $repo_guard_python "$repo_guard_root/tools/repo_maintenance_guard.py" {event} "$@"{suffix} || exit $?
        break
    fi
done
if [ "$repo_guard_found" != 1 ]; then
    printf '%s\\n' '安全检查需要 Python 3.10+，请安装后重试。' >&2
    exit 1
fi
'''
    if event == 'pre-push':
        text += 'exec 0<&4\nexec 3<&- 4<&-\n'
    return text + END + '\n'


def install(root: Path) -> dict:
    configured = config('core.hooksPath')
    hookdir = Path(configured).expanduser() if configured else root / 'tools/repo_maintenance_hooks'
    if not hookdir.is_absolute():
        hookdir = root / hookdir
    # Husky 的 _ 目录是生成的分发层；版本化入口位于它的上一层。
    if hookdir.name == '_' and hookdir.parent.name == '.husky':
        hookdir = hookdir.parent
    hookdir = hookdir.resolve()
    if not hookdir.is_relative_to(root):
        raise ValueError('core.hooksPath 指向仓库之外；不自动修改共享或全局钩子')
    hookdir.mkdir(parents=True, exist_ok=True)
    changed = []
    for event in ('pre-commit', 'commit-msg', 'pre-push'):
        target = hookdir / event
        if target.is_symlink():
            raise ValueError('不覆盖符号链接钩子：' + event)
        old = target.read_text(encoding='utf-8-sig') if target.exists() else '#!/bin/sh\n'
        if BEGIN in old:
            if END not in old:
                raise ValueError('安全检查安装标记不完整：' + event)
            a, rest = old.split(BEGIN, 1)
            _, b = rest.split(END, 1)
            old = a + b.lstrip('\r\n')
        first, sep, body = old.partition('\n')
        if not first.startswith('#!'):
            first, body = '#!/bin/sh', old
        result = first.rstrip('\r') + '\n' + launcher(event) + body
        target.write_text(result, encoding='utf-8', newline='\n')
        target.chmod(target.stat().st_mode | 0o111)
        changed.append(target.relative_to(root).as_posix())
    if not configured:
        git('config', '--local', 'core.hooksPath', 'tools/repo_maintenance_hooks')
    if not config('commit.template'):
        git('config', '--local', 'commit.template', '.gitmessage.txt')
    return dict(version=VERSION, hooks=changed, hooks_path=config('core.hooksPath'), commit_template=config('commit.template'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('install', 'pre-commit', 'commit-msg', 'pre-push', 'status'))
    parser.add_argument('arguments', nargs='*')
    args = parser.parse_args()
    root = repo_root()
    os.chdir(root)
    if args.command == 'install':
        print(json.dumps(install(root), ensure_ascii=False))
        return 0
    if args.command == 'status':
        print(json.dumps(dict(version=VERSION, hooks_path=config('core.hooksPath'), commit_template=config('commit.template')), ensure_ascii=False))
        return 0
    exceptions = allowlist(root)
    if args.command == 'pre-commit':
        errors = staged(exceptions)
    elif args.command == 'commit-msg':
        if not args.arguments:
            raise ValueError('commit-msg 缺少提交信息文件')
        errors = message_problems(Path(args.arguments[0]).read_text(encoding='utf-8-sig'))
    else:
        errors = pushed(sys.stdin.buffer.read(), exceptions)
    if errors:
        print('安全检查未通过（仅显示规则与位置，不输出凭证值）：', file=sys.stderr)
        for error in errors[:50]:
            print('  ' + error, file=sys.stderr)
        print('请移除敏感内容；确属公开测试夹具时，按 SECURITY.md 用精确哈希登记例外。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('安全检查无法完成：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
