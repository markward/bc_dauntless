# Ship Death Sequence — Design

**Date:** 2026-06-11
**Status:** Approved (design); implementation pending
**Scope:** Logic death + basic VFX

## Problem

Ships do not die. Combat damage reaches the hull correctly, but the death
*sequence* downstream of "hull reaches zero" does not exist, so a ship at 0 %
hull keeps flying, thinking, and firing.

Traced chain (pre-change):

1. ✅ Combat routes to the hull — `combat.py:412` `ship.DamageSystem(hull, post_shield)`.
2. ✅ Hull hits zero → `objects.py` `DamageSystem` calls `SetDying(True)`.
3. ❌ Nothing transitions dying → dead. `SetDead` has **zero callers** in `engine/`.
4. ❌ Nothing consumes `IsDying()`.
5. ❌ `IsDead()` consumers only ask "is my *target* dead?", never "am *I* dead?",
   and nobody ever sets dead anyway.
6. ❌ AI driver, weapon fire, and ship motion have **no death gate** at all.

So `SetDying(True)` is a marker that lights up and does nothing.

Two related gaps surfaced while diagnosing:

- **Critical flag is dead data.** `ShipSubsystem` stores `_critical` and exposes
  `GetCritical/SetCritical/IsCritical` (`subsystems.py:952-970`), plumbed from
  hardpoint properties (`ships.py:705`, `ships.py:936`). Nothing reads it. In
  stock BC, the engine destroys a ship when *any* subsystem flagged
  `SetCritical(1)` reaches zero — that set is the hull (39/39 ships) **and** the
  warp core (22/23 ships; `matankeldon.py` deliberately sets the core
  non-critical). The current hull-identity check in `DamageSystem` misses the
  warp-core breach entirely.
- **`DestroySystem` is unimplemented.** The SDK's scripted instant-kills
  (`AI/PlainAI/SelfDestruct.py`, `E2M1.py`, `Maelstrom/Maelstrom.py`) call
  `pShip.DestroySystem(sub)`. We have no such method, so `TGObject.__getattr__`
  (`objects.py:16`) returns a truthy `_Stub` and the call is a silent no-op.

## Goals

- Make ships actually die: critical subsystem → 0 ⇒ dying → (throes) → dead →
  `ET_OBJECT_DESTROYED` → removed from set.
- Trigger off the engine's **critical flag**, folding in the warp-core breach and
  the matankeldon exception for free.
- Implement `DestroySystem(sub)` so the SDK's scripted kills work.
- Halt AI and weapons during the dying window (inert coast — physics untouched).
- Basic, readable VFX: a real `ExplosionA/B` fireball via the existing particle
  infrastructure.

## Non-goals (explicit)

- No game-over / mission-fail UI. The player ship dies like any other ship;
  missions already hook `ET_OBJECT_DESTROYED` for player death (Q5-A).
- No debris, splash damage, or staged death-throes beyond the single explosion.
- No per-ship throes duration (constant for now).
- No warp-out / escape-pod interactions.

## Decisions (from brainstorming)

| # | Question | Decision |
|---|----------|----------|
| Q1 | Throes timing | **B** — fixed throes window (two states: dying, dead; one timer) |
| Q2 | Behavior during throes | **A** — inert coast: gate AI + weapons, leave physics integrator alone |
| Q3 | VFX | **A** — reuse SDK `Effects.CreateExplosionPuffHigh` with real `ExplosionA/B` sprites |
| Q4 | Trigger | **A** — critical-flag based, plus implement `DestroySystem` |
| Q5 | Player death | **A** — treat player like any ship; no new game-over flow |
| Arch | Where the state machine lives | **Option 1** — dedicated `ship_death` module, ticked from `_advance_combat` |

## Architecture

### New module: `engine/appc/ship_death.py`

A focused unit owning the throes registry, with a three-function public
interface. Mirrors how `hit_vfx` / `particles` plug into the per-frame
`_advance_combat` hub.

