#!/usr/bin/env bash
# Build the browser check app and run it in headless Chromium (procedure of BRIEF 4b).
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
WEB=<scratchpad>/spikes/web
S="$D/web_build"
rm -rf "$S"; mkdir -p "$S/cpr_spike"
cp "$D/webapp/main.py" "$D/replay.py" "$D/synth.py" "$D/mkreplay.py" "$D/posehash.py" "$S/cpr_spike/"
cd "$D" && python3 make_web_fixtures.py "$S/cpr_spike"
cd "$S"
pyxel package "$S/cpr_spike" "$S/cpr_spike/main.py" >/dev/null 2>&1
pyxel app2html cpr_spike.pyxapp >/dev/null 2>&1
ls -la "$S"
set +e
node "$WEB/tools/webrun.js" --url "$S/cpr_spike.html" --mirror "$WEB/mirror" --until '^SPIKE_DONE' --timeout 180000 \
  --json "$D/web_result.json" --shot "$D/web_shot.png" --quiet
echo "webrun exit=$?"
