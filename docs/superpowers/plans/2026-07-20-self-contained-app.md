# Self-Contained Orchid.app Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Orchid.app runs from anywhere with no privacy grants: code inside the bundle, venv + settings in `~/Library/Application Support/Orchid`.

**Architecture:** Per spec `docs/superpowers/specs/2026-07-20-self-contained-app-design.md`. Sources of truth stay at repo root; `build_app.sh` copies them into `Contents/Resources` (git-ignored) and re-signs.

**Tech Stack:** unchanged (Python 3.9+, mido/python-rtmidi, tkinter, bash).

## Global Constraints

- No new dependencies; repo `.venv` dev workflow unchanged; CLI unchanged.
- All commands run from repo root via `.venv/bin/python`.
- Launcher never reads the repo — only its own bundle and `$HOME/Library/Application Support/Orchid`.
- Sign with the first "Developer ID Application" identity found, else ad-hoc (`-s -`).
- Commit after every task with the exact message given in the task.

---

### Task 1: settings.py → Application Support + mkdir on save

**Files:**
- Modify: `settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "Orchid" / "settings.json"`; `save()` creates parent dirs. Signatures of `load(path=...)`/`save(values, path=...)` unchanged.

- [ ] **Step 1: Write the failing test** (append to `tests/test_settings.py`)

```python
def test_save_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "settings.json"
    settings.save({"in_port": "x"}, path)
    assert settings.load(path)["in_port"] == "x"


def test_default_path_is_in_application_support():
    assert "Application Support/Orchid" in str(settings.SETTINGS_PATH)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: 2 failures (`FileNotFoundError` from save; path assertion).

- [ ] **Step 3: Implement**

In `settings.py` replace the `SETTINGS_PATH` line and `save`:

```python
SETTINGS_PATH = (Path.home() / "Library" / "Application Support" / "Orchid"
                 / "settings.json")
```

```python
def save(values, path=SETTINGS_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2))
```

Remove `settings.json` from `.gitignore` (no longer created in the repo).

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 38 passed

- [ ] **Step 5: Commit**

```bash
git add settings.py tests/test_settings.py .gitignore
git commit -m "feat: store settings in Application Support"
```

---

### Task 2: Self-contained launcher + build script

**Files:**
- Rewrite: `Orchid.app/Contents/MacOS/orchid`
- Create: `build_app.sh` (executable)
- Modify: `.gitignore` (add `Orchid.app/Contents/Resources/`)

**Interfaces:**
- Consumes: `gui.py` sibling-imports `chords`/`settings` (so launcher must `cd` into Resources before exec).
- Produces: `./build_app.sh` — the only supported way to refresh the app after code changes.

- [ ] **Step 1: Rewrite the launcher**

`Orchid.app/Contents/MacOS/orchid`:

```bash
#!/bin/bash
# Orchid launcher: fully self-contained. Code lives in Contents/Resources;
# the Python environment and settings live in ~/Library/Application Support/Orchid.
LOG=/tmp/orchid-launch.log
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
APPDIR="$HOME/Library/Application Support/Orchid"
VENV="$APPDIR/venv"

{
    echo "=== launch $(date) ==="
    echo "resources: $RES"
    echo "venv: $VENV"
} >>"$LOG" 2>&1

BLOCKED=0

# probe <python>: succeeds if it can import tkinter; notes TCC denials.
probe() {
    local out
    out="$("$1" -c "import tkinter" 2>&1)" && return 0
    echo "probe $1 failed: $out" >>"$LOG"
    case "$out" in *"Operation not permitted"*) BLOCKED=1 ;; esac
    return 1
}

alert() { osascript -e "display alert \"Orchid\" message \"$1\""; }

