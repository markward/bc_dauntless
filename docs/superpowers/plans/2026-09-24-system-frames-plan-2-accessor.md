# System Frames — Plan 2: The Accessor and the Unscoped Consumers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the engine ONE way to compare positions across sets — `engine/systems/frames.py` — and move every consumer that compared raw set-local positions with no set scope onto it, replacing Plan 1's interim `same_set` stopgap.

**Architecture:** A set belongs to a frame: its star system if it is a mapped region (anchor = the region's `anchor_gu`), otherwise its own one-set frame (anchor zero). Positions stay set-local everywhere BC can see them; the engine converts only when comparing, through one primitive, `offset_between(set_a, set_b)` = anchor(b) − anchor(a) (None across frames), which expresses b's set-local coordinates in a's. Same-set pairs get a zero offset and are byte-identical to today; different-frame pairs never interact; same-frame cross-region pairs become correct.

**Tech Stack:** Python 3 (engine), pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-system-frames-design.md` — §1 (frames and the accessor), §6 (converting consumers — order is a safety property). Plan 1 (`docs/superpowers/plans/2026-09-24-system-frames-plan-1-foundation.md`) is complete on this branch.

## Global Constraints

- Work only in the worktree `.claude/worktrees/system-frames` on branch `feat/system-frames`. Export `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"` and `DAUNTLESS_SDK_DIR="/Users/mward/Documents/Star Trek Bridge Commander/sdk"` in every shell (the worktree has no settings.json).
- **Banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Explicit pathspecs. Temporary mutation: `cp` to /tmp, edit, run, `cp` back, `diff` silent.
- **BC's surface is untouched** (spec §1): `GetWorldLocation`, `SetTranslate*`, `PlaceObjectByName`, `GetNearObjects`, `LineCollides`, `GetRelativePositionInfo` stay set-local. Only engine-side consumers convert.
- **The invariant every conversion is tested against** (spec §1): for two objects in the SAME set, a converted consumer produces exactly today's result.
- **Cross-frame comparisons are undefined, not zero**: objects in different frames never collide, splash, hit, home, score, or render into each other's scene. An object in no set has no frame and interacts with nothing.
- A set whose name resolves to a region but which `region_hooks.is_mapped()` says was never mapped (the alarm case) is its OWN frame — adding an anchor to BC-placed positions would be wrong.
- Nothing per-frame may go near `resolve.for_set`'s deep copy.
- Never spell `game`/`sdk` as a path segment in code; never capture a path at import. Spatial names are `*_gu`.
- The gate is `scripts/check_tests.sh`; never call a failure "pre-existing" by eyeball. Never launch the game.
- In test bodies, `<...>` stands for the named object built with the builders the cited existing test file already uses (read that file first); the ASSERTIONS are fixed and must be transcribed in meaning, never weakened.

## Review Focus

1. **An object in no set** (a debris chunk whose parent left its set, a test double, a transient during `_PlacePlayerAction`) must interact with nothing and never raise — in every converted consumer. → Task 7, `test_a_setless_object_interacts_with_nothing_anywhere`.
2. **A hand-built set named like a mapped region but never mapped** must be its own frame, so its BC-scale positions are not shifted by an anchor. → Task 1, `test_an_unmapped_set_with_a_region_name_is_its_own_frame`.
3. **A cutscene rendering a different set of the same system** (`MakeRenderedSet`) — render feeds must be expressed in THAT set's local coordinates, not the player's. → Task 5, `test_render_feeds_follow_the_explicit_rendered_set`.
4. **De-penetration of a cross-region pair** must write each object's position back in its OWN set's coordinates. → Task 2, `test_cross_region_depenetration_writes_each_set_local`.
5. **A torpedo whose shooter has died or left its set** must still resolve hits and homing through the torpedo's OWN set. → Task 4, `test_torpedo_resolves_through_its_own_set_after_its_source_leaves`.

---

### Task 1: `engine/systems/frames.py` — the accessor

**Files:**
- Create: `engine/systems/frames.py`
- Modify: `engine/systems/resolve.py` (`system_of` stops deep-copying)
- Create: `tests/helpers/mapped_regions.py`
- Test: `tests/unit/test_system_frames.py`

**Interfaces:**
- Consumes: `resolve._index()`, `resolve.anchor_of(set_name)`, `region_hooks.is_mapped(pSet)`, `App.g_kSetManager.get_explicit_rendered_set()`, `engine.appc.ship_iter.active_set()`.
- Produces (every later task uses these exact names):
  - `Frame` — NamedTuple `(key, anchor_gu)`; `key` is `("system", <system name>)` or `("set", <the SetClass object>)`.
  - `frame_of(pSet) -> Frame | None` — None for None or a non-set.
  - `frame_of_object(obj) -> Frame | None` — via `obj.GetContainingSet()` (probed with `engine.core.ids.implements`).
  - `same_frame(a, b) -> bool` — objects.
  - `offset_between(set_a, set_b) -> tuple | None` — `anchor(b) − anchor(a)`; add it to a point in b's set-local coords to express it in a's. None if either is None or the frames differ; `(0.0, 0.0, 0.0)` for the same set.
  - `local_in(set_a, obj) -> tuple | None` — obj's `GetWorldLocation()` expressed in set_a's local coordinates (None across frames).
  - `system_position(obj) -> tuple | None` — `(key, x, y, z)` (spec §1).
  - `system_distance(a, b) -> float` — `math.inf` across frames or when either has no frame.
  - `viewing_set() -> SetClass | None` — `get_explicit_rendered_set()` if set, else `active_set()`.
- `resolve.system_of(set_name)` keeps its signature and result but reads `_index()` directly.

- [ ] **Step 1: Write the region helper**

Create `tests/helpers/mapped_regions.py`:

```python
"""Create REAL, mapped region sets through BC's own region modules.

Plan 1 wraps every mapped Systems.<Sys>.<Region> Initialize() so the map is
applied as BC creates the set; importing the module fresh through the SDK
loader and calling Initialize() is therefore the honest way to get a set that
is mapped exactly as it would be in play.
"""
import importlib
import sys


def load_region(system: str, region: str):
    import App
    import tools.mission_harness as mh
    mh.setup_sdk()
    qual = f"Systems.{system}.{region}"
    sys.modules.pop(qual, None)
    importlib.import_module(qual).Initialize()
    pSet = App.g_kSetManager.GetSet(region)
    assert pSet is not None, f"{qual}.Initialize() registered no set {region!r}"
    return pSet
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_system_frames.py`:

```python
"""engine/systems/frames.py — the one accessor for comparing positions across sets."""
import math

import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import frames, resolve
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def _ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _plain_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def test_a_mapped_region_is_in_its_system_frame_at_its_anchor():
    ona1 = load_region("Ona", "Ona1")
    f = frames.frame_of(ona1)
    assert f.key == ("system", "Ona")
    assert f.anchor_gu == pytest.approx(resolve.anchor_of("Ona1"))


def test_an_unmapped_set_is_its_own_frame_with_zero_anchor():
    qb = _plain_set("QuickBattle")
    f = frames.frame_of(qb)
    assert f.key == ("set", qb)
    assert f.anchor_gu == (0.0, 0.0, 0.0)


def test_an_unmapped_set_with_a_region_name_is_its_own_frame():
    """Review Focus 2: a hand-built "Ona1" that no region module mapped holds
    BC-scale positions; shifting them by Ona1's anchor would be wrong."""
    raw = _plain_set("Ona1")
    assert frames.frame_of(raw).key == ("set", raw)
    assert frames.frame_of(raw).anchor_gu == (0.0, 0.0, 0.0)


def test_same_set_offset_is_zero():
    ona1 = load_region("Ona", "Ona1")
    assert frames.offset_between(ona1, ona1) == (0.0, 0.0, 0.0)


def test_two_regions_of_one_system_offset_by_their_anchor_difference():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    assert frames.offset_between(ona1, ona2) == pytest.approx(
        tuple(b - a for a, b in zip(a1, a2)))


def test_different_frames_have_no_offset():
    ona1 = load_region("Ona", "Ona1")
    qb = _plain_set("QuickBattle")
    assert frames.offset_between(ona1, qb) is None
    assert frames.offset_between(None, ona1) is None


def test_same_set_distance_equals_raw_distance():
    """The invariant: same-set pairs are byte-identical to raw positions."""
    ona1 = load_region("Ona", "Ona1")
    a = _ship(ona1, "a", (10.0, 20.0, 30.0))
    b = _ship(ona1, "b", (13.0, 24.0, 30.0))
    assert frames.system_distance(a, b) == 5.0
    assert frames.same_frame(a, b)


def test_cross_region_distance_uses_system_positions():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    # b sits at the SAME system position as a, expressed in Ona2's local frame.
    a = _ship(ona1, "a", (0.0, 0.0, 0.0))
    b = _ship(ona2, "b", tuple(x1 - x2 for x1, x2 in zip(a1, a2)))
    assert frames.system_distance(a, b) == pytest.approx(0.0, abs=1e-6)
    # Same local numbers in two regions are far apart in the system.
    c = _ship(ona2, "c", (0.0, 0.0, 0.0))
    assert frames.system_distance(a, c) == pytest.approx(math.dist(a1, a2))


def test_cross_frame_distance_is_infinite():
    ona1 = load_region("Ona", "Ona1")
    qb = _plain_set("QuickBattle")
    a = _ship(ona1, "a", (0.0, 0.0, 0.0))
    b = _ship(qb, "b", (0.0, 0.0, 0.0))
    assert frames.system_distance(a, b) == math.inf
    assert not frames.same_frame(a, b)


def test_setless_object_has_no_frame():
    loose = App.ShipClass_Create()
    ona1 = load_region("Ona", "Ona1")
    a = _ship(ona1, "a", (0.0, 0.0, 0.0))
    assert frames.frame_of_object(loose) is None
    assert frames.system_distance(a, loose) == math.inf
    assert not frames.same_frame(loose, loose)


def test_system_position_is_local_plus_anchor():
    ona2 = load_region("Ona", "Ona2")
    a = _ship(ona2, "a", (1.0, 2.0, 3.0))
    key, x, y, z = frames.system_position(a)
    ax, ay, az = resolve.anchor_of("Ona2")
    assert key == ("system", "Ona")
    assert (x, y, z) == pytest.approx((ax + 1.0, ay + 2.0, az + 3.0))


def test_local_in_expresses_an_object_in_another_sets_coordinates():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    b = _ship(ona2, "b", (5.0, 0.0, 0.0))
    off = frames.offset_between(ona1, ona2)
    assert frames.local_in(ona1, b) == pytest.approx((5.0 + off[0], off[1], off[2]))
    assert frames.local_in(_plain_set("QuickBattle"), b) is None


def test_viewing_set_prefers_the_explicit_rendered_set():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    App.g_kSetManager.MakeRenderedSet("Ona2")
    assert frames.viewing_set() is ona2


def test_system_of_does_not_deep_copy():
    """frames reads system_of per comparison; it must be an index lookup."""
    import copy
    calls = []
    real = copy.deepcopy
    copy.deepcopy = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        assert resolve.system_of("Ona1") == "Ona"
    finally:
        copy.deepcopy = real
    assert calls == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_system_frames.py -v`
Expected: collection ERROR — `ImportError: cannot import name 'frames'`.

- [ ] **Step 4: Fix `resolve.system_of`**

In `engine/systems/resolve.py` replace `system_of`'s body:

```python
def system_of(set_name: str) -> str | None:
    """The system's name for the set, or None.

    An index lookup, never for_set()'s deep copy: engine/systems/frames.py
    calls this for every frame resolution."""
    by_set, _ = _index()
    found = by_set.get(set_name)
    return found[0].system if found is not None else None
```

- [ ] **Step 5: Write `engine/systems/frames.py`**

```python
"""One way to compare positions across sets (system-frames spec §1).

A set belongs to exactly one FRAME. A mapped region (a set its region module
created, which apply_map marked) is in its star system's frame, anchored at
the region's anchor_gu. Every other set -- Starbase 12, a mission's own set,
the warp transit set, the bridge, QuickBattle, and a set that merely carries a
region's NAME but was never mapped -- is its own one-set frame with a zero
anchor.

Positions stay set-local everywhere BC can see them. Engine code converts only
when it compares, and the primitive is offset_between(set_a, set_b): add it to
a point in b's set-local coordinates to express that point in a's. Same set
-> zero, so same-set results are byte-identical to comparing raw numbers.
Different frames -> None: they never interact. An object in no set has no
frame and interacts with nothing.

No cache: anchor_of() is a dict lookup returning an immutable tuple, and a
set's frame can change exactly once, when the region hook marks it mapped
after BC's Initialize() -- a cache would have to know that; a lookup does not.
"""
from __future__ import annotations

import math
from typing import NamedTuple

_ZERO = (0.0, 0.0, 0.0)


class Frame(NamedTuple):
    key: tuple
    anchor_gu: tuple


def frame_of(pSet):
    from engine.appc.sets import SetClass
    if not isinstance(pSet, SetClass):
        return None
    from engine.systems import region_hooks, resolve
    if region_hooks.is_mapped(pSet):
        name = pSet.GetName()
        anchor = resolve.anchor_of(name)
        system = resolve.system_of(name)
        if anchor is not None and system is not None:
            return Frame(("system", system), tuple(float(c) for c in anchor))
    return Frame(("set", pSet), _ZERO)


def _containing_set(obj):
    from engine.core.ids import implements
    if obj is None or not implements(obj, "GetContainingSet"):
        return None
    return obj.GetContainingSet()


def frame_of_object(obj):
    return frame_of(_containing_set(obj))


def offset_between(set_a, set_b):
    fa, fb = frame_of(set_a), frame_of(set_b)
    if fa is None or fb is None or fa.key != fb.key:
        return None
    if set_a is set_b:
        return _ZERO
    return tuple(b - a for a, b in zip(fa.anchor_gu, fb.anchor_gu))


def _xyz(obj):
    p = obj.GetWorldLocation()
    return (p.x, p.y, p.z)


def local_in(set_a, obj):
    off = offset_between(set_a, _containing_set(obj))
    if off is None:
        return None
    x, y, z = _xyz(obj)
    return (x + off[0], y + off[1], z + off[2])


def same_frame(a, b) -> bool:
    return offset_between(_containing_set(a), _containing_set(b)) is not None


def system_position(obj):
    f = frame_of_object(obj)
    if f is None:
        return None
    x, y, z = _xyz(obj)
    return (f.key, x + f.anchor_gu[0], y + f.anchor_gu[1], z + f.anchor_gu[2])


def system_distance(a, b) -> float:
    pb = local_in(_containing_set(a), b)
    if pb is None:
        return math.inf
    return math.dist(_xyz(a), pb)


def viewing_set():
    import App
    s = App.g_kSetManager.get_explicit_rendered_set()
    if s is not None:
        return s
    from engine.appc.ship_iter import active_set
    return active_set()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_system_frames.py tests/unit/test_system_resolve.py -v`
Expected: all PASS. (If `App.ShipClass_Create()` objects need a transform-store slot to report `GetWorldLocation`, mirror how `tests/unit/test_cross_set_interaction_gate.py` builds ships — read it first; do not weaken an assertion.)

- [ ] **Step 7: Commit**

```bash
git add engine/systems/frames.py engine/systems/resolve.py tests/helpers/mapped_regions.py tests/unit/test_system_frames.py
git commit -m "feat(systems): frames.py -- one accessor for comparing positions across sets"
```

---

### Task 2: Collision pairing compares by frame

**Files:**
- Modify: `engine/appc/collisions.py` (`resolve_collisions` pair loop ~653-698; `_respond_pair` and everything it calls that reads or writes a body's position — `_deepest_piece_overlap` ~221-253, the de-penetration reads at ~495/499 and their writes)
- Test: `tests/unit/test_cross_set_interaction_gate.py` (collision cases), `tests/unit/test_collisions.py` (unchanged, must stay green)

**Interfaces:**
- Consumes: `frames.offset_between(set_a, set_b)`, `frames._containing_set` (use the public `obj.GetContainingSet()` via `engine.core.ids.implements` if you prefer not to import a private helper — either way ONE helper, not a copy).
- Produces: `_respond_pair(body_a, body_b, ship_instances, dt, b_offset=(0.0, 0.0, 0.0))` — `b_offset` is `offset_between(set_of(a), set_of(b))`; every read of body B's position inside the pair maths adds it (B expressed in A's set-local frame), and every write of B's position subtracts it back (B stored in B's own set-local frame). A's reads and writes are untouched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cross_set_interaction_gate.py` (reuse its existing ship/planet builders; add `from tests.helpers.mapped_regions import load_region`):

