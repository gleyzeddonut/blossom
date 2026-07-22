"""Native macOS (Cocoa) control window for the Orchid chord processor.

Styled as a dark "hardware panel": glowing chord display, piano with a
highlighted modifier zone, chord-key legend, and Perform / MIDI cards.
"""

import random
import subprocess
import sys
import threading
import time
import traceback

import mido
import objc
from AppKit import (
    NSAlert, NSAppearance, NSAppearanceNameDarkAqua, NSApplication,
    NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
    NSBezierPath, NSButton, NSColor, NSFont, NSFontAttributeName,
    NSFontWeightBold, NSFontWeightRegular, NSFontWeightSemibold,
    NSForegroundColorAttributeName, NSGradient, NSKernAttributeName,
    NSGraphicsContext, NSMakeRect, NSMenu, NSMenuItem, NSPopUpButton,
    NSShadow, NSSlider, NSSliderCell,
    NSTextAlignmentCenter, NSTextAlignmentRight, NSTextField, NSView,
    NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from AppKit import NSMutableParagraphStyle, NSParagraphStyleAttributeName
from Foundation import NSAttributedString, NSObject
from PyObjCTools import AppHelper

import settings
import update
from chords import (CHORD_NAMES, NOTE_NAMES, QUALITY_INTERVALS,
                    ChordEngine, note_name, parse_note)


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


# -- palette ----------------------------------------------------------------

def _rgb(hexstr, alpha=1.0):
    hexstr = hexstr.lstrip("#")
    r, g, b = (int(hexstr[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


PANEL_TOP, PANEL_BOTTOM = "#232028", "#1B1820"
DISPLAY_BG = "#0D0B12"
WELL_BG = "#141119"
ACCENT = "#9D6BFF"
GLOW_TEXT = "#B48AFF"
DIM_ACCENT = "#6D55A0"
TEXT_PRIMARY = "#E0DAEE"
TEXT_SECONDARY = "#C9C2D8"
TEXT_SECTION = "#8A819C"
TEXT_HINT = "#6F6786"
TEXT_FAINT = "#57565E"
BRAND = "#B9A8DE"
ERROR_RED = "#FF6B60"

PIANO_WHITE = "#ECE7DB"
PIANO_BLACK = "#17141C"
ZONE_WHITE = "#D9C6F4"
ZONE_BLACK = "#7A5FAE"
SOUNDING = "#9D6BFF"

PAD_TOP, PAD_BOTTOM = "#312C3B", "#262130"
PAD_NOTE, PAD_QUALITY = "#E4DCF5", "#A48FD4"

# Arp step orders. "played" follows the order notes were added.
_ARP_PATTERNS = ("up", "down", "updn", "rand", "played")

# MIDI clock runs at 24 ticks per quarter note.
_ARP_TICKS = {"1/4": 24, "1/8": 12, "1/8T": 8,
              "1/16": 6, "1/16T": 4, "1/32": 3}

# Arp subdivisions: fraction of a quarter note per step.
_ARP_DIVS = {"1/4": 1.0, "1/8": 0.5, "1/8T": 1 / 3.0,
             "1/16": 0.25, "1/16T": 1 / 6.0, "1/32": 0.125}

# Short quality names for the chord-key legend.
_QUALITY_ABBREV = {"major": "maj", "minor": "min", "dom7": "7",
                   "halfdim": "\u00f87", "minMaj7": "mM7", "min9": "m9",
                   "maj9": "M9", "min6": "m6", "dim7": "\u00b07"}

_NO_CHORD = "\u2014"                   # legend slot with nothing assigned

# Default chord-key layout, one quality per zone offset.
DEFAULT_CHORD_KEYS = ["major", "maj7", "minor", "min7", "dom7", "add9",
                      "sus4", "13", "halfdim", "dim", "aug", _NO_CHORD]


def _chord_key_map(names):
    """(chord_map, chord_names) for the engine from 12 slot assignments."""
    cmap, cnames = {}, {}
    for i, name in enumerate(names):
        intervals = QUALITY_INTERVALS.get(name)
        if intervals:
            cmap[i] = intervals
            cnames[i] = name
    return cmap, cnames


def _label(text, frame, size=13, color=None, bold=False, mono=False,
           align=None):
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    weight = NSFontWeightBold if bold else NSFontWeightRegular
    if mono:
        field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(size, weight))
    elif bold:
        field.setFont_(NSFont.boldSystemFontOfSize_(size))
    else:
        field.setFont_(NSFont.systemFontOfSize_(size))
    if color is not None:
        field.setTextColor_(color)
    if align is not None:
        field.setAlignment_(align)
    return field


def _draw_centered(text, cx, y, font, color):
    astr = NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font,
               NSForegroundColorAttributeName: color})
    size = astr.size()
    astr.drawAtPoint_((cx - size.width / 2.0, y))


class GradientView(NSView):
    """Window background: vertical panel gradient."""

    def drawRect_(self, rect):
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            _rgb(PANEL_BOTTOM), _rgb(PANEL_TOP))
        gradient.drawInRect_angle_(self.bounds(), 90)


class CardView(NSView):
    """Rounded translucent card with optional row separator lines."""

    def initWithFrame_(self, frame):
        self = objc.super(CardView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.seps = []       # y offsets (from card bottom) of separators
        return self

    def drawRect_(self, rect):
        bounds = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, 12, 12)
        _rgb("#FFFFFF", 0.03).set()
        path.fill()
        _rgb("#FFFFFF", 0.07).set()
        path.setLineWidth_(0.5)
        path.stroke()
        _rgb("#FFFFFF", 0.06).set()
        for y in self.seps:
            NSBezierPath.fillRect_(
                NSMakeRect(16, y, bounds.size.width - 32, 0.5))


class DisplayView(NSView):
    """Inset dark 'screen' behind the chord display."""

    def drawRect_(self, rect):
        bounds = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, 12, 12)
        _rgb(DISPLAY_BG).set()
        path.fill()
        _rgb("#FFFFFF", 0.07).set()  # top edge highlight
        NSBezierPath.fillRect_(NSMakeRect(12, bounds.size.height - 1,
                                          bounds.size.width - 24, 0.5))


def _accent_shadow(blur):
    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(_rgb(ACCENT, 0.65))
    shadow.setShadowBlurRadius_(blur)
    shadow.setShadowOffset_((0, 0))
    return shadow


class PillSwitch(NSView):
    """Custom animated toggle: accent pill with glow when on. Drawn by us,
    so it keeps its colour when the window is in the background."""

    def initWithFrame_(self, frame):
        self = objc.super(PillSwitch, self).initWithFrame_(frame)
        if self is None:
            return None
        self._state = False
        self._progress = 0.0      # animated 0 (off) .. 1 (on)
        self._animating = False
        self.on_change = None     # callable(self)
        self.pill_size = (38.0, 20.0)
        return self

    @objc.python_method
    def state(self):
        return 1 if self._state else 0

    @objc.python_method
    def setState_(self, value):
        self._state = bool(value)
        self._progress = 1.0 if self._state else 0.0   # no animation
        self.setNeedsDisplay_(True)

    def mouseDownCanMoveWindow(self):
        return False   # clicks operate the control, never drag the window

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self._state = not self._state
        self._animate()
        if self.on_change is not None:
            self.on_change(self)

    @objc.python_method
    def _animate(self):
        if self._animating:
            return

        def tick():
            target = 1.0 if self._state else 0.0
            diff = target - self._progress
            if abs(diff) < 0.03:
                self._progress = target
                self._animating = False
                self.setNeedsDisplay_(True)
                return
            self._progress += diff * 0.35   # ease out
            self.setNeedsDisplay_(True)
            AppHelper.callLater(1 / 60.0, tick)

        self._animating = True
        tick()

    def drawRect_(self, rect):
        bounds = self.bounds()
        width, height = self.pill_size
        x = bounds.size.width - width
        y = (bounds.size.height - height) / 2.0
        track = NSMakeRect(x, y, width, height)
        knob_r = height - 4
        p = self._progress
        track_color = _rgb("#39323F").blendedColorWithFraction_ofColor_(
            p, _rgb(ACCENT))
        NSGraphicsContext.saveGraphicsState()
        if p > 0.01:
            shadow = NSShadow.alloc().init()
            shadow.setShadowColor_(_rgb(ACCENT, 0.65 * p))
            shadow.setShadowBlurRadius_(8)
            shadow.setShadowOffset_((0, 0))
            shadow.set()
        track_color.set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            track, height / 2, height / 2).fill()
        NSGraphicsContext.restoreGraphicsState()
        knob_color = _rgb("#79707F").blendedColorWithFraction_ofColor_(
            p, _rgb(PANEL_BOTTOM))
        knob_x = x + 2 + p * (width - knob_r - 4)
        knob_color.set()
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(knob_x, y + 2, knob_r, knob_r)).fill()


class WellView(NSView):
    """Dark rounded 'well' drawn behind popup buttons."""

    def drawRect_(self, rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 6, 6)
        _rgb(WELL_BG).set()
        path.fill()
        _rgb("#FFFFFF", 0.12).set()
        path.setLineWidth_(0.5)
        path.stroke()


