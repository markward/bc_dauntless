"""SP2 — the single Classify referee (spec §5, RE-confirmed 7x7 table)."""
import pytest
from engine.appc.character_anim_queue import (
    AnimRec, classify, STOP_OLD, REJECT_NEW, STOP_BOTH, COEXIST,
)
from engine.appc.characters import CharacterClass_Create

def test_fresh_character_queue_is_empty():
    c = CharacterClass_Create()
    assert c._anim_current is None
    assert c._anim_pending == []
    assert c._anim_count() == 0
    # SP2 target-name buffers (BC +0xa0 / +0xa4)
    assert c._target_name is None
    assert c._glance_name is None

def R(cat, name=None):
    return AnimRec(category=cat, name=name, flags=0, play=object())

# The authoritative table (spec §5). rows=existing, cols=new; 'N' = name* cell.
TABLE = [
    # new: 0    1    2    3    4    5    6
    ["RN","SO","SO","SO","SO","SO","SO"],  # 0 BREATHE
    ["CO","RN","SO","SO","CO","CO","CO"],  # 1 INTERRUPTABLE
    ["CO","CO","CO","CO","CO","CO","CO"],  # 2 NON_INTERRUPTABLE
    ["CO","CO","CO","CO","N ","CO","CO"],  # 3 TURN
    ["CO","CO","CO","CO","CO","CO","CO"],  # 4 TURN_BACK
    ["CO","CO","SO","SO","SO","CO","N "],  # 5 GLANCE
    ["CO","CO","SO","SO","SO","CO","CO"],  # 6 GLANCE_BACK
]
_CODE = {"SO": STOP_OLD, "RN": REJECT_NEW, "CO": COEXIST}

@pytest.mark.parametrize("ex", range(7))
@pytest.mark.parametrize("nw", range(7))
def test_table_cells_without_names(ex, nw):
    cell = TABLE[ex][nw].strip()
    verdict = classify(R(ex), R(nw), existing_is_current=False)
    if cell == "N":
        # name* with null names collapses to coexist
        assert verdict == COEXIST
    else:
        assert verdict == _CODE[cell]

def test_null_existing_is_coexist():
    assert classify(None, R(2), existing_is_current=False) == COEXIST

def test_name_cell_stop_both_when_names_equal_and_not_current():
    # existing TURN(3) vs new TURN_BACK(4), same non-null name, existing queued
    assert classify(R(3, "Captain"), R(4, "Captain"), existing_is_current=False) == STOP_BOTH
    # existing GLANCE(5) vs new GLANCE_BACK(6)
    assert classify(R(5, "Kirk"), R(6, "Kirk"), existing_is_current=False) == STOP_BOTH

def test_name_cell_coexists_when_existing_is_current():
    assert classify(R(3, "Captain"), R(4, "Captain"), existing_is_current=True) == COEXIST

def test_name_cell_coexists_when_names_differ_or_null():
    assert classify(R(3, "Captain"), R(4, "Data"), existing_is_current=False) == COEXIST
    assert classify(R(3, None), R(4, "Data"), existing_is_current=False) == COEXIST
    assert classify(R(3, "Captain"), R(4, None), existing_is_current=False) == COEXIST

from engine.appc.characters import CharacterClass

def _mk(cat, name=None):
    return object()  # opaque 'play' handle

def test_enqueue_into_empty_coexists():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(_mk(2), CharacterClass.CAT_NON_INTERRUPTABLE, 0, None)
    assert c._anim_count() == 1

def test_new_breathe_rejected_against_breathe_incumbent():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(_mk(0), CharacterClass.CAT_BREATHE)          # pending[0]
    c.SetCurrentAnimation(_mk(0), CharacterClass.CAT_BREATHE)          # reject-new
    assert c._anim_count() == 1

def test_real_move_stops_queued_idle_then_enqueues():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(_mk(0), CharacterClass.CAT_BREATHE)          # idle queued
    c.SetCurrentAnimation(_mk(2), CharacterClass.CAT_NON_INTERRUPTABLE)  # stop-old + enqueue
    # the idle was stopped/removed; the move is queued
    cats = [r.category for r in c._anim_pending]
    assert CharacterClass.CAT_BREATHE not in cats
    assert CharacterClass.CAT_NON_INTERRUPTABLE in cats


