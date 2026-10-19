"""Tests for engine.dev_character_viewscreen — the developer-only "put any SDK
character on the viewscreen" shortcut. The catalogue is read from the SDK tree
(character scripts + the missions that stage them), so these tests build a tiny
fake tree rather than relying on the installed SDK."""
import sys
import types

import pytest

from engine import dev_character_viewscreen as dcv


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_CHARACTER = '''
def CreateCharacter(pSet):
\tpX = App.CharacterClass_Create("a", "b")
\tpSet.AddObjectToSet(pX, "%s")
\tpX.SetCharacterName("%s")
%s\treturn pX

def ConfigureForGalaxy(pX):
\tpX.SetLocation("DBCommander")
'''


def _character(object_name, character_name=None, location=None):
    loc = '\tpX.SetLocation("%s")\n' % location if location else ""
    return _CHARACTER % (object_name, character_name or object_name, loc)


@pytest.fixture
def sdk(tmp_path):
    _write(tmp_path, "Bridge/Characters/Kessok.py", _character("Kessok", location="KessokSeated"))
    _write(tmp_path, "Bridge/Characters/Admiral_Liu.py", _character("Liu"))
    # The crew add themselves under their station name.
    _write(tmp_path, "Bridge/Characters/Saffi.py", _character("XO", "Saffi"))
    # Not a character: no CreateCharacter.
    _write(tmp_path, "Bridge/Characters/CharacterPaths.py", "g_pcRootPath = 'x'\n")
    _write(tmp_path, "Maelstrom/Episode8/E8M1/E8M1.py",
           'MissionLib.SetupBridgeSet("KessokSet", "data/Models/Sets/Kessok/kessokbridge.nif")\n'
           'MissionLib.SetupCharacter("Bridge.Characters.Kessok", "KessokSet")\n')
    # Liu appears on two sets; the more common one wins.
    for i in range(2):
        _write(tmp_path, "Maelstrom/M%d.py" % i,
               'MissionLib.SetupBridgeSet("StarbaseSet", "data/Models/Sets/StarbaseControl/starbasecontrolRM.nif")\n'
               'MissionLib.SetupCharacter("Bridge.Characters.Admiral_Liu", "StarbaseSet")\n')
    _write(tmp_path, "Maelstrom/M9.py",
           'MissionLib.SetupBridgeSet("LiuSet", "data/Models/Sets/Other/other.nif")\n'
           'MissionLib.SetupCharacter("Bridge.Characters.Admiral_Liu", "LiuSet")\n')
    return tmp_path


def test_catalogue_lists_only_character_scripts_by_character_name(sdk):
    names = [e.name for e in dcv.build_catalogue(sdk)]
    assert names == ["Kessok", "Liu", "Saffi"]


def test_entry_keeps_the_set_object_name_viewscreen_on_looks_up(sdk):
    saffi = {e.name: e for e in dcv.build_catalogue(sdk)}["Saffi"]
    assert saffi.object_name == "XO"


def test_catalogue_uses_the_set_an_sdk_mission_stages_the_character_on(sdk):
    kessok = {e.name: e for e in dcv.build_catalogue(sdk)}["Kessok"]
    assert kessok.module == "Bridge.Characters.Kessok"
    assert kessok.set_name == "KessokSet"
    assert kessok.set_model == "data/Models/Sets/Kessok/kessokbridge.nif"


def test_catalogue_prefers_the_most_used_set(sdk):
    liu = {e.name: e for e in dcv.build_catalogue(sdk)}["Liu"]
    assert liu.set_name == "StarbaseSet"


def test_character_no_mission_stages_falls_back_to_the_galaxy_bridge(sdk):
    saffi = {e.name: e for e in dcv.build_catalogue(sdk)}["Saffi"]
    assert (saffi.set_name, saffi.set_model) == dcv.FALLBACK_SET


def test_unplaced_character_on_the_fallback_set_is_seated(sdk):
    # Saffi's CreateCharacter sets no location (ConfigureForGalaxy does, later).
    saffi = {e.name: e for e in dcv.build_catalogue(sdk)}["Saffi"]
    assert saffi.location == dcv.FALLBACK_LOCATION


def test_character_that_places_itself_is_left_alone(sdk):
    entries = {e.name: e for e in dcv.build_catalogue(sdk)}
    assert entries["Kessok"].location is None
    # Liu sets no location but is on a mission set, which the mission places.
    assert entries["Liu"].location is None


