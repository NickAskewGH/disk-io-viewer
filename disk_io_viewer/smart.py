import tkinter as tk
from tkinter import ttk

from .config import Device
from .smart_session import SmartSession


class SmartWindow(tk.Toplevel):
    """Read one drive on demand while the Tk event loop keeps sampling I/O."""

    def __init__(self, parent: tk.Tk, device: Device, name: str, session: SmartSession):
        super().__init__(parent, name=name)
        self.session = session
        self.device = device
        self.title(f"SMART · {device.label}")
        self.geometry("860x540")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text=str(device.path), padding=8).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.report = tk.Text(self, wrap="none", font="TkFixedFont", padx=8, pady=6)
        vertical = ttk.Scrollbar(self, command=self.report.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.report.xview)
        self.report.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.report.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")

        actions = ttk.Frame(self, padding=6)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.refresh = ttk.Button(actions, text="Refresh", command=self.read)
        self.refresh.pack(side="right")
        self.pending = None
        self.timer = None
        self.bind("<Destroy>", self.on_destroy)
        self.read()

    def show(self, message: str) -> None:
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", message)
        self.report.configure(state="disabled")
        self.report.yview_moveto(0)
        self.report.xview_moveto(0)

    def read(self) -> None:
        if self.pending is None:
            self.pending = self.session.read(self.device.path)
            self.refresh.state(["disabled"])
            self.show("Waiting for SMART report…")
            self.poll()

    def poll(self) -> None:
        self.timer = None
        if self.pending.done():
            self.show(self.pending.result())
            self.pending = None
            self.refresh.state(["!disabled"])
        else:
            self.timer = self.after(100, self.poll)

    def on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            if self.timer is not None:
                self.after_cancel(self.timer)
            if self.pending is not None:
                self.pending.cancel()
