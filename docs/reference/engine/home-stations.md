# Home stations, owners and the Quick Battle restore

Spec: `docs/superpowers/specs/2026-10-25-home-stations-design.md`. Status: built on feat/home-stations, not live-verified.

## Stations
- `engine/systems/home_stations.{py,json}`: 13 stations, strictly validated (unknown or missing keys, duplicate (set, name), format other than 1 all raise `ValueError`).
- `read_point` reads placement points from the SDK at run time; no BC coordinate is stored.
- `place_for_set` is called from the region hook right after `apply_map`. `is_standing` (destroyed-this-mission record, cleared on mission change) is the only gate.
- Stations join no mission group.
- A mission's `CreateShip` reuses the station (marked, same script, alive) through a wrapper routed via `sdk_overrides` and both SDK loader twins.
- `free_roam_docking_defaults()` runs on each Quick Battle load.

## Owners
`engine/systems/owners.py`: anything a world system places carries an owner tag. Quick Battle never treats an owned object as a battle object, keeps it in its own set and proximity manager, and lets its owner rebuild it. Patrols are meant to be the next owner.

## Quick Battle restore
`engine/quickbattle/sim_restore.py` wraps `ChangeRegion`, `StartSimulation2` and `EndSimulation`. The snapshot covers real objects (owned, present before the battle, or built by the region's `Initialize`). Restore keeps an unchanged object and rebuilds a changed or destroyed one (an owner rebuilds its own, the rest from their script), then applies its condition. `engine/appc/ship_death.py`: `_remove` is identity-safe; `forget` is new.

## Star map faction icons
`engine/systems/station_factions.py` lists, per charted system, the factions with a standing home station there: the station script's species in the ship catalog, `Neutral` or uncatalogued (Biranu) adds nothing, Federation first then alphabetical. The star map reads it at every opening (`star_map_panel._faction_icons`) and puts each emblem (`ship_catalog.insignia_path`) between the star and its name, inside the label, so a name a mission hides takes its emblems with it. A faction with no emblem shows nothing. Presence is stations only (Mark, 2026-10-25).

## Warp arrival beside the Dry Dock
DryDock's "Player Start" (BC's default warp arrival) is one unit from the Dry Dock station, so a default warp arrived inside the dock (Mark, live 2026-10-26). `engine/systems/arrival_points.py` adds a "Dauntless Arrival" waypoint to the region from the region hook, 20 GU forward and 30 GU left of "Player Start" in its own frame and facing the same way. The player's tunnel arrival (`warp._PlacePlayerAction`) and in-system dash (`dash.start_set_course`) take it in place of the default. A placement a mission linked is kept. A ship in a WarpSequence also uses `_PlacePlayerAction`, so an NPC that warps in to the default point arrives there too.

## Stations defend themselves
Spec: `docs/superpowers/specs/2026-10-26-station-self-defence-design.md`. `engine/systems/station_hostility.py`, active while Quick Battle (free roam included) runs.
- A station is a ship whose property is stationary, or a home station (never genus: that takes in comm arrays and lights).
- A hit is the player's `ET_WEAPON_HIT` on a station: phaser or torpedo, damage above 0, shield hits count, and the station must be the player's current target (a stray shot never counts). Counted hits are at least `HIT_GAP_S` = 5 s apart in game time; two within `WINDOW_S` = 60 s turn the station hostile.
- Hostile: the name moves from the friendly/neutral groups into the real enemy group. An armed station (phaser, torpedo or pulse system) gets BC's `AI.Compound.StarbaseAttack` aimed at Quick Battle's friendly group by name, so wingmen join in and the station fires at them. An unarmed station only changes side, its AI untouched. Stations never enter `g_kShips`: they neither count towards nor block a win.
- Ends when the player enters a set in another star system (moving between regions of one system keeps it; the warp transit set is no destination), when a battle starts or ends (`StartSimulation2`/`EndSimulation` wrappers). The station's prior groups and, if replaced, its prior AI come back; damage stays. Counted hits in another system are forgotten too. A mission change only forgets (`reset()`): the old sets are torn down, nothing is restored.
- `is_hostile` / `hostile_stations` are the readable register for other systems.

