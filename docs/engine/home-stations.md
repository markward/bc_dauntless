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
- A hit is the player's `ET_WEAPON_HIT` on a station: phaser or torpedo, damage above 0, shield hits count. Counted hits are at least `HIT_GAP_S` = 5 s apart in game time; two within `WINDOW_S` = 60 s turn the station hostile.
- Hostile: the name moves from the friendly/neutral groups into the real enemy group. An armed station (phaser, torpedo or pulse system) gets BC's `AI.Compound.StarbaseAttack` aimed at Quick Battle's friendly group by name, so wingmen join in and the station fires at them. An unarmed station only changes side, its AI untouched. Stations never enter `g_kShips`: they neither count towards nor block a win.
- Ends when the player enters a set in another star system (moving between regions of one system keeps it; the warp transit set is no destination), when a battle starts or ends (`StartSimulation2`/`EndSimulation` wrappers), and on mission change. The station's prior groups and, if replaced, its prior AI come back; damage stays. Counted hits in another system are forgotten too.
- `is_hostile` / `hostile_stations` are the readable register for other systems.

## Free-roam death is final
`engine/quickbattle/free_roam_death.py` wraps `QuickBattle.ShipDestroyed`: the player killed outside a battle is not recreated (BC's `RecreatePlayer` respawn is skipped), the death sequence still plays and the pause menu still works. A death in a battle still ends the battle. Mark's reason: once a save game exists the player will reload a recent save.

## Gotchas
- A rebuild loses pre-battle scars (the renderer cannot clear one hull's wear); a rebuilt rock starts at rest.
- The Prendel outpost reappears in E6M4 until world state lands.
- Unowned real ships that BC's `ChangeRegion` pulls into the battle region stay there afterwards.
- Not live-verified.
