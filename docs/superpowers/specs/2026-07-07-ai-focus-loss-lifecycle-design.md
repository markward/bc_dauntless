# AI Focus-Loss Lifecycle (Cloak Decloak-to-Attack Cadence) — Design

**Date:** 2026-07-07
**Status:** Approved (design), pending implementation plan
**Scope:** Part **A** of the cloak-behavior work — make cloak-capable NPCs decloak
to attack and re-cloak, by giving the AI driver the missing `LostFocus` half of
the preprocessor focus lifecycle. **Step 0** (reserve-based auto-decloak) is already
merged on `feat/cloak-behavior`. Parts **B** (genuine reserve depletion) and **C**
(defensive cloak-to-repair) are separate specs.

## Problem

Cloak-capable NPCs cloak and then stay hidden for the rest of the battle — they
never decloak to attack. (Confirmed live: ships cloaked and held for 10+ minutes
with no decloak.)

### Root cause

The AI driver implements only *half* of the SDK preprocessor focus lifecycle:
- `_tick_preprocessing` sets `ai._has_focus = True` and calls `GotFocus()` once
  (latched by `_got_focus_called`) — `engine/appc/ai_driver.py:389,400`.
- Nothing ever calls `LostFocus()`, and `_has_focus` / `_got_focus_called` are
  never cleared.

The **only** AI decloak trigger in stock BC is `CloakShip.LostFocus() →
StopCloaking()` (`sdk/Build/scripts/AI/Preprocessors.py:2098`), fired when the AI
tree shifts focus off the cloak branch to the fire branch. Since the driver never
dispatches `LostFocus`, `StopCloaking` never runs, so the authored
`CloakAttack` cadence (approach cloaked → decloak → fire → re-cloak) is dead. The
cloaked attacker keeps its target the whole time (`sensor_detection.can_detect`
gates on the *target* being cloaked, not the observer) — it simply sits cloaked
with no node telling it to decloak.

Two other SDK preprocessors also define `LostFocus` and are equally inert today:
- `FireScript.LostFocus → StopFiring` (`Preprocessors.py:266`)
- `AlertLevel.LostFocus → restore previous alert` (`Preprocessors.py:2054`)

## Approach

**Add a general focus-loss lifecycle to the AI driver.** Each container dispatches
exactly one child per tick (`_tick_priority_list` returns after the first eligible
child; `_tick_sequence` holds on its active index), so at any tick there is a
single active path root→leaf, and the `PreprocessingAI` nodes on it are "focused."
When a condition/timer flips the active path, nodes that drop off it have lost
focus.

Mechanism, entirely in `engine/appc/ai_driver.py`:

1. **Root-tick detection.** A module-level re-entrancy depth counter in `tick_ai`.
   The outermost call (per ship, from `tick_all_ai`) is the root; recursive calls
   into children are not. `tick_all_ai` calls `tick_ai(ship_root)` once per ship,
   so each is a root.
2. **Focus collection.** At root entry, reset a module-level `_reached_this_tick`
   list. `_tick_preprocessing` appends its `PreprocessingAI` node to it. The
   collected set == the preprocessors on the active path == currently focused.
3. **Reconciliation at root-tick exit.** Compare `_reached_this_tick` against
   `root_ai._focused_preprocessors` (last tick's focused set, stored on the root AI
   object). Every node focused last tick but **not** reached this tick has lost
   focus: dispatch `node._preprocessing_instance.LostFocus()` if defined, and reset
   `node._has_focus = False` and `node._got_focus_called = False` so a later
   re-entry re-fires `GotFocus`. Store `_reached_this_tick` as the new
   `root_ai._focused_preprocessors`.

Net effect: when the tree switches from the Cloak branch to the Fire branch,
`CloakShip.LostFocus() → StopCloaking()` fires (decloak to attack); when it returns
to the Cloak branch, `GotFocus() → StartCloaking()` re-fires (re-cloak). That is the
SDK's authored cadence. The same machinery correctly drives `FireScript.StopFiring`
(a ship that leaves its fire branch stops firing) and `AlertLevel` restore.

### "General" vs "cloak-only" (decided: general)

Dispatching `LostFocus` for any preprocessor that defines it is the faithful BC
model (focus loss is a tree-wide lifecycle) and de-risks Parts B/C and future
doctrines. The blast radius — `FireScript.StopFiring` and `AlertLevel` restore now
firing — is *more correct*, and the full test gate + combat smoke tests are the
safety net. A cloak-only special-case was rejected as a hack that ignores the real
model.

## Components / mechanism detail

### 1. `tick_ai` re-entrancy guard + reconciliation — `engine/appc/ai_driver.py`

- Module-level `_tick_depth` (int) and `_reached_this_tick` (list).
- `tick_ai(ai, game_time)`: `is_root = (_tick_depth == 0)`; if root, `_reached_this_tick = []`.
  Increment `_tick_depth`; run the existing type-dispatch in a `try`; decrement in
  `finally`. If `is_root`, call `_reconcile_focus(ai, _reached_this_tick)` after the
  dispatch. Return status unchanged.
