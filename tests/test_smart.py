import os
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch

from disk_io_viewer.config import Config, Device


@unittest.skipUnless(os.environ.get("DISPLAY"), "Tk needs a display")
class SmartTests(unittest.TestCase):
    def test_scrolled_click_report_authorization_and_close(self):
        import tkinter as tk

        from disk_io_viewer.viewer import Viewer

        root = tk.Tk()
        self.addCleanup(root.destroy)
        paths = [Path(f"/dev/fixture{i}") for i in range(4)]
        devices = tuple(Device(path, path.name) for path in paths)
        with patch("disk_io_viewer.sampler.read_device", side_effect=FileNotFoundError):
            session = Mock()
            viewer = Viewer(root, Config(devices, 30, 60), session)
        root.geometry("600x175")
        root.update()
        canvas = viewer.canvas
        canvas.yview_moveto(1)
        y = 120
        self.assertEqual(int(canvas.canvasy(y)) // 170, 3)

        ready = Future()
        ready.set_result("SMART overall-health: FAILED")
        waiting = Future()
        session.read.side_effect = [ready, waiting]
        canvas.event_generate("<Button-1>", x=30, y=y)
        window = root.children["smart3"]
        session.read.assert_called_once_with(paths[3])
        self.assertIn("FAILED", window.report.get("1.0", "end"))
        canvas.event_generate("<Button-1>", x=30, y=y)
        self.assertEqual(session.read.call_count, 1)
        window.refresh.invoke()
        session.read.assert_called_with(paths[3])
        self.assertIsNotNone(window.timer)
        window.destroy()
        self.assertTrue(waiting.cancelled())
        self.assertNotIn("smart3", root.children)
