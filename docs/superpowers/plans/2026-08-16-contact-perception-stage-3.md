# Contact Perception — Stage 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate detectability into one query that every consumer reads, computing each contact's distance exactly once — with no behaviour change whatsoever.

**Architecture:** `perception.contacts_for` grows into `perceived_by(observer)`, returning `Contact` records that carry the perception verdict and both distance forms. `engine/ui/target_list_visibility.py` is deleted; `IsVisible()` becomes derived. The four consumers that each re-derive their own filters and distances become readers of one answer.

**Tech Stack:** Python 3, pytest. No C++ — nothing here touches `native/`.

**Spec:** `docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md`

**Predecessor:** stages 1–2, merged at `9e157008` and live-verified 2026-08-16.

## Why stage 4 is not in this document

Stage 4 (nebula concealment reaching the UI, cloak becoming range-defeatable at 1% of effective sensor range, both behind a fidelity toggle) is deliberately **not** planned here. Two reasons:

1. Its task shape depends on how `perceived_by` actually lands — writing speculative task detail now would be waste.
2. Stage 4 changes gameplay. Bisecting a gameplay change against a large refactor is exactly the trap the stage 1–2 split avoided: when something feels wrong in a nebula fight, "refactor or new rule?" must have an answer.

**Land stage 3, live-verify it, then plan stage 4.** A short outline is at the end so the intent is not lost.

## Global Constraints

- **NO behaviour change.** This is the binding constraint of the entire stage. Detectability keeps the rule it has today: **range + cloak + sensors-offline, and NO nebula concealment.** Do not switch anything to `can_detect` — that predicate additionally applies nebula concealment with hysteresis, and adopting it is stage 4's job. If a test's expected value has to change, stop: you have altered behaviour.
- **Shared checkout with concurrent sessions.** NEVER run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, `cp` it to `/tmp`, mutate, restore by `cp`, and `diff` to prove byte-identity.
- **Never use `hasattr()` to test whether an object supports an engine method.** `TGObject.__getattr__` returns a truthy `_Stub` for any missing attribute, so `hasattr` is vacuously true. Use `isinstance` or `engine.core.ids.implements(obj, name)`. The one legitimate exception is `hasattr(x, "_underscore_name")`, because `__getattr__` raises for those.
- **Units are game units.** Variables end `_gu` / `_gups`. Never `_m`, `_km`, `_mps`. Convert only at display boundaries via `engine/units.py`.
- **Do not modify anything under `sdk/`** — it is the original game's source and is ground truth.
- **Test gate:** `scripts/check_tests.sh`. It must report no failure absent from `tests/known_failures.txt`. Never add to that baseline.
- Run tests with `uv run pytest`, not bare `pytest`.

---

### Task 1: The `Contact` record and `perceived_by`

**Files:**
- Modify: `engine/appc/perception.py`
- Test: `tests/unit/test_perceived_by.py`

**Interfaces:**
- Consumes: `contact_index.ships_in(pSet) -> tuple`
- Produces:
  - `Contact` — a frozen dataclass with fields `ship`, `dist_sq_gu: float`, `surface_gu: float`, `perceivable: bool`, `targetable: bool`
  - `perceived_by(observer) -> tuple[Contact, ...]`
  - `contacts_for(observer) -> tuple` — unchanged signature, now a thin wrapper returning the ships of the targetable records, so existing callers keep working while later tasks migrate them

**The rule to reproduce exactly.** Read `engine/ui/target_list_visibility.py` and `engine/ui/target_list_view.py` before writing anything. Today's behaviour, which you must reproduce and not improve:

- If the observer's sensor subsystem is offline → nothing is perceivable at all (`update_target_list_visibility` sets every row NotVisible and returns).
- Otherwise effective range comes from `sensor_detection.effective_sensor_range(observer)` — `base × condition% × power%`.
- A fully cloaked ship (`sensor_detection.is_hidden_by_cloak`) is not perceivable, regardless of range.
- Otherwise perceivable iff centre-to-centre squared distance ≤ range².
- **No nebula concealment.** `concealment_at` is not called anywhere in this stage.

`targetable` additionally requires: not the observer, `IsTargetable()`, and alive-or-targetable-wreck (`ship_death._out_of_action` / `is_targetable_wreck` — see `target_list_view.py:225`).

