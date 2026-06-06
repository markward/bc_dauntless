# Damage Attribution — Spherical Splash Model

**Status:** drafted, awaiting user review
**Date:** 2026-06-06
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md) — roadmap this spec slots into; supersedes the attribution decision in §3.
- [`2026-06-01-subsystem-damage-propagation-design.md`](./2026-06-01-subsystem-damage-propagation-design.md) — superseded by this spec; the winner-takes-all "closest within 2× radius" rule is replaced by the splash model below.
- [`2026-05-14-phaser-combat-design.md`](./2026-05-14-phaser-combat-design.md), [`2026-05-14-torpedo-combat-design.md`](./2026-05-14-torpedo-combat-design.md) — producers of the `(impact_position, damage)` records this model consumes.

## 1. Goal

Define how a single weapon impact translates into damage applied to the receiving ship's subsystems and hull. Replace the current winner-takes-all / picked-subsystem model with a spherical-splash model that:

- attributes damage to **every** subsystem whose damage sphere intersects the hit's splash sphere, weighted by overlap;
- always applies hull damage in addition to subsystem damage (no competition between hull and subsystems for the same damage budget);
- uses SDK-defined per-subsystem `SetRadius(...)` and per-weapon `SetDamageRadiusFactor(...)` values so attribution behaviour is data-driven, not hardcoded per weapon class;
- supports an out-of-scope future "manual targeting" mouse-pointer mode for free, because the resolver only consumes `(P, N, D)` and never the player's chosen target subsystem.

## 2. Diagnosis — what's wrong now

Two observable failures motivate this work:

1. **Hits on the hull don't damage nearby subsystems.** The current path in `engine.appc.combat.apply_hit` calls `pick_target_subsystem(ship)` which is effectively a no-op on real ships (it iterates `GetNumChildSubsystems`, a method that doesn't exist on `ShipClass`). It always returns `ship.GetHull()`. Damage routes shields → hull, never touching subsystems unless the player explicitly aimed at one.
2. **Targeting a subsystem makes that subsystem absorb damage to the exclusion of others.** When a target is picked, all damage goes to that subsystem. This contradicts stock Bridge Commander, where targeting biases *aim* and the splash distribution at the impact point determines which subsystems take damage.

Both are addressed here by replacing the picker entirely with a geometric resolver that ignores the player's target choice and considers only the impact point's position relative to every subsystem on the receiving ship.

## 3. Locked design decisions

These were settled in the brainstorm session and are not open for relitigation in implementation; they are the contract this spec defines.

### 3.1 Hit point is mesh-accurate

Damage attribution consumes `(P, N)` produced by ray-vs-triangle trace against the loaded NIF geometry. This is Project 1 of [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md), unchanged. This spec assumes Project 1 lands first.

### 3.2 Splash radius is data-driven from `SetDamageRadiusFactor`

Each weapon firing emits a single damage event with a splash radius `R_hit` resolved as follows:

```
R_hit = hardpoint_weapon.GetDamageRadiusFactor()   if non-zero
      = payload_template.GetDamageRadiusFactor()    otherwise
      = 0.15                                        phaser hardcoded default
```

Where:

- `hardpoint_weapon` is the `WeaponProperty` on the firing ship's hardpoint, e.g. `Galaxy.ForwardTorpedo1` with `SetDamageRadiusFactor(0.20)`.
- `payload_template` is the projectile-type template, e.g. `PhotonTorpedo` with `SetDamageRadiusFactor(0.13)`. Only present for torpedo / projectile weapons; phasers have no payload.
- The phaser fallback of `0.15` matches the value the SDK hardpoint files write for phasers in practice; the fallback is reached only on a hardpoint that omits the explicit call.

`R_hit` is in game units (1 GU = 175 m). The override interpretation of `hardpoint_DRF > payload_DRF` is treated as the working hypothesis; see §6 (verification plan) for the instrumented test that will confirm or revise this.

`WeaponHitEvent` in the stock SDK already exposes `GetRadius()` (see `sdk/Build/scripts/App.py:6252`), strongly implying the original engine resolves `R_hit` internally per hit and publishes it on the event. Our firing path follows suit: the resolver above runs at firing time and the resolved value is stamped onto the broadcast `WeaponHitEvent` so downstream consumers (VFX, audio, persistent damage records) can read it without re-resolving.

### 3.3 Candidate subsystems by sphere–sphere intersection

For each subsystem `i` on the target ship with body-frame position `H_i^body` and SDK radius `R_i = subsystem.GetRadius()`:

