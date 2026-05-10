# Lore Reference

> Source: Activision/Totally Games *Star Trek: Bridge Commander* PC manual
> (`stbc manual.pdf`, retail print, 2002), specifically the *Introduction*
> framing fiction (pp. 2–5) and the *Starfleet Archival Database*
> (pp. 37–76, accessed at "Level 7 clearance").

This subtree captures the in-universe canon as the manual presents it:
**who** the player commands, **what** they fly, **where** the campaign
is set, and **what just happened** that brings the player to the
captain's chair on day one.

Everything here is canon-as-shipped — the manual's wording, dates,
ranks, and ship registries are reproduced as-printed even when later
*Star Trek* canon (or BC modders' fiction) extended them.

---

## Setting at a glance

- **Year**: 2378 (a few weeks after the surrender of the Dominion).
- **Region**: the **Maelstrom** — a volatile area on the edge of
  Federation, Klingon and Cardassian space, infamous for its triple-
  ambient stellar radiation, subspace tears, and quantum
  destabilisation.
- **Player ship**: USS *Dauntless* NCC-71879, a *Galaxy*-class
  starship nicknamed "**The Seeing Eye**".
- **Home base**: Starbase 12, orbiting New Holland near the Maelstrom,
  commanded by Admiral Alice Liu.
- **Inciting event**: the "Vesuvi incident" of 2378-06-10. The Dauntless
  loses her captain — Captain Robert Wright — and her First Officer
  (the player) takes acting command.

> See [`setting.md`](setting.md) for full background.

---

## Document map

| Folder / file | Contents |
|---|---|
| [`setting.md`](setting.md) | Alpha-Quadrant post-war state, the Maelstrom, the Vesuvi incident, Starbase 12, the classified Sovereign Project. |
| [`characters/`](characters/) | One bio per named officer aboard the *Dauntless*, plus the supporting cast that exists in the manual fiction (Liu, Wright-Serson, Vesuvi colonists, Geordi LaForge, etc.). |
| [`ships/`](ships/) | Per-class ship details for every vessel selectable in Quick Battle / Multiplayer or referenced in the campaign, and details of the named hulls (*Dauntless*, *Sovereign*). Stations included. |

---

## How the manual structures the universe

The manual fictions itself as a "Starfleet Archival Database" the player
is querying with **Level 7 clearance**. Each entry begins with a
"QUERY:" header. We've preserved the spirit of that database while
reorganising for software-reference rather than narrative reading:

- **Crew Records (USS Dauntless)** → [`characters/`](characters/)
- **USS Dauntless NCC-71879** → [`ships/uss-dauntless.md`](ships/uss-dauntless.md)
- **Sovereign Project / Classified** → [`ships/uss-sovereign.md`](ships/uss-sovereign.md) and the engineering notes from Geordi LaForge.
- **Operational Ships and Facilities, Maelstrom** → split by faction across [`ships/`](ships/).
- **Astrometrics, Maelstrom** + **Alpha Quadrant, Recent History** → [`setting.md`](setting.md).
- **Admiral Liu, Letter of Condolence** → [`characters/captain-wright.md`](characters/captain-wright.md) and [`characters/supporting-cast.md`](characters/supporting-cast.md).

---

## Conventions used here

- **Stardate/Earth date**: dates are quoted in the form the manual uses
  (Earth Gregorian, e.g. `1/25/2378`, or "Stardate 47457.1" where
  applicable).
- **Specifications**: ship specs are reproduced exactly as printed —
  displacement (metric tons), length/draft/beam (m), warp speeds, crew
  complement, phasers/torpedoes/shield ratings on six faces, hull rating.
- **"Manual silent on …"** — wherever this phrase appears, it means the
  manual does not state that fact; the doc deliberately doesn't invent
  one.
- **Ranks** appear as printed in the manual at the time of writing
  (e.g. Brex is *Lt. Commander* despite his many years of service —
  he is enlisted-promoted-to-NCO/officer track, see his bio).
