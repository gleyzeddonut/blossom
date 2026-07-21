#!/bin/bash
# Copy the app's Python sources into the bundle and (re)sign it.
# Run after any change to gui.py, chords.py, settings.py, requirements.txt,
# or the launcher script.
set -e
cd "$(dirname "$0")"
RES=Blossom.app/Contents/Resources
mkdir -p "$RES"
cp gui.py chords.py settings.py update.py requirements.txt VERSION blossom.icns "$RES/"
chmod +x Blossom.app/Contents/MacOS/blossom
ID="$(security find-identity -v -p codesigning 2>/dev/null \
      | awk -F'"' '/Developer ID Application/ {print $2; exit}')"
codesign --force --deep -s "${ID:--}" Blossom.app
echo "Built and signed Blossom.app${ID:+ ($ID)}"