```python
def test_cross_region_pair_at_the_same_system_position_collides():
    """Two regions of ONE system share a frame: a ship in Ona2 placed at the
    system position of a ship in Ona1 collides with it."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)         # add to Ona2-local -> Ona1-local
    a = <ship of radius 50 in ona1 at (0, 0, 0)>
    b = <ship of radius 50 in ona2 at (-off[0] + 60, -off[1], -off[2])>  # 60 GU from a in the system
    hits = collisions.resolve_collisions([a, b])
    assert len(hits) == 1


def test_cross_region_pair_with_equal_local_numbers_does_not_collide():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a = <ship of radius 50 in ona1 at (0, 0, 0)>
    b = <ship of radius 50 in ona2 at (60, 0, 0)>    # near only numerically
    assert collisions.resolve_collisions([a, b]) == []


def test_cross_region_depenetration_writes_each_set_local():
    """Review Focus 4: after resolving an overlapping cross-region pair, each
    body's stored position is in its OWN set's coordinates -- b must not be
    written in a's frame."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)
    a = <ship r=50 in ona1 at (0, 0, 0)>
    b = <ship r=50 in ona2 at (-off[0] + 60, -off[1], -off[2])>
    collisions.resolve_collisions([a, b], dt=1.0 / 60.0)
    bx, by, bz = frames.local_in(ona1, b)
    # b was pushed AWAY from a along +x in the shared frame, and is still
    # within a few hundred GU of a -- not teleported by an anchor's worth.
    assert 60.0 <= bx < 400.0 and abs(by) < 1.0 and abs(bz) < 1.0
```