- World-space hardpoint position: `H_i^world = ship_pos + R_world · H_i^body` where `R_world = ship.GetWorldRotation()` (column-vector convention per CLAUDE.md).
- Candidate iff `|P − H_i^world| < R_i + R_hit`.

The hull is **always** a candidate with weight `w_hull = 1.0` — not subject to the sphere-overlap test, not subject to the falloff in §3.4. Every post-shield hit applies the full post-shield damage `D` to the hull. The user's framing makes this explicit: stock BC "converts those arbitrary hits to both general hull damage and subsystem damage," with hull damage attached to *every* hit regardless of where on the ship it landed.

The SDK call `Hull.SetRadius(...)` in hardpoint files (e.g. Galaxy `1.0`, sunbuster `4.0`) is retained on the hull subsystem for legacy / AI / camera consumers but is **not** consumed by this resolver. (Treating it as a catchment radius produces wrong results: a phaser hit at the Galaxy nacelle is ~3.5 GU from ship center, well outside `R_hull + R_hit = 1.15` GU, which would incorrectly exclude the hull from candidates.)

### 3.4 Per-candidate weight via linear falloff

For each candidate:

```
w_i = clamp((R_i + R_hit − |P − H_i^world|) / R_hit, 0, 1)
```

Properties:

- `w_i = 1.0` whenever the impact point lies inside (or on the surface of) the subsystem sphere — that is, `|P − H_i| ≤ R_i`. The clamp saturates the weight: a hit any deeper into the subsystem does not amplify damage further.
- `w_i → 0` as the impact point approaches the edge of the combined sphere (`|P − H_i| → R_i + R_hit`), and is exactly zero at and beyond it.
- Bigger `R_i` widens the catchment area but does **not** scale the weight; physically, a large subsystem is hit more *often*, not harder per hit.
- Normalised by `R_hit`, so weapons with bigger splash decay over a wider band but at the same edge-vs-centre ratio.

### 3.5 Allocation is independent (no conservation)

Each candidate takes `D_i = D · w_i` independently. Total damage applied across all candidates can (and usually does) exceed `D`. A direct hit on the centre of the warp core damages both the warp core and the hull at full strength simultaneously.

Rationale:

- Matches stock BC's observable behaviour where the hull bar drops at full rate alongside the damaged subsystem.
- Avoids the perverse tuning incentive where shooting at well-protected interior subsystems is *worse* for the attacker because the damage "leaks" away from the hull.
- Conservation across an arbitrary candidate set is a property the user is not asking for; preserving "every subsystem absorbs the splash it intercepts" is.

### 3.6 Shields gate the splash

Shield face is selected by impact direction in body frame: `face = dominant_axis(R_world^T · (P − ship_pos))`. The shield strength on that face attenuates `D_raw` to produce `D` (the post-shield damage that feeds the splash distribution). Aft hits hit the aft face regardless of the player's aim. This is the existing Project 3 of the pipeline roadmap, unchanged.

### 3.7 Targeting biases aim only

The player's target-subsystem selection is consumed exclusively by the firing math to compute the aim point. It has zero influence on damage attribution. A phaser aimed at "Engines" that visibly strikes the saucer rim damages whatever subsystems are within the splash sphere at the saucer rim — not the engines.

## 4. The model in detail

Pseudocode for the resolver, intended to live in `engine/appc/combat.py` and replace the body of `pick_target_subsystem` (which is renamed / inlined):

```python
def attribute_damage(victim_ship, impact_world, impact_normal, raw_damage,
                     hardpoint_weapon, payload_template):
    # 3.2 — splash radius
    if hardpoint_weapon and hardpoint_weapon.GetDamageRadiusFactor() > 0:
        r_hit = hardpoint_weapon.GetDamageRadiusFactor()
    elif payload_template:
        r_hit = payload_template.GetDamageRadiusFactor()
    else:
        r_hit = PHASER_DEFAULT_DAMAGE_RADIUS  # 0.15

    # 3.6 — shields
    face = shield_face_from_impact(victim_ship, impact_world)
    post_shield_damage = apply_shield_attenuation(victim_ship, face, raw_damage)
    if post_shield_damage <= 0.0:
        return  # absorbed by shields; no hull / subsystem damage

    # 3.3 — candidate set, 3.4 — weights, 3.5 — independent allocation
    R = victim_ship.GetWorldRotation()
    ship_pos = victim_ship.GetWorldLocation()

    # Hull always takes full damage (no sphere test, no falloff).
    hull = victim_ship.GetHull()
    if hull is not None:
        victim_ship.DamageSystem(hull, post_shield_damage)

    # Subsystems take a weighted share based on splash sphere overlap.
    for subsystem in iter_all_subsystems(victim_ship):
        if subsystem is hull:
            continue
        h_body = subsystem.GetPosition()
        h_world = ship_pos + R.MultMatrixLeft_world_from_body(h_body)
        r_sub = subsystem.GetRadius()
        d = (impact_world - h_world).Magnitude()
        if d >= r_sub + r_hit:
            continue  # outside splash, no contribution
        w = max(0.0, min(1.0, (r_sub + r_hit - d) / r_hit))
        if w > 0.0:
            victim_ship.DamageSystem(subsystem, post_shield_damage * w)

    broadcast_weapon_hit_event(victim_ship, impact_world, impact_normal,
                                post_shield_damage, r_hit, hardpoint_weapon)
```

