# Hull Damage Tessellation — Plan 6: Hit Trigger & Eligibility

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire weapon-hit events into the (already-built) GPU hull-deformation pipeline so dents and gouges actually appear in combat, and cap the per-frame cost to the player plus a bounded set of nearby/large ships.

**Architecture:** Two new pure-Python modules in `engine/appc/`: `hull_deformation.py` (maps absorbed hull damage → crater depth/radius in GU + the inward shove direction, mirroring `damage_decals.py`) and `deform_eligibility.py` (per-frame selection of the player + capped nearest/largest ships). `hit_feedback.dispatch` gains a deform-emission block that mirrors the existing decal block, gated additionally on a damage threshold and on eligibility, and throttled per-ship. `host_loop._advance_combat` refreshes the eligible set once per tick before hits are processed.

**Tech Stack:** Python 3 (`engine/appc/`), pytest. No C++ changes — the renderer, the `host.hull_deform_add` binding, the crater field, and the deform shaders all already exist on `main` (Plans 1–5b). This plan only feeds them.

**Design source:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` §4 (eligibility & cost control) and §6 (data flow hit → deformation).

---

## Design rationale (read before starting)

The crater field, the `host.hull_deform_add` binding (world→body transform + GU→model conversion), the tessellation routing in `frame.cc` (`deform = tessellation_available() && inst.craters.count() > 0`), and the dent/gouge shading are **already merged to `main`**. Nothing in C++ needs to change. Today no gameplay code ever calls `hull_deform_add`, so the hull never deforms in battle. This plan adds that call.

**Why eligibility is pure-Python gating on crater emission (no new C++ flag).** The spec §4 mentions plumbing a per-instance flag into `scenegraph::World`. That flag is only strictly required for the §5 *player-always-tessellated anti-pop baseline* (tessellating an **undamaged** player hull), which is deferred to Plan 7. For cost control in this plan, gating crater *emission* in Python is sufficient and simpler: a non-eligible ship never receives a crater, so `inst.craters.count()` stays 0 and `frame.cc` keeps it on the cheap static path automatically. A ship that was damaged while eligible and later drifts out of the eligible set keeps its craters (its damage persists, correctly) but its tessellation cost is already bounded by the adaptive-TCS camera-distance falloff. So no C++ change is needed here.

**Deferred to Plan 7 (do NOT build in this plan):** the §5 player always-on tessellation anti-pop baseline + conservative Phong smoothing, the second Modern VFX toggle ("Player hull smoothing/tessellation"), and the `scenegraph::World` per-instance force-tessellate flag. These are optional fidelity polish; damage appearance does not depend on them.

**Calibration is a deliverable note, not a task.** The depth/radius constants in `hull_deformation.py` and the shader's `RUPTURE_MIN`/`RUPTURE_MAX` (0.15/0.45 model units, in `opaque.frag`) are eye-tuning knobs. We cannot calibrate them here (calibration needs the live windowed game, which we do not run). The unit tests verify the *shape* of the mapping (monotonic, clamped, threshold-gated), not absolute visual correctness. The final report must flag these constants for the user to tune at review.

---

## File structure

- **Create** `engine/appc/hull_deformation.py` — pure mappings: damage→depth(GU), splash→radius(GU), inward shove direction, emission threshold + throttle interval. No host/renderer import. Mirrors `engine/appc/damage_decals.py`.
- **Create** `engine/appc/deform_eligibility.py` — pure `select_eligible(player, ships, *, max_count)` + module-level current-set state (`set_current` / `is_eligible` / `current` / `reset`) + an impure `update(ships)` glue that resolves the player via `App` and refreshes the set.
- **Modify** `engine/appc/hit_feedback.py` — add a `_last_deform_emit` throttle dict and a deform-emission block in `dispatch` after the decal block.
- **Modify** `engine/host_loop.py` — import `deform_eligibility`; call `deform_eligibility.update(ships_list)` at the top of `_advance_combat`.
- **Create** `tests/unit/test_hull_deformation.py`
- **Create** `tests/unit/test_deform_eligibility.py`
- **Create** `tests/unit/test_deform_emission.py`
- **Create** `tests/unit/test_advance_combat_eligibility.py`

---

### Task 1: `hull_deformation.py` — damage → crater mappings

**Files:**
- Create: `engine/appc/hull_deformation.py`
- Test: `tests/unit/test_hull_deformation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_hull_deformation.py`:

```python
"""Pure mappings: absorbed hull damage -> crater depth/radius (GU) and the
inward shove direction. Curve SHAPE is contractual; absolute values are
eye-calibration knobs (see plan 6 rationale)."""
import math

