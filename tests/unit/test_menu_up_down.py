import App
from engine.bridge_character_anim import (
    BridgeCharacterAnimController, set_controller, clear_controller,
)


def _char():
    """A bridge officer with a menu ATTACHED, as the SDK does
    (`pHelm.SetMenu(tcw.FindMenu("Helm"))`, HelmCharacterHandlers:50).

    The attachment is load-bearing: MenuUp() raises the officer's OWN menu
    (GetMenu()), so an officer holding the NULL menu has nothing to raise and
    returns 0 — see tests/unit/test_character_menu_primitive.py."""
    c = App.CharacterClass_Create("b.nif", "h.nif")
    c.SetCharacterName("Test")
    c.SetMenu(App.STTopLevelMenu_CreateW("Test"))
    return c


def test_menu_up_sets_flag_returns_truthy_and_turns_to_captain():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        ret = c.MenuUp()
        assert ret                                  # truthy (SDK checks it)
        assert c.IsMenuUp() == 1
        # SP2: MenuUp's _notify_menu re-points through the CharacterClass door
        # (TurnTowards("Captain")) -> ENQUEUES a CAT_TURN "Captain" record rather
        # than calling the controller directly.
        assert len(c._anim_pending) == 1
        rec = c._anim_pending[0]
        assert rec.category == c.CAT_TURN and rec.name == "Captain"
        # Draining the queue drives the record to the clip-player: play_record
        # calls request_turn_to(c, "Captain", back=False, hold=True, now=False).
        c.UpdateAnimationQueue()
        assert ctrl._pending_turns == [(c, "Captain", False, True, False, None)]
    finally:
        clear_controller()


def test_menu_down_clears_flag_and_turns_back():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        c.MenuUp()
        c.UpdateAnimationQueue()                     # the turn-to plays (becomes current)
        c.MenuDown()
        assert c.IsMenuUp() == 0
        # MenuDown -> TurnBack() enqueues a CAT_TURN_BACK "Captain" record. It
        # COEXISTS with the currently-playing turn (the name-tiebreak is lenient
        # vs the current animation), so it queues rather than annihilating it.
        # (A queued CAT_TURN_BACK is driven by Special4's turn-back-follow-up
        # chaining -- composing "<loc>BackCaptain" and playing it -- which is
        # exercised in test_character_anim_queue.py; it needs a registered
        # back-builder this bare officer lacks, so we assert at the enqueue seam.)
        back = [r for r in c._anim_pending if r.category == c.CAT_TURN_BACK]
        assert len(back) == 1 and back[0].name == "Captain"
    finally:
        clear_controller()


def test_menu_up_no_controller_is_safe():
    clear_controller()
    c = _char()
    assert c.MenuUp()                               # still truthy, no crash
    assert c.IsMenuUp() == 1