def test_stop_both_in_queue_rejects_new_and_drops_existing():
    # existing TURN(3) 'Kirk' queued (not current), new TURN_BACK(4) 'Kirk' -> name* -> STOP_BOTH:
    # the queued TURN is dropped AND the new TURN_BACK is rejected -> queue ends empty.
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_TURN, 0, "Kirk")        # pending[0]
    assert c._anim_count() == 1
    c.SetCurrentAnimation(object(), CharacterClass.CAT_TURN_BACK, 0, "Kirk")   # STOP_BOTH
    assert c._anim_count() == 0


def test_drop_then_reject_does_not_duplicate_survivor():
    # pending [BREATHE, INTERRUPTABLE, BREATHE], new INTERRUPTABLE:
    #   BREATHE vs INTERRUPT -> stop-old (drop); INTERRUPT vs INTERRUPT -> reject-new (return).
    # Expected surviving pending: [INTERRUPTABLE, BREATHE] (no duplicate).
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_BREATHE)        # enqueues BREATHE
    c._anim_pending.append(AnimRec(category=CharacterClass.CAT_INTERRUPTABLE, play=object()))
    c._anim_pending.append(AnimRec(category=CharacterClass.CAT_BREATHE, play=object()))
    assert c._anim_count() == 3
    c.SetCurrentAnimation(object(), CharacterClass.CAT_INTERRUPTABLE)  # drop-then-reject
    cats = [r.category for r in c._anim_pending]
    assert cats == [CharacterClass.CAT_INTERRUPTABLE, CharacterClass.CAT_BREATHE]


def test_predicates_track_the_queue():
    c = CharacterClass_Create()
    assert c.IsAnimating() == 0 and c.IsGoingToAnimate() == 0
    c.SetCurrentAnimation(object(), CharacterClass.CAT_NON_INTERRUPTABLE)  # cat 2
    assert c.IsGoingToAnimate() == 1
    assert c.IsAnimatingNonInterruptable() == 1
    assert c.IsAnimatingInterruptable() == 0


def test_interruptable_predicate_true_only_for_0156():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_GLANCE)  # 5 -> interruptable
    assert c.IsAnimatingInterruptable() == 1
    assert c.IsAnimatingNonInterruptable() == 0


def test_onanimrelease_glance_away_clears_state():
    c = CharacterClass_Create()
    c._glance_name = "Kirk"
    c.SetFlags(CharacterClass.CS_GLANCING)          # 0x2
    from engine.appc.character_anim_queue import AnimRec
    c.OnAnimRelease(AnimRec(category=CharacterClass.CAT_GLANCE_BACK))  # 6
    assert c._glance_name is None
    assert c.IsStateSet(CharacterClass.CS_GLANCING) == 0

def test_onanimrelease_turn_back_clears_state():
    c = CharacterClass_Create()
    c._target_name = "Captain"
    c.SetFlags(CharacterClass.CS_TURNED)            # 0x4
    from engine.appc.character_anim_queue import AnimRec
    c.OnAnimRelease(AnimRec(category=CharacterClass.CAT_TURN_BACK))    # 4
    assert c._target_name is None
    assert c.IsStateSet(CharacterClass.CS_TURNED) == 0

def test_release_retires_finished_current():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_NON_INTERRUPTABLE)
    # promote pending -> current so there is something to release (Task 8 does
    # this in the driver; here set it directly for the unit)
    c._anim_current = c._anim_pending.pop(0)
    c.ReleaseCurrentAnimation(0)     # stub is_active False -> finished -> cleared
    assert c._anim_current is None


def test_shouldplaynow_cat2_always_plays():
    c = CharacterClass_Create()
    c._target_name = "P1"                       # a pending move-target set
    assert c.ShouldPlayNow(AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE)) is True


def test_shouldplaynow_move_target_blocks_non_turnback():
    c = CharacterClass_Create()
    c._target_name = "P1"
    assert c.ShouldPlayNow(AnimRec(category=CharacterClass.CAT_GLANCE)) is False   # blocked
    assert c.ShouldPlayNow(AnimRec(category=CharacterClass.CAT_TURN_BACK)) is True # cat 4 exempt


def test_prepareplay_applies_flags_and_sets_glance_target():
    c = CharacterClass_Create()
    c.PreparePlay(AnimRec(category=CharacterClass.CAT_GLANCE, name="Kirk",
                          flags=CharacterClass.CS_UI_DISABLED))
    assert c.IsStateSet(CharacterClass.CS_UI_DISABLED) == 1   # flags applied
    assert c._glance_name == "Kirk"                            # cat 5 -> glance target


# ── Task 7: Special4 (turn-back) / Special6 (glance-back) follow-up chaining ─

