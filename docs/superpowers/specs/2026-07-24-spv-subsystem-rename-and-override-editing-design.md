# SPV Subsystem Context Menu — Rename + Staged Hardpoint-Override Editing

**Date:** 2026-07-24
**Status:** Approved design, ready for implementation plan
**Branch:** `feat/spv-enhancements`

## Summary

Add a right-click context menu to the Ship Property Viewer's (SPV) subsystem
list. Its first (and only, for now) item is **Rename**, which changes a
subsystem's name. Renames are **staged** — applied live in the SPV for preview
but not written to disk — until the user explicitly clicks **Save** and confirms.
On save, the change is persisted into the engine-owned hardpoint override file
(`engine/appc/hardpoint_overrides.py`) through a **routing seam** that will later
direct edits for modded ships to the mod's own files.

This is the foundation for in-SPV editing of glow/light region values (the
literal next stage), so the persistence writer and the staged-change model are
built to carry arbitrary value edits, not just renames.

## Motivation

The SPV already renders every subsystem as a 3D pin + list row and knows each
subsystem's live object. `hardpoint_overrides.py` is the aggregated,
engine-owned place where per-ship hardpoint data is amended without editing the
SDK tree. Wiring the two together lets a developer tweak hardpoint data
(starting with names, soon glow volumes) visually and have the change persist as
a normal, later-committed source edit — the same file modders already use.

## Scope

**In scope (v1):**
- Right-click context menu on SPV subsystem-list rows, extensible to more items.
- A single **Rename** item → centred modal → stage the rename.
- Live preview of staged renames in the SPV list.
- A **Save changes (N)** affordance + confirmation that writes all pending
  changes to `hardpoint_overrides.py`.
- A routing seam (`resolve_override_target(ship)`) so the write destination is
  decided by ship origin, with only the game-ship target implemented.
- A generalized "managed-overrides" block writer in `hardpoint_overrides.py`.

**Out of scope (structure only, not built):**
- Editing glow/light region values in the SPV (next stage — the writer and
  staged-change model must accommodate it, but no UI/edit type is added here).
- Modded-ship override routing (the resolver has the seam; no mod target
  implementation).
- Guarding against renaming semantically-loaded subsystems (see Risks).

## Design

### Component 1 — Interaction (CEF + panel)

**Context menu.** Right-clicking a subsystem row opens a small menu anchored at
the cursor with one item, **Rename**. The menu is a list so future items append
without restructuring. Right-click sets a distinct "context-target" highlight on
the row and does **not** change the current 3D pin selection. ESC / click-away /
selecting an item closes it.

**Rename modal.** Selecting Rename opens a small centred modal reusing the
`cp-*` configuration-panel styling, with the subsystem's current name pre-filled
in a text field: `Rename "Port Impulse" → [__________]  [Apply] [Cancel]`.

**Staging.** Apply **stages** the edit:
- It applies live for preview — `subsystem.SetName(new_name)` on the real live
  object, so the list row updates immediately this session.
- It writes **nothing** to disk. The changed row shows a "dirty" marker.

**Save.** While any edit is pending, a **Save changes (N)** button is visible in
the SPV. Clicking it opens a confirmation listing the pending edits
("Amend these values in hardpoint_overrides.py?"). Only on confirm are the
changes written. Cancelling the confirmation leaves the pending edits staged.

**Closing without saving.** Closing the SPV with unsaved edits keeps the live
preview for the rest of the session (the live `SetName` already ran) but never
touches the file; the edits are lost on the next reload.

Applies to **all rows** — categories and children are all real subsystems with
`GetName`/`SetName`.

Mouse handling: right-click (`MOUSE_BUTTON_RIGHT`) over the list is chrome, like
the existing left-column rules — it must not start an orbit drag or pin pick.
The context menu and modal are `pointer-events:auto` CEF chrome.

### Component 2 — Apply + persist (routing seam)

A single staging entry point records a pending change and applies the live
preview. Persistence is deferred to Save and always routed:

```
resolve_override_target(ship) -> OverrideTarget
    game ship   → HardpointOverridesFile   (engine/appc/hardpoint_overrides.py)   [v1]
    modded ship → mod's own file           [future — seam only, not built]
```

- Save calls `resolve_override_target(ship).write(leaf, pending_changes)`.
- The SPV/UI code never names a path; adding mod support later is one resolver
  branch + one `OverrideTarget` implementation, no UI change.
- Leaf key = `ship.GetShipStats().HardpointFile` (the same key `OVERRIDES` uses
  and `loadspacehelper` imports).

