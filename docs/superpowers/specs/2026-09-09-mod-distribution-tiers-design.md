# Mod Distribution Tiers — Design

**Status:** approved, partially implemented (tier 1 exists; tier 2 not started)
**Date:** 2026-09-09
**Related:** `2026-09-08-mod-overlay-design.md`, `2026-09-09-foundation-compatibility-design.md`

## The decision

Mods reach dauntless by two routes, with **different promises**.

| | Tier 1 — sideload | Tier 2 — hosted |
|---|---|---|
| Source | the player drops a folder into `mods/` | a dauntless mod server |
| Format | whatever BC modders shipped, 2002-2010 | a format we define |
| Promise | **best effort — it may not work** | supported |
| Licensing | the player's own copy; we never redistribute | authored for us, terms agreed at submission |

## Why two tiers rather than one

**Supporting every legacy convention is unbounded.** The conventions are not a
standard — they are twenty years of accumulated practice from a community that
has largely dispersed. Foundation, FoundationTech, ATP, BCMP, `.pyc`-only
modules, textures loose beside the NIF, materials exported with 80%
self-illumination. Each is engine work, and there is no list of them to finish.

**But converting legacy mods to a clean format would not have helped much.**
The problem splits, and only one half is convertible:

| | Convertible? | Evidence |
|---|---|---|
| Scripts and metadata — Foundation calls, `dTechs`, layout, `.pyc` | yes, mechanically | the whole Foundation layer is ~12 names |
| Binary assets — NIF structure, texture layout, material values | **no** — that is rewriting art | **all three engine bugs found so far were here** |

Those three — textures not found beside the NIF, material emissive added
instead of modulated, an unresolved multitexture stage clobbering Base — were
BC-fidelity bugs in our own renderer that stock content simply never exposed.
A cleaner manifest would not have fixed one of them. So conversion addresses
the half that turned out to be cheap.

**And redistribution is closed to us.** Community packages carry unclear terms
or none: Foundation is "all rights reserved" with its grant scoped to the
Activision SDK licence; FoundationTech ships no licence text at all. Converting
someone's mod and hosting the result is a distribution act on content nobody
holds the rights to. That is why `mods/` is gitignored, and it is why "submit
your mod and we will convert it" is not available to us. A tier-2 server
carries content authored *for* dauntless, with terms agreed at submission.

## What "best effort" means for tier 1

It is a real promise, not an absence of one. Concretely:

- A sideloaded mod **never breaks the game**. A broken mod degrades to a
  reported line, never a failed boot — the rule `build_index` and the plugin
  loader already follow.
- Whatever we *can* resolve, we do: assets through the overlay index, scripts
  through the SDK finder, ships through the Foundation layer.
- Whatever we cannot, we **name**. The boot report says which frameworks are
  missing, which files were unplaced, which techs are not installed, which
  attributes we did not recognise. A player is never left guessing why a ship
  did not appear.
- We do not promise any particular mod works, and we do not owe a fix for
  every convention we meet.

## Known tier-1 fidelity gaps

Places where a sideloaded mod can run without error and still not behave as
it did under BC. These are not bugs to be fixed on sight — some are
deliberate, live-verified divergences — but a mod author hitting one deserves
to find it written down rather than discover it by feel.

**`NormalDischargeRate` is live for us and dead for BC.** BC's firing path
reads a flat power-level table for energy-weapon discharge and never consults
the hardpoint's `SetNormalDischargeRate`. We read the property. That
divergence is on the *frozen, do-not-change* list in
[`2026-07-15-bc-faithful-weapon-dispatch-design.md`](2026-07-15-bc-faithful-weapon-dispatch-design.md)
§7 — it is there because our live 2026-06-29 instrumented measurements beat
the RE doc's transcription where they conflict, and reconciling them is a
separately gated follow-up.

It is invisible on stock content: **all 208 emitters in all 52 stock hardpoint
files declare exactly `1.0`** (measured 2026-09-09 — "essentially every" was an
understatement; it is every one). **A mod that authors anything else gets a
phaser that drains at a rate BC would have ignored.** Nothing warns about this
today: the value is read, applied, and plausible, so it produces a wrong feel
rather than a reported line — the one failure mode the tier-1 promise above is
otherwise built to avoid.

**CONFIRMED LIVE, 2026-09-09, and it is worse than "a wrong feel".**
CGSovereign authors `SetNormalDischargeRate(200.0)` on 30 emitters against a
`MaxCharge` of `1.0`, so the bank empties in `1/200` s — one tick. Reported
from the live pass as *"blasting for like 0.1s before being fully drained."*
VoyagerCubeHP does the same to 12 tractors at `10.0`. Two of six mods in the
corpus, not one.

That uniformity also has a sharp corollary: because stock is 1.0 everywhere,
no stock-only measurement can distinguish reading the property from a flat
1.0 — which is exactly what the frozen entry's own justification was built
on. Resolving it needs the flat table's real values, tracked in
[`../../instrumented_experiments/2026-09-09-phaser-discharge-rate-source.md`](../../instrumented_experiments/2026-09-09-phaser-discharge-rate-source.md).
Until that lands the behaviour stays as shipped — and a boot-report line
naming any mod that authors a non-1.0 rate would at least make the divergence
visible instead of leaving it to be felt.

For contrast, the same audit is *why* the LC Intrepid's 0.8 s / 2.0 s phaser
cycle is **not** a gap: `MaxCharge`, `MinFiringCharge` and `RechargeRate` are
all read faithfully through the audited model, so that ship simply is a
burst-phaser design.

## The floor

Best effort still has a floor, and it is this:

> **A sideloaded ship mod that installs cleanly must be selectable and
> flyable.**

Below that line the tier delivers nothing a player can see, and "it may not
work" becomes "it does not work". That is not a lesser promise, it is an empty
one.

We are currently below the floor, and the reason is recorded in the Foundation
spec: registration populates QuickBattle's five ship tables, but
`GenerateShipMenu` builds the ship pane from hardcoded `if (iShipsUnlocked1 &
AKIRA)` lines and never consults those tables. The ships register and no menu
shows them. Meeting the floor means injecting registered ships into the built
menu; it is the immediate next piece of work.

## Non-goals

- **A converter for legacy mods.** Not now. It addresses the cheap half of the
  problem, and the licensing constraint blocks the hosted-conversion form of it
  anyway. A purely local converter remains possible later.
- **Tier-2 server design.** Format, hosting, submission terms and client are a
  separate spec. This document records only that tier 2 exists and why.
- **Parity with the original game's mod ecosystem.** Explicitly not promised.

## Consequences

- Compatibility work on legacy conventions becomes **discretionary** — judged
  case by case on whether it lifts many mods or one — rather than an implied
  obligation created by having a `mods/` folder at all.
- Engine bugs that legacy mods expose stay **non**-discretionary. Those are
  fidelity bugs in our reconstruction of BC, and mods are simply the harshest
  test of it. All three found so far would have been worth fixing with no mod
  support at all.
