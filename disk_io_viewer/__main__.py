import argparse
import sys
from pathlib import Path

from disk_io_viewer.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Live per-device disk I/O graphs")
    default_config = Path("disk-io.toml")
    if getattr(sys, "frozen", False):
        default_config = Path(sys.executable).with_name("disk-io.toml")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help="local TOML file (default: %(default)s)",
    )
    args = parser.parse_args()
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{args.config}: {exc}\n")
    try:
        import tkinter as tk

        from disk_io_viewer.smart_session import SmartSession
        from disk_io_viewer.viewer import Viewer
    except ImportError as exc:
        parser.exit(1, f"Python with Tk support is required: {exc}\n")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        parser.exit(1, f"Cannot open the disk I/O window: {exc}\n")
    session = SmartSession(config.devices)
    try:
        Viewer(root, config, session)
        root.mainloop()
    finally:
        session.close()


if __name__ == "__main__":
    main()
