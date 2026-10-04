"""ModsScreenPanel: every decision the Mods screen makes. The page renders
the payload and reports clicks; it holds no logic (spec §1)."""
import json
from urllib.parse import quote

import pytest

from engine.ship_catalog.catalog import ShipRecord
from engine.ship_catalog.gate_writer import GateWriteError
from engine.ui.mods_screen_panel import ModsScreenPanel


def rec(ship_id, mod="DCMPv2", values=None, missing=None, sub_menu=None, player=True,
        variant_of=None, class_default=False, name=None):
    values = values or {}
    if missing is None:
        missing = tuple(k for k in ("era", "role", "playable", "title", "species") if k not in values)
    return ShipRecord(ship_id=ship_id, source="mod", mod=mod, shipdef_attr=ship_id,
                      icon="DCMPDefiantClass", values=values, variant_of=variant_of,
                      class_default=class_default, missing=missing, errors=(),
                      raw_name=name or ship_id[4:], raw_race="Fed", sub_menu=sub_menu,
                      player_menu=player)


SPECIES = ["Federation", "Klingon"]
_STOCK_VALUES = {"role": "tactical", "species": "Federation", "era": ("DS9", "DS9"), "playable": True}
STOCK = {"Galaxy": dict(_STOCK_VALUES), "Nebula": dict(_STOCK_VALUES)}


def gate(*editable, readonly=(), writer=None):
    return ModsScreenPanel("gate", list(editable), list(readonly), species=SPECIES,
                           stock_classes=STOCK, writer=writer)


def payload(p):
    s = p.render_payload() or p._last_pushed
    return json.loads(s[len("setModsScreen("):-2])


def row(p, f):
    return next(r for r in payload(p)["rows"] if r["file"] == f)


def ev(p, *parts):
    assert p.dispatch_event(":".join(parts))


def test_prefills_from_suggestions_and_era_stays_blank():
    p = gate(rec("DCMPAvenger", sub_menu="Defiant Class"))
    r = row(p, "DCMPAvenger")
    assert (r["title"], r["species"], r["role"], r["playable"], r["variant_of"]) == (
        "Avenger", "Federation", "tactical", True, "Defiant")
    assert r["era"] is None and r["missing"] == ["era"]
    assert payload(p)["can_continue"] is False


def test_row_carries_a_resolved_icon_url_never_raising_on_a_missing_icon():
    # rec()'s fixture icon ("DCMPDefiantClass") has no on-disk TGA in the
    # test environment -- the row must still render, with icon_url "".
    p = gate(rec("DCMPAvenger"))
    assert row(p, "DCMPAvenger")["icon_url"] == ""


def test_set_era_from_and_to_drag_each_other():
    p = gate(rec("DCMPAvenger"))
    ev(p, "set", "DCMPAvenger", "era-from", "DS9")
    assert row(p, "DCMPAvenger")["era"] == "DS9-DS9"
    ev(p, "set", "DCMPAvenger", "era-to", "TNG")
    assert row(p, "DCMPAvenger")["era"] == "TNG-TNG"
    ev(p, "set", "DCMPAvenger", "era-to", "PIC")
    assert row(p, "DCMPAvenger")["era"] == "TNG-PIC"
    ev(p, "set", "DCMPAvenger", "era", "all")
    assert row(p, "DCMPAvenger")["era"] == "all"


def test_ticked_rows_all_take_an_edit():
    p = gate(rec("DCMPA"), rec("DCMPB"), rec("DCMPC"))
    ev(p, "tick", "DCMPA"); ev(p, "tick", "DCMPB")
    ev(p, "set", "DCMPA", "role", "station")
    assert [row(p, f)["role"] for f in ("DCMPA", "DCMPB", "DCMPC")] == ["station", "station", "tactical"]
    assert payload(p)["ticked"] == 2


def test_edit_on_unticked_row_touches_only_that_row():
    p = gate(rec("DCMPA"), rec("DCMPB"))
    ev(p, "tick", "DCMPA")
    ev(p, "set", "DCMPB", "species", "Klingon")
    assert row(p, "DCMPA")["species"] == "Federation" and row(p, "DCMPB")["species"] == "Klingon"


def test_tick_mod_ticks_only_editable_rows():
    ro = rec("DCMPDone", values={"title": "Done", "era": ("DS9", "DS9"), "role": "tactical",
                                 "species": "Federation", "playable": True}, missing=())
    p = gate(rec("DCMPA"), readonly=[ro])
    ev(p, "tick-mod", "DCMPv2")
    assert row(p, "DCMPA")["ticked"] and not row(p, "DCMPDone")["ticked"]
    assert row(p, "DCMPDone")["editable"] is False
    assert p.dispatch_event("set:DCMPDone:role:station") is True
    assert row(p, "DCMPDone")["role"] == "tactical"


def test_typed_values_are_url_decoded():
    p = gate(rec("DCMPA"))
    ev(p, "set", "DCMPA", "title", quote("USS Avenger: Refit"))
    assert row(p, "DCMPA")["title"] == "USS Avenger: Refit"


def test_star_auto_picks_title_match_and_moves_on_click():
    p = gate(rec("DCMPAvenger", sub_menu="Defiant Class"),
             rec("DCMPDefiant", sub_menu="Defiant Class"))
    assert row(p, "DCMPDefiant")["is_default"] and not row(p, "DCMPAvenger")["is_default"]
    ev(p, "star", "DCMPAvenger")
    assert row(p, "DCMPAvenger")["is_default"] and not row(p, "DCMPDefiant")["is_default"]


def test_star_spans_mods():
    p = gate(rec("A", mod="ModA", variant_of="K", name="Kay"),
             rec("B", mod="ModB", variant_of="k", name="Bee"))
    assert [row(p, f)["is_default"] for f in ("A", "B")] == [True, False]


