#!/usr/bin/env bash
# Build a local mirror of everything the Pyxel 3.0.1 web runtime fetches at run time.
# Sources (already downloaded into vendor/):
#   vendor/pyxel_wasm_orig  <- https://raw.githubusercontent.com/kitao/pyxel/v3.0.1/wasm/*
#   vendor/pyodide_npm      <- https://registry.npmjs.org/pyodide/-/pyodide-314.0.7.tgz
# Result:
#   mirror/kitao.dev/pyxel/3.0.1/            unmodified runtime (used via Playwright route interception)
#   mirror/kitao.dev/pyxel/pyodide/v314.0.7/ Pyodide core
#   mirror/kitao.dev/pyxel/local/            pyxel.js patched to load Pyodide relative to itself (plain http.server)
set -euo pipefail
W="$(cd "$(dirname "$0")/.." && pwd)"
M="$W/mirror/kitao.dev/pyxel"
rm -rf "$W/mirror"
mkdir -p "$M/3.0.1/images" "$M/pyodide/v314.0.7" "$M/local"
cp "$W"/vendor/pyxel_wasm_orig/{pyxel.js,pyxel.css,import_hook.py,pyxel-3.0.1-cp311-abi3-pyemscripten_2026_0_wasm32.whl} "$M/3.0.1/"
cp "$W"/vendor/pyxel_wasm_orig/images/* "$M/3.0.1/images/"
cp "$W"/vendor/pyodide_npm/package/{pyodide.js,pyodide.asm.mjs,pyodide.asm.wasm,python_stdlib.zip,pyodide-lock.json} "$M/pyodide/v314.0.7/"
# Patched variant: only the two Pyodide URL constants change.
python3 -I - "$M/3.0.1/pyxel.js" "$M/local/pyxel.js" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
a = 'const PYODIDE_URL = `https://kitao.dev/pyxel/pyodide/v${PYODIDE_VERSION}/pyodide.js`;'
b = 'const PYODIDE_PACKAGE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;'
assert src.count(a) == 1 and src.count(b) == 1, "pyxel.js layout changed; patch needs review"
src = src.replace(a, 'const PYODIDE_URL = new URL(`../pyodide/v${PYODIDE_VERSION}/pyodide.js`, document.currentScript.src).href;')
src = src.replace(b, 'const PYODIDE_PACKAGE_URL = new URL(`../pyodide/v${PYODIDE_VERSION}/`, document.currentScript.src).href;')
open(sys.argv[2], "w", encoding="utf-8").write(src)
PY
for f in pyxel.css import_hook.py pyxel-3.0.1-cp311-abi3-pyemscripten_2026_0_wasm32.whl images; do
  ln -s "../3.0.1/$f" "$M/local/$f"
done
find "$W/mirror" -type f -o -type l | sort | sed "s#$W/##"
