"""保存失败必须保留上一份可恢复状态，不能被当作通知已落盘。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from watch import store


class StoreTests(unittest.TestCase):
    def test_flush_failure_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.json")
            original = {"outbox": [{"text": "待发送"}]}
            self.assertIsNone(store.save_json(path, original))
            with patch.object(store.os, "fsync", side_effect=OSError("磁盘写入失败")):
                self.assertIsNotNone(store.save_json(path, {"outbox": []}))
            self.assertEqual(store.load_json(path), original)
            self.assertIsNone(store.save_json(path, {"outbox": []}))
            self.assertEqual(store.load_json(path), {"outbox": []})