Notes:

- `iter_all_subsystems` walks `ship.GetSubsystems()` plus the `_children` lists of weapon-system aggregates (`_phaser_system`, `_torpedo_system`), so individual phaser banks and torpedo tubes are candidates in their own right.
- `R.MultMatrixLeft_world_from_body(h_body)` is shorthand for the column-vector `R · h_body` transform; in code this is `h_body.MultMatrixLeft(R)` per the convention in CLAUDE.md and the SDK's `TGPoint3`.
- `DamageSystem(subsystem, w · D)` flows into the existing `IsDamaged / IsDisabled / IsDestroyed` predicates and parent aggregation rules (per the propagation spec, which is otherwise superseded by this document).
- `WeaponHitEvent` is broadcast once with the impact point; consumers (bridge feedback, VFX) bind off the event and don't need the per-candidate allocation.

### 4.1 Edge cases

- **No subsystem candidates within splash.** Hull still takes full damage (unconditional). No subsystem damage occurs. Common on hits that land far from any interior subsystem.
- **All hits absorbed by shields.** No subsystem or hull damage; the broadcast hit event still fires so VFX render the shield flash.
- **Impact point inside multiple subsystems.** Common for tight ships (Rankuf). Each gets a high weight independently; nothing prevents one hit from disabling a subsystem cluster.
- **Weapon with no payload and no hardpoint DRF.** Falls back to the phaser default (0.15). This is a safety net for hand-authored weapons that forget to declare radius; not an intended configuration.
- **Subsystem with `R = 0`.** Treated as a point that can only be hit if the splash sphere encloses the point exactly (`d < r_hit`). Weight is `1 − d / r_hit`. Stock SDK ships do not appear to ship `R = 0` subsystems but the resolver should not crash if one appears.

## 5. Integration with the existing combat-damage-pipeline roadmap

This spec slots in as a refinement of Project 2 of [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md):

- **Project 1 (mesh-accurate hit resolution)** — unchanged. This spec assumes its output.
- **Project 2 (subsystem damage propagation)** — body of the picker is replaced with the §4 resolver. The "closest within 2× radius" rule and `pick_target_subsystem` are removed. Parent-aggregator predicates from the propagation spec remain — they describe how parent subsystems derive damaged / disabled / destroyed state from children and are orthogonal to attribution.
- **Project 3 (shield face mapping)** — unchanged.
- **Project 4 (damage VFX + bridge feedback)** — consumes the `WeaponHitEvent` payload (`P, N, post_shield_damage`) without caring how attribution split the damage internally. No change required here.
- **Project 5 (subsystem-failure consequences)** — unchanged.

The propagation spec [`2026-06-01-subsystem-damage-propagation-design.md`](./2026-06-01-subsystem-damage-propagation-design.md) is **partially superseded**: the attribution decision (winner-takes-all closest within 2× radius) is replaced; the parent-aggregation rules are retained. When this spec lands, the propagation doc gets a `Superseded by: 2026-06-06-damage-attribution-design.md` marker on its attribution sections.

## 6. Verification plan — instrumented test

The splash-radius resolver in §3.2 codifies the working hypothesis that **hardpoint DRF overrides payload DRF**. The combination logic in `Weapon.GetDamageRadiusFactor()` lives inside `Appc.DLL` and cannot be inspected from Python. The original engine, however, ships the *resolved* per-hit radius on the broadcast hit event: `WeaponHitEvent.GetRadius()` (App.py:6252). Reading that value directly per hit short-circuits any back-solving and answers the combination-logic question with one number per hit.

### 6.1 Method

