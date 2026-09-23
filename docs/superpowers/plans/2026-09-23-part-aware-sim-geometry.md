# Part-Aware Sim Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the simulation agree with the renderer about where a ship's
articulated parts are — so a severed Bird of Prey wing stops colliding, stops
emitting, and a hit on a raised wing carves the wing rather than the hull
beneath it.

**Architecture:** Every baked structure stays whole-hull and rest-pose, shared
across instances exactly as today. Only the QUERY moves. Collision pieces gain
a part tag at cache time and are dropped (severed) or transformed (mid-travel)
at read time; a carve deposit landing on a moved node is pulled back into that
node's rest frame before it reaches the field. Nothing is re-baked and no
per-part structure is created.

**Tech Stack:** Python 3 (`engine/appc/`), C++20 + glm (`native/src/renderer/`,
`native/src/host/`), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`
(§4.3 "Consuming the part frame", §5 severance). ⚠️ Read §4.3.1 together with
Task 5 of this plan, which CORRECTS it.

## Global Constraints

- **Shared checkout — destructive git is BANNED.** Read the "Shared checkout"
  section of `CLAUDE.md` and obey it exactly: never restore the working tree
  from the index or HEAD, never stash, never clean, never hard-reset, and
  never stage with a wildcard. Stage with explicit pathspecs only. To mutate a
  file temporarily, `cp` it to the scratchpad, mutate, restore by `cp`, and
  `diff` to prove the restore is byte-identical.
- **NEVER launch the game** (`./build/dauntless`). Mark does live verification.
- **Build only from `<project-root>/build/`**: `cmake -B build -S . && cmake --build build -j`.
  Never run `cmake` inside `native/`.
- **Test gate is `scripts/check_tests.sh`**, not `scripts/run_tests.sh` (which
  cannot see C++ regressions). Baseline is exactly one pytest failure —
  `cat tests/known_failures.txt`, never a remembered count.
- **Units.** `MODEL_TO_SHIP = 0.01` (= `host_loop.BC_MODEL_SCALE`). Hardpoints,
  `PART_BOXES` and `part_for_point` are SHIP units; `world_to_body` and NIF
  data are MODEL units. Multiply model→ship. This exact confusion shipped a
  dead feature once (`test_record_hit_takes_MODEL_units_not_ship_units`).
- **Rotation is column-vector, right-handed**: `v_world = R · v_body`,
  world-forward is `GetCol(1)`, never `GetRow(1)`.
- **Never spell `game` or `sdk` as a path segment.** Use `engine/paths.py`.
- **`mutable` model state is shared across instances.** Never pose a baked
  structure per instance; transform the query instead.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `engine/appc/hull_bounds.py` | per-piece collision spheres, cache + read | cached tuple gains a part tag; readers drop detached pieces and transform moved ones |
| `engine/appc/particles.py` | particle controller registry | add `is_emitting()` accessor and `active()` registry reader |
| `engine/appc/part_severance.py` | attribution, accumulation, severance | on sever, silence particle controllers emitting from the part |
| `native/src/renderer/include/renderer/part_frame.h` | **new** — pure geometry: which overridden node holds a body point, and its rest frame | created |
| `native/src/renderer/part_frame.cc` | implementation of the above | created |
| `native/src/host/host_bindings.cc` | `hull_carve_add` binding | pull the body point/normal back to rest |
| `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md` | design record | §4.3.1 corrected; hull-volume and glow rows replaced |

---

### Task 1: Collision pieces carry a part tag, and a severed part's pieces vanish

A Bird of Prey that has lost a wing still collides with that wing today. The
pieces are cached body-frame spheres with no notion of which part they belong
to, so nothing can remove them.

**Files:**
- Modify: `engine/appc/hull_bounds.py:51-70` (`cache_hull_bound_spheres`),
  `:87-107` (`hull_spheres_world`), `:110-152` (`hull_spheres_near`),
  `:172-200` (`bound_radius`)
- Test: `tests/unit/test_hull_bounds_parts.py` (create)

**Interfaces:**
- Consumes: `articulation.leaf_for(ship) -> str`,
  `part_severance.part_for_point(leaf, point_ship_units) -> str | None`,
  `part_severance.is_detached(ship, part_name) -> bool`
- Produces: the cached tuple shape becomes
  `((cx, cy, cz), radius, part_name_or_None)` — a 3-tuple per piece, ship
  units, stored under `ship.__dict__["_hull_bound_spheres"]`. Task 3 reads the
  same shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_hull_bounds_parts.py`:

