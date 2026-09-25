# System Frames — Plan 3: Seeing the System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standing in any region of a mapped system, you see that system — its other worlds at their true bearings, distances and sizes, drawn from the system map — because entering a system loads all its regions, celestial bodies are drawn from the map only, and ships are realized from every set in the viewed frame.

**Architecture:** A level-triggered system loader creates a system's missing regions through BC's own region modules (Plan 1's wrap maps them). A pure function turns the viewed frame into a celestial draw list (map bodies, positioned in the viewed set's local coordinates); `host_loop` diffs render instances against it, so there is nothing to cache, supersede or sweep. A mapped set's Planet objects are never realized — they exist only for interaction, and `apply_map` put them exactly where the map body is drawn. Ship realization and the celestial/sun scope follow `frames.viewing_set()`, unifying the render scope Plan 2 left split (its Ruling 3).

**Tech Stack:** Python 3 (engine, pytest). No native changes in this plan.

**Spec:** `docs/superpowers/specs/2026-09-24-system-frames-design.md` — §3 (loading a system), §4 (drawing), testing and live yardstick. Plans 1 and 2 are complete on this branch.

## ⚠️ Proposed spec change — needs Mark's approval at plan review

Spec §5 (the double-precision render origin) and its mesh-query relativisation are **deferred from Plan 3 to the plan that builds the hand-off and dash.** Evidence:

- float32 precision only degrades FAR from the viewed set's local origin: ulp is 0.0039 GU at 50,000 GU and 0.0625 GU at 900,000 GU.
- Until the player can travel between regions, the camera stays within a region's content: every region's staged content lies within 46,773 GU of its set origin (Prendel 3's region radius, the largest). Near-camera precision is therefore ≤ ~0.004 GU — as today.
- Distant map bodies are drawn up to ~900,000 GU away, where 0.06 GU is invisible.
- Precision fails exactly when a ship can be ~450,000 GU from its set's origin — only possible once the dash / hand-off lets the player leave a region, which is the next plan.
- The render origin touches every native pass that reads `camera.eye` as absolute (15+ sites: torpedo, dust, nebula, godray, reticle, hologram, cloak, sun, lens flare, shadow fit, pins) plus the transform store and five mesh-query bindings; doing it now delays the next live pass for no visible benefit.

Task 5 records this in the spec. If Mark declines, the render origin becomes an extra task before Task 5 and this plan grows by that task.

## Global Constraints

- Work only in `.claude/worktrees/system-frames` on `feat/system-frames`. Export `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"` and `DAUNTLESS_SDK_DIR="/Users/mward/Documents/Star Trek Bridge Commander/sdk"` in every shell.
- **Banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Explicit pathspecs. Mutation: cp → edit → run → cp back → `diff` silent.
- **The draw list is a pure function of the viewed frame** (spec §4). No proxy cache, no supersession queue, no sweep — the reference branch's failure mode.
- **In a mapped frame the system map is the only draw source for planets/moons.** A mapped set's Planet objects are never realized as render instances. Unmapped frames draw exactly as today.
- **Suns:** exactly one, from the VIEWED set's own Sun object (Plan 1's `apply_map` placed every region's Sun at the map star, so the viewed set's Sun is already the map star in view coordinates). Never draw a sibling set's Sun.
- **Nothing unloads until the mission changes** (spec §3); arrival adopts an existing set, never re-creates it.
- All positions handed to the renderer are in the VIEWED set's local coordinates (Plan 2's convention; `frames.in_view`, `frames.viewing_set()`).
- A region module is `Systems.<map.system>.<region.set_name>` — verified: every map's `system` equals its SDK `Systems/` directory name.
- Never spell `game`/`sdk` as a path segment; never capture a path at import. Never launch the game. The gate (`scripts/check_tests.sh`) decides failures. Known intermittents: `tests/integration/test_pursuers_avoid_each_other.py`, `tests/integration/test_orbit_planet_ai.py::test_orbit_ai_out_of_range_fires_only_on_arrival` — re-run in isolation and report if one fails.
- In test bodies `<...>` stands for objects built with the builders the cited existing test file uses; assertions are fixed in meaning and never weakened.