class ChevronView(NSView):
    """Small vector 'v' indicator for dropdown wells; crisp at any scale."""

    def drawRect_(self, rect):
        bounds = self.bounds()
        cx = bounds.size.width / 2.0
        cy = bounds.size.height / 2.0
        path = NSBezierPath.bezierPath()
        path.moveToPoint_((cx - 3.5, cy + 1.8))
        path.lineToPoint_((cx, cy - 1.8))
        path.lineToPoint_((cx + 3.5, cy + 1.8))
        _rgb(TEXT_FAINT).set()
        path.setLineWidth_(1.5)
        path.setLineCapStyle_(1)   # round
        path.stroke()


class DragValueView(NSView):
    """Numeric readout you drag vertically to change, or double-click to
    type. Draws itself, so it matches the panel at any scale."""

    def initWithFrame_(self, frame):
        self = objc.super(DragValueView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.value = 0.0
        self.min_value, self.max_value = 0.0, 100.0
        self.step = 0.5            # units per pixel of vertical drag
        self.fmt = lambda v: "%d" % round(v)
        self.on_change = None      # callable(self)
        self.enabled = True
        self._drag = None
        self._editor = None
        self._override = None      # display text that replaces the value
        return self

    def mouseDownCanMoveWindow(self):
        return False

    def acceptsFirstMouse_(self, event):
        return True

    @objc.python_method
    def set_value(self, value, notify=True):
        self.value = max(self.min_value, min(self.max_value, float(value)))
        self.setNeedsDisplay_(True)
        if notify and self.on_change is not None:
            self.on_change(self)

    @objc.python_method
    def set_override(self, text):
        self._override = text
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        if not self.enabled:
            return
        if event.clickCount() >= 2:
            self._begin_edit()
            return
        self._drag = (event.locationInWindow().y, self.value)

    def mouseDragged_(self, event):
        if self._drag is None or not self.enabled:
            return
        y0, v0 = self._drag
        self._override = None
        self.set_value(v0 + (event.locationInWindow().y - y0) * self.step)

    def mouseUp_(self, event):
        self._drag = None

    @objc.python_method
    def _begin_edit(self):
        if self._editor is not None:
            return
        field = NSTextField.alloc().initWithFrame_(self.bounds())
        field.setStringValue_(self.fmt(self.value).split()[0].rstrip("%"))
        field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(
            11, NSFontWeightRegular))
        field.setBezeled_(False)
        field.setDrawsBackground_(True)
        field.setBackgroundColor_(_rgb(WELL_BG))
        field.setTextColor_(_rgb(GLOW_TEXT))
        field.setTarget_(self)
        field.setAction_("editDone:")
        self.addSubview_(field)
        self._editor = field
        self.window().makeFirstResponder_(field)

    def editDone_(self, sender):
        try:
            value = float(str(sender.stringValue()).strip())
        except ValueError:
            value = self.value
        editor, self._editor = self._editor, None
        if editor is not None:
            editor.removeFromSuperview()
        self._override = None
        self.set_value(value)

    def drawRect_(self, rect):
        bounds = self.bounds()
        text = self._override if self._override else self.fmt(self.value)
        astr = NSAttributedString.alloc().initWithString_attributes_(
            text, {NSFontAttributeName:
                   NSFont.monospacedSystemFontOfSize_weight_(
                       11, NSFontWeightRegular),
                   NSForegroundColorAttributeName: _rgb(GLOW_TEXT)})
        size = astr.size()
        astr.drawAtPoint_((bounds.size.width - size.width,
                           (bounds.size.height - size.height) / 2.0))


class MenuValueView(NSView):
    """Dropdown rendered as plain text with a small chevron beside it -
    no box. Click anywhere on it to pop the menu."""

    def initWithFrame_(self, frame):
        self = objc.super(MenuValueView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.items = []
        self.value = ""
        self.on_change = None
        self.font_size = 12.0
        self.enabled = True
        return self

    @objc.python_method
    def titleOfSelectedItem(self):
        return self.value

    @objc.python_method
    def selectItemWithTitle_(self, title):
        if title in self.items:
            self.value = str(title)
            self.setNeedsDisplay_(True)

    @objc.python_method
    def setEnabled_(self, on):
        self.enabled = bool(on)
        self.setNeedsDisplay_(True)

    def mouseDownCanMoveWindow(self):
        return False

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        if not self.enabled:
            return
        menu = NSMenu.alloc().init()
        for name in self.items:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                name, "picked:", "")
            item.setTarget_(self)
            if name == self.value:
                item.setState_(1)
            menu.addItem_(item)
        NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self)

    def picked_(self, sender):
        self.value = str(sender.title())
        self.setNeedsDisplay_(True)
        if self.on_change is not None:
            self.on_change(self)

    def drawRect_(self, rect):
        bounds = self.bounds()
        color = _rgb(GLOW_TEXT, 0.9 if self.enabled else 0.4)
        astr = NSAttributedString.alloc().initWithString_attributes_(
            self.value, {NSFontAttributeName:
                         NSFont.monospacedSystemFontOfSize_weight_(
                             self.font_size, NSFontWeightRegular),
                         NSForegroundColorAttributeName: color})
        size = astr.size()
        y = (bounds.size.height - size.height) / 2.0
        astr.drawAtPoint_((0, y))
        cx = size.width + 9
        cy = bounds.size.height / 2.0
        path = NSBezierPath.bezierPath()
        path.moveToPoint_((cx - 3.2, cy + 1.6))
        path.lineToPoint_((cx, cy - 1.6))
        path.lineToPoint_((cx + 3.2, cy + 1.6))
        _rgb(TEXT_FAINT).set()
        path.setLineWidth_(1.4)
        path.setLineCapStyle_(1)
        path.stroke()


class FooterStrip(NSView):
    """Full-bleed recessed strip at the bottom of the window."""

    def drawRect_(self, rect):
        bounds = self.bounds()
        _rgb("#000000", 0.18).set()
        NSBezierPath.fillRect_(bounds)
        _rgb("#FFFFFF", 0.07).set()   # top hairline
        NSBezierPath.fillRect_(NSMakeRect(0, bounds.size.height - 0.5,
                                          bounds.size.width, 0.5))


class FooterWell(NSView):
    """Quiet labeled well used in the MIDI footer."""

    def initWithFrame_(self, frame):
        self = objc.super(FooterWell, self).initWithFrame_(frame)
        if self is None:
            return None
        self.label = ""
        return self

    def drawRect_(self, rect):
        bounds = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, 5, 5)
        _rgb("#141119", 0.7).set()
        path.fill()
        _rgb("#FFFFFF", 0.08).set()
        path.setLineWidth_(0.5)
        path.stroke()
        astr = NSAttributedString.alloc().initWithString_attributes_(
            self.label, {NSFontAttributeName: NSFont.boldSystemFontOfSize_(10),
                         NSForegroundColorAttributeName: _rgb(TEXT_FAINT),
                         NSKernAttributeName: 0.8})
        astr.drawAtPoint_((9, (bounds.size.height - astr.size().height) / 2.0))


class GlowSliderCell(NSSliderCell):
    """Slider with a dark track, glowing accent fill, and soft knob."""

    def drawBarInside_flipped_(self, rect, flipped):
        # Span the track between the knob-centre extremes so the knob
        # visually reaches both ends of the bar.
        knob = self.knobRectFlipped_(flipped)
        inset = knob.size.width / 2.0
        track = NSMakeRect(rect.origin.x + inset,
                           rect.origin.y + (rect.size.height - 6) / 2.0,
                           rect.size.width - 2 * inset, 6)
        _rgb(WELL_BG).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            track, 3, 3).fill()
        # Fill up to the knob's centre so bar and knob stay aligned.
        filled_w = knob.origin.x + knob.size.width / 2.0 - track.origin.x
        if filled_w > 3:
            filled = NSMakeRect(track.origin.x, track.origin.y,
                                filled_w, track.size.height)
            NSGraphicsContext.saveGraphicsState()
            _accent_shadow(6).set()
            _rgb(ACCENT).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                filled, 3, 3).fill()
            NSGraphicsContext.restoreGraphicsState()

    def drawKnob_(self, rect):
        # Centre the knob on the track, not on the knob rect (they differ).
        bar = self.barRectFlipped_(self.controlView().isFlipped())
        center_y = bar.origin.y + bar.size.height / 2.0
        knob = NSMakeRect(rect.origin.x + (rect.size.width - 13) / 2.0,
                          center_y - 9, 13, 18)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            knob, 3, 3)
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            _rgb("#2C2734"), _rgb("#4A4454"))
        gradient.drawInBezierPath_angle_(path, 90)
        _rgb("#FFFFFF", 0.12).set()
        path.setLineWidth_(0.5)
        path.stroke()


