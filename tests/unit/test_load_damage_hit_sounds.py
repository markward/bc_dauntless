"""LoadDamageHitSounds module shape: pool tuple non-empty, names unique,
GetRandomSound is bound at LoadSounds() time."""
import pytest


def test_module_imports():
    import LoadDamageHitSounds
    assert hasattr(LoadDamageHitSounds, "LoadSounds")
    assert callable(LoadDamageHitSounds.LoadSounds)


def test_critical_pool_non_empty_and_unique():
    import LoadDamageHitSounds
    pool = LoadDamageHitSounds.g_lsSubsystemCriticals
    assert len(pool) >= 4, "need at least 4 entries for GetRandomSound rotation"
    assert len(set(pool)) == len(pool), "pool entries must be unique"
    for name in pool:
        assert isinstance(name, str)
        assert name.startswith("Subsystem Critical")


def test_get_random_sound_bound_after_loadsounds(monkeypatch):
    """LoadSounds() rebinds GetRandomSound to LoadTacticalSounds.GetRandomSound
    so callers don't need a separate import."""
    import LoadDamageHitSounds
    # Reset to unbound state to verify rebind is idempotent.
    LoadDamageHitSounds.GetRandomSound = None

    # Stub out App.Game_GetCurrentGame().LoadSound so LoadSounds doesn't
    # need a real audio backend.
    import App
    class _StubGame:
        def LoadSound(self, path, name, loadspec):
            class _Snd:
                def SetVolume(self, *_a): return self
            return _Snd()
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _StubGame())

    LoadDamageHitSounds.LoadSounds()
    assert LoadDamageHitSounds.GetRandomSound is not None
    # Sanity: invoking it returns one of the pool entries.
    pick = LoadDamageHitSounds.GetRandomSound(LoadDamageHitSounds.g_lsSubsystemCriticals)
    assert pick in LoadDamageHitSounds.g_lsSubsystemCriticals
