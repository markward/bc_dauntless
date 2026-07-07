# AI Focus-Loss Lifecycle (Cloak Cadence, Part A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the AI driver the missing `LostFocus` half of the preprocessor focus lifecycle so cloak-capable NPCs decloak to attack and re-cloak (SDK `CloakShip.LostFocus → StopCloaking`).

**Architecture:** Each container ticks exactly one child per tick, so at any tick a single active path is "focused." `tick_ai` gains a re-entrancy guard identifying the root (per-ship) call; the root collects which `PreprocessingAI` nodes were reached this tick and dispatches `LostFocus()` to any node that was focused last tick but not this one, resetting its focus flags so re-entry re-fires `GotFocus`. General (drives `CloakShip`, `FireScript`, `AlertLevel`).

**Tech Stack:** Python 3 (engine/appc), pytest. Pure-Python — no C++ rebuild.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-ai-focus-loss-lifecycle-design.md`.
- Change confined to `engine/appc/ai_driver.py` + `engine/appc/subsystems.py` + new tests. **No C++ rebuild.**
- Focus loss is **general**: dispatch `LostFocus()` for any preprocessor that defines it (not cloak-only).
- The reconciliation runs once per **root** tick (outermost `tick_ai`, one per ship from `tick_all_ai`); recursive calls into children must not reconcile.
- Per-root state (`_focused_preprocessors`) lives on the root AI object; two ships must not cross-contaminate.
- Membership tests use object **identity** (`id(node)`), not `==`.
- Dev diagnostics use `print()` gated by `dev_mode.is_enabled()` — **never `logging`** (host has no logging handler). `[cloak]` prefix, off in production.
- Test gate: `scripts/check_tests.sh` (pytest + ctest). Baseline failures only those in `tests/known_failures.txt`.
- `US_ACTIVE = 0`, `US_DORMANT = 2` (class consts on `ArtificialIntelligence`). Priority list: lower priority-int = higher priority.

---

### Task 1: Focus-loss lifecycle in the AI driver

**Files:**
- Modify: `engine/appc/ai_driver.py` (wrap `tick_ai` with a root guard + reconciliation; extract the current body to `_dispatch_ai`; add `_reconcile_focus`, `_dispatch_lost_focus`; record reached nodes in `_tick_preprocessing`)
- Test: `tests/unit/test_ai_driver_focus_loss.py` (new)

**Interfaces:**
- Consumes: `PreprocessingAI`, `PriorityListAI_Create`, `ArtificialIntelligence` from `engine.appc.ai`; `tick_ai` from `engine.appc.ai_driver`; `ShipClass` from `engine.appc.ships`.
- Produces: module-level `_dispatch_lost_focus(node)`, `_reconcile_focus(root_ai, reached)` in `engine.appc.ai_driver`; `tick_ai` now dispatches `LostFocus()` on focus loss and resets `node._has_focus` / `node.__dict__["_got_focus_called"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ai_driver_focus_loss.py`:

```python
"""AI driver focus-loss lifecycle: a PreprocessingAI that drops off the active
dispatch path must receive LostFocus() and have its focus flags reset, so the
SDK cloak cadence (CloakShip.LostFocus -> StopCloaking) works. See
docs/superpowers/specs/2026-07-07-ai-focus-loss-lifecycle-design.md.
"""
from engine.appc.ai import (
    PreprocessingAI, PriorityListAI_Create, ArtificialIntelligence,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DORMANT = ArtificialIntelligence.US_DORMANT


class _WithLostFocus:
    def __init__(self):
        self.got = 0
        self.lost = 0
    def GotFocus(self):
        self.got += 1
    def LostFocus(self):
        self.lost += 1
    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


class _NoLostFocus:
    def __init__(self):
        self.got = 0
    def GotFocus(self):
        self.got += 1
    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


def _pp(inst, name):
    pp = PreprocessingAI(ShipClass(), name)
    pp.SetPreprocessingMethod(inst, "Update")
    return pp


def _list_with(a_pp, b_pp):
    pl = PriorityListAI_Create(None, "PL")
    pl.AddAI(a_pp, 0)   # a is higher priority (lower int)
    pl.AddAI(b_pp, 1)
    return pl


def test_lost_focus_when_node_drops_off_active_path():
    ia, ib = _WithLostFocus(), _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(ib, "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)                     # a eligible -> a focused
    assert ia.got == 1 and ia.lost == 0
    a._status = US_DORMANT               # a no longer eligible
    tick_ai(pl, 1.0)                     # b focused, a drops -> a.LostFocus
    assert ia.lost == 1
    assert a._has_focus is False
    assert a.__dict__.get("_got_focus_called") is False


def test_regaining_focus_refires_got_focus():
    ia = _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)                     # a focused, got=1
    a._status = US_DORMANT
    tick_ai(pl, 1.0)                     # a drops -> lost=1
    a._status = US_ACTIVE
    tick_ai(pl, 2.0)                     # a re-focused -> got=2
    assert ia.got == 2
    assert ia.lost == 1


def test_node_staying_on_path_keeps_focus():
    ia = _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)
    tick_ai(pl, 1.0)
    tick_ai(pl, 2.0)
    assert ia.got == 1
    assert ia.lost == 0


def test_no_lost_focus_method_is_noop_but_resets_flags():
    ia = _NoLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)
    a._status = US_DORMANT
    tick_ai(pl, 1.0)                     # a drops; no LostFocus -> no error
    assert a._has_focus is False
    assert a.__dict__.get("_got_focus_called") is False


