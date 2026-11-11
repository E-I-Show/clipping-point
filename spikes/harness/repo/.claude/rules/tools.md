---
paths:
  - "tools/*.py"
  - "tools/claude/*.py"
  - "tools/web/*"
---

# Verification tools (prototype rule file)

## Promises
- Exit codes: 0 pass, 1 problems, 2 could not finish / nothing checked. Every wrapper ends with one `<TOOL>_OK|FAILED|INCOMPLETE key=value...` line that carries counts.
- The verification plan exists once, in `tools/verify.py` (STEPS, ALL, AREAS).
- After changing a tool run `python3 tools/selftest_break.py`: every planted fault must be caught.
