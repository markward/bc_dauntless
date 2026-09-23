# Hardpoint → Part Parenting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a subsystem mounted on an articulated part move with that part, so a Bird of Prey's wingtip cannons fire from where the wings actually are.

**Architecture:** `subsystem_world_position` is the single choke point — firing origins (`_emitter_world_position`), UI overlays, SPV pins and the target reticle all funnel through it, and it currently computes `ship_loc + R · local_mount` against the model's REST pose. We insert one body-frame step: resolve which part a mount belongs to, apply that part's live articulation to the mount, then proceed unchanged. Ships with no rig take an early return and are byte-identical.

**Tech Stack:** Python 3.11, pytest. No C++ and no rebuild — every change is Python.

**Spec:** `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md` (§4.1 "The defect", §4.2 "Hardpoint → part assignment")

## Global Constraints

- **Two unit systems meet in this work and confusing them has already caused one silent live failure.** `articulation.PART_BOXES`, subsystem `GetPosition()` and `subsystem_world_position` are all in **SHIP units** (a BoP wingtip is `x = 1.008`). `host_io.world_to_body` and `set_instance_node_rotation` work in **MODEL units** (the same wingtip is `x = 100.8`). The ratio is `MODEL_TO_SHIP = 0.01` (= `host_loop.BC_MODEL_SCALE`). Task 1 exists specifically to remove this trap before Task 2 builds on it.
- **Rotation is column-vector, right-handed** (`CLAUDE.md`): `v_world = R · v_body`, `GetCol(1)` is forward. Never `GetRow`.
- **Deflection 0 must stay byte-identical** to today. It is the model's authored rest pose and the pose combat runs in.
- **Never use `git add -A` or `git add .`** — this checkout is shared. Always stage explicit paths.
- Run the gate with `scripts/check_tests.sh`, never `scripts/run_tests.sh` (which is pytest-only). Compare failures against `tests/known_failures.txt`; the only baselined entry is `tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`.
- Tests run with `.venv/bin/python3 -m pytest` from the worktree root.

---

### Task 1: Put `Part.pivot` in ship units

The rig currently stores `pivot` in MODEL units while everything else about a part (`PART_BOXES`, mounts) is in SHIP units. Task 2 must transform ship-unit mounts about the pivot, so leaving two units in one module invites the exact bug that already shipped. There is exactly one consumer (`host_loop.py:7046`), so converting at that single C++ boundary is safe.

**Files:**
- Modify: `engine/appc/articulation.py` (the `Part` docstring, `_RIGS`, `rotation_for`)
- Modify: `engine/host_loop.py:7040-7050` (`_sync_ship_articulation`)
- Test: `tests/unit/test_articulation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `articulation.Part.pivot` in SHIP units. `articulation.rotation_for(part, deflection) -> ((px,py,pz) ship units, (ax,ay,az) unit, theta_radians)`. `articulation.MODEL_TO_SHIP = 0.01`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_articulation.py`:

```python
def test_pivot_is_in_ship_units():
    """The pivot must share units with PART_BOXES and subsystem mounts, which
    are SHIP units (a BoP wingtip is x = 1.008, not 100.8). It used to be in
    MODEL units, which is the same confusion that made part attribution
    silently never fire — see part_severance.MODEL_TO_SHIP."""
    port, starboard = articulation.rig_for("birdofprey")
    assert starboard.pivot[0] == pytest.approx(0.16)
    assert port.pivot[0] == pytest.approx(-0.16)
    assert starboard.pivot[2] == pytest.approx(0.05)
    # Inside the authored wing box, which is also ship units.
    box = articulation.part_boxes_for("birdofprey")["left wing01"]
    assert box[0][0] <= starboard.pivot[0] <= box[1][0]


def test_rotation_for_returns_ship_units():
    part = articulation.rig_for("birdofprey")[1]
    pivot, _axis, _theta = articulation.rotation_for(part, 1.0)
    assert pivot == part.pivot
    assert abs(pivot[0]) < 1.0, "a ship-units pivot is ~0.16, not ~16"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/unit/test_articulation.py::test_pivot_is_in_ship_units -v`
Expected: FAIL — `assert 16.0 == approx(0.16 ...)`

- [ ] **Step 3: Convert the rig data**

In `engine/appc/articulation.py`, change the `Part` docstring line for `pivot` to:

```python
    pivot:     hinge point, parent/model space, SHIP units (model NIF units
               / 100). Shares units with PART_BOXES and subsystem mounts on
               purpose: Task 1 of the hardpoint-parenting plan unified them
               after a MODEL-vs-SHIP mix-up made part attribution silently
               never fire. Converted to model units at the ONE C++ call site
               (host_loop._sync_ship_articulation).
```

Replace the two `Part(...)` entries in `_RIGS["birdofprey"]` with:

```python
        Part(node="left wing",   pivot=(-0.16, 0.0, 0.05),
             axis=(0.0, 1.0, 0.0), angle_deg=45.0),
        Part(node="left wing01", pivot=(0.16, 0.0, 0.05),
             axis=(0.0, 1.0, 0.0), angle_deg=-45.0),
```

Add below `TRAVEL_SECONDS`:

```python
# Ship units -> model (NIF) units, for the C++ boundary only. = BC_MODEL_SCALE.
MODEL_TO_SHIP = 0.01
```

- [ ] **Step 4: Convert at the C++ boundary**

In `engine/host_loop.py`, replace the body of the loop at `_sync_ship_articulation` (around line 7046):

```python
    for part in parts:
        pivot, axis, theta = articulation.rotation_for(part, deflection)
        host_io.set_instance_node_rotation(iid, part.node, pivot, axis, theta)
```

with:

```python
    for part in parts:
        pivot, axis, theta = articulation.rotation_for(part, deflection)
        # The rig is authored in SHIP units (shared with PART_BOXES and
        # subsystem mounts); the binding works in MODEL units. This is the
        # ONLY place the two meet.
        pivot_model = tuple(c / articulation.MODEL_TO_SHIP for c in pivot)
        host_io.set_instance_node_rotation(iid, part.node, pivot_model,
                                           axis, theta)
```

- [ ] **Step 5: Run the articulation tests**

Run: `.venv/bin/python3 -m pytest tests/unit/test_articulation.py -v`
Expected: PASS — all tests including the two new ones. The existing
`test_full_deflection_lifts_the_wing_tip_towards_horizontal` uses model-unit tip
coordinates against a now-ship-unit pivot, so if it fails, update it to use ship
units throughout: `tip_x` becomes `±1.0258` and `tip_z` becomes `-0.7125`.

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/appc/articulation.py engine/host_loop.py tests/unit/test_articulation.py
git commit -m "refactor(articulation): pivot in SHIP units, converted at the C++ boundary

The rig stored pivot in MODEL units while PART_BOXES and subsystem mounts
use SHIP units. Hardpoint parenting has to rotate ship-unit mounts about
the pivot, so two units in one module invites exactly the mix-up that made
part attribution silently never fire. One consumer, so the conversion moves
to that single call site."
```

---

### Task 2: Transform a body-frame point by its part's live articulation

The reusable primitive Task 3 needs: given a ship and a body-frame point in ship units, return where that point actually is once its part has rotated.

**Files:**
- Modify: `engine/appc/articulation.py` (add `part_transform_point`)
- Test: `tests/unit/test_articulation.py`

**Interfaces:**
- Consumes: `articulation.Part` (ship-unit pivot, from Task 1); `articulation.rig_for`, `articulation.part_boxes_for`; `part_severance.part_for_point(leaf, point_ship_units) -> str | None`.
- Produces: `articulation.part_transform_point(ship, point) -> (x, y, z)` — body frame, ship units, in and out.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_articulation.py`:

```python
class _PosedShip:
    """Minimal stand-in: a leaf and a deflection is all the transform needs."""

    def __init__(self, deflection, leaf="birdofprey"):
        self._articulation_leaf = leaf
        self._d = deflection

    def GetArticulationDeflection(self):
        return self._d


def test_transform_is_identity_at_rest():
    """Deflection 0 is the model's authored pose. Every consumer of this must
    be byte-identical to not calling it at all."""
    p = (0.8, 0.0, -0.4)
    assert articulation.part_transform_point(_PosedShip(0.0), p) == p


def test_a_wing_point_rises_with_the_wing():
    """The starboard wingtip is the Star Cannon's mount. At full deflection it
    must follow the wing, not stay at the rest position — that gap is the live
    bug this plan fixes (~60 m on a BoP)."""
    rest = (1.008, 0.450, -0.670)
    moved = articulation.part_transform_point(_PosedShip(1.0), rest)
    assert moved[2] > rest[2], "the mount must rise with the wing"
    assert moved[1] == pytest.approx(rest[1]), "Y is the hinge axis: unchanged"
    # It moves a long way — this is why the un-parented mount was so visibly wrong.
    dist = sum((moved[i] - rest[i]) ** 2 for i in range(3)) ** 0.5
    assert dist > 0.5


def test_a_body_point_never_moves():
    """The body is not an articulated part. A warp-core mount must be
    untouched at any deflection."""
    p = (0.0, -0.33, 0.0)
    assert articulation.part_transform_point(_PosedShip(1.0), p) == p


def test_an_unrigged_ship_is_untouched():
    p = (0.8, 0.0, -0.4)
    assert articulation.part_transform_point(_PosedShip(1.0, "galaxy"), p) == p


def test_the_two_wings_mirror():
    port = articulation.part_transform_point(_PosedShip(1.0), (-1.008, 0.45, -0.67))
    star = articulation.part_transform_point(_PosedShip(1.0), (1.008, 0.45, -0.67))
    assert port[0] == pytest.approx(-star[0])
    assert port[2] == pytest.approx(star[2])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/unit/test_articulation.py -k transform -v`
Expected: FAIL — `AttributeError: module 'engine.appc.articulation' has no attribute 'part_transform_point'`

- [ ] **Step 3: Implement it**

Append to `engine/appc/articulation.py`:

```python
def part_transform_point(ship, point):
    """Where a body-frame point ends up once its part has articulated.

    In and out are BODY frame, SHIP units (what subsystem mounts and
    PART_BOXES use). Identity for a ship with no rig, for a point on no
    articulated part, and at deflection 0 -- so an unarticulated hull is
    byte-identical to not calling this.

    This is what makes a hardpoint FOLLOW its part. A BoP's wingtip cannon
    sits at (1.008, 0.450, -0.670); with the wings up that mount is ~0.9 ship
    units (~150 m) from where the gun is drawn, and the beam fires from the
    stale point.
    """
    parts = rig_for(leaf_for(ship))
    if not parts:
        return point
    try:
        deflection = float(ship.GetArticulationDeflection())
    except Exception:  # noqa: BLE001 - not a ShipClass (prop / test double)
        return point
    if deflection == 0.0:
        return point

    from engine.appc.part_severance import part_for_point
    name = part_for_point(leaf_for(ship), point)
    if name is None:
        return point
    part = next((p for p in parts if p.node == name), None)
    if part is None:
        return point

    pivot, axis, theta = rotation_for(part, deflection)
    return _rotate_about(point, pivot, axis, theta)


def _rotate_about(point, pivot, axis, theta):
    """Rodrigues rotation of `point` about the line (pivot, unit axis) by
    `theta` radians. Right-handed, matching the renderer's column-vector
    convention (CLAUDE.md) and glm::rotate in set_instance_node_rotation, so
    the mount and the drawn mesh agree by construction."""
    if theta == 0.0:
        return point
    vx = point[0] - pivot[0]
    vy = point[1] - pivot[1]
    vz = point[2] - pivot[2]
    ax, ay, az = axis
    c = math.cos(theta)
    s = math.sin(theta)
    dot = ax * vx + ay * vy + az * vz
    cx = ay * vz - az * vy
    cy = az * vx - ax * vz
    cz = ax * vy - ay * vx
    return (pivot[0] + vx * c + cx * s + ax * dot * (1.0 - c),
            pivot[1] + vy * c + cy * s + ay * dot * (1.0 - c),
            pivot[2] + vz * c + cz * s + az * dot * (1.0 - c))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/unit/test_articulation.py -v`
Expected: PASS (all).

- [ ] **Step 5: DO NOT add a per-ship assignment cache**

Spec §4.2 says hardpoint→part assignment is "computed once at load and cached
per ship, never per tick". This plan deliberately resolves per call instead.
Recorded here so a reviewer does not read it as an oversight and "fix" it:

- The hot path never reaches the box test. `part_transform_point` returns at
  the first line for a hull with no rig (every ship but the Bird of Prey), and
  at the second for deflection 0 (every rigged ship in combat, since wings-down
  IS red alert). The cost only exists for a rigged ship mid-travel.
- What remains is four AABB distances and a sort, for ~16 subsystems on one
  ship — on the order of a thousand float ops per second, against a 60 Hz tick.