class LegendView(NSView):
    """Row of 12 pads naming the chord-quality keys of the modifier zone.
    Click a pad to reassign its quality."""

    def initWithFrame_(self, frame):
        self = objc.super(LegendView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.base = 36
        self.names = list(DEFAULT_CHORD_KEYS)
        self.on_pick = None      # callable(slot_index, event)
        return self

    @objc.python_method
    def set_base(self, base):
        self.base = base
        self.setNeedsDisplay_(True)

    @objc.python_method
    def set_assignments(self, names):
        self.names = list(names)
        self.setNeedsDisplay_(True)

    def mouseDownCanMoveWindow(self):
        return False   # clicks operate the control, never drag the window

    def mouseDown_(self, event):
        if self.on_pick is None:
            return
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        pad_w = (self.bounds().size.width - 11 * 4.0) / 12.0
        index = int(point.x / (pad_w + 4.0))
        if 0 <= index < 12:
            self.on_pick(index, event)

    def drawRect_(self, rect):
        bounds = self.bounds()
        width, height = bounds.size.width, bounds.size.height
        pad_w = (width - 11 * 4.0) / 12.0
        note_font = NSFont.boldSystemFontOfSize_(11)
        quality_font = NSFont.systemFontOfSize_(9)
        for i in range(12):
            x = i * (pad_w + 4.0)
            pad = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, 0, pad_w, height), 8, 8)
            gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
                _rgb(PAD_BOTTOM), _rgb(PAD_TOP))
            gradient.drawInBezierPath_angle_(pad, 90)
            cx = x + pad_w / 2.0
            _draw_centered(NOTE_NAMES[(self.base + i) % 12], cx,
                           height - 17, note_font, _rgb(PAD_NOTE))
            name = self.names[i] if i < len(self.names) else _NO_CHORD
            quality = _QUALITY_ABBREV.get(name, name)
            _draw_centered(quality, cx, 3, quality_font, _rgb(PAD_QUALITY))


PIANO_LOW, PIANO_HIGH = 24, 96          # C1 .. C7
_WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}     # pitch classes drawn as white keys
_BLACK_W = 0.62                         # black key width as share of white


class PianoView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(PianoView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.sounding = set()
        self.zone = set()        # modifier keys, tinted violet
        self.on_note = None      # callable(note, down) for mouse presses
        self._mouse_note = None
        return self

    @objc.python_method
    def set_sounding(self, notes):
        self.sounding = {n for n in notes if PIANO_LOW <= n <= PIANO_HIGH}
        self.setNeedsDisplay_(True)

    @objc.python_method
    def set_zone(self, notes):
        self.zone = {n for n in notes if PIANO_LOW <= n <= PIANO_HIGH}
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _geometry(self):
        bounds = self.bounds()
        width, height = bounds.size.width, bounds.size.height
        whites = [n for n in range(PIANO_LOW, PIANO_HIGH + 1)
                  if n % 12 in _WHITE_PCS]
        key_w = width / len(whites)
        return width, height, whites, key_w

    @objc.python_method
    def _key_color(self, n, default):
        if n in self.sounding:
            return _rgb(SOUNDING)
        if n in self.zone:
            return default is _WHITE and _rgb(ZONE_WHITE) or _rgb(ZONE_BLACK)
        return default is _WHITE and _rgb(PIANO_WHITE) or _rgb(PIANO_BLACK)

    def drawRect_(self, rect):
        width, height, whites, key_w = self._geometry()
        container = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 8, 8)
        _rgb(DISPLAY_BG).set()
        container.fill()
        NSGraphicsContext.saveGraphicsState()
        container.addClip()
        # Keys overshoot the top edge so only their bottom corners show round.
        white_x = {}
        x = 0.0
        for n in whites:
            white_x[n] = x
            self._fill_key(n, _WHITE,
                           NSMakeRect(x, 2, key_w, height + 4), 3)
            x += key_w
        # soft separator lines between white keys instead of hard gaps
        _rgb("#000000", 0.18).set()
        for i in range(1, len(whites)):
            NSBezierPath.fillRect_(
                NSMakeRect(i * key_w - 0.5, 2, 1, height))
        black_w, black_h = key_w * _BLACK_W, height * 0.6
        shadow = NSShadow.alloc().init()
        shadow.setShadowColor_(_rgb("#000000", 0.45))
        shadow.setShadowBlurRadius_(3.0)
        shadow.setShadowOffset_((0, -1.5))
        for n in range(PIANO_LOW, PIANO_HIGH + 1):
            if n % 12 in _WHITE_PCS:
                continue
            bx = white_x[n - 1] + key_w - black_w / 2
            NSGraphicsContext.saveGraphicsState()
            shadow.set()                      # black keys sit above the whites
            self._fill_key(n, _BLACK,
                           NSMakeRect(bx, height - 2 - black_h,
                                      black_w, black_h + 8), 2.5)
            NSGraphicsContext.restoreGraphicsState()
        NSGraphicsContext.restoreGraphicsState()

    @objc.python_method
    def _fill_key(self, n, kind, rect, radius):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, radius, radius)
        if n in self.sounding:
            NSGraphicsContext.saveGraphicsState()
            _accent_shadow(6).set()
            self._key_color(n, kind).set()
            path.fill()
            NSGraphicsContext.restoreGraphicsState()
        else:
            self._key_color(n, kind).set()
            path.fill()

    @objc.python_method
    def note_at(self, x, y):
        """MIDI note under view-local point (x, y), or None."""
        width, height, whites, key_w = self._geometry()
        if not (0 <= x < width and 0 <= y <= height):
            return None
        black_w, black_h = key_w * _BLACK_W, height * 0.6
        if y >= height - black_h:          # black keys sit on top
            for i, w in enumerate(whites):
                n = w + 1
                if n % 12 in _WHITE_PCS or n > PIANO_HIGH:
                    continue
                bx = i * key_w + key_w - black_w / 2
                if bx <= x <= bx + black_w:
                    return n
        return whites[int(x / key_w)]

    def mouseDownCanMoveWindow(self):
        return False   # clicks operate the control, never drag the window

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        note = self.note_at(point.x, point.y)
        if note is not None and self.on_note is not None:
            self._mouse_note = note
            self.on_note(note, True)

    def mouseUp_(self, event):
        if self._mouse_note is not None and self.on_note is not None:
            note, self._mouse_note = self._mouse_note, None
            self.on_note(note, False)


# sentinels for PianoView._key_color's default-colour selection
_WHITE, _BLACK = object(), object()


HELP_TEXT = """\
BLOSSOM — SETUP & GUIDE

WHAT IT IS
Blossom sits between a MIDI keyboard and a synth. You play simple
notes; Blossom turns them into chords and sends them to your synth.
It makes no sound of its own — the synth on the Output port does.

FIRST-TIME SETUP
1. Input: the keyboard you play (e.g. your Prophet).
2. Output: the synth that should make sound (e.g. a Juno via a
   USB MIDI interface). Match "Channel" to the channel your synth
   listens on (usually 1).
3. Play a key above the bottom octave — it should light up blue on
   the piano and sound on your synth.

No sound? On your keyboard, make sure MIDI out is enabled over USB
(on a Prophet 6: GLOBALS -> MIDI Out Select -> USB). Check the synth
end with a click on Blossom's on-screen piano: if clicking makes
sound, the problem is the keyboard side; if not, it's the synth side.
Use "Refresh" after plugging in gear.

CHORD KEYS (the violet bottom octave)
Hold one or more chord keys while playing notes above the zone:
maj, maj7, min, min7, 7, add9, sus4, 13, half-dim, dim, aug.
Held keys COMBINE (maj7 + add9 = maj9). Change or release them
while a chord rings and it morphs live. "Base note" moves this zone.

KEY MODE
Set "Key" and every white-key note plays its correct diatonic chord
(in C: C maj, D min, E min...). Chord keys always override.
The menu next to Key picks what off-key (black-key) notes do:
  V7    the dominant of the note below (C# -> G7). Classic V-of.
  dom7  a 7th chord on the pressed key (C# -> C#7). Tritone sub.
  snap  the chord of the note below (C# -> C maj). Never wrong.
  thru  just the bare note.
With a Key set, chord-key tensions bend into the scale (b9, #11...).

PERFORM
  Spread    lifts a middle voice an octave — wider, airier chords.
  Mono      one chord at a time; a new note releases the last chord.
  Strum     rolls chord notes low-to-high, guitar-style.
  Humanize  small random timing and velocity — less robotic.
  Arp       cycles the held chord instead of sustaining it.
            Pick a subdivision (1/8, 1/16, triplets...) and tempo.
Mod wheel: pushing it up cascades the chord through inversions.
Voice leading is automatic — chords connect smoothly on their own.

SYNCING THE ARP TO YOUR DAW
1. Open Audio MIDI Setup -> Window -> Show MIDI Studio.
   Double-click "IAC Driver" (it may look greyed out), tick
   "Device is online", and make sure the Ports list has at least
   one bus - if it's empty, click "+" to add one ("IAC Bus 1").
   Click Apply. Restart your DAW so it sees the new port.
2. Tell your DAW to send MIDI clock to the IAC bus:
   - Ableton Live: Settings -> Link/Tempo/MIDI -> MIDI Ports ->
     enable "Sync" Out for the IAC bus.
   - Logic Pro: Settings -> MIDI -> Sync -> MIDI Clock ->
     transmit to the IAC bus.
3. In Blossom, set "Sync" to that IAC bus, flip the Sync toggle on,
   and press play in the DAW.
The tempo readout shows the DAW's tempo, the arp locks to the beat,
and pressing play restarts the pattern on the downbeat. Stop the
DAW and the arp falls back to Blossom's own tempo slider.

If the arp sounds offset from the beat:
- Stop and restart DAW playback once (that re-anchors the downbeat;
  Blossom can't know the beat if it joined while the DAW was already
  playing).
- In Ableton, expand the IAC port row in the MIDI Ports list and
  nudge "Sync Delay" until it sits in the pocket - Live's clock
  output commonly needs this with any external gear.

TIPS
- Key mode + Mono + Arp 1/16 with the DAW rolling = one-finger
  synced sequences.
- Play two chord roots at once and the display names the combined
  harmony (C + Em reads "C maj7").
- Settings save automatically and restore on launch.
"""


