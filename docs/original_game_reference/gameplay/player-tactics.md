# Player Tactics (Manual's Combat Doctrine)

The combat advice the *Bridge Commander* manual gives the player.
This is the **intent** layer: how the designers expected combat to be
read, prioritised, and resolved at the captain's level.

> **Pair with**: [`combat-and-damage.md`](combat-and-damage.md) for the
> implementation side (the `DoDamage`/`ProcessDamage` pipeline,
> shield/subsystem absorption math, weapon-hit handling). This file
> answers *"what should the player do?"*; that file answers *"what
> does the engine do when they do it?"*.

> **Source**: manual pp. 21–26 ("Combat" section), with cross-pulls
> from p. 11 (alert states), p. 14 (manoeuvres / tactics), p. 17
> (power management), p. 24 (HUD reading).

---

## The core mental model

The manual frames starship combat as **a graceful dance of death
between deadly giants** — not a starfighter dogfight, not a static
artillery duel, but more like **submarine warfare with line-of-sight
weapons**. Two ideas drive every other tip:

1. **Always face the enemy with your strongest shield while bringing
   your most-charged weapons to bear.** The whole game of combat is
   continually orienting the ship to do both at once.
2. **Distance and timing are weapons.** Phasers fall off with range;
   torpedoes track better at range. Whichever weapon you want to use
   dictates whether you should be closing, holding, or separating.

> *"Effective combat manoeuvres involve continually orienting your
> ship to protect your weakest shields, while at the same time
> bringing your most powerful weapons to bear."* — manual p. 21.

---

## Distance management

Every weapon has a different distance preference:

| Weapon | Best at | Worst at |
|---|---|---|
| **Phasers** | **Close range** — beam weapons do reduced damage at greater distances. | Long range. |
| **Torpedoes (firing)** | **Long range** — torpedoes track their targets more effectively from a distance. | Close range — easier to evade. |
| **Torpedoes (evading)** | **Long range** — outside tracking range, you can dodge cleanly. | Close range — incoming torpedoes track too well to evade. |

> *"Stations generally have the greatest range of damage."* — manual
> p. 22. Read: stations out-range you on phasers; engaging one needs
> a different distance plan than engaging a ship.

Range falloff varies *per ship class* — there is no single "phaser
range"; consult the per-class stats in
[`../lore/ships/`](../lore/ships/) for relative values.

### Felix's distance manoeuvres map cleanly to this

The Tactical menu's *Manoeuvres* sub-options encode the distance
choice as orders:

| Order | Use when |
|---|---|
| *At Will* | Felix picks distance based on the situation. |
| *Close Distance* | You want phaser-DPS pressure. |
| *Maintain Distance* | You're holding torpedo range while letting Felix line up. |
| *Separate Distance* | You want torpedo-tracking advantage; or you're disengaging. |

