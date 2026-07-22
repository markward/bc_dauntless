import json
from engine.appc.characters import (
    CharacterClass, CharacterClass_SetCurrentToolTipOwner,
)
from engine.ui.character_tooltip_panel import CharacterTooltipPanel


def _owner_with_rows():
    # NOTE: intentionally NOT a real CharacterStatus.tgl key ("Helm" itself IS
    # one in the shipped game data -- it resolves to "Ensign Kiska LoMar,
    # Helm" -- which would make this test environment-dependent on whether
    # game/ is installed). This name exercises the miss->raw-name fallback
    # deterministically; TGL hit/miss behaviour is TGLocalizationDatabase's
    # own contract (tests/unit/test_localization.py), not this panel's.
    ch = CharacterClass()
    ch.SetCharacterName("TestOfficerXYZ")
    ch.SetStatus("Waiting", 0)
    ch.SetStatus("5 : 120 kph", 1)
    CharacterClass_SetCurrentToolTipOwner(ch)
    return ch


def test_snapshot_hidden_when_no_owner():
    CharacterClass_SetCurrentToolTipOwner(None)
    p = CharacterTooltipPanel()
    assert p.snapshot()["visible"] is False


def test_snapshot_shows_owner_rows_in_key_order():
    _owner_with_rows()
    p = CharacterTooltipPanel()
    snap = p.snapshot()
    assert snap["visible"] is True
    assert snap["title"] == "TestOfficerXYZ"
    assert snap["rows"] == ["Waiting", "5 : 120 kph"]
    CharacterClass_SetCurrentToolTipOwner(None)


def test_render_payload_diff_gated():
    _owner_with_rows()
    p = CharacterTooltipPanel()
    first = p.render_payload()
    assert first is not None and first.startswith("setCharacterTooltip(")
    assert p.render_payload() is None          # unchanged -> no re-emit
    CharacterClass_SetCurrentToolTipOwner(None)


def test_name_is_routing_prefix():
    assert CharacterTooltipPanel().name == "character-tooltip"
