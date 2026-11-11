---
paths:
  - "app/cp_core/datadefs.py"
  - "app/data/*.json"
  - "testpacks/**/*.json"
  - "tests/test_datadefs.py"
---

# Definition data (prototype rule file)

## Promises
- Every key of every table is in `SCHEMA`; unknown keys are errors. Notes use keys starting with `_`.
- On-screen names use `Label(max_len)`; the budget is the width the screens reserve. Raise it only together with the screens (`tools/screen_check.py` will tell).
- Shipped data produces zero warnings. Test packs live in `testpacks/`, never under `app/`.

## If you add X also do Y
- new table -> SCHEMA + LOAD_ORDER + a file in `app/data/` + a BROKEN case in `tests/test_datadefs.py`.
