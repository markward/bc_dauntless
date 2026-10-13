# Stub Telemetry Heatmap

Accumulated from **783 runs** (2026-07-13 08:53 UTC .. 2026-10-13 08:10 UTC). Open: 176, resolved: 375, regressed: 1.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## ⚠️ Regressed (hit again after being marked resolved)

| owner | attr | markedResolvedOn | lastSeenOn | hits |
|---|---|---|---|---|
| TGAnimAction | _anim_node.kind | 2026-07-13 | 2026-10-06 12:13 UTC | 117 |

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

> **Scouting notes:** `docs/engine/stub-scouting-2026-08-10.md` — what it would take to plug these, why the two risk tables below are currently hard to action, and one confirmed live bug. **Do not add prose to this file: regeneration deletes it.**

> **Constant-surface sweep closed 2026-08-31:** every `App.<NAME>` / `App.<CLASS>.<CONST>` row the q13 sweep covers was applied and moved to Resolved that day (marked `2026-08-31`, filter the Resolved table below on that date to see the set). What is left below is a DIFFERENT bug class — missing **methods**, missing module-level **instances** (`g_k*` colours), and missing **constructor/cast functions** — none of it is a constant-value lookup, so this sweep cannot close any more of it. See `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md`.

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | TGIcon | GetRight | 46772 | 529/783 | 2026-10-08 20:09 UTC |  |
| 2 | g_kMainMenuButton2HighlightedColor | a | 42392 | 9/783 | 2026-10-08 20:09 UTC |  |
| 3 | g_kMainMenuButton2HighlightedColor | b | 42392 | 9/783 | 2026-10-08 20:09 UTC |  |
| 4 | g_kMainMenuButton2HighlightedColor | g | 42392 | 9/783 | 2026-10-08 20:09 UTC |  |
| 5 | g_kMainMenuButton2HighlightedColor | r | 42392 | 9/783 | 2026-10-08 20:09 UTC |  |
| 6 | App | CharacterClass_IsCollisionAlertEnabled | 22873 | 669/783 | 2026-10-13 08:10 UTC |  |
| 7 | App | SortedRegionMenu_GetRoot | 19307 | 78/783 | 2026-10-08 20:09 UTC |  |
| 8 | SortedRegionMenu_GetRoot() | GetNumChildren | 19307 | 78/783 | 2026-10-08 20:09 UTC |  |
| 9 | TGPane | GetBottom | 19180 | 511/783 | 2026-10-08 20:09 UTC |  |
| 10 | App | __path__ | 17498 | 392/783 | 2026-10-08 20:09 UTC |  |
| 11 | TGFrame | GetRight | 16078 | 115/783 | 2026-10-08 20:09 UTC |  |
| 12 | SparkEmitterProperty_Create() | SetOrientation | 13449 | 246/783 | 2026-10-08 20:09 UTC |  |
| 13 | SparkEmitterProperty_Create() | SetPosition | 13449 | 246/783 | 2026-10-08 20:09 UTC |  |
| 14 | App | SparkEmitterProperty_Create | 10770 | 246/783 | 2026-10-08 20:09 UTC |  |
| 15 | SparkEmitterProperty_Create() | GetName | 10770 | 246/783 | 2026-10-08 20:09 UTC |  |
| 16 | SmokeEmitterProperty_Create() | SetOrientation | 8269 | 273/783 | 2026-10-08 20:09 UTC |  |
| 17 | SmokeEmitterProperty_Create() | SetPosition | 8269 | 273/783 | 2026-10-08 20:09 UTC |  |
| 18 | TGParagraph | GetRight | 8220 | 511/783 | 2026-10-08 20:09 UTC |  |
| 19 | App | TGProfilingInfo_SetTimingData | 8214 | 61/783 | 2026-09-29 14:03 UTC |  |
| 20 | App | SmokeEmitterProperty_Create | 6859 | 273/783 | 2026-10-08 20:09 UTC |  |
| 21 | SmokeEmitterProperty_Create() | GetName | 6859 | 273/783 | 2026-10-08 20:09 UTC |  |
| 22 | TGPane | GetRight | 6850 | 511/783 | 2026-10-08 20:09 UTC |  |
| 23 | PhaserSystem | CanFire | 6352 | 3/783 | 2026-09-14 15:59 UTC |  |
| 24 | PhaserSystem | GetAmmo | 6352 | 3/783 | 2026-09-14 15:59 UTC |  |
| 25 | TorpedoSystem | CanFire | 6352 | 3/783 | 2026-09-14 15:59 UTC |  |
| 26 | TractorBeamSystem | CanFire | 5208 | 3/783 | 2026-09-14 15:59 UTC |  |
| 27 | TractorBeamSystem | GetAmmo | 5208 | 3/783 | 2026-09-14 15:59 UTC |  |
| 28 | TorpedoSystem | GetAmmo | 3176 | 3/783 | 2026-09-14 15:59 UTC |  |
| 29 | ExplodeEmitterProperty_Create() | SetOrientation | 3084 | 246/783 | 2026-10-08 20:09 UTC |  |
| 30 | ExplodeEmitterProperty_Create() | SetPosition | 3084 | 246/783 | 2026-10-08 20:09 UTC |  |
| 31 | EngPowerCtrl | GetBottom | 2740 | 511/783 | 2026-10-08 20:09 UTC |  |
| 32 | ShipClass | subsystems | 2474 | 513/783 | 2026-10-08 20:09 UTC |  |
| 33 | App | ExplodeEmitterProperty_Create | 2379 | 246/783 | 2026-10-08 20:09 UTC |  |
| 34 | ExplodeEmitterProperty_Create() | GetName | 2379 | 246/783 | 2026-10-08 20:09 UTC |  |
| 35 | KeyboardBinding | LaunchEvent | 2172 | 48/783 | 2026-09-29 18:39 UTC |  |
| 36 | CharacterClass | SetGender | 2054 | 167/783 | 2026-10-08 20:09 UTC |  |
| 37 | CharacterClass | SetRandomAnimationChance | 2054 | 167/783 | 2026-10-08 20:09 UTC |  |
| 38 | CharacterClass | SetSize | 2054 | 167/783 | 2026-10-08 20:09 UTC |  |
| 39 | TGInputManager | MoveMouseCursorTo | 1890 | 758/783 | 2026-10-13 08:10 UTC |  |
| 40 | CharacterClass | SetBlinkChance | 1855 | 167/783 | 2026-10-08 20:09 UTC |  |
| 41 | STSubPane | ResizeToContents | 1658 | 390/783 | 2026-10-06 09:09 UTC |  |
| 42 | _STStylizedWindow | ScrollToBottom | 1658 | 390/783 | 2026-10-06 09:09 UTC |  |
| 43 | CharacterClass | SetAnimatedSpeaking | 1520 | 167/783 | 2026-10-08 20:09 UTC |  |
| 44 | CharacterClass | SetBlinkStages | 1520 | 167/783 | 2026-10-08 20:09 UTC |  |
| 45 | App | BlinkingLightProperty_Create | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 46 | BlinkingLightProperty_Create() | GetName | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 47 | BlinkingLightProperty_Create() | SetColor | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 48 | BlinkingLightProperty_Create() | SetDuration | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 49 | BlinkingLightProperty_Create() | SetOrientation | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 50 | BlinkingLightProperty_Create() | SetPeriod | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 51 | BlinkingLightProperty_Create() | SetPosition | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 52 | BlinkingLightProperty_Create() | SetRadius | 1476 | 68/783 | 2026-10-06 09:09 UTC |  |
| 53 | BlinkingLightProperty_Create() | SetTextureName | 1451 | 57/783 | 2026-10-06 09:09 UTC |  |
| 54 | STButton | SetName | 1387 | 470/783 | 2026-10-08 20:09 UTC |  |
| 55 | EngPowerCtrl | GetRight | 1370 | 511/783 | 2026-10-08 20:09 UTC |  |
| 56 | TGFrame | GetBottom | 1370 | 511/783 | 2026-10-08 20:09 UTC |  |
| 57 | TGParagraph | GetBottom | 1370 | 511/783 | 2026-10-08 20:09 UTC |  |
| 58 | Mission | AddPrecreatedShip | 1208 | 153/783 | 2026-10-08 20:09 UTC |  |
| 59 | STTopLevelMenu | GetContainingWindow | 1166 | 179/783 | 2026-10-08 20:09 UTC |  |
| 60 | STButton | GetName | 842 | 337/783 | 2026-10-08 20:09 UTC |  |
| 61 | Game | AddPersistentModule | 773 | 773/783 | 2026-10-13 08:10 UTC |  |
| 62 | _STStylizedWindow | ScrollToTop | 694 | 349/783 | 2026-09-30 06:36 UTC |  |
| 63 | App | g_kMainMenuButton2HighlightedColor | 658 | 96/783 | 2026-10-08 20:09 UTC |  |
| 64 | Planet | GetCloakingSubsystem | 619 | 2/783 | 2026-08-17 14:57 UTC |  |
| 65 | Planet | GetCloakingSubsystem.IsTryingToCloak | 619 | 2/783 | 2026-08-17 14:57 UTC |  |
| 66 | STTargetMenu | GetHeight | 583 | 179/783 | 2026-10-08 20:09 UTC |  |
| 67 | STTargetMenu | Resize | 583 | 179/783 | 2026-10-08 20:09 UTC |  |
| 68 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 583 | 179/783 | 2026-10-08 20:09 UTC |  |
| 69 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 583 | 179/783 | 2026-10-08 20:09 UTC |  |
| 70 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 583 | 179/783 | 2026-10-08 20:09 UTC |  |
| 71 | KeyboardBinding | FindKey | 546 | 90/783 | 2026-10-08 20:09 UTC |  |
| 72 | CharacterClass | SetLookAtAdj | 544 | 231/783 | 2026-10-08 20:09 UTC |  |
| 73 | TGPane | SetAlwaysHandleEvents | 446 | 390/783 | 2026-10-06 09:09 UTC |  |
| 74 | TGPane | SetNotAlwaysHandleEvents | 443 | 388/783 | 2026-10-06 09:09 UTC |  |
| 75 | CharacterClass | SetAsExtra | 429 | 128/783 | 2026-10-06 12:29 UTC |  |
| 76 | STTopLevelMenu | ForceUpdate | 388 | 179/783 | 2026-10-08 20:09 UTC |  |
| 77 | TGParagraph | SetFontGroup | 388 | 179/783 | 2026-10-08 20:09 UTC |  |
| 78 | PhaserBank | CalculateRoughDirection | 349 | 1/783 | 2026-09-24 08:51 UTC |  |
| 79 | PhaserBank | CalculateRoughDirection.Dot | 349 | 1/783 | 2026-09-24 08:51 UTC |  |
| 80 | TGAnimAction | GetNumActions | 321 | 17/783 | 2026-10-06 12:13 UTC |  |
| 81 | PulseWeaponSystem | CanFire | 244 | 1/783 | 2026-09-14 15:59 UTC |  |
| 82 | PulseWeaponSystem | GetAmmo | 244 | 1/783 | 2026-09-14 15:59 UTC |  |
| 83 | TGParagraph | RecalcBounds | 218 | 34/783 | 2026-09-29 18:39 UTC |  |
| 84 | TGAnimAction | GetAction | 204 | 17/783 | 2026-10-06 12:13 UTC |  |
| 85 | STTargetMenu | ForceUpdate | 194 | 179/783 | 2026-10-08 20:09 UTC |  |
| 86 | STTopLevelMenu | Resize | 194 | 179/783 | 2026-10-08 20:09 UTC |  |
| 87 | STTopLevelMenu | ResizeToContents | 194 | 179/783 | 2026-10-08 20:09 UTC |  |
| 88 | RockClass | subsystems | 192 | 6/783 | 2026-10-08 20:09 UTC |  |
| 89 | App | g_kSTMenu2Selected | 187 | 97/783 | 2026-10-08 20:09 UTC |  |
| 90 | CharacterClass | SetAudioMode | 178 | 164/783 | 2026-10-08 20:09 UTC |  |
| 91 | App | MapWindow_Cast | 157 | 132/783 | 2026-10-08 20:09 UTC |  |
| 92 | MapWindow_Cast() | IsWindowActive | 157 | 132/783 | 2026-10-08 20:09 UTC |  |
| 93 | App | EngineGlowProperty_Create | 148 | 39/783 | 2026-09-28 11:45 UTC |  |
| 94 | EngineGlowProperty_Create() | GetName | 148 | 39/783 | 2026-09-28 11:45 UTC |  |
| 95 | PhaserBank | SetConditionPercentage | 129 | 17/783 | 2026-09-04 20:31 UTC |  |
| 96 | CharacterClass | SetMenuEnabled | 118 | 79/783 | 2026-10-08 20:09 UTC |  |
| 97 | TGAnimAction | GetAction._anim_node | 117 | 17/783 | 2026-10-06 12:13 UTC |  |
| 98 | App | EnergyWeapon_Cast | 104 | 11/783 | 2026-10-08 20:09 UTC |  |
| 99 | EnergyWeapon_Cast() | GetMaxCharge | 104 | 11/783 | 2026-10-08 20:09 UTC |  |
| 100 | EnergyWeapon_Cast() | SetChargeLevel | 104 | 11/783 | 2026-10-08 20:09 UTC |  |
| 101 | TorpedoTube | SetConditionPercentage | 102 | 17/783 | 2026-09-04 20:31 UTC |  |
| 102 | _CinematicWindow | AddChild | 89 | 36/783 | 2026-09-29 18:39 UTC |  |
| 103 | TGAnimAction | GetAction._clip | 87 | 17/783 | 2026-10-06 12:13 UTC |  |
| 104 | ShipSubsystem | SetConditionPercentage | 83 | 18/783 | 2026-09-29 21:10 UTC |  |
| 105 | _CinematicWindow | DeleteChild | 82 | 30/783 | 2026-09-29 18:39 UTC |  |
| 106 | CharacterClass | SetRandomAnimationEnabled | 80 | 79/783 | 2026-10-08 20:09 UTC |  |
| 107 | TGEvent | GetObjPtr | 43 | 2/783 | 2026-10-07 08:58 UTC |  |
| 108 | App | g_kSTMenu1NormalBase | 42 | 7/783 | 2026-10-08 20:09 UTC |  |
| 109 | HullSubsystem | SetConditionPercentage | 36 | 17/783 | 2026-09-04 20:31 UTC |  |
| 110 | TGEventManager | BroadcastEvent | 36 | 22/783 | 2026-09-29 14:03 UTC |  |
| 111 | App | g_kSTMenu3NormalBase | 35 | 7/783 | 2026-10-08 20:09 UTC |  |
| 112 | TractorBeam | SetConditionPercentage | 34 | 17/783 | 2026-09-04 20:31 UTC |  |
| 113 | App | InterfaceModule_ForceFocusOnObject | 32 | 10/783 | 2026-09-24 10:28 UTC |  |
| 114 | WarpSequence | SetEventDestination | 24 | 24/783 | 2026-10-06 12:13 UTC |  |
| 115 | PowerSubsystem | SetConditionPercentage | 20 | 17/783 | 2026-09-04 20:31 UTC |  |
| 116 | SensorSubsystem | SetConditionPercentage | 20 | 17/783 | 2026-09-04 20:31 UTC |  |
| 117 | ShieldSubsystem | SetConditionPercentage | 20 | 17/783 | 2026-09-04 20:31 UTC |  |
| 118 | Waypoint | StartGetSubsystemMatch | 19 | 4/783 | 2026-08-06 10:09 UTC |  |
| 119 | RepairSubsystem | SetConditionPercentage | 16 | 16/783 | 2026-09-04 20:31 UTC |  |
| 120 | App | WarpFlash_CreateWithoutShip | 14 | 14/783 | 2026-10-08 20:09 UTC |  |
| 121 | WarpEngineSubsystem | GetWarpExitLocation | 14 | 14/783 | 2026-10-08 20:09 UTC |  |
| 122 | WarpEngineSubsystem | GetWarpExitRotation | 14 | 14/783 | 2026-10-08 20:09 UTC |  |
| 123 | WarpEngineSubsystem | SetPlacement | 14 | 14/783 | 2026-10-08 20:09 UTC |  |
| 124 | App | ZoomCameraObjectClass_Cast | 8 | 8/783 | 2026-10-08 20:09 UTC |  |
| 125 | App | g_kDamageDisplayDisabledColor | 8 | 8/783 | 2026-10-08 20:09 UTC |  |
| 126 | PulseWeapon | SetConditionPercentage | 8 | 1/783 | 2026-09-04 20:26 UTC |  |
| 127 | ZoomCameraObjectClass_Cast() | ToggleZoom | 8 | 8/783 | 2026-10-08 20:09 UTC |  |
| 128 | App | g_kDamageDisplayDamagedColor | 7 | 7/783 | 2026-10-08 20:09 UTC |  |
| 129 | App | g_kDamageDisplayDestroyedColor | 7 | 7/783 | 2026-10-08 20:09 UTC |  |
| 130 | App | g_kMainMenuButtonColor | 7 | 7/783 | 2026-10-08 20:09 UTC |  |
| 131 | Game | InGodMode | 6 | 2/783 | 2026-07-16 18:38 UTC |  |
| 132 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 133 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 134 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 135 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 136 | Sun | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 137 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 138 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 139 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/783 | 2026-07-13 12:09 UTC |  |
| 140 | CloakingSubsystem | SetConditionPercentage | 4 | 1/783 | 2026-09-04 20:26 UTC |  |
| 141 | ShipClass | DisableGlowAlphaMaps | 4 | 1/783 | 2026-09-29 21:10 UTC |  |
| 142 | App | CharacterClass_SetAllowExtras | 3 | 2/783 | 2026-09-02 19:35 UTC |  |
| 143 | AsteroidField | SetNavPoint | 3 | 3/783 | 2026-10-06 12:13 UTC |  |
| 144 | AsteroidField | SetStatic | 3 | 3/783 | 2026-10-06 12:13 UTC |  |
| 145 | Game | SetGodMode | 3 | 2/783 | 2026-07-16 18:38 UTC |  |
| 146 | GridClass | GetPhaserSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 147 | GridClass | GetPulseWeaponSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 148 | GridClass | GetTorpedoSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 149 | GridClass | GetTractorBeamSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 150 | Sun | GetPhaserSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 151 | Sun | GetPulseWeaponSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 152 | Sun | GetTorpedoSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 153 | Sun | GetTractorBeamSystem | 3 | 2/783 | 2026-07-13 12:09 UTC |  |
| 154 | TGEventHandlerObject_Cast() | RemoveHandlerForInstance | 3 | 1/783 | 2026-10-08 20:09 UTC |  |
| 155 | TorpedoSystem | IsTubeReady | 3 | 3/783 | 2026-09-16 16:44 UTC |  |
| 156 | App | InterfaceModule_DoTheRightThing | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 157 | App | STStylizedWindow_Create | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 158 | App | TGEventHandlerObject_Cast | 2 | 1/783 | 2026-10-08 20:09 UTC |  |
| 159 | STStylizedWindow_Create() | AddChild | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 160 | STStylizedWindow_Create() | InteriorChangedSize | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 161 | STStylizedWindow_Create() | SetVisible | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 162 | STSubPane | GetConceptualParent | 2 | 1/783 | 2026-08-21 15:53 UTC |  |
| 163 | STSubPane | GetConceptualParent.SetNotVisible | 2 | 1/783 | 2026-08-21 15:53 UTC |  |
| 164 | _CinematicWindow | MoveToFront | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 165 | _CinematicWindow | SetFocus | 2 | 2/783 | 2026-09-04 09:16 UTC |  |
| 166 | App | CharacterClass_GetCharacterFromMenu | 1 | 1/783 | 2026-08-21 15:53 UTC |  |
| 167 | App | STMissionLog_GetMissionLog | 1 | 1/783 | 2026-08-31 13:22 UTC |  |
| 168 | App | WarpFlash_Create | 1 | 1/783 | 2026-10-06 12:29 UTC |  |
| 169 | CharacterClass_GetCharacterFromMenu() | GetName | 1 | 1/783 | 2026-08-21 15:53 UTC |  |
| 170 | STMissionLog_GetMissionLog() | GetFirstChild | 1 | 1/783 | 2026-08-31 13:22 UTC |  |
| 171 | STMissionLog_GetMissionLog() | SetVisible | 1 | 1/783 | 2026-08-31 13:22 UTC |  |
| 172 | STTopLevelMenu | GetConceptualParent | 1 | 1/783 | 2026-08-21 15:53 UTC |  |
| 173 | STTopLevelMenu | GetConceptualParent.SetNotVisible | 1 | 1/783 | 2026-08-21 15:53 UTC |  |
| 174 | SortedRegionMenu | SetRegionName | 1 | 1/783 | 2026-09-29 21:10 UTC |  |
| 175 | TGPane | GetConceptualParent | 1 | 1/783 | 2026-08-21 15:53 UTC |  |
| 176 | TGPane | GetConceptualParent.SetNotVisible | 1 | 1/783 | 2026-08-21 15:53 UTC |  |

