# Warp tunnel as the loading screen — design

**Date:** 2026-10-16
**Status:** design, awaiting Mark's review. Not implemented. Includes turning the
system haze on for production (§4).
**Branch:** `perf/warp-arrival-spike-log` (worktree `.claude/worktrees/warp-arrival-spikes`).
The spike-capture tooling this design relies on is committed there (`636df711`).
**Area:** `engine/appc/warp.py`, `engine/host_loop.py`, `native/src/renderer/system_nebula_pass.{h,cc}`,
`native/src/renderer/nebula_atmosphere.{h,cc}`, `native/src/renderer/far_pass.cc`, `native/src/host/host_bindings.cc`

## Why

Arriving in a system after a set-to-set warp freezes the game for several
seconds. The tunnel plays normally, the exit flash happens, and then the game
locks up on the first frame in the new set. Mark hit it warping into Vesuvi (E1M2 is the
example), and it is the worst first impression the warp has.

**Intent (Mark, 2026-10-16): the warp tunnel is the loading screen.** The
tunnel lasts at least its normal length. That length is a **floor**, so a fast
machine never sees a shortened tunnel. After the floor, the tunnel ends when
loading is done. A slow machine sees a longer tunnel, never a freeze. There is
**no loading indicator**: the tunnel just keeps going.

## Measured (live, 2026-10-16)

The numbers come from Mark's run with `DAUNTLESS_PROFILE_SPIKES` on a **Debug**
build with `--developer`. The route was QuickBattle start → Vesuvi Haven
(Vesuvi6) → Starbase 12 → Vesuvi Haven. The log has every frame of 100 ms or
more, with raw (not averaged) times per step. Indented rows are part of their
parent.

| Arrival | Frame | Biggest pieces |
|---|---|---|
| Vesuvi6, first visit | **9151 ms** | `env.system_nebula` **7422** · `rock.near.draw` (in `viewscreen.rtt`) **1134** · `scene.celestial`/`load.planet_model` ×5 **237** · `warp.swap_set` 134 (`region_init` 57, `realize_set` 77, of which `hull_prewarm` 51) · `scene.system_load` 102 · `rock.near.stream` 40 · `sky.bake` 20 |
| Starbase12 | 1219 ms | `sim.gameloop` **817, unattributed** · `env.system_nebula` 203 · `load.planet_model` ×2 95 · `scene.comm_sets` 46 |
| (inside the tunnel) | 445 ms | `sim.gameloop` **402, unattributed** |
| Vesuvi6, return visit | **7376 ms** | `env.system_nebula` **7259** · `rock.near.stream` 39 · `scene.far_tier` 16 |

What the numbers say:

1. **The system haze table is the freeze.** It accounts for 81% of the first
   arrival and 98% of the return. `_push_system_nebula`
   (`engine/host_loop.py`) pushes the system's radial profile. Native
   `SystemNebulaPass::set_profile` then runs `atmosphere::build_table`, a
   256×128 far-field table, on the main thread. A warp clears the profile
   (`m=None` while streaking), so the identical table is rebuilt on **every**
   arrival, including a return to the same system. The code comment says
   "~1.6 s"; measured on this Debug build it is **7.3–7.4 s**. Its Python half
   (`profile.k_sys`) takes ~0 ms, so the whole cost is the native table build.
2. **Second: about 1.1 s on the first rock draw of the session.**
   `rock.near.draw` loads impostor atlases lazily (`FarPass::atlas_for`: two
   PNG decodes, an 8-pass CPU dilate and a mip upload per rock). This is
   *inferred* from the code. The scope has no finer split, so confirm it before
   building on it.
3. **Then about 0.5 s of first-visit content:** planet models, the region
   `Initialize`, realizing ships and their hull volumes, and the system loader.
4. **Two blocks of time with no named owner:** 817 ms inside `sim.gameloop` on
   the Starbase12 arrival frame, and 402 ms inside the tunnel. No existing scope
   covers either.
