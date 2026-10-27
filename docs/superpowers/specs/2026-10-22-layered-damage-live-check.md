# Layered hull damage: live-check list for Mark

Written 2026-10-22 at the end of phase 4 (plan
`docs/superpowers/plans/2026-10-22-layered-damage-p4-finish.md`, branch
`spike/damage-redesign`, head `651f79d89`). It folds the phase-3 known limits
and every "for Mark" / live-check item from the phase-4 ledger
(`.superpowers/sdd/2026-10-22-layered-damage-p4-finish/progress.md`) into one
list. Nothing on it has been seen in game yet. The perf verdict is in
`docs/reference/engine/perf-register.md` (P-12, SIG-111 to SIG-115). Updated after the
final review's fix wave (the break check moved off the main thread; rig-part
chunks go dark).

Every launch runs from the worktree root, Debug build.

## Launch commands

Plain game (boots into Quick Battle setup; the pause menu has **Load
Mission…** and **Developer Options…**):

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/damage-redesign
./build/dauntless --developer
```

Damage Preview with time to look (the Akira loses its impulse system 3 s in,
then dies 60 s after the last blast instead of 4 s):

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/damage-redesign
DAUNTLESS_MISSION=engine.dev_missions.damage_preview DAUNTLESS_DAMAGE_PREVIEW_DEATH_S=60 ./build/dauntless --developer
```

The same, with the Akira at the closest distance (1.5 GU ahead):

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/damage-redesign
DAUNTLESS_MISSION=engine.dev_missions.damage_preview DAUNTLESS_DAMAGE_PREVIEW_DEATH_S=60 DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU=1.5 ./build/dauntless --developer
```

A stock mission with authored wrecks (Episode 3 Mission 4):

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/damage-redesign
DAUNTLESS_MISSION=Maelstrom.Episode3.E3M4.E3M4 ./build/dauntless --developer
```