`surface_gu` is `sqrt(dist_sq_gu) - ship.GetRadius()`, clamped at 0 — BC's readout convention, verified against the original game (`reticle_text.py:50-58`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_perceived_by.py`:

```python
"""perceived_by answers membership + detectability + distance in one pass."""
import pytest

from engine.appc import contact_index
from engine.appc.perception import Contact, perceived_by, contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem


def _observer(pSet, base_range=2000.0, condition=100.0):
    """A player-shaped ship with a REAL sensor subsystem.

    Follows tests/unit/test_sensor_detection.py::_ship_with_sensor. This
    matters: a bare ShipClass() has no sensor subsystem, so
    effective_sensor_range falls back to FALLBACK_RANGE_GU (30000) — 15x a
    Galaxy's real range — and every range assertion below would be testing
    the fallback instead of the thing it names.
    """
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, "player")
    return ship, sensors


def _placed(pSet, name, x=0.0, radius=0.0):
    """A contact in pSet at (x, 0, 0) with the given bounding radius."""
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(x, 0.0, 0.0)
    if radius:
        s.SetRadius(radius)
    pSet.AddObjectToSet(s, name)
    return s


def test_contact_carries_ship_and_flags():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    other = _placed(pSet, "Galor", x=10.0)

    got = perceived_by(player)

    assert len(got) == 1
    assert isinstance(got[0], Contact)
    assert got[0].ship is other
    assert got[0].perceivable is True
    assert got[0].targetable is True


def test_observer_is_never_its_own_contact():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)

    assert perceived_by(player) == ()


def test_distance_is_squared_centre_distance():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    _placed(pSet, "Galor", x=30.0)

    assert perceived_by(player)[0].dist_sq_gu == pytest.approx(900.0)


def test_surface_distance_subtracts_the_target_radius():
    """BC's range readout is to the bounding sphere, not the centre —
    negligible for ships, decisive for planets and stations."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    _placed(pSet, "Starbase", x=100.0, radius=40.0)

    assert perceived_by(player)[0].surface_gu == pytest.approx(60.0)


def test_surface_distance_clamps_at_zero_when_inside_the_radius():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    _placed(pSet, "Planet", x=10.0, radius=90.0)

    assert perceived_by(player)[0].surface_gu == 0.0


def test_contact_beyond_sensor_range_is_not_perceivable():
    """2000 GU sensors, contact at 2500 GU — out of range but still a
    contact record, because membership and perception are separate answers."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet, base_range=2000.0)
    _placed(pSet, "Faraway", x=2500.0)

    got = perceived_by(player)

    assert len(got) == 1
    assert got[0].perceivable is False


def test_offline_sensors_make_nothing_perceivable():
    """Matches update_target_list_visibility's early return today. 20% is
    below the default 25% disabled threshold, so the array reads offline."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet, condition=20.0)
    _placed(pSet, "Galor", x=10.0)

    assert all(not c.perceivable for c in perceived_by(player))


def test_non_targetable_contact_is_still_perceivable():
    """targetable and perceivable are different questions — a mission-hidden
    ship is still detected, it just cannot be a target-list row."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    hidden = _placed(pSet, "Kessok", x=10.0)
    hidden.SetTargetable(0)

    got = perceived_by(player)

    assert got[0].perceivable is True
    assert got[0].targetable is False


def test_contacts_for_still_returns_targetable_ships():
    """Back-compat wrapper — existing callers must not change behaviour."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    other = _placed(pSet, "Galor", x=10.0)
    hidden = _placed(pSet, "Kessok", x=20.0)
    hidden.SetTargetable(0)

    assert contacts_for(player) == (other,)


def test_no_observer_or_no_set_reads_empty():
    contact_index.reset()
    adrift = ShipClass_Create("Galaxy")
    adrift.SetName("Adrift")
    assert perceived_by(None) == ()
    assert perceived_by(adrift) == ()
```

