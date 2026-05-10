# Multiplayer Scoring

How frags translate into points across the four multiplayer game types,
and the asymmetric ship-class weighting that makes a *Marauder*-kills-
*Sovereign* worth more than the reverse.

> **Source**: manual pp. 30–31 ("Game Types"), p. 28 ("Network Minimum
> System Requirements"), and the Host Game / Ship Select rules on
> p. 29–30.

> **Pair with**: [`../ui/quick-battle-and-multiplayer.md`](../ui/quick-battle-and-multiplayer.md)
> for the screens that surface these rules; [`../networking/transport-and-sessions.md`](../networking/transport-and-sessions.md)
> for the wire protocol that carries score updates.

---

## The two end-condition axes

For every game type the host picks one (or both) of:

| Axis | Behaviour |
|---|---|
| **Time limit** | Match ends when the timer expires. |
| **Score / frag limit** | Match ends when a player or team reaches the threshold. |

Whether the threshold is *score* (weighted points) or *frags*
(unweighted kill counts) **depends on the game type** — see the
per-mode tables below. This is the manual's most consequential
gameplay rule for MP and is easy to overlook.

---

## The asymmetric ship-class weighting rule

The single rule that runs through Deathmatch, Team Deathmatch and UFP
vs. Non-UFP:

> *"While you may be tempted to always choose the strongest ship, you
> will not get as many points for a kill when a stronger ship destroys
> a weaker vessel. However, you will get more points if a weaker ship
> (e.g. a Ferengi Marauder) defeats a stronger ship (e.g. a Federation
> Sovereign class). As a result, the number of kills alone will not
> necessarily determine battles, as the game will assess points based
> on the relative values of the ships destroyed."* — manual p. 30.

Practical reading:

```
points_awarded(killer, victim) = f( relative_value(victim) ,
                                    relative_value(killer) )

where f is monotonically:
   • higher when victim is stronger relative to killer
   • lower  when victim is weaker  relative to killer
```

The manual does not publish the exact formula, the per-class strength
weights, or whether the function is multiplicative, ratio-based, or
table-driven. A faithful reimplementation will need to extract this
either from observation or from the original `stbc.exe` scoring code.

What's documented:

- Ship "value" is **per-class**, not per-equipment / per-loadout.
- The *Sovereign* class is given as the canonical "strong" example.
- The *Ferengi Marauder* (D'Kora class) is given as the canonical
  "weak" example.
- The relative-value gap between those two is large enough that
  manual flags it as the headline trade-off.

> Class-by-class shield ratings, hull ratings and weapon loadouts are
> listed in [`../lore/ships/`](../lore/ships/) — they are the most
> obvious signal for what "value" means here.

---

## Game-type-by-game-type behaviour

### Deathmatch

Free-for-all. Any ship class is selectable.

| Field | Value |
|---|---|
| **Teams** | None — every player is on their own. |
| **Allowed ships** | Any class in the catalogue. |
| **Scoring** | Weighted by ship-class disparity (see above). |
| **End condition** | Time limit *or* score limit (host's choice). |
| **When score limit set** | **Points are more important than frags** (manual phrasing). |

### Team Deathmatch

Two teams; either side may pick any ship.

| Field | Value |
|---|---|
| **Teams** | Two; players pick a side at the lobby. |
| **Allowed ships (each team)** | Any class. |
| **Scoring** | Weighted by ship-class disparity (same as Deathmatch). |
| **End condition** | Time limit *or* score limit. |
| **When score limit set** | Points are more important than frags. |

### UFP vs. Non-UFP Deathmatch

Asymmetric two-team mode constrained by faction.

| Field | Value |
|---|---|
| **Teams** | UFP vs. Non-UFP. |
| **UFP-team ships** | Any **Federation** vessel — including a **Shuttle**. (The Shuttle is *only* selectable in this mode.) |
| **Non-UFP-team ships** | Any **non-Federation** ship in the game (Klingon, Romulan, Ferengi, Cardassian, Kessok). |
| **Scoring** | Weighted by ship-class disparity (same as Deathmatch). |
| **End condition** | Time limit *or* score limit. |
| **When score limit set** | Points are more important than frags. |

### Defend the Starbase

Asymmetric attack/defend with a starbase as the protected target.

| Field | Value |
|---|---|
| **Teams** | Attackers vs. Defenders. |
| **Allowed ships (each team)** | Any class. |
| **Scoring** | **Frag count** — *not* the weighted ship-disparity score. |
| **End condition (a)** | **Time limit** — defenders win if time expires before the starbase is destroyed. |
| **End condition (b)** | **Frag limit on the defending team's kills of attackers** — defenders win if attackers are killed enough times. |
| **Attacker win** | Destroy the starbase before either limit ends the match. |
| **Manual phrasing on score vs. frags** | *"Kills are more important than score."* |

> Defend-the-Starbase is the **only** game type in which the asymmetric
> ship-class weighting **does not apply**. Counted as raw kills.

---

## End-condition matrix at a glance

| Mode | Time limit can end the match? | Score limit can end? | Score = points or frags? |
|---|---|---|---|
| Deathmatch | yes | yes | **points (weighted)** |
| Team Deathmatch | yes | yes | **points (weighted)** |
| UFP vs. Non-UFP | yes | yes | **points (weighted)** |
| Defend the Starbase | yes (defender wins) | yes (defender's kill count) | **frags (unweighted)** |

---

## Network capacity tiers (host-side responsibility)

The host's connection determines how many players can join.

| Host's connection | Max players |
|---|---|
| 28.8k modem | **3** |
| 33.6k modem | **4** |
| 56k modem with **dedicated server** | **4** |
| LAN / broadband | **5–8** |

Implications for any reimplementation:

- The 4 / 8 ceiling suggests two distinct net-tier code paths in the
  original. Confirmable against
  [`../networking/transport-and-sessions.md`](../networking/transport-and-sessions.md)
  for the actual transport behaviour.
- The dedicated-server option is the one that gets the host past the
  4-player ceiling on modem (because the host stops trying to also
  *play*).

### Dedicated Server mode

The host is on the *Host Game* screen. When *Dedicated Server* is
ticked:

- The host **does not play** in the match.
- The host **can view scores live**.
- The host **can boot unruly players**.

This is the only non-modder route to active in-match moderation
documented in the manual.

---

## Score-window UI

Each player can toggle their **Score Window** on with `[`. (The Chat
Window is `]`, Team Chat input is `\` — see [`../ui/keyboard-mouse-reference.md`](../ui/keyboard-mouse-reference.md#miscellaneous-commands).)

The manual does not document the score-window's columnar layout.
Behaviourally it must minimally show:

- Each player (or team) and their current points / frags total.
- For modes with score limits, the threshold.
- For modes with time limits, the remaining time (or the host's chat
  output reflecting it).

A reimplementation has freedom on the exact layout.

---

## Reimplementation checklist

If you're rebuilding this scoring layer, the rules to verify:

- [ ] Frag with weighted score (DM / Team DM / UFP vs. Non-UFP) —
      stronger-victim-vs-weaker-killer awards more, weaker-victim
      awards less. Source-of-truth for class weights is *not* in the
      manual; extract from `stbc.exe`.
- [ ] Frag with unweighted score (Defend the Starbase) — points = 1
      per kill regardless of class.
- [ ] End-condition disjunction: **either** time-limit **or** score/
      frag-limit ends the match. Hosts may set both; whichever fires
      first.
- [ ] UFP vs. Non-UFP — Federation Shuttle is selectable in this mode
      only.
- [ ] Player-count ceilings: enforce per-tier (3 / 4 / 4 dedicated /
      5–8 LAN).
- [ ] Probe restriction: probes cannot be launched in any MP mode (per
      [`../ui/quick-battle-and-multiplayer.md` § Probes are restricted in MP](../ui/quick-battle-and-multiplayer.md#probes-are-restricted-in-mp)).
- [ ] Cloak availability: only enabled in MP (and Quick Battle), only
      on classes equipped with cloak.
- [ ] Dedicated-server mode: host plays no ship, sees the score
      stream, can kick players.

---

## See also

- [`../ui/quick-battle-and-multiplayer.md` § Game Types](../ui/quick-battle-and-multiplayer.md#game-types) — the lobby / Ship Select view of these rules.
- [`../networking/transport-and-sessions.md`](../networking/transport-and-sessions.md) — wire-protocol pair.
- [`../lore/ships/`](../lore/ships/) — per-class shield/hull/weapon ratings (the obvious raw input for "ship value" weighting).
