# Warp-in arrivals (campaign + Quick Battle warp-in delay) — design

Date: 2026-10-22 · Branch: `feat/qb-warp-in-delay` · Status: built on feat/qb-warp-in-delay; Mark tried it in game 2026-10-22 ("seems to work perfectly"); §6.6 measurement still owed

## 1. Intent

Mark wants a per-group **warp-in delay (minutes)** in the Quick Battle setup
screen. A delayed group is absent at the start, then warps in after its delay.

Mark's steer:

- If arriving ships need new engine work, the same work must also give the
  campaign its warp-ins.
- The original missions show how BC did this, so follow them.

That is the shape of this design. **One warp-in routine, BC's own**, made real
in our engine. Every campaign mission that brings ships in gets it, and Quick
Battle's late groups use the identical path.

### 1.1 What BC does (evidence)

Campaign missions never build their own warp-ins. About 103 call sites in
16 missions call one SDK routine, `loadspacehelper.CreateShip(script, set,
name, placementName, 1)`; the fifth argument means "with warp flash".

| Missions | Sites |
|---|---|
| E6M1 | 30 |
| E7M1 | 18 |
| E8M2 | 15 |
| E4M6 | 9 |
| E7M3 | 7 |
| E7M2 | 6 |
| E6M4 | 4 |
| E5M4, E3M5 | 3 each |
| E4M4 | 2 |
| E7M6, E1M1, E2M0, E3M2, E3M1, E4M5 | 1 each |

The chain, in the SDK (paths under the SDK scripts root):

1. `loadspacehelper.py:105-133`: `AddObjectToSet`, `PlaceObjectByName`,
   `UpdateNodeOnly`, then `EffectScriptActions.CreateEndWarpSequence(id,
   placement).Play()`. With no placement name, it only calls
   `WarpFlash(ship)`, which calls `App.WarpFlash_Create(pShip)`.
2. `Actions/EffectScriptActions.py:178-198`: with T = `WarpEngineSubsystem_GetWarpEffectTime()`:
   - t=0: `InitiateDewarp`, then the "Exit Warp" sound on the ship's node;
   - t=T/2: `SetWarpStage(WES_DEWARP_ENDING)`;
   - t=T: `SetWarpStage(WES_NOT_WARPING)`;
   - then `SetImpulse(0.2)`, so the ship coasts.
3. `InitiateDewarp` (:212-233) runs these steps:
   - `pWarp.SetPlacement(placement)`;
   - `SetWarpState(WES_WARPING)`;
   - `TransitionToState(WES_DEWARP_INITIATED)`;
   - then `WarpFlashEnterSet`, which reads `GetWarpExitLocation()` and
     `GetWarpExitRotation()` and calls `App.WarpFlash_CreateWithoutShip(set,
     loc, rot, radius[, time])` (:61-91).
4. Missions give the ship its AI **straight after `CreateShip` returns**,
   while the flash sequence is still starting. Examples: E5M4:1020-1027,
   E7M3:1021-1025, E6M1:1963-1972.
5. Missions delay arrivals with ordinary game-time timers or sequences. For
   example, E7M3:1330 sets a 180 s `MissionLib.CreateTimer`, which leads to
   `ReinforcementsArrived` (:1133), which leads to `CreateShip(...,1)` (:1021).
6. **E5M4:980-1027 is the template for Quick Battle.** It builds placements at
   run time relative to the player (`PlacementObject_Create`, `SetTranslate`,
   `AlignToVectors` facing the player, a second and third placement offset
   sideways). It then calls `CreateShip(..., "<placement>", 1)` for three
   ships and `SetAI` on each.

A second, smaller path: an AI ship in another set warps into the player's set
through `AI/PlainAI/Warp.py` and `App.WarpSequence_Create`. The explicit
warp-in ones are in E7M3: `AttackerGroup1AI`, `AttackerGroup2AI`,
`DefenderAmbushAI` and `ReinforcementAI`. BC's `WarpSequence.py:276` plays
`WarpFlashEnterSet` on arrival.