@pytest.fixture
def fake_missionlib(monkeypatch):
    calls = []
    ml = types.ModuleType("MissionLib")
    ml.g_bViewscreenOn = 0
    ml.ViewscreenOff = lambda *a: calls.append(("off",) + a)
    ml.SetupBridgeSet = lambda *a: calls.append(("set",) + a) or object()
    ml.SetupCharacter = lambda *a: calls.append(("char",) + a) or object()
    ml.ViewscreenOn = lambda *a: calls.append(("on",) + a) or 1
    monkeypatch.setitem(sys.modules, "MissionLib", ml)
    return ml, calls


def test_show_stages_the_character_the_way_a_mission_does(fake_missionlib):
    _, calls = fake_missionlib
    entry = dcv.CharacterEntry("Kessok", "Bridge.Characters.Kessok",
                               "KessokSet", "data/Models/Sets/Kessok/kessokbridge.nif")
    assert dcv.show(entry) is True
    assert calls == [
        ("set", "KessokSet", "data/Models/Sets/Kessok/kessokbridge.nif"),
        ("char", "Bridge.Characters.Kessok", "KessokSet"),
        ("on", None, "KessokSet", "Kessok", 0, 0, 1),
    ]


def test_show_turns_an_active_viewscreen_off_first(fake_missionlib):
    ml, calls = fake_missionlib
    ml.g_bViewscreenOn = 1
    entry = dcv.CharacterEntry("Liu", "Bridge.Characters.Admiral_Liu",
                               "StarbaseSet", "x.nif")
    dcv.show(entry)
    assert calls[0] == ("off", None, 0)


def test_show_seats_a_character_that_needs_placing(fake_missionlib):
    ml, calls = fake_missionlib
    placed = []
    character = types.SimpleNamespace(SetLocation=placed.append)
    ml.SetupCharacter = lambda *a: calls.append(("char",) + a) or character
    entry = dcv.CharacterEntry("Saffi", "Bridge.Characters.Saffi", *dcv.FALLBACK_SET,
                               object_name="XO", location=dcv.FALLBACK_LOCATION)
    dcv.show(entry)
    assert placed == [dcv.FALLBACK_LOCATION]
    assert calls[-1] == ("on", None, dcv.FALLBACK_SET[0], "XO", 0, 0, 1)


def test_show_reports_failure_when_the_character_is_not_created(fake_missionlib):
    ml, calls = fake_missionlib
    ml.SetupCharacter = lambda *a: None
    entry = dcv.CharacterEntry("Liu", "Bridge.Characters.Admiral_Liu",
                               "StarbaseSet", "x.nif")
    assert dcv.show(entry) is False
    assert not any(c[0] == "on" for c in calls)


def test_hide_turns_the_viewscreen_off(fake_missionlib):
    ml, calls = fake_missionlib
    ml.g_bViewscreenOn = 1
    dcv.hide()
    assert calls == [("off", None, 1)]


# ---- Developer Options "Characters" tab ----------------------------------

@pytest.fixture
def panel(monkeypatch):
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    entries = [dcv.CharacterEntry("Kessok", "Bridge.Characters.Kessok", "KessokSet", "k.nif"),
               dcv.CharacterEntry("Saffi", "Bridge.Characters.Saffi", *dcv.FALLBACK_SET)]
    monkeypatch.setattr(dcv, "catalogue", lambda: entries)
    shown = []
    monkeypatch.setattr(dcv, "show", lambda e: shown.append(e.name) or True)
    monkeypatch.setattr(dcv, "hide", lambda: shown.append("<off>"))
    return DeveloperOptionsPanel(), shown


def _body(payload):
    import json
    return json.loads(payload[len("setDeveloperOptions("):-2])


def test_characters_tab_lists_every_catalogue_character(panel):
    p, _ = panel
    assert "characters" in [tid for tid, _ in p._tabs]
    p.open()
    p.dispatch_event("tab:characters")
    body = _body(p.render_payload())
    assert body["characters"] == ["Kessok", "Saffi"]


def test_show_character_action_shows_it_and_reports_it(panel):
    p, shown = panel
    p.open()
    p.render_payload()
    assert p.dispatch_event("action:show_character:Kessok") is True
    assert shown == ["Kessok"]
    body = _body(p.render_payload())
    assert body["viewscreen_character"] == "Kessok"


def test_unknown_character_is_not_dispatched(panel):
    p, shown = panel
    assert p.dispatch_event("action:show_character:Nobody") is False
    assert shown == []


def test_viewscreen_off_action_clears_the_shown_character(panel):
    p, shown = panel
    p.open()
    p.dispatch_event("action:show_character:Kessok")
    p.dispatch_event("action:viewscreen_off")
    assert shown == ["Kessok", "<off>"]
    assert _body(p.render_payload())["viewscreen_character"] is None
