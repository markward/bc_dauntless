# Rock class — design (modern asteroids, sub-project 2)

**Date:** 2026-09-30
**Branch:** `feat/rock-class`, forked from `feat/rock-catalogue` (sub-project 1,
unmerged, awaiting live check). Base the work on that branch, never on `main`.
**Roadmap:** `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md`
(standing decisions for this sub-project are there; this spec settles the rest).

## Intent

Asteroids stop being ships while still answering every call a mission makes on
them. A rock is a lean body: it takes hits, shows rock craters, and when its
hull runs out it **breaks up** — no ship death sequence, no fireball. Pieces big
enough become new targetable rocks; smaller ones tumble as rock chunks until
sub-project 3 (minors) exists.

This is a **deliberate departure from BC**, which built every asteroid as a full
`ShipClass`.

## Decisions (Mark, 2026-09-30)

| # | Decision |
|---|---|
| Q1 | `RockClass` **subclasses `ShipClass`**. Missions depend on `ShipClass_Cast` succeeding on rocks (see Evidence). |
| Q2 | A rock built from a **stock asteroid type keeps that type's hull HP and mass**; its shields, power and AI are ignored. Only a rock with no type file (broken off, seeded later, `DamageableObject_Create`) derives HP and mass. |
| Q3 | At 0 HP a rock **breaks up at once** (~0.5 s): crack, dust and grit burst, no fireball. |
| — | Rocks are **excluded from death-explosion splash in both directions**: a dying rock splashes nothing, and a dying ship's splash does not reach rocks. |
| — | Design sections 1–3 approved as presented. |

## Evidence

- **Cast mechanism.** `ShipClass_Cast` / `ShipClass_GetObject`
  (`engine/appc/ships.py:1936-1948`) are `isinstance` checks, so a subclass
  passes. (TESTED tier once the E2E tests below exist; today: code read.)
- **Missions that need the cast.** Each returns early on `None`, so a non-ship
  rock would silently skip a story beat:
  - E1M2 `ObjectDestroyed` (`E1M2.py:1257`) — clearing the debris rocks spawns
    the moving asteroids (`g_bDebrisCleared`).
  - E1M2 `PlanetCollision` (`E1M2.py:1314`) — "an asteroid hit Haven".
  - E1M2 `WeaponFired` (`E1M2.py:1388`) — Picard's shot counter (minor).
  - E2M1 `KaroonCollision` (`E2M1.py:649`) — Karoon hits an asteroid.
  - E2M1 tractor handler (`E2M1.py:1079`) — `ShipClass_GetObject(Beol4,
    "Asteroid 3")` or the Warbird never flings the Karoon.
  - E1M2 `AsteroidExploding` (`E1M2.py:3084`, the death script) uses
    `DamageableObject_Cast`, which any design passes.
