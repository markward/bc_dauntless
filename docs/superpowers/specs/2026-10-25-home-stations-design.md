# Home stations — stations live in their regions, not in the missions

Status: design, 2026-10-25. Not built.

## 1. Intent

In BC, a station exists only while a mission script creates it. Starbase 12,
the Tau Ceti dry docks and the Cardassian stations are all built by
`loadspacehelper.CreateShip(...)` calls in Maelstrom mission scripts; the
region files (`Systems/<System>/<Region>.py`) build only the sun, planets and
placement points.

Dauntless boots into free roam: the SDK Quick Battle with no objectives, the
player free to warp anywhere. There, no mission ever creates a station, so the
player has no Starbase 12 to return to for repairs, and the Cardassian and
dry-dock regions look empty.

This design makes each station part of its **home region**: whenever that
region's set is built, the station is there. That applies everywhere: in free
roam, in a Quick Battle fought in that region, and in the campaign. When a
campaign mission later asks for "its" station, it gets back the one that is
already there instead of a second copy.

Mark's framing (2026-10-25): Starbase 12 is the player's home base, and having
it present during a Quick Battle fought at Starbase 12 "is very much the
point".

## 2. Goals, non-goals, anti-goals

**Goals**

- Every station in §3 is present whenever its home region's set is built.
- Starbase 12 can be docked with at any time in its region, and docking
  repairs the ship. This needs no new docking code (§5).
- Campaign missions keep working unchanged: a mission's `CreateShip` for a
  station that is already present returns that station.
- Every station goes through one check, "is this station still standing?",
  so a later world-state design can answer "no" for stations the story
  destroyed without changing this code.

**Non-goals**

- Docking at the dry docks or the Cardassian stations. They have no docking
  points in their hardpoints (only `fedstarbase.py` carries `Docking Entry
  Start/End` and `Inside Visibility N`), and the Helm Dock button is wired to
  Starbase 12 alone. Out of scope, by Mark's ruling.
- Species icons on the star map for systems with stations. Separate design,
  next in line.
