# Contact Perception — Stage 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sensing a contest rather than a binary — a cloaked ship becomes detectable at very close range with powerful sensors, and nebula concealment reaches the target list and radar instead of only the weapons.

**Architecture:** `can_detect` stops treating cloak as an early return and treats it as a range multiplier (1% of effective sensor range). `perception.perceived_by` switches from its own rule to `can_detect`, which brings nebula concealment to the UI. Both changes sit behind one module-level code flag; there is no UI.

**Tech Stack:** Python 3, pytest. No C++ — nothing here touches `native/`.

**Spec:** `docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md`

**Predecessor:** stage 3 on this branch (`c3e7e2fe`), which built `perceived_by` and consolidated the readers. Stage 4 builds directly on top.

## The mechanic, as specified

A Galaxy has 2,000 GU of sensors and a 60 GU phaser range. At 1% of *effective* range:

| Ship | Sensor range | Cloak detection |
|---|---|---|
| Galaxy | 2,000 GU | **20 GU** (3.5 km) |
| Sovereign | 2,400 GU | 24 GU |
| Warbird | 3,000 GU | 30 GU |

That is one third of phaser range — you must be effectively on top of the target. Because it is a percentage of *effective* range, it scales with sensor condition and power: boosting sensor power extends it, wrecked sensors remove it entirely.

**Symmetric.** `can_detect` is also the AI target-selection and firing gate, so AI ships get the same capability and cloaked attack runs become detectable at close range. 1% was chosen over 1.5% specifically to keep cloak viable.

## Two corrections to earlier assumptions

Both were found by reading the post-stage-3 code, and both change what this plan must do.

**1. Stage 4 does NOT decouple `perceivable` from `targetable`, so the `IsVisible` precondition does not fire.** Stage 3 recorded a precondition: when stage 4 decouples the two, `set_contacts`' `SetNotVisible()` branch goes live with only synthetic test coverage. Re-checking the actual definition — `targetable = perceivable and alive_or_wreck and IsTargetable()` — switching `perceivable` to `can_detect` makes it *stricter* but keeps the implication. `targetable ⇒ perceivable` still holds, so the branch stays dead and a contact that fails detection still vanishes rather than greying out. **Task 3 resolves this deliberately rather than leaving a dead branch documented as a landmine.**

**2. Calling `can_detect` from `perceived_by` would recompute the distance stage 3 just consolidated.** `can_detect` does its own `_get_xyz` and squared-distance work (`sensor_detection.py:166-169`). `perceived_by` already has that number for the record. Naively calling it would restore a duplicate derivation one task after removing five. Task 2 handles this.

## Global Constraints

- **This stage changes gameplay deliberately.** Every behaviour change gets a test that *pins* it, with a comment saying it is intended, so a later reader does not "fix" it back.
- **One flag, code-only.** `ENHANCED_SENSOR_CONTEST` (name it as you like, but one) in `engine/appc/sensor_detection.py`. **No `SettingsSnapshot` field, no configuration-panel row, no CEF work** — `engine/ui/configuration_panel.py` must not be touched. It may be exposed to users later; that is not this stage.
- **Default ON.** An unexposed flag defaulting off is dead code. Flipping it to `False` must restore pre-stage-4 behaviour exactly, and a test must prove that.
- **Nebula rules themselves do not change.** `CONCEAL_K`, `LOCK_BREAK_T`, `HYSTERESIS` and the density maths stay exactly as they are. Stage 4 changes *who consults them*, not what they say.
- **Shared checkout with concurrent sessions.** NEVER run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Explicit pathspec staging only. To mutate a file temporarily, `cp` to `/tmp`, mutate, restore by `cp`, `diff` to prove byte-identity. **If a concurrent session sweeps your commit, report it — do not attempt history repair.**
- **Never use `hasattr()` to test whether an object supports an engine method** — `TGObject.__getattr__` returns a truthy `_Stub`, making it vacuously true. Use `isinstance` or `engine.core.ids.implements`. `hasattr(x, "_underscore_name")` is the legitimate exception.
- **Do not modify anything under `sdk/`.**
- Distances are game units, suffixed `_gu`.
- **Test gate:** `scripts/check_tests.sh` — no failure absent from `tests/known_failures.txt`, and never add to that baseline.
- Run tests with `uv run pytest`.

