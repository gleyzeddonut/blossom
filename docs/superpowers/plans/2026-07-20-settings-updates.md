# Settings + Self-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cmd+, Settings window with version display and one-click update from the public GitHub repo `gleyzeddonut/orchid`.

**Architecture:** Per spec `docs/superpowers/specs/2026-07-20-settings-updates-design.md`.

**Tech Stack:** stdlib urllib/threading only — no new dependencies.

## Global Constraints

- UI updates from worker threads only via `AppHelper.callAfter`; `@objc.python_method` on non-selector methods.
- Network failures must never crash or block the UI (10s timeouts, daemon threads).
- `build_app.sh` copy list gains `update.py` and `VERSION`.
- Commit after each task with the exact message given.

---

### Task 1: VERSION + update.py

**Files:**
- Create: `VERSION` (content `1.0.0`), `update.py`
- Test: `tests/test_update.py`

**Interfaces:**
- Produces: `parse_version(text) -> tuple`, `is_newer(candidate, current) -> bool`, `local_version() -> str`, `fetch_remote_version() -> str|None`, `download_update(dest_dir=UPDATE_DIR)`, constants `RAW_BASE`, `APP_FILES`, `UPDATE_DIR`.

- [ ] **Step 1: Failing tests** — `tests/test_update.py`:

```python
import pytest

import update


@pytest.mark.parametrize("text,expected", [
    ("1.0.0", (1, 0, 0)), ("2.10.3", (2, 10, 3)), (" 1.2 \n", (1, 2)),
    ("garbage", (0,)), ("", (0,)), (None, (0,)),
])
def test_parse_version(text, expected):
    assert update.parse_version(text) == expected


@pytest.mark.parametrize("cand,cur,newer", [
    ("1.0.1", "1.0.0", True), ("2.0.0", "1.9.9", True), ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False), ("1.10.0", "1.9.0", True), ("garbage", "1.0.0", False),
])
def test_is_newer(cand, cur, newer):
    assert update.is_newer(cand, cur) is newer


def test_local_version_reads_version_file():
    assert update.local_version() == open("VERSION").read().strip()
```

- [ ] **Step 2: Run** — expect `ModuleNotFoundError: update`.

- [ ] **Step 3: Implement** — `VERSION` containing `1.0.0`; `update.py`:

```python
"""Self-update support: version comparison and fetching from GitHub."""

import urllib.request
from pathlib import Path

OWNER, REPO, BRANCH = "gleyzeddonut", "orchid", "main"
RAW_BASE = "https://raw.githubusercontent.com/%s/%s/%s/" % (OWNER, REPO, BRANCH)
APP_FILES = ("gui.py", "chords.py", "settings.py", "update.py",
             "requirements.txt", "VERSION")
UPDATE_DIR = Path.home() / "Library" / "Application Support" / "Orchid" / "app"
TIMEOUT = 10


def parse_version(text):
    """'1.2.3' -> (1, 2, 3); anything malformed -> (0,)."""
    try:
        return tuple(int(part) for part in str(text).strip().split("."))
    except ValueError:
        return (0,)


def is_newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def local_version():
    """Version of the code this process is running from."""
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


def fetch_remote_version():
    """Latest published version string, or None if unreachable."""
    try:
        with urllib.request.urlopen(RAW_BASE + "VERSION", timeout=TIMEOUT) as resp:
            return resp.read().decode().strip()
    except OSError:
        return None


def download_update(dest_dir=UPDATE_DIR):
    """Download the published app files into dest_dir. All-or-nothing."""
    staged = {}
    for name in APP_FILES:
        with urllib.request.urlopen(RAW_BASE + name, timeout=TIMEOUT) as resp:
            staged[name] = resp.read()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in staged.items():
        (dest / name).write_bytes(data)
```

- [ ] **Step 4: Run full suite** — expected 91 passed (76 + 15).
- [ ] **Step 5: Commit** — `feat: version file and update module`

---

### Task 2: menu + Settings window in gui.py

**Files:** Modify `gui.py`.

**Interfaces:**
- Consumes: `update` module (Task 1).
- Produces: selectors `openSettings:`, `runUpdate:`; app main menu with Cmd+, and Cmd+Q.

- [ ] **Step 1: Implement.** Imports: add `subprocess`, `sys`, `threading`, `import update`; AppKit imports gain `NSApp, NSMenu, NSMenuItem`. New controller methods (all UI-thread; workers marshal back):

```python
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
```

And in `main()`, before `runEventLoop`:

```python
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
```

with `app.setMainMenu_(_build_menu(controller))` after the controller is created.

- [ ] **Step 2: Verify** — `import gui` ok; full suite still green.
- [ ] **Step 3: Commit** — `feat: settings window (Cmd+,) with self-update`

---

### Task 3: launcher override + build script + publish

**Files:** Modify `Orchid.app/Contents/MacOS/orchid`, `build_app.sh`, `README.md`.

- [ ] **Step 1: Launcher** — replace the final three lines (`echo launching` / `cd` / `exec`) with:

```bash
APP_CODE="$RES"
OVERRIDE="$APPDIR/app"
if [ -f "$OVERRIDE/VERSION" ] && [ -f "$OVERRIDE/gui.py" ]; then
    if "$VENV/bin/python" -c '
import sys
def v(path):
    try:
        return tuple(int(x) for x in open(path + "/VERSION").read().strip().split("."))
    except Exception:
        return (0,)
sys.exit(0 if v(sys.argv[1]) > v(sys.argv[2]) else 1)' "$OVERRIDE" "$RES"; then
        APP_CODE="$OVERRIDE"
    fi
fi
echo "launching gui.py from $APP_CODE" >>"$LOG"
cd "$APP_CODE"
exec "$VENV/bin/python" "$APP_CODE/gui.py" 2>>"$LOG"
```

- [ ] **Step 2: build_app.sh** — copy line becomes:
`cp gui.py chords.py settings.py update.py requirements.txt VERSION "$RES/"`

- [ ] **Step 3: README** — append to the App section:

```markdown
**Updates:** Cmd+, opens Settings, shows the version, and offers one-click
updates published from the GitHub repo (bump `VERSION`, push to main).
```

- [ ] **Step 4: Rebuild, verify, merge** — `./build_app.sh`, codesign verify, suite green, merge to main.

- [ ] **Step 5: Publish** — `gh repo create orchid --public --source=. --remote=origin --push`, then verify `curl https://raw.githubusercontent.com/gleyzeddonut/orchid/main/VERSION` returns `1.0.0`.