def test_special4_declines_when_no_target_name():
    c = CharacterClass_Create()
    c._target_name = None
    assert c.Special4(AnimRec(category=CharacterClass.CAT_TURN_BACK)) is False


def test_special4_composes_key_plays_and_returns_true(monkeypatch):
    c = CharacterClass_Create()
    c._target_name = "Captain"
    c._location_name = "DBTactical"
    sentinel = object()
    seen_keys = []

    def fake_resolve(key):
        seen_keys.append(key)
        return sentinel

    monkeypatch.setattr(c, "_resolve_anim", fake_resolve)

    played = []
    monkeypatch.setattr(c, "_anim_play_now", lambda rec: played.append(rec))

    result = c.Special4(AnimRec(category=CharacterClass.CAT_TURN_BACK))

    assert seen_keys == ["DBTacticalBackCaptain"]
    assert len(played) == 1
    assert played[0].category == CharacterClass.CAT_TURN_BACK
    assert played[0].name == "Captain"
    assert played[0].play is sentinel
    assert result is True


def test_special4_declines_when_builder_resolves_none(monkeypatch):
    c = CharacterClass_Create()
    c._target_name = "Captain"
    c._location_name = "DBTactical"
    monkeypatch.setattr(c, "_resolve_anim", lambda key: None)
    played = []
    monkeypatch.setattr(c, "_anim_play_now", lambda rec: played.append(rec))
    assert c.Special4(AnimRec(category=CharacterClass.CAT_TURN_BACK)) is False
    assert played == []


def test_special6_declines_when_no_glance_name():
    c = CharacterClass_Create()
    c._glance_name = None
    assert c.Special6(AnimRec(category=CharacterClass.CAT_GLANCE_BACK)) is False


def test_special6_composes_key_plays_and_returns_true(monkeypatch):
    c = CharacterClass_Create()
    c._glance_name = "Kirk"
    c._location_name = "DBTactical"
    sentinel = object()
    seen_keys = []

    def fake_resolve(key):
        seen_keys.append(key)
        return sentinel

    monkeypatch.setattr(c, "_resolve_anim", fake_resolve)

    played = []
    monkeypatch.setattr(c, "_anim_play_now", lambda rec: played.append(rec))

    result = c.Special6(AnimRec(category=CharacterClass.CAT_GLANCE_BACK))

    assert seen_keys == ["DBTacticalGlanceAwayKirk"]
    assert len(played) == 1
    assert played[0].category == CharacterClass.CAT_GLANCE_BACK
    assert played[0].name == "Kirk"
    assert played[0].play is sentinel
    assert result is True


def test_special6_declines_when_builder_resolves_none(monkeypatch):
    c = CharacterClass_Create()
    c._glance_name = "Kirk"
    c._location_name = "DBTactical"
    monkeypatch.setattr(c, "_resolve_anim", lambda key: None)
    played = []
    monkeypatch.setattr(c, "_anim_play_now", lambda rec: played.append(rec))
    assert c.Special6(AnimRec(category=CharacterClass.CAT_GLANCE_BACK)) is False
    assert played == []


# ── Task 8: UpdateAnimationQueue — the per-frame driver (tier-0 §4.8) ────────

def test_update_queue_promotes_pending_to_current():
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    c._anim_pending.append(rec)
    c.UpdateAnimationQueue()
    assert c._anim_current is rec
    assert c._anim_pending == []


def test_update_queue_noop_when_empty_or_current_already_set():
    c = CharacterClass_Create()
    # empty queue, no current -> no-op
    c.UpdateAnimationQueue()
    assert c._anim_current is None
    assert c._anim_pending == []

    # current already set (and still active, so ReleaseCurrentAnimation does
    # not retire it) -> pending left untouched (early return)
    existing = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    c._anim_current = existing
    c._anim_is_active = lambda rec: True
    pending_rec = AnimRec(category=CharacterClass.CAT_GLANCE, play=object())
    c._anim_pending.append(pending_rec)
    c.UpdateAnimationQueue()
    assert c._anim_current is existing
    assert c._anim_pending == [pending_rec]


def test_update_queue_turn_back_routes_to_special4(monkeypatch):
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_TURN_BACK, play=object())
    c._anim_pending.append(rec)

    calls = []
    monkeypatch.setattr(c, "Special4", lambda r: (calls.append(r), True)[1])
    stop_calls = []
    monkeypatch.setattr(c, "_anim_stop_play", lambda r: stop_calls.append(r))

    c.UpdateAnimationQueue()

    assert calls == [rec]
    assert stop_calls == []
    assert c._anim_current is rec
    assert c._anim_pending == []


