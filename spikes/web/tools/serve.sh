#!/usr/bin/env bash
# Serve the mirror (runtime + apps) on http://127.0.0.1:8765/ . Root = mirror/kitao.dev
W="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 -m http.server "${1:-8765}" --bind 127.0.0.1 -d "$W/mirror/kitao.dev"
