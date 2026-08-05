# SPV Live Emitter Refresh on Save (design)

**Date:** 2026-08-05
**Status:** approved (Mark), ready for implementation plan
**Area:** Ship Property Viewer save path + host-loop emitter cache

## Goal

When the SPV Save persists subsystem light-emitter edits, the player ship's
emitters must update **live, next frame** — no game restart. Emitters only
this pass; glow volumes (and subsystem-position re-anchoring, which only
affects glow volumes) are a deferred follow-up.

## Background — why a restart is needed today

The per-frame emitter producer reads `session.ship_emitters[iid]`, a cache
built **once at spawn** by `_build_ship_emitter_cache(ship)`, which reads each
subsystem's `GetProperty()` → `light_emitters.baked_emitters(prop)`. The SPV
Save writes `hardpoint_overrides.py` but never touches that cache, so the live
ship keeps its spawn-time emitters until the next ship build.

**Emitter positions are ship body-frame** (`light_emitters.py:3-4`; the
producer transforms `spec["position"]` by the *ship's* world transform only,
`host_loop.py:1019`), independent of the subsystem mount. So every renderable
emitter property — position, axis, length, radius, colour, intensity, kind —
lives inside the emitter **spec**. Refreshing the cache from the current specs
therefore refreshes everything an emitter renders. Moving a *subsystem*
(`SetPosition`) does not move its emitters; it only re-anchors that subsystem's
glow volumes, which are out of scope here.

## Approach — rebuild the live cache from the SPV's authoritative specs

The SPV panel already holds the authoritative post-save emitter specs per
subsystem (`_effective_emitters(i)`, which after Save reads `_saved_emitter`).
Rather than round-trip through the live property (which cannot cleanly express
an emitter *removal* — `baked_emitters` stops at the first unset
`LightEmitterKind`, and there is no property "unset"), the host rebuilds the
cache **directly from the panel's effective specs**. The file write is
unchanged and remains the persistence path; only the in-memory live cache is
rebuilt.

This handles add / remove / recolour / retune / reposition uniformly, because
the panel's effective list is the ground truth the SPV preview already shows.

### Part 1 — `_build_ship_emitter_cache` gains an optional spec source

Refactor (behaviour-preserving) so the builder can source specs from something
other than the live property:

```python
def _build_ship_emitter_cache(ship, specs_of=None):
    """... specs_of: optional (sub) -> list[spec]; defaults to reading
    baked_emitters(sub.GetProperty()). Everything else (impulse membership,
    phase = j*1.7 + subsystem_index, iteration over _iter_subsystems) is
    unchanged."""
    ...
    for si, sub in enumerate(_iter_subsystems(ship)):
        if specs_of is None:
            prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
            specs = light_emitters.baked_emitters(prop) if prop is not None else []
        else:
            specs = specs_of(sub) or []
        if not specs:
            continue
        is_impulse = id(sub) in impulse_ids
        for j, spec in enumerate(specs):
            entries.append((sub, is_impulse, j * 1.7 + si, spec))
    return entries
```

The default path (`specs_of is None`) is byte-for-byte the current behaviour,
so every existing spawn caller is unaffected.

### Part 2 — a host refresh helper keyed by the panel's specs

```python
def refresh_ship_emitters(session, ship, specs_by_sub_id):
    """Rebuild session.ship_emitters for `ship` from SPV effective specs.
    `specs_by_sub_id` maps id(subsystem) -> list[spec]. No-op if the ship has
    no live render instance. Best-effort (logged under --developer)."""
    if session is None or ship is None:
        return
    iid = session.ship_instances.get(ship) if session.ship_instances else None
    if iid is None:
        return
    try:
        session.ship_emitters[iid] = _build_ship_emitter_cache(
            ship, specs_of=lambda sub: specs_by_sub_id.get(id(sub), []))
    except Exception as e:
        dev_mode.log_swallowed("spv live emitter refresh", e)
```

Subsystems the SPV never touched return their unchanged baked list via
`_effective_emitters`, so their cache entries rebuild identically.

### Part 3 — the panel invokes a callback on save

The panel takes an optional `on_saved` callback at construction (default
`None`, so all existing tests/constructions keep working):

```python
def __init__(self, ship_getter, on_saved=None):
    ...
    self._on_saved = on_saved
```

At the end of the successful `save` branch (after the `_saved_*` dicts are
updated and pending cleared), it builds the spec map and invokes the callback.

**Descriptors do NOT carry the live subsystem object** (they are
`json.dumps`'d for CEF, so a raw object can't be stored on them). Instead the
panel re-walks `_iter_subsystems(ship)` with the **same skip rule and order**
`build_descriptors` uses (skip a subsystem whose `GetPosition()` is `None`;
increment a `di` counter only for kept ones), so `di` lines up with the
descriptor index and `self._effective_emitters(di)` is the authoritative list:

```python
if self._on_saved is not None:
    from engine.ui.ship_property_viewer import _iter_subsystems
    specs_by_sub_id = {}
    di = 0
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue                       # same skip as build_descriptors
        specs_by_sub_id[id(sub)] = self._effective_emitters(di)
        di += 1
    try:
        self._on_saved(ship, specs_by_sub_id)
    except Exception:
        pass   # a live-refresh failure must never break Save/persistence
```

`id(sub)` here is the same object identity the cache builder sees (both walk
`_iter_subsystems(ship)`), so the `specs_of` lookup in Part 2 matches. Any
subsystem the cache builder visits that is absent from the map (e.g. a
non-positionable one, which can never hold an SPV-authored emitter anyway)
falls back to `[]` — correct.

### Part 4 — wire the callback at construction

In `host_loop.py` where the panel is built (`~6250`):

```python
ship_property_viewer = ShipPropertyViewerPanel(
    ship_getter=_spv_player,
    on_saved=lambda ship, specs: refresh_ship_emitters(
        controller.session, ship, specs),
)
```

`controller`/`session` are already in scope there (the `_spv_player` closure
uses them).

## Non-goals

- **Glow volumes** — deferred (needs a native clear-regions binding).
- **Subsystem-position / radius live refresh** — position only matters for
  glow volumes; radius is a gameplay/collision property the SPV preview
  already reflects. Both stay file-only (next spawn), as today.
- No change to persistence, the file format, or the renderer.

## Testing

Python (pytest), headless:

- **Builder refactor:** `_build_ship_emitter_cache(ship, specs_of=...)` sources
  from the callable; `specs_of=None` reproduces the property-read path
  (regression: existing spawn behaviour unchanged); impulse membership + phase
  identical on both paths.
- **Refresh helper:** rebuilds `session.ship_emitters[iid]` from the spec map;
  add/remove/edit all reflected; unknown-`id(sub)` → empty list (dropped);
  no live instance → no-op; a raising builder is swallowed.
- **Panel callback:** a successful Save with emitter edits invokes `on_saved`
  with a `specs_by_sub_id` matching the panel's effective emitters; a Save with
  no callback set does not crash; a callback that raises does not break the
  save (pending still cleared, file still written).

Gate: `scripts/check_tests.sh` (no C++ change; ctest unaffected).

## Global constraints

- Emitters only; glow volumes and subsystem-position/radius stay file-only.
- `_build_ship_emitter_cache(ship)` with no `specs_of` MUST be byte-identical
  to today (every spawn caller depends on it).
- A live-refresh failure must NEVER break Save or persistence — the callback
  is best-effort and fully guarded.
- Rebuild from the panel's authoritative effective specs, NOT by mutating the
  live property (removal can't be expressed on a property).
- Production/spawn path unaffected; the callback is `None` unless wired.
