# Foundation / FoundationTech — API surface register

**Status:** partial skeleton, ~30 names. **NOT a complete surface.**
**Date:** 2026-09-08
**Related:** `docs/superpowers/specs/2026-09-08-mod-overlay-design.md`
(Spec 3 — Foundation compatibility — will be written from this)

## What this is

Foundation is a third-party BC plugin framework (Dasher42, 2002; later
maintained by MLeo Daalder). A large fraction of community mods are built
against it, so it is a **compatibility target** for us in the same sense
`Appc` is: we need to satisfy the surface mods call, not reproduce the
implementation.

This file records what that surface looks like, recovered **without using
Foundation's source**, from two consumers and one public document.

## ⚠️ Read this before using the file

- **It is incomplete and it is not ranked.** Two consumers is not a corpus.
  Absence from this file is *not* evidence a name doesn't exist — treat
  every gap as unknown, not as absent. (Same discipline as
  `docs/engine/aieditor-ai-surface-and-gaps.md`: every ❌ there is a
  hypothesis, and an audit found several already implemented.)
- **We do not have Foundation's source, and should not vendor it.**
  Foundation is "All rights reserved", with permission granted only *"as a
  component of Bridge Commander under the terms of the Activision SDK
  license"*; LGPL appears there solely as a copyleft obligation on
  modifications, not as a grant. FoundationTech ships **no licence text at
  all**. Neither is GPL, so neither can be copied into this GPLv3 tree.
  Reading either for interface facts is fine; copying expression is not.
- **Signatures below are inferred from call sites**, not from definitions.
  Argument names are ours except where the readme names them.

## Evidence tiers

| Tier | Source | Why it is trusted |
|---|---|---|
| **A** | Call sites in FoundationTech 20051126 | Real, working usage against real Foundation |
| **B** | Call sites in a stock-shaped ship mod (Steamrunner Aad) | Real usage, but only the ship-registration slice |
| **C** | Foundation_Readme.html (2002) | Author's own prose; signatures partly explicit, semantics loose |

## The `*Def` family

Everything user-facing is a `Def` constructor that registers itself. All of
them appear to descend from `MutatorElementDef`, whose `__init__` FTech
calls directly:

```python
Foundation.MutatorElementDef.__init__(self, name, dict)     # tier A
```

Any of them may take a **final argument literally named `dict`**, shaped
`{'modes': [mutator, ...]}`, which files that def inside one or more
mutators (tier C, confirmed by tier A usage).

| Name | Signature (inferred) | Tier |
|---|---|---|
| `MutatorElementDef` | `(name, dict)` — base of the family | A |
| `MutatorDef` | `(name)` → object with `.Activate()` / `.Deactivate()` | A, C |
| `OverrideDef` | `(name, target_dotted, replacement_dotted [, dict])` | A, C |
| `SoundDef` | `(file, name, volume [, dict])` | A, C |
| `SystemDef` | `(name, n_planets [, n_missing_inner])` | C |
| `TGLDef` | `(name, path)` | C |
| `ShipDef` | namespace object; mods assign `ShipDef.<Name> = …` | B |
| `FedShipDef` | `(abbrev, species, {name, iconName, shipFile} [, dict])` | B |
| `TriggerDef` | subclassable base; **FTech replaces it wholesale** | A |
| `ListenerDef` | unknown signature | A |
| `PropertyDef` | unknown signature | A |
| `SystemMenuBuilderDef` | `(tglDatabase)` | C |

Observed literal calls, verbatim:

```python
# tier A
Foundation.SoundDef('Custom/FTB/Sfx/Weapons/RomPlasmaBurst.wav',
                    'FTB Plasma', 1.0, {'modes': [mode]})
Foundation.OverrideDef('SetShipID',
                       'Tactical.Interface.ShipDisplay.SetShipID',
                       'FoundationTech.SetShipID', dMode)
Foundation.MutatorDef('Foundation Technologies')

# tier C
Foundation.SystemDef('New System', 5, 2)   # 5 planets, inner 2 missing
Foundation.TGLDef('FTB Ships', 'data/TGL/FTBShips.TGL')
```

## Module-level names