```python
"""Collision pieces know which articulated part they sit on.

A severed Bird of Prey wing is hidden by the renderer (a zero node override
collapses its subtree) but the SIM had no way to know, so the wing kept
colliding and kept absorbing narrow-phase hits from empty space.
"""
import pytest

from engine.appc import hull_bounds as hb
from engine.appc import part_severance as ps


class _Ship:
    """Minimal stand-in: hull_bounds only reads __dict__, the leaf and the
    world transform. A real ShipClass satisfies all three. Identity world
    transform, so body frame == world frame and a test can assert on
    hull_spheres_world without unwinding a rotation."""

    def __init__(self):
        self._articulation_leaf = "birdofprey"
        self._articulation_deflection = 0.0

    def GetArticulationDeflection(self):
        return self._articulation_deflection

    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        return TGMatrix3()

    def GetScale(self):
        return 1.0


def _nif(spheres):
    """Undo cache_hull_bound_spheres' NIF->ship factor, so a test can state
    the sphere it wants in SHIP units and have it survive the round trip."""
    from engine.host_loop import BC_MODEL_SCALE
    inv = 1.0 / BC_MODEL_SCALE
    return [(cx * inv, cy * inv, cz * inv, r * inv) for cx, cy, cz, r in spheres]


# A point deep inside PART_BOXES["birdofprey"]["left wing"] and inside no
# other box, so part_for_point attributes it outright rather than to None.
WING_PT = (-0.80, -0.20, -0.30)
# The body box's centre region: overlapped by the wing boxes by design, so
# part_for_point returns None here. That is the safe, common answer.
BODY_PT = (0.0, -0.20, 0.05)


def test_the_fixture_points_attribute_as_this_file_assumes():
    """Guards every other test in this file. If PART_BOXES is ever re-authored
    these two constants stop meaning what the tests below need them to mean,
    and those tests would pass vacuously instead of failing here."""
    assert ps.part_for_point("birdofprey", WING_PT) == "left wing"
    assert ps.part_for_point("birdofprey", BODY_PT) is None


def test_a_wing_piece_is_tagged_with_its_part():
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part == "left wing"


def test_a_body_piece_is_tagged_None():
    """Unattributed is the safe answer and must stay the common one: a piece
    with no part behaves exactly as it did before this change."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*BODY_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part is None


def test_a_severed_parts_pieces_leave_hull_spheres_world(monkeypatch):
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05), (*BODY_PT, 0.05)]))
    assert len(hb.hull_spheres_world(ship)) == 2
    monkeypatch.setattr(ps, "is_detached", lambda s, name: name == "left wing")
    assert len(hb.hull_spheres_world(ship)) == 1, (
        "the severed wing's piece must stop colliding")


def test_a_severed_parts_pieces_leave_hull_spheres_near(monkeypatch):
    """hull_spheres_near is the one collisions.py and collision_avoidance.py
    actually call, and it has its own body-frame fast path — so it needs its
    own assertion, not the world variant's."""
    from engine.appc.math import TGPoint3
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05), (*BODY_PT, 0.05)]))
    here = TGPoint3(0.0, 0.0, 0.0)
    assert len(hb.hull_spheres_near(ship, here, 10.0)) == 2
    monkeypatch.setattr(ps, "is_detached", lambda s, name: name == "left wing")
    assert len(hb.hull_spheres_near(ship, here, 10.0)) == 1


def test_bound_radius_still_counts_a_severed_part(monkeypatch):
    """DELIBERATE. bound_radius is a gate that must ENCLOSE the pieces before
    a caller expands into them; over-stating it is safe, under-stating it
    lets a ship fly through geometry. Shrinking it on severance would also
    mean invalidating its memo on every detach. Left conservative on purpose
    — do not "fix" this."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    before = hb.bound_radius(ship)
    assert before > 0.0
    monkeypatch.setattr(ps, "is_detached", lambda s, name: True)
    assert hb.bound_radius(ship) == pytest.approx(before)


def test_an_unrigged_ship_tags_nothing():
    """The overwhelming majority of hulls. A ship with no rig must take
    exactly the path it took before parts existed."""
    ship = _Ship()
    ship._articulation_leaf = ""
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_hull_bounds_parts.py -v`

Expected: the two tagging tests and `test_an_unrigged_ship_tags_nothing` FAIL
with `ValueError: not enough values to unpack (expected 3, got 2)`. The two
severance tests FAIL on the second assertion (count stays 2 — nothing filters).
`test_the_fixture_points_attribute_as_this_file_assumes` and
`test_bound_radius_still_counts_a_severed_part` PASS already; that is correct,
they are guards, not drivers.

- [ ] **Step 3: Tag the pieces at cache time**

In `engine/appc/hull_bounds.py`, replace the body of
`cache_hull_bound_spheres` (below its docstring) with:

```python
    from engine.host_loop import BC_MODEL_SCALE
    from engine.appc import articulation
    from engine.appc.part_severance import part_for_point
    s = BC_MODEL_SCALE
    # Attribution is computed ONCE here, never per tick: the pieces and the
    # part boxes are both rest-pose and neither ever changes after load.
    leaf = articulation.leaf_for(ship)
    out = []
    for cx, cy, cz, r in spheres:
        if r <= 0.0:
            continue
        c = (cx * s, cy * s, cz * s)
        out.append((c, r * s, part_for_point(leaf, c) if leaf else None))
    ship.__dict__[_ATTR] = tuple(out)
    ship.__dict__.pop(_BOUND_R_ATTR, None)
```

Append to that function's docstring:

```
    Each piece is tagged with the articulated part its CENTRE falls on, or
    None. `part_for_point` returns None wherever the part boxes overlap —
    which is most of the hull by design, since a BoP's wing boxes swallow the
    body box at the roots — so the tag is a minority case, and None keeps the
    piece behaving exactly as it did before parts existed.
```

- [ ] **Step 4: Drop detached pieces in every reader**

In `hull_spheres_world`, replace the loop header:

```python
    from engine.appc.part_severance import is_detached
    out = []
    for (cx, cy, cz), r, part in cached:
        if part is not None and is_detached(ship, part):
            continue                           # severed: no longer collides
        v = TGPoint3(cx * scale, cy * scale, cz * scale)
```

In `hull_spheres_near`, the same guard, placed BEFORE the distance compare so
a severed piece costs nothing:

```python
    from engine.appc.part_severance import is_detached
    out = []
    for (cx, cy, cz), r, part in cached:
        if part is not None and is_detached(ship, part):
            continue                           # severed: no longer collides
        # Body-frame piece centre at the ship's live scale.
        sx, sy, sz = cx * scale, cy * scale, cz * scale
```

In `bound_radius`, unpack the new shape without acting on it:

```python
        for (cx, cy, cz), r, _part in cached:
```

and append to `bound_radius`'s docstring:

```
    Counts a SEVERED part's pieces too. This is a gate that must enclose
    whatever it gates, so over-stating it is safe and under-stating it is
    not; shrinking it on severance would also mean invalidating this memo on
    every detach. Pinned by tests/unit/test_hull_bounds_parts.py::
    test_bound_radius_still_counts_a_severed_part.
```

- [ ] **Step 5: Run the new tests and the existing hull-bounds suite**

Run: `uv run pytest tests/unit/test_hull_bounds_parts.py tests/unit/test_hull_bounds_recache.py -v`