```python
THROES_DURATION       = 2.5   # seconds; constant now, swap for a per-ship property later
EXPLOSION_SIZE_FACTOR = 1.0   # ship-radius multiplier (starting value, tuned by feel)
MIN_EXPLOSION_SIZE    = 2.0   # GU floor for tiny craft (starting value, tuned by feel)

_active: list[dict] = []     # entries: {"ship", "time_left"}

def begin(ship) -> None:
    """Idempotent. If ship not already dying/dead:
    SetDying(True); record (ship, time_left=THROES_DURATION); spawn explosion."""

def advance(dt: float) -> None:
    """Tick every dying ship. Decrement time_left; when <= 0:
    SetDead() (fires publish_destroyed -> ET_OBJECT_DESTROYED), then
    RemoveObjectFromSet(ship). Prune the entry. Skip/prune invalid ships."""

def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""

def _out_of_action(ship) -> bool:
    """hasattr-guarded IsDying()/IsDead(). Single definition of
    'out of action', imported by the AI and weapon gate sites."""
```

**Interface contract:** `begin` is the only entry point for "this ship should
die"; nothing else sets `_dead` directly. The dying→dead transition is
single-owned by `advance`.

**Wiring:**
- `advance(dt)` called once per frame from `_advance_combat` (host_loop.py:237),
  alongside the existing `hit_vfx.update_ages(dt)` / `particles.advance(dt)`.
- `reset()` wired into the same mission-swap teardown that calls
  `ship_lifecycle.reset()` / `particles.reset()`.

### Trigger path: `engine/appc/objects.py` (`DamageableObject`)

`_is_critical(sub)` — `bool(sub.IsCritical())`, guarded so objects/subsystems
without the method return False.

`DamageSystem` — swap the hull-identity check for a critical-flag check:

```python
cur = subsystem.GetCondition()
new_cond = max(0.0, cur - amt)
subsystem.SetCondition(new_cond)
if new_cond <= 0.0 and _is_critical(subsystem) \
        and not self.IsDying() and not self.IsDead():
    from engine.appc import ship_death
    ship_death.begin(self)
```

New `DestroySystem(subsystem)`:

```python
def DestroySystem(self, subsystem) -> None:
    """Force a subsystem to zero condition, then apply the same death rule
    as DamageSystem. Mirrors SDK pShip.DestroySystem(sub). Ship death is a
    side effect only when the subsystem is critical; DestroySystem(pSensors)
    just zeroes sensors."""
    if subsystem is None:
        return
    subsystem.SetCondition(0.0)
    if hasattr(subsystem, "SetDestroyed"):
        subsystem.SetDestroyed(True)
    if _is_critical(subsystem) and not self.IsDying() and not self.IsDead():
        from engine.appc import ship_death
        ship_death.begin(self)
```

`IsDying`/`IsDead` live on `ShipClass`; `DamageableObject` is the base, so the
trigger calls are `hasattr`-guarded (a non-ship damageable never triggers).

## State machine

```
ALIVE ──(critical sub -> 0)──▶ DYING ──(throes timer expires)──▶ DEAD ──▶ removed
        via ship_death.begin              via ship_death.advance
```

- `begin`: `SetDying(True)`, `time_left = THROES_DURATION`, spawn explosion.
  Idempotent (a second critical sub dropping mid-throes is a no-op).
- `advance`: `time_left -= dt`; at `<= 0` → `SetDead()` → `RemoveObjectFromSet` → prune.

## Behavior gates (inert coast)

A ship is "out of action" when `IsDying() or IsDead()`. Two early-return gates:

1. **AI** — `tick_ai(ai, game_time)` (ai_driver.py:34): resolve the AI's ship;
   if `_out_of_action`, return `US_DONE` without running the behavior.
2. **Weapons** — extend the existing `_is_offline(self)` funnel in
   `subsystems.py` (checked before every fire) to also return True when the
   parent ship is out of action. Covers held-fire bursts, single fire, and
   torpedo launch in one spot.

**Physics is untouched** — the ship keeps current linear/angular velocity and
drifts. No motion gate.

## Death explosion VFX

