"""Native macOS (Cocoa) control window for the Orchid chord processor."""

import subprocess
import sys
import threading

import mido
import objc
from AppKit import (
    NSAlert, NSApplication, NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered, NSBezierPath, NSButton, NSColor, NSMakeRect,
    NSMenu, NSMenuItem, NSPopUpButton, NSTextField, NSView, NSWindow,
    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

import settings
import update
from chords import ChordEngine, note_name, parse_note


def validate_config(in_port, out_port, base_text, channel_text):
    """Return (config, None) if inputs are usable, else (None, error message)."""
    if not in_port or not out_port:
        return None, "Pick both a MIDI In and MIDI Out port."
    base = parse_note(base_text)
    if base is None or not 0 <= base <= 116:
        return None, "Base note must be a note between C-1 and G#8 (like C2)."
    try:
        channel = int(str(channel_text))
    except ValueError:
        return None, "Channel must be a number 1-16."
    if not 1 <= channel <= 16:
        return None, "Channel must be a number 1-16."
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


PIANO_LOW, PIANO_HIGH = 24, 96          # C1 .. C7
_WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}     # pitch classes drawn as white keys


class PianoView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(PianoView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.sounding = set()
        return self

    @objc.python_method
    def set_sounding(self, notes):
        self.sounding = {n for n in notes if PIANO_LOW <= n <= PIANO_HIGH}
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bounds = self.bounds()
        width, height = bounds.size.width, bounds.size.height
        NSColor.grayColor().set()
        NSBezierPath.fillRect_(bounds)
        whites = [n for n in range(PIANO_LOW, PIANO_HIGH + 1)
                  if n % 12 in _WHITE_PCS]
        key_w = width / len(whites)
        white_x = {}
        x = 0.0
        for n in whites:
            white_x[n] = x
            if n in self.sounding:
                NSColor.systemBlueColor().set()
            else:
                NSColor.whiteColor().set()
            NSBezierPath.fillRect_(NSMakeRect(x + 0.5, 0.5, key_w - 1, height - 1))
            x += key_w
        black_w, black_h = key_w * 0.6, height * 0.6
        for n in range(PIANO_LOW, PIANO_HIGH + 1):
            if n % 12 in _WHITE_PCS:
                continue
            bx = white_x[n - 1] + key_w - black_w / 2
            if n in self.sounding:
                NSColor.systemBlueColor().set()
            else:
                NSColor.blackColor().set()
            NSBezierPath.fillRect_(NSMakeRect(bx, height - black_h, black_w, black_h))


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
            NSMakeRect(0, 0, 420, 330), style, NSBackingStoreBuffered, False)
        self.window.setTitle_("Orchid")
        self.window.center()
        content = self.window.contentView()

        content.addSubview_(_label("MIDI In", NSMakeRect(20, 288, 76, 20)))
        self.in_pop = NSPopUpButton.alloc().initWithFrame_(
            NSMakeRect(100, 284, 300, 26))
        content.addSubview_(self.in_pop)

        content.addSubview_(_label("MIDI Out", NSMakeRect(20, 254, 76, 20)))
        self.out_pop = NSPopUpButton.alloc().initWithFrame_(
            NSMakeRect(100, 250, 300, 26))
        content.addSubview_(self.out_pop)

        refresh = NSButton.alloc().initWithFrame_(NSMakeRect(96, 216, 100, 28))
        refresh.setTitle_("Refresh")
        refresh.setBezelStyle_(1)  # rounded push button
        refresh.setTarget_(self)
        refresh.setAction_("refreshPorts:")
        content.addSubview_(refresh)

        content.addSubview_(_label("Base note", NSMakeRect(20, 186, 76, 20)))
        self.base_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(100, 182, 60, 24))
        content.addSubview_(self.base_field)

        content.addSubview_(_label("Channel", NSMakeRect(185, 186, 64, 20)))
        self.channel_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(250, 182, 60, 24))
        content.addSubview_(self.channel_field)

        self.toggle_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(20, 142, 380, 32))
        self.toggle_btn.setTitle_("Start")
        self.toggle_btn.setBezelStyle_(1)
        self.toggle_btn.setTarget_(self)
        self.toggle_btn.setAction_("toggle:")
        content.addSubview_(self.toggle_btn)

        self.status = _label("stopped", NSMakeRect(20, 116, 380, 20))
        content.addSubview_(self.status)

        self.piano = PianoView.alloc().initWithFrame_(NSMakeRect(20, 16, 380, 88))
        content.addSubview_(self.piano)

        self.window.setDelegate_(self)
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _load_settings(self):
        stored = settings.load()
        self.base_field.setStringValue_(note_name(stored["base"]))
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
        AppHelper.callAfter(self._update_ui, text, engine.sounding_notes)

    @objc.python_method
    def _update_ui(self, text, notes):
        self.status.setStringValue_(text)
        self.piano.set_sounding(notes)

    @objc.python_method
    def _stop(self):
        self._close_ports()
        self.toggle_btn.setTitle_("Start")
        self.status.setStringValue_("stopped")
        self.piano.set_sounding([])

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

    # -- settings & updates -------------------------------------------------

    def openSettings_(self, sender):
        if getattr(self, "settings_window", None) is None:
            self._build_settings_window()
        self.settings_window.makeKeyAndOrderFront_(None)
        self._check_for_update()

    @objc.python_method
    def _build_settings_window(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 320, 150), style, NSBackingStoreBuffered, False)
        win.setTitle_("Orchid Settings")
        win.center()
        win.setReleasedWhenClosed_(False)
        content = win.contentView()
        content.addSubview_(_label("Orchid version %s" % update.local_version(),
                                   NSMakeRect(20, 104, 280, 20)))
        self.update_status = _label("", NSMakeRect(20, 74, 280, 20))
        content.addSubview_(self.update_status)
        self.update_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 28, 280, 32))
        self.update_btn.setTitle_("Update")
        self.update_btn.setBezelStyle_(1)
        self.update_btn.setTarget_(self)
        self.update_btn.setAction_("runUpdate:")
        self.update_btn.setHidden_(True)
        content.addSubview_(self.update_btn)
        self.settings_window = win

    @objc.python_method
    def _check_for_update(self):
        self.update_status.setStringValue_("Checking for updates…")
        self.update_btn.setHidden_(True)

        def worker():
            remote = update.fetch_remote_version()
            AppHelper.callAfter(self._update_check_done, remote)

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def _update_check_done(self, remote):
        if remote is None:
            self.update_status.setStringValue_("Could not check for updates (offline?).")
        elif update.is_newer(remote, update.local_version()):
            self.update_status.setStringValue_("Update available: %s" % remote)
            self.update_btn.setTitle_("Update to %s" % remote)
            self.update_btn.setHidden_(False)
        else:
            self.update_status.setStringValue_("You're up to date.")

    def runUpdate_(self, sender):
        self.update_btn.setEnabled_(False)
        self.update_status.setStringValue_("Downloading update…")

        def worker():
            try:
                update.download_update()
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r",
                     str(update.UPDATE_DIR / "requirements.txt")],
                    check=False, capture_output=True)
                err = None
            except OSError as exc:
                err = str(exc)
            AppHelper.callAfter(self._update_done, err)

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def _update_done(self, err):
        self.update_btn.setEnabled_(True)
        if err:
            self.update_status.setStringValue_("Update failed: %s" % err)
            return
        self.update_btn.setHidden_(True)
        self.update_status.setStringValue_("Updated — quit and reopen Orchid.")
        self._alert("Update installed. Quit and reopen Orchid to use it.")

    # -- window delegate ----------------------------------------------------

    def windowWillClose_(self, notification):
        self._close_ports()
        AppHelper.stopEventLoop()


def _build_menu(controller):
    menubar = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    menubar.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Settings…", "openSettings:", ",")
    settings_item.setTarget_(controller)
    app_menu.addItem_(settings_item)
    app_menu.addItem_(NSMenuItem.separatorItem())
    app_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit Orchid", "terminate:", "q"))
    app_item.setSubmenu_(app_menu)
    return menubar


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    controller = OrchidController.alloc().init()
    app.setMainMenu_(_build_menu(controller))
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