**Pending-change model.** A staged change is generic enough to carry future edit
types: `(original_subsystem_name, operation)` where operation is a setter call.
For v1 the only operation is `SetName(new_name)`. Future glow edits are
`SetGlowRegionRadius(i, r)` etc. keyed by the same original subsystem name.

### Component 3 — Persistence writer (`hardpoint_overrides.py`)

`HardpointOverridesFile.write(leaf, pending_changes)` rewrites the `_<leaf>`
function in place, maintaining a **managed-overrides block** — not
rename-specific — grouped per subsystem:

```python
def _galaxy(find):
    # ... hand-authored glow (untouched) ...
    # >>> dauntless-overrides (managed) >>>
    p = find("Port Impulse")            # keyed by ORIGINAL stock name
    if p is not None:
        p.SetName("Left Impulse")       # rename today
        # p.SetGlowRegionRadius(0, 0.30)  ← light edits land here later
    # <<< dauntless-overrides <<<
```

Rules:
- The managed block is placed at the **end** of the function so hand-authored
  glow `find("<stock name>")` lookups resolve against the stock name *before*
  any rename runs.
- If the ship has no section, the writer creates the `_<leaf>(find)` function and
  registers it in the `OVERRIDES` dict.
- The writer parses the existing managed block to key edits by **original stock
  name**, so it is idempotent, re-nameable (renaming an already-renamed
  subsystem updates its entry rather than chaining/duplicating), and additive (a
  later radius edit joins the same `find` group). No runtime registry is needed —
  the block is the source of truth for original→current.
- Only the managed block (between the delimiter comments) is ever rewritten;
  hand-authored code outside it is preserved byte-for-byte.

**Original-name resolution.** The SPV row shows the current (possibly already
overridden) name. To key an edit by original stock name, the writer inverts the
existing managed block's `find(original) → SetName(current)` entries: if the
row's current name matches an existing entry's target, that entry's `find`
argument is the original key; otherwise the current name *is* the original.

### Component 4 — Load-time application (unchanged mechanism)

No change to how overrides apply: `hardpoint_overrides.apply(leaf)` already runs
each `_<leaf>` function from the SDK-loader hook after the hardpoint registers
its templates (and again after `loadspacehelper`'s reload, before
`LoadPropertySet`). The managed block's `SetName`/setter calls run there like any
other override. Persisted renames therefore take effect on the next load; the
live `SetName` covers the current session.

## Risks and mitigations

- **Canonical-name coupling.** `SetName` renames the *functional* subsystem.
  SDK/targeting/combat/glow code that looks up subsystems by canonical name
  (e.g. "Bridge", "Shield Generator", or the glow block's own `find()` args) can
  be affected. The SPV is `--developer`-only, so v1 accepts this and does not
  guard renaming semantically-loaded systems. Ordering the managed block last
  protects the *same-file* glow lookups; cross-system name coupling is the
  developer's responsibility. A future warning on known-load-bearing names is
  possible but out of scope.
- **Runtime source mutation.** Writing to a tracked source file at runtime is
  acceptable in this repo (it is an intended, later-committed edit). It only
  affects future loads; the live preview covers the session. The writer must be
  crash-safe: a parse/format failure aborts the write without corrupting the
  file (write to a temp buffer, validate it parses, then replace).
- **Concurrent SPV edits / stale file.** The writer re-reads and re-parses the
  file at Save time, so it composes with hand edits made between session start
  and Save.

## Testing

- **Writer unit tests** (pure, no GL): create/extend a `_<leaf>` function; add a
  rename; re-rename the same subsystem (updates, not duplicates); rename a second
  subsystem in the same ship (new `find` group); hand-authored glow code outside
  the managed block is preserved; malformed input aborts without corrupting the
  file. Assert the written module imports and `apply(leaf)` calls the expected
  `SetName`.
- **Routing tests:** `resolve_override_target` returns the game target for a
  stock ship; the seam is exercised without a mod target.
- **Panel tests:** staging records a pending change and calls the live `SetName`;
  Save routes to the target with all pending changes; the dirty marker /
  `Save (N)` count reflects pending state; closing without save does not write.
- **Mouse-region test:** right-click over the list is treated as chrome (no
  orbit/pick), mirroring the existing left-column coverage.
- Full gate (`scripts/check_tests.sh`) green; live-verify under `--developer`.

## Future work (informs structure, not built here)

- In-SPV glow/light region editing reuses the pending-change model, the routing
  seam, and the managed-overrides block — adding an edit UI and new operation
  types only.
- Modded-ship routing: a second `OverrideTarget` writing to the mod's files.
