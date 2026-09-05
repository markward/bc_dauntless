"""LoadDamageHitSounds — companion to LoadTacticalSounds.

Project-4-only addition: registers a CRITICAL-tier sound pool that
doesn't exist in stock BC. Hull-tier audio uses the orphaned
g_lsWeaponExplosions pool already declared in LoadTacticalSounds (this
matches stock BC's Effects.TorpedoHullHit / PhaserHullHit semantics).
Shield-tier audio also reuses g_lsWeaponExplosions for torpedo impacts
(matching Effects.TorpedoShieldHit); phaser-on-shields is silent
(stock BC has no PhaserShieldHit handler).

- "Subsystem Critical 1-8"   — new pool re-pointing the existing
                               explo_large_NN.WAV files under new names
                               so the existing g_lsBigDeathExplosions
                               registrations (used for station deaths)
                               are not overloaded.

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