- `_reconcile_focus(root_ai, reached)`: `prev = getattr(root_ai, "_focused_preprocessors", [])`;
  for each `node` in `prev` not in `reached`, call `_dispatch_lost_focus(node)`;
  set `root_ai._focused_preprocessors = list(reached)`. Membership uses object
  identity (the same `PreprocessingAI` instances).
- `_dispatch_lost_focus(node)`: `inst = node._preprocessing_instance`; if `inst` has
  a callable `LostFocus`, call it; set `node._has_focus = False` and
  `node._got_focus_called = False`.

### 2. Focus collection in `_tick_preprocessing`

Append `ai` to `_reached_this_tick` at the point focus is asserted (alongside the
existing `ai._has_focus = True`, ~line 389).

### 3. Dev-mode `[cloak]` observability — `engine/appc/subsystems.py`

Gated by `engine.dev_mode.is_enabled()`, **`print()` (not `logging` — swallowed by
the host)**, matching the `[viewscreen]`/`[ai]` convention. Emit on cloak state
transitions in `CloakingSubsystem`:
- `StartCloaking` → `[cloak] <ship> -> cloaking`
- `StopCloaking` → `[cloak] <ship> -> decloaking`
- `_force_decloak` → `[cloak] <ship> -> forced decloak`

Ship name via `GetParentShip().GetName()` when available; guard for a missing
parent. Off in production.

## Error handling / edge cases

| Case | Behavior |
|---|---|
| Preprocessor without `LostFocus` | `_dispatch_lost_focus` is a no-op for it (still resets focus flags) |
| Node still on the active path | in `reached` → not dispatched (keeps focus) |
| Two ships ticked in one frame | per-root-AI `_focused_preprocessors`; module `_reached_this_tick` reset at each root entry — no cross-contamination |
| Mission swap / new AI tree | fresh root AI object → no `_focused_preprocessors` → clean start |
| Nested `tick_ai` (containers) | depth counter ensures only the outermost call reconciles |
| Exception mid-dispatch | `_tick_depth` decremented in `finally`; reconciliation still runs for the root |
| Focus thrashing (path oscillates tick-to-tick) | bounded by the SDK's own timers / `NeedPower≥80%` gating + cloak transition durations; watch in live test |

## Testing

### Unit (`tests/unit/`, focus lifecycle)

1. A preprocessor focused then dropped from the active path gets `LostFocus()`
   dispatched and its `_has_focus`/`_got_focus_called` reset.
2. After a drop, re-entering the node re-fires `GotFocus()`.
3. A node that stays on the active path across ticks does **not** get `LostFocus`.
4. A preprocessor without a `LostFocus` method is a no-op (no error), flags still reset.
5. Two independent ship trees don't cross-contaminate focus (ship A losing focus
   doesn't dispatch on ship B's nodes).
6. Nested container dispatch still reconciles once (outermost root only).

### Integration (`tests/integration/`, cadence)

7. A `CloakShip` whose parent container switches branch dispatches `StopCloaking`
   (headless): build a PriorityList/Sequence with a Cloak node and a sibling; flip
   the active branch; assert `StopCloaking` fired.
8. A headless `CloakAttack` ship: after cloaking, when the tree moves to the fire
   branch it decloaks, and re-cloaks when it returns — no hide-forever.

### Regression

9. Combat smoke tests still pass with `FireScript.StopFiring` / `AlertLevel` restore
   now firing (`AlertLevel` stays focused through sustained combat, so red alert
   does not drop; ships still fire). Run the full gate `scripts/check_tests.sh`.

This is a pure-Python change (`ai_driver.py` + `subsystems.py`) — **no C++ rebuild**.

### Live verification

The change is Python-only; **no `cmake` rebuild needed**. Steps:

1. Launch **from a terminal** (stdout visible): `./build/dauntless --developer`
2. Start a battle with a cloak-capable enemy (Warbird / Bird-of-Prey) — QuickBattle
   or a combat mission via the dev **Load Mission…** picker.
3. Watch stdout for `[cloak] <ship> -> cloaking` then, as it closes/attacks,
   `[cloak] <ship> -> decloaking`, and re-cloaking later. **Expected:** ships
   decloak to fire and re-cloak on a cycle — not hide forever.
4. Visually confirm the decloak/attack/re-cloak cadence (refraction VFX + weapons
   fire) rather than a permanently-cloaked ghost.

If ships still never decloak, capture the stdout `[cloak]` lines (or their absence)
so we can see whether `StopCloaking` is dispatching.

## Out of scope

- **Part B** — making the reserve genuinely deplete so exhaustion forces a decloak.
- **Part C** — defensive cloak-to-repair (net-new AI decision node).
- Cloak transition-duration tuning (the fade takes ~4.5 s; separate tuning pass).
- Any change to the cloak power model (Step 0 already fixed the auto-decloak trigger).