Use the existing `tools/appc_logger.py` patching infrastructure (Python 1.5 syntax; appended to `App.py`; output via `g_kConfigMapping.SaveConfigFile("BCAttribLog.cfg")`).

**Approach:** hook a global `WeaponHitEvent` listener via the SDK's existing event subscription path. For each event fired:

- `attacker_id      = evt.GetFiringObject().GetObjectID()`
- `victim_id        = evt.GetTargetObject().GetObjectID()`
- `weapon_type      = evt.GetWeaponType()`  # PHASER / TORPEDO / TRACTOR_BEAM
- `weapon_inst_id   = evt.GetWeaponInstanceID()`  # used to resolve the hardpoint
- `hit_world        = evt.GetWorldHitPoint()`
- `hit_normal       = evt.GetWorldHitNormal()`
- `event_radius     = evt.GetRadius()`  # ← the resolved R_hit
- `event_damage     = evt.GetDamage()`
- `is_hull_hit      = evt.IsHullHit()`

Then resolve the input DRF values for cross-referencing:

- `hardpoint_DRF`: look up the firing ship's hardpoint by weapon instance ID and call `weapon_property.GetDamageRadiusFactor()` on it.
- `payload_DRF`: for torpedo hits, look up the projectile template module by weapon type and read its `SetDamageRadiusFactor` value from a one-shot table built at logger init by importing each `Tactical/Projectiles/*.py` module and inspecting its `Initialize` function (or, simpler: hardcode the table from the values in §5 of the brainstorm record — the SDK projectile DRF values are not expected to change).

Emit one record per hit: `(weapon_type, payload_type_name, hardpoint_DRF, payload_DRF, event_radius, hit_world, victim_id, tick)`.

This avoids the entire condition-delta back-solving approach in the original draft of this section. The engine's resolved radius is observed directly.

### 6.2 Controlled scenarios (QuickBattle)

Each scenario produces a small log; aggregate across scenarios to characterise the combination function.