def test_stock_class_has_no_star():
    p = gate(rec("LCvoyagerZZ", mod="LC", variant_of="Nebula"))
    r = row(p, "LCvoyagerZZ")
    assert r["stock_class"] is True and r["is_default"] is False


def test_class_conflict_blocks_continue_and_names_it():
    p = gate(rec("A", variant_of="K"), rec("B", variant_of="K"))
    for f in ("A", "B"):
        ev(p, "set", f, "era", "all")
    ev(p, "set", "B", "role", "station")
    assert payload(p)["can_continue"] is False
    assert "role" in row(p, "A")["conflict"]


def test_continue_writes_complete_rows_and_sets_outcome():
    written = []
    p = gate(rec("DCMPA", sub_menu="Defiant Class"), writer=lambda rows: written.extend(rows))
    ev(p, "set", "DCMPA", "era", "all")
    ev(p, "continue")
    assert p.outcome == "continue"
    (w,) = written
    assert (w.mod, w.ship_id, w.attr) == ("DCMPv2", "DCMPA", "DCMPA")
    assert w.answers == {"title": "A", "species": "Federation", "era": ("all",),
                         "role": "tactical", "playable": True, "variant_of": "Defiant",
                         "class_default": True}


def test_continue_while_incomplete_is_inert():
    p = gate(rec("DCMPA"), writer=lambda rows: pytest.fail("must not write"))
    ev(p, "continue")
    assert p.outcome is None


def test_writer_error_is_shown_and_skip_still_works():
    def boom(rows):
        raise GateWriteError("/mods/x/zz_Dauntless_DCMPA.py: Permission denied")
    p = gate(rec("DCMPA"), writer=boom)
    ev(p, "set", "DCMPA", "era", "all")
    ev(p, "continue")
    assert p.outcome is None and "Permission denied" in payload(p)["error"]
    ev(p, "skip")
    assert p.outcome == "skip"


def test_an_edit_clears_the_error_line():
    p = gate(rec("DCMPA"), writer=lambda rows: None)
    p._error = "Some answers did not take effect: DCMPA: era"
    ev(p, "set", "DCMPA", "era", "all")
    assert payload(p)["error"] == ""


def test_continue_clears_a_stale_error_before_writing():
    calls = []

    def flaky(rows):
        calls.append(rows)
        if len(calls) == 1:
            raise GateWriteError("first: Permission denied")
    p = gate(rec("DCMPA"), writer=flaky)
    ev(p, "set", "DCMPA", "era", "all")
    ev(p, "continue")
    assert "Permission denied" in payload(p)["error"]
    ev(p, "continue")
    assert p.outcome == "continue" and payload(p)["error"] == ""


def test_home_mode_is_read_only_with_play():
    ro = rec("DCMPDone", values={"title": "Done", "era": ("DS9", "DS9"), "role": "tactical",
                                 "species": "Federation", "playable": True}, missing=())
    p = ModsScreenPanel("home", [], [ro], species=SPECIES, stock_classes=STOCK)
    assert payload(p)["mode"] == "home" and payload(p)["header"] == "Mod Ships"
    p.handle_key_esc()
    assert p.outcome == "play"


def test_esc_does_nothing_in_gate_mode():
    p = gate(rec("DCMPA"))
    p.handle_key_esc()
    assert p.outcome is None


def test_render_payload_is_diff_cached_and_invalidate_re_emits():
    p = gate(rec("DCMPA"))
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() is not None


def test_quit_and_teardown():
    p = gate(rec("DCMPA"))
    ev(p, "quit")
    assert p.outcome == "quit" and p.teardown_script == "setModsScreen(null);"


def _locked_class_rows():
    # Non-matching read-only title on purpose: neither member's title equals
    # or contains the class word "Defiant", so a correct fix must rely on
    # the read-only member's own class_default flag, not a title-match
    # fallback that would coincidentally pick the right row anyway.
    ro = rec("ADefiant", mod="ModA", variant_of="Defiant", class_default=True,
             values={"title": "Prime", "era": ("DS9", "DS9"), "role": "tactical",
                     "species": "Federation", "playable": True}, missing=())
    editable = rec("BValiant", mod="ModB", variant_of="Defiant", name="Valiant")
    return editable, ro


def test_readonly_locked_default_blocks_star():
    editable, ro = _locked_class_rows()
    p = gate(editable, readonly=[ro])
    assert row(p, "ADefiant")["is_default"] and not row(p, "BValiant")["is_default"]
    assert row(p, "BValiant")["star_locked"] is True
    ev(p, "star", "BValiant")
    assert row(p, "ADefiant")["is_default"] and not row(p, "BValiant")["is_default"]


def test_readonly_locked_default_writes_false_for_editable_member():
    editable, ro = _locked_class_rows()
    written = []
    p = gate(editable, readonly=[ro], writer=lambda rows: written.extend(rows))
    ev(p, "set", "BValiant", "era", "all")
    ev(p, "continue")
    assert p.outcome == "continue"
    (w,) = written
    assert w.answers["class_default"] is False


def test_stock_class_role_conflict_blocks_continue_and_clears():
    p = gate(rec("LCvoyagerZZ", mod="LC", variant_of="Nebula"))
    ev(p, "set", "LCvoyagerZZ", "era", "all")
    ev(p, "set", "LCvoyagerZZ", "role", "station")
    assert "role" in row(p, "LCvoyagerZZ")["conflict"]
    assert payload(p)["can_continue"] is False
    ev(p, "set", "LCvoyagerZZ", "role", "tactical")
    assert row(p, "LCvoyagerZZ")["conflict"] == ""
    assert payload(p)["can_continue"] is True
