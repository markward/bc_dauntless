# Cloak as a Managed Survival Resource (B + C) — Design

**Date:** 2026-07-07
**Status:** Approved (design), pending implementation plan
**Scope:** Parts **B** (reserve depletion) + **C** (defensive cloak-to-repair) of the
cloak-behavior work. Builds on **Step 0** (reserve-based auto-decloak) and **Part A**
(decloak-to-attack cadence), both merged to `main`.

## Goal

Turn cloak from a free "I win" button into a **managed survival resource**:
- **B:** sustained cloak genuinely drains the reserve battery; a healthy reactor keeps
  it topped up, a damaged one loses ground and the reserve empties → the ship is
  forced to decloak (Step 0's guard). "Damaged drains faster" emerges from the
  existing reactor-condition scaling.
- **C:** a crippled cloak-capable NPC breaks off, cloaks, and repairs in hiding, then
  either re-attacks once repaired or is flushed out early when its reserve runs dry
  (the **healed-or-forced** loop).

## Component B — Reserve depletion

### Mechanism

Today a cloaked ship's reserve barely drains: the cloak's draw is throttled to the
backup **conduit** rate (~300/s on a Warbird) while the reactor refills ~1500/s. Give
`CloakingSubsystem` a `DRAWS_DIRECT_FROM_RESERVE` class flag (mirroring
`TractorBeamSystem.DRAWS_DIRECT_FROM_MAIN`) so its per-frame `_update_power` draws via
`power.StealPowerFromReserve(base)` — the existing backup-only direct-draw path
(`subsystems.py:1639`) — at its **full authored rate**, bypassing the conduit throttle.

- The reserve now changes by `reactor_output × condition% (refill, main-first spill)`
  minus the cloak draw each interval.
- Whether a ship **sustains** cloak is `reactor_output × condition%` vs the cloak drain:
  a healthy reactor stays ahead; a damaged reactor falls behind → reserve empties →
  Step 0's `_backup_reserve <= MIN_RESERVE_TO_HOLD_CLOAK` guard force-decloaks it.
- The Step 0 reserve snapshot (`CloakingSubsystem._update_power` → `_backup_reserve`)
  already reads the post-draw reserve, so the exhaustion path works unchanged.

### Draw rate is a single tunable constant

Expose the cloak's reserve drain as `CLOAK_RESERVE_DRAIN_PER_SECOND` (module constant on
`CloakingSubsystem`, **no hardpoint edits**), used as the `base` for
`StealPowerFromReserve`. Default chosen so the **crossover sits near reactor output** —
a healthy ship sustains cloak, a damaged one is flushed out.

**Tuning tension (documented, Mark tunes by eye — [[feedback_vfx_calibrate_up_then_down]]):**
a clean "healthy sustains / damaged flushed" crossover requires the drain to sit near
reactor output (~1000–1200/s), which against a 200 000 reserve makes depletion take
on the order of a minute-plus (comparable to the repair timescale — acceptable). Driving
the drain far above reactor output would flush ships in seconds but also deplete healthy
ships. Starting value biases to the crossover behavior; it is the primary live-tune.

## Component C — Defensive cloak-to-repair

### Structure

New module `engine/appc/defensive_cloak.py` exposing `tick_defensive_cloak(dt)`, called
from `engine/core/loop.py` beside `tick_collision_avoidance` (the established pattern
for engine behavior overlaid on the SDK AI). It keeps a per-ship mode and applies to
**any AI ship with a functional (non-disabled, non-destroyed) cloaking subsystem**,
regardless of offensive doctrine.

Per-ship state (keyed by ship, cleared on death / set exit): `mode ∈ {NORMAL, DEFENSIVE}`.

### Transitions

**Enter (NORMAL → DEFENSIVE):** all of —
- ship is AI-controlled (`GetAI()` is not None) and has a functional cloaking subsystem,
- hull `GetHull().GetConditionPercentage() < CLOAK_HULL_THRESHOLD` (default 0.35),
- ship is in combat (`GetTarget()` is not None — a simple, tunable combat proxy),
- not already DEFENSIVE.
→ `cloak.StartCloaking()`, set mode = DEFENSIVE.

**While DEFENSIVE:**
- The ship's **SDK AI tick is suppressed**: `tick_all_ai` skips a ship for which
  `defensive_cloak.is_defensive(ship)` is true. This is the conflict-avoidance seam —
  Part A's `CloakShip`/focus lifecycle does not run for a defensively-cloaked ship, so
  the engine controller and the SDK tree never both drive the cloak.
- The ship coasts (no active flee in v1 — it is invisible/untargetable while cloaked, so
  hiding needs no repositioning). `tick_collision_avoidance` and `tick_all_ship_motion`
  still run; `RepairSubsystem.Update` heals it (loop-driven, AI-independent).

**Exit (DEFENSIVE → NORMAL), whichever comes first:**
- **Healed:** hull `>= FIT_TO_FIGHT_THRESHOLD` (default 0.70; the 0.35→0.70 gap is the
  hysteresis that prevents cloak/decloak thrash) → `cloak.StopCloaking()`, mode = NORMAL.
  SDK AI resumes → re-attacks.
- **Forced out:** B's reserve exhaustion already tripped Step 0's auto-decloak, so the
  cloak is no longer engaged (`not cloak.IsTryingToCloak()`) → the controller detects it,
  sets mode = NORMAL (does not re-cloak). SDK AI resumes → back in the fight, still hurt.
