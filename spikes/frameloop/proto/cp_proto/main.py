# title: CLIPPING POINT frame-loop prototype
# author: spike
# desc: 60 Hz update / 30 fps render skeleton with headless smoke test
# version: 0.0.1
#
# Startup script. Must sit at the app root: `pyxel play` puts THIS file's directory on sys.path,
# so cp_core / cp_app are importable only when main.py is next to them.
from cp_app.app import main

main()