In `ship_death.begin(ship)`, via the SDK helper our `AnimTSParticleController`
shim fully supports (verified: every method `CreateExplosionPuffHigh` calls is
implemented; `EffectAction_Create` exists; `particle_pass.cc` renders
`texture_path`; SDK texture paths resolve via the `game/` prefix fix in
`a45bcb2`).

```python
from engine.appc import Effects

def _spawn_explosion(ship):
    radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0
    size   = max(radius * EXPLOSION_SIZE_FACTOR, MIN_EXPLOSION_SIZE)
    pos    = TGPoint3(0.0, 0.0, 0.0)   # ship origin (body frame)
    dir    = TGPoint3(0.0, 0.0, 1.0)
    action = Effects.CreateExplosionPuffHigh(
        fLife=THROES_DURATION, fSize=size,
        pEmitFrom=ship, kEmitPos=pos, kEmitDir=dir, pAttachTo=_effects_root())
    action.Play()
```

- **Sizing** — ship-radius-relative (BC ship/object scales vary wildly).
- **Emit anchor** — `SetEmitFromObject(ship)` so the fireball tracks the
  tumbling hulk; controller `fLife` ≈ throes duration plus the helper's built-in
  `+1.5s` tail, so particles finish blooming after the ship is removed.
- **Texture** — `ExplosionA.tga` / `ExplosionB.tga` (helper picks 70/30).
- **Attach node** — `_effects_root()` returns the same attach target the
  existing one-shot effects use (the effects scene root, or `None` — in which
  case `particle_pass` renders the controller unattached at its emit position).
- **Backend tick** — controller registers with the `particles` backend, which
  `_advance_combat` already advances; no new render wiring.
- **Fallback** — if `CreateExplosionPuffHigh` raises (missing asset / headless
  test with no backend), `begin` swallows and logs once. Death logic must never
  depend on VFX succeeding.

## Removal ordering (death instant)

When the throes timer expires, in `advance`:

1. `ship.SetDead()` → existing path fires `ship_lifecycle.publish_destroyed` →
   broadcasts `ET_OBJECT_DESTROYED`. Handlers (`TargetGone`,
   `ConditionDestroyed`) react **while the ship handle is still valid**.
2. `RemoveObjectFromSet(ship)`.
3. Prune the registry entry.

**Event before removal** so handlers can still read name/position.

**Edge cases:**
- Ship removed by a script mid-throes (`SetDeleteMe`) → `advance` skips/prunes
  invalid entries.
- `begin` called twice → idempotent.
- Mission swap during throes → `reset()` clears the registry.

## Save / load

Persist the existing `_dying` / `_dead` flags only — no timer serialization. A
save captured mid-throes reloads as "dying"; first `advance` assigns a fresh
`THROES_DURATION` and completes normally. Dead ships are already removed, so
never saved. Deliberate corner-case simplification.

## Testing (TDD)

Run **focused subsets only** — the full suite OOMs the host.

- **Logic** (`tests/unit/test_ship_death.py`):
  - critical sub → 0 starts dying
  - warp-core kill works; matankeldon non-critical core survives
  - throes timer → dead → `ET_OBJECT_DESTROYED` fired exactly once → removed from set
  - `DestroySystem(hull)` and `DestroySystem(power)` kill; `DestroySystem(sensors)` does not
  - `begin` idempotent; `reset` clears
- **Gates** (extend `tests/unit/test_subsystems.py` / AI tests):
  - dying ship's weapons `CanFire() == 0` / `StopFiring`
  - `tick_ai` returns `US_DONE` for a dying ship
  - physics / velocity untouched during throes
- **VFX**: `begin` spawns one controller targeting an `Explosion*.tga`;
  raise-safe when the backend is absent.

## Files touched

- **New:** `engine/appc/ship_death.py`, `tests/unit/test_ship_death.py`
- **Edit:** `engine/appc/objects.py` (`DamageSystem`, new `DestroySystem`,
  `_is_critical`), `engine/appc/ai_driver.py` (AI gate),
  `engine/appc/subsystems.py` (weapon gate via `_is_offline`),
  `engine/host_loop.py` (`advance`/`reset` wiring)