From the clean-room reference (all `reviewed-not-tested`):

- **`spec/SceneComposition.md` §7.8:** `WarpFlash` is a set object with a start
  and an end time stamp. It retires itself in the same set tick once its end
  time has passed. Scripts can reach it only through the two create calls. The
  reference does not describe the look, size or default duration; the renderer
  is out of its scope.
- **`spec/WarpEngineSubsystem.md` §5.2:** in `WES_DEWARP_BEGINNING` and
  `WES_DEWARP_ENDING`, when a warp target exists, velocity is zero and the
  ship's **position is driven**. Each frame it is set to the target plus a
  stored offset scaled by `1 − timeRemaining/2.0`, so the ship slides in over a
  fixed 2.0 s. On `WES_NOT_WARPING` velocity is zero (§5.3).
- **Not confirmed:** that `SetPlacement` is what sets that warp target, the
  offset's size and direction, and `GetWarpExitLocation`'s exact rule.

### 1.2 What our engine does today

- **Real:** the warp-state machine.
  - `WarpEngineSubsystem.SetWarpState`, `TransitionToState`,
    `tick_transition` and `IsWarping` (`engine/appc/subsystems.py:1680-1780`).
    Dewarp states finish by themselves after the effect time.
  - The module-level `WarpEngineSubsystem_GetWarpEffectTime()` is 3.0
    (`subsystems.py:3043`). That value times the SDK sequence's stage calls.
    Each ship's own effect time is 0, so its own dewarp deadline is the 2.0 s
    fallback, which matches BC's fixed 2.0 s stage (§1.1).
  - Collisions are off while warping (`engine/appc/collisions.py:238-259`).
  - **But** `tick_warp_states` runs only in `host_loop`, on the clamped
    wall-clock frame step (`_player_dt`). It stops under pause but ignores time
    scale, and it never runs headless.
- **Stubbed** (resolved by `__getattr__`; listed in `docs/stub_heatmap.md`
  rows 132-135 and 180):
  - `WarpEngineSubsystem.SetPlacement`
  - `GetWarpExitLocation`
  - `GetWarpExitRotation`
  - `App.WarpFlash_CreateWithoutShip`
  - `App.WarpFlash_Create`
  - **Also missing:** `SetClass.GetRegionModule`. `WarpFlashEnterSet` imports
    `pSet.GetRegionModule()` and calls `.GetSet()` on it; our
    `SetRegionModule` stores nothing. Without it, the five names above still
    give no campaign flash.
- **Result:** every campaign reinforcement appears instantly at its mark.
  There is no flash and no slide-in. It cannot collide for about 3 s. The
  "Exit Warp" sound plays.
- **No world-space flash exists.** The only "warp flash" is the player's
  full-screen whiteout (`resolve.frag`, `renderer.set_warp_flash_intensity`).
- **Arrival from another set:** our native `WarpSequence` (`engine/appc/warp.py`)
  places the ship instantly at zero velocity, with no flash. Its player-only
  effects are gated by `_is_current_player`.
- **Already recorded as open:**
  - `docs/superpowers/specs/2026-09-22-in-system-navigation-design.md:145-149`
    ("scripted arrivals are currently flashless");
  - `2026-09-25-in-system-warp-design.md:489-492`.

## 2. Goals

1. **Warp-in for campaign missions.** `CreateShip(..., placement, 1)` produces
   a visible warp-in at the placement:
   - a flash at the exit point;
   - the ship slides from the exit point onto its placement during the dewarp
     states;
   - the "Exit Warp" sound;
   - the ship coasts at 0.2 impulse afterwards.

   This needs real `SetPlacement`/`GetPlacement`, `GetWarpExitLocation`,
   `GetWarpExitRotation`, `WarpFlash_CreateWithoutShip`, `WarpFlash_Create`
   and `SetClass.SetRegionModule`/`GetRegionModule`.
2. **Flash without a placement.** `CreateShip(..., "", 1)` and any direct
   `WarpFlash_Create(ship)` show the flash at the ship.