Helper surface verified against the tree: `ShipClass_Create`,
`SetTranslateXYZ`, `SetRadius`/`GetRadius` (`objects.py:134-137`), and the
`SensorSubsystem` construction all exist as written.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_perceived_by.py -v`
Expected: FAIL — `ImportError: cannot import name 'Contact'`

- [ ] **Step 3: Write minimal implementation**

Rewrite `engine/appc/perception.py`. Keep the existing module docstring's framing (store holds what exists / read answers what an observer perceives) and update the STAGE note. Add:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Contact:
    """One contact, fully resolved for this frame.

    Consumers do no further arithmetic: the target list reads `targetable`,
    the radar reads `perceivable` plus its own display clip, and the range
    readouts read `surface_gu`. Distance is computed once here — before this,
    the same player-to-contact vector was derived in five places under two
    different conventions.
    """
    ship: object
    dist_sq_gu: float
    surface_gu: float
    perceivable: bool
    targetable: bool


def perceived_by(observer) -> tuple:
    """Every ship in *observer*'s system, resolved for this frame.

    STAGE 3 SCOPE: reproduces today's UI detectability rule exactly — range,
    cloak, and the sensors-offline short-circuit, with NO nebula concealment.
    Stage 4 switches this to sensor_detection.can_detect (which adds nebula
    with hysteresis) and makes cloak range-defeatable, both behind a
    stock-BC fidelity toggle.
    """
    from engine.appc.sensor_detection import (
        effective_sensor_range, is_hidden_by_cloak)
    from engine.appc.ship_death import _out_of_action, is_targetable_wreck

    if observer is None:
        return ()
    pSet = observer.GetContainingSet()
    # A real SetClass exposes _objects; a _Stub or None does not. hasattr()
    # cannot discriminate — TGObject.__getattr__ answers every name.
    if pSet is None or not hasattr(pSet, "_objects"):
        return ()

    # Sensors offline => effective range 0 => nothing perceivable. One check,
    # before any iteration.
    range_gu = effective_sensor_range(observer)
    range_sq = range_gu * range_gu
    ox, oy, oz = _get_xyz(observer)

    out = []
    for ship in contact_index.ships_in(pSet):
        if ship is observer:
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - ox, sy - oy, sz - oz
        dist_sq = dx * dx + dy * dy + dz * dz
        # Cheap bools before the distance comparison; nothing here samples a
        # field or takes a square root.
        perceivable = (
            range_gu > 0.0
            and not is_hidden_by_cloak(ship)
            and dist_sq <= range_sq
        )
        alive_or_wreck = (not _out_of_action(ship)) or is_targetable_wreck(ship)
        out.append(Contact(
            ship=ship,
            dist_sq_gu=dist_sq,
            surface_gu=_surface_gu(dist_sq, ship),
            perceivable=perceivable,
            targetable=perceivable and alive_or_wreck and bool(ship.IsTargetable()),
        ))
    return tuple(out)


def _surface_gu(dist_sq: float, ship) -> float:
    """Distance to the target's bounding sphere, BC's range-readout convention
    (verified against the original game by orbiting Haven — see
    engine/ui/reticle_text.py). Negligible for ships, decisive for planets."""
    d = dist_sq ** 0.5
    r = ship.GetRadius() if implements(ship, "GetRadius") else 0.0
    return d - r if d > r else 0.0


def contacts_for(observer) -> tuple:
    """Targetable ships in *observer*'s system. Back-compat wrapper over
    perceived_by for callers not yet migrated to Contact records."""
    return tuple(c.ship for c in perceived_by(observer) if c.targetable)
```

Import `implements` from `engine.core.ids` and `_get_xyz` from
`engine.appc.subsystems` (the same helper `target_list_visibility` uses today —
check its import site and reuse it rather than writing another).

