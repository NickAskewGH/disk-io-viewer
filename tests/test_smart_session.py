import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from disk_io_viewer.config import Device
from disk_io_viewer.smart_session import SmartSession


class SmartSessionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.launcher = self.folder / "pkexec"
        self.counter = self.folder / "requests"
        self.tools = {"smartctl": "/usr/sbin/smartctl", "pkexec": str(self.launcher)}
        self.enterContext(
            patch("disk_io_viewer.smart_session.os.geteuid", return_value=1000)
        )
        self.enterContext(
            patch(
                "disk_io_viewer.smart_session.shutil.which",
                side_effect=lambda name, path: self.tools[name],
            )
        )
        self.paths = [
            self.folder / name for name in ("absent drive A", "absent drive B")
        ]
        self.devices = tuple(Device(p, p.name) for p in self.paths)

    def start(self, action):
        self.launcher.write_text(
            f'#!/bin/sh\necho called >> "{self.counter}"\n[ "$1" = --disable-internal-agent ] || exit 1\nshift\n{action}\n'
        )
        self.launcher.chmod(0o700)
        session = SmartSession(self.devices)
        self.addCleanup(session.close)
        return session

    def test_single_startup_request_serves_both_drives_and_refresh(self):
        session = self.start('exec "$@"')
        self.assertIsNotNone(session.process)
        paths = [*self.paths, self.paths[0]]
        replies = [session.read(path) for path in paths]
        for reply, path in zip(replies, paths, strict=True):
            self.assertEqual(reply.result(timeout=4), f"Device is unavailable: {path}")
        self.assertEqual(self.counter.read_text().splitlines(), ["called"])
        self.assertTrue(session.authorized)
        session.close()
        self.assertEqual(session.process.wait(timeout=4), 0)

    def test_cancelled_startup_uses_normal_account_without_prompting_again(self):
        self.tools["smartctl"] = str(self.folder / "smartctl")
        tool = Path(self.tools["smartctl"])
        tool.write_text('#!/bin/sh\necho "Permission denied"\nexit 2\n')
        tool.chmod(0o700)
        session = self.start("exit 126")
        for path in self.paths:
            path.touch()
        with patch("disk_io_viewer.smart_session.device_number", return_value=1):
            for path in self.paths:
                report = session.read(path).result(timeout=4)
                self.assertIn("Permission denied", report)
                self.assertIn("authorization was canceled", report)
        self.assertEqual(self.counter.read_text().splitlines(), ["called"])
