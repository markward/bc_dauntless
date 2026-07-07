# NPC Subsystem Targeting — Design

**Date:** 2026-07-07
**Status:** Approved (design), pending implementation plan
**Scope:** Fix "B" from the NPC-AI power/repair audit — make NPC weapons actually
aim at the subsystem the AI has already chosen. Cloak behavior is a **separate
spec** (`2026-07-07-npc-cloak-behavior-design.md`, not yet written).

## Problem

NPC AI computes a strategic subsystem target every fire tick but the choice is
silently discarded, so every NPC phaser and torpedo aims at the target's
geometric hull centre. NPCs never deliberately go for the warp core, shields,
weapons, or engines — the strategic levers the power/repair systems were built to
reward are never pulled.

### Root cause (verified in the audit)

- The real SDK `FireScript` preprocessor runs in our engine and rates subsystems
  correctly (`RateSubsystemForTargeting`,
  `sdk/Build/scripts/AI/Preprocessors.py:963`): `IsCritical x6.0`, weapons/shields
  `5.0`, cloak `4.0`, impulse `3.0`, hull `-200`. Gated on `ChooseSubsystemTargets`,
  enabled at difficulty >= 0.35 (`BasicAttack.py:159-182`); default difficulty is
  0.5, so this is **on** in normal play.
- `FireScript.ChooseTargetSubsystem` stashes its result as
  `self.idTargetedSubsystem` (`Preprocessors.py:943`) and delivers it to weapons as
  a positional offset via `StartFiring(pTarget, vSubsystemOffset)`
  (`Preprocessors.py:465`).
- Our `WeaponSystem.StartFiring` stores that offset as `emitter._target_offset`
  but **nothing ever reads it for aim** (0 reads across `engine/`).
- The actual aim sites read the *firing ship's* `GetTargetSubsystem()`:
  phaser damage tick (`engine/host_loop.py:614`) and torpedo launch
  (`engine/appc/weapon_subsystems.py:255`).
- `SetTargetSubsystem` is called **only by player UI**
  (`engine/ui/target_list_view.py:305/386/395`); NPCs never set it, so their
  `GetTargetSubsystem()` is always `None` -> centre-of-hull aim.