if ! "$VENV/bin/python" -c "import tkinter, mido, rtmidi" >>"$LOG" 2>&1; then
    echo "venv unusable; (re)building" >>"$LOG"
    PY=""
    for p in /usr/bin/python3 "$(command -v python3 2>/dev/null)"; do
        if [ -n "$p" ] && [ -x "$p" ] && probe "$p"; then
            PY="$p"
            break
        fi
    done
    if [ -z "$PY" ]; then
        if [ "$BLOCKED" = 1 ]; then
            alert "macOS is blocking Orchid from reading files it needs. Details: $LOG"
        else
            alert "No Python with tkinter found. Install the Xcode Command Line Tools (run: xcode-select --install) and try again. Details: $LOG"
        fi
        exit 1
    fi
    rm -rf "$VENV"
    mkdir -p "$APPDIR"
    "$PY" -m venv "$VENV" >>"$LOG" 2>&1
    "$VENV/bin/python" -m pip install -r "$RES/requirements.txt" >>"$LOG" 2>&1
    if ! "$VENV/bin/python" -c "import tkinter, mido, rtmidi" >>"$LOG" 2>&1; then
        alert "Orchid could not set up its Python environment. Details: $LOG"
        exit 1
    fi
fi

echo "launching gui.py" >>"$LOG"
cd "$RES"
exec "$VENV/bin/python" "$RES/gui.py" 2>>"$LOG"
```

- [ ] **Step 2: Create `build_app.sh`**

```bash
#!/bin/bash
# Copy the app's Python sources into the bundle and (re)sign it.
# Run after any change to gui.py, chords.py, settings.py, requirements.txt,
# or the launcher script.
set -e
cd "$(dirname "$0")"
RES=Orchid.app/Contents/Resources
mkdir -p "$RES"
cp gui.py chords.py settings.py requirements.txt "$RES/"
chmod +x Orchid.app/Contents/MacOS/orchid
ID="$(security find-identity -v -p codesigning 2>/dev/null \
      | awk -F'"' '/Developer ID Application/ {print $2; exit}')"
codesign --force --deep -s "${ID:--}" Orchid.app
echo "Built and signed Orchid.app${ID:+ ($ID)}"
```

Then: `chmod +x build_app.sh`

- [ ] **Step 3: Git-ignore the bundle's Resources**

Append `Orchid.app/Contents/Resources/` to `.gitignore`.

- [ ] **Step 4: Build and verify**

Run: `./build_app.sh`
Expected: "Built and signed Orchid.app (Developer ID Application: Daniel Gleyzer (K7VM2MP885))"

Run: `ls Orchid.app/Contents/Resources && codesign --verify --deep --strict Orchid.app && echo sig-ok`
Expected: the four files listed; `sig-ok`.

- [ ] **Step 5: Launch-logic test with scratch HOME**

Run the launcher with `HOME` pointed at a scratch dir (background it — on
success it blocks in gui.py, which cannot render in a sandboxed shell):
the log must show a fresh venv build there and reach "launching gui.py".
Then kill the process. If pip is slow, wait for the log rather than a fixed
sleep.

- [ ] **Step 6: Commit**

```bash
git add Orchid.app/Contents/MacOS/orchid build_app.sh .gitignore
git commit -m "feat: self-contained app bundle with build script"
```

---

### Task 3: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the App section**

Replace the entire "## App" section (including the "Where to keep this
folder" paragraph) with:

```markdown
## App

Double-click `Orchid.app` — it is fully self-contained and runs from
anywhere (Documents, /Applications, wherever). Pick your MIDI In/Out, hit
Start, play. The first launch on a machine builds the app's Python
environment in `~/Library/Application Support/Orchid` (give it a minute);
after that it opens instantly. Settings are remembered there too. No
privacy permissions are needed.

To put it on another Mac, copy just `Orchid.app` (AirDrop or Finder copy
keeps the code signature; after a plain `git clone`, run `./build_app.sh`
once to assemble and sign the app). After changing any of the Python
sources, run `./build_app.sh` to refresh the bundle.
```

- [ ] **Step 2: Full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 38 passed

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: self-contained app usage"
```
