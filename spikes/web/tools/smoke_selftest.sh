#!/usr/bin/env bash
# Prove that the smoke runner fails when it should (and passes when it should).
# Each row: app, expected verdict. Any mismatch makes this script exit 1.
# Needs: tools/serve.sh running (http://127.0.0.1:8765), apps built with tools/build_app.sh.
set -uo pipefail
W="$(cd "$(dirname "$0")/.." && pwd)"
cd "$W"
MODE="${1:-http}"   # http = patched runtime via http.server ; file = unmodified app2html HTML + route interception
rows=(
  "hello PASS"
  "fail_import FAIL"
  "fail_missing_module FAIL"
  "fail_syntax FAIL"
  "fail_update FAIL"
  "fail_draw FAIL"
  "fail_api FAIL"
  "fail_hang FAIL"
  "fail_callback FAIL"
  "fail_asyncio FAIL"
  "fail_sysexit FAIL"
  "quiet_stderr PASS"
  "swallowed PASS"
)
bad=0
printf "%-22s %-8s %-8s %s\n" app expected got signals
for row in "${rows[@]}"; do
  set -- $row; app=$1; want=$2
  if [ "$MODE" = http ]; then
    node tools/webrun.js --url "http://127.0.0.1:8765/apps/$app.html" --timeout 20000 --quiet --json "results/selftest_${MODE}_$app.json" --shot "shots/selftest_${MODE}_$app.png" >/dev/null 2>&1
  else
    node tools/webrun.js --url "build/$app.html" --mirror mirror --timeout 20000 --quiet --json "results/selftest_${MODE}_$app.json" >/dev/null 2>&1
  fi
  code=$?
  got=$([ $code -eq 0 ] && echo PASS || echo FAIL)
  kinds=$(python3 -c "
import json,sys
d=json.load(open('results/selftest_${MODE}_$app.json'))
ks=[]
for f in d['failures']:
    if f['kind'] not in ks: ks.append(f['kind'])
print(','.join(ks) or '-')")
  mark=ok; [ "$got" = "$want" ] || { mark=MISMATCH; bad=1; }
  printf "%-22s %-8s %-8s %s  [%s]\n" "$app" "$want" "$got" "$kinds" "$mark"
done
exit $bad
