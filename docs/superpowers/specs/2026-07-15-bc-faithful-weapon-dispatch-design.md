# BC-Faithful Weapon Dispatch and Torpedo Flight — Design

**Date:** 2026-07-15
**Status:** Approved (pending user review of this document)
**Evidence base:** `../STBC-Reverse-Engineering-1/docs/gameplay/weapon-firing-mechanics.md`
(2026-07-15 audited revision — Parts 1–3, §5.5). All behaviours below are
verified against decompiled `stbc.exe` function bodies, not SDK inference.
Per the evidence-tier rule, RE'd binary internals outrank SDK inference for
engine behaviour; our own live instrumented measurements outrank both where
they conflict (see §7's do-not-touch list).

## 1. Goal and scope

A two-layer fidelity project:

1. **Shared layer** — port BC's `UpdateWeapons`/`TryFireWeapon` tick as the
   single dispatch engine for all four weapon-system types (phaser, pulse,
   tractor, torpedo), replacing `_dispatch_one_or_all` and the dispatch half
   of `_HeldFireWeaponSystem._pump_held_fire` in
   `engine/appc/weapon_subsystems.py`.
2. **Torpedo layer** — the audited launch trajectory, CanFire gates,
   in-flight guidance, skew apparatus, and event bookkeeping.

Plus a **phaser-internal fidelity group** (§7) folded in because the tick
port already opens that code: CanFire gate list, recharge condition factor,
`SetPowerLevel` clamp, `GetChargePercentage` gating.

**Boundary:** the port replaces *system-level dispatch*; per-weapon
`Fire`/`CanFire` bodies (charge model, beam states, tractor modes) stay ours
except where a section below names a specific change. Anything numeric that
the 2026-06-29 instrumented weapon-exchange probe verified against the real
game is explicitly frozen (§7).

## 2. Shared WeaponSystem tick

### 2.1 New state

On `WeaponSystem` (mirroring the audited C++ fields):

| Field | BC offset | Semantics |
|---|---|---|
| `_force_update` | +0xAC | "bypass the random inter-shot delay this tick" |
| `_group_fire_mode` | +0xB0 | working group, published per tick via virtual `SetGroupFireMode` |
| `_last_weapon_idx` | +0xB4 | round-robin cursor (replaces `_next_emitter_index`) |
| `_firing_chain_mode` | +0xB8 | active chain index; setter clamps below chain count |
| `_last_group_fired` | +0xBC | −1 sentinel; an *input* to group resolution (resume) |
| target list | +0xC0/+0xC4 | list of targets; dead entries pruned per tick. Our single `_held_target` becomes its head; `StartFiring(target, offset)` appends. |

Chains come from `WeaponSystemProperty._firing_chains` (already parsed by
`SetFiringChainString`, `engine/appc/properties.py`). Grammar:
`mask;name` pairs (`"0;Single;123;Dual;53;Quad"`); a chain's mask is a group
bitmask; groups are **1-based** bit ids; group 0 (or an empty/absent chain)
means "all weapons".

On `Weapon` (per-emitter): `Groups` bitmask (from hardpoint `SetGroups`,
stored on the property, BC property+0x50), a fire timer (BC +0x9C), and
`IsDumbFire` (BC property+0x48).

### 2.2 `update_weapons(dt)` — per tick, faithful to §3.2's seven steps

1. Clear `did_fire`. Bail if the owner ship is dead.
2. Prune dead/unresolvable entries from the target list.
3. Resolve the working group. `_last_group_fired == −1` → the chain's first
   group (or group 0 with no chain). Otherwise **resume the last-fired
   group** if it is still in the chain's bitmask, else fall back to the
   chain's first group.
4. Build candidates round-robin starting **just past** `_last_weapon_idx`,
   keeping weapons whose Groups bitmask contains the working group (all
   weapons when the group is 0).
5. Publish the working group via `SetGroupFireMode`.
6. `try_fire_weapon` each candidate. Success → record
   `_last_weapon_idx`/`_last_group_fired`; **stop if single-fire**. Failure →
   clear that weapon's target id; if the system has **zero targets** and the
   weapon **IsDumbFire**, call `FireDumb`.
7. Group produced nothing and a chain exists → advance to the next group in
   the chain (wrapping) and retry. Full wrap with no fire → reset
   `_last_group_fired` to −1, give up this tick.

Known-benign BC quirk, reproduced for fidelity: in single-fire mode the loop
examines the last-fired weapon twice (bounds arithmetic).

### 2.3 `try_fire_weapon(weapon, dt)` — faithful to §3.3's six steps

1. `_force_update` clear → accumulate `dt` into the weapon's fire timer;
   set → force the timer to 0.33.
2. Weapon not already firing and timer < **0.33** → return False.
3. Re-seed: continuously-firing weapon → timer = 0; else a fresh random draw.
   (BC's draw distribution is unverified in the corpus; we use
   `uniform(0, 0.33)` with a comment marking it as our choice.)
4. `CanFire()` false → `StopFiring()`, return False.
5. `Fire(target, offset)`; fired → return True.
6. Else clear the weapon's target id and walk the system target list: for
   each entry resolving to a live ship, re-point the weapon (target id + aim
   offset) and retry `Fire`. True on first success.

### 2.4 Gate relocation and entry points

The dispatch-level gates currently in `_dispatch_one_or_all`/
`_pump_held_fire` (`_emitter_in_arc`, range, cloak, detectability) move —
logic unchanged — into the per-weapon `Fire` preamble, where BC puts them
(arc lives in the weapon's own fire path / `CanHit`, not in the tick).
System-level offline/cloak gates (`_is_offline`, `_cloak_blocks_fire`) stay
at `StartFiring`/pump level as today.

Player fire input keeps its entry point but takes the exact SDK shape: one
`StartFiring(target, offset)` + `SetForceUpdate(1)` per trigger
(`TacticalInterfaceHandlers.py:355–370`).

**Cadence consequence (accepted):** all systems gain BC's 0.33 s random
inter-shot delay at tick level. Invisible for continuous beams after the
first shot; slightly randomizes pulse cadence (BC-authentic); stacks under
the torpedo 0.5 s stagger.

## 3. Torpedo launch path

### 3.1 Shared spawn (both `Fire` and `FireDumb`)

Replaces the aimed-launch block in `_spawn_projectile`:

- **Position** — tube mount offset rotated by ship world rotation + ship
  world position (`_emitter_world_position()`, unchanged).
- **Direction** — tube property's local `Direction`, world-rotated,
  normalized. Skew-firing tube: perturb **in the local frame first**,
  `Direction + 0.033 × Right` (fixed sign, never negated/indexed/random),
  then world-transform.
- **Velocity** — `unit_direction × mod.GetLaunchSpeed()` **plus the firing
  ship's linear velocity**. The launch is *never* aimed at the target.

### 3.2 `TorpedoTube.Fire` — gating, not aiming

In order:

1. **Aim-point resolve**: target world position + tube aim offset scaled by
   target world scale and rotated by target world rotation. Unresolvable
   target → post fire-failed event, no launch. (No projectile speed, target
   velocity, or intercept time enters this — it is a static point.)
2. **±30° square-cone check**: transform tube→aim-point vector into the
   tube's local `Direction`/`Right`/`Up` basis; require forward component
   > 0 AND `|atan2(right, fwd)| ≤ 0.5235984` AND
   `|atan2(up, fwd)| ≤ 0.5235984` (yaw and pitch independent). No occlusion
   test — firing at a target behind an asteroid is legal. Fail →
   fire-failed event, no launch. This check **supersedes** the old
   dispatch-level hemisphere fallback (`_emitter_in_arc`'s `dot > 0` path
   for arc-less emitters) on the torpedo path — the §2.4 "logic unchanged"
   relocation applies to the phaser/pulse/tractor gates only.
3. Stamp target id + aim offset on the torpedo (launch-gate-only; guidance
   never reads the offset).
4. Spawn (§3.1), bookkeeping, events (§6).

`FireDumb` = same minus steps 1–3; it is also the tick's dumbfire fallback.

### 3.3 `TorpedoTube.CanFire` — the five audited gates

1. Round loaded (`NumReady > 0`).
2. Subsystem not disabled.
3. **Ship-wide stagger**: `game_time − TorpedoSystem._last_system_fire_time
   > 0.5` — **skipped for a skew-firing tube**. `_last_system_fire_time` is
   new `TorpedoSystem` state, stamped by every tube fire.
4. Per-tube `ImmediateDelay` refire gate (existing).
5. Power check (existing).

Our ammo-exhausted gate stays (guards a real engine path; BC enforces at
reload time instead — harmless superset until §9 resolves).

### 3.4 Skew fire — implemented dormant

`TorpedoTube.SetSkewFire/IsSkewFire`: persistent per-tube flag, **never
cleared by firing**. `TorpedoSystem.SetSkewFire`: pure broadcast to child
tubes, no system state. Nothing in engine or shipped SDK sets it (audited:
zero call sites); it exists for mods and fidelity.

### 3.5 Deleted

The tan(15°) spread fan (`_SPREAD_DIVERGENCE_TAN`), `_SPREAD_DELAY`, the
`spread_unit`/`homing_delay` parameters, `_homing_start_age`, and
`TorpedoSystem`'s `_spread`/`GetSpread`/`SetSpread`/`GetSpreadOptions`.
Spread is emergent: chain membership + 0.5 s stagger walk-out + per-tube
mount axes. All tests touching these update in the same change.

## 4. In-flight guidance (`engine/appc/projectiles.py`)

`_steer_toward` → `Guide`, per the audited §5.5, in this order:

1. **Dead-target check first**: target dead/removed → skip guidance
   entirely. Ballistic coast; no cache fallback, no retarget, no
   self-destruct.
2. **Cloak cache**: while the target is detectable, cache its world position
   on the torpedo each frame; when cloaked (existing detectability surface),
   steer to the frozen cached point.
3. **Second-order lead**: `aim = target_pos + target_vel·t + 0.5·target_accel·t²`
   with `t = distance / torpedo_speed`, recomputed every frame.
   Acceleration is estimated from the per-frame velocity delta cached on the
   torpedo (one frame late vs BC reading its physics object; same quantity).
4. **Center-mass only**: `_target_subsystem` homing deleted. Subsystem lock
   still shapes phaser aim; torpedoes ignore it (the fire-time aim offset is
   dead weight in flight — audited).
5. **Decaying turn budget**:
   `max_turn = (guidance_remaining / guidance_initial) × max_angular_accel × dt`,
   `guidance_remaining` counting down. Full agility at launch, zero at
   expiry, then dead-straight flight. The existing clamped great-circle
   rotation stays (equivalent to BC's axis-angle construction).
6. **Constant speed** — velocity renormalized to pre-existing magnitude
   (already true).

**Defaults** (constructor; SDK projectile scripts override per shot):
`guidance_lifetime = 4.0` (init both initial and remaining, matching BC's
`SetGuidanceLifetime` writing both fields), `max_angular_accel = 0.125`,
`lifetime = 60.0` (was 30.0 — only 6 of 16 SDK projectile scripts call
`SetLifetime`, so the default is live for the other 10).

Expiry stays silent (dead flag, vanish, no event). Impact keeps the existing
shield-then-hull path and source-ship exclusion.

**Feel changes, stated plainly:** torpedoes visibly curve out of the tube
onto the target; aft launches at forward targets legitimately fail with
fire-failed; long-range misses coast twice as far; volleys walk out at
~2/sec instead of arriving as a fanned clump.

## 5. Spread selector → firing chains

The weapons-config panel's Single/Dual/Quad selector is BC's **firing-chain
selector** (audited §2.10: the toggle callback calls
`WeaponSystem::SetFiringChainMode`; no count parameter exists anywhere).

- Panel selector now cycles `SetFiringChainMode(n)` (clamped to chain
  count); labels come from authored chain names. Galaxy/Sovereign (the only
  3 hardpoint files with chains, incl. `galaxy_dauntless_mods.py`) show
  Single/Dual/Quad; the 67 empty-string ships show no spread control
  (BC-authentic single implicit mode, group 0 = all weapons).
- `engine/appc/weapon_config.py`'s cycle function and the panel JS follow
  the new getter/setter; UI plumbing otherwise unchanged.

### Intended-design wire (2026-07-15 decomp update)

New decomp-project evidence, confirmed against the official BC SDK Model
Property Editor documentation (`modelpropertyeditor.html:255`): the spread
selector and skew fire (§3.4) were **one feature that shipped
disconnected**, not two independent systems. The doc says of a torpedo
tube's Right vector:

> "the right vector will be used to change the firing direction slightly if
> torpedoes are fired in non-single-fire mode"

i.e. selecting a non-Single firing chain was always meant to arm skew fire.
Retail never wired the connection — the intended hook is a vtable-only
salvo setter (`0x0057B1F0`) with zero callers anywhere in `stbc.exe`, so
stock BC's spread selector only ever changed which tubes are eligible
(chain group membership); it never actually fanned or desynced them.

**Dauntless wires the intended behaviour, not the shipped bug.**
`TorpedoSystem.SetFiringChainMode` now broadcasts `SetSkewFire` to every
child tube based on the newly-active chain's groups (`_active_chain_groups
()`):

- **Non-Single chain** (any active-group list other than `[0]`) → skew ON
  for every tube. Skew tubes are exempt from the 0.5s ship-wide stagger
  (§3.3), so every member of the working group launches in the **same
  tick** — a true simultaneous salvo, fanned by each tube's authored Right
  vector (Galaxy's four forward tubes: Rights `(-1,0,0)`, `(0,0,-1)`,
  `(1,0,0)`, `(0,0,1)` → a 4-way fan cross on ±X/±Z).
- **Single chain** (active groups `== [0]`, also the chainless fallback) →
  skew OFF, restoring BC's shipped one-per-click walk-out (§3.2/§3.3 as
  already described above).

This is a deliberate divergence from literal retail behaviour, ruled by
Mark: the disconnection is a shipped bug, not an authored design choice —
BC's own SDK documentation describes the intended mechanism in the present
tense, and the salvo setter exists in the vtable with no caller, not as
dead/removed code. See `TorpedoSystem.SetFiringChainMode` (engine/appc/
weapon_subsystems.py) and `tests/unit/test_spread_skew_wiring.py`.

## 6. Events

| Event | Id | Change |
|---|---|---|
| `ET_TORPEDO_FIRED` | 0x00800066 | Unchanged (already posted; source=projectile, dest=tube; instrumentation-verified 2026-07-12). |
| `ET_WEAPON_FIRED` | 0x0080007C | **New.** Posted by torpedo fire (after `ET_TORPEDO_FIRED`, BC's order) and by phaser first-shot (beam start). Real SDK surface: player-instance handlers in E2M6/E6M2/E6M4/E6M5, broadcast handlers in E1M2/E2M1/E2M2/E6M4. Bound to (weapon, owner ship). |
| `ET_TORPEDO_RELOAD` | 0x00800065 | Unchanged (already posted on slot refill; dest=tube, no source). |
| Fire-failed | 0x00800037 | **New.** Posted on aim-resolve or cone failure, bound to the tube. No SDK symbol name exists and no shipped script listens; defined in `engine/appc/events.py` with the audited hex id and a comment. |
| Ammo-consumed | 0x00800067 | **New.** Posted on fire **only when the firing ship is the player ship** (audited player-locality gate). Same id doubles as BC's ammo-type-changed event in `SetAmmoType` — out of scope here. |
| Unload NULL-torpedo quirk | — | **Not reproduced.** BC's `UnloadTorpedo` posts `ET_TORPEDO_FIRED` with a NULL torpedo (faultable by any listener); no shipped script relies on it; we decline knowingly. |

## 7. Phaser-internal fidelity (safe group only)

In scope — all in `_EnergyWeaponFireMixin` / `PhaserSystem`:

1. **CanFire gate list** (audited §1.6, three gates): ship alive; charge —
   `> 0` to *sustain* an already-firing beam, `≥ MinFiringCharge` to
   *start*; disabled-product gate
   (`DisabledPercentage < bank.Condition% × system.Condition%`, i.e.
   `GetOverallConditionPercentage`). The start/sustain asymmetry **is** the
   hysteresis: delete `REFIRE_HEADROOM_FRACTION` and the `_armed` flag. The
   existing system-level offline gate stays (BC gates power elsewhere).
2. **Recharge formula** gains the missing `× ConditionPercentage` factor
   (damaged banks recharge proportionally slower). The audited 1.25
   non-local boost is inert in single-player by construction — documented
   in a comment, not implemented as live code.
3. **`SetPowerLevel` clamps to {0,1,2}** — BC ships an
   uninitialized-stack-damage bug for out-of-range levels; the audit itself
   says clamp on write.
4. **`GetChargePercentage`** returns 0.0 when the parent system is off or
   the bank disabled.
5. **`IsDisabled` recursion** — verify-only: our all-children rule already
   matches the audited one.

**Frozen — do NOT change (live-verified against the real game,
2026-06-29 instrumented weapon-exchange probe):**

- Discharge-rate source (we read the hardpoint's `NormalDischargeRate`; BC's
  firing path reads a flat power-level table and leaves that property dead).
- Damage formula and power-level damage scales (BC C++ table says
  LOW 0.25 / MED 0.5 / HIGH 0.5; our constants were verified end-to-end
  against real-game exchanges and may already absorb these factors).
- PP_LOW "no hull damage" routing in `combat.apply_hit` (live dev-console
  probed).

Where the RE doc's formula transcription and our live measurements conflict,
the live measurements win. Reconciling these numerically is a separate,
explicitly gated follow-up — not this project.

## 8. Testing and verification

**Unit** (new):

- Launch: tube-direction trajectory, ship-velocity inheritance, skew
  perturbation applied in the local frame pre-transform, launch never aimed
  at target.
- Cone gate: boundary at exactly 0.5235984 rad, yaw/pitch independence,
  behind-target rejection, fire-failed event on failure, no occlusion test.
- CanFire: five gates; stagger at 0.5 s ship-wide; skew exemption.
- Chains: grammar parse, 1-based group membership, resume behaviour
  (`LastGroupFired` as input), group-0/no-chain fallback, chain-mode clamp.
- Tick: round-robin resume past `LastWeaponIdx`, single-fire stop (and the
  benign double-examine), dumbfire fallback only on zero-targets +
  IsDumbFire, 0.33 timer + ForceUpdate bypass, CanFire-fail → StopFiring,
  target-list retry.
- Guidance: lead formula (incl. t = dist/speed), decay envelope reaching
  zero at expiry, cloak freeze, dead-target ballistic, center-mass with a
  subsystem lock held, 60 s default, 4.0/0.125 defaults.
- Events: order (`ET_TORPEDO_FIRED` then `ET_WEAPON_FIRED`), bindings,
  player-only ammo event, phaser first-shot `ET_WEAPON_FIRED`.
- Phasers: start/sustain asymmetry (start below MinFiringCharge refused;
  sustain above 0 allowed; restart after depletion requires
  MinFiringCharge), disabled-product gate, recharge condition factor,
  SetPowerLevel clamp, GetChargePercentage gating.

**Updated in the same change** (never orphaned): every test touching
`_spread`/`GetSpreadOptions`, the fan/`homing_delay`/`_homing_start_age`,
torpedo subsystem homing, 30 s TTL, `REFIRE_HEADROOM_FRACTION`/`_armed`,
and the `_dispatch_one_or_all` round-robin.

**Gate:** `scripts/check_tests.sh` (both suites vs the known-failures
ledger) before merge.

**Live verification** (green tests don't count until seen running):
QuickBattle, Galaxy:

1. Cycle Single/Dual/Quad — tube counts follow the authored chains; volley
   walks out at ~0.5 s intervals.
2. Aft tubes at a forward target — no launch (fire-failed), no torpedo.
3. Crossing target — torpedo visibly curves on a lead path; goes ballistic
   after ~4 s of guidance.
4. Kill the target mid-flight — coast, no retarget.
5. Cloaked target — torpedo steers to the frozen last-seen point.
6. Phaser exchange — feel unchanged (frozen numerics), depletion/restart
   behaviour per the asymmetry.

## 9. Open question → decompilation project (reload contradiction)

`combat-and-damage.md:740–830` (which our shipped, live-verified reload
implements: per-slot timers on the game clock) contradicts
`weapon-firing-mechanics.md` §2.2/§2.6 (slot-timer array is vestigial dead
code; nothing advances it; `ReloadTorpedo` has no per-frame caller — only
`SetAmmoType` and its SWIG wrapper). Taken literally, §2.6 implies stock BC
tubes never refill mid-combat, which contradicts observable gameplay.

**Decision: keep our shipped slot reload unchanged.** Question sent back:

> What refills `TorpedoTube::NumReady` during normal play? Is there a
> per-frame caller of `ReloadTorpedo` (or any other `NumReady`/`LoadedCount`
> writer) outside `SetAmmoType` — e.g. from `TorpedoSystem::Update`, the
> ship tick, or a Python-side path we haven't found? If reload truly never
> happens outside ammo switches, how does an extended stock fight not run
> every tube dry at `MaxReady` rounds?

Nothing else in this design depends on the answer.

**Second question for the decomp project (chain parse):**

> How does the C++ parse `FiringChainString` segments into chain masks —
> per-digit group ids (`"53"` → groups {5,3}) or `atoi` decimal bitmask
> (`53` → groups {1,3,5,6})? And does the group sweep honour authored
> segment order or ascending bit order (`GetNextGroup` scans upward, which
> would try group 3 before 5 in Quad)? Our implementation keeps the
> per-digit ordered-list reading — it is the only one under which the
> authored names (Single/Dual/Quad vs tube `SetGroups` masks 25/26/4) make
> sense.

**Partially answered (2026-07-15):** the BC SDK Model Property Editor
documentation states "Zero is used for the group of all weapons,
single-firing" — confirming group `0` is BOTH the chainless fallback *and*
the authored "Single" chain's group list, and that it specifically means
single-fire (not merely "no chain authored"). That's the fact the spread
<->skew wire (§5) keys off: `_active_chain_groups() == [0]` is the one case
that must clear skew rather than arm it. The segment-parse encoding
(per-digit vs `atoi` bitmask) and the group-sweep order remain open.

## 10. Non-goals

- Wire formats / MP relay (§2.8, §2.9, §3.5 of the RE doc).
- Numeric phaser reconciliation (discharge table, damage scales, PP_LOW) —
  gated follow-up per §7.
- The vestigial slot-timer array semantics (pending §9).
- BC's beam three-state charge-freeze during ramp-up (needs beam-state
  surface we don't have; logged as follow-up).
- AI-side fire policy (`RandomAI`, preprocessor dumb-fire loop) — separate
  gap doc territory.

**Live verification pending:** Mark runs the §8 QuickBattle pass (items 1-6) before this branch merges.
