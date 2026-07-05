"""Bridge-officer speech through the LIVE boot path (QuickBattle, host-level).

The 2026-07-05 live-silence bug survived a green integration suite twice:
(1) the unit/integration tests configured officers directly while the live
QuickBattle creates the player at battle start, and (2) the tests popped the
Bridge.*CharacterHandlers stub modules while the live harness kept them, so
AttachMenuToHelm was a silent no-op in the game only. This test closes both
seams: it drives the REAL SDK QuickBattle cascade under tools/mission_harness
(the runtime loader — stub list and AST transforms included), runs the SAME
engine.bridge_officers.wire_after_mission_load the host's post-load hook
runs, starts the battle for real, and clicks through the REAL CEF panel
dispatch. Speech is asserted at the bus with real TGL resolution — text AND
voice wav — because an emit with an unresolvable line is live silence.
"""
import json

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: F401


def _find(node, label):
    if node["label"] == label:
        return node
    for child in node.get("children", []):
        found = _find(child, label)
        if found is not None:
            return found
    return None


def _start_battle(hl, controller):
    import App
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)          # past the 2s preload sequence
    hl._fire_pending_preload_done()        # -> StartSimulation2 -> RecreatePlayer


def _snapshot(panel):
    # render_payload dedupes unchanged payloads (returns None) — snapshot once
    # and reuse the widget-id map for every click.
    payload = panel.render_payload()
    assert payload is not None
    return json.loads(payload[len("setCrewMenus("):-2])


def _click(panel, data, root_label, button_label):
    root = next(m for m in data["menus"] if m["label"] == root_label)
    node = _find(root, button_label)
    assert node is not None, (button_label, root)
    assert panel.dispatch_event("click:%d" % node["id"])


def test_quickbattle_helm_clicks_speak_through_live_path(monkeypatch):
    import App
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()

    from engine.bridge_officers import wire_after_mission_load
    wire_after_mission_load()              # what _after_mission_loaded runs

    _start_battle(hl, controller)
    import QuickBattle.QuickBattle as QB
    assert QB.bInSimulation == 1

    # RecreatePlayer ran DetachCrewMenus + created a NEW player ship;
    # ET_SET_PLAYER -> OnSetPlayer must have re-wired Kiska onto the real
    # TCW helm menu (this is the registration the auto-vivified-orphan
    # GetMenu bug crashed, and the stubbed HelmCharacterHandlers no-opped).
    from engine.appc.windows import TacticalControlWindow
    helm = TacticalControlWindow.GetInstance().FindMenu("Helm")
    assert helm._handlers.get(App.ET_REPORT) == \
        ["Bridge.HelmCharacterHandlers.Report"]
    assert helm._handlers.get(App.ET_ALL_STOP, []).count(
        "Bridge.HelmCharacterHandlers.AllStop") == 1

    # Real speech capture: bus level, AFTER TGL resolution — both subtitle
    # text and the voice wav must resolve or the click is live silence.
    from engine.appc import crew_speech
    spoken = []
    monkeypatch.setattr(
        crew_speech.bus(), "speak",
        lambda speaker, text, wav, priority, now=None:
            spoken.append((speaker, text, wav)) or 1.0)

    from engine.ui.crew_menu_panel import CrewMenuPanel
    panel = CrewMenuPanel()
    data = _snapshot(panel)

    _click(panel, data, "Helm", "All Stop")
    assert spoken and spoken[0][0] == "Kiska", spoken
    assert spoken[0][1] and spoken[0][2], spoken   # text + voice wav resolved

    spoken.clear()
    _click(panel, data, "Helm", "Report")          # the SDK Communicate button
    assert any(s == "Kiska" and text and wav
               for s, text, wav in spoken), spoken
    # The engine-status report replaced the "nothing to add" fallback.
    assert not any("nothing to add" in (text or "").lower()
                   for _, text, _ in spoken), spoken