1. **Phaser hit.** Fire a phaser from any ship onto any target. Expected `event_radius`: **0.15** (matches the SDK's hardpoint DRF for every phaser hardpoint examined; phasers have no payload).
2. **Photon torpedo from Galaxy launcher** — hardpoint DRF 0.20, payload DRF 0.13. Expected `event_radius`: 0.20 (override), 0.026 (multiplicative), 0.33 (additive).
3. **Quantum torpedo from Akira launcher** — hardpoint DRF 0.60, payload DRF 0.14. Expected `event_radius`: 0.60 (override), 0.084 (multiplicative), 0.74 (additive).
4. **Cross-check with a no-payload weapon on a non-default-radius hardpoint.** Fire the Keldon's `AftBeam` (hardpoint DRF 0.10) onto any target. Expected `event_radius`: 0.10. Failure here implies hardpoint DRF is not the value the engine resolves to even in the no-payload case, and the whole working hypothesis is wrong.
5. **Cross-check with a payload-only / hardpoint-default torpedo if one exists.** Some torpedo hardpoints may omit `SetDamageRadiusFactor` entirely, leaving the engine to fall back to the payload value. If so, observe `event_radius == payload_DRF` for that case. Audit hardpoint files for examples first; not all ships will provide one.

### 6.3 Decision rule

| Observation across scenarios 2, 3, 4 | Action |
|---|---|
| `event_radius == hardpoint_DRF` in all three | Override hypothesis confirmed. Resolver in §3.2 stands. Mark this section "verified $DATE". |
| `event_radius == hardpoint_DRF * payload_DRF` (scenarios 2, 3) and `== hardpoint_DRF` (scenario 4) | Multiplicative combination when payload exists, override when it doesn't. Update resolver. |
| `event_radius == hardpoint_DRF + payload_DRF` (scenarios 2, 3) and `== hardpoint_DRF` (scenario 4) | Additive combination when payload exists. Update resolver. |
| Mixed values across same scenario type | The engine is doing something we haven't modelled (weapon-class-specific, distance-modulated, etc.). Escalate to a new brainstorm before changing the resolver. |

### 6.4 Caveats

- `WeaponHitEvent.GetWorldHitPoint()` fidelity is unverified. Even though we no longer back-solve, the spec's §3.3 candidate test depends on this point. Cross-check by comparing event position against the same-tick mesh raycast and reporting the residual. If event position is bounding-sphere-approximated, our model still works on its own raycast output but consumers of the event payload (VFX) should be aware.
- The instrumented logger runs in the *original game*, not our build. Its purpose is to characterise what the engine we're reimplementing actually does. Findings translate directly into the §3.2 resolver in our Python combat module; no Python combat code runs during the instrumentation pass.
- Event subscription mechanics: the SDK's `g_kEventManager` (if accessible) or a global `Subscribe` callback path must be discovered. If the logger can't subscribe globally, an alternative is to wrap the hit-effect spawning functions that fire on hit (`HitEffect`-creating helpers in `Tactical/Projectiles/*.py` Initialize blocks). This is a lower-fidelity fallback because not all hits route through script-side effect creation.
- Recording every hit produces a small log; no session-length cap needed.

## 7. Non-goals

- **Manual targeting mouse-pointer mode.** Out of scope for this spec. The model is designed so that adding manual targeting later is a UI / aim-computation change with no attribution change.
- **Weapon-type-specific falloff curves.** Linear for everything in v1. Quadratic / gaussian curves are a tuning escape hatch revisited only if linear feels wrong in playtest.
- **Armour, ablative layers, multi-hit cumulative effects.** Stock BC doesn't model these; out of scope.
- **Friendly fire / multi-victim splash.** A single torpedo damaging two ships at once is out of scope. If profiling shows this is a real BC behaviour, revisit; current SDK call sites suggest one hit = one victim.
- **Determinism guarantees across save/load.** The model is functionally pure given the inputs; save state is unchanged (still just `_condition` per subsystem).

## 8. Parking lot

- **Body-frame transform helper.** §4 references `MultMatrixLeft_world_from_body` shorthand. The implementation should factor out the body→world transform alongside the shield-face-mapping helper from Project 3; both want it.
- **Iteration cost at 60 Hz.** Galaxy has ~20 subsystems; iterating all candidates per hit is fine. If a future engagement involves dozens of ships each taking continuous phaser ticks, consider a per-ship bounding sphere early-out (skip subsystem iteration if `|P − ship_pos| > ship_bound + R_hit_max`).
- **Hit position smoothing for phasers.** Continuous phaser ticks against a manoeuvring target may produce a sawtooth pattern across subsystems frame-to-frame. Stock BC presumably smooths this; investigate after v1 if jitter is visible in playtest.
- **Damage VFX consumer.** The eventual persistent-hull-damage spec (the original topic of the brainstorm that birthed this one) consumes the per-hit `(P, N, post_shield_damage)` record. That spec is parked pending this one landing.

## 9. Open questions

- **Q1 — exact combination logic for `Weapon.GetDamageRadiusFactor()`.** Answered by §6 verification via direct observation of `WeaponHitEvent.GetRadius()`.
- **Q2 — is `WeaponHitEvent.GetWorldHitPoint()` mesh-accurate in stock BC, or bounding-sphere-approximated?** Cross-check step in §6.4. Affects VFX consumers downstream but does not change this spec's resolver.
- **Q3 — does stock BC apply hull damage to subsystem-aggregator parents differently from leaf subsystems?** Out of scope here; covered by the propagation spec's aggregation rules.
- **Q4 — `WeaponHitEvent` subscription mechanism in the live game.** §6.1 assumes a global event subscription is reachable from snippet code. If not, the fallback in §6.4 (wrapping projectile `Initialize` hit-effect helpers) loses fidelity for phaser hits. Validating subscription access is a prerequisite for the instrumentation work.

## 10. Workflow

This spec is the contract. The implementation plan comes next (writing-plans skill). Expected work units:

1. Replace `pick_target_subsystem` with the §4 resolver in `engine/appc/combat.py`.
2. Add a `weapon_splash_radius(hardpoint_weapon, payload_template)` helper.
3. Update unit tests in `tests/unit/test_combat.py` to exercise the splash distribution (currently they assert winner-takes-all behaviour).
4. Add integration test: fire phaser at Galaxy, assert SensorArray, WarpCore, and Hull all take damage when hit lands within their combined spheres; assert no damage to subsystems outside the splash.
5. Update or supersede [`2026-06-01-subsystem-damage-propagation-design.md`](./2026-06-01-subsystem-damage-propagation-design.md) attribution sections; retain its parent-aggregation rules.
6. Author `tools/attribution_logger.py` (sibling of `appc_logger.py`) implementing §6. Run scenarios in QuickBattle when the live game is reachable; record findings in a verification report committed to `docs/project/verification/`.

The instrumentation work (item 6) is independent of items 1-5 and can be scheduled separately. Items 1-5 are the unblocking work for combat-damage-pipeline Projects 2+4.
