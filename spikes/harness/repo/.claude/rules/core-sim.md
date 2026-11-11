---
paths:
  - "app/cp_core/world.py"
  - "app/cp_core/rng.py"
  - "app/cp_core/session.py"
  - "tests/test_world_fingerprint.py"
  - "tests/test_rng.py"
  - "tests/test_session.py"
  - "tests/snapshots/world_*.json"
---

# Simulation and determinism (prototype rule file)

## Promises
- One call of `step` = one tick = 1/60 s. No wall clock, no frame time in logic.
- Random numbers come from `cp_core.rng` only. A new feature draws with `hash_u64` / `hash_unit`
  (seed + keys), never from an existing stream: existing snapshots must not move.
- Snapshots under `tests/snapshots/` change only with `tools/test.py --update-snapshots`, in a
  commit of their own that says why and which fields were expected to move.

## Guard tests
- `test_world_fingerprint_matches_snapshot`: fixed-input scenarios, full summary pinned.
- `test_rng_same_result_in_processes_with_different_hash_seeds`: nothing depends on PYTHONHASHSEED.

When designing a stage in this area read `docs/proposals.md`.
