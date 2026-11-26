import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, Device, device_number


@dataclass(frozen=True)
class Observation:
    timestamp: float
    number: int
    generation: int
    name: str
    sectors_read: int
    sectors_written: int


def read_device(path: Path) -> Observation:
    number = device_number(path)
    directory = Path(f"/sys/dev/block/{os.major(number)}:{os.minor(number)}").resolve(
        strict=True
    )
    with (directory / "stat").open() as stream:
        # diskseq changes when Linux reuses a device number after hotplug.
        try:
            generation = int((directory / "diskseq").read_text())
        except FileNotFoundError:  # Older kernels and partition nodes.
            generation = os.fstat(stream.fileno()).st_ino
        fields = stream.read().split()
        timestamp = time.monotonic()
    if len(fields) < 7:
        raise ValueError("Incomplete disk statistics")
    return Observation(
        timestamp, number, generation, directory.name, int(fields[2]), int(fields[6])
    )


@dataclass(frozen=True)
class Point:
    timestamp: float
    rates: tuple[float, float] | None


@dataclass
class Series:
    device: Device
    previous: Observation | None = None
    points: deque[Point] = field(default_factory=deque)
    status: str = "Collecting"
    kernel_name: str = ""

    def observe(self, current: Observation, interval: float) -> None:
        previous = self.previous
        self.previous = current
        self.kernel_name = current.name
        rates = None
        if previous and (current.number, current.generation) == (
            previous.number,
            previous.generation,
        ):
            elapsed = current.timestamp - previous.timestamp
            reads = current.sectors_read - previous.sectors_read
            writes = current.sectors_written - previous.sectors_written
            if 0 < elapsed <= 2 * interval and min(reads, writes) >= 0:
                rates = (512 * reads / elapsed, 512 * writes / elapsed)
        self.status = "Collecting" if rates is None else ""
        self.points.append(Point(current.timestamp, rates))

    def unavailable(self, timestamp: float, status: str) -> None:
        self.previous = None
        self.kernel_name = ""
        self.status = status
        self.points.append(Point(timestamp, None))


class Monitor:
    def __init__(self, config: Config):
        self.config = config
        self.series = [Series(device) for device in config.devices]

    def sample(self) -> float:
        seen = set()
        for series in self.series:
            try:
                obs = read_device(series.device.path)
            except PermissionError:
                series.unavailable(time.monotonic(), "Permission denied")
            except (OSError, ValueError):
                series.unavailable(time.monotonic(), "Unavailable")
            else:
                if obs.number in seen:
                    series.unavailable(obs.timestamp, "Duplicate device")
                else:
                    seen.add(obs.number)
                    series.observe(obs, self.config.interval)
        now = time.monotonic()
        cutoff = now - self.config.history
        for series in self.series:
            while series.points and series.points[0].timestamp < cutoff:
                series.points.popleft()
        return now
