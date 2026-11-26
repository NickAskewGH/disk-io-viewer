import os
import unittest
from collections import deque
from itertools import pairwise
from pathlib import Path
from unittest.mock import Mock, patch

from disk_io_viewer.config import Config, Device
from disk_io_viewer.sampler import Point


@unittest.skipUnless(os.environ.get("DISPLAY"), "Tk needs a display")
class ChartTests(unittest.TestCase):
    def test_panels_scale_gaps_resize_and_scrolling(self):
        import tkinter as tk

        from disk_io_viewer.viewer import GIB, MIB, READ, WRITE, Viewer

        clock = self.enterContext(
            patch("disk_io_viewer.viewer.time.monotonic", return_value=100)
        )
        root = tk.Tk()
        self.addCleanup(root.destroy)
        devices = tuple(
            Device(Path(f"/dev/fixture{i}"), name)
            for i, name in enumerate(["NVMe", "HDD", "Offline"])
        )
        with patch("disk_io_viewer.sampler.read_device", side_effect=FileNotFoundError):
            viewer = Viewer(root, Config(devices, 30, 60), Mock())
        fast, slow, _offline = viewer.monitor.series
        fast.points = deque(
            [
                Point(40, (GIB, 0)),
                Point(50, (0, 0)),
                Point(60, None),
                Point(70, (MIB, 0)),
                Point(100, (0, MIB)),
            ]
        )
        slow.points = deque([Point(70, (MIB / 2, 0)), Point(100, (4096, 512))])
        fast.status = slow.status = ""
        root.geometry("580x270")
        root.update()
        canvas = viewer.canvas
        self.assertIn("30 s averages", root.title())

        def traces(color):
            return [
                i
                for i in canvas.find_withtag("trace")
                if canvas.itemcget(i, "fill") == color
            ]

        reads = traces(READ)
        self.assertEqual(len(reads), 3)
        self.assertLess(canvas.coords(reads[0])[-2], canvas.coords(reads[1])[0])
        self.assertEqual(canvas.coords(reads[1])[-2], canvas.coords(reads[2])[-2])
        for item in reads + traces(WRITE):
            self.assertFalse(canvas.itemcget(item, "dash"))
            self.assertEqual(float(canvas.itemcget(item, "width")), 2)
            self.assertEqual(canvas.itemcget(item, "smooth"), "raw")
        texts = [
            canvas.itemcget(i, "text")
            for i in canvas.find_all()
            if canvas.type(i) == "text"
        ]
        for label in [
            "GiB/s",
            "MiB/s",
            "Read 0 B/s",
            "Read 4.00 KiB/s",
            "Write 512 B/s",
            "Write 1.00 MiB/s",
            "Unavailable",
        ]:
            self.assertIn(label, texts)
        self.assertEqual(
            [t for t in texts if t in {"NVMe", "HDD", "Offline"}],
            ["NVMe", "HDD", "Offline"],
        )
        old_right = canvas.coords(reads[1])[-2]
        root.geometry("720x270")
        root.update()
        self.assertGreater(canvas.coords(traces(READ)[1])[-2], old_right)
        canvas.yview_moveto(1)
        self.assertGreater(canvas.yview()[0], 0)

        # Between samples, only the curves should move, at the time-axis speed.
        item = traces(READ)[1]
        before = canvas.coords(item)
        clock.return_value = 100.25
        with (
            patch.object(viewer.monitor, "sample") as sample,
            patch.object(root, "after") as schedule,
        ):
            viewer.tick()
        sample.assert_not_called()
        self.assertLessEqual(schedule.call_args.args[0], 34)
        dx = (canvas.winfo_width() - 62 - 16) * 0.25 / 60
        after = canvas.coords(item)
        for x0, x1 in zip(before[::2], after[::2]):
            self.assertAlmostEqual(x1, x0 - dx)
        self.assertEqual(after[1::2], before[1::2])

    def test_curve_keeps_samples_and_local_extrema(self):
        from disk_io_viewer.viewer import curve_coordinates

        points = [(0, 10), (1, 3), (3, 0), (4, 50), (15, 50)]
        coords = curve_coordinates(points)
        self.assertEqual(list(zip(coords[::6], coords[1::6])), points)
        for i, ((x0, y0), (x1, y1)) in enumerate(pairwise(points)):
            for x, y in zip(
                coords[6 * i + 2 : 6 * i + 6 : 2], coords[6 * i + 3 : 6 * i + 6 : 2]
            ):
                self.assertTrue(x0 <= x <= x1)
                self.assertTrue(min(y0, y1) <= y <= max(y0, y1))
        # The tangent is horizontal on both sides of the local extremum.
        self.assertEqual(coords[11], 0)
        self.assertEqual(coords[15], 0)
