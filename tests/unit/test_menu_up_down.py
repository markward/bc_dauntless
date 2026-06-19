import App
from engine.bridge_character_anim import (
    BridgeCharacterAnimController, set_controller, clear_controller,
)


def _char():
    c = App.CharacterClass_Create("b.nif", "h.nif")
    c.SetCharacterName("Test")
    return c


def test_menu_up_sets_flag_returns_truthy_and_requests_turn():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        ret = c.MenuUp()
        assert ret                                  # truthy (SDK checks it)
        assert c.IsMenuUp() == 1
        assert ctrl._pending_turns == [(c, True)]
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
        assert ctrl._pending_turns[-1] == (c, False)
    finally:
        clear_controller()


def test_menu_up_no_controller_is_safe():
    clear_controller()
    c = _char()
    assert c.MenuUp()                               # still truthy, no crash
    assert c.IsMenuUp() == 1