3. **Set-to-set arrivals.** An AI ship arriving in the **player's current set**
   through our native `WarpSequence` gets the same flash and slide-in. That
   is E7M3's attack and reinforcement groups.
   - **Departures too.** An AI ship leaving the player's current set flashes
     where it was, before it is hidden, as BC's `WarpSequence.py:98` does. Today
     these ships just vanish. *Our call:* the same flash, the same small hook in
     `engine/appc/warp.py`, and it's the campaign behaviour Mark asked to unlock.
4. **Quick Battle warp-in delay.** Each non-player group has a **Warp-in**
   setting.
   - When it is set, the group's ships do not exist at the start. When the
     delay has passed, they arrive through the same routine as the campaign.
   - Each ship goes through its own `CreateShip(..., placement, 1)`, with
     placements built at run time the way E5M4 does.
5. **Victory waits for late enemies.** "Defeat everything" counts late enemies
   from the start. You cannot win until every enemy, late ones included, has
   arrived and been destroyed. (Mark, 2026-10-22.)
6. **Late ships get their AI on arrival,** the way the missions do: straight
   after `CreateShip`, using the group's difficulty, the same AI module
   `generate_ships` would have chosen, and the same `g_kShips` record.
7. **The crew calls out Quick Battle arrivals** with BC's own existing voice
   lines (§6.7). Campaign missions already script their own callouts, so
   nothing is added there.

## 3. Non-goals

- **No new victory conditions.** Mark plans more later. This design only
  keeps "defeat everything" correct with late ships.
- **No change to NPC in-system travel.** Mark ruled on 2026-09-28: one speed,
  no flash. Only ships arriving from another set, or created with the flash
  flag, get a warp-in.
- **No change to the player's own warp.** The tunnel, the dash and the
  full-screen whiteout stay as they are.
- **No warp "stretch" of the ship model** (BC's `SetWarpStage` comment
  mentions it). Out of scope unless it already exists.
- **No save/load of pending arrivals** or of a live flash. The Quick Battle
  setup is per run, and BCS save work is parked.
- **No multiplayer.**

## 4. Anti-goals (a failure even if it "works")

- **A Quick-Battle-only warp-in** that the campaign doesn't share. The whole
  point is one routine.
- **Winning before the late enemies have arrived and been destroyed.**
- **A visible hitch when a late group arrives** (loading ship models
  mid-battle). See §6.6.
- **A pending arrival that fires after End Simulation, Restart or a mission
  swap,** spawning ships into a dead battle or the wrong mission.
- **Any change to Quick Battle with no delays set.** It must behave
  byte-identically to today: same spawn, same placement, same AI order.

## 5. Decisions made with Mark (2026-10-22)

| Decision | Mark's answer |
|---|---|
| Build path | Reuse the campaign's own mechanism, so the same work unlocks campaign warp-ins. |
| Victory | "Defeat everything" counts late enemies; no win until they have arrived and been destroyed. |
| AI | Follow the missions: AI assigned on arrival. |
| Where a late group arrives | "It doesn't matter where they arrive from, make it random." |
| During the slide | The ship holds its heading and holds fire until it has fully arrived, but can be targeted throughout. |
| Delay control | A − and + button either side of the value; click the value to type a number; any whole number is accepted. |
| Flash look | Generated in a shader (core, streak along the line of travel, ring), not BC's 64×64 flipbook. |
| Crew callouts | Quick Battle arrivals use BC's existing voice lines (§6.7); no new recordings. |

## 6. Design

### 6.1 Engine: the warp-in routine (campaign and Quick Battle alike)

Make these real on `WarpEngineSubsystem` (`engine/appc/subsystems.py`) and the
App module surface:

- **`SetPlacement(placement)` / `GetPlacement()`:** store the placement as the
  dewarp **target**.
- **`GetWarpExitLocation()` / `GetWarpExitRotation()`:**
  - With a target: the exit point is the target's position moved **back along
    the target's forward axis** by the slide distance (§6.3). The exit
    rotation is the target's rotation.
  - With no target: the ship's own world location and rotation.

  *Our call.* The reference leaves the rule unconfirmed (`clone` grade).
