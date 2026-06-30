# The #1 question: what BC's C++ actually does to a target when a weapon hits

Status: IN-PROGRESS  (Q1, Q3, Q4, Q5, Q6, Q7 closed via q02..q08; Q2 deferred; Q8-Q10 deferred to approach 1)
Author: 2026-06-29 session (instrumentation approach 2)
Created: 2026-06-29
Closed:  —

## The question (priority #1)

> **Per hit, exactly what does Appc do — what curve converts range to delivered
> damage, and how is that damage split across the impacted shield face, the
> locked subsystem, and the hull?**

This is the single highest-leverage unknown left in the project. Bridge
Commander *is* a combat sim; this formula governs combat balance and the entire
feel of an engagement. It lives entirely inside the closed C++ (`Appc`) — the
SDK only ever *commands* "fire" and reads results back, so no amount of static
SDK analysis recovers it. And right now our reimplementation **guesses** it:

- [`engine/appc/combat.py:apply_hit`](../../engine/appc/combat.py) assumes a
  **linear** falloff and a **strict** shields → subsystem → hull cascade.
- [`engine/host_loop.py`](../../engine/host_loop.py) `_advance_combat` /
  `_phaser_damage_for_tick` carry the same assumed curve.
- The original spec is explicit:
  [`2026-05-15-damage-routing-investigation.md:22`](2026-05-15-damage-routing-investigation.md)
  — *"Both choices are guesses inherited from PR 2b… Appc.dll holds the real
  formula."*

Everything downstream — AI difficulty, mission scripting, combat VFX intensity,
the damage-decal calibration — is currently tuned against a fabricated baseline.
Pin this one formula and a whole layer of guesswork collapses.

A tightly-coupled second half of the same weapon-exchange loop is the **energy
charge model** (discharge/recharge rate and its *unit*). The console can probe
both in one sitting, so this runbook covers both; damage routing is the
priority.

This experiment **subsumes** the two predecessor PENDING runbooks, which were
designed for the weaker App.py-snippet path:
- [`2026-05-15-damage-routing-investigation.md`](2026-05-15-damage-routing-investigation.md)
  (questions Q-D1…Q-D7)
- [`2026-05-15-phaser-charge-dynamics.md`](2026-05-15-phaser-charge-dynamics.md)
  (questions Q-C1…Q-C8)

Keep those for their question lists and the SDK-side context; this doc replaces
their *method*.

## Why now — instrumentation approach 2 (the dev console)

The original instrumentation (approach 1) appended a snippet to `App.py` and
could only **hook `GetGameTime` and dump downsampled rows via
`SaveConfigFile`** (see [README.md](README.md) and `tools/appc_logger.py`). To
measure damage routing that way you had to *fly a Galaxy at an enemy and hold
the trigger*, then infer the curve from noisy, downsampled before/after deltas
across uncontrolled ranges. Slow, blind, statistical.

**Approach 2 drives the game's own Python dev console.** That changes the
character of the experiment in two decisive ways:

1. **Live read-back.** The console echoes return values, so we read `Appc`
   state synchronously and iterate — no `SaveConfigFile` round-trip, no
   parsing a config dump on another machine.
2. **Deterministic, scripted setup.** We don't have to *fly and shoot*. The
   damage-routing function is directly callable:

   ```
   DamageableObject.AddDamage(position, radius, damage)   # App.py:5358
   ```

   (real signature confirmed from SDK use:
   `pObject.AddDamage(pEmitPos, fRadius, fDamage)` —
   [`Effects.py:698`](../../sdk/Build/scripts/Effects.py)). This is the routing
   black box itself. We can hand it a **known** world position, radius, and raw
   damage, then read the resulting per-face / per-subsystem / hull deltas — a
   clean unit test of the C++ routing, with **no weapon, no flying, no
   range-eyeballing, no downsampling**.

So the #1 question turns from a statistical fly-and-fire study into a handful of
deterministic one-liners. That is exactly the capability the old tooling
lacked, and exactly why this question is the one to ask first now that we have
the console.

> **Constraint that still applies:** the console is the *same embedded Python
> 1.5*. No f-strings, no `True`/`False` literals, no `import X as Y`, and
> `except Foo, e:` (comma) syntax. Keep every line 1.5-safe. Assume `os` is
> absent; `sys` is present. Output is the console echo (do **not** rely on
> `print`/`sys.stdout` until Part A confirms what the console actually shows).

