"""GetOrderString must fall back off a DISABLED tactic to the first enabled one.

BC's Tactics/Maneuvers availability is derived from the g_dAIs table: when the
selected combination has no AI entry, UpdateOrderMenus disables the offending
button (TacticalMenuHandlers.py:1552-1575) while the state index keeps pointing
at it. GetOrderString (:1896) is the recovery path -- it checks
``pMenu.GetNthChild(iIndex)`` and, if that button is disabled, walks from the
first child and returns the first ENABLED order instead.

STCharacterMenu (the class of g_pTacticsStatusUIMenu / g_pManeuversStatusUIMenu,
built by CreateOrderMenu:445) had no GetNthChild, so the lookup returned a
truthy _Stub, ``not pButton.IsEnabled()`` was False, and the fallback never ran
-- GetTactic() reported the disabled tactic.

Why that is player-visible: g_dAIs carries an (order, None, None) catch-all for
OrderDefense/OrderStop/OrderStopSelect ONLY. For the two attack orders there is
none, so a stale disabled tactic makes ChooseAIFromOrders return (None, None)
and StartPlayerAI bail at :1838 -- the tactical officer never engages. The
concrete hole used below is (OrderDestroy, TacticFore, ManeuverSeparate), absent
from g_dAIs while TacticFore itself is a perfectly valid tactic.
"""
import pytest

import App


@pytest.fixture
def tmh():
    """The real SDK TacticalMenuHandlers with a Tactics menu built the way
    CreateOrderMenu builds it, and a Tactical-controlled player ship."""
    import Bridge.TacticalMenuHandlers as tmh
    import MissionLib
    from engine.appc.characters import STButton
    from engine.appc.tg_ui.st_widgets import STCharacterMenu_CreateW

    MissionLib.g_sPlayerShipController = "Tactical"

    menu = STCharacterMenu_CreateW("Tactics")
    for label, _sub_type in tmh.g_lTactics:
        menu.AddChild(STButton(label))
    tmh.g_pTacticsStatusUIMenu = menu
    return tmh


def _tactic_button(tmh, name):
    for button in tmh.g_pTacticsStatusUIMenu._children:
        if button.GetLabel() == name:
            return button
    raise AssertionError("no %r button" % name)


def test_enabled_tactic_is_reported_as_is(tmh):
    # Baseline: nothing disabled, so the fallback must NOT engage and the
    # indexed tactic wins.
    tmh.g_iTacticState = tmh.g_lTactics.index(("TacticFore", tmh.EST_TACTIC_FORE))
    assert tmh.GetTactic() == "TacticFore"


def test_disabled_tactic_falls_back_to_first_enabled(tmh):
    # (OrderDestroy, TacticFore, ManeuverSeparate) has no g_dAIs entry, so
    # UpdateOrderMenus disables Fore while g_iTacticState still indexes it.
    tmh.g_iTacticState = tmh.g_lTactics.index(("TacticFore", tmh.EST_TACTIC_FORE))
    _tactic_button(tmh, "TacticFore").SetDisabled()
    assert tmh.GetTactic() == "TacticAtWill"


def test_fallback_skips_leading_disabled_tactics(tmh):
    # The walk starts at GetFirstChild, so it must step over disabled entries
    # rather than returning the first child outright.
    tmh.g_iTacticState = tmh.g_lTactics.index(("TacticFore", tmh.EST_TACTIC_FORE))
    for name in ("TacticFore", "TacticAtWill", "TacticLeft"):
        _tactic_button(tmh, name).SetDisabled()
    assert tmh.GetTactic() == "TacticRight"


def test_chosen_ai_stays_resolvable_after_the_fallback(tmh):
    # The point of the fallback: the triple ChooseAIFromOrders receives must
    # exist in g_dAIs. Without it the attack order resolves to (None, None)
    # and StartPlayerAI bails, so the tactical officer never engages.
    tmh.g_iTacticState = tmh.g_lTactics.index(("TacticFore", tmh.EST_TACTIC_FORE))
    _tactic_button(tmh, "TacticFore").SetDisabled()
    module, params = tmh.ChooseAIFromOrders(
        "OrderDestroy", tmh.GetTactic(), "ManeuverSeparate")
    assert module is not None and params is not None


def test_the_hole_this_guards_is_real(tmh):
    # Pins the premise rather than trusting it: the combination really is
    # absent from g_dAIs, and the attack orders really have no (order, None,
    # None) catch-all to soften it.
    assert ("OrderDestroy", "TacticFore", "ManeuverSeparate") not in tmh.g_dAIs
    assert ("OrderDestroy", None, None) not in tmh.g_dAIs
    assert tmh.ChooseAIFromOrders(
        "OrderDestroy", "TacticFore", "ManeuverSeparate") == (None, None)
