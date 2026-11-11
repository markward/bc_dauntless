# Foundation: BridgeDef and StarBaseDef

**Status:** built on `feat/foundation-bridge-starbase-defs`. Live-checked by Mark 2026-11-11: the Intrepid Bridge 2.0 pack's bridge (after the texture-folder and viewscreen fixes) and KM's Starbase 220 in Quick Battle (loads and spawns).
**Date:** 2026-11-11
**Related:** `2026-09-09-foundation-compatibility-design.md` (the Foundation surface), `2026-09-16-ship-bridge-matrix-design.md` §1 (the `_scan_mod_bridges` contract this fills in), `2026-11-11-legacy-script-parsing-design.md` (the Python 1.5 fixes plugins now get)

## 1. Why

Bridges are one of the mod categories Dauntless supports, and bridge packs register through Foundation's `BridgeDef`. Mod stations register through `StarBaseDef`. Neither existed in our Foundation. Measured on the Kobayashi Maru 2011.10 pack: 18 literal `BridgeDef` calls (16 bridges, plus Galaxy and Sovereign re-registered with their own officer positions) and 11 station definitions (`StarBaseDef`, `CardStarBaseDef`, and two `ShipDef` subclasses). `SystemDef`, `OverrideDef` and FoundationTech stay out of scope (Mark, 2026-11-11).

## 2. What was built

| Piece | Where | What |
|---|---|---|
| Plugin loader | `engine/foundation/loader.py` | `Custom/Autoload` and `Custom/Ships` scripts run through the active SDK loader: Python 1.5 source fixes and transforms, or the lifter for a bytecode-only `.pyc`. They used to run with `runpy` (plain Python 3): 31 of KM's 149 Autoload plugins did not compile and `has_key` crashed at run time. Still executed once per load, not imported. |
| `ShipDef` as a class | `engine/foundation/shipdef.py` | `Foundation.ShipDef` is a real class mods derive from (`class RomulanStarBaseDef(Foundation.ShipDef)`) and still the registry ships are assigned onto. A metaclass makes its `__dict__` (and `vars()`) the plain dict of assigned names, writable as BCUT scripts expect. Factories (`FedShipDef`, ...) build `ShipDef` instances. |
| Races | `engine/foundation/race.py` | Foundation's nine race objects (`Foundation.Federation` ... `Foundation.Borg`), by Foundation's abbreviations (Fed, Card, Dom, the rest their own name). |
| `StarBaseDef`, `CardStarBaseDef` | `engine/foundation/__init__.py` | Stations: race Federation / Cardassian, `StrFriendlyAI()` / `StrEnemyAI()` = `StarbaseFriendlyAI` / `StarbaseAI`. Quick Battle's table rows now take their AI from the definition, so a mod station gets BC's starbase AI like the stock station rows. |
| `BridgeDef` | `engine/foundation/bridge.py` | `BridgeDef(name, bridgeString, dict)`, Foundation's `Registry` (`_keyList`, `_arrayList`), `MutatorElementDef`, `bridgeList`, `BridgeSetLocation`, and `pCurrentBridge`, read live from the bridge set's config (`LoadBridge.Load` is not hooked). |
| Officer positions | `engine/bridge_positions.py` | Wraps `CommonAnimations.SetPosition` (installed from `capture_placement`): a location the loaded bridge's `BridgeDef` declares is placed by it; anything else goes to BC's `SetPosition` unchanged. |
| Bridge list | `engine/bridge_selection.py` | `_scan_mod_bridges` per its contract: `Bridge/<name>.py` defining `CreateBridgeModel` (read, never imported), plus a bytecode-only `.pyc` read from its code. Labels are the pack's `BridgeDef` name, worked out per call (plugins can register after the list is first read). |

## 3. Decisions

- **A location's extra statements run with `pCharacter` bound.** Bridge packs write `'pCharacter.SetHidden(1)'` on lift locations. Foundation exec'd these inside `BridgeDef.SetLocation`, where no `pCharacter` exists; the `NameError` hit a bare `except`, so the officer stayed visible. BC's own lift locations hide the officer, and the statement says to. We run the statement (1.5 source, through `fix_source`) with `pCharacter` defined. A failing statement is reported once and the officer is still placed.
- **Unused `BridgeDef` keys are stored, not applied.** `Maps` (alert-state light textures), `bridgeSound` and `LoadingScreen` were read by other BC plugins (bridge add-ons we refuse as Foundation infrastructure). They stay on `definition.dict`, and the boot report names them.
- **A pack's `BridgeDef` for a stock bridge takes effect.** KM's "Galaxy/Sovereign Bridge Advanced" re-register `GalaxyBridge` / `SovereignBridge` with their own locations; with KM installed, those positions win, as they did under Foundation.
- **The mutator is still inert.** `MutatorDef` gained `elements` and `bridgeList` so definitions can add themselves to modes; nothing switches modes.

## 4. Proof

Focused tests (no BC or mod content): `tests/unit/test_foundation_loader.py`, `test_foundation_starbase.py`, `test_foundation_bridgedef.py`, `test_bridge_positions.py`, `test_bridge_selection.py` (the `_scan_mod_bridges` contract test is no longer `xfail`).

Against KM, statically (no KM code was run): the scan finds 18 bridge scripts, and every one of the 16 non-stock literal `BridgeDef` calls names one of them (two differ only in case, which the lookup folds).

## 5. Live check (Mark, 2026-11-11)

Found and fixed during it:

- **A pack's flat texture folder.** Bridge scripts name `<set>/High/` but packs often ship textures beside the NIF; set textures now search the LoadModel folder, then the NIF's own folder, with the stock tier folder kept last (`host_loop._set_texture_dirs`).
- **The viewscreen feed on a mod screen mesh** whose UVs run outside 0-1: the feed's UV is wrapped before the V flip (`bridge.frag`). The Intrepid screen is about 2.29:1 against a 16:9 feed, so it is stretched about 30% horizontally; BC likely did the same (unverified).
- **A bytecode-only mod ship** (`ships/Starbase220.pyc`, no `.py`) was reported unresolved: the installed-ship scan now accepts `.pyc`.
- **A raising script action ended the game** (the station script read `SpeciesToShip.STARBASE220`, which only KM's replaced species table defines). A `TGScriptAction` that raises now prints its traceback and counts as finished, like broadcast handlers.

Starbase 220 needs KM's own `Multiplayer/SpeciesToShip` (KM replaces the stock one) and a `bcdebug` module (KM's needs BC's Windows-only `nt`). The model loads and spawns; Mark judged it ugly, which is the asset.

## 6. Not done

- KM's other stations, and KM as a whole pack (its plugins, its `bcdebug`/`nt` dependency).
- The Intrepid pack's `bridgemenuscroller.py` plugin needs `OverrideDef` and fails at load (reported, harmless).
- `SystemDef`, `OverrideDef`, FoundationTech, and the `Maps` / `bridgeSound` / `LoadingScreen` settings.
