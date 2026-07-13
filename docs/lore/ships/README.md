# Ships and Stations

Per-class technical and lore details for every vessel and station the
manual catalogues, plus the named hulls central to the campaign.

> Source: manual, *Operational Ships and Facilities, Maelstrom*
> (pp. 59–76); *USS Dauntless NCC-71879* (p. 39); *Sovereign Project /
> Classified* (pp. 53–58).

---

## Two named hulls

| File | Hull | Class | Role in the campaign |
|---|---|---|---|
| [`uss-dauntless.md`](uss-dauntless.md) | **USS *Dauntless* NCC-71879** | *Galaxy* class | The player's ship. "The Seeing Eye." |
| [`uss-sovereign.md`](uss-sovereign.md) | **USS *Sovereign* NX-73811** | *Sovereign* class (refit) | Currently being refit in the Vesuvi system; classified, Captain's Eyes Only. |

These are not ship *classes* — they are the specific hulls — because
they have their own dedicated histories.

---

## Class catalogue (selectable in QB / MP and seen in mission)

| File | Faction | Classes covered |
|---|---|---|
| [`federation-classes.md`](federation-classes.md) | Federation | *Akira*, *Ambassador*, *Galaxy*, *Nebula*, *Sovereign* |
| [`klingon-classes.md`](klingon-classes.md) | Klingon Empire | B'rel-class Bird of Prey, *Vor'cha* attack cruiser |
| [`romulan-classes.md`](romulan-classes.md) | Romulan Star Empire | *D'Deridex* warbird |
| [`cardassian-classes.md`](cardassian-classes.md) | Cardassian Union | *Galor* attack cruiser, *Keldon* warship |
| [`ferengi-classes.md`](ferengi-classes.md) | Ferengi Alliance | *D'Kora* marauder |

---

## Stations

[`stations.md`](stations.md) — Federation Starbases, Federation
Outposts, Regula-series space facilities, drydocks, and Cardassian
Starbase / Station / Outpost classes.

---

## Conventions

The spec tables below reproduce the manual's print figures verbatim:

- **Displacement** in metric tons.
- **Overall length / draft / beam** in metres.
- **Velocity**: standard cruising / max cruising / max attainable warp.
- **Complement**: officer / enlisted / passenger split + total
  standard crew.
- **Phasers / Torpedoes / Special**: weapons loadout descriptions used
  by the manual.
- **Shield Ratings**: a six-tuple — *Fore / Aft / Dorsal / Ventral /
  Port / Starboard*.
- **Hull Rating**: scalar.

Where the manual writes **UNKNOWN** in the *Shields* row (e.g. for
Romulan and Cardassian hulls), it's preserved as-printed.

The shield-rating six-tuple corresponds to the same six faces shown on
the in-game **Shields** HUD panel. See
[`../../ui/tactical-mode.md` § Shields panel](../../ui/tactical-mode.md#shields-panel-lower-edge).

Hull Rating and the per-face Shield Ratings are the relative numbers
the engine's combat math uses; the gameplay docs in
[`gameplay/`](../../gameplay/) cover the mechanics they feed.

---

## Notable design observations from the manual

- **Akira class** was purpose-built for combat, breaking Starfleet's
  exploration charter. Three were lost to Cardassian orbital weapons
  platforms in Chin'toka.
- **Galaxy class** is so expensive that **fewer than 15 hulls were
  ever built**. *Dauntless* is the third hull of the class (after
  *Galaxy* NCC-70637 and *Yamato* NCC-71807).
- **Nebula class** was designed as a cheaper *Galaxy*-alternative.
  Highly modular dorsal equipment module configurable for combat or
  research roles.
- **Sovereign class** introduced regenerative shielding, ablative hull
  armour, bio-neural gel packs (anti-Borg tech). The prototype
  *Sovereign* NX-73811 was shelved; *Enterprise-E* shipped with
  conventional shields/deflector but inherited many other innovations.
- **Vor'cha class** is the largest Klingon hull short of the
  *Negh'Var*; built originally to counter the Federation, later
  proved valuable as a command ship vs. the Dominion.
- **D'Deridex (Romulan Warbird)** is **nearly twice the length of a
  *Galaxy*-class** but slightly less manoeuvrable, with mostly forward-
  firing armament — Romulans favour frontal attacks.
- **Galor class** is now treaty-restricted from production — the
  Cardassian surrender forbids warship build-up. Hulls in service
  patrol the Federation/Cardassian border and the Maelstrom.
- **Keldon class** is the larger, more powerful *Galor* variant —
  also treaty-banned post-Dominion-War. Was the basis of the Obsidian
  Order's secret Orias-system fleet.
- **D'Kora (Ferengi Marauder)** is a trader first, warship second —
  but a capable warship when it has to be, with a high-power ventral
  phaser beam and plasma emitters that have been observed disabling
  *Galaxy*-class hulls.
