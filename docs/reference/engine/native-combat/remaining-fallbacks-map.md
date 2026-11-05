> **Superseded for K1 (2026-11-03, fire control native only):** §1.1's K1 reasons and ASKs, §1.5's K1 guards, §3.1, §3.2, §3.4 and §5.4 describe hand-backs to a Python fire-control copy that is now deleted. A former K1 hand-back is a counted no-fire (`k1_no_fire`). The Manual Aim slot and `no_mount` asks are gone: a non-mount aim point is a plain body-frame point (M5). The K2, K3 and K4 rows are unchanged by that phase. See `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md` §6.

> **§3.1-3.6 implemented 2026-11-01** on branch `ws/combat-round-trips` (tip `3b113928d`, final fixes `b0652db1a`). Outcome, measurements and rulings: `docs/superpowers/specs/2026-11-01-native-combat-round-trips-design.md` §10. Rows marked **Done (round trips)** were updated then; everything else is the pre-build snapshot.

> Snapshot map written 2026-11-01 on branch `ws/combat-posed-parts` (HEAD `10b78fec1`, with Task 7's picked-spot torpedo work **uncommitted in the same tree**: `engine/appc/projectiles.py`, `native_combat.py`, `subsystems.py`, `projectile_geometry.*`, `torpedo_table.*`, `k3_projectiles.*`, `host_bindings.cc` were being edited while this was written). Line numbers are of that working tree; re-check one before relying on it. Input to roadmap workstreams **C** (close the routine fallbacks), **E** (retire the Python copies), **G** (event queue) and **I** (kernels off the lock) of `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md`. Model documents: `k1-fire-control-map.md`, `k2-beams-map.md`, `k3-k4-map.md`, `posed-parts-map.md`. Anything not read directly off the code or measured is marked **inferred**.

# Remaining fallbacks, ASKs and per-record hand-backs — code map

## 0. The headline

**The counted fallbacks are already closed in normal play.** In a 64-ship `combat_stress` fight run headless for 8,999 game ticks (150 s of game time, ~840 torpedoes and pulse bolts flown to a hit or expiry, ships dying), with the switch on and the audit off, every K1, K2 and K4 fallback reason and every K1, K2 and K4 ASK counted **zero**. The one non-zero K3 counter was `steer_point`/`unattributed`: 540, one per torpedo carrying an aim offset. Two more scenes agree (§2).

What still hands work to Python every tick is **not a fallback**. It is the record protocol itself:

| Record (kernel) | Per tick, 64 ships | Python cost, ms per tick (Debug, instrumented) | What it is |
|---|---|---|---|
| K1 `WALK_START` | **73.0** | **0.54** | Python is asked for the walk's aim offset object, scans for instance patches and pins the system, once per walked system |
| K1 `FIRE`, beam already firing | 18.3 | ~0.26 | the "effect" is three field writes; no sound, no event |
| K2 `CONTACT`, resting beam | 17.6 | ~0.25 | presentation only (`hit_feedback.beam_contact`) |
| K1 `BANK_STOP`, bank not firing | 3.45 | 0.02 | the "effect" is two or three field writes |
| K2 `SYSTEM_STOP`, offline system | 1.3 (0 → ~4 as ships die) | not timed | `WeaponSystem.StopFiring` re-run every tick |

The first three are 98-100% of their record kind (§2.3) and are pure data or presentation, so they can become write-log entries or a list returned with `DONE`. Doing that removes most of fire control's remaining Python and is also the precondition for workstream I. §3 ranks them.

**Done (round trips, 2026-11-01): none of the five rows above, nor K3's `unattributed`, comes back as a record of its own any more.** Walk starts are native, beam sustains and idle bank stops are logged writes, resting contacts ride the next record in a queue (their Python presentation still runs), and offline system stops are logged writes. Records fell 84-87% in the K1 differential and 85% in the K2 host differential. Measured, 64 ships, Debug: fire control 1.335 → 1.000 ms per tick (−25%), phasers flat (0.749 → 0.737), combat step 2.483 → 2.111 (−15%). That is ~0.37 ms per tick saved, against the ~1 ms inferred here (round-trips spec §10, SIG-166).

**Presentation queue (2026-11-02):** resting contacts no longer run Python mid-walk at all: they are queued natively and presented after the K2 step's `DONE`, 99.7% of them in C++ (shield splashes). `cb.phasers` 0.733 → 0.573 ms per tick (perf register SIG-172; spec `2026-11-02-combat-effect-queue-design.md` §10).

The SDK-contract records (sound, `ET_*` events, projectile spawn, damage) come to about **1.1 per tick** in this fight (§4).

---

## 1. Inventory: every remaining reason and ASK, by kernel

File abbreviations:

| Abbrev. | File |
|---|---|
| **NC** | `engine/appc/native_combat.py` |
| **HL** | `engine/host_loop.py` |
| **WS** | `engine/appc/weapon_subsystems.py` |
| **PR** | `engine/appc/projectiles.py` |
| **PS** | `engine/appc/part_severance.py` |
| **SHIPS** | `engine/appc/ships.py` |
| **HF** | `engine/appc/hit_feedback.py` |
| **K1C / K2C / K3C / K4C** | `native/src/combat/src/k{1_fire_control,2_beams,3_projectiles,4_eligibility}.cc` |
| **K1H / K2H / K3H / K4H** | the matching headers in `native/src/combat/include/dauntless/combat/` |
| **PG** | `native/src/combat/src/projectile_geometry.cc` (being edited by Task 7) |
| **WG / BG / SD** | `weapon_geometry.cc` / `beam_geometry.cc` / `sensor_detect.cc` |
| **SSC** | `native/src/combat/src/step_scan.cc` |
| **MIRC / MIRH** | `native/src/combat/src/mirror.cc` / `include/.../mirror.h` |
| **HB** | `native/src/host/host_bindings.cc` |

Classes: **(a) ROUTINE** fires in normal play. **(b) SCAFFOLDING** patch, override, guard or audit; it goes with the Python copy and is not ported. **(c) SDK-CONTRACT** a real call into SDK or engine Python that has to stay Python, but could move to a boundary. **(d) RARE/EDGE** exotic state. "Measured" is the 64-ship 8,999-tick run unless stated. Every zero below is zero in all three scenes of §2.

### 1.1 K1 fire control

**Whole system to Python (RUN_PYTHON, `k1_python_reasons`).** Pre-scan K1C:440-542, pump K1C:735-771, counted K1C:366-369.

| Reason | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `self_managed` | K1C:447 (prescan), K1C:761 (pump) | a held **tractor** system (`pump_self_managed`), or not a K1 system kind | (a) ROUTINE **where tractors are used**: tractors are out of K1 by design. This fight has none. | 0 |
| `overridden` | K1C:449, 514 | the system's or a child's class overrides a `_K1_SYSTEM_METHODS`/`_K1_LEAF_METHODS` name (NC:1027-1037), from the flag `_k1_overridden` NC:1070-1092 | (b) | 0 |
| `instance_patch` | NC:2597-2619 (`walk_start`), counted K1C:1228 (`skip_walk`) | an instance attribute shadows `update_weapons`/`try_fire_weapon` (NC:1040) or a leaf's `Fire`/`_fire_decide`/`_fire_effect`/`CanFire` (NC:1041) | (b) | 0 |
| `posed_ship`, `posed_target` | — (K1H:140-141) | retired by posed parts, never counted | — | 0 |
| `part_stale` | K1C:528 | a posed ship's leaf part slot is not current at the pre-scan | (d): the slots are re-resolved at every step boundary (NC:2881, 2905) | 0 |
| `mount_unknown`, `no_mount`, `offset_off_mount` | never in RUN_PYTHON (comment NC:206-210) | — | — | 0 |
| `stub_or_unplaced` | K1C:460-471, 490-492 | no real `IsDead`, or an invalid transform, on the ship, the pump ship, the held target or a list entry | (d) | 0 |
| `pulse_ship_target` | K1C:496 | a pulse system with no live target-list entry (Python would fall back to `ship.GetTarget()`, which is not mirrored) | (d) **inferred**: could follow a kill before the AI stops firing; 0 even with deaths | 0 |
| `pulse_module` | K1C:531 | a pulse leaf whose script did not resolve, or a power setting outside 0-2 | (d) | 0 |
| `ammo_row` | K1C:539 | a torpedo ammo slot names no live Ammo row | (d) | 0 |
| `stale_row` | K1C:443, 456, 459, 464, 469, 481, 490, 502, 512, 519, 522, 750 | an unnamed (-2) or freed row the walk reads | (d) | 0 |
| `unslotted_ship` | K1C:737 | a pump ship with no Object row | (d) | 0 |
| `gate` | K1C:770 | `pump_stops` threw (K1C:571-597: offline test, `can_detect`, range) | (d) | 0 |
| `other` | K1C:505, 513, 515, 517 | structure: a negative chain group, a child of another kind, ship or parent | (d) | 0 |

**ASKs (`k1_asks`; Python answers in `_k1_answer` NC:2736-2787).** K1 counts only the total and, for `fire`, the reason (K1C:1047-1050).

| ASK | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `fire` / `part_stale` | K1C:1039-1052 via WG:85, 103, 253, 267 | a slot went stale mid-walk (an effect's handler bumped the part-map generation) | (d) | 0 |
| `fire` / `mount_unknown` | WG:306-307 | a posed target's stored offset hits a mount-order entry the mirror cannot name | (d) | 0 |
| `fire` / `no_mount` | WG:243-252 via `_resolve_torpedo_aim_point` WG:288-315 (and the pulse lead, WG:353) | a tube or cannon aims at a **posed** target with an offset that is no authored mount, and the firing ship's Manual Aim slot does not hold it (Python's box rule, ruling C4) | (a) ROUTINE-RARE, posed + picked spots only (§5.4) | 0 here; **4-22 per 660-tick run** in the posed differentials (`.superpowers/sdd/2026-11-01-native-combat-posed-parts/task-5-report.md:99`) |
| `fire` / `offset_off_mount` | WG:262-263 | a posed target's offset is within 1e-5 of a mount but not bit-equal | (d) | 0 |
| `fire` / `other` | K1C:656, 663, 668 (pulse module unresolved, cannon `_target` unnamed, `ship.GetTarget()` fallback), any other `decide` throw | (d) | 0 |
| `can_fire` | K1C:1018 | the native `can_fire` threw (`fire_gates.cc:31` fall-backs: an unnamed ref) | (d) | 0 |
| `retry` | K1C:1096 | a target-list entry in the retry loop has no row or no real `IsDead` | (d) | 0 |
| `is_dead` | K1C:1117 | `ship_dead` threw on a retry entry | (d) | 0 |
| `is_member` | K1C:895 | the weapon's Property row is gone | (d) | 0 |
| `is_dumb` | K1C:938 | an effect's handler dropped the weapon's row | (d) | 0 |
| `group_step` | K1C:885 | a handler swapped the system's children (a child is no named leaf) | (d) | 0 |
| `reseed` | K1C:602 | single-fire bookkeeping with an unnamed child | (d) | 0 |

**Per-walk and per-effect records (not reasons, but each one is a Python round trip).** Python handling is in `run_k1` NC:2790-2869.

| Record | Emitted at | Python | Class | Measured per tick |
|---|---|---|---|---|
| `WALK_START` | K1C:816 | `walk_start` patch scan NC:2597-2619, `walked._live_held_offset()` WS:1551-1564, `combat_k1_set_offset` (NC:2828-2844) | (a) ROUTINE (§3.1); the patch scan inside it is (b). **Done (round trips):** no record. The kernel computes the offset; the driver fetches the object when Python first reaches the walk (`_K1Walk.materialise`). A WALK_START comes back only when the bindings' walk check hands the walk back (an instance patch, a non-stock ship class, an instance dict not yet built) | **73.0** → ~0 (`k1_logged.walk_start`) |
| `FIRE`, beam, `was_firing` True | K1C:1055-1059 | `bank._fire_effect` NC:2824-2827 → WS:888-903: `_firing = True; _target = target; _target_offset = offset`, nothing else | (a) ROUTINE (§3.2). **Done (round trips):** three logged writes, no record (`k1_logged.beam_sustain`) | **18.3** → 0 |
| `FIRE`, beam edge | same | WS:2672-2681: also `_play_fire_sfx` (WS:1002) and `ET_WEAPON_FIRED` (WS:699-715) | (c) | 0.12 |
| `FIRE`, tube | same | WS:3411-3441: stamps, `_spawn_torpedo` (WS:3503, runs the projectile script), `ET_TORPEDO_FIRED`, `ET_WEAPON_FIRED`, player-only `ET_TORPEDO_AMMO_CONSUMED` | (c) | 0.05 |
| `FIRE`, pulse | same | WS:2937-2956: `_spawn_projectile` (script), damage scale, charge drain, cooldown | (c) | 0.04 |
| `FIRE_FAILED` | K1C:1063 | `_broadcast_weapon_fire_failed` WS:3451-3480 (`ET_WEAPON_FIRE_FAILED` = `ET_CANT_FIRE`) | (c) | 0.35 (all tubes) |
| `BANK_STOP`, bank not firing | K1C:1024, 1031 | `StopFiring`: WS:905-911 (energy: `_firing`, `_beam_on_countdown`), WS:1191-1192 (tube), WS:2971-2975 (pulse) | (a) ROUTINE (§3.4). **Done (round trips):** the class's StopFiring writes, logged; a FIRING bank keeps the record (loop sound) (`k1_logged.idle_bank_stop`) | **3.45** (100% idle) → 0 |
| `STOP_SYSTEM` | K1C:773 | `WeaponSystem.StopFiring` WS:1540-1549 | (a)/(c) | ~0 (4 in total) |
| `FIRE_DUMB` | K1C:940, 948 | `FireDumb` (spawn) | (c) | 0 |
| `DONE` | K1C:731, 990 | session end | — | 2.27 (1 pump + 1.27 StartFiring sessions) |

### 1.2 K2 phaser beams

**Whole step to Python (`k2_python_step_reasons`, `_k2_step_fallback` NC:3579-3594, `k2_phasers` NC:3607-3633).**

| Reason | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `nested` | NC:3582 | no snapshot yet, or a K2 session already open | (d) | 0 |
| `instances` | NC:3585 | `ship_instances` is not a `TrackedInstances` | (b) (tests and tools) | 0 |
| `patched` | NC:3587, 3615 | a function or class K2 stands in for differs from its snapshot, or a never-seen class flagged "whole" (`_k2_python_ship` NC:3248-3296) | (b) | 0 |
| `audit` | NC:3592 | `DAUNTLESS_NATIVE_AUDIT=1` | (b) | 0 |

**Whole ship to Python (RUN_PYTHON, `k2_python_reasons`).** Ship prescan K2C:322-345, child K2C:352-378, loop K2C:424-447.

| Reason | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `unslotted_ship` | K2C:424 | the ship has no Object row | (d) | 0 |
| `overridden` | K2C:426, 439; child K2C:356 | a listed `python_ships` entry (an instance patch, an override, **or a class K2 has not seen**: `_k2_unseen` NC:3233-3245), or a system or bank `k1_overridden` | (b) | 0 |
| `not_ship_class` | K2C:326, 428 | not a ShipClass | (d) | 0 |
| `posed_ship` | — | retired | — | 0 |
| `part_stale` | K2C:343, 368 | a posed bank mount or posed lock mount slot not current | (d) | 0 |
| `stale_row` | K2C:325, 328-329, 354, 360, 372, 374, 436 | unnamed or freed row | (d) | 0 |
| `stub_or_unplaced` | K2C:327, 373 | invalid transform | (d) | 0 |
| `gate` | K2C:447 | the offline test threw | (d) | 0 |
| `other` | K2C:288-289, 355, 358, 438 | structure, or an unexpected throw before the ship's first record | (d) | 0 |

A bank that fails after its ship has a record becomes ASK `bank_step` (K2C:278-283).

**ASKs (`k2_ask_queries`; Python answers in `_k2_answer` NC:3486-3530).**

| ASK | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `is_dead` | K2C:501 (idle bank), K2C:521 (firing bank) | `ship_dead` threw: the bank's target row has no real `IsDead` (a non-ship object) | (d) | 0 |
| `can_detect` | K2C:553 | native `can_detect` threw (SD:65-120: unnamed refs, no transform; SD:172 non-ShipClass parent; SD:498-501 unresolved set frame; SD:527 a plain `Nebula` in `jammed`). Stock SDK scripts make only `MetaNebula`s (`MetaNebula_Create` in 5 files, `Nebula_Create` in none) | (d) | 0 (`fallbacks` 0 of 795,573 dispatched sensor queries too) |
| `aim_point` | K2C:598 | `phaser_aim_point` threw (BG:56 non-ShipClass firer; BG:69 `mount_unknown` under Manual Aim at a posed target; BG:78 unnamed lock; WG:252 `no_mount` with no Manual Aim slot) | (d), posed + Manual Aim edge | 0 |
| `shields_block` | K2C:723 | BG:186-202: target not a ShipClass with a real `GetShields`, unnamed shield or cloak subsystem | (d) | 0 |
| `bubble` | K2C:745, 751 | target not a ShipClass, or a zero semi-axis (BG:231) | (d) | 0 |
| `resolve_hit` | K2C:680 (no view offset for the target's set), K2C:696 (native trace threw) | a target with a render instance in a set other than the viewing set (`view_offsets` holds only `frames.viewing_set()`, NC:3420-3430), or a trace throw | (d) **inferred**: needs a multi-set scene with instances outside the viewed set | 0 |
| `bank_step` | K2C:281 | a later bank of an already-recorded ship fails `ship_why`/`child_why` | (d) | 0 |

**Per-bank records.** Python handling is in `run_k2` NC:3533-3576.

| Record | Emitted at | Python | Class | Measured per tick |
|---|---|---|---|---|
| `CONTACT`, resting (`flush_dwell <= 0`) | K2C:402 | `_k2_contact` NC:3464-3483 → `_phaser_contact` HL:1211-1232 → `hit_feedback.beam_contact` HF:564-615: `host_io.shield_hit` or `_hull_impact_visual` HF:502-561 (`hit_vfx.spawn`). No damage, no event, no RNG read | (a) ROUTINE, presentation (§3.3). **Done (round trips, level i):** no record of its own; queued in walk order onto the next record that runs Python (or DONE) and run before that record's effect (`k2_batched_contacts`). Its Python presentation still runs, so `cb.phasers` did not drop | **17.6** (97.6%) → 0 records |
| `CONTACT`, damage pulse | K2C:402 | HL:1233-1256 → `combat.apply_hit` (damage, `ET_WEAPON_HIT`, death cascade) | (c) / workstream D | 0.41 |
| `SYSTEM_STOP` | K2C:450 | `WeaponSystem.StopFiring` WS:1540-1549, **every tick** for an offline or off system (comment K2C:441-442) | (a) ROUTINE (§3.5). **Done (round trips):** when every bank is idle, the system's five writes and each bank's, logged, still every tick and still waking; a firing bank keeps the record (`k2_logged_system_stop`) | 1.30 on average: 0 until ~tick 5,000, ~4 by tick 9,000 (dead ships, **inferred**) → ~0 records |
| `BANK_STOP` | K2C:516, 524, 538, 556, 562, 575, 646 | `bank.StopFiring()`. All 402 timed ones were **firing** banks, so they stop the loop sound | (c) | 0.08 |

### 1.3 K3 torpedoes

**Whole step to Python (`k3_python_reasons`).** Python side `_k3_fallback` NC:4050-4080. Kernel `begin` K3C:819-875.

| Reason | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `off` | NC:4054 | switch off | — | 0 |
| `audit` | NC:4057 | audit on | (b) | 0 |
| `patched` | NC:4060, 4070 | snapshot missing, or a `_K3_FUNCTIONS` entry changed (NC:3936-3956) | (b) | 0 |
| `plain_active` | NC:4062 | `projectiles._active` is not the tracked `_ActiveList` | (b) | 0 |
| `instances` | NC:4065 | `ship_instances` not a `TrackedInstances` | (b) | 0 |
| `scan` | NC:4068; K3C:833-835 | no representable step scan for this `ships_list`, or a stale scan serial (step-scan reasons §1.4) | (b) or (d), whichever scan reason caused it | 0 |
| `row` | NC:4077 | a torpedo listed twice in `_active` | (d) | 0 |
| `guard` | NC:4079 (`_k3_classes_ok` NC:4026-4045) | a torpedo or seen ship class resolves a stood-in name differently | (b) | 0 |
| `table` | K3C:838-840 | the torpedo table's size differs from `len(_active)` | (d) | 0 |
| `unrepresentable` | K3C:844 | a torpedo row holds an unencodable field | (d) | 0 |
| `stale_ref` | K3C:845-848 | `_target_ship`, `_source_ship`, `_containing_set` or `_mount_key` names a row that was **dropped** (MIRC:974-977 reads -2: the torpedo holds its referent strongly, so the object lives but took the Python path) | (d), §5.2 | 0 |
| `torpedo_xform` | K3C:850 | a torpedo's transform slot is invalid | (d) | 0 |
| `ship_cache` | K3C:857-874 | step 0's ship cache threw (`ship_dead`, `world_location`, `bubble_bound_radius`) | (d) | 0 |

**ASKs (`k3_asks`; Python answers in `_k3_answer` NC:4181-4217).**

| ASK / why | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `steer_point` / `unattributed` | PG:333-334 → K3C:310-313 | the torpedo's `_mount_key` is not attributed for this target and offset. Python's `_steer_point` (PR:1130-1136) scans `authored_mount_subsystem` (PS:506-518) **once per (torpedo, target, offset)** and writes `_mount_key` | (a) ROUTINE (§3.6). **Done (round trips):** attributed natively with `authored_mount_subsystem`; `_mount_key` written quietly at DONE (`k3_native_attributions`). `kMountUnknown` or a non-ShipClass target keeps the ASK | **540** (0.06 per tick); Felix 19; 16-ship 6 → 0 in every differential |
| `steer_point` / `unbaked` | PG:354-358 | a picked spot whose `_baked_offset` is not for this target and offset (Task 7: Python bakes it) | (a) ROUTINE-RARE (re-targets) | 0 |
| `steer_point` / `mount_unrepresentable` | PG:335-337 | `_mount_key` names a dropped Subsystem row | (d) | 0 |
| `steer_point` / `mount_stale`, `offset_off_mount` | PG:345-348 | a posed target whose attributed mount row is gone, or whose offset is not the mount's own point | (d) | 0 |
| `steer_point` / `part_stale`, `no_mount`, `geometry` | PG:365-372 | a stale slot, NoMount (no longer reached since Task 7, PG header), or another geometry throw | (d) | 0 |
| `steer_point` / `posed_target` | — | retired | — | 0 |
| `guide` / `target_not_in_scan`, `source_not_in_scan` | K3C:285-288 | the target or source is not in this step's `ships_list` (HL:2562-2572: every ShipClass in every set), so its class was never scanned | (b) (§5.3) | 0 |
| `guide` / need_guide reasons | PG:243-244 (unrepresentable torpedo field, `_target_ship` -2), PG:257, 287 (unrepresentable set), PG:261 (target without a real `IsDead`), PG:269 (torpedo transform), PG:277 (`_source_ship` -2), PG:285 (source or target frame missing), PG:307 (`can_detect` threw) | (d) | 0 |
| `frame` | K3C:299 (via PG:255), K3C:356 (broadphase) | a set with no frame-table entry this step | (d) **inferred**: the step scan frames every ship's and torpedo's set first (NC:3724-3728) | 0 |
| `shields_block` | K3C:693 | as K2 | (d) | 0 |
| `bubble` | K3C:715 | as K2 | (d) | 0 |
| `resolve_hit` | K3C:445 (no view offset), K3C:459 (throw) | as K2 | (d) | 0 |

**DONE's effects** (NC:4135-4157): the write log (`_k3_apply` NC:4160-4178) is data. Then, per expired torpedo, `expire(t)` PR:595-607: `RemoveObjectFromSet` and `ET_TORPEDO_EXITED_SET` (PR:589) (c). Hits are returned and applied by `combat.apply_hit` at HL:1332-1341 (c / D). Measured: 0.077 hits and 0.016 TTL expiries per tick.

### 1.4 K4 eligibility and the shared step scan

**Python side** (`k4_update` NC:3861-3906; `step_scan` NC:3707-3748):

| Reason | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `audit` | NC:3866 | audit | (b) | 0 |
| `patched` | NC:3868; NC:3732 (scan) | a `_K4_FUNCTIONS` entry or a K2-watched class changed | (b) | 0 |
| `unsnapped` | NC:3730 | K2's role snapshot not taken yet | (b) | 0 |
| `ships` | NC:3871 | `ships_list` is not a list or tuple (the host always passes a list, HL:1309) | (d) | 0 |
| `player` | NC:3884 | the player has no row, a class K2 never saw, or an instance patch | (b)/(d) | 0 |
| `frame` | NC:3741, 3886 | `frames.frame_of` raised | (d) | 0 |
| `max_count`, `weights` | NC:3891, 3897 | `select_eligible`'s default or a weight is not a plain number | (b) | 0 |

**Scan reasons** (binding HB:3750-3790, rows SSC:41-81): `no_row` HB:3761, 3767 (d); `unseen` HB:3776 (b); `instance_patch` HB:3785 (b); `stale` SSC:62 (d); `is_dead` SSC:63 (b: no real `IsDead`); `not_ship` SSC:64 (d); `set` SSC:67 (d); `duplicate` SSC:75 (d). **Kernel reasons** K4C:66-132: `scan` K4C:66, 86, 98; `player` K4C:75; `nonfinite` K4C:76, 87, 99, 132; `frame` K4C:124; `set` K4C:127. All (d). **All measured 0**: K4 decided all 8,999 ticks.

### 1.5 Per-step Python guards (SCAFFOLDING, not reasons)

These run every tick whatever happens and go away with the Python copies (mod policy). Measured cost per tick (§2.4): `_k2_ship_handles` 0.034 ms (NC:3298-3316), `_k2_step_fallback` 0.015, `_k1_recheck_overrides` 0.011 (NC:1095-1127; also once per StartFiring session), `_k3_fallback` 0.007, the guard part of `step_scan` (`_k2_classes_unchanged` plus the binding's class and instance checks; the frame table is real work) ≤0.047, the guards inside `k4_update` ≤0.009. Together about **0.12 ms per tick**.

`resolve_stale_part_slots` (NC:1413-1429) is not scaffolding. It is how part slots stay current: an O(ships) Python sweep at each boundary (`k1_pump` NC:2881, `k1_system` NC:2905, `k2_phasers` NC:3623, `step_scan` NC:3719). Measured 4.2 calls and 0.027 ms per tick.

---

## 2. Measured frequencies

### 2.1 Method

Headless host loop (`engine.host_loop.run`, `OPEN_STBC_HOST_HEADLESS=1`) under pytest with the root conftest loaded as a plugin (`uv run pytest -p tests.conftest --rootdir=. -c pyproject.toml <scratch test>`). The pattern is `tests/host/test_native_combat_scene_audit.py::_run` with the audit off: `DAUNTLESS_NATIVE_COMBAT=1`, `_frame_clock` stepped 0.05 s (3 ticks per frame), `seed_every_rng(5)`, `native_combat.reset()` first, `DAUNTLESS_MODS_DIR` empty. The scratch test wrapped `_h.combat_k{1,2,3}_next` to count records by kind and ASK query, wrapped `GameLoop.tick` to snapshot `counts()` every 300 ticks, and wrapped the kernel entry points. A second pass timed Python handling between records with `perf_counter`. A third classified records against the live objects (beam `was_firing`, bank `_firing` before StopFiring, contact `flush_dwell`). Scratch scripts are not in the repo. Build: `build/` **Debug**, binaries dated 19:14 (may predate part of Task 7's uncommitted edits). The machine was shared, so the timings are indicative.

| Run | Scene | Ticks | Wall |
|---|---|---|---|
| R1 (counts) | `combat_stress`, 64 AI ships + player | 8,999 | 180 s |
| R2 (timing) | same, seed 5 | 4,499 | 87 s |
| R3 (classes) | same, seed 5 | 4,499 | 88 s |
| R4 | `felix_destroy` (player BoP + 4 AI BoPs vs Sovereign, Felix's Destroy order), no kill inside the window | 7,199 | 36 s |
| R5 | `combat_stress`, 16 ships, 6 ticks per frame, 120 frames: **SIG-160's exact setup** | 720 | 8 s |

### 2.2 Counters (`native_combat.counts()`, non-zero only)

| Counter | R1 64 ships / 8,999 ticks | R4 Felix / 7,199 | R5 16 ships / 720 |
|---|---|---|---|
| `k1_records` | 878,593 | 58,549 | 11,303 |
| `k1_python_systems`, `k1_asks`, every `k1_python_reasons`, every `k1_fire_ask_reasons` | **0** | **0** | **0** |
| `k1_posed.walks` | 937 (all before tick 900) | 433 | **222** |
| `k2_records` | 183,745 | 10,810 | 2,613 |
| `k2_python_ships`, `k2_asks`, `k2_python_steps`, every reason and query | **0** | **0** | **0** |
| `k2_posed.lock_aims` | 408 | 0 | — |
| `k3_runs` / `k3_records` | 8,559 / 9,099 | 6,642 / 6,661 | 226 / 232 |
| `k3_python_steps`, every K3 begin and Python reason, `guide` | **0** | **0** | **0** |
| `k3_asks.steer_point` (all `unattributed`) | **540** | 19 | 6 |
| `k4_runs` / every K4 reason | 8,999 / **0** | 7,199 / **0** | 720 / **0** |
| `native_calls` / `fallbacks` | 795,573 / 0 | 53,995 / 0 | 7,947 / 0 |

### 2.3 Records by kind (R1) and by class (R3)

| Record | R1 total | R1 per tick | R3 class split (4,499 ticks) |
|---|---|---|---|
| K1 `WALK_START` | 657,337 | 73.0 | 322,692 held offset, 0 Manual Aim; every one carried a write (the pruned `_target_list`) |
| K1 `FIRE` | 166,510 | 18.5 | beam sustain 78,303 (**98.8%**), beam edge 557, tube 245, pulse 166 |
| K1 `BANK_STOP` | 31,086 | 3.45 | **100% idle**: phaser 4,353, tube 5,707, pulse 738 |
| K1 `FIRE_FAILED` | 3,188 | 0.35 | all tubes |
| K1 `DONE` | 20,468 | 2.27 | 8,999 pumps + 11,469 StartFiring sessions |
| K1 `STOP_SYSTEM` | 4 | 0 | — |
| K2 `CONTACT` | 162,349 | 18.0 | resting 75,484 (**97.6%**), damage pulse 1,840; trace tiers in R1: mesh 106,030, sphere 47,968, fallback 8,351 |
| K2 `SYSTEM_STOP` | 11,671 | 1.30 | none before tick ~5,000 |
| K2 `BANK_STOP` | 726 | 0.08 | all 402 in R3 were firing banks |
| K3 `steer_point` ASK | 540 | 0.06 | `unattributed` |
| K3 hits / TTL expiries | 689 / 148 | 0.077 / 0.016 | — |

Over time (R1 cumulative): `WALK_START` 42,271 by tick 900, 323,081 by 4,500, 597,514 by 8,100. `SYSTEM_STOP` 0 by 4,500, 249 by 5,400, 6,271 by 8,100. K3 `steer_point` 32 by 900, 484 by 8,100. So the rates hold steady through the fight, except `SYSTEM_STOP`, which climbs as ships die.

### 2.4 Python cost per record (R2, Debug, instrumented)

The "Python" column is the time from a record's return to the next `next()`/`end()` call. It covers `apply_writes`, the effect, re-pinning, the context re-send and the wrapper's own counting (~1 µs).

| Record | n | µs per record | ms per tick |
|---|---|---|---|
| K1 `WALK_START` | 322,692 | 7.47 | **0.536** |
| K2 `CONTACT` | 77,324 | 15.18 | 0.261 |
| K1 `FIRE` | 79,271 | 14.81 | 0.261 |
| K1 `BANK_STOP` | 10,798 | 6.53 | 0.016 |
| K1 `DONE` | 10,055 | 4.48 | 0.010 |
| K3 `steer_point` ASK | 245 | 45.0 | 0.002 |
| K1 `FIRE_FAILED` | 1,554 | 4.75 | 0.002 |

Time inside the kernels' `next()`, per tick: K1 0.548 ms, K2 0.431, K3 0.035. Entry points per tick: `k1_pump` 1.307 ms, `k2_phasers` 0.771, `run_k3` 0.130, `k1_system` 0.116 (5,556 calls, 94 µs each, inside `gl.ai`), `k4_update` 0.009. `apply_writes` was called 485,915 times at 2.56 µs (0.277 ms per tick); that time is inside the record rows above.

**Reading (derived):** of fire control's 1.31 ms per tick, the kernel is 0.55 ms and `WALK_START` handling is 0.54 ms. Beam-sustain FIREs are most of the remaining 0.26 ms. Of `cb.phasers`' 0.77 ms, resting contacts are ~0.25 ms.

---

## 3. ROUTINE items, ranked by measured frequency × cost

| Rank | Item | Per tick | ms per tick (R2) | Native data needed | Design (§) |
|---|---|---|---|---|---|
| 1 | K1 `WALK_START` offset hand-back | 73.0 | 0.54 | none new | 3.1 |
| 2 | K1 `FIRE` beam sustain | 18.3 | ~0.26 | none new | 3.2 |
| 3 | K2 resting `CONTACT` | 17.6 | ~0.25 | none new (a native port needs the hit-VFX inputs) | 3.3 |
| 4 | K1 `BANK_STOP` on an idle bank | 3.45 | 0.016-0.023 | none new | 3.4 |
| 5 | K2 `SYSTEM_STOP` on an offline system, every tick | 1.3 → 4 | not timed (~0.01-0.04 **inferred**) | none new | 3.5 |
| 6 | Boundary part-slot sweep `resolve_stale_part_slots` | 4.2 calls | 0.027 | — | stays Python until the box rule and slots are native (§5.4) |
| 7 | K3 `steer_point` `unattributed` (one per torpedo) | 0.06 | 0.003 | none new | 3.6 |
| 8 | K1 `fire` ASK `no_mount` (posed target, picked or stale offset) | 0 here; ≤0.03 in the posed differentials | negligible | per-leaf part boxes | 5.4 |
| 9 | K1 `self_managed` (held tractors) | 0 here | scene-dependent | the tractor model | out of K1 by design |
| 10 | K3 `steer_point` `unbaked` (picked spot re-targeted) | 0 here | negligible | none for unposed targets | 3.6 |

**Items 1-5 and 7 are done (round trips, 2026-11-01; per-section results below).** Items 1-5 do not port any decision logic: the decision is already native. They change what the kernel hands back. Each one turns a Python call that is pure field writes (or presentation) into write-log entries, or into a list returned with `DONE`. The write log already exists for exactly this (K1H:30-35 for K1; K2H's `_dwell` log; K3's DONE log), as does a quiet-setter path that keeps passive-state wakes (`_quiet_setter` NC:2636-2670: a `NativeWrapped` field runs its passive base `__set__`, so a `WakeField` write still wakes). Ruling P1 ("no decision outlives a Python effect") is not at risk, because no Python runs between a write being logged and its record being applied.

### 3.1 K1 `WALK_START` → native offset, lazy object

**Python today** (NC:2828-2844): `walk.walk_start(walked)` scans the system's and children's `__dict__` for `_K1_SYSTEM_PATCHES`/`_K1_LEAF_PATCHES` (NC:2597-2619, **scaffolding**). Then `walk.offset = walked._live_held_offset()` (WS:1551-1564): `ship = self.GetParentShip()`; `probe = getattr(type(ship), "is_using_target_offset", None)`; if `callable(probe) and ship.is_using_target_offset()` (SHIPS:1797-1798: `bool(self._use_target_offset and self._manual_target_offset is not None)`), it returns `ship.GetTargetOffsetTG()` (SHIPS:1760-1775, a fresh copy of the manual offset); else `getattr(self, "_held_offset", None)`. The value goes to `combat_k1_set_offset` (`None` unless a `TGPoint3`). Finally `pin_system`. Every `WALK_START` also carries the pruned `_target_list` write (K1C:808-812), which `apply_writes` maps handle by handle.

**Native data:** all of it is already mirrored. On the ObjectRow: `is_ship_class`, `_use_target_offset`, `_manual_target_offset` + `manual_offset_set` (MIRH:156-158). On the SubsystemRow: `_held_offset` + `held_offset_set` (MIRH:193-194). The pushing sites are already the descriptors: `ShipClass._use_target_offset` NativeField(bool) SHIPS:38, `_manual_target_offset` NativeField(OFFSET) SHIPS:39, `WeaponSystem._held_offset` NativeField(OFFSET) WS:1280. The OFFSET type pushes "unset" for anything that is not a `TGPoint3`, which matches `set_offset`'s `None`. **No new push sites.** ~~While the Python copy exists, `_live_held_offset`, `is_using_target_offset` and `GetTargetOffsetTG` must join the K1 override guard (`_K1_SYSTEM_METHODS` NC:1032; a ShipClass-side flag for the latter two). Under the mod policy they then leave with it.~~ **Superseded by phase 6 Part A** (spec `2026-11-05-phase6-engine-stages-native-design.md` §3 "Mods and patches"): a patch of a method a Part A stage stands in for is no longer obeyed; see the table in `native-infra-patterns.md` ("What each kernel still honours") for what remains.

**Cheapest bit-exact design:**
1. The kernel computes the offset VALUE at UW_DEAD_PRUNE (K1C:794-816) from those rows, with the same predicate. A firing ship that is not a ShipClass row has no `is_using_target_offset` (the probe is `None`), so it reads the held offset.
2. No `WALK_START` record. The kernel tags the walk's first real record (FIRE, BANK_STOP, FIRE_FAILED, FIRE_DUMB, ASK, STOP) with the walked system. The driver then calls `walked._live_held_offset()` once, when that first record arrives, to get the **object** that ruling P5 needs for `_target_offset` writes and effects. This is equivalent because no Python runs between the walk's start and its first record. `_live_held_offset` only reads; for Manual Aim it returns a fresh copy either way. **Inferred**: confirm that no `__getattr__` stub sits on that path.
3. The pruned-list write stays in the log and is applied with the next record or at `DONE`. Bit-exact identity requires keeping the write on every walk, because Python's `_prune_targets` (WS:1427-1434) builds a NEW list each time. Logging it only when it changed would save more, but leaves the old list object in place, which `AddTarget`'s in-place append (WS:1425-1426) would then mutate. **Inferred** safe, but it is an identity change: keep the write unless a check of every `_target_list` alias says otherwise.
4. Pinning is needed only when a record follows, so pin lazily at that same first record.

Expected effect: 73 round trips per tick become ~2 (the walks that produce an effect), saving most of 0.54 ms per tick (**inferred** 0.35-0.45 ms, since the list writes remain). It is also the largest mid-step Python question left in K1 (workstream I).

**Done (round trips Task 1, `ac8c1df7e`).** As designed, with two changes. The patch scan (point 2) did NOT move to the first record: it stays at the walk start, made in C by the bindings' walk check (ruling F5), so a patched method is never decided natively; the check also covers the ship side (`is_using_target_offset`, `GetTargetOffsetTG` on the instance or a non-stock class). The object fetch happens at the walk's first record OR at the first logged write naming the walk's offset, whichever is first (ruling D5). No `__getattr__` stub sits on the path (tested). Measured with §3.2 and §3.4: fire control 1.335 → 1.000 ms per tick (SIG-166), less than this section's estimate plus §3.2's. ⚠️ The walk check makes CPython lookups inside `next()` (no bytecode, no GC-tracked allocation), so it is now the thing that keeps K1 on the lock (workstream I).

### 3.2 K1 `FIRE` for a beam already firing → three logged writes

**Python today:** `bank._fire_effect(target, walk.offset, decision)` (NC:2824-2827) → `PhaserBank._fire_effect` WS:2672-2681 → mixin WS:888-903. With `decision[0]` (was_firing) True, the only effect is `self._firing = True; self._target = target; self._target_offset = offset`, then `return True` (the `_weapon_did_fire` bookkeeping is the kernel's, K1C:1070-1072). There is no sound, no `ET_WEAPON_FIRED` (WS:2679-2680 posts only `if not decision[0]`) and no countdown.

**Native data:** `_firing` (a NativeWakeField, WS:742), `_target` (ref), `_target_offset` (OFFSET); all mirrored, and the kernel already logs `_target`/`_target_offset` writes for pulse cannons (`write_target`, `write_target_offset`, K1C:674-675) and supports the `walk_offset` marker. **No new fields.** `_fire_effect` is already in `_K1_LEAF_METHODS` (NC:1028), so an override still sends the system to Python while the copies exist.

**Design:** in `TF_FIRE` (K1C:1039-1069), when the decision is Beam with `was_firing` true, log the three writes in Python's order (`_firing`, `_target`, `_target_offset = walk_offset`) and go straight to `TF_FIRED`; emit no record. `apply_writes`' quiet setter runs the WakeField base for `_firing`, so a sleeping bank still wakes exactly as `self._firing = True` would. (A firing bank is never asleep, **inferred** from the passive-weapons rule.) The edge case (`was_firing` False) stays a FIRE record (§4). Saves ~0.25 ms per tick (**inferred** from 14.8 µs × 18.3 less the logged-write cost).

**Done (round trips Task 2, `ee4447310`).** As designed; the `_target_offset` write is the walk-offset marker, resolved to the walk's own object (ruling D5). Measured jointly with §3.1 and §3.4 (fire control −25%, SIG-166).

### 3.3 K2 resting `CONTACT` → a contact list, then presentation natively

**Python today:** `_k2_contact` (NC:3464-3483) rebuilds the points, reads `hl._phaser_level(sys_)`, and calls `_phaser_contact` (HL:1203-1232). With `flush_dwell <= 0` that is `hit_feedback.beam_contact` (HF:564-615): `shields_block` (passed in by K2 unless an ASK answered it), then `host_io.shield_hit(...)` or `_hull_impact_visual` (HF:502-561: `spark_params`, `host_io.world_to_body`, `hit_vfx.spawn`). Operand order: `tick_damage = _phaser_damage_for_tick(max_damage=bank.GetMaxDamage(), max_damage_distance=bank.GetMaxDamageDistance(), dist=dist, dt=dt) * PHASER_INTENSITY_SCALE[level]` (HL:1222-1226), used only for the spark threshold.

**Order sensitivity:** none for game state (read off the code: no damage, no event, no `random`). `hit_vfx.spawn` appends to a render-side list that `cb.vfx` ages (HL:1343-1347) **before** `cb.phasers` in the step, so spawning at the end of the step lands at the same point relative to the ageing.

**Design, two levels:**
- (i) *No port:* the kernel collects resting contacts into a list delivered with `DONE`, and the driver runs `beam_contact` for each after the walk. That keeps Python cost and saves only the round trips and context re-sends (`cx.resend()` NC:3574), roughly a third (**inferred**). It does make K2's walk free of per-contact Python (workstream I).
- (ii) *Port:* hand the list to a native presentation step: the shield flash (`host_io.shield_hit` arguments: iid, mesh-space anchor, intensity, `weapon_splash_radius`) and the hull flash/sparks (`spark_params`, the `world_to_body` the renderer already owns). New mirror data: the bank's `GetMaxDamage`/`GetMaxDamageDistance` (Property, **inferred** not yet mirrored for K2) and `weapon_splash_radius(bank, None)`'s inputs. Presentation, so "bit-exact" means the same VFX list, not game state.

**Done, level (i) only (round trips Task 3, `30462f621`, fix `f51a4f8e0`).** Not at `DONE`: the queue rides the NEXT record that runs Python, and the driver runs the queued contacts before that record's effect, so a damage pulse's `apply_hit` still follows every earlier resting contact's VFX (ruling E5). Measured: `cb.phasers` 0.749 → 0.737 ms per tick, flat. The round trips went, but the presentation Python, which was most of the cost, stays. **Level (ii) is the next lever** here.

### 3.4 K1 `BANK_STOP` on a bank that is not firing → logged writes

**Python today** (NC:2845-2846): `bank.StopFiring()`. Energy banks, WS:905-911: `was_firing = self._firing; self._firing = False; self._beam_on_countdown = 0.0`; the loop-sound stop runs only `if was_firing`. Tube, WS:1191-1192: `self._firing = False`. Pulse, WS:2971-2975: `_firing = False; _target = None; _target_offset = None`.

**Native data:** `_firing`, `_beam_on_countdown` (MIRH:220, NativeField WS:750), `_target`, `_target_offset`; all mirrored. **Design:** when the bank row's `_firing` is 0 (all 10,798 in R3), log the class's writes in its order instead of emitting the record; a firing bank keeps the record (sound). The WakeField `_firing` write still wakes a sleeper through the quiet setter. This is exactly what Python does: per `passive_state.WakeField` (`engine/appc/passive_state.py:59-69`), "every write (even of an equal value) wakes a sleeping owner". ~~`StopFiring` joins the K1 leaf override guard while the copies exist.~~ **Superseded by phase 6 Part A** (see the "What each kernel still honours" table in `native-infra-patterns.md`).

**Done (round trips Task 2, `ee4447310`).** As designed.

### 3.5 K2 `SYSTEM_STOP` on an offline system → logged writes

**Python today** (NC:3562-3563): `sys_.StopFiring()` = WS:1540-1549: `_fire_held = False; _held_target = None; _held_offset = None; _target_list = []; _last_group_fired = -1`, then `w.StopFiring()` for each `GetWeapon(i)`. K2 emits it every tick for a system that is offline or off (K2C:441-450). The growth from tick ~5,000 matches ships dying (**inferred**: a dead ship's systems read offline).

**Design:** once every bank is idle, the same as §3.4: the five system writes plus each bank's writes, logged in order (the K2 write log carries only `_dwell` today, K2H:311-315, so it needs the K1 value variant). Banks that are firing keep a record. All fields are mirrored. A further saving, skipping the stop when every value is already the target value, is **not** bit-exact: each write wakes, and `_target_list = []` replaces the list object.

**Done (round trips Task 3, `30462f621`).** As designed; K2's write log now carries K1's value variant. Still emitted every tick, still waking. K1's own pump `STOP_SYSTEM` (K1C:773, ~0 here) is still a record: a candidate for the same treatment.

### 3.6 K3 `steer_point` `unattributed` → native attribution

**Python today** (`_k3_answer` NC:4188-4191 → PR:1125-1144): when `key` is None, or `key[0] is not target`, or `key[1:4] != offset`, it computes `torpedo._mount_key = (target, x, y, z, authored_mount_subsystem(target, (x, y, z)))`. That is the first subsystem in `_mounted_subsystems` order whose mount is within `eps=1e-5` per axis, by `abs(mount[i] - point[i]) <= eps` (PS:506-518). Then the steer point.

**Native data:** the lookup is already native: `authored_mount_subsystem(m, target, offset)` (`part_pose.h:97-106`, used by K1 and K2 for posed targets). The mount order it needs is pushed for **every** ShipClass, posed or not (`push_mount_order` NC:1530-1543, from the `MountSlotField`/`NativeMountRefField` writes NC:708-730, NC:1897 and `ShipSubsystem.AddChildSubsystem` `subsystems.py:1175`). The torpedo row already holds `mount_attributed`/`mount_offset`/`mount_sub` (`set_torpedo_mount` MIRC:955-963). **No new push sites.**

**Design:** in PG's attribution check (PG:330-334), call `authored_mount_subsystem`. `kMountUnknown` keeps the ASK, and so does a non-ShipClass target (its mount order is never pushed: `part_pose.h:101-104`). Otherwise write the row's mount natively and add a `_mount_key` entry to `K3TorpWrite`, which `_k3_apply` (NC:4161-4178) turns into the tuple `(target_obj, x, y, z, mount_obj or None)`, quietly. The `unbaked` follow-up for a mount-less offset (PG:354-358) is natively the offset itself on an **unposed** target (Task 7 spec §10: "an unposed target's bake is the offset itself"). On a posed target it is the box rule (§5.4). Cost is tiny (0.003 ms per tick), but it is the only K3 question left in normal play, so closing it makes K3 data-in/data-out for workstream I.

**Done (round trips Task 4, `aad2afb12`).** As designed. Steer-point ASKs went to 0 in the K3 and posed differentials (73-178 per run before), each now counted in `k3_native_attributions`. Not separately measurable in the benchmark.

---

## 4. SDK-contract records in the per-tick path (input to workstream G)

All `ET_*` posting goes through `TGEventManager.AddEvent` (`engine/appc/events.py:802-845`), which **dispatches synchronously**: destination handlers unguarded, broadcast handlers log-and-continue. So a handler runs *inside* the K1/K2 walk, and the walk re-reads the mirror after it (ruling P1, K1H:24-28). That re-read is why every effect is its own record today. The engine's own note says BC itself appended to a FIFO queue (`docs/reference/engine/event-emitter-gaps.md:486-490`).

| Record | Per tick (R1/R3) | What it does | SDK consumers (stock scripts) | Deferrable to a boundary queue without changing order-sensitive outcomes? | Blocks |
|---|---|---|---|---|---|
| K1 FIRE beam **edge** | 0.12 | `_play_fire_sfx` (WS:1002), `ET_WEAPON_FIRED` src bank, dst ship (WS:699-715) | Instance handlers on the player or a ship: `E2M0.py:2087`, `E2M6.py:631`, `E6M2.py:790`, `E6M4.py:579`, `E6M5.py:646`; broadcast `E1M2.py:1139`, `E6M4.py:564` | **Not provably.** A handler may StopFiring, change AI or end the mission. Today the rest of the pump sees that at once; deferred, the remaining walks this tick would not. Likely closer to BC (FIFO, **inferred**) | parity with the Python differentials (golden fights would change); a ruling on intra-tick handler visibility |
| K1 FIRE **tube** | 0.05 | stamps (`_num_ready`, cooldowns, parent `_last_system_fire_time`), `_spawn_torpedo` (projectile script → F), `ET_TORPEDO_FIRED` (src torpedo), `ET_WEAPON_FIRED`, player `ET_TORPEDO_AMMO_CONSUMED` (WS:3411-3441). BC's audited order is TORPEDO_FIRED → WEAPON_FIRED → AMMO_CONSUMED (WS:3433-3436) | `Conditions/ConditionTorpsReady.py` (AI conditions, also `ET_TORPEDO_RELOAD`), `Maelstrom/Episode7/Episode7.py` | The stamps are data, so they can be logged writes. Spawning at the step's end is the same position for K3, which already ran this step (`cb.projectiles` HL:1322-1326 runs before `cb.held_weapons` HL:1379-1380, **inferred**). The events need their within-tick order kept and need the torpedo object to exist | the launch-script cache (F); a projectile created from C++ data; AI conditions reading tube state mid-tick |
| K1 FIRE **pulse** | 0.04 | `_spawn_projectile` (script), `_damage *= GetDamageScale()`, charge drain by `_shot_cost()`, cooldown (WS:2937-2956). No event | — | yes for the data (writes) and the spawn (as tube) | F |
| K1 FIRE_FAILED | 0.35 | `ET_WEAPON_FIRE_FAILED` (= `ET_CANT_FIRE`, 0x800037), dst tube (WS:3451-3480) | `Bridge/TacticalMenuHandlers.py:422`, `Bridge/TacticalCharacterHandlers.py:58` (`PlayerCantFire`: player UI) | yes, **inferred**: report-only UI feedback. For AI ships no stock handler reacts | nothing structural; G's ordering list |
| K1 BANK_STOP / STOP_SYSTEM, **firing** bank | ~0 in K1 | loop-sound `Stop()` (WS:909-911) | — | yes (sound) | — |
| K1 FIRE_DUMB | 0 | `FireDumb` spawn | as tube | as tube | F |
| K1 ASK `fire`/`retry`/`group_step`, RUN_PYTHON | 0 | the whole Python `Fire`/`try_fire_weapon`/`update_weapons`, effects inside | as above | no: they ARE Python decisions; they vanish when the Python copy goes | — |
| K2 CONTACT **damage pulse** | 0.41 | `combat.apply_hit` (HL:1249-1256): shields, hull, subsystems, `ET_WEAPON_HIT` (MissionLib + ~20 mission scripts), deaths (`ET_OBJECT_EXPLODING` …) | many | **No.** The next bank on the same target must see the shields and hull this pulse left (P1). Damage has to apply in order inside the walk. The event-emitter-gaps #13 rule ("collision events before the damage", `event-emitter-gaps.md:621-635`) is the same kind of constraint for weapon hits | workstream D (damage in C++, reading flags per decision 8); then only the events queue |
| K2 BANK_STOP (firing) | 0.08 | `StopFiring` → loop-sound stop | — | yes | — |
| K3 DONE expire | 0.016 TTL + 0.077 hit | `RemoveObjectFromSet` + `ET_TORPEDO_EXITED_SET` (PR:595-607, 589) | `Maelstrom/Episode8/E8M2/E8M2.py:4513`, `Conditions/ConditionIncomingTorps.py` | already at the K3 step's end; queueable as is | — |
| K3 hits → `apply_hit` | 0.077 | HL:1332-1341, after `update_all` | as K2 pulse | already a batch at the step boundary; the order is the hit list's | D |

Roadmap §5.1's "events that decide" (`ET_ENVIRONMENT_DAMAGE`, `ET_OBJECT_CONVERTED_TO_HULK`, `ET_SHIELDS_SET_STATE`) are **not** among the per-tick weapon records above. The weapon events here only report. The order-sensitive part is the damage they sit next to.

---

## 5. The known items, resolved

### 5.1 "Ships before they acquire a target" (SIG-160)

**Closed by posed parts; no reason fires.** SIG-160's 222 `RUN_PYTHON` were the two Birds of Prey walked while posed: no target yet means cruise, and cruise swings the wings. The reason was `posed_ship` (K1H:140, now retired), raised by the old pre-scan rejection of a posed firing ship. R5 reproduces SIG-160's exact setup (16 ships, 120 frames at 6 ticks a frame) and counts `k1_posed.walks` **222** with `k1_python_systems` **0**: the same 222 walks, now native (K1C:798-799 counts them). R1 shows the 64-ship version: 937 posed walks, all in the first 900 ticks, and 0 hand-backs.

### 5.2 K3 `stale_ref`: whole step, or per torpedo

`begin` hands the whole step to Python when any torpedo's `_target_ship`, `_source_ship`, `_containing_set` or `_mount_key` reads -2 (K3C:845-848). That happens only after the referent's row was **dropped** (`_drop` NC:332-366, on a value the mirror cannot encode). Measured 0.

Per-torpedo alternative, field by field (derived from the code; needs tests):
- **`_target_ship` -2:** already handled per torpedo once `begin` lets it through. `guided` reads `!= -1` (K3C:563), so a stale target still counts as guided, like Python's `is not None`. `guide()` then finds -2 not in the scan and ASKs `guide` (K3C:285-286), which is Python's whole `_guide`, exact. Nothing else in the step reads the target.
- **`_mount_key` -2:** already handled per torpedo: PG:335-337 → `steer_point` `mount_unrepresentable` ASK.
- **`_source_ship` -2:** NOT safe per torpedo as the kernel stands. The broadphase's and the narrow phase's `ship is source` tests (K3C:386, 407, 675) compare handles, so a -2 source never matches the firer's live handle, while Python's identity test can. The firer could then be hit by its own torpedo. This needs either a per-torpedo "source identity" answer at `begin` (Python maps the object to its scan index, or to -1 if it is not in the scan), or it stays whole-step.
- **`_containing_set` -2:** the broadphase groups by set and resolves offsets (K3C:632, PG:255-257), so a -2 set would have to read like an unresolvable frame for that torpedo only. That needs per-torpedo exclusion from the broadphase plus a Python narrow pass. It should stay whole-step.

Cheapest: narrow `stale_ref` at K3C:845 to `_source_ship` and `_containing_set`, and let target and mount take their existing ASKs. The larger lever is §5.7: a dropped SHIP row costs far more than `stale_ref`.

### 5.3 K3 ASK `guide` for targets outside the step scan

K3C:283-288: a target or source not in `ships_list`. Since `ships_list` is every ShipClass in every set (HL:2562-2572), this needs a non-ShipClass target, or a ship removed from every set while a torpedo still flies at it. Measured 0 across ~840 torpedoes and bolts and many deaths (R1). The check exists only because "its class and overrides were never checked" (K3C:283-284). That is **scaffolding** under the mod policy. Once the Python copies go, a target with a live Object row and a real `IsDead` can be guided natively: `guide_torpedo` already checks `has_real_is_dead` (PG:261) and the transform (PG:269). A target with no row cannot be named at all (it reads -2 → `need_guide`). No new mirror data.

### 5.4 K1 fire-time `no_mount` for picked spots on posed targets

Raised at WG:243-252 inside `_resolve_torpedo_aim_point` (tubes) and the pulse lead (`_solve_pulse_launch_direction`), counted at K1C:1047-1050 as `k1_fire_ask_reasons["no_mount"]`. It fires when the target is **posed**, the tube's stored `_target_offset` is no authored mount (`authored_mount_subsystem` → none), and the firing ship's Manual Aim slot (`manual_slot_pose`, pushed by `_resolve_manual_slot` NC:1499-1512) does not hold this exact target and offset. Python then runs the box rule `part_severance.part_for_point` (PS:76-110) at fire time (ruling C4). Sources (Task 5 report:107-112): a player tube whose stored offset is the *previous* pick, and an NPC tube's offset kept across a re-target. Counts: 0 in R1/R4/R5 (no Manual Aim headless; NPCs fight at red = identity pose). 4-22 per 660-tick posed differential run.

Cheapest native design: **port the box rule**. `part_for_point` is pure over `articulation.part_boxes_for(leaf)`, which is cached per leaf for the process (PS:82-86), and the point: `_distance_to_box` per box, `sorted((d, name))`, one inside wins, several inside → None, otherwise nearest by `ATTRIBUTION_MARGIN` (PS:96-110). Push each leaf's boxes once with their part names (the sort's tie-break compares names, so names must travel), and port `_distance_to_box` statement by statement. The same port also retires the Manual Aim slot machinery, K2's posed `aim_point` `no_mount`, K3's posed `unbaked`, and most of `resolve_stale_part_slots`' manual-slot work. **Inferred**: `part_boxes_for`'s first call per leaf may need a render instance (`iid`), so Python resolves it once, at the first push.

### 5.5 K4 reasons

All zero in all three runs; K4 decided every tick (8,999 / 7,199 / 720). Its Python-side reasons `audit`, `patched`, `unsnapped`, `max_count`, `weights` and part of `player` are scaffolding (§1.4). The scan reasons are scaffolding (`unseen`, `instance_patch`, `is_dead`) or rare (`no_row`, `stale`, `set`, `duplicate`, `not_ship`). The kernel reasons (`nonfinite`, `frame`, `set`, `player`, `scan`) are rare. Nothing routine is left in K4.

### 5.6 K2's remaining ASKs

`is_dead`, `can_detect`, `aim_point`, `shields_block`, `bubble`, `resolve_hit`, `bank_step`: all **0** in all three runs (§1.2 has each trigger). None is routine in a single-set fight. The two that a real campaign scene could reach are `resolve_hit` (a target with a render instance outside the viewing set; NC:3420-3431 sends only the viewing set's offset, **inferred** rare because instances are made for the viewed set) and `aim_point` (Manual Aim at a posed target without a slot, closed by §5.4). `can_detect`'s fallback is reachable only through a plain `App.Nebula` (no stock script creates one) or an unresolved set frame.

### 5.7 A dropped SHIP row costs K3 and K4 their whole step for the ship's life (derived, not measured)

`_drop(obj)` (NC:332-362) runs when a value the mirror cannot encode is written to a mirrored field (`_call` NC:433-437 on a `ValueError`). It deletes the object's `_nslot`, frees its row and re-pushes its referrers as -2. For a **ship** that means, read off the code:
- The step scan needs every `ships_list` entry to have an Object row (HB:3758-3767 `no_row`). `ships_list` is every ShipClass in every set (HL:2562-2572), so **K4 and K3 run whole in Python every step** (`k4_python_reasons["no_row"]`, `k3_python_reasons["scan"]`) for as long as that ship exists. Nothing registers it again: `register` (NC:928-957) is called when the object is built, **inferred** from its call sites.
- K1 and K2 contain it per ship: `unslotted_ship` (K1C:737, K2C:424), and `stale_row` for systems whose refs now read -2.
- Every torpedo naming the ship also reads `stale_ref` (§5.2), though the scan fails first.

No drop happened in R1/R4/R5 (all these counters are 0), so this is a latent cliff, not a measured cost. It is the one way a single rare event turns into a whole-step fallback that persists. Worth a ruling once the Python copies go: either make a drop impossible for ship rows (reject the unencodable value at the field), or let the scan treat an unslotted ship as "not a K3/K4 participant" when nothing can hit or select it. At minimum, count drops so a capture shows them.

---

## 6. Other things worth knowing

- **The kernels themselves are now half of fire control** (K1 `next()` 0.548 ms of `k1_pump`'s 1.307 per tick, Debug). After §3.1-3.2 the kernel dominates, and a Release build matters for the next measurement. Every perf-register capture so far is Debug. *Round trips (2026-11-01): §3.1-3.2 shipped and fire control measured 1.000 ms per tick (SIG-166); the kernel/Python split after it was not measured.*
- **`k1_system` (StartFiring) sessions are not cheap per call:** 94 µs average, 1.27 per tick, run from `gl.ai`, not `sim.combat`. Each repeats `_k1_recheck_overrides` and `resolve_stale_part_slots` over the parent and its target list (NC:2891-2908) and runs one walk with its own `WALK_START`. §3.1 removes part of it (done: the walk starts natively; the re-check and slot sweep remain). The rest belongs with workstream J (AI ↔ combat).
- **Felix (R4) had no kill in 120 s** with the Destroy order given. Its per-tick rates (6.3 walks, 0.55 FIRE, 0.5 CONTACT) are an order of magnitude below R1; its fallbacks are 0 as well.
- **Not exercised by any run here:** Manual Aim (headless), tractors, cloaking, nebulae, multi-set fights, mission scripts with weapon-event handlers. Zeros for the reasons those reach (`self_managed`, `no_mount`, `aim_point`, `can_detect`, `resolve_hit`) come from these scenes only. Their counts in the posed differentials are cited where known.
