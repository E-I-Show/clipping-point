#!/usr/bin/env bash
# 新しいコンテナで1度回す、環境のセットアップ。何度回しても同じ結果になる。対話は求めない。
#   bash tools/setup_env.sh
# やること：
#   1. 版を固定した依存（requirements-dev.txt）を入れる。入っていれば何もしない。
#   2. ブラウザ版のランタイムの写しを .cache/pyxel_web/ に取得し、tools/web/SHA256SUMS と照合する。
#      そろっていて照合が通れば、取得し直さない。
# Node.js、Playwright、Chromium は、環境に入っているものを使う。ここでは入れない。
# 終了コードは、失敗した手順のもの（fetch_runtime.py は、照合が合わなければ1、取得できなければ2）。
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install --no-input --disable-pip-version-check --root-user-action=ignore --quiet -r requirements-dev.txt
python3 tools/web/fetch_runtime.py
