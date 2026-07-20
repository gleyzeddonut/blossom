"""Native macOS (Cocoa) control window for the Orchid chord processor."""

import mido
import objc
from AppKit import (
    NSAlert, NSApplication, NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered, NSButton, NSMakeRect, NSPopUpButton, NSTextField,
    NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

import settings
from chords import ChordEngine


def validate_config(in_port, out_port, base_text, channel_text):
    """Return (config, None) if inputs are usable, else (None, error message)."""
    if not in_port or not out_port:
        return None, "Pick both a MIDI In and MIDI Out port."
    try:
        base = int(str(base_text))
        channel = int(str(channel_text))
    except ValueError:
        return None, "Base note and channel must be numbers."
    if not 0 <= base <= 116:
        return None, "Base note must be 0-116."
    if not 1 <= channel <= 16:
        return None, "Channel must be 1-16."
    return {"in_port": in_port, "out_port": out_port,
            "base": base, "channel": channel}, None


def _label(text, frame):
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    return field


class OrchidController(NSObject):
    def init(self):
        self = objc.super(OrchidController, self).init()
        if self is None:
            return None
        self.engine = None
        self.inport = None
        self.outport = None
        self._build_window()
        self._load_settings()
        return self

    # -- window construction ------------------------------------------------

    @objc.python_method
    def _build_window(self):
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 400, 240), style, NSBackingStoreBuffered, False)
        self.window.setTitle_("Orchid")
        self.window.center()
        content = self.window.contentView()

        content.addSubview_(_label("MIDI In", NSMakeRect(20, 196, 76, 20)))
        self.in_pop = NSPopUpButton.alloc().initWithFrame_(
            NSMakeRect(100, 192, 280, 26))
        content.addSubview_(self.in_pop)

        content.addSubview_(_label("MIDI Out", NSMakeRect(20, 162, 76, 20)))
        self.out_pop = NSPopUpButton.alloc().initWithFrame_(
            NSMakeRect(100, 158, 280, 26))
        content.addSubview_(self.out_pop)

        refresh = NSButton.alloc().initWithFrame_(NSMakeRect(96, 124, 100, 28))
        refresh.setTitle_("Refresh")
        refresh.setBezelStyle_(1)  # rounded push button
        refresh.setTarget_(self)
        refresh.setAction_("refreshPorts:")
        content.addSubview_(refresh)

        content.addSubview_(_label("Base note", NSMakeRect(20, 94, 76, 20)))
        self.base_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(100, 90, 60, 24))
        content.addSubview_(self.base_field)

        content.addSubview_(_label("Channel", NSMakeRect(185, 94, 64, 20)))
        self.channel_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(250, 90, 60, 24))
        content.addSubview_(self.channel_field)

        self.toggle_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(20, 50, 360, 32))
        self.toggle_btn.setTitle_("Start")
        self.toggle_btn.setBezelStyle_(1)
        self.toggle_btn.setTarget_(self)
        self.toggle_btn.setAction_("toggle:")
        content.addSubview_(self.toggle_btn)

        self.status = _label("stopped", NSMakeRect(20, 16, 360, 20))
        content.addSubview_(self.status)

        self.window.setDelegate_(self)
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _load_settings(self):
        stored = settings.load()
        self.base_field.setStringValue_(str(stored["base"]))
        self.channel_field.setStringValue_(str(stored["channel"]))
        self.refreshPorts_(None)
        if stored["in_port"] in list(self.in_pop.itemTitles()):
            self.in_pop.selectItemWithTitle_(stored["in_port"])
        if stored["out_port"] in list(self.out_pop.itemTitles()):
            self.out_pop.selectItemWithTitle_(stored["out_port"])

    # -- actions ------------------------------------------------------------

    def refreshPorts_(self, sender):
        self.in_pop.removeAllItems()
        self.in_pop.addItemsWithTitles_(mido.get_input_names())
        self.out_pop.removeAllItems()
        self.out_pop.addItemsWithTitles_(mido.get_output_names())

    def toggle_(self, sender):
        if self.inport is None:
            self._start()
        else:
            self._stop()

    @objc.python_method
    def _start(self):
        config, err = validate_config(
            self.in_pop.titleOfSelectedItem(),
            self.out_pop.titleOfSelectedItem(),
            self.base_field.stringValue(),
            self.channel_field.stringValue())
        if err:
            self._alert(err)
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
            self._alert("Could not open MIDI ports:\n%s" % exc)
            return
        self.toggle_btn.setTitle_("Stop")
        self.status.setStringValue_("running")

    @objc.python_method
    def _on_message(self, msg):
        # mido's callback thread: send MIDI here, marshal UI to main thread.
        engine, outport = self.engine, self.outport
        if engine is None or outport is None:
            return
        for out in engine.process(msg):
            outport.send(out)
        quality = engine.current_quality
        text = "running — %s" % quality if quality else "running"
        AppHelper.callAfter(self.status.setStringValue_, text)

    @objc.python_method
    def _stop(self):
        self._close_ports()
        self.toggle_btn.setTitle_("Start")
        self.status.setStringValue_("stopped")

    @objc.python_method
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

    @objc.python_method
    def _alert(self, text):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Orchid")
        alert.setInformativeText_(text)
        alert.runModal()

    # -- window delegate ----------------------------------------------------

    def windowWillClose_(self, notification):
        self._close_ports()
        AppHelper.stopEventLoop()


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    controller = OrchidController.alloc().init()  # noqa: F841 (kept alive)
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
