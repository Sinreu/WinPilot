"""GUI regression tests; render every page to catch Tkinter option errors."""
import os
import unittest
from unittest.mock import patch

from winpilot.gui import WinPilotApp


class LabelTests(unittest.TestCase):
    def test_label_allows_explicit_justify(self):
        parent = object()
        app = WinPilotApp.__new__(WinPilotApp)
        with patch('winpilot.gui.tk.Label') as label:
            app._label(parent, 'Checking labels', justify='center', anchor='e')
            self.assertEqual(label.call_args.kwargs['justify'], 'center')
            self.assertEqual(label.call_args.kwargs['anchor'], 'e')

    def test_label_uses_defaults(self):
        app = WinPilotApp.__new__(WinPilotApp)
        with patch('winpilot.gui.tk.Label') as label:
            app._label(object(), 'Test')
            self.assertEqual(label.call_args.kwargs['justify'], 'left')
            self.assertEqual(label.call_args.kwargs['anchor'], 'w')


@unittest.skipUnless(os.name == 'nt' or os.environ.get('WINPILOT_GUI_TESTS') == '1', 'GUI smoke test runs on Windows or with WINPILOT_GUI_TESTS=1')
class GuiSmokeTests(unittest.TestCase):
    def test_every_page_can_render(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            # Never run operations that change Windows while testing the UI.
            with patch.object(WinPilotApp, '_task'):
                app = WinPilotApp(root)
                for page in ('overview', 'cleanup', 'startup', 'tweaks', 'diagnostics', 'logs'):
                    with self.subTest(page=page):
                        app.show_page(page)
                        root.update_idletasks()
        finally:
            root.destroy()