Keep the existing `contacts_for` docstring's warning about the targetable gate
being target-list-specific; move it onto `Contact.targetable`'s field comment.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_perceived_by.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Confirm no existing behaviour moved**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: no new failures versus `tests/known_failures.txt`. `contacts_for`'s existing tests must pass **unchanged** — if any needs editing, you have altered behaviour; stop and report.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/perception.py tests/unit/test_perceived_by.py
git commit -m "feat(perception): Contact record + perceived_by, distance computed once"
```

---

### Task 2: Derive `IsVisible` and delete the visibility pass

**Files:**
- Modify: `engine/appc/target_menu.py` (`STSubsystemMenu.IsVisible`, `STTargetMenu.set_contacts`)
- Modify: `engine/host_loop.py` (`_pump_contacts`, and the `update_target_list_visibility` call site + import at `:94`)
- Delete: `engine/ui/target_list_visibility.py`
- Delete: `tests/unit/test_sensor_visibility.py` **only if** it tests solely the deleted function — check first
- Test: `tests/unit/test_target_menu_visibility_derived.py`

**Interfaces:**
- Consumes: `perceived_by` from Task 1
- Produces: `STTargetMenu.set_contacts(contacts)` now takes `Contact` records rather than ships

**Why this matters beyond tidiness.** The SDK's `CycleTarget` skips rows where `not IsVisible()` (`sdk/Build/scripts/TacticalInterfaceHandlers.py:701-730`). Today the flag pass and the panel filters use *different* rules — the flag pass ignores death entirely — so Tab-cycling can select a contact the target list refuses to draw. Deriving both from one answer removes that divergence by construction.

**Watch the row-cache interaction.** `set_contacts` currently builds a row for any ship not yet cached. It must keep listing rows for `targetable` contacts only, and `IsVisible()` must reflect `perceivable`. Read `STTargetMenu` in full before editing — its `_children` is a property over `_rows()`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_target_menu_visibility_derived.py`:

```python
"""Row visibility is derived from the pushed Contact records, not written
by a separate pass."""
import App
from engine.appc.perception import Contact
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _menu():
    App._reset_target_menu_singleton()
    return App.STTargetMenu_CreateW("Targets")


def _contact(ship, perceivable=True, targetable=True):
    return Contact(ship=ship, dist_sq_gu=100.0, surface_gu=10.0,
                   perceivable=perceivable, targetable=targetable)


def test_perceivable_contact_row_is_visible():
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship)])
    assert menu.GetObjectEntry(ship).IsVisible() == 1


def test_unperceivable_contact_row_is_not_visible():
    """SDK CycleTarget skips rows where IsVisible() is 0, so an out-of-range
    contact must not be Tab-selectable."""
    menu = _menu()
    ship = _ship("Faraway")
    menu.set_contacts([_contact(ship, perceivable=False)])
    row = menu.GetObjectEntry(ship)
    assert row is not None
    assert row.IsVisible() == 0


def test_non_targetable_contact_gets_no_row():
    menu = _menu()
    ship = _ship("Kessok")
    menu.set_contacts([_contact(ship, targetable=False)])
    assert menu.GetNumChildren() == 0


def test_visibility_follows_a_later_push():
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship, perceivable=True)])
    assert menu.GetObjectEntry(ship).IsVisible() == 1

    menu.set_contacts([_contact(ship, perceivable=False)])

    assert menu.GetObjectEntry(ship).IsVisible() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_visibility_derived.py -v`
Expected: FAIL — `set_contacts` treats its argument as ships, so `Contact` objects are rejected by its `isinstance(s, ShipClass)` filter and no rows appear.

- [ ] **Step 3: Write minimal implementation**

1. `STTargetMenu.set_contacts(contacts)` accepts `Contact` records: list rows for `c.targetable`, and set each row's visibility from `c.perceivable` (`SetVisible()` / `SetNotVisible()` — the existing `STMenu` accessors).
2. `_pump_contacts` in `host_loop.py` calls `perceived_by(player)` and pushes the records.
3. Delete the `update_target_list_visibility` call from the frame block, and its import at `host_loop.py:94`.
4. Delete `engine/ui/target_list_visibility.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_visibility_derived.py tests/host/test_contacts_pump.py -v`
Expected: PASS

- [ ] **Step 5: Handle the fallout, honestly**

Run: `uv run pytest tests/unit tests/integration -q`

Tests importing the deleted module will fail — `tests/unit/test_sensor_detection.py` and `tests/unit/test_sensors_disabled_blanks_target_ui.py` both do. For each:

- If it tested the deleted function's *mechanism*, re-point it at `perceived_by` **asserting the same expected values**.
- If it tested behaviour that still exists elsewhere, leave it alone.
- **Never delete a test to make the suite green, and never weaken an assertion.** If an expected value would have to change, stop and report BLOCKED — this stage changes no behaviour, so a changed expectation means something is wrong.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/target_menu.py engine/host_loop.py \
        tests/unit/test_target_menu_visibility_derived.py
