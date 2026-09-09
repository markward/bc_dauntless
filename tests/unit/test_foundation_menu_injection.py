"""Injecting registered ships into the BUILT QuickBattle menus.

Registration alone (test_foundation_quickbattle.py) only feeds the five
static tables; GenerateShipMenu -- called from BuildDialog -- builds the
ship pane from hardcoded per-ship lines and never reads them. This is the
other half: a real STButton landing inside a real STCharacterMenu category
in the already-built g_pShipsPane / g_pPlayerPane, which is exactly what
engine/ui/quick_battle_setup_panel.py's `_collect_categories` DFS looks for.
"""

import pytest

from engine import foundation
from engine.foundation import quickbattle
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.tg_ui.st_widgets import STCharacterMenu, STCharacterMenu_CreateW
from engine.appc.characters import STButton


ET_SELECT_SHIP_TYPE = 501
ET_SELECT_PLAYER_SHIP_TYPE = 502


class _FakeQB:
    """Stands in for the built SDK QuickBattle module: real pane/category
    widgets (so the picker's own DFS shape is exercised for real), plus a
    CreateBridgeMenuButton and BuildDialog shaped like the real ones.
    """

    def __init__(self):
        self.g_pShipsPane = TGPane()
        self.g_pPlayerPane = TGPane()
        self.g_pXO = object()
        self.ET_SELECT_SHIP_TYPE = ET_SELECT_SHIP_TYPE
        self.ET_SELECT_PLAYER_SHIP_TYPE = ET_SELECT_PLAYER_SHIP_TYPE
        self.calls = []
        self.build_dialog_calls = 0

    def CreateBridgeMenuButton(self, name, event, sub_type, character,
                                width=0.0, height=0.0):
        self.calls.append((name, event, sub_type, character))
        return STButton(name, (event, sub_type, character))

    def BuildDialog(self, bPreservePane=0):
        # Real BuildDialog replaces both panes wholesale on every call --
        # GenerateShipMenu runs from scratch, stock ships included.
        self.build_dialog_calls += 1
        self.g_pShipsPane = TGPane()
        self.g_pPlayerPane = TGPane()


def _add_stock_category(pane, label, *button_names):
    """A pre-existing STCharacterMenu, the shape BuildDialog's own
    GenerateShipMenu leaves behind for the stock ships."""
    cat = STCharacterMenu_CreateW(label)
    for n in button_names:
        cat.AddChild(STButton(n, None))
    pane.AddChild(cat, 0.0, 0.0)
    return cat


def _categories(pane):
    return [c for c, _x, _y in pane._children if isinstance(c, STCharacterMenu)]


def _buttons(category):
    return list(category._children)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def _ship(name="ZZTest", label="ZZ Test Ship", ship_group="Fed Ships",
          player_group=None):
    d = foundation.FedShipDef(
        name, 1, {"name": label, "shipFile": name})
    d.RegisterQBShipMenu(ship_group, qb=None)
    if player_group is not None:
        d.RegisterQBPlayerShipMenu(player_group, qb=None)
    return d


def test_no_registered_ships_adds_nothing():
    qb = _FakeQB()
    added = quickbattle.inject_into_menus(qb=qb)
    assert added == 0
    assert _categories(qb.g_pShipsPane) == []
    assert _categories(qb.g_pPlayerPane) == []
    assert qb.calls == []


def test_unknown_group_gets_a_new_category():
    _ship(ship_group="Fed Ships")
    qb = _FakeQB()
    added = quickbattle.inject_into_menus(qb=qb)

    assert added == 1
    cats = _categories(qb.g_pShipsPane)
    assert len(cats) == 1
    assert cats[0].GetLabel() == "Fed Ships"
    assert cats[0].GetButtonW("ZZ Test Ship") is not None


def test_existing_category_is_reused_not_duplicated():
    qb = _FakeQB()
    _add_stock_category(qb.g_pShipsPane, "Fed Ships", "Akira", "Galaxy")
    _ship(ship_group="Fed Ships")

    added = quickbattle.inject_into_menus(qb=qb)

    assert added == 1
    cats = _categories(qb.g_pShipsPane)
    assert len(cats) == 1                     # no second "Fed Ships" menu
    labels = [b.GetLabel() for b in _buttons(cats[0])]
    assert labels == ["Akira", "Galaxy", "ZZ Test Ship"]


def test_button_carries_the_ships_own_type_id_and_event_type():
    d = _ship(ship_group="Fed Ships")
    qb = _FakeQB()
    quickbattle.inject_into_menus(qb=qb)

    sid = dict(quickbattle.registered())["ZZ Test Ship"]
    assert qb.calls == [("ZZ Test Ship", ET_SELECT_SHIP_TYPE, sid, qb.g_pXO)]


