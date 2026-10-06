"""部署地址缺失时不能把私有仓误判为不存在；使用假响应验证配置链路。"""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class GuardrailEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cache = self.base / 'private.json'
        self.policy_path = self.base / 'policy.json'
        self.policy = {
            'private_cache': str(self.cache),
            'private_seed': str(self.base / 'missing-seed.json'),
            'cnb_token_file': str(self.base / 'missing-token'),
        }
        self.env = {'GUARD_POLICY': str(self.policy_path), 'CNB_TOKEN': 'test-only'}
        self.cache.write_text(json.dumps({
            'sources': ['cnb'], 'cnb_groups': ['Example'], 'owners': ['Example'],
        }), encoding='utf-8')
        self.requests = []

    def response(self, request, **kwargs):
        self.requests.append(request.full_url)
        path = request.full_url.split('example.test', 1)[1].split('?', 1)[0]
        data = {
            '/user/groups': [{'path': 'Example'}],
            '/user/groups/Example': [],
            '/Example/-/repos': [{'name': 'sample', 'visibility_level': 'Private'}],
            '/Example/sample': {'visibility_level': 'Private'},
        }[path]
        return io.StringIO(json.dumps(data))

    def run_script(self, name, *args):
        self.policy_path.write_text(json.dumps(self.policy), encoding='utf-8')
        output = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(sys, 'argv', [name, *args]), \
                patch('subprocess.run', side_effect=FileNotFoundError), \
                patch('urllib.request.urlopen', side_effect=self.response), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = 0
            try:
                runpy.run_path(str(ROOT / 'guardrails/hooks' / name), run_name='__main__')
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue()

    def test_missing_endpoint_keeps_refresh_cache(self):
        before = self.cache.read_bytes()
        code, output = self.run_script('refresh-private.py')
        self.assertEqual(code, 1)
        self.assertIn('FAIL', output)
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertEqual(self.requests, [])

    def test_missing_endpoint_is_error_not_negative_result(self):
        code, output = self.run_script('resolve-private.py', 'sample')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['sample']['status'], 'error')
        negative = json.loads(Path(str(self.cache) + '.resolve.json').read_text())
        self.assertNotIn('sample', negative)
        self.assertEqual(self.requests, [])

    def test_environment_endpoint_overrides_policy(self):
        self.policy['cnb_api'] = 'https://unused.example.test'
        self.env['CNB_API'] = '  https://api.example.test/  '
        self.assert_private_from_configured_endpoint()
        self.assertTrue(all(url.startswith('https://api.example.test/') for url in self.requests))

    def test_policy_endpoint_works_without_environment_override(self):
        self.policy['cnb_api'] = 'https://policy.example.test/'
        self.assert_private_from_configured_endpoint()
        self.assertTrue(all(url.startswith('https://policy.example.test/') for url in self.requests))

    def assert_private_from_configured_endpoint(self):
        code, output = self.run_script('refresh-private.py')
        self.assertEqual(code, 0, output)
        self.assertIn('Example/sample', json.loads(self.cache.read_text())['private'])
        code, output = self.run_script('resolve-private.py', 'sample')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['sample']['status'], 'private')


if __name__ == '__main__':
    unittest.main()