import pytest

from engine.appc import hull_deformation as hd


def test_should_deform_threshold():
    assert hd.should_deform(hd.MIN_DEFORM_HULL) is True
    assert hd.should_deform(hd.MIN_DEFORM_HULL + 1.0) is True
    assert hd.should_deform(hd.MIN_DEFORM_HULL - 0.001) is False
    assert hd.should_deform(0.0) is False


def test_crater_depth_monotonic_and_capped():
    assert hd.crater_depth_gu(0.0) == 0.0
    assert hd.crater_depth_gu(-5.0) == 0.0
    d_small = hd.crater_depth_gu(50.0)
    d_big = hd.crater_depth_gu(200.0)
    assert 0.0 < d_small < d_big
    # Saturates at the per-hit cap for very large hits (e.g. a ram).
    assert hd.crater_depth_gu(1.0e9) == pytest.approx(hd.MAX_CRATER_DEPTH_GU)


def test_crater_radius_scales_with_floor():
    # Scales the splash radius, but never below the floor.
    assert hd.crater_radius_gu(1.0) == pytest.approx(1.0 * hd.DEFORM_RADIUS_SCALE)
    assert hd.crater_radius_gu(0.0) == pytest.approx(hd.MIN_DEFORM_RADIUS_GU)


def test_impact_direction_falls_back_to_minus_normal():
    # No source/hit info -> push straight in along -normal (unit).
    d = hd.impact_direction((0.0, 0.0, 1.0))
    assert d == pytest.approx((0.0, 0.0, -1.0))


def test_impact_direction_uses_inward_weapon_ray():
    # Source above the +Z face firing down at the hit point -> ray is (0,0,-1).
    d = hd.impact_direction(
        (0.0, 0.0, 1.0), source_pos=(0.0, 0.0, 10.0), hit_point=(0.0, 0.0, 2.0))
    assert d == pytest.approx((0.0, 0.0, -1.0))
    assert math.isclose(d[0] ** 2 + d[1] ** 2 + d[2] ** 2, 1.0, rel_tol=1e-6)


def test_impact_direction_rejects_outward_ray():
    # A ray that points OUT of the surface (dot with -normal <= 0) is rejected
    # in favour of -normal, so the hull is never shoved outward.
    d = hd.impact_direction(
        (0.0, 0.0, 1.0), source_pos=(0.0, 0.0, 2.0), hit_point=(0.0, 0.0, 10.0))
    assert d == pytest.approx((0.0, 0.0, -1.0))


