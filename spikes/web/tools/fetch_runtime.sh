#!/usr/bin/env bash
# Download everything the Pyxel 3.0.1 web runtime needs from hosts that are reachable here
# (raw.githubusercontent.com and registry.npmjs.org), then verify against vendor/SHA256SUMS.
#   - Pyxel side: the wasm/ directory of the kitao/pyxel repository at tag v3.0.1
#   - Pyodide 314.0.7 core: the npm package "pyodide"
# kitao.dev (the production CDN) and cdn.jsdelivr.net are NOT contacted.
set -euo pipefail
W="$(cd "$(dirname "$0")/.." && pwd)"
V="$W/vendor"
mkdir -p "$V/pyxel_wasm_orig/images" "$V/pyodide_npm"
base="https://raw.githubusercontent.com/kitao/pyxel/v3.0.1/wasm"
for p in pyxel.js import_hook.py pyxel.css pyxel-3.0.1-cp311-abi3-pyemscripten_2026_0_wasm32.whl \
  images/pyxel_logo_76x32.png images/touch_to_start_114x14.png images/click_to_start_114x14.png \
  images/gamepad_cross_98x98.png images/gamepad_button_98x98.png images/gamepad_menu_92x26.png images/pyxel_icon_64x64.ico; do
  curl -fsS -m 180 -o "$V/pyxel_wasm_orig/$p" "$base/$p"
done
curl -fsS -m 180 -o "$V/pyodide_npm/pyodide-314.0.7.tgz" https://registry.npmjs.org/pyodide/-/pyodide-314.0.7.tgz
rm -rf "$V/pyodide_npm/package"
tar xzf "$V/pyodide_npm/pyodide-314.0.7.tgz" -C "$V/pyodide_npm"
(cd "$V" && sha256sum -c SHA256SUMS)
