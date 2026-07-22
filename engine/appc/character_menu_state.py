"""MenuState -- CharacterClass's owned menu-state sub-object (tier-0 reference
sec 4.12, struct +0x14c; menu id at +0x14c, ready-flag byte at +0x28 bit 0x1).

Formalizes SP1's informal _menu handle. Holds the top-level menu handle (the id
source) plus a ready flag. GetCharacterFromMenu (a bridge-set search by menu id)
uses menu_id(). Consolidation only -- MenuUp/MenuDown behaviour is unchanged.
"""
from __future__ import annotations


class MenuState:
    def __init__(self):
        self._menu = None       # STTopLevelMenu handle (id source)
        self._ready = False     # +0x28 bit 0x1

    def set_menu(self, menu) -> None:
        # A falsy menu is the _NULL_MENU detach sentinel (its __bool__ is
        # False) or None; both mean "no menu" -> menu_id 0, not-ready. Real
        # menus (STMenu/STTopLevelMenu) are always truthy. This keeps
        # menu_id()'s "0 when none" contract and stops every detached officer
        # aliasing to id(_NULL_MENU).
        menu = menu if menu else None
        self._menu = menu
        # Ready mirrors the existing MenuUp gate: a real, enabled menu.
        try:
            self._ready = bool(menu) and bool(menu.IsEnabled())
        except Exception:
            self._ready = bool(menu)

    def menu_id(self) -> int:
        return id(self._menu) if self._menu is not None else 0

    def has_menu(self) -> bool:
        return self._menu is not None

    def is_ready(self) -> bool:
        return self._ready