Expected: PASS. `test_hull_bounds_recache.py` builds its spheres through
`cache_hull_bound_spheres`, so it exercises the new shape end to end.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`

Expected: `OK — no new failures. 1 known failure(s) still baselined.`
If any other test or caller unpacks `_hull_bound_spheres` as a 2-tuple, fix it
here — the shape change is this task's responsibility. Find them with
`grep -rn "_hull_bound_spheres" engine tests`.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/hull_bounds.py tests/unit/test_hull_bounds_parts.py
git commit -m "feat(collision): a severed part's hull pieces stop colliding

Collision spheres are tagged with their articulated part once at cache
time, and readers skip a detached part's pieces. A Bird of Prey that has
lost a wing no longer collides with it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Anything emitting from a detached part goes dark

`part_severance.sever` already conditions every subsystem on the part to zero,
and emitter LIGHTS are health-gated (`light_emitters.resolve_emitter_intensity`
returns None for DESTROYED), so cast light already dies with the wing. Nothing
pins that, and particle controllers have no such gate — a controller emitting
from a subsystem on a severed wing keeps streaming from a wing that is gone.

**Files:**
- Modify: `engine/appc/particles.py:131` (`stop_emitting`, add `is_emitting`
  beside it), `:171` (`active_count`, add `active` beside it)
- Modify: `engine/appc/part_severance.py:211-235` (`sever`), `:237-265`
  (`_destroy_subsystems_on_part`)
- Test: `tests/unit/test_part_severance_emitters.py` (create)

**Interfaces:**
- Consumes: `particles.AnimTSParticleController_Create()`,
  `particles.register(controller)`, `particles.reset()`,
  `controller.SetEmitFromObject(obj)`, `controller.stop_emitting()`
- Produces:
  - `particles.active() -> list` — the live controller registry.
  - `AnimTSParticleController.is_emitting() -> bool`.
  - `part_severance._destroy_subsystems_on_part(ship, part_name) -> list` —
    now returns the subsystem objects it destroyed.
  - `part_severance._silence_emitters_on(killed) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_part_severance_emitters.py`:

```python
"""Nothing keeps emitting from a part that has physically left the ship.

Cast LIGHT already dies, because emitter intensity is gated on the parent
subsystem's condition and severance zeroes it. Particles had no such gate:
a controller emitting from a wing cannon kept streaming from a wing that
was no longer attached.
"""
from engine.appc import part_severance as ps
from engine.appc import particles


