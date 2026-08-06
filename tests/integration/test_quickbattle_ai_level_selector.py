"""QuickBattle's AI Level radio (Low/Medium/High) — the chosen state must
actually move when SetAI runs.

QuickBattle builds this selector as a bare STSubPane (QuickBattle.py:1587,
GenerateAIMenu) rather than an STMenu, then drives the radio through
``g_pAIMenu.GetButtonW(label).SetChosen(n)`` (:2545-2555 SetAI, :2485-2487
ResetShipList). STSubPane extends TGPane, which had no label lookup, so
GetButtonW fell through TGObject.__getattr__ to a truthy _Stub and every
SetChosen landed on the stub instead of the button — the radio stayed on
whatever GenerateAIMenu chose at build time. docs/stub_heatmap.md ranked it
642 hits / 76 of 199 runs, paired 1:1 with a GetButtonW.SetChosen breadcrumb.

This drives the REAL SDK module, not a reimplementation of its logic.
"""
import pytest

import App


@pytest.fixture
def qb():
    """The real SDK QuickBattle module with just enough globals for
    GenerateAIMenu: a localization database, a parent pane, and the XO that
    the buttons' TGFloatEvents are addressed to."""
    import QuickBattle.QuickBattle as QuickBattle
    from engine.appc.characters import CharacterClass
    from engine.appc.tg_ui.widgets import TGPane

    QuickBattle.g_pMissionDatabase = App.g_kLocalizationManager.Load(
        "data/TGL/QuickBattle.tgl")
    QuickBattle.g_pShipsPane = TGPane()
    QuickBattle.g_pXO = CharacterClass()
    QuickBattle.GenerateAIMenu()
    return QuickBattle


def _chosen(qb, key):
    button = qb.g_pAIMenu.GetButtonW(qb.g_pMissionDatabase.GetString(key))
    assert button is not None, "no %r button on the AI Level subpane" % key
    return button.IsChosen()


def test_generate_ai_menu_starts_on_medium(qb):
    # GenerateAIMenu calls pMedium.SetChosen(1) on the button object directly
    # (QuickBattle.py:1601), so this half always worked — it is the baseline
    # the SetAI test moves away from.
    assert (_chosen(qb, "Low"), _chosen(qb, "Medium"), _chosen(qb, "High")) == (0, 1, 0)


def test_set_ai_high_moves_the_chosen_flag_off_medium(qb):
    qb.SetAI(qb.AI_HIGH)
    assert (_chosen(qb, "Low"), _chosen(qb, "Medium"), _chosen(qb, "High")) == (0, 0, 1)


def test_set_ai_low_moves_the_chosen_flag_off_medium(qb):
    qb.SetAI(qb.AI_LOW)
    assert (_chosen(qb, "Low"), _chosen(qb, "Medium"), _chosen(qb, "High")) == (1, 0, 0)


def test_set_ai_records_the_selected_level(qb):
    # The gameplay half of SetAI (the module global) never depended on
    # GetButtonW, so it must keep working — this pins that the fix did not
    # disturb it.
    qb.SetAI(qb.AI_HIGH)
    assert qb.g_iSelectedAILevel == qb.AI_HIGH
