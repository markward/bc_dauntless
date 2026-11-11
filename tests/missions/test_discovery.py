"""MissionRegistry.discover reads the stock script listing (the install's
.pyc, plus the test-only Custom/Tutorial fixture tree) into a typed tree."""

from engine import stock_scripts
from engine.missions.discovery import (
    discover,
    MissionEntry,
    EpisodeEntry,
    FamilyEntry,
    MissionRegistry,
)


def test_discover_returns_registry():
    reg = discover()
    assert isinstance(reg, MissionRegistry)
    assert isinstance(reg.families, list)
    assert reg.families  # at least one


def test_discover_finds_tutorial_missions():
    reg = discover()
    fams = {f.dir_name: f for f in reg.families}
    assert "Tutorial" in fams

    tutorial = fams["Tutorial"]
    missions = [m.dir_name for ep in tutorial.episodes for m in ep.missions]
    # M4Complex exists as a dir in some installs but has no leaf .py shipped
    # with the SDK; discover() only lists missions that can actually load.
    for expected in ("M1Basic", "M2Objects", "M3Gameflow"):
        assert expected in missions, f"missing {expected}; got {missions}"
    # The Episode/Episode.py initializer must NOT appear as a mission —
    # it's the episode entry-point, not a leaf mission.
    assert "Episode" not in missions, f"Episode init leaked into missions: {missions}"


def test_discover_finds_maelstrom_episode_grouping():
    reg = discover()
    fams = {f.dir_name: f for f in reg.families}
    assert "Maelstrom" in fams
    eps = {ep.dir_name for ep in fams["Maelstrom"].episodes}
    for expected in ("Episode1", "Episode2", "Episode3"):
        assert expected in eps, f"missing {expected}; got {eps}"


def test_discover_maelstrom_campaign_order_and_labels():
    """Maelstrom missions follow the original game's menu order and labels,
    not a lexical directory sort. Episode 4 plays E4M6 first; Episode 2's
    first mission (dir E2M0) is labelled "E1M3"."""
    reg = discover()
    fams = {f.dir_name: f for f in reg.families}
    eps = {ep.dir_name: ep for ep in fams["Maelstrom"].episodes}

    ep4_dirs = [m.dir_name for m in eps["Episode4"].missions]
    assert ep4_dirs == ["E4M6", "E4M4", "E4M5"], ep4_dirs

    ep2 = eps["Episode2"]
    assert [m.dir_name for m in ep2.missions] == ["E2M0", "E2M1", "E2M2", "E2M6"]
    # display_name backfill requires the real Options.tgl; assert the campaign
    # label only when it's present (game install), else accept dir-name fallback.
    first = ep2.missions[0]
    assert first.display_name in ("E1M3", "E2M0"), first.display_name


def test_maelstrom_campaign_table_matches_disk():
    """Guard against SDK/table drift: every on-disk Maelstrom mission dir is in
    MAELSTROM_CAMPAIGN, and the table lists no directory that isn't on disk."""
    from engine.missions.name_resolver import MAELSTROM_CAMPAIGN

    reg = discover()
    fams = {f.dir_name: f for f in reg.families}
    on_disk = {
        (ep.dir_name, m.dir_name)
        for ep in fams["Maelstrom"].episodes for m in ep.missions
    }
    in_table = {
        (ep_dir, mission_dir)
        for ep_dir, rows in MAELSTROM_CAMPAIGN.items()
        for mission_dir, _key in rows
    }
    assert on_disk == in_table, (
        f"only on disk: {on_disk - in_table}; "
        f"only in table: {in_table - on_disk}"
    )


def test_discover_module_name_format():
    reg = discover()
    m1 = next(
        m for f in reg.families if f.dir_name == "Tutorial"
        for ep in f.episodes for m in ep.missions
        if m.dir_name == "M1Basic"
    )
    assert m1.module_name == "Custom.Tutorial.Episode.M1Basic.M1Basic"


def test_discover_synthetic_tree(tmp_path):
    """End-to-end on a tmp_path fixture tree -- no SDK assets required."""
    custom = tmp_path / "Custom" / "Tutorial" / "Episode"
    (custom / "MX").mkdir(parents=True)
    (custom / "MX" / "MX.py").write_text("def Initialize(pMission): pass\n")
    # A dir whose .py has no Initialize -- must NOT be discovered.
    (custom / "Skip").mkdir()
    (custom / "Skip" / "Skip.py").write_text("# nothing here\n")
    # A dir whose name doesn't match its .py -- must NOT be discovered.
    (custom / "Mismatch").mkdir()
    (custom / "Mismatch" / "Other.py").write_text(
        "def Initialize(pMission): pass\n")
    # An episode entry point -- must NOT be discovered.
    (custom / "Episode.py").write_text("def Initialize(pEpisode): pass\n")
    stock_scripts.clear_fixture_trees()
    stock_scripts.add_fixture_tree(tmp_path, "Custom/Tutorial")

    reg = discover()
    found = [
        m.dir_name
        for f in reg.families if f.dir_name == "Tutorial"
        for ep in f.episodes for m in ep.missions
    ]
    assert found == ["MX"]


def test_discovery_needs_no_sdk_for_maelstrom():
    """With the SDK fixture trees cleared, the retail install alone still
    lists Maelstrom and Multiplayer; the Tutorial family (an SDK sample) is
    simply absent. (engine.paths has no SDK accessor left to probe: the
    absence guard is tests/unit/test_game_never_reads_sdk.py.)"""
    stock_scripts.clear_fixture_trees()

    reg = discover()
    fams = {f.dir_name: f for f in reg.families}
    assert "Tutorial" not in fams
    assert "Maelstrom" in fams and "Multiplayer" in fams
    multiplayer = [m.module_name for ep in fams["Multiplayer"].episodes
                   for m in ep.missions]
    assert "Multiplayer.Episode.Mission1.Mission1" in multiplayer
    # Multiplayer/MissionShared defines Initialize(pMission) but is not a
    # <dir>/<dir> mission script.
    assert not any("MissionShared" in m for m in multiplayer)
    e1 = {ep.dir_name: ep for ep in fams["Maelstrom"].episodes}["Episode1"]
    assert [m.module_name for m in e1.missions] == [
        "Maelstrom.Episode1.E1M1.E1M1", "Maelstrom.Episode1.E1M2.E1M2"]