def test_player_pane_uses_the_player_event_type_and_group():
    _ship(ship_group="Fed Ships", player_group="Player Ships")
    qb = _FakeQB()
    quickbattle.inject_into_menus(qb=qb)

    ship_cats = _categories(qb.g_pShipsPane)
    player_cats = _categories(qb.g_pPlayerPane)
    assert [c.GetLabel() for c in ship_cats] == ["Fed Ships"]
    assert [c.GetLabel() for c in player_cats] == ["Player Ships"]

    events = {(name, evt) for name, evt, _sid, _char in qb.calls}
    assert ("ZZ Test Ship", ET_SELECT_SHIP_TYPE) in events
    assert ("ZZ Test Ship", ET_SELECT_PLAYER_SHIP_TYPE) in events


def test_a_ship_never_registered_for_the_player_pane_is_skipped():
    """menuGroup set, playerMenuGroup left None -- register() leaves it None
    when RegisterQBPlayerShipMenu is never called."""
    _ship(ship_group="Fed Ships", player_group=None)
    qb = _FakeQB()
    quickbattle.inject_into_menus(qb=qb)

    assert _categories(qb.g_pPlayerPane) == []


def test_injection_is_idempotent_against_the_same_pane():
    _ship(ship_group="Fed Ships")
    qb = _FakeQB()

    first = quickbattle.inject_into_menus(qb=qb)
    second = quickbattle.inject_into_menus(qb=qb)

    assert first == 1
    assert second == 0
    cats = _categories(qb.g_pShipsPane)
    assert len(cats) == 1
    assert len(_buttons(cats[0])) == 1


def test_build_dialog_wrap_reinjects_after_rebuild():
    """BuildDialog() replaces g_pShipsPane/g_pPlayerPane wholesale on every
    call, real BuildDialog included -- GenerateShipMenu runs from scratch
    even for the stock ships. inject_into_menus wraps BuildDialog once so a
    rebuild reached from ANYWHERE (not just the one host_loop.py call site)
    still carries mod ships into the fresh panes."""
    _ship(ship_group="Fed Ships")
    qb = _FakeQB()
    quickbattle.inject_into_menus(qb=qb)   # installs the BuildDialog wrap

    old_pane = qb.g_pShipsPane
    qb.BuildDialog()                       # SDK-style rebuild, called directly
    assert qb.g_pShipsPane is not old_pane  # a genuinely fresh pane...

    cats = _categories(qb.g_pShipsPane)
    assert [c.GetLabel() for c in cats] == ["Fed Ships"]   # ...re-populated
    assert cats[0].GetButtonW("ZZ Test Ship") is not None


def test_reset_clears_registrations_so_a_later_call_injects_nothing():
    _ship(ship_group="Fed Ships")
    quickbattle.reset()
    qb = _FakeQB()

    added = quickbattle.inject_into_menus(qb=qb)

    assert added == 0
    assert _categories(qb.g_pShipsPane) == []


# ── Group labels are TGL KEYS, not display strings ──────────────────────
# BC's own QuickBattle.py builds every stock category through the mission
# database: `STCharacterMenu_CreateW(g_pMissionDatabase.GetString("Fed
# Ships"))`. Foundation's StaticDefs.py registers the 30 stock ships under
# those same keys ('Fed Ships', 'Card Ships', ...), which is why every mod
# in the corpus authors `menuGroup = 'Fed Ships'`. Comparing a mod's raw
# key against a built category's RESOLVED label never matches, so mod ships
# used to form a duplicate "Fed Ships" category beside "Federation Ships".

class _FakeDatabase:
    """The two stock keys whose TGL text differs from the key itself."""

    _STRINGS = {
        "Fed Ships":  "Federation Ships",
        "Card Ships": "Cardassian Ships",
    }

    def GetString(self, key):
        # Appc returns the key unchanged for an unregistered key.
        return self._STRINGS.get(key, key)


def _qb_with_database():
    qb = _FakeQB()
    qb.g_pMissionDatabase = _FakeDatabase()
    return qb


def test_tgl_key_group_lands_in_the_resolved_stock_category():
    _ship(ship_group="Fed Ships")
    qb = _qb_with_database()
    _add_stock_category(qb.g_pShipsPane, "Federation Ships", "Galaxy")

    added = quickbattle.inject_into_menus(qb=qb)

    assert added == 1
    cats = _categories(qb.g_pShipsPane)
    assert [c.GetLabel() for c in cats] == ["Federation Ships"]
    assert cats[0].GetButtonW("ZZ Test Ship") is not None


def test_group_with_no_tgl_entry_keeps_its_own_category():
    # "Borg Ships" is a category the mod invents (the Steamrunner pack
    # registers two ships there); BC has no such key, so GetString returns
    # it unchanged and a new category is the correct outcome.
    _ship(ship_group="Borg Ships")
    qb = _qb_with_database()
    _add_stock_category(qb.g_pShipsPane, "Federation Ships", "Galaxy")

    added = quickbattle.inject_into_menus(qb=qb)

    assert added == 1
    labels = [c.GetLabel() for c in _categories(qb.g_pShipsPane)]
    assert labels == ["Federation Ships", "Borg Ships"]


