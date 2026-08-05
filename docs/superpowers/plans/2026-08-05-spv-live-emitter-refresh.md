# SPV Live Emitter Refresh on Save Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On SPV Save, rebuild the player ship's live emitter cache from the panel's authoritative specs so light-emitter edits appear next frame with no restart.

**Architecture:** Pure Python. `_build_ship_emitter_cache` gains an optional spec source; a host helper rebuilds `session.ship_emitters[iid]` from the SPV's effective specs; the panel invokes a best-effort `on_saved` callback wired at construction.

**Tech Stack:** Python 3 (pytest). No C++.

**Design doc:** `docs/superpowers/specs/2026-08-05-spv-live-emitter-refresh-design.md`

## Global Constraints

- **Emitters only.** Glow volumes, subsystem-position, and radius stay file-only (next spawn), as today.
- `_build_ship_emitter_cache(ship)` with **no** `specs_of` argument MUST be byte-identical to today — every spawn caller depends on it.
- A live-refresh failure must **NEVER** break Save or persistence — the callback and helper are best-effort and fully guarded (swallow + `dev_mode.log_swallowed`).
- Rebuild from the panel's authoritative **effective specs**, NOT by mutating the live property (an emitter removal cannot be expressed on a property — `baked_emitters` stops at the first unset `LightEmitterKind`).
- The callback is `None` unless wired, so production/spawn and every existing test are unaffected.
- Test gate: `scripts/check_tests.sh`.

---

### Task 1: Emitter-cache spec source + host refresh helper

**Files:**
- Modify: `engine/host_loop.py` (`_build_ship_emitter_cache` ~line 934; add `refresh_ship_emitters` nearby)
- Test: `tests/test_host_loop_emitter_refresh.py` (create)

**Interfaces:**
- Consumes: `_iter_subsystems`, `light_emitters.baked_emitters`, `subsystem_glow.impulse_engines`, `session.ship_instances` (ship→iid), `session.ship_emitters` (iid→cache list), `dev_mode.log_swallowed`.
- Produces: `_build_ship_emitter_cache(ship, specs_of=None)` (new optional param); `refresh_ship_emitters(session, ship, specs_by_sub_id)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_host_loop_emitter_refresh.py`. Build a minimal fake ship whose `_iter_subsystems` yields two fake subsystems, each with `GetProperty()` returning a property `baked_emitters` can read. Reuse the emitter-cache test scaffolding in `tests/test_host_loop_emitter_lights.py` (it already constructs fake ships + subsystems with baked emitters — mirror that fixture rather than inventing a new fake surface). Assertions:

```python
def test_build_cache_specs_of_overrides_property(fake_ship_two_subs):
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs
    # specs_of supplies a brand-new emitter list for subA, none for subB
    new_spec = {"kind": "point", "position": (1.0, 2.0, 3.0),
                "axis": (0.0, -1.0, 0.0), "length": 1.0, "radius": 0.5,
                "radius_y": 0.5, "color": (1.0, 0.0, 0.0), "intensity": 2.0}
    entries = host_loop._build_ship_emitter_cache(
        ship, specs_of=lambda sub: [new_spec] if sub is subA else [])
    # exactly one entry, for subA, carrying the supplied spec
    assert len(entries) == 1
    sub, is_impulse, phase, spec = entries[0]
    assert sub is subA
    assert spec["position"] == (1.0, 2.0, 3.0)


def test_build_cache_default_reads_property(fake_ship_two_subs):
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs
    # specs_of=None reproduces the property-read path unchanged
    default_entries = host_loop._build_ship_emitter_cache(ship)
    assert isinstance(default_entries, list)
    # every entry's sub is one of the two, and specs come from baked_emitters
    for sub, _imp, _ph, _spec in default_entries:
        assert sub in (subA, subB)


def test_refresh_ship_emitters_rebuilds_cache():
    from engine import host_loop
    class Sess:
        ship_instances = {}
        ship_emitters = {}
    ship = object()
    subid_specs = {}
    sess = Sess()
    # no live instance for this ship → no-op (must not raise, must not create a key)
    host_loop.refresh_ship_emitters(sess, ship, subid_specs)
    assert sess.ship_emitters == {}
```