Replace each `<...>` with the file's existing builder (same radius and position semantics); assertions are fixed.

Also update the file's Plan-1 cross-SET tests so they express the new rule: cross-FRAME pairs never interact (keep `test_player_in_another_set_does_not_strike_a_left_behind_planet` with the left-behind set in a DIFFERENT frame — e.g. a plain `"Starbase12"`/`"XiEntrades4"`-style unmapped set, or two different systems' mapped regions), and a same-set pair behaves exactly as before.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cross_set_interaction_gate.py -v`
Expected: `test_cross_region_pair_at_the_same_system_position_collides` FAILS (the `same_set` gate rejects the pair); the others pass or fail per their assertions — record which.

- [ ] **Step 3: Gate by frame and thread the offset**

In `resolve_collisions`, replace the `same_set` gate:

```python
            a_set = a_obj.GetContainingSet() if implements(a_obj, "GetContainingSet") else None
            b_set = b_obj.GetContainingSet() if implements(b_obj, "GetContainingSet") else None
            # Different frames never interact; one frame (the same set, or two
            # regions of one system) compares in A's set-local coordinates.
            b_offset = frames.offset_between(a_set, b_set)
            if b_offset is None:
                continue
```

Build `bodies` so each body's `center` is its own set-local position (unchanged), and pass `b_offset` to `_respond_pair(bodies[i], bodies[k], ship_instances, dt, b_offset=b_offset)`. Inside `_respond_pair` and every helper it calls, find EVERY read of body B's (or `b.obj`'s) position — `b.center`, `b.obj.GetWorldLocation()`, `b.obj.GetTranslate()`, the argument passed as `obj_b.GetWorldLocation()` into `hull_spheres_near(obj_a, ...)` in `_deepest_piece_overlap`, and any ray-trace origin built from B — and add `b_offset`; find every write of B's position (de-penetration `SetTranslateXYZ` for B) and subtract `b_offset` before writing. Where a helper takes `obj_a` and `obj_b` symmetrically (e.g. `hull_spheres_near(obj_b, obj_a.GetWorldLocation(), ...)`), A's position expressed in B's frame is `a_pos − b_offset`. List every site you changed in the report. For a zero offset every expression must reduce to today's arithmetic exactly.

- [ ] **Step 4: Run collision suites**

Run: `uv run pytest tests/unit/test_cross_set_interaction_gate.py tests/unit/test_collisions.py tests/unit/test_collision_event.py tests/unit/test_debris_chunk.py tests/unit/test_ship_death_hulks.py tests/integration/test_collision_avoidance.py tests/integration/test_e1m1_dock_immobility.py -q`
Expected: all PASS.

- [ ] **Step 5: Prove it bites (mutation)** — set `b_offset = (0.0, 0.0, 0.0)` unconditionally after the None check (cp/restore/diff): `test_cross_region_pair_at_the_same_system_position_collides` and `..._depenetration_...` FAIL; restore.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_cross_set_interaction_gate.py
git commit -m "feat(collisions): pair by frame; a cross-region pair compares in one set's coordinates"
```