def test_two_ships_focus_isolated():
    ia, ib = _WithLostFocus(), _WithLostFocus()
    a1, b1 = _pp(ia, "A1"), _pp(_WithLostFocus(), "B1")
    a2, b2 = _pp(ib, "A2"), _pp(_WithLostFocus(), "B2")
    pl1, pl2 = _list_with(a1, b1), _list_with(a2, b2)
    tick_ai(pl1, 0.0)
    tick_ai(pl2, 0.0)
    a1._status = US_DORMANT              # only ship1's A drops
    tick_ai(pl1, 1.0)
    tick_ai(pl2, 1.0)
    assert ia.lost == 1
    assert ib.lost == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ai_driver_focus_loss.py -v`
Expected: FAIL — `test_lost_focus_when_node_drops_off_active_path` etc. assert `ia.lost == 1` but no `LostFocus` is dispatched yet (`lost == 0`).

- [ ] **Step 3: Implement the lifecycle in `engine/appc/ai_driver.py`**

Replace the existing `tick_ai` function (currently `def tick_ai(ai, game_time)` at ~line 36 through its final `return ai._status`) with the guard wrapper + extracted dispatch + helpers:

```python
# Focus-loss lifecycle state. tick_ai is single-threaded (one ship at a time),
# so module-level scratch is safe. _reached_this_tick collects the
# PreprocessingAI nodes reached (== focused) during the current root tick.
_focus_depth = 0
_reached_this_tick: list = []