## Confirmed Appc surface (all on the live objects)

Read back live with these (verified in
[`sdk/Build/scripts/App.py`](../../sdk/Build/scripts/App.py)):

| Need | Call | App.py |
|---|---|---|
| Player ship | `Game_GetCurrentPlayer()` | 10791 |
| Current target | `player.GetTarget()` | — |
| Shields object | `ship.GetShields()` | 5386 |
| Shield faces (count / per-face) | `sh.GetNumShields()`, `sh.GetCurShields(i)`, `sh.SetCurShields(i, v)`, `sh.GetMaxShields(i)` | 6364–6370 |
| Hull subsystem | `ship.GetHull()` → `.GetCondition()` / `.GetMaxCondition()` | 5382 / 5644 |
| Locked subsystem | `player.GetTargetSubsystem()` → `.GetCondition()` / `.GetName()` | 5454 / 5644 |
| **Route damage (the black box)** | `ship.AddDamage(pos, radius, damage)` | 5358 |
| Direct-damage a subsystem (set up states) | `ship.DamageSystem(subsys, amount)` | 5520 |
| Phaser system / a bank | `ship.GetPhaserSystem()`, `ws.GetWeapon(i)`, `ws.GetNumWeapons()` | 5410 / 5833 |
| Charge level (read/set) | `w.GetChargeLevel()`, `w.SetChargeLevel(v)`, `w.GetMaxCharge()`, `w.GetChargePercentage()` | 6436 / 6438 / 6437 |
| Declared rates / damage | `w.GetNormalDischargeRate()`, `w.GetRechargeRate()`, `w.GetMaxDamage()`, `w.GetMaxDamageDistance()` | 6427 / 6426 / 6434 / 6435 |
| Firing flag | `w.IsFiring()`, `ws.IsFiring()` | 5787 / 5865 |
| Frame counter (tick id) | `g_kSystemWrapper.GetUpdateNumber()` | — |
| Game time | `UtopiaModule.GetGameTime()` | — |

`TGPoint3` is constructible in the App namespace for the `pos` arg; or reuse a
live one (e.g. `t.GetWorldLocation()`).

## Specific questions

Damage routing (priority — these are the original Q-D set, re-asked against the
direct `AddDamage` probe):

- **Q1 (falloff anchor).** With the shield face full, call
  `AddDamage(hit_pos, R, D)` for a fixed `D` at increasing **distance** of
  `hit_pos` from the ship centre (or with increasing `radius` offset). Does the
  delivered delta equal `D` at the centre? → confirms the full-damage anchor.
- **Q2 (falloff shape).** Plot delivered-delta vs distance. Is it linear
  `D·(1 − d/MaxDamageDistance)`, quadratic, capped, or stepped? **This is the
  crux.** (Original Q-D2/Q-D3.)
- **Q3 (does `AddDamage` even respect shields?).** First discovery: does
  `AddDamage` subtract from the facing shield, or go straight to hull/visible
  damage? If it bypasses shields, find the weapon-path entry that doesn't (the
  console can also just fire a real bank and diff — Part E fallback).
- **Q4 (shield absorption while face alive).** With the impacted face alive,
  does **all** of the (post-falloff) damage subtract from that face, or does a
  fraction bleed to hull immediately? (Q-D4.)
- **Q5 (split after face depleted).** Pre-set the facing shield to 0 via
  `SetCurShields(i, 0)`. Now where does a hit go — 100% subsystem until
  destroyed, proportional subsystem/hull, or something else? (Q-D5.)
- **Q6 (subsystem-lock, shielded).** With a subsystem locked
  (`player.GetTargetSubsystem()` non-null) and the face still up, does any
  damage route to the locked subsystem through the shield? (Q-D6.)
- **Q7 (subsystem-lock, unshielded).** Face at 0 + subsystem locked: is the
  locked subsystem damaged at a higher rate than hull, and what is the ratio?
  (Q-D7.)

Energy charge model (the original Q-C set, the second half of the exchange):

