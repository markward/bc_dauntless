"""TGPane.IsCompletelyVisible() — RE-faithful 'self AND ancestor chain' visibility.

See docs/superpowers/specs/2026-07-17-iscompletelyvisible-faithful-design.md.
"""
from engine.appc.tg_ui.widgets import TGPane


def test_lone_visible_pane_is_completely_visible():
    p = TGPane()
    assert p.IsCompletelyVisible() == 1


def test_lone_hidden_pane_is_not_completely_visible():
    p = TGPane()
    p.SetNotVisible()
    assert p.IsCompletelyVisible() == 0


def test_hidden_ancestor_hides_visible_child():
    parent = TGPane()
    child = TGPane()
    parent.AddChild(child)
    assert child.IsCompletelyVisible() == 1
    parent.SetNotVisible()
    assert child.IsCompletelyVisible() == 0        # ancestor hidden


def test_visible_chain_is_completely_visible():
    grand = TGPane()
    parent = TGPane()
    child = TGPane()
    grand.AddChild(parent)
    parent.AddChild(child)
    assert child.IsCompletelyVisible() == 1


def test_deletechild_clears_parent_backref():
    parent = TGPane()
    child = TGPane()
    parent.AddChild(child)
    parent.SetNotVisible()
    parent.DeleteChild(child)
    # Orphaned child no longer inherits the hidden parent's state.
    assert child.IsCompletelyVisible() == 1


def test_returns_int_not_bool():
    p = TGPane()
    assert type(p.IsCompletelyVisible()) is int