git rm engine/ui/target_list_visibility.py
git commit -m "refactor(perception): derive row visibility; delete the separate visibility pass"
```

Stage any adapted test files by explicit path in the same commit.

---

### Task 3: Migrate the readers onto the record

**Files:**
- Modify: `engine/ui/target_list_view.py` (`_snapshot`, around `:205-280`)
- Modify: `engine/ui/sensors_panel.py` (around `:96-120`)
- Modify: `engine/ui/reticle_text.py` (`:46-58`)
- Modify: `engine/ui/ship_display_panel.py` (`:552-560`)
- Test: `tests/unit/test_readers_share_one_distance.py`

**Interfaces:**
- Consumes: `Contact` from Task 1

**The duplication being removed.** The same player-to-contact vector is currently derived in these four places plus `can_detect`, under two conventions — centre for detection, surface for the readouts. After this task there is one computation.

**Preserve two things exactly:**

1. **The radar keeps its own display clip.** `sensors_panel` clips to `RadarDisplay.GetRange()` (1,000 GU default) while the target list uses the player's actual sensor range (2,000 GU on a Galaxy). The target list legitimately lists contacts the radar does not draw — display scale and perception are different concepts. Do not collapse them.
2. **`reticle_text` and `ship_display_panel` currently disagree on how they read position** — one uses `GetWorldLocation()`, the other `GetTranslate()`. Both now read `surface_gu` from the record, which unifies them. Confirm the readouts still produce the same numbers for a normal ship; if they differ, say by how much and why before proceeding.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_readers_share_one_distance.py`:

```python
"""Every consumer reads the same distance, computed once."""
import pytest

from engine.appc import contact_index
from engine.appc.perception import perceived_by
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.units import GU_TO_KM


def _observer(pSet):
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, "player")
    return ship


def _placed(pSet, name, x=0.0, radius=0.0):
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(x, 0.0, 0.0)
    if radius:
        s.SetRadius(radius)
    pSet.AddObjectToSet(s, name)
    return s


def test_ship_display_range_matches_the_contact_record():
    """ship_display_panel derived its own distance via GetTranslate();
    reticle_text used GetWorldLocation(). Both now read one record."""
    from engine.ui.ship_display_panel import _range_and_speed_to

    contact_index.reset()
    pSet = SetClass()
    player = _observer(pSet)
    target = _placed(pSet, "Galor", x=200.0, radius=5.0)

    contact = perceived_by(player)[0]
    # NOTE the argument order: _range_and_speed_to(ship, player).
    rng_km, _ = _range_and_speed_to(target, player)

    assert rng_km == pytest.approx(contact.surface_gu * GU_TO_KM)


def test_reticle_range_matches_the_contact_record():
    """reticle_text renders range into a formatted string
    (line2 = "%.2f km / %.0f kph"), so parse it back out rather than
    inventing a payload key that does not exist."""
    from engine.ui.reticle_text import build_reticle_text

    contact_index.reset()
    pSet = SetClass()
    player = _observer(pSet)
    target = _placed(pSet, "Galor", x=200.0, radius=5.0)
    player.SetTarget(target)

    contact = perceived_by(player)[0]
    payload = build_reticle_text(player, _camera(), _viewport())
    shown_km = float(payload["line2"].split(" km")[0])

    assert shown_km == pytest.approx(contact.surface_gu * GU_TO_KM, abs=0.01)
```

`build_reticle_text(player, camera, viewport)` needs a camera and a viewport.
Build them the way the existing reticle tests do — start from
`tests/unit/test_target_reticle.py` and reuse its fixtures for `_camera()` and
`_viewport()` rather than inventing your own. If that file's fixtures are not
reusable at this level, drop the reticle test and say so in your report; the
`ship_display_panel` half is the load-bearing one and must not be dropped.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_readers_share_one_distance.py -v`
Expected: FAIL — the two readers derive distance independently, so nothing guarantees they agree (they may coincidentally agree today; if the test passes immediately, strengthen it by giving the target a non-zero radius and a position where the accessors differ, or report that they cannot be made to disagree).

- [ ] **Step 3: Write minimal implementation**

Route all four consumers through the record:

- `target_list_view._snapshot`: drop its own `is_hidden_by_cloak` / `_out_of_action` / player-identity filters; iterate the pushed records and use `targetable`.
- `sensors_panel`: iterate the records for membership and `perceivable`, then apply its own radar-range clip using `dist_sq_gu`.
- `reticle_text` and `ship_display_panel`: read `surface_gu`.

Where a consumer has no direct access to the records, read them from the target-menu singleton the host loop already pushes to, rather than calling `perceived_by` again — a second call would re-do the work this task exists to remove.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_readers_share_one_distance.py -v`
Expected: PASS

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failure absent from `tests/known_failures.txt`.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/target_list_view.py engine/ui/sensors_panel.py \
        engine/ui/reticle_text.py engine/ui/ship_display_panel.py \
        tests/unit/test_readers_share_one_distance.py
