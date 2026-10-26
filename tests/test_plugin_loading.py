"""在独立进程中模拟框架发现插件，防止仓库根目录意外掩盖导入错误。"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class PluginLoadingTests(unittest.TestCase):
    def test_nested_packages_do_not_require_or_replace_top_level_watch(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            for name in ("resource_watch_first", "resource_watch_second"):
                plugin = Path(directory, "data", "plugins", name)
                plugin.mkdir(parents=True)
                shutil.copy2(root / "main.py", plugin / "main.py")
                shutil.copytree(root / "watch", plugin / "watch",
                                ignore=shutil.ignore_patterns("__pycache__"))
            result = subprocess.run(
                [sys.executable, "-I", "-c", _IMPORT_CHECK,
                 str(root / "tests" / "astrbot_stub.py"), directory, str(root)],
                cwd=directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


_IMPORT_CHECK = """
import importlib
import importlib.util
from pathlib import Path
import sys
import types

spec = importlib.util.spec_from_file_location("framework_stub", sys.argv[1])
stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stub)
sys.modules.update(stub.framework_modules())
sys.path.insert(0, sys.argv[2])
assert Path(sys.argv[3]).resolve() not in [Path(p).resolve() for p in sys.path]
before = list(sys.path)
assert "watch" not in sys.modules
first = importlib.import_module("data.plugins.resource_watch_first.main")
assert first.Monitor.__module__ == "data.plugins.resource_watch_first.watch.runner"
assert "watch" not in sys.modules

# 另一插件可能恰好使用同名顶层模块，加载本插件不能借用或覆盖它。
other_watch = types.ModuleType("watch")
sys.modules["watch"] = other_watch
second = importlib.import_module("data.plugins.resource_watch_second.main")
assert second.Monitor.__module__ == "data.plugins.resource_watch_second.watch.runner"
assert first.Monitor is not second.Monitor
assert sys.modules["watch"] is other_watch
assert sys.path == before
assert first.ResourceWatch(types.SimpleNamespace()).monitor is None
assert second.ResourceWatch(types.SimpleNamespace()).monitor is None
"""