---

### Task 3: Splash damage and damage eligibility compare by frame

**Files:**
- Modify: `engine/appc/splash_damage.py` (`apply` ~26-56, `_impact_point` ~68-89), `engine/appc/damage_eligibility.py` (`select_eligible` ~39-64)
- Test: `tests/unit/test_cross_set_interaction_gate.py` (splash), `tests/unit/test_damage_eligibility.py`

**Interfaces:**
- Consumes: `frames.local_in(set_a, obj)`, `frames.system_distance(a, b)`.
- Produces: splash centre and each target compared in the TARGET's set-local frame (so `_impact_point`'s ray trace runs in the frame the target's hull lives in); eligibility proximity uses `system_distance` (cross-frame → `inf` → proximity term 0).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cross_set_interaction_gate.py`:

```python
def test_splash_reaches_a_ship_in_another_region_of_the_same_system():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)
    dying = <dying ship in ona1 at (0, 0, 0) with a splash radius covering 100 GU>
    victim = <ship in ona2 at (-off[0] + 50, -off[1], -off[2])>
    splash_damage.apply(dying)
    assert <victim took splash damage>


def test_splash_does_not_reach_a_ship_at_equal_local_numbers_in_another_region():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    dying = <dying ship in ona1 at (0, 0, 0)>
    victim = <ship in ona2 at (50, 0, 0)>
    splash_damage.apply(dying)
    assert <victim took no damage>
```

Use the existing splash test's builders and damage assertion (`test_splash_does_not_reach_a_ship_at_the_same_coords_in_another_set` shows how).

Append to `tests/unit/test_damage_eligibility.py`:

```python
def test_a_ship_in_another_frame_gets_no_proximity_credit():
    ona1 = load_region("Ona", "Ona1")
    qb = <plain unmapped set "QuickBattle">
    player = <ship in ona1 at (0,0,0)>
    near_same = <ship r=10 in ona1 at (100,0,0)>
    near_other = <ship r=10 in qb at (100,0,0)>
    chosen = damage_eligibility.select_eligible(player, [near_other, near_same], max_count=1)
    assert chosen == [near_same]   # adapt to select_eligible's actual return shape
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cross_set_interaction_gate.py -k splash tests/unit/test_damage_eligibility.py -v`
Expected: the cross-region splash test FAILS (same_set rejects it); the eligibility test FAILS if proximity is currently computed across frames (record the actual result).

- [ ] **Step 3: Implement**

`splash_damage.apply`: replace the `same_set` gate and the raw `centre` / `loc` arithmetic with a per-target conversion:

```python
    centre_set = ship.GetContainingSet() if implements(ship, "GetContainingSet") else None
    for target in list(iter_ships()):
        if target is ship:
            continue
        tgt_set = target.GetContainingSet() if implements(target, "GetContainingSet") else None
        # Express the blast centre in the TARGET's set-local frame: the hull,
        # the ray trace and the fallback point all live there. None = another
        # frame, which a blast never reaches.
        off = frames.offset_between(tgt_set, centre_set)
        if off is None:
            continue
        c = ship.GetWorldLocation()
        centre = TGPoint3(c.x + off[0], c.y + off[1], c.z + off[2])
        loc = target.GetWorldLocation()
        # ...existing distance, weight and _impact_point(target, centre, ...) code, unchanged
```

`_impact_point` needs no change: it already receives `centre` and reads the target's own position, both now in the target's frame. For a same-set pair `off` is `(0,0,0)` and every number is identical to today.

`damage_eligibility.select_eligible`: replace the proximity distance with `frames.system_distance(s, player)`; `1.0 / (1.0 + inf)` is `0.0`, so a cross-frame ship scores on size alone. Keep `_world_pos`/`_dist` only if something else uses them (grep); otherwise delete them.

- [ ] **Step 4: Run the suites**

Run: `uv run pytest tests/unit/test_cross_set_interaction_gate.py tests/unit/test_splash_damage.py tests/unit/test_warp_core_breach.py tests/unit/test_warp_core_breach_integration.py tests/unit/test_ship_death.py tests/unit/test_object_lifetime.py tests/unit/test_damage_eligibility.py tests/unit/test_hull_carve_emission.py tests/unit/test_decal_emission.py tests/unit/test_collision_hull_carve.py tests/unit/test_apply_hit_intensity.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/splash_damage.py engine/appc/damage_eligibility.py tests/unit/test_cross_set_interaction_gate.py tests/unit/test_damage_eligibility.py
git commit -m "feat(combat): splash and damage eligibility compare by frame"
```

---

### Task 4: Torpedoes hit, home and warn by frame

**Files:**
- Modify: `engine/appc/projectiles.py` (`update_all` ~420-596, `_guide` ~647-694, `_steer_point` ~621-644, `_closing_time` ~343-358, `incoming_ids` docstring ~406-417)
- Test: `tests/unit/test_cross_set_interaction_gate.py` (torpedo cases), `tests/unit/test_incoming_torps.py`

**Interfaces:**
- Consumes: `frames.offset_between`, `frames.local_in`.
- Produces: in `update_all`, each torpedo's segment (`prev_pos`, `cur_pos`) is tested against each ship in the SHIP's set-local frame (segment + `offset_between(ship_set, torp_set)`); `_guide`/`_steer_point` steer at the target expressed in the TORPEDO's set-local frame (`local_in(torp_set, target)` plus the existing target-local offset); `_closing_time(observer, torp)` uses the torpedo expressed in the observer's frame (None → not incoming). The torpedo's frame is always its OWN containing set (joined at launch), never its source's.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cross_set_interaction_gate.py` (mirror the existing torpedo tests' builders — `test_torpedo_does_hit_a_ship_at_its_coords_in_its_own_set` shows how a torpedo is launched into a set and advanced):

```python
def test_torpedo_hits_a_ship_in_another_region_at_its_system_position():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)
    <torpedo in ona1 at (0, 0, 0) moving +x fast enough to reach 40 GU this tick>
    target = <ship r=20 in ona2 at (-off[0] + 30, -off[1], -off[2])>
    hits = projectiles.update_all(1.0, [target])
    assert <target in hits>


def test_torpedo_homes_on_a_target_in_another_region_of_its_system():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)
    <torpedo in ona1 at (0, 0, 0) heading +y, targeting a ship in ona2 at (-off[0] + 500, -off[1], -off[2])>
    projectiles._guide(<torpedo>, 0.1)
    assert <torpedo's heading turned toward +x (its x-velocity grew)>


def test_torpedo_resolves_through_its_own_set_after_its_source_leaves():
    """Review Focus 5."""
    ona1 = load_region("Ona", "Ona1")
    <launch a torpedo from a shooter in ona1; then remove the shooter from ona1>
    target = <ship in ona1 in the torpedo's path>
    assert <update_all still reports the hit>
```

Append to `tests/unit/test_incoming_torps.py`:

```python
def test_a_torpedo_in_another_frame_is_never_incoming():
    <observer in a mapped Ona1; a torpedo in a plain "QuickBattle" set at the observer's numeric position, closing fast>
    assert projectiles.is_incoming(observer, torp, 100.0, None, False) is False
```

Replace `<...>` with the existing builders; assertions are fixed in meaning.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cross_set_interaction_gate.py -k torpedo tests/unit/test_incoming_torps.py -v`
Expected: the two cross-region tests FAIL (same_set rejects); the incoming test FAILS today (no gate).

- [ ] **Step 3: Implement**

