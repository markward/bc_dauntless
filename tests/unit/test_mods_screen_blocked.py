"""The Mods screen lists mods Dauntless refused to load (spec 2026-10-16 §5.3)."""
import json

from engine import mod_policy, mods
from engine.ui import mods_screen
from engine.ui.mods_screen_panel import ModsScreenPanel


def _payload(panel):
    script = panel.render_payload()
    return json.loads(script[len("setModsScreen("):-2])


def test_panel_payload_carries_blocked_mods():
    panel = ModsScreenPanel("home", [], [], species=[], stock_classes={},
                            blocked=[("NanoFX_2.0 BETA", mod_policy.REASON_NANOFX_BLOCKED)])
    assert _payload(panel)["blocked"] == [
        {"name": "NanoFX_2.0 BETA", "reason": mod_policy.REASON_NANOFX_BLOCKED}]


def test_panel_payload_blocked_defaults_empty():
    panel = ModsScreenPanel("home", [], [], species=[], stock_classes={})
    assert _payload(panel)["blocked"] == []


def test_build_panel_reads_blocked_from_the_live_index(monkeypatch):
    st = mods.ModStatus(name="NanoFX_2.0 BETA", content_root=None,
                        blocked=mod_policy.REASON_NANOFX_BLOCKED)
    monkeypatch.setattr(mods, "current", lambda: mods.ModIndex(files={}, mods=[st]))
    panel = mods_screen._build_panel("home")
    assert _payload(panel)["blocked"][0]["name"] == "NanoFX_2.0 BETA"
