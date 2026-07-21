"""The CharacterClass animation-queue referee + record type (spec §5).

Pure and side-effect-free: a single referee `classify(existing, new,
existing_is_current)` implementing BC's RE-confirmed 7x7 verdict table. Kept out
of characters.py so the table is testable cell-for-cell in isolation.
"""
from dataclasses import dataclass

# Verdict codes. Values chosen for readability; callers use the names.
STOP_OLD = 0       # stop the existing animation, let the new one play
REJECT_NEW = 1     # keep the existing, drop the new
STOP_BOTH = 2      # stop the existing AND drop the new
COEXIST = 3        # leave both; the new joins the queue


@dataclass
class AnimRec:
    """A queued animation record (BC's 0x10-byte AnimRec).

    category : CAT_* code (0..6)
    name     : the record's own name (BC +0x0C, the 4th SetCurrentAnimation arg);
               compared by the referee in the two name* cells. May be None.
    flags    : CS_* flags to apply while playing (BC +0x04).
    play     : the resolved thing the clip-player runs (SDK sequence / clips).
    on_complete : completion callback (Task 10; defaults None).
    hold     : whether to hold the animation on completion (Task 10; defaults False).
    now      : whether to play immediately (Task 10; defaults False).
    done_flags : flags to apply on completion (Task 10; defaults 0).
    """
    category: int
    name: object = None
    flags: int = 0
    play: object = None
    on_complete: object = None
    hold: bool = False
    now: bool = False
    done_flags: int = 0


# Sentinel for the two name-tiebreaker cells.
_NAME = object()

# rows = existing category, cols = new category (spec §5, verbatim).
_T = None  # filled below for readability
_VERDICT_TABLE = [
    # new: 0BREATHE    1INTERRUPT  2NON_INT    3TURN       4TURN_BACK  5GLANCE     6GLANCE_BACK
    [REJECT_NEW, STOP_OLD,  STOP_OLD,  STOP_OLD,  STOP_OLD,  STOP_OLD,  STOP_OLD ],  # 0 BREATHE
    [COEXIST,    REJECT_NEW, STOP_OLD, STOP_OLD,  COEXIST,   COEXIST,   COEXIST  ],  # 1 INTERRUPTABLE
    [COEXIST,    COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST  ],  # 2 NON_INTERRUPTABLE
    [COEXIST,    COEXIST,   COEXIST,   COEXIST,   _NAME,     COEXIST,   COEXIST  ],  # 3 TURN
    [COEXIST,    COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST  ],  # 4 TURN_BACK
    [COEXIST,    COEXIST,   STOP_OLD,  STOP_OLD,  STOP_OLD,  COEXIST,   _NAME    ],  # 5 GLANCE
    [COEXIST,    COEXIST,   STOP_OLD,  STOP_OLD,  STOP_OLD,  COEXIST,   COEXIST  ],  # 6 GLANCE_BACK
]


def classify(existing, new, existing_is_current):
    """Return the verdict for enqueuing `new` against `existing` (spec §5).

    `existing` is None when there is no conflict partner (⇒ COEXIST).
    `existing_is_current` distinguishes Classify1 (vs the currently-playing
    animation, lenient) from Classify2 (vs a queued record, strict).
    """
    if existing is None:
        return COEXIST
    cell = _VERDICT_TABLE[existing.category][new.category]
    if cell is _NAME:
        if (existing.name and new.name and existing.name == new.name
                and not existing_is_current):
            return STOP_BOTH
        return COEXIST
    return cell
