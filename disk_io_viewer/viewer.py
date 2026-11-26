import math
import time
import tkinter as tk
from itertools import pairwise
from tkinter import ttk

from .config import Config
from .sampler import Monitor, Series
from .smart import SmartWindow
from .smart_session import SmartSession

MIB = 1024**2
GIB = 1024**3
READ = "#2465c4"
WRITE = "#ce3434"
TRACE_WIDTH = 2
FRAME_SECONDS = 1 / 30
PLOT_LEFT = 62
RIGHT_MARGIN = 16
TEXT = "#26282b"
MUTED = "#545960"
PAPER = "#fafaf9"
GRID = "#d9dbd8"
PANEL_HEIGHT = 170


def axis_scale(peak: float) -> tuple[float, int, str]:
    """Return the ceiling in bytes/s and the unit for the four grid intervals."""
    unit, label = (GIB, "GiB/s") if peak >= GIB else (MIB, "MiB/s")
    target = max(peak, MIB) / unit / 4
    power = 10 ** math.floor(math.log10(target))
    step = next(n for n in (1, 2, 2.5, 5, 10) if n * power >= target)
    ceiling = 4 * step * power * unit
    if unit == MIB:
        ceiling = min(ceiling, GIB)
    return ceiling, unit, label


def rate_label(value: float) -> str:
    for unit, label in ((GIB, "GiB/s"), (MIB, "MiB/s"), (1024, "KiB/s")):
        if value >= unit:
            return f"{value / unit:.2f} {label}"
    return f"{value:.4g} B/s"