- **Q8 (discharge unit — the core ambiguity).** `GetNormalDischargeRate()`
  returns a number; is it charge **per tick** or **per second**? Set charge to
  max, start firing, read charge again after a measured interval **and** a
  measured frame count (`GetUpdateNumber` before/after); `Δcharge/Δseconds` vs
  `Δcharge/Δframes` against the declared rate distinguishes them. (Q-C1.)
- **Q9 (recharge rate + unit).** Same method while idle. (Q-C2.)
- **Q10 (fire/auto-stop/restart thresholds).** Lowest charge at which
  `CanFire`/`IsFiring` stays true; the charge at which a held bank auto-stops;
  and the charge it must reach to restart (hysteresis). (Q-C3…Q-C5.)

## Console recipes

All snippets are Python-1.5-safe. Lines are meant to be typed/pasted into the
game's dev console between frames; the game keeps running, so state set on one
line persists to the next.

### Part A — confirm the console's I/O (do this first)

Establish how the console surfaces values and whether it tolerates multi-line
blocks. Try, in order, until one prints a readable number:

```python
p = Game_GetCurrentPlayer()
p.GetName()
g_kSystemWrapper.GetUpdateNumber()
```

Record which form echoes output. If bare expressions don't echo, define a tiny
helper that returns a string you can read off whatever surface *does* work
(console line, HUD text, or — last resort — the approach-1
`g_kConfigMapping.SetStringValue(...)/SaveConfigFile(...)` sink). Everything
below assumes you can read a returned value somehow; note the mechanism in
Findings.

### Part B — the falloff curve (Q1/Q2), fully deterministic

Grab a target, snapshot the facing shield + hull, hit it with a known `D` at a
known offset, snapshot again. Repeat at several offsets.

```python
p = Game_GetCurrentPlayer()
t = p.GetTarget()                       # acquire an enemy first (Tab) if needed
sh = t.GetShields()
n  = sh.GetNumShields()

# Helper: total shield + hull as a single readable string (1.5-safe).
def snap(t, sh, n):
    s = 0.0
    i = 0
    while i < n:
        s = s + sh.GetCurShields(i)
        i = i + 1
    h = t.GetHull().GetCondition()
    return "shield_total=%.3f hull=%.3f" % (s, h)

# Baseline:
snap(t, sh, n)

# Deterministic hit at the target centre, radius 1, raw damage 1000:
c = t.GetWorldLocation()
t.AddDamage(c, 1.0, 1000.0)
snap(t, sh, n)                          # delta vs baseline = delivered@centre
```

Then sweep the hit position outward along one axis (or grow the radius) to map
delivered-delta vs distance:

```python
import App
def hit_at_offset(t, dx):
    c = t.GetWorldLocation()
    pos = App.TGPoint3(c.x + dx, c.y, c.z)   # if TGPoint3 ctor differs, reuse a live point and mutate
    t.AddDamage(pos, 1.0, 1000.0)
```

Reset shields between hits so each measurement starts from a known state:

```python
def reset_shields(sh, n, v):
    i = 0
    while i < n:
        sh.SetCurShields(i, v)
        i = i + 1
reset_shields(sh, n, sh.GetMaxShields(0))
```

Tabulate `(offset, delivered_delta)`. The ratio of delivered@offset to
delivered@centre **is** the falloff curve. Compare offsets to
`GetMaxDamageDistance()` for the phaser bank to anchor the x-axis.

### Part C — the routing split (Q3–Q7)

Drive specific states with the setters, then hit once and read where it landed:

```python
# Q5: facing shield depleted, no lock — set the hit face to 0, others full.
reset_shields(sh, n, sh.GetMaxShields(0))
sh.SetCurShields(0, 0.0)                # 0 = the face we'll hit
hull0 = t.GetHull().GetCondition()
t.AddDamage(t.GetWorldLocation(), 1.0, 1000.0)
"hull_delta=%.3f" % (hull0 - t.GetHull().GetCondition())
# also read every subsystem condition before/after to see if a subsystem took it
```

For Q6/Q7 set the subsystem lock from the firing ship
(`player.SetTargetSubsystem(...)`, per
[`project_subsystem_lock_on_player`](../../) memory — the lock lives on the
**player**, not the target), then repeat the shielded and unshielded hits and
diff `player.GetTargetSubsystem().GetCondition()` vs hull.

