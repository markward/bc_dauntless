# TorpedoTube recreation — design

Status: DRAFT (awaiting review)
Created: 2026-07-12
Blocked on: probe q12 for one sub-item only (`ET_TORPEDO_FIRED`); everything else is unblocked.

## Goal

Make `App.TorpedoTube` faithful to the original engine. Today it sits on the
wrong base class, computes its firing direction in the wrong reference frame
(which silently breaks AI dumb-fire), reloads off a wall clock, ignores
`ImmediateDelay`, cannot represent `MaxReady > 1` ships at all, and is the
source of the top two entries in `docs/stub_heatmap.md` — which turn out to be
phantoms of our own making.

## Evidence tiers

This design leans on three sources with different authority. Naming them
explicitly, because the first draft of this design was wrong precisely because
it inferred engine internals from tier 1 when tier 3 already had the answer.

| Tier | Source | Tells us |
|---|---|---|
| 1 | `sdk/Build/scripts/**` (game scripts) | what the engine is *asked* to do |
| 2 | `sdk/Build/scripts/App.py` (SWIG) | what methods *exist* |
| 3 | `docs/original_game_reference/gameplay/combat-and-damage.md` (RE'd from `stbc.exe`) | what the engine *actually does inside* |

Tier 3 outranks tier 1 for behaviour. Where tier 3 is silent or marks a field
`(?)`, this spec says so rather than inventing a mechanism.

---

## Section 1 — Class hierarchy

**Problem.** BC's hierarchy is `TorpedoTube → Weapon → ShipSubsystem`
(`sdk/.../App.py:5758,5988`). `Weapon` is a **leaf emitter** and is *not* a
`PoweredSubsystem` — it has no power, no `IsOn`, no charge. Ours is
`TorpedoTube → WeaponSystem → PoweredSubsystem`
(`engine/appc/weapon_subsystems.py:1625`), so every tube carries a powered-
aggregate surface it should never have (`StartFiring`, `GetNumWeapons`,
`GetWeapon`, the whole power API). That mis-modelling is *why* `host_loop`
felt entitled to ask a tube for `UpdateCharge`.

**Change.** Add `class Weapon(ShipSubsystem)` to `engine/appc/weapon_subsystems.py`
and re-parent `TorpedoTube` onto it.

`Weapon` carries only the SDK-demanded leaf surface:

| Method | Justification |
|---|---|
| `FireDumb` | SDK-called — `AI/Preprocessors.py:458` |
| `CalculateWeaponAppeal` | SDK-called — `AI/PlainAI/IntelligentCircleObject.py:238` |
| `CalculateRoughDirection` | SDK-called — `Preprocessors.py:456`, `IntelligentCircleObject.py:234` |
| `GetProperty` | SDK-called — `Tactical/Interface/WeaponsDisplay.py:276,360` |
| `Fire`, `CanFire`, `StopFiring`, `IsFiring` | not SDK-called on a tube, but our `TorpedoSystem` drives its tubes through them |

**Explicitly NOT implemented** (zero SDK call sites on a tube, per verification):
`SetFiring`, `IsMemberOfGroup`, `GetTargetID`, `IsDumbFire`,
`GetOverallConditionPercentage`, `IsInArc`, `CanHit`, `SetSkewFire`,
`IsSkewFire`. `IsInArc`/`CanHit` are additionally *unspecifiable* — their BC
signatures cannot be recovered from the SDK, so implementing them would mean
inventing an interface.

**Constraints discovered during verification:**

- `Fire`/`CanFire`/`StopFiring`/`IsFiring` **must be overridden on `TorpedoTube`**,
  not merely inherited. `TorpedoTube.Fire` consumes `_num_ready` and takes the
  keyword-only `spread_unit=` / `homing_delay=` arguments that
  `TorpedoSystem.StartFiring` passes (`weapon_subsystems.py:858`) for Dual/Quad
  spread volleys. A generic `Weapon.Fire(target, offset)` would raise `TypeError`
  on every spread volley. `Weapon` declares them; `TorpedoTube` implements them.
- `Weapon.__init__` must set `_firing`, `_target`, `_target_offset` — currently
  set in `TorpedoTube.__init__` (`:1640-1642`) and relied on by `IsFiring()`.
- `engine/appc/subsystems.py:2421 _WEAPON_EXPORTS` must gain `"Weapon"`. That
  façade is a PEP-562 `__getattr__` allowlist; ~30 sites import weapon classes
  through it, and an omission is an `AttributeError` at import.
- **Every child of a `TorpedoSystem` must be a `TorpedoTube`.**
  `AI/Preprocessors.py:454-458` iterates `GetChildSubsystem(i)` and calls
  `TorpedoTube_Cast(...)` with **no `None` check**, then dereferences the result.

**Safety.** Verified: nothing in `engine/`, `App.py`, `native/`, `game/` or the
SDK calls any `WeaponSystem`- or `PoweredSubsystem`-only method on a tube.
`ShipSubsystem` already supplies `IsDisabled`/`IsDamaged`/`IsDestroyed`
(`subsystems.py:868-895`) and `GetDamageRadiusFactor`, so
`ConditionTorpsReady`'s `pTube.IsDisabled()` keeps working. `TorpedoTube.CanFire`
already reaches power via `parent.IsOn()`, and the parent stays a
`PoweredSubsystem`.

**Scope boundary.** `PhaserBank`, `PulseWeapon` and `TractorBeam` also
(wrongly) subclass `WeaponSystem`. They are **out of scope here** — they are
live-verified and working. Introducing `EnergyWeapon(Weapon)` and migrating all
three is the **immediate follow-up project**.

### Risk: removals fail *silently*

`TGObject.__getattr__` (`engine/core/ids.py:125`) returns a **truthy, callable
`_Stub`** for any missing attribute. So after the re-parent, `tube.IsOn()` does
not raise — it returns a truthy stub, and `float(stub)` is `0.0`. **A method we
accidentally drop will not fail loudly; it will silently return a wrong value.**
Every `hasattr(...)` guard in the codebase is vacuously true for the same reason
and will not protect us.

Mitigation: (a) explicit tests asserting the tube's surface, and (b) run a
combat session with `DAUNTLESS_STUB_TELEMETRY` on and diff the heatmap for **new**
`TorpedoTube` rows. Nothing else will surface a lost method.

---

## Section 2 — Direction and reference frame

**Problem.** `CalculateRoughDirection()` returns `App.TGPoint3_GetModelForward()`
for *every* tube (`weapon_subsystems.py:1722`) — ignoring the tube's own stored
direction and never rotating into world space.

`AI/Preprocessors.py:447-456` builds `vToTarget` as a **world-space** delta and
dots it against `CalculateRoughDirection()` to select which tubes may dumb-fire.
`AI/PlainAI/IntelligentCircleObject.py:204,234` is decisive: it takes the result
and explicitly converts it **world→model** (`mWorldToModel`, comment *"Change it
to model space"*). So `CalculateRoughDirection` is unambiguously **world space**.

Consequence today: every tube reads as ship-forward. Aft tubes dumb-fire at
targets ahead; nothing fires at targets behind. **This is the AI dumb-fire bug.**

**Change.** Factor the body→world rotation out of `_emitter_in_arc`
(`weapon_subsystems.py:113-118`) into `_emitter_world_direction(emitter, ship)`
and have `CalculateRoughDirection` return it. The identical rotation is currently
duplicated in four places (`:51-56`, `:113-118`, `:141-147`, `:273-295`, plus
`subsystems.py:704-706`), so the helper is a genuine deduplication.

**Two things that must be right:**

- **`GetDirection()` stays MODEL space and is not touched.** It is dotted against
  a *model-space* restriction vector at `ConditionTorpsReady.py:128` and used as
  model-space at `Preprocessors.py:767`. `GetDirection` (model) and
  `CalculateRoughDirection` (world) are different vectors for different callers.
  Conflating them breaks the condition.
- **Resolve the ship with `_climb_to_ship()`, NOT `GetParentShip()`.**
  `ShipClass._attach_subsystem` (`ships.py:690-700`) calls `SetParentShip` only on
  **top-level** subsystems. Tubes are added as children under `TorpedoSystem`, so
  `tube._parent_ship` is `None` on every real tube. `_climb_to_ship()`
  (`subsystems.py:649-660`) walks up through `GetParentSubsystem()`.
  A plan that says `GetParentShip()` silently returns `None` and falls back.

**Orphaned tube** (no parent ship): return the un-rotated `GetDirection()`, which
defaults to `+Y` body-forward and coincides with today's `TGPoint3_GetModelForward()`.

**Honest note on impact.** `CalculateRoughDirection` currently has **zero
production callers** — only tests. Its value is realised when the SDK dumb-fire
path (`Preprocessors.py`) actually consumes it. Fixing the frame is correct and
cheap, but it is a prerequisite for AI dumb-fire, not an immediately visible win.

---

## Section 3 — Reload model (from the RE'd binary)

The decompile (`combat-and-damage.md:740-830`) gives the real model. We implement
it as specified rather than inferring.

**State** (per tube):

| Field | Value |
|---|---|
| `num_ready` | int |
| `last_fire_time` | float, **game time**, init **`-1000.0`** (not `-inf`) |
| `reload_timers` | float **array, one slot per `MaxReady`** |

Slot states: `-1.0` = loaded/ready; `0.0` = cooldown just started; `> 0.0` = cooling.

**`CanFire`** — `num_ready > 0` **and** ammo available **and**
`gameTime - last_fire_time >= ImmediateDelay`.

**`Fire`** — stamp `last_fire_time = gameTime`; `num_ready--`; decrement system
ammo; mark a free slot timer to `0.0`; spawn the projectile.

**`ReloadTorpedo`** — return early if `num_ready >= max_ready` or no ammo;
else `num_ready++`, system `total_ammo_consumed++`, set the **greatest-timer slot**
to `-1.0`, and post the reload event (Section 4).

**`UnloadTorpedo`** — inverse; also used by `SetAmmoType(type, immediate=1)`, which
per the decompile unloads every tube and clears every reload timer.

### How a slot actually becomes ready — the RE doc contradicts itself here

The state table (`combat-and-damage.md:775-780`) reads as though slot values are
**countdown timers** that tick (`> 0.0` = "cooling down"). But the note twelve lines
below (`:812-815`) says the opposite:

> *"Cooldown timers do not appear to 'tick down' via an explicit function. Instead
> the engine reads `last_fire_time` and compares against `g_Clock->gameTime +
> ReloadDelay` to schedule reloads via the event system."*

Both cannot be true, and we do not get to find out from the SDK. **Decision:** we
implement the *compare* reading, because it is the one the RE author states
explicitly and it is frame-rate independent:

- Each slot stores the **game time at which its cooldown started** (`-1.0` = loaded).
- `UpdateReload` polls each tube; a slot with a start-stamp becomes ready when
  `gameTime - slot_start >= ReloadDelay`, at which point `ReloadTorpedo()` runs.
- Per-slot stamps (not the single `last_fire_time`) are what make `MaxReady > 1`
  reload independently — a single scalar cannot.

This is recorded as **OQ-5**. Probe q12's measured fire→reload interval validates
it directly: on a Galaxy the gap between a tube's fire and its reload must be
~40 s, and on a `MaxReady=2` ship the two slots must come back independently.

### `ImmediateDelay` is a refire gate — not what our docstring claims

`combat-and-damage.md:824` puts it in `CanFire`:
`gameTime - last_fire_time >= ImmediateDelay`. It is **not** "delay from fire
request to launch" (the current unsourced claim at `weapon_subsystems.py:1629`,
which cites `galaxy.py:28-30` — bare setter calls with no comment supporting it).
That docstring gets corrected.

It is load-bearing, not cosmetic: values range to **5.0 s** across hardpoints
(keldon `1.5`, cardhybrid `1.0`, others `2.0`/`5.0`), not a uniform `0.25`.

### `MaxReady > 1` is real

Four hardpoint families ship `MaxReady=2`: `keldon.py:30`, `galor.py:30`,
`kessokmine.py:164`, `warbird.py:30,393`. Our single-scalar `_last_fire_time`
**cannot represent them**. The per-slot timer array fixes this.

### Do NOT convert to dt-integration

An earlier draft proposed integrating the `dt` that `UpdateReload(self, dt)`
already receives. **That is wrong here and would introduce a new bug.**
`_advance_weapons` is called once per **render frame** with a *constant*
`TICK_DT = 1/60` (`host_loop.py:6054`, `:5525`) — it is **not** inside the
fixed-timestep sim loop. Integrating `dt` there makes reload **frame-rate
dependent**: a Galaxy tube would reload in 20 s on a 120 Hz display.

The decompile uses a **game-clock compare**, which is frame-rate independent and
pause-frozen. We do the same. Clock accessor: `App.g_kUtopiaModule.GetGameTime()`
(deferred `import App` inside the method — the established idiom, already used at
`weapon_subsystems.py:1727` and `damage_decals.py:62`).

**The pause bug this fixes.** `_last_fire_time` is currently a `time.monotonic()`
wall-clock stamp (`:1668`). Wall time advances while the sim is frozen, so after a
40 s pause (or alt-tab, or a long mission load) the elapsed term already exceeds
`ReloadDelay` and **every tube instantly reloads** on the first frame back.

---

## Section 4 — Events

### `ET_TORPEDO_RELOAD` — lands now

Define it as a real integer in project-root `App.py` and post it from
`ReloadTorpedo` with the **tube as Destination**
(`ConditionTorpsReady.py:140,169`). Evidenced by the decompile, and it has no
destructive consumer.

**Value:** take the next free integer from our own private block (current high is
`ET_ADD_TO_REPAIR_LIST = 0x1321`, `App.py:988`). We do **not** need BC's real
integer — `App.py:762` states our event values are *"arbitrary but stable"*, and
nothing interoperates with BC's numbering. If q12 returns the real value we may
adopt it, but this item is **not blocked on q12**.

**Source:** not load-bearing. No SDK script reads `GetSource()` on a reload event,
and the decompile does not say what `ReloadTorpedo` posts with. We are the poster,
so we set it to the tube's parent `TorpedoSystem` and record that as a choice, not
a finding. q12 will confirm or correct it at zero cost.

### `ET_TORPEDO_FIRED` — BLOCKED on probe q12

Do **not** wire this until q12 reports. Three tiers disagree:

- Tier 3: the tube's `Fire` posts **`ET_WEAPON_FIRED`**, explicitly annotated
  *"NB: NOT `ET_TORPEDO_FIRED`"* (`combat-and-damage.md:806`).
- Tier 1: `ConditionTorpsReady` and `Episode7` consume `ET_TORPEDO_FIRED` with the
  **Torpedo projectile as Source** and the **tube as Destination**.
- The torpedo *projectile* path has **never been RE'd** — the most likely poster.

**Why guessing is unsafe:** `Episode7.TorpedoFired` (`Episode7.py:88-115`)
destroys the event's `GetDestination()` subsystem outright
(`MissionLib.SetConditionPercentage(pLauncher, 0)`) on a 10% roll. A wrong
Destination destroys the wrong subsystem.

Note this handler is an **authored E7M1 story beat** — unstable phased-plasma
torpedoes blow out the tube that fired them, with crew dialogue and a
forward/aft branch on the tube's name. It is a *feature we have lost*, not a
hazard we would be creating. It is also our **sign-off gate**: once wired, firing
phased plasma in E7M1 should occasionally destroy a tube with the correct dialogue.

Probe: `tools/probes/q12_torpedo_events.py` /
`docs/instrumented_experiments/2026-07-12-torpedo-event-probe.md`.

### `events.py` hardening — record and warn, never refuse

`ET_*` constants absent from our `App.py` fall through the module `__getattr__`
(`App.py:1935-1946`) to a `_NamedStub`. `events.py` uses the event type as a **raw
dict key** with no `int()` coercion (`:329`, `:384`), and `_Stub.__hash__` is
`id(self)` while `__getattr__` **does not memoize** `ET_*` — so **every access
mints a fresh key**. Each registration lands in its own private, permanently
unreachable slot. 89 distinct stub `ET_` names across ~270 SDK registration sites
are dead this way.

**Hardening must NOT refuse the registration.**
`Tactical/Interface/CinematicInterfaceHandlers.py:15` holds a module-level stub as
a *live same-object dispatch key* (registered at `:229`, fired at `:275` through
that same global). Refusing would break it. Instead:

1. At registration, detect a non-int event type — test `not isinstance(x, int)`,
   **not** `isinstance(x, App._NamedStub)`. There are two unrelated `_Stub`
   hierarchies (`App._Stub` and `engine.core.ids._Stub`) and a class check misses one.
2. **Record it to `stub_telemetry`** so it surfaces as ranked rows in
   `docs/stub_heatmap.md` — turning ~270 invisible dead handlers into a worklist.
   Note `stub_telemetry.ENABLED` is env-gated off by default
   (`stub_telemetry.py:35`), so this is only visible under `--developer`/telemetry runs.
3. Warn once per name; do not spam, do not raise.

**Fix `RemoveBroadcastHandler` (`events.py:344-353`).** It uses
`list.remove(entry)` / `in`, which compares tuples element-wise with `==`.
`_Stub.__eq__` is **type**-based, so *any* all-stub tuple compares equal to any
other — it can remove the **wrong handler**. Only the first tuple element needs to
be a stub for this to trigger. Use identity-based removal.

---

## Section 5 — Kill the phantom stub probes

`UpdateCharge` and `GetMaxCharge` are **not part of BC's `TorpedoTube` API and
never were** — they are bound exclusively on `EnergyWeapon`
(`sdk/.../App.py:6426-6440`), and `TorpedoTubeProperty` carries no charge fields.
`Actions/ShipScriptActions.py:355-400` confirms: it restores *charge* for energy
weapons, then switches to a *completely different* mechanism (`LoadAmmoType` /
`FillAmmoType`) for torpedoes.

The 4.5M heatmap hits (ranks **1 and 2**) come entirely from **our own code**
probing tubes for an API they cannot have:

- `host_loop.py:487` — `hasattr(emitter, "UpdateCharge")`, every emitter, every frame.
- `weapons_display_panel.py:233` — `hasattr(mount, "GetMaxCharge")`.

`hasattr` is always `True` because `__getattr__` returns a truthy `_Stub`, so
`host_loop` then *calls* the stub on every tube every frame.

**Change:** delete both probes; dispatch on `isinstance`. Correct the false
docstring at `weapons_display_panel.py:222-228` (it claims tubes have a zero
`_max_charge`; there is no `_max_charge` on a tube at all — the zero comes from
`_Stub.__float__`).

After the re-parent this is enforced *structurally*: a `Weapon` has no charge API
to probe for. `TorpedoTube` should disappear from the heatmap entirely.

---

## Section 6 — Testing

Gate: **`scripts/check_tests.sh`** (builds C++, runs pytest + ctest, diffs against
`tests/known_failures.txt`). Not `run_tests.sh` — it is pytest-only.

**New tests:**

- World-space `CalculateRoughDirection` on a **rotated** ship: an aft tube must dot
  **negative** against a target ahead. This is the dumb-fire bug; a test on an
  identity-rotation ship would pass even with the buggy implementation.
- `GetDirection()` remains model-space and unchanged.
- Reload advances on **game time**, and does **not** advance across a pause.
- `ImmediateDelay` refire gate blocks a second shot inside the window.
- `MaxReady=2` tube (warbird/keldon) reloads two slots independently.
- `TorpedoTube` no longer exposes `StartFiring` / `IsOn` / `UpdateCharge`
  (assert via the MRO, **not** `hasattr` — `hasattr` is vacuously true).
- Non-int event type at registration is recorded, not silently dead.
- `RemoveBroadcastHandler` removes the *correct* handler among stub-keyed entries.

**Tests that will need updating (identified in verification):**

| File | Why |
|---|---|
| `tests/unit/test_child_weapon_classes.py:30-33` | asserts `isinstance(tt, WeaponSystem)` — now false |
| `tests/unit/test_torpedo_tube_reload.py` | hard-codes `time.monotonic()`; encodes the single-timer model the decompile contradicts |
| `tests/unit/test_weapon_power_factor.py:141-215` | 5 torpedo cases seed `_last_fire_time` from `monotonic()` |
| `tests/unit/test_torpedo_tube_fire_dumb.py:22-33` | asserts the model-space `CalculateRoughDirection` |

**Live sign-off:** E7M1 — fire phased plasma; a tube should occasionally be
destroyed with the correct Felix/Saffi/Brex dialogue and forward/aft branch.
(Only after q12 unblocks `ET_TORPEDO_FIRED`.)

---

## Out of scope — findings to file separately

These surfaced during verification. All are real; none belong in this project.

1. **`EnergyWeapon(Weapon)`** — migrate `PhaserBank`/`PulseWeapon`/`TractorBeam` off
   `WeaponSystem`. **The agreed immediate follow-up.**
2. **`_advance_weapons` runs once per render frame with a constant `TICK_DT`**
   (`host_loop.py:6054`), so `UpdateCharge` — phaser/pulse/tractor recharge — **is
   frame-rate dependent today**. Real bug. Fix is to move it into `GameLoop.tick()`.
3. **`sensor_detection.py:63`** calls `App.g_kTimerManager.GetGameTime()`, which does
   not exist (`TGTimerManager` exposes `get_time()`). Wrapped in `try/except` → it
   **silently returns 0.0 forever**.
4. **89 stub `ET_` names / ~270 dead registrations**, incl. `ET_WEAPON_FIRED` and
   `ET_CANT_FIRE` — the latter silently disables the out-of-ammo / not-loaded voice
   lines and UI sounds in `TacticalMenuHandlers`. The friendly-fire chain
   (`MissionLib.py:3583`) is dead the same way.
5. **`ET_CLOAKED_COLLISION` and `ET_POWER_FRACTION_CHANGED` are both `1075`**
   (`App.py:913`, `:941`) — with dict-keyed dispatch these cross-fire.
6. **`MissionLib.py:4247`** — `if kOpenEvent == kCloseEvent:` is `True` for two
   *different* stub event types (type-based `_Stub.__eq__`).
7. **RE the torpedo projectile path** — closes `ET_TORPEDO_FIRED` properly, and q12
   only observes it rather than explaining it.

## Open questions

- **OQ-1** — `ET_TORPEDO_FIRED`: who posts it, with what Source/Destination, and on
  what trigger? → probe **q12**.
- **OQ-2** — Numeric IDs for the five torpedo/weapon events. → probe **q12**.
  (We must not invent values: `0x66`/`0x65` collide with our existing
  `ET_MISSION_START = 102` / `ET_ACTION_COMPLETED = 101`.)
- **OQ-3** — `ET_TORPEDO_RELOAD`'s Source. Unestablished from the SDK. → probe **q12**.
- **OQ-4** — `ImmediateDelay`'s field offset is marked `(?)` in the RE doc. The
  *behaviour* (a `CanFire` refire gate) is well-evidenced; the memory layout is not.
  We implement the behaviour and do not depend on the layout.
- **OQ-5** — The RE doc is **self-contradictory** on whether `reload_timers` tick
  down or are compared against `last_fire_time` (`combat-and-damage.md:775-780` vs
  `:812-815`). We implement the compare reading (see Section 3) and validate it
  against q12's measured fire→reload interval.