## Resolved

| owner | attr | markedResolvedOn | lastSeenOn |
|---|---|---|---|
| App | ET_FRIENDLY_FIRE_GAME_OVER | 2026-07-13 | 2026-07-13 19:30 UTC |
| App | ET_FRIENDLY_FIRE_REPORT | 2026-07-13 | 2026-07-13 19:30 UTC |
| CharacterAction | _anim_node | 2026-07-13 | 2026-07-13 19:30 UTC |
| CharacterAction | _anim_node.kind | 2026-07-13 | 2026-07-13 19:30 UTC |
| CharacterAction | _clip | 2026-07-13 | 2026-07-13 19:30 UTC |
| EventType | ET_FRIENDLY_FIRE_GAME_OVER | 2026-07-13 | 2026-07-13 19:30 UTC |
| EventType | ET_FRIENDLY_FIRE_REPORT | 2026-07-13 | 2026-07-13 19:30 UTC |
| ImpulseEngineSubsystem | GetCurMaxSpeed | 2026-07-13 | 2026-07-13 20:01 UTC |
| LightPlacement | GetPhaserSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetPhaserSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetPulseWeaponSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetPulseWeaponSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetTorpedoSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetTorpedoSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetTractorBeamSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| LightPlacement | GetTractorBeamSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetPhaserSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetPhaserSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetPulseWeaponSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetPulseWeaponSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetTorpedoSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetTorpedoSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetTractorBeamSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetTractorBeamSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Planet | GetVelocity | 2026-07-13 | 2026-07-13 08:53 UTC |
| Planet | GetVelocity.x | 2026-07-13 | 2026-07-13 08:53 UTC |
| Planet | GetVelocity.y | 2026-07-13 | 2026-07-13 08:53 UTC |
| Planet | GetVelocity.z | 2026-07-13 | 2026-07-13 08:53 UTC |
| Planet | IsDying | 2026-07-13 | — |
| ShipClass | _drift_velocity | 2026-07-13 | 2026-07-13 19:30 UTC |
| ShipClass | _drift_velocity.Length | 2026-07-13 | 2026-07-13 19:30 UTC |
| TGAnimAction | _action_type | 2026-07-13 | — |
| TGScriptAction | _action_type | 2026-07-13 | — |
| TGScriptAction | _anim_node | 2026-07-13 | 2026-07-13 19:30 UTC |
| TGScriptAction | _anim_node.kind | 2026-07-13 | 2026-07-13 19:30 UTC |
| TorpedoTube | GetMaxCharge | 2026-07-13 | — |
| TorpedoTube | UpdateCharge | 2026-07-13 | 2026-07-13 12:57 UTC |
| WarpEngineSubsystem | TransitionToState | 2026-07-13 | — |
| Waypoint | GetPhaserSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetPhaserSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetPulseWeaponSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetPulseWeaponSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetTorpedoSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetTorpedoSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetTractorBeamSystem | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | GetTractorBeamSystem.GetNumChildSubsystems | 2026-07-13 | 2026-07-13 12:09 UTC |
| Waypoint | IsDying | 2026-07-13 | 2026-07-13 13:43 UTC |
| WeaponHitEvent | GetWeaponType | 2026-07-13 | 2026-07-13 20:01 UTC |
| WeaponHitEvent | TRACTOR_BEAM | 2026-07-13 | 2026-07-13 20:01 UTC |
| App | ET_AI_CONDITION_CHANGED | 2026-07-14 | 2026-07-14 00:15 UTC |
| App | ET_AI_SHIELD_WATCHER | 2026-07-14 | 2026-07-14 00:15 UTC |
| App | ET_AI_SYSTEM_STATUS_WATCHER | 2026-07-14 | 2026-07-14 00:15 UTC |
| App | ET_SCANNABLE_CHANGE | 2026-07-14 | 2026-07-14 00:31 UTC |
| App | ET_TARGET_WAS_CHANGED | 2026-07-14 | 2026-07-14 00:31 UTC |
| App | PulseWeaponSystem_Cast | 2026-07-14 | 2026-07-14 00:15 UTC |
| App | Weapon_Cast | 2026-07-14 | 2026-07-14 00:15 UTC |
| EventType | ET_AI_CONDITION_CHANGED | 2026-07-14 | 2026-07-14 00:15 UTC |
| EventType | ET_AI_SHIELD_WATCHER | 2026-07-14 | 2026-07-14 00:15 UTC |
| EventType | ET_AI_SYSTEM_STATUS_WATCHER | 2026-07-14 | 2026-07-14 00:15 UTC |
| EventType | ET_SCANNABLE_CHANGE | 2026-07-14 | 2026-07-14 00:31 UTC |
| EventType | ET_TARGET_WAS_CHANGED | 2026-07-14 | 2026-07-14 00:31 UTC |
| HullSubsystem | GetObjType | 2026-07-14 | 2026-07-14 00:15 UTC |
| PhaserSystem | GetObjType | 2026-07-14 | 2026-07-14 00:15 UTC |
| PhaserSystem | ShouldBeAimed | 2026-07-14 | 2026-07-14 00:15 UTC |
| Planet | IsScannable | 2026-07-14 | 2026-07-14 00:31 UTC |
| PulseWeaponSystem_Cast() | GetNumChildSubsystems | 2026-07-14 | 2026-07-14 00:15 UTC |
| ShipClass | IsScannable | 2026-07-14 | 2026-07-14 00:31 UTC |
| TorpedoSystem | GetObjType | 2026-07-14 | 2026-07-14 00:15 UTC |
| TorpedoSystem | ShouldBeAimed | 2026-07-14 | 2026-07-14 00:15 UTC |
| App | ET_WEAPON_FIRED | 2026-07-15 | 2026-07-13 23:37 UTC |
| CharacterAction | name | 2026-07-15 | 2026-07-15 08:23 UTC |
| PhaserSystem | SetForceUpdate | 2026-07-15 | 2026-07-15 11:17 UTC |
| PulseWeapon | IsSkewFire | 2026-07-15 | 2026-07-15 21:54 UTC |
| TorpedoSystem | SetForceUpdate | 2026-07-15 | 2026-07-15 09:45 UTC |
| App | ET_INPUT_SELF_DESTRUCT | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_0 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_1 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_2 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_3 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_4 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_5 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_6 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_7 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_8 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_9 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_A | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_B | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_C | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_D | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_E | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F1 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F10 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F11 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F12 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F2 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F3 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F4 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F5 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F6 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F7 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F8 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_F9 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_G | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_H | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_I | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_J | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_K | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_L | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_M | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_N | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_O | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_P | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_Q | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_R | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_S | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_T | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_U | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_V | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_W | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_X | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_Y | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_ALT_Z | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_A | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_B | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_C | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_D | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_E | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_F | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_G | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_H | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_I | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_J | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_K | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_L | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_M | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_N | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_O | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_P | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_Q | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_R | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_S | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_T | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_U | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_V | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_W | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_X | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_Y | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CAPS_Z | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_0 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_1 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_2 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_3 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_4 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_5 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_6 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_7 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_8 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_9 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_A | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_B | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_C | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_D | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_E | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F1 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F10 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F11 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F12 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F2 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F3 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F4 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F5 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F6 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F7 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F8 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_F9 | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_G | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_H | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_I | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_J | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_K | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_L | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_M | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_N | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_O | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_P | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_Q | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_R | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_S | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_T | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_U | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_V | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_W | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_X | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_Y | 2026-07-16 | 2026-07-16 06:01 UTC |
| App | WC_CTRL_Z | 2026-07-16 | 2026-07-16 06:01 UTC |
| Game | LoadDatabaseSoundInGroup | 2026-07-16 | 2026-07-16 16:34 UTC |
| TorpedoSystem | SetSingleFire | 2026-07-16 | 2026-07-16 06:01 UTC |
| EngPowerDisplay | IsCompletelyVisible | 2026-07-17 | 2026-07-17 20:10 UTC |
| STCharacterMenu | GetFirstChild | 2026-07-28 17:38 | 2026-07-28 12:02 UTC |
| STCharacterMenu | GetFirstChild.SetDisabled | 2026-07-28 17:38 | 2026-07-28 12:02 UTC |
| STCharacterMenu | GetFirstChild.SetEnabled | 2026-07-28 17:38 | 2026-07-28 12:02 UTC |
| STCharacterMenu | GetNextChild | 2026-07-28 17:38 | 2026-07-28 12:02 UTC |
| STCharacterMenu | GetNextChild.SetDisabled | 2026-07-28 17:38 | 2026-07-28 12:02 UTC |
| STCharacterMenu | GetNextChild.SetEnabled | 2026-07-28 17:38 | 2026-07-28 12:02 UTC |
| STButton | IsDisabled | 2026-07-29 | 2026-07-29 07:31 UTC |
| STCharacterMenu | GetNthChild | 2026-08-06 | 2026-08-06 11:38 UTC |
| STCharacterMenu | GetNthChild.IsEnabled | 2026-08-06 | 2026-08-06 11:38 UTC |
| STSubPane | GetButtonW | 2026-08-06 | 2026-08-06 11:38 UTC |
| STSubPane | GetButtonW.SetChosen | 2026-08-06 | 2026-08-06 11:38 UTC |
| ShipClass | TurnTowardDifference | 2026-08-06 | 2026-07-29 08:14 UTC |
| App | ET_PLAYER_TORPEDO_TYPE_CHANGED | 2026-08-06 11:14 | 2026-08-06 11:13 UTC |
| EventType | ET_PLAYER_TORPEDO_TYPE_CHANGED | 2026-08-06 11:14 | 2026-08-06 11:13 UTC |
| STCharacterMenu | RemoveItemW | 2026-08-06 15:16 | 2026-08-06 11:38 UTC |
| App | Torpedo_Cast | 2026-08-09 | 2026-07-17 19:27 UTC |
| CharacterClass | AddPositionZoom | 2026-08-09 | 2026-07-22 21:44 UTC |
| ImpulseEngineSubsystem | SetInvincible | 2026-08-09 | 2026-07-13 23:39 UTC |
| PulseWeaponSystem | ShouldBeAimed | 2026-08-09 | 2026-07-14 00:15 UTC |
| ShipClass | CompleteStop | 2026-08-09 | 2026-07-17 21:33 UTC |
| ShipClass | GetImpulse | 2026-08-09 | 2026-07-23 07:41 UTC |
| ShipClass | GetSceneNodeId | 2026-08-09 | 2026-07-16 18:38 UTC |
| ShipClass | IsDestroyBrokenSystems | 2026-08-09 | 2026-07-17 19:27 UTC |
| ShipClass | IsPlayerShip | 2026-08-09 | 2026-07-13 13:43 UTC |
| ShipClass | SetInvincible | 2026-08-09 | 2026-07-13 23:39 UTC |
| ShipClass | SetScannable | 2026-08-09 | 2026-07-13 23:37 UTC |
| ShipClass | SetSplashDamage | 2026-08-09 | 2026-07-23 19:20 UTC |
| ShipSubsystem | SetInvincible | 2026-08-09 | 2026-07-13 23:39 UTC |
| TGEvent | GetCString | 2026-08-09 | 2026-07-13 23:37 UTC |
| Torpedo_Cast() | GetObjID | 2026-08-09 | 2026-07-17 19:27 UTC |
| WarpEngineSubsystem | SetInvincible | 2026-08-09 | 2026-07-13 23:39 UTC |
| App | g_kMusicManager | 2026-08-10 | 2026-08-07 07:51 UTC |
| g_kMusicManager | PlayFanfare | 2026-08-10 | 2026-08-07 07:51 UTC |
| App | WarpSequence_Cast | 2026-08-11 | 2026-08-11 17:55 UTC |
| App | WaypointEvent_Create | 2026-08-11 | 2026-08-10 11:34 UTC |
| WarpSequence_Cast() | GetDestination | 2026-08-11 | 2026-08-11 17:55 UTC |
| WarpSequence_Cast() | GetDestinationMission | 2026-08-11 | 2026-08-11 17:55 UTC |
| WaypointEvent_Create() | GetDestination | 2026-08-11 | 2026-08-10 11:34 UTC |
| WaypointEvent_Create() | GetEventType | 2026-08-11 | 2026-08-10 11:34 UTC |
| WaypointEvent_Create() | SetDestination | 2026-08-11 | 2026-08-10 11:34 UTC |
| WaypointEvent_Create() | SetEventType | 2026-08-11 | 2026-08-10 11:34 UTC |
| WaypointEvent_Create() | SetPlacement | 2026-08-11 | 2026-08-10 11:34 UTC |
| ShipClass | SetTargetable | 2026-08-16 | 2026-08-06 10:09 UTC |
| TGInputManager | GetDisplayStringFromUnicode | 2026-08-16 | 2026-08-11 21:48 UTC |
| App | CinematicWindow_Cast | 2026-08-18 | 2026-08-18 13:43 UTC |
| CinematicWindow_Cast() | SetInteractive | 2026-08-18 | 2026-08-18 13:43 UTC |
| TGKeyboardEvent | EventHandled | 2026-08-18 | 2026-08-18 15:40 UTC |
| TGKeyboardEvent | SetHandled | 2026-08-18 | 2026-08-18 15:40 UTC |
| TGParagraph | SetString | 2026-08-18 | 2026-08-18 15:23 UTC |
| App | UtopiaModule_ConvertGameUnitsToKilometers | 2026-08-21 | 2026-08-21 12:29 UTC |
| SortedRegionMenu | SetPlacementName | 2026-08-21 | 2026-08-21 09:37 UTC |
| ShieldSubsystem | GetNumShields | 2026-08-30 | 2026-08-30 21:41 UTC |
| App | ET_AI_REACHED_WAYPOINT | 2026-08-31 | 2026-08-10 11:34 UTC |
| App | ET_CAMERA_ANIMATION_DONE | 2026-08-31 | 2026-08-22 08:23 UTC |
| App | ET_CANCEL | 2026-08-31 | 2026-07-13 23:39 UTC |
| App | ET_CANT_FIRE | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_CONTACT_ENGINEERING | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_EXITED_WARP | 2026-08-31 | 2026-08-22 07:37 UTC |
| App | ET_FIRE | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_FRIENDLY_TRACTOR_REPORT | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_INPUT_FIRSTPERSON | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_TAB_FOCUS_CHANGE | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_TOGGLE_PICK_FIRE | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_BACKWARD | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_DOWN | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_FORWARD | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_LEFT | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_RIGHT | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_TARGET | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INPUT_VIEWSCREEN_UP | 2026-08-31 | 2026-07-28 10:11 UTC |
| App | ET_INVALID | 2026-08-31 | 2026-08-30 22:45 UTC |
| App | ET_IN_SYSTEM_WARP | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_KEYBOARD | 2026-08-31 | 2026-08-11 21:48 UTC |
| App | ET_LAUNCH_PROBE | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_LOAD_GAME | 2026-08-31 | 2026-07-13 23:39 UTC |
| App | ET_MOUSE | 2026-08-31 | 2026-07-26 08:41 UTC |
| App | ET_NAME_CHANGE | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_NAV_POINT_CHANGED | 2026-08-31 | 2026-08-20 18:58 UTC |
| App | ET_NEW_GAME | 2026-08-31 | 2026-07-13 23:39 UTC |
| App | ET_OBJECTIVES | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_OBJECT_COLLISION | 2026-08-31 | 2026-08-21 15:53 UTC |
| App | ET_PLANET_COLLISION | 2026-08-31 | 2026-08-22 07:37 UTC |
| App | ET_RADAR_TOGGLE_CLICKED | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_REPORT_GOAL_INFO | 2026-08-31 | 2026-08-22 08:23 UTC |
| App | ET_RESTORE_PERSISTENT_TARGET | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_SB12_RELOAD | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_SB12_REPAIR | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_SET_TARGET | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_SET_WARP_SEQUENCE | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_SHOW_MISSION_LOG | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_TARGET_LIST_OBJECT_ADDED | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_TARGET_LIST_OBJECT_REMOVED | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_TORPEDO_ENTERED_SET | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_TORPEDO_EXITED_SET | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_TRACTOR_BEAM_STARTED_FIRING | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_TRACTOR_BEAM_STARTED_HITTING | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_TRACTOR_BEAM_STOPPED_FIRING | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | ET_TRACTOR_BEAM_STOPPED_HITTING | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | ET_UI_REPOSITION | 2026-08-31 | 2026-08-22 08:23 UTC |
| App | GENUS_ASTEROID | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | GENUS_STATION | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | PSID_INVALID | 2026-08-31 | 2026-08-22 09:52 UTC |
| App | SPECIES_FEDERATION_START | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | SPECIES_UNKNOWN | 2026-08-31 | 2026-08-30 23:25 UTC |
| App | TGSAF_DEFAULTS | 2026-08-31 | 2026-08-21 20:37 UTC |
| EventType | ET_CANCEL | 2026-08-31 | 2026-07-13 23:39 UTC |
| EventType | ET_CANT_FIRE | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_CONTACT_ENGINEERING | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_EXITED_WARP | 2026-08-31 | 2026-08-22 07:37 UTC |
| EventType | ET_FIRE | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_FRIENDLY_TRACTOR_REPORT | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_INPUT_TOGGLE_PICK_FIRE | 2026-08-31 | 2026-07-13 23:39 UTC |
| EventType | ET_IN_SYSTEM_WARP | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_LAUNCH_PROBE | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_LOAD_GAME | 2026-08-31 | 2026-07-13 23:39 UTC |
| EventType | ET_NAME_CHANGE | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_NAV_POINT_CHANGED | 2026-08-31 | 2026-08-20 18:58 UTC |
| EventType | ET_NEW_GAME | 2026-08-31 | 2026-07-13 23:39 UTC |
| EventType | ET_OBJECTIVES | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_OBJECT_COLLISION | 2026-08-31 | 2026-08-21 15:53 UTC |
| EventType | ET_PLANET_COLLISION | 2026-08-31 | 2026-08-22 07:37 UTC |
| EventType | ET_REPORT_GOAL_INFO | 2026-08-31 | 2026-08-22 08:23 UTC |
| EventType | ET_RESTORE_PERSISTENT_TARGET | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_SET_TARGET | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_SET_WARP_SEQUENCE | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_SHOW_MISSION_LOG | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_TARGET_LIST_OBJECT_ADDED | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_TARGET_LIST_OBJECT_REMOVED | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_TORPEDO_ENTERED_SET | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_TORPEDO_EXITED_SET | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_TRACTOR_BEAM_STARTED_FIRING | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_TRACTOR_BEAM_STARTED_HITTING | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_TRACTOR_BEAM_STOPPED_FIRING | 2026-08-31 | 2026-08-30 23:25 UTC |
| EventType | ET_TRACTOR_BEAM_STOPPED_HITTING | 2026-08-31 | 2026-08-22 09:52 UTC |
| EventType | ET_UI_REPOSITION | 2026-08-31 | 2026-08-22 08:23 UTC |
| EventType | ET_WEAPON_FIRED | 2026-08-31 | 2026-07-13 23:37 UTC |
| SortedRegionMenu | SetMissionName | 2026-09-02 | 2026-09-02 19:35 UTC |
| ShipClass | GetTargetOffsetTG | 2026-09-14 | 2026-09-14 20:14 UTC |
| App | PhaserBank_Cast | 2026-09-19 | 2026-09-16 16:55 UTC |
| App | PulseWeaponProperty_Cast | 2026-09-19 | 2026-09-19 19:39 UTC |
| App | TGCondition_Cast | 2026-09-19 | 2026-09-02 20:35 UTC |
| App | TGPoint3_GetRandomUnitVector | 2026-09-19 | 2026-09-19 19:39 UTC |
| App | WeaponSystem_Cast | 2026-09-19 | 2026-09-15 21:01 UTC |
| PhaserBank_Cast() | CalculateRoughDirection | 2026-09-19 | 2026-09-16 16:44 UTC |
| PhaserBank_Cast() | CalculateRoughDirection().Dot | 2026-09-19 | 2026-09-16 16:44 UTC |
| PhaserBank_Cast() | CanFire | 2026-09-19 | 2026-09-16 16:55 UTC |
| PhaserBank_Cast() | CanHit | 2026-09-19 | 2026-09-16 16:55 UTC |
| PhaserBank_Cast() | GetChargeLevel | 2026-09-19 | 2026-09-16 16:44 UTC |
| PulseWeaponProperty_Cast() | GetOrientationForward | 2026-09-19 | 2026-09-19 19:39 UTC |
| PulseWeaponProperty_Cast() | GetOrientationForward().x | 2026-09-19 | 2026-09-19 19:39 UTC |
| PulseWeaponProperty_Cast() | GetOrientationForward().y | 2026-09-19 | 2026-09-19 19:39 UTC |
| PulseWeaponProperty_Cast() | GetOrientationForward().z | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGCondition_Cast() | GetStatus | 2026-09-19 | 2026-09-02 20:35 UTC |
| TGPoint3_GetRandomUnitVector() | Add | 2026-09-19 | 2026-09-04 20:31 UTC |
| TGPoint3_GetRandomUnitVector() | Dot | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGPoint3_GetRandomUnitVector() | GetPerpendicularComponent | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGPoint3_GetRandomUnitVector() | GetPerpendicularComponent().Dot | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGPoint3_GetRandomUnitVector() | GetPerpendicularComponent().Unitize | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGPoint3_GetRandomUnitVector() | Scale | 2026-09-19 | 2026-09-04 20:31 UTC |
| TGPoint3_GetRandomUnitVector() | Unitize | 2026-09-19 | 2026-09-04 20:31 UTC |
| TGPoint3_GetRandomUnitVector() | x | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGPoint3_GetRandomUnitVector() | y | 2026-09-19 | 2026-09-19 19:39 UTC |
| TGPoint3_GetRandomUnitVector() | z | 2026-09-19 | 2026-09-19 19:39 UTC |
| WeaponSystem_Cast() | IsInTargetList | 2026-09-19 | 2026-09-15 21:01 UTC |
| WeaponSystem_Cast() | StopFiring | 2026-09-19 | 2026-08-17 16:31 UTC |
| SensorSubsystem | GetIdentificationTime | 2026-10-04 | 2026-09-01 08:26 UTC |
| App | g_kRadarEnemyColor | 2026-10-05 | 2026-09-26 06:36 UTC |
| App | g_kRadarFriendlyColor | 2026-10-05 | 2026-09-26 06:36 UTC |
| App | g_kRadarNeutralColor | 2026-10-05 | 2026-09-26 06:36 UTC |
| App | g_kRadarUnknownColor | 2026-10-05 | 2026-09-26 06:36 UTC |
| SensorSubsystem | GetNumProbes | 2026-10-07 | 2026-10-07 10:20 UTC |
| SensorSubsystem | SetNumProbes | 2026-10-07 | 2026-10-07 10:20 UTC |
| TacticalControlWindow | GetOpenMenu | 2026-10-08 | 2026-08-21 15:53 UTC |
| TacticalControlWindow | SetNotVisible | 2026-10-08 | 2026-10-08 20:09 UTC |
| TacticalControlWindow | SetVisible | 2026-10-08 | 2026-08-21 15:53 UTC |

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:109 | 116655 | 5/783 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 106740 | 25/783 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:100 | 65160 | 2/783 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/PhaserSweep.py:175 | 23864 | 20/783 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 17873 | 436/783 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/ai_inspector_model.py:333 | 9078 | 3/783 |
| 7 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 4979 | 232/783 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 1808 | 3/783 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 1685 | 8/783 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:515 | 1006 | 8/783 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 684 | 89/783 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/IntelligentCircleObject.py:63 | 650 | 5/783 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 424 | 137/783 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:249 | 324 | 1/783 |
| 15 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:274 | 295 | 1/783 |
| 16 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:785 | 286 | 269/783 |
| 17 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 278 | 59/783 |
| 18 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:748 | 264 | 112/783 |
| 19 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 251 | 49/783 |
| 20 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:531 | 247 | 4/783 |
| 21 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/Preprocessors.py:1699 | 229 | 18/783 |
| 22 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/Conditions/ConditionInPhaserFiringArc.py:175 | 198 | 20/783 |
| 23 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 156 | 41/783 |
| 24 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 153 | 60/783 |
| 25 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:1699 | 151 | 9/783 |
| 26 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:261 | 110 | 9/783 |
| 27 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/bridge_placement.py:166 | 87 | 17/783 |
| 28 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/bridge_placement.py:167 | 87 | 17/783 |
| 29 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/PlainAI/PhaserSweep.py:175 | 67 | 2/783 |
| 30 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:234 | 60 | 5/783 |
| 31 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/MissionLib.py:748 | 48 | 19/783 |
| 32 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:298 | 40 | 1/783 |
| 33 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/CinematicInterfaceHandlers.py:121 | 32 | 3/783 |
| 34 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionInPhaserFiringArc.py:175 | 30 | 7/783 |
| 35 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:114 | 28 | 1/783 |
| 36 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:114 | 24 | 1/783 |
| 37 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 21 | 1/783 |
| 38 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 19 | 10/783 |
| 39 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:2537 | 17 | 3/783 |
| 40 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/audio/engine_rumble.py:44 | 9 | 1/783 |
| 41 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/weapon_subsystems.py:531 | 7 | 1/783 |
| 42 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 3 | 1/783 |
| 43 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1127 | 3 | 2/783 |
| 44 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1129 | 3 | 2/783 |
| 45 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/Preprocessors.py:2307 | 3 | 3/783 |
| 46 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 2 | 1/783 |
| 47 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 2 | 1/783 |
| 48 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:748 | 2 | 1/783 |
| 49 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Compound/DockWithStarbase.py:272 | 2 | 1/783 |
| 50 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:130 | 2 | 1/783 |
| 51 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 1 | 1/783 |
| 52 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:785 | 1 | 1/783 |
| 53 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Actions/CameraScriptActions.py:398 | 1 | 1/783 |
| 54 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:321 | 1 | 1/783 |
| 55 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/MissionLib.py:4292 | 1 | 1/783 |
| 56 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/MissionLib.py:4302 | 1 | 1/783 |

## Numeric-coercion call sites (int()==0 risk)

| rank | kind | file:line | total hits | coverage |
|---|---|---|---|---|
| 1 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/BridgeHandlers.py:1355 | 17933 | 58/783 |
| 2 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:123 | 7820 | 46/783 |
| 3 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:21 | 2990 | 50/783 |
| 4 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:22 | 2990 | 50/783 |
| 5 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:23 | 2990 | 50/783 |
| 6 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:179 | 1472 | 46/783 |
| 7 | index | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/BridgeHandlers.py:1355 | 1374 | 20/783 |
| 8 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:774 | 1039 | 3/783 |
| 9 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:214 | 920 | 92/783 |
| 10 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:316 | 613 | 187/783 |
| 11 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:123 | 170 | 1/783 |
| 12 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:294 | 59 | 26/783 |
| 13 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:533 | 38 | 37/783 |
| 14 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:179 | 32 | 1/783 |
| 15 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:210 | 10 | 1/783 |
| 16 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:470 | 10 | 10/783 |
| 17 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:526 | 4 | 3/783 |
| 18 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/tg_ui/widgets.py:294 | 1 | 1/783 |
| 19 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/windows.py:533 | 1 | 1/783 |
