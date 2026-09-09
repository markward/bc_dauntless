# Foundation Compatibility — Design

**Status:** approved, not yet implemented
**Date:** 2026-09-09
**Builds on:** `docs/superpowers/specs/2026-09-08-mod-overlay-design.md`
(Spec 3 in that document's "Followed by" line)
**Surface register:** `docs/engine/foundation-api-surface.md`

## Problem

Foundation is a third-party plugin framework (Dasher42, 2002) that a large
share of Bridge Commander ship mods are built against. Without it, such a mod
half-installs: its `Scripts/Ships/<X>.py`, `Scripts/Ships/Hardpoints/<X>.py`
and `Data/Models/**` are stock-shaped and load through the mod overlay alone,
but the half that makes the ship *selectable* — `Scripts/Custom/Ships/<X>.py` —
does `import Foundation` and silently does nothing.

Both mods currently installed for testing report exactly this:

```
mods:
  LC Intrepid Pack: 30 files, 1 ignored, unplaced: sfx, requires: Foundation (unsupported)
  aad-moerman-s-steamrunner: 42 files, 3 ignored, requires: Foundation (unsupported)
```

Nine ship definitions across the two, none of them reachable in game.

The reason Foundation exists at all is that BC's QuickBattle holds a **static**
ship table: `g_dFriendlyShipTypeToDetails` and friends are literal dicts keyed by
`ST_*` integer constants (`ST_MARAUDER = 0` … `ST_TRANSPORT = 30`), so adding a
ship means editing a shipped file. Foundation's readme puts it plainly: it
"replaces the static indexes of Bridge Commander with dynamic structures".

## Goal

A mod dropped into `mods/` that registers ships through Foundation has those
ships appear in QuickBattle and spawn correctly, with no edit to any stock
file and no change to our CEF picker.

## Non-goals

- **`OverrideDef` and `MutatorDef`.** Foundation's monkeypatch layer — replace
  a Python object by dotted path, with `Activate()`/`Deactivate()`, grouped
  into mutators toggled from the config screen. This is where mods reach into
  code we have reimplemented natively (the overlay spec's risk 4) and it
  deserves its own design.
- **Foundation Technologies.** `dTechs` is accepted and ignored — see
  "dTechs" below, which argues this is the ecosystem's own behaviour rather
  than a shortfall.
- **`SystemDef` / `TGLDef` / `SystemMenuBuilderDef`.** Documented in the
  readme, used by neither mod in the corpus. Add when a mod needs them.
- **Reproducing Foundation's implementation.** We implement the surface mods
  call, against our own architecture. Foundation is "all rights reserved" and
  cannot be vendored into this GPLv3 tree; see the surface register.

## The measured surface

From the two installed mods — nine ship definitions, seven `FedShipDef` and
two `BorgShipDef`:

| Name | Uses | Notes |
|---|---|---|
| `ShipDef.<Name> = <Race>ShipDef(abbrev, species, {…})` | 9 | the constructor |
| `.RegisterQBShipMenu(group)` | 9 | puts the ship in the menus |
| `.RegisterQBPlayerShipMenu(group)` | 9 | …and in the player list |
| `.desc` | 9 | |
| `shipList`, `shipList._keyList.has_key`, `ShipDef.__dict__` | 18 / 9 / 18 | generated boilerplate tail |
| `.SubMenu`, `.SubSubMenu` | Steamrunner | menu nesting |
| `.hasTGLName`, `.hasTGLDesc` | Intrepid | TGL-sourced naming |
| `.dTechs` | Steamrunner | FoundationTech, not Foundation |
| `SoundDef(file, name, volume)` | 1 | Intrepid's `Custom/Autoload` plugin |

Roughly twelve names. The register catalogues ~30, but those were recovered
from FoundationTech — a *framework consumer*, which exercises far more than
ship mods do. This spec builds what ship mods actually call.

**The corpus is thin.** Two mods is enough to see the shape and not enough to
be confident of coverage. Anything a third mod needs is a gap, not a defect.

## Where the module lives

`Foundation.py` at the **project root**, joining `App.py`, `LoadBridge.py` and
`LoadDamageHitSounds.py`. Implementation in `engine/foundation/`; the root file
is a thin re-export so application code stays out of the root.

This makes "ours always wins" fall out of existing machinery rather than a
special case: `_SDKFinder` checks `PROJECT_ROOT` **before** the mod index, an
ordering the overlay chose deliberately because project-root shims are our own
replacements and must not be overridable. A mod pack bundling Foundation's own
`Foundation.py` therefore never reaches import — which is what we want, since
the real one is Python 1.5 and monkeypatches `QuickBattle.py` and
`loadspacehelper.py`, both of which we have reimplemented.

⚠️ This is the **fourth** project-root shim, and `CLAUDE.md` says to consider
grouping them into `shims/` at the third. That migration is due but is not
part of this work.

## The ShipDef family

`ShipDef` is a bare namespace object. Mods assign onto it and read back
through `__dict__`:

```python
Foundation.ShipDef.LCintrepidZZ = Foundation.FedShipDef(
    abbrev, species, {'name': longName, 'iconName': iconName,
                      'shipFile': shipFile})
Foundation.ShipDef.LCintrepidZZ.desc = "..."
Foundation.ShipDef.LCintrepidZZ.RegisterQBShipMenu("Fed Ships")
```

`FedShipDef` and `BorgShipDef` are a small factory family keyed by race; race
supplies the default side and QuickBattle AI module. Each returns an object
carrying the attributes the corpus sets — `desc`, `SubMenu`, `SubSubMenu`,
`hasTGLName`, `hasTGLDesc`, `dTechs`, and indexable `friendlyDetails` /
`enemyDetails` of at least three elements, which the generated boilerplate
subscripts at `[2]`.

`shipList` is dict-like with `has_key`, `[]` and the `_keyList` that the
Bridge Commander Universal Tool's generated tail reaches into:

```python
if Foundation.shipList._keyList.has_key(longName):
    Foundation.ShipDef.__dict__[longName].friendlyDetails[2] = ...
```

That tail runs in every generated ship script, so `_keyList` is required
surface, not an implementation detail we may hide.

## Registration into QuickBattle

`RegisterQBShipMenu(group)` and `RegisterQBPlayerShipMenu(group)` mint a fresh
`ST_*` id and append to the **five** parallel tables QuickBattle builds its
panes from — verified by reading the module rather than from memory:

| Table | Key → value |
|---|---|
| `g_dShipNameToType` | `"Sovereign"` → `ST_SOVEREIGN` |
| `g_dShipNameToIconNumber` | `"Sovereign"` → icon number |
| `g_dFriendlyShipTypeToDetails` | `ST_*` → detail row (friendly side) |
| `g_dEnemyShipTypeToDetails` | `ST_*` → detail row (enemy side) |
| `g_dShipTypeToIconNumber` | `ST_*` → icon number |

The detail row shape is

```python
ST_SOVEREIGN: ["Sovereign", "Sovereign", "QBFriendlySovereignDestroyed",
               "QuickBattleFriendlyAI", "Friendly"]
#              ship script,  label,       destroyed event, AI module, side
```

New ids allocate sequentially from `ST_MOD_BASE = 1000`. Stock occupies
`0..30`, so collision is impossible rather than merely unlikely, and the gap
is wide enough that a future BC-content addition could not close it.

`menuGroup` plus `SubMenu` / `SubSubMenu` become the category path.

⚠️ **CORRECTION — feeding the tables is necessary but NOT sufficient.**

This section originally claimed "our CEF picker needs no changes at all — feed
the tables and the ship appears". That was wrong, and the end-to-end test in
the plan's final task is what caught it: every unit test passed, all five
tables were correctly populated, and no ship appeared.

`quick_battle_setup_panel` does indeed hold no ship list — it walks the live
`g_pShipsPane` widget tree. But that tree is built by `GenerateShipMenu`, which
**never consults the five tables**. Every ship in it is a literal line gated by
an unlock bitflag:

```python
if (iShipsUnlocked1 & AKIRA):
    pFederation.AddChild(CreateBridgeMenuButton(..., ST_AKIRA, g_pXO))
```

The tables govern what happens *after* a selection — the detail row, the AI
module, the player-ship assignment — not what is offered. Both menus are
hardcoded, which is exactly why real Foundation replaces `QuickBattle.py`
outright.

So registration needs **both** halves: the tables (so a selected ship behaves
correctly) **and** an injection of categories and buttons into the built menu
(so it can be selected at all). The second is a follow-up task; without it the
feature registers ships that nothing displays.

The error came from reading `_read_ships`, seeing it walk widgets, and
inferring the tables fed those widgets rather than reading the builder. Worth
recording: the same reading-one-layer-and-inferring-the-next mistake produced
two wrong diagnoses earlier in the same work.

That is also why this approach was chosen over injecting widgets after the
panes are built, or keeping a parallel registry the panel merges in: both of
those produce a ship that is *listed* but is not a real QuickBattle ship, so
everything else reading those tables — mission scripts, the AI resolving
`QuickBattleFriendlyAI`, the destroyed-event wiring — would not know it
exists. The failure would surface later as "it's in the menu but won't spawn".

## Loader lifecycle

`Foundation.load_plugins()` walks two directories, through the SDK finder so
mod-supplied files resolve via the overlay like any other script:

1. `scripts/Custom/Autoload/*.py`, sorted by filename
2. `scripts/Custom/Ships/*.py`, sorted by filename

Neither directory is imported by BC itself — Foundation is what loads them,
which is precisely why our two mods' ships currently do nothing.

Autoload runs first because plugins register resources (sounds, and later
systems and TGL tables) that ship definitions may reference. Filename ordering
is authors' own convention: real plugins carry numeric prefixes, e.g. FTech's
`000-Fixes20030305-FoundationTriggers.py`.

⚠️ **Autoload-before-Ships is inferred, not established.** We do not have
Foundation's own ordering. It is the safe direction (resources before
consumers), but if a mod ever depends on the reverse, this is the assumption
to revisit first.

Placement in boot: after `mods.install()` and after `_SDKFinder` is installed,
both of which already precede any mission load — so registration lands well
before QuickBattle builds its panes.

## SoundDef, and the `sfx/` prerequisite

`SoundDef(file, name, volume)` maps onto `g_kSoundManager.LoadSound(path,
name, …)`, the same registration `LoadTacticalSounds.py` uses.

The Intrepid's call is:

```python
Foundation.SoundDef("sfx/Weapons/ZZ_KlingonTMP2.wav", "VoyPhoton", 1.0)
```

**`sfx/` is not a placeable content directory.** The overlay maps only `Data/`
and `Scripts/`, which is why that mod's report says `unplaced: sfx`. So
`game_asset("sfx/…")` misses the index, falls through to the stock game root,
and finds nothing — `SoundDef` would register a sound that can never play.

**Adding `sfx` to the overlay's `_TARGET_FOR` is in scope for this work** —
one entry plus its target root, done as its own task before `SoundDef`, since
`SoundDef` cannot be meaningfully tested without it. The overlay spec deferred
it only because nothing in the pipeline had been checked against it, and now
something has. That spec's `sfx/` non-goal is superseded and should be amended
in the same change rather than left contradicting this one.

## dTechs

`dTechs` is FoundationTech's per-ship equipment list: keys are tech names,
values are that tech's configuration for the ship.

```python
dTechs = {"AutoTargeting": {"Phaser": [2, 1]}}
```

FTech reads it at spawn:

```python
if proto and proto.__dict__.has_key('dTechs'):
    self.__dict__.update(proto.dTechs)
    for i in proto.dTechs.keys():
        if oTechs._keyList.has_key(i):
            oTechs[i].Attach(self)
        else:
            print "Tech: " + i + " isn't installed::" + sName
```

Note the `else`. **A ship declaring a tech that is not installed is a normal,
handled condition in the ecosystem** — FTech logs a line and carries on. So
accepting `dTechs` and ignoring it is not a shortfall on our part; it is
exactly what FTech does with FTech's own tech modules absent.

We match that, and report it the way we report everything else rather than
silently: the mod's boot line gains *"declares techs that are not installed:
AutoTargeting"*.

This also makes FTech a clean later addition: a tech registry plus
`Attach(ship)` at spawn, sitting behind the same `dTechs` data we already
accept.

## Failure isolation and reporting

Every `Custom/*` script executes under its own guard. A script that raises
names itself and the loader continues, so one broken mod cannot stop the
others registering — the same rule `build_index` already follows for an
unreadable mod, and the same reason: a mod that silently does nothing is a
support nightmare.

Results feed the existing boot report, which gains per mod: ships registered,
plugins run, techs declared-but-absent, and any script that failed with its
exception.

## Testing

Fixtures are synthetic mod trees in `tmp_path` — the real mods are gitignored
and no test may depend on them.

- **ShipDef family** — attributes the corpus sets; `friendlyDetails[2]`
  subscriptable; `BorgShipDef` differs from `FedShipDef` in side/AI defaults
- **shipList** — `has_key`, `[]`, `_keyList`, and the generated boilerplate
  tail running end to end without raising
- **ST_ allocation** — never collides with `0..30`; stable across a run
- **Table injection** — all four tables gain a correctly shaped row
- **Loader** — both directories walked, filename order honoured, one raising
  script does not prevent the others
- **`SoundDef`** — resolves a mod-supplied `sfx/` file once `_TARGET_FOR`
  covers it

The test that matters most enters higher than any of those: a synthetic
`Custom/Ships` script registers, QuickBattle builds its panes, and the ship is
asserted present as a button. "Listed but won't spawn" is the failure this
design exists to avoid, and entering one layer below the pane build would not
catch it.

## Risks

1. **The corpus is two mods.** Nine ship definitions, one Autoload plugin. A
   third mod may use surface neither exercises. *(Accepted; the framework
   detector will name what is missing.)*
2. **Autoload-before-Ships is inferred.** See "Loader lifecycle".
3. **`dTechs` ships register without their techs.** Matches FTech's own
   behaviour and is now reported, but a Steamrunner variant will not fly as
   its author intended.
4. **Four project-root shims.** The `shims/` grouping `CLAUDE.md` asks for is
   overdue and this adds to the pressure.
5. **Coupling to QuickBattle's table shapes.** Four literal dicts in a stock
   SDK file. If BC's own tables were ever restructured this breaks — but they
   are shipped content and will not change.
