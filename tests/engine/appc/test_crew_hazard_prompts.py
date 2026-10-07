"""Crew 'raise shields' prompts on entering asteroids or radiation.

The latch rules are tested on HazardLatch directly; the engine wiring
(levels, shields, blockers, speaker lookup) through CrewHazardPrompts with
its probes monkeypatched on the module.
"""
import random

import pytest

from engine.appc import crew_hazard_prompts as chp


# ── HazardLatch: when a prompt is due ───────────────────────────────────────

def _latch():
    return chp.HazardLatch(threshold=0.1, cooldown_s=120.0)


def test_entering_with_shields_down_prompts_once():
    h = _latch()
    assert h.step(0.2, shields_up=False, blocked=False, now=0.0) is True
    assert h.step(0.2, shields_up=False, blocked=False, now=1.0) is False
    assert h.step(0.2, shields_up=False, blocked=False, now=500.0) is False


def test_at_or_below_threshold_never_prompts():
    h = _latch()
    assert h.step(0.1, shields_up=False, blocked=False, now=0.0) is False
    assert h.step(0.0, shields_up=False, blocked=False, now=1.0) is False


def test_shields_already_up_does_not_prompt():
    h = _latch()
    assert h.step(0.5, shields_up=True, blocked=False, now=0.0) is False


def test_blocked_defers_the_prompt_until_unblocked():
    h = _latch()
    assert h.step(0.5, shields_up=False, blocked=True, now=0.0) is False
    assert h.step(0.5, shields_up=False, blocked=False, now=1.0) is True


def test_hovering_at_the_edge_does_not_re_prompt():
    h = _latch()
    assert h.step(0.11, shields_up=False, blocked=False, now=0.0) is True
    # dips just under the threshold but not below half of it: still the same exposure
    assert h.step(0.09, shields_up=False, blocked=False, now=200.0) is False
    assert h.step(0.11, shields_up=False, blocked=False, now=201.0) is False


def test_leaving_below_half_threshold_re_arms_after_cooldown():
    h = _latch()
    assert h.step(0.5, shields_up=False, blocked=False, now=0.0) is True
    assert h.step(0.04, shields_up=False, blocked=False, now=10.0) is False
    # re-entered inside the cooldown: nothing
    assert h.step(0.5, shields_up=False, blocked=False, now=60.0) is False
    # still inside, cooldown elapsed: the deferred prompt lands
    assert h.step(0.5, shields_up=False, blocked=False, now=121.0) is True


def test_a_dropped_prompt_waits_for_the_next_exposure():
    h = _latch()
    assert h.due(0.5, shields_up=False, blocked=False, now=0.0) is True
    h.drop()
    assert h.step(0.5, shields_up=False, blocked=False, now=1.0) is False
    # leaving re-arms; a drop starts no cooldown, so re-entry prompts at once
    assert h.step(0.0, shields_up=False, blocked=False, now=2.0) is False
    assert h.step(0.5, shields_up=False, blocked=False, now=3.0) is True


def test_lowering_shields_inside_reminds_again_after_cooldown():
    h = _latch()
    assert h.step(0.5, shields_up=False, blocked=False, now=0.0) is True
    assert h.step(0.5, shields_up=True, blocked=False, now=5.0) is False
    assert h.step(0.5, shields_up=False, blocked=False, now=30.0) is False
    assert h.step(0.5, shields_up=False, blocked=False, now=125.0) is True


# ── CrewHazardPrompts: engine wiring ────────────────────────────────────────

class _Officer:
    def __init__(self):
        self.lines = []

    def SpeakLine(self, db, line, priority):
        self.lines.append((db, line, priority))


@pytest.fixture
def world(monkeypatch):
    """Probes for a player in clear space, shields down, nothing blocking."""
    w = {
        "asteroids": 0.0, "radiation": 0.0, "shields_up": False,
        "mission": "", "cinematic": False, "travelling": False,
        "dialogue": False,
        "officers": {"Engineer": _Officer(), "Science": _Officer()},
    }
    monkeypatch.setattr(chp, "_levels", lambda p: (w["asteroids"], w["radiation"]))
    monkeypatch.setattr(chp, "_shields_up", lambda p: w["shields_up"])
    monkeypatch.setattr(chp, "_mission_name", lambda: w["mission"])
    monkeypatch.setattr(chp, "_cinematic", lambda: w["cinematic"])
    monkeypatch.setattr(chp, "_travelling", lambda p: w["travelling"])
    monkeypatch.setattr(chp, "_dialogue_active", lambda: w["dialogue"])
    monkeypatch.setattr(chp, "_officer", lambda station: w["officers"].get(station))
    monkeypatch.setattr(chp, "_database", lambda: "DB")
    return w


