import os, sys
print("startup __file__ =", os.path.relpath(__file__, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
print("sys.path[0] endswith:", sys.path[0].split(os.sep)[-2:])
try:
    import pkg
    print("import pkg OK", pkg.VALUE)
except ModuleNotFoundError as e:
    print("import pkg FAILED:", e)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import pkg
    print("after adding the app root to sys.path: import pkg OK", pkg.VALUE)