## Review Focus

1. **A mission that `Initialize()`s a region AFTER the loader already created it** (BC's Initialize creates a new SetClass and `AddSet` replaces ours). The mission's set must win and be mapped; nothing may keep drawing or interacting with the orphaned set. → Task 1, `test_a_mission_reinitializing_a_loaded_region_wins`.
2. **A region module that fails to import or raises in Initialize** must not strand the player or stop the other regions loading (the reference branch's `51412754` lesson); it must be logged loudly. → Task 1, `test_one_broken_region_does_not_stop_the_rest`.
3. **The warp tunnel** (`_WarpTransit`, an unmapped one-set frame) must draw NO map bodies, and arriving back must restore exactly the arrival frame's bodies — the reference branch's live bug. → Task 5, `test_sky_round_trip`.
4. **A cutscene rendering a sibling region** (`MakeRenderedSet("Ona2")` while the player is in Ona1): planets, the sun and ships must all come from the Ona2 view — one scope, not two. → Task 3, `test_a_sibling_region_cutscene_draws_one_consistent_scene`.
5. **Two mapped bodies with the same display name in one system** (Geble3 and Geble4 both have "Moon 1"): the draw list must key by owner region, never name alone. → Task 2, `test_draw_list_keys_bodies_by_owner_region`.

---

### Task 1: Entering a system loads all its regions

**Files:**
- Create: `engine/systems/system_loader.py`
- Modify: `engine/host_loop.py` (call the loader once per tick before instance reconciliation; reset it on mission swap)
- Test: `tests/unit/test_system_loader.py`

**Interfaces:**
- Consumes: `frames.containing_set(obj)`, `frames.frame_of(pSet)`, `resolve.regions_of(system) -> list[str]`, `region_hooks.is_mapped(pSet)`, `App.g_kSetManager.GetSet(name)`.
- Produces:
  - `system_loader.ensure_loaded(player) -> list[str]` — if the player's set is in a mapped system frame not yet loaded, creates every region of that system whose set does not exist (via `importlib.import_module(f"Systems.{system}.{region}").Initialize()`), and returns the names it created; `[]` when there is nothing to do. Level-triggered, idempotent, cheap when nothing changed (one frame-key compare).
  - `system_loader.reset() -> None` — forget the last loaded system (mission swap; `tests/conftest.py` autouse reset).
  - `system_loader.loaded_system() -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_system_loader.py`:

```python
"""Entering a system loads all its regions (system-frames spec §3)."""
import sys

import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import region_hooks, system_loader
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()
    system_loader.reset()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    system_loader.reset()


def _player_in(pSet):
    p = App.ShipClass_Create()
    p.SetName("player")
    pSet.AddObjectToSet(p, "player")
    return p


def test_entering_a_region_loads_its_siblings_mapped():
    player = _player_in(load_region("Ona", "Ona1"))
    created = system_loader.ensure_loaded(player)
    assert sorted(created) == ["Ona2", "Ona3"]
    for name in ("Ona1", "Ona2", "Ona3"):
        pSet = App.g_kSetManager.GetSet(name)
        assert pSet is not None and region_hooks.is_mapped(pSet)
    assert system_loader.loaded_system() == "Ona"


def test_it_is_idempotent_and_adopts_existing_sets():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")          # a mission already made it
    player = _player_in(ona1)
    assert system_loader.ensure_loaded(player) == ["Ona3"]
    assert App.g_kSetManager.GetSet("Ona2") is ona2
    assert system_loader.ensure_loaded(player) == []


def test_an_unmapped_set_loads_nothing():
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    assert system_loader.ensure_loaded(_player_in(qb)) == []
    assert system_loader.loaded_system() is None


def test_moving_to_another_system_loads_it_and_unloads_nothing():
    player = _player_in(load_region("Ona", "Ona1"))
    system_loader.ensure_loaded(player)
    xi = load_region("XiEntrades", "XiEntrades4")
    App.g_kSetManager.GetSet("Ona1").RemoveObjectFromSet("player")
    xi.AddObjectToSet(player, "player")
    created = system_loader.ensure_loaded(player)
    assert "XiEntrades4" not in created and len(created) >= 1
    assert App.g_kSetManager.GetSet("Ona2") is not None   # nothing unloaded


def test_one_broken_region_does_not_stop_the_rest(monkeypatch, capsys):
    """Review Focus 2."""
    import importlib
    real = importlib.import_module
    def flaky(name, *a, **k):
        if name == "Systems.Ona.Ona2":
            raise ImportError("simulated broken region module")
        return real(name, *a, **k)
    monkeypatch.setattr(importlib, "import_module", flaky)
    player = _player_in(load_region("Ona", "Ona1"))
    created = system_loader.ensure_loaded(player)
    assert "Ona3" in created and "Ona2" not in created
    assert "Ona2" in capsys.readouterr().out            # logged loudly


def test_a_mission_reinitializing_a_loaded_region_wins():
    """Review Focus 1: BC's Initialize replaces the set; the new one is mapped
    and is what GetSet returns."""
    player = _player_in(load_region("Ona", "Ona1"))
    system_loader.ensure_loaded(player)
    ours = App.g_kSetManager.GetSet("Ona2")
    theirs = load_region("Ona", "Ona2")                  # the mission's own call
    assert App.g_kSetManager.GetSet("Ona2") is theirs is not ours
    assert region_hooks.is_mapped(theirs)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_system_loader.py -v`
Expected: collection ERROR — `cannot import name 'system_loader'`.

- [ ] **Step 3: Implement `engine/systems/system_loader.py`**

```python
"""Entering a star system loads every one of its regions (spec §3).

Level-triggered: each tick the host asks ensure_loaded(player). When the
player's set is a mapped region of a system not yet loaded, each region of
that system whose set does not exist is created through BC's own region
module -- Systems.<System>.<Region>.Initialize() -- so Plan 1's wrap applies
the map before anything realizes it. Sets that already exist (a mission made
them, or we did earlier) are adopted, never re-created. Nothing is unloaded
until the mission changes: that is BC's own bound (the mission-swap
_sets.clear()), and leaving a system is not a lifetime event.

One broken region module must not strand the player or stop its siblings
loading: its failure is printed loudly and the loop continues.
"""
from __future__ import annotations

import importlib

_loaded: str | None = None


def reset() -> None:
    global _loaded
    _loaded = None


def loaded_system() -> str | None:
    return _loaded


def ensure_loaded(player) -> list:
    global _loaded
    from engine.systems import frames, resolve
    f = frames.frame_of(frames.containing_set(player))
    if f is None or f.key[0] != "system":
        return []
    system = f.key[1]
    if system == _loaded:
        return []
    import App
    created = []
    for region in resolve.regions_of(system):
        if App.g_kSetManager.GetSet(region) is not None:
            continue
        qual = f"Systems.{system}.{region}"
        try:
            importlib.import_module(qual).Initialize()
        except Exception as exc:  # noqa: BLE001 -- one region never strands the rest
            print(f"[systems] could not load region {region!r} ({qual}): "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue
        if App.g_kSetManager.GetSet(region) is not None:
            created.append(region)
    _loaded = system
    return created
```

- [ ] **Step 4: Wire it into the host**

In `engine/host_loop.py`, call `system_loader.ensure_loaded(<the current player>)` once per tick immediately BEFORE `_reconcile_runtime_instances(...)` (find its per-tick call), guarded so a missing player is a no-op. In the mission-swap reset block (where `_sets.clear()` happens), call `system_loader.reset()`. In `tests/conftest.py`'s `_reset_leakable_engine_globals`, add a guarded `system_loader.reset()` beside the other resets.

- [ ] **Step 5: Run the tests, then the gate**

Run: `uv run pytest tests/unit/test_system_loader.py tests/unit/test_region_map_on_initialize.py -v` → all PASS. Then `scripts/check_tests.sh`. Missions that start in a mapped region now load 2-8 sets at start; if a mission/integration test fails because of the extra sets, report it with output — do not suppress the loader for that test.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/system_loader.py engine/host_loop.py tests/conftest.py tests/unit/test_system_loader.py
git commit -m "feat(systems): entering a system loads all its regions"
```

---

### Task 2: The celestial draw list is a pure function of the viewed frame

**Files:**
- Create: `engine/systems/celestial.py`
- Test: `tests/unit/test_celestial_draw_list.py`

**Interfaces:**
- Consumes: `frames.frame_of`, `frames.viewing_set`, `resolve` (`anchor_of`, and the map via a non-copying accessor — add `resolve.map_of(system) -> SystemMap` that returns the CACHED map from `_index()`; callers must treat it as read-only, stated in its docstring), `engine.systems.map.Body`.
- Produces:
  - `celestial.CelestialBody` — frozen dataclass `(key: tuple, name: str, model: str, radius_gu: float, position: tuple)`; `key = (system, owner_region or "", body name)`; `position` is in the VIEWED set's local coordinates.
  - `celestial.draw_list(view) -> tuple[CelestialBody, ...]` — for a mapped viewed set: every NON-STAR body of its system (planets and moons of every region), `position = body.position_gu − anchor(view)`; for an unmapped or None view: `()`. Pure: same input, same output; no module state.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_celestial_draw_list.py`:

```python
import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import celestial, resolve
from engine.systems import map as system_map
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()


def test_every_non_star_body_of_the_system_in_view_coordinates():
    ona1 = load_region("Ona", "Ona1")
    m = system_map.load("ona")
    a1 = resolve.anchor_of("Ona1")
    got = {b.name: b for b in celestial.draw_list(ona1)}
    want = [b for b in m.bodies if b.orbits is not None]
    assert sorted(got) == sorted(b.name for b in want)
    for b in want:
        assert got[b.name].position == pytest.approx(
            tuple(p - a for p, a in zip(b.position_gu, a1)))
        assert got[b.name].radius_gu == b.radius_gu


def test_the_star_is_not_in_the_draw_list():
    ona1 = load_region("Ona", "Ona1")
    assert "Ona" not in {b.name for b in celestial.draw_list(ona1)}


def test_the_same_view_gives_the_same_list():
    ona1 = load_region("Ona", "Ona1")
    assert celestial.draw_list(ona1) == celestial.draw_list(ona1)


def test_an_unmapped_view_draws_nothing_from_a_map():
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    assert celestial.draw_list(qb) == ()
    assert celestial.draw_list(None) == ()


def test_viewing_from_a_sibling_region_shifts_by_the_anchor_difference():
    ona1, ona2 = load_region("Ona", "Ona1"), load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    b1 = {b.key: b for b in celestial.draw_list(ona1)}
    b2 = {b.key: b for b in celestial.draw_list(ona2)}
    assert b1.keys() == b2.keys()
    for k in b1:
        assert b1[k].position == pytest.approx(
            tuple(p + (x2 - x1) for p, x1, x2 in zip(b2[k].position, a1, a2)))


def test_draw_list_keys_bodies_by_owner_region():
    """Review Focus 5: Geble3 and Geble4 both have a body named "Moon 1"."""
    g = load_region("Geble", "Geble3")
    keys = [b.key for b in celestial.draw_list(g) if b.name == "Moon 1"]
    assert len(keys) == len(set(keys)) >= 2


def test_map_of_returns_the_cached_map_without_copying():
    import copy
    calls = []
    real = copy.deepcopy
    copy.deepcopy = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        resolve.map_of("Ona")
    finally:
        copy.deepcopy = real
    assert calls == []
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/unit/test_celestial_draw_list.py -v` → ImportError.

- [ ] **Step 3: Implement**

`resolve.map_of(system)`: return the cached `SystemMap` for that system name from `_index()` (build a system→map dict inside `_index`'s cached tuple if needed — keep `_index`'s existing two return values working for every caller; grep). Docstring: read-only; mutating it poisons every later caller — use `for_set` if you need a copy.

`engine/systems/celestial.py`:

```python
"""What a star system looks like from the viewed set (spec §4).

A PURE function of the viewed set: every non-star body of its system, placed
in the viewed set's local coordinates (body.position_gu - anchor(view)). The
renderer diffs its instances against this list; there is no cache to supersede
and nothing to sweep -- the reference branch's two-source design died of that.
The star is not here: the viewed set's own Sun object already sits at the map
star (apply_map) and draws through the sun pass.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CelestialBody:
    key: tuple
    name: str
    model: str
    radius_gu: float
    position: tuple


def draw_list(view) -> tuple:
    from engine.systems import frames, resolve
    f = frames.frame_of(view)
    if f is None or f.key[0] != "system":
        return ()
    m = resolve.map_of(f.key[1])
    ax, ay, az = f.anchor_gu
    out = []
    for b in m.bodies:
        if b.orbits is None:
            continue
        x, y, z = b.position_gu
        out.append(CelestialBody(
            key=(m.system, b.owner_region or "", b.name),
            name=b.name, model=b.appearance.model,
            radius_gu=float(b.radius_gu),
            position=(x - ax, y - ay, z - az)))
    return tuple(out)
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_celestial_draw_list.py tests/unit/test_system_resolve.py tests/unit/test_system_frames.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/celestial.py engine/systems/resolve.py tests/unit/test_celestial_draw_list.py
git commit -m "feat(systems): the celestial draw list, a pure function of the viewed frame"
```

---

### Task 3: One render scope — the viewed frame

**Files:**
- Modify: `engine/host_loop.py` — `_live_sets` (→ the viewed set), `_iter_planets` / `realize_set_objects`' planet loop / `_MissionLoader._realize_session`'s planet section (skip planets of MAPPED sets), `_reconcile_runtime_instances` (ships from every set in the viewed frame), `_sync_instance_transforms` (non-player ships from sibling sets pushed in view coordinates; the player unbound from the store when its set is not the viewed set), `_aggregate_planets` call site (dust: map bodies too); `engine/audio/hum_allocator.py` (distance pre-filter)
- Test: `tests/host/test_render_scope_viewed_frame.py` (new)

**Interfaces:**
- Consumes: `frames.viewing_set()`, `frames.offset_between`, `frames.in_view`, `region_hooks.is_mapped`, `celestial.draw_list` (dust only here; drawing is Task 4).
- Produces:
  - `_live_sets()` returns `[frames.viewing_set()]` (or `[]`), so `_iter_suns` / `_aggregate_suns` draw exactly the viewed set's Sun — never a sibling's (they share the map star's system position; drawing more than one is a duplicate).
  - A mapped set's Planet objects are never realized (no instance in `session.planet_instances`); unmapped sets unchanged.
  - Ships: `_reconcile_runtime_instances` realizes and keeps ships from every set whose `offset_between(view, set)` is not None, and removes the rest. Culled by `SHIP_DRAW_DISTANCE_GU` from the camera eye (in view coordinates) — value derived in Step 3, stated with its derivation in a comment.
  - Every non-player ship's pushed world matrix uses its position in VIEW coordinates (`GetWorldLocation() + offset_between(view, ship_set)`), same interpolation as today. The player: store-bound when its set IS the viewed set (unchanged); otherwise pushed like any other ship with its offset.
  - Lens flares: the flare feed takes ONLY the viewed set (like suns). Every loaded region's Sun sits at the same map star, so feeding the whole viewed frame (Plan 2's rule) would draw one coincident flare per loaded region. Test: Ona1-3 loaded, view Ona1 -> exactly one flare.
  - Hum roster (`hum_allocator._roster`) pre-filtered by distance from the listener (drop ships beyond `engine_rumble.HUM_MAX_DISTANCE` in view coordinates) — Plan 2 carried minor.

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_render_scope_viewed_frame.py` (mirror the fake renderer and session setup of `tests/unit/test_realize_set.py` and `tests/unit/test_render_feeds_by_frame.py`):

```python
def test_mapped_set_planets_are_never_realized():
    <Ona1 via load_region; realize_set_objects(session, ona1, fake_renderer)>
    assert <no Planet from Ona1 in session.planet_instances>

def test_unmapped_set_planets_realize_as_today():
    <a plain set with a Planet; realize>
    assert <that Planet in session.planet_instances>

def test_ships_from_every_set_in_the_viewed_frame_are_realized():
    <Ona1 (player, viewed) and Ona2 each with a ship within SHIP_DRAW_DISTANCE_GU of the camera in view coords; a plain Starbase12 with a ship>
    <run _reconcile_runtime_instances>
    assert <Ona1 and Ona2 ships realized; Starbase12 ship not>

def test_a_sibling_ship_is_pushed_at_its_view_position():
    <Ona2 ship at local (0,0,0); view = Ona1; run _sync_instance_transforms>
    assert <its pushed matrix translation == frames.offset_between(ona1, ona2)>

def test_ships_beyond_the_draw_distance_are_not_realized():
    <an Ona2 ship far beyond SHIP_DRAW_DISTANCE_GU from the camera>
    assert <not realized>

def test_only_the_viewed_sets_sun_is_drawn():
    <Ona1, Ona2, Ona3 loaded; view Ona1>
    suns = host_loop._aggregate_suns()
    assert len(suns) == 1 and <it is Ona1's Sun, at the map star in Ona1 coords>

def test_a_sibling_region_cutscene_draws_one_consistent_scene():
    """Review Focus 4."""
    <player in Ona1; MakeRenderedSet("Ona2")>
    assert host_loop._live_sets() == [ona2]
    assert <the single sun is Ona2's> and <a player-ship render matrix is in Ona2 coordinates>

def test_hum_roster_drops_ships_beyond_audible_range():
    <viewed Ona1; a same-frame Ona2 ship 40,000 GU away; a local ship 10 GU away>
    assert <roster contains the local ship and not the far one>
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** the interface above. Derive `SHIP_DRAW_DISTANCE_GU` in its comment: exterior vertical FOV 35° over 1080 px ⇒ one pixel ≈ 5.66e-4 rad; a Galaxy (radius ≈ 3 GU — read the real figure from the Galaxy hardpoint/model extent and cite it) spans one pixel at ≈ 2·r / 5.66e-4 GU; choose the draw distance so the LARGEST ship class commonly present (read the largest non-station ship radius from the SDK hardpoints/model extents; cite it) is still ≥ 1 px at the cull, rounded up to a round number. State the resulting number and the ship it was derived from. Apply the cull to realization and removal (a ship crossing the line is realized/destroyed — hysteresis of 10% so a ship on the line does not thrash).

  Also route the dust feed through the map: `_aggregate_planets` receives, for a mapped viewed frame, the draw list's bodies (position + radius) instead of set Planet objects; unmapped frames unchanged.

- [ ] **Step 4: Run** the new file plus `tests/unit/test_realize_set.py tests/unit/test_render_feeds_by_frame.py tests/unit/test_active_set_render_scope.py tests/audio/test_hum_allocator.py tests/host -q`; then the gate. Existing tests that assumed mapped-set planets get instances: update them ONLY by choosing an unmapped set for what they test, never by weakening; list each.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py engine/audio/hum_allocator.py tests/host/test_render_scope_viewed_frame.py <each existing test file you updated>
git commit -m "feat(render): one render scope -- the viewed frame; mapped planets are map-drawn only"
```

---

### Task 4: Draw the map's bodies

**Files:**
- Modify: `engine/host_loop.py` — a per-tick `_reconcile_celestial_instances(session, renderer)` next to `_reconcile_runtime_instances`; `MissionSession` gains `celestial_instances: dict` (key → iid) and `celestial_placed: dict` (key → the CelestialBody last pushed); mission-swap and teardown clear them
- Test: `tests/host/test_celestial_instances.py` (new)

**Interfaces:**
- Consumes: `celestial.draw_list(frames.viewing_set())`, the existing planet realize helpers (`_planet_nif_path`-style model resolution by model path, `r_.load_model(path, planet_tex_search)`, `_model_sphere_radius_from_aabb`, the nif caches the realize path uses).
- Also produces (spec §4 "a script that moves or resizes a mapped body is logged loudly, not arbitrated"): `_check_mapped_bodies_untouched(view)` — for the viewed set if mapped, each of its own Planet objects is compared with its map body (set-local position = position_gu − anchor, radius) within 1e-3 GU; a mismatch prints ONE `[systems] mapped body moved by a script: <set>/<name> ...` line per body per mission (remembered in a module set cleared on mission swap) and changes nothing. Test: move a mapped planet with SetTranslateXYZ -> exactly one warning, draw list unchanged.
- Produces: every tick, the set of celestial instances equals the draw list: new keys → create instance (natural scale = `radius_gu / sphere_radius`), set its world matrix at `position` via `set_world_transform` (a static body, not store-bound); vanished keys → destroy instance; a key whose `position` changed (the view moved to a sibling region) → re-push its matrix. Idle cost: one tuple compare of the new list against `celestial_placed`.

- [ ] **Step 1: Write the failing tests** (fake renderer as in `tests/unit/test_realize_set.py`):

```python
def test_viewing_ona1_realizes_every_ona_body_at_its_view_position():
    <load Ona1-3; player in Ona1; run _reconcile_celestial_instances>
    assert <one instance per draw_list body; each matrix translation == body.position; scale == radius/sphere_radius>

def test_moving_the_view_to_a_sibling_repositions_without_recreating():
    <as above; then MakeRenderedSet("Ona2"); reconcile>
    assert <same instance ids>; assert <translations shifted by the anchor difference>

def test_leaving_the_system_destroys_its_bodies():
    <view moves to a plain unmapped set; reconcile>
    assert <every celestial instance destroyed; celestial_instances empty>

def test_an_idle_tick_touches_nothing():
    <reconcile twice with no change>
    assert <second call makes zero renderer calls>

def test_a_body_with_no_resolvable_model_is_skipped_loudly():
    <monkeypatch the model resolver to fail for one body>
    assert <others realized; one printed warning naming the body>
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** `_reconcile_celestial_instances` exactly as the interface says; call it once per tick right after `_reconcile_runtime_instances`; clear both dicts wherever `planet_instances` is cleared on mission swap/teardown. Resolve the model through the SAME code path the existing planet realize uses (texture search list, nif caches) — extract a shared helper if needed rather than copying.

- [ ] **Step 4: Run** the new file + Task 3's file + `tests/host tests/unit/test_realize_set.py -q`, then the gate.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_celestial_instances.py
git commit -m "feat(render): draw the system map's bodies, diffed against the viewed frame each tick"
```

---

### Task 5: System Preview, the sky round trip, the yardstick, and the spec

**Files:**
- Create: `engine/dev_missions/system_preview.py`, `tools/systems/yardstick.py`
- Modify: `engine/host_loop.py` (register "System Preview" in the Developer family, beside "Collision Sim"), `docs/superpowers/specs/2026-09-24-system-frames-design.md` (§5 deferral; §3-§4 status)
- Test: `tests/integration/test_sky_round_trip.py`, `tests/unit/test_dev_system_preview.py`

**Interfaces:**
- `system_preview.Initialize(pMission)`: loads the Galaxy bridge (as `collision_sim.py` does), `Systems.Ona.Ona1.Initialize()`, creates the player (Galaxy) at Ona1's "Player Start" with `MissionLib.CreatePlayerShip("Galaxy", pSet, "player", "Player Start")`. The system loader (Task 1) loads Ona2/Ona3 on the first tick. No other ships.
- `tools/systems/yardstick.py <System> <Region> [<Region> ...]`: loads the dev mission headlessly (or the named region + player at Player Start), and for each named region as the viewed set prints every draw-list body: name, bearing (port/starboard degrees and elevation relative to the player's heading), range to centre and surface (GU and km via `engine.units`), apparent size `2·asin(r/d)`; plus the sun from `_aggregate_suns()`. Plain text table.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_dev_system_preview.py`: the mission module imports; after running its Initialize through `tools.mission_harness.run_mission("engine.dev_missions.system_preview")` and one `system_loader.ensure_loaded(player)`, Ona1/Ona2/Ona3 exist and are mapped and the player is in Ona1 at Player Start; the Developer family registry contains a "System Preview" entry pointing at `engine.dev_missions.system_preview` (assert through the same registry function the picker uses).

`tests/integration/test_sky_round_trip.py` (Review Focus 3 — the reference branch's live bug as a test): with the preview mission loaded, drive a real warp (as `tests/unit/test_warp_leaves_the_set_standing.py` does, through `_WarpDepartAction` / `ChangeRenderedSetAction` / `_ArriveFinalizeAction`) Ona1 → tunnel → Ona2 → tunnel → Ona1. At each station, `celestial.draw_list(frames.viewing_set())` has exactly the Ona map's non-star bodies in that station's coordinates; in the tunnel it is `()`; and after each station `_reconcile_celestial_instances` leaves exactly one instance per draw-list key (no ghost, none missing).

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** the mission, its registration, and the yardstick tool. Keep the tool thin: it reuses `celestial.draw_list`, `frames`, `engine.units`.

- [ ] **Step 4: Record the spec change** in `docs/superpowers/specs/2026-09-24-system-frames-design.md`: under §5 add "Deferred to the moving-through-a-system plan (Plan 3 decision, approved by Mark <date of approval>)" with the evidence from this plan's "Proposed spec change" section; under §3 and §4 add a one-paragraph "Status (Plan 3)" each: what is built and the draw-distance figure with its derivation.

- [ ] **Step 5: Produce the yardstick for the live pass**

Run `uv run python tools/systems/yardstick.py Ona Ona1 Ona2` and paste the full output into the task report. This is what Mark flies against.

- [ ] **Step 6: Gate and commit**

Run `scripts/check_tests.sh` → `OK — no new failures.`

```bash
git add engine/dev_missions/system_preview.py tools/systems/yardstick.py engine/host_loop.py docs/superpowers/specs/2026-09-24-system-frames-design.md tests/integration/test_sky_round_trip.py tests/unit/test_dev_system_preview.py
git commit -m "feat(systems): System Preview dev mission, the sky round trip, and the live yardstick"
```

## After the last task

Mark flies: `--developer` → Load Mission → Developer → System Preview, with the Task 5 yardstick in hand. What must hold: Ona 2 and Ona 3 visible from Ona 1 at the yardstick's bearings and sizes; the star once, at its bearing; Set Course Ona 1 → Ona 2 → Ona 1 and every world still in the sky from each station (the reference branch's live bug); no body changes size or jumps when its region's set loads.
