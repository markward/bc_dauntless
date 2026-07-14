# Stub Telemetry Heatmap

Accumulated from **16 runs** (2026-07-13 08:53 UTC .. 2026-07-13 20:23 UTC). Open: 351, resolved: 18, regressed: 0.

_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._

## Unimplemented-attribute roadmap (open)

_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn` cell and commit — it moves to Resolved on the next regeneration, and is flagged again if it is ever hit after that date._

| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |
|---|---|---|---|---|---|---|
| 1 | CharacterAction | name | 8578 | 1/16 | 2026-07-13 20:01 UTC |  |
| 2 | Game | LoadDatabaseSoundInGroup | 2402 | 13/16 | 2026-07-13 20:23 UTC |  |
| 3 | SparkEmitterProperty_Create() | SetOrientation | 440 | 10/16 | 2026-07-13 19:30 UTC |  |
| 4 | SparkEmitterProperty_Create() | SetPosition | 440 | 10/16 | 2026-07-13 19:30 UTC |  |
| 5 | TGPane | GetBottom | 392 | 13/16 | 2026-07-13 20:23 UTC |  |
| 6 | App | SparkEmitterProperty_Create | 307 | 10/16 | 2026-07-13 19:30 UTC |  |
| 7 | SparkEmitterProperty_Create() | GetName | 307 | 10/16 | 2026-07-13 19:30 UTC |  |
| 8 | SmokeEmitterProperty_Create() | SetOrientation | 254 | 10/16 | 2026-07-13 19:30 UTC |  |
| 9 | SmokeEmitterProperty_Create() | SetPosition | 254 | 10/16 | 2026-07-13 19:30 UTC |  |
| 10 | App | Weapon_Cast | 250 | 3/16 | 2026-07-13 20:23 UTC | 2026-07-14 |
| 11 | STCharacterMenu | GetNextChild | 242 | 11/16 | 2026-07-13 20:01 UTC |  |
| 12 | App | SmokeEmitterProperty_Create | 184 | 10/16 | 2026-07-13 19:30 UTC |  |
| 13 | SmokeEmitterProperty_Create() | GetName | 184 | 10/16 | 2026-07-13 19:30 UTC |  |
| 14 | TGParagraph | GetRight | 168 | 13/16 | 2026-07-13 20:23 UTC |  |
| 15 | App | PulseWeaponSystem_Cast | 151 | 1/16 | 2026-07-13 20:01 UTC | 2026-07-14 |
| 16 | PhaserSystem | ShouldBeAimed | 151 | 1/16 | 2026-07-13 20:01 UTC |  |
| 17 | PulseWeaponSystem_Cast() | GetNumChildSubsystems | 151 | 1/16 | 2026-07-13 20:01 UTC | 2026-07-14 |
| 18 | TorpedoSystem | ShouldBeAimed | 151 | 1/16 | 2026-07-13 20:01 UTC |  |
| 19 | STCharacterMenu | GetNextChild.SetDisabled | 144 | 11/16 | 2026-07-13 20:01 UTC |  |
| 20 | TGPane | GetRight | 140 | 13/16 | 2026-07-13 20:23 UTC |  |
| 21 | ShipClass | GetSceneNodeId | 113 | 16/16 | 2026-07-13 20:23 UTC |  |
| 22 | App | ET_LAUNCH_PROBE | 110 | 13/16 | 2026-07-13 20:23 UTC |  |
| 23 | ExplodeEmitterProperty_Create() | SetOrientation | 106 | 10/16 | 2026-07-13 19:30 UTC |  |
| 24 | ExplodeEmitterProperty_Create() | SetPosition | 106 | 10/16 | 2026-07-13 19:30 UTC |  |
| 25 | App | ET_TARGET_WAS_CHANGED | 102 | 13/16 | 2026-07-13 20:23 UTC |  |
| 26 | ShipClass | SetSplashDamage | 100 | 13/16 | 2026-07-13 20:23 UTC |  |
| 27 | TGInputManager | MoveMouseCursorTo | 97 | 16/16 | 2026-07-13 20:23 UTC |  |
| 28 | Waypoint | GetPhaserSystem.GetNumChildSubsystems | 90 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 29 | Waypoint | GetPulseWeaponSystem.GetNumChildSubsystems | 90 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 30 | Waypoint | GetTorpedoSystem.GetNumChildSubsystems | 90 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 31 | Waypoint | GetTractorBeamSystem.GetNumChildSubsystems | 90 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 32 | ShipClass | subsystems | 78 | 13/16 | 2026-07-13 20:23 UTC |  |
| 33 | Mission | AddPrecreatedShip | 77 | 10/16 | 2026-07-13 19:30 UTC |  |
| 34 | App | ExplodeEmitterProperty_Create | 71 | 10/16 | 2026-07-13 19:30 UTC |  |
| 35 | ExplodeEmitterProperty_Create() | GetName | 71 | 10/16 | 2026-07-13 19:30 UTC |  |
| 36 | App | ET_CANT_FIRE | 64 | 13/16 | 2026-07-13 20:23 UTC |  |
| 37 | App | ET_PLAYER_TORPEDO_TYPE_CHANGED | 64 | 13/16 | 2026-07-13 20:23 UTC |  |
| 38 | TorpedoSystem | SetSingleFire | 64 | 13/16 | 2026-07-13 20:23 UTC |  |
| 39 | ShipClass | IsScannable | 63 | 13/16 | 2026-07-13 20:23 UTC |  |
| 40 | STTopLevelMenu | GetContainingWindow | 60 | 10/16 | 2026-07-13 19:30 UTC |  |
| 41 | App | ET_TRACTOR_BEAM_STARTED_FIRING | 58 | 13/16 | 2026-07-13 20:23 UTC |  |
| 42 | App | ET_SET_TARGET | 56 | 13/16 | 2026-07-13 20:23 UTC |  |
| 43 | App | ET_TRACTOR_BEAM_STOPPED_FIRING | 56 | 13/16 | 2026-07-13 20:23 UTC |  |
| 44 | EngPowerCtrl | GetBottom | 56 | 13/16 | 2026-07-13 20:23 UTC |  |
| 45 | TGIcon | GetRight | 56 | 13/16 | 2026-07-13 20:23 UTC |  |
| 46 | EventType | ET_TARGET_WAS_CHANGED | 54 | 8/16 | 2026-07-13 20:23 UTC |  |
| 47 | STCharacterMenu | GetNextChild.SetEnabled | 54 | 3/16 | 2026-07-13 20:01 UTC |  |
| 48 | ShipClass | GetTargetOffsetTG | 50 | 4/16 | 2026-07-13 20:23 UTC |  |
| 49 | App | g_kMainMenuButton2HighlightedColor | 49 | 7/16 | 2026-07-13 19:30 UTC |  |
| 50 | App | WC_ALT_1 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 51 | App | WC_ALT_2 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 52 | App | WC_ALT_3 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 53 | App | WC_ALT_4 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 54 | App | WC_ALT_5 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 55 | App | WC_ALT_6 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 56 | App | WC_ALT_7 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 57 | App | WC_ALT_8 | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 58 | App | WC_ALT_C | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 59 | App | WC_ALT_T | 48 | 16/16 | 2026-07-13 20:23 UTC |  |
| 60 | App | ET_OBJECTIVES | 46 | 13/16 | 2026-07-13 20:23 UTC |  |
| 61 | Waypoint | GetPhaserSystem | 45 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 62 | Waypoint | GetPulseWeaponSystem | 45 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 63 | Waypoint | GetTorpedoSystem | 45 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 64 | Waypoint | GetTractorBeamSystem | 45 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 65 | STCharacterMenu | GetFirstChild | 44 | 11/16 | 2026-07-13 20:01 UTC |  |
| 66 | KeyboardBinding | FindKey | 42 | 7/16 | 2026-07-13 19:30 UTC |  |
| 67 | TGInputManager | GetDisplayStringFromUnicode | 42 | 7/16 | 2026-07-13 19:30 UTC |  |
| 68 | App | ET_AI_SYSTEM_STATUS_WATCHER | 40 | 6/16 | 2026-07-13 20:23 UTC |  |
| 69 | EventType | ET_SET_TARGET | 36 | 8/16 | 2026-07-13 20:23 UTC |  |
| 70 | TorpedoSystem | SetForceUpdate | 34 | 3/16 | 2026-07-13 20:23 UTC |  |
| 71 | App | WC_ALT_0 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 72 | App | WC_ALT_9 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 73 | App | WC_ALT_A | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 74 | App | WC_ALT_B | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 75 | App | WC_ALT_D | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 76 | App | WC_ALT_E | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 77 | App | WC_ALT_F | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 78 | App | WC_ALT_F1 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 79 | App | WC_ALT_F10 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 80 | App | WC_ALT_F11 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 81 | App | WC_ALT_F12 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 82 | App | WC_ALT_F2 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 83 | App | WC_ALT_F3 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 84 | App | WC_ALT_F4 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 85 | App | WC_ALT_F5 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 86 | App | WC_ALT_F6 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 87 | App | WC_ALT_F7 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 88 | App | WC_ALT_F8 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 89 | App | WC_ALT_F9 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 90 | App | WC_ALT_G | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 91 | App | WC_ALT_H | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 92 | App | WC_ALT_I | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 93 | App | WC_ALT_J | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 94 | App | WC_ALT_K | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 95 | App | WC_ALT_L | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 96 | App | WC_ALT_M | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 97 | App | WC_ALT_N | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 98 | App | WC_ALT_O | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 99 | App | WC_ALT_P | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 100 | App | WC_ALT_Q | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 101 | App | WC_ALT_R | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 102 | App | WC_ALT_S | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 103 | App | WC_ALT_U | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 104 | App | WC_ALT_V | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 105 | App | WC_ALT_W | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 106 | App | WC_ALT_X | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 107 | App | WC_ALT_Y | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 108 | App | WC_ALT_Z | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 109 | App | WC_CAPS_G | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 110 | App | WC_CAPS_K | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 111 | App | WC_CAPS_R | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 112 | App | WC_CTRL_1 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 113 | App | WC_CTRL_2 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 114 | App | WC_CTRL_3 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 115 | App | WC_CTRL_4 | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 116 | App | WC_CTRL_D | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 117 | App | WC_CTRL_I | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 118 | App | WC_CTRL_Q | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 119 | App | WC_CTRL_T | 32 | 16/16 | 2026-07-13 20:23 UTC |  |
| 120 | STCharacterMenu | GetFirstChild.SetDisabled | 32 | 11/16 | 2026-07-13 20:01 UTC |  |
| 121 | EventType | ET_CANT_FIRE | 31 | 8/16 | 2026-07-13 20:23 UTC |  |
| 122 | EventType | ET_LAUNCH_PROBE | 31 | 8/16 | 2026-07-13 20:23 UTC |  |
| 123 | EventType | ET_PLAYER_TORPEDO_TYPE_CHANGED | 31 | 8/16 | 2026-07-13 20:23 UTC |  |
| 124 | App | ET_AI_SHIELD_WATCHER | 30 | 6/16 | 2026-07-13 20:23 UTC |  |
| 125 | App | ET_FRIENDLY_FIRE_REPORT | 30 | 10/16 | 2026-07-13 19:30 UTC |  |
| 126 | STTargetMenu | GetHeight | 30 | 10/16 | 2026-07-13 19:30 UTC |  |
| 127 | STTargetMenu | Resize | 30 | 10/16 | 2026-07-13 19:30 UTC |  |
| 128 | STTopLevelMenu | GetContainingWindow.GetBorderWidth | 30 | 10/16 | 2026-07-13 19:30 UTC |  |
| 129 | STTopLevelMenu | GetContainingWindow.GetMaximumHeight | 30 | 10/16 | 2026-07-13 19:30 UTC |  |
| 130 | STTopLevelMenu | GetContainingWindow.SetMaximumSize | 30 | 10/16 | 2026-07-13 19:30 UTC |  |
| 131 | App | ET_FRIENDLY_FIRE_GAME_OVER | 29 | 10/16 | 2026-07-13 19:30 UTC |  |
| 132 | EngPowerCtrl | GetRight | 28 | 13/16 | 2026-07-13 20:23 UTC |  |
| 133 | TGFrame | GetBottom | 28 | 13/16 | 2026-07-13 20:23 UTC |  |
| 134 | TGParagraph | GetBottom | 28 | 13/16 | 2026-07-13 20:23 UTC |  |
| 135 | STSubPane | GetButtonW | 27 | 4/16 | 2026-07-13 20:23 UTC |  |
| 136 | STSubPane | GetButtonW.SetChosen | 27 | 4/16 | 2026-07-13 20:23 UTC |  |
| 137 | WaypointEvent_Create() | GetEventType | 26 | 3/16 | 2026-07-13 13:43 UTC |  |
| 138 | STCharacterMenu | GetNthChild | 22 | 11/16 | 2026-07-13 20:01 UTC |  |
| 139 | STCharacterMenu | GetNthChild.IsEnabled | 22 | 11/16 | 2026-07-13 20:01 UTC |  |
| 140 | App | ET_CONTACT_ENGINEERING | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 141 | App | ET_FIRE | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 142 | App | ET_FRIENDLY_TRACTOR_REPORT | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 143 | App | ET_SHOW_MISSION_LOG | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 144 | App | ET_TRACTOR_BEAM_STARTED_HITTING | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 145 | App | ET_TRACTOR_BEAM_STOPPED_HITTING | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 146 | STTopLevelMenu | ForceUpdate | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 147 | TGParagraph | SetFontGroup | 20 | 10/16 | 2026-07-13 19:30 UTC |  |
| 148 | EventType | ET_TRACTOR_BEAM_STARTED_FIRING | 19 | 8/16 | 2026-07-13 20:23 UTC |  |
| 149 | App | CinematicWindow_Cast | 18 | 16/16 | 2026-07-13 20:23 UTC |  |
| 150 | CinematicWindow_Cast() | SetInteractive | 18 | 16/16 | 2026-07-13 20:23 UTC |  |
| 151 | EventType | ET_OBJECTIVES | 18 | 8/16 | 2026-07-13 20:23 UTC |  |
| 152 | EventType | ET_TRACTOR_BEAM_STOPPED_FIRING | 18 | 8/16 | 2026-07-13 20:23 UTC |  |
| 153 | App | ET_CAMERA_ANIMATION_DONE | 17 | 7/16 | 2026-07-13 19:30 UTC |  |
| 154 | STButton | SetName | 17 | 11/16 | 2026-07-13 20:23 UTC |  |
| 155 | App | ET_INPUT_FIRSTPERSON | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 156 | App | ET_INPUT_SELF_DESTRUCT | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 157 | App | ET_INPUT_TAB_FOCUS_CHANGE | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 158 | App | ET_INPUT_TOGGLE_PICK_FIRE | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 159 | App | ET_INPUT_VIEWSCREEN_BACKWARD | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 160 | App | ET_INPUT_VIEWSCREEN_DOWN | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 161 | App | ET_INPUT_VIEWSCREEN_FORWARD | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 162 | App | ET_INPUT_VIEWSCREEN_LEFT | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 163 | App | ET_INPUT_VIEWSCREEN_RIGHT | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 164 | App | ET_INPUT_VIEWSCREEN_TARGET | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 165 | App | ET_INPUT_VIEWSCREEN_UP | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 166 | App | EnergyWeapon_Cast | 16 | 1/16 | 2026-07-13 13:43 UTC |  |
| 167 | App | WC_CAPS_A | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 168 | App | WC_CAPS_B | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 169 | App | WC_CAPS_C | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 170 | App | WC_CAPS_D | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 171 | App | WC_CAPS_E | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 172 | App | WC_CAPS_F | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 173 | App | WC_CAPS_H | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 174 | App | WC_CAPS_I | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 175 | App | WC_CAPS_J | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 176 | App | WC_CAPS_L | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 177 | App | WC_CAPS_M | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 178 | App | WC_CAPS_N | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 179 | App | WC_CAPS_O | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 180 | App | WC_CAPS_P | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 181 | App | WC_CAPS_Q | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 182 | App | WC_CAPS_S | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 183 | App | WC_CAPS_T | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 184 | App | WC_CAPS_U | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 185 | App | WC_CAPS_V | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 186 | App | WC_CAPS_W | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 187 | App | WC_CAPS_X | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 188 | App | WC_CAPS_Y | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 189 | App | WC_CAPS_Z | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 190 | App | WC_CTRL_0 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 191 | App | WC_CTRL_5 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 192 | App | WC_CTRL_6 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 193 | App | WC_CTRL_7 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 194 | App | WC_CTRL_8 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 195 | App | WC_CTRL_9 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 196 | App | WC_CTRL_A | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 197 | App | WC_CTRL_B | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 198 | App | WC_CTRL_C | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 199 | App | WC_CTRL_E | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 200 | App | WC_CTRL_F | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 201 | App | WC_CTRL_F1 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 202 | App | WC_CTRL_F10 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 203 | App | WC_CTRL_F11 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 204 | App | WC_CTRL_F12 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 205 | App | WC_CTRL_F2 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 206 | App | WC_CTRL_F3 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 207 | App | WC_CTRL_F4 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 208 | App | WC_CTRL_F5 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 209 | App | WC_CTRL_F6 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 210 | App | WC_CTRL_F7 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 211 | App | WC_CTRL_F8 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 212 | App | WC_CTRL_F9 | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 213 | App | WC_CTRL_G | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 214 | App | WC_CTRL_H | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 215 | App | WC_CTRL_J | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 216 | App | WC_CTRL_K | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 217 | App | WC_CTRL_L | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 218 | App | WC_CTRL_M | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 219 | App | WC_CTRL_N | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 220 | App | WC_CTRL_O | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 221 | App | WC_CTRL_P | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 222 | App | WC_CTRL_R | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 223 | App | WC_CTRL_S | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 224 | App | WC_CTRL_U | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 225 | App | WC_CTRL_V | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 226 | App | WC_CTRL_W | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 227 | App | WC_CTRL_X | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 228 | App | WC_CTRL_Y | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 229 | App | WC_CTRL_Z | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 230 | EnergyWeapon_Cast() | GetMaxCharge | 16 | 1/16 | 2026-07-13 13:43 UTC |  |
| 231 | EnergyWeapon_Cast() | SetChargeLevel | 16 | 1/16 | 2026-07-13 13:43 UTC |  |
| 232 | EventType | ET_AI_SYSTEM_STATUS_WATCHER | 16 | 5/16 | 2026-07-13 20:23 UTC |  |
| 233 | Game | AddPersistentModule | 16 | 16/16 | 2026-07-13 20:23 UTC |  |
| 234 | PhaserSystem | SetForceUpdate | 16 | 4/16 | 2026-07-13 20:23 UTC |  |
| 235 | App | Torpedo_Cast | 15 | 1/16 | 2026-07-13 20:01 UTC |  |
| 236 | App | ET_AI_REACHED_WAYPOINT | 13 | 3/16 | 2026-07-13 13:43 UTC |  |
| 237 | App | WaypointEvent_Create | 13 | 3/16 | 2026-07-13 13:43 UTC |  |
| 238 | WaypointEvent_Create() | GetDestination | 13 | 3/16 | 2026-07-13 13:43 UTC |  |
| 239 | WaypointEvent_Create() | SetDestination | 13 | 3/16 | 2026-07-13 13:43 UTC |  |
| 240 | WaypointEvent_Create() | SetEventType | 13 | 3/16 | 2026-07-13 13:43 UTC |  |
| 241 | WaypointEvent_Create() | SetPlacement | 13 | 3/16 | 2026-07-13 13:43 UTC |  |
| 242 | LightPlacement | GetPhaserSystem.GetNumChildSubsystems | 12 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 243 | LightPlacement | GetPulseWeaponSystem.GetNumChildSubsystems | 12 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 244 | LightPlacement | GetTorpedoSystem.GetNumChildSubsystems | 12 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 245 | LightPlacement | GetTractorBeamSystem.GetNumChildSubsystems | 12 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 246 | STCharacterMenu | GetFirstChild.SetEnabled | 12 | 3/16 | 2026-07-13 20:01 UTC |  |
| 247 | STSubPane | ResizeToContents | 12 | 4/16 | 2026-07-13 20:23 UTC |  |
| 248 | Torpedo_Cast() | GetObjID | 12 | 1/16 | 2026-07-13 20:01 UTC |  |
| 249 | _STStylizedWindow | ScrollToBottom | 12 | 4/16 | 2026-07-13 20:23 UTC |  |
| 250 | EventType | ET_AI_SHIELD_WATCHER | 11 | 5/16 | 2026-07-13 20:23 UTC |  |
| 251 | Planet | GetVelocity | 11 | 1/16 | 2026-07-13 08:53 UTC | 2026-07-13 |
| 252 | Planet | GetVelocity.x | 11 | 1/16 | 2026-07-13 08:53 UTC | 2026-07-13 |
| 253 | Planet | GetVelocity.y | 11 | 1/16 | 2026-07-13 08:53 UTC | 2026-07-13 |
| 254 | Planet | GetVelocity.z | 11 | 1/16 | 2026-07-13 08:53 UTC | 2026-07-13 |
| 255 | Planet | IsScannable | 11 | 10/16 | 2026-07-13 19:30 UTC |  |
| 256 | App | ET_IN_SYSTEM_WARP | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 257 | App | ET_MOUSE | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 258 | App | ET_NAME_CHANGE | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 259 | App | ET_NAV_POINT_CHANGED | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 260 | App | ET_OBJECT_COLLISION | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 261 | App | ET_RADAR_TOGGLE_CLICKED | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 262 | App | ET_RESTORE_PERSISTENT_TARGET | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 263 | App | ET_SCANNABLE_CHANGE | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 264 | App | ET_TARGET_LIST_OBJECT_ADDED | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 265 | App | ET_TARGET_LIST_OBJECT_REMOVED | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 266 | App | MapWindow_Cast | 10 | 9/16 | 2026-07-13 20:01 UTC |  |
| 267 | EventType | ET_FRIENDLY_FIRE_REPORT | 10 | 5/16 | 2026-07-13 19:30 UTC |  |
| 268 | MapWindow_Cast() | IsWindowActive | 10 | 9/16 | 2026-07-13 20:01 UTC |  |
| 269 | STTargetMenu | ForceUpdate | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 270 | STTopLevelMenu | Resize | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 271 | STTopLevelMenu | ResizeToContents | 10 | 10/16 | 2026-07-13 19:30 UTC |  |
| 272 | TacticalControlWindow | SetNotVisible | 10 | 9/16 | 2026-07-13 20:01 UTC |  |
| 273 | App | ET_AI_CONDITION_CHANGED | 8 | 3/16 | 2026-07-13 20:23 UTC |  |
| 274 | App | ET_SET_WARP_SEQUENCE | 8 | 3/16 | 2026-07-13 20:23 UTC |  |
| 275 | EventType | ET_FRIENDLY_FIRE_GAME_OVER | 8 | 5/16 | 2026-07-13 19:30 UTC |  |
| 276 | EventType | ET_SET_WARP_SEQUENCE | 8 | 3/16 | 2026-07-13 20:23 UTC |  |
| 277 | ShipClass | IsDestroyBrokenSystems | 8 | 2/16 | 2026-07-13 20:01 UTC |  |
| 278 | App | ET_REPORT_GOAL_INFO | 7 | 7/16 | 2026-07-13 19:30 UTC |  |
| 279 | App | ET_UI_REPOSITION | 7 | 7/16 | 2026-07-13 19:30 UTC |  |
| 280 | App | g_kSTMenu2Selected | 7 | 7/16 | 2026-07-13 19:30 UTC |  |
| 281 | SortedRegionMenu | SetPlacementName | 7 | 7/16 | 2026-07-13 19:30 UTC |  |
| 282 | TorpedoSystem | GetObjType | 7 | 3/16 | 2026-07-13 20:23 UTC |  |
| 283 | GridClass | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 284 | GridClass | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 285 | GridClass | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 286 | GridClass | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 287 | LightPlacement | GetPhaserSystem | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 288 | LightPlacement | GetPulseWeaponSystem | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 289 | LightPlacement | GetTorpedoSystem | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 290 | LightPlacement | GetTractorBeamSystem | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 291 | Planet | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 292 | Planet | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 293 | Planet | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 294 | Planet | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 295 | STButton | GetName | 6 | 3/16 | 2026-07-13 20:01 UTC |  |
| 296 | Sun | GetPhaserSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 297 | Sun | GetPulseWeaponSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 298 | Sun | GetTorpedoSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 299 | Sun | GetTractorBeamSystem.GetNumChildSubsystems | 6 | 2/16 | 2026-07-13 12:09 UTC |  |
| 300 | Waypoint | StartGetSubsystemMatch | 6 | 1/16 | 2026-07-13 13:43 UTC |  |
| 301 | App | ET_TORPEDO_ENTERED_SET | 5 | 3/16 | 2026-07-13 20:23 UTC |  |
| 302 | App | ET_TORPEDO_EXITED_SET | 5 | 3/16 | 2026-07-13 20:23 UTC |  |
| 303 | EventType | ET_CONTACT_ENGINEERING | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 304 | EventType | ET_FIRE | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 305 | EventType | ET_FRIENDLY_TRACTOR_REPORT | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 306 | EventType | ET_IN_SYSTEM_WARP | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 307 | EventType | ET_NAME_CHANGE | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 308 | EventType | ET_NAV_POINT_CHANGED | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 309 | EventType | ET_OBJECT_COLLISION | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 310 | EventType | ET_RESTORE_PERSISTENT_TARGET | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 311 | EventType | ET_SCANNABLE_CHANGE | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 312 | EventType | ET_SHOW_MISSION_LOG | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 313 | EventType | ET_TARGET_LIST_OBJECT_ADDED | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 314 | EventType | ET_TARGET_LIST_OBJECT_REMOVED | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 315 | EventType | ET_TORPEDO_ENTERED_SET | 5 | 3/16 | 2026-07-13 20:23 UTC |  |
| 316 | EventType | ET_TORPEDO_EXITED_SET | 5 | 3/16 | 2026-07-13 20:23 UTC |  |
| 317 | EventType | ET_TRACTOR_BEAM_STARTED_HITTING | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 318 | EventType | ET_TRACTOR_BEAM_STOPPED_HITTING | 5 | 5/16 | 2026-07-13 19:30 UTC |  |
| 319 | _STStylizedWindow | ScrollToTop | 5 | 3/16 | 2026-07-13 20:23 UTC |  |
| 320 | App | SPECIES_FEDERATION_START | 4 | 3/16 | 2026-07-13 20:23 UTC |  |
| 321 | App | SPECIES_UNKNOWN | 4 | 4/16 | 2026-07-13 20:23 UTC |  |
| 322 | App | WarpSequence_Cast | 4 | 1/16 | 2026-07-13 20:01 UTC |  |
| 323 | EventType | ET_AI_CONDITION_CHANGED | 4 | 3/16 | 2026-07-13 20:23 UTC |  |
| 324 | HullSubsystem | GetObjType | 4 | 3/16 | 2026-07-13 20:23 UTC |  |
| 325 | TGPane | SetAlwaysHandleEvents | 4 | 4/16 | 2026-07-13 20:23 UTC |  |
| 326 | TGParagraph | SetString | 4 | 4/16 | 2026-07-13 20:23 UTC |  |
| 327 | App | __path__ | 3 | 3/16 | 2026-07-13 13:43 UTC |  |
| 328 | App | g_kMusicManager | 3 | 1/16 | 2026-07-13 20:01 UTC |  |
| 329 | EventType | ET_REPORT_GOAL_INFO | 3 | 3/16 | 2026-07-13 19:30 UTC |  |
| 330 | EventType | ET_UI_REPOSITION | 3 | 3/16 | 2026-07-13 19:30 UTC |  |
| 331 | GridClass | GetPhaserSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 332 | GridClass | GetPulseWeaponSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 333 | GridClass | GetTorpedoSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 334 | GridClass | GetTractorBeamSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 335 | Planet | GetPhaserSystem | 3 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 336 | Planet | GetPulseWeaponSystem | 3 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 337 | Planet | GetTorpedoSystem | 3 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 338 | Planet | GetTractorBeamSystem | 3 | 2/16 | 2026-07-13 12:09 UTC | 2026-07-13 |
| 339 | STCharacterMenu | RemoveItemW | 3 | 2/16 | 2026-07-13 20:01 UTC |  |
| 340 | Sun | GetPhaserSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 341 | Sun | GetPulseWeaponSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 342 | Sun | GetTorpedoSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 343 | Sun | GetTractorBeamSystem | 3 | 2/16 | 2026-07-13 12:09 UTC |  |
| 344 | TGPane | SetNotAlwaysHandleEvents | 3 | 3/16 | 2026-07-13 20:23 UTC |  |
| 345 | g_kMusicManager | PlayFanfare | 3 | 1/16 | 2026-07-13 20:01 UTC |  |
| 346 | App | ET_KEYBOARD | 2 | 1/16 | 2026-07-13 11:10 UTC |  |
| 347 | App | ET_SB12_RELOAD | 2 | 1/16 | 2026-07-13 13:43 UTC |  |
| 348 | App | ET_SB12_REPAIR | 2 | 1/16 | 2026-07-13 13:43 UTC |  |
| 349 | ShipClass | IsPlayerShip | 2 | 1/16 | 2026-07-13 13:43 UTC |  |
| 350 | WarpSequence_Cast() | GetDestination | 2 | 1/16 | 2026-07-13 20:01 UTC |  |
| 351 | WarpSequence_Cast() | GetDestinationMission | 2 | 1/16 | 2026-07-13 20:01 UTC |  |

## Resolved

| owner | attr | markedResolvedOn | lastSeenOn |
|---|---|---|---|
| CharacterAction | _anim_node | 2026-07-13 | 2026-07-13 19:30 UTC |
| CharacterAction | _anim_node.kind | 2026-07-13 | 2026-07-13 19:30 UTC |
| CharacterAction | _clip | 2026-07-13 | 2026-07-13 19:30 UTC |
| ImpulseEngineSubsystem | GetCurMaxSpeed | 2026-07-13 | 2026-07-13 20:01 UTC |
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
| Waypoint | IsDying | 2026-07-13 | 2026-07-13 13:43 UTC |
| WeaponHitEvent | GetWeaponType | 2026-07-13 | 2026-07-13 20:01 UTC |
| WeaponHitEvent | TRACTOR_BEAM | 2026-07-13 | 2026-07-13 20:01 UTC |

## Boolean-test call sites (truthiness risk)

| rank | file:line | total hits | coverage |
|---|---|---|---|
| 1 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:30 | 10263 | 9/16 |
| 2 | /Users/mward/Documents/Projects/bc_dauntless/engine/bridge_idle_gestures.py:29 | 1685 | 8/16 |
| 3 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:644 | 302 | 1/16 |
| 4 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/PlainAI/IntelligentCircleObject.py:63 | 250 | 3/16 |
| 5 | /Users/mward/Documents/Projects/bc_dauntless/engine/audio/engine_rumble.py:44 | 72 | 16/16 |
| 6 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/weapon_subsystems.py:515 | 41 | 3/16 |
| 7 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py:408 | 30 | 10/16 |
| 8 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1909 | 22 | 11/16 |
| 9 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:748 | 20 | 9/16 |
| 10 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/MissionLib.py:785 | 18 | 16/16 |
| 11 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:261 | 12 | 1/16 |
| 12 | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/subsystem_cascade.py:25 | 4 | 2/16 |
| 13 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToMission.py:23 | 4 | 1/16 |
| 14 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionIncomingTorps.py:234 | 3 | 1/16 |
| 15 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Compound/DockWithStarbase.py:272 | 2 | 1/16 |
| 16 | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/Conditions/ConditionWarpingToSet.py:83 | 2 | 1/16 |

## Numeric-coercion call sites (int()==0 risk)

| rank | kind | file:line | total hits | coverage |
|---|---|---|---|---|
| 1 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:123 | 2720 | 16/16 |
| 2 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/input.py:179 | 512 | 16/16 |
| 3 | index | /Users/mward/Documents/Projects/bc_dauntless/sdk/Build/scripts/AI/Preprocessors.py:774 | 151 | 1/16 |
| 4 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/windows.py:470 | 10 | 10/16 |
| 5 | int | /Users/mward/Documents/Projects/bc_dauntless/engine/appc/tg_ui/widgets.py:294 | 8 | 4/16 |