Add a `fake_ship_two_subs` fixture. If `tests/test_host_loop_emitter_lights.py` exposes reusable fake builders, import them; otherwise build a small fake here with two subsystems each exposing `GetProperty()` (property with baked emitter data) and `GetName()`, and a ship exposing whatever `_iter_subsystems` requires (check `_iter_subsystems` in `engine/ui/ship_property_viewer.py` for the accessor chain — mirror the fake used by the existing emitter-light test).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_host_loop_emitter_refresh.py -v`
Expected: FAIL — `_build_ship_emitter_cache()` takes no `specs_of`; `refresh_ship_emitters` undefined.

- [ ] **Step 3: Add the `specs_of` parameter**

In `_build_ship_emitter_cache` (host_loop.py ~934), change the signature to `def _build_ship_emitter_cache(ship, specs_of=None):` and replace the per-subsystem spec read:

```python
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
```

Keep the impulse-membership block and everything else exactly as-is. The `specs_of is None` branch must be behaviourally identical to the current code (the current code does `prop = sub.GetProperty() if hasattr(...) else None; if prop is None: continue; specs = baked_emitters(prop)` — preserve the effective semantics: a `None` prop yields no specs and is skipped).

- [ ] **Step 4: Add the refresh helper**

Add near `_build_ship_emitter_cache`:

```python
def refresh_ship_emitters(session, ship, specs_by_sub_id):
    """Rebuild session.ship_emitters for `ship` from SPV effective specs.
    `specs_by_sub_id` maps id(subsystem) -> list[spec]. No-op if the ship has
    no live render instance. Best-effort (never raises)."""
    if session is None or ship is None:
        return
    instances = getattr(session, "ship_instances", None)
    iid = instances.get(ship) if instances else None
    if iid is None:
        return
    try:
        session.ship_emitters[iid] = _build_ship_emitter_cache(
            ship, specs_of=lambda sub: specs_by_sub_id.get(id(sub), []))
    except Exception as e:
        dev_mode.log_swallowed("spv live emitter refresh", e)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_host_loop_emitter_refresh.py -v`
Expected: PASS.

- [ ] **Step 6: Regression — existing emitter-light tests still green**

Run: `uv run pytest tests/test_host_loop_emitter_lights.py -v`
Expected: PASS (the default `specs_of=None` path is unchanged).

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/test_host_loop_emitter_refresh.py
git commit -m "feat(spv): emitter-cache spec source + live refresh helper"
```

---

### Task 2: Panel save callback + host wiring

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (`__init__` ~92; the `save` handler ~2378)
- Modify: `engine/host_loop.py` (panel construction ~6250)
- Test: `tests/ui/test_ship_property_viewer_save_refresh.py` (create)

**Interfaces:**
- Consumes: `_iter_subsystems` (from `engine.ui.ship_property_viewer`), `_effective_emitters`, the existing `save` handler, `Task 1`'s `refresh_ship_emitters`.
- Produces: `ShipPropertyViewerPanel(ship_getter, on_saved=None)`; the on-save callback invocation; the wired `on_saved` lambda at the host construction site.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_ship_property_viewer_save_refresh.py`. Reuse the panel fixture pattern from `tests/ui/test_ship_property_viewer_pipette.py` (monkeypatch `build_descriptors`), and construct the panel with an `on_saved` spy. Because Save writes a file, stub the write path the same way the existing panel save tests do (find how `tests/ui/` tests exercise the `save` action without a real ship/leaf — mirror that). Assertions:

```python
def test_save_invokes_on_saved_with_effective_specs(spv_panel_factory, monkeypatch):
    calls = []
    p = spv_panel_factory(on_saved=lambda ship, specs: calls.append((ship, specs)))
    p.open()
    # stage an emitter edit on subsystem 0, then Save (stub the writer as the
    # existing save tests do so the write "succeeds")
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    ... # arrange a successful save (stub resolve_override_target(...).write)
    p.dispatch_event("save")
    assert len(calls) == 1
    ship, specs = calls[0]
    # specs is keyed by id(sub); at least one sub maps to a non-empty list
    assert any(v for v in specs.values())