def test_impact_direction_degenerate_ray_falls_back():
    # source == hit_point -> zero ray -> fall back to -normal.
    d = hd.impact_direction(
        (0.0, 1.0, 0.0), source_pos=(5.0, 5.0, 5.0), hit_point=(5.0, 5.0, 5.0))
    assert d == pytest.approx((0.0, -1.0, 0.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_hull_deformation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.hull_deformation'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/hull_deformation.py`:

```python
"""Pure mappings for the persistent hull-deformation (crater) store.

No host / renderer dependency: absorbed hull damage -> crater depth (GU),
weapon splash radius -> crater radius (GU), and the inward shove direction.
The C++ HullCraterField owns the actual records (see
native/src/scenegraph/hull_craters.*) and converts GU -> model units; this
module only computes the scalar/vector inputs the emission path in
engine.appc.hit_feedback feeds to host.hull_deform_add.

Mirrors engine.appc.damage_decals. Constants here and the shader's
RUPTURE_MIN/RUPTURE_MAX (native/src/renderer/shaders/opaque.frag) are
eye-calibration knobs; see docs/superpowers/plans/...-plan6-hit-trigger.md.
"""

# Absorbed hull damage below this leaves only a scorch decal, no geometry
# crater. Set near the spark threshold (hit_feedback.SPARK_HULL_THRESHOLD =
# 80) so a torpedo/ram dents but per-tick phaser dribble (~0.28/tick) does
# not. Tuning knob.
MIN_DEFORM_HULL = 40.0

# GU of crater depth deposited per unit of absorbed hull damage, and the
# per-hit depth cap. The crater field also caps the *cumulative* merged depth
# (HullCraterField::kMaxDepth, in model units). Tuning knobs — calibrate by
# eye against the live renderer together with RUPTURE_MIN/MAX.
DEPTH_GU_PER_HULL = 0.0004
MAX_CRATER_DEPTH_GU = 0.5

# Crater radius = splash radius (GU) * scale, with a floor so a crater always
# has falloff extent. Independent of the decal radius scale. Tuning knobs.
DEFORM_RADIUS_SCALE = 1.5
MIN_DEFORM_RADIUS_GU = 0.15

# Game-time seconds between craters emitted on one ship, so a continuous beam
# cannot saturate the 24-slot crater field in a fraction of a second (mirrors
# hit_feedback.DECAL_EMIT_INTERVAL). Tuning knob.
DEFORM_EMIT_INTERVAL = 0.25


def should_deform(absorbed_hull: float) -> bool:
    """True iff this hit is heavy enough to deform geometry (vs scorch only)."""
    return float(absorbed_hull) >= MIN_DEFORM_HULL


def crater_depth_gu(absorbed_hull: float) -> float:
    """Map hull damage actually dealt to a crater depth in game units.

    Monotonic in absorbed_hull, saturating at MAX_CRATER_DEPTH_GU. Zero for
    non-positive input.
    """
    if absorbed_hull <= 0.0:
        return 0.0
    return min(MAX_CRATER_DEPTH_GU, float(absorbed_hull) * DEPTH_GU_PER_HULL)


def crater_radius_gu(splash_radius_gu: float) -> float:
    """Scale the gameplay splash radius (GU) to a crater radius (GU), floored
    so the displacement always has some extent."""
    return max(MIN_DEFORM_RADIUS_GU, float(splash_radius_gu) * DEFORM_RADIUS_SCALE)


def _normalize(v, fallback):
    """Unit vector for v=(x,y,z), or `fallback` when v is ~zero-length."""
    x, y, z = v
    m = (x * x + y * y + z * z) ** 0.5
    if m <= 1e-9:
        return fallback
    return (x / m, y / m, z / m)


def impact_direction(normal, source_pos=None, hit_point=None):
    """Unit inward shove direction in WORLD space, as an (x, y, z) tuple.

    Prefers the weapon ray (source -> hit point) when both positions are
    given and the ray points INTO the surface; otherwise falls back to the
    inward surface normal (-normal). The guard guarantees the hull is never
    displaced outward. All arguments are (x, y, z) tuples.
    """
    nx, ny, nz = normal
    inward = _normalize((-nx, -ny, -nz), fallback=(-nx, -ny, -nz))
    if source_pos is None or hit_point is None:
        return inward
    ray = _normalize(
        (hit_point[0] - source_pos[0],
         hit_point[1] - source_pos[1],
         hit_point[2] - source_pos[2]),
        fallback=None)
    if ray is None:
        return inward
    # Accept the ray only if it agrees with the inward direction.
    if ray[0] * inward[0] + ray[1] * inward[1] + ray[2] * inward[2] <= 0.0:
        return inward
    return ray
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_hull_deformation.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hull_deformation.py tests/unit/test_hull_deformation.py
git commit -m "feat(deform): hull_deformation damage->crater-depth/radius mappings"
```

---

### Task 2: `deform_eligibility.py` — player + capped nearest/largest selection

**Files:**
- Create: `engine/appc/deform_eligibility.py`
- Test: `tests/unit/test_deform_eligibility.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deform_eligibility.py`:

```python
"""Per-frame eligibility: player always included; remaining slots filled by a
proximity+size score; capped at max_count. Deterministic for fixed inputs."""
import pytest

from engine.appc import deform_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Ship:
    def __init__(self, pos=(0.0, 0.0, 0.0), radius=1.0):
        self._pos = pos
        self._radius = radius

    def GetWorldLocation(self):
        return _Pt(*self._pos)

    def GetRadius(self):
        return self._radius


@pytest.fixture(autouse=True)
def _clean():
    de.reset()
    yield
    de.reset()


def test_player_always_eligible_even_if_far_and_small():
    player = _Ship(pos=(1000.0, 0.0, 0.0), radius=0.1)
    near_big = _Ship(pos=(1.0, 0.0, 0.0), radius=50.0)
    ids = de.select_eligible(player, [player, near_big], max_count=1)
    # max_count=1 -> only the player fits, and the player always wins its slot.
    assert id(player) in ids
    assert id(near_big) not in ids


def test_cap_respected():
    player = _Ship()
    others = [_Ship(pos=(float(i), 0.0, 0.0), radius=1.0) for i in range(1, 10)]
    ids = de.select_eligible(player, [player] + others, max_count=4)
    assert len(ids) == 4
    assert id(player) in ids


def test_nearest_preferred_for_equal_size():
    player = _Ship(pos=(0.0, 0.0, 0.0))
    near = _Ship(pos=(2.0, 0.0, 0.0), radius=1.0)
    far = _Ship(pos=(500.0, 0.0, 0.0), radius=1.0)
    ids = de.select_eligible(player, [player, near, far], max_count=2)
    assert id(near) in ids
    assert id(far) not in ids


def test_largest_preferred_for_equal_distance():
    player = _Ship(pos=(0.0, 0.0, 0.0))
    big = _Ship(pos=(10.0, 0.0, 0.0), radius=80.0)
    small = _Ship(pos=(10.0, 0.0, 0.0), radius=1.0)
    ids = de.select_eligible(player, [player, big, small], max_count=2)
    assert id(big) in ids
    assert id(small) not in ids


def test_select_without_player_uses_size_only():
    big = _Ship(pos=(999.0, 0.0, 0.0), radius=50.0)
    small = _Ship(pos=(0.0, 0.0, 0.0), radius=1.0)
    ids = de.select_eligible(None, [big, small], max_count=1)
    assert id(big) in ids
    assert id(small) not in ids


def test_is_eligible_reads_current_set():
    s = _Ship()
    assert de.is_eligible(s) is False
    de.set_current(frozenset({id(s)}))
    assert de.is_eligible(s) is True
    de.reset()
    assert de.is_eligible(s) is False


def test_update_resolves_player_and_refreshes(monkeypatch):
    player = _Ship(pos=(0.0, 0.0, 0.0), radius=1.0)
    other = _Ship(pos=(1.0, 0.0, 0.0), radius=1.0)

    class _Game:
        def GetPlayer(self):
            return player

    import App
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)
    de.update([player, other])
    assert de.is_eligible(player) is True
    assert id(other) in de.current()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_deform_eligibility.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.deform_eligibility'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/deform_eligibility.py`:

```python
"""Per-frame hull-deformation eligibility.

Tessellated deformation is expensive, so only a bounded set of ships may
accumulate craters: the player (always) plus the N highest-scoring others,
where score combines proximity to the player and ship size (spec §4). The
selection result is stored as a module-level set of object ids that
engine.appc.hit_feedback reads before emitting a crater.

Pure selection lives in select_eligible(); update() is the impure glue that
resolves the current player via App and refreshes the stored set once per
combat tick (called from engine.host_loop._advance_combat).
"""

# Total eligible ships, INCLUDING the player. Tuning knob.
DEFAULT_MAX_ELIGIBLE = 6

# Score weights: proximity vs size. Tuning knobs.
PROX_WEIGHT = 1.0
SIZE_WEIGHT = 1.0

_current: frozenset = frozenset()


def _world_pos(ship):
    if not hasattr(ship, "GetWorldLocation"):
        return (0.0, 0.0, 0.0)
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _radius(ship) -> float:
    return float(ship.GetRadius()) if hasattr(ship, "GetRadius") else 0.0


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def select_eligible(player, ships, *, max_count: int = DEFAULT_MAX_ELIGIBLE):
    """Return a frozenset of id()s eligible for hull deformation.

    The player (if not None) always claims a slot. Remaining slots go to the
    highest-scoring other ships. With a player, score = PROX_WEIGHT * prox +
    SIZE_WEIGHT * size; without one, score = size only. Deterministic for
    fixed inputs (ties broken by id()).
    """
    ships = list(ships)
    eligible: set = set()
    if player is not None:
        eligible.add(id(player))

    player_pos = _world_pos(player) if player is not None else None
    max_r = max((_radius(s) for s in ships), default=0.0) or 1.0

    def score(s) -> float:
        size = _radius(s) / max_r
        if player_pos is None:
            return SIZE_WEIGHT * size
        prox = 1.0 / (1.0 + _dist(_world_pos(s), player_pos))
        return PROX_WEIGHT * prox + SIZE_WEIGHT * size

    others = [s for s in ships if player is None or id(s) != id(player)]
    others.sort(key=lambda s: (-score(s), id(s)))
    for s in others:
        if len(eligible) >= max_count:
            break
        eligible.add(id(s))
    return frozenset(eligible)


def set_current(ids) -> None:
    """Replace the stored eligible-id set."""
    global _current
    _current = frozenset(ids)


def current() -> frozenset:
    """The current eligible-id set."""
    return _current


def is_eligible(ship) -> bool:
    """True iff `ship` is in the current eligible set."""
    return id(ship) in _current


def reset() -> None:
    """Clear eligibility (tests, mission swaps, view-mode transitions)."""
    set_current(frozenset())


def update(ships) -> None:
    """Resolve the current player via App and refresh the eligible set.

    Called once per combat tick before hits are processed. Safe when no game
    / player is available (falls back to size-only selection).
    """
    try:
        import App
        game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
    except Exception:
        player = None
    set_current(select_eligible(player, ships))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_deform_eligibility.py -q`
Expected: PASS (7 tests).

> Note: `App` is the project-root shim (`App.py`). If `App.Game_GetCurrentGame` is absent in the shim, `monkeypatch.setattr(..., raising=False)` in the test adds it; the production `App` provides it. The `update()` body guards with `hasattr` either way.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/deform_eligibility.py tests/unit/test_deform_eligibility.py
git commit -m "feat(deform): per-frame deform eligibility (player + capped nearest/largest)"
```

---

### Task 3: emit `hull_deform_add` from `hit_feedback.dispatch`

**Files:**
- Modify: `engine/appc/hit_feedback.py` (add `_last_deform_emit` near line 66; add emission block after the decal block, ~line 250)
- Test: `tests/unit/test_deform_emission.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deform_emission.py`:

```python
"""dispatch must emit a hull-deform crater exactly when: hull damage clears
the deform threshold, a mesh normal is present, the renderer is present, the
hit is committed (not god mode), AND the target ship is deform-eligible.
Throttled per-ship. Mirrors test_decal_emission."""
import pytest

from engine.appc import hit_feedback
from engine.appc import damage_decals as dd
from engine.appc import hull_deformation as hd
from engine.appc import deform_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeHost:
    def __init__(self):
        self.deform_calls = []

    # Match the host_bindings.cc py::arg names exactly.
    def hull_deform_add(self, *, instance_id, world_point, world_normal,
                        world_impact_dir, radius, depth):
        self.deform_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, world_impact_dir=world_impact_dir,
            radius=radius, depth=depth))


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()