---

### Task 1: Cloak becomes a range multiplier

**Files:**
- Modify: `engine/appc/sensor_detection.py` (constants block near `:18-30`; `can_detect` at `:133-169`)
- Test: `tests/unit/test_cloak_detection_contest.py`

**Interfaces:**
- Produces: `ENHANCED_SENSOR_CONTEST: bool` (default `True`), `CLOAK_RANGE_FACTOR: float` (`0.01` as planned; retuned live and joined by `CLOAK_DETECTION_BASE_GU` — read the constants, not this line)
- `can_detect(observer, target) -> bool` — signature unchanged

**The change.** Today `can_detect` returns `False` the moment the target is cloaked, before any sensor maths runs:

```python
    cloak = _cloak_subsystem(target)
    if cloak is not None and cloak.IsCloaked():
        return False
```

It becomes a multiplier on effective range, applied after `effective_sensor_range` so it scales with condition and power:

```python
    cloaked = cloak is not None and cloak.IsCloaked()
    if cloaked and not ENHANCED_SENSOR_CONTEST:
        return False          # stock BC: cloak is absolute
    r = effective_sensor_range(observer)
    if r <= 0.0:
        return False
    if cloaked:
        r = r * CLOAK_RANGE_FACTOR
```

Keep everything below unchanged — the nebula gate, the hysteresis latch, the final squared-distance comparison. Note the ordering: the cloak multiplier and the nebula factor both scale `r`, and they compose (a cloaked ship inside a nebula is harder still). That is intended.

**Gate on `IsCloaked()`, not `IsTryingToCloak()`** — a mid-cloak ship stays fully visible until the transition completes. That matches the existing comment and the SDK's `SelectTarget`; do not change it.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cloak_detection_contest.py`:

```python
"""Cloak is a range contest, not an absolute — INTENTIONAL divergence from BC.

Every assertion here pins a deliberate gameplay change. If one of these starts
failing, the question is "was the change reverted?", not "what broke?".
"""
from engine.appc import sensor_detection as sd
from engine.appc.sensor_detection import can_detect
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem


def _observer(base_range=2000.0, condition=100.0):
    """Observer with a REAL sensor subsystem — follows
    tests/unit/test_sensor_detection.py::_ship_with_sensor. A bare ShipClass()
    has none, so effective_sensor_range would return FALLBACK_RANGE_GU (30000),
    fifteen times a Galaxy's real reach, and every assertion below would be
    measuring the fallback instead of the thing it names."""
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    return ship


def _target(x, cloaked=False):
    """A contact at (x, 0, 0). Cloak construction follows
    tests/unit/test_select_target_drops_cloaked.py::_kitted_ship."""
    s = ShipClass()
    s.SetName("Warbird")
    s.SetTranslateXYZ(x, 0.0, 0.0)
    if cloaked:
        s.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        s.GetCloakingSubsystem().InstantCloak()
    return s


def test_cloaked_ship_is_detected_inside_one_percent_of_sensor_range():
    """2000 GU sensors give a 20 GU cloak bubble — one third of a Galaxy's
    60 GU phaser range. You must be effectively on top of it."""
    assert can_detect(_observer(), _target(15.0, cloaked=True)) is True


def test_cloaked_ship_is_not_detected_beyond_one_percent():
    assert can_detect(_observer(), _target(25.0, cloaked=True)) is False


def test_uncloaked_ship_at_the_same_distance_is_still_detected():
    """The multiplier must apply ONLY to cloaked targets."""
    assert can_detect(_observer(), _target(25.0)) is True


def test_cloak_reach_scales_with_sensor_condition():
    """It is a percentage of EFFECTIVE range, so damage shrinks it — this is
    what makes boosting sensor power meaningful."""
    assert can_detect(_observer(), _target(15.0, cloaked=True)) is True
    # 50% condition -> 1000 GU effective -> 10 GU cloak reach
    assert can_detect(_observer(condition=50.0),
                      _target(15.0, cloaked=True)) is False


def test_offline_sensors_detect_nothing_even_point_blank():
    """20% is below the default 25% disabled threshold -> range 0."""
    assert can_detect(_observer(condition=20.0),
                      _target(1.0, cloaked=True)) is False


def test_toggle_off_restores_absolute_cloak(monkeypatch):
    """Flipping the flag must return stock BC exactly: cloak is absolute."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert can_detect(_observer(), _target(1.0, cloaked=True)) is False


def test_toggle_off_leaves_uncloaked_detection_untouched(monkeypatch):
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert can_detect(_observer(), _target(500.0)) is True
```

