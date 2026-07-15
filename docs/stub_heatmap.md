# Stub Telemetry Heatmap

Accumulated from **36 runs** (2026-07-13 08:53 UTC .. 2026-07-15 08:23 UTC). Open: 349, resolved: 69, regressed: 0.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | CharacterAction | name | 105055 | 17/36 | 2026-07-15 08:23 UTC |  |
| 2 | TGParagraph | SetString | 7425 | 20/36 | 2026-07-15 08:23 UTC |  |
| 3 | TGIcon | GetRight | 6312 | 33/36 | 2026-07-15 08:23 UTC |  |
| 4 | Game | LoadDatabaseSoundInGroup | 5868 | 30/36 | 2026-07-15 08:23 UTC |  |
| 5 | EngPowerDisplay | IsCompletelyVisible | 2470 | 13/36 | 2026-07-15 08:23 UTC |  |
| 6 | TGFrame | GetRight | 2470 | 13/36 | 2026-07-15 08:23 UTC |  |
| 7 | ShipClass | GetSceneNodeId | 1219 | 36/36 | 2026-07-15 08:23 UTC |  |
| 8 | TGPane | GetBottom | 1008 | 30/36 | 2026-07-15 08:23 UTC |  |
| 9 | SparkEmitterProperty_Create() | SetOrientation | 992 | 22/36 | 2026-07-15 06:49 UTC |  |
| 10 | SparkEmitterProperty_Create() | SetPosition | 992 | 22/36 | 2026-07-15 06:49 UTC |  |
| 11 | STCharacterMenu | GetNextChild | 990 | 26/36 | 2026-07-15 08:23 UTC |  |
| 12 | App | SparkEmitterProperty_Create | 612 | 22/36 | 2026-07-15 06:49 UTC |  |
| 13 | SparkEmitterProperty_Create() | GetName | 612 | 22/36 | 2026-07-15 06:49 UTC |  |
| 14 | SmokeEmitterProperty_Create() | SetOrientation | 552 | 22/36 | 2026-07-15 06:49 UTC |  |
| 15 | SmokeEmitterProperty_Create() | SetPosition | 552 | 22/36 | 2026-07-15 06:49 UTC |  |
| 16 | STCharacterMenu | GetNextChild.SetDisabled | 513 | 26/36 | 2026-07-15 08:23 UTC |  |
| 17 | TGParagraph | GetRight | 432 | 30/36 | 2026-07-15 08:23 UTC |  |
| 18 | ShipClass | GetTargetOffsetTG | 429 | 12/36 | 2026-07-15 07:57 UTC |  |
| 19 | TGPane | GetRight | 360 | 30/36 | 2026-07-15 08:23 UTC |  |
| 20 | App | SmokeEmitterProperty_Create | 352 | 22/36 | 2026-07-15 06:49 UTC |  |
| 21 | SmokeEmitterProperty_Create() | GetName | 352 | 22/36 | 2026-07-15 06:49 UTC |  |
| 22 | TGInputManager | MoveMouseCursorTo | 351 | 36/36 | 2026-07-15 08:23 UTC |  |
| 23 | Planet | GetCloakingSubsystem | 324 | 1/36 | 2026-07-13 23:37 UTC |  |
| 24 | Planet | GetCloakingSubsystem.IsTryingToCloak | 324 | 1/36 | 2026-07-13 23:37 UTC |  |
| 25 | ShipClass | SetSplashDamage | 305 | 30/36 | 2026-07-15 08:23 UTC |  |
| 26 | STCharacterMenu | GetNextChild.SetEnabled | 297 | 14/36 | 2026-07-15 08:23 UTC |  |
| 27 | App | ET_LAUNCH_PROBE | 288 | 30/36 | 2026-07-15 08:23 UTC |  |
| 28 | PulseWeaponSystem | ShouldBeAimed | 270 | 1/36 | 2026-07-14 00:15 UTC |  |
| 29 | TorpedoSystem | SetForceUpdate | 255 | 7/36 | 2026-07-15 07:57 UTC |  |
| 30 | ExplodeEmitterProperty_Create() | SetOrientation | 248 | 22/36 | 2026-07-15 06:49 UTC |  |
| 31 | ExplodeEmitterProperty_Create() | SetPosition | 248 | 22/36 | 2026-07-15 06:49 UTC |  |
| 32 | ShipClass | subsystems | 228 | 30/36 | 2026-07-15 08:23 UTC |  |
| 33 | App | CharacterClass_IsCollisionAlertEnabled | 226 | 12/36 | 2026-07-15 08:23 UTC |  |
| 34 | TorpedoSystem | SetSingleFire | 206 | 30/36 | 2026-07-15 08:23 UTC |  |
| 35 | Mission | AddPrecreatedShip | 196 | 22/36 | 2026-07-15 06:49 UTC |  |
| 36 | STCharacterMenu | GetFirstChild | 180 | 26/36 | 2026-07-15 08:23 UTC |  |
| 37 | PhaserSystem | SetForceUpdate | 174 | 12/36 | 2026-07-15 07:57 UTC |  |
| 38 | App | ET_CANT_FIRE | 168 | 30/36 | 2026-07-15 08:23 UTC |  |
| 39 | App | ET_PLAYER_TORPEDO_TYPE_CHANGED | 168 | 30/36 | 2026-07-15 08:23 UTC |  |
| 40 | App | ExplodeEmitterProperty_Create | 148 | 22/36 | 2026-07-15 06:49 UTC |  |
| 41 | ExplodeEmitterProperty_Create() | GetName | 148 | 22/36 | 2026-07-15 06:49 UTC |  |
| 42 | App | ET_TRACTOR_BEAM_STARTED_FIRING | 146 | 30/36 | 2026-07-15 08:23 UTC |  |
| 43 | App | ET_SET_TARGET | 144 | 30/36 | 2026-07-15 08:23 UTC |  |
| 44 | App | ET_TRACTOR_BEAM_STOPPED_FIRING | 144 | 30/36 | 2026-07-15 08:23 UTC |  |
| 45 | EngPowerCtrl | GetBottom | 144 | 30/36 | 2026-07-15 08:23 UTC |  |
| 46 | STTopLevelMenu | GetContainingWindow | 144 | 22/36 | 2026-07-15 06:49 UTC |  |
| 47 | App | g_kMainMenuButton2HighlightedColor | 133 | 18/36 | 2026-07-15 06:49 UTC |  |
| 48 | STCharacterMenu | GetNthChild | 130 | 26/36 | 2026-07-15 08:23 UTC |  |
| 49 | STCharacterMenu | GetNthChild.IsEnabled | 130 | 26/36 | 2026-07-15 08:23 UTC |  |
| 50 | EventType | ET_SET_TARGET | 124 | 25/36 | 2026-07-15 08:23 UTC |  |
| 51 | App | ET_OBJECTIVES | 120 | 30/36 | 2026-07-15 08:23 UTC |  |
| 52 | KeyboardBinding | FindKey | 114 | 18/36 | 2026-07-15 06:49 UTC |  |
| 53 | STCharacterMenu | GetFirstChild.SetDisabled | 114 | 26/36 | 2026-07-15 08:23 UTC |  |
| 54 | TGInputManager | GetDisplayStringFromUnicode | 114 | 18/36 | 2026-07-15 06:49 UTC |  |
| 55 | App | WC_ALT_1 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 56 | App | WC_ALT_2 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 57 | App | WC_ALT_3 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 58 | App | WC_ALT_4 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 59 | App | WC_ALT_5 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 60 | App | WC_ALT_6 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 61 | App | WC_ALT_7 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 62 | App | WC_ALT_8 | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 63 | App | WC_ALT_C | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 64 | App | WC_ALT_T | 108 | 36/36 | 2026-07-15 08:23 UTC |  |
| 65 | EventType | ET_CANT_FIRE | 105 | 25/36 | 2026-07-15 08:23 UTC |  |
| 66 | EventType | ET_LAUNCH_PROBE | 105 | 25/36 | 2026-07-15 08:23 UTC |  |
| 67 | EventType | ET_PLAYER_TORPEDO_TYPE_CHANGED | 105 | 25/36 | 2026-07-15 08:23 UTC |  |
| 68 | STSubPane | GetButtonW | 102 | 13/36 | 2026-07-15 08:23 UTC |  |
| 69 | STSubPane | GetButtonW.SetChosen | 102 | 13/36 | 2026-07-15 08:23 UTC |  |
| 70 | CharacterClass | SetGender | 96 | 7/36 | 2026-07-15 06:49 UTC |  |
| 71 | CharacterClass | SetRandomAnimationChance | 96 | 7/36 | 2026-07-15 06:49 UTC |  |
| 72 | CharacterClass | SetSize | 96 | 7/36 | 2026-07-15 06:49 UTC |  |
| 73 | App | Torpedo_Cast | 81 | 4/36 | 2026-07-15 08:23 UTC |  |
| 74 | App | GENUS_ASTEROID | 80 | 2/36 | 2026-07-15 07:57 UTC |  |
| 75 | CharacterClass | SetBlinkChance | 80 | 7/36 | 2026-07-15 06:49 UTC |  |
| 76 | WaypointEvent_Create() | GetEventType | 74 | 11/36 | 2026-07-15 06:39 UTC |  |
| 77 | App | WC_ALT_0 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 78 | App | WC_ALT_9 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 79 | App | WC_ALT_A | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 80 | App | WC_ALT_B | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 81 | App | WC_ALT_D | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 82 | App | WC_ALT_E | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 83 | App | WC_ALT_F | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 84 | App | WC_ALT_F1 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 85 | App | WC_ALT_F10 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 86 | App | WC_ALT_F11 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 87 | App | WC_ALT_F12 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 88 | App | WC_ALT_F2 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 89 | App | WC_ALT_F3 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 90 | App | WC_ALT_F4 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 91 | App | WC_ALT_F5 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 92 | App | WC_ALT_F6 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 93 | App | WC_ALT_F7 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 94 | App | WC_ALT_F8 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 95 | App | WC_ALT_F9 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 96 | App | WC_ALT_G | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 97 | App | WC_ALT_H | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 98 | App | WC_ALT_I | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 99 | App | WC_ALT_J | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 100 | App | WC_ALT_K | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 101 | App | WC_ALT_L | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 102 | App | WC_ALT_M | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 103 | App | WC_ALT_N | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 104 | App | WC_ALT_O | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 105 | App | WC_ALT_P | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 106 | App | WC_ALT_Q | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 107 | App | WC_ALT_R | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 108 | App | WC_ALT_S | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 109 | App | WC_ALT_U | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 110 | App | WC_ALT_V | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 111 | App | WC_ALT_W | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 112 | App | WC_ALT_X | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 113 | App | WC_ALT_Y | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 114 | App | WC_ALT_Z | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 115 | App | WC_CAPS_G | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 116 | App | WC_CAPS_K | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 117 | App | WC_CAPS_R | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 118 | App | WC_CTRL_1 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 119 | App | WC_CTRL_2 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 120 | App | WC_CTRL_3 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 121 | App | WC_CTRL_4 | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 122 | App | WC_CTRL_D | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 123 | App | WC_CTRL_I | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 124 | App | WC_CTRL_Q | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 125 | App | WC_CTRL_T | 72 | 36/36 | 2026-07-15 08:23 UTC |  |
| 126 | CharacterClass | SetAnimatedSpeaking | 72 | 7/36 | 2026-07-15 06:49 UTC |  |
| 127 | CharacterClass | SetBlinkStages | 72 | 7/36 | 2026-07-15 06:49 UTC |  |
| 128 | EngPowerCtrl | GetRight | 72 | 30/36 | 2026-07-15 08:23 UTC |  |
| 129 | STTargetMenu | GetHeight | 72 | 22/36 | 2026-07-15 06:49 UTC |  |
| 130 | STTargetMenu | Resize | 72 | 22/36 | 2026-07-15 06:49 UTC |  |
| 131 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 72 | 22/36 | 2026-07-15 06:49 UTC |  |
| 132 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 72 | 22/36 | 2026-07-15 06:49 UTC |  |
| 133 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 72 | 22/36 | 2026-07-15 06:49 UTC |  |
| 134 | TGFrame | GetBottom | 72 | 30/36 | 2026-07-15 08:23 UTC |  |
| 135 | TGParagraph | GetBottom | 72 | 30/36 | 2026-07-15 08:23 UTC |  |
| 136 | STButton | SetName | 71 | 28/36 | 2026-07-15 08:23 UTC |  |
| 137 | STCharacterMenu | GetFirstChild.SetEnabled | 66 | 14/36 | 2026-07-15 08:23 UTC |  |
| 138 | EventType | ET_TRACTOR_BEAM_STARTED_FIRING | 63 | 25/36 | 2026-07-15 08:23 UTC |  |
| 139 | EventType | ET_OBJECTIVES | 62 | 25/36 | 2026-07-15 08:23 UTC |  |
| 140 | EventType | ET_TRACTOR_BEAM_STOPPED_FIRING | 62 | 25/36 | 2026-07-15 08:23 UTC |  |
| 141 | Torpedo_Cast() | GetObjID | 60 | 4/36 | 2026-07-15 08:23 UTC |  |
| 142 | STSubPane | ResizeToContents | 53 | 13/36 | 2026-07-15 08:23 UTC |  |
| 143 | _STStylizedWindow | ScrollToBottom | 53 | 13/36 | 2026-07-15 08:23 UTC |  |
| 144 | App | ET_SET_WARP_SEQUENCE | 50 | 8/36 | 2026-07-15 08:23 UTC |  |
| 145 | EventType | ET_SET_WARP_SEQUENCE | 50 | 8/36 | 2026-07-15 08:23 UTC |  |
| 146 | App | ET_CAMERA_ANIMATION_DONE | 49 | 18/36 | 2026-07-15 06:49 UTC |  |
| 147 | App | ET_FIRE | 49 | 22/36 | 2026-07-15 06:49 UTC |  |
| 148 | App | ET_TRACTOR_BEAM_STARTED_HITTING | 49 | 22/36 | 2026-07-15 06:49 UTC |  |
| 149 | App | ET_TRACTOR_BEAM_STOPPED_HITTING | 49 | 22/36 | 2026-07-15 06:49 UTC |  |
| 150 | App | ET_CONTACT_ENGINEERING | 48 | 22/36 | 2026-07-15 06:49 UTC |  |
| 151 | App | ET_FRIENDLY_TRACTOR_REPORT | 48 | 22/36 | 2026-07-15 06:49 UTC |  |
| 152 | App | ET_SHOW_MISSION_LOG | 48 | 22/36 | 2026-07-15 06:49 UTC |  |
| 153 | STTopLevelMenu | ForceUpdate | 48 | 22/36 | 2026-07-15 06:49 UTC |  |
| 154 | TGParagraph | SetFontGroup | 48 | 22/36 | 2026-07-15 06:49 UTC |  |
| 155 | App | WarpSequence_Cast | 46 | 6/36 | 2026-07-15 08:23 UTC |  |
| 156 | App | CinematicWindow_Cast | 43 | 36/36 | 2026-07-15 08:23 UTC |  |
| 157 | CinematicWindow_Cast() | SetInteractive | 43 | 36/36 | 2026-07-15 08:23 UTC |  |
| 158 | App | ET_AI_REACHED_WAYPOINT | 37 | 11/36 | 2026-07-15 06:39 UTC |  |
| 159 | App | ET_INPUT_TOGGLE_PICK_FIRE | 37 | 36/36 | 2026-07-15 08:23 UTC |  |
| 160 | App | WaypointEvent_Create | 37 | 11/36 | 2026-07-15 06:39 UTC |  |
| 161 | WaypointEvent_Create() | GetDestination | 37 | 11/36 | 2026-07-15 06:39 UTC |  |
| 162 | WaypointEvent_Create() | SetDestination | 37 | 11/36 | 2026-07-15 06:39 UTC |  |
| 163 | WaypointEvent_Create() | SetEventType | 37 | 11/36 | 2026-07-15 06:39 UTC |  |
| 164 | WaypointEvent_Create() | SetPlacement | 37 | 11/36 | 2026-07-15 06:39 UTC |  |
| 165 | App | ET_INPUT_FIRSTPERSON | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 166 | App | ET_INPUT_SELF_DESTRUCT | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 167 | App | ET_INPUT_TAB_FOCUS_CHANGE | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 168 | App | ET_INPUT_VIEWSCREEN_BACKWARD | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 169 | App | ET_INPUT_VIEWSCREEN_DOWN | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 170 | App | ET_INPUT_VIEWSCREEN_FORWARD | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 171 | App | ET_INPUT_VIEWSCREEN_LEFT | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 172 | App | ET_INPUT_VIEWSCREEN_RIGHT | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 173 | App | ET_INPUT_VIEWSCREEN_TARGET | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 174 | App | ET_INPUT_VIEWSCREEN_UP | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 175 | App | WC_CAPS_A | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 176 | App | WC_CAPS_B | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 177 | App | WC_CAPS_C | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 178 | App | WC_CAPS_D | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 179 | App | WC_CAPS_E | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 180 | App | WC_CAPS_F | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 181 | App | WC_CAPS_H | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 182 | App | WC_CAPS_I | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 183 | App | WC_CAPS_J | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 184 | App | WC_CAPS_L | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 185 | App | WC_CAPS_M | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 186 | App | WC_CAPS_N | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 187 | App | WC_CAPS_O | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 188 | App | WC_CAPS_P | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 189 | App | WC_CAPS_Q | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 190 | App | WC_CAPS_S | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 191 | App | WC_CAPS_T | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 192 | App | WC_CAPS_U | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 193 | App | WC_CAPS_V | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 194 | App | WC_CAPS_W | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 195 | App | WC_CAPS_X | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 196 | App | WC_CAPS_Y | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 197 | App | WC_CAPS_Z | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 198 | App | WC_CTRL_0 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 199 | App | WC_CTRL_5 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 200 | App | WC_CTRL_6 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 201 | App | WC_CTRL_7 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 202 | App | WC_CTRL_8 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 203 | App | WC_CTRL_9 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 204 | App | WC_CTRL_A | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 205 | App | WC_CTRL_B | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 206 | App | WC_CTRL_C | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 207 | App | WC_CTRL_E | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 208 | App | WC_CTRL_F | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 209 | App | WC_CTRL_F1 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 210 | App | WC_CTRL_F10 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 211 | App | WC_CTRL_F11 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 212 | App | WC_CTRL_F12 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 213 | App | WC_CTRL_F2 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 214 | App | WC_CTRL_F3 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 215 | App | WC_CTRL_F4 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 216 | App | WC_CTRL_F5 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 217 | App | WC_CTRL_F6 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 218 | App | WC_CTRL_F7 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 219 | App | WC_CTRL_F8 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 220 | App | WC_CTRL_F9 | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 221 | App | WC_CTRL_G | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 222 | App | WC_CTRL_H | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 223 | App | WC_CTRL_J | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 224 | App | WC_CTRL_K | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 225 | App | WC_CTRL_L | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 226 | App | WC_CTRL_M | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 227 | App | WC_CTRL_N | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 228 | App | WC_CTRL_O | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 229 | App | WC_CTRL_P | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 230 | App | WC_CTRL_R | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 231 | App | WC_CTRL_S | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 232 | App | WC_CTRL_U | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 233 | App | WC_CTRL_V | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 234 | App | WC_CTRL_W | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 235 | App | WC_CTRL_X | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 236 | App | WC_CTRL_Y | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 237 | App | WC_CTRL_Z | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 238 | Game | AddPersistentModule | 36 | 36/36 | 2026-07-15 08:23 UTC |  |
| 239 | STButton | GetName | 33 | 14/36 | 2026-07-15 08:23 UTC |  |
| 240 | App | GENUS_STATION | 26 | 2/36 | 2026-07-15 07:57 UTC |  |
| 241 | App | ET_TARGET_LIST_OBJECT_ADDED | 25 | 22/36 | 2026-07-15 06:49 UTC |  |
| 242 | App | MapWindow_Cast | 25 | 21/36 | 2026-07-15 06:49 UTC |  |
| 243 | App | SPECIES_FEDERATION_START | 25 | 8/36 | 2026-07-15 08:23 UTC |  |
| 244 | MapWindow_Cast() | IsWindowActive | 25 | 21/36 | 2026-07-15 06:49 UTC |  |
| 245 | TacticalControlWindow | SetNotVisible | 25 | 21/36 | 2026-07-15 06:49 UTC |  |
| 246 | App | ET_IN_SYSTEM_WARP | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 247 | App | ET_MOUSE | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 248 | App | ET_NAME_CHANGE | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 249 | App | ET_NAV_POINT_CHANGED | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 250 | App | ET_OBJECT_COLLISION | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 251 | App | ET_RADAR_TOGGLE_CLICKED | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 252 | App | ET_RESTORE_PERSISTENT_TARGET | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 253 | App | ET_TARGET_LIST_OBJECT_REMOVED | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 254 | App | ET_TORPEDO_ENTERED_SET | 24 | 8/36 | 2026-07-15 08:23 UTC |  |
| 255 | App | ET_TORPEDO_EXITED_SET | 24 | 8/36 | 2026-07-15 08:23 UTC |  |
| 256 | EventType | ET_TORPEDO_ENTERED_SET | 24 | 8/36 | 2026-07-15 08:23 UTC |  |
| 257 | EventType | ET_TORPEDO_EXITED_SET | 24 | 8/36 | 2026-07-15 08:23 UTC |  |
| 258 | STTargetMenu | ForceUpdate | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 259 | STTopLevelMenu | Resize | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 260 | STTopLevelMenu | ResizeToContents | 24 | 22/36 | 2026-07-15 06:49 UTC |  |
| 261 | ShipClass | IsDestroyBrokenSystems | 24 | 6/36 | 2026-07-15 07:57 UTC |  |
| 262 | WarpSequence_Cast() | GetDestination | 23 | 6/36 | 2026-07-15 08:23 UTC |  |
| 263 | WarpSequence_Cast() | GetDestinationMission | 23 | 6/36 | 2026-07-15 08:23 UTC |  |
| 264 | EventType | ET_FIRE | 20 | 17/36 | 2026-07-15 06:49 UTC |  |
| 265 | EventType | ET_TARGET_LIST_OBJECT_ADDED | 20 | 17/36 | 2026-07-15 06:49 UTC |  |
| 266 | EventType | ET_TRACTOR_BEAM_STARTED_HITTING | 20 | 17/36 | 2026-07-15 06:49 UTC |  |
| 267 | EventType | ET_TRACTOR_BEAM_STOPPED_HITTING | 20 | 17/36 | 2026-07-15 06:49 UTC |  |
| 268 | App | ET_REPORT_GOAL_INFO | 19 | 18/36 | 2026-07-15 06:49 UTC |  |
| 269 | App | ET_UI_REPOSITION | 19 | 18/36 | 2026-07-15 06:49 UTC |  |
| 270 | App | g_kSTMenu2Selected | 19 | 18/36 | 2026-07-15 06:49 UTC |  |
| 271 | EventType | ET_CONTACT_ENGINEERING | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 272 | EventType | ET_FRIENDLY_TRACTOR_REPORT | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 273 | EventType | ET_IN_SYSTEM_WARP | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 274 | EventType | ET_NAME_CHANGE | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 275 | EventType | ET_NAV_POINT_CHANGED | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 276 | EventType | ET_OBJECT_COLLISION | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 277 | EventType | ET_RESTORE_PERSISTENT_TARGET | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 278 | EventType | ET_SHOW_MISSION_LOG | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 279 | EventType | ET_TARGET_LIST_OBJECT_REMOVED | 19 | 17/36 | 2026-07-15 06:49 UTC |  |
| 280 | SortedRegionMenu | SetPlacementName | 19 | 18/36 | 2026-07-15 06:49 UTC |  |
| 281 | _STStylizedWindow | ScrollToTop | 18 | 8/36 | 2026-07-15 08:23 UTC |  |
| 282 | App | ET_KEYBOARD | 16 | 8/36 | 2026-07-15 06:39 UTC |  |
| 283 | App | EnergyWeapon_Cast | 16 | 1/36 | 2026-07-13 13:43 UTC |  |
| 284 | CharacterClass | AddPositionZoom | 16 | 7/36 | 2026-07-15 06:49 UTC |  |
| 285 | CharacterClass | SetLookAtAdj | 16 | 7/36 | 2026-07-15 06:49 UTC |  |
| 286 | EnergyWeapon_Cast() | GetMaxCharge | 16 | 1/36 | 2026-07-13 13:43 UTC |  |
| 287 | EnergyWeapon_Cast() | SetChargeLevel | 16 | 1/36 | 2026-07-13 13:43 UTC |  |
| 288 | ShipClass | SetScannable | 16 | 1/36 | 2026-07-13 23:37 UTC |  |
| 289 | ShipClass | SetTargetable | 16 | 1/36 | 2026-07-13 23:37 UTC |  |
| 290 | App | SPECIES_UNKNOWN | 15 | 13/36 | 2026-07-15 08:23 UTC |  |
| 291 | EventType | ET_REPORT_GOAL_INFO | 15 | 14/36 | 2026-07-15 06:49 UTC |  |
| 292 | EventType | ET_UI_REPOSITION | 15 | 14/36 | 2026-07-15 06:49 UTC |  |
| 293 | TGPane | SetAlwaysHandleEvents | 14 | 13/36 | 2026-07-15 08:23 UTC |  |
| 294 | TGPane | SetNotAlwaysHandleEvents | 13 | 12/36 | 2026-07-15 08:23 UTC |  |
| 295 | App | TGCondition_Cast | 12 | 1/36 | 2026-07-13 23:37 UTC |  |
| 296 | STCharacterMenu | RemoveItemW | 12 | 6/36 | 2026-07-15 08:23 UTC |  |
| 297 | TGCondition_Cast() | GetStatus | 12 | 1/36 | 2026-07-13 23:37 UTC |  |
| 298 | CharacterClass | SetMenuEnabled | 11 | 7/36 | 2026-07-15 06:49 UTC |  |
| 299 | App | __path__ | 8 | 7/36 | 2026-07-14 12:26 UTC |  |
| 300 | CharacterClass | SetAudioMode | 8 | 7/36 | 2026-07-15 06:49 UTC |  |
| 301 | CharacterClass | SetRandomAnimationEnabled | 8 | 7/36 | 2026-07-15 06:49 UTC |  |
| 302 | Waypoint | StartGetSubsystemMatch | 8 | 2/36 | 2026-07-13 23:39 UTC |  |
| 303 | App | g_kMusicManager | 7 | 3/36 | 2026-07-15 07:57 UTC |  |
| 304 | g_kMusicManager | PlayFanfare | 7 | 3/36 | 2026-07-15 07:57 UTC |  |
| 305 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 306 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 307 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 308 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 309 | Sun | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 310 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 311 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 312 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/36 | 2026-07-13 12:09 UTC |  |
| 313 | App | ET_SB12_RELOAD | 5 | 2/36 | 2026-07-13 23:39 UTC |  |
| 314 | App | ET_SB12_REPAIR | 5 | 2/36 | 2026-07-13 23:39 UTC |  |
| 315 | ShipSubsystem | SetInvincible | 4 | 1/36 | 2026-07-13 23:39 UTC |  |
| 316 | GridClass | GetPhaserSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 317 | GridClass | GetPulseWeaponSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 318 | GridClass | GetTorpedoSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 319 | GridClass | GetTractorBeamSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 320 | Sun | GetPhaserSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 321 | Sun | GetPulseWeaponSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 322 | Sun | GetTorpedoSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 323 | Sun | GetTractorBeamSystem | 3 | 2/36 | 2026-07-13 12:09 UTC |  |
| 324 | App | ET_CANCEL | 2 | 1/36 | 2026-07-13 23:39 UTC |  |
| 325 | App | ET_LOAD_GAME | 2 | 1/36 | 2026-07-13 23:39 UTC |  |
| 326 | ShipClass | CompleteStop | 2 | 2/36 | 2026-07-15 08:23 UTC |  |
| 327 | ShipClass | IsPlayerShip | 2 | 1/36 | 2026-07-13 13:43 UTC |  |
| 328 | App | ET_NEW_GAME | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 329 | App | ET_WEAPON_FIRED | 1 | 1/36 | 2026-07-13 23:37 UTC |  |
| 330 | App | InterfaceModule_DoTheRightThing | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 331 | App | STStylizedWindow_Create | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 332 | AsteroidField | SetNavPoint | 1 | 1/36 | 2026-07-13 23:37 UTC |  |
| 333 | AsteroidField | SetStatic | 1 | 1/36 | 2026-07-13 23:37 UTC |  |
| 334 | EventType | ET_CANCEL | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 335 | EventType | ET_INPUT_TOGGLE_PICK_FIRE | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 336 | EventType | ET_LOAD_GAME | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 337 | EventType | ET_NEW_GAME | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 338 | EventType | ET_WEAPON_FIRED | 1 | 1/36 | 2026-07-13 23:37 UTC |  |
| 339 | ImpulseEngineSubsystem | SetInvincible | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 340 | PhaserSystem | GetObjType | 1 | 1/36 | 2026-07-14 00:15 UTC |  |
| 341 | STStylizedWindow_Create() | AddChild | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 342 | STStylizedWindow_Create() | InteriorChangedSize | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 343 | STStylizedWindow_Create() | SetVisible | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 344 | ShipClass | SetInvincible | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 345 | TGEvent | GetCString | 1 | 1/36 | 2026-07-13 23:37 UTC |  |
| 346 | WarpEngineSubsystem | SetInvincible | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 347 | _CinematicWindow | AddChild | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 348 | _CinematicWindow | MoveToFront | 1 | 1/36 | 2026-07-13 23:39 UTC |  |
| 349 | _CinematicWindow | SetFocus | 1 | 1/36 | 2026-07-13 23:39 UTC |  |

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

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 106740 | 25/36 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 1808 | 3/36 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 1685 | 8/36 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:515 | 1006 | 8/36 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/IntelligentCircleObject.py:63 | 650 | 5/36 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/collisions.py:249 | 324 | 1/36 |
| 7 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2422 | 226 | 12/36 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 213 | 36/36 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 130 | 26/36 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 72 | 22/36 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:261 | 60 | 4/36 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:748 | 50 | 21/36 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 46 | 6/36 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:785 | 42 | 36/36 |
| 15 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 23 | 6/36 |
| 16 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:234 | 21 | 2/36 |
| 17 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 12 | 6/36 |
| 18 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:2537 | 12 | 1/36 |
| 19 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Compound/DockWithStarbase.py:272 | 2 | 1/36 |
| 20 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Actions/CameraScriptActions.py:398 | 1 | 1/36 |

## Numeric-coercion call sites (int()==0 risk)

| rank | kind | file:line | total hits | coverage |
|---|---|---|---|---|
| 1 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:123 | 6120 | 36/36 |
| 2 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:179 | 1152 | 36/36 |
| 3 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:774 | 1039 | 3/36 |
| 4 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:294 | 29 | 13/36 |
| 5 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:470 | 10 | 10/36 |
| 6 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:533 | 10 | 9/36 |
| 7 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:526 | 4 | 3/36 |