def _spoken(w):
    return [line for o in w["officers"].values() for (_db, line, _p) in o.lines]


def _driver(seed=0):
    return chp.CrewHazardPrompts(rng=random.Random(seed))


def test_asteroids_above_0_05_prompt_an_asteroid_line(world):
    world["asteroids"] = 0.06
    d = _driver()
    d.update(object(), now=0.0)
    assert _spoken(world) in (["BrexAsteroidShields1"], ["MiguelAsteroidShields2"])


def test_asteroid_lines_go_to_their_own_speakers(world):
    world["asteroids"] = 0.5
    seen = set()
    for seed in range(40):
        for o in world["officers"].values():
            o.lines.clear()
        _driver(seed).update(object(), now=0.0)
        for station, o in world["officers"].items():
            for _db, line, _p in o.lines:
                seen.add((station, line))
    assert seen == {("Engineer", "BrexAsteroidShields1"),
                    ("Science", "MiguelAsteroidShields2")}


def test_radiation_above_0_1_prompts_a_brex_radiation_line(world):
    world["radiation"] = 0.11
    _driver().update(object(), now=0.0)
    assert world["officers"]["Engineer"].lines
    assert _spoken(world)[0] in ("BrexRadiationShields1", "BrexRadiationShields2")


def test_lines_are_spoken_from_the_dauntless_database_at_spontaneous_priority(world):
    from engine.appc.ai import CSP_SPONTANEOUS
    world["radiation"] = 0.5
    _driver().update(object(), now=0.0)
    db, _line, priority = world["officers"]["Engineer"].lines[0]
    assert db == "DB" and priority == CSP_SPONTANEOUS


@pytest.mark.parametrize("mission", ["Maelstrom.Episode3.E3M2.E3M2",
                                     "Maelstrom.Episode3.E3M4.E3M4"])
def test_missions_with_their_own_shield_prompt_are_skipped(world, mission):
    world["mission"] = mission
    world["radiation"] = world["asteroids"] = 0.5
    _driver().update(object(), now=0.0)
    assert _spoken(world) == []


def test_other_missions_are_not_skipped(world):
    world["mission"] = "Maelstrom.Episode3.E3M1.E3M1"
    world["radiation"] = 0.5
    _driver().update(object(), now=0.0)
    assert _spoken(world)


@pytest.mark.parametrize("key", ["cinematic", "travelling", "shields_up"])
def test_cinematic_travel_and_raised_shields_suppress(world, key):
    world[key] = True
    world["radiation"] = 0.5
    _driver().update(object(), now=0.0)
    assert _spoken(world) == []


def test_dialogue_in_progress_drops_the_prompt_for_this_exposure(world):
    world["radiation"] = 0.5
    world["dialogue"] = True
    d = _driver()
    d.update(object(), now=0.0)
    world["dialogue"] = False
    d.update(object(), now=1.0)
    d.update(object(), now=500.0)
    assert _spoken(world) == []


def test_a_dropped_prompt_returns_on_the_next_exposure(world):
    world["radiation"] = 0.5
    world["dialogue"] = True
    d = _driver()
    d.update(object(), now=0.0)
    world["dialogue"] = False
    world["radiation"] = 0.0
    d.update(object(), now=1.0)
    world["radiation"] = 0.5
    d.update(object(), now=2.0)
    assert len(_spoken(world)) == 1


def test_polls_at_one_hertz(world):
    d = _driver()
    d.update(object(), now=0.0)
    world["radiation"] = 0.5
    d.update(object(), now=0.5)          # inside the 1 s poll gap
    assert _spoken(world) == []
    d.update(object(), now=1.0)
    assert len(_spoken(world)) == 1


def test_both_hazards_at_once_speak_one_line(world):
    world["radiation"] = world["asteroids"] = 0.5
    d = _driver()
    d.update(object(), now=0.0)
    assert len(_spoken(world)) == 1
    # the first line is now dialogue in progress, so the other hazard's
    # prompt is dropped rather than queued behind it
    world["dialogue"] = True
    d.update(object(), now=1.0)
    assert len(_spoken(world)) == 1


