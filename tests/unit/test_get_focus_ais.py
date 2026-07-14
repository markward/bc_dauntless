"""GetFocusAIs returns the AIs on the current focus path.

AI/Preprocessors.py:2230 (FelixReportStatus.Update) calls
self.pCodeAI.GetFocusAIs(). We didn't define it, and ArtificialIntelligence is a
plain class — so it raised AttributeError straight out of the AI tick. All 28
AI/Player trees root a FelixReportStatus.
"""
from engine.appc.ai import PlainAI_Create, PriorityListAI_Create


def test_get_focus_ais_returns_only_the_focused_nodes_in_tree_order():
    root = PriorityListAI_Create(None, "root")
    a = PlainAI_Create(None, "a")
    b = PlainAI_Create(None, "b")
    root.AddAI(a, 0)
    root.AddAI(b, 1)

    assert root.GetFocusAIs() == []

    a._has_focus = True
    assert root.GetFocusAIs() == [a]

    b._has_focus = True
    assert root.GetFocusAIs() == [a, b]


def test_get_focus_ais_includes_self_when_self_has_focus():
    root = PriorityListAI_Create(None, "root")
    root._has_focus = True
    assert root.GetFocusAIs() == [root]
