# Stub Telemetry Heatmap

Accumulated from **416 runs** (2026-07-13 08:53 UTC .. 2026-08-31 11:12 UTC). Open: 190, resolved: 318, regressed: 0.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

> **Scouting notes:** `docs/engine/stub-scouting-2026-08-10.md` — what it would take to plug these, why the two risk tables below are currently hard to action, and one confirmed live bug. **Do not add prose to this file: regeneration deletes it.**

> **Constant-surface sweep closed 2026-08-31:** every `App.<NAME>` / `App.<CLASS>.<CONST>` row the q13 sweep covers was applied and moved to Resolved that day (marked `2026-08-31`, filter the Resolved table below on that date to see the set). What is left below is a DIFFERENT bug class — missing **methods**, missing module-level **instances** (`g_k*` colours), and missing **constructor/cast functions** — none of it is a constant-value lookup, so this sweep cannot close any more of it. See `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md`.

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | TGPoint3_GetRandomUnitVector() | x | 80805 | 23/416 | 2026-08-31 11:12 UTC |  |
| 2 | TGPoint3_GetRandomUnitVector() | y | 80805 | 23/416 | 2026-08-31 11:12 UTC |  |
| 3 | TGPoint3_GetRandomUnitVector() | z | 80805 | 23/416 | 2026-08-31 11:12 UTC |  |
| 4 | TGParagraph | SetString | 45066 | 175/416 | 2026-08-18 15:23 UTC |  |
| 5 | TGIcon | GetRight | 42952 | 280/416 | 2026-08-31 11:12 UTC |  |
| 6 | App | TGPoint3_GetRandomUnitVector | 28222 | 23/416 | 2026-08-31 11:12 UTC |  |
| 7 | PhaserBank_Cast() | CalculateRoughDirection | 23864 | 20/416 | 2026-08-22 10:15 UTC |  |
| 8 | PhaserBank_Cast() | CalculateRoughDirection().Dot | 23864 | 20/416 | 2026-08-22 10:15 UTC |  |
| 9 | PhaserBank_Cast() | CanFire | 23864 | 20/416 | 2026-08-22 10:15 UTC |  |
| 10 | PhaserBank_Cast() | GetChargeLevel | 23864 | 20/416 | 2026-08-22 10:15 UTC |  |
| 11 | TGPoint3_GetRandomUnitVector() | Dot | 20976 | 14/416 | 2026-08-31 11:12 UTC |  |
| 12 | TGPoint3_GetRandomUnitVector() | GetPerpendicularComponent | 20888 | 14/416 | 2026-08-31 11:12 UTC |  |
| 13 | TGPoint3_GetRandomUnitVector() | GetPerpendicularComponent().Dot | 20888 | 14/416 | 2026-08-31 11:12 UTC |  |
| 14 | TGPoint3_GetRandomUnitVector() | GetPerpendicularComponent().Unitize | 20888 | 14/416 | 2026-08-31 11:12 UTC |  |
| 15 | App | UtopiaModule_ConvertGameUnitsToKilometers | 18077 | 72/416 | 2026-08-21 12:29 UTC |  |
| 16 | TGFrame | GetRight | 15151 | 88/416 | 2026-08-31 08:32 UTC |  |
| 17 | App | SortedRegionMenu_GetRoot | 15124 | 34/416 | 2026-08-30 23:25 UTC |  |
| 18 | SortedRegionMenu_GetRoot() | GetNumChildren | 15124 | 34/416 | 2026-08-30 23:25 UTC |  |
| 19 | App | CharacterClass_IsCollisionAlertEnabled | 10998 | 333/416 | 2026-08-31 11:12 UTC |  |
| 20 | TGPane | GetBottom | 10080 | 265/416 | 2026-08-31 11:12 UTC |  |
| 21 | ShipClass | GetTargetOffsetTG | 6002 | 190/416 | 2026-08-31 11:12 UTC |  |
| 22 | PhaserSystem | CanFire | 5864 | 2/416 | 2026-08-30 21:41 UTC |  |
| 23 | PhaserSystem | GetAmmo | 5864 | 2/416 | 2026-08-30 21:41 UTC |  |
| 24 | TorpedoSystem | CanFire | 5864 | 2/416 | 2026-08-30 21:41 UTC |  |
| 25 | TractorBeamSystem | CanFire | 4720 | 2/416 | 2026-08-30 21:41 UTC |  |
| 26 | TractorBeamSystem | GetAmmo | 4720 | 2/416 | 2026-08-30 21:41 UTC |  |
| 27 | TGParagraph | GetRight | 4320 | 265/416 | 2026-08-31 11:12 UTC |  |
| 28 | App | TGProfilingInfo_SetTimingData | 3686 | 10/416 | 2026-08-30 21:20 UTC |  |
| 29 | SparkEmitterProperty_Create() | SetOrientation | 3640 | 86/416 | 2026-08-22 09:52 UTC |  |
| 30 | SparkEmitterProperty_Create() | SetPosition | 3640 | 86/416 | 2026-08-22 09:52 UTC |  |
| 31 | TGPane | GetRight | 3600 | 265/416 | 2026-08-31 11:12 UTC |  |
| 32 | ShieldSubsystem | GetNumShields | 2932 | 2/416 | 2026-08-30 21:41 UTC |  |
| 33 | TorpedoSystem | GetAmmo | 2932 | 2/416 | 2026-08-30 21:41 UTC |  |
| 34 | App | __path__ | 2199 | 125/416 | 2026-08-31 11:12 UTC |  |
| 35 | App | SparkEmitterProperty_Create | 2139 | 86/416 | 2026-08-22 09:52 UTC |  |
| 36 | SparkEmitterProperty_Create() | GetName | 2139 | 86/416 | 2026-08-22 09:52 UTC |  |
| 37 | SmokeEmitterProperty_Create() | SetOrientation | 1998 | 86/416 | 2026-08-22 09:52 UTC |  |
| 38 | SmokeEmitterProperty_Create() | SetPosition | 1998 | 86/416 | 2026-08-22 09:52 UTC |  |
| 39 | TGInputManager | MoveMouseCursorTo | 1451 | 410/416 | 2026-08-31 11:12 UTC |  |
| 40 | ShipClass | subsystems | 1448 | 265/416 | 2026-08-31 11:12 UTC |  |
| 41 | EngPowerCtrl | GetBottom | 1440 | 265/416 | 2026-08-31 11:12 UTC |  |
| 42 | App | SmokeEmitterProperty_Create | 1208 | 86/416 | 2026-08-22 09:52 UTC |  |
| 43 | SmokeEmitterProperty_Create() | GetName | 1208 | 86/416 | 2026-08-22 09:52 UTC |  |
| 44 | STSubPane | ResizeToContents | 992 | 216/416 | 2026-08-31 11:12 UTC |  |
| 45 | _STStylizedWindow | ScrollToBottom | 992 | 216/416 | 2026-08-31 11:12 UTC |  |
| 46 | ExplodeEmitterProperty_Create() | SetOrientation | 922 | 86/416 | 2026-08-22 09:52 UTC |  |
| 47 | ExplodeEmitterProperty_Create() | SetPosition | 922 | 86/416 | 2026-08-22 09:52 UTC |  |
| 48 | CharacterClass | SetGender | 905 | 72/416 | 2026-08-22 09:52 UTC |  |
| 49 | CharacterClass | SetRandomAnimationChance | 905 | 72/416 | 2026-08-22 09:52 UTC |  |
| 50 | CharacterClass | SetSize | 905 | 72/416 | 2026-08-22 09:52 UTC |  |
| 51 | STButton | SetName | 802 | 261/416 | 2026-08-31 11:12 UTC |  |
| 52 | CharacterClass | SetBlinkChance | 770 | 72/416 | 2026-08-22 09:52 UTC |  |
| 53 | EngPowerCtrl | GetRight | 720 | 265/416 | 2026-08-31 11:12 UTC |  |
| 54 | TGFrame | GetBottom | 720 | 265/416 | 2026-08-31 11:12 UTC |  |
| 55 | TGParagraph | GetBottom | 720 | 265/416 | 2026-08-31 11:12 UTC |  |
| 56 | Mission | AddPrecreatedShip | 704 | 86/416 | 2026-08-22 09:52 UTC |  |
| 57 | CharacterClass | SetAnimatedSpeaking | 683 | 72/416 | 2026-08-22 09:52 UTC |  |
| 58 | CharacterClass | SetBlinkStages | 683 | 72/416 | 2026-08-22 09:52 UTC |  |
| 59 | Planet | GetCloakingSubsystem | 619 | 2/416 | 2026-08-17 14:57 UTC |  |
| 60 | Planet | GetCloakingSubsystem.IsTryingToCloak | 619 | 2/416 | 2026-08-17 14:57 UTC |  |
| 61 | App | PhaserBank_Cast | 608 | 22/416 | 2026-08-22 10:15 UTC |  |
| 62 | App | g_kMainMenuButton2HighlightedColor | 542 | 77/416 | 2026-08-22 08:23 UTC |  |
| 63 | STTopLevelMenu | GetContainingWindow | 542 | 86/416 | 2026-08-22 09:52 UTC |  |
| 64 | App | ExplodeEmitterProperty_Create | 527 | 86/416 | 2026-08-22 09:52 UTC |  |
| 65 | ExplodeEmitterProperty_Create() | GetName | 527 | 86/416 | 2026-08-22 09:52 UTC |  |
| 66 | KeyboardBinding | LaunchEvent | 475 | 28/416 | 2026-08-30 22:45 UTC |  |
| 67 | STButton | GetName | 463 | 190/416 | 2026-08-31 11:12 UTC |  |
| 68 | KeyboardBinding | FindKey | 462 | 76/416 | 2026-08-22 08:23 UTC |  |
| 69 | Game | AddPersistentModule | 414 | 414/416 | 2026-08-31 11:12 UTC |  |
| 70 | _STStylizedWindow | ScrollToTop | 409 | 193/416 | 2026-08-31 11:12 UTC |  |
| 71 | App | WarpSequence_Cast | 294 | 61/416 | 2026-08-11 17:55 UTC |  |
| 72 | STTargetMenu | GetHeight | 271 | 86/416 | 2026-08-22 09:52 UTC |  |
| 73 | STTargetMenu | Resize | 271 | 86/416 | 2026-08-22 09:52 UTC |  |
| 74 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 271 | 86/416 | 2026-08-22 09:52 UTC |  |
| 75 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 271 | 86/416 | 2026-08-22 09:52 UTC |  |
| 76 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 271 | 86/416 | 2026-08-22 09:52 UTC |  |
| 77 | TGPane | SetAlwaysHandleEvents | 244 | 216/416 | 2026-08-31 11:12 UTC |  |
| 78 | TGPane | SetNotAlwaysHandleEvents | 242 | 214/416 | 2026-08-31 11:12 UTC |  |
| 79 | STTopLevelMenu | ForceUpdate | 180 | 86/416 | 2026-08-22 09:52 UTC |  |
| 80 | TGParagraph | SetFontGroup | 180 | 86/416 | 2026-08-22 09:52 UTC |  |
| 81 | WaypointEvent_Create() | GetEventType | 180 | 31/416 | 2026-08-10 11:34 UTC |  |
| 82 | TGParagraph | RecalcBounds | 157 | 17/416 | 2026-08-22 10:15 UTC |  |
| 83 | App | PulseWeaponProperty_Cast | 148 | 26/416 | 2026-08-28 15:05 UTC |  |
| 84 | CharacterClass | SetLookAtAdj | 148 | 71/416 | 2026-08-22 09:52 UTC |  |
| 85 | PulseWeaponProperty_Cast() | GetOrientationForward | 148 | 26/416 | 2026-08-28 15:05 UTC |  |
| 86 | PulseWeaponProperty_Cast() | GetOrientationForward().x | 148 | 26/416 | 2026-08-28 15:05 UTC |  |
| 87 | PulseWeaponProperty_Cast() | GetOrientationForward().y | 148 | 26/416 | 2026-08-28 15:05 UTC |  |
| 88 | PulseWeaponProperty_Cast() | GetOrientationForward().z | 148 | 26/416 | 2026-08-28 15:05 UTC |  |
| 89 | WarpSequence_Cast() | GetDestination | 140 | 60/416 | 2026-08-11 17:55 UTC |  |
| 90 | WarpSequence_Cast() | GetDestinationMission | 140 | 60/416 | 2026-08-11 17:55 UTC |  |
| 91 | Torpedo_Cast() | GetObjID | 110 | 9/416 | 2026-07-17 19:27 UTC |  |
| 92 | App | MapWindow_Cast | 102 | 85/416 | 2026-08-30 23:25 UTC |  |
| 93 | MapWindow_Cast() | IsWindowActive | 102 | 85/416 | 2026-08-30 23:25 UTC |  |
| 94 | TacticalControlWindow | SetNotVisible | 102 | 85/416 | 2026-08-30 23:25 UTC |  |
| 95 | CharacterClass | SetMenuEnabled | 92 | 65/416 | 2026-08-22 08:23 UTC |  |
| 96 | App | WaypointEvent_Create | 90 | 31/416 | 2026-08-10 11:34 UTC |  |
| 97 | App | g_kSTMenu2Selected | 90 | 77/416 | 2026-08-22 08:23 UTC |  |
| 98 | STTargetMenu | ForceUpdate | 90 | 86/416 | 2026-08-22 09:52 UTC |  |
| 99 | STTopLevelMenu | Resize | 90 | 86/416 | 2026-08-22 09:52 UTC |  |
| 100 | STTopLevelMenu | ResizeToContents | 90 | 86/416 | 2026-08-22 09:52 UTC |  |
| 101 | WaypointEvent_Create() | GetDestination | 90 | 31/416 | 2026-08-10 11:34 UTC |  |
| 102 | WaypointEvent_Create() | SetDestination | 90 | 31/416 | 2026-08-10 11:34 UTC |  |
| 103 | WaypointEvent_Create() | SetEventType | 90 | 31/416 | 2026-08-10 11:34 UTC |  |
| 104 | WaypointEvent_Create() | SetPlacement | 90 | 31/416 | 2026-08-10 11:34 UTC |  |
| 105 | App | EnergyWeapon_Cast | 80 | 8/416 | 2026-08-21 20:37 UTC |  |
| 106 | EnergyWeapon_Cast() | GetMaxCharge | 80 | 8/416 | 2026-08-21 20:37 UTC |  |
| 107 | EnergyWeapon_Cast() | SetChargeLevel | 80 | 8/416 | 2026-08-21 20:37 UTC |  |
| 108 | CharacterClass | SetAudioMode | 74 | 71/416 | 2026-08-22 09:52 UTC |  |
| 109 | SortedRegionMenu | SetPlacementName | 67 | 66/416 | 2026-08-21 09:37 UTC |  |
| 110 | CharacterClass | SetRandomAnimationEnabled | 66 | 65/416 | 2026-08-22 08:23 UTC |  |
| 111 | TGKeyboardEvent | EventHandled | 64 | 3/416 | 2026-08-18 15:40 UTC |  |
| 112 | _CinematicWindow | AddChild | 57 | 18/416 | 2026-08-22 10:15 UTC |  |
| 113 | _CinematicWindow | DeleteChild | 51 | 13/416 | 2026-08-22 10:15 UTC |  |
| 114 | TGEvent | GetObjPtr | 33 | 1/416 | 2026-08-22 07:37 UTC |  |
| 115 | App | WeaponSystem_Cast | 30 | 1/416 | 2026-08-17 16:31 UTC |  |
| 116 | WeaponSystem_Cast() | IsInTargetList | 28 | 1/416 | 2026-08-17 16:31 UTC |  |
| 117 | App | InterfaceModule_ForceFocusOnObject | 24 | 7/416 | 2026-08-31 08:32 UTC |  |
| 118 | CharacterClass | SetAsExtra | 21 | 7/416 | 2026-08-22 09:52 UTC |  |
| 119 | Waypoint | StartGetSubsystemMatch | 19 | 4/416 | 2026-08-06 10:09 UTC |  |
| 120 | ShipClass | SetTargetable | 18 | 3/416 | 2026-08-06 10:09 UTC |  |
| 121 | App | BlinkingLightProperty_Create | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 122 | App | TGCondition_Cast | 16 | 2/416 | 2026-08-21 15:53 UTC |  |
| 123 | BlinkingLightProperty_Create() | GetName | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 124 | BlinkingLightProperty_Create() | SetColor | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 125 | BlinkingLightProperty_Create() | SetDuration | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 126 | BlinkingLightProperty_Create() | SetOrientation | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 127 | BlinkingLightProperty_Create() | SetPeriod | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 128 | BlinkingLightProperty_Create() | SetPosition | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 129 | BlinkingLightProperty_Create() | SetRadius | 16 | 8/416 | 2026-08-30 22:10 UTC |  |
| 130 | TGCondition_Cast() | GetStatus | 16 | 2/416 | 2026-08-21 15:53 UTC |  |
| 131 | SensorSubsystem | SetNumProbes | 14 | 9/416 | 2026-08-21 20:37 UTC |  |
| 132 | App | WarpFlash_CreateWithoutShip | 9 | 9/416 | 2026-08-21 20:37 UTC |  |
| 133 | WarpEngineSubsystem | GetWarpExitLocation | 9 | 9/416 | 2026-08-21 20:37 UTC |  |
| 134 | WarpEngineSubsystem | GetWarpExitRotation | 9 | 9/416 | 2026-08-21 20:37 UTC |  |
| 135 | WarpEngineSubsystem | SetPlacement | 9 | 9/416 | 2026-08-21 20:37 UTC |  |
| 136 | TGKeyboardEvent | SetHandled | 7 | 3/416 | 2026-08-18 15:40 UTC |  |
| 137 | App | g_kSTMenu1NormalBase | 6 | 1/416 | 2026-08-22 07:37 UTC |  |
| 138 | Game | InGodMode | 6 | 2/416 | 2026-07-16 18:38 UTC |  |
| 139 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 140 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 141 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 142 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 143 | SortedRegionMenu | SetMissionName | 6 | 6/416 | 2026-08-22 09:52 UTC |  |
| 144 | Sun | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 145 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 146 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 147 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/416 | 2026-07-13 12:09 UTC |  |
| 148 | App | ZoomCameraObjectClass_Cast | 5 | 5/416 | 2026-08-21 20:37 UTC |  |
| 149 | App | g_kSTMenu3NormalBase | 5 | 1/416 | 2026-08-22 07:37 UTC |  |
| 150 | ZoomCameraObjectClass_Cast() | ToggleZoom | 5 | 5/416 | 2026-08-21 20:37 UTC |  |
| 151 | Game | SetGodMode | 3 | 2/416 | 2026-07-16 18:38 UTC |  |
| 152 | GridClass | GetPhaserSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 153 | GridClass | GetPulseWeaponSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 154 | GridClass | GetTorpedoSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 155 | GridClass | GetTractorBeamSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 156 | SensorSubsystem | GetIdentificationTime | 3 | 3/416 | 2026-08-22 09:52 UTC |  |
| 157 | Sun | GetPhaserSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 158 | Sun | GetPulseWeaponSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 159 | Sun | GetTorpedoSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 160 | Sun | GetTractorBeamSystem | 3 | 2/416 | 2026-07-13 12:09 UTC |  |
| 161 | App | g_kRadarEnemyColor | 2 | 1/416 | 2026-08-22 07:37 UTC |  |
| 162 | AsteroidField | SetNavPoint | 2 | 2/416 | 2026-08-16 15:23 UTC |  |
| 163 | AsteroidField | SetStatic | 2 | 2/416 | 2026-08-16 15:23 UTC |  |
| 164 | STSubPane | GetConceptualParent | 2 | 1/416 | 2026-08-21 15:53 UTC |  |
| 165 | STSubPane | GetConceptualParent.SetNotVisible | 2 | 1/416 | 2026-08-21 15:53 UTC |  |
| 166 | TacticalControlWindow | GetOpenMenu | 2 | 1/416 | 2026-08-21 15:53 UTC |  |
| 167 | WeaponSystem_Cast() | StopFiring | 2 | 1/416 | 2026-08-17 16:31 UTC |  |
| 168 | App | CharacterClass_GetCharacterFromMenu | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 169 | App | InterfaceModule_DoTheRightThing | 1 | 1/416 | 2026-07-13 23:39 UTC |  |
| 170 | App | STStylizedWindow_Create | 1 | 1/416 | 2026-07-13 23:39 UTC |  |
| 171 | App | g_kDamageDisplayDamagedColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 172 | App | g_kDamageDisplayDestroyedColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 173 | App | g_kDamageDisplayDisabledColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 174 | App | g_kMainMenuButtonColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 175 | App | g_kRadarFriendlyColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 176 | App | g_kRadarNeutralColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 177 | App | g_kRadarUnknownColor | 1 | 1/416 | 2026-08-22 07:37 UTC |  |
| 178 | CharacterClass_GetCharacterFromMenu() | GetName | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 179 | PhaserSystem | GetObjType | 1 | 1/416 | 2026-07-14 00:15 UTC |  |
| 180 | STStylizedWindow_Create() | AddChild | 1 | 1/416 | 2026-07-13 23:39 UTC |  |
| 181 | STStylizedWindow_Create() | InteriorChangedSize | 1 | 1/416 | 2026-07-13 23:39 UTC |  |
| 182 | STStylizedWindow_Create() | SetVisible | 1 | 1/416 | 2026-07-13 23:39 UTC |  |
| 183 | STTopLevelMenu | GetConceptualParent | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 184 | STTopLevelMenu | GetConceptualParent.SetNotVisible | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 185 | TGEvent | GetCString | 1 | 1/416 | 2026-07-13 23:37 UTC |  |
| 186 | TGPane | GetConceptualParent | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 187 | TGPane | GetConceptualParent.SetNotVisible | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 188 | TacticalControlWindow | SetVisible | 1 | 1/416 | 2026-08-21 15:53 UTC |  |
| 189 | _CinematicWindow | MoveToFront | 1 | 1/416 | 2026-07-13 23:39 UTC |  |
| 190 | _CinematicWindow | SetFocus | 1 | 1/416 | 2026-07-13 23:39 UTC |  |

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
| TGAnimAction | _anim_node.kind | 2026-07-13 | — |
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
| WarpEngineSubsystem | SetInvincible | 2026-08-09 | 2026-07-13 23:39 UTC |
| App | g_kMusicManager | 2026-08-10 | 2026-08-07 07:51 UTC |
| g_kMusicManager | PlayFanfare | 2026-08-10 | 2026-08-07 07:51 UTC |
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

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:109 | 116655 | 5/416 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 106740 | 25/416 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:100 | 65160 | 2/416 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/PhaserSweep.py:175 | 23864 | 20/416 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 10977 | 332/416 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/ai_inspector_model.py:333 | 8224 | 2/416 |
| 7 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 1808 | 3/416 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 1685 | 8/416 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:515 | 1006 | 8/416 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 684 | 89/416 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/IntelligentCircleObject.py:63 | 650 | 5/416 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:249 | 324 | 1/416 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:274 | 295 | 1/416 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:785 | 286 | 269/416 |
| 15 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 278 | 59/416 |
| 16 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 268 | 85/416 |
| 17 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 251 | 49/416 |
| 18 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:531 | 247 | 4/416 |
| 19 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:748 | 202 | 84/416 |
| 20 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 153 | 60/416 |
| 21 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:261 | 110 | 9/416 |
| 22 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:1699 | 90 | 7/416 |
| 23 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:234 | 60 | 5/416 |
| 24 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:298 | 40 | 1/416 |
| 25 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/CinematicInterfaceHandlers.py:121 | 32 | 3/416 |
| 26 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:114 | 28 | 1/416 |
| 27 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 21 | 1/416 |
| 28 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 19 | 10/416 |
| 29 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:2537 | 16 | 2/416 |
| 30 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/audio/engine_rumble.py:44 | 9 | 1/416 |
| 31 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/weapon_subsystems.py:531 | 7 | 1/416 |
| 32 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 3 | 1/416 |
| 33 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1127 | 3 | 2/416 |
| 34 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1129 | 3 | 2/416 |
| 35 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 2 | 1/416 |
| 36 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 2 | 1/416 |
| 37 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:748 | 2 | 1/416 |
| 38 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Compound/DockWithStarbase.py:272 | 2 | 1/416 |
| 39 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/StarbaseAttack.py:130 | 2 | 1/416 |
| 40 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 1 | 1/416 |
| 41 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:785 | 1 | 1/416 |
| 42 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Actions/CameraScriptActions.py:398 | 1 | 1/416 |
| 43 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:321 | 1 | 1/416 |

## Numeric-coercion call sites (int()==0 risk)

| rank | kind | file:line | total hits | coverage |
|---|---|---|---|---|
| 1 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/BridgeHandlers.py:1355 | 15124 | 34/416 |
| 2 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:123 | 7820 | 46/416 |
| 3 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:21 | 1639 | 16/416 |
| 4 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:22 | 1639 | 16/416 |
| 5 | float | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/math.py:23 | 1639 | 16/416 |
| 6 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:179 | 1472 | 46/416 |
| 7 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:774 | 1039 | 3/416 |
| 8 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:214 | 920 | 92/416 |
| 9 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:316 | 613 | 187/416 |
| 10 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:123 | 170 | 1/416 |
| 11 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:294 | 59 | 26/416 |
| 12 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:533 | 38 | 37/416 |
| 13 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:179 | 32 | 1/416 |
| 14 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:210 | 10 | 1/416 |
| 15 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:470 | 10 | 10/416 |
| 16 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:526 | 4 | 3/416 |
| 17 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/tg_ui/widgets.py:294 | 1 | 1/416 |
| 18 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/windows.py:533 | 1 | 1/416 |