### Part D — charge unit + thresholds (Q8–Q10)

```python
ws = p.GetPhaserSystem()
w  = ws.GetWeapon(0)
w.GetNormalDischargeRate()              # declared number — unit unknown
w.GetMaxCharge(); w.GetChargeLevel()
w.SetChargeLevel(w.GetMaxCharge())      # known start
f0 = g_kSystemWrapper.GetUpdateNumber()
t0 = UtopiaModule.GetGameTime()
# --- start firing (hold the fire key, or trigger the bank), wait ~1 s of wall time ---
f1 = g_kSystemWrapper.GetUpdateNumber()
t1 = UtopiaModule.GetGameTime()
c1 = w.GetChargeLevel()
"dframes=%d dt=%.4f dcharge=%.4f" % (f1 - f0, t1 - t0, w.GetMaxCharge() - c1)
```

`dcharge/dt` ≈ declared rate → **per second**; `dcharge/dframes` ≈ declared
rate → **per tick**. That single comparison answers the unit question that
[`engine/appc/weapon_subsystems.py:372`](../../engine/appc/weapon_subsystems.py)
`UpdateCharge` currently guesses. Read `GetChargeLevel()` at the moment
`IsFiring()` flips false for the auto-stop threshold; keep reading during idle
recharge for the restart/hysteresis point.

### Part E — fallback / cross-check (fire a real bank)

If `AddDamage` turns out **not** to be the weapon routing path (Q3), fall back
to the controlled-fire diff: park at a fixed range, snapshot, fire exactly one
bank for a known number of frames, snapshot. Still far better than approach 1
because the console reads state synchronously and you control the setup. The
predecessor doc's fly-and-fire passes
([damage-routing §How to run](2026-05-15-damage-routing-investigation.md)) become
the slow last resort, not the primary method.

## Expected output / how to read it

A short table per part, e.g. for Part B:

```
offset(GU)  delivered_delta   ratio_to_centre
0.0         1000.0            1.00
R/4         ...               ...
R/2         ...               ~0.50 linear?  ~0.25 quadratic?
R           ...               ~0.00 ?
```

The deltas themselves are the answer; no statistical fitting needed if
`AddDamage` is deterministic.

## What it unblocks

Once Findings are filled in:

- Replace the assumed-linear falloff in
  [`engine/host_loop.py`](../../engine/host_loop.py) `_phaser_damage_for_tick`
  with the measured curve.
- Replace the strict-cascade split in
  [`engine/appc/combat.py:apply_hit`](../../engine/appc/combat.py) with the
  verified shield/subsystem/hull ratios and the real subsystem-lock routing.
- Replace the guessed discharge/recharge **unit** and hysteresis in
  [`engine/appc/weapon_subsystems.py`](../../engine/appc/weapon_subsystems.py)
  `UpdateCharge` (the `0.20·MaxCharge` "feel-tuned nominal" at line 190).

Then the two predecessor experiments can be marked DONE (answered here) and the
combat baseline stops being a fabrication.

## Cleanup

The console mutates live state (shields, charge, subsystem conditions) but
writes nothing to disk unless you used the `SaveConfigFile` fallback in Part A.

- If you used the config-file sink, run `uv run python tools/uninstall.py` and
  delete any `BC*Log.cfg` left in `game/`.
- Otherwise: just **restart Quick Battle** (or quit BC) to discard the mutated
  combat state. No repo edits are required for the console path — that is part
  of why approach 2 is cleaner than approach 1.

## Findings

Captured 2026-06-29 / 2026-06-30 across nine probes:

