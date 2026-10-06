"""STMenu.DeleteChild(<object>) must drop the child from the label lookups
too, not only from the drawn `_children` list.

The SDK removes buttons by OBJECT (HelmMenuHandlers.ExitedSet:
`pHailMenu.DeleteChild(pItem)`), then dedupes re-adds by LABEL
(CreateHailButton: `if pHailMenu.GetButtonW(name): return None`). With the
object path leaving `_buttons` stale, a ship whose Hail button was removed --
sensor continuity's lost track -- could never get it back on
re-identification: GetButtonW still "found" the deleted button.
"""
from engine.appc.characters import STButton_CreateW, STMenu_CreateW


def test_delete_child_by_object_drops_the_button_lookup():
    menu = STMenu_CreateW("Hail")
    a = STButton_CreateW("Vagabond")
    b = STButton_CreateW("Haven")
    menu.AddChild(a)
    menu.AddChild(b)
    menu.DeleteChild(a)
    assert menu.GetButtonW("Vagabond") is None
    assert menu.GetButtonW("Haven") is b
    assert a not in menu._children and b in menu._children


def test_delete_child_by_object_drops_the_submenu_lookup():
    menu = STMenu_CreateW("Hail")
    fleet = STMenu_CreateW("Wingman")
    menu.AddChild(fleet)
    menu.DeleteChild(fleet)
    assert menu.GetSubmenuW("Wingman") is None
    assert fleet not in menu._children


def test_delete_child_by_object_keeps_a_different_object_under_the_same_label():
    """AddChild overwrites `_buttons[label]` with the newest button; deleting
    the OLDER, shadowed one must not drop the newer one's lookup."""
    menu = STMenu_CreateW("Hail")
    old = STButton_CreateW("Drone")
    new = STButton_CreateW("Drone")
    menu.AddChild(old)
    menu.AddChild(new)
    menu.DeleteChild(old)
    assert menu.GetButtonW("Drone") is new