class OrchidController(NSObject):
    def init(self):
        self = objc.super(OrchidController, self).init()
        if self is None:
            return None
        self.engine = None
        self.inport = None
        self.outport = None
        self.strum_ms = 0
        self.humanize_ms = 0
        self.chord_keys = list(DEFAULT_CHORD_KEYS)
        self._strum_lock = threading.Lock()
        self._pending = {}   # note -> Timer for strum-delayed note-ons
        self.arp_on = False
        self.arp_pattern = "up"
        self.arp_octaves = 1
        self.arp_gate = 0.6
        self.tempo_bpm = 120
        self.arp_rate_ms = 250     # derived from tempo and subdivision
        self._arp_lock = threading.Lock()
        self._arp_notes = {}     # note -> velocity, the arp's target pool
        self._arp_stop = threading.Event()
        self._arp_idx = 0
        self.clock_inport = None
        self._last_tick = 0.0    # monotonic time of the last MIDI clock
        self._tick_count = -1
        self._tick_dts = []      # recent tick intervals, for tempo display
        self._build_window()
        self._load_settings()
        threading.Thread(target=self._arp_loop, daemon=True).start()
        return self

    # -- window construction ------------------------------------------------

    @objc.python_method
    def _build_window(self):
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskResizable
                 | NSWindowStyleMaskFullSizeContentView)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 500, 840), style, NSBackingStoreBuffered, False)
        self.window.setTitle_("Blossom")
        self.window.setTitleVisibility_(1)             # hidden
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setMovableByWindowBackground_(True)
        self.window.setAppearance_(
            NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        self.window.setContentAspectRatio_((500.0, 840.0))
        self.window.setContentMinSize_((400.0, 672.0))
        self.window.setContentMaxSize_((760.0, 1277.0))
        self.window.center()

        # Everything is laid out in a fixed 500x796 panel; resizing the
        # window scales the panel (windowDidResize_), keeping proportions.
        self.panel = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 500, 840))
        self.window.contentView().addSubview_(self.panel)
        content = self.panel

        background = GradientView.alloc().initWithFrame_(content.bounds())
        content.addSubview_(background)

        # -- title area ------------------------------------------------
        wordmark = _label("", NSMakeRect(0, 798, 500, 18))
        centered = NSMutableParagraphStyle.alloc().init()
        centered.setAlignment_(NSTextAlignmentCenter)
        wordmark.setAttributedStringValue_(
            NSAttributedString.alloc().initWithString_attributes_(
                "BLOSSOM", {NSFontAttributeName: NSFont.boldSystemFontOfSize_(12),
                           NSForegroundColorAttributeName: _rgb(BRAND),
                           NSKernAttributeName: 4.2,
                           NSParagraphStyleAttributeName: centered}))
        content.addSubview_(wordmark)

        self.status = _label("", NSMakeRect(240, 800, 220, 14), size=10,
                             color=_rgb(TEXT_SECTION),
                             align=NSTextAlignmentRight)
        content.addSubview_(self.status)

        # -- chord display ---------------------------------------------
        display = DisplayView.alloc().initWithFrame_(
            NSMakeRect(20, 670, 460, 110))
        content.addSubview_(display)
        self.chord_label = _label("", NSMakeRect(10, 38, 440, 56),
                                  align=NSTextAlignmentCenter)
        self.chord_label.setFont_(
            NSFont.monospacedSystemFontOfSize_weight_(42, NSFontWeightSemibold))
        self.chord_label.setTextColor_(_rgb(GLOW_TEXT))
        self.chord_label.setWantsLayer_(True)
        layer = self.chord_label.layer()
        layer.setShadowColor_(_rgb(ACCENT).CGColor())
        layer.setShadowRadius_(14.0)
        layer.setShadowOpacity_(0.55)
        layer.setShadowOffset_((0, 0))
        display.addSubview_(self.chord_label)
        self.notes_label = _label("", NSMakeRect(10, 14, 440, 16), size=13,
                                  color=_rgb(DIM_ACCENT), mono=True,
                                  align=NSTextAlignmentCenter)
        display.addSubview_(self.notes_label)

        # -- piano + chord-key legend ----------------------------------
        self.piano = PianoView.alloc().initWithFrame_(
            NSMakeRect(20, 556, 460, 100))
        self.piano.on_note = self._piano_clicked
        content.addSubview_(self.piano)

        legend_card = CardView.alloc().initWithFrame_(
            NSMakeRect(20, 480, 460, 76))
        content.addSubview_(legend_card)
        content.addSubview_(_label("CHORD KEYS", NSMakeRect(36, 530, 150, 14),
                                   size=10, bold=True,
                                   color=_rgb(TEXT_SECTION)))
        self.legend_range = _label("", NSMakeRect(220, 530, 244, 14), size=10,
                                   mono=True, color=_rgb(TEXT_HINT),
                                   align=NSTextAlignmentRight)
        content.addSubview_(self.legend_range)
        self.legend = LegendView.alloc().initWithFrame_(
            NSMakeRect(28, 488, 444, 36))
        self.legend.on_pick = self._pick_chord_key
        content.addSubview_(self.legend)

        # -- ARP strip -------------------------------------------------
        self.arp_strip = CardView.alloc().initWithFrame_(
            NSMakeRect(20, 422, 460, 44))
        content.addSubview_(self.arp_strip)
        self.arp_check = PillSwitch.alloc().initWithFrame_(
            NSMakeRect(8, 10, 44, 24))
        self.arp_check.on_change = self.arpChanged_
        self.arp_strip.addSubview_(self.arp_check)
        self.arp_label = _label("ARP", NSMakeRect(56, 15, 32, 13),
                                size=10, bold=True, color=_rgb(TEXT_SECTION))
        self.arp_strip.addSubview_(self.arp_label)

        def strip_pop(x, w, titles, action):
            view = MenuValueView.alloc().initWithFrame_(
                NSMakeRect(x, 14, w, 16))
            view.items = list(titles)
            view.value = titles[0]
            view.font_size = 11.0
            view.on_change = action
            self.arp_strip.addSubview_(view)
            return view

        self.arp_div_pop = strip_pop(92, 60, list(_ARP_DIVS),
                                     self.arpDivChanged_)
        self.arp_pattern_pop = strip_pop(160, 66, list(_ARP_PATTERNS),
                                         self.arpTweakChanged_)
        self.arp_oct_pop = strip_pop(234, 36, ["1", "2", "3"],
                                     self.arpTweakChanged_)
        self.arp_strip.addSubview_(_label("gate", NSMakeRect(286, 15, 30, 13),
                                          size=10, color=_rgb(TEXT_HINT)))
        self.gate_drag = DragValueView.alloc().initWithFrame_(
            NSMakeRect(316, 14, 44, 16))
        self.gate_drag.min_value, self.gate_drag.max_value = 10, 100
        self.gate_drag.step = 0.6
        self.gate_drag.fmt = lambda v: "%d%%" % round(v)
        self.gate_drag.set_value(60, notify=False)
        self.gate_drag.on_change = self._gate_changed
        self.arp_strip.addSubview_(self.gate_drag)
        self.tempo_drag = DragValueView.alloc().initWithFrame_(
            NSMakeRect(372, 14, 76, 16))
        self.tempo_drag.min_value, self.tempo_drag.max_value = 40, 220
        self.tempo_drag.step = 0.5
        self.tempo_drag.fmt = lambda v: "%d bpm" % round(v)
        self.tempo_drag.set_value(120, notify=False)
        self.tempo_drag.on_change = self._tempo_changed
        self.arp_strip.addSubview_(self.tempo_drag)

        # -- HARMONY card ----------------------------------------------
        harmony = CardView.alloc().initWithFrame_(
            NSMakeRect(20, 114, 460, 294))
        harmony.seps = [224, 180, 136, 92, 46]
        content.addSubview_(harmony)
        content.addSubview_(_label("HARMONY", NSMakeRect(36, 384, 150, 16),
                                   size=10, bold=True,
                                   color=_rgb(TEXT_SECTION)))

        self.key_label = _label("Key", NSMakeRect(36, 354, 36, 16),
                                   color=_rgb(TEXT_PRIMARY))
        content.addSubview_(self.key_label)
        def menu_value(frame, items, default, action, size=12.0):
            view = MenuValueView.alloc().initWithFrame_(frame)
            view.items = list(items)
            view.value = default
            view.font_size = size
            view.on_change = action
            content.addSubview_(view)
            return view

        self.key_pop = menu_value(NSMakeRect(96, 350, 64, 20),
                                  ["Off"] + list(NOTE_NAMES), "Off",
                                  self.settingsChanged_)
        self.mode_pop = menu_value(NSMakeRect(172, 350, 110, 20),
                                   ["major", "minor", "dorian", "phrygian",
                                    "lydian", "mixolydian"], "major",
                                   self.settingsChanged_)
        self.offkey_label = _label("off-key", NSMakeRect(318, 354, 44, 13),
                                   size=11, color=_rgb(TEXT_HINT))
        content.addSubview_(self.offkey_label)
        self.offkey_pop = menu_value(NSMakeRect(368, 350, 80, 20),
                                     ["V7", "dom7", "snap", "thru"], "V7",
                                     self.settingsChanged_)

        self.voicing_label = _label("Voicing", NSMakeRect(36, 310, 60, 16),
                                   color=_rgb(TEXT_PRIMARY))
        content.addSubview_(self.voicing_label)
        self.voicing_pop = menu_value(NSMakeRect(240, 306, 96, 20),
                                      ["1-3", "1-5", "1-3-5", "1-3-5-7",
                                       "smart"], "1-3-5",
                                      self.settingsChanged_)
        self.lead_label = _label("voice lead", NSMakeRect(346, 310, 64, 13),
                                   size=11, color=_rgb(TEXT_HINT))
        content.addSubview_(self.lead_label)
        self.lead_check = PillSwitch.alloc().initWithFrame_(
            NSMakeRect(414, 304, 50, 24))
        self.lead_check.on_change = self.leadChanged_
        content.addSubview_(self.lead_check)

        self.spread_label = _label("Spread", NSMakeRect(36, 266, 60, 16),
                                   color=_rgb(TEXT_PRIMARY))
        content.addSubview_(self.spread_label)
        content.addSubview_(_label("wider voicings",
                                   NSMakeRect(96, 267, 200, 14), size=11,
                                   color=_rgb(TEXT_HINT)))
        self.spread_check = PillSwitch.alloc().initWithFrame_(
            NSMakeRect(414, 260, 50, 24))
        self.spread_check.on_change = self.spreadChanged_
        content.addSubview_(self.spread_check)

        self.mono_label = _label("Mono", NSMakeRect(36, 222, 50, 16),
                                   color=_rgb(TEXT_PRIMARY))
        content.addSubview_(self.mono_label)
        content.addSubview_(_label("one chord at a time",
                                   NSMakeRect(86, 223, 200, 14), size=11,
                                   color=_rgb(TEXT_HINT)))
        self.mono_check = PillSwitch.alloc().initWithFrame_(
            NSMakeRect(414, 216, 50, 24))
        self.mono_check.on_change = self.monoChanged_
        content.addSubview_(self.mono_check)

        self.strum_label = _label("Strum", NSMakeRect(36, 176, 70, 16),
                                   color=_rgb(TEXT_PRIMARY))
        content.addSubview_(self.strum_label)
        self.strum_slider = NSSlider.alloc().initWithFrame_(
            NSMakeRect(110, 174, 272, 20))
        self.strum_slider.setCell_(GlowSliderCell.alloc().init())
        self.strum_slider.setContinuous_(True)
        self.strum_slider.setMinValue_(0)
        self.strum_slider.setMaxValue_(80)     # ms between chord notes
        self.strum_slider.setTarget_(self)
        self.strum_slider.setAction_("strumChanged:")
        content.addSubview_(self.strum_slider)
        self.strum_value = _label("0 ms", NSMakeRect(394, 176, 70, 16),
                                  size=12, mono=True, color=_rgb(GLOW_TEXT),
                                  align=NSTextAlignmentRight)
        content.addSubview_(self.strum_value)

        self.humanize_label = _label("Humanize", NSMakeRect(36, 130, 70, 16),
                                   color=_rgb(TEXT_PRIMARY))
        content.addSubview_(self.humanize_label)
        self.humanize_slider = NSSlider.alloc().initWithFrame_(
            NSMakeRect(110, 128, 272, 20))
        self.humanize_slider.setCell_(GlowSliderCell.alloc().init())
        self.humanize_slider.setContinuous_(True)
        self.humanize_slider.setMinValue_(0)
        self.humanize_slider.setMaxValue_(40)  # ms of timing slop
        self.humanize_slider.setTarget_(self)
        self.humanize_slider.setAction_("humanizeChanged:")
        content.addSubview_(self.humanize_slider)
        self.humanize_value = _label("0 ms", NSMakeRect(394, 130, 70, 16),
                                     size=12, mono=True,
                                     color=_rgb(GLOW_TEXT),
                                     align=NSTextAlignmentRight)
        content.addSubview_(self.humanize_value)

        # -- MIDI footer (recessed strip) ------------------------------
        footer = FooterStrip.alloc().initWithFrame_(NSMakeRect(0, 0, 500, 100))
        content.addSubview_(footer)
        content.addSubview_(_label("MIDI", NSMakeRect(20, 76, 60, 12),
                                   size=9, bold=True, color=_rgb(TEXT_HINT)))
        refresh = NSButton.alloc().initWithFrame_(NSMakeRect(330, 74, 82, 16))
        refresh.setBordered_(False)
        refresh.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                "\u21bb Refresh",
                {NSFontAttributeName: NSFont.systemFontOfSize_(10),
                 NSForegroundColorAttributeName: _rgb("#8A72B8")}))
        refresh.setTarget_(self)
        refresh.setAction_("refreshPorts:")
        content.addSubview_(refresh)
        content.addSubview_(_label("v%s" % update.local_version(),
                                   NSMakeRect(424, 76, 56, 12), size=9,
                                   mono=True, color=_rgb(TEXT_FAINT),
                                   align=NSTextAlignmentRight))

        self.footer_wells = {}

        def footer_well(x, y, w, label, pop_x, pop_w):
            well = FooterWell.alloc().initWithFrame_(NSMakeRect(x, y, w, 24))
            well.label = label
            self.footer_wells[label] = well
            content.addSubview_(well)
            pop = NSPopUpButton.alloc().initWithFrame_(
                NSMakeRect(pop_x, y, pop_w, 24))
            pop.setBordered_(False)
            pop.setFont_(NSFont.systemFontOfSize_(10))
            pop.setAlphaValue_(0.72)   # quiet footer values
            pop.cell().setArrowPosition_(0)    # native arrow scales badly
            content.addSubview_(pop)
            content.addSubview_(ChevronView.alloc().initWithFrame_(
                NSMakeRect(x + w - 16, y + 7, 10, 10)))
            return pop

        self.in_pop = footer_well(20, 44, 226, "IN", 52, 192)
        self.out_pop = footer_well(254, 44, 226, "OUT", 296, 182)
        self.clock_pop = footer_well(20, 16, 186, "SYNC", 66, 138)
        self.sync_check = PillSwitch.alloc().initWithFrame_(
            NSMakeRect(210, 19, 36, 18))
        self.sync_check.pill_size = (32.0, 17.0)
        self.sync_check.on_change = self.syncChanged_
        content.addSubview_(self.sync_check)
        self.base_pop = footer_well(254, 16, 109, "BASE", 298, 63)
        self.base_pop.addItemsWithTitles_(
            [note_name(n) for n in range(0, 117)])
        self.channel_pop = footer_well(371, 16, 109, "CH", 402, 76)
        self.channel_pop.addItemsWithTitles_(
            [str(c) for c in range(1, 17)])

        for pop in (self.in_pop, self.out_pop, self.clock_pop,
                    self.base_pop, self.channel_pop):
            pop.setTarget_(self)
            pop.setAction_("settingsChanged:")

        self._set_tooltips()
        self.window.setDelegate_(self)
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _set_tooltips(self):
        tips = {
            self.piano: "Shows what's playing. Click keys to try sounds.",
            self.legend: "Your chord buttons. Click one to change what "
                         "chord it makes.",
            self.arp_label: "Plays your chord one note at a time, in "
                            "rhythm.",
            self.tempo_drag: "Speed. Drag up or down, or double-click to "
                             "type a number.",
            self.gate_drag: "Note length: low = short and choppy, high = "
                            "long and smooth.",
            self.key_label: "Pick a key and every note you play becomes a "
                            "chord that fits.",
            self.mode_pop: "Happy (major), sad (minor), or in between.",
            self.offkey_label: "What the out-of-key notes do. Try them.",
            self.voicing_label: "How big the chords are: 2, 3, or 4 notes. "
                                "Smart decides for you.",
            self.lead_label: "Makes chords flow into each other smoothly.",
            self.spread_label: "Opens the chord up for a bigger sound.",
            self.mono_label: "New chord cuts off the old one.",
            self.strum_label: "Rakes the notes like a guitar strum.",
            self.humanize_label: "A little looseness, like a real player.",
            self.footer_wells["IN"]: "The keyboard you play.",
            self.footer_wells["OUT"]: "The synth that makes the sound.",
            self.footer_wells["SYNC"]: "Locks the arp to your DAW's beat.",
            self.footer_wells["BASE"]: "Where the chord buttons start on "
                                       "your keyboard.",
            self.footer_wells["CH"]: "MIDI channel - match your synth.",
        }
        for view, tip in tips.items():
            view.setToolTip_(tip)

    @objc.python_method
    def _apply_arp_dim(self):
        on = bool(self.arp_check.state())
        self.arp_strip.animator().setAlphaValue_(1.0 if on else 0.55)
        self.arp_div_pop.setEnabled_(on)
        self.arp_pattern_pop.setEnabled_(on)
        self.arp_oct_pop.setEnabled_(on)
        self.gate_drag.enabled = on
        self.tempo_drag.enabled = on

    @objc.python_method
    def _set_status(self, text, ok):
        self.status.setStringValue_("" if ok else text)
        self.status.setTextColor_(_rgb(ERROR_RED))

    @objc.python_method
    def _set_zone_display(self, base):
        self.piano.set_zone(range(base, base + 12))
        self.legend.set_base(base)
        self.legend_range.setStringValue_(
            "%s\u2013%s \u00b7 click a pad to reassign"
            % (note_name(base), note_name(base + 11)))

    @objc.python_method
    def _load_settings(self):
        stored = settings.load()
        self.base_pop.selectItemWithTitle_(note_name(stored["base"]))
        self.channel_pop.selectItemWithTitle_(str(stored["channel"]))
        if stored.get("key") in NOTE_NAMES:
            self.key_pop.selectItemWithTitle_(stored["key"])
        keys = stored.get("chord_keys")
        if (isinstance(keys, list) and len(keys) == 12
                and all(k == _NO_CHORD or k in QUALITY_INTERVALS
                        for k in keys)):
            self.chord_keys = list(keys)
        self.legend.set_assignments(self.chord_keys)
        if stored.get("voicing") in ("1-3", "1-5", "1-3-5", "1-3-5-7",
                                     "smart"):
            self.voicing_pop.selectItemWithTitle_(stored["voicing"])
        if stored.get("offkey") in ("dom7", "V7", "snap", "thru"):
            self.offkey_pop.selectItemWithTitle_(stored["offkey"])
        self.spread_check.setState_(1 if stored.get("spread") else 0)
        self.mono_check.setState_(1 if stored.get("mono") else 0)
        self.strum_slider.setIntValue_(int(stored.get("strum", 0)))
        self.strum_ms = int(stored.get("strum", 0))
        self.strum_value.setStringValue_("%d ms" % self.strum_ms)
        self.humanize_slider.setIntValue_(int(stored.get("humanize", 0)))
        self.humanize_ms = int(stored.get("humanize", 0))
        self.humanize_value.setStringValue_("%d ms" % self.humanize_ms)
        self.tempo_bpm = int(stored.get("tempo", 120))
        self.tempo_drag.set_value(self.tempo_bpm, notify=False)
        self.arp_gate = max(0.1, min(1.0, float(stored.get("arp_gate", 60))
                                     / 100.0))
        self.gate_drag.set_value(self.arp_gate * 100, notify=False)
        if stored.get("mode") in ("major", "minor", "dorian", "phrygian",
                                  "lydian", "mixolydian"):
            self.mode_pop.selectItemWithTitle_(stored["mode"])
        if stored.get("arp_pattern") in _ARP_PATTERNS:
            self.arp_pattern_pop.selectItemWithTitle_(stored["arp_pattern"])
            self.arp_pattern = stored["arp_pattern"]
        if stored.get("arp_oct") in (1, 2, 3):
            self.arp_oct_pop.selectItemWithTitle_(str(stored["arp_oct"]))
            self.arp_octaves = int(stored["arp_oct"])
        if stored.get("arp_div") in _ARP_DIVS:
            self.arp_div_pop.selectItemWithTitle_(stored["arp_div"])
        else:
            self.arp_div_pop.selectItemWithTitle_("1/8")
        self._update_arp_rate()
        self.arp_check.setState_(1 if stored.get("arp") else 0)
        self.arp_on = bool(stored.get("arp"))
        self.sync_check.setState_(1 if stored.get("sync_on") else 0)
        self.lead_check.setState_(0 if stored.get("voice_lead") is False else 1)
        self._apply_arp_dim()
        self._set_zone_display(stored["base"])
        if stored.get("float_on_top"):
            self.window.setLevel_(3)            # NSFloatingWindowLevel
        self.refreshPorts_(None)
        if stored.get("clock_port") in list(self.clock_pop.itemTitles()):
            self.clock_pop.selectItemWithTitle_(stored["clock_port"])
        if stored["in_port"] in list(self.in_pop.itemTitles()):
            self.in_pop.selectItemWithTitle_(stored["in_port"])
        if stored["out_port"] in list(self.out_pop.itemTitles()):
            self.out_pop.selectItemWithTitle_(stored["out_port"])
        self._restart()

    # -- actions ------------------------------------------------------------

    def refreshPorts_(self, sender):
        cur_in = self.in_pop.titleOfSelectedItem()
        cur_out = self.out_pop.titleOfSelectedItem()
        cur_clock = self.clock_pop.titleOfSelectedItem()
        self.in_pop.removeAllItems()
        self.in_pop.addItemsWithTitles_(mido.get_input_names())
        self.out_pop.removeAllItems()
        self.out_pop.addItemsWithTitles_(mido.get_output_names())
        self.clock_pop.removeAllItems()
        self.clock_pop.addItemsWithTitles_(["Off"] + mido.get_input_names())
        if cur_in in list(self.in_pop.itemTitles()):
            self.in_pop.selectItemWithTitle_(cur_in)
        if cur_out in list(self.out_pop.itemTitles()):
            self.out_pop.selectItemWithTitle_(cur_out)
        if cur_clock in list(self.clock_pop.itemTitles()):
            self.clock_pop.selectItemWithTitle_(cur_clock)
        if sender is not None:
            self._restart()

    def settingsChanged_(self, sender):
        self._restart()

    def leadChanged_(self, sender):
        self._save_tweaks()
        if self.engine is not None:
            self._send_outputs(self.engine.set_voice_lead(sender.state()))
            self.piano.set_sounding(self.engine.sounding_notes)

    def spreadChanged_(self, sender):
        # Live change: re-voice held chords without reopening ports.
        self._save_tweaks()
        if self.engine is not None and self.outport is not None:
            self._send_outputs(self.engine.set_spread(sender.state()))
            self.piano.set_sounding(self.engine.sounding_notes)

    def monoChanged_(self, sender):
        self._save_tweaks()
        if self.engine is not None and self.outport is not None:
            self._send_outputs(self.engine.set_mono(sender.state()))
            self.piano.set_sounding(self.engine.sounding_notes)

    def strumChanged_(self, sender):
        self.strum_ms = int(sender.intValue())
        self.strum_value.setStringValue_("%d ms" % self.strum_ms)
        self._save_tweaks()

    def humanizeChanged_(self, sender):
        self.humanize_ms = int(sender.intValue())
        self.humanize_value.setStringValue_("%d ms" % self.humanize_ms)
        self._save_tweaks()

    @objc.python_method
    def _tempo_changed(self, sender):
        self.tempo_bpm = int(round(sender.value))
        self._update_arp_rate()
        self._save_tweaks()

    @objc.python_method
    def _gate_changed(self, sender):
        self.arp_gate = sender.value / 100.0
        self._save_tweaks()

    def arpTweakChanged_(self, sender):
        self.arp_pattern = str(self.arp_pattern_pop.titleOfSelectedItem())
        self.arp_octaves = int(self.arp_oct_pop.titleOfSelectedItem())
        self._arp_idx = 0
        self._save_tweaks()

    def arpDivChanged_(self, sender):
        self._update_arp_rate()
        self._save_tweaks()

    @objc.python_method
    def _update_arp_rate(self):
        factor = _ARP_DIVS.get(self.arp_div_pop.titleOfSelectedItem(), 0.5)
        self.arp_rate_ms = 60000.0 / max(self.tempo_bpm, 1) * factor

    def arpChanged_(self, sender):
        on = bool(sender.state())
        self._apply_arp_dim()
        self._save_tweaks()
        engine, outport = self.engine, self.outport
        if on and not self.arp_on:
            with self._arp_lock:
                self._arp_notes = {n: 100 for n in
                                   (engine.sounding_notes if engine else [])}
            # silence the sustained chord; the arp retriggers its notes
            if engine is not None and outport is not None:
                for n in engine.sounding_notes:
                    outport.send(mido.Message("note_off", note=n, velocity=0,
                                              channel=engine.channel))
            self.arp_on = True
        elif not on and self.arp_on:
            self.arp_on = False
            with self._arp_lock:
                self._arp_notes = {}
            # restore the sustained chord the engine still believes is held
            if engine is not None and outport is not None:
                for n in engine.sounding_notes:
                    outport.send(mido.Message("note_on", note=n, velocity=90,
                                              channel=engine.channel))

    @objc.python_method
    def _pick_chord_key(self, index, event):
        self._picking_slot = index
        menu = NSMenu.alloc().init()
        for name in list(QUALITY_INTERVALS) + [_NO_CHORD]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                name, "chordKeyPicked:", "")
            item.setTarget_(self)
            if name == self.chord_keys[index]:
                item.setState_(1)
            menu.addItem_(item)
        NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self.legend)

    def chordKeyPicked_(self, sender):
        index = getattr(self, "_picking_slot", None)
        if index is None:
            return
        self.chord_keys[index] = str(sender.title())
        self.legend.set_assignments(self.chord_keys)
        self._save_tweaks()
        if self.engine is not None:
            cmap, cnames = _chord_key_map(self.chord_keys)
            self.engine.chord_map = cmap
            self.engine.chord_names = cnames

    @objc.python_method
    def _save_tweaks(self):
        stored = settings.load()
        stored["spread"] = bool(self.spread_check.state())
        stored["mono"] = bool(self.mono_check.state())
        stored["strum"] = int(self.strum_slider.intValue())
        stored["humanize"] = int(self.humanize_slider.intValue())
        stored["arp"] = bool(self.arp_check.state())
        stored["tempo"] = int(round(self.tempo_drag.value))
        stored["arp_gate"] = int(round(self.gate_drag.value))
        stored["arp_div"] = self.arp_div_pop.titleOfSelectedItem()
        stored["arp_pattern"] = self.arp_pattern_pop.titleOfSelectedItem()
        stored["arp_oct"] = int(self.arp_oct_pop.titleOfSelectedItem())
        stored["mode"] = self.mode_pop.titleOfSelectedItem()
        stored["clock_port"] = self.clock_pop.titleOfSelectedItem()
        stored["chord_keys"] = list(self.chord_keys)
        stored["sync_on"] = bool(self.sync_check.state())
        stored["voice_lead"] = bool(self.lead_check.state())
        settings.save(stored)

    @objc.python_method
    def _restart(self):
        """(Re)open ports with the current UI settings; runs on any change."""
        previous = self.engine
        prev_wheel = previous.wheel_offset if previous is not None else 0
        prev_voicing = (previous._last_voicing
                        if previous is not None else None)
        self._close_ports()   # flushes the old engine, clearing its state
        config, err = validate_config(
            self.in_pop.titleOfSelectedItem(),
            self.out_pop.titleOfSelectedItem(),
            self.base_pop.titleOfSelectedItem(),
            self.channel_pop.titleOfSelectedItem())
        if err:
            self._set_status(err, ok=False)
            self.piano.set_sounding([])
            return
        key_title = self.key_pop.titleOfSelectedItem()
        config["key"] = key_title
        config["offkey"] = self.offkey_pop.titleOfSelectedItem()
        config["voicing"] = self.voicing_pop.titleOfSelectedItem()
        config["voice_lead"] = bool(self.lead_check.state())
        config["spread"] = bool(self.spread_check.state())
        config["mono"] = bool(self.mono_check.state())
        config["strum"] = int(self.strum_slider.intValue())
        config["humanize"] = int(self.humanize_slider.intValue())
        config["arp"] = bool(self.arp_check.state())
        config["tempo"] = int(round(self.tempo_drag.value))
        config["arp_gate"] = int(round(self.gate_drag.value))
        config["arp_div"] = self.arp_div_pop.titleOfSelectedItem()
        config["arp_pattern"] = self.arp_pattern_pop.titleOfSelectedItem()
        config["arp_oct"] = int(self.arp_oct_pop.titleOfSelectedItem())
        config["mode"] = self.mode_pop.titleOfSelectedItem()
        config["clock_port"] = self.clock_pop.titleOfSelectedItem()
        config["chord_keys"] = list(self.chord_keys)
        config["sync_on"] = bool(self.sync_check.state())
        settings.save(config)
        key = NOTE_NAMES.index(key_title) if key_title in NOTE_NAMES else None
        cmap, cnames = _chord_key_map(self.chord_keys)
        self.engine = ChordEngine(zone_base=config["base"],
                                  chord_map=cmap, chord_names=cnames,
                                  channel=config["channel"] - 1,
                                  key=key, spread=config["spread"],
                                  mono=config["mono"],
                                  offkey=config["offkey"],
                                  voicing=config["voicing"],
                                  voice_lead=config["voice_lead"],
                                  mode=config["mode"])
        if previous is not None:
            # settings tweaks shouldn't reset live performance state
            self.engine.wheel_offset = prev_wheel
            self.engine._last_voicing = prev_voicing
        try:
            self.outport = mido.open_output(config["out_port"])
            self.inport = mido.open_input(config["in_port"],
                                          callback=self._on_message)
        except (OSError, ValueError) as exc:
            self._close_ports()
            self._set_status("Could not open MIDI ports: %s" % exc, ok=False)
            return
        self._apply_clock()
        self._set_zone_display(config["base"])
        self.chord_label.setStringValue_("")
        self.notes_label.setStringValue_("")
        self._set_status("RUNNING", ok=True)

    def syncChanged_(self, sender):
        if not sender.state():
            self.tempo_drag.set_override(None)
        self._save_tweaks()
        self._apply_clock()

    @objc.python_method
    def _apply_clock(self):
        """Open or close the clock port per the Sync toggle and picker."""
        clock, self.clock_inport = self.clock_inport, None
        if clock is not None:
            clock.close()
        self._last_tick = 0.0
        self._tick_count = -1
        del self._tick_dts[:]
        title = self.clock_pop.titleOfSelectedItem()
        if self.sync_check.state() and title and title != "Off":
            try:
                self.clock_inport = mido.open_input(title,
                                                    callback=self._on_clock)
            except (OSError, ValueError) as exc:
                self._set_status("Could not open clock port: %s" % exc,
                                 ok=False)

    @objc.python_method
    def _send_outputs(self, outs):
        """Send engine output; successive chord note-ons strum low-to-high.

        A pending (not yet sent) note-on is cancelled if its note-off arrives
        first, so quick releases can't leave stuck notes."""
        outport = self.outport
        if outport is None:
            return
        if self.arp_on:
            # The arpeggiator owns note timing: engine output only edits
            # its note pool; everything else passes straight through.
            with self._arp_lock:
                for msg in outs:
                    if msg.type == "note_on":
                        self._arp_notes[msg.note] = msg.velocity
                    elif msg.type == "note_off":
                        self._arp_notes.pop(msg.note, None)
                    else:
                        outport.send(msg)
            return
        ons = [m for m in outs if m.type == "note_on"]
        for msg in outs:
            if msg.type == "note_off":
                # Sending under the lock keeps ordering against fire():
                # a pending note-on either cancels here or fully sends first.
                with self._strum_lock:
                    timer = self._pending.pop(msg.note, None)
                    if timer is None:
                        outport.send(msg)
                if timer is not None:
                    timer.cancel()             # note never sounded; skip off
            elif msg.type != "note_on":
                outport.send(msg)
        jitter = int(self.humanize_ms / 3)
        for i, msg in enumerate(sorted(ons, key=lambda m: m.note)):
            if jitter:
                velocity = max(1, min(127, msg.velocity
                                      + random.randint(-jitter, jitter)))
                msg = msg.copy(velocity=velocity)
            delay = i * self.strum_ms / 1000.0
            if self.humanize_ms:
                delay += random.uniform(0, self.humanize_ms / 1000.0)
            if delay < 0.002:
                outport.send(msg)
                continue

            def fire(m=msg):
                try:
                    with self._strum_lock:
                        if self._pending.pop(m.note, None) is None:
                            return             # cancelled or superseded
                        port = self.outport
                        if port is not None:
                            port.send(m)
                except Exception:
                    traceback.print_exc()

            timer = threading.Timer(delay, fire)
            timer.daemon = True
            with self._strum_lock:
                stale = self._pending.pop(msg.note, None)
                self._pending[msg.note] = timer
            if stale is not None:
                stale.cancel()                 # retrigger replaces old timer
            timer.start()

    @objc.python_method
    def _clock_synced(self):
        return (self.clock_inport is not None
                and time.monotonic() - self._last_tick < 1.0)

    @objc.python_method
    def _arp_step(self, gate):
        """Play one arp note per the pattern; note-off follows after `gate`.
        Humanize adds timing and velocity slop to each step."""
        engine, outport = self.engine, self.outport
        with self._arp_lock:
            base = list(self._arp_notes)       # insertion order = played
            velocities = dict(self._arp_notes)
        if not (self.arp_on and base and outport is not None
                and engine is not None):
            self._arp_idx = 0
            return
        octaves = max(1, int(self.arp_octaves))
        pool = [n + 12 * o for o in range(octaves)
                for n in base if n + 12 * o <= 127]
        pattern = self.arp_pattern
        if pattern == "down":
            seq = sorted(pool, reverse=True)
        elif pattern == "updn":
            up = sorted(pool)
            seq = up + up[-2:0:-1] if len(up) > 2 else up
        elif pattern == "played":
            seq = pool
        else:
            seq = sorted(pool)
        if pattern == "rand":
            note = random.choice(pool)
        else:
            note = seq[self._arp_idx % len(seq)]
            self._arp_idx += 1
        source = note if note in velocities else \
            min(base, key=lambda b: abs(b - note))
        velocity = velocities.get(source, 100)
        jitter = int(self.humanize_ms / 3)
        if jitter:
            velocity = max(1, min(127, velocity
                                  + random.randint(-jitter, jitter)))
        channel = engine.channel
        delay = (random.uniform(0, self.humanize_ms / 1000.0)
                 if self.humanize_ms else 0.0)

        def fire_on():
            try:
                port = self.outport
                if port is None:
                    return
                port.send(mido.Message("note_on", note=note,
                                       velocity=velocity, channel=channel))

                def note_off():
                    try:
                        p = self.outport
                        if p is not None:
                            p.send(mido.Message("note_off", note=note,
                                                velocity=0, channel=channel))
                    except Exception:
                        pass

                off = threading.Timer(gate, note_off)
                off.daemon = True
                off.start()
            except Exception:
                pass

        if delay < 0.002:
            fire_on()
        else:
            timer = threading.Timer(delay, fire_on)
            timer.daemon = True
            timer.start()

    @objc.python_method
    def _arp_loop(self):
        """Background thread: internal arp clock. Idles while MIDI clock
        from the DAW is driving the steps instead."""
        while not self._arp_stop.is_set():
            if not self.arp_on or self._clock_synced():
                if self._arp_stop.wait(0.05):
                    return
                continue
            rate = max(self.arp_rate_ms, 30) / 1000.0
            self._arp_step(rate * self.arp_gate)
            if self._arp_stop.wait(rate):
                return

    @objc.python_method
    def _on_clock(self, msg):
        # mido callback thread for the clock port: drive arp steps in sync.
        try:
            if msg.type == "clock":
                now = time.monotonic()
                if self._last_tick:
                    self._tick_dts.append(now - self._last_tick)
                    del self._tick_dts[:-48]
                self._last_tick = now
                self._tick_count += 1
                ticks = _ARP_TICKS.get(
                    self.arp_div_pop.titleOfSelectedItem(), 12)
                if self._tick_count % ticks == 0 and self.arp_on:
                    dt = (sum(self._tick_dts) / len(self._tick_dts)
                          if self._tick_dts else self.arp_rate_ms / 1000.0 / 12)
                    self._arp_step(ticks * dt * self.arp_gate)
                if self._tick_count % 24 == 0 and self._tick_dts:
                    bpm = 60.0 / (24 * sum(self._tick_dts)
                                  / len(self._tick_dts))
                    AppHelper.callAfter(
                        self.tempo_drag.set_override,
                        "\u2248%d bpm" % round(bpm))
            elif msg.type == "start":
                self._tick_count = -1     # next clock lands on the downbeat
                self._arp_idx = 0
            elif msg.type == "songpos":
                # Song position is counted in 16th notes; MIDI clock runs
                # 6 ticks per 16th. Anchoring the tick counter here keeps
                # the arp on the grid when the DAW resumes mid-song.
                self._tick_count = msg.pos * 6 - 1
                self._arp_idx = 0
        except Exception:
            traceback.print_exc()

    @objc.python_method
    def _on_message(self, msg):
        # mido's callback thread: send MIDI here, marshal UI to main thread.
        try:
            engine, outport = self.engine, self.outport
            if engine is None or outport is None:
                return
            self._send_outputs(engine.process(msg))
            AppHelper.callAfter(self._update_ui, engine.current_chord,
                                engine.sounding_notes,
                                engine.held_zone_notes)
        except Exception:
            traceback.print_exc()

    @objc.python_method
    def _piano_clicked(self, note, down):
        # Mouse presses behave exactly like incoming MIDI notes.
        if self.engine is None or self.outport is None:
            self._set_status("CHECK MIDI SETTINGS", ok=False)
            return
        self._on_message(mido.Message("note_on" if down else "note_off",
                                      note=note,
                                      velocity=100 if down else 0))

    @objc.python_method
    def _update_ui(self, chord, notes, held=()):
        self.chord_label.setStringValue_(chord)
        self.notes_label.setStringValue_(
            " \u00b7 ".join(note_name(n) for n in notes))
        self.piano.set_sounding(list(notes) + list(held))

    @objc.python_method
    def _close_ports(self):
        inport, self.inport = self.inport, None
        if inport is not None:
            inport.close()
        clock, self.clock_inport = self.clock_inport, None
        if clock is not None:
            clock.close()
        self._last_tick = 0.0
        self._tick_count = -1
        del self._tick_dts[:]
        with self._strum_lock:
            pending, self._pending = dict(self._pending), {}
        for timer in pending.values():
            timer.cancel()
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
        alert.setMessageText_("Blossom")
        alert.setInformativeText_(text)
        alert.runModal()

    # -- help ---------------------------------------------------------------

    def openHelp_(self, sender):
        if getattr(self, "help_window", None) is None:
            self._build_help_window()
        self.help_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _build_help_window(self):
        from AppKit import NSScrollView, NSTextView
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 560, 620), style, NSBackingStoreBuffered, False)
        win.setTitle_("Blossom Help")
        win.setReleasedWhenClosed_(False)
        win.setAppearance_(
            NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        win.center()
        scroll = NSScrollView.alloc().initWithFrame_(
            win.contentView().bounds())
        scroll.setHasVerticalScroller_(True)
        scroll.setAutoresizingMask_(18)
        text = NSTextView.alloc().initWithFrame_(scroll.bounds())
        text.setEditable_(False)
        text.setBackgroundColor_(_rgb(PANEL_BOTTOM))
        text.setTextColor_(_rgb(TEXT_PRIMARY))
        text.setFont_(NSFont.systemFontOfSize_(13))
        text.setTextContainerInset_((16, 16))
        text.setString_(HELP_TEXT)
        scroll.setDocumentView_(text)
        win.contentView().addSubview_(scroll)
        self.help_window = win

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
            NSMakeRect(0, 0, 320, 186), style, NSBackingStoreBuffered, False)
        win.setTitle_("Blossom Settings")
        win.center()
        win.setReleasedWhenClosed_(False)
        content = win.contentView()
        content.addSubview_(_label("Blossom version %s" % update.local_version(),
                                   NSMakeRect(20, 140, 280, 20)))
        content.addSubview_(_label("Keep above other windows",
                                   NSMakeRect(20, 112, 220, 18)))
        self.float_check = PillSwitch.alloc().initWithFrame_(
            NSMakeRect(250, 108, 50, 24))
        self.float_check.setState_(
            1 if settings.load().get("float_on_top") else 0)
        self.float_check.on_change = self.floatChanged_
        content.addSubview_(self.float_check)
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

    def floatChanged_(self, sender):
        on = bool(sender.state())
        self.window.setLevel_(3 if on else 0)   # NSFloatingWindowLevel
        stored = settings.load()
        stored["float_on_top"] = on
        settings.save(stored)

    @objc.python_method
    def _check_for_update(self):
        self.update_status.setStringValue_("Checking for updates\u2026")
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
        self.update_status.setStringValue_("Downloading update\u2026")

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
        self.update_status.setStringValue_("Updated \u2014 quit and reopen Blossom.")
        self._alert("Update installed. Quit and reopen Blossom to use it.")

    # -- window delegate ----------------------------------------------------

    def windowDidResize_(self, notification):
        if getattr(self, "panel", None) is None:
            return
        self.panel.setFrame_(self.window.contentView().bounds())
        self.panel.setBoundsSize_((500.0, 840.0))

    def windowWillClose_(self, notification):
        self._arp_stop.set()
        self._close_ports()
        AppHelper.stopEventLoop()


def _build_menu(controller):
    menubar = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    menubar.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Settings\u2026", "openSettings:", ",")
    settings_item.setTarget_(controller)
    app_menu.addItem_(settings_item)
    app_menu.addItem_(NSMenuItem.separatorItem())
    app_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit Blossom", "terminate:", "q"))
    app_item.setSubmenu_(app_menu)
    help_item = NSMenuItem.alloc().init()
    menubar.addItem_(help_item)
    help_menu = NSMenu.alloc().initWithTitle_("Help")
    guide = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Blossom Help", "openHelp:", "?")
    guide.setTarget_(controller)
    help_menu.addItem_(guide)
    help_item.setSubmenu_(help_menu)
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