- **E3M1's "asteroid" is a disguised Amagon ship** (`E3M1.py:411`). Out of scope.
- **Nothing attaches an AI to a rock.** The hardpoints' `SetAIString
  ("NonFedAttack")` is copied (`ships.py:1210`) and never read by the engine or
  the SDK. E2M1's "FlyToAsteroid" AI belongs to the Warbird.
- **Scripted velocity is never integrated today.** `SetVelocity` /
  `SetAngularVelocity` only store (`engine/appc/objects.py:601-620`);
  `ship_motion._step_ship_motion` returns when no setpoint was written
  (`ship_motion.py:185-188`), and no other code advances a position from
  `_velocity` (only the decaying collision overlay, `collisions.py:698`). So
  E1M2's five moving asteroids very likely **never move** in Dauntless today.
  Code-read only; Task-level tests must pin it before and after.
- **`DamageableObject_Create` is unimplemented** — `App.DamageableObject_Create`
  resolves to the module `__getattr__` `_NamedStub` (`App.py:2059-2072`), so
  Multi1's and Multi6's 54 rocks each (`Multi1.py:86-149`, `Multi6_S.py:47-110`)
  are inert and invisible. Multi1 also calls `SetNetType`, `RandomOrientation`,
  `UpdateNodeOnly` and `pSet.IsLocationEmptyTG` on them; check
  `docs/stub_heatmap.md` for each before assuming it exists.
- **Torpedoes already strike any ship they cross**
  (`engine/appc/projectiles.py:update_all`), so a `ShipClass` rock blocks them
  for free. Phasers resolve against the locked target only — no change.
- **The stbc-reference MCP was unreachable** throughout (EHOSTDOWN). BC's own
  asteroid classes are not checked against the clean-room RE.

## Design

### 1. The class, creation, and per-tick cost

**`RockClass(ShipClass)`** lives in `engine/rocks/rock.py`. `GetGenus()` keeps
answering `GENUS_ASTEROID` (3) — SDK `ScienceCharacterHandlers.py` relies on it.

**Becoming a rock.** `ShipClass_Create` only receives a name, so a rock is
recognised when its properties land: in `ShipClass.SetupProperties`, after the
`ShipProperty` copy, if the genus is `GENUS_ASTEROID` the object's
`__class__` is reassigned to `RockClass` and `RockClass._become_rock()` runs.
Genus, not name, is the marker, so a mod's genus-3 rock is a rock too.
`RockClass` adds no `__slots__` and no incompatible layout, so the reassignment
is legal.

**Other constructors.**
- `RockClass_Create(radius_gu, family, seed, name)` — for broken-off pieces now
  and seeded rocks in sub-project 4. Model: a catalogue rock (a fragment for
  broken-off pieces) chosen deterministically from `seed` within `family`.
- `App.DamageableObject_Create(model_name)` → a `RockClass` when `model_name`
  resolves to a stock asteroid LOD model; otherwise a plain `DamageableObject`
  (that path is out of scope beyond not crashing). Radius comes from the
  model's bound radius times `GetScale()`.

**Hull and mass (Q2).**
- From a stock type: the hardpoint's hull `MaxCondition` and `ShipProperty`
  mass, unchanged. Mission `GetHull().SetMaxCondition(...)` overrides still
  apply (E1M2 does this per moving rock).
- A broken-off piece: `parent_max_hp × (v_piece / v_parent)^(2/3)`; mass
  `parent_mass × v_piece / v_parent`.
- No parent and no type file: `hull = 2500 × (r / 0.8)²`, `mass = 400 × (r /
  0.8)³`, `r` in GU — calibrated on stock `Asteroid` (radius 0.8, 2500 HP,
  mass 400). An explicit `SetMass` (Multi1: 400) wins.
- The hull stays **critical**, so reaching 0 still routes to death — to rock
  death (§2), not `ship_death`.

**Subsystems.** The default subsystem objects `ShipClass_Create` allocates stay
(SDK UI code pokes at whatever is targeted and does not null-guard). Shield
maxima are zeroed so `shields_block` is false; power, shield, repair and cloak
never tick.

**Loops that skip rocks** (a rock is filtered out of each):
- AI: `ai_driver.tick_all_ai` (`ai_driver.py:1660`).
- Ship motion: `ship_motion.tick_all_ship_motion` (`ship_motion.py:135`).
- Subsystem updates and articulation: `GameLoop._update_ship_subsystems`
  (`engine/core/loop.py:90-118`).
- `SetAI` on a rock logs once (developer log) and stores nothing.

The cleanest cut is a second iterator, `ship_iter.iter_non_rock_ships()`, used
by exactly those three call sites; `iter_ships()` keeps returning rocks for
every other consumer.

**Rock motion step** — `rocks.motion.tick_all(dt)`, called beside
`tick_all_ship_motion`: `p += v·dt` from `GetVelocity()`; rotation integrated
from `GetAngularVelocity()` honouring the space it was set in
(`DIRECTION_MODEL_SPACE` is used by E1M2, `E1M2.py:3032`, so the stored space
must be kept); `SetStatic` / immobile rocks never move. The collision overlay
keeps working as it does for ships. A tractor on a rock works through whatever
the tractor writes today (verify at plan time against `engine/appc/tractor.py`).

**Loops that keep rocks:** collisions, torpedo hits, the target list, sensors,
AI line of sight (`ProximityManager.GetLineIntersectObjects`), direct-hit
damage. **Not** death splash (next section).

### 2. Damage, death and breakup

**Hits.** `combat.apply_hit` is unchanged; with no live shields the damage goes
to the hull and carves craters as it does on ships. Breakable-component
severing (`hull_breakup.after_carve`) is left as it is: a carve that cuts a
piece off a big rock (radius above `BREAKABLE_MIN_RADIUS_GU`) sheds a chunk,
which reads as chipping.

**Rock surface flag.** Each rock's renderer instance carries
`surface_is_rock`, set at both realise sites (`host_loop.py` beside the
`set_rim_eligible` calls, ~6051 and ~7159). With it:
- `breach_pass` fills crater interiors from the rock's own base texture
  (triplanar, darkened) instead of the hull-interior `Damage.tga`
- `breach_venting` emits nothing
- `hull_hit_smoke.maybe_emit` skips rocks
- no hull arcing
- `breach_debris` tints chunks and sparks grey-brown

Rebuilt against today's files, using `feat/procedural-asteroids` (commits
`5ff22ff2`, `4b67f4ae`, `30f11f80`, `a28ed044`) as **reference only** — every
file it touched has been rewritten since, so nothing is cherry-picked.

**Rock death** (`engine/rocks/death.py`), replacing `ship_death.begin` for rocks
when the critical hull reaches 0:
1. Mark dying; run the death script (`RunDeathScript`, raise-safe).
2. Fire `ET_OBJECT_EXPLODING` at once, with the killer, exactly as
   `ship_death._broadcast_exploding` does.
3. Visual: crack flash plus dust and grit burst. No fireball, no explosion
   storm, no `death_cascade`.
4. **No splash damage.** `splash_damage.apply` returns early for a rock source
   and skips rock targets.
5. Break up (below), then remove the parent and fire `ET_OBJECT_DESTROYED`
   after 0.5 s, or after the lifetime the death script set if it set one
   (E1M2 sets 0.5 s).

**Breakup.**
- Volume budget: 70% of the parent's volume goes into 2–5 pieces; the rest is
  dust. Piece count and sizes come from a generator seeded by the rock's name,
  so the same rock always breaks the same way.
- Pieces fly apart with the parent's velocity plus an outward push along
  parent-centre → piece-centre, and a random tumble.
- A piece with radius ≥ **1.0 GU** (`kMajorMinRadiusGU`, a Python dial) becomes
  a new `RockClass` via `RockClass_Create`: a catalogue *fragment* of the
  parent's family, named `"<parent>-1"`, `"<parent>-2"`, … (so
  `"Asteroid 5-1-2"` after two generations), targetable / scannable /
  hailable copied from the parent, HP and mass per §1.
- A smaller piece above `kChunkMinRadiusGU` becomes a tumbling rock chunk
  (`debris_chunk` style, catalogue fragment mesh, capped and oldest-first
  evicted). Sub-project 3 replaces these with minors.
- Below that, dust only.
- Pieces do not inherit the parent's death script, and are not in any mission
  name list, so mission bookkeeping sees exactly one death per scripted rock.

**Family.** A rock's family comes from its catalogue pick (sub-project 1's
`engine/rocks/catalogue.py`). With catalogue rocks toggled off (stock BC
meshes), pieces still use the silicate family.

### 3. Collisions broadphase

`collisions.resolve_collisions` is all-pairs today (`collisions.py:738-760`).
Breakup and Multi1's 54 rocks raise the body count, so add a **uniform spatial
hash**: cell size = 2 × the largest collidable radius in the set, clamped
to a floor; each body tests its own and the 26 neighbouring cells. Frames
(`frames.offset_between`) are handled as now — bodies in different frames are
never paired. **The pair set must equal the all-pairs set**: a test runs both
over randomised scenes and asserts identical pairs and identical resolved
state.

## Out of scope

Minors and halos, fly-through and shield flicker (sub-project 3); the far tier
(3b); profile seeding, the generic density interface and Vesuvi's 0.4 edit (4);
planetary rings; sensor occlusion; the Karoon's own scripted `SetVelocity` in
E2M1 (a ship, not a rock — noted as a related gap, not fixed here);
multiplayer net semantics of `DamageableObject_Create` (`SetNetType` may stay
inert).

## Testing

- **Unit:** genus-3 `SetupProperties` switches class; non-rocks unchanged;
  `ShipClass_Cast`, `ShipClass_GetObject`, `DamageableObject_Cast` pass on a
  rock; rocks absent from the AI, motion and subsystem loops and present in
  collisions / torpedo candidates; `SetAI` inert; hull and mass rules (stock,
  piece, formula, explicit `SetMass`); drift and model-space spin; static rocks
  never move; death splash skipped both ways; breakup determinism (same name →
  same pieces), volume budget, major/chunk/dust split at the thresholds,
  naming, flag inheritance, no death-script inheritance; event order
  EXPLODING → DESTROYED with the lifetime honoured.
- **Broadphase equivalence** against all-pairs.
- **E2E through the mission harness** (entry at the mission, not a helper):
  E1M2 — debris clearing spawns the moving asteroids; a moving asteroid
  reaches Haven and fires `AsteroidHitPlanet`; E2M1 — `KaroonCollision` fires
  on an asteroid and `"Asteroid 3"` resolves; Multi1 — 54 rocks exist, are
  `RockClass`, and have distinct positions.
- **Renderer:** `surface_is_rock` binding round-trips; venting descriptors
  empty for a rock instance; breach pass samples the base texture for a rock
  (headless GL test in the existing breach-pass style).
- **Gate:** `scripts/check_tests.sh` exits 0.

## Live check (Mark)

`./build/dauntless --developer`, then: E1M2 — shoot the debris, watch the
moving asteroids actually move and break; E3M2 — Vesuvi 4's Unknown Debris
still scan and do not die; QuickBattle in Multi1 — 54 rocks visible; shoot a
big rock until it breaks into targetable pieces.