class _Sub:
    def __init__(self, name, pos):
        self._name = name
        self._pos = pos
        self.condition = 100.0

    def GetName(self):
        return self._name

    def GetPosition(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(*self._pos)

    def SetCondition(self, c):
        self.condition = float(c)

    def GetCondition(self):
        return self.condition

    def GetMaxCondition(self):
        return 100.0


class _Ship:
    def __init__(self, subs):
        self._articulation_leaf = "birdofprey"
        self._articulation_deflection = 0.0
        self._subs = list(subs)

    def GetArticulationDeflection(self):
        return self._articulation_deflection

    def _iter_subsystems(self):
        return list(self._subs)


STAR_CANNON = (1.008, 0.450, -0.670)     # authored mount, starboard wing
WARP_CORE = (0.0, -0.33, 0.0)            # body


def test_the_fixture_mounts_attribute_as_this_file_assumes():
    """Guard. If these two mounts stop attributing as expected, every test
    below would pass or fail for the wrong reason."""
    assert ps.part_for_point("birdofprey", STAR_CANNON) == "left wing01"
    assert ps.part_for_point("birdofprey", WARP_CORE) != "left wing01"


def test_a_particle_controller_on_the_severed_part_stops():
    particles.reset()
    star = _Sub("Star Cannon", STAR_CANNON)
    ship = _Ship([star])
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(star)
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert not c.is_emitting(), (
        "a controller emitting from a subsystem on the severed wing must "
        "stop — the wing it streams from is no longer attached")


def test_a_controller_elsewhere_keeps_emitting():
    """The other half, and the one a weak test would miss: severance must not
    silence the whole ship."""
    particles.reset()
    star = _Sub("Star Cannon", STAR_CANNON)
    core = _Sub("Warp Core", WARP_CORE)
    ship = _Ship([star, core])
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(core)
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert c.is_emitting(), "the body's emitters are untouched"


def test_silencing_matches_by_IDENTITY_not_by_name():
    """Two ships in one battle carry identically named subsystems. Matching
    on GetName() would silence the other Bird of Prey's cannon too."""
    particles.reset()
    mine = _Sub("Star Cannon", STAR_CANNON)
    theirs = _Sub("Star Cannon", STAR_CANNON)
    ship = _Ship([mine])
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(theirs)
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert c.is_emitting(), (
        "another ship's identically named cannon must keep emitting")


def test_cast_light_from_the_severed_part_goes_dark():
    """PIN. This already works — emitter intensity reads the parent
    subsystem's glow state and severance zeroes its condition — but nothing
    asserted it, so either half could be changed without noticing."""
    from engine.appc import light_emitters, subsystem_glow
    star = _Sub("Star Cannon", STAR_CANNON)
    ship = _Ship([star])
    assert subsystem_glow.glow_state(star) != subsystem_glow.DESTROYED

    ps.sever(ship, None, "left wing01")

    assert subsystem_glow.glow_state(star) == subsystem_glow.DESTROYED
    assert light_emitters.resolve_emitter_intensity(
        {"intensity": 1.0}, star, 0.0) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_part_severance_emitters.py -v`

Expected: the three particle tests FAIL with `AttributeError:
'AnimTSParticleController' object has no attribute 'is_emitting'`. The
guard and the light pin PASS — that is correct, they assert what already
works. If
`test_the_fixture_mounts_attribute_as_this_file_assumes` fails, stop and
report — the rest of the file is built on it.

- [ ] **Step 3: Add the `is_emitting` accessor and the `active` reader**

In `engine/appc/particles.py`, on `AnimTSParticleController`, immediately
after `stop_emitting`:

```python
    def is_emitting(self):
        """Whether `stop_emitting` has been called on this controller.

        There is no boolean flag: `_stop_age` is None while emitting and
        holds the age at which emission ceased afterwards (line 67,
        "None => still emitting"). Do NOT add a second flag, and do NOT
        route this through `_effective_stop_age`, which also caps by
        `_effect_life_time` / `_duration` and so answers a different
        question — whether the effect has run out, not whether it was
        stopped.

        Exists so a caller can ASSERT the emitting state; `stop_emitting`
        had no reader at all, which meant nothing could tell a stopped
        controller from a running one."""
        return self._stop_age is None
```

Beside `active_count` (which reads the module-level `_active` list):

```python
def active() -> list:
    """The live controller registry, as a list.

    `active_count` already reads `_active`; exposing the list itself lets a
    caller act on the controllers rather than only count them."""
    return list(_active)
```

⚠️ `register(controller)` resets `controller._stop_age = None`
(`particles.py:183`), so a controller must be registered BEFORE it is
stopped — which is the order both tests use.

- [ ] **Step 4: Return the destroyed subsystems from `_destroy_subsystems_on_part`**

Change its signature to `-> list`, extend its docstring, make every early
`return` a `return []`, accumulate, and return:

```python
def _destroy_subsystems_on_part(ship, part_name) -> list:
    """Destroy every subsystem whose mount lies on `part_name`, and return
    them.

    Mirrors `hull_breakup._destroy_subsystems_inside`: condition straight to
    zero through the normal subsystem-damage path, so the usual events fire. A
    disruptor cannon that has physically left the ship cannot keep firing.

    The returned list is what `sever` uses to silence particle emitters
    attached to those subsystems. Cast LIGHT needs no such step — emitter
    intensity is gated on the parent's glow state, which the zero condition
    already flips to DESTROYED.
    """
```

and in the loop:

```python
    killed = []
    for sub in list(subs or []):
        ...
        try:
            sub.SetCondition(0.0)
            killed.append(sub)
        except Exception as _e:  # noqa: BLE001
            dev_mode.log_swallowed("severed part subsystem destroy", _e)
    return killed
```

- [ ] **Step 5: Add the silencer and call it from `sever`**

Add to `engine/appc/part_severance.py`, above `sever`:

```python
def _silence_emitters_on(killed) -> None:
    """Stop every particle controller emitting from one of `killed`.

    Identity, never name: two ships in one battle carry identically named
    subsystems, and `_emit_from` holds the object itself. Pinned by
    tests/unit/test_part_severance_emitters.py::
    test_silencing_matches_by_IDENTITY_not_by_name.

    Best-effort: a VFX failure must never abort a severance that has already
    happened to the hull.
    """
    if not killed:
        return
    try:
        from engine.appc import particles
        live = particles.active()
    except Exception as _e:  # noqa: BLE001
        dev_mode.log_swallowed("severed part emitter silence", _e)
        return
    dead = {id(s) for s in killed}
    for c in list(live or []):
        try:
            if id(getattr(c, "_emit_from", None)) in dead:
                c.stop_emitting()
        except Exception as _e:  # noqa: BLE001
            dev_mode.log_swallowed("severed part emitter silence", _e)
```

In `sever`, replace the bare `_destroy_subsystems_on_part(ship, part_name)`
call with:

```python
    _silence_emitters_on(_destroy_subsystems_on_part(ship, part_name))
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_part_severance_emitters.py tests/unit/test_part_severance.py -v`

Expected: PASS, all of them.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`

Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add engine/appc/part_severance.py engine/appc/particles.py tests/unit/test_part_severance_emitters.py
git commit -m "feat(severance): nothing keeps emitting from a detached part

Particle controllers emitting from a subsystem on a severed part are
stopped, matched by identity so another ship's identically named cannon
keeps running. Cast light already died with the part (intensity is gated
on the parent's glow state) — pinned with a test, because nothing
asserted it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Collision pieces follow a part mid-travel

With Task 1 in place a severed wing stops colliding, but a RAISED wing still
collides where it would be if it were down. This is the smaller half — a Bird
of Prey's rest pose IS its combat pose (wings down = armed), so this only
applies while unarmed or during the two-second travel.

**Files:**
- Modify: `engine/appc/hull_bounds.py:87-107` (`hull_spheres_world`),
  `:110-152` (`hull_spheres_near`)
- Test: `tests/unit/test_hull_bounds_parts.py` (extend)

**Interfaces:**
- Consumes: `articulation.part_transform_point(ship, point) -> tuple` — body
  frame in, body frame out, SHIP units, identity at rest / no rig / detached.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_hull_bounds_parts.py`:

```python
# ── Mid-travel ───────────────────────────────────────────────────────────────

def test_a_wing_piece_moves_with_its_part_at_full_deflection():
    """The piece must sit where the wing is DRAWN. `part_transform_point` is
    the same Rodrigues hinge the renderer's node override uses, so the
    collision sphere and the drawn mesh agree by construction."""
    from engine.appc import articulation
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))

    ship._articulation_deflection = 0.0
    (rest, _r) = hb.hull_spheres_world(ship)[0]

    ship._articulation_deflection = 1.0
    (moved, _r2) = hb.hull_spheres_world(ship)[0]

    expected = articulation.part_transform_point(ship, WING_PT)
    assert (moved.x, moved.y, moved.z) != (rest.x, rest.y, rest.z)
    assert moved.x == pytest.approx(expected[0], abs=1e-6)
    assert moved.y == pytest.approx(expected[1], abs=1e-6)
    assert moved.z == pytest.approx(expected[2], abs=1e-6)