def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree; reconcile preprocessor focus at the root call.

    The outermost tick_ai call (one per ship, from tick_all_ai) is the root: it
    collects which PreprocessingAI nodes were reached (== on the active path ==
    focused) this tick, then dispatches LostFocus() to any node that was focused
    last tick but not this one. Recursive calls into children just dispatch."""
    global _focus_depth, _reached_this_tick
    is_root = _focus_depth == 0
    if is_root:
        _reached_this_tick = []
    _focus_depth += 1
    try:
        status = _dispatch_ai(ai, game_time)
    finally:
        _focus_depth -= 1
    if is_root and ai is not None:
        _reconcile_focus(ai, _reached_this_tick)
    return status


def _dispatch_ai(ai, game_time: float) -> int:
    """Type-dispatch one AI node (the former body of tick_ai)."""
    if ai is None:
        return US_DONE
    # Inert-coast gate: a dying/dead ship issues no new orders.
    from engine.appc import ship_death
    ship = ai.GetShip() if hasattr(ai, "GetShip") else None
    if ship is not None and ship_death._out_of_action(ship):
        return US_DONE
    if isinstance(ai, BuilderAI):
        return _tick_builder(ai, game_time)
    if isinstance(ai, PreprocessingAI):
        return _tick_preprocessing(ai, game_time)
    if isinstance(ai, ConditionalAI):
        return _tick_conditional(ai, game_time)
    if isinstance(ai, PriorityListAI):
        return _tick_priority_list(ai, game_time)
    if isinstance(ai, SequenceAI):
        return _tick_sequence(ai, game_time)
    if isinstance(ai, RandomAI):
        return _tick_random(ai, game_time)
    if isinstance(ai, PlainAI):
        return _tick_plain(ai, game_time)
    return ai._status


def _reconcile_focus(root_ai, reached) -> None:
    """Dispatch LostFocus() to preprocessors focused last tick but not this one.

    Identity-based: `reached` holds the PreprocessingAI nodes ticked this root
    tick. Any node in the root's previous focused set that is not among them has
    left the active dispatch path."""
    reached_ids = {id(n) for n in reached}
    for node in getattr(root_ai, "_focused_preprocessors", ()):
        if id(node) not in reached_ids:
            _dispatch_lost_focus(node)
    root_ai._focused_preprocessors = list(reached)


def _dispatch_lost_focus(node) -> None:
    """Call the preprocessor instance's LostFocus() (if any) and clear the
    node's focus latches so a later re-entry re-fires GotFocus()."""
    inst = getattr(node, "_preprocessing_instance", None)
    lost = getattr(inst, "LostFocus", None) if inst is not None else None
    if callable(lost):
        lost()
    node._has_focus = False
    node.__dict__["_got_focus_called"] = False
```

Then record reached nodes in `_tick_preprocessing`: immediately after the existing `ai._has_focus = True` line (~line 389), add:

```python
    # Focus-loss lifecycle: record that this preprocessor was reached (focused)
    # this tick, so the root reconciliation (see tick_ai / _reconcile_focus) can
    # LostFocus() any node that drops off the active path next tick.
    _reached_this_tick.append(ai)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ai_driver_focus_loss.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the AI-driver regression tests**

Run: `uv run pytest tests/unit/test_ai_driver.py tests/unit/test_ai_driver_got_focus.py tests/unit/test_force_update_reschedule.py tests/unit/test_ai_primitives.py -q`
Expected: PASS (no regressions from the tick_ai refactor).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai_driver.py tests/unit/test_ai_driver_focus_loss.py
git commit -m "feat(ai): general focus-loss lifecycle (dispatch LostFocus on path change)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Dev-mode `[cloak]` transition prints

**Files:**
- Modify: `engine/appc/subsystems.py` (`CloakingSubsystem.StartCloaking`, `StopCloaking`, `_force_decloak`)
- Test: `tests/unit/test_cloak_dev_log.py` (new)

**Interfaces:**
- Consumes: `dev_mode.is_enabled()` (already imported as `import engine.dev_mode as dev_mode` at `subsystems.py:21`); `CloakingSubsystem.GetParentShip()`.
- Produces: a private `CloakingSubsystem._cloak_dev_log(verb)` printing `[cloak] <ship> -> <verb>` when dev mode is on.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cloak_dev_log.py`:

```python
"""Dev-mode [cloak] transition prints (print(), not logging — the host has no
logging handler). Off in production."""
from engine import dev_mode
from engine.appc.subsystems import CloakingSubsystem
from engine.appc.ships import ShipClass


def _cloak_on_ship(name="Warbird 1"):
    ship = ShipClass()
    ship.SetName(name)
    cloak = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cloak)   # _attach_subsystem sets _parent_ship
    return ship, cloak


def test_cloak_prints_when_dev_mode_on(monkeypatch, capsys):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    ship, cloak = _cloak_on_ship()
    cloak.StartCloaking()
    out = capsys.readouterr().out
    assert "[cloak]" in out
    assert "Warbird 1" in out
    assert "cloaking" in out