Note `can_detect` reads the flag as a module global, so `monkeypatch.setattr` on the module is the right lever — do not import the constant by value into the function.

**One more test to add, which I could not write for you:** a mid-cloak ship (`IsTryingToCloak`, not yet `IsCloaked`) must stay *fully* visible with no multiplier. Read `CloakingSubsystem`'s cloak-state machine around `engine/appc/subsystems.py:2354` and `:2430` (`_cloak_state`, `CLOAK_CLOAKED`) to find how to drive it into the transitional state, then assert a mid-cloak target at 500 GU is still detected. If the state cannot be reached cleanly from a unit test, say so in your report rather than faking it.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cloak_detection_contest.py -v`
Expected: the detection tests FAIL (cloak currently returns False unconditionally); the toggle-off and offline-sensor tests may already pass.

- [ ] **Step 3: Write minimal implementation**

Add the two constants beside the existing concealment block, with a comment explaining that 1% of *effective* range puts a Galaxy at 20 GU — one third of phaser range — and that the change is symmetric because `can_detect` is also the AI and firing gate. Then apply the `can_detect` change above.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cloak_detection_contest.py -v`

- [ ] **Step 5: Check what else moved — this is the important step**

Run: `uv run pytest tests/unit tests/integration -q`

`can_detect` gates AI target selection, weapon firing, the player's lock, and sensor identification. Existing cloak tests **will** change meaning — for example a test asserting an AI drops a cloaked target may now detect it if the fixture places them close together.

For each failure, decide honestly:
- **Fixture is far apart, still undetected** → should still pass. If it fails, your maths is wrong.
- **Fixture is close together and now detects** → the test is asserting stock-BC cloak behaviour. Move it under the toggle: assert the stock result with the flag off, and add the new result with the flag on. **Do not simply flip the expected value** — that erases the record of what changed.
- **Cannot tell** → report BLOCKED with specifics rather than guessing.

Never delete a test or weaken an assertion.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sensor_detection.py tests/unit/test_cloak_detection_contest.py
git commit -m "feat(sensors): cloak becomes a range contest, not an absolute"
```

Stage any adapted test files by explicit path in the same commit.

---

### Task 2: Nebula concealment reaches the UI

**Files:**
- Modify: `engine/appc/sensor_detection.py` (`can_detect` — accept a precomputed distance)
- Modify: `engine/appc/perception.py` (`perceived_by`)
- Test: `tests/unit/test_nebula_hides_contacts_from_ui.py`

**Interfaces:**
- `can_detect(observer, target, dist_sq_gu=None) -> bool` — new optional third argument. When `None` it computes the distance itself exactly as today, so **every existing caller is unaffected**.

