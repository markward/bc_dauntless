# Stub Telemetry Heatmap

Accumulated from **628 runs** (2026-07-13 08:53 UTC .. 2026-09-19 19:39 UTC). Open: 192, resolved: 349, regressed: 1.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## ⚠️ Regressed (hit again after being marked resolved)

| owner | attr | markedResolvedOn | lastSeenOn | hits |
|---|---|---|---|---|
| TGAnimAction | _anim_node.kind | 2026-07-13 | 2026-09-04 21:03 UTC | 109 |

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

> **Scouting notes:** `docs/engine/stub-scouting-2026-08-10.md` — what it would take to plug these, why the two risk tables below are currently hard to action, and one confirmed live bug. **Do not add prose to this file: regeneration deletes it.**

> **Constant-surface sweep closed 2026-08-31:** every `App.<NAME>` / `App.<CLASS>.<CONST>` row the q13 sweep covers was applied and moved to Resolved that day (marked `2026-08-31`, filter the Resolved table below on that date to see the set). What is left below is a DIFFERENT bug class — missing **methods**, missing module-level **instances** (`g_k*` colours), and missing **constructor/cast functions** — none of it is a constant-value lookup, so this sweep cannot close any more of it. See `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md`.

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | TGIcon | GetRight | 45933 | 413/628 | 2026-09-19 19:39 UTC |  |
| 2 | TGParagraph | SetString | 45066 | 175/628 | 2026-08-18 15:23 UTC |  |
| 3 | g_kMainMenuButton2HighlightedColor | a | 39970 | 6/628 | 2026-09-15 20:08 UTC |  |
| 4 | g_kMainMenuButton2HighlightedColor | b | 39970 | 6/628 | 2026-09-15 20:08 UTC |  |
| 5 | g_kMainMenuButton2HighlightedColor | g | 39970 | 6/628 | 2026-09-15 20:08 UTC |  |
| 6 | g_kMainMenuButton2HighlightedColor | r | 39970 | 6/628 | 2026-09-15 20:08 UTC |  |
| 7 | App | CharacterClass_IsCollisionAlertEnabled | 19818 | 521/628 | 2026-09-19 19:39 UTC |  |
| 8 | App | SortedRegionMenu_GetRoot | 18167 | 63/628 | 2026-09-16 17:29 UTC |  |
| 9 | SortedRegionMenu_GetRoot() | GetNumChildren | 18167 | 63/628 | 2026-09-16 17:29 UTC |  |
| 10 | App | UtopiaModule_ConvertGameUnitsToKilometers | 18077 | 72/628 | 2026-08-21 12:29 UTC |  |
| 11 | TGFrame | GetRight | 16026 | 110/628 | 2026-09-16 14:15 UTC |  |
| 12 | TGPane | GetBottom | 14252 | 396/628 | 2026-09-19 19:39 UTC |  |
| 13 | App | __path__ | 11026 | 270/628 | 2026-09-19 19:39 UTC |  |
| 14 | SparkEmitterProperty_Create() | SetOrientation | 6784 | 144/628 | 2026-09-19 19:39 UTC |  |
| 15 | SparkEmitterProperty_Create() | SetPosition | 6784 | 144/628 | 2026-09-19 19:39 UTC |  |
| 16 | PhaserSystem | CanFire | 6352 | 3/628 | 2026-09-14 15:59 UTC |  |
| 17 | PhaserSystem | GetAmmo | 6352 | 3/628 | 2026-09-14 15:59 UTC |  |
| 18 | TorpedoSystem | CanFire | 6352 | 3/628 | 2026-09-14 15:59 UTC |  |
| 19 | TGParagraph | GetRight | 6108 | 396/628 | 2026-09-19 19:39 UTC |  |
| 20 | App | TGProfilingInfo_SetTimingData | 5405 | 36/628 | 2026-09-19 19:39 UTC |  |
| 21 | TractorBeamSystem | CanFire | 5208 | 3/628 | 2026-09-14 15:59 UTC |  |
| 22 | TractorBeamSystem | GetAmmo | 5208 | 3/628 | 2026-09-14 15:59 UTC |  |
| 23 | TGPane | GetRight | 5090 | 396/628 | 2026-09-19 19:39 UTC |  |
| 24 | App | SparkEmitterProperty_Create | 5074 | 144/628 | 2026-09-19 19:39 UTC |  |
| 25 | SparkEmitterProperty_Create() | GetName | 5074 | 144/628 | 2026-09-19 19:39 UTC |  |
| 26 | SmokeEmitterProperty_Create() | SetOrientation | 4103 | 171/628 | 2026-09-19 19:39 UTC |  |
| 27 | SmokeEmitterProperty_Create() | SetPosition | 4103 | 171/628 | 2026-09-19 19:39 UTC |  |
| 28 | App | SmokeEmitterProperty_Create | 3203 | 171/628 | 2026-09-19 19:39 UTC |  |
| 29 | SmokeEmitterProperty_Create() | GetName | 3203 | 171/628 | 2026-09-19 19:39 UTC |  |
| 30 | TorpedoSystem | GetAmmo | 3176 | 3/628 | 2026-09-14 15:59 UTC |  |
| 31 | ShieldSubsystem | GetNumShields | 2932 | 2/628 | 2026-08-30 21:41 UTC |  |
| 32 | ShipClass | subsystems | 2049 | 396/628 | 2026-09-19 19:39 UTC |  |
| 33 | EngPowerCtrl | GetBottom | 2036 | 396/628 | 2026-09-19 19:39 UTC |  |
| 34 | KeyboardBinding | LaunchEvent | 1948 | 42/628 | 2026-09-16 17:29 UTC |  |
| 35 | TGInputManager | MoveMouseCursorTo | 1725 | 603/628 | 2026-09-19 19:39 UTC |  |
| 36 | CharacterClass | SetGender | 1619 | 129/628 | 2026-09-16 09:50 UTC |  |
| 37 | CharacterClass | SetRandomAnimationChance | 1619 | 129/628 | 2026-09-16 09:50 UTC |  |
| 38 | CharacterClass | SetSize | 1619 | 129/628 | 2026-09-16 09:50 UTC |  |
| 39 | ExplodeEmitterProperty_Create() | SetOrientation | 1596 | 144/628 | 2026-09-19 19:39 UTC |  |
| 40 | ExplodeEmitterProperty_Create() | SetPosition | 1596 | 144/628 | 2026-09-19 19:39 UTC |  |
| 41 | CharacterClass | SetBlinkChance | 1440 | 129/628 | 2026-09-16 09:50 UTC |  |
| 42 | STSubPane | ResizeToContents | 1318 | 302/628 | 2026-09-19 19:39 UTC |  |
| 43 | _STStylizedWindow | ScrollToBottom | 1318 | 302/628 | 2026-09-19 19:39 UTC |  |
| 44 | CharacterClass | SetAnimatedSpeaking | 1229 | 129/628 | 2026-09-16 09:50 UTC |  |
| 45 | CharacterClass | SetBlinkStages | 1229 | 129/628 | 2026-09-16 09:50 UTC |  |
| 46 | App | ExplodeEmitterProperty_Create | 1146 | 144/628 | 2026-09-19 19:39 UTC |  |
| 47 | ExplodeEmitterProperty_Create() | GetName | 1146 | 144/628 | 2026-09-19 19:39 UTC |  |
| 48 | Mission | AddPrecreatedShip | 1092 | 142/628 | 2026-09-16 09:50 UTC |  |
| 49 | STButton | SetName | 1088 | 374/628 | 2026-09-19 19:39 UTC |  |
| 50 | EngPowerCtrl | GetRight | 1018 | 396/628 | 2026-09-19 19:39 UTC |  |
| 51 | TGFrame | GetBottom | 1018 | 396/628 | 2026-09-19 19:39 UTC |  |
| 52 | TGParagraph | GetBottom | 1018 | 396/628 | 2026-09-19 19:39 UTC |  |
| 53 | STTopLevelMenu | GetContainingWindow | 878 | 142/628 | 2026-09-16 09:50 UTC |  |
| 54 | STButton | GetName | 645 | 288/628 | 2026-09-19 19:39 UTC |  |
| 55 | App | g_kMainMenuButton2HighlightedColor | 619 | 88/628 | 2026-09-16 09:50 UTC |  |
| 56 | Planet | GetCloakingSubsystem | 619 | 2/628 | 2026-08-17 14:57 UTC |  |
| 57 | Planet | GetCloakingSubsystem.IsTryingToCloak | 619 | 2/628 | 2026-08-17 14:57 UTC |  |
| 58 | Game | AddPersistentModule | 618 | 618/628 | 2026-09-19 19:39 UTC |  |
| 59 | _STStylizedWindow | ScrollToTop | 542 | 268/628 | 2026-09-19 19:39 UTC |  |
| 60 | KeyboardBinding | FindKey | 528 | 87/628 | 2026-09-16 09:50 UTC |  |
| 61 | STTargetMenu | GetHeight | 439 | 142/628 | 2026-09-16 09:50 UTC |  |
| 62 | STTargetMenu | Resize | 439 | 142/628 | 2026-09-16 09:50 UTC |  |
| 63 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 439 | 142/628 | 2026-09-16 09:50 UTC |  |
| 64 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 439 | 142/628 | 2026-09-16 09:50 UTC |  |
| 65 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 439 | 142/628 | 2026-09-16 09:50 UTC |  |
| 66 | TGPane | SetAlwaysHandleEvents | 337 | 302/628 | 2026-09-19 19:39 UTC |  |
| 67 | TGPane | SetNotAlwaysHandleEvents | 335 | 300/628 | 2026-09-19 19:39 UTC |  |
| 68 | TGAnimAction | GetNumActions | 299 | 16/628 | 2026-09-04 21:03 UTC |  |
| 69 | STTopLevelMenu | ForceUpdate | 292 | 142/628 | 2026-09-16 09:50 UTC |  |
| 70 | TGParagraph | SetFontGroup | 292 | 142/628 | 2026-09-16 09:50 UTC |  |
| 71 | CharacterClass | SetLookAtAdj | 264 | 129/628 | 2026-09-19 19:39 UTC |  |
| 72 | PulseWeaponSystem | CanFire | 244 | 1/628 | 2026-09-14 15:59 UTC |  |
| 73 | PulseWeaponSystem | GetAmmo | 244 | 1/628 | 2026-09-14 15:59 UTC |  |
| 74 | App | BlinkingLightProperty_Create | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 75 | BlinkingLightProperty_Create() | GetName | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 76 | BlinkingLightProperty_Create() | SetColor | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 77 | BlinkingLightProperty_Create() | SetDuration | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 78 | BlinkingLightProperty_Create() | SetOrientation | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 79 | BlinkingLightProperty_Create() | SetPeriod | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 80 | BlinkingLightProperty_Create() | SetPosition | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 81 | BlinkingLightProperty_Create() | SetRadius | 202 | 41/628 | 2026-09-16 21:47 UTC |  |
| 82 | TGAnimAction | GetAction | 190 | 16/628 | 2026-09-04 21:03 UTC |  |
| 83 | TGParagraph | RecalcBounds | 186 | 29/628 | 2026-09-16 17:29 UTC |  |
| 84 | WaypointEvent_Create() | GetEventType | 180 | 31/628 | 2026-08-10 11:34 UTC |  |
| 85 | BlinkingLightProperty_Create() | SetTextureName | 179 | 30/628 | 2026-09-16 21:47 UTC |  |
| 86 | CharacterClass | SetAsExtra | 162 | 54/628 | 2026-09-19 19:39 UTC |  |
| 87 | STTargetMenu | ForceUpdate | 146 | 142/628 | 2026-09-16 09:50 UTC |  |
| 88 | STTopLevelMenu | Resize | 146 | 142/628 | 2026-09-16 09:50 UTC |  |
| 89 | STTopLevelMenu | ResizeToContents | 146 | 142/628 | 2026-09-16 09:50 UTC |  |
| 90 | App | MapWindow_Cast | 143 | 122/628 | 2026-09-16 09:50 UTC |  |
| 91 | MapWindow_Cast() | IsWindowActive | 143 | 122/628 | 2026-09-16 09:50 UTC |  |
| 92 | TacticalControlWindow | SetNotVisible | 143 | 122/628 | 2026-09-16 09:50 UTC |  |
| 93 | CharacterClass | SetAudioMode | 130 | 127/628 | 2026-09-16 09:50 UTC |  |
| 94 | PhaserBank | SetConditionPercentage | 129 | 17/628 | 2026-09-04 20:31 UTC |  |
| 95 | CharacterClass | SetMenuEnabled | 112 | 76/628 | 2026-09-16 09:50 UTC |  |
| 96 | TGAnimAction | GetAction._anim_node | 109 | 16/628 | 2026-09-04 21:03 UTC |  |
| 97 | TorpedoTube | SetConditionPercentage | 102 | 17/628 | 2026-09-04 20:31 UTC |  |
| 98 | App | g_kSTMenu2Selected | 101 | 88/628 | 2026-09-16 09:50 UTC |  |
| 99 | App | EngineGlowProperty_Create | 99 | 28/628 | 2026-09-16 21:47 UTC |  |
| 100 | EngineGlowProperty_Create() | GetName | 99 | 28/628 | 2026-09-16 21:47 UTC |  |
| 101 | App | EnergyWeapon_Cast | 96 | 10/628 | 2026-09-15 19:46 UTC |  |
| 102 | EnergyWeapon_Cast() | GetMaxCharge | 96 | 10/628 | 2026-09-15 19:46 UTC |  |
| 103 | EnergyWeapon_Cast() | SetChargeLevel | 96 | 10/628 | 2026-09-15 19:46 UTC |  |
| 104 | App | WaypointEvent_Create | 90 | 31/628 | 2026-08-10 11:34 UTC |  |
| 105 | WaypointEvent_Create() | GetDestination | 90 | 31/628 | 2026-08-10 11:34 UTC |  |
| 106 | WaypointEvent_Create() | SetDestination | 90 | 31/628 | 2026-08-10 11:34 UTC |  |
| 107 | WaypointEvent_Create() | SetEventType | 90 | 31/628 | 2026-08-10 11:34 UTC |  |
| 108 | WaypointEvent_Create() | SetPlacement | 90 | 31/628 | 2026-08-10 11:34 UTC |  |
| 109 | TGAnimAction | GetAction._clip | 81 | 16/628 | 2026-09-04 21:03 UTC |  |
| 110 | ShipSubsystem | SetConditionPercentage | 79 | 17/628 | 2026-09-04 20:31 UTC |  |
| 111 | CharacterClass | SetRandomAnimationEnabled | 77 | 76/628 | 2026-09-16 09:50 UTC |  |
| 112 | _CinematicWindow | AddChild | 77 | 31/628 | 2026-09-16 17:29 UTC |  |
| 113 | _CinematicWindow | DeleteChild | 70 | 25/628 | 2026-09-16 17:29 UTC |  |
| 114 | SortedRegionMenu | SetPlacementName | 67 | 66/628 | 2026-08-21 09:37 UTC |  |
| 115 | TGKeyboardEvent | EventHandled | 64 | 3/628 | 2026-08-18 15:40 UTC |  |
| 116 | HullSubsystem | SetConditionPercentage | 36 | 17/628 | 2026-09-04 20:31 UTC |  |
| 117 | TractorBeam | SetConditionPercentage | 34 | 17/628 | 2026-09-04 20:31 UTC |  |
| 118 | TGEvent | GetObjPtr | 33 | 1/628 | 2026-08-22 07:37 UTC |  |
| 119 | App | InterfaceModule_ForceFocusOnObject | 30 | 9/628 | 2026-09-16 16:55 UTC |  |
| 120 | WarpSequence | SetEventDestination | 23 | 23/628 | 2026-09-04 20:57 UTC |  |
| 121 | PowerSubsystem | SetConditionPercentage | 20 | 17/628 | 2026-09-04 20:31 UTC |  |
| 122 | SensorSubsystem | SetConditionPercentage | 20 | 17/628 | 2026-09-04 20:31 UTC |  |
| 123 | ShieldSubsystem | SetConditionPercentage | 20 | 17/628 | 2026-09-04 20:31 UTC |  |
| 124 | Waypoint | StartGetSubsystemMatch | 19 | 4/628 | 2026-08-06 10:09 UTC |  |
| 125 | ShipClass | SetTargetable | 18 | 3/628 | 2026-08-06 10:09 UTC |  |
| 126 | SortedRegionMenu | SetMissionName | 18 | 12/628 | 2026-09-02 19:35 UTC |  |
| 127 | RepairSubsystem | SetConditionPercentage | 16 | 16/628 | 2026-09-04 20:31 UTC |  |
| 128 | SensorSubsystem | SetNumProbes | 16 | 11/628 | 2026-09-15 19:46 UTC |  |
| 129 | App | WarpFlash_CreateWithoutShip | 12 | 12/628 | 2026-09-15 20:08 UTC |  |
| 130 | WarpEngineSubsystem | GetWarpExitLocation | 12 | 12/628 | 2026-09-15 20:08 UTC |  |
| 131 | WarpEngineSubsystem | GetWarpExitRotation | 12 | 12/628 | 2026-09-15 20:08 UTC |  |
| 132 | WarpEngineSubsystem | SetPlacement | 12 | 12/628 | 2026-09-15 20:08 UTC |  |
| 133 | PulseWeapon | SetConditionPercentage | 8 | 1/628 | 2026-09-04 20:26 UTC |  |
| 134 | App | ZoomCameraObjectClass_Cast | 7 | 7/628 | 2026-09-15 19:46 UTC |  |
| 135 | TGKeyboardEvent | SetHandled | 7 | 3/628 | 2026-08-18 15:40 UTC |  |
| 136 | ZoomCameraObjectClass_Cast() | ToggleZoom | 7 | 7/628 | 2026-09-15 19:46 UTC |  |
| 137 | App | g_kSTMenu1NormalBase | 6 | 1/628 | 2026-08-22 07:37 UTC |  |
| 138 | Game | InGodMode | 6 | 2/628 | 2026-07-16 18:38 UTC |  |
| 139 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 140 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 141 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 142 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 143 | Sun | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 144 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 145 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 146 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/628 | 2026-07-13 12:09 UTC |  |
| 147 | App | g_kSTMenu3NormalBase | 5 | 1/628 | 2026-08-22 07:37 UTC |  |
| 148 | CloakingSubsystem | SetConditionPercentage | 4 | 1/628 | 2026-09-04 20:26 UTC |  |
| 149 | SensorSubsystem | GetIdentificationTime | 4 | 4/628 | 2026-09-01 08:26 UTC |  |
| 150 | App | CharacterClass_SetAllowExtras | 3 | 2/628 | 2026-09-02 19:35 UTC |  |
| 151 | Game | SetGodMode | 3 | 2/628 | 2026-07-16 18:38 UTC |  |
| 152 | GridClass | GetPhaserSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 153 | GridClass | GetPulseWeaponSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 154 | GridClass | GetTorpedoSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 155 | GridClass | GetTractorBeamSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 156 | Sun | GetPhaserSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 157 | Sun | GetPulseWeaponSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 158 | Sun | GetTorpedoSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 159 | Sun | GetTractorBeamSystem | 3 | 2/628 | 2026-07-13 12:09 UTC |  |
| 160 | TorpedoSystem | IsTubeReady | 3 | 3/628 | 2026-09-16 16:44 UTC |  |
| 161 | App | InterfaceModule_DoTheRightThing | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 162 | App | STStylizedWindow_Create | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 163 | App | g_kRadarEnemyColor | 2 | 1/628 | 2026-08-22 07:37 UTC |  |
| 164 | AsteroidField | SetNavPoint | 2 | 2/628 | 2026-08-16 15:23 UTC |  |
| 165 | AsteroidField | SetStatic | 2 | 2/628 | 2026-08-16 15:23 UTC |  |
| 166 | STStylizedWindow_Create() | AddChild | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 167 | STStylizedWindow_Create() | InteriorChangedSize | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 168 | STStylizedWindow_Create() | SetVisible | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 169 | STSubPane | GetConceptualParent | 2 | 1/628 | 2026-08-21 15:53 UTC |  |
| 170 | STSubPane | GetConceptualParent.SetNotVisible | 2 | 1/628 | 2026-08-21 15:53 UTC |  |
| 171 | TacticalControlWindow | GetOpenMenu | 2 | 1/628 | 2026-08-21 15:53 UTC |  |
| 172 | _CinematicWindow | MoveToFront | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 173 | _CinematicWindow | SetFocus | 2 | 2/628 | 2026-09-04 09:16 UTC |  |
| 174 | App | CharacterClass_GetCharacterFromMenu | 1 | 1/628 | 2026-08-21 15:53 UTC |  |
| 175 | App | STMissionLog_GetMissionLog | 1 | 1/628 | 2026-08-31 13:22 UTC |  |
| 176 | App | g_kDamageDisplayDamagedColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 177 | App | g_kDamageDisplayDestroyedColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 178 | App | g_kDamageDisplayDisabledColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 179 | App | g_kMainMenuButtonColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 180 | App | g_kRadarFriendlyColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 181 | App | g_kRadarNeutralColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 182 | App | g_kRadarUnknownColor | 1 | 1/628 | 2026-08-22 07:37 UTC |  |
| 183 | CharacterClass_GetCharacterFromMenu() | GetName | 1 | 1/628 | 2026-08-21 15:53 UTC |  |
| 184 | PhaserSystem | GetObjType | 1 | 1/628 | 2026-07-14 00:15 UTC |  |
| 185 | STMissionLog_GetMissionLog() | GetFirstChild | 1 | 1/628 | 2026-08-31 13:22 UTC |  |
| 186 | STMissionLog_GetMissionLog() | SetVisible | 1 | 1/628 | 2026-08-31 13:22 UTC |  |
| 187 | STTopLevelMenu | GetConceptualParent | 1 | 1/628 | 2026-08-21 15:53 UTC |  |
| 188 | STTopLevelMenu | GetConceptualParent.SetNotVisible | 1 | 1/628 | 2026-08-21 15:53 UTC |  |
| 189 | TGEvent | GetCString | 1 | 1/628 | 2026-07-13 23:37 UTC |  |
| 190 | TGPane | GetConceptualParent | 1 | 1/628 | 2026-08-21 15:53 UTC |  |
| 191 | TGPane | GetConceptualParent.SetNotVisible | 1 | 1/628 | 2026-08-21 15:53 UTC |  |
| 192 | TacticalControlWindow | SetVisible | 1 | 1/628 | 2026-08-21 15:53 UTC |  |

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
| Torpedo_Cast() | GetObjID | 2026-08-09 | 2026-07-17 19:27 UTC |
| WarpEngineSubsystem | SetInvincible | 2026-08-09 | 2026-07-13 23:39 UTC |
| App | g_kMusicManager | 2026-08-10 | 2026-08-07 07:51 UTC |
| g_kMusicManager | PlayFanfare | 2026-08-10 | 2026-08-07 07:51 UTC |
| App | WarpSequence_Cast | 2026-08-11 | 2026-08-11 17:55 UTC |
| WarpSequence_Cast() | GetDestination | 2026-08-11 | 2026-08-11 17:55 UTC |
| WarpSequence_Cast() | GetDestinationMission | 2026-08-11 | 2026-08-11 17:55 UTC |
| TGInputManager | GetDisplayStringFromUnicode | 2026-08-16 | 2026-08-11 21:48 UTC |
| App | CinematicWindow_Cast | 2026-08-18 | 2026-08-18 13:43 UTC |
| CinematicWindow_Cast() | SetInteractive | 2026-08-18 | 2026-08-18 13:43 UTC |
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

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:109 | 116655 | 5/628 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 106740 | 25/628 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:100 | 65160 | 2/628 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/PhaserSweep.py:175 | 23864 | 20/628 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 17873 | 436/628 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/ai_inspector_model.py:333 | 9078 | 3/628 |
| 7 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 1924 | 84/628 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 1808 | 3/628 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 1685 | 8/628 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:515 | 1006 | 8/628 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 684 | 89/628 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/IntelligentCircleObject.py:63 | 650 | 5/628 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 424 | 137/628 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:249 | 324 | 1/628 |
| 15 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:274 | 295 | 1/628 |
| 16 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:785 | 286 | 269/628 |
| 17 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 278 | 59/628 |
| 18 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:748 | 264 | 112/628 |
| 19 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 251 | 49/628 |
| 20 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:531 | 247 | 4/628 |
| 21 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/Preprocessors.py:1699 | 229 | 18/628 |
| 22 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/Conditions/ConditionInPhaserFiringArc.py:175 | 198 | 20/628 |
| 23 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 153 | 60/628 |
| 24 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:1699 | 151 | 9/628 |
| 25 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:261 | 110 | 9/628 |
| 26 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/bridge_placement.py:166 | 81 | 16/628 |
| 27 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/bridge_placement.py:167 | 81 | 16/628 |
| 28 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/PlainAI/PhaserSweep.py:175 | 67 | 2/628 |
| 29 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:234 | 60 | 5/628 |
| 30 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:298 | 40 | 1/628 |
| 31 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/CinematicInterfaceHandlers.py:121 | 32 | 3/628 |
| 32 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionInPhaserFiringArc.py:175 | 30 | 7/628 |
| 33 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:114 | 28 | 1/628 |
| 34 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:114 | 24 | 1/628 |
| 35 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 21 | 1/628 |
| 36 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/MissionLib.py:748 | 20 | 9/628 |
| 37 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 19 | 10/628 |
| 38 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:2537 | 17 | 3/628 |
| 39 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 12 | 4/628 |
| 40 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/audio/engine_rumble.py:44 | 9 | 1/628 |
| 41 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/weapon_subsystems.py:531 | 7 | 1/628 |
| 42 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 3 | 1/628 |
| 43 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1127 | 3 | 2/628 |
| 44 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1129 | 3 | 2/628 |
| 45 | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/AI/Preprocessors.py:2307 | 3 | 3/628 |
| 46 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 2 | 1/628 |
| 47 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 2 | 1/628 |
| 48 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:748 | 2 | 1/628 |
| 49 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Compound/DockWithStarbase.py:272 | 2 | 1/628 |
| 50 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:130 | 2 | 1/628 |
| 51 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 1 | 1/628 |
| 52 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:785 | 1 | 1/628 |
| 53 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Actions/CameraScriptActions.py:398 | 1 | 1/628 |
| 54 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:321 | 1 | 1/628 |

## Numeric-coercion call sites (int()==0 risk)

| rank | kind | file:line | total hits | coverage |
|---|---|---|---|---|
| 1 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/BridgeHandlers.py:1355 | 17933 | 58/628 |
| 2 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:123 | 7820 | 46/628 |
| 3 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:21 | 2990 | 50/628 |
| 4 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:22 | 2990 | 50/628 |
| 5 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:23 | 2990 | 50/628 |
| 6 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:179 | 1472 | 46/628 |
| 7 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:774 | 1039 | 3/628 |
| 8 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:214 | 920 | 92/628 |
| 9 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:316 | 613 | 187/628 |
| 10 | index | /Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/BridgeHandlers.py:1355 | 234 | 5/628 |
| 11 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:123 | 170 | 1/628 |
| 12 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:294 | 59 | 26/628 |
| 13 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:533 | 38 | 37/628 |
| 14 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:179 | 32 | 1/628 |
| 15 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:210 | 10 | 1/628 |
| 16 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:470 | 10 | 10/628 |
| 17 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:526 | 4 | 3/628 |
| 18 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/tg_ui/widgets.py:294 | 1 | 1/628 |
| 19 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/windows.py:533 | 1 | 1/628 |
