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


def test_menu_up_sets_flag_returns_truthy_and_requests_turn():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        ret = c.MenuUp()
        assert ret                                  # truthy (SDK checks it)
        assert c.IsMenuUp() == 1
        # _pending_turns entries are now the richer request_turn_to tuple
        # (character, detail, back, hold, now, on_complete); MenuUp delegates
        # to request_turn_to(character, "Captain", back=False, hold=True).
        assert ctrl._pending_turns == [(c, "Captain", False, True, False, None)]
    finally:
        clear_controller()


def test_menu_down_clears_flag_and_requests_turn_back():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        c.MenuUp()
        c.MenuDown()
        assert c.IsMenuUp() == 0
        # MenuDown delegates to request_turn_to(character, "Captain", back=True,
        # hold=True) — see shape note in test_menu_up_sets_flag_... above.
        assert ctrl._pending_turns[-1] == (c, "Captain", True, True, False, None)
    finally:
        clear_controller()


def test_menu_up_no_controller_is_safe():
    clear_controller()
    c = _char()
    assert c.MenuUp()                               # still truthy, no crash
    assert c.IsMenuUp() == 1
