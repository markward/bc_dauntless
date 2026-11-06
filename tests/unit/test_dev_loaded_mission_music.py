"""A mission loaded directly (picker, DAUNTLESS_MISSION) sets up its music.

The dev loader skips BC's Game.LoadEpisode cascade; host_loop._init_mission
runs only the campaign's and the episode's SetupMusic, so E1M1 opens on its
episode's music as it does when booted through the campaign."""


def test_e1m1_loaded_directly_starts_its_music():
    from tests.helpers import headless_mission as hm
    hm.load("Maelstrom.Episode1.E1M1.E1M1")
    import App
    import DynamicMusic
    assert DynamicMusic.g_bInitialized
    assert App.g_kMusicManager.current() is not None
