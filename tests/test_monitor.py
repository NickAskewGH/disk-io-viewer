import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from disk_io_viewer.config import Config, Device, load_config
from disk_io_viewer.sampler import Monitor, Observation, Series

DISK = Device(Path("/dev/fixture"), "Scratch")


def observation(t, reads=0, writes=0, number=1, generation=1):
    return Observation(t, number, generation, "fixture", reads, writes)


class ConfigTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "monitor.toml"
            path.write_text(content)
            return load_config(path)

    def test_example_order_including_offline(self):
        with patch(
            "disk_io_viewer.config.device_number",
            side_effect=[1, 2, FileNotFoundError()],
        ):
            config = load_config(
                Path(__file__).resolve().parents[1] / "disk-io.example.toml"
            )
        self.assertEqual(
            [d.label for d in config.devices],
            ["Scratch NVMe", "System SSD", "Archive HDD"],
        )
        self.assertEqual((config.interval, config.history), (1, 60))

    def test_invalid_config(self):
        entry = '[[devices]]\npath = "/missing-fixture"\n'
        for text, key in [
            ("", "devices"),
            ('[[devices]]\npath = "sda"', "path"),
            ("sample_interval_seconds = nan\n" + entry, "sample_interval_seconds"),
            ("sample_interval_seconds = 0\n" + entry, "sample_interval_seconds"),
            ("sample_interval_seconds = true\n" + entry, "sample_interval_seconds"),
            ("history_seconds = 1\n" + entry, "history_seconds"),
            (entry + 'label = ""', "label"),
            (entry + entry, "duplicates"),
        ]:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, key):
                self.load(text)
        self.assertEqual(self.load(entry).devices[0].label, "missing-fixture")

    def test_aliases(self):
        with (
            patch("disk_io_viewer.config.device_number", return_value=5),
            self.assertRaisesRegex(ValueError, "entry 2.path duplicates"),
        ):
            self.load('[[devices]]\npath = "/first"\n[[devices]]\npath = "/alias"')


class SamplingTests(unittest.TestCase):
    def test_elapsed_time_and_idle(self):
        series = Series(DISK)
        for obs, expected in [
            (observation(0), None),
            (observation(2, 4096, 1024), (2**20, 2**18)),
            (observation(3.5, 4099, 1024), (1024, 0)),
            (observation(4, 4099, 1024), (0, 0)),
        ]:
            series.observe(obs, 1)
            self.assertEqual(series.points[-1].rates, expected)

    def test_continuity(self):
        for new in [
            observation(1, 9, 100),
            observation(1, 100, 9),
            observation(1, 100, 100, number=2),
            observation(1, 100, 100, generation=2),
            observation(2.01, 100, 100),
            observation(0, 100, 100),
        ]:
            with self.subTest(new=new):
                series = Series(DISK)
                series.observe(observation(0, 10, 10), 1)
                series.observe(new, 1)
                self.assertIsNone(series.points[-1].rates)
                series.observe(
                    observation(
                        new.timestamp + 1,
                        new.sectors_read + 1,
                        new.sectors_written + 1,
                        new.number,
                        new.generation,
                    ),
                    1,
                )
                self.assertEqual(series.points[-1].rates, (512, 512))

    def test_per_device_recovery_and_expiry(self):
        monitor = Monitor(Config((DISK, Device(Path("/alias"), "Other")), 1, 2))
        first, second = monitor.series
        sequence = [
            (observation(0, number=2), "Collecting"),
            (FileNotFoundError(), "Unavailable"),
            (PermissionError(), "Permission denied"),
            (observation(3, number=1), "Duplicate device"),
            (observation(4, number=2), "Collecting"),
            (observation(5, 1, 2, number=2), ""),
        ]
        for t, (result, status) in enumerate(sequence):
            with (
                patch(
                    "disk_io_viewer.sampler.read_device",
                    side_effect=[observation(t, t, t), result],
                ),
                patch("disk_io_viewer.sampler.time.monotonic", return_value=t),
            ):
                monitor.sample()
            self.assertEqual(second.status, status)
            self.assertGreaterEqual(second.points[0].timestamp, t - 2)
            self.assertEqual(first.points[-1].rates, (512, 512) if t else None)
            self.assertEqual(second.points[-1].rates, None if status else (512, 1024))