git commit -m "refactor(perception): every reader shares one computed distance"
```

---

### Task 4: Hoist the per-set nebula list

**Files:**
- Modify: `engine/appc/contact_index.py`
- Modify: `engine/appc/sensor_detection.py` (`concealment_at`, `:89-117`)
- Test: `tests/unit/test_nebula_list_hoisted.py`

**Interfaces:**
- Produces: `contact_index.nebulae_in(pSet) -> tuple`

**The waste.** `concealment_at` calls `pSet.GetClassObjectList(App.CT_NEBULA)` — a full scan of the set to find nebulae — **once per ship, per call**. It is called per AI ship per tick today, and stage 4 will call it per contact per frame. Twenty contacts means twenty scans to rediscover the same list, which is usually empty.

Nebulae essentially never spawn or despawn mid-mission, so this is genuinely event-maintained state — the same shape as the ship buckets.

**No behaviour change:** `concealment_at` must return identical values. Only the lookup path changes. The density function already early-outs before the expensive fBm when the sample point is outside the sphere union (`nebula_density.py:81-83`) — do not touch that.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_nebula_list_hoisted.py`:

```python
"""Nebulae are indexed per set, not rediscovered per query."""
from engine.appc import contact_index
from engine.appc.sets import SetClass


def test_a_set_with_no_nebulae_reads_empty():
    contact_index.reset()
    assert contact_index.nebulae_in(SetClass()) == ()


def test_concealment_is_zero_and_cheap_without_nebulae():
    """The overwhelmingly common case: no nebulae in the set."""
    from engine.appc.sensor_detection import concealment_at
    from engine.appc.ships import ShipClass
    contact_index.reset()
    pSet = SetClass()
    ship = ShipClass()
    ship.SetName("Galor")
    pSet.AddObjectToSet(ship, "Galor")

    assert concealment_at(ship) == 0.0
```

Add a third test that a set **containing** a nebula reports it via `nebulae_in`, and that `concealment_at` returns the same value it did before the hoist. Build the nebula using `_set_with_dense_nebula()` from `tests/unit/test_nebula_concealment.py` (a set with one sphere-nebula at the origin, r=200 GU) — import or copy that helper rather than inventing a `MetaNebula` construction of your own.

Note that file's fixtures use a local `_Ship` fake exposing only `GetName`/`GetWorldLocation`/`GetContainingSet`. Those fakes are **not** `ShipClass` instances, so they never enter a contact-index bucket. Your `nebulae_in` test therefore needs a real set with a real nebula, not those fakes — and if `concealment_at`'s new lookup path assumes the index has been populated, a nebula added before the index existed would read as absent. Check how the nebula gets into the set in that helper and make sure the same route maintains the index.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula_list_hoisted.py -v`
Expected: FAIL — `nebulae_in` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `nebulae_in(pSet)` to `contact_index`, maintained by the same `SetClass` hooks that maintain the ship buckets (a nebula is not a `ShipClass`, so it needs its own branch — check what type `CT_NEBULA` objects actually are before writing the filter). Then have `concealment_at` read it instead of scanning.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_nebula_list_hoisted.py tests/unit/test_sensor_detection.py -v`
Expected: PASS, with `test_sensor_detection.py` **unchanged** — nebula concealment values must be identical.

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`

- [ ] **Step 6: Commit**

```bash
git add engine/appc/contact_index.py engine/appc/sensor_detection.py \
        tests/unit/test_nebula_list_hoisted.py