`update_all`: cache each ship with its set and set-local position. For each torpedo, after the broadphase distance check (which must itself compare in one frame — compute `off = frames.offset_between(ship_set, torp_set)`; skip on None; broadphase on `prev_pos + off` vs the ship), express the segment in the ship's frame — `seg_prev = prev_pos + off`, `seg_cur = cur_pos + off` (as `TGPoint3`) — and pass those to `shield_bubble_entry` / `sphere_hit` / the hit-point resolution. Any hit point returned is in the ship's frame, which is what hit consumers expect (they act on the ship). The torpedo's own `SetTranslateXYZ(cur_pos...)` stays in its own frame. Delete the `same_set` gate.

`_guide`: replace the `same_set` gate with `off = frames.offset_between(torp_set, target_set)`; None → return (ballistic, as today). `_steer_point(torpedo, target)` returns the target's position plus its existing target-local offset, plus `off` (target expressed in the torpedo's frame). Where `_guide` reads `torpedo._last_seen_target_pos`, confirm that stored point was produced by `_steer_point` (so it is already in the torpedo's frame); if it is stored anywhere else in raw target coordinates, convert it there too.

`_closing_time(observer, torp)`: `p = frames.local_in(observer.GetContainingSet(), torp)`; None → return None (never incoming). Use `p` in place of the raw torpedo position; if it also reads the torpedo's velocity, velocity is a direction and needs no offset.

`incoming_ids` docstring: it claims torpedoes live in no set and that distance excludes distant sets; replace with: torpedoes join their source's set at launch (`_join_source_set`), and `_closing_time` returns None across frames, so a torpedo in another frame is never incoming.

- [ ] **Step 4: Run the projectile suites**

Run: `uv run pytest tests/unit/test_cross_set_interaction_gate.py tests/unit/test_torpedo_advance.py tests/unit/test_projectile_broadphase.py tests/unit/test_projectiles_hit_point_shape.py tests/unit/test_torpedo_decal_emission.py tests/unit/test_torpedo_shield_impact_vfx.py tests/unit/test_torpedo_guidance_fidelity.py tests/unit/test_torpedo_subsystem_homing.py tests/unit/test_ai_sensor_gate.py tests/unit/test_incoming_torps.py tests/unit/test_torpedo_set_membership.py tests/audio/test_torpedo_launch_positional.py -q`
Expected: all PASS.

- [ ] **Step 5: Prove it bites (mutation)** — force `off = (0.0, 0.0, 0.0)` in `update_all` (cp/restore/diff): the cross-region hit test FAILS; restore.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/projectiles.py tests/unit/test_cross_set_interaction_gate.py tests/unit/test_incoming_torps.py
git commit -m "feat(projectiles): torpedoes hit, home and warn by frame"
```

---

### Task 5: Render feeds are expressed in the viewed set's frame

**Files:**
- Modify: `engine/host_loop.py` — `_aggregate_planets` (~4327) and its call site (~10068), `_aggregate_lens_flares` (~4378) and `engine/appc/lens_flare.py:aggregate_lens_flares_for_renderer` (~53-73), `_build_torpedo_render_data` (~1187), `_build_dynamic_light_render_data` (~1233); `engine/appc/explosion_lights.py` (`_bear` ~180-214 and render data)
- Test: `tests/unit/test_render_feeds_by_frame.py` (new); existing: `tests/test_aggregate_planets.py`, `tests/integration/test_host_loop_lens_flares.py`, `tests/unit/test_lens_flare.py`, `tests/unit/test_torpedo_render_marshal.py`, `tests/unit/test_dynamic_light_render_marshal.py`, `tests/unit/test_dynamic_light_scope.py`, `tests/unit/test_explosion_lights.py`, `tests/unit/test_death_cascade_fireball.py`, `tests/unit/test_dynamic_light_camera_fade.py`

**Interfaces:**
- Consumes: `frames.viewing_set()`, `frames.offset_between(view, other)`.
- Produces: every feed below includes an item only if its set is in the viewing set's frame, and hands the renderer its position expressed in the viewing set's local coordinates (`local + offset_between(view, item_set)`). With no viewing set there is no scene, and every feed is empty. `_aggregate_planets(pSets)` and `aggregate_lens_flares_for_renderer(game_root, pSets)` gain a keyword `view=None`; when given, they filter and convert as above; the call sites pass `list(App.g_kSetManager._sets.values())` and `view=frames.viewing_set()`. Explosion light entries carry the SET they were born in (`"set"` key, never sent to the renderer) so render data can convert or drop them.

Note: Plan 3 replaces this with a double-precision render origin and map-drawn bodies (spec §4-§5). Until then the renderer draws in the viewed set's local coordinates, so these conversions are what makes a cross-region item appear where it is — and what keeps a left-behind set's torpedoes and explosions out of the scene you are in.

- [ ] **Step 0: Inventory every world-space feed to the renderer**

The five feeds named above are the ones already identified. Spec §6 also names hit VFX, and combat in a LEFT-BEHIND set (off-screen NPCs still fight) pushes its effects in that set's raw coordinates. Before writing tests, grep `engine/host_loop.py` and `engine/appc/` for every call that hands the renderer a WORLD-SPACE position each frame or per event — at least: `_build_phaser_beam_render_data`, `_build_tractor_beam_render_data`, shield-impact / splash VFX, shockwaves, particle emitters and bursts, hull-hit smoke, debris-chunk render transforms, and anything else passing a position through `host_io`/the renderer. Write the list into the report with, for each: its source set, and whether it is (i) converted in this task, (ii) already render-scoped (e.g. iterates `ship_instances`, which only holds the viewed set's realized objects — say how you checked), or (iii) instance-attached and resolved in C++ through the instance's own transform (no conversion needed). Every item in (i) gets a test in Step 1 of the same three-case shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_render_feeds_by_frame.py` with one test per feed, each asserting three things with objects placed in (a) the viewed set, (b) another region of the same system, (c) an unmapped set in another frame:
- (a) appears at exactly its raw position (the same-set invariant),
- (b) appears at `local + offset_between(view, its set)`,
- (c) does not appear.

Feeds: `_aggregate_planets(..., view=...)`, `aggregate_lens_flares_for_renderer(..., view=...)` (build flares the way `tests/unit/test_lens_flare.py` does), `_build_torpedo_render_data()` and `_build_dynamic_light_render_data()` (torpedoes registered as `tests/unit/test_torpedo_render_marshal.py` does, with `App.g_kSetManager.MakeRenderedSet(<view name>)`), and `_build_explosion_light_render_data()` (explosions born via `explosion_lights` the way `tests/unit/test_explosion_lights.py` does).

Plus (Review Focus 3):

```python
def test_render_feeds_follow_the_explicit_rendered_set():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    <player ship in ona1; a torpedo in ona1 at (0, 0, 0)>
    App.g_kSetManager.MakeRenderedSet("Ona2")      # a cutscene looking at Ona2
    off = frames.offset_between(ona2, ona1)
    (entry,) = host_loop._build_torpedo_render_data()
    assert entry["position"] == pytest.approx(off)  # expressed in Ona2's frame
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_render_feeds_by_frame.py -v`
Expected: FAIL — `view` is not a keyword yet / items from other frames are present / positions are raw.

- [ ] **Step 3: Implement**

A single small helper in `engine/host_loop.py` next to the feeds, used by all of them:

```python
def _in_view(view, pSet, x, y, z):
    """(x, y, z) of a point in pSet's frame, expressed in the viewed set's
    local coordinates -- or None when pSet is not in the viewed frame (a
    left-behind set, another system) or nothing is viewed. Same set: the
    point unchanged, so the renderer sees exactly today's numbers."""
    off = frames.offset_between(view, pSet)
    if off is None:
        return None
    return (x + off[0], y + off[1], z + off[2])
```

Apply it in each feed (the torpedo's set is `t.GetContainingSet()`; a planet's and a flare source's is the set being iterated; an explosion light's is the `"set"` captured in `_bear` from `ship.GetContainingSet()`). `_camera_distance_fade(pos)` must receive the CONVERTED position (it compares with the camera eye, which is in the viewed set's frame). Strip the `"set"` key from explosion entries before they reach the renderer. `lens_flare.aggregate_lens_flares_for_renderer` gets the same conversion via a `view` keyword (import `frames` there; keep the helper's logic in ONE place — call `host_loop._in_view` from lens_flare only if that creates no import cycle; otherwise move `_in_view` into `engine/systems/frames.py` as `frames.in_view(view, pSet, x, y, z)` and use it from both).

- [ ] **Step 4: Run the render-feed suites**

Run: `uv run pytest tests/unit/test_render_feeds_by_frame.py tests/test_aggregate_planets.py tests/integration/test_host_loop_lens_flares.py tests/unit/test_lens_flare.py tests/unit/test_torpedo_render_marshal.py tests/unit/test_dynamic_light_render_marshal.py tests/unit/test_dynamic_light_scope.py tests/unit/test_explosion_lights.py tests/unit/test_death_cascade_fireball.py tests/unit/test_dynamic_light_camera_fade.py tests/unit/test_active_set_render_scope.py tests/test_host_loop_emitter_lights.py -q`
Expected: all PASS. Existing tests that relied on feeds including objects from every set must be updated only by placing their objects in the viewed set (bind a viewed set) — never by weakening an assertion; list each such edit in the report.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py engine/appc/lens_flare.py engine/appc/explosion_lights.py tests/unit/test_render_feeds_by_frame.py
git add <each existing test file you updated>
git commit -m "feat(render): render feeds carry only the viewed frame, in the viewed set's coordinates"
```

---

### Task 6: Positional audio belongs to the emitter's frame

**Files:**
- Modify: `engine/audio/scene_scope.py`, `engine/audio/tg_sound.py` (`Play` ~175-223), `engine/audio/attached_sources.py` (`node_world_position` ~42, `pump` ~103), `engine/host_loop.py` (`tick_audio` ~230)
- Test: `tests/audio/test_scene_scope.py`, `tests/audio/test_audio_frames.py` (new)

**Interfaces:**
- Consumes: `frames.frame_of`, `frames.viewing_set`, `frames.offset_between`.
- Produces:
  - `scene_scope.set_active_frame(key)` replaces `set_rendered_set(name)`: every registered source whose frame key differs is stopped (today's semantics, keyed by frame instead of set name).
  - `scene_scope.register(handle, key)` — key is a `Frame.key`.
  - `scene_scope.active_frame()` replaces `rendered_set()`.
  - `tg_sound.Play` registers a sound under the frame of the EMITTER's set (the attach node's containing set) when there is one; a sound with only an explicit position and no node keeps today's rule and registers under the active frame.
  - `attached_sources.node_world_position(node)` returns the node's position expressed in the VIEWING set's local coordinates (`frames.local_in(frames.viewing_set(), node)`), or None when the node is in another frame (the source is then silent/stopped rather than playing at wrong coordinates).
  - `tick_audio` calls `scene_scope.set_active_frame(frames.frame_of(frames.viewing_set()).key if ... else None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/audio/test_audio_frames.py` (mirror `tests/audio/test_scene_scope.py`'s fake audio backend and handle builders):

```python
def test_a_sound_is_tagged_with_its_emitters_frame_not_the_players():
    """spec §6 / the Plan-1 carried bug: an NPC in a left-behind set that
    fires after the player warps out must not register under the player's
    scene."""
    <player in plain set "Starbase12" (viewed); NPC ship in mapped Ona1>
    <play a positional TGSound attached to the NPC>
    assert <its registered key is frames.frame_of(ona1).key>
    <tick_audio / set_active_frame(Starbase12's key)>
    assert <the NPC's sound was stopped>


def test_a_sound_in_another_region_of_the_same_system_keeps_playing_at_the_right_place():
    <player in Ona1 (viewed); emitter ship in Ona2 at local (0,0,0)>
    <play attached sound; pump>
    assert <it is still playing> and <the position handed to the backend == frames.offset_between(ona1, ona2)>


def test_same_set_sound_position_is_unchanged():
    <player and emitter in Ona1; emitter at local (10, 20, 30)>
    assert <position handed to the backend == (10, 20, 30)>
```

Replace `<...>` with the existing test's fakes; assertions are fixed in meaning.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/audio/test_audio_frames.py -v`
Expected: FAIL (sounds are tagged with the rendered set name; positions are raw).

- [ ] **Step 3: Implement** the interface above. Rename call sites of `set_rendered_set`/`rendered_set` (grep engine/ and tests/); keep the stop-on-change semantics and the reaping of dead handles exactly as they are. Update `register`'s "Known proxy" docstring note — it is no longer a proxy.

- [ ] **Step 4: Run the audio suites**

Run: `uv run pytest tests/audio -q`
Expected: all PASS; update existing scene_scope tests for the renamed API without weakening assertions.

- [ ] **Step 5: Commit**

```bash
git add engine/audio/scene_scope.py engine/audio/tg_sound.py engine/audio/attached_sources.py engine/host_loop.py tests/audio/test_audio_frames.py tests/audio/test_scene_scope.py
git add <other updated audio tests>
git commit -m "feat(audio): a positional sound belongs to its emitter's frame"
```

---

### Task 7: Retire the stopgap; the tripwire

**Files:**
- Modify: `engine/appc/ship_iter.py` (delete `same_set`), `tests/helpers/one_set.py` (keep — objects in one set are in one frame; update its docstring to cite frames, not `same_set`)
- Create: `tests/integration/test_frame_tripwire.py`
- Modify: `docs/superpowers/specs/2026-09-24-system-frames-design.md` (§6: record which consumers are converted, and that the Plan-1 same_set stopgap is retired)

**Interfaces:**
- Consumes: everything above.
- Produces: no `same_set` anywhere (`grep -rn "same_set" engine/ tests/` returns nothing but historical prose in docs).

- [ ] **Step 1: Write the tripwire**

Create `tests/integration/test_frame_tripwire.py` — the spec §6 gate. Setup: `load_region("Ona", "Ona1")`, `"Ona2"`, `"Ona3"`, plus `load_region("XiEntrades", "XiEntrades4")` (another system — the final review's measured scenario: XiEntrades4's arrival point lies inside Ona 1's set-local sphere), plus a plain unmapped `"Starbase12"`. Place a ship in each at local `(0, 5236, 1.5)` (XiEntrades4's arrival point) and a small planet/ship where each region's mapped body is.

Assert, for each converted consumer:
- `collisions.resolve_collisions(list(collisions.iter_collidables()))` pairs nothing across frames (no hit involves two objects whose frame keys differ), and the XiEntrades4 ship is not hit by Ona 1's planet;
- `splash_damage.apply(<a dying ship in Ona1>)` touches no ship outside the Ona frame;
- `projectiles.update_all` with a torpedo in Ona1 at the XiEntrades4 ship's local numbers hits nothing outside Ona;
- `damage_eligibility.select_eligible(<player in XiEntrades4>, all ships)` never ranks a cross-frame ship above a same-frame ship of equal size;
- `_aggregate_planets(all sets, view=<XiEntrades4>)`, `_build_torpedo_render_data()`, explosion lights and lens flares with XiEntrades4 viewed contain nothing from Ona or Starbase12;
- a positional sound attached to an Ona1 ship registers under the Ona frame and is stopped when the active frame is XiEntrades4's.

Plus (Review Focus 1):

```python
def test_a_setless_object_interacts_with_nothing_anywhere():
    loose = <ship created but added to no set, at (0, 5236, 1.5)>
    <include it in resolve_collisions' input, update_all's ships, select_eligible's ships>
    assert <no hit, no splash, no torpedo hit involves it> and <select_eligible does not raise>
```

- [ ] **Step 2: Run it** — `uv run pytest tests/integration/test_frame_tripwire.py -v` → PASS (Tasks 2-6 already converted everything). If anything fails, that consumer's conversion is incomplete: fix it in the consumer, never in the tripwire.

- [ ] **Step 3: Delete `same_set`** from `engine/appc/ship_iter.py`; `grep -rn "same_set" engine/ tests/` must return nothing (update `tests/unit/test_cross_set_interaction_gate.py`'s `test_same_set_is_identity_of_containing_set` into the frame equivalent, or delete it if `tests/unit/test_system_frames.py` already covers it — say which).

- [ ] **Step 4: Prove the tripwire bites** — temporarily make `frames.offset_between` return `(0.0, 0.0, 0.0)` for ANY two non-None sets (cp/restore/diff): the tripwire FAILS on collisions (XiEntrades4 ship struck by Ona 1's planet) and at least one render feed; restore.

- [ ] **Step 5: Record it in the spec** — in §6 under the consumer table, add a short "Status (Plan 2)" paragraph: collision, splash, torpedoes, damage eligibility, dust, lens flares, torpedo/explosion lights and render data, and audio now compare through `engine/systems/frames.py`; the Plan-1 `same_set` stopgap is retired; the set-scoped widening list (perception, avoidance, AI conditions, weapon range gates, target list, camera modes) remains.

- [ ] **Step 6: Gate and commit**

Run: `scripts/check_tests.sh` → `OK — no new failures.`

```bash
git add engine/appc/ship_iter.py tests/helpers/one_set.py tests/integration/test_frame_tripwire.py docs/superpowers/specs/2026-09-24-system-frames-design.md tests/unit/test_cross_set_interaction_gate.py
git commit -m "feat(systems): retire the same_set stopgap; the frame tripwire guards every converted consumer"
```