- **Cloak lost:** the cloaking subsystem became disabled/destroyed → mode = NORMAL, SDK
  AI resumes.

### Interaction summary

Step 0 makes cloak **hold**; Part A makes offensive ships **decloak-to-attack**; B makes
the reserve **finite**; C decides **when a hurt ship hides**, owning it fully during the
hide. No two mechanisms drive the cloak at once (C suppresses the SDK tree while DEFENSIVE).

## Observability

Extend the Part A dev-mode `[cloak]` prints (print, not logging — the host has no logging
handler; off in production) with the defensive transitions, emitted from
`defensive_cloak.py` gated by `dev_mode.is_enabled()`:
- enter → `[cloak] <ship> -> defensive hide (hull NN%)`
- healed exit → `[cloak] <ship> -> re-engaging (repaired NN%)`
- forced-out exit is already visible via Step 0's `[cloak] <ship> -> forced decloak`.

## Error handling / edge cases

| Case | Behavior |
|---|---|
| Player ship | Never affected — controller only touches ships with `GetAI() is not None`; the player has no AI. |
| Cloak disabled/destroyed while DEFENSIVE | Exit to NORMAL, resume SDK AI (a broken cloak can't hide). |
| Ship dies while DEFENSIVE | Per-ship state cleared on death (`ship_death`/set-exit); no dangling mode. |
| No target (out of combat) when hull drops | Does not enter DEFENSIVE (combat proxy `GetTarget()`); a ship damaged by e.g. an asteroid with no enemy won't hide. |
| Already offensively cloaked when hull crosses threshold | Smooth: already CLOAKED; controller takes ownership, keeps it cloaked, suppresses SDK tree. |
| Mission swap / new ship | Fresh ship object → NORMAL by default; stale per-ship state must not leak across swaps (clear on set exit, mirror existing globals-reset patterns). |
| Repair bay destroyed | Ship hides but never heals → eventually forced out by B (reserve exhaustion) — correct. |

## Testing

### Unit — B (`tests/unit/`)
1. A cloaked ship with `DRAWS_DIRECT_FROM_RESERVE` draws its full `CLOAK_RESERVE_DRAIN_PER_SECOND` from the reserve (reserve drops at the full rate, not the conduit-throttled rate).
2. Healthy reactor (condition 1.0, output > drain): reserve stays > 0 over a long run → stays cloaked.
3. Damaged reactor (condition low, output < drain): reserve drains to 0 → Step 0 auto-decloak fires → `IsTryingToCloak()` becomes 0.

### Unit — C (`tests/unit/`)
4. Enter: an AI ship with a functional cloak, a target, and hull < 0.35 → `StartCloaking` called, mode DEFENSIVE.
5. Suppression: `is_defensive(ship)` true → `tick_all_ai` skips that ship's SDK AI tick (assert the SDK AI was not ticked).
6. Healed exit: hull raised ≥ 0.70 → `StopCloaking`, mode NORMAL, SDK AI resumes.
7. Forced-out exit: cloak auto-decloaks (reserve dry) → controller sets NORMAL without re-cloaking.
8. Hysteresis: hull at 0.50 (between thresholds) does not toggle mode either direction.
9. Player/no-AI ship and no-cloak ship are never entered into DEFENSIVE.

### Integration (`tests/integration/`)
10. Headless: a damaged cloak-capable AI ship in combat enters DEFENSIVE (cloaks), repairs over ticks, and on reaching the fit threshold decloaks and resumes its SDK AI. A second ship with a weak reactor is flushed out by reserve exhaustion before healing.

### Regression
11. Full gate `scripts/check_tests.sh`. B changes the cloak draw path — confirm the Step 0 starvation tests and power-consumer tests still pass. Pure-Python — no C++ rebuild.

### Live verification
Launch **from a terminal** (`./build/dauntless --developer`). Fight a Warbird/Bird-of-Prey;
damage it below ~35% hull and watch stdout: `[cloak] <ship> -> defensive hide`, then
either `-> re-engaging (repaired …)` after it heals, or `-> forced decloak` if its reactor
can't sustain the cloak. Confirm a badly-damaged ship gets flushed out still hurt, and a
lightly-damaged one hides, heals, and comes back. Watch for cloak/decloak **thrash** (tune
thresholds/drain if seen).

## Out of scope

- Active flee/reposition while defensively cloaked (v2 — v1 coasts).
- Non-cloak retreat behavior (the SDK's `WarpBeforeDeath`/`Flee` already exist and are
  untouched).
- Warp-out-to-repair or docking-to-repair.
- Player-facing cloak power management UI.

## Tuning constants (all module-level, no hardpoint edits)

| Constant | Where | Default | Meaning |
|---|---|---|---|
| `CLOAK_RESERVE_DRAIN_PER_SECOND` | `CloakingSubsystem` | ~1000 (crossover-biased) | reserve draw rate while cloaked |
| `MIN_RESERVE_TO_HOLD_CLOAK` | `CloakingSubsystem` (Step 0) | 0.0 | reserve level below which cloak is force-dropped |
| `CLOAK_HULL_THRESHOLD` | `defensive_cloak` | 0.35 | hull % below which a cloak ship hides |
| `FIT_TO_FIGHT_THRESHOLD` | `defensive_cloak` | 0.70 | hull % at which it re-engages (hysteresis top) |
