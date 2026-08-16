"""Dev-only force for E1M1's PlayedTutorial gate.

E1M1.CrewIntros:1954 only builds the skip banner + keyboard handler when
g_kVarManager's global PlayedTutorial == 1.0, which BC sets at the END of the
opening (E1M1.SaveTheGame:2659) and persists. Our TGVarManager is in-memory and
only round-trips through savegames, so a cold launch always reads 0.0.

Stopgap until persistent saves land -- see docs/engine/e1m1-skip-intro.md.
"""
import App
from engine import dev_mode, dev_tutorial_flag


def _read():
    return App.g_kVarManager.GetFloatVariable("global", "PlayedTutorial")


def test_flag_is_forced_when_developer_mode_is_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 0.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert _read() == 1.0


def test_flag_is_untouched_when_developer_mode_is_off(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 0.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert _read() == 0.0


def test_an_existing_true_flag_is_not_clobbered_in_production(monkeypatch):
    # A savegame that legitimately carries the flag must survive with dev off.
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 1.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert _read() == 1.0
