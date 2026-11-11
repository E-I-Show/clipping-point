---
paths:
  - "app/cp_ui/*.py"
  - "app/cp_app/canvas_pyxel.py"
  - "tests/test_ui_screens.py"
---

# 2D screens (prototype rule file)

## Promises
- Screens draw only through `Canvas` (text / rect / rectb / line / blt). No direct `pyxel.*` or `Image.*` draw call for 2D UI: the tour counts ink that no recorded call covers.
- Whole-pixel int coordinates. Every panel, row and HUD cluster is a `canvas.box(...)`.
- Text is printable ASCII (the built-in font draws nothing for other characters).

## If you add X also do Y
- new screen -> `SCREENS` + `fixtures.build` (typical and extreme) ; then `tools/screen_check.py --only <name>` and `tools/tour.py --only <name>` and look at the PNGs.