What the SDK rating actually prefers (`RateSubsystemForTargeting`): weapons and
shields carry a **type-rating of 5.0** (cloak 4, impulse 3), the **hull is -200**
(effectively never targeted), and **critical** systems get **+6.0**. `IsTypeOf`
only fires when the subsystem has a bound property (`subsystems.py:400-410`), which
production ships have. So at full health the highest-rated targets are typically the
enemy's **weapons and shields** (≈5-6), with the small damage-penalty terms
(`-0.0005 x condition`) nudging toward easier kills. The **warp core** (critical,
`SetCritical(1)` + `SetTargetable(1)`, `Galaxy.py:755`) is chosen when its +6 critical
bonus outweighs its large max-condition damage penalty — condition-dependent, not a
guaranteed first pick. Net: this is stock-BC-faithful subsystem targeting (go for
weapons/shields/critical systems, avoid the hull), **not** a warp-core monomania.
If warp-core-specific prioritization is later desired (the user's tactical intuition),
that is a rating-heuristic change beyond stock BC — out of scope here.

## Approach

**Chosen seam: mirror the FireScript choice onto the firing ship via
`SetTargetSubsystem`.** Add one hook in the driver's preprocessor tick: immediately
after a FireScript instance's `Update()` runs, resolve `inst.idTargetedSubsystem`
to the subsystem object and call `ship.SetTargetSubsystem(subsystem_or_None)`. Both
existing aim sites already honor `GetTargetSubsystem()`, so they begin obeying the
choice with no change. No SDK edit; no aim-site rewrite.

### Why this seam (rejected alternative)

Honoring `emitter._target_offset` at the aim sites was rejected: it touches both
aim sites, needs body->world offset math, and still loses subsystem *identity* for
damage attribution. The `idTargetedSubsystem` route reuses the exact path the
player already uses and is a single, well-bounded hook.

### Safety: no side effects on the HUD

The only `GetTargetSubsystem()` readers that must stay player-scoped are the HUD
(`target_list_view.py:281/296`, `target_reticle.py:41`); both read the *player*
ship explicitly, so an NPC carrying a non-null target subsystem cannot disturb
them. The firing-ship-scoped readers are precisely what we want to drive: the
phaser damage tick (`host_loop.py:614`), the torpedo launch aim
(`weapon_subsystems.py:255`), and — a third, beneficial one confirmed in final
review — the visible-beam terminator (`host_loop.py:863`), which now points an
NPC's beam VFX at the chosen subsystem too. (Verified by grep in the audit + review.)

## Components / mechanism

### 1. The hook — `engine/appc/ai_driver.py`

In `_tick_preprocessing`, immediately after the preprocessor `Update()` call
(around `ai_driver.py:373`), add a FireScript-only post-step:

- **Gate:** only for FireScript instances — `hasattr(inst, "lWeapons")` and
  `"idTargetedSubsystem" in inst.__dict__` (bypass `TGObject.__getattr__` `_Stub`).
  No other preprocessor is affected.
- **Resolve ship:** `ship = inst.pCodeAI.GetShip()`; bail if `None`.
- **Resolve subsystem:** read `inst.idTargetedSubsystem`.
  - `None` -> push `None` (low difficulty / no `ChooseSubsystemTargets` / out of
    fire range) so NPCs correctly fall back to centre-of-hull aim. Preserves stock
    behavior below difficulty 0.35.
  - Otherwise resolve via `App.TGObject_GetTGObjectPtr(id)` +
    `App.ShipSubsystem_Cast(...)`.
- **Validate before pushing:**
  - resolved object is falsy/dead -> push `None`.
  - resolved subsystem's parent ship is not the firing ship's current
    `GetTarget()` (stale id after a target switch) -> push `None`.
  - else -> `ship.SetTargetSubsystem(subsystem)`.
- **Idempotence / churn:** only call `SetTargetSubsystem` when the value changes
  from the ship's current `GetTargetSubsystem()`, to avoid redundant writes and to
  drive the debug log (below) only on transitions.

This runs at FireScript cadence (0.2 s), the same cadence at which the choice is
recomputed — no extra work.

### 2. Dev-mode debug log (testability) — `engine/appc/ai_driver.py`

Gated behind developer mode (`engine.dev_mode.is_enabled()`), emit a single line
when an NPC's chosen subsystem *changes*:

```
[ai] <ship name> -> targeting <subsystem name>   (or "-> targeting hull centre" for None)
```

Off in production (never emitted without `--developer`). **Use `print()`, not
`logging`** — the host configures no logging handler, so `logging.info(...)` is
silently swallowed and never reaches the terminal (this was the "not seeing it"
bug of 2026-07-07). Match the visible `[viewscreen]` / `[host_loop]` dev-diagnostic
convention (a `[ai]` prefix, printed to stdout). This makes the live test a direct
observation instead of an inference — provided the game is launched from a terminal
so stdout is visible.

## Error handling / edge cases

| Case | Behavior |
|---|---|
| `idTargetedSubsystem is None` | push `None` -> centre aim (stock behavior) |
| id resolves to dead/invalid object | push `None` |
| id belongs to a different (old) target | push `None` |
| firing ship has no `pCodeAI`/ship | skip (no crash) |
| non-FireScript preprocessor | untouched (gate excludes it) |
| player ship | unaffected — player sets its own target subsystem via UI; the driver hook only runs for AI-driven FireScript nodes |

## Testing

### Unit / integration (`tests/unit/`)

1. Hook pushes the resolved subsystem onto the ship when FireScript sets
   `idTargetedSubsystem`.
2. Hook pushes `None` when `idTargetedSubsystem` is `None`.
3. Hook clears to `None` on a stale id (subsystem's parent != current target).
4. Hook clears to `None` on a dead/invalid id.
5. Hook is a no-op for a non-FireScript preprocessor (SelectTarget, ManagePower).
6. Hook only writes on change (no redundant `SetTargetSubsystem` calls).
7. Integration: a high-difficulty NPC attacking a target ends up with that
   target's warp core (critical, highest-rated) as its `GetTargetSubsystem()`.

Run the full gate (`scripts/check_tests.sh`) — this change is pure Python
(`ai_driver.py`), so **no C++ rebuild is required**.

### Live in-game verification

The change is Python-only; **no `cmake` rebuild needed**. Steps:

1. Launch developer build: `./build/dauntless --developer`
2. In **Configuration -> Gameplay**, set **AI Difficulty = Hard** (guarantees
   `ChooseSubsystemTargets` is on; Medium/0.5 also works).
3. Start a combat scenario with at least one attacking NPC — QuickBattle with an
   enemy ship, or a combat mission via the dev **Load Mission...** picker.
4. **Launch from a terminal and watch stdout** for `[ai] <ship> -> targeting <subsystem>`
   lines as combat begins. **Expected:** NPCs report targeting high-value
   subsystems (typically **weapons** and **shields**, sometimes the **Warp Core**
   or engines), not "hull centre". Seeing any non-null subsystem name confirms the
   choice is now reaching the ship.
5. **Behavioral tell (before/after):** let a fight run to a kill. **Expected with
   the fix:** NPCs concentrate fire — shields drop faster than the hull, and
   specific subsystems get disabled (weapons/engines), with occasional **warp-core
   breach** kills (instant destruction) — rather than slow uniform hull attrition.
   On current `main` (pre-fix) NPCs only ever whittle the hull.
6. **Player-side cross-check:** target the NPC that is under fire (or check your own
   ship if the NPC is shooting you) and open the target-subsystem HUD / Ship
   Property Viewer; confirm one subsystem's condition drops markedly faster than
   the rest — the one named in the debug log.

If the debug log shows `hull centre` persistently at Hard difficulty, that
indicates the FireScript rating isn't selecting a subsystem (difficulty/config or
targetability) rather than the hook — report the log and we diagnose upstream.

## Out of scope

- Cloak decloak-to-attack cadence, cloak reserve depletion, and defensive
  cloak-to-repair — covered by the separate NPC cloak behavior spec.
- The `SensorSubsystem.SetNumProbes`/`GetNumProbes` stub (peripheral no-op found in
  the audit) — unrelated; track separately.
- Any change to the subsystem *rating* heuristic itself (we run the SDK's as-is).
