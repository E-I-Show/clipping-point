import pyxel
pyxel.init(64, 64, headless=True)
try:
    pyxel.init(64, 64, headless=True)
    print("second init OK")
except BaseException as e:
    print("second init ->", type(e).__name__, str(e)[:80])
