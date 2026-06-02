# Deferred: AI fires once and stops

**Status:** deferred 2026-06-02. Surfaced during Project 4 visual smoke.

## Symptom

In NPC-vs-NPC fights, an AI ship fires one phaser burst, then no further beams render. (The continuous-SFX symptom was a separate bug — fixed in `a685094`, the loop-handle leak in `Fire()` re-entry.)

## What we know is NOT the cause

- The phaser loop-SFX leak is fixed (`a685094`) — `_play_fire_sfx` only spawns a fresh `_PlayingSound` handle on the False→True transition of `self._firing`.
- The range gate (`fcc0937`) only stops fire when target is beyond max `MaxDamageDistance`; for an NPC dogfight at engagement range this gate should be permissive.
- `StopFiringAtTarget` aliases `StopFiring` (`engine/appc/subsystems.py:925-928`); it's called only when AI explicitly disengages, not every tick.

## Likely paths to investigate

1. **AI's `Preprocessors.py:465` cadence vs. our `_dispatch_one_or_all`.** The AI calls `pWeaponSystem.StartFiring(pTarget, vSubsystemOffset)` every AI evaluation tick (~100ms). In `single_fire` mode `_dispatch_one_or_all` advances `_next_emitter_index` on every Fire and gates `CanFire` per bank. After a burst, every bank's `_armed=False` until recharge crosses `_min_firing_charge + REFIRE_HEADROOM_FRACTION * _max_charge` (~20% of max). If the AI's StartFiring keeps round-robin-advancing past the depleted banks each tick, the rearm logic could be bypassed in a way that leaves all banks cold.

2. **`PhaserSystem.StartFiring` resets `self._currently_firing = []` on every call.** This is reset state — not bank state, but it's reset unconditionally per AI tick. Verify nothing downstream of `_currently_firing` is load-bearing for re-fire.

3. **`retry_held_fire` is the per-tick driver** (`engine/host_loop.py:_advance_combat`). It's gated on `self._fire_held`. AI's `StartFiring` sets `_fire_held=True`; nothing in the AI path calls `StopFiring`, but the held-fire path may be racing the AI's per-tick `StartFiring` re-call in a way that misclassifies "still firing" vs. "just depleted, re-arm" in single-fire mode (`subsystems.py:1136-1142`).

4. **Charge math.** Walk through `_EnergyWeaponFireMixin.UpdateCharge` against the actual property values for a Galaxy phaser (MaxCharge, MinFiringCharge, DischargeRate, RechargeRate from `sdk/Build/scripts/ships/Hardpoints/galaxy.py`). Confirm the recharge actually crosses the rearm threshold within a reasonable window — if the AI is keeping `_firing=True` via the leak-fix's idempotent re-Fire path while the bank's underlying state machine expects `Fire→Stop→Fire` cycles, recharge may never run.

## Where to start

- Add instrumentation: log every `Fire` / `StopFiring` / `_armed` flip / `_charge_level` crossing in a NPC ship's PhaserBanks during a 10-second NPC-vs-NPC engagement.
- Compare against player-fire trace (should be the same code paths with `_fire_held` driven by LBUTTON instead of by AI Preprocessors).
- The likely fix is either a missing rearm signal in single-fire mode, or `StartFiring` should be idempotent when `_fire_held` is already True for the same target (no `_currently_firing` reset, no re-dispatch).

## Related work

- `a685094` — Fire() edge-trigger SFX fix (closed the loop leak that was confusingly co-occurring).
- `fcc0937` — phaser fire-range gate (the only other recent firing-pipeline change).
- `docs/superpowers/specs/2026-05-14-phaser-combat-design.md` — the original phaser pipeline design.
