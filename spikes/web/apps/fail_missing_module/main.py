import pyxel
import module_that_does_not_exist  # noqa: F401

pyxel.init(160, 120)
pyxel.run(lambda: None, lambda: pyxel.cls(1))
