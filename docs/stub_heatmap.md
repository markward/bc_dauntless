# Stub Telemetry Heatmap

Accumulated from **11 runs** (2026-07-10 21:48 UTC .. 2026-07-12 13:20 UTC). Open: 145, resolved: 0, regressed: 0.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

> **Not every top hit is a missing feature.** `TorpedoTube.UpdateCharge` and
> `TorpedoTube.GetMaxCharge` — ranks 1 and 2, ~6.4M hits between them — were
> **phantoms**, and were resolved on 2026-07-13 by **deletion, not implementation**.
> Charge is an `EnergyWeapon` concept (`sdk/Build/scripts/App.py:6426-6440`); BC's
> `TorpedoTube` never had those methods. The hits came entirely from our own code
> probing a tube for them with `hasattr` — which is **vacuously true** on any
> subsystem, because `TGObject.__getattr__` returns a truthy `_Stub` (and records a
> hit) for any missing attribute. `host_loop` then *called* the no-op stub on every
> tube, every frame. Fixed by dispatching on `isinstance`
> (`engine/host_loop.py`, `engine/ui/weapons_display_panel.py`).
>
> **When triaging this table, first ask whether the SDK actually calls the method
> on that owner.** If it doesn't, the bug is the caller, not a missing feature — and
> "implementing" it would be a faithfulness regression. The regression check still
> applies: reintroduce a `hasattr` probe and these rows light up again.

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | TorpedoTube | UpdateCharge | 4988686 | 11/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 2 | TorpedoTube | GetMaxCharge | 1394148 | 7/11 | 2026-07-12 12:57 UTC | 2026-07-13 |
| 3 | CharacterAction | _clip | 57942 | 9/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 4 | Waypoint | IsDying | 23372 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 5 | WeaponHitEvent | GetWeaponType | 16023 | 5/11 | 2026-07-12 12:57 UTC |  |
| 6 | WeaponHitEvent | TRACTOR_BEAM | 16023 | 5/11 | 2026-07-12 12:57 UTC |  |
| 7 | Planet | GetVelocity | 4924 | 1/11 | 2026-07-10 21:53 UTC |  |
| 8 | Planet | GetVelocity.x | 4924 | 1/11 | 2026-07-10 21:53 UTC |  |
| 9 | Planet | GetVelocity.y | 4924 | 1/11 | 2026-07-10 21:53 UTC |  |
| 10 | Planet | GetVelocity.z | 4924 | 1/11 | 2026-07-10 21:53 UTC |  |
| 11 | Planet | IsDying | 3578 | 1/11 | 2026-07-10 21:53 UTC | 2026-07-13 |
| 12 | ImpulseEngineSubsystem | GetCurMaxSpeed | 3491 | 4/11 | 2026-07-12 12:57 UTC |  |
| 13 | TorpedoSystem | ShouldBeAimed | 3491 | 4/11 | 2026-07-12 12:57 UTC |  |
| 14 | PhaserSystem | ShouldBeAimed | 2700 | 4/11 | 2026-07-12 12:57 UTC |  |
| 15 | Game | LoadDatabaseSoundInGroup | 2423 | 10/11 | 2026-07-12 13:20 UTC |  |
| 16 | PulseWeaponSystem | ShouldBeAimed | 1207 | 1/11 | 2026-07-10 21:58 UTC |  |
| 17 | ShipClass | GetSceneNodeId | 571 | 11/11 | 2026-07-12 13:20 UTC |  |
| 18 | TGPane | GetBottom | 420 | 10/11 | 2026-07-12 13:20 UTC |  |
| 19 | STCharacterMenu | GetNextChild | 286 | 8/11 | 2026-07-12 13:20 UTC |  |
| 20 | ShipClass | GetTargetOffsetTG | 238 | 6/11 | 2026-07-12 12:57 UTC |  |
| 21 | STCharacterMenu | GetNextChild.SetDisabled | 180 | 8/11 | 2026-07-12 13:20 UTC |  |
| 22 | TGParagraph | GetRight | 180 | 10/11 | 2026-07-12 13:20 UTC |  |
| 23 | TGPane | GetRight | 150 | 10/11 | 2026-07-12 13:20 UTC |  |
| 24 | PhaserSystem | SetForceUpdate | 136 | 6/11 | 2026-07-12 12:57 UTC |  |
| 25 | Waypoint | GetPhaserSystem.GetNumChildSubsystems | 108 | 2/11 | 2026-07-10 22:08 UTC |  |
| 26 | Waypoint | GetPulseWeaponSystem.GetNumChildSubsystems | 108 | 2/11 | 2026-07-10 22:08 UTC |  |
| 27 | Waypoint | GetTorpedoSystem.GetNumChildSubsystems | 108 | 2/11 | 2026-07-10 22:08 UTC |  |
| 28 | Waypoint | GetTractorBeamSystem.GetNumChildSubsystems | 108 | 2/11 | 2026-07-10 22:08 UTC |  |
| 29 | ShipClass | SetSplashDamage | 102 | 10/11 | 2026-07-12 13:20 UTC |  |
| 30 | TorpedoSystem | SetForceUpdate | 102 | 4/11 | 2026-07-12 12:57 UTC |  |
| 31 | TGInputManager | MoveMouseCursorTo | 92 | 11/11 | 2026-07-12 13:20 UTC |  |
| 32 | TorpedoSystem | SetSingleFire | 88 | 10/11 | 2026-07-12 13:20 UTC |  |
| 33 | ShipClass | subsystems | 82 | 10/11 | 2026-07-12 13:20 UTC |  |
| 34 | ShipClass | IsScannable | 71 | 9/11 | 2026-07-12 13:20 UTC |  |
| 35 | Mission | AddPrecreatedShip | 67 | 7/11 | 2026-07-12 13:20 UTC |  |
| 36 | EngPowerCtrl | GetBottom | 60 | 10/11 | 2026-07-12 13:20 UTC |  |
| 37 | TGIcon | GetRight | 60 | 10/11 | 2026-07-12 13:20 UTC |  |
| 38 | STTopLevelMenu | GetContainingWindow | 58 | 7/11 | 2026-07-12 13:20 UTC |  |
| 39 | STCharacterMenu | GetNextChild.SetEnabled | 54 | 4/11 | 2026-07-12 13:20 UTC |  |
| 40 | Waypoint | GetPhaserSystem | 54 | 2/11 | 2026-07-10 22:08 UTC |  |
| 41 | Waypoint | GetPulseWeaponSystem | 54 | 2/11 | 2026-07-10 22:08 UTC |  |
| 42 | Waypoint | GetTorpedoSystem | 54 | 2/11 | 2026-07-10 22:08 UTC |  |
| 43 | Waypoint | GetTractorBeamSystem | 54 | 2/11 | 2026-07-10 22:08 UTC |  |
| 44 | STCharacterMenu | GetFirstChild | 52 | 8/11 | 2026-07-12 13:20 UTC |  |
| 45 | STSubPane | GetButtonW | 48 | 3/11 | 2026-07-12 12:57 UTC |  |
| 46 | STSubPane | GetButtonW.SetChosen | 48 | 3/11 | 2026-07-12 12:57 UTC |  |
| 47 | STCharacterMenu | GetFirstChild.SetDisabled | 40 | 8/11 | 2026-07-12 13:20 UTC |  |
| 48 | TGPane | GetScreenOffset | 39 | 3/11 | 2026-07-12 13:20 UTC |  |
| 49 | STCharacterMenu | GetNthChild | 36 | 8/11 | 2026-07-12 13:20 UTC |  |
| 50 | STCharacterMenu | GetNthChild.IsEnabled | 36 | 8/11 | 2026-07-12 13:20 UTC |  |
| 51 | ShipClass | _drift_velocity | 33 | 9/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 52 | ShipClass | _drift_velocity.Length | 33 | 9/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 53 | LightPlacement | GetPhaserSystem.GetNumChildSubsystems | 32 | 2/11 | 2026-07-10 22:08 UTC |  |
| 54 | LightPlacement | GetPulseWeaponSystem.GetNumChildSubsystems | 32 | 2/11 | 2026-07-10 22:08 UTC |  |
| 55 | LightPlacement | GetTorpedoSystem.GetNumChildSubsystems | 32 | 2/11 | 2026-07-10 22:08 UTC |  |
| 56 | LightPlacement | GetTractorBeamSystem.GetNumChildSubsystems | 32 | 2/11 | 2026-07-10 22:08 UTC |  |
| 57 | EngPowerCtrl | GetRight | 30 | 10/11 | 2026-07-12 13:20 UTC |  |
| 58 | TGAnimAction | _action_type | 30 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 59 | TGFrame | GetBottom | 30 | 10/11 | 2026-07-12 13:20 UTC |  |
| 60 | TGParagraph | GetBottom | 30 | 10/11 | 2026-07-12 13:20 UTC |  |
| 61 | TorpedoSystem | GetObjType | 30 | 4/11 | 2026-07-12 12:57 UTC |  |
| 62 | STTargetMenu | GetHeight | 29 | 7/11 | 2026-07-12 13:20 UTC |  |
| 63 | STTargetMenu | Resize | 29 | 7/11 | 2026-07-12 13:20 UTC |  |
| 64 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 29 | 7/11 | 2026-07-12 13:20 UTC |  |
| 65 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 29 | 7/11 | 2026-07-12 13:20 UTC |  |
| 66 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 29 | 7/11 | 2026-07-12 13:20 UTC |  |
| 67 | STTopLevelMenu | ForceUpdate | 28 | 7/11 | 2026-07-12 13:20 UTC |  |
| 68 | TGParagraph | SetFontGroup | 28 | 7/11 | 2026-07-12 13:20 UTC |  |
| 69 | ShipClass | IsDestroyBrokenSystems | 26 | 5/11 | 2026-07-12 12:57 UTC |  |
| 70 | TacticalControlWindow | Layout | 26 | 6/11 | 2026-07-12 13:20 UTC |  |
| 71 | _STStylizedWindow | Move | 26 | 6/11 | 2026-07-12 13:20 UTC |  |
| 72 | KeyboardBinding | FindKey | 24 | 4/11 | 2026-07-12 13:20 UTC |  |
| 73 | TGInputManager | GetDisplayStringFromUnicode | 24 | 4/11 | 2026-07-12 13:20 UTC |  |
| 74 | STSubPane | ResizeToContents | 22 | 3/11 | 2026-07-12 12:57 UTC |  |
| 75 | _STStylizedWindow | ScrollToBottom | 22 | 3/11 | 2026-07-12 12:57 UTC |  |
| 76 | HullSubsystem | GetObjType | 18 | 4/11 | 2026-07-12 12:57 UTC |  |
| 77 | STCharacterMenu | RemoveItemW | 17 | 2/11 | 2026-07-10 21:58 UTC |  |
| 78 | LightPlacement | GetPhaserSystem | 16 | 2/11 | 2026-07-10 22:08 UTC |  |
| 79 | LightPlacement | GetPulseWeaponSystem | 16 | 2/11 | 2026-07-10 22:08 UTC |  |
| 80 | LightPlacement | GetTorpedoSystem | 16 | 2/11 | 2026-07-10 22:08 UTC |  |
| 81 | LightPlacement | GetTractorBeamSystem | 16 | 2/11 | 2026-07-10 22:08 UTC |  |
| 82 | TGAnimAction | GetNumActions | 16 | 1/11 | 2026-07-10 22:03 UTC |  |
| 83 | Planet | IsScannable | 15 | 7/11 | 2026-07-12 13:20 UTC |  |
| 84 | STButton | SetName | 15 | 8/11 | 2026-07-12 13:20 UTC |  |
| 85 | STTargetMenu | ForceUpdate | 14 | 7/11 | 2026-07-12 13:20 UTC |  |
| 86 | STTopLevelMenu | Resize | 14 | 7/11 | 2026-07-12 13:20 UTC |  |
| 87 | STTopLevelMenu | ResizeToContents | 14 | 7/11 | 2026-07-12 13:20 UTC |  |
| 88 | CharacterAction | _anim_node | 13 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 89 | CharacterAction | _anim_node.kind | 13 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 90 | _STStylizedWindow | ScrollToTop | 13 | 3/11 | 2026-07-12 12:57 UTC |  |
| 91 | STCharacterMenu | GetFirstChild.SetEnabled | 12 | 4/11 | 2026-07-12 13:20 UTC |  |
| 92 | Game | AddPersistentModule | 11 | 11/11 | 2026-07-12 13:20 UTC |  |
| 93 | TGAnimAction | GetAction | 10 | 1/11 | 2026-07-10 22:03 UTC |  |
| 94 | TacticalControlWindow | SetNotVisible | 9 | 7/11 | 2026-07-12 13:20 UTC |  |
| 95 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 96 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 97 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 98 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 99 | Planet | GetPhaserSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 100 | Planet | GetPulseWeaponSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 101 | Planet | GetTorpedoSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 102 | Planet | GetTractorBeamSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 103 | Sun | GetPhaserSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 104 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 105 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 106 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 8 | 2/11 | 2026-07-10 22:08 UTC |  |
| 107 | STButton | GetName | 6 | 4/11 | 2026-07-12 13:20 UTC |  |
| 108 | ShipClass | SetLifeTime | 6 | 1/11 | 2026-07-10 21:53 UTC |  |
| 109 | TGAnimAction | GetAction._anim_node | 6 | 1/11 | 2026-07-10 22:03 UTC |  |
| 110 | TGAnimAction | _anim_node.kind | 6 | 1/11 | 2026-07-10 22:03 UTC | 2026-07-13 |
| 111 | GridClass | GetPhaserSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 112 | GridClass | GetPulseWeaponSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 113 | GridClass | GetTorpedoSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 114 | GridClass | GetTractorBeamSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 115 | Planet | GetPhaserSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 116 | Planet | GetPulseWeaponSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 117 | Planet | GetTorpedoSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 118 | Planet | GetTractorBeamSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 119 | SensorSubsystem | GetIdentificationTime | 4 | 3/11 | 2026-07-12 12:30 UTC |  |
| 120 | ShipClass | SetScannable | 4 | 1/11 | 2026-07-10 22:08 UTC |  |
| 121 | ShipClass | SetTargetable | 4 | 1/11 | 2026-07-10 22:08 UTC |  |
| 122 | SortedRegionMenu | SetPlacementName | 4 | 4/11 | 2026-07-12 13:20 UTC |  |
| 123 | Sun | GetPhaserSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 124 | Sun | GetPulseWeaponSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 125 | Sun | GetTorpedoSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 126 | Sun | GetTractorBeamSystem | 4 | 2/11 | 2026-07-10 22:08 UTC |  |
| 127 | TGAnimAction | GetAction._clip | 4 | 1/11 | 2026-07-10 22:03 UTC |  |
| 128 | TGScriptAction | _action_type | 4 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 129 | TGScriptAction | _anim_node | 4 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 130 | TGScriptAction | _anim_node.kind | 4 | 4/11 | 2026-07-12 13:20 UTC | 2026-07-13 |
| 131 | TGPane | SetAlwaysHandleEvents | 3 | 3/11 | 2026-07-12 12:57 UTC |  |
| 132 | TGPane | SetNotAlwaysHandleEvents | 3 | 3/11 | 2026-07-12 12:57 UTC |  |
| 133 | TGParagraph | SetString | 3 | 3/11 | 2026-07-12 12:57 UTC |  |
| 134 | PhaserSystem | GetObjType | 2 | 1/11 | 2026-07-10 21:58 UTC |  |
| 135 | Sun | IsScannable | 2 | 2/11 | 2026-07-10 22:08 UTC |  |
| 136 | WarpEngineSubsystem | TransitionToState | 2 | 1/11 | 2026-07-10 22:08 UTC | 2026-07-13 |
| 137 | STButton | GetConceptualParent | 1 | 1/11 | 2026-07-10 22:08 UTC |  |
| 138 | STButton | GetConceptualParent.GetText | 1 | 1/11 | 2026-07-10 22:08 UTC |  |
| 139 | STButton | GetText.GetString | 1 | 1/11 | 2026-07-10 22:08 UTC |  |
| 140 | ShipClass | CompleteStop | 1 | 1/11 | 2026-07-10 21:53 UTC |  |
| 141 | ShipClass | SetInvincible | 1 | 1/11 | 2026-07-10 22:03 UTC |  |
| 142 | SortedRegionMenu | SetMissionName | 1 | 1/11 | 2026-07-10 22:08 UTC |  |
| 143 | WarpEngineSubsystem | GetWarpExitLocation | 1 | 1/11 | 2026-07-10 22:08 UTC |  |
| 144 | WarpEngineSubsystem | GetWarpExitRotation | 1 | 1/11 | 2026-07-10 22:08 UTC |  |
| 145 | WarpEngineSubsystem | SetPlacement | 1 | 1/11 | 2026-07-10 22:08 UTC |  |

## Resolved

| owner | attr | markedResolvedOn | lastSeenOn |
|---|---|---|---|

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 57942 | 9/11 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 57942 | 9/11 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 7398 | 4/11 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/reticle_text.py:59 | 2451 | 1/11 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:457 | 499 | 5/11 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 72 | 11/11 |
| 7 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 36 | 8/11 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 29 | 7/11 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 13 | 5/11 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/ScienceMenuHandlers.py:488 | 6 | 2/11 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/bridge_placement.py:138 | 4 | 1/11 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/bridge_placement.py:139 | 4 | 1/11 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2119 | 1 | 1/11 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2122 | 1 | 1/11 |