See [`../ui/bridge-mode.md` § Tactical (Felix) menu — Manoeuvres Menu](../ui/bridge-mode.md#tactical-felix-menu--f2).

---

## Torpedo-evasion technique

The manual's specific instruction (p. 21):

> *"As soon as your enemy fires torpedoes, it is a good idea to
> increase speed and turn the nose of your ship in the perpendicular
> direction. Continue to direct your ship perpendicular to the
> torpedo's trajectory. You cannot expect to evade them all, so if
> you must take a hit be sure it is on a stronger shield."*

Procedure for evading torpedoes:

1. Detect the launch (Sensors panel — torpedoes have differentiated
   icons).
2. Increase speed (`1`–`9`, mouse-wheel, or boost Engine power).
3. Turn perpendicular to the torpedo's trajectory (WASD/Q/E; or
   Felix's *Evade* toggle).
4. Hold perpendicular until the torpedo passes or impacts.
5. **If a hit is unavoidable**, position so the impact lands on your
   strongest face — see [Shield rotation](#shield-rotation-keep-the-strong-face-toward-the-enemy).

A higher Engines power slider (Brex's panel) directly improves the
turn rate that makes step 3 possible.

---

## Offensive priorities — pick a strategy *before* engaging

Two doctrines, picked situationally:

### 1. Subsystem-first

Take down individual subsystems via the Target List drill-down rather
than blindly trading hits with the hull.

| Their subsystem | Your benefit |
|---|---|
| **Weapons** | Stops their offence; they can still manoeuvre / cloak / sense. |
| **Engines** | Handicaps their manoeuvring; they become easier prey. |
| **Sensors** | They can no longer target you. |
| **Cloak** | Strips concealment. |
| **Shield Generator** | Shield faces stop recharging — easier follow-up kills. |
| **Tractor** | Removes their ability to lock you in place. |

Subsystem targeting is **most effective once shields are down or
weakened on the face nearest that subsystem** (per the Phaser
Intensity rule below).

### 2. Shield-strip-first

Ignore subsystems initially; focus all fire on **a single shield
face** until it's depleted, then go for hull damage / specific
subsystems through the gap.

> *"Try to work down a particular shield instead of spreading your
> fire across all sides of an enemy."* — manual p. 22.

This is the conventional dps choice. It's also the one Felix's
*Tactics* sub-options most directly support:

| Felix tactic | Reads as |
|---|---|
| *Left Phaser Attack* / *Right Phaser Attack* | Bring left or right phaser arrays onto the target — useful when you've identified a weak face on a specific side. |
| *Fore Attack* | Concentrate fore phasers + fore torpedoes. |
| *Aft Attack* | Use rear torpedoes — disengaging or running fight. |
| *Top Shields* / *Bottom Shields* | Felix manoeuvres so your dorsal/ventral face stays toward the target. |
| *At Will* | Felix picks. |

### Phaser Intensity choice

| Intensity | When to use |
|---|---|
| **Full** | Standard offensive mode. Max DPS. Drains the Weapons reservoir fastest. |
| **Low** | Disabling without destroying. Less DPS but lower drain — fires longer per battery cycle. |

The manual flags two specific Low-Intensity rules:

- *"Low Intensity phasers do not generally damage the hull of your
  target and are therefore safer to use than Full when disabling
  ships you do not wish to destroy."* — but **only if you've targeted
  a particular system or subsystem**. Without a subsystem target,
  Low Intensity *will* damage hull.
- *"Low Intensity phasers can be more effective for damaging
  subsystems, provided the target's shields are disabled or in a
  weakened state."*

Practical reading: Low Intensity is the *surgical* mode. Use it once
shields are down (or against a specific subsystem) to disable
without escalating the engagement to lethal. Full Intensity is the
sledgehammer.

---

## Defensive priorities

### Shield rotation — keep the strong face toward the enemy

The single most-emphasised defensive technique in the manual. Repeated
twice (p. 22, p. 24):

> *"As a good Captain, you should constantly rotate the shields
> facing the enemy in order to prevent any single shield from being
> depleted completely. In addition, your ship will begin to take
> damage as weapons energy begins to bleed through weakened shields."*

How to do it:

- **Manual flight (Tactical Mode)**: WASD/Q/E to turn the ship as
  you take fire.
- **Delegated**: Felix's *Top Shields* / *Bottom Shields* tactics
  command keeps a specific dorsal/ventral face toward target;
  *Maintain Distance* + *Evade* will likewise keep him manoeuvring.

The HUD pieces that drive this decision:

- **Shields panel** (lower edge) — six-face health.
- **Phaser Arc / Torpedo Display** (lower-right) — the transparent
  blue/grey indicator between ship icon and phaser strip shows
  *which arc the target is in*; rotating moves the target between
  arcs. (No indicator = blind spot.)
- **Sensors panel** (lower-left) — bracketed contacts are firing on
  you.

### Repair triage

When systems take damage, prioritisation matters more than letting
Brex auto-assign in damage-arrival order. Click a *Damaged Systems*
row to promote it to top of the queue.

Manual-recommended priorities (p. 22):

- **Shields > weapons** when severely damaged.
- **Phasers > torpedoes** in some situations — depends on what fight
  you're in.
- (Implicit) **Warp Core** if it's taking hits — warp-core damage
  reduces production for *everything* and accelerates battery drain.

The general rule: repair what's hurting you most *right now*, not
what's least damaged.

### Power-bias in combat

Power can shift mid-engagement. Manual examples:

- **Heavier weapons + shields, lighter sensors** in difficult fights.
- **Boost engines vs. faster opponents** (so your turn rate matches
  theirs).
- **Boost sensors** if you need long-range targeting / scanning.

Boost up to **125% on any slider** — the manual is explicit there are
no ill effects beyond the increased drain. See
[`power-system.md` § The 125% rule](power-system.md#the-125-rule).

### Increase distance vs. phaser pressure

Manual: *"Increase the distance between yourself and your enemy if
they are wearing you down with phaser fire. All phasers do reduced
damage at greater distances."* — p. 22.

This is the inverse of the Distance Management table: when *you* are
absorbing phaser fire, opening range is a defensive move; when you're
delivering it, closing is the offensive move.

---

## Reading the HUD in combat

A practical "what panel tells me what" lookup for combat:

| Question you have | Panel to read |
|---|---|
| Where are my enemies? | **Sensors** (lower-left) |
| Who's firing on me? | **Sensors** — bracketed contacts. |
| Which torpedoes are inbound? | **Sensors** — type-differentiated icons. |
| What's my own shield state? | **Shields** (lower edge) — colour per face. |
| What's the enemy's shield state? | **Target Shields** (upper-left, when target selected). |
| Is my phaser ready? Which arc? | **Phaser Arc display** (lower-right) — colour per strip + blue/grey arc indicators. |
| Are torpedoes loaded? | Torpedo dots near bow/stern of ship icon (lower-right). |
| What's the enemy's subsystem damage? | **Target Shields** — damage icons on the ship image. |
| Am I in a phaser blind spot? | **Phaser Arc display** — *no* blue/grey indicator means no arc covers the target. |

For per-panel detail see [`../ui/tactical-mode.md`](../ui/tactical-mode.md).

---

## Decision flow — what to do, in order

Compressed playbook for a single engagement:

```
1. Detect.
   Sensors panel + Target List. Pick a primary target.

2. Decide doctrine.
   Subsystem-first or shield-strip-first?
   → Subsystem when you need the enemy disabled, not destroyed,
     or to neutralise a specific threat (e.g. their cloak).
   → Shield-strip when you simply need to win.

3. Choose distance.
   → Phasers? Close.
   → Torpedoes? Hold range.
   → Disengaging? Open range fast.

4. Choose intensity.
   → Full for damage; Low for disabling once shields are down.

5. Order Felix.
   Manoeuvres (Close / Maintain / Separate / At Will)
   + Tactics (which face / which weapons)
   + Orders (Destroy / Disable / Stop / Evade)
   + Targets drill-down (which subsystem if any).

6. Manage power.
   Red Alert; bias Weapons + Shields up; Engines up if outpaced.

7. Rotate the ship.
   Always face the strong shield toward the threat.

8. Triage repairs.
   Promote whatever is hurting you most.

9. When the fight ends, drop to Green Alert and recharge.
```

---

## Behaviours that trip players up

Reading these together makes the gameplay coherent; missing them
makes combat feel arbitrary.

- **Issuing any order to Felix from Tactical Mode hands the conn back
  to him.** You stop flying. To take direct flight back, press a
  flight key.
- **Manual Fire mode** — `H` toggles a cursor reticle. The cursor is
  now your aim point; placement on a hull region picks a subsystem
  target. Felix retains piloting if you've ordered him to.
- **At Red Alert idle, you drain batteries.** Don't sit there.
- **Cloak ⇒ no shields, no weapons.** It's a stealth/repositioning
  tool, not a combat tool.
- **The 125% slider boost is free of side-effects.** Use it
  aggressively *up to* what your batteries can sustain.
- **Probes extend sensor range and survive your own Sensor Array
  loss** — Miguel's *Launch Probe* is more than a passive scanner.
  (Single-player and Quick Battle only — not in MP.)
- **Phaser arcs**: if no blue/grey indicator points from your ship
  image to the strip, you're in a blind spot. Turn the ship.
- **Stations out-range you.** Don't engage one with the same distance
  plan you'd use against a frigate.

---

## See also

- [`combat-and-damage.md`](combat-and-damage.md) — implementation pair (damage pipeline, shield/subsystem absorption).
- [`power-system.md`](power-system.md) — the energy economy that powers all of this.
- [`ship-subsystems.md`](ship-subsystems.md) — subsystem inventory + damage states.
- [`../ui/tactical-mode.md`](../ui/tactical-mode.md) — HUD layout reference.
- [`../ui/bridge-mode.md` § Tactical (Felix) menu](../ui/bridge-mode.md#tactical-felix-menu--f2) — full Felix order tree.
- [`../lore/ships/`](../lore/ships/) — per-class shield/hull ratings, weapon loadouts, and faction tactical notes.