def test_decloak_prints_when_dev_mode_on(monkeypatch, capsys):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    ship, cloak = _cloak_on_ship()
    cloak.InstantCloak()               # -> CLOAKED so StopCloaking is not a no-op
    capsys.readouterr()                # drain
    cloak.StopCloaking()
    out = capsys.readouterr().out
    assert "[cloak]" in out
    assert "decloaking" in out


def test_cloak_silent_when_dev_mode_off(monkeypatch, capsys):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    ship, cloak = _cloak_on_ship()
    cloak.StartCloaking()
    out = capsys.readouterr().out
    assert "[cloak]" not in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cloak_dev_log.py -v`
Expected: FAIL — no `[cloak]` output yet.

- [ ] **Step 3: Implement the dev log in `engine/appc/subsystems.py`**

Add a helper method to `CloakingSubsystem` (place it next to `_force_decloak`):

```python
    def _cloak_dev_log(self, verb: str) -> None:
        """Dev-mode-only transition trace. print(), not logging — the host
        configures no logging handler, so logging.* is swallowed. Matches the
        [viewscreen]/[ai] convention; off in production."""
        if not dev_mode.is_enabled():
            return
        ship = self.GetParentShip() if hasattr(self, "GetParentShip") else None
        name = ship.GetName() if (ship is not None and hasattr(ship, "GetName")) else "<ship>"
        print(f"[cloak] {name} -> {verb}")
```

Then call it from each transition:
- In `StartCloaking`, after `self._cloak_state = self.CLOAK_CLOAKING` (before/after the event fire): `self._cloak_dev_log("cloaking")`.
- In `StopCloaking`, after `self._cloak_state = self.CLOAK_DECLOAKING`: `self._cloak_dev_log("decloaking")`.
- In `_force_decloak`, inside the `if self._cloak_state in (CLOAKING, CLOAKED)` block (i.e. only when it actually acts), after setting `self._cloak_state = self.CLOAK_DECLOAKED`: `self._cloak_dev_log("forced decloak")`.

(Place each call so it only fires when the method actually changes state — i.e. after the early-return no-op guards.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_cloak_dev_log.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_cloak_dev_log.py
git commit -m "feat(cloak): dev-mode [cloak] transition prints for live verification

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Integration — real CloakShip decloaks on focus loss, re-cloaks on regain

**Files:**
- Test: `tests/integration/test_cloak_focus_cadence.py` (new)

**Interfaces:**
- Consumes: `AI.Preprocessors.CloakShip`; `PreprocessingAI`, `PriorityListAI_Create`, `ArtificialIntelligence` from `engine.appc.ai`; `tick_ai`; `ShipClass`, `CloakingSubsystem`; Task 1's lifecycle.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_cloak_focus_cadence.py`:

```python
"""End-to-end: the SDK CloakShip preprocessor cloaks on GotFocus and decloaks
on LostFocus, driven by Task 1's focus-loss lifecycle when the AI tree switches
the active branch. This is the cloak decloak-to-attack cadence."""
from AI.Preprocessors import CloakShip
from engine.appc.ai import (
    PreprocessingAI, PriorityListAI_Create, ArtificialIntelligence,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DORMANT = ArtificialIntelligence.US_DORMANT


class _Plain:
    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


def _ship_with_cloak():
    ship = ShipClass()
    ship.SetName("Warbird 1")
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship


def test_cloakship_cadence_via_focus_loss():
    ship = _ship_with_cloak()
    cloak_inst = CloakShip(1)                      # bCloakOn = 1
    cloak_pp = PreprocessingAI(ship, "Cloak")
    cloak_pp.SetPreprocessingMethod(cloak_inst, "Update")   # sets cloak_inst.pCodeAI = cloak_pp
    other_pp = PreprocessingAI(ship, "Fire")
    other_pp.SetPreprocessingMethod(_Plain(), "Update")

    pl = PriorityListAI_Create(None, "PL")
    pl.AddAI(cloak_pp, 0)                           # cloak higher priority
    pl.AddAI(other_pp, 1)

    # Cloak node focused -> GotFocus -> CheckCloak -> StartCloaking.
    tick_ai(pl, 0.0)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 1

    # Tree switches to the fire branch: cloak node drops off the active path ->
    # LostFocus -> StopCloaking.
    cloak_pp._status = US_DORMANT
    tick_ai(pl, 1.0)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 0

    # Tree returns to the cloak branch -> GotFocus re-fires -> re-cloak.
    cloak_pp._status = US_ACTIVE
    tick_ai(pl, 2.0)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 1
```

