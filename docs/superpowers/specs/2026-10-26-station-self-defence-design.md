# Stations defend themselves — design

Status: built on feat/station-self-defence, not live-verified (2026-10-26). Follows home stations
(`docs/engine/home-stations.md`, merged 7d83e5c3e).

## 1. Intent

Mark: "Any station I've fired at and demonstrated intent to continue attacking
should try to defend itself." Today a home station has no AI and belongs to no
side, so the player can shell it indefinitely and it just takes the damage.
This makes stations behave like they are crewed: keep attacking one and it
turns on you.

It is also the first piece of "the galaxy reacts to you". Mark plans patrols
that will respond to a station under attack (living-galaxy vision), so the
hostility must be a recorded fact other systems can read, not only a change
in the station's own AI.

## 2. Goals

- G1. In **free roam and Quick Battle only**, a station the player has damaged
  **twice within a minute** becomes the player's enemy (Mark).
- G2. An **armed** station then attacks the player (Mark). Armed today:
  Starbase 12 and every Cardassian station (shipyard, outposts, resupply
  station, Litvok Nor).
- G3. An **unarmed** station "does nothing in particular" (Mark): it is marked
  hostile but takes no action. Today: the three Dry Docks, the station beside
  them, Savoy Station, Lyra Station, Biranu Station.
- G4. Hostility lasts **until the player leaves the star system** (Mark).
  Moving between regions of the same system (Starbase 12 ↔ Dry Docks, both
  Tau Ceti) keeps it. Back in the system later, the station is as it was.
- G5. "Who is hostile to the player, and since when" is readable by other
  engine code, for the patrols that come later.

## 3. Non-goals

- Campaign missions. BC's own friendly-fire rule (Felix's warnings, then
  mission over, `MissionLib.FriendlyFireHandler`) stays in charge there, and a
  station a mission already treats as an enemy is unaffected (Mark).
- Responders. Nobody comes to a station's aid yet; that is the patrols
  project. (The player's own Quick Battle allies do attack it, §5.3.)
- Hostility spreading to other stations or ships of the same faction
  (my call, §7).
- NPC fire. Only the player's attacks count.

## 4. Anti-goals (would make this a failure even if it "works")

- One phaser sweep turning a station hostile. A stray or brief shot must not
  count as intent (the reason for "twice").
- A station that turned on you counting towards winning a Quick Battle, or
  blocking a battle from being won.
- Campaign behaviour changing in any way.
- A station that stays hostile after you have left the system and come back.

## 5. Behaviour

### 5.1 What counts as a station
A ship whose ship property is **stationary** (`SetStationary(1)`, BC's own
flag), **or** any home station (`home_stations.home_station_of`), my call.
The flag alone is not enough: `spacefacility.py:112` sets
`SetStationary(0)` (Savoy Station, Lyra Station, the station beside the Dry
Docks) and `biranustation.py` sets no flag at all, yet Mark counted all of
them as stations. Six stock hardpoints set the flag: fedstarbase, drydock,
cardstation, cardoutpost, cardstarbase, cardfacility. Mod stations count
through the flag. Genus 2 is not used: it also takes in comm arrays and comm
lights.

### 5.2 What counts as an attack, and "twice"
- A hit is one `ET_WEAPON_HIT` whose firing object is the player, whose target
  is a station, whose weapon type is a weapon (phaser/beam, torpedo, pulse —
  never a collision or environmental damage), whose damage is above 0, and
  the station is the player's current target (ruling 2026-10-26: a stray shot
  must not count as intent).
  Shield hits count: shooting a station's shields is still attacking it.
- Beams deliver damage in 0.5 s pulses (`BEAM_DWELL_FLUSH_S`), so a single
  sweep is several hits. **Counted hits must be at least 5 seconds apart**
  (my call): the first hit counts, the next one counts only once 5 s have
  passed since the last counted one. Two counted hits within 60 s of game
  time turn the station hostile. So one short sweep never triggers it;
  holding the beam on a station for 5 s, or coming back for a second pass
  within a minute, does.
- Times are game time (pauses and time scale apply).
- Counts are per station, and reset when the player leaves the system.

### 5.3 Turning hostile
In this order:
1. Record the hostility (the G5 register: station, system, game time).
2. Take the station's name out of the mission's friendly and neutral groups
   and add it to the enemy group, so the target list and every other
   affiliation read shows it as an enemy. Its previous memberships are kept
   for §5.4.
   This is the real enemy group, on purpose: in Quick Battle the player's
   allied ships and friendly stations attack everything in it, so **the
   player's wingmen join in against the station** (Mark, 2026-10-26: "yes").
