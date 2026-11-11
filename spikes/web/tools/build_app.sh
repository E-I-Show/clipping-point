#!/usr/bin/env bash
# Package apps/<name>/ into build/<name>.pyxapp and two HTML files:
#   build/<name>.html                       exactly what `pyxel app2html` writes (runtime from https://kitao.dev)
#   mirror/kitao.dev/apps/<name>.html       same, but script src -> /pyxel/local/pyxel.js (for python -m http.server)
set -euo pipefail
W="$(cd "$(dirname "$0")/.." && pwd)"
name="$1"; startup="${2:-main.py}"
mkdir -p "$W/build" "$W/mirror/kitao.dev/apps"
cd "$W/build"
rm -f "$name.pyxapp" "$name.html"
# pyxel package names the app after the directory, so stage a clean copy without __pycache__.
rm -rf "$W/build/_stage/$name"; mkdir -p "$W/build/_stage"
cp -r "$W/apps/$name" "$W/build/_stage/$name"
# shared pure-Python modules live in apps/_shared and are copied into every app
if [ -d "$W/apps/_shared" ]; then cp "$W"/apps/_shared/*.py "$W/build/_stage/$name/"; fi
find "$W/build/_stage/$name" -name __pycache__ -prune -exec rm -rf {} +
pyxel package "$W/build/_stage/$name" "$W/build/_stage/$name/$startup" >/dev/null 2>&1
pyxel app2html "$name.pyxapp" >/dev/null 2>&1
test -s "$name.html"
sed 's#https://kitao.dev/pyxel/[0-9.]*/pyxel.js#/pyxel/local/pyxel.js#' "$name.html" > "$W/mirror/kitao.dev/apps/$name.html"
grep -q '/pyxel/local/pyxel.js' "$W/mirror/kitao.dev/apps/$name.html"
echo "built build/$name.html ($(stat -c %s "$name.html") bytes) and mirror/kitao.dev/apps/$name.html"