**The problem this solves.** `perceived_by` currently applies its own rule (range + cloak + sensors-offline) and separately computes the squared distance for the record. Switching it to `can_detect` brings nebula concealment and the hysteresis latch to the UI — but `can_detect` recomputes the same distance internally, restoring a duplicate derivation one stage after removing five. Passing the already-computed value fixes that.

**The latch is a correctness requirement, not an optimisation.** `can_detect` mutates a module-global `_broken` set keyed by `(id(observer), id(target))` (`sensor_detection.py:156-162`). Once the UI calls it, the UI drives the same latch the weapons read. `perceived_by` must call it **exactly once per contact per frame**. Its current loop already has that shape — keep it that way, and do not add a second call anywhere.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_nebula_hides_contacts_from_ui.py`. Reuse `_set_with_dense_nebula()` from `tests/unit/test_nebula_concealment.py` (as `tests/unit/test_nebula_list_hoisted.py` already does) rather than building a `MetaNebula` yourself.

```python
def test_a_ship_in_dense_nebula_is_not_perceivable():
    """INTENTIONAL BEHAVIOUR CHANGE. Before stage 4 the target list ignored
    nebulae entirely — you could select and hold a target you could not fire
    on. Detection is now one rule everywhere."""
    # observer outside, target inside the dense clump core
    assert perceived_by(observer)[0].perceivable is False


def test_a_ship_in_clear_space_is_unaffected():
    # same set, target outside the nebula -> perceivable
```

Add a test that the record's `dist_sq_gu` is still correct for a nebula-concealed contact — the contact is not perceivable, but the distance on the record must still be the real one, because the readouts use it.

Add a test pinning that `can_detect` with an explicit `dist_sq_gu` returns the same answer as without it, for the same geometry. That is what protects the optimisation from drifting from the real computation.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula_hides_contacts_from_ui.py -v`
Expected: the concealment test FAILS — `perceived_by` does not consult nebulae yet.

- [ ] **Step 3: Write minimal implementation**

1. Give `can_detect` the optional `dist_sq_gu` parameter. When it is `None`, compute as today. When supplied, skip the `_get_xyz` pair and use it. The rest of the function is untouched.
2. In `perceived_by`, replace the hand-rolled `perceivable = (...)` expression with a single `can_detect(observer, ship, dist_sq_gu=dist_sq)` call, keeping the distance computation that feeds the record.
3. Keep the sensors-offline short-circuit if it saves work, but confirm `can_detect` already returns `False` when `effective_sensor_range` is 0 — it does — so the behaviour is the same either way.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_nebula_hides_contacts_from_ui.py tests/unit/test_perceived_by.py -v`

`test_perceived_by.py` should still pass unedited — its fixtures have no nebulae, so `can_detect` gives the same answers as the old rule. If any of it fails, say which and why before adapting.

- [ ] **Step 5: Full sweep**

Run: `uv run pytest tests/unit tests/integration -q`, then `scripts/check_tests.sh`.

Same rules as Task 1 Step 5 for any test whose meaning changed: move it under the toggle, do not flip expectations, never delete or weaken.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sensor_detection.py engine/appc/perception.py \
        tests/unit/test_nebula_hides_contacts_from_ui.py
git commit -m "feat(perception): one detection rule — nebula concealment reaches the UI"
```

---

### Task 3: Resolve the dead `IsVisible` branch

**Files:**
- Modify: `engine/appc/target_menu.py` (`set_contacts`)
- Modify: `docs/superpowers/plans/2026-08-16-contact-perception-stage-3.md` (retire the precondition)
- Test: whichever file the decision touches

**The situation.** Stage 3 recorded a precondition: when stage 4 decouples `perceivable` from `targetable`, `set_contacts`' `SetNotVisible()` branch goes live having only ever run against synthetic records. **Re-checking after Tasks 1–2, it does not decouple** — `targetable = perceivable and alive_or_wreck and IsTargetable()` still implies `perceivable`, so a contact failing detection vanishes from the list rather than greying out, and the branch stays dead.