def test_missing_speaker_falls_back_to_the_other_line(world):
    del world["officers"]["Science"]
    world["asteroids"] = 0.5
    for seed in range(20):
        world["officers"]["Engineer"].lines.clear()
        _driver(seed).update(object(), now=0.0)
        assert _spoken(world) == ["BrexAsteroidShields1"]


def test_no_speaker_on_the_bridge_keeps_the_prompt_pending(world):
    engineer = world["officers"].pop("Engineer")
    world["radiation"] = 0.5
    d = _driver()
    d.update(object(), now=0.0)
    world["officers"]["Engineer"] = engineer
    d.update(object(), now=1.0)
    assert len(engineer.lines) == 1


def test_no_player_does_nothing(world):
    world["radiation"] = 0.5
    _driver().update(None, now=0.0)
    assert _spoken(world) == []


def test_reset_forgets_cooldowns(world):
    world["radiation"] = 0.5
    d = _driver()
    d.update(object(), now=0.0)
    d.reset()
    d.update(object(), now=1.0)
    assert len(_spoken(world)) == 2


# ── The real database resolves through the replacements overlay ─────────────

def test_dauntless_crew_database_loads_every_prompt_line():
    import App
    db = App.g_kLocalizationManager.Load(chp.DATABASE)
    try:
        for options in chp.HAZARDS.values():
            for _station, key in options:
                assert db.HasString(key), key
                assert db.GetFilename(key).endswith(key + ".wav")
    finally:
        App.g_kLocalizationManager.Unload(db)


# ── The real engine probes ──────────────────────────────────────────────────

@pytest.fixture
def bridge():
    import App
    from engine.appc.sets import SetClass
    pset = SetClass()
    App.g_kSetManager.AddSet(pset, "bridge")
    yield pset
    App.g_kSetManager.DeleteSet("bridge")


def test_officer_is_none_without_a_real_bridge_set():
    assert chp._officer("Engineer") is None


def test_officer_is_none_when_the_station_is_empty(bridge):
    assert chp._officer("Engineer") is None


def test_officer_finds_the_station_character(bridge):
    from engine.appc.characters import CharacterClass_Create
    brex = CharacterClass_Create("", "")
    bridge.AddObjectToSet(brex, "Engineer")
    assert chp._officer("Engineer") is brex


def test_shields_probe_reads_the_generator(monkeypatch):
    from tests.helpers.shielded_ship import make_shielded_ship
    assert chp._shields_up(make_shielded_ship(shields_up=True)) is True
    assert chp._shields_up(make_shielded_ship(shields_up=False)) is False


def test_levels_probe_takes_the_stronger_asteroid_source(monkeypatch):
    from engine.rocks import far_tier
    from engine.systems import profile
    monkeypatch.setattr(profile, "sample_for_object",
                        lambda o: profile.Sample(asteroids=0.02, radiation=0.3))
    monkeypatch.setattr(far_tier, "field_strength_at", lambda o: 0.4)
    assert chp._levels(object()) == (0.4, 0.3)


def test_unmapped_space_reads_clear():
    from tests.helpers.shielded_ship import make_shielded_ship
    assert chp._levels(make_shielded_ship()) == (0.0, 0.0)


def test_silent_for_follows_the_speech_bus():
    from engine.appc import crew_speech
    crew_speech.bus().reset()
    assert crew_speech.silent_for(now=0.0) == float("inf")
    duration = crew_speech.bus().speak("Brex", "Raise shields.", None, 1, now=0.0)
    assert crew_speech.silent_for(now=0.5) < 0.0
    assert crew_speech.silent_for(now=duration + 3.0) == pytest.approx(3.0)
    crew_speech.bus().reset()


@pytest.mark.parametrize("silent,scripted,active", [
    (float("inf"), False, False),
    (5.0, False, False),
    (4.9, False, True),
    (-1.0, False, True),
    (float("inf"), True, True),
])
def test_dialogue_active_is_a_scripted_line_or_recent_speech(
        monkeypatch, silent, scripted, active):
    from engine.appc import actions, crew_speech
    monkeypatch.setattr(crew_speech, "silent_for", lambda now=None: silent)
    monkeypatch.setattr(actions, "scripted_line_pending", lambda: scripted)
    assert chp._dialogue_active() is active