- **Dewarp drive.** While dewarping toward a target, position is driven and
  velocity is held at zero. The ship goes from the exit point to the target
  over the dewarp span, and then sits exactly on the target. When the dewarp
  completes, the target is cleared.
  - The slide runs for **2.0 s from `TransitionToState(WES_DEWARP_INITIATED)`**.
    That is the ship's own dewarp deadline (its effect time is 0) and BC's
    fixed stage length (§1.1).
  - The SDK sequence's later `SetWarpStage` calls (at 1.5 s and 3.0 s) must
    not restart or move the slide.
  - Easing is the builder's choice, as long as it lands exactly on the target.
- **During the slide** (Mark, 2026-10-22):
  - the ship **holds its exit heading**, so the AI cannot turn it;
  - it **holds fire**: no weapon on it fires until the slide has landed;
  - it **can be targeted** throughout.

  The AI is assigned at creation as the missions do, and takes over when the
  slide ends. This applies to every warp-in, campaign and Quick Battle alike.
  The reference is silent here, so this is our rule, not recovered BC
  behaviour.
- **`App.WarpFlash_CreateWithoutShip(set, loc, rot, radius[, time])` and
  `App.WarpFlash_Create(ship[, time])`:** create a self-retiring flash record in
  that set, retired once its end time passes (`SceneComposition` §7.8).
  - Default duration if `time` is omitted: a tunable, initially
    `GetWarpEffectTime()/2`. *Our call.*
  - The flash is drawn only when its set is the rendered set.
- **Rendering feed.** Flashes reach the renderer through the normal per-frame
  feed, never from `render_payload` game-state mutation (see
  `docs/engine/perf-cadences-and-latency.md`).
- **`SetClass.SetRegionModule(name)` / `GetRegionModule()`:** store and return
  the module name, so `WarpFlashEnterSet`'s `__import__(...).GetSet()` resolves.
- **Timing.** Everything above advances on **game time**: no wall-clock, and
  frozen under pause. **Move `tick_warp_states`, the slide and the flash
  ticks into the simulation step**, so the host and the headless
  `headless_mission._sim_tick` run them alike. Today it runs only in
  `host_loop` on `_player_dt` (§1.2; see also
  `2026-07-13-warp-collision-suppression-design.md:197-213`).

### 6.2 Set-to-set arrivals (our native `WarpSequence`)

When a non-player ship's warp **arrives in the player's current set**,
`_PlacePlayerAction` and its NPC equivalent in `engine/appc/warp.py` run the
same dewarp toward the arrival placement (§6.1) and create the flash. That
matches BC's `WarpSequence.py:276`.

Arrivals into sets the player is not in stay instant, with no flash.

### 6.3 The flash: look and size

The reference has nothing on the look, so the look is ours. Mark calibrates it
live; see `feedback_vfx_calibrate_up_then_down`.

**Procedural, drawn in a shader** (Mark, 2026-10-22). There are no texture
assets; BC's 64×64 `warpflash1..8.tga` flipbook is **not** used.

- **Why procedural:**
  - it stays sharp at any size on a 4K display;
  - it is bright enough to feed the HDR bloom;
  - it can show the ship's direction of travel, which a round flipbook
    cannot.

  This follows the shield splash, which went from a texture to a procedural
  effect (`project_procedural_shield_splash`).
- ⛔ **Not the sprite library** either. Mark rejected it for stock effects on
  2026-10-16. Stock particle output must stay byte-identical
  (`tests/unit/test_stock_particle_output_unchanged.py`).

**The look**, after the on-screen Trek warp-in: a bright point stretches into a
streak along the line of travel, then collapses as the ship appears. Three
terms, each a function of the flash's age over its life:

1. **Core:** a hot point at the exit point. It flares fast and fades over the
   life.
