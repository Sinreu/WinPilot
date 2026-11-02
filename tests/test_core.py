"""Safe filesystem tests executable on Windows, Linux and macOS."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from winpilot import core


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, old=True):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('hello, WinPilot', encoding='utf-8')
        if old:
            import os
            os.utime(path, (time.time() - 48 * 3600, time.time() - 48 * 3600))
        return path

    def test_preview_and_delete_old_only(self):
        old = self.write('old/sub.log')
        recent = self.write('current.log', old=False)
        candidates, summary = core.scan_temp(self.root)
        self.assertEqual(summary.files, 1)
        self.assertTrue(any(candidate.samefile(old) for candidate in candidates))
        self.assertEqual(summary.bytes, len('hello, WinPilot'))
        done = core.clean_temp(self.root)
        self.assertEqual(done.files, 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as other:
            victim = Path(other) / 'victim.txt'
            victim.write_text('preserve')
            import os
            os.utime(victim, (time.time() - 864000, time.time() - 864000))
            alias = self.root / 'alias'
            try:
                alias.symlink_to(Path(other), target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks not available without privileges')
            self.assertEqual(core.clean_temp(self.root).files, 0)
            self.assertTrue(victim.exists())

    def test_save_load_backup(self):
        state_path = self.root / 'backups.json'
        with patch.object(core, 'STATE_FILE', state_path), patch.object(core, 'APP_DIR', self.root):
            state = core.load_state()
            state['disabled_startup']['Example'] = {'value': 'abc', 'type': 1}
            core.save_state(state)
            self.assertEqual(core.load_state(), state)

    def test_invalid_state_is_not_silently_overwritten(self):
        p = self.root / 'backups.json'
        p.write_text('invalid json')
        with patch.object(core, 'STATE_FILE', p):
            with self.assertRaises(ValueError):
                core.load_state()

    def test_format_size(self):
        self.assertEqual(core.format_size(0), '0 Б')
        self.assertEqual(core.format_size(2048), '2.0 КБ')


if __name__ == '__main__':
    unittest.main()