## Free-roam death is final
`engine/quickbattle/free_roam_death.py` wraps `QuickBattle.ShipDestroyed`: the player killed outside a battle is not recreated (BC's `RecreatePlayer` respawn is skipped), the death sequence still plays and the pause menu still works. A death in a battle still ends the battle. Mark's reason: once a save game exists the player will reload a recent save.

## Tau Ceti shuttle service
Spec: `docs/superpowers/specs/2026-10-26-tau-ceti-shuttles-design.md`. `engine/systems/shuttle_service.py` (module docstring is the authority), ticked as `gl.shuttles` in `GameLoop.tick`.
- Ten `Shuttle` ships ("SB12 Shuttle 1..10") between Starbase 12 and the Dry Docks, in every mode, joined to no mission group, owner `tau_ceti_shuttles`. Docked = a record in no set (free). Launch one a minute (`_STAGGER_S`), docked `DOCK_S` = 600 s between trips.
- Phases: DOCKED, UNDOCKING, DEPARTING, WARPING_OUT, TO_DOCK, CIRCLING, LEAVING_DOCKS, WARPING_BACK, APPROACHING, ENTERING, DOCKED; plus WAITING (Starbase 12 missing) and LOST. Holds may interleave (bay taken, no free orbit). Headless round trip for shuttle 1 ≈ 505 s measured (`tests/integration/test_shuttle_round_trip.py`); with ten shuttles queueing a cycle can reach ≈ 1,600 s.
- Lanes: rings of per-shuttle points ("SB12 Shuttle Lane N", 50 GU ring, 31 GU apart) round the centre lane point `LANE_GU` = 2,000 GU out, in each region; a second ring (own holding point) round a clearance point 150 GU outside the bay mouth. The Dry Docks' lane lies along Dry Dock's forward; Starbase 12's straight out of the bay ("Docking Exit End" along the exit axis, `_lane_axis`).
- ⚠️ Why Starbase 12's lane is on the bay axis: BC's Intercept steers round any ship over 150 GU in its way (`AdjustDestinationForLargeObstacles`, Intercept.py:286) with a detour point it moves every update, and Starbase 12's radius is **296 GU live** (`host_loop._seed_ship_radius`, the model box's corner; headless it is 0, and the unit tests use 150 — neither crosses the line). With the lane along the station's forward the station was ahead of every fly-out and the in-system warp chased the detour point round the station for ever (live 2026-10-26). On the bay axis the station is behind a departing shuttle and beyond an arriving one's approach point. A shuttle the player's docking pushed through to the far side flies at impulse to a point abreast of the station first ("SB12 Shuttle Round", the station's radius, at least 200 GU, plus 50 GU out, square to the bay axis on its own side). `tests/integration/test_shuttle_round_trip.py` flies a round trip with the live radii and the warp flythrough.
- Bay: one shuttle at a time (none launches or enters while another is UNDOCKING/ENTERING); arrivals first (a due launch waits while a shuttle holds outside). Collisions with Starbase 12 are off on bay legs, on after. The player owns the bay while docking, docked or undocking (a Dock/Undock AI tree on the player, or the player within 200 GU of the bay mouth, e.g. parked there): the service holds. An undocking shuttle that BC's player docking pushed out (more than 275 GU from the bay mouth), or with the bay taken by the player, departs from where it is (collisions with the station off until 200 GU from its centre) instead of following the bay waypoints back in through the player.
- Restore-teleport guard: BC's `DockWithStarbase` records objects it pushed from inside the starbase in `g_kRestoreTranslateDict` (by ObjID) and `FinishedUndocking` teleports them back minutes later. While the bay is the player's, the service removes its shuttles from that record every tick.
- Obstacle avoidance (ruling R10): DEPARTING, TO_DOCK, LEAVING_DOCKS, APPROACHING, WAITING and the lane/approach holds run inside BC's `AvoidObstacles` preprocessor; the bay legs and CIRCLING do not. The target dry dock is kept out of the scan by the per-pair collision mask on TO_DOCK and CIRCLING. BC's avoidance grazes an obstacle's bound rather than keeping a margin (measured headless: closest centre 0.91-1.05 x the obstacle radius, no contact). Mark's E1M1 acceptance relies on it.
- Mission exclusions (ruling R9): `_EXCLUDED_MISSIONS` (E8M2: its EnterSet targets, for the player, every ship but the Chairo entering Starbase12 before Omega Draconis 5). While one is current the service stays docked, as when away. Audit (2026-10-26) of the SDK Maelstrom missions that build Starbase12 or DryDock, their ET_ENTERED_SET / ET_EXITED_SET / ET_OBJECT_DESTROYED / ET_OBJECT_EXPLODING handlers: every one filters by ship name, mission group or the player, so none is listed: E1M2, E2M2, E2M6, E3M1, E3M4, E3M5, E4M4, E4M6, E5M2, E5M4, E6M1, E6M4, E6M5, E7M2, E7M3, E8M1 (and, cleared at review, E1M1, E2M0, E2M1, E3M2, E4M5, E6M2, E6M3, E7M1, E7M6, Starbase12_S). Near misses: E6M5 counts ships whose name starts "Shuttle" (`[:7]`; "SB12 Shuttle" does not match, keep the prefix); E4M4's ShipDestroyed re-checks its win on any death, but only with the player in Voltair1 (the service is paused then); E7M3's ObjectDestroyed sets a dialogue flag on any death while two or more enemies follow (cosmetic).
- Warp transit: docking, discarding or resetting a shuttle mid NPC warp aborts its `WarpSequence` (with the renderer on a flythrough parks it in BC's "warp" set and later drops it into the destination); a launch removes the ship from any set still holding it.
- Dock choice: random (the service's own `Random`) among standing docks with a free orbit, fewest other shuttles bound for it first. Circle `CIRCLES` = 2 turns, left side in.
- Orbit bands come from the dock layout: no orbit inside max(2 x hull radius, 20 GU), none beyond half the gap to the nearest other station minus 5 GU; ~7 GU bands, 3 GU apart, filling outwards, emptying inwards. This supersedes the plan's 40/60 GU floors (Dry Dock and Dry Dock3 are 89 GU apart). Re-measure if `home_stations.json` moves the docks.
- Pause: only when the player is in another star system, or an excluded mission is current (every shuttle docks, timers freeze). No live player or the warp transit set leaves it as is.
- Quick Battle: the owner opts out of `sim_restore` (`restores_after_battle`); the service itself docks the shuttles a battle damaged or destroyed, and battle losses are not recorded. A second `StartSimulation2` with no End merges into the running battle.
- Losses: `losses()` lists (index, name, set, game time, killer), cleared on mission change; a lost shuttle stays lost until then.
- E1M1: SDK E1M1 ends the mission on any non-player death in DryDock, so a shuttle dying there ends the tutorial (accepted by Mark).
- Live-check: the bay queue (up to five shuttles holding outside Starbase 12, arrivals entering before launches); circle sizes against the docks; live dock radii (above ~15 GU Dry Dock/Dry Dock3 become ineligible: no orbit fits); a player parked at the bay mouth holds the service; dock with a shuttle in the bay, undock, and check no shuttle teleports back into the bay (restore guard); shuttles flying round ships in their way without leaving their circles.
- Cost: `gl.shuttles` times only the service's own bookkeeping, not the shuttles' AI, motion or drawing. The real comparison is the service on versus off: the same capture with `DAUNTLESS_DEV_RENDER_OFF=shuttle_service` (developer mode; `shuttle_service.set_enabled(False)` docks every shuttle and makes `tick` a no-op). Not yet taken.
- Not live-verified.

## Gotchas
- A rebuild loses pre-battle scars (the renderer cannot clear one hull's wear); a rebuilt rock starts at rest.
- The Prendel outpost reappears in E6M4 until world state lands.
- Unowned real ships that BC's `ChangeRegion` pulls into the battle region stay there afterwards.
- Not live-verified.