- A cache would have to be invalidated when a part detaches, and a stale entry
  would point a live gun at a wing that is no longer there. That is a worse
  failure than the cost it saves.

Revisit only if a profile shows it (`docs/engine/frame-profiler.md`), and note
that project's own rule: MEASURE BEFORE OPTIMISING.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/articulation.py tests/unit/test_articulation.py
git commit -m "feat(articulation): part_transform_point — where a mount goes when its part moves

Rodrigues rotation about the part's hinge, right-handed to match
set_instance_node_rotation's glm::rotate, so the mount and the drawn mesh
agree by construction. Identity at rest, on the body, and for unrigged hulls."
```

---

### Task 3: Route subsystem mounts through the part frame

The payoff. `subsystem_world_position` is the single choke point — `_emitter_world_position` (firing origins), the SPV pins, `phaser_overlay`, `target_reticle` and `host_loop:9282` all call it.

**Files:**
- Modify: `engine/appc/subsystems.py:26-51` (`subsystem_world_position`)
- Test: `tests/unit/test_subsystem_part_parenting.py` (create)

**Interfaces:**
- Consumes: `articulation.part_transform_point(ship, point) -> (x, y, z)` (Task 2).
- Produces: `subsystem_world_position(sub, ship=None)` unchanged in signature; its result now follows articulated parts.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_subsystem_part_parenting.py`:

```python
"""A subsystem mounted on an articulated part must move with that part.

THE LIVE BUG THIS FIXES: a Bird of Prey's Port/Star Cannon are authored at
(±1.008, 0.450, -0.670) — measured to be on the wingtips. The mount was
computed against the model's REST pose, so with the wings raised the beam
fired from ~0.9 ship units (~150 m) away from the drawn gun.

Normally hidden, because wings-up ⟺ weapons cold. But entering RED alert
powers weapons instantly while the wings take 2 s to come down, so the
cannons fire from progressively wrong positions for those two seconds —
exactly when combat starts.
"""
import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import subsystem_world_position


class _Sub:
    def __init__(self, pos):
        self._p = TGPoint3(*pos)

    def GetPosition(self):
        return self._p

    def _climb_to_ship(self):
        return None


class _Ship:
    """Identity rotation at the origin, so world == body and the assertions
    read as the body-frame offsets they are."""

    def __init__(self, deflection, leaf="birdofprey"):
        self._articulation_leaf = leaf
        self._d = deflection

    def GetArticulationDeflection(self):
        return self._d

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()


STAR_CANNON = (1.008, 0.450, -0.670)


def test_at_rest_the_mount_is_unchanged():
    w = subsystem_world_position(_Sub(STAR_CANNON), _Ship(0.0))
    assert (w.x, w.y, w.z) == pytest.approx(STAR_CANNON)


def test_with_the_wings_up_the_cannon_follows_the_wing():
    w = subsystem_world_position(_Sub(STAR_CANNON), _Ship(1.0))
    assert w.z > STAR_CANNON[2], "the cannon must rise with the wing"
    moved = math.dist((w.x, w.y, w.z), STAR_CANNON)
    assert moved > 0.5, "this is the ~150 m error the fix removes"


def test_a_body_mount_is_unaffected_at_any_deflection():
    warp_core = (0.0, -0.33, 0.0)
    w = subsystem_world_position(_Sub(warp_core), _Ship(1.0))
    assert (w.x, w.y, w.z) == pytest.approx(warp_core)


def test_an_unrigged_ship_is_byte_identical():
    w = subsystem_world_position(_Sub(STAR_CANNON), _Ship(1.0, "galaxy"))
    assert (w.x, w.y, w.z) == pytest.approx(STAR_CANNON)


def test_a_ship_without_articulation_support_still_works():
    """A prop or test double with no GetArticulationDeflection must not raise —
    this function is on the firing path for every weapon in the game."""
    class _Bare:
        def GetWorldLocation(self):
            return TGPoint3(0.0, 0.0, 0.0)

        def GetWorldRotation(self):
            return TGMatrix3()

    w = subsystem_world_position(_Sub(STAR_CANNON), _Bare())
    assert (w.x, w.y, w.z) == pytest.approx(STAR_CANNON)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/unit/test_subsystem_part_parenting.py -v`
Expected: FAIL on `test_with_the_wings_up_the_cannon_follows_the_wing` — the
mount is returned unchanged, so `w.z == -0.670` and `moved == 0.0`.

