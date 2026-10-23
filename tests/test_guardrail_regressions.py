"""守卫必须审真实对象，同时避免把代码/消息示例当作执行指令。"""
import contextlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load_module('agent_guard_regression', 'tools/agent-guard.py')
ENDPOINTS = load_module('endpoint_guard_regression', 'tools/check-no-endpoints.py')
PRE_PUSH = load_module('push_guard_regression', 'tools/githooks/pre_push.py')


class ShellParsingTests(unittest.TestCase):
    def test_message_and_print_arguments_are_not_commands(self):
        commands = [
            "git commit -m 'fix(docs): 更新 ; git commit -n 示例'",
            "git commit -m 'fix(docs): 修订说明' -m '--no-verify'",
            "printf '%s\\n' git commit --no-verify",
            "git commit --message=--no-verify",
            "git commit -am--no-verify",
            "git commit -- --no-verify",
            "git push --push-option --no-verify origin main",
            "git push -n origin main",
            "git commit -m 'fix(docs): 更新' # git commit -n",
            "printf done # ; git commit -n",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(GUARD.offending(command))

    def test_real_options_after_global_options_and_separators_are_detected(self):
        commands = [
            'git -C subdir commit --no-verify',
            'git --git-dir folder --work-tree other commit -an',
            'git -c core.hooksPath=other commit -m text',
            'git --config-env=core.hooksPath=HOOK_DIR push',
            'MODE=test command git commit -anm text',
            'printf done; git push --no-verify',
            'git \\\ncommit --no-verify',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(GUARD.offending(command))

    def test_unbalanced_shell_is_not_reinterpreted(self):
        self.assertIsNone(GUARD.offending("printf 'git commit --no-verify"))

    def test_heredoc_bodies_are_data_but_following_commands_are_checked(self):
        for command in (
            "cat <<'EOF'\ngit commit --no-verify\nEOF\n",
            'cat <<"EOF"\ngit commit --no-verify\nEOF\n',
            "cat <<-EOF\n\tgit commit --no-verify\n\tEOF\n",
            "cat <<'FIRST' <<SECOND\ngit commit -n\nFIRST\ngit push --no-verify\nSECOND\n",
            "cat <<EOF\ngit commit --no-verify\n",
        ):
            with self.subTest(command=command):
                self.assertIsNone(GUARD.offending(command))
        self.assertIsNotNone(GUARD.offending("cat <<'EOF'\ngit commit --no-verify\nEOF\ngit commit -n\n"))
        self.assertIsNotNone(GUARD.offending("printf '%s' '<<EOF'; git commit -n"))

    def test_supplemental_checks_use_actual_options(self):
        from shell_commands import inspect_command
        policy = {'agent_branch_prefixes': ['agent/'], 'agent_provider_emails': ['noreply@example.test']}
        cases = [
            ('commit', "git commit -m '--no-gpg-sign'", 'match'),
            ('commit', "git commit --no-gpg-sign", 'violation'),
            ('commit', "printf '%s' 'git commit --no-verify'", 'pass'),
            ('commit', 'git -C other commit --author="Agent <noreply@example.test>"', 'violation'),
            ('push', 'git push --push-option agent/example origin main', 'match'),
            ('push', 'git push origin HEAD:agent/example', 'violation'),
            ('push', 'git -C other push --no-verify origin main', 'violation'),
        ]
        for target, command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(inspect_command(command, target, policy)[0], expected)


class EndpointSyntaxTests(unittest.TestCase):
    def test_malformed_reserved_urls_remain_safe_parser_fixtures(self):
        for url in ('https://[broken.example.test/', 'https://[broken.invalid/'):
            problems = []
            ENDPOINTS.scan_text('fixture.py', 'url = ' + repr(url), problems)
            self.assertEqual(problems, [])
            with patch.object(ENDPOINTS, 'ALLOWED_HOSTS', ('localhost',)):
                ENDPOINTS.scan_text('fixture.py', 'url = ' + repr(url), problems)
            self.assertTrue(problems)

    def test_unicode_and_legacy_loopback_forms_are_safe_examples_without_dns(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('must not resolve')), \
                patch('socket.gethostbyname', side_effect=AssertionError('must not resolve')):
            for host in ('１２７.０.０.１', '１２７。０。０。１', 'ⓛⓞⓒⓐⓛⓗⓞⓢⓣ',
                         '０ｘ７ｆ０００００１', '127.1', '2130706433', '0177.0.0.1',
                         '0x7f.1', '0', '[::1]', '[::1]:8080', '[::ffff:127.0.0.1]'):
                with self.subTest(host=host):
                    self.assertTrue(ENDPOINTS.host_allowed(host))
                    problems = []
                    ENDPOINTS.scan_text('fixture.md', 'http://' + host + '/', problems)
                    self.assertEqual(problems, [])

    def test_public_numeric_forms_and_ipv6_are_not_placeholder_exemptions(self):
        # 构造用于分类的数值，不访问网络；公开地址的任何数字表示都不能获豁免。
        value = int.from_bytes(bytes([8]) * 4, 'big')
        dotted = str(ipaddress.IPv4Address(value))
        public_v6 = str(ipaddress.IPv6Address((0x2600 << 112) | 1))
        forms = [dotted, str(value), hex(value), '0' + format(value, 'o'),
                 ''.join(chr(ord(char) + 0xFEE0) if char.isdigit() else char for char in dotted),
                 '[' + public_v6 + ']', '[' + public_v6 + ']:443', '[::ffff:' + dotted + ']']
        for host in forms:
            with self.subTest(host=host):
                self.assertFalse(ENDPOINTS.host_allowed(host))
                problems = []
                ENDPOINTS.scan_text('fixture.md', 'https://' + host + '/', problems)
                self.assertTrue(problems)

    def test_only_exact_percent_host_placeholder_is_allowed(self):
        self.assertTrue(ENDPOINTS.host_allowed('%s'))
        self.assertTrue(ENDPOINTS.host_allowed('%s:8080'))
        problems = []
        ENDPOINTS.scan_text('fixture.py', '"http://%s/"', problems)
        self.assertEqual(problems, [])
        with patch.object(ENDPOINTS, 'ALLOWED_HOSTS', ('localhost',)):
            for host in ('%s.example.test', 'prefix%s', 'ｅｘａｍｐｌｅ.test',
                         '[example.test]', '[::1].example.test', '[::1',
                         '4294967296', '0x100000000', '127.0.0.999', '127.09'):
                with self.subTest(host=host):
                    self.assertFalse(ENDPOINTS.host_allowed(host))

    def test_python_imports_and_attributes_are_not_domains(self):
        problems = []
        app, module = 'sample' + '.app', 'sample' + '.io'
        ENDPOINTS.scan_text('sample.py', f'from {app} import Application\nimport {module}\nx = {app}\n', problems)
        self.assertEqual(problems, [])

    def test_same_line_strings_comments_and_docstrings_are_still_scanned(self):
        # 测试域名仍使用保留域，仅在 mock 的允许规则中将它视为应拦截对象。
        app, module = 'sample' + '.app', 'sample' + '.io'
        with patch.object(ENDPOINTS, 'host_allowed', return_value=False):
            for source in (
                f'from {app} import Application; endpoint = "https://api.example.test/"',
                f'import {module}  # https://api.example.test/',
                '"""\nhttps://api.example.test/\n"""',
            ):
                problems = []
                ENDPOINTS.scan_text('sample.py', source, problems)
                self.assertTrue(problems, source)
                self.assertFalse(any(app in str(p) or module in str(p) for p in problems))

    def test_plain_text_hosts_are_still_scanned(self):
        problems = []
        with patch.object(ENDPOINTS, 'host_allowed', return_value=False):
            ENDPOINTS.scan_text('sample.md', 'api.example.test', problems)
        self.assertTrue(problems)

    def test_markdown_closing_brackets_are_not_part_of_domain_authority(self):
        for text in ('[https://api.example.test/](https://api.example.test/)',
                     '[https://api.example.test]', 'https://api.example.test]'):
            with self.subTest(text=text):
                problems = []
                ENDPOINTS.scan_text('fixture.md', text, problems)
                self.assertEqual(problems, [])


class GitObjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.git('init', '-q')
        self.env = dict(os.environ, GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.test',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.test')

    def git(self, *args, input=None):
        if isinstance(input, str):
            input = input.encode('utf-8')
        result = subprocess.run(['git', *args], cwd=self.base, input=input, capture_output=True,
                                env=getattr(self, 'env', None))
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        return result.stdout.decode('utf-8', 'replace').strip()

    def commit(self, name, text, parent=None, message='test: 离线夹具'):
        blob = self.git('hash-object', '-w', '--stdin', input=text)
        tree = self.git('mktree', input='100644 blob %s\t%s\n' % (blob, name))
        return self.git('commit-tree', tree, *(['-p', parent] if parent else []), '-m', message)

    def scan(self, commits):
        problems = []
        original_run = subprocess.run

        def run(*args, **kwargs):
            return original_run(*args, cwd=self.base, **kwargs)

        with patch.object(ENDPOINTS.subprocess, 'run', side_effect=run), \
                patch.object(ENDPOINTS, 'host_allowed', return_value=False):
            ENDPOINTS.scan_commits(commits, problems)
        return problems

    def test_root_and_removed_content_remain_visible(self):
        first = self.commit('sample.txt', 'https://api.example.test/')
        second = self.commit('sample.txt', 'clean', parent=first)
        self.assertTrue(any(first[:12] in item[0] for item in self.scan([first, second])))

    def test_worktree_cannot_hide_committed_blob(self):
        first = self.commit('sample.txt', 'https://api.example.test/')
        (self.base / 'sample.txt').write_text('clean', encoding='utf-8')
        self.assertTrue(self.scan([first]))

    def test_messages_paths_and_extensionless_files_are_scanned(self):
        for name, text, message in (
            ('sample.txt', 'clean', 'test: https://api.example.test/'),
            ('api.example.test', 'clean', 'test: 离线夹具'),
            ('Dockerfile', '# https://api.example.test/', 'test: 离线夹具'),
        ):
            with self.subTest(name=name, message=message):
                self.assertTrue(self.scan([self.commit(name, text, message=message)]))

    def test_rename_into_forbidden_configuration_path_is_scanned(self):
        first = self.commit('sample.txt', 'clean')
        second = self.commit('config.json', 'clean', parent=first)
        self.git('config', 'diff.renames', 'true')
        problems = self.scan([second])
        self.assertTrue(any('真实配置文件' in item[2] for item in problems))

    def test_supplemental_guard_scans_root_commit(self):
        policy = json.loads((ROOT / 'guardrails/policy/policy.json').read_text(encoding='utf-8'))
        policy_path = self.base / 'policy.json'
        policy_path.write_text(json.dumps(policy), encoding='utf-8')
        with patch.dict(os.environ, {'GUARD_POLICY': str(policy_path)}):
            engine = load_module('supplemental_guard_regression', 'guardrails/policy/check.py')
        commit = self.commit('sample.txt', 'root-content')
        ok, text = engine.added_lines(commit, str(self.base))
        self.assertTrue(ok)
        self.assertIn('root-content', text)
        self.assertIn('sample.txt', text)

    def test_direct_scan_works_under_gbk_environment(self):
        (self.base / 'sample.txt').write_text('clean', encoding='utf-8')
        self.git('add', 'sample.txt')
        result = subprocess.run([sys.executable, str(ROOT / 'tools/check-no-endpoints.py')], cwd=self.base,
                                env=dict(os.environ, PYTHONIOENCODING='gbk', PYTHONUTF8='0'), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class PushScopeTests(unittest.TestCase):
    def test_tag_push_is_included_and_delete_is_skipped(self):
        oid = '1' * 40
        zero = '0' * 40
        with patch.object(sys, 'stdin', io.StringIO('refs/tags/v1 %s refs/tags/v1 %s\n(delete) %s refs/heads/old %s\n' % (oid, zero, zero, oid))):
            self.assertEqual(PRE_PUSH.parse_stdin(), [(oid, 'refs/tags/v1', zero)])

    def test_endpoint_range_has_no_merge_or_count_omission(self):
        with patch.object(PRE_PUSH, 'sh', return_value=subprocess.CompletedProcess([], 0, 'new\n', '')) as shell:
            self.assertEqual(PRE_PUSH.new_commits('local', 'remote', all_content=True), ['new'])
        args = shell.call_args.args
        self.assertIn('remote..local', args)
        self.assertNotIn('--no-merges', args)
        self.assertFalse(any(arg.startswith('--max-count') for arg in args))

    def test_guard_failure_warns_but_violation_blocks(self):
        refs = [('1' * 40, 'main', '2' * 40)]
        for code, blocked in ((0, False), (1, True), (2, False)):
            with patch.object(PRE_PUSH, 'repo_root', return_value=str(ROOT)), \
                    patch.object(PRE_PUSH, 'new_commits', return_value=['1' * 40]), \
                    patch.object(PRE_PUSH, 'sh', return_value=subprocess.CompletedProcess([], code, 'report', '')), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                result = PRE_PUSH.check_endpoints(refs)
            self.assertEqual(bool(result), blocked)
            if code == 2:
                self.assertIn('放行', errors.getvalue())


class PrivateCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cache = self.base / 'cache.json'
        self.seed = self.base / 'seed.json'
        self.seed.write_text(json.dumps({'owners': ['Example'], 'private': ['Example/seed']}), encoding='utf-8')
        self.cache.write_text(json.dumps({'private': ['Example/old'], 'sources': ['cnb']}), encoding='utf-8')
        self.policy = self.base / 'policy.json'
        self.policy.write_text(json.dumps({'private_cache': str(self.cache), 'private_seed': str(self.seed),
                                         'cnb_token_file': str(self.base / 'absent'), 'cnb_api': 'https://api.example.test'}), encoding='utf-8')

    def run_script(self, name, env, response, *args):
        with patch.dict(os.environ, dict(env, GUARD_POLICY=str(self.policy)), clear=True), \
                patch.object(sys, 'argv', [name, *args]), \
                patch('subprocess.run', side_effect=FileNotFoundError), \
                patch('urllib.request.urlopen', side_effect=response), patch('time.sleep'), \
                contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = 0
            try:
                runpy.run_path(str(ROOT / 'guardrails/hooks' / name), run_name='__main__')
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue()

    def test_cnb_forbidden_or_malformed_enumeration_preserves_cache(self):
        before = self.cache.read_bytes()
        for response in (
            urllib.error.HTTPError('https://api.example.test', 403, 'forbidden', {}, None),
            lambda *args, **kwargs: io.StringIO('{}'),
        ):
            if isinstance(response, urllib.error.HTTPError):
                self.addCleanup(response.close)
            code, _ = self.run_script('refresh-private.py', {'CNB_TOKEN': 'test-only'}, response)
            self.assertEqual(code, 1)
            self.assertEqual(self.cache.read_bytes(), before)

    def test_pat_only_unknown_name_does_not_require_optional_cli(self):
        self.cache.write_text(json.dumps({'sources': ['token1'], 'owners': ['Example'],
                                         'token_owners': {'GH_TOKEN_1': ['Example']}}), encoding='utf-8')
        response = urllib.error.HTTPError('https://api.example.test', 404, 'missing', {}, None)
        self.addCleanup(response.close)
        code, output = self.run_script('resolve-private.py', {'GH_TOKEN_1': 'test-only'}, response, 'normal-title')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['normal-title']['status'], 'absent')


def bash_executable():
    if os.name == 'nt':
        git = shutil.which('git')
        if git:
            candidate = Path(git).parent.parent / 'bin/bash.exe'
            if candidate.exists():
                return str(candidate)
        return None  # 系统 bash 可能是 WSL 启动器，不能据此判定可运行本机脚本。
    return shutil.which('bash')


@unittest.skipUnless(bash_executable(), '需要本机 Bash 执行 shell 入口回归')
class ShellEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.policy = self.base / 'policy.json'
        self.policy.write_text(json.dumps({'agent_signing_fingerprint': '', 'signing_instructions': '',
                                          'agent_provider_emails': [], 'agent_branch_prefixes': ['agent/']}), encoding='utf-8')
        self.engine = self.base / 'engine.py'
        self.engine.write_text('import os\nprint(os.environ["TEST_ENGINE_STATUS"])\n', encoding='utf-8')
        for name in ('_lib.sh', 'forbid-content.sh', 'forbid-commit.sh', 'forbid-push.sh',
                     'git/commit-msg', 'git/pre-push', 'git/pre-commit'):
            source = (ROOT / 'guardrails/hooks' / name).read_text(encoding='utf-8')
            source = source.replace('/root/.claude/policy/check.py', self.engine.as_posix())
            source = source.replace('/root/.claude/policy/policy.json', self.policy.as_posix())
            source = source.replace('/root/.claude/policy/shell_commands.py', (ROOT / 'guardrails/policy/shell_commands.py').as_posix())
            target = self.base / name
            target.parent.mkdir(exist_ok=True)
            target.write_text(source, encoding='utf-8', newline='\n')

    def run_hook(self, name, status, input=''):
        script = r'''
python3(){ "$TEST_PYTHON" "$@"; }
git(){
  if [ "$1" = config ]; then
    case "${3:-}" in
      commit.gpgsign) printf true ;;
      gpg.format) printf ssh ;;
      user.signingkey) printf test-only-key ;;
    esac
  elif [ "$1" = diff ]; then
    case "$*" in *--name-only*) printf sample.txt ;; *) printf '+sample\n' ;; esac
  fi
}
source "$1" sample
'''
        path = (self.base / name).as_posix()
        return subprocess.run([bash_executable(), '-c', script, path, path],
                              input=input, encoding='utf-8', errors='replace', capture_output=True,
                              env=dict(os.environ, TEST_ENGINE_STATUS=status, TEST_PYTHON=sys.executable), timeout=30)

    def test_git_hooks_warn_on_engine_error_and_block_violations(self):
        for name in ('git/commit-msg', 'git/pre-push', 'git/pre-commit'):
            for status, code in (('error', 0), ('violation', 1), ('pass', 0)):
                with self.subTest(name=name, status=status):
                    result = self.run_hook(name, status)
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                    if status == 'error':
                        self.assertIn('放行', result.stderr)

    def test_tool_hooks_warn_on_engine_error_and_block_violations(self):
        cases = [('forbid-content.sh', {'content': 'sample'}),
                 ('forbid-commit.sh', {'command': 'git commit -m text'}),
                 ('forbid-push.sh', {'command': 'git push origin main'})]
        for name, tool_input in cases:
            for status, code in (('error', 0), ('violation', 2), ('pass', 0)):
                with self.subTest(name=name, status=status):
                    result = self.run_hook(name, status, json.dumps({'tool_input': tool_input}))
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                    if status == 'error':
                        self.assertIn('放行', result.stderr)

    def test_malformed_tool_input_is_a_warning(self):
        for name in ('forbid-content.sh', 'forbid-commit.sh', 'forbid-push.sh'):
            result = self.run_hook(name, 'pass', 'not-json')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('放行', result.stderr)

    def test_shell_fast_path_does_not_block_message_literals(self):
        for command, code in (("git commit -m '--no-verify'", 0), ('git -C subdir commit --no-verify', 2)):
            result = self.run_hook('forbid-commit.sh', 'pass', json.dumps({'tool_input': {'command': command}}))
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