- [`q01_console_io.txt`](../../tools/probes/results/q01_console_io.txt) — console namespace + API verification
- [`q02_addamage_falloff.txt`](../../tools/probes/results/q02_addamage_falloff.txt) — `AddDamage` primitive
- [`q03_weapon_fire_diff.txt`](../../tools/probes/results/q03_weapon_fire_diff.txt) — weapon-fire snapshot diff
- [`q04_shield_bleedthrough.txt`](../../tools/probes/results/q04_shield_bleedthrough.txt) — shield routing model
- [`q05a_face_zero_full.txt`](../../tools/probes/results/q05a_face_zero_full.txt) — face-at-zero routing, FULL intensity, no lock
- [`q05b_face_zero_light.txt`](../../tools/probes/results/q05b_face_zero_light.txt) — face-at-zero routing, LIGHT intensity, no lock
- [`q06_lock_shielded.txt`](../../tools/probes/results/q06_lock_shielded.txt) — shielded + subsystem lock
- [`q07a_lock_face_zero_full.txt`](../../tools/probes/results/q07a_lock_face_zero_full.txt) — face-at-zero + lock, FULL intensity
- [`q07b_lock_face_zero_light.txt`](../../tools/probes/results/q07b_lock_face_zero_light.txt) — face-at-zero + lock, LIGHT intensity
- [`q08_lock_rear_subsystem.txt`](../../tools/probes/results/q08_lock_rear_subsystem.txt) — Q7 disambiguation: lock rear-mounted impulse engines, fire from front
- [`q09_range_falloff.txt`](../../tools/probes/results/q09_range_falloff.txt) — range/DPS falloff curve, 7 samples from 5 km to 30 km

### Headline: two distinct damage primitives

Approach 2 confirmed BC's C++ exposes **two independent damage-routing paths**:

| Primitive | Caller | Routing |
|---|---|---|
| `DamageableObject.AddDamage(node, radius, damage)` | explosions / collisions / death bursts (SDK: `DeathExplosionDamage`, `Effects.py:689`) | **Bypasses shields entirely** — always goes straight to hull |
| Weapon-fire path (internal Appc, not directly callable from Python) | normal phaser/torp combat fire | **Strict cascade through shields** — facing shield until it reaches zero, then hull |

This explains why `engine/appc/combat.py:apply_hit`'s strict-cascade model is correct in spirit but only describes one of the two paths. Splash damage from explosions needs a separate code path that bypasses shields entirely.

### Per-question status

- **Q1 ✓** — AddDamage at the centre node delivers exactly the requested damage (ratio 1.0, verified at radii 0.1, 1, 5, 30, 60, 120 — all delivered 1000.0 hull damage). Radius does not affect delivered damage when the hit node is the ship centre.
- **Q2 — DEFERRED.** `AddDamage` takes a scene NODE, not a TGPoint3 (`Effects.py:691` literally comments *"INVALID NiAVObject wrapper"*). Position can't be varied by mutating coordinates; would need to iterate sub-nodes or use `target.GetRandomPointOnModel()` for statistical sampling. Low priority — AddDamage is the explosion path, not the weapon path.
- **Q3 ✓** — AddDamage bypasses shields (q02: 1000 hull / 0 shield across 6 radii). Weapon-fire path routes through shields (q03: 715 shield / 180 hull over a 35 sec fire window).
- **Q4 ✓** — **STRICT CASCADE, no bleed-through fraction.** With every face reset to max and weapons fired for ~9 sec, hull damage was exactly **0.0**; all 136.6 of delivered damage stayed on the faces. q03's 80/20 split was therefore a face briefly depleting mid-window, not a constant bleed-through.
- **Q5 ✓** — **The phaser intensity setting is load-bearing for routing.** With all shield faces at 0 and *no* deliberate subsystem lock (just targeting the ship body), routing depends entirely on `PhaserSystem.GetPowerLevel()`:

  | Intensity | hull Δ | top-subsystem Δ | Split |
  |---|---|---|---|
  | FULL  (PP_HIGH = 2) | 375 | sensors -342 | ~52% hull / 48% sub |
  | LIGHT (PP_LOW  = 0) | **0** | sensors -136 | **0% hull / 100% sub** |

  Two structural findings under this:
  - **Subsystem routing is geometric.** All subsystem damage went to **sensors** in q05/q07 because the operator fired from in front of the Galaxy-1, and the sensor array is the forward-mounted subsystem closest to the phaser impact points. *Sensors is not a fixed default* — damage routes to whichever subsystem's hardpoints lie nearest the impact, so the answer depends on angle on target. A follow-up probe firing from above/below/behind would map this explicitly.
  - The damage signal is on **`GetDamage()` (parent counter)** and **`GetCombinedConditionPercentage()` (child rollup)**, NOT on `GetCondition()` of the top-level named subsystems alone. q05 v1 missed this and reported all-zero subsystem damage; the walked-children probe sees it correctly.
