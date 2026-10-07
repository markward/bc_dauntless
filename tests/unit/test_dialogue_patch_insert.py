"""An anchor CharacterAction plays its patched-in lines before it completes
(spec docs/superpowers/specs/2026-10-07-dialogue-patches-design.md)."""
import App
import pytest

from engine.appc import crew_speech, dialogue_patches as dp
from engine.appc.actions import TGSequence_Create
from engine.appc.characters import CharacterClass_Create
from engine.appc.localization import TGLocalizationDatabase
from engine.appc.sets import SetClass

TGL = "data/TGL/Test/Mission.tgl"


@pytest.fixture
def world(monkeypatch):
    """A bridge set with an XO, a viewscreen set with Soams, a mission DB,
    and a patch table the test fills in. Every line spoken is recorded."""
    sets = {}
    for set_name, obj in (("bridge", "XO"), ("MiscEng", "Soams")):
        pset = SetClass()
        App.g_kSetManager.AddSet(pset, set_name)
        pset.AddObjectToSet(CharacterClass_Create("", ""), obj)
        sets[set_name] = pset
    db = TGLocalizationDatabase(TGL, strings={k: k + " text" for k in
                                             ("Anchor", "Ins1", "Ins2", "After")})
    table = {}
    monkeypatch.setattr(dp, "inserts_for",
                        lambda tgl, key: table.get((dp.norm_tgl(tgl), key), []))
    spoken = []
    real_emit = crew_speech.emit

    def spy(speaker, d, line_id, priority):
        spoken.append(str(line_id))
        return real_emit(speaker, d, line_id, priority)

    monkeypatch.setattr(crew_speech, "emit", spy)
    yield {"db": db, "table": table, "spoken": spoken, "sets": sets}
    for set_name in sets:
        App.g_kSetManager.DeleteSet(set_name)


def _patch(world, anchor, *inserts):
    world["table"][(dp.norm_tgl(TGL), anchor)] = [
        {"speaker": s, "key": k} for s, k in inserts]


def _line(world, key, db=None, speaker=("bridge", "XO")):
    char = App.CharacterClass_GetObject(App.g_kSetManager.GetSet(speaker[0]), speaker[1])
    return App.CharacterAction_Create(char, App.CharacterAction.AT_SAY_LINE, key,
                                      "Captain", 1, world["db"] if db is None else db)


def _run(seconds=30.0):
    from tests.helpers import headless_mission as hm
    hm.tick(seconds)


def test_no_patch_completes_exactly_as_before(world):
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "After"]
    assert not seq.IsPlaying()


def test_inserts_play_after_the_anchor_and_before_what_follows(world):
    _patch(world, "Anchor", ("MiscEng/Soams", "Ins1"), ("bridge/XO", "Ins2"))
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "Ins1", "Ins2", "After"]


def test_an_explicit_dependent_of_the_anchor_also_waits(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AddAction(anchor)
    seq.AddAction(_line(world, "After"), anchor)
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "Ins1", "After"]


def test_skipping_the_anchor_still_plays_the_inserts(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    anchor.Skip()
    _run()
    assert world["spoken"] == ["Anchor", "Ins1", "After"]


def test_aborting_while_the_anchor_speaks_plays_no_inserts(world):
    # The spec rule is "an aborted anchor never starts its inserts" -- that
    # only bites when the abort lands WHILE the anchor is mid-line (_playing,
    # not yet Completed). Aborting before the anchor ever plays (e.g. a
    # blocking predecessor) can't exercise it: the anchor's Completed() is
    # never reached either way, patched or not.
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    seq.Abort()                        # mid-line: anchor is still speaking
    _run()
    assert world["spoken"] == ["Anchor"]


def test_aborting_while_inserts_play_stops_them_and_the_anchor(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"), ("bridge/XO", "Ins2"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    anchor.Completed()                 # anchor done speaking -> inserts start
    assert anchor._insert_seq is not None
    seq.Abort()
    _run()
    assert "After" not in world["spoken"]
    assert "Ins2" not in world["spoken"]
    assert anchor._insert_seq is None


def test_completed_twice_plays_inserts_once(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    anchor.Completed()
    anchor.Completed()
    _run()
    assert world["spoken"].count("Ins1") == 1
    assert world["spoken"].count("After") == 1


def test_a_missing_speaker_is_skipped_and_the_rest_play(world):
    _patch(world, "Anchor", ("bridge/Nobody", "Ins1"), ("bridge/XO", "Ins2"))
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "Ins2", "After"]


def test_a_line_missing_from_the_database_is_skipped(world):
    _patch(world, "Anchor", ("bridge/XO", "NotInTheTGL"))
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "After"]


def test_an_anchor_without_its_own_database_completes_normally(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    char = App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"), "XO")
    anchor = App.CharacterAction_Create(char, App.CharacterAction.AT_SAY_LINE,
                                        "Anchor", "Captain", 1, None)
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.Play()
    _run()
    assert not seq.IsPlaying()
    assert "Ins1" not in world["spoken"]


def test_inserts_count_as_scripted_dialogue(world):
    # Controller ruling (task-3-brief.md Step 1): the brief's own assertion
    # (actions.scripted_line_pending() is True) is trivially true because the
    # un-completed anchor is itself a pending speak line -- it would pass even
    # if the insert sequence were invisible to scripted_line_pending. Assert
    # the INSERT sequence itself counts instead.
    from engine.appc import actions
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.Play()
    anchor.Completed()
    inserts = anchor._insert_seq
    assert inserts is not None
    assert inserts in actions._launched_sequences
    assert inserts.IsPlaying() and inserts._speech_left()
    seq.Abort()


def test_viewscreen_speakers_get_bcs_viewscreen_arguments(world):
    _patch(world, "Anchor", ("MiscEng/Soams", "Ins1"), ("bridge/XO", "Ins2"))
    actions_ = dp.insert_actions(_line(world, "Anchor"))
    assert [(a._set_name, a._flag) for a in actions_] == [(None, 0), ("Captain", 1)]