| Name | Kind | Notes | Tier |
|---|---|---|---|
| `shipList` | dict-like | `.has_key(k)`, `[k]`, `._keyList` | A, B |
| `propertyList` | container | unknown element type | A |
| `oTechs` | mutable global slot | FTech assigns `self` into it on activate, `None` on deactivate | A |
| `Flags` | class | only ever seen commented out in FTech | A |
| `version` | value | | A |
| `FolderManager` | callable | `FolderManager('ship', shipFile)` → module | A |
| `LoadExtraPlugins` | callable | `LoadExtraPlugins("scripts\\Custom\\Techs")` | A |
| `BuildGameMode` | callable | QuickBattle merges all active mutators into one | C |
| `ERA_TOS`, `ERA_TMP`, `ERA_PRETNG`, `ERA_TNG`, `ERA_DS9`, `ERA_NEMESIS`, `ERA_ENT` | constants | values unknown | A |

## ShipDef attributes mods set

From the reference ship mod (tier B) — the slice that matters for getting a
downloaded ship into the QuickBattle menus:

```python
Foundation.ShipDef.Fsteamr = Foundation.FedShipDef(
    abbrev, species, {'name': longName, 'iconName': iconName,
                      'shipFile': shipFile})

Foundation.ShipDef.Fsteamr.desc         = "..."
Foundation.ShipDef.Fsteamr.SubMenu      = "TNG Ships"
Foundation.ShipDef.Fsteamr.SubSubMenu   = "Steamrunner Class"
Foundation.ShipDef.Fsteamr.dTechs       = {...}    # FoundationTech, not Foundation
Foundation.ShipDef.Fsteamr.RegisterQBShipMenu(menuGroup)
Foundation.ShipDef.Fsteamr.RegisterQBPlayerShipMenu(playerMenuGroup)

Foundation.ShipDef.<longName>.friendlyDetails[2]   # indexable, ≥3 elements
Foundation.ShipDef.<longName>.enemyDetails[2]
```

`FedShipDef` naming strongly implies per-race siblings. **Unverified** — no
source examined exercises another.

## Semantics worth capturing now

- **`OverrideDef` is monkeypatching by dotted path.** `Activate()` swaps the
  named Python object for the replacement; `Deactivate()` restores it. This
  is Foundation's headline feature — replace engine code without
  overwriting files.
- **Mutators load in definition order.** The readme says so explicitly and
  recommends Nanobyte's Mod Packager for finer control. Any compatibility
  layer must preserve definition order, not sort.
- **Foundation is designed to be monkeypatched itself.** FTech does
  `Foundation.TriggerDef = TriggerDef`, replacing the class on the module,
  then hangs new event types off it:
  ```python
  Foundation.TriggerDef.ET_FND_CREATE_SHIP        = App.UtopiaModule_GetNextEventType()
  Foundation.TriggerDef.ET_FND_CREATE_PLAYER_SHIP = App.UtopiaModule_GetNextEventType()
  ```
  So plugins mutate the framework module in place. A compatibility shim that
  exposes read-only or immutable attributes will break real mods.
- **Plugin paths are Windows-shaped.** `LoadExtraPlugins("scripts\\Custom\\Techs")`
  passes backslashes. Any implementation must normalise separators.
- **`Custom/Ships/` is Foundation's, not the SDK's.** The stock SDK ships
  `Custom/` with an `__init__.py` and a `Tutorial/`, but **no `Custom/Ships/`**;
  Foundation supplies that directory and its `__init__.py`. A ship mod's
  `Custom/Ships/*.py` is therefore not an importable package without
  Foundation — which is exactly why such a mod half-works under a bare
  overlay: the ship loads, but never appears in the menus.

## `OverrideDef` is our risk-4 problem

The mod-overlay spec's risk 4 — *"a mod overriding a module we have
reimplemented in `engine/` or C++ will appear to do nothing"* — is
`OverrideDef` stated in Foundation's own vocabulary. Its entire "Overrides"
category assumes the thing being replaced is a live Python object reachable
by dotted path. Wherever we have moved that behaviour natively, the override
silently no-ops.

Closing it needs a list of SDK modules we shadow. Deferred to Phase 2.

## How to complete this file

**Do not complete it by reading Foundation's source.** The surface that
matters is what mods actually *call*, ranked by frequency — the same shape
as `docs/stub_heatmap.md` for Appc, and for the same reason: it tells you
what to build first.

The mod-overlay spec's framework-detection scanner is the tool that produces
it. Point it at a corpus of 20–50 mods and it emits the ranked surface
automatically. Until that exists, this file is a skeleton and should be
treated as one.
