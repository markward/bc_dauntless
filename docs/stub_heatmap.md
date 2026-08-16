# Stub Telemetry Heatmap

Accumulated from **233 runs** (2026-07-13 08:53 UTC .. 2026-08-10 15:55 UTC). Open: 219, resolved: 231, regressed: 0.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

> **Scouting notes:** `docs/engine/stub-scouting-2026-08-10.md` — what it would take to plug these, why the two risk tables below are currently hard to action, and one confirmed live bug. **Do not add prose to this file: regeneration deletes it.**

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | TGParagraph | SetString | 44730 | 136/233 | 2026-08-10 15:55 UTC |  |
| 2 | TGIcon | GetRight | 41536 | 155/233 | 2026-08-10 11:34 UTC |  |
| 3 | TGFrame | GetRight | 14859 | 65/233 | 2026-08-10 11:34 UTC |  |
| 4 | App | CharacterClass_IsCollisionAlertEnabled | 6860 | 171/233 | 2026-08-10 15:55 UTC |  |
| 5 | TGPane | GetBottom | 5768 | 143/233 | 2026-08-10 11:34 UTC |  |
| 6 | ShipClass | GetTargetOffsetTG | 2718 | 85/233 | 2026-08-10 15:55 UTC |  |
| 7 | SparkEmitterProperty_Create() | SetOrientation | 2610 | 62/233 | 2026-08-10 11:34 UTC |  |
| 8 | SparkEmitterProperty_Create() | SetPosition | 2610 | 62/233 | 2026-08-10 11:34 UTC |  |
| 9 | TGParagraph | GetRight | 2472 | 143/233 | 2026-08-10 11:34 UTC |  |
| 10 | TGPane | GetRight | 2060 | 143/233 | 2026-08-10 11:34 UTC |  |
| 11 | App | ET_LAUNCH_PROBE | 1865 | 143/233 | 2026-08-10 11:34 UTC |  |
| 12 | App | SparkEmitterProperty_Create | 1508 | 62/233 | 2026-08-10 11:34 UTC |  |
| 13 | SparkEmitterProperty_Create() | GetName | 1508 | 62/233 | 2026-08-10 11:34 UTC |  |
| 14 | SmokeEmitterProperty_Create() | SetOrientation | 1426 | 62/233 | 2026-08-10 11:34 UTC |  |
| 15 | SmokeEmitterProperty_Create() | SetPosition | 1426 | 62/233 | 2026-08-10 11:34 UTC |  |
| 16 | TGInputManager | MoveMouseCursorTo | 1136 | 231/233 | 2026-08-10 15:55 UTC |  |
| 17 | PhaserBank_Cast() | CalculateRoughDirection | 1112 | 2/233 | 2026-08-10 11:30 UTC |  |
| 18 | PhaserBank_Cast() | CalculateRoughDirection().Dot | 1112 | 2/233 | 2026-08-10 11:30 UTC |  |
| 19 | PhaserBank_Cast() | CanFire | 1112 | 2/233 | 2026-08-10 11:30 UTC |  |
| 20 | PhaserBank_Cast() | GetChargeLevel | 1112 | 2/233 | 2026-08-10 11:30 UTC |  |
| 21 | App | ET_CANT_FIRE | 1106 | 143/233 | 2026-08-10 11:34 UTC |  |
| 22 | ShipClass | subsystems | 850 | 143/233 | 2026-08-10 11:34 UTC |  |
| 23 | App | SmokeEmitterProperty_Create | 846 | 62/233 | 2026-08-10 11:34 UTC |  |
| 24 | SmokeEmitterProperty_Create() | GetName | 846 | 62/233 | 2026-08-10 11:34 UTC |  |
| 25 | App | GENUS_ASTEROID | 844 | 34/233 | 2026-08-10 11:30 UTC |  |
| 26 | App | ET_SET_TARGET | 824 | 143/233 | 2026-08-10 11:34 UTC |  |
| 27 | EngPowerCtrl | GetBottom | 824 | 143/233 | 2026-08-10 11:34 UTC |  |
| 28 | EventType | ET_SET_TARGET | 804 | 138/233 | 2026-08-10 11:34 UTC |  |
| 29 | App | ET_TRACTOR_BEAM_STARTED_FIRING | 794 | 139/233 | 2026-08-10 11:34 UTC |  |
| 30 | App | ET_TRACTOR_BEAM_STOPPED_FIRING | 792 | 139/233 | 2026-08-10 11:34 UTC |  |
| 31 | App | ET_OBJECTIVES | 759 | 143/233 | 2026-08-10 11:34 UTC |  |
| 32 | EventType | ET_CANT_FIRE | 744 | 138/233 | 2026-08-10 11:34 UTC |  |
| 33 | EventType | ET_LAUNCH_PROBE | 744 | 138/233 | 2026-08-10 11:34 UTC |  |
| 34 | ExplodeEmitterProperty_Create() | SetOrientation | 664 | 62/233 | 2026-08-10 11:34 UTC |  |
| 35 | ExplodeEmitterProperty_Create() | SetPosition | 664 | 62/233 | 2026-08-10 11:34 UTC |  |
| 36 | CharacterClass | SetGender | 591 | 47/233 | 2026-08-10 11:34 UTC |  |
| 37 | CharacterClass | SetRandomAnimationChance | 591 | 47/233 | 2026-08-10 11:34 UTC |  |
| 38 | CharacterClass | SetSize | 591 | 47/233 | 2026-08-10 11:34 UTC |  |
| 39 | Mission | AddPrecreatedShip | 516 | 62/233 | 2026-08-10 11:34 UTC |  |
| 40 | CharacterClass | SetBlinkChance | 498 | 47/233 | 2026-08-10 11:34 UTC |  |
| 41 | STSubPane | ResizeToContents | 472 | 106/233 | 2026-08-10 15:55 UTC |  |
| 42 | _STStylizedWindow | ScrollToBottom | 472 | 106/233 | 2026-08-10 15:55 UTC |  |
| 43 | CharacterClass | SetAnimatedSpeaking | 444 | 47/233 | 2026-08-10 11:34 UTC |  |
| 44 | CharacterClass | SetBlinkStages | 444 | 47/233 | 2026-08-10 11:34 UTC |  |
| 45 | EngPowerCtrl | GetRight | 412 | 143/233 | 2026-08-10 11:34 UTC |  |
| 46 | TGFrame | GetBottom | 412 | 143/233 | 2026-08-10 11:34 UTC |  |
| 47 | TGParagraph | GetBottom | 412 | 143/233 | 2026-08-10 11:34 UTC |  |
| 48 | STButton | SetName | 404 | 141/233 | 2026-08-10 11:34 UTC |  |
| 49 | EventType | ET_OBJECTIVES | 402 | 138/233 | 2026-08-10 11:34 UTC |  |
| 50 | App | g_kMainMenuButton2HighlightedColor | 399 | 56/233 | 2026-08-10 11:34 UTC |  |
| 51 | STTopLevelMenu | GetContainingWindow | 390 | 62/233 | 2026-08-10 11:34 UTC |  |
| 52 | EventType | ET_TRACTOR_BEAM_STARTED_FIRING | 387 | 134/233 | 2026-08-10 11:34 UTC |  |
| 53 | EventType | ET_TRACTOR_BEAM_STOPPED_FIRING | 386 | 134/233 | 2026-08-10 11:34 UTC |  |
| 54 | App | ExplodeEmitterProperty_Create | 374 | 62/233 | 2026-08-10 11:34 UTC |  |
| 55 | ExplodeEmitterProperty_Create() | GetName | 374 | 62/233 | 2026-08-10 11:34 UTC |  |
| 56 | KeyboardBinding | FindKey | 342 | 56/233 | 2026-08-10 11:34 UTC |  |
| 57 | TGInputManager | GetDisplayStringFromUnicode | 342 | 56/233 | 2026-08-10 11:34 UTC | ✅ FIXED 2026-08-16 — engine/appc/input.py; see docs/engine/e1m1-skip-intro.md |
| 58 | App | ET_SET_WARP_SEQUENCE | 326 | 75/233 | 2026-08-10 11:30 UTC |  |
| 59 | EventType | ET_SET_WARP_SEQUENCE | 326 | 75/233 | 2026-08-10 11:30 UTC |  |
| 60 | Planet | GetCloakingSubsystem | 324 | 1/233 | 2026-07-13 23:37 UTC |  |
| 61 | Planet | GetCloakingSubsystem.IsTryingToCloak | 324 | 1/233 | 2026-07-13 23:37 UTC |  |
| 62 | App | WarpSequence_Cast | 286 | 59/233 | 2026-08-10 11:30 UTC |  |
| 63 | App | UtopiaModule_ConvertGameUnitsToKilometers | 256 | 23/233 | 2026-08-10 11:34 UTC |  |
| 64 | App | CinematicWindow_Cast | 246 | 230/233 | 2026-08-10 15:55 UTC |  |
| 65 | CinematicWindow_Cast() | SetInteractive | 246 | 230/233 | 2026-08-10 15:55 UTC |  |
| 66 | Game | AddPersistentModule | 233 | 233/233 | 2026-08-10 15:55 UTC |  |
| 67 | STButton | GetName | 212 | 85/233 | 2026-08-10 11:34 UTC |  |
| 68 | App | GENUS_STATION | 201 | 27/233 | 2026-08-10 11:30 UTC |  |
| 69 | STTargetMenu | GetHeight | 195 | 62/233 | 2026-08-10 11:34 UTC |  |
| 70 | STTargetMenu | Resize | 195 | 62/233 | 2026-08-10 11:34 UTC |  |
| 71 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 195 | 62/233 | 2026-08-10 11:34 UTC |  |
| 72 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 195 | 62/233 | 2026-08-10 11:34 UTC |  |
| 73 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 195 | 62/233 | 2026-08-10 11:34 UTC |  |
| 74 | _STStylizedWindow | ScrollToTop | 193 | 92/233 | 2026-08-10 11:30 UTC |  |
| 75 | App | SPECIES_FEDERATION_START | 188 | 88/233 | 2026-08-10 11:30 UTC |  |
| 76 | WaypointEvent_Create() | GetEventType | 180 | 31/233 | 2026-08-10 11:34 UTC |  |
| 77 | App | ET_TORPEDO_ENTERED_SET | 177 | 74/233 | 2026-08-10 11:30 UTC |  |
| 78 | App | ET_TORPEDO_EXITED_SET | 177 | 74/233 | 2026-08-10 11:30 UTC |  |
| 79 | EventType | ET_TORPEDO_ENTERED_SET | 177 | 74/233 | 2026-08-10 11:30 UTC |  |
| 80 | EventType | ET_TORPEDO_EXITED_SET | 177 | 74/233 | 2026-08-10 11:30 UTC |  |
| 81 | App | SPECIES_UNKNOWN | 153 | 106/233 | 2026-08-10 15:55 UTC |  |
| 82 | App | PhaserBank_Cast | 144 | 4/233 | 2026-08-10 11:30 UTC |  |
| 83 | App | ET_INPUT_TOGGLE_PICK_FIRE | 141 | 140/233 | 2026-07-28 10:11 UTC |  |
| 84 | App | ET_INPUT_FIRSTPERSON | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 85 | App | ET_INPUT_TAB_FOCUS_CHANGE | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 86 | App | ET_INPUT_VIEWSCREEN_BACKWARD | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 87 | App | ET_INPUT_VIEWSCREEN_DOWN | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 88 | App | ET_INPUT_VIEWSCREEN_FORWARD | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 89 | App | ET_INPUT_VIEWSCREEN_LEFT | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 90 | App | ET_INPUT_VIEWSCREEN_RIGHT | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 91 | App | ET_INPUT_VIEWSCREEN_TARGET | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 92 | App | ET_INPUT_VIEWSCREEN_UP | 140 | 140/233 | 2026-07-28 10:11 UTC |  |
| 93 | App | ET_CAMERA_ANIMATION_DONE | 137 | 56/233 | 2026-08-10 11:34 UTC |  |
| 94 | WarpSequence_Cast() | GetDestination | 136 | 58/233 | 2026-08-10 11:30 UTC |  |
| 95 | WarpSequence_Cast() | GetDestinationMission | 136 | 58/233 | 2026-08-10 11:30 UTC |  |
| 96 | App | ET_FIRE | 131 | 62/233 | 2026-08-10 11:34 UTC |  |
| 97 | App | ET_TRACTOR_BEAM_STARTED_HITTING | 131 | 62/233 | 2026-08-10 11:34 UTC |  |
| 98 | App | ET_TRACTOR_BEAM_STOPPED_HITTING | 131 | 62/233 | 2026-08-10 11:34 UTC |  |
| 99 | App | ET_CONTACT_ENGINEERING | 130 | 62/233 | 2026-08-10 11:34 UTC |  |
| 100 | App | ET_FRIENDLY_TRACTOR_REPORT | 130 | 62/233 | 2026-08-10 11:34 UTC |  |
| 101 | App | ET_SHOW_MISSION_LOG | 130 | 62/233 | 2026-08-10 11:34 UTC |  |
| 102 | STTopLevelMenu | ForceUpdate | 130 | 62/233 | 2026-08-10 11:34 UTC |  |
| 103 | TGParagraph | SetFontGroup | 130 | 62/233 | 2026-08-10 11:34 UTC |  |
| 104 | TGPane | SetAlwaysHandleEvents | 124 | 106/233 | 2026-08-10 15:55 UTC |  |
| 105 | TGPane | SetNotAlwaysHandleEvents | 122 | 104/233 | 2026-08-10 15:55 UTC |  |
| 106 | Torpedo_Cast() | GetObjID | 110 | 9/233 | 2026-07-17 19:27 UTC |  |
| 107 | CharacterClass | SetLookAtAdj | 98 | 47/233 | 2026-08-10 11:34 UTC |  |
| 108 | App | ET_AI_REACHED_WAYPOINT | 90 | 31/233 | 2026-08-10 11:34 UTC |  |
| 109 | App | WaypointEvent_Create | 90 | 31/233 | 2026-08-10 11:34 UTC |  |
| 110 | WaypointEvent_Create() | GetDestination | 90 | 31/233 | 2026-08-10 11:34 UTC |  |
| 111 | WaypointEvent_Create() | SetDestination | 90 | 31/233 | 2026-08-10 11:34 UTC |  |
| 112 | WaypointEvent_Create() | SetEventType | 90 | 31/233 | 2026-08-10 11:34 UTC |  |
| 113 | WaypointEvent_Create() | SetPlacement | 90 | 31/233 | 2026-08-10 11:34 UTC |  |
| 114 | App | ET_TARGET_LIST_OBJECT_ADDED | 66 | 62/233 | 2026-08-10 11:34 UTC |  |
| 115 | App | ET_IN_SYSTEM_WARP | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 116 | App | ET_NAME_CHANGE | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 117 | App | ET_NAV_POINT_CHANGED | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 118 | App | ET_OBJECT_COLLISION | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 119 | App | ET_RADAR_TOGGLE_CLICKED | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 120 | App | ET_RESTORE_PERSISTENT_TARGET | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 121 | App | ET_TARGET_LIST_OBJECT_REMOVED | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 122 | STTargetMenu | ForceUpdate | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 123 | STTopLevelMenu | Resize | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 124 | STTopLevelMenu | ResizeToContents | 65 | 62/233 | 2026-08-10 11:34 UTC |  |
| 125 | App | MapWindow_Cast | 62 | 55/233 | 2026-08-10 11:34 UTC |  |
| 126 | MapWindow_Cast() | IsWindowActive | 62 | 55/233 | 2026-08-10 11:34 UTC |  |
| 127 | TacticalControlWindow | SetNotVisible | 62 | 55/233 | 2026-08-10 11:34 UTC |  |
| 128 | EventType | ET_FIRE | 61 | 57/233 | 2026-08-10 11:34 UTC |  |
| 129 | EventType | ET_TARGET_LIST_OBJECT_ADDED | 61 | 57/233 | 2026-08-10 11:34 UTC |  |
| 130 | EventType | ET_TRACTOR_BEAM_STARTED_HITTING | 61 | 57/233 | 2026-08-10 11:34 UTC |  |
| 131 | EventType | ET_TRACTOR_BEAM_STOPPED_HITTING | 61 | 57/233 | 2026-08-10 11:34 UTC |  |
| 132 | EventType | ET_CONTACT_ENGINEERING | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 133 | EventType | ET_FRIENDLY_TRACTOR_REPORT | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 134 | EventType | ET_IN_SYSTEM_WARP | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 135 | EventType | ET_NAME_CHANGE | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 136 | EventType | ET_NAV_POINT_CHANGED | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 137 | EventType | ET_OBJECT_COLLISION | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 138 | EventType | ET_RESTORE_PERSISTENT_TARGET | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 139 | EventType | ET_SHOW_MISSION_LOG | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 140 | EventType | ET_TARGET_LIST_OBJECT_REMOVED | 60 | 57/233 | 2026-08-10 11:34 UTC |  |
| 141 | App | ET_REPORT_GOAL_INFO | 57 | 56/233 | 2026-08-10 11:34 UTC |  |
| 142 | App | ET_UI_REPOSITION | 57 | 56/233 | 2026-08-10 11:34 UTC |  |
| 143 | App | g_kSTMenu2Selected | 57 | 56/233 | 2026-08-10 11:34 UTC |  |
| 144 | SortedRegionMenu | SetPlacementName | 57 | 56/233 | 2026-08-10 11:34 UTC |  |
| 145 | App | ET_KEYBOARD | 53 | 27/233 | 2026-08-10 11:34 UTC |  |
| 146 | App | ET_MOUSE | 53 | 51/233 | 2026-07-26 08:41 UTC |  |
| 147 | EventType | ET_REPORT_GOAL_INFO | 53 | 52/233 | 2026-08-10 11:34 UTC |  |
| 148 | EventType | ET_UI_REPOSITION | 53 | 52/233 | 2026-08-10 11:34 UTC |  |
| 149 | App | PulseWeaponProperty_Cast | 52 | 10/233 | 2026-08-10 11:30 UTC |  |
| 150 | CharacterClass | SetMenuEnabled | 52 | 45/233 | 2026-08-10 11:34 UTC |  |
| 151 | PulseWeaponProperty_Cast() | GetOrientationForward | 52 | 10/233 | 2026-08-10 11:30 UTC |  |
| 152 | PulseWeaponProperty_Cast() | GetOrientationForward().x | 52 | 10/233 | 2026-08-10 11:30 UTC |  |
| 153 | PulseWeaponProperty_Cast() | GetOrientationForward().y | 52 | 10/233 | 2026-08-10 11:30 UTC |  |
| 154 | PulseWeaponProperty_Cast() | GetOrientationForward().z | 52 | 10/233 | 2026-08-10 11:30 UTC |  |
| 155 | CharacterClass | SetAudioMode | 49 | 47/233 | 2026-08-10 11:34 UTC |  |
| 156 | CharacterClass | SetRandomAnimationEnabled | 46 | 45/233 | 2026-08-10 11:34 UTC |  |
| 157 | App | EnergyWeapon_Cast | 32 | 3/233 | 2026-08-06 10:09 UTC |  |
| 158 | EnergyWeapon_Cast() | GetMaxCharge | 32 | 3/233 | 2026-08-06 10:09 UTC |  |
| 159 | EnergyWeapon_Cast() | SetChargeLevel | 32 | 3/233 | 2026-08-06 10:09 UTC |  |
| 160 | Waypoint | StartGetSubsystemMatch | 19 | 4/233 | 2026-08-06 10:09 UTC |  |
| 161 | ShipClass | SetTargetable | 18 | 3/233 | 2026-08-06 10:09 UTC |  |
| 162 | App | InterfaceModule_ForceFocusOnObject | 14 | 2/233 | 2026-08-10 11:30 UTC |  |
| 163 | App | TGCondition_Cast | 12 | 1/233 | 2026-07-13 23:37 UTC |  |
| 164 | TGCondition_Cast() | GetStatus | 12 | 1/233 | 2026-07-13 23:37 UTC |  |
| 165 | App | __path__ | 11 | 9/233 | 2026-08-10 10:56 UTC |  |
| 166 | CharacterClass | SetAsExtra | 9 | 3/233 | 2026-08-06 10:09 UTC |  |
| 167 | App | ET_SB12_RELOAD | 8 | 5/233 | 2026-08-06 10:09 UTC |  |
| 168 | App | ET_SB12_REPAIR | 8 | 5/233 | 2026-08-06 10:09 UTC |  |
| 169 | SensorSubsystem | SetNumProbes | 8 | 4/233 | 2026-08-06 10:09 UTC |  |
| 170 | App | BlinkingLightProperty_Create | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 171 | BlinkingLightProperty_Create() | GetName | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 172 | BlinkingLightProperty_Create() | SetColor | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 173 | BlinkingLightProperty_Create() | SetDuration | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 174 | BlinkingLightProperty_Create() | SetOrientation | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 175 | BlinkingLightProperty_Create() | SetPeriod | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 176 | BlinkingLightProperty_Create() | SetPosition | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 177 | BlinkingLightProperty_Create() | SetRadius | 6 | 3/233 | 2026-08-06 19:34 UTC |  |
| 178 | Game | InGodMode | 6 | 2/233 | 2026-07-16 18:38 UTC |  |
| 179 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 180 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 181 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 182 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 183 | Sun | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 184 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 185 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 186 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/233 | 2026-07-13 12:09 UTC |  |
| 187 | App | PSID_INVALID | 3 | 3/233 | 2026-08-06 10:09 UTC |  |
| 188 | Game | SetGodMode | 3 | 2/233 | 2026-07-16 18:38 UTC |  |
| 189 | GridClass | GetPhaserSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 190 | GridClass | GetPulseWeaponSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 191 | GridClass | GetTorpedoSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 192 | GridClass | GetTractorBeamSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 193 | Sun | GetPhaserSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 194 | Sun | GetPulseWeaponSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 195 | Sun | GetTorpedoSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 196 | Sun | GetTractorBeamSystem | 3 | 2/233 | 2026-07-13 12:09 UTC |  |
| 197 | App | ET_CANCEL | 2 | 1/233 | 2026-07-13 23:39 UTC |  |
| 198 | App | ET_LOAD_GAME | 2 | 1/233 | 2026-07-13 23:39 UTC |  |
| 199 | App | ET_EXITED_WARP | 1 | 1/233 | 2026-07-22 14:57 UTC |  |
| 200 | App | ET_NEW_GAME | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 201 | App | InterfaceModule_DoTheRightThing | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 202 | App | STStylizedWindow_Create | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 203 | AsteroidField | SetNavPoint | 1 | 1/233 | 2026-07-13 23:37 UTC |  |
| 204 | AsteroidField | SetStatic | 1 | 1/233 | 2026-07-13 23:37 UTC |  |
| 205 | EventType | ET_CANCEL | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 206 | EventType | ET_EXITED_WARP | 1 | 1/233 | 2026-07-22 14:57 UTC |  |
| 207 | EventType | ET_INPUT_TOGGLE_PICK_FIRE | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 208 | EventType | ET_LOAD_GAME | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 209 | EventType | ET_NEW_GAME | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 210 | EventType | ET_WEAPON_FIRED | 1 | 1/233 | 2026-07-13 23:37 UTC |  |
| 211 | PhaserSystem | GetObjType | 1 | 1/233 | 2026-07-14 00:15 UTC |  |
| 212 | STStylizedWindow_Create() | AddChild | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 213 | STStylizedWindow_Create() | InteriorChangedSize | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 214 | STStylizedWindow_Create() | SetVisible | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 215 | SensorSubsystem | GetIdentificationTime | 1 | 1/233 | 2026-08-06 15:39 UTC |  |
| 216 | TGEvent | GetCString | 1 | 1/233 | 2026-07-13 23:37 UTC |  |
| 217 | _CinematicWindow | AddChild | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 218 | _CinematicWindow | MoveToFront | 1 | 1/233 | 2026-07-13 23:39 UTC |  |
| 219 | _CinematicWindow | SetFocus | 1 | 1/233 | 2026-07-13 23:39 UTC |  |

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

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:109 | 116655 | 5/233 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 106740 | 25/233 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/engine/ui/tactical_orders_panel.py:100 | 65160 | 2/233 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 6839 | 170/233 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 1808 | 3/233 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 1685 | 8/233 |
| 7 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/PhaserSweep.py:175 | 1112 | 2/233 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:515 | 1006 | 8/233 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 684 | 89/233 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/IntelligentCircleObject.py:63 | 650 | 5/233 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:249 | 324 | 1/233 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 270 | 57/233 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 251 | 49/233 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:531 | 247 | 4/233 |
| 15 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:785 | 244 | 229/233 |
| 16 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 192 | 61/233 |
| 17 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 149 | 58/233 |
| 18 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:748 | 122 | 54/233 |
| 19 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:261 | 110 | 9/233 |
| 20 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:234 | 60 | 5/233 |
| 21 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:298 | 40 | 1/233 |
| 22 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 21 | 1/233 |
| 23 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 19 | 10/233 |
| 24 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:2537 | 12 | 1/233 |
| 25 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/audio/engine_rumble.py:44 | 9 | 1/233 |
| 26 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/weapon_subsystems.py:531 | 7 | 1/233 |
| 27 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 3 | 1/233 |
| 28 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1127 | 3 | 2/233 |
| 29 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/TacticalInterfaceHandlers.py:1129 | 3 | 2/233 |
| 30 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 2 | 1/233 |
| 31 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 2 | 1/233 |
| 32 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:748 | 2 | 1/233 |
| 33 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Compound/DockWithStarbase.py:272 | 2 | 1/233 |
| 34 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 1 | 1/233 |
| 35 | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/sdk/Build/scripts/MissionLib.py:785 | 1 | 1/233 |
| 36 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Actions/CameraScriptActions.py:398 | 1 | 1/233 |

## Numeric-coercion call sites (int()==0 risk)

| rank | kind | file:line | total hits | coverage |
|---|---|---|---|---|
| 1 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:123 | 7820 | 46/233 |
| 2 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:179 | 1472 | 46/233 |
| 3 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:774 | 1039 | 3/233 |
| 4 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:214 | 920 | 92/233 |
| 5 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:316 | 278 | 79/233 |
| 6 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:123 | 170 | 1/233 |
| 7 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:294 | 59 | 26/233 |
| 8 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:533 | 38 | 37/233 |
| 9 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/input.py:179 | 32 | 1/233 |
| 10 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:210 | 10 | 1/233 |
| 11 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:470 | 10 | 10/233 |
| 12 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:526 | 4 | 3/233 |
| 13 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/tg_ui/widgets.py:294 | 1 | 1/233 |
| 14 | int | /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-channel-binder/engine/appc/windows.py:533 | 1 | 1/233 |
