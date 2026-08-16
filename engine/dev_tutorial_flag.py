"""Developer-only force for E1M1's PlayedTutorial gate.

E1M1.CrewIntros:1954 gates the "Press 's' to skip introduction" banner and its
keyboard handler on g_kVarManager's global PlayedTutorial == 1.0. BC sets that
at the END of the opening (E1M1.SaveTheGame:2659) and persists it, making the
prompt replay-only. Our TGVarManager is in-memory and only round-trips through
savegames (engine/appc/save_load.py:181), so a cold-launched E1M1 always reads
0.0 and the skip path is unreachable.

STOPGAP. The correct fix is to persist the "global" scope across launches; that
belongs with persistent-save support. See docs/engine/e1m1-skip-intro.md for
the follow-up.

Gating lives inside the function, mirroring dev_combat_cheats: even if this were
somehow called in a production build, mission behaviour cannot change.
"""
from engine import dev_mode


def apply_played_tutorial_flag() -> None:
    """Force PlayedTutorial=1.0 under --developer; otherwise do nothing."""
    if not dev_mode.is_enabled():
        return
    import App
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 1.0)