- [ ] **Step 2: Run to verify it passes (Task 1 already provides the mechanism)**

Run: `uv run pytest tests/integration/test_cloak_focus_cadence.py -v`
Expected: PASS. (If the first decloak assertion fails, the cloak node's `LostFocus` isn't dispatching — check Task 1's `_reconcile_focus`.)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_cloak_focus_cadence.py
git commit -m "test(cloak): CloakShip decloak-to-attack cadence via focus loss

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Full gate + live verification handoff

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. In particular, combat smoke tests must still pass with `FireScript.LostFocus → StopFiring` and `AlertLevel` restore now firing — if a combat test regresses (e.g. a ship stops firing when it shouldn't), that is a real finding: investigate whether the ship's fire branch is incorrectly losing focus. Any failure not in `tests/known_failures.txt` blocks completion.

- [ ] **Step 2: Present the in-game live-test checklist to the user**

Python-only — **no `cmake` rebuild**. Give the user these steps:

1. Launch **from a terminal** (stdout visible): `./build/dauntless --developer`
2. Start a battle with a cloak-capable enemy (Warbird / Bird-of-Prey) — QuickBattle or a combat mission via the dev **Load Mission…** picker.
3. Watch stdout for `[cloak] <ship> -> cloaking`, then as it closes to attack `[cloak] <ship> -> decloaking`, and re-cloaking later. **Expected:** ships decloak to fire and re-cloak on a cycle — not hide forever (the pre-fix behavior you saw: cloaked and held for 10+ minutes).
4. Confirm visually: decloak → weapons fire → re-cloak, rather than a permanently-cloaked ghost.

If ships still never decloak, capture the `[cloak]` stdout lines (or their absence) — absence of a `decloaking` line means the cloak node never loses focus (AI-tree/timer issue), not the lifecycle.

- [ ] **Step 3: Update memory after live-verify**

Once the user confirms decloak-to-attack in game, update `project_cloaking_system.md` (memory): Part A DONE + live-verified, note the branch/commits; mark the "decloak→re-acquire cadence" follow-on resolved.

---

## Self-Review

**Spec coverage:**
- Root cause (GotFocus without LostFocus) → Task 1. ✓
- General focus-loss mechanism (root guard, reconciliation, identity membership, flag reset, re-GotFocus) → Task 1 impl + tests. ✓
- Edge cases: no-LostFocus no-op (Task 1 test 4), two-ship isolation (test 5), stays-focused (test 3), re-entry re-GotFocus (test 2). ✓
- Dev-mode `[cloak]` prints, print-not-logging, off in production → Task 2. ✓
- Integration cadence (CloakShip decloak on focus loss + re-cloak) → Task 3. ✓
- Regression (FireScript/AlertLevel LostFocus now firing) → Task 4 Step 1. ✓
- Live verification → Task 4 Step 2. ✓
- Out-of-scope (B reserve depletion, C defensive cloak, transition-duration tuning) → untouched. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. Task 2 Step 3 describes exact call sites in prose because they interleave with existing method bodies, but names the exact line/state to place each call after.

**Type consistency:** `_dispatch_lost_focus(node)` / `_reconcile_focus(root_ai, reached)` used identically in impl and reasoning. `_reached_this_tick` / `_focus_depth` module globals consistent between `tick_ai` and `_tick_preprocessing`. `ai._preprocessing_instance` (source of `LostFocus`) matches `_tick_preprocessing:350`. Focus latches `_has_focus` / `_got_focus_called` match the existing `_tick_preprocessing` names (389/400). `IsTryingToCloak()` returns 1/0 as used in Task 3.