Leaving a documented-dead branch is the worst of both worlds: it reads as load-bearing, it has no production coverage, and the note describing it is now wrong.

**Decide and implement one of these.** Read `set_contacts`, the SDK's `CycleTarget` (`sdk/Build/scripts/TacticalInterfaceHandlers.py:701-730`), and stage 3's own docstring on the branch before choosing.

- **(a) Remove the branch.** `set_contacts` lists only targetable contacts and always calls `SetVisible()`. Simplest, and honest about what the code does. Costs the ability to grey out a row without removing it, should that ever be wanted.
- **(b) Keep it and make it reachable** by listing perceivable-but-not-targetable contacts as invisible rows. This is a *visible behaviour change* beyond what this stage was scoped for and would put rows on screen for mission-hidden ships — do not choose this without escalating.

**Recommendation: (a).** It matches what the code actually does today, and (b) is a UI design decision nobody has asked for.

If you choose (a): delete the branch, delete or re-point the two synthetic tests that pinned it (they test a state `perceived_by` cannot produce — deleting tests for a deleted branch is correct, and is not the banned "delete a test to go green"), and **update stage 3's plan document** to retire the precondition, replacing it with a one-line note saying stage 4 resolved it by removing the branch.

- [ ] **Step 1: Decide, and record the decision in the report before writing code**
- [ ] **Step 2: Write or adapt the tests for the chosen path**
- [ ] **Step 3: Implement**
- [ ] **Step 4:** `uv run pytest tests/unit/test_target_menu_visibility_derived.py tests/unit/test_target_menu_derived_children.py -v`
- [ ] **Step 5:** `scripts/check_tests.sh`
- [ ] **Step 6: Commit**

```bash
git add engine/appc/target_menu.py docs/superpowers/plans/2026-08-16-contact-perception-stage-3.md
git commit -m "refactor(target-menu): resolve the dead IsVisible branch"
```

---

## Verification

- [ ] `scripts/check_tests.sh` clean against `tests/known_failures.txt`
- [ ] Flipping `ENHANCED_SENSOR_CONTEST` to `False` restores pre-stage-4 behaviour, proven by test
- [ ] `grep -rn "configuration_panel" ` shows this stage did not touch it
- [ ] Every behaviour change has a test whose comment says it is intentional

**Live verification — this stage changes gameplay, so it is a feel test, not just a regression test.**

1. **Cloak, as attacker.** Cloak (or watch an AI cloak) and approach. Confirm you are *not* detected at medium range and *are* at roughly 20 GU — about a third of phaser range. It should feel like being caught, not like cloak being useless.
2. **Cloak, as defender.** Fight a Bird of Prey or Warbird that cloak-attacks. Confirm cloaked runs still work at range but you can catch them close in. **This is the tuning question** — if cloak now feels worthless, 1% is too generous and wants lowering.
3. **Sensor power.** Boost power to sensors and confirm the cloak-detection bubble grows; take sensor damage and confirm it shrinks.
4. **Nebula.** Fight inside a dense nebula. Contacts should now drop off the target list and radar, not just break weapons lock. Confirm they fade rather than strobe — the hysteresis latch is what prevents flicker.
5. **Clear space unchanged.** A normal engagement outside a nebula with nobody cloaked should feel exactly as it did before.

Item 2 is the one that decides whether the number is right.

## Out of scope

- Exposing the toggle in the UI. Deliberately code-only for now.
- `FALLBACK_RANGE_GU = 30000` being 15× a Galaxy's real 2,000 GU — confirm the player never lands on that path.
- Hail and Science-scan menus adopting the shared query with their own authored gates.
- The targetable gate reaching the radar (a mission-hidden ship is not blipped) — observed acceptable in the stage 1–2 live pass, still unverified as *correct*.
- `sensor_detection.can_detect` and `weapons_display_panel.py` still deriving the player→target vector independently of the record.
