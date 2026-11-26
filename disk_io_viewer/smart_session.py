import base64
import os
import shutil
import subprocess
import sys
from concurrent.futures import Future
from pathlib import Path
from queue import Queue
from threading import Thread

from .config import Device, device_number

SYSTEM_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"

# Only integer selections cross the private pipe. The configured paths are
# positional arguments, never shell source. Each report occupies one reply line.
REPORT_SERVER = r"""
smartctl=$1
shift
printf 'ready\n'
while IFS= read -r selection; do
    index=0
    for device do
        if [ "$index" = "$selection" ]; then
            {
                if path=$(/usr/bin/readlink -e -- "$device") && [ -b "$path" ]; then
                    /usr/bin/timeout -k 2 30 "$smartctl" -a -- "$path" </dev/null 2>&1
                    if [ "$?" = 124 ]; then printf '\nThe SMART read timed out.\n'; fi
                else
                    printf 'Device is unavailable: %s\n' "$device"
                fi
            } | /usr/bin/base64 -w 0
            break
        fi
        index=$((index + 1))
    done
    printf '\n'
done
"""


class SmartSession:
    def __init__(self, devices: tuple[Device, ...]):
        self.paths = tuple(d.path for d in devices)
        self.requests = Queue()
        self.process = None
        self.authorized = False
        self.closed = False
        self.reason = "SMART authorization was canceled or unavailable."
        self.smartctl = shutil.which("smartctl", path=SYSTEM_PATH)
        pkexec = shutil.which("pkexec", path=SYSTEM_PATH)
        self.env = os.environ.copy()
        self.env["LC_ALL"] = "C"
        if getattr(sys, "frozen", False):
            self.env.pop("LD_LIBRARY_PATH", None)
            if "LD_LIBRARY_PATH_ORIG" in self.env:
                self.env["LD_LIBRARY_PATH"] = self.env["LD_LIBRARY_PATH_ORIG"]
        if self.smartctl and (pkexec or os.geteuid() == 0):
            command = [
                "/bin/sh",
                "-c",
                REPORT_SERVER,
                "disk-io-smart",
                self.smartctl,
                *self.paths,
            ]
            if os.geteuid() != 0:
                command[:0] = [pkexec, "--disable-internal-agent"]
            try:
                self.process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self.env,
                    bufsize=0,
                )
            except OSError as exc:
                self.reason = f"Cannot start SMART authorization: {exc}"
        Thread(target=self._serve, daemon=True).start()

    def read(self, path: Path) -> Future[str]:
        result = Future()
        if self.closed:
            result.set_result("The SMART session is closed.")
        else:
            self.requests.put((self.paths.index(path), result))
        return result

    def close(self) -> None:
        self.closed = True
        self.requests.put(None)
        if self.process:
            # EOF releases the helper even if the parent exits without a signal.
            self.process.stdin.close()
            if not self.authorized and self.process.poll() is None:
                try:
                    self.process.terminate()
                except PermissionError:
                    pass

    def _serve(self) -> None:
        try:
            if self.process:
                self.authorized = self.process.stdout.readline() == b"ready\n"
            while (request := self.requests.get()) is not None:
                index, result = request
                if not result.set_running_or_notify_cancel():
                    continue
                try:
                    report = (
                        self._report(index)
                        if not self.closed
                        else "The SMART session is closed."
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    report = f"Cannot read SMART data: {exc}"
                result.set_result(report)
        finally:
            if self.process:
                self.process.stdin.close()
                self.process.stdout.close()
                self.process.wait()

    def _report(self, index: int) -> str:
        if self.authorized:
            try:
                self.process.stdin.write(f"{index}\n".encode())
                reply = self.process.stdout.readline()
                if reply:
                    return (
                        base64.b64decode(reply.strip(), validate=True)
                        .decode(errors="replace")
                        .strip()
                        or "No SMART report returned."
                    )
            except BrokenPipeError:
                pass
            self.authorized = False
            self.reason = "The authorized SMART session ended."
        if not self.smartctl:
            return (
                "Install smartmontools and restart the viewer to enable SMART reports."
            )
        path = self.paths[index].resolve(strict=True)
        device_number(path)
        try:
            read = subprocess.run(
                [self.smartctl, "-a", "--", str(path)],
                check=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                env=self.env,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return "The SMART read timed out. Click Refresh to try again."
        text = (read.stdout + read.stderr).decode(errors="replace").strip()
        if (
            "permission denied" in text.lower()
            or "operation not permitted" in text.lower()
        ):
            return (
                f"{self.reason} Restart the viewer to request access again.\n\n{text}"
            )
        return text or f"No SMART report returned (exit status {read.returncode})."