2. **Streak:** a thin bright line along the flash's **forward axis**. That is
   the exit rotation's `GetCol(1)`, which is why
   `WarpFlash_CreateWithoutShip` takes a rotation; `WarpFlash_Create(ship)`
   uses the ship's own rotation.
   - It stretches out early, then retracts toward the core as the ship lands.
   - It is drawn as a camera-facing ribbon about that world axis, so it
     still reads when seen nose-on or side-on.
3. **Ring:** a brief expanding ring, perpendicular to the forward axis, that
   fades as it grows.

**Scale and timing**, every value *our call*, a tunable, and a starting point
for calibration:

- Sizes are in multiples of the radius passed to the create call, so a
  shuttle's flash is small and a station's is large:
  - core: initially 1.5× radius;
  - streak: initially 8× radius;
  - ring: up to 3× radius.
- The slide distance is initially 10× radius. Line the streak up with the
  slide, so the ship travels down the streak and lands as it collapses.
- The life defaults to `GetWarpEffectTime()/2` when the create call gives no
  time.
- Colour is a cool blue-white.
- Start **bright**: the core and streak go well past the bloom threshold.
  Mark tunes up and then down (`feedback_vfx_calibrate_up_then_down`).

**Implementation:**

- **One scalar shape function of** (offset from the core in the flash's own
  frame, age, radius). Write it **once in a C++ header** as the CPU twin, and
  mirror it in the shader, the way `shield_splash_shape` lives in
  `renderer/shield_state.h` and `shaders/shield.frag`. A unit test pins the
  twin, so shader and CPU can't drift.
- **Additive and depth-tested,** so a hull or planet in front hides it. It
  draws in the HDR target before bloom, in the transparent-VFX phase.
- **The pass:** a small dedicated pass, or a mode of an existing additive pass
  (`shockwave_pass` already draws an animated ring and core flash). The
  builder decides; reuse if it fits without bending the existing pass's look.
- **New GLSL** must follow the project's GLSL 410 rules. Shader errors only
  show at runtime (`project_shaders_glsl_410`, `feedback_shader_errors_are_runtime`).

**Sound:** "Exit Warp" is already played by the SDK sequence. Do not add
"Warp Flash" on top unless the live check wants it.

**Tuning:** a developer dial group, `"warp in"` on `/ L O`, the way other VFX
are tuned. It covers:

- core, streak and ring size × radius;
- streak and ring timing;
- slide × radius;
- default life;
- brightness;
- colour.

Settled values are then baked as consts.

### 6.4 Quick Battle: the setting

- **`Group` gains `warp_in_min: int = 0`.** 0 means present at the start.
  - **Allowed values:** **any whole number of minutes, 0 or more** (Mark,
    2026-10-22). There is no upper limit.
  - `_DRAFT_FIELDS` validates against fixed id lists today, so this field
    needs an integer path. That path must reject non-integers, negatives,
    booleans and floats such as `2.5`.
  - **The player group** never has a delay: it is always present.
- **Round trip:**
  - `to_json` writes the field.
  - `from_json` reads it, **defaulting to 0 when the key is missing**, so every
    existing preset still loads unchanged.
  - A value that isn't a whole number ≥ 0 is rejected like the other fields'
    bad values.
  - `update_details` gains the argument; it is positional today, so update
    every caller and test.
- **Panel** (`engine/ui/quick_battle_setup_panel.py`):
  - the draft field;
  - the catalog list;
  - the group payload;
  - the group summary line. A delayed group reads e.g. "Enemy · warps in at
    5 min".
- **JS** (`native/assets/ui-cef/js/quick_battle_setup.js` `renderDetails`):
  - one more row, **Warp-in**: a **− value +** stepper (Mark, 2026-10-22).
    - **The buttons:** − and + step by 1 minute. − is disabled at 0.
    - **The value:** reads "Start" at 0, otherwise "N min".
    - **Typing a value:** clicking the value turns it into a number field.
      - The player types any whole number, committed on `change`.
      - Anything else (blank, negative, a fraction, text) reverts to the
        previous value.
      - Esc cancels, and Enter or blur commits.
    - **Reuse:**
      - the sheet's quantity stepper look (`qbs-qty`);
      - the CEF text-capture panel contract, so the game reads no keys while
        typing (`data-panel` on the root, commit on `change`; CLAUDE.md
        "Keyboard capture for CEF text fields");
      - the existing `draft:<field>:<value>` verb with an integer value;
  - while a delay is set, the **Direction** row shows as "Random" and can't be
    used. The group keeps its stored direction, so turning the delay off
    restores it. *Our call* on the presentation.