- **Q6 ✓** — **Subsystem locks do NOT bypass intact shields.** q06 with all faces at max, FULL intensity, `power` deliberately locked (verified via readback): the facing face took 184 damage and **nothing else moved** — hull = 0, locked `power` subsystem = 0 damage. Strict cascade holds; the lock confers no penetrating power.
- **Q7 ✓** — **Subsystem locks do NOT redirect weapon fire.** q08 nailed this down: with `impulse` (rear-mounted on Galaxy) deliberately locked and the player firing from directly in front, all damage still went to `sensors` (forward-mounted, geometrically nearest the impact) and **zero damage** reached the locked impulse subsystem:

  | Probe | locked sub | top damaged sub | locked sub Δ |
  |---|---|---|---|
  | q05a (no lock, FULL)         | n/a     | sensors (-342) | n/a |
  | q07a (lock=power, FULL)      | power   | sensors (-191) | power (-0) |
  | q05b (no lock, LIGHT)        | n/a     | sensors (-136) | n/a |
  | q07b (lock=power, LIGHT)     | power   | sensors (-58)  | power (-0) |
  | **q08 (lock=impulse, FULL)** | impulse | sensors (-291) | **impulse (-0)** |

  The lock readback at PRE confirmed `lock_was = impulse` (the API accepted the lock), but the damage routing ignored it entirely. The hull/sub split was 54/46 — identical to q07a. Subsystem locks must be purely AI-priority / visual reticle / bridge-officer-aim hints — NOT a damage-routing input. Engine implication: **`combat.apply_hit` doesn't need a lock-aware branch; routing is `(intensity, nearest_geometric_subsystem_to_impact)`**.
- **Q8 / Q9 / Q10 — DEFERRED to approach 1.** q03 proved snapshot-diff can't measure discharge: the bank fully recharges between PRE and POST snapshots (`d_charge = 0` over 35 sec). Per-tick polling via an `App.py` snippet (see `tools/charge_logger.py` for the pattern) is the right tool.

### Bonus findings (not in original question set)

- **`AddDamage` radius is a *splash* parameter, not a falloff axis at the centre.** Same 1000 damage delivered at r=0.1 and r=120 when hit-node = ship centre. Radius likely matters only when the hit point is offset from centre and the splash sphere intersects different parts of the hull — not yet measured.
- **Weapons deliver non-zero damage beyond `MaxDamageDistance`.** q04 hinted at this; q09 confirmed and mapped the curve.  Seven samples from 5 km to 30 km against a stationary Galaxy-1:

  | Range (km) | Range/R | DPS | Ratio to peak | Linear-cap pred |
  |---|---|---|---|---|
  | 30.17 | 2.87× | 24.80 | 0.30 | 0.00 (capped) |
  | 24.92 | 2.37× | 29.45 | 0.36 | 0.00 |
  | 19.86 | 1.89× | 36.23 | 0.44 | 0.00 |
  | 15.00 | 1.43× | 57.69 | 0.70 | 0.00 |
  | 10.01 | 0.95× | **82.89 (peak)** | 1.00 | 0.05 |
  | 5.00  | 0.48× | 74-78 | ~0.92 | 0.52 |

  Two structural findings: damage **plateaus within R** (5 km and 10 km within ~10% despite 2× range difference) AND **decays approximately as `R/d` beyond R** (predicted ratios 0.70/0.50/0.40/0.33 vs observed 0.70/0.43/0.35/0.30 — fit within 5-15%). The current engine model `max(0, 1 - d/R)` is qualitatively wrong; replace `engine/host_loop.py:_phaser_damage_for_tick` with a plateau-within-R + `R/d`-beyond-R curve.
- **`ShipSubsystem.SetCondition(0)` cleanly disables target engines / weapons** (`setup_disable_target.py`). Verified on Galaxy-1 and Marauder-1; impulse, warp, phasers, torpedoes, pulse all zero on demand. Stays disabled until the target dies or scene resets. This is the test-control primitive we needed for all subsequent A/B probes.
- **Shield face regen rate is ~6.7 pts/sec per face** (Galaxy-1, observed over 4.25 / 4.75 sec windows in q05a/q05b). Means any "face-at-zero" experiment has a shrinking window the moment you unpause.
</content>
</invoke>