- Remembering across missions or saves that a station was destroyed (an
  open-world campaign's world state). Separate design after the map icons.
  This design only provides the hook it will answer (§6).

**Anti-goals** (it would be a failure even if it technically works)

- A campaign mission that creates a station gets `None` back, or ends up
  holding a different object from the one in the scene.
- Two stations of the same name in one set.
- A station follows the player out of its region (see §7, Quick Battle).
- A station destroyed during a mission reappears while that mission is
  still running.

## 3. The stations

Every station a Maelstrom mission creates, taken from the SDK scripts
(2026-10-25). The name and ship script must match the mission's `CreateShip`
call exactly, or the mission will not recognise the station and will build a
second one.

| Station | Ship script | Name in the set | Home set | Placement point | Point defined in |
|---|---|---|---|---|---|
| Starbase 12 | `FedStarbase` | `Starbase 12` | `Starbase12` | `Starbase12 Location` | region file `Systems/Starbase12/Starbase12.py` |
| Dry dock | `DryDock` | `Dry Dock` | `DryDock` | `DryDock Start` | region file `Systems/DryDock/DryDock.py` |
| Dry dock | `DryDock` | `Dry Dock2` | `DryDock` | `DryDock2` | `Maelstrom/Episode1/E1M1/Dock_P.py` |
| Dry dock | `DryDock` | `Dry Dock3` | `DryDock` | `DryDock3` | `Maelstrom/Episode1/E1M1/Dock_P.py` |
| Cardassian shipyard | `CardStation` | `Cardassian Shipyard` | `Chambana1` | `Hybrid Shipyard` | `Maelstrom/Episode4/E4M5/E4M5_Chambana1_P.py` |
| Cardassian outpost | `CardOutpost` | `Outpost` | `Cebalrai2` | `Cardassian Outpost Start` | `Maelstrom/Episode4/E4M6/E4M6_Cebalrai2_P.py` |
| Cardassian resupply station | `CardStation` | `Resupply Station` | `Ascella3` | `Station Start` | `Maelstrom/Episode7/E7M3/Ascella3_P.py` |
| Litvok Nor | `CardStarbase` | `Litvok Nor` | `Alioth6` | `DS9 Start` | `Maelstrom/Episode7/E7M6/E7M6_P.py` |
| Dry dock station | `SpaceFacility` | `Station` | `DryDock` | `StationPlacement` | `Maelstrom/Episode1/E1M1/Dock_P.py` |
| Cardassian outpost | `CardOutpost` | `Outpost` | `Prendel3` | `Base Location` | `Prendel3_P` (E5M2) |
| Biranu Station | `BiranuStation` | `Biranu Station` | `Biranu2` | `Facility Location` | region file `Systems/Biranu/Biranu2.py` |
| Savoy Station | `SpaceFacility` | `Savoy Station` | `Savoy1` | `Station Location` | region file `Systems/Savoy/Savoy1.py` |
| Lyra Station | `SpaceFacility` | `Lyra Station` | `Albirea3` | `Station Start` | `Maelstrom/Episode7/E7M2/E7M2_Albirea_P.py` |

All thirteen rows load the same way; no station is a special case (Mark,
2026-10-25). Two rows share the name `Outpost`; a station is identified by
its set and name together, so that is fine.

Excluded: the Multiplayer `Mission5` starbase (multiplayer, not a home
station) and any station a Quick Battle setup spawns (those get Quick Battle
names and are combatants, not home stations).

**Where the table lives:** a checked-in data file beside the system maps
(`engine/systems/`), one row per station as above, plus the placement file's
module path where the point is not in the region file. **My call**: data, not
code, so mod stations can be added later without new code. Unknown keys are
rejected, as with the other data files.

## 4. Placing a station when its region is built

`engine/systems/region_hooks.py` already wraps every region module's
`Initialize` (from `sdk_overrides.on_sdk_module_exec`). Every path that builds
a region set ends there: warp arrival, `MissionLib.SetupSpaceSet`, a mission
calling `Systems.X.Y.Initialize()` directly, and Quick Battle's
`ChangeRegion`. After BC's `Initialize` body and the system map have run, the
hook places each station whose home set this is:

1. Ask `is_standing(station)` (§6). If not, skip it.
2. If the set already holds an object with that name, skip it.
3. Build it with the SDK's own `loadspacehelper.CreateShip(script, set, name,
   placement point)`, so it gets exactly the hardpoints, overrides (including
   the Fed Starbase shields override) and splash damage that a mission-built
   station gets.
4. Tag it with its owner, the home-stations owner (§4a), so §5 and §7 can
   recognise it.

## 4a. Owners: objects a world system places

Mark plans to extend this system to patrol ships and other ship activity
(2026-10-25, §11). So the tag on a placed station is not station-specific: it
is an **owner tag**. Any world system that places objects into a region (home
stations now, patrols later) registers as an owner and tags each object it
places with itself plus a key of its own (for stations, the table row).

An owner provides:

- **rebuild(old object, record)**: build a fresh replacement after a Quick
  Battle changed or destroyed the original (§7). The owner rebuilds, not a
  generic path, so a later patrol owner can re-attach its orders and AI.
  Stations rebuild through the same placement as §4.
- **after_rebuild(record)**: clean-up once the replacement exists. For
  stations, forget a destruction that happened inside the battle (§6).

What holds for every owned object, by being owned:

- It is never part of a Quick Battle, whenever it appeared (§7).
- Quick Battle's `ChangeRegion` leaves it in its own set (§7).

What stays station-only: the "still standing?" check (§6) and the mission
reuse rule (§5). Patrols will bring their own rules (allegiance, campaign
behaviour) in their own design.

**Placement points.** Four rows use a point defined in the region file, which
`Initialize` has already loaded. Nine use a point that only a mission
placement file defines. The point's position must be read from the SDK file
at run time; **no BC coordinate is copied into Dauntless's data**. Loading a
mission placement file into the set must not leave that file's other points
behind, and must not clash when the mission itself later loads the same file
into the same set (E8M2 loads `E7M1_P` into the Starbase 12 set, for example).
How to read just the one point is left to the builder.

**Ordering.** The station is built inside the region hook, so it exists before
the set is realised. That is the same constraint the hook already enforces for
the system map.

**Allegiance.** A placed station joins no mission group, so it is neutral
until a mission adds it to one. **My call.**

## 5. A mission asks for a station that is already there

Every Maelstrom mission that builds the Starbase 12 set also creates the
station there (26 mission scripts). That does not hold for every home set:
see §5a. A mission change deletes
every region set (`engine/core/mission_change.py`), so a campaign mission
always starts from a freshly built set. The region hook then places the
station, and moments later the mission's `CreateShip` asks for it again.

Without handling, that collides. BC's `AddObjectToSet` refuses a duplicate
name, so `CreateShip` returns `None` and the mission's next call crashes.
Ours (`engine/appc/sets.py`, `AddObjectToSet`) silently replaces the entry
and orphans the first station.

**Rule:** when `loadspacehelper.CreateShip(script, set, name, point, ...)` is
called and the set holds a **home station** (an object owned by the
home-stations owner, §4a) with that name and that ship
script that has not been destroyed, it returns that station instead of
building a new one. Before returning, it places the station at the point the
mission asked for (`PlaceObjectByName` + `UpdateNodeOnly`, as `CreateShip`
does; E8M2 moves Starbase 12 to `Starbase Location`). The warp-flash argument
is ignored for a reused station. This follows BC's own precedent:
`CreateShip` already returns an existing ship when
`pMission.GetPrecreatedShip(script)` has one.

Anything that does not match all three (home station, same name, same
script, still alive) goes through BC's unchanged path.

The interception goes through the same SDK override mechanism as the region
hook. The builder picks the exact hook point.

**Carried-over state, my call.** A reused station keeps whatever happened to
it before the mission asked for it (damage, disabled systems). In the
campaign this window is normally empty, because the set is fresh. The
exception is a station a mission creates mid-way, on the player's arrival:
the player can now reach and damage E7M3's Resupply Station before that
moment. If the player has already disabled its disruptors,
`ET_SUBSYSTEM_COMPLETELY_DISABLED` will not fire again after the mission
attaches its handler. Accepted for now. Mark has said that sandbox-versus-
story consequences belong to the world-state design.

## 5a. Missions that build a home set but never create its station

**Settled (Mark, 2026-10-25): accepted as-is until world state lands.** Some campaign missions build a home region and never
create its station, so under §4 the station appears where the original game
never had it:

- E5M4 builds Alioth6 (`E5M4.py:173-175`), where the player is sent to scan,
  and never creates Litvok Nor. Litvok Nor would appear two episodes before
  E7M6 introduces it.
- E6M4 builds Prendel3 and never creates the Prendel outpost that E5M2 does.
- Dauntless's system loader (`engine/systems/system_loader.py`) builds every
  region of a system when the player enters it, campaign included. A mission
  that builds Cebalrai1 (E8M1) therefore also builds Cebalrai2, with its
  outpost.

Findings (2026-10-25):

- **Litvok Nor in E5M4: no mechanical consequence found.** Its point
  (`DS9 Start`) is at least 400 GU from every E5M4 placement point and 677 GU
  from the planet's centre (radius 360). The scan objective targets the planet
  "Alioth 6" by name. The station is neutral and has no AI, so E5M4's Galors
  and Keldons ignore it. The only cost is that the crew never mentions it.
  Mark: a station that "suddenly appears" in E7M6 would be odder than one that
  was always there.
- **The Prendel outpost is destroyed in the story.** E5M2 cannot be won
  without destroying it: the win comes only from its `ObjectDestroyed`
  handler, and `E5DestroyOutpostGoal` is added while it stands. So it *should*
  be gone in E6M4. Without world state it would reappear there. That is the
  world-state design's job (§11); until it lands, this is a known wrong.
  Mark accepted it for now (2026-10-25), and the order stays: map icons
  next, then world state.

## 6. "Is this station still standing?"

One function, the only gate on placing a station:
`is_standing(station) -> bool`.

What it answers in this design: **no** if the station was destroyed since the
current mission started (Quick Battle's free roam counts as a mission),
otherwise **yes**. The record lives in memory and is cleared on a mission
change. That covers a region set being rebuilt mid-mission (leave and come
back), which must not bring back a station the mission just had destroyed.

The world-state design will later answer **no** for stations the story has
destroyed, across missions and saves. It replaces this function's body, not
its callers.

**Free roam has no mission change.** Region sets are never torn down in free
roam, so a station destroyed there outside a Quick Battle stays gone until the
game is relaunched. Mark: "good for now". A station destroyed *during* a Quick
Battle comes back at its end (§7).

A destroyed home station is not reused (§5). If a mission later creates a
station of that name, it gets BC's normal new one.

## 7. Quick Battle

- **A battle fought in a home region** includes its station. That is the
  point (Mark, 2026-10-25). Quick Battle's `ChangeRegion` calls the region
  module's `Initialize`, so §4 places it with no extra work.
- **`ChangeRegion` moves every ship.** It loops over
  `pOldSet.GetClassObjectList(App.CT_SHIP)` and moves each one into the new
  region (`QuickBattle.py`, `ChangeRegion`). A home station is a ship, so
  without handling Starbase 12 would follow the player to Belaruz. **Owned
  objects (§4a), home stations included, must stay in their own set.** This
  is an anti-goal.
- **A Quick Battle is a simulation on the player's ship's computer** (Mark,
  2026-10-25). What the simulation created is tracked. When it ends (End
  Combat, Restart, or a swap), everything the simulation damaged that is
  *not* part of it gets its condition back. BC already does this for the
  player: `EndSimulation` calls `RecreatePlayer`.
  - BC's `EndSimulation` deletes every damageable object in the region except
    the player. It must delete only what the simulation created. Otherwise a
    home station is deleted and never comes back, because a second battle in
    the same region returns early from `ChangeRegion` without re-running
    `Initialize`. Dauntless already wraps `EndSimulation`
    (`engine/quickbattle/spawn.py`, for late arrivals).
  - **Decided (Mark, 2026-10-25):** don't trace who hit what. Snapshot
    every real object in the region when the simulation starts (hull,
    subsystems, shields, ammunition) and restore it at the end. That includes
    indirect damage (a dying simulated ship's explosion), damage the player's
    own ship does, and asteroids. A home station the simulation destroyed is
    placed again as it was at the start, and its destruction does not count
    for `is_standing`.
  - **Which objects are real.** An owned object (§4a) is always real, even
    one that appeared during the battle. For an unowned object, timing
    decides: it is real if it existed before the battle started or was built
    by the region's own `Initialize`. Everything else belongs to the battle.
  - **Restoring.** An object whose condition the battle changed is rebuilt,
    because the renderer cannot wipe one ship's scars. An owned object is
    rebuilt by its owner (§4a). An unowned one (an asteroid) is rebuilt from
    its ship script, name, position, rotation and scale. Either way the
    pre-battle condition is then applied. Scars from before the battle are
    lost on a rebuilt object.
- Quick Battle setup may also spawn a `FedStarbase` as a combatant. It gets a
  Quick Battle name, so it never matches a home station and §5 never applies.
- Free-roam stations are neutral (§4), so Quick Battle's enemy count and
  victory check do not include them.

## 8. Docking at Starbase 12

No new code. The region script `Systems/Starbase12/Starbase12_S.py` already
does the rest when the player enters the `Starbase12` set: `EnterSet` builds
Graff's control room and enables the Helm Dock button. `DockStarbase` looks
up `"Starbase 12"` in that set and gives the player
`AI.Compound.DockWithStarbase`, which calls `RepairShipFully` unless
`StarbaseRepairsEnabled(0)` has been called. The only thing it was missing
was the station.

Graff's docking cutscene plays as in BC. **My call**: if it gets tiresome in
free roam, that is a later change.

One thing to verify, not assume: `g_bRepairsEnabled` and `g_idGraffAction`
are module globals in `Starbase12_S`. Free roam must start with repairs
enabled and no leftover Graff action, even after a campaign mission set them.
Check what the mission-change reset already covers.

## 9. Tests

Headless, focused files only (the gate runs only on a merge into main).

- Free roam: warp the player into each home set. Each station from §3 is
  present by name, at its placement point, built from the right ship script.
- Free roam, Starbase 12: the Dock button is enabled on entry. Docking runs
  `DockWithStarbase` and leaves a damaged player fully repaired.
- Campaign reuse: E1M1 (Starbase 12 and the three dry docks) and E7M3 (the
  Resupply Station, created on arrival at Ascella 3). The mission's
  `CreateShip` returns the same object the region hook placed, the set holds
  exactly one object of that name, and the mission's handlers are attached to
  it.
- E8M2: the reused Starbase 12 ends at `Starbase Location`.
- Quick Battle: switch region away from Starbase 12. The player moves and the
  station stays in `Starbase12`.
- Quick Battle at Starbase 12: End Combat, then Restart. The station is still
  there after each.
- Quick Battle restore: during a battle, damage the station's hull, shields
  and a subsystem, and have the player's own ship damage an asteroid. After
  End Combat, both are back to their pre-battle condition. A station destroyed
  during the battle is placed again afterwards, and `is_standing` still
  answers yes.
- Owners: an object tagged by a test-only owner that appears mid-battle
  survives End Combat, stays in its set on a region change, and when damaged
  is rebuilt through that owner's `rebuild`, not the generic path.
- Destroyed mid-mission: destroy a home station, rebuild its set, and the
  station is not placed again until the next mission change.
- Every test above must fail before the change.

## 10. Left to the builder

- How to read one placement point from a mission placement file without
  side effects (§4).
- The exact hook point for the `CreateShip` reuse rule (§5).
- How `ChangeRegion` keeps owned objects home (§7): wrap it, or filter what
  it moves.
- The data file's name and schema details (§3).
- What the Quick Battle snapshot captures and how it restores it (§7), within
  the rule: hull, subsystems, shields and ammunition of every real object in
  the region, put back exactly.
- How the "destroyed this mission" record learns of a destruction (the
  existing death path vs `ET_OBJECT_DESTROYED`).

## 11. What comes next

1. **Station icons on the star map.** A species icon beside each system that
   holds a station. The table in §3 is its source.
2. **World state for an open-world campaign.** Remember stations the story
   destroyed (and other story flags) across missions and saves. It answers
   §6's `is_standing`.
3. **Patrols and other ship activity** (Mark, 2026-10-25). The same region
   system later spawns patrol ships and other traffic. Two points from Mark:
   - **Campaign patrols** are to be tried, then tested to see whether the
     campaign survives them. They may turn out to be incompatible: extra
     armed ships can trip mission checks that count every ship in a set.
     For another day.
   - **Allegiance** comes from a table of who attacks whom, not from
     stations' "no side". Quick Battle's win check must leave patrols out.
