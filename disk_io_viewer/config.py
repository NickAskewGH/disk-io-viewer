import math
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    path: Path
    label: str


@dataclass(frozen=True)
class Config:
    devices: tuple[Device, ...]
    interval: float
    history: float


def device_number(path: Path) -> int:
    info = path.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise ValueError(f"{path} is not a block device")
    return info.st_rdev


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        data = tomllib.load(stream)

    def seconds(key: str, default: float) -> float:
        value = data.get(key, default)
        if type(value) not in (int, float) or not 0 < value < math.inf:
            raise ValueError(f"{key} must be a positive finite number")
        try:
            return float(value)
        except OverflowError as exc:
            raise ValueError(f"{key} is too large") from exc

    interval = seconds("sample_interval_seconds", 1)
    history = seconds("history_seconds", 60)
    if history < 2 * interval:
        raise ValueError("history_seconds must cover at least two sample intervals")

    entries = data.get("devices")
    if not isinstance(entries, list) or not entries:
        raise ValueError("devices must contain at least one [[devices]] entry")
    paths = set()
    numbers = {}
    devices = []
    for index, entry in enumerate(entries, 1):
        key = f"devices entry {index}"
        raw = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(raw, str) or "\x00" in raw or not Path(raw).is_absolute():
            raise ValueError(f"{key}.path must be an absolute device path")
        device_path = Path(raw)
        label = entry.get("label", device_path.name)
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{key}.label must be a non-empty string")
        if device_path in paths:
            raise ValueError(f"{key}.path duplicates {device_path}")
        paths.add(device_path)
        try:
            number = device_number(device_path)
        except OSError:
            pass  # Keep offline and inaccessible devices in the list for retry.
        except ValueError as exc:
            raise ValueError(f"{key}.path: {exc}") from exc
        else:
            if number in numbers:
                raise ValueError(f"{key}.path duplicates {numbers[number]}")
            numbers[number] = device_path
        devices.append(Device(device_path, label))
    return Config(tuple(devices), interval, history)