def test_an_untagged_piece_never_moves():
    """The common case, and the one that must stay byte-identical: a piece on
    no part is unaffected at any deflection."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*BODY_PT, 0.05)]))
    ship._articulation_deflection = 0.0
    (rest, _r) = hb.hull_spheres_world(ship)[0]
    ship._articulation_deflection = 1.0
    (same, _r2) = hb.hull_spheres_world(ship)[0]
    assert (same.x, same.y, same.z) == (rest.x, rest.y, rest.z)


def test_hull_spheres_near_ACCEPTS_a_piece_at_its_MOVED_position():
    """The half a weak test would miss. hull_spheres_near rejects in the
    ship's BODY frame before transforming out, so if the part transform were
    applied only to survivors, a moved piece would be rejected against its
    REST position and never returned at all."""
    from engine.appc import articulation
    from engine.appc.math import TGPoint3
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    ship._articulation_deflection = 1.0
    mx, my, mz = articulation.part_transform_point(ship, WING_PT)

    # A tight query centred on where the wing IS, too small to reach its rest
    # position. At identity world transform, body frame == world frame.
    got = hb.hull_spheres_near(ship, TGPoint3(mx, my, mz), 0.01)
    assert len(got) == 1, "a moved piece must be found where it is drawn"

    rest_only = hb.hull_spheres_near(ship, TGPoint3(*WING_PT), 0.01)
    assert rest_only == [], (
        "the piece's REST position must be empty once the wing has moved")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_hull_bounds_parts.py -v -k "moves or untagged or MOVED"`

Expected: `test_a_wing_piece_moves_with_its_part_at_full_deflection` FAILs on
`moved != rest`; `test_hull_spheres_near_ACCEPTS_a_piece_at_its_MOVED_position`
FAILs with `len(got) == 0`. `test_an_untagged_piece_never_moves` PASSes — it
is a guard against over-reach, not a driver.

- [ ] **Step 3: Transform tagged pieces in `hull_spheres_world`**

```python
    from engine.appc.part_severance import is_detached
    from engine.appc import articulation
    out = []
    for (cx, cy, cz), r, part in cached:
        if part is not None and is_detached(ship, part):
            continue                           # severed: no longer collides
        if part is not None:
            # Body frame, ship units, in and out. Identity at rest and for an
            # unrigged hull, so an untagged piece costs one None compare.
            cx, cy, cz = articulation.part_transform_point(ship, (cx, cy, cz))
        v = TGPoint3(cx * scale, cy * scale, cz * scale)
```

- [ ] **Step 4: Transform BEFORE the reject in `hull_spheres_near`**

The order matters and is the whole content of the third test: the body-frame
distance compare must run against the MOVED centre.

```python
    from engine.appc.part_severance import is_detached
    from engine.appc import articulation
    out = []
    for (cx, cy, cz), r, part in cached:
        if part is not None and is_detached(ship, part):
            continue                           # severed: no longer collides
        if part is not None:
            # BEFORE the reject below, not after: the compare happens in the
            # ship's body frame, so a moved piece tested at its REST centre
            # would be rejected and never returned.
            cx, cy, cz = articulation.part_transform_point(ship, (cx, cy, cz))
        # Body-frame piece centre at the ship's live scale.
        sx, sy, sz = cx * scale, cy * scale, cz * scale
```

Append to `hull_spheres_near`'s docstring:

```
    A piece tagged with an articulated part is moved into that part's live
    pose FIRST, before the reject — see tests/unit/test_hull_bounds_parts.py::
    test_hull_spheres_near_ACCEPTS_a_piece_at_its_MOVED_position. Untagged
    pieces, which are the overwhelming majority on every hull and all of them
    on an unrigged one, take exactly the path they took before.
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_hull_bounds_parts.py -v`

Expected: PASS, all of them.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`

Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/appc/hull_bounds.py tests/unit/test_hull_bounds_parts.py
git commit -m "feat(collision): a part's hull pieces follow it mid-travel

A raised Bird of Prey wing collides where it is drawn, not where it would
be if it were down. The transform runs BEFORE hull_spheres_near's
body-frame reject, or a moved piece would be rejected at its rest centre
and never returned.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A carve deposited on a moved part lands on the part

Since picking followed the live pose (plan 2), a shot at a raised wing returns
the real world hit point on that wing. `hull_carve_add` converts it through
`inst->world`, which carries the hull's rest-pose node structure — so the carve
lands wherever that body point sits AT REST, off the wing entirely. The damage
field is baked rest-pose and shared by every instance of the hull, so the QUERY
moves, not the field.

**Files:**
- Create: `native/src/renderer/include/renderer/part_frame.h`,
  `native/src/renderer/part_frame.cc`
- Modify: `native/src/renderer/CMakeLists.txt:161` (source list, beside
  `aabb.cc`), `native/tests/renderer/CMakeLists.txt:19` (test list, beside
  `aabb_test.cc`), `native/src/host/host_bindings.cc:4303` (`hull_carve_add`)
- Test: `native/tests/renderer/part_frame_test.cc` (create)

**Interfaces:**
- Consumes: `assets::Model` (`nodes`, `root_node`, `meshes`,
  `Node::parent_index`, `Node::meshes`, `Node::local_transform`,
  `Mesh::cpu_data()`), `scenegraph::Instance::node_overrides`
  (`std::unordered_map<int, glm::mat4>`), `resolve_model(inst->model_handle)`
- Produces:
  ```cpp
  namespace renderer {
  std::optional<glm::mat4> rest_from_posed_at(
      const assets::Model& model,
      const std::unordered_map<int, glm::mat4>& overrides,
      const glm::vec3& body_point);
  }
  ```

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/part_frame_test.cc`:

```cpp
// A carve must land on the part it struck, not on the hull beneath where
// that part sits at rest. The damage field is baked rest-pose and shared by
// every instance of the hull, so the query point is pulled back into the
// struck part's rest frame rather than the field being re-baked per pose.

#include <gtest/gtest.h>

#include <optional>
#include <unordered_map>

#include <glm/gtc/matrix_transform.hpp>

#include <assets/model.h>
#include <renderer/part_frame.h>

namespace {

// Root (no geometry) + a child holding one triangle around x = +10, so an
// override on the child is distinguishable from one on the root and the
// moved and rest positions are far apart.
assets::Model root_plus_movable_child() {
    assets::Model m;
    m.root_node = 0;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
    });
    m.nodes.push_back(assets::Node{
        .name = "wing", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f),
                                          glm::vec3(10.0f, 0.0f, 0.0f)),
        .meshes = {0},
    });
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = glm::vec3(-1, -1, -1)});
    cpu.vertices.push_back({.position = glm::vec3(1, -1, 1)});
    cpu.vertices.push_back({.position = glm::vec3(0, 1, 0)});
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return m;
}

}  // namespace

TEST(PartFrame, NoOverridesClaimsNothing) {
    // The overwhelmingly common case and the one that must not change: with
    // no overrides every carve keeps its body point untouched.
    auto m = root_plus_movable_child();
    const std::unordered_map<int, glm::mat4> none;
    EXPECT_FALSE(renderer::rest_from_posed_at(m, none, glm::vec3(10, 0, 0))
                     .has_value());
}

TEST(PartFrame, APointOnTheMovedPartYieldsItsRestFrame) {
    // THE POINT. The wing is drawn at x = -10; a carve there must come back
    // with the transform that puts it at x = +10, where the field has it.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));

    auto rest = renderer::rest_from_posed_at(m, ov, glm::vec3(-10, 0, 0));
    ASSERT_TRUE(rest.has_value());
    const glm::vec3 p(*rest * glm::vec4(-10.0f, 0.0f, 0.0f, 1.0f));
    EXPECT_NEAR(p.x, 10.0f, 1e-4f);
    EXPECT_NEAR(p.y, 0.0f, 1e-4f);
    EXPECT_NEAR(p.z, 0.0f, 1e-4f);
}

TEST(PartFrame, APointOffEveryMovedPartClaimsNothing) {
    // The other half, and the one a weak test would miss: a hit on the body
    // while a wing is raised must not be dragged into the wing's frame.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));
    EXPECT_FALSE(renderer::rest_from_posed_at(m, ov, glm::vec3(0, 0, 0))
                     .has_value());
}

TEST(PartFrame, ASeveredPartClaimsNothing) {
    // A hidden part is the ZERO matrix (set_instance_node_hidden), which is
    // singular — inverting it produces NaNs that would poison the field.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::mat4(0.0f);
    for (float x : {10.0f, 0.0f, -10.0f}) {
        EXPECT_FALSE(
            renderer::rest_from_posed_at(m, ov, glm::vec3(x, 0, 0)).has_value())
            << "severed part claimed a carve at x = " << x;
    }
}

TEST(PartFrame, AMovedParentClaimsItsChildsMesh) {
    // The trap plan 2 hit LIVE: find_parent_node_index attaches a mesh to its
    // immediate NiNode parent (__NDL_MultiMtl_Node), NOT to the part node an
    // override names. A real BC hull is three levels, not two, so a node's
    // geometry includes its DESCENDANTS'.
    auto m = root_plus_movable_child();
    m.nodes[1].meshes.clear();               // geometry hangs off the child
    m.nodes.push_back(assets::Node{
        .name = "__NDL_MultiMtl_Node", .parent_index = 1,
        .local_transform = glm::translate(glm::mat4(1.0f),
                                          glm::vec3(0.0f, 0.0f, 5.0f)),
        .meshes = {0},
    });
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));

    // The grandchild mesh sits around (10, 0, 5) at rest, (-10, 0, 5) posed.
    auto rest = renderer::rest_from_posed_at(m, ov, glm::vec3(-10, 0, 5));
    ASSERT_TRUE(rest.has_value())
        << "an override on a part must claim its CHILDREN's geometry too";
    const glm::vec3 p(*rest * glm::vec4(-10.0f, 0.0f, 5.0f, 1.0f));
    EXPECT_NEAR(p.x, 10.0f, 1e-4f);
    EXPECT_NEAR(p.z, 5.0f, 1e-4f);
}
```

- [ ] **Step 2: Register the test and run it to verify it fails**

Add `part_frame_test.cc` to the source list in
`native/tests/renderer/CMakeLists.txt`, beside `aabb_test.cc`.

Run: `cmake -B build -S . && cmake --build build -j`

Expected: FAIL to compile — `renderer/part_frame.h: No such file or directory`.

- [ ] **Step 3: Write the header**

Create `native/src/renderer/include/renderer/part_frame.h`:

```cpp
// native/src/renderer/include/renderer/part_frame.h
#pragma once

#include <optional>
#include <unordered_map>

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// The transform that maps a POSED body-frame point back into the rest frame
/// of the overridden node whose geometry contains it — or nullopt when no
/// overridden node claims that point.
///
/// Every baked structure in this engine (the .dhv distance field, the carve
/// field, the trace BVH) is whole-hull, rest-pose and SHARED across every
/// instance of a model. So a query arriving in the LIVE pose is transformed
/// back into rest space rather than the structure being re-posed per
/// instance. This is the primitive that does it, and it is the same rule
/// ray_trace.cc follows from the other direction (there the RAY moves; here
/// the POINT does).
///
/// Returns nullopt for a SINGULAR override: a hidden or severed part is the
/// zero matrix, whose inverse is all NaN and would poison whatever field the
/// result were applied to.
///
/// An override names a PART node, but find_parent_node_index attaches a mesh
/// to its immediate NiNode parent, which on a real BC hull is an interposed
/// __NDL_MultiMtl_Node. So a node's geometry is its own meshes AND every
/// descendant's. Getting that wrong is what made manual fire miss a raised
/// wing live — see the spec's §5c child-node trap.
std::optional<glm::mat4> rest_from_posed_at(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides,
    const glm::vec3& body_point);

}  // namespace renderer
```

- [ ] **Step 4: Write the implementation**

Create `native/src/renderer/part_frame.cc`:

```cpp
// native/src/renderer/part_frame.cc
#include <renderer/part_frame.h>

#include <limits>
#include <vector>

#include <assets/model.h>

namespace renderer {
namespace {

constexpr float kSingularEps = 1e-6f;
// Slack on the posed bounds, in model units. The bounds are an AABB of a
// rotated subtree and so are already loose; this only stops a carve landing
// exactly on the surface from falling between the part and the hull.
constexpr float kBoundsSlack = 1e-3f;

bool nearly_singular(const glm::mat4& m) {
    const float d = glm::determinant(m);
    return d > -kSingularEps && d < kSingularEps;
}

}  // namespace

std::optional<glm::mat4> rest_from_posed_at(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides,
    const glm::vec3& body_point) {
    if (overrides.empty() || model.nodes.empty()) return std::nullopt;
    const std::size_t n = model.nodes.size();
    if (model.root_node < 0 || static_cast<std::size_t>(model.root_node) >= n) {
        return std::nullopt;
    }

    // Rest world-per-node. The asset pipeline orders nodes so parents precede
    // children, so one linear pass suffices (same as aabb.cc).
    std::vector<glm::mat4> rest(n, glm::mat4(1.0f));
    rest[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < n; ++i) {
        const int parent = model.nodes[i].parent_index;
        if (parent >= 0 && static_cast<std::size_t>(parent) < n) {
            rest[i] = rest[parent] * model.nodes[i].local_transform;
        }
    }

    for (const auto& entry : overrides) {
        const int node = entry.first;
        if (node < 0 || static_cast<std::size_t>(node) >= n) continue;
        if (nearly_singular(entry.second)) continue;  // severed: claims nothing

        // Posed world for this node. `local` REPLACES the node's own local
        // transform; everything below it inherits the change.
        const int parent = model.nodes[node].parent_index;
        const glm::mat4 base =
            (parent >= 0 && static_cast<std::size_t>(parent) < n)
                ? rest[parent] : glm::mat4(1.0f);
        const glm::mat4 posed_node = base * entry.second;
        if (nearly_singular(posed_node) || nearly_singular(rest[node])) continue;

        // One rigid-ish map each way for the whole subtree.
        const glm::mat4 to_rest  = rest[node] * glm::inverse(posed_node);
        const glm::mat4 to_posed = posed_node * glm::inverse(rest[node]);

        // Bound this node's POSED subtree geometry and test containment.
        // Descendants are included: an override on a part moves its
        // children's meshes too, and on a real hull the meshes are ONLY on
        // the children.
        glm::vec3 lo(std::numeric_limits<float>::max());
        glm::vec3 hi(std::numeric_limits<float>::lowest());
        bool any = false;
        for (std::size_t i = 0; i < n; ++i) {
            bool in_subtree = (static_cast<int>(i) == node);
            for (int p = model.nodes[i].parent_index;
                 !in_subtree && p >= 0 && static_cast<std::size_t>(p) < n;
                 p = model.nodes[p].parent_index) {
                if (p == node) in_subtree = true;
            }
            if (!in_subtree) continue;
            const glm::mat4 world_i = to_posed * rest[i];
            for (int mesh_idx : model.nodes[i].meshes) {
                if (mesh_idx < 0 ||
                    static_cast<std::size_t>(mesh_idx) >= model.meshes.size()) {
                    continue;
                }
                const auto* cpu = model.meshes[mesh_idx].cpu_data();
                if (cpu == nullptr) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 p(world_i * glm::vec4(v.position, 1.0f));
                    lo = glm::min(lo, p);
                    hi = glm::max(hi, p);
                    any = true;
                }
            }
        }
        if (!any) continue;
        lo -= kBoundsSlack;
        hi += kBoundsSlack;
        if (body_point.x < lo.x || body_point.x > hi.x) continue;
        if (body_point.y < lo.y || body_point.y > hi.y) continue;
        if (body_point.z < lo.z || body_point.z > hi.z) continue;
        return to_rest;
    }
    return std::nullopt;
}

}  // namespace renderer
```

Add `part_frame.cc` to the source list in
`native/src/renderer/CMakeLists.txt`, beside `aabb.cc`.

- [ ] **Step 5: Build and run the native test**

Run: `cmake --build build -j && ctest --test-dir build -R PartFrame --output-on-failure`

Expected: 5 tests PASS.

- [ ] **Step 6: Apply the pullback in `hull_carve_add`**

In `native/src/host/host_bindings.cc`, add `#include <renderer/part_frame.h>`
to the include block. In the `hull_carve_add` lambda, immediately after the
`nb` fallback block (the one ending `: glm::vec3(0.f, 0.f, 1.f);`), insert:

```cpp
              // A carve struck where the part is DRAWN, but the damage field
              // is baked rest-pose and shared by every instance of this hull.
              // So pull the point and its normal back into the struck part's
              // rest frame rather than re-posing the field. No-op when the
              // instance has no overrides — which is every hull but a rigged
              // one away from rest, i.e. almost always.
              glm::vec3 pb_rest = pb;
              if (!inst->node_overrides.empty()) {
                  const assets::Model* posed_model =
                      resolve_model(inst->model_handle);
                  if (posed_model != nullptr) {
                      if (auto to_rest = renderer::rest_from_posed_at(
                              *posed_model, inst->node_overrides, pb)) {
                          pb_rest = glm::vec3(*to_rest * glm::vec4(pb, 1.0f));
                          const glm::vec3 nr(glm::mat3(*to_rest) * nb);
                          if (glm::length(nr) > 1e-4f) nb = glm::normalize(nr);
                      }
                  }
              }
```

Then replace every subsequent use of `pb` inside this lambda with `pb_rest`.
Find them with `grep -n "pb" native/src/host/host_bindings.cc` scoped to the
lambda's line range; the `nb` fallback's own `glm::length(pb)` / `normalize(pb)`
must stay as `pb`, because it runs BEFORE the pullback.

- [ ] **Step 7: Build and run the full gate**

Run: `scripts/check_tests.sh`

Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/part_frame.h native/src/renderer/part_frame.cc native/src/renderer/CMakeLists.txt native/tests/renderer/part_frame_test.cc native/tests/renderer/CMakeLists.txt native/src/host/host_bindings.cc
git commit -m "fix(carve): a hit on a moved part carves the part, not the hull

Picking follows the live pose, so a shot at a raised wing returns a world
point on that wing — which world_to_body then resolved against the hull's
rest node structure, landing the scar somewhere else. The field stays
baked and shared; the query is pulled back into the struck part's rest
frame. A severed part (zero matrix) claims nothing rather than inverting
to NaN, and an override claims its DESCENDANTS' meshes, which is where a
real BC hull keeps them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Correct §4.3.1 — Ruling 1 STANDS

The spec says this work reverses Ruling 1 and requires inverting
`test_subsystem_kill_uses_the_REST_mount_even_mid_travel` in two files. That
prediction is **wrong**, and acting on it would break two correct tests.

Both tests compare a subsystem's rest mount against bounds that are STILL
rest-pose after this plan: `part_severance` tests against `PART_BOXES`
(authored rest-pose, unchanged), and `hull_breakup` tests against a carved
component from `hull_split_detached` — the damage field, which Task 4
deliberately keeps in rest space. Collision spheres do move, but no subsystem
kill reads them: `hull_spheres_world` / `hull_spheres_near` /
`point_is_inside_hull` have exactly two consumers, `collisions.py:248` and
`collision_avoidance.py:600`, neither of which touches subsystems.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`
  (§4.3 table rows for hull volume and glow regions; all of §4.3.1)
- Test: none — documentation. `tests/docs/test_doc_consistency.py` must stay
  green.

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Verify the claim before writing it down**

Do not take the paragraph above on trust — it is the kind of claim this
project has been burned by. Run:

```bash
grep -rn "hull_spheres_world\|hull_spheres_near\|point_is_inside_hull" engine | grep -v "engine/appc/hull_bounds.py"
```

Expected: exactly the two consumers named above (plus their import lines).
If a third consumer exists and it reads subsystems, STOP and report — §4.3.1's
original prediction would then be right for that path.

- [ ] **Step 2: Rewrite §4.3.1**

Replace the whole of the section headed
`### ⚠️ 4.3.1 This REVERSES Ruling 1, deliberately` with:

```markdown
### ✅ 4.3.1 Ruling 1 STANDS — this section's earlier prediction was wrong

**Superseded 2026-09-23, before implementation.** This section previously
predicted that §4.3 would reverse Ruling 1 and require inverting
`test_subsystem_kill_uses_the_REST_mount_even_mid_travel` in both
`tests/unit/test_part_severance.py` and `tests/unit/test_hull_breakup.py`.

**It does not, and they must not be touched.** The prediction assumed the
sim's BOUNDS would move into the live pose. Under "transform the query, never
the structure" they do not:

- `part_severance._destroy_subsystems_on_part` tests a rest mount against
  `PART_BOXES`, authored rest-pose and unchanged. Which part a subsystem sits
  on is a STATIC property of the hull, not a function of where the part
  currently happens to be.
- `hull_breakup._destroy_subsystems_inside` tests a rest mount against a
  carved component from `hull_split_detached` — the damage field, which stays
  baked rest-pose. A carve struck on a moved part is pulled BACK into rest
  space before deposit (`renderer::rest_from_posed_at`), precisely so this
  stays true.

Collision pieces (`hull_bounds.py`) genuinely do articulate, but no subsystem
kill reads them: `hull_spheres_world` / `hull_spheres_near` /
`point_is_inside_hull` have exactly two consumers, `collisions.py:248` and
`collision_avoidance.py:600`, neither of which touches subsystems.

So both tests remain correct as written, and their docstrings stay as the
record of why. The one claim inside them that is now too broad is "the sim
never articulates" — narrow it in place to "the structures these compare
against are never articulated", and leave everything else alone.

**The general lesson, worth more than the ruling:** a design that moves
queries instead of structures keeps every rest-pose comparison in the codebase
valid for free. That is the property to preserve when this is extended.
```

- [ ] **Step 3: Narrow the over-broad sentence in both test docstrings**

In `tests/unit/test_part_severance.py:186` and
`tests/unit/test_hull_breakup.py:105`, the docstrings say the sim never
articulates. Replace that clause in each with:

```
    the structures this compares against are never articulated: PART_BOXES are
    authored rest-pose, and the voxel field and .dhv SDF stay baked from the
    NIF in rest pose (a carve struck on a moved part is pulled back to rest
    before deposit -- renderer::rest_from_posed_at). Collision spheres DO
    articulate as of the part-aware sim-geometry plan, but nothing in this
    path reads them. See spec 4.3.1.
```

Leave every assertion untouched.

- [ ] **Step 4: Replace the hull-volume row in the §4.3 table**

That row describes a point query with no caller: `engine/appc/hull_volume.py`
only bakes and prewarms, and the field is consumed by `InstanceFieldCache` →
`breach.frag` / `opaque.frag` on the GPU in model space. Replace its `fix`
cell with:

```
**NO SEPARATE WORK.** There is no sim-side point query against the .dhv — it is
baked by `hull_volume.py` and sampled on the GPU in model space. The only thing
that WRITES into it is a carve, and a carve arriving from a moved part is
pulled back to rest by `renderer::rest_from_posed_at` before deposit (see the
damage-carve row). Keeping the field rest-pose preserves model-level sharing
AND keeps §4.3.1's rest-pose comparisons valid.
```

- [ ] **Step 5: Replace the glow-regions row**

Glow regions are fitted to nacelle and engine hardpoints; the only rigged hull
in the game carries cannons on its wings, not glow volumes. Replace its `fix`
cell with:

```
**Not transformed — silenced instead.** Anything emitting from a DETACHED part
stops: cast light already did (emitter intensity is gated on the parent
subsystem's glow state, which severance zeroes), and particle controllers now
do too (`part_severance._silence_emitters_on`). Transforming glow capsules into
the live pose buys nothing today — no rigged hull has one — and is re-openable
if one ever does.
```

- [ ] **Step 6: Run the doc-consistency test and the two affected suites**

Run: `uv run pytest tests/docs/test_doc_consistency.py tests/unit/test_part_severance.py tests/unit/test_hull_breakup.py -v`

Expected: PASS. `test_doc_consistency.py` machine-checks OQ status counts
against the summary line; this edit touches neither.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`

Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md tests/unit/test_part_severance.py tests/unit/test_hull_breakup.py
git commit -m "docs(articulation): Ruling 1 stands — 4.3.1's prediction was wrong

4.3.1 predicted that sim geometry would move into the live pose and both
rest-mount characterisation tests would need inverting. Transforming the
query instead of the structure means the bounds those tests compare
against stay rest-pose, so both remain correct; only their too-broad 'the
sim never articulates' clause is narrowed. Also collapses the hull-volume
row (no sim-side point query exists) and replaces the glow-region row
with emitter silencing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark, after Task 5)

The gate cannot see game feel, and three failures in this feature family were
found live that no test caught. Run `./build/dauntless --developer`,
QuickBattle against a Bird of Prey:

1. **Severed wing does not collide.** Shoot a wing off, then fly through where
   it was. No bump, no scrape.
2. **Severed wing goes quiet.** Shoot a wing off while its disruptor is
   firing. Cast light and any particle stream stop at the moment of
   detachment, not seconds later.
3. **Scar lands on a raised wing.** Drop to green alert so the wings rise,
   then shoot a wing. The scar appears ON the wing, not floating beside the
   hull.
4. **Raised wing collides where it is drawn.** Ram the other wing while it is
   raised. The collision happens at the raised wing, not below it.
5. **Regression — an unrigged hull is unchanged.** Fly a Galaxy through a
   normal fight. Collisions, carves and nacelle glow must be
   indistinguishable from before; every pre-existing code path is taken.
