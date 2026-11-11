---
paths:
  - "app/cp_core/storage.py"
  - "app/cp_core/profile.py"
  - "app/cp_app/storage_web.py"
  - "tests/test_storage.py"
  - "tests/test_profile.py"
  - "tests/snapshots/profile_schema.json"
---

# Save data (prototype rule file)

## Promises
- The game talks to `SaveStore` only. Files and localStorage are backends; no other module opens save files or touches `js.localStorage`.
- A new persistent field: add it to the dataclass, decide version bump + migration, update `profile_schema.json` in the same commit. A field that must not persist goes into `NOT_SAVED` with its reason.
- Unreadable data is quarantined (`<key>.bad`), never overwritten silently.

## If you add X also do Y
- new blob kind -> key prefix in `cp_core/profile.py` docstring, size accounting test, web smoke still passes.
