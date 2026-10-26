"""框架替身与包加载器；插件必须按部署时的包路径导入，不能借测试目录找 watch。"""

import importlib
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch


class Chain:
    def __init__(self):
        self.text = ""
        self.mention_all = False

    def message(self, text):
        self.text += text
        return self

    def at_all(self):
        self.mention_all = True
        return self

class Star:
    def __init__(self, context):
        self.context = context


def framework_modules():
    modules = {name: types.ModuleType(name) for name in
               ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.star")}
    modules["astrbot.api"].logger = Mock()
    event = modules["astrbot.api.event"]
    event.AstrMessageEvent = object
    event.MessageChain = Chain
    event.filter = types.SimpleNamespace(command=lambda *a, **kw: lambda f: f)
    star = modules["astrbot.api.star"]
    star.Star, star.Context = Star, object
    star.register = lambda *a: lambda cls: cls
    return modules


def load_plugin():
    package_name = "resource_watch_test_plugin"
    package = types.ModuleType(package_name)
    package.__path__ = [str(Path(__file__).resolve().parents[1])]
    modules = framework_modules()
    modules[package_name] = package
    with patch.dict(sys.modules, modules):
        return importlib.import_module(package_name + ".main")