@pytest.fixture
def patched(monkeypatch):
    # Deterministic clock; clear per-ship throttle and eligibility between tests.
    monkeypatch.setattr(dd, "current_game_time", lambda: 100.0)
    hit_feedback._last_deform_emit.clear()
    de.reset()
    yield monkeypatch
    hit_feedback._last_deform_emit.clear()
    de.reset()


def _dispatch(host, ship, *, absorbed_hull, normal=_Pt(0, 0, 1),
              persist_decal=True, source=None, radius=0.2):
    hit_feedback.dispatch(
        ship=ship, source=source, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        host=host, ship_instances={ship: "IID"},
        weapon_type="torpedo", radius=radius, persist_decal=persist_decal,
    )


def test_deform_emitted_on_strong_eligible_hit(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert len(host.deform_calls) == 1
    call = host.deform_calls[0]
    assert call["instance_id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["world_normal"] == (0, 0, 1)
    # source=None -> impact dir is the inward normal.
    assert call["world_impact_dir"] == pytest.approx((0.0, 0.0, -1.0))
    assert call["radius"] == pytest.approx(hd.crater_radius_gu(0.2))
    assert call["depth"] == pytest.approx(
        hd.crater_depth_gu(hd.MIN_DEFORM_HULL + 60.0))


def test_no_deform_below_threshold(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL - 1.0)
    assert host.deform_calls == []


def test_no_deform_when_not_eligible(patched):
    host = _FakeHost()
    ship = _Ship()
    # eligibility set is empty (reset in fixture)
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert host.deform_calls == []


def test_no_deform_without_normal(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0, normal=None)
    assert host.deform_calls == []


def test_no_deform_under_god_mode(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0,
              persist_decal=False)
    assert host.deform_calls == []


def test_deform_throttled_per_ship(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    # Two hits at the same (frozen) game time -> second is throttled out.
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert len(host.deform_calls) == 1


def test_headless_host_none_is_safe(patched):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(None, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)


def test_impact_dir_uses_weapon_ray(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))

    class _Src:
        def GetWorldLocation(self):
            # Above the +Z hit face; ray to hit point (1,2,3) points down-ish.
            return _Pt(1.0, 2.0, 13.0)

    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0, source=_Src())
    # Ray (0,0,-10) normalized = (0,0,-1); agrees with inward normal -> used.
    assert host.deform_calls[0]["world_impact_dir"] == pytest.approx((0.0, 0.0, -1.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_deform_emission.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.hit_feedback' has no attribute '_last_deform_emit'` (and the deform emission does not happen yet).

- [ ] **Step 3: Add the throttle dict**

In `engine/appc/hit_feedback.py`, immediately after the existing `_last_decal_emit` definition (line 66), add:

```python
# Hull-deformation emission throttle, parallel to _last_decal_emit. Keyed by
# id(ship) only (a crater is weapon-agnostic geometry, unlike a decal class).
_last_deform_emit: dict = {}  # id(ship) -> last emit game-time
```

- [ ] **Step 4: Add the emission block**

In `engine/appc/hit_feedback.py`, at the END of `dispatch` (immediately after the decal `if` block that ends at line ~250, before the function returns), add:

```python
    # 5. Persistent hull deformation — tessellated dent/gouge crater. Same
    # hull-absorbing, mesh-normal, renderer-present, committed-hit gating as
    # the decal, PLUS: the hit must clear the deform threshold (phaser dribble
    # scorches but does not dent) and the target must be deform-eligible
    # (player + capped nearest/largest; see engine.appc.deform_eligibility).
    # Throttled per-ship so a sustained beam cannot saturate the crater field.
    if (persist_decal and normal is not None and host is not None
            and ship_instances is not None
            and hasattr(host, "hull_deform_add")):
        from engine.appc import hull_deformation, deform_eligibility, damage_decals
        if (hull_deformation.should_deform(absorbed_hull)
                and deform_eligibility.is_eligible(ship)):
            iid = ship_instances.get(ship)
            if iid is not None:
                now = damage_decals.current_game_time()
                key = id(ship)
                if (now - _last_deform_emit.get(key, -1e9)
                        >= hull_deformation.DEFORM_EMIT_INTERVAL):
                    _last_deform_emit[key] = now
                    src_pos = None
                    if source is not None and hasattr(source, "GetWorldLocation"):
                        sp = source.GetWorldLocation()
                        src_pos = (sp.x, sp.y, sp.z)
                    impact_dir = hull_deformation.impact_direction(
                        (normal.x, normal.y, normal.z),
                        source_pos=src_pos,
                        hit_point=(point.x, point.y, point.z))
                    host.hull_deform_add(
                        instance_id=iid,
                        world_point=(point.x, point.y, point.z),
                        world_normal=(normal.x, normal.y, normal.z),
                        world_impact_dir=impact_dir,
                        radius=hull_deformation.crater_radius_gu(radius),
                        depth=hull_deformation.crater_depth_gu(absorbed_hull),
                    )
```

> The deform block calls `host.hull_deform_add` directly (kwargs match the `host_bindings.cc` `py::arg` names), exactly as the decal block calls `host.damage_decal_add` directly. The `engine/renderer.py` wrapper is for host_loop-side callers and is intentionally not used here.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_deform_emission.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Run the existing decal/dispatch suites to confirm no regression**

Run: `uv run pytest tests/unit/test_decal_emission.py tests/unit/test_torpedo_decal_emission.py tests/unit/test_hit_feedback_dispatch.py tests/unit/test_hit_feedback_classify.py -q`
Expected: PASS (all existing tests unchanged).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/hit_feedback.py tests/unit/test_deform_emission.py
git commit -m "feat(deform): emit hull_deform_add from hit_feedback (gated + throttled)"
```

---

### Task 4: refresh eligibility per tick in `host_loop._advance_combat`

**Files:**
- Modify: `engine/host_loop.py` (import block at lines 55-64; `_advance_combat` at line 325)
- Test: `tests/unit/test_advance_combat_eligibility.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_advance_combat_eligibility.py`:

```python
"""_advance_combat must refresh deform eligibility once per tick, with the
tick's ship list, BEFORE hits are processed. Collaborators are stubbed so the
test exercises only the eligibility seam."""
import engine.host_loop as host_loop
from engine.appc import deform_eligibility as de
from engine.appc import projectiles, hit_vfx, particles, ship_death
from engine.appc import subsystem_emitters, camera_shake


class _Ship:
    def GetPhaserSystem(self):
        return None  # skip the phaser damage loop


def test_advance_combat_updates_eligibility(monkeypatch):
    calls = []
    monkeypatch.setattr(de, "update", lambda ships: calls.append(list(ships)))

    # Stub everything else _advance_combat touches so an empty/None world is safe.
    monkeypatch.setattr(projectiles, "update_all", lambda *a, **k: [])
    monkeypatch.setattr(hit_vfx, "update_ages", lambda *a, **k: None)
    monkeypatch.setattr(particles, "advance", lambda *a, **k: None)
    monkeypatch.setattr(ship_death, "advance", lambda *a, **k: None)
    monkeypatch.setattr(subsystem_emitters, "pump", lambda *a, **k: None)
    monkeypatch.setattr(camera_shake, "update", lambda *a, **k: None)
    monkeypatch.setattr(host_loop, "_camera_world_pos", lambda host: None)

    s1, s2 = _Ship(), _Ship()
    host_loop._advance_combat([s1, s2], 0.016, host=None, ship_instances={})

    assert calls == [[s1, s2]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_advance_combat_eligibility.py -q`
Expected: FAIL — `calls == []` (the assertion fails) because `_advance_combat` does not yet call `deform_eligibility.update`.

- [ ] **Step 3: Add the import**

In `engine/host_loop.py`, add `deform_eligibility,` to the existing `from engine.appc import (...)` block (lines 55-64). The block becomes:

```python
from engine.appc import (
    projectiles,
    hit_vfx,
    particles,
    ship_death,
    subsystem_emitters,
    camera_shake,
    hit_feedback,
    combat,
    deform_eligibility,
)
```

- [ ] **Step 4: Call update at the top of `_advance_combat`**

In `engine/host_loop.py`, in `_advance_combat`, immediately after `ships_list = list(ships)` (line 325), add:

```python
    # Refresh hull-deformation eligibility for this tick before any hits are
    # processed, so hit_feedback gates crater emission against a fresh set
    # (player + capped nearest/largest). See engine.appc.deform_eligibility.
    deform_eligibility.update(ships_list)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_advance_combat_eligibility.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_advance_combat_eligibility.py
git commit -m "feat(deform): refresh deform eligibility per combat tick"
```

---

### Task 5: full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the new and adjacent Python suites**

Run:
```bash
uv run pytest tests/unit/test_hull_deformation.py \
  tests/unit/test_deform_eligibility.py \
  tests/unit/test_deform_emission.py \
  tests/unit/test_advance_combat_eligibility.py \
  tests/unit/test_decal_emission.py \
  tests/unit/test_hit_feedback_dispatch.py \
  tests/unit/test_combat_hit_resolution.py -q
```
Expected: all PASS.

- [ ] **Step 2: Run the full Python suite (scoped to tests/, from repo root)**

Run: `uv run pytest tests/ -q`
Expected: full suite green (no regressions; new tests added).

> Note: run from the repo root, not `build/`, and scope to `tests/` — the `build/_deps/` third-party trees contain their own pytest files that error on collection.

- [ ] **Step 3: Confirm no C++ changes were needed**

Run: `git diff --name-only main -- native/`
Expected: empty output (this plan is Python-only).

---

## Out of scope / follow-up (Plan 7, optional)

The following were deliberately deferred and are NOT in this plan:

1. **Player always-on tessellation (anti-pop baseline) + conservative Phong smoothing** (spec §5). Requires a `scenegraph::World` per-instance force-tessellate flag, a `frame.cc` routing change (`deform = ... && (craters.count() > 0 || force_tessellate)`), a TCS low baseline tess level for the player, and curvature-aware Phong smoothing in the TES. This is fidelity polish; damage still appears without it (the player tessellates as soon as it takes its first crater).
2. **Second Modern VFX toggle — "Player hull smoothing/tessellation"** (spec §7) — gates the §5 behaviour. The first toggle ("Procedural hull damage") already shipped in Plan 5b.

## Calibration note for review (carry into the final report)

These constants are eye-tuning knobs and could not be calibrated here (calibration needs the live windowed game):

- `engine/appc/hull_deformation.py`: `MIN_DEFORM_HULL`, `DEPTH_GU_PER_HULL`, `MAX_CRATER_DEPTH_GU`, `DEFORM_RADIUS_SCALE`, `MIN_DEFORM_RADIUS_GU`, `DEFORM_EMIT_INTERVAL`.
- `native/src/renderer/shaders/opaque.frag`: `RUPTURE_MIN` (0.15), `RUPTURE_MAX` (0.45) — the model-unit depths at which a dent becomes a gouge.
- `engine/appc/deform_eligibility.py`: `DEFAULT_MAX_ELIGIBLE`, `PROX_WEIGHT`, `SIZE_WEIGHT`.

The crater field converts GU depth → model units by dividing by the instance scale `s`; the depth constants must be tuned together with `RUPTURE_MIN/MAX` once a real ship's `s` is observed in the running renderer.