def test_save_without_callback_does_not_crash(spv_panel_factory):
    p = spv_panel_factory(on_saved=None)
    p.open()
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    ... # arrange a successful save
    p.dispatch_event("save")   # must not raise


def test_on_saved_exception_does_not_break_save(spv_panel_factory):
    def boom(ship, specs):
        raise RuntimeError("refresh failed")
    p = spv_panel_factory(on_saved=boom)
    p.open()
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    ... # arrange a successful save
    p.dispatch_event("save")
    assert not p._pending_emitter   # pending still cleared → save completed
```

Provide a `spv_panel_factory(on_saved=...)` fixture that builds a real `ShipPropertyViewerPanel` with the monkeypatched `build_descriptors` (subsystems with `GetPosition`/`GetProperty`) and returns it. Determine the exact successful-save stub by reading how the current `save` tests in `tests/ui/` drive the `save` action (the handler calls `hardpoint_leaf_for_ship(ship)` and `resolve_override_target(ship).write(leaf, edits)` — stub whichever the existing tests stub so the write path returns without error).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_save_refresh.py -v`
Expected: FAIL — `__init__` has no `on_saved`; callback never invoked.

- [ ] **Step 3: Add the `on_saved` constructor param**

In `__init__` (panel ~92), change the signature to `def __init__(self, ship_getter, on_saved=None):` and store `self._on_saved = on_saved` alongside `self._ship_getter`. (No reset needed in `open()`/`close()` — it's construction-time config.)

- [ ] **Step 4: Invoke the callback on successful save**

At the END of the `save` handler's success branch (after `self._last_pushed = None`, just before `return True` — i.e. after `_saved_emitter.update(...)`, pending cleared, and `_undo_stack.clear()`), add:

```python
if self._on_saved is not None:
    try:
        from engine.ui.ship_property_viewer import _iter_subsystems
        specs_by_sub_id = {}
        di = 0
        for sub in _iter_subsystems(ship):
            local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
            if local is None:
                continue                       # same skip as build_descriptors
            specs_by_sub_id[id(sub)] = self._effective_emitters(di)
            di += 1
        self._on_saved(ship, specs_by_sub_id)
    except Exception:
        pass   # live refresh is best-effort; never break Save/persistence
```

(`ship` is already resolved earlier in the save handler as `ship = self._ship_getter()`.)

- [ ] **Step 5: Wire the callback at the host construction site**

In `host_loop.py` (~6250) change the panel construction to pass the callback:

```python
ship_property_viewer = ShipPropertyViewerPanel(
    ship_getter=_spv_player,
    on_saved=lambda ship, specs: refresh_ship_emitters(
        controller.session, ship, specs),
)
```

`controller` is in scope there (the `_spv_player` closure above it uses `controller.session`). Confirm `refresh_ship_emitters` is importable/defined at module scope in `host_loop.py` (Task 1).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_save_refresh.py -v`
Expected: PASS.

- [ ] **Step 7: Full gate**

Run: `scripts/check_tests.sh`
Expected: OK — no new failures (1 known baselined). No C++ changed.

- [ ] **Step 8: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py engine/host_loop.py tests/ui/test_ship_property_viewer_save_refresh.py
git commit -m "feat(spv): live-refresh player emitters on save"
```

---

## Self-review notes

- **Spec coverage:** Part 1 (spec source) + Part 2 (refresh helper) → Task 1; Part 3 (panel callback) + Part 4 (wiring) → Task 2. Full coverage.
- **Type consistency:** `specs_of` is `(sub) -> list[spec]`; `specs_by_sub_id` is `{id(sub): list[spec]}`; `refresh_ship_emitters(session, ship, specs_by_sub_id)`; `on_saved(ship, specs_by_sub_id)`. Consistent across tasks.
- **Ordering:** Task 1 defines `refresh_ship_emitters` that Task 2's wiring calls — Task 1 first.
- **Risk:** the `specs_of=None` behaviour-identity is the one regression surface — Task 1 Step 6 guards it with the existing emitter-light suite. The save-path stub in Task 2 must match how existing `tests/ui/` save tests drive a successful write; the implementer reads those first.