class Viewer:
    def __init__(self, root: tk.Tk, config: Config, smart_session: SmartSession):
        self.smart_session = smart_session
        self.root = root
        self.monitor = Monitor(config)
        self.now = self.deadline = time.monotonic()
        root.title(f"Disk I/O · {config.interval:g} s averages")
        root.minsize(420, 180)
        height = min(
            PANEL_HEIGHT * len(config.devices), root.winfo_screenheight() * 3 // 4
        )
        root.geometry(f"720x{height}")
        self.canvas = canvas = tk.Canvas(root, background=PAPER, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set, yscrollincrement=24)
        canvas.bind("<Button-1>", self.open_smart)
        canvas.bind("<Button-4>", lambda _: canvas.yview_scroll(-2, "units"))
        canvas.bind("<Button-5>", lambda _: canvas.yview_scroll(2, "units"))
        canvas.bind("<Configure>", lambda _: self.draw())
        self.tick()

    def open_smart(self, event: tk.Event) -> None:
        index = math.floor(self.canvas.canvasy(event.y) / PANEL_HEIGHT)
        if not 0 <= index < len(self.monitor.series):
            return
        name = f"smart{index}"
        window = self.root.children.get(name)
        if window is None:
            SmartWindow(
                self.root, self.monitor.series[index].device, name, self.smart_session
            )
        else:
            window.deiconify()
            window.lift()

    def tick(self) -> None:
        now = time.monotonic()
        if now >= self.deadline:
            self.now = self.monitor.sample()
            self.draw()
            now = time.monotonic()
            interval = self.monitor.config.interval
            # Preserve the cadence across slow ticks without replaying missed ones.
            self.deadline = now + (interval - (now - self.deadline) % interval)
        else:
            # Slide the existing curves; labels and grid stay fixed between samples.
            width = self.canvas.winfo_width() - PLOT_LEFT - RIGHT_MARGIN
            if width > 0:
                dx = (self.now - now) / self.monitor.config.history * width
                self.canvas.move("trace", dx, 0)
            self.now = now
        delay = min(max(0, self.deadline - now), FRAME_SECONDS)
        self.root.after(max(1, math.ceil(delay * 1000)), self.tick)

    def draw(self) -> None:
        canvas = self.canvas
        width = canvas.winfo_width()
        if width < 2:
            return
        canvas.delete("all")
        for index, series in enumerate(self.monitor.series):
            self.draw_panel(series, index * PANEL_HEIGHT, width)
        canvas.configure(
            scrollregion=(0, 0, width, PANEL_HEIGHT * len(self.monitor.series))
        )

    def draw_panel(self, series: Series, top: int, width: int) -> None:
        c = self.canvas
        title = series.device.label
        if series.kernel_name and series.kernel_name != title:
            title += f" ({series.kernel_name})"
        c.create_text(
            14,
            top + 16,
            text=title,
            fill=TEXT,
            anchor="w",
            font=("TkDefaultFont", 11, "bold"),
        )
        rates = series.points[-1].rates if series.points else None
        for index, (name, color) in enumerate((("Read", READ), ("Write", WRITE))):
            x = 15 + index * 157
            y = top + 39
            c.create_line(x, y, x + 22, y, fill=color, width=TRACE_WIDTH)
            value = rate_label(rates[index]) if rates is not None else "—"
            c.create_text(x + 28, y, anchor="w", fill=TEXT, text=f"{name} {value}")
        if series.status:
            c.create_text(
                width - 12, top + 39, text=series.status, anchor="e", fill=MUTED
            )

        left, right = PLOT_LEFT, width - RIGHT_MARGIN
        upper, lower = top + 64, top + 143
        peak = max(
            (max(p.rates) for p in series.points if p.rates is not None), default=0
        )
        ceiling, unit, label = axis_scale(peak)
        history = self.monitor.config.history
        for i in range(5):
            fraction = i / 4
            y = lower - fraction * (lower - upper)
            c.create_line(left, y, right, y, fill=GRID)
            x = left + fraction * (right - left)
            c.create_line(x, lower, x, upper, fill=GRID)
            age = (1 - fraction) * history
            c.create_text(
                x, lower + 12, text=f"−{age:g}s" if age else "now", fill=MUTED
            )

        for index, color in enumerate((READ, WRITE)):
            points = []
            for point in series.points:
                if point.rates is None:
                    self.draw_segment(points, color)
                    points.clear()
                    continue
                x = right - (self.now - point.timestamp) / history * (right - left)
                y = lower - point.rates[index] / ceiling * (lower - upper)
                points.append((x, y))
            self.draw_segment(points, color)
        # Mask the scrolling curves at the fixed left edge, beneath the tick labels.
        c.create_rectangle(0, upper - 2, left - 1, lower + 2, fill=PAPER, outline="")
        c.create_text(12, (upper + lower) / 2, angle=90, text=label, fill=MUTED)
        for i in range(5):
            fraction = i / 4
            c.create_text(
                left - 7,
                lower - fraction * (lower - upper),
                anchor="e",
                text=f"{fraction * ceiling / unit:g}",
                fill=MUTED,
            )

    def draw_segment(self, points: list[tuple[float, float]], color: str) -> None:
        if len(points) == 1:
            x, y = points[0]
            self.canvas.create_oval(
                x - 1, y - 1, x + 1, y + 1, fill=color, outline="", tags="trace"
            )
        elif points:
            self.canvas.create_line(
                *curve_coordinates(points),
                fill=color,
                width=TRACE_WIDTH,
                smooth="raw",
                splinesteps=12,
                capstyle="round",
                tags="trace",
            )


def curve_coordinates(points: list[tuple[float, float]]) -> list[float]:
    """Cubic Bézier controls through the samples, bounded by adjacent values."""
    slopes = []
    for (x0, y0), (x1, y1) in pairwise(points):
        slopes.append((y1 - y0) / (x1 - x0) if x1 > x0 else 0.0)

    # Flatten at peaks and troughs. Else use the gentler adjacent slope,
    # so even a large change in sample spacing cannot introduce an overshoot.
    tangents = [slopes[0]]
    for before, after in pairwise(slopes):
        slope = min((before, after), key=abs) if before * after > 0 else 0.0
        tangents.append(slope)
    tangents.append(slopes[-1])

    coords = list(points[0])
    for i, ((x0, y0), (x1, y1)) in enumerate(pairwise(points)):
        dx = (x1 - x0) / 3
        coords.extend(
            (x0 + dx, y0 + dx * tangents[i], x1 - dx, y1 - dx * tangents[i + 1], x1, y1)
        )
    return coords