def test_update_queue_deferred_record_is_stopped_but_becomes_current():
    c = CharacterClass_Create()
    c._target_name = "P1"    # blocks ShouldPlayNow for a plain glance (cat 5)
    rec = AnimRec(category=CharacterClass.CAT_GLANCE, play=object())
    c._anim_pending.append(rec)

    played = []
    c._anim_play_now = lambda r: played.append(r)
    stopped = []
    c._anim_stop_play = lambda r: stopped.append(r)

    c.UpdateAnimationQueue()

    assert played == []
    assert stopped == [rec]
    assert c._anim_current is rec
    assert c._anim_pending == []


# ── Task 9: ClearAnimationsOfType / ClearExtraAnimations / ClearAnimations ───

def test_clear_animations_of_type_removes_matching_pending_only():
    c = CharacterClass_Create()
    glance = AnimRec(category=CharacterClass.CAT_GLANCE, play=object())
    non_interruptable = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    c._anim_pending.append(glance)
    c._anim_pending.append(non_interruptable)
    c.ClearAnimationsOfType(CharacterClass.CAT_GLANCE)
    assert c._anim_pending == [non_interruptable]


def test_clear_animations_of_type_clears_matching_current():
    c = CharacterClass_Create()
    c._anim_current = AnimRec(category=CharacterClass.CAT_GLANCE, play=object())
    c.ClearAnimationsOfType(CharacterClass.CAT_GLANCE)
    assert c._anim_current is None


def test_clear_animations_of_type_leaves_non_matching_current():
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    c._anim_current = rec
    c.ClearAnimationsOfType(CharacterClass.CAT_GLANCE)
    assert c._anim_current is rec


def test_clear_extra_animations_removes_0_1_5_6_leaves_2_and_3():
    c = CharacterClass_Create()
    kept_cats = (CharacterClass.CAT_NON_INTERRUPTABLE, CharacterClass.CAT_TURN)
    removed_cats = (CharacterClass.CAT_BREATHE, CharacterClass.CAT_INTERRUPTABLE,
                    CharacterClass.CAT_GLANCE, CharacterClass.CAT_GLANCE_BACK)
    for cat in kept_cats + removed_cats:
        c._anim_pending.append(AnimRec(category=cat, play=object()))
    c.ClearExtraAnimations()
    cats = [r.category for r in c._anim_pending]
    assert set(cats) == set(kept_cats)


def test_clear_animations_empties_queue_and_nulls_name_buffers():
    c = CharacterClass_Create()
    c._anim_current = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    c._anim_pending.append(AnimRec(category=CharacterClass.CAT_GLANCE, play=object()))
    c._target_name = "Captain"
    c._glance_name = "Kirk"
    c.ClearAnimations()
    assert c._anim_current is None
    assert c._anim_pending == []
    assert c._target_name is None
    assert c._glance_name is None


def test_clear_animations_does_not_crash_on_empty_character():
    c = CharacterClass_Create()
    c.ClearAnimations()  # must not raise
    assert c._anim_current is None
    assert c._anim_pending == []


# ── Task 10: Completion-callback fields (on_complete, hold, now, done_flags) ──

def test_animrec_defaults_have_none_and_falses():
    """Verify AnimRec has default values for the new completion-callback fields."""
    rec = AnimRec(category=CharacterClass.CAT_TURN)
    assert rec.on_complete is None
    assert rec.hold is False
    assert rec.now is False
    assert rec.done_flags == 0


def test_set_current_animation_with_completion_fields():
    """Verify SetCurrentAnimation accepts and threads completion-callback params."""
    c = CharacterClass_Create()
    cb = lambda: None
    c.SetCurrentAnimation(
        object(),
        CharacterClass.CAT_TURN,
        on_complete=cb,
        hold=True,
        now=True,
        done_flags=42
    )
    assert len(c._anim_pending) == 1
    rec = c._anim_pending[0]
    assert rec.on_complete is cb
    assert rec.hold is True
    assert rec.now is True
    assert rec.done_flags == 42


def test_set_current_animation_positional_backward_compat():
    """Verify existing positional calls still work (backward compat)."""
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_NON_INTERRUPTABLE, 8, None)
    assert len(c._anim_pending) == 1
    rec = c._anim_pending[0]
    assert rec.category == CharacterClass.CAT_NON_INTERRUPTABLE
    assert rec.flags == 8
    assert rec.name is None
    # New fields should have defaults
    assert rec.on_complete is None
    assert rec.hold is False
    assert rec.now is False
    assert rec.done_flags == 0


