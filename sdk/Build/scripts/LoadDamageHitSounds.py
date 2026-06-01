"""LoadDamageHitSounds — companion to LoadTacticalSounds.

Registers damage-impact audio names not in stock BC:
- "Shield Hit"               — single name, softer existing WAV.
- "Subsystem Critical 1-8"   — pool re-pointing the existing
                               explo_large_NN.WAV files under new names
                               so the existing g_lsBigDeathExplosions
                               registrations (used for station deaths)
                               are not overloaded.

Hull-tier audio uses the orphaned g_lsWeaponExplosions pool already
declared in LoadTacticalSounds; no entries needed here for HULL.

Called once at host bootstrap alongside LoadTacticalSounds.LoadSounds().
"""
import App


g_lsSubsystemCriticals = (
    "Subsystem Critical 1",
    "Subsystem Critical 2",
    "Subsystem Critical 3",
    "Subsystem Critical 4",
    "Subsystem Critical 5",
    "Subsystem Critical 6",
    "Subsystem Critical 7",
    "Subsystem Critical 8",
)


# Rebound by LoadSounds() so callers can use a single
# LoadDamageHitSounds.GetRandomSound(pool) call without importing
# LoadTacticalSounds. Initial value is None so the test in
# tests/unit/test_load_damage_hit_sounds.py can verify the rebind.
GetRandomSound = None


def LoadSounds():
    """Register the new sound names with TGSoundManager."""
    global GetRandomSound
    pGame = App.Game_GetCurrentGame()

    # SHIELD tier — softer existing WAV, volume reduced.
    snd = pGame.LoadSound("sfx/Explosions/explo15.WAV",
                           "Shield Hit", App.TGSound.LS_3D)
    if snd is not None:
        snd.SetVolume(0.6)

    # CRITICAL tier pool — explo_large_NN.WAV under new names.
    pGame.LoadSound("sfx/Explosions/explo_large_01.WAV",
                     "Subsystem Critical 1", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_02.WAV",
                     "Subsystem Critical 2", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_03.WAV",
                     "Subsystem Critical 3", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_04.WAV",
                     "Subsystem Critical 4", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_05.WAV",
                     "Subsystem Critical 5", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_06.WAV",
                     "Subsystem Critical 6", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_07.WAV",
                     "Subsystem Critical 7", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_08.WAV",
                     "Subsystem Critical 8", App.TGSound.LS_3D)

    # Rebind GetRandomSound to LoadTacticalSounds' implementation so
    # callers have a single picker entry point.
    import LoadTacticalSounds
    GetRandomSound = LoadTacticalSounds.GetRandomSound