- **Plan:** `SpawnOrder` gains `warp_in_s: float` (minutes × 60), filled in
  `battle_plan`.

### 6.5 Quick Battle: spawning and arrival

`spawn.generate_ships` splits the plan into **now** orders (`warp_in_s == 0`)
and **late** orders.

**Now orders:** exactly today's path, unchanged.

**Late orders, at battle start:**

- They are already in `_write_manifests`, so `g_kEnemyList` stays complete and
  `StartSimulation2` still arms the win.
- **Count them now:** late enemies are added to `g_iNumEnemies` and late
  friendlies to `g_iNumFriends`. `ShipDestroyed` (`QuickBattle.py:3345-3356`)
  then cannot reach 0 until they have arrived and died.
- **Warm their models** (§6.6).
- *Accepted:* late friendly/neutral groups still arrive after the battle is
  won, until End.
- **Schedule one game-time timer per delayed group,** at the battle's
  `GetGameTime()` plus the delay. Use the timer manager the way BC's own
  `g_idTimer` is used (`QuickBattle.py:3307-3315`), or `MissionLib.CreateTimer`.

**On a group's timer:**

1. **Placement.** The group's direction is **random**, picked at this moment
   from the six faces relative to the player's **current** position and
   orientation. Its distance is the group's distance.
   - Positions come from the existing `placement.group_positions`, including
     the player seed and anti-stacking nudge `generate_ships` uses today.
   - *Our call:* the six faces rather than any direction on the sphere,
     because it reuses tested placement code. Random means Python `random`
     through an injectable RNG, so tests are deterministic.
2. **Per ship, the E5M4 way:**
   - build a run-time `PlacementObject` named
     `"QB warp in <group id> <n>"` at the position, facing the same way
     `_face` would;
   - call `loadspacehelper.CreateShip(order.ship_file, set, name, placement,
     1)`;
   - apply display name and registry as today.
3. **Bookkeeping, as for "now" ships:**
   - enemy, friendly and neutral group names;
   - the `g_kShips` record;
   - then, **immediately**, the AI: set `g_iCurrentAILevel`, then
     `__import__(ai).CreateAI(ship)` and `SetAI(..., 0, 0)`, exactly as
     `StartSimulation2` does (`QuickBattle.py:3112-3124`).
   - Do **not** count the ship again; it was counted at the start.
   - Once the whole group is in, the crew calls it out (§6.7).
4. **If a ship fails to spawn,** log it and **un-count it**: decrement the
   count it was pre-added to. If that brings `g_iNumEnemies` to 0 while the
   battle is running, run the same win path `ShipDestroyed` uses. A broken
   reinforcement must never leave a battle that cannot be won. This also
   closes the known minor bug for late ships: an enemy whose placement throws
   isn't counted (`project_quickbattle_setup_redesign`).

**Cleanup.** Every pending timer is deleted in `EndSimulation`, next to
`g_idTimer` (`QuickBattle.py:3178-3181`). That covers End, Restart and
leaving Quick Battle. A mission swap must also drop them: if timers are not
already cleared by the swap, the hook does it.

- *Builder:* confirm how the existing hooks reach `EndSimulation`, and wrap it
  the way `install_generate_ships_hook` wraps `GenerateShips`. Don't edit the
  SDK.
- A timer that fires with no battle running (`bInSimulation` false) does
  nothing. The battle set is read **when the timer fires** (`g_pSet`), never
  captured at scheduling: `ChangeRegion()` swaps `g_pSet` after
  `GenerateShips`.
- A timer that fires while the battle runs but cannot spawn its group (no
  battle set, no player) takes the **failed-spawn path** of step 4: the
  group's ships are un-counted, and the win check runs. *Our call.*