# ── Task 12: seam wiring (controller + builder resolution) + turn/glance ────

from engine import bridge_character_anim


class _FakeController:
    def __init__(self):
        self.played = []
        self.stopped = []
        self.active = False

    def play_record(self, character, rec) -> None:
        self.played.append((character, rec))

    def stop(self, character) -> None:
        self.stopped.append(character)

    def is_active(self, character) -> bool:
        return self.active


@pytest.fixture
def fake_controller():
    ctrl = _FakeController()
    bridge_character_anim.set_controller(ctrl)
    try:
        yield ctrl
    finally:
        bridge_character_anim.set_controller(None)


def test_anim_is_active_false_with_no_controller_wired():
    bridge_character_anim.set_controller(None)
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    assert c._anim_is_active(rec) is False


def test_update_animation_queue_plays_through_wired_controller(fake_controller):
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    c._anim_pending.append(rec)
    c.UpdateAnimationQueue()
    assert fake_controller.played == [(c, rec)]
    assert c._anim_current is rec


def test_anim_stop_play_calls_controller_stop(fake_controller):
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_BREATHE, play=object())
    c._anim_stop_play(rec)
    assert fake_controller.stopped == [c]


def test_anim_is_active_reflects_wired_controller(fake_controller):
    c = CharacterClass_Create()
    rec = AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE, play=object())
    fake_controller.active = True
    assert c._anim_is_active(rec) is True
    fake_controller.active = False
    assert c._anim_is_active(rec) is False


def test_resolve_anim_returns_none_when_builder_raises(monkeypatch):
    from engine.appc import bridge_placement

    def boom(character, key):
        raise RuntimeError("no builder")

    monkeypatch.setattr(bridge_placement, "resolve_builder", boom)
    c = CharacterClass_Create()
    assert c._resolve_anim("anything") is None


def test_turntowards_captain_enqueues_turn_record_and_returns_zero():
    c = CharacterClass_Create()
    c.SetActive(1)
    cb = lambda: None
    result = c.TurnTowards("Captain", on_complete=cb)
    assert result == 0
    assert len(c._anim_pending) == 1
    rec = c._anim_pending[0]
    assert rec.category == CharacterClass.CAT_TURN
    assert rec.name == "Captain"
    assert rec.on_complete is cb
    assert rec.hold is True


def test_turntowards_non_captain_or_none_enqueues_nothing():
    c = CharacterClass_Create()
    c.SetActive(1)
    assert c.TurnTowards("Data") == 0
    assert c._anim_pending == []
    assert c.TurnTowards(None) == 0
    assert c._anim_pending == []


def test_turnback_clears_interruptable_set_and_enqueues_turn_back():
    c = CharacterClass_Create()
    for cat in (CharacterClass.CAT_BREATHE, CharacterClass.CAT_INTERRUPTABLE,
                CharacterClass.CAT_GLANCE, CharacterClass.CAT_GLANCE_BACK):
        c._anim_pending.append(AnimRec(category=cat, play=object()))
    cb = lambda: None
    result = c.TurnBack(cb)
    assert result == 1
    cats = [r.category for r in c._anim_pending]
    assert CharacterClass.CAT_BREATHE not in cats
    assert CharacterClass.CAT_INTERRUPTABLE not in cats
    assert CharacterClass.CAT_GLANCE not in cats
    assert CharacterClass.CAT_GLANCE_BACK not in cats
    assert CharacterClass.CAT_TURN_BACK in cats
    rec = [r for r in c._anim_pending if r.category == CharacterClass.CAT_TURN_BACK][0]
    assert rec.on_complete is cb


def test_glanceat_enqueues_glance_record_with_name():
    c = CharacterClass_Create()
    cb = lambda: None
    result = c.GlanceAt("Kirk", cb)
    assert result == 1
    assert len(c._anim_pending) == 1
    rec = c._anim_pending[0]
    assert rec.category == CharacterClass.CAT_GLANCE
    assert rec.name == "Kirk"
    assert rec.on_complete is cb


def test_glanceat_none_returns_zero_and_enqueues_nothing():
    c = CharacterClass_Create()
    assert c.GlanceAt(None) == 0
    assert c._anim_pending == []


def test_glanceaway_enqueues_glance_back_record():
    c = CharacterClass_Create()
    cb = lambda: None
    result = c.GlanceAway(cb)
    assert result == 1
    assert len(c._anim_pending) == 1
    rec = c._anim_pending[0]
    assert rec.category == CharacterClass.CAT_GLANCE_BACK
    assert rec.on_complete is cb