# ── SubMenu / SubSubMenu nest inside the group ──────────────────────────
# Foundation ship defs carry SubMenu and SubSubMenu beside menuGroup, and
# the corpus uses both depths: the LC Intrepid pack puts three ships under
# menuGroup 'Fed Ships' + SubMenu "LC Intrepid Class", and the Steamrunner
# pack adds SubSubMenu "Steamrunner Class" under SubMenu "TNG Ships". The
# hierarchy is menuGroup > SubMenu > SubSubMenu > ship. STMenu already
# models this natively -- AddChild registers a nested STMenu in _submenus,
# reachable via GetSubmenuW -- so nesting is BC's own widget shape.

def _sub_ship(name, label, sub=None, subsub=None, group="Fed Ships"):
    d = foundation.FedShipDef(name, 1, {"name": label, "shipFile": name})
    if sub is not None:
        d.SubMenu = sub
    if subsub is not None:
        d.SubSubMenu = subsub
    d.RegisterQBShipMenu(group, qb=None)
    return d


def test_submenu_nests_the_ship_one_level_deeper():
    _sub_ship("ZZI", "USS Intrepid LC", sub="LC Intrepid Class")
    qb = _qb_with_database()

    quickbattle.inject_into_menus(qb=qb)

    cats = _categories(qb.g_pShipsPane)
    assert [c.GetLabel() for c in cats] == ["Federation Ships"]
    # The ship is NOT a direct child of the group...
    assert cats[0].GetButtonW("USS Intrepid LC") is None
    # ...it is inside the submenu.
    sub = cats[0].GetSubmenuW("LC Intrepid Class")
    assert sub is not None
    assert sub.GetButtonW("USS Intrepid LC") is not None


def test_ships_sharing_a_submenu_share_one_menu():
    for n, label in (("ZZI", "USS Intrepid LC"),
                     ("ZZV", "USS Voyager LC"),
                     ("ZZB", "USS Bellerophon LC")):
        _sub_ship(n, label, sub="LC Intrepid Class")
    qb = _qb_with_database()

    added = quickbattle.inject_into_menus(qb=qb)

    assert added == 3
    group = _categories(qb.g_pShipsPane)[0]
    subs = [c for c in group._children if isinstance(c, STCharacterMenu)]
    assert len(subs) == 1, "one submenu, not one per ship"
    assert sorted(b.GetLabel() for b in subs[0]._children) == [
        "USS Bellerophon LC", "USS Intrepid LC", "USS Voyager LC"]


def test_subsubmenu_nests_a_third_level():
    _sub_ship("ZZS", "Steamrunner Aad",
              sub="TNG Ships", subsub="Steamrunner Class")
    qb = _qb_with_database()

    quickbattle.inject_into_menus(qb=qb)

    group = _categories(qb.g_pShipsPane)[0]
    tng = group.GetSubmenuW("TNG Ships")
    assert tng is not None
    klass = tng.GetSubmenuW("Steamrunner Class")
    assert klass is not None
    assert klass.GetButtonW("Steamrunner Aad") is not None


def test_subsubmenu_without_submenu_uses_one_level():
    """A gap in the chain closes up rather than creating an unnamed level."""
    _sub_ship("ZZX", "Odd One Out", subsub="Only Deep Label")
    qb = _qb_with_database()

    quickbattle.inject_into_menus(qb=qb)

    group = _categories(qb.g_pShipsPane)[0]
    only = group.GetSubmenuW("Only Deep Label")
    assert only is not None
    assert only.GetButtonW("Odd One Out") is not None


def test_no_submenu_still_lands_directly_in_the_group():
    """The path stock ships take must be untouched."""
    _sub_ship("ZZP", "Plain Ship")
    qb = _qb_with_database()

    quickbattle.inject_into_menus(qb=qb)

    group = _categories(qb.g_pShipsPane)[0]
    assert group.GetButtonW("Plain Ship") is not None
    assert [c for c in group._children
            if isinstance(c, STCharacterMenu)] == []


def test_nested_injection_is_idempotent():
    _sub_ship("ZZI", "USS Intrepid LC", sub="LC Intrepid Class")
    qb = _qb_with_database()

    assert quickbattle.inject_into_menus(qb=qb) == 1
    assert quickbattle.inject_into_menus(qb=qb) == 0

    group = _categories(qb.g_pShipsPane)[0]
    subs = [c for c in group._children if isinstance(c, STCharacterMenu)]
    assert len(subs) == 1
    assert len(subs[0]._children) == 1
