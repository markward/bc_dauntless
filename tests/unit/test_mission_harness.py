def test_discover_missions_finds_m1basic():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    assert "Custom.Tutorial.Episode.M1Basic.M1Basic" in missions


def test_discover_missions_count():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    # SDK has 35 files with def Initialize(pMission) — sanity-check the range
    assert 30 <= len(missions) <= 40


def test_discover_missions_no_init_files():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    assert not any("__init__" in m for m in missions)


def test_discover_missions_no_episode_scripts():
    from tools.mission_harness import discover_missions
    # Episode-level scripts use Initialize(pEpisode), not Initialize(pMission)
    missions = discover_missions()
    assert not any(m.endswith("Episode1") or m.endswith("Episode5") for m in missions)