**Player death before arrival:** the loss path is unchanged; pending arrivals
are cleaned up with the battle.

### 6.6 No hitch on arrival

Creating a ship mid-battle loads its model. That is what campaign warp-ins do
too, but Quick Battle can do better because it knows the roster at start.

- **At battle start,** warm each late order's model, so creation on arrival
  hits a warm cache. Today the load is keyed from a ship object
  (`_runtime_ship_model_source(ship)`, with registry swaps and decals), and
  BC's own preload calls are records only.
  - *Our call:* "absent at the start" (Goal 4) is about play, not about
    objects. The builder may create late ships at start **outside any set**
    and add them on arrival, or add a ship-free warm path, whichever is
    simpler.
  - Either way, before arrival a late ship must be invisible to sensors, the
    target list, AI, collisions, the renderer and the win count's
    destroyed-path.
  - Radii for placement come from the same source.
- **Measure** one late group of 5 arriving in `combat_stress` with the
  frame profiler. Spike log: `DAUNTLESS_PROFILE_SPIKES`, `docs/engine/frame-profiler.md`.
  Record the result as a signal in `docs/engine/perf-register.md`. The
  capture also includes one first-of-class campaign warp-in (e.g. E2M0's
  Zhukov), because the radius seeder now loads a model inside `CreateShip`
  before the mission's own `ReplaceTexture`, and a look at `StartFiring`
  volume for the fire-gate cost.
- **Campaign warp-ins are not preloaded** in this design. If the measurement
  shows a hitch for them too, it goes in the register as a follow-up.

### 6.7 Quick Battle: crew callouts (Mark, 2026-10-22)

When a late group arrives, the crew calls it out with **BC's existing voice
lines** from `data/TGL/Bridge Crew General.TGL`. All the voice files and their
lip-sync files are present. No new lines are recorded or authored.

**Enemies: the tactical officer** (Felix; Korbus on a bridge whose tactical
officer uses `Korbus Bridge General.tgl`, through that character's own
database). These are the lines E6M1, E6M4 and E6M5 use for warp-in
reinforcements. N is the number of enemy ships that actually spawned:

| Condition | Key | Line |
|---|---|---|
| Enemies are already in play (any live enemy in the battle) | `Incoming6` | "More enemy vessels have entered the area Captain." |
| Otherwise, N = 1 | `Incoming1` | "One hostile entering the system, sir." |
| N = 2 | `Incoming2` | "Two enemies warping in, Captain." |
| N = 3 | `Incoming3` | "Three hostile ships entering the system." |
| N = 4 | `Incoming4` | "I'm reading four enemy ships entering the system." |
| N ≥ 5 | `Incoming5` | "Several enemy ships have entered the system." |

The "already in play" rule is E6M1's choice for its second wave.

**Friendlies and neutrals: the science officer.**

- The line is `gs025`, "Sensors are detecting a vessel in this system." It is
  the only generic arrival line BC has that isn't about enemies. Every
  friendly-arrival line in the game is tied to a mission.
- *Our call*, as Mark's "plug in those existing lines": one line per arrival,
  whatever the count, even though the line says "a vessel".

**How:**

- Exactly as QuickBattle speaks its own lines:
  `App.CharacterAction_Create(<character>, App.CharacterAction.AT_SAY_LINE,
  key, "Captain", 1, <general database>)`, played in a sequence
  (`QuickBattle.py:3348, 3433`).
- The characters come from the bridge: `CharacterClass_GetObject(bridge,
  "Tactical")` / `"Science"`.
- The general database is QuickBattle's `g_pGeneralDatabase`
  (`QuickBattle.py:709`), or the speaking character's own database where it
  has one, as Korbus does.

**When:**

- Once the group's ships are created, as the missions do; they speak right
  after `CreateShip`.
- One line per side per arrival tick: two enemy groups landing together give
  one enemy line with their combined count.
