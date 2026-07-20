"""Tkinter control window for the Orchid chord processor."""

import tkinter as tk
from tkinter import messagebox, ttk

import mido

import settings
from chords import ChordEngine


class OrchidApp:
    def __init__(self, root):
        self.root = root
        self.engine = None
        self.inport = None
        self.outport = None
        self._build()
        self._load_settings()

    def _build(self):
        self.root.title("Orchid")
        self.root.resizable(False, False)
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text="MIDI In").grid(row=0, column=0, sticky="w")
        self.in_box = ttk.Combobox(frame, state="readonly", width=32)
        self.in_box.grid(row=0, column=1, columnspan=2, pady=2)

        ttk.Label(frame, text="MIDI Out").grid(row=1, column=0, sticky="w")
        self.out_box = ttk.Combobox(frame, state="readonly", width=32)
        self.out_box.grid(row=1, column=1, columnspan=2, pady=2)

        ttk.Button(frame, text="Refresh", command=self.refresh_ports).grid(
            row=2, column=1, sticky="w", pady=2)

        ttk.Label(frame, text="Base note").grid(row=3, column=0, sticky="w")
        self.base_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.base_var, width=6).grid(
            row=3, column=1, sticky="w", pady=2)

        ttk.Label(frame, text="Channel").grid(row=4, column=0, sticky="w")
        self.channel_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.channel_var, width=6).grid(
            row=4, column=1, sticky="w", pady=2)

        self.toggle_btn = ttk.Button(frame, text="Start", command=self.toggle)
        self.toggle_btn.grid(row=5, column=0, columnspan=3, pady=(10, 4),
                             sticky="ew")

        self.status_var = tk.StringVar(value="stopped")
        ttk.Label(frame, textvariable=self.status_var).grid(
            row=6, column=0, columnspan=3)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _load_settings(self):
        stored = settings.load()
        self.base_var.set(str(stored["base"]))
        self.channel_var.set(str(stored["channel"]))
        self.refresh_ports()
        if stored["in_port"] in self.in_box["values"]:
            self.in_box.set(stored["in_port"])
        if stored["out_port"] in self.out_box["values"]:
            self.out_box.set(stored["out_port"])

    def refresh_ports(self):
        self.in_box["values"] = mido.get_input_names()
        self.out_box["values"] = mido.get_output_names()

    def toggle(self):
        if self.inport is None:
            self.start()
        else:
            self.stop()

    def _validated(self):
        in_port, out_port = self.in_box.get(), self.out_box.get()
        if not in_port or not out_port:
            messagebox.showerror("Orchid", "Pick both a MIDI In and MIDI Out port.")
            return None
        try:
            base = int(self.base_var.get())
            channel = int(self.channel_var.get())
        except ValueError:
            messagebox.showerror("Orchid", "Base note and channel must be numbers.")
            return None
        if not 0 <= base <= 116:
            messagebox.showerror("Orchid", "Base note must be 0-116.")
            return None
        if not 1 <= channel <= 16:
            messagebox.showerror("Orchid", "Channel must be 1-16.")
            return None
        return {"in_port": in_port, "out_port": out_port,
                "base": base, "channel": channel}

    def start(self):
        config = self._validated()
        if config is None:
            return
        settings.save(config)
        self.engine = ChordEngine(zone_base=config["base"],
                                  channel=config["channel"] - 1)
        try:
            self.outport = mido.open_output(config["out_port"])
            self.inport = mido.open_input(config["in_port"],
                                          callback=self._on_message)
        except (OSError, ValueError) as exc:
            self._close_ports()
            messagebox.showerror("Orchid", f"Could not open MIDI ports:\n{exc}")
            return
        self.toggle_btn.config(text="Stop")
        self.status_var.set("running")

    def _on_message(self, msg):
        # mido's callback thread: send MIDI here, but only the main thread
        # may touch widgets.
        engine, outport = self.engine, self.outport
        if engine is None or outport is None:
            return
        for out in engine.process(msg):
            outport.send(out)
        quality = engine.current_quality
        text = f"running — {quality}" if quality else "running"
        self.root.after(0, self.status_var.set, text)

    def stop(self):
        self._close_ports()
        self.toggle_btn.config(text="Start")
        self.status_var.set("stopped")

    def _close_ports(self):
        inport, self.inport = self.inport, None
        if inport is not None:
            inport.close()
        engine, self.engine = self.engine, None
        outport, self.outport = self.outport, None
        if outport is not None:
            if engine is not None:
                for out in engine.flush():
                    outport.send(out)
            outport.close()

    def on_close(self):
        self._close_ports()
        self.root.destroy()


def main():
    root = tk.Tk()
    OrchidApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
