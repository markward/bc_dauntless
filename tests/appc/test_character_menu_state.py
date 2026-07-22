from engine.appc.character_menu_state import MenuState
from engine.appc.characters import (
    CharacterClass, STTopLevelMenu_CreateW, CharacterClass_GetCharacterFromMenu,
)


def test_empty_menu_state():
    ms = MenuState()
    assert ms.has_menu() is False
    assert ms.menu_id() == 0
    assert ms.is_ready() is False


def test_set_menu_tracks_id_and_ready():
    ms = MenuState()
    menu = STTopLevelMenu_CreateW("Helm")
    ms.set_menu(menu)
    assert ms.has_menu() is True
    assert ms.menu_id() == id(menu)
    assert ms.is_ready() is True


def test_set_menu_stamps_menu_state_on_character():
    ch = CharacterClass()
    menu = STTopLevelMenu_CreateW("Helm")
    ch.SetMenu(menu)
    assert ch._menu_state.menu_id() == id(menu)


def test_get_character_from_menu_resolves_owner(monkeypatch):
    ch = CharacterClass()
    ch.SetCharacterName("Helm")
    menu = STTopLevelMenu_CreateW("Helm")
    ch.SetMenu(menu)
    # Resolve against a one-character candidate list.
    found = CharacterClass_GetCharacterFromMenu(id(menu), candidates=[ch])
    assert found is ch
    assert CharacterClass_GetCharacterFromMenu(999999, candidates=[ch]) is None


def test_menu_up_behaviour_unchanged_no_menu():
    ch = CharacterClass()                 # no menu set
    assert ch.MenuUp() == 0               # nothing to raise (same as pre-SP4)


def test_menu_up_behaviour_unchanged_disabled_menu():
    ch = CharacterClass()
    menu = STTopLevelMenu_CreateW("Helm")
    menu.SetDisabled()
    ch.SetMenu(menu)
    assert ch.MenuUp() == 0               # disabled menu: not raised


def test_detach_null_menu_reports_no_menu():
    from engine.appc.characters import STTopLevelMenu_CreateNull
    ch = CharacterClass()
    ch.SetMenu(STTopLevelMenu_CreateNull())   # DetachMenuFrom* pattern
    assert ch._menu_state.has_menu() is False
    assert ch._menu_state.menu_id() == 0
    assert ch._menu_state.is_ready() is False


def test_set_menu_none_and_falsy_normalize():
    ms = MenuState()
    ms.set_menu(None)
    assert ms.has_menu() is False and ms.menu_id() == 0
