# Power System (Player-Facing Model)

The energy economy of a Federation starship as the *Bridge Commander*
manual presents it to the player. This is the **intent** spec — what
the player sees, what the manual tells them to do, what trade-offs the
designers wanted them to feel.

> **Pair with**: [`ship-subsystems.md` § Power and reactor](ship-subsystems.md#power-and-reactor)
> for the implementation side (vtables, Update functions, EPS
> distribution math). This file describes *what* the engine has to
> reproduce; that file describes *how* the original engine did it.

> **Source**: manual pp. 16–20 (Engineering / Power Transmission Grid),
> p. 17 (Special: Tractor / Cloak), p. 24 (HUD displays).

---

## Three reservoirs and one producer

Every Federation hull has the same four-element power layout:

```
   ┌──────────────┐    when usage < production:
   │  Warp Core   │────►  surplus charges Main Battery, then Reserve
   │  (producer)  │
   └──────┬───────┘    when usage > production:
          │              ↓ Main Battery is drained (yellow band)
          ▼              ↓ then Reserve Battery (red band)
   ┌──────────────────┐
   │  Main Battery    │  always-on secondary reservoir
   ├──────────────────┤
   │ Reserve Battery  │  hard-cap "deepest" reservoir
   └──────────────────┘
          │
          ▼
   ┌──────────────────────────────────────────────┐
   │ Loads (Power Allocation Sliders, 0–125%):    │
   │   • Weapons                                   │
   │   • Engines                                   │
   │   • Sensor Array                              │
   │   • Shield Generator                          │
   │   • Tractor Beam (drains Main directly)       │
   │   • Cloak (drains Reserve directly; ship-     │
   │     conditional, MP/QB only)                  │
   └──────────────────────────────────────────────┘
```

### Warp Core

The single producer.

- Output **scales with damage**: as the Warp Core takes hits, its
  ability to produce power is reduced (visible on the Power Used Bar
  shifting into yellow / red bands).
- **Reaching 0% causes a warp-core breach and destroys the ship.**
- When damage drops production, the engine **may auto-rebalance** the
  Power Allocation Sliders to fit the reduced budget. (Manual: *"if
  you take damage to the Warp Core, your power settings may be
  automatically adjusted to account for reduced warp core capacity."*)

### Main Battery

The always-on secondary reservoir.

- Drains when total load > Warp-Core production.
- Recharges when total load < production.

### Reserve Battery

The deep reservoir.

- Drains *only* when Main is also being drawn (the Power Used Bar has
  spilled all the way past the yellow band into the red band).
- Has a hard ceiling — *"You cannot draw any more power once your
  reserve capacity is fully utilized and the bar reaches the far right
  of the frame."*

---

## The Power Used Bar — three-band semantics

A single horizontal bar showing total system draw. Its surrounding
frame is colour-banded so the source of the power is visible at a
glance:

| Frame band | Meaning |
|---|---|
| **Blue** | Within Warp-Core production. Bar inside this band ⇒ batteries are charging. |
| **Yellow** | Bar has spilled past Warp-Core production into Main-Battery draw. |
| **Red** | Bar has spilled all the way past Main into Reserve-Battery draw. |

Shorthand for any UI-reimplementation:

```
load <= warp_core_output            → bar in BLUE   → charging
warp_core_output < load <= MaxMain  → bar in YELLOW → drawing Main
MaxMain < load <= MaxReserve        → bar in RED    → drawing Main + Reserve
load > MaxReserve                   → unreachable; bar pinned at right
```

Where `MaxMain` is `warp_core_output + main_battery_drain_rate`, and
`MaxReserve` is `MaxMain + reserve_battery_drain_rate`. The manual
does not give numeric drain rates; those are engine constants (see
[`ship-subsystems.md`](ship-subsystems.md)).

---

## Power Allocation Sliders

Per-system controls in the Engineering panel. Each slider has the
range **0% – 125%**, with **100% = nominal capacity**.

| Slider | Higher (toward 125%) | Lower (toward 0%) |
|---|---|---|
| **Weapons** | Phasers charge faster; torpedoes reload faster. | Phasers/torpedoes charge/reload slower. |
| **Engines** | Ship turns more responsively; max impulse speed up. | Sluggish turning; lower top speed. |
| **Sensor Array** | Longer effective sensor range; **objects appear on the Target List from further away**. | Shorter range; contacts drop off the Target List sooner. |
| **Shield Generator** | Faster shield-face recharge rate. | Slower recharge. |

### The 125% rule

The manual is explicit: *"100% is the normal capacity for each system,
although you can boost all the way up to 125% if necessary. **There
are no ill effects from doing so, except for the increased power
draw.**"*

**Implication for any engine reimplementation**: the 125% boost should
not introduce damage / wear / overheat / heat-state of any kind. It
purely costs more from the reservoirs.

The manual qualifies it: *"This extra capacity should be used
carefully, since the higher drain could leave you without battery
power at an awkward moment."* — i.e. the cost is opportunity cost on
the batteries, not material cost to the ship.

---

## Tractor and Cloak — direct-from-battery loads

These two systems do **not** appear as Power Allocation Sliders.
Instead they're toggles that draw directly from a specific reservoir
when active:

| System | Draws from | Available on |
|---|---|---|
| **Tractor Beam** | **Main Battery** | All Federation hulls (any mode) |
| **Cloak** | **Reserve Battery** | Only ship classes equipped with cloak — multiplayer / Quick Battle only |

Both appear as `On / Off` indicators in the Engineering panel and as
toggles on Felix's *Weapons* sub-panel.

### Tractor Beam mechanics

- Locks only when a target is in range and **fore or aft** of the ship.
- While held, the target's manoeuvring is impeded.
- Continuously drains the Main Battery; long holds will deplete it.

### Cloak mechanics

- While cloaked, **shields go offline** *and* **weapons cannot fire**.
- Player ship doesn't appear on enemy Target Lists.
- Phasers cannot lock onto a cloaked vessel.
- Continuously drains the Reserve Battery.

---

## Alert states drive baseline draw

The First Officer's alert toggles change the baseline power state of
the ship — they're the player's coarse-grained "how hot is everything
running" control:

| Alert | Shields | Weapons | Battery state |
|---|---|---|---|
| **Green** | Down (powered off) | Down (powered off) | **Recharging.** Non-aggressive posture; everything safe to recharge. |
| **Yellow** | **Up** (raised) | Down | Stable: shield draw modest enough that the Warp Core can usually keep up. |
| **Red** | Up | Up | **Drains continuously while idle** — manual: *"At Red Alert you will begin draining battery power."* |

Practical consequence: **don't sit at Red Alert when not in combat**.
Drop to Green between fights to recharge.

---

## Power-management decision tree (manual-derived)

The manual's "Power Usage Tips" (p. 20) compress to:

```
Is the ship sluggish, or are contacts dropping off the Target List?
├─ Yes → Check Power Allocation
│         ├─ Warp Core damaged? → expect reduced budget; rebalance
│         └─ Bar in yellow/red? → either reduce loads or boost a
│                                  specific slider deliberately
└─ No  → keep doing what you're doing.

Are you in active combat?
├─ Yes → Red Alert. Consider boosting:
│         ├─ Weapons + Shields if trading hits
│         ├─ Engines if the enemy is faster
│         ├─ Sensors if you need longer-range targeting / scanning
│         (or pull from a slider you don't currently need)
└─ No  → Green Alert. Let batteries recharge.

Is a battery actively draining (Power Used Bar in yellow or red)?
├─ Yes → assess: is the drain because Warp Core is damaged, or
│         because you've boosted/cloaked/tractored?
│         ├─ Warp Core damaged → prioritise repair (Brex/F5)
│         └─ Boost/cloak/tractor → it's voluntary; let go when safe
└─ No  → batteries are charging (or steady).

Did you take Warp Core damage?
└─ Yes → batteries will drain faster even at the same load.
         Rebalance loads downward; expect auto-rebalance.

Need to fully replenish?
└─ Dock at a starbase (LoMar/F1 → Dock at SB12).
```

---

## Combined-system interactions worth noting

### Cloak ⇒ no shields ⇒ no weapons

The cloak isn't just a power drain; it's an *operational mode swap*.
The ship loses **both** shielding and weapons capability for as long
as the cloak is engaged. Consequence: cloak is a stealth/repositioning
tool, never a combat tool. (No "fire while cloaked" — the wartime
cloaked-photon-launch feat in Klingon hulls is documented as
exceptional, see [`../lore/ships/klingon-classes.md`](../lore/ships/klingon-classes.md#brel-class-bird-of-prey).)

### Tractor ⇒ unavoidable Main Battery cost

Tractor is one of the few non-combat tools that draws directly from a
finite reservoir during use. Long tractor holds risk leaving Main
empty when combat starts — the manual flags this explicitly.

### Boosted Sensor Array ⇒ longer Target List

Boosting Sensor Array power **doesn't only extend scanning range —
it extends the range at which contacts appear on the Target List**.
This makes Sensor Array boost a **targeting** decision, not just a
detection one: at high Sensor Array power, distant contacts become
selectable as targets earlier in the engagement.

### Auto-rebalance on Warp Core damage

When the Warp Core takes damage, the engine may auto-redistribute
slider values downward to fit the reduced budget. The manual says
"may" — implying it's a guard-rail, not an unconditional rule. A
reimplementation should either:

- (a) reproduce auto-rebalance behaviour faithfully, or
- (b) document its absence and let the player rebalance manually.

The original engine's exact rebalance algorithm is in
[`ship-subsystems.md`](ship-subsystems.md#power-and-reactor).

---

## Recharge vs. resupply

| Action | Recharges what |
|---|---|
| Drop to **Green Alert** (no boosts, no cloak/tractor) | Batteries refill from Warp-Core surplus. |
| Reduce Power Allocation Sliders below production | Batteries refill from Warp-Core surplus. |
| **Dock at a starbase** (Starbase 12 via LoMar's *Dock*) | Batteries replenished + **Destroyed** systems repaired + torpedo magazines restocked. |

Docking is the only path to repair a *Destroyed* system (Brex's
*Destroyed Systems* list). Battery and ammo are the bonuses.

---

## See also

- [`../ui/bridge-mode.md` § Engineering (Brex) menu](../ui/bridge-mode.md#engineering-brex-menu--f5) — the panel layout the player operates this through.
- [`../ui/tactical-mode.md` § Phaser Arc / Torpedo Display](../ui/tactical-mode.md#phaser-arc--torpedo-display-lower-right) — how Weapons-slider power expresses on-screen.
- [`ship-subsystems.md` § Power and reactor](ship-subsystems.md#power-and-reactor) — implementation pair for this document.
- [`combat-and-damage.md`](combat-and-damage.md) — how Warp-Core damage is delivered.