- [ ] **Step 3: Insert the part step**

In `engine/appc/subsystems.py`, replace lines 44-48 (from `offset = TGPoint3(...)` down to the `MultMatrixLeft` call) with:

```python
    # Follow the part this mount sits on, BEFORE rotating into world space:
    # articulation is a body-frame motion, so it composes inside R.
    # Identity for unrigged hulls, body mounts and deflection 0 — so the
    # overwhelming majority of calls are unchanged.
    from engine.appc.articulation import part_transform_point
    px, py, pz = part_transform_point(ship, (local.x, local.y, local.z))
    offset = TGPoint3(px, py, pz)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)   # R · offset (column-vector)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/unit/test_subsystem_part_parenting.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

If anything else fails, the likely cause is a test double that lacks
`GetArticulationDeflection` — `part_transform_point` already swallows that, so
investigate rather than widening the except.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_subsystem_part_parenting.py
git commit -m "fix(subsystems): a mount on an articulated part now follows it

subsystem_world_position computed ship_loc + R · local against the model's
REST pose, so a BoP's wingtip cannons stayed put while the wings moved —
~150 m off, and they fire from the stale point for the 2 s after RED alert
while the wings come down.

One choke point: _emitter_world_position (firing origins), the SPV pins,
phaser_overlay and target_reticle all route through it, so they agree by
construction. Identity at rest, on the body, and for unrigged hulls."
```

---

### Task 4: Pin rest-pose attribution, and correct the spec

**This task was rewritten during the pre-flight scan.** It originally said to
route `part_severance._destroy_subsystems_on_part` through
`part_transform_point`. That is wrong and would introduce a bug:

- `PART_BOXES` are authored in the model's **REST** pose.
- The voxel side **never sees `node_overrides`** (verified: no reference in
  `native/src/voxel/` or `carve_field_cache.cc`), and the `.dhv` SDF is baked
  from the NIF — so `hull_breakup`'s component bounds are rest-pose too.

**The whole SIM is rest-pose-consistent; only the RENDERER articulates.** Both
destroy-subsystem functions are already correct, and spec §4.1 symptom 2 — which
claims they are defective — is wrong. Task 3 is unaffected, because
`subsystem_world_position` feeds what is DRAWN and must match the moving mesh.

So this task pins the correct behaviour against a future "fix", and corrects the
spec.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md` (§4.1)
- Test: `tests/unit/test_part_severance.py`

**Interfaces:**
- Consumes: `articulation.part_transform_point` (Task 2) — only to prove it is
  NOT applied here.
- Produces: no code change.

- [ ] **Step 1: Write the regression test**

Extend the `_Ship` double in `tests/unit/test_part_severance.py` — add to its
`__init__`:

```python
        self._articulation_deflection = 0.0
```

and add the method:

```python
    def GetArticulationDeflection(self):
        return self._articulation_deflection
```

Then add this test:

```python
def test_subsystem_kill_uses_the_REST_mount_even_mid_travel():
    """Attribution here is a REST-pose question, and must stay one.

    PART_BOXES are authored in the model's rest pose, and the sim never
    articulates: the voxel field and the .dhv SDF are both built from the NIF
    and never see node_overrides. Only the RENDERER moves parts. So the
    authored mount is the right thing to test, at any deflection.

    This test exists because the implementation plan originally specified the
    opposite -- routing this through part_transform_point, so an ARTICULATED
    mount would be tested against REST boxes. That mismatches frames and
    misattributes. Caught in pre-flight; pinned here so it is not re-attempted.

    Contrast subsystem_world_position, which feeds what is DRAWN (beam
    origins, SPV pins) and therefore MUST articulate.
    """
    star = _Sub("Star Cannon", (1.008, 0.450, -0.670))
    body = _Sub("Warp Core", (0.0, -0.33, 0.0))
    ship = _Ship(subs=(star, body))
    ship._articulation_deflection = 0.5      # mid-travel: worst case

    ps.sever(ship, None, "left wing01")

    assert star.condition == 0.0, (
        "the cannon authored on the starboard wing must die with it, "
        "regardless of where the wing is currently drawn")
    assert body.condition == 100.0
