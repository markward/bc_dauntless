# Sensor Continuity and Occlusion (sub-project 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Major rocks hide contacts by line of sight (for player and AI); ships inside asteroid fields or moderate nebula read Unknown; concealment shorter than a dialled window keeps identity silently, longer loses the track.

**Architecture:** Two new single-idea modules — `sensor_occlusion` (does a major rock block A→B, cached per tick) and `sensor_media` (is the target inside an identity-hiding medium) — plug into the existing one rule `sensor_detection.can_detect` and into the player-only contact manager `sensor_contacts`, which gains the continuity clock and ONE display answer, `shows_identity(obj)`, that the target list, the reticle and the Science button label all read. Mission guards for E5M2 and Helm's delayed hail button sit in their own module.

**Tech Stack:** Python engine shim (`engine/appc/`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-sensor-continuity-occlusion-design.md` (roadmap `2026-10-03-sensor-model-roadmap.md`, decisions 7–11).

## Global Constraints

- Work ONLY in `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/sensor-tiers` on branch `feat/sensor-continuity`. Never commit to main; never push.
- BANNED git: `checkout -- <path>`, `checkout .`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`, `add .`. Stage explicit paths. Temporary mutation: `cp` backup, edit, run, `cp` restore, `diff`.
- NEVER `pkill`/`killall`. NEVER launch the game (Task 7 is the controller's, after Mark approves).
- Tests: `uv run pytest <path> -q` from the worktree root.
- Dial defaults (all in `engine/appc/sensor_dials.py`, nowhere else): `continuity_window_s` **5.0**, `min_blocker_radius_gu` **2.0**, `field_unknown_threshold` **0.5**, `nebula_unknown_threshold` **0.14**.
- A major rock = `isinstance(obj, RockClass)` (engine/rocks/rock.py) in the observer's set with `rocks.rock.effective_radius(obj) >= min_blocker_radius_gu`. Never `GetRadius()` alone (ignores scale). Planets, suns, ships, minor/near-band rocks never occlude.
- Occlusion test: segment observer-centre → target-centre vs the rock's sphere; observer and target themselves excluded.
- Occlusion is skipped entirely when `sensor_detection.ENHANCED_SENSOR_CONTEST` is False.
- Concealed (player only) = in the player's set ∧ inside player sensor range ∧ (`not can_detect(player, obj)` ∨ `sensor_media.medium_unknown(obj)`). Leaving range is never concealment.
- Lost track = `RemoveKnownObject` + `Bridge.HelmMenuHandlers.ExitedSet(obj)` called directly. NEVER post a synthetic `ET_EXITED_SET`.
- `shows_identity(obj)` is the ONE display answer for the target-list caption, the reticle name and the Science Scan button label. Never re-derive it at a call site.
- Never put a game-state mutation in a panel's `render_payload`.
- Check `docs/stub_heatmap.md` before claiming an SDK call is a no-op; never grep `def <Name>(` to decide surface exists.
- When a call changes meaning, grep the tests that named it and confirm each still bites (mutation check with `cp`/`diff`).

## Review Focus

1. **Moving a ship or rock within the same game time** (tests, or two queries in one tick) must not return a stale occlusion answer when set membership changed. (Task 2 `test_adding_a_rock_in_the_same_tick_is_seen`.)
2. **A contact hidden by a rock that leaves sensor range while hidden** — the clock must stop (range loss is not concealment), identity survives. (Task 4 `test_leaving_range_while_hidden_stops_the_clock`.)
3. **A scanned ship inside a field** — exactly one window of real name, then lost track while still inside. (Task 4 `test_scan_in_field_gives_exactly_one_window`.)
4. **The three display surfaces agree** for an in-field identified ship in its first 5 s: list caption, reticle and Science button all show "Unknown N". (Task 4 `test_list_reticle_and_science_agree_in_field`.)
5. **The player's own ship and the target are never their own occluders**, even when one is a RockClass (rocks can be targeted). (Task 2 `test_endpoints_never_occlude`.)

---

## File structure

| File | Responsibility |
|---|---|
| `engine/appc/sensor_dials.py` | + four dials |
| `engine/appc/sensor_occlusion.py` (new) | Does a major rock block the line A→B (per-tick cache) |
| `engine/appc/sensor_media.py` (new) | Is a target inside an identity-hiding medium; are its subsystems hidden |
| `engine/appc/sensor_detection.py` | `can_detect` gains the occlusion gate |
| `engine/appc/sensor_contacts.py` | continuity clock, lost track, `shows_identity`, scan glimpse, Science label sync |
| `engine/appc/perception.py`, `engine/appc/ai_driver.py`, `engine/ui/reticle_text.py`, `engine/appc/science_scan_labels.py` | read `shows_identity` / `subsystems_hidden` |
| `engine/appc/sensor_mission_guards.py` (new) | E5M2 Outpost guard; Helm `AddHailButton` re-check |
| `engine/host_loop.py` | install guards beside `science_scan_labels.install()` (2 sites) |
| `tests/conftest.py` | autouse reset of new module state |
| `tests/helpers/rocks.py` (new) | `make_major_rock(pSet, name, at, radius_gu)` fixture helper |

---

### Task 1: Four new sensor dials

**Files:**
- Modify: `engine/appc/sensor_dials.py`
- Test: `tests/unit/test_sensor_dials.py` (extend)

**Interfaces:**
- Produces: `sensor_dials.get("continuity_window_s"|"min_blocker_radius_gu"|"field_unknown_threshold"|"nebula_unknown_threshold") -> float`.

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_sensor_dials.py`):

```python
def test_continuity_and_occlusion_dials_defaults_and_order():
    sensor_dials.reset()
    assert sensor_dials.get("continuity_window_s") == 5.0
    assert sensor_dials.get("min_blocker_radius_gu") == 2.0
    assert sensor_dials.get("field_unknown_threshold") == 0.5
    assert sensor_dials.get("nebula_unknown_threshold") == 0.14
    assert sensor_dials.DIAL_ORDER[:3] == (
        "identification_time_s", "near_fraction", "sweep_period_s")
    assert set(sensor_dials.DIAL_ORDER[3:]) == {
        "continuity_window_s", "min_blocker_radius_gu",
        "field_unknown_threshold", "nebula_unknown_threshold"}


def test_new_dials_step_and_clamp():
    d = dict(sensor_dials.DEFAULTS)
    assert sensor_dials.step(d, "continuity_window_s", +1)["continuity_window_s"] == 5.5
    assert sensor_dials.step(d, "min_blocker_radius_gu", -1)["min_blocker_radius_gu"] == 1.75
    assert sensor_dials.step(d, "field_unknown_threshold", +1)["field_unknown_threshold"] == 0.55
    assert sensor_dials.step(d, "nebula_unknown_threshold", +1)["nebula_unknown_threshold"] == 0.15
    low = dict(d, continuity_window_s=0.5, min_blocker_radius_gu=0.25,
               field_unknown_threshold=0.05, nebula_unknown_threshold=0.01)
    for name in ("continuity_window_s", "min_blocker_radius_gu",
                 "field_unknown_threshold", "nebula_unknown_threshold"):
        assert sensor_dials.step(low, name, -1)[name] == low[name]
    high = dict(d, field_unknown_threshold=1.0, nebula_unknown_threshold=1.0)
    assert sensor_dials.step(high, "field_unknown_threshold", +1)["field_unknown_threshold"] == 1.0
    assert sensor_dials.step(high, "nebula_unknown_threshold", +1)["nebula_unknown_threshold"] == 1.0
```

- [ ] **Step 2: Run** — `uv run pytest tests/unit/test_sensor_dials.py -q` → FAIL (KeyError).

- [ ] **Step 3: Implement** — extend the three dicts in `sensor_dials.py`, keeping existing entries first:

```python
DEFAULTS: dict = {
    "identification_time_s": 4.0,
    "near_fraction": 0.5,
    "sweep_period_s": 1.0,
    # Sub-project 2 (2026-10-05-sensor-continuity-occlusion-design.md) --
    # play-test dials, not recovered BC values.
    "continuity_window_s": 5.0,       # Mark's rule: concealed < this keeps identity
    "min_blocker_radius_gu": 2.0,     # rocks smaller than this never occlude
    "field_unknown_threshold": 0.5,   # field a(x) at/above this reads Unknown
    "nebula_unknown_threshold": 0.14, # half of sensor_detection.LOCK_BREAK_T
}
_STEP = {"identification_time_s": 0.5, "near_fraction": 0.05,
         "sweep_period_s": 0.25, "continuity_window_s": 0.5,
         "min_blocker_radius_gu": 0.25, "field_unknown_threshold": 0.05,
         "nebula_unknown_threshold": 0.01}
_MIN = {"identification_time_s": 0.5, "near_fraction": 0.05,
        "sweep_period_s": 0.25, "continuity_window_s": 0.5,
        "min_blocker_radius_gu": 0.25, "field_unknown_threshold": 0.05,
        "nebula_unknown_threshold": 0.01}
_MAX = {"near_fraction": 1.0, "field_unknown_threshold": 1.0,
        "nebula_unknown_threshold": 1.0}
```

Update the module docstring: the first three are BC's (RE'd), the last four are play-test dials.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_dev_dial_groups.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_dials.py tests/unit/test_sensor_dials.py
git commit -m "feat(sensors): continuity window, blocker size and medium thresholds dials"
```

---

### Task 2: Occlusion by major rocks, gated into can_detect

**Files:**
- Create: `engine/appc/sensor_occlusion.py`
- Create: `tests/helpers/rocks.py`
- Modify: `engine/appc/sensor_detection.py` (`can_detect`, module docstring)
- Modify: `tests/conftest.py` (autouse reset)
- Test: `tests/unit/test_sensor_occlusion.py`, `tests/unit/test_sensor_occlusion_bench.py`

**Interfaces:**
- Consumes: `sensor_dials.get("min_blocker_radius_gu")`; `engine.rocks.rock.RockClass`, `effective_radius`; `contact_index.ships_in(pSet)`; `engine.appc.subsystems._get_xyz`.
- Produces: `sensor_occlusion.blocked(observer, target) -> bool`; `sensor_occlusion.reset() -> None`. `tests/helpers/rocks.make_major_rock(pSet, name, at=(x,y,z), radius_gu=3.0)` → a RockClass in `pSet` whose `effective_radius` equals `radius_gu`.

- [ ] **Step 1: Write the helper and the failing tests**

`tests/helpers/rocks.py` — build a genus-asteroid ship the way `tests/unit/test_rock_class.py::_make` does (ShipProperty genus `App.GENUS_ASTEROID`, HullProperty, `SetupProperties()` → it becomes `RockClass`), then make `effective_radius(rock) == radius_gu` (read `engine/rocks/rock.py:effective_radius`: base = `GetRadius()` if > 0 else hull radius; × `GetScale()` — set the hull radius to `radius_gu` and leave scale 1, or set scale; assert `effective_radius(rock) == radius_gu` inside the helper so a wrong construction fails loudly), position it with `SetTranslateXYZ(*at)`, and `pSet.AddObjectToSet(rock, name)`. Return the rock.

`tests/unit/test_sensor_occlusion.py`:

```python
"""Major rocks block line of sight (sensor continuity/occlusion spec)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import sensor_occlusion, sensor_dials
from engine.appc import sensor_detection as sd
from tests.helpers.rocks import make_major_rock


def _ship(s, name, x, base_range=2000.0):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    s.AddObjectToSet(ship, name)
    return ship


def test_rock_on_the_line_blocks():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is True
    assert sd.can_detect(a, b) is False


def test_rock_off_the_line_does_not_block():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 10.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is False
    assert sd.can_detect(a, b) is True


def test_small_rock_never_blocks_and_the_dial_moves_the_line():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Pebble", at=(50.0, 0.0, 0.0), radius_gu=1.5)
    assert sensor_occlusion.blocked(a, b) is False
    sensor_dials._dials["min_blocker_radius_gu"] = 1.0
    sensor_occlusion.reset()
    assert sensor_occlusion.blocked(a, b) is True


def test_rock_beyond_the_target_does_not_block():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(150.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is False


def test_endpoints_never_occlude():
    s = SetClass()
    a = _ship(s, "A", 0.0)
    rock_target = make_major_rock(s, "BigRock", at=(100.0, 0.0, 0.0), radius_gu=40.0)
    assert sensor_occlusion.blocked(a, rock_target) is False


def test_scaled_radius_is_used_not_raw_get_radius():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    rock = make_major_rock(s, "Rock", at=(50.0, 2.5, 0.0), radius_gu=1.0)
    rock.SetScale(3.0)                      # effective 3.0 GU: now covers y=2.5
    sensor_occlusion.reset()
    assert sensor_occlusion.blocked(a, b) is True


def test_adding_a_rock_in_the_same_tick_is_seen():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    assert sensor_occlusion.blocked(a, b) is False
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is True     # no reset, same game time


def test_toggle_off_skips_occlusion(monkeypatch):
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert sd.can_detect(a, b) is True


def test_ai_candidate_filter_respects_occlusion():
    from engine.appc import ai_sensor_gate
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    gated = ai_sensor_gate._wrap_active_tuple(lambda self, pSet: (b,))
    with ai_sensor_gate.observing(a):
        assert gated(None, s) == ()
```

If `App.GENUS_ASTEROID` is spelled differently in this tree, use the constant `tests/unit/test_rock_class.py`/`engine/rocks/rock.py` actually use. If `make_major_rock` cannot make `SetScale` affect `effective_radius` in `test_scaled_radius_is_used_not_raw_get_radius`, read `effective_radius` again and construct accordingly — the test's purpose is "scale counts".

- [ ] **Step 2: Run** — `uv run pytest tests/unit/test_sensor_occlusion.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** `engine/appc/sensor_occlusion.py`:

```python
"""Does a major rock block the line of sight from A to B?
(sensor continuity/occlusion spec, roadmap decision 7)

A major rock is a RockClass in A's set whose SCALED radius
(rocks.rock.effective_radius -- never GetRadius() alone, which ignores
SetScale) is at least the `min_blocker_radius_gu` dial. The test is the
segment between the two centres against each rock's sphere; A and B are never
their own occluders. Planets, suns, ships and minor/near-band rocks never
occlude; fields between ships never occlude.

Cost: can_detect has a dozen callers, some per frame and per torpedo, so
answers are cached per (A, B) for the current game time, and each set's list of
major rocks is cached per game time AND per bucket size -- a rock added or
removed within the same tick (tests, spawns, breakups) changes the bucket size
and invalidates it. Never raises: a failure answers "not blocked" and is logged.
"""
import weakref

import App
import engine.dev_mode as dev_mode
from engine.appc import sensor_dials

_pair_cache: dict = {}          # (id(a), id(b)) -> bool, valid for _cache_key
_cache_key = None               # (game_time, bucket-size signature)
_rock_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def reset() -> None:
    global _cache_key
    _pair_cache.clear()
    _rock_cache.clear()
    _cache_key = None


def _now() -> float:
    try:
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        return 0.0


def _major_rocks(pset, now):
    """(rock, x, y, z, r) for every major rock in *pset*, cached per tick and
    per bucket size."""
    from engine.appc import contact_index
    from engine.appc.subsystems import _get_xyz
    from engine.rocks.rock import RockClass, effective_radius
    ships = contact_index.ships_in(pset)
    min_r = sensor_dials.get("min_blocker_radius_gu")
    sig = (now, len(ships), min_r)
    hit = _rock_cache.get(pset)
    if hit is not None and hit[0] == sig:
        return hit[1]
    rocks = []
    for s in ships:
        if isinstance(s, RockClass):
            r = effective_radius(s)
            if r >= min_r:
                x, y, z = _get_xyz(s)
                rocks.append((s, x, y, z, r))
    rocks = tuple(rocks)
    _rock_cache[pset] = (sig, rocks)
    return rocks


def _segment_hits(ax, ay, az, bx, by, bz, cx, cy, cz, r) -> bool:
    dx, dy, dz = bx - ax, by - ay, bz - az
    seg2 = dx * dx + dy * dy + dz * dz
    px, py, pz = cx - ax, cy - ay, cz - az
    t = 0.0 if seg2 <= 1e-12 else (px * dx + py * dy + pz * dz) / seg2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    qx, qy, qz = px - t * dx, py - t * dy, pz - t * dz
    return qx * qx + qy * qy + qz * qz < r * r


def blocked(observer, target) -> bool:
    global _cache_key
    try:
        pset = observer.GetContainingSet()
        if pset is None:
            return False
        now = _now()
        rocks = _major_rocks(pset, now)
        if not rocks:
            return False
        key_sig = (now, id(pset), len(rocks))
        if _cache_key != key_sig:
            _pair_cache.clear()
            _cache_key = key_sig
        pair = (id(observer), id(target))
        hit = _pair_cache.get(pair)
        if hit is not None:
            return hit
        from engine.appc.subsystems import _get_xyz
        ax, ay, az = _get_xyz(observer)
        bx, by, bz = _get_xyz(target)
        answer = False
        for rock, cx, cy, cz, r in rocks:
            if rock is observer or rock is target:
                continue
            if _segment_hits(ax, ay, az, bx, by, bz, cx, cy, cz, r):
                answer = True
                break
        _pair_cache[pair] = answer
        return answer
    except Exception as e:
        dev_mode.log_swallowed("sensor_occlusion.blocked", e)
        return False
```

Note the pair cache is a single flat dict keyed by `id()`s and cleared whenever the (time, set, rock-count) signature changes; ids are safe for one tick because `engine/core/ids.py` pins every TGObject for the process lifetime. If multiple sets are queried in one tick the cache thrashes but stays correct — acceptable (the player's set dominates).

In `sensor_detection.can_detect`, after the `if cloaked: r = ...` line and BEFORE the nebula concealment gate, add:

```python
    # ── Occlusion gate (sub-project 2) ────────────────────────────────────
    # A major rock on the line of sight hides the target from everyone --
    # list, radar, weapons, torpedoes and AI alike. Part of the sensing
    # contest, so the stage-4 toggle switches it off with the rest.
    if ENHANCED_SENSOR_CONTEST:
        from engine.appc import sensor_occlusion
        if sensor_occlusion.blocked(observer, target):
            return False
```

Update `can_detect`'s docstring and the module docstring to name the occlusion gate. Add to `tests/conftest.py` autouse reset (same try/except shape as the other sensor resets): `sensor_occlusion.reset()`.

- [ ] **Step 4: Benchmark test** `tests/unit/test_sensor_occlusion_bench.py`: build one set with 30 ships (sensors as above) spread over ±800 GU and 54 major rocks scattered in the same volume; time a "frame" = every ship asks `can_detect` of every other ship once, then two more passes (cached); compare against the same frame with the 54 rocks removed (fresh set). Run each 5 times, take the best. Assert `with_rocks <= 3.0 * without_rocks`. Before committing, run it 5 times and record the measured ratios in your report; if the ratio is above 3.0, STOP and report BLOCKED with the numbers rather than raising the budget.

- [ ] **Step 5: Run** — `uv run pytest tests/unit/test_sensor_occlusion.py tests/unit/test_sensor_occlusion_bench.py tests/unit -q -k "sensor or cloak or nebula or detect or occlu or rock"` → PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sensor_occlusion.py engine/appc/sensor_detection.py tests/helpers/rocks.py tests/conftest.py tests/unit/test_sensor_occlusion.py tests/unit/test_sensor_occlusion_bench.py
git commit -m "feat(sensors): major rocks block line of sight in can_detect"
```

---

### Task 3: Identity-hiding media; subsystems hidden for player and AI

**Files:**
- Create: `engine/appc/sensor_media.py`
- Modify: `engine/appc/perception.py` (`subsystems_targetable`)
- Modify: `engine/appc/ai_driver.py:~1137` (subsystem aim fallback)
- Test: `tests/unit/test_sensor_media.py`

**Interfaces:**
- Consumes: `sensor_dials.get("field_unknown_threshold"|"nebula_unknown_threshold")`; `engine.rocks.far_tier.field_strength_at(obj) -> float`; `sensor_detection.concealment_at(obj) -> float`, `is_hidden_by_cloak(obj) -> bool`.
- Produces: `sensor_media.medium_unknown(obj) -> bool`; `sensor_media.subsystems_hidden(obj) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
"""Identity-hiding media (spec: 'Unknown by medium')."""
from engine.appc import sensor_media, sensor_dials
from engine.appc import sensor_detection as sd
import engine.rocks.far_tier as far_tier


class _Obj:
    pass


def test_field_at_or_above_threshold_hides_identity(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.0)
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.5)
    assert sensor_media.medium_unknown(o) is True
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.49)
    assert sensor_media.medium_unknown(o) is False


def test_moderate_nebula_hides_identity(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.0)
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.14)
    assert sensor_media.medium_unknown(o) is True
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.13)
    assert sensor_media.medium_unknown(o) is False


def test_thresholds_are_dials(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.0)
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.3)
    sensor_dials._dials["field_unknown_threshold"] = 0.25
    assert sensor_media.medium_unknown(o) is True


def test_subsystems_hidden_by_medium_or_cloak(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.0)
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.0)
    monkeypatch.setattr(sd, "is_hidden_by_cloak", lambda obj: False)
    assert sensor_media.subsystems_hidden(o) is False
    monkeypatch.setattr(sd, "is_hidden_by_cloak", lambda obj: True)
    assert sensor_media.subsystems_hidden(o) is True
    monkeypatch.setattr(sd, "is_hidden_by_cloak", lambda obj: False)
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 1.0)
    assert sensor_media.subsystems_hidden(o) is True
```

Plus an AI test copying the fixture style of the existing AI cloak-aim test (grep `is_hidden_by_cloak` in tests/ — e.g. `tests/unit/test_cloak_subsystem_suppression.py` or an ai_driver test): an AI ship whose target is inside a field (monkeypatch `far_tier.field_strength_at` → 1.0) ends with `GetTargetSubsystem() is None` after the aim step that previously chose a subsystem. Name it `test_ai_subsystem_aim_falls_back_to_hull_in_a_field`. And a perception test: a known, uncloaked contact in a field has `subsystems_targetable is False`.

- [ ] **Step 2: Run** — FAIL (module missing).

- [ ] **Step 3: Implement** `engine/appc/sensor_media.py`:

```python
"""Is a target inside a medium that hides its identity?
(sensor continuity/occlusion spec, roadmap decision 8)

Unknown by medium = inside an asteroid field (far_tier.field_strength_at at or
above `field_unknown_threshold`) or in moderate nebula
(sensor_detection.concealment_at at or above `nebula_unknown_threshold`). The
contact stays listed and targetable; only its identity and subsystem detail are
withheld. The dense nebula core is a different, stronger effect (can_detect
drops the contact) and is not decided here.

⚠️ field_strength_at only knows the tile fields last pushed for the VIEWED set,
so a ship in an unviewed set reads 0 -- accepted (spec "Known limits"): only the
player identifies, and the player's set is the viewed one.

Module attributes are looked up at call time (far_tier.field_strength_at,
sensor_detection.concealment_at, is_hidden_by_cloak) so tests can monkeypatch
them on their home modules.
"""
from engine.appc import sensor_dials


def medium_unknown(obj) -> bool:
    if obj is None:
        return False
    from engine.rocks import far_tier
    from engine.appc import sensor_detection
    if far_tier.field_strength_at(obj) >= sensor_dials.get("field_unknown_threshold"):
        return True
    return sensor_detection.concealment_at(obj) >= sensor_dials.get("nebula_unknown_threshold")


def subsystems_hidden(obj) -> bool:
    """A fuzzy sensor return: targetable at ship level, not by subsystem.
    Cloak or an identity-hiding medium. One predicate for player and AI."""
    from engine.appc import sensor_detection
    return bool(sensor_detection.is_hidden_by_cloak(obj) or medium_unknown(obj))
```

`concealment_at` takes a ship with `GetContainingSet`/`GetWorldLocation`; if it raises for a planet or a bare object, guard inside `medium_unknown` by catching and treating as 0.0 (log via `dev_mode.log_swallowed`), and add a test with a Planet.

`perception.perceived_by`: `subsystems_targetable=identified and not sensor_media.subsystems_hidden(ship)` (replacing `not sd.is_hidden_by_cloak(ship)`); update the comment above it.

`ai_driver.py` (~line 1137): replace `is_hidden_by_cloak(current_target)` with `sensor_media.subsystems_hidden(current_target)`; update the comment block (cloak or medium; still absolute state on the target, so one predicate serves both sides). Remove the now-unused `is_hidden_by_cloak` import if nothing else in the file uses it.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_sensor_media.py tests/unit -q -k "cloak or perceiv or ai_driver or subsystem or sensor"` → PASS; fix fixtures only.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_media.py engine/appc/perception.py engine/appc/ai_driver.py tests/unit/test_sensor_media.py
git commit -m "feat(sensors): fields and moderate nebula hide identity and subsystems, for player and AI"
```

---

### Task 4: Continuity — the window, lost track, one display answer

**Files:**
- Modify: `engine/appc/sensor_contacts.py`
- Modify: `engine/appc/perception.py` (`identified` uses `shows_identity`)
- Modify: `engine/ui/reticle_text.py` (`player_knows` → `shows_identity`)
- Modify: `engine/appc/science_scan_labels.py` (`_unknown_label` uses `shows_identity`)
- Test: `tests/unit/test_sensor_continuity.py`

**Interfaces:**
- Consumes: `sensor_occlusion.blocked` (Task 2), `sensor_media.medium_unknown` (Task 3), `sensor_dials.get("continuity_window_s")` (Task 1), `unknown_labels.placeholder/current`, `STMenu.RenameButton(old, new)`, `sensor_identification._identify_one`.
- Produces: `sensor_contacts.shows_identity(obj, now_gt=None) -> bool`; `sensor_contacts.is_concealed(player, obj) -> bool`; `sensor_contacts.concealed_since(obj) -> float | None`.

**Rules (from the spec, binding):**
- `is_concealed(player, obj)` = same set ∧ `dist <= effective_sensor_range(player)` ∧ (`not can_detect(player, obj)` ∨ `sensor_media.medium_unknown(obj)`).
- On each sweep, for every contact the player KNOWS: concealed → `_concealed_since.setdefault(obj, now)`; if `now - since >= continuity_window_s` → lose track. Not concealed → `_concealed_since.pop(obj)`.
- Lose track: `sensors.RemoveKnownObject(obj)`; call `Bridge.HelmMenuHandlers.ExitedSet(obj)` (import guarded; swallow+log on failure); pop `_concealed_since[obj]` and `_scanned_at[obj]`.
- Passive arming and passive commit additionally require `not is_concealed(player, obj)`.
- Scan commit (`by_scan`): drop it if `sensor_occlusion.blocked(player, obj)` at commit time. On a successful scan commit: `_scanned_at[obj] = now`; if `is_concealed(player, obj)`, `_concealed_since[obj] = now` (the window runs from the scan).
- `shows_identity(obj, now)` = player knows obj ∧ (not `medium_unknown(obj)` ∨ (`obj in _scanned_at` ∧ `now - _scanned_at[obj] < continuity_window_s`)).
- Science label sync, on each sweep, for every contact: `want_real = shows_identity(obj)`; if it differs from `_shown_real.get(obj)`, rename that contact's Scan Object button between `unknown_labels.placeholder(obj)` and `obj.GetDisplayName()` with `STMenu.RenameButton` (no-op if no button), then record `_shown_real[obj] = want_real`. Allocate the placeholder only when the contact has a button or is listed (`target_menu.contact_for(obj)` targetable) — match Task-6-of-sub-project-1's allocation rule.
- `reset()` and `_sync_player`'s wipe also clear `_concealed_since`, `_scanned_at`, `_shown_real`. `on_exited_set` pops all three for `obj`.

- [ ] **Step 1: Write the failing tests** — fixtures copy `tests/unit/test_sensor_contacts.py::_world`/`_ship` (current-game-player idiom: `Game(); game.SetPlayer(player); _set_current_game(game)`) and `tests/helpers/rocks.make_major_rock`. Monkeypatch `engine.rocks.far_tier.field_strength_at` to put a ship "in a field". Patch `Bridge.HelmMenuHandlers.ExitedSet` with a recorder (or, if the SDK module is not importable in unit tests, patch the import hook used by sensor_contacts — read how you import it and patch that seam). Tests (all with real assertions):

```python
def test_hidden_under_the_window_keeps_identity():
    # identify bird (AddKnownObject), put a major rock between, tick at t=0,1,..,4
    # assert IsObjectKnown(bird) == 1 throughout; remove the rock at t=4.5, tick 5
    # assert still known and concealed_since(bird) is None


def test_hidden_for_the_window_loses_track_and_calls_helm_exitedset():
    # rock between from t=0; ticks every 1.0 to t=6
    # assert IsObjectKnown(bird) == 0 by t=5 (window 5.0, sweep 1.0)
    # assert the Helm ExitedSet recorder was called exactly once with bird
    # assert no ET_EXITED_SET event was posted (subscribe a recorder to it)


def test_window_is_a_dial():
    # sensor_dials._dials["continuity_window_s"] = 2.0; lost by t=2


def test_leaving_range_while_hidden_stops_the_clock():
    # rock hides bird at t=0; at t=2 move bird beyond sensor range
    # tick to t=10: bird still known; concealed_since(bird) is None


def test_in_field_identified_ship_reads_unknown_then_named_again():
    # bird known; field 1.0 at t=0 -> shows_identity(bird) False
    # field 0.0 at t=3 -> shows_identity(bird) True, still known


def test_in_field_for_the_window_loses_track():
    # field 1.0 from t=0, bird stays listed (perceivable); by t=5 IsObjectKnown == 0


def test_no_passive_identification_inside_a_field():
    # bird unknown, near band, field 1.0; ticks to t=10 -> never known


def test_scan_in_field_gives_exactly_one_window(monkeypatch):
    # field 1.0; schedule a scan (sensors.IdentifyObject) at t=0 with _now pinned
    # commit at t=4 -> known, shows_identity True at t=4..8.9
    # at t=9 (scan time 4 + window 5) track lost: IsObjectKnown == 0


def test_scan_of_a_rock_blocked_target_does_nothing(monkeypatch):
    # rock between; IdentifyObject; tick past the dwell -> still unknown


def test_list_reticle_and_science_agree_in_field():
    # known bird enters field: perception Contact.identified False,
    # reticle name == unknown_labels.placeholder(bird) (call the reticle name
    # builder the way tests/unit/test_reticle_text.py does),
    # Science scan button (if the bridge fixture is available, else assert
    # science_scan_labels._unknown_label(bird) == placeholder) uses the same label
```

Write each body fully. For the Science agreement, use the integration fixture from `tests/integration/test_science_scan_unknown_labels.py` if unit-level bridge menus are unavailable — put that one test in `tests/integration/test_sensor_continuity_science.py` instead and say so.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** in `sensor_contacts.py` per the Rules block: module state `_concealed_since`, `_scanned_at`, `_shown_real` (WeakKeyDictionary); `is_concealed`, `concealed_since`, `shows_identity`, `_lose_track(player, sensors, obj)`, `_sync_science_label(obj, now)`; extend `_sweep` (continuity pass for known contacts, label sync for all contacts, passive arm requires not concealed), `_commit_due` (passive requires not concealed; scan drops when blocked; scan success sets `_scanned_at` and restarts the clock if concealed), `reset`, `_sync_player`, `on_exited_set`. Update the module docstring with the continuity rules.

Then switch the three readers:
- `perception.perceived_by`: `identified = bool(observer_sensors is not None and observer_sensors.IsObjectKnown(ship) and sensor_contacts.shows_identity(ship))`.
- `reticle_text.py`: the unknown-name branch uses `not sensor_contacts.shows_identity(target)` instead of `not sensor_contacts.player_knows(target)`.
- `science_scan_labels._unknown_label`: `if obj is None or sensor_contacts.shows_identity(obj): return None`.

Grep the tests of those three readers (test_reticle_text.py, test_unknown_contact_display.py, test_science_scan_unknown_labels.py, test_perceived_by.py) and confirm each still bites.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_sensor_continuity.py tests/unit tests/integration -q -k "sensor or reticle or science or scan or perceiv or target or identif"` → PASS; then `uv run pytest tests/unit tests/integration -q` once (baselined: `test_shield_level_change_announces`).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_contacts.py engine/appc/perception.py engine/ui/reticle_text.py engine/appc/science_scan_labels.py tests/unit/test_sensor_continuity.py
git add <tests/integration/test_sensor_continuity_science.py if created, and each fixture file fixed, explicitly>
git commit -m "feat(sensors): continuity window, lost track and one shown-identity answer"
```

---

### Task 5: Mission guards — E5M2 Outpost, Helm's delayed hail button

**Files:**
- Create: `engine/appc/sensor_mission_guards.py`
- Modify: `engine/host_loop.py` (beside both `science_scan_labels.install()` calls, ~283 and ~4487)
- Modify: `tests/conftest.py` (reset the E5M2 first-seen flag)
- Test: `tests/integration/test_sensor_mission_guards.py`

**Interfaces:**
- Consumes: `sensor_contacts.player_knows(obj)`.
- Produces: `sensor_mission_guards.install() -> None` (idempotent); `sensor_mission_guards.reset() -> None`.

- [ ] **Step 1: Write the failing tests**
- E5M2: load the mission headlessly (`tests.integration.test_sdk_bridge_load._fresh_world()` then `host_loop._init_mission("Maelstrom.Episode5.E5M2.E5M2")`), call `sensor_mission_guards.install()`, set `mod.g_bBaseDetected = 1`, create or find an object named "Outpost" (read E5M2 to see how the Outpost is created; if it already exists after init use it), post `ET_SENSORS_SHIP_IDENTIFIED` (destination = Outpost) twice through `App.g_kEventManager.AddEvent`. Record `MissionLib.AddGoal` calls (monkeypatch) and queued sequences (monkeypatch `mod.QueueSequence`). Assert `AddGoal("E5ScanOutpostGoal")` happened once and `QueueSequence` at most once across both events. Name: `test_e5m2_outpost_reidentification_replays_nothing`. Also `test_e5m2_other_ships_pass_through` (a non-Outpost ship's identification reaches the original handler every time — assert via a recorder on the original).
- Helm race: build the bridge as `tests/integration/test_hail_button_population.py` does; a hailable ship known at identification; call `Bridge.HelmMenuHandlers.AddHailButton(None, ship.GetObjID())` after `sensors.RemoveKnownObject(ship)` → no Hail button for it; with the ship known → a button appears. Names: `test_delayed_hail_button_skipped_after_lost_track`, `test_delayed_hail_button_added_when_still_known`.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** `engine/appc/sensor_mission_guards.py`:

```python
"""SDK/mission guards for re-identification (sensor continuity spec, Guards).

Sub-project 2 can identify a ship more than once (lost track -> found again),
which stock BC never did. Two SDK handlers were audited as unsafe for that
(roadmap "Re-identification audit"):

  * E5M2.ShipIdentified (E5M2.py:610) replays dialogue and re-adds a goal on
    every Outpost identification. Only the first Outpost identification per
    mission runs the mission body; later ones skip it and pass the event on.
  * HelmMenuHandlers.AddHailButton (HelmMenuHandlers.py:568) runs 1 s after
    identification and never re-checks; a track lost inside that second would
    still get a button. Re-checked against the player's known set.

Both wrap by module attribute -- handlers resolve by name at dispatch
(engine/appc/events.py:_resolve_handler). install() is idempotent and is re-run
on mission swap (the SDK modules may be re-imported).
"""
import sys

import engine.dev_mode as dev_mode

_outpost_seen = False


def reset() -> None:
    global _outpost_seen
    _outpost_seen = False


def _wrap_e5m2(orig):
    def ShipIdentified(pObject, pEvent):
        global _outpost_seen
        try:
            import App
            ship = App.ShipClass_Cast(pEvent.GetDestination())
            is_outpost = ship is not None and ship.GetName() == "Outpost"
        except Exception as e:
            dev_mode.log_swallowed("E5M2 guard", e)
            is_outpost = False
        if is_outpost and _outpost_seen:
            if pObject is not None:
                pObject.CallNextHandler(pEvent)
            return None
        if is_outpost:
            _outpost_seen = True
        return orig(pObject, pEvent)
    ShipIdentified._sensor_guarded = True
    return ShipIdentified


def _wrap_add_hail(orig):
    def AddHailButton(pAction, idObject):
        try:
            import App
            from engine.appc import sensor_contacts
            obj = App.ObjectClass_Cast(App.TGObject_GetTGObjectPtr(idObject))
            if obj is not None and not sensor_contacts.player_knows(obj):
                return 0
        except Exception as e:
            dev_mode.log_swallowed("AddHailButton guard", e)
        return orig(pAction, idObject)
    AddHailButton._sensor_guarded = True
    return AddHailButton


def install() -> None:
    try:
        import Bridge.HelmMenuHandlers as helm
        if not getattr(helm.AddHailButton, "_sensor_guarded", False):
            helm.AddHailButton = _wrap_add_hail(helm.AddHailButton)
    except ImportError:
        pass
    e5m2 = sys.modules.get("Maelstrom.Episode5.E5M2.E5M2")
    if e5m2 is not None and not getattr(e5m2.ShipIdentified, "_sensor_guarded", False):
        e5m2.ShipIdentified = _wrap_e5m2(e5m2.ShipIdentified)
```

E5M2 is only in `sys.modules` after its mission loads. Find where host_loop imports/initialises a mission module (`_init_mission`) and call `sensor_mission_guards.install()` right after the mission module is imported and before its handlers can fire — if `install()` beside `science_scan_labels.install()` in `_reset_sensor_state` runs BEFORE the import, add one more call after the mission module import and say where in your report. `_reset_sensor_state` also calls `sensor_mission_guards.reset()`. Add `sensor_mission_guards.reset()` to conftest's autouse reset.

Verify `pObject.CallNextHandler(pEvent)` is the right "pass it on" call for a broadcast func handler in this engine (read engine/appc/events.py dispatch for broadcast func handlers); if broadcast handlers are not chained, simply `return None` and say so.

- [ ] **Step 4: Run** — `uv run pytest tests/integration/test_sensor_mission_guards.py tests/integration/test_hail_button_population.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_mission_guards.py engine/host_loop.py tests/conftest.py tests/integration/test_sensor_mission_guards.py
git commit -m "feat(sensors): guard E5M2 Outpost and Helm's delayed hail button against re-identification"
```

---

### Task 6: Mission integration, docs and the gate

**Files:**
- Test: `tests/integration/test_sensor_continuity_missions.py`
- Modify: `CLAUDE.md` (extend the sensor-tiers row; stay under the 1,200-char row budget enforced by `tests/docs/test_doc_consistency.py`)
- Modify: `docs/superpowers/specs/2026-10-05-sensor-continuity-occlusion-design.md` ("As built")
- Modify: `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md` (status)

- [ ] **Step 1: Integration test** — E2M1 (`host_loop._init_mission("Maelstrom.Episode2.E2M1.E2M1")` after `_fresh_world()`): find the Karoon and the player; identify the Karoon (`ForceObjectIdentified`); place a major rock (use one of E2M1's own asteroids if `effective_radius >= 2.0`, else `make_major_rock`) exactly between player and Karoon; drive `sensor_contacts.tick` from t=1000 in 1.0 steps to t=1007. Assert: `can_detect(player, karoon)` False while blocked; Karoon unknown by t=1005; move the rock away; Karoon is listed again (`perception.perceived_by(player)` has it targetable) and `sensors.IdentifyObject(karoon)` + ticks past the dwell re-identifies it. Name: `test_e2m1_karoon_hidden_then_recovered`.

- [ ] **Step 2: Run** — `uv run pytest tests/integration/test_sensor_continuity_missions.py -q` → PASS. If E2M1 cannot be driven this way headlessly, STOP and report BLOCKED with what you found.

- [ ] **Step 3: Gate** — `scripts/check_tests.sh` (long; up to 600000 ms per command; run in background if needed). GL tests SKIP in a sandbox and the gate fails on unbaselined skips — re-run with the Bash tool's sandbox disabled if you see GL skips. NEVER pkill/killall. Expected: the only failures, if any, are the 5 `RockPerfEquivalence` digest tests already recorded as pre-existing on main (ctest + inproc). Any other failure is a regression from this branch — fix it.

- [ ] **Step 4: Docs** — CLAUDE.md sensor row: append one sentence: "Sub-project 2: a major rock (scaled radius ≥ `min_blocker_radius_gu`) on the line of sight hides a contact in `can_detect` (player + AI); inside a field / moderate nebula reads Unknown; concealed < `continuity_window_s` (5 s) keeps identity, longer loses the track. One display answer: `sensor_contacts.shows_identity`." Keep the row ≤ 1,200 chars (run `uv run pytest tests/docs -q`). Spec "As built": deviations and rulings from the ledger the controller gives you. Roadmap: sub-project 2 status "built, unmerged".

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_sensor_continuity_missions.py CLAUDE.md docs/superpowers/specs/2026-10-05-sensor-continuity-occlusion-design.md docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md
git commit -m "test(sensors): E2M1 continuity integration; docs"
```

---

### Task 7 (controller, after Mark approves the launch): frame-profiler measurement

Not a subagent task. The controller asks Mark for permission to launch (each launch), then:

1. In the worktree: `cmake --build build -j`.
2. Read `docs/engine/frame-profiler.md` first (four ways to misread it; the profiler is under Developer Options → Diagnostics → Frame Profiler; reports to stderr every 120 frames; check the SCENE line).
3. Launch `DAUNTLESS_MISSION=engine.dev_missions.combat_stress ./build/dauntless --developer`, profiler on, capture 3 reports (occlusion ON). Then switch occlusion OFF live without relaunching: Developer Options → Lighting → "Dial keys" → sensors, select `min_blocker_radius_gu` with `/`, and step it up with `O` until it exceeds every rock's scaled radius (no major rocks ⇒ the occlusion term returns immediately). Capture 3 more reports. Compare the `sim.*` scopes.
4. Repeat in a rock-heavy mission (Multi1, 54 rocks) only if Mark approves that launch too.
5. Record CPU numbers only (GPU timing is dead on this Mac) in the spec's "As built" → "Performance (measured)", and commit.