git commit -m "perf(perception): index nebulae per set instead of scanning per query"
```

---

## Verification

- [ ] `scripts/check_tests.sh` clean against `tests/known_failures.txt`
- [ ] `grep -rn "target_list_visibility" engine/ tests/` returns nothing
- [ ] `git log --oneline` shows four commits

**Live verification required — headless tests cannot see this.** Because this stage changes no behaviour, the live pass is a *regression* check:

1. Target list still populates, still tracks the player's system across a warp.
2. Friendly/enemy affiliation colours still correct.
3. Tab-cycling still matches the visible list — and now, a contact out of sensor range should be neither drawn nor Tab-selectable (today it can be Tab-selected).
4. Range readouts on the reticle and ship-display panel agree with each other and read the same as before.
5. Radar still respects its own zoom range, still shows a shorter range than the target list.
6. Damage or unpower the sensors: list empties, returns on repair.
7. A nebula mission behaves exactly as before — nebulae must NOT affect the target list in this stage.

Item 7 is the one to watch: if nebulae start hiding contacts, stage 4 has leaked into stage 3.

---

## Stage 4 outline (NOT planned here)

Recorded so the intent survives; gets its own plan after stage 3 is live-verified.

**The mechanic Mark specified.** Cloak stops being an early return in `can_detect` and becomes a range multiplier — `CLOAK_RANGE_FACTOR = 0.01` of *effective* sensor range, so it scales with sensor condition and power. A Galaxy (2,000 GU sensors) detects a cloaked ship at **20 GU**, one third of its 60 GU phaser range. Symmetric: AI ships get the same capability, and since `can_detect` is also the AI target-selection and firing gate, cloaked attack runs become detectable at close range. 1% was chosen over 1.5% specifically to keep cloak viable.

**Also in stage 4:** switch `perceived_by` from the current UI rule to `can_detect`, which brings nebula concealment (with its per-pair hysteresis latch) to the target list and radar.

**Both are divergences from stock BC** and go behind a fidelity toggle in the shape of the existing Modern VFX settings — `SettingsSnapshot` field plus injected applier plus a `toggle:` action (`engine/ui/configuration_panel.py`; `subtitles_on` is the Gameplay-tab precedent). Off returns stock behaviour.

**Open question for that plan:** one toggle covering both changes, or two. One is simpler and they are conceptually a single feature ("sensing is a contest, not a binary"); two lets nebula and cloak be tuned independently. My recommendation is one, but it is Mark's call.

**Hard requirement:** `can_detect` mutates a module-global hysteresis latch keyed by `(id(observer), id(target))` (`sensor_detection.py:156-162`). Once the UI calls it, the UI drives the same latch the weapons read. `perceived_by` must call it **once per contact per frame** — a correctness requirement, not an optimisation. It already has that shape, which is why stage 4 is a small change on top of stage 3.

**RESOLVED 2026-08-16 (stage 4, Task 3): the precondition above was wrong — switching `perceived_by` to `can_detect` (Tasks 1–2) made detection *stricter*, not decoupled.** `targetable = perceivable and alive_or_wreck and IsTargetable()` still holds verbatim (`engine/appc/perception.py:141`), so `targetable ⇒ perceivable` never broke and `set_contacts`' `SetNotVisible` branch stayed dead. Stage 4 removed it rather than trying to make it live: `set_contacts` now lists only targetable contacts and always calls `SetVisible()`; a contact that fails detection is dropped from the list, not greyed out. `SetNotVisible`/`IsVisible` remain real SDK surface (SDK `CycleTarget` still reads `IsVisible()`) — only the automatic call from `set_contacts` was removed. See `.superpowers/sdd/2026-08-16-contact-perception-stage-4/task-3-report.md` for the full reasoning.

**Deferred, still open:**
- `FALLBACK_RANGE_GU = 30000` is 15× a Galaxy's real 2,000 GU sensor range, and is what any ship without a resolvable sensor subsystem receives. Confirm the player never lands on that path.
- The targetable gate lives in `contacts_for`/`Contact.targetable`, which the radar reads through — so a mission-hidden ship vanishes from the radar too. No evidence BC's radar consults targetability. Live-observed as fine on 2026-08-16, but unverified as *correct*.
- `SetManager.RemoveSet`/`DeleteSet` drops a set without reaping its contact-index bucket. Retention only, bounded by `reset_sdk_globals`.
- Hail and Science-scan menus adopting the shared query, each with their own authored gate.