5. Boot also pays `scene.far_tier` 1164 ms (the catalogue push) on frame 1. That
   is outside this design's scope, but noted.

**This work also turns the haze on for production** (Mark, 2026-10-16: "yes
lets turn it on by default"). Today it is gated on `--developer` + Volumetric
Nebulae, pending live approval. That gate goes; see §4. So the 7.4 s build
lands on every player's first visit unless the preload hides it.

## Goals

- No arrival frame over **250 ms** after any set-to-set warp. That holds on a
  first visit and on a return, and with and without `--developer`. Measure it
  with the same spike capture, on the same route.
- The tunnel never runs shorter than it does today.
- The tunnel itself stays smooth. Preload work must not move the freeze into
  the tunnel; a stuttering tunnel is a failure.
- A return to a system already visited this session costs nothing that the
  first visit already paid.

## Non-goals

- The in-system dash: it never leaves the system.
- Developer mission-picker swaps (`swap_mission`) and the first mission load at
  boot: there is no tunnel to hide them behind.
- Boot cost: `scene.far_tier` 1.16 s on frame 1, `sky.bake`, CEF start.
- A Release build, or changing `CMAKE_BUILD_TYPE`. Never reconfigure the
  canonical tree's build type. Debug numbers are the ones measured, and the
  design must work at Debug speed.
- NPC warps. Only the player's warp drives the preload; NPCs warping elsewhere
  load nothing new to render.

## Anti-goals (would be a failure even if the freeze went away)

- A tunnel that hangs forever because something never reports ready.
- A loading bar, spinner or text.
- Gameplay state moved or mutated early: preloading must not run SDK scripts
  out of order, fire events, or change which set the player is in before BC
  would. (See `docs/engine/perf-cadences-and-latency.md` for how a moved cost
  became a gameplay change before.)
- Production render output changing for a frame because of the preload. The
  arrival frame must look the same as today, minus the freeze.

## Design

### 1. The tunnel waits for "destination ready" (mechanism)

`_HoldUntilAction` (`engine/appc/warp.py`) already holds the transit until
`start + t_burst + 0.9·t_transit`, and completes at once if that deadline has
passed. That deadline is the **floor**: `t_transit` is 8–40 s, scaled by
distance (`_T_MIN`/`_T_MAX`). Extend the hold so it completes only when
**both** are true:

- the floor deadline has passed, and
- the **destination preload** reports ready, or a **safety cap** has expired.

**Safety cap (Claude's call): 30 s past the floor.** If the preload is not
ready by then, release anyway. Whatever is unfinished then runs on the arrival
frame as it does today, and one `[warp-preload] late: <items>` line goes to
stderr. A bug then costs a freeze, never an endless tunnel.

Only the **player's** warp waits. An NPC's `WarpSequence` keeps today's
behaviour.

### 2. The destination preload (what runs during the tunnel)

A preload job starts when the player's warp departs (`_WarpDepartAction`, at
the burst). The destination module is known from `WarpSequence_Create`. Each
item is either **cached for the session** (paid once) or **re-pushed cheaply**
on arrival. In priority order, by measured cost:

| # | Item | Today | Change | Where it runs |
|---|---|---|---|---|
| 1 | System haze table | rebuilt on every arrival, 7.4 s main thread | **build on a worker thread, cache per system for the session** | worker (CPU); GL upload on main, under 5 ms |
| 2 | Rock impostor atlases (to confirm) | lazy on first draw, ~1.1 s | decode + dilate on a worker; upload a few per tunnel frame | worker + main, budgeted |
| 3 | Planet models of the destination system | cold `load_model` on arrival | `_load_planet_model(..., cache=controller)` during the tunnel, one per frame | main (GL), budgeted |
| 4 | Ship models + hull volumes of the destination set | on the swap | load models (not instances) during the tunnel, and prewarm hull volumes **by hull path + resolution** through a new binding (`prewarm_field(iid)` takes an instance id; `HullVolumeCache` is keyed on absolute hull path, resolution, quality — never create hidden instances to reach it) | main (GL), budgeted |
| 5 | Unattributed 817 ms / 402 ms | unknown | **add scopes first**, then decide | — |

**Item 1, the haze table (the bulk of the win).**
- `atmosphere::build_table(profile, look)` is a pure function: no GL, no
  globals. Split `SystemNebulaPass::set_profile` into two halves:
  - a CPU **build** that can run on a `std::async` worker, keyed by a hash of
    (profile rows, look: `g`, `floor`, `k_sys`, star radius, colours);
  - a main-thread **install** that uploads the ready table.
- Keep built tables in a small per-session cache (one entry per key; a few MB at
  most).
- On arrival, `_push_system_nebula` hits the cache and installs without
  building.
- Remove the arrival rebuild itself. Today the latch `_system_nebula_pushed_for`
  is reset while streaking, which makes the post-warp push look new. With the
  cache this costs only an upload, but leave a comment so nobody "optimises" the
  cache away.
- A dev dial change (veil, g, floor) changes the key, so live tuning still
  works. It rebuilds once, on the main thread as today, which is acceptable
  under `--developer`.
- Expose to Python as `system_nebula_prebuild(profile_dict)` (non-blocking) and
  `system_nebula_ready(profile_dict) -> bool`. Python builds the dict exactly as
  `_push_system_nebula` does; factor that into one helper so the two can never
  differ.

**Items 3–4, GL loads.** These need the main thread and the GL context
(`load_model` requires it). Run them **one item per tunnel frame** at most, so
no single tunnel frame does more than one model load. Measured planet loads are
~47 ms each and ship loads ~22 ms, so a tunnel frame may run 50–70 ms. That's
acceptable, but take it to Mark if he sees the tunnel stutter: the budget is
the knob. Only load what arrival will actually load. Use the same helpers with
the same arguments (`_load_planet_model`, `_load_runtime_ship_model`), because
the native cache dedupes on (path, replacements, decals, scale). A preload with
different arguments would load a second copy and save nothing.

**When the destination set does not exist yet** (no mission change, set never
loaded), the ships cannot be known before `Initialize` runs at the swap. Do
**not** run `Initialize` early (anti-goal: SDK scripts out of order). Preload
only what the **system map** knows (planets, haze, atlases) and leave the ships
to the swap. The measured cost there is ~134 ms, under the goal.

**Cross-mission warps (E1M2's case) are in scope.** `_MissionChangePoint`
runs mid-tunnel, before `_HoldUntilAction`, and `mission_change.change()` clears
every set but the bridge and `"warp"`, then runs the new mission's
`Initialize`. So:

- **The mission-change frame is exempt from the tunnel-frame budget.** It runs
  SDK setup at BC's own point in the sequence and cannot move. It is already
  inside the tunnel today, so the player sees a tunnel hitch, not an arrival
  freeze. Its cost is reported, not gated. *(Claude's call.)*
- **The preload re-plans after the mission change.** Session caches (haze
  tables, atlases, the controller's `nif_to_handle`) survive the clear. The
  per-set part (which ships to load) is re-evaluated once
  `_MissionChangePoint` has run, because a set the new mission creates there is
  created at the SDK's legitimate moment. *(Claude's call.)*

### 3. Finding the two unattributed blocks (first build step)

Before building items 2–5, add scopes so the 817 ms (Starbase12 arrival,
inside `sim.gameloop` with no warp scope) and the 402 ms (in the tunnel) have
owners. Also split `rock.near.draw` into `rock.near.build`,
`rock.near.mesh_draw` and `rock.impostor.draw`, and time `atlas_for`'s loads,
to confirm item 2. Then rerun Mark's route, plus a cross-mission warp (E1M1 into E1M2). Anything
new is added to the table above **from the measurement**, not guessed.

**If a measured cost cannot be preloaded** (for example SDK script work tied
to set entry), stop and bring the measurement to Mark before building around
it. Do not spread it over post-arrival frames, and do not quietly exempt it.
*(Claude's call.)*

### 4. The system haze in production

Remove the developer half of the gate. The haze then follows only the Volumetric
Nebulae setting, which is part of the "Improved Space" master (default on,
`engine/settings_store.py`). Every place that gates it:

- `_system_nebula_gate` and the early `dev_mode.is_enabled()` return in
  `_push_system_nebula` (`engine/host_loop.py`). The flare-veil users of the
  same gate (~5353, ~5375) follow it automatically.
- `plan_nebula_draws(..., dauntless::is_developer_mode() && ...)` in
  `native/src/host/host_bindings.cc` `frame()`.
- The comments and docstrings saying "developer-only", the spec status in
  `docs/superpowers/specs/2026-09-29-system-nebula-render-design.md`, the
  radial-profile spec's runtime table row, and the CLAUDE.md "Radial system
  profile" row ("developer-only pending live approval").

**Production look = the dials' `DEFAULTS`** (`engine/dev_nebula_dials.py`: veil
0.15, g, floor). The dial *keys* that change them stay developer-only. With
`--developer` the live dials still tune and still change the cache key.
*(Claude's call: the defaults are what Mark has been looking at in every dev
run.)*

**Order: the preload ships first, then the unlock**, in the same branch. Unlocked
on its own, it would add a 7 s freeze to every production arrival into a
profiled system.

Tests: production (no `--developer`) with the setting on pushes the profile and
draws the system pass. With the setting off, no renderer call is made, as
today's dev-off path guarantees now. Update the existing tests that pin "production
makes no renderer call"; don't delete them.

## Constraints

- Never reconfigure the build type; Debug is the baseline.
- `load_model` and every texture upload need the main thread's GL context.
  Only CPU-pure work goes to a worker.
- Python 3.11 host; the GIL is held by Python code, so a CPU worker must be
  native (pybind releases the GIL around the call), not a Python thread.
- Shared checkout: never run destructive git. Work stays on this branch in the
  worktree, and Mark live-tests there.
- Spike capture (`DAUNTLESS_PROFILE_SPIKES`) is the acceptance measurement.
  Keep its scopes; add to them.

## Acceptance

1. Mark's route (Vesuvi Haven → Starbase 12 → Vesuvi Haven), with and without
   `--developer`, with spike capture on: no frame of 250 ms or more whose
   context line is an arrival (`warp_streaking=False`, first frame in the new
   set). No tunnel frame of 100 ms or more.
2. The tunnel is never shorter than today (floor unchanged). On this Debug
   build the first Vesuvi visit may run longer than its floor if the haze table
   is not ready. That is expected, not a failure.
3. Headless tests: the hold completes only when floor and ready are both met;
   the cap releases a never-ready preload; an NPC warp never waits; the haze
   cache returns the identical table for an identical key, and a changed dial
   changes the key.
4. The full gate (`scripts/check_tests.sh`) is green.
5. Mark confirms live that it feels seamless.

## Left to the builder

- Hash function and cache container for the haze table key.
- How the preload job is structured (one object per warp, held on the
  `WarpSequence`, is the obvious shape).
- Exact per-frame budget for GL loads, within "one model per frame".
- Test layout.
- Whether the atlas preload decodes every catalogue rock or only those the
  destination's density field can produce. Every rock is fine: there are 37,
  and it is session-cached.

## Calls Claude made (check these)

- Production look = the dev dials' `DEFAULTS`; the dial keys stay developer-only.
- The unlock lands after the preload, on the same branch.
- Safety cap of 30 s past the floor.
- "One GL load per tunnel frame" as the budget.
- Ships are preloaded only when the destination set already exists; nothing
  runs `Initialize` early.
- The mission-change frame is exempt from the tunnel-frame budget; the preload re-plans after it.
- An unpreloadable cost stops the build and goes back to Mark.
- The arrival goal is 250 ms, not "one frame". Matching or beating the
  pre-existing per-frame noise on the bridge is out of scope here.