- If no ship of that side spawned, there is no line.
- If the character or database is missing, skip quietly and log it.
- The "Exit Warp" sound and the line can overlap; that is how the campaign
  plays.

## 7. Testing

Focused tests only; never the whole suite or the gate (CLAUDE.md).

- **Unit:**
  - **Warp engine:**
    - `SetPlacement`/`GetPlacement`;
    - exit location and rotation with and without a target;
    - the dewarp drive lands exactly on the target with zero velocity and
      clears the target;
    - pause (zero dt) freezes it;
    - during the slide, AI steering doesn't change the heading, weapons
      don't fire, and the ship stays targetable; both are released when it
      lands;
    - `SetRegionModule`/`GetRegionModule` round-trip.
  - **Flash:** a flash record retires after its end time, under game time
    only.
  - **Flash shape (ctest):** the CPU twin of the shape function. The core
    peaks early, the streak lies along the forward axis and retracts by the
    end of life, the ring grows and fades, and everything is zero at the end
    of life. Plus a GL render test that the pass draws additively and is
    occluded by depth.
  - **Scenario:** the `warp_in_min` round-trip, an old preset without the key
    loads as 0, a bad value is rejected (negative, fraction, text, boolean),
    a large value such as 600 is accepted, and the player group can never get
    a delay.
  - **Panel:** the integer draft path, with the same accept/reject cases.
  - **UI suite:** the stepper's − and + (with − disabled at 0), and typing a
    value that commits or reverts.
  - **Plan:** `warp_in_s`.
- **Headless integration:**
  - **E5M4 pursuers** (or another `CreateShip(...,1)` site):
    - after the sequence, the ship sits on its placement;
    - a flash was created at the exit point and retired;
    - the AI was set;
    - the "Exit Warp" sound fired.
  - **E7M3** set-to-set reinforcement arrives with a flash when the player is
    in the destination set, and an AI ship warping out of the player's set
    leaves a flash.
  - **Quick Battle:**
    - with one enemy group at 1 minute and one at start, killing the first
      group does **not** win;
    - the late group arrives at about 60 s of game time, at its distance from
      the player's position then, with AI;
    - killing it wins.
  - **Quick Battle, End and Restart:** ending or restarting before arrival
    leaves no pending timer and spawns nothing.
  - **Quick Battle, failed spawn:** a late enemy that fails to spawn is
    un-counted, so the battle stays winnable.
  - **Quick Battle, no delays:** today's spawn and placement output is
    byte-identical.
  - **Quick Battle, callouts:**
    - each enemy row of the §6.7 table picks the right key;
    - an arrival while enemies are already in play picks `Incoming6`;
    - a friendly or neutral arrival picks `gs025`;
    - a mixed arrival in the same tick gives one line per side;
    - no ships spawned means no line;
    - a missing character skips quietly.
- **Stub heatmap:** the stubbed names above should leave
  `docs/stub_heatmap.md` once it is regenerated.

## 8. Live check (Mark)

From the worktree: `./build/dauntless --developer`.

1. **Quick Battle:**
   - one enemy group at Start and one at 1 min;
   - kill the first group: no victory;
   - the second group flashes in near you about a minute in, from a random
     side, and Felix calls it out ("More enemy vessels have entered the
     area");
   - kill it: victory.
2. **Campaign:** a mission with warp-in reinforcements, through the Developer
   mission picker. E5M4's pursuers or E6M1's Artrus waves.
3. **Calibrate** the flash's core, streak and ring, its brightness, colour and timing, and the slide distance on the
   `"warp in"` dials.

## 9. Left to the builder

- Where the flash record lives:
  - a light object in the set's object list, retired by the set tick;
  - or a list on the set, ticked alongside it.

  Either way, it is not a `ShipClass` and not targetable.
- Whether the flash is its own pass or a mode of an existing additive pass, and how the per-frame feed carries
  it.
- The slide easing.
- The exact `g_kShips` and AI-module lookups, reused from `generate_ships` and
  `_details`.
- The developer dial group's internals.
- How the pending-arrival timers are keyed and stored, as long as cleanup is
  complete.