```

- [ ] **Step 2: Run it — it must PASS immediately**

Run: `.venv/bin/python3 -m pytest tests/unit/test_part_severance.py -k REST_mount -v`
Expected: **PASS**. This is a characterisation test: it pins behaviour that is
already correct. If it FAILS, stop — something has already routed this through
the articulated frame, and that is the bug this test exists to prevent.

- [ ] **Step 3: Correct the spec**

In `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`, replace
the two numbered symptoms under `### 4.1 The defect` with:

```markdown
1. **RESOLVED 2026-09-23.** At full deflection a wingtip travelled ~0.85 ship
   units (~150 m) while the cannon hardpoint did not move. Normally hidden
   (wings-up <-> weapons cold), but entering red alert powers weapons instantly
   while the wings take 2 s to come down, so the cannons fired from
   progressively wrong positions for those two seconds — exactly when combat
   starts. Fixed by routing mounts through `articulation.part_transform_point`
   inside `subsystem_world_position`, the single choke point that firing
   origins, the SPV pins, `phaser_overlay` and `target_reticle` all share.
2. **WITHDRAWN 2026-09-23 — this was never a defect.** An earlier draft claimed
   `hull_breakup._destroy_subsystems_inside` and
   `part_severance._destroy_subsystems_on_part` were broken because they test a
   "static body-frame mount". They are correct: `PART_BOXES` are authored in the
   REST pose, the voxel side never sees `node_overrides`, and the `.dhv` SDF is
   baked from the NIF. **The whole SIM is rest-pose-consistent; only the
   RENDERER articulates.** Transforming the mount there would mismatch frames
   and misattribute. Pinned by
   `test_subsystem_kill_uses_the_REST_mount_even_mid_travel`.

   WARNING: this changes if the sim ever articulates — per-part hull volumes and
   picking (§4.3) would move the voxel and trace geometry into the live pose,
   and both functions would then need the transform.
```

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 5: Commit**

Stage exactly `tests/unit/test_part_severance.py` and
`docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md` (explicit
paths only — never `-A`), with this message:

```
test(severance): pin REST-pose attribution; withdraw spec 4.1 symptom 2

The spec claimed the destroy-subsystem functions were defective for testing a
static body-frame mount. They are not: PART_BOXES are authored in the rest
pose, the voxel side never sees node_overrides, and the .dhv SDF is baked from
the NIF. The whole SIM is rest-pose-consistent; only the RENDERER articulates.

Transforming the mount there would mismatch frames and misattribute -- which
the implementation plan originally specified. Caught in pre-flight and pinned
with a characterisation test so it is not re-attempted.
```

---

## Spec coverage

| spec section | covered by |
|---|---|
| §4.1 symptom 1 — emitters do not follow the part | Tasks 2 + 3 |
| §4.1 symptom 2 — sever-kill tests a static mount | **withdrawn** — not a defect; Task 4 pins the correct behaviour and corrects the spec |
| §4.2 — proximity-with-margin assignment | **already built** in phase 2a as `part_severance.part_for_point`; Tasks 2 and 4 consume it rather than reimplementing |
| §4.2 — "cached per ship, never per tick" | deliberate deviation, argued in Task 2 Step 5 |
| §4.3 — picking / hull volume / carve in part space | **out of scope**, see below |
| §4.4 — ordering ("hardpoint parenting is independently valuable and fixes the live bug") | this plan is exactly that slice |

## Verification

After Task 4, this is live-checkable and **should be checked before any further work** — the two previous live sessions were lost to failures no test could see.

Run from the main checkout (this project's worktree/live split):

```bash
./build/dauntless --developer
```

QuickBattle with a player **Bird of Prey**:

1. `Shift+1` (green) — wings rise over 2 s.
2. Press **H** (manual aim) and watch where the phaser beam originates. It should leave the **wingtip guns**, following them as they move.
3. `Shift+3` (red) — during the 2 s the wings are coming down, fire. Beams must track the moving guns, not lag at the rest position.

The failure this fixes looks like: beams emerging from empty space below and
inboard of the visible cannons.

## Out of scope

Deliberately not in this plan; all remain open in the spec:

- **§4.3 picking, hull volume, carve in part space.** `TraceAccel` is cached per MODEL and shared across instances, so posing it needs the per-part sub-BVH design. A raised wing is still not hittable at its drawn position.
- **§5b the SPV authoring panel** and the `model_part_bounds` binding — the spec says author a second ship by hand first.
- **OQ-2** seam hits mid-travel.
- **OQ-7** whether craters read blocky at the reduced carve radius.