3. If the station has at least one weapon system, give it BC's own station
   attack AI, `AI.Compound.StarbaseAttack.CreateAI(station, <the mission's
   friendly group>)`, keeping the AI it had before for §5.4. That group holds
   the player and, in a battle, the allies, so the station fights back against
   the wingmen attacking it too (my call, following from Mark's answer). Names,
   not objects, so it survives the player ship being rebuilt. That AI only
   acts while a target is in the station's region, so it goes quiet when the
   player flies away.
4. Unarmed: steps 1–2 only.

Nothing is said or shown beyond the target list turning red (my call; crew
lines are a later nicety).

### 5.4 Ending it
When the player **leaves the system** (the player's set changes to a set
whose system, `sector_model.system_id_for_set`, differs; the warp transit set
is ignored as a destination), every station hostile in that system returns
to what it was: its group memberships restored, its previous AI restored
(home stations: none), its hit count cleared, its register entry removed.
Damage it took stays.

Also cleared, without restoring anything that no longer exists:
- on mission change (alongside `home_stations.reset`);
- on Quick Battle start and end. Battle generation wipes the groups, and the
  battle restore rebuilds any damaged home station from scratch, so a
  hostility recorded against the old object must not survive (§6).

A hostile station destroyed is simply removed from the register.

### 5.5 Dying in free roam
Today, outside a battle, Quick Battle's `ShipDestroyed` handler calls
`RecreatePlayer()`: the player is rebuilt a short hop away, same name, same
system, and a hostile station would start shooting the new ship within one
AI poll (3 s), a death loop with no way out.

Mark, 2026-10-26: "trigger a death sequence, then leave the player's ship
destroyed. When we implement a save game mechanism they will have to reload
recent save." So in free roam (not during a battle):
- the player's ship dies through the normal death cascade (explosion and
  break-up as for any ship);
- it is **not** recreated. The player is left with no ship; the camera stays
  on the scene of the death.
- the pause menu still works, so the player can quit or start again. Until
  there is a save game, that is the only way on.

My call: this applies to **any** player death in free roam, not only a death
at a station's hands. Mark's reason (reload a save) is not specific to
stations, and a rule that respawns after a rock but not after a starbase
would be arbitrary. During a battle, death keeps Quick Battle's own handling
(the battle ends).

### 5.6 Mode gate
Active only when the running mission is Quick Battle (which is also free
roam: free roam is Quick Battle before a battle starts). Any other mission:
the hook does nothing, not even count.

## 6. Interactions that constrain the build

- **Quick Battle victory** counts only ships in `g_kShips`, filled by
  `GenerateShips`. A station added to the enemy group is never in it, so it
  neither counts towards nor blocks victory. Do not register stations there.
- **Quick Battle groups** are wiped by `GenerateShips`
  (`RemoveAllNames()` on friendly and enemy). Hostility stored only in groups
  would vanish silently; the register is the truth (G5).
- **Battle restore** (`engine/quickbattle/sim_restore.py`) rebuilds a damaged
  owned station as a new object with no AI. A hostile station being shot mid-
  battle will be rebuilt friendly at battle end. That is accepted and matches
  §5.4's "battle end clears it".
- **Friendly fire in Quick Battle.** QB enables BC's friendly-fire warnings for
  its friendly group. Home stations join no group, so attacking one never feeds
  them. A station Quick Battle itself placed on the player's side does: BC's
  warnings (and its game over) apply to it as in stock BC, alongside this.
- **Stations Quick Battle placed** (from the setup screen) are in scope (any
  station). Already enemy: unaffected. Friendly or neutral: turn hostile as
  above, and §5.4 restores their battle side and AI. Ending the battle clears
  them anyway.

## 7. My calls (Mark to check)

- Only the station attacked turns hostile; no spread to its faction.
- Counted hits ≥ 5 s apart (§5.2); shield hits count.
- Quick Battle-placed stations are included (§6).
- No crew line or message on the turn; the red target-list entry is the tell.
- Leaving the system restores the station exactly as it was, previous AI
  included; damage is kept. `SetAI` shuts the replaced AI down, so the
  previous AI is rebuilt from its creating script rather than reused.
- Station = stationary flag or home station (§5.1).
- A hostile station targets the friendly group, so it fires at the player's
  wingmen as well as the player (§5.3).
- No respawn applies to every free-roam death, not only station kills (§5.5).
- Built against main as of 7d83e5c3e. If the Quick Battle victory branch
  (`feat/qb-victory-p1`, named battle types with protected/objective ships)
  merges first, an objective or protected object Quick Battle placed is
  excluded from turning hostile.

## 8. Left to the builder

- Where the hook lives (a new `engine/systems/` module beside
  `home_stations.py` is the natural home) and how it registers for
  `ET_WEAPON_HIT` / set-exit events.
- The register's shape, provided another module can ask "is this station
  hostile to the player" and "which stations in system X are".
- Tests: headless, driving real SDK station scripts through `apply_hit` and a
  real warp/set change, including the one-sweep-does-not-trigger case, the
  in-system region change keeping hostility, and the campaign gate.

## 9. Not live-verified

Nothing here has been tried in game.