The asteroid mission (Episode 1 Mission 2):

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/damage-redesign
DAUNTLESS_MISSION=Maelstrom.Episode1.E1M2.E1M2 ./build/dauntless --developer
```

Useful in-game tools:

- **Developer Options → Combat:** "2× player weapon strength" makes damage
  come quickly. Leave God Mode **off** for any test where your own ship must
  take damage: God Mode skips the lasting damage.
- **H** is Manual Aim: point the mouse at the part of the target you want to
  hit.
- **Load Mission… → Developer** has Damage Preview and Collision Sim.

## 1. The undamaged look is unchanged

- **Where:** any undamaged ship, for example your own Galaxy in Quick Battle,
  or the Akira in Damage Preview before the first blast.
- **Look for:** exactly the look of main: panel shading, glow, specular,
  scorch decals and collision scuffs.
- **Wrong:** any difference on a ship that has not been hit, such as a seam,
  a darker or lighter hull, missing scorch marks, or scuffs that look
  different. The old carve's clip was removed from the stock shader; the
  tests say the undamaged hull renders the same, and this checks it by eye.

## 2. Molten rims on fresh tears

- **Where:** Damage Preview (close-up command). Watch the impulse blasts at
  the rear of the Akira from 3 s in. Also torpedo a ship in Quick Battle and
  zoom in on a fresh hole.
- **Look for:**
  - The edge of a fresh tear glows hot and fades over a few seconds, like
    the old breach rim.
  - Around a **small hole**, the hot area is a **white-hot band**.
  - On a **far wreck**, it reads as a glowing **blob** rather than a ring.
  - Where a tear and a rim overlap, the glow stacks (up to three times as
    bright before bloom). Judge whether that is too hot.
  - The cut **plate's own lip does not glow**: only the torn hull and the
    structure seen through the hole do. Decide whether you want the lip to
    glow too.
- **Wrong:** rims that never fade; rims glowing where there is no hole; a
  rim on a moving part (LC Intrepid nacelle, Bird of Prey wing) glowing
  somewhere other than on that part; flat clipped white that swallows the
  hole. Known and accepted: a rim from a blast inside a moving part may glow
  on the body, or not at all.

## 3. Venting from fresh tears

- **Where:** as item 2.
- **Look for:** gas venting from a hole when it tears open, then stopping.
- **Wrong:** no venting at all, venting from undamaged hull, or venting that
  never stops.

## 4. Interior behind holes, and the switch at 20 GU

- **Where:** Damage Preview. After the blasts, fly toward and away from the
  Akira with impulse.
- **Look for:**
  - Closer than about 20 GU, decks and rooms show behind the holes.
  - Further out, the holes switch to painted wreck damage. The switch should
    be hard to notice.
  - The bridge viewscreen shows rooms only for its target.
- **Wrong:** an obvious pop at the switch; rooms showing through intact
  hull; holes that look empty or see-through to space when close.
- **Tuning:** Developer Options → Hull damage → "Rooms Near Distance" (10,
  15, 20, 30 or 40 GU). "Interior Behind Holes" turns the rooms off for an
  A/B.

## 5. Soot near damage

- **Where:** any damaged ship with big scorch marks (Quick Battle, torpedo a
  ship several times).
- **Look for:** scorch soot is a little lighter right at a hole and blends
  smoothly into the full scorch away from it.
- **Wrong:** a visible ring or circle on a large scorch mark around a hole.

## 6. Authored wreck holes are about half their old size (decision)

- **Where:** Episode 3 Mission 4 (command above): the drifting wrecks are
  built from BC's authored damage scripts. Episode 2 Mission 1 (the damaged
  Karoon) and Episode 6 Mission 2 (the hulks) use them too.
- **Look for:** each authored damage spot is now a hole made by the same
  rule as weapon damage. The holes are about **half the old size or less**:
  a small authored spot that used to be about 0.4 GU is now about 0.175 GU,
  and a large one about 0.35 GU.
- **Decide:** are the wrecks now too lightly damaged? The fix would be a
  size multiplier on authored damage only.
- **Wrong:** wrecks with no visible damage at all, or holes in the wrong
  place on the hull.

## 7. Death blasts vary in size

- **Where:** Damage Preview: let the Akira die, then relaunch and watch
  again. Or kill several large ships in Quick Battle.
- **Look for:** a mix of blast sizes in a death: about half small, a third
  medium and a fifth big.
- **Wrong:** every blast the same size; or big blasts so common the ship is
  hollowed out at once.
- **Tuning:** Developer Options → Hull damage → "Big Death Blast Chance".

## 8. Warp-core breach

- **Where:** a large ship whose warp core breaches in its death (Quick
  Battle against a Galaxy or Sovereign is the likeliest).
- **Look for:** a wound at the core that grows over about one second.
- **Wrong:** no core wound, or one that appears at full size at once.

## 9. A part breaks off in one piece

- **Where:** Quick Battle against a ship larger than a Galor (an Akira,
  Galaxy or Sovereign). Turn on 2× weapons, use Manual Aim (H) and torpedo one
  spot again and again where a part joins the hull, such as a nacelle pylon.
  None of the scripted Damage Preview deaths cut a part off (the timed runs
  checked this), so this has to be done by hand.
- **Look for:**
  - The whole assembly leaves as **one** chunk (a pylon and its nacelle
    together), not a scatter of fragments.
  - Nothing of the lost part is left drawn on the ship.
  - The break line is a smooth curve following the part's shape. That is a
    known limit: the break is not capped or filled.
  - Systems inside the lost part are destroyed.
- **Wrong:** the part shows both on the ship and as a chunk; a chunk with
  nothing visible; two chunks for one part; the game stutters badly when it
  happens. The timed runs found that one break check on a dying Akira took
  at least 8 to 11 ms, all in one frame. That check now runs in the
  background: in the same timed run the game's own share of it fell to well
  under a millisecond (perf register SIG-115). So **any** stutter while a
  big ship comes apart is now worth reporting. Also report a part that
  leaves visibly late after the hit that cut it: the break now lands a
  frame or more after its check.

## 10. Lost parts go dark

- **Where:** as item 9, and also a part shot off a RIGGED ship: an LC
  Intrepid nacelle or a Bird of Prey wing. Both kinds of chunk now go dark
  the moment they leave.
- **Look for:** the chunk has no window lights and no glow.
- **Wrong:** windows still lit on the drifting chunk, of either kind.

## 11. Shadows of lost parts

- **Where:** as item 9, with the sun lighting the ship from the side.
- **Look for:** the ship no longer casts the lost part's shadow onto itself.
  The chunk casts its own shadow.
- **Wrong:** a shadow of the missing part still falling on the hull; the
  chunk casting no shadow.

## 12. Lights on lost parts go out

- **Where:** as item 9: a part with lights on it on an UNRIGGED ship, such
  as an Akira, Galaxy or Sovereign nacelle with its glow lights. That is the
  path this item checks (the structure break). A mod ship with running
  lights shows it most clearly only if it has no rig. The LC Intrepid is
  RIGGED: its nacelle leaves through the rig's own part break, a different
  path, and its lights go out by that rule; worth a look, but it does not
  test this one.
- **Look for:** running lights, glow lights and sparks or smoke on the lost
  part go out when it leaves. Lights on the rest of the ship stay on.
- **Known gap:** a light placed slightly off the hull's skin may stay lit.
  If you see a light hanging in space where the part was, report it. The fix
  is ready: look up the nearest solid part of the hull for that light.
- **Wrong:** lights still floating where the part was; lights on the
  remaining hull going out.

## 13. Cloak

- **Where:** fly a Bird of Prey or a Warbird in Quick Battle, take some
  damage (God Mode off), then cloak.
- **Look for:** when fully cloaked, none of the damage is visible: no holes,
  rooms or glowing rims hanging in space.
- **Known and accepted:** a ship that has lost a part still shows that part
  during the cloak shimmer. Chunks do not take part in the cloak.
- **Wrong:** floating holes, rooms or rims on a cloaked ship.

## 14. LC Intrepid: damage moves with the nacelles

- **Where:** Quick Battle, fly the LC Intrepid as your ship. Let an enemy hit
  your nacelles (God Mode off), then go to warp so the nacelles swing up.
  If "Warp on Heading" does not move them, warp to another system.
- **Look for:** the scorch marks and holes on a nacelle stay on that
  nacelle as it moves, and come back with it.
- **Wrong:** damage left hanging where the nacelle used to be; damage
  sliding across the nacelle; damage showing on the body instead.

## 15. Bird of Prey wings

- **Where:** Quick Battle, fly a Bird of Prey. At red alert the wings sit at
  their modelled position; at green alert they swing to the cruise position.
  Take wing hits at red alert (God Mode off), then go to green alert, and
  back.
- **Look for:** wing damage moves with the wing both ways.
- **Wrong:** damage left in the air or drawn on the body when the wings move.

## 16. Rock craters

- **Where:** Episode 1 Mission 2 (command above). Target an asteroid and
  fire torpedoes and phasers at it.
- **Look for:** craters that look like rock, with a rocky inside and no
  decks, rooms, rims or venting. Big hits on a rock crumble it as before.
- **Wrong:** ship-style damage on rocks (glowing rims, panels, rooms); no
  craters.

## 17. Phasers and collisions wear slowly

- **Where:** Quick Battle (hold phasers on one spot of an enemy) and **Load
  Mission… → Developer → Collision Sim**.
- **Look for:** light phaser fire marks the hull slowly and does not cut
  parts off; a hard collision wears the plating, a light bump does not.
- **Tuning:** Developer Options → Hull damage → "Phaser Wear Rate" and
  "Collision Wear Threshold".

## 18. Developer Options → Hull damage tab

- **Where:** pause → Developer Options… → **Hull damage** tab.
- **Look for:** the rows look like the other tabs; each value row steps
  through five settings and the change shows in the game at once:
  - Plating Strip Wear, Breach Wear, Deck Break Wear;
  - Toughness Spread, Breach Lumps, Soot;
  - Phaser Wear Rate, Collision Wear Threshold, Big Death Blast Chance;
  - Interior Behind Holes (on or off), Rooms Near Distance.
  "Reset hull damage dials" puts them all back. Settings last only for the
  session.
- **Wrong:** a row that changes nothing, a broken layout, or keys still
  reaching the game while the panel has focus.

## 19. Decision at merge time

- An early commit on the branch (`d21f0188a`) holds a picture of an
  undamaged hull made from BC's own pixels. It was removed later, but it is
  still in the branch history. **Decide** whether to squash the branch when
  it merges so those pixels never reach main.
