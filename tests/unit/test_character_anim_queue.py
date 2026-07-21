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
